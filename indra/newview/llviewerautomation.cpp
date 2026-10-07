#include "llviewerprecompiledheaders.h"
#include "llviewerautomation.h"
#include "llagent.h"
#include "llagentcamera.h"
#include "llappviewer.h"
#include "llcontrol.h"
#include "lldir.h"
#include "llenvironment.h"
#include "lleventapi.h"
#include "lltimer.h"
#include "llsdutil.h"
#include "llgl.h"
#include "llleap.h"
#include "llnotificationsutil.h"
#include "llpanellogin.h"
#include "llstartup.h"
#include "llversioninfo.h"
#include "llviewercamera.h"
#include "llviewercontrol.h"
#include "llviewerregion.h"
#include "llviewershadermgr.h"
#include "llviewerwindow.h"
#include "llwindow.h"
#include "pipeline.h"
#include <algorithm>
#include <cmath>
#include <deque>
#include <filesystem>
#include <map>
#include <vector>

extern bool gCubeSnapshot;

namespace
{
bool camera_locked = false;
LLVector3d camera_position;
LLVector3 camera_forward, camera_up;
F32 camera_fov = 1.f;
LLUUID camera_region;
LLSD original_settings = LLSD::emptyMap();
std::deque<LLSD> requests;
LLLeap::weak_t bridge;
bool bridge_started = false;

struct Query { std::string name; GLuint start, end; };
struct Frame
{
    std::vector<Query> queries;
    F64 interval = 0, submit = 0;
};
Frame current_frame;
std::deque<Frame> pending;
std::vector<GLuint> query_pool, free_queries;
std::vector<LLSD> samples;
LLSD capture_metadata, capture_end_metadata;
std::string capture_state = "idle", capture_error;
S32 target_frames = 0, warmup_frames = 0, submitted_frames = 0;
F64 previous_frame_time = 0, submission_start = 0, capture_started = 0;
bool recording_frame = false;
bool query_overflow = false;

bool active() { return capture_state == "warming" || capture_state == "capturing" || capture_state == "draining"; }
LLSD vector3(const LLVector3& v) { LLSD a; for (int i=0; i<3; ++i) a.append(v.mV[i]); return a; }
LLSD vector3d(const LLVector3d& v) { LLSD a; for (int i=0; i<3; ++i) a.append(v.mdV[i]); return a; }
bool finiteVector(const LLSD& a)
{
    if (!a.isArray() || a.size() != 3) return false;
    for (const auto& v : llsd::inArray(a))
        if ((!v.isInteger() && !v.isReal()) || !std::isfinite(v.asReal())) return false;
    return true;
}
bool renderSetting(const std::string& name)
{
    return name.find("Render") == 0 || name.find("BoxxySSS") == 0 ||
           name == "WindowWidth" || name == "WindowHeight" || name == "FullScreen" ||
           name == "MaxFPS" || name == "YieldTime" || name == "BackgroundYieldTime";
}
struct SettingsCollector : LLControlGroup::ApplyFunctor
{
    LLSD values = LLSD::emptyMap();
    void apply(const std::string& name, LLControlVariable* control) override
    {
        if (renderSetting(name))
            values[name] = control->type() == TYPE_BOOLEAN ? LLSD(control->getValue().asBoolean()) : control->getValue();
    }
};
LLSD settings()
{
    SettingsCollector collector;
    gSavedSettings.applyToAll(&collector);
    return collector.values;
}
LLSD camera()
{
    LLSD result;
    auto* cam = LLViewerCamera::getInstance();
    result["position_global"] = vector3d(gAgent.getPosGlobalFromAgent(cam->getOrigin()));
    result["forward"] = vector3(cam->getAtAxis());
    result["up"] = vector3(cam->getUpAxis());
    result["vertical_fov_degrees"] = cam->getView() * RAD_TO_DEG;
    result["locked"] = camera_locked;
    result["width"] = gViewerWindow->getWindowWidthRaw();
    result["height"] = gViewerWindow->getWindowHeightRaw();
    if (gAgent.getRegion())
    {
        result["region"] = gAgent.getRegion()->getName();
        result["region_id"] = gAgent.getRegion()->getRegionID();
        result["region_origin_global"] = vector3d(gAgent.getRegion()->getOriginGlobal());
    }
    return result;
}
LLSD metadata()
{
    LLSD result;
    result["schema_version"] = 1;
    result["viewer"] = LLVersionInfo::instance().getChannelAndVersion();
    result["gpu"] = gGLManager.mGLRenderer;
    result["driver"] = gGLManager.mGLVersionString;
    result["camera"] = camera();
    result["settings"] = settings();
    result["width"] = gViewerWindow->getWindowWidthRaw();
    result["height"] = gViewerWindow->getWindowHeightRaw();
    result["render_width"] = (S32)gPipeline.mRT->screen.getWidth();
    result["render_height"] = (S32)gPipeline.mRT->screen.getHeight();
    result["foreground"] = gViewerWindow->getActive();
    if (auto sky = LLEnvironment::instance().getCurrentSky()) result["sky"] = sky->getSettings();
    if (auto water = LLEnvironment::instance().getCurrentWater()) result["water"] = water->getSettings();
    result["timing_note"] = "GPU scopes are inclusive elapsed intervals; nested scopes must not be added. Frame GPU time ends before presentation, excluding VSync wait and post-present reflection maintenance. CPU frame interval includes idle/presentation. PCSS is embedded in shared lighting shaders: use paired on/off captures. Live scene motion/streaming can change between runs.";
    return result;
}
void releaseQueries()
{
    recording_frame = false;
    if (!query_pool.empty()) glDeleteQueries((GLsizei)query_pool.size(), query_pool.data());
    query_pool.clear(); free_queries.clear(); pending.clear(); current_frame = Frame();
}
void failCapture(const std::string& error)
{
    capture_error = error; capture_state = "failed"; releaseQueries();
}
void collect()
{
    // Only read results after the frame's final timestamp is available.
    while (!pending.empty())
    {
        Frame& frame = pending.front();
        GLint ready = 0;
        glGetQueryObjectiv(frame.queries.front().end, GL_QUERY_RESULT_AVAILABLE, &ready);
        if (!ready) break;
        LLSD sample;
        sample["frame_interval_ms"] = frame.interval;
        sample["render_submit_ms"] = frame.submit;
        sample["gpu_ms"] = LLSD::emptyMap();
        for (const auto& query : frame.queries)
        {
            GLuint64 start = 0, end = 0;
            glGetQueryObjectui64v(query.start, GL_QUERY_RESULT, &start);
            glGetQueryObjectui64v(query.end, GL_QUERY_RESULT, &end);
            if (end < start) { failCapture("GPU timestamps were not monotonic"); return; }
            sample["gpu_ms"][query.name] = sample["gpu_ms"][query.name].asReal() + F64(end-start) / 1000000.;
            free_queries.push_back(query.start); free_queries.push_back(query.end);
        }
        samples.push_back(sample);
        pending.pop_front();
    }
    if (capture_state == "draining" && pending.empty())
    {
        capture_end_metadata = metadata();
        if (!llsd_equals(capture_metadata["settings"], capture_end_metadata["settings"]))
        { failCapture("Rendering settings changed during capture"); return; }
        capture_state = "complete";
        releaseQueries();
    }
}
LLSD statistics(std::vector<F64> values)
{
    LLSD result;
    if (values.empty()) return result;
    std::sort(values.begin(), values.end());
    F64 total = 0; for (F64 value : values) total += value;
    result["mean"] = total / values.size();
    result["median"] = values.size()%2 ? values[values.size()/2] : (values[values.size()/2-1]+values[values.size()/2])*.5;
    result["p95"] = values[(size_t)std::ceil(values.size()*.95)-1];
    result["p99"] = values[(size_t)std::ceil(values.size()*.99)-1];
    result["min"] = values.front(); result["max"] = values.back();
    return result;
}
LLSD captureResult(bool raw)
{
    LLSD result;
    result["state"] = capture_state;
    result["error"] = capture_error;
    result["requested_frames"] = target_frames;
    result["submitted_frames"] = submitted_frames;
    result["completed_frames"] = (S32)samples.size();
    result["warmup_remaining"] = warmup_frames;
    if (capture_state != "complete" && capture_state != "failed") return result;
    result["metadata"] = capture_metadata;
    result["end_metadata"] = capture_end_metadata;
    std::map<std::string, std::vector<F64>> metrics;
    for (const auto& sample : samples)
        for (const auto& item : llsd::inMap(sample["gpu_ms"])) metrics[item.first];
    for (auto& metric : metrics)
    {
        S32 active_frames = 0;
        for (const auto& sample : samples)
        {
            const LLSD& v = sample["gpu_ms"][metric.first];
            metric.second.push_back(v.asReal());
            if (v.isDefined()) ++active_frames;
        }
        result["gpu_ms"][metric.first] = statistics(metric.second);
        result["gpu_ms"][metric.first]["active_frames"] = active_frames;
    }
    for (const char* name : {"frame_interval_ms", "render_submit_ms"})
    {
        std::vector<F64> values;
        for (const auto& sample : samples) values.push_back(sample[name].asReal());
        result[name] = statistics(values);
    }
    if (raw) { result["samples"] = LLSD::emptyArray(); for (auto& sample : samples) result["samples"].append(sample); }
    return result;
}

// Bounds come from the shipped graphics controls, keeping unsupported values out
// of shader quality indices and render-target dimensions.
const std::map<std::string, std::pair<F64,F64>>& writableSettings()
{
    static const std::map<std::string, std::pair<F64,F64>> values = {
#include "llviewerautomation_settings.inc"
    };
    return values;
}
void restoreSettings()
{
    for (const auto& item : llsd::inMap(original_settings))
        if (auto control = gSavedSettings.getControl(item.first)) control->setValue(item.second, false);
    original_settings = LLSD::emptyMap();
}

void bridgeFailure(const std::string& message)
{
    gSavedSettings.setBOOL("MCPBridgeEnabled", false);
    LLSD args;
    args["MESSAGE"] = message;
    LLNotificationsUtil::add("GenericAlertOK", args);
}

void updateBridge()
{
    static LLCachedControl<bool> enabled(gSavedSettings, "MCPBridgeEnabled", false);
    if (bridge_started && bridge.expired())
    {
        bridge_started = false;
        if (active()) failCapture("MCP bridge exited during capture");
        restoreSettings();
        camera_locked = false;
        bridgeFailure("Local MCP stopped unexpectedly. Check the viewer log, then enable it again from Develop (Debug at login).");
    }
    if (!enabled)
    {
        if (bridge_started)
        {
            // Closing the LEAP pipes lets the helper close its listener and
            // remove its session file. Other LEAP plugins are left alone.
            if (active()) failCapture("Local MCP was disabled during capture");
            requests.clear();
            restoreSettings();
            camera_locked = false;
            if (auto running = bridge.lock()) delete running.get();
            bridge.reset();
            bridge_started = false;
        }
        return;
    }
    if (bridge_started) return;

    // This developer bridge uses the checkout's existing private environment.
    // Walk from the executable, so ordinary launches do not depend on the CWD.
    namespace fs = std::filesystem;
    fs::path root(gDirUtilp->getExecutableDir());
    std::error_code error;
    for (int depth = 0; depth < 6 && !root.empty(); ++depth)
    {
        const auto scripts = root / "scripts" / "viewer_mcp";
#if LL_WINDOWS
        const auto python = scripts / ".venv" / "Scripts" / "python.exe";
#else
        const auto python = scripts / ".venv" / "bin" / "python";
#endif
        const auto helper = scripts / "leap_bridge.py";
        if (fs::is_regular_file(python, error) && fs::is_regular_file(helper, error))
        {
            LLProcess::Params params;
            params.desc = "Prism local MCP bridge";
            params.executable = python.string();
            params.args.add(helper.string());
            params.args.add("--session-file");
            params.args.add((root / ".logs" / "viewer-mcp" / "connection.json").string());
            // The helper exits on stdin EOF, including when this viewer quits.
            params.autokill = false;
            if (auto launched = LLLeap::create(params, false))
            {
                bridge = launched->getWeak();
                bridge_started = true;
                return;
            }
            bridgeFailure("Could not start Local MCP. Check the viewer log and run scripts/viewer_mcp/setup.ps1 in the checkout.");
            return;
        }
        auto parent = root.parent_path();
        if (parent == root) break;
        root = parent;
    }
    bridgeFailure("Local MCP needs the developer checkout and its Python environment. Run scripts/viewer_mcp/setup.ps1 in the checkout, then enable Local MCP again.");
}

class AutomationAPI : public LLEventAPI
{
public:
    AutomationAPI() : LLEventAPI("PrismAutomation", "Local rendering test tools; enable Local MCP from Develop (Debug at login)")
    {
        for (const char* op : {"status", "login", "camera_get", "camera_set", "camera_release", "settings_get", "settings_set", "restore", "profile_start", "profile_status", "profile_cancel", "snapshot", "shaders_reload", "quit"})
            add(op, "Prism developer automation operation", &AutomationAPI::dispatch);
    }
    void dispatch(const LLSD& request)
    {
        // LEAP dispatch runs inside pipe/event processing. Graphics setters can
        // rebuild shaders and pump events; execute after that callback unwinds.
        if (requests.size() >= 16)
        {
            Response reply(LLSD(), request);
            reply.error("Automation request queue is full");
            return;
        }
        requests.push_back(request);
    }
    void execute(const LLSD& request)
    {
        Response reply(LLSD(), request);
        try { handle(request, reply); }
        catch (const std::exception& error) { reply.error(error.what()); }
    }
    void handle(const LLSD& request, Response& reply)
    {
        const std::string op = request["op"].asString();
        if (op == "status")
        {
            reply["state"] = LLStartUp::getStartupStateString();
            reply["logged_in"] = LLStartUp::getStartupState() == STATE_STARTED;
            reply["disconnected"] = gDisconnected;
            reply["login_fields_populated"] = LLPanelLogin::isCredentialSet();
            reply["camera_locked"] = camera_locked;
            reply["capture_state"] = capture_state;
            reply["mcp_enabled"] = gSavedSettings.getBOOL("MCPBridgeEnabled");
            reply["shader_directory"] = gDirUtilp->getExpandedFilename(LL_PATH_APP_SETTINGS, "shaders");
            reply["viewer"] = LLVersionInfo::instance().getChannelAndVersion();
            return;
        }
        if (op == "login")
        {
            if (LLStartUp::getStartupState() != STATE_LOGIN_WAIT) { reply.error("Login requires STATE_LOGIN_WAIT"); return; }
            LLSD click; click["op"] = "onClickConnect";
            LLEventPumps::instance().obtain("LLPanelLogin").post(click);
            reply["submitted"] = true;
            return;
        }
        if (op == "quit") { LLAppViewer::instance()->requestQuit(); reply["requested"] = true; return; }
        if (op == "profile_status")
        {
            if (active() && LLTimer::getTotalSeconds()-capture_started > 180.) failCapture("Capture timed out; viewer may be paused or minimized");
            reply.setResponse(captureResult(request["include_samples"].asBoolean())); return;
        }
        if (op == "profile_cancel")
        {
            releaseQueries(); capture_state = "cancelled"; reply["state"] = capture_state; return;
        }
        if (op == "settings_get")
        {
            reply["values"] = settings();
            for (const auto& item : writableSettings())
            {
                reply["writable"][item.first]["min"] = item.second.first;
                reply["writable"][item.first]["max"] = item.second.second;
            }
            return;
        }
        if (active()) { reply.error("Cancel or finish the active capture before changing camera/settings, reloading shaders or taking a snapshot"); return; }
        if (op == "restore") { restoreSettings(); camera_locked = false; reply["restored"] = true; return; }
        if (op == "settings_set")
        {
            const LLSD& values = request["values"];
            if (!values.isMap() || values.size() > 128) { reply.error("values must be a map of at most 128 settings"); return; }
            for (const auto& item : llsd::inMap(values))
            {
                auto found = writableSettings().find(item.first);
                auto control = gSavedSettings.getControl(item.first);
                const LLSD& value = item.second;
                if (!control || found == writableSettings().end()) { reply.error("Setting is not writable: " + item.first); return; }
                if (control->type() == TYPE_BOOLEAN ? !value.isBoolean() : (!value.isInteger() && !value.isReal()))
                { reply.error("Wrong type for " + item.first); return; }
                F64 n = value.isBoolean() ? (value.asBoolean() ? 1. : 0.) : value.asReal();
                if (!std::isfinite(n) || n < found->second.first || n > found->second.second ||
                    ((control->type() == TYPE_S32 || control->type() == TYPE_U32) && n != std::floor(n)))
                { reply.error("Value outside supported range for " + item.first); return; }
            }
            for (const auto& item : llsd::inMap(values))
            {
                auto control = gSavedSettings.getControl(item.first);
                if (!original_settings.has(item.first)) original_settings[item.first] = control->getValue();
                control->setValue(item.second, false); // Never persist experimental settings.
                reply["values"][item.first] = control->getValue();
            }
            return;
        }
        if (op == "camera_release") { camera_locked = false; reply["released"] = true; return; }
        if (LLStartUp::getStartupState() != STATE_STARTED || gDisconnected || !gAgent.getRegion())
        { reply.error("This operation requires a connected, logged-in viewer"); return; }
        if (op == "shaders_reload")
        {
            // Same full reload as Develop's Purge Shader Cache, deferred until
            // the LEAP pipe callback has unwound. Never mix it into a capture.
            LLTimer timer;
            auto* shaders = LLViewerShaderMgr::instance();
            shaders->clearShaderCache();
            const bool loaded = shaders->setShaders();
            reply["reloaded"] = loaded;
            reply["elapsed_seconds"] = F64(timer.getElapsedTimeF64());
            reply["shader_directory"] = gDirUtilp->getExpandedFilename(LL_PATH_APP_SETTINGS, "shaders");
            reply["source_version"] = gSavedSettings.getString("RenderShaderCacheVersion");
            if (!loaded) reply.error("Shader reload was skipped or failed; inspect the viewer log for compiler diagnostics");
            return;
        }
        if (op == "camera_get") { reply.setResponse(camera()); return; }
        if (op == "camera_set")
        {
            if (!finiteVector(request["position_global"]) || !finiteVector(request["forward"]) || !finiteVector(request["up"]))
            { reply.error("position_global, forward and up must each contain three finite numbers"); return; }
            const F64 fov = request["vertical_fov_degrees"].asReal();
            LLVector3 forward(request["forward"]), up(request["up"]);
            LLVector3d position(request["position_global"]);
            if (!forward.isFinite() || !up.isFinite() || !std::isfinite(fov) || fov < 10. || fov > 120. || forward.normalize() < .0001f || up.normalize() < .0001f || (forward % up).lengthSquared() < .0001f)
            { reply.error("Invalid camera basis or vertical FOV (10-120 degrees)"); return; }
            if ((position-gAgent.getPositionGlobal()).lengthSquared() > 4096.*4096.)
            { reply.error("Camera must be within 4096 metres of the agent; move to the target region first"); return; }
            if (request.has("region_id") && request["region_id"].asUUID() != gAgent.getRegion()->getRegionID())
            { reply.error("Saved camera belongs to a different region"); return; }
            camera_position = position; camera_forward = forward; camera_up = up;
            camera_fov = (F32)(fov * DEG_TO_RAD); camera_region = gAgent.getRegion()->getRegionID();
            camera_locked = true;
            gAgentCamera.changeCameraToThirdPerson(false);
            gAgentCamera.setFocusOnAvatar(false, false);
            gAgentCamera.setCameraPosAndFocusGlobal(position, position + LLVector3d(forward)*10., LLUUID::null);
            LLViewerAutomation::applyCamera();
            reply.setResponse(camera()); return;
        }
        if (op == "snapshot")
        {
            const std::string path = request["filename"].asString();
            if (path.empty() || path.size() > 1024) { reply.error("A snapshot filename is required"); return; }
            const bool ok = gViewerWindow->saveSnapshot(path, gViewerWindow->getWindowWidthRaw(), gViewerWindow->getWindowHeightRaw(),
                request["show_ui"].asBoolean(), request["show_hud"].asBoolean(), false, false,
                LLSnapshotModel::SNAPSHOT_TYPE_COLOR, LLSnapshotModel::SNAPSHOT_FORMAT_PNG);
            if (!ok) { reply.error("Snapshot failed"); return; }
            reply["filename"] = path; reply["metadata"] = metadata(); return;
        }
        if (op == "profile_start")
        {
            S32 frames = request["frames"].asInteger(), warmup = request["warmup_frames"].asInteger();
            if (!request["frames"].isInteger() || !request["warmup_frames"].isInteger() || frames < 10 || frames > 2000 || warmup < 1 || warmup > 2000)
            { reply.error("frames must be 10-2000; warmup_frames must be 1-2000"); return; }
            if (!gViewerWindow->getWindow()->getVisible() || gViewerWindow->getWindow()->getMinimized())
            { reply.error("Viewer must be visible and not minimized"); return; }
            if (!glQueryCounter) { reply.error("GPU timestamp queries are unavailable"); return; }
            releaseQueries(); samples.clear(); capture_error.clear();
            query_pool.resize(4096); glGenQueries((GLsizei)query_pool.size(), query_pool.data()); free_queries = query_pool;
            target_frames = frames; warmup_frames = warmup; submitted_frames = 0;
            capture_metadata = metadata(); capture_end_metadata = LLSD();
            previous_frame_time = 0; capture_started = LLTimer::getTotalSeconds(); capture_state = "warming";
            reply.setResponse(captureResult(false)); return;
        }
        reply.error("Unknown operation");
    }
};
AutomationAPI api;
}

void LLViewerAutomation::processRequests()
{
    static bool processing = false;
    if (processing) return;
    processing = true;
    updateBridge();
    std::deque<LLSD> ready;
    ready.swap(requests);
    for (const auto& request : ready) api.execute(request);
    processing = false;
}

void LLViewerAutomation::applyCamera()
{
    if (!camera_locked || gCubeSnapshot) return;
    if (!gAgent.getRegion() || gDisconnected || gAgent.getRegion()->getRegionID() != camera_region)
    {
        camera_locked = false;
        if (active()) failCapture("Region changed or viewer disconnected during capture");
        return;
    }
    auto* cam = LLViewerCamera::getInstance();
    LLVector3 position = gAgent.getPosAgentFromGlobal(camera_position);
    cam->setOriginAndLookAt(position, camera_up, position + camera_forward);
    cam->setViewNoBroadcast(camera_fov);
    cam->resetCameraSmoothing();
}
void LLViewerAutomation::beginFrame()
{
    if (!active()) return;
    if (gDisconnected || !gViewerWindow->getWindow()->getVisible() || gViewerWindow->getWindow()->getMinimized())
    { failCapture("Viewer disconnected, hidden or minimized"); return; }
    if (!gAgent.getRegion() || gAgent.getRegion()->getRegionID() != capture_metadata["camera"]["region_id"].asUUID())
    { failCapture("Region changed during capture"); return; }
    if (LLTimer::getTotalSeconds()-capture_started > 180.) { failCapture("Capture exceeded 180 seconds"); return; }
    if (capture_metadata["width"].asInteger() != gViewerWindow->getWindowWidthRaw() || capture_metadata["height"].asInteger() != gViewerWindow->getWindowHeightRaw())
    { failCapture("Window resized during capture"); return; }
    collect();
    if (!active()) return;
    const F64 now = LLTimer::getTotalSeconds();
    const F64 interval = previous_frame_time ? (now-previous_frame_time)*1000. : 0.;
    previous_frame_time = now;
    if (capture_state == "draining") return;
    if (warmup_frames > 0) { --warmup_frames; return; }
    if (free_queries.size() < 256) { failCapture("GPU query backlog exceeded bounded capacity"); return; }
    capture_state = "capturing"; recording_frame = true;
    current_frame = Frame(); current_frame.interval = interval; submission_start = now; query_overflow = false;
    Query query; query.name = "frame";
    query.start = free_queries.back(); free_queries.pop_back();
    query.end = free_queries.back(); free_queries.pop_back();
    glQueryCounter(query.start, GL_TIMESTAMP); current_frame.queries.push_back(query);
}
void LLViewerAutomation::endFrame()
{
    if (!recording_frame) return;
    if (query_overflow) { failCapture("Too many GPU scopes in one frame"); return; }
    glQueryCounter(current_frame.queries.front().end, GL_TIMESTAMP);
    current_frame.submit = (LLTimer::getTotalSeconds()-submission_start)*1000.;
    recording_frame = false; pending.push_back(std::move(current_frame));
    if (++submitted_frames == target_frames) capture_state = "draining";
}
LLViewerAutomation::GPUScope::GPUScope(const char* name)
{
    if (!recording_frame) return;
    if (free_queries.size() < 2) { query_overflow = true; return; }
    Query query; query.name = name;
    query.start = free_queries.back(); free_queries.pop_back();
    query.end = free_queries.back(); free_queries.pop_back();
    mEnd = query.end; glQueryCounter(query.start, GL_TIMESTAMP); current_frame.queries.push_back(query);
}
LLViewerAutomation::GPUScope::~GPUScope()
{
    if (mEnd && recording_frame) glQueryCounter(mEnd, GL_TIMESTAMP);
}
void LLViewerAutomation::cleanup()
{
    releaseQueries(); camera_locked = false;
}
