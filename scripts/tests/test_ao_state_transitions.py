"""Exercise production AO handoffs without a simulator: python this_file.py.

Requires g++ on PATH. Uses production controller/keyframe stop methods as well as
AO state transitions. Inventory assets are resolved; simulator echoes are explicit.
"""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "indra/newview/llboxxyao.cpp").read_text()
header = (ROOT / "indra/newview/llboxxyao.h").read_text()
controller_source = (ROOT / "indra/llcharacter/llmotioncontroller.cpp").read_text()
keyframe_source = (ROOT / "indra/llcharacter/llkeyframemotion.cpp").read_text()
avatar_source = (ROOT / "indra/newview/llvoavatar.cpp").read_text()


def method(name, text=source, owner="LLBoxxyAO"):
    start = re.search(r"^[\w:*<>]+\s+" + re.escape(owner + "::" + name) + r"\(", text, re.MULTILINE).start()
    end = text.index("\n}", start) + 2
    return text[start:end]


harness = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <iostream>
#include <list>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <vector>
using F32 = float;
using S32 = int;
using U32 = unsigned;
struct LLUUID {
    int value = 0;
    LLUUID(int id = 0) : value(id) {}
    bool isNull() const { return value == 0; }
    bool notNull() const { return !isNull(); }
    void setNull() { value = 0; }
    std::string asString() const { return std::to_string(value); }
    bool operator==(LLUUID b) const { return value == b.value; }
    bool operator!=(LLUUID b) const { return !(*this == b); }
    bool operator<(LLUUID b) const { return value < b.value; }
    static const LLUUID null;
};
const LLUUID LLUUID::null;
std::ostream& operator<<(std::ostream& out, LLUUID id) { return out << id.value; }
struct LLTimer {
    bool started = false;
    int starts = 0;
    void start() { started = true; ++starts; }
    void stop() { started = false; }
    bool getStarted() const { return started; }
    void setTimerExpirySec(float) {}
};
struct LLEventTimer { virtual ~LLEventTimer() = default; virtual bool tick() = 0; };
template<class T> struct LLSingleton {};
namespace boost { namespace signals2 {
struct connection {};
template<class T> struct signal {
    using slot_type = void(*)();
    connection connect(slot_type) { return {}; }
    void operator()() {}
};
}}
#define LLSINGLETON(T) public: T() = default; static T& instance()
#define private public
'''
# Use the production state definitions and members, exposing them only in this harness.
harness += re.sub(r'^#include .*$', '', header, flags=re.MULTILINE)
harness += r'''
#undef private
LLBoxxyAO::~LLBoxxyAO() = default;
LLBoxxyAO* active_ao = nullptr;
LLBoxxyAO& LLBoxxyAO::instance() { return *active_ao; }
bool LLBoxxyAO::tick() { return false; }
LLUUID LLBoxxyAO::resolveAnimationAsset(Animation& animation) { return animation.asset_id; }
#define LL_DEBUGS(tag) if (false) std::cerr
#define LL_INFOS(tag) if (false) std::cerr
#define LL_ENDL std::endl
#define LL_PROFILE_ZONE_SCOPED_CATEGORY_AVATAR
#define llmin std::min
#define llmax std::max
float ll_frand() { return 0.75f; }
enum { ANIM_REQUEST_STOP, ANIM_REQUEST_START };
struct LLMotion {
    struct Pose { float getWeight() { return 1.f; } } pose;
    LLUUID id;
    bool active = false, stopped = true, blending = false;
    float mStopTimestamp = 0, mActivationTimestamp = 0;
    float mResidualWeight = 0, mSendStopTimestamp = 1e20f;
    virtual ~LLMotion() = default;
    virtual void setStopTime(float time) { stopped = true; mStopTimestamp = time; }
    void setStopped(bool value) { stopped = value; }
    bool isStopped() const { return stopped; }
    bool isActive() const { return active; }
    bool isBlending() const { return blending; }
    bool canDeprecate() const { return true; }
    void deactivate() { active = false; }
    float getFadeWeight() const { return 1; }
    float getStopTime() const { return mStopTimestamp; }
    virtual float getEaseOutDuration() const { return 0.3f; }
    Pose* getPose() { return &pose; }
    LLUUID getID() const { return id; }
};
struct LLKeyframeMotion : LLMotion {
    // An uploaded stand can loop over a short section of a long asset.
    struct JointMotionList {
        bool mLoop = true;
        float mLoopInPoint = 0, mLoopOutPoint = 2, mDuration = 60;
    } data;
    JointMotionList* mJointMotionList = &data;
    float getEaseOutDuration() const { return 0.3f; }
    void setStopTime(float time) override;
};
struct CharacterCallbacks { void requestStopMotion(LLMotion*) {} } character_callbacks;
struct LLMotionController {
    using motion_set_t = std::set<LLMotion*>;
    using motion_list_t = std::list<LLMotion*>;
    float mAnimTime = 5, mLastTime = 0;
    CharacterCallbacks* mCharacter = &character_callbacks;
    bool mPaused = false;
    std::map<LLUUID, LLMotion*> mAllMotions;
    std::set<LLMotion*> mDeprecatedMotions, mLoadingMotions;
    std::list<LLMotion*> mActiveMotions;
    std::map<LLMotion*, float> mLoadingMotionStartTimes;
    std::vector<std::unique_ptr<LLMotion>> storage;
    LLMotion* findMotion(LLUUID id) {
        auto it = mAllMotions.find(id);
        return it == mAllMotions.end() ? nullptr : it->second;
    }
    LLMotion* createMotion(LLUUID id) {
        storage.push_back(std::make_unique<LLKeyframeMotion>());
        LLMotion* motion = storage.back().get();
        motion->id = id;
        mAllMotions[id] = motion;
        return motion;
    }
    bool isMotionLoading(LLMotion* motion) { return mLoadingMotions.count(motion); }
    bool isMotionActive(LLMotion* motion) { return motion && motion->active; }
    bool activateMotionInstance(LLMotion* motion, float time) {
        motion->stopped = false;
        motion->mActivationTimestamp = time;
        if (!isMotionLoading(motion)) {
            motion->active = true;
            mActiveMotions.remove(motion);
            mActiveMotions.push_front(motion);
        }
        return true;
    }
    void removeMotionInstance(LLMotion* motion) {
        mActiveMotions.remove(motion);
        storage.erase(std::find_if(storage.begin(), storage.end(),
                                   [motion](const auto& entry) { return entry.get() == motion; }));
    }
    int playing(LLUUID id) {
        return std::count_if(mActiveMotions.begin(), mActiveMotions.end(),
                             [id](LLMotion* motion) { return motion->id == id; });
    }
    bool startMotion(const LLUUID&, float = 0, bool = false);
    bool stopMotionLocally(const LLUUID&, bool);
    void stopMotionWithEaseOut(const LLUUID&);
    bool stopMotionInstance(LLMotion*, bool);
    bool deactivateMotionInstance(LLMotion*);
    void deprecateMotionInstance(LLMotion*);
    void updateIdleMotion(LLMotion*);
    void updateIdleActiveMotions();
    void advance(float seconds) {
        mLastTime = mAnimTime;
        mAnimTime += seconds;
        updateIdleActiveMotions();
    }
};
struct LLCharacter {
    LLMotionController mMotionController;
    bool startMotion(LLUUID id) { return mMotionController.startMotion(id); }
    bool stopMotion(LLUUID id, bool immediate = false) { return mMotionController.stopMotionLocally(id, immediate); }
};
struct LLVOAvatar : LLCharacter {
    bool mInAir = false;
    std::map<LLUUID, int> mSignaledAnimations;
    LLMotionController& getMotionController() { return mMotionController; }
    bool isSelf() { return true; }
    LLUUID remapMotionID(LLUUID id) { return id; }
    bool startMotion(const LLUUID&, float = 0);
    bool stopMotion(const LLUUID&, bool = false);
} avatar;
LLVOAvatar* gAgentAvatarp = &avatar;
bool isAgentAvatarValid() { return true; }
bool is_boxxy_animation_syncing() { return false; }
struct AnimLibrary { const char* animationName(LLUUID) { return ""; } } gAnimLibrary;
struct Agent {
    std::vector<std::pair<LLUUID, int>> requests;
    bool getFlying() { return false; }
    void sendAnimationRequest(LLUUID id, int request) { requests.emplace_back(id, request); }
    void setAFK() {}
    void onAnimStop(LLUUID) {}
} gAgent;
'''
harness += method("setStopTime", keyframe_source, "LLKeyframeMotion") + "\n"
for name in ("startMotion", "stopMotionLocally", "stopMotionWithEaseOut", "stopMotionInstance",
             "deprecateMotionInstance", "deactivateMotionInstance", "updateIdleMotion", "updateIdleActiveMotions"):
    harness += method(name, controller_source, "LLMotionController") + "\n"
for i, name in enumerate(sorted(set(re.findall(r'\bANIM_AGENT_\w+', source)) | {"ANIM_AGENT_AWAY"}), 1):
    harness += f"const LLUUID {name}({i});\n"
for name in (
    "initializeStates", "stateForType", "stateForMotion", "getCurrentState", "isActiveOverride",
    "isTransientMotion", "overrideMotion", "stopStockMotionVariants",
    "startCurrentOverride", "restartCycleTimer", "performCycle", "completePendingCycleStop",
):
    harness += method(name) + "\n"
for name in ("startMotion", "stopMotion"):
    harness += method(name, avatar_source, "LLVOAvatar") + "\n"

harness += r'''
struct Fixture {
    LLBoxxyAO ao;
    LLBoxxyAO::Set set;
    Fixture() {
        active_ao = &ao;
        avatar = {};
        gAgent.requests.clear();
        ao.initializeStates(set);
        ao.mCurrentSet = &set;
        ao.mEnabled = true;
        ao.mLastMotion = ANIM_AGENT_STAND;
        for (auto& state : set.states) {
            LLBoxxyAO::Animation animation;
            animation.asset_id = LLUUID(100 + state.type);
            state.animations.push_back(animation);
            state.cycle = true;
            animation.asset_id = LLUUID(200 + state.type);
            state.animations.push_back(animation);
        }
    }
    LLBoxxyAO::State& state(LLUUID stock) { return *ao.stateForMotion(stock); }
    LLUUID event(LLUUID stock, bool start) {
        // Exercise the real avatar hooks without automatically delivering any
        // simulator echo. The result below is only for assertions in the tests.
        auto* state = ao.stateForMotion(stock);
        LLUUID previous = state ? state->current_asset : LLUUID::null;
        if (start) avatar.startMotion(stock);
        else avatar.stopMotion(stock);
        if (!state || ao.isTransientMotion(stock)) return LLUUID::null;
        return start ? state->current_asset : (state->current_asset.isNull() ? previous : LLUUID::null);
    }
    bool stopped(LLUUID asset) {
        return std::find(gAgent.requests.begin(), gAgent.requests.end(),
                         std::make_pair(asset, int(ANIM_REQUEST_STOP))) != gAgent.requests.end();
    }
    void retired(LLUUID stock, LLUUID asset) {
        assert(state(stock).current_asset.isNull());
        assert(stopped(asset));
        fading(asset);
    }
    void fading(LLUUID asset) {
        for (LLMotion* motion : avatar.mMotionController.mActiveMotions) {
            if (motion->id == asset) {
                assert(motion->isStopped());
                assert(motion->getStopTime() <= avatar.mMotionController.mAnimTime);
            }
        }
    }
};
int main() {
    // A state handoff must keep the outgoing pose alive for its authored fade.
    {
        Fixture f;
        LLUUID stand = f.event(ANIM_AGENT_STAND, true);
        LLUUID walk = f.event(ANIM_AGENT_WALK, true);
        assert(avatar.mMotionController.playing(stand) == 1);
        assert(avatar.mMotionController.findMotion(stand)->getStopTime() == avatar.mMotionController.mAnimTime);
        // The incoming motion is already active before any simulator reply.
        auto* walking = avatar.mMotionController.findMotion(walk);
        assert(walking && walking->isActive());
        walking->blending = true;
        size_t requests = gAgent.requests.size();
        avatar.startMotion(walk);
        assert(avatar.mMotionController.findMotion(walk) == walking);
        assert(avatar.mMotionController.playing(walk) == 1);
        assert(gAgent.requests.size() == requests);
        float fade_start = avatar.mMotionController.findMotion(stand)->getStopTime();
        avatar.mMotionController.advance(0.15f);
        assert(avatar.mMotionController.playing(stand) == 1);
        f.event(stand, false); // A stop echo must not restart or truncate the fade.
        assert(avatar.mMotionController.findMotion(stand)->getStopTime() == fade_start);
        assert(avatar.mMotionController.playing(stand) == 1);
        avatar.mMotionController.advance(0.16f);
        assert(avatar.mMotionController.playing(stand) == 0);
        assert(avatar.mMotionController.playing(walk) == 1);
    }
    // Fading covers deprecated copies too, and cannot be prolonged by stop echoes.
    {
        LLMotionController c;
        LLUUID id(900), other(901);
        c.startMotion(id);
        c.findMotion(id)->blending = true;
        c.startMotion(id);
        c.startMotion(other);
        assert(c.playing(id) == 2);
        c.stopMotionWithEaseOut(id);
        assert(c.playing(id) == 2);
        for (LLMotion* motion : c.mActiveMotions) {
            if (motion->id == id) assert(motion->isStopped() && motion->getStopTime() == 5.f);
        }
        c.advance(0.15f);
        c.stopMotionWithEaseOut(id);
        assert(c.playing(id) == 2);
        c.advance(0.16f);
        assert(c.playing(id) == 0 && c.mDeprecatedMotions.empty());
        assert(c.playing(other) == 1);
        auto* loading = c.createMotion(LLUUID(902));
        c.mLoadingMotions.insert(loading);
        c.startMotion(loading->id);
        c.stopMotionWithEaseOut(loading->id);
        assert(loading->isStopped());
        c.mPaused = true;
        c.stopMotionWithEaseOut(other);
        assert(c.playing(other) == 0);
    }
    // A soft stop of an uploaded loop can leave almost a minute of exit motion.
    // An explicit immediate stop must cancel even an already-stopping instance.
    {
        LLMotionController c;
        LLUUID id(900);
        c.startMotion(id);
        c.stopMotionLocally(id, false);
        assert(c.playing(id) == 1);
        assert(c.findMotion(id)->getStopTime() > c.mAnimTime + 30);
        assert(c.stopMotionLocally(id, true));
        assert(c.playing(id) == 0);
    }
    // A local cycle start followed by its simulator echo while blending creates
    // a deprecated copy. UUID-based immediate stops must retire both instances.
    {
        LLMotionController c;
        LLUUID id(900), other(901);
        c.startMotion(id);
        c.findMotion(id)->blending = true;
        c.startMotion(id);
        c.startMotion(other);
        assert(c.playing(id) == 2 && c.mDeprecatedMotions.size() == 1);
        assert(c.stopMotionLocally(id, true));
        assert(c.playing(id) == 0 && c.mDeprecatedMotions.empty());
        assert(c.playing(other) == 1);
        auto* loading = c.createMotion(LLUUID(902));
        c.mLoadingMotions.insert(loading);
        c.startMotion(loading->id);
        assert(!loading->isStopped());
        assert(c.stopMotionLocally(loading->id, true) && loading->isStopped());
        // A replacement can fail to start after the old copy was deprecated.
        c.deprecateMotionInstance(c.findMotion(other));
        assert(!c.findMotion(other) && c.playing(other) == 1);
        assert(c.stopMotionLocally(other, true));
        assert(c.playing(other) == 0 && c.mDeprecatedMotions.empty());
    }
    // The usual stock-stop-before-stock-start order must stop locally too.
    for (LLUUID next : {ANIM_AGENT_WALK, ANIM_AGENT_FALLDOWN}) {
        Fixture f;
        LLUUID stand = f.event(ANIM_AGENT_STAND, true);
        avatar.mSignaledAnimations[next] = 1;
        assert(f.event(ANIM_AGENT_STAND, false) == stand);
        f.retired(ANIM_AGENT_STAND, stand);
        f.event(next, true);
        assert(f.ao.getCurrentState() == &f.state(next));
    }
    // Delayed custom-asset start/stop echoes cannot leave a looping stand active.
    {
        Fixture f;
        f.event(ANIM_AGENT_STAND, true);
        f.ao.performCycle(1);
        LLUUID stand = f.state(ANIM_AGENT_STAND).current_asset;
        avatar.mMotionController.findMotion(stand)->blending = true;
        avatar.startMotion(stand); // Simulator echo of the optimistic cycle start.
        assert(avatar.mMotionController.playing(stand) == 1); // Echo did not create a blend copy.
        f.event(ANIM_AGENT_WALK, true);
        f.retired(ANIM_AGENT_STAND, stand);
        avatar.startMotion(stand); // Another start was already in flight.
        f.event(stand, false);     // The custom stop echo uses the asset UUID.
        f.fading(stand);
        avatar.mMotionController.advance(0.31f);
        assert(avatar.mMotionController.playing(stand) == 0);
        LLUUID unrelated(900);
        avatar.startMotion(unrelated);
        f.event(unrelated, false);
        assert(avatar.mMotionController.playing(unrelated) == 1); // Ordinary soft stops unchanged.
    }
    // AO enable/login consumes the stock stop before walking ever begins.
    {
        Fixture f;
        f.ao.startCurrentOverride();
        LLUUID stand = f.state(ANIM_AGENT_STAND).current_asset;
        avatar.startMotion(stand);
        assert(f.event(ANIM_AGENT_STAND, false).isNull());
        assert(f.state(ANIM_AGENT_STAND).current_asset == stand);
        assert(f.event(ANIM_AGENT_WALK, true).notNull());
        f.retired(ANIM_AGENT_STAND, stand);
    }
    // A stand stop can also precede the walk signal and be retained as stale.
    for (LLUUID stand_id : {ANIM_AGENT_STAND, ANIM_AGENT_STAND_1, ANIM_AGENT_STAND_4}) {
        for (LLUUID walk_id : {ANIM_AGENT_WALK, ANIM_AGENT_WALK_NEW,
                              ANIM_AGENT_FEMALE_WALK, ANIM_AGENT_FEMALE_WALK_NEW}) {
            Fixture f;
            LLUUID stand = f.event(stand_id, true);
            assert(f.event(stand_id, false).isNull());
            avatar.mSignaledAnimations[walk_id] = 1;
            LLUUID walk = f.event(walk_id, true);
            f.retired(stand_id, stand);
            assert(avatar.mMotionController.playing(walk) == 1);
            // A late old-state stop must not cancel the new state's cycle timer.
            assert(f.event(stand_id, false).isNull());
            assert(f.ao.mCycleTimer.getStarted());
            assert(f.state(walk_id).current_asset == walk);
            LLUUID next_stand = f.event(stand_id, true);
            f.retired(walk_id, walk);
            assert(next_stand == stand);
        }
    }
    // Clean up before early returns for missing, unresolved, or disabled overrides.
    for (int mode = 0; mode < 3; ++mode) {
        Fixture f;
        LLUUID stand = f.event(ANIM_AGENT_STAND, true);
        LLUUID next = mode == 2 ? ANIM_AGENT_SIT : ANIM_AGENT_WALK;
        if (mode == 0) f.state(next).animations.clear();
        if (mode == 1) f.state(next).animations[0].asset_id.setNull();
        assert(f.event(next, true).isNull());
        f.retired(ANIM_AGENT_STAND, stand);
        assert(!f.ao.mCycleTimer.getStarted());
    }
    // Leaving mid-cycle retires both stands, even before the new stand is echoed.
    {
        Fixture f;
        LLUUID old_stand = f.event(ANIM_AGENT_STAND, true);
        f.ao.performCycle(1);
        LLUUID new_stand = f.state(ANIM_AGENT_STAND).current_asset;
        assert(old_stand != new_stand && f.ao.mPendingCycleStop == old_stand);
        f.event(ANIM_AGENT_WALK, true);
        f.retired(ANIM_AGENT_STAND, new_stand);
        assert(f.stopped(old_stand));
        f.fading(old_stand);
        assert(f.ao.mPendingCycleStop.isNull());
    }
    // Every primary state (including falling and swimming) owns the same handoff.
    for (int type = LLBoxxyAO::STATE_WALKING; type < LLBoxxyAO::STATE_COUNT; ++type) {
        if (type == LLBoxxyAO::STATE_TYPING) continue;
        Fixture f;
        f.set.override_sits = true;
        f.ao.mBelowWater = type >= LLBoxxyAO::STATE_FLOATING;
        LLUUID old_stand = f.event(ANIM_AGENT_STAND, true);
        f.ao.performCycle(1);
        LLUUID new_stand = f.state(ANIM_AGENT_STAND).current_asset;
        auto& next = f.set.states[type];
        f.event(next.stock_motion, true);
        f.retired(ANIM_AGENT_STAND, new_stand);
        assert(f.stopped(old_stand));
        f.fading(old_stand);
        LLUUID next_asset = next.current_asset;
        assert(next_asset == LLUUID(100 + type));
        assert(std::find(gAgent.requests.begin(), gAgent.requests.end(),
                         std::make_pair(next_asset, int(ANIM_REQUEST_START))) != gAgent.requests.end());
        assert(f.ao.getCurrentState() == &next);
        // Transient motions request their own simulator start instead of returning it.
        avatar.startMotion(next_asset);
        f.event(ANIM_AGENT_STAND, true);
        f.retired(next.stock_motion, next_asset);
    }
    // Late stops from Standing cannot force an unacknowledged Walking cycle to finish.
    {
        Fixture f;
        f.event(ANIM_AGENT_STAND, true);
        LLUUID walk = f.event(ANIM_AGENT_WALK, true);
        f.ao.performCycle(1);
        assert(f.ao.mPendingCycleStop == walk);
        f.event(ANIM_AGENT_STAND, false);
        assert(f.ao.mPendingCycleStop == walk && !f.stopped(walk));
        assert(f.ao.mCycleTimer.getStarted());
    }
    // Rotating stock stand variants must also preserve a pending custom stand handoff.
    {
        Fixture f;
        LLUUID stand = f.event(ANIM_AGENT_STAND, true);
        f.ao.performCycle(1);
        LLUUID replacement = f.state(ANIM_AGENT_STAND).current_asset;
        int starts = f.ao.mCycleTimer.starts;
        assert(f.event(ANIM_AGENT_STAND_3, true) == replacement);
        assert(f.ao.mPendingCycleStop == stand && !f.stopped(stand));
        assert(f.ao.mCycleTimer.starts == starts);
    }
    // Same-state stand rotation preserves the pose and cycle interval; typing layers.
    {
        Fixture f;
        LLUUID stand = f.event(ANIM_AGENT_STAND, true);
        int starts = f.ao.mCycleTimer.starts;
        assert(f.event(ANIM_AGENT_STAND_2, true) == stand);
        assert(f.ao.mCycleTimer.starts == starts && !f.stopped(stand));
        LLUUID typing = f.event(ANIM_AGENT_TYPE, true);
        assert(f.ao.getCurrentState() == &f.state(ANIM_AGENT_STAND));
        assert(!f.stopped(stand));
        f.event(ANIM_AGENT_WALK, true);
        f.retired(ANIM_AGENT_STAND, stand);
        assert(!f.stopped(typing) && avatar.mMotionController.playing(typing) == 1);
        assert(f.event(ANIM_AGENT_TYPE, false) == typing);
    }
    std::cout << "PASS: all primary AO state handoffs, missing/delayed stock stops, walk variants, stock fallback, "
                 "pending stand cycles, same-state rotation, layered typing, loop exits, duplicate blend instances "
                 "and delayed custom-asset echoes; authored fades and local starts without echo restarts\n";
}
'''

with tempfile.TemporaryDirectory() as temp:
    cpp = Path(temp) / "ao_transitions.cpp"
    exe = Path(temp) / "ao_transitions.exe"
    cpp.write_text(harness)
    subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
