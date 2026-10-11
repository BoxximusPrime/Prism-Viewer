"""Exercise production MCP CPU accumulation/serialization with a fake clock and GPU.

Requires g++ on PATH. Does not build, launch, or change the running viewer.
"""
from pathlib import Path
import subprocess
import tempfile

from test_camera_smoothing import ROOT, function


def main():
    source_path = "indra/newview/llviewerautomation.cpp"
    source = (ROOT / source_path).read_text()
    code = r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include <deque>
#include <map>
#include <string>
#include <thread>
#include <vector>
#include "llviewerautomation.h"
using F64 = double; using S32 = int;
using GLuint = unsigned; using GLuint64 = unsigned long long; using GLint = int;
struct LLSD {
    bool defined = false;
    double number = 0;
    std::string text;
    std::map<std::string, LLSD> values;
    std::vector<LLSD> items;
    LLSD() = default;
    LLSD(double n):defined(true),number(n) {}
    LLSD(int n):LLSD(double(n)) {}
    LLSD(const std::string& s):defined(true),text(s) {}
    LLSD(const char* s):LLSD(std::string(s)) {}
    LLSD& operator[](const std::string& key) { defined = true; return values[key]; }
    const LLSD& operator[](const std::string& key) const {
        static const LLSD missing;
        auto it = values.find(key); return it == values.end() ? missing : it->second;
    }
    static LLSD emptyMap() { LLSD v; v.defined = true; return v; }
    static LLSD emptyArray() { return emptyMap(); }
    void append(const LLSD& v) { items.push_back(v); }
    double asReal() const { return number; }
    bool isDefined() const { return defined; }
};
namespace llsd { const auto& inMap(const LLSD& v) { return v.values; } }
bool llsd_equals(const LLSD&, const LLSD&) { return true; }
LLSD metadata() { return LLSD::emptyMap(); }
struct LLTimer {
    static inline double now = 0;
    static inline int reads = 0;
    static double getTotalSeconds() { ++reads; return now; }
};
enum { GL_TIMESTAMP, GL_QUERY_RESULT_AVAILABLE, GL_QUERY_RESULT };
using GLsizei = int;
bool gpu_ready = false;
void glDeleteQueries(GLsizei, const GLuint*) {}
void glQueryCounter(GLuint, int) {}
void glGetQueryObjectiv(GLuint, int, GLint* ready) { *ready = gpu_ready; }
void glGetQueryObjectui64v(GLuint id, int, GLuint64* value) { *value = id * 1000000; }
'''
    code += source[source.index("struct Query {"):source.index("LLSD vector3(")]
    for signature in (
        "void releaseQueries()", "void failCapture(", "void collect()",
        "LLSD statistics(", "LLSD captureResult(",
        "void LLViewerAutomation::beginCPUFrame()",
        "void LLViewerAutomation::endCPUFrame()",
        "LLViewerAutomation::CPUScope::CPUScope(",
        "LLViewerAutomation::CPUScope::~CPUScope()",
        "void LLViewerAutomation::endFrame()",
    ):
        code += "\n" + function(source_path, signature) + "\n"
    code += r'''
void near(double a, double b) { assert(std::abs(a - b) < 1e-8); }
void work(const char* stage, double seconds) {
    LLViewerAutomation::CPUScope scope(stage);
    LLTimer::now += seconds;
}
void submit() {
    current_frame = Frame(); current_frame.queries.push_back({"frame", 1, 2});
    current_frame.interval = 20;
    recording_frame = true; submission_start = LLTimer::now;
    work("render.display", .004);
    LLViewerAutomation::endFrame();
}
int main() {
    using namespace LLViewerAutomation;
    for (const char* state : {"idle", "cancelled", "failed", "complete", "draining", "warming"}) {
        capture_state = state; warmup_frames = state == std::string("warming") ? 1 : 0;
        int reads = LLTimer::reads;
        beginCPUFrame(); work("disabled", .001); endCPUFrame();
        assert(LLTimer::reads == reads && cpu_times.empty());
    }
    capture_state = "warming"; warmup_frames = 0; target_frames = 2;
    beginCPUFrame();
    {
        CPUScope parent("scene.idle");
        work("avatar.animation", .002);
        work("avatar.animation", .003);
        work("skinning.palette_build", .001);
    }
    int reads = LLTimer::reads;
    std::thread worker([] { LL_AUTOMATION_CPU_SCOPE("worker"); });
    worker.join();
    assert(LLTimer::reads == reads && cpu_times.count("worker") == 0);
    submit();
    assert(pending.back().cpu_times.empty());
    work("render.present", .007);
    work("render.post_present", .002);
    endCPUFrame();
    near(pending.back().cpu_times.at("avatar.animation"), 5);
    near(pending.back().cpu_times.at("scene.idle"), 6);
    near(pending.back().cpu_times.at("render.present"), 7);
    near(pending.back().cpu_times.at("frame"), 19);
    collect(); // GPU backlog: CPU data must remain attached to its own frame.
    assert(samples.empty() && pending.size() == 1);
    capture_state = "capturing";
    beginCPUFrame();
    work("scene.idle", .001);
    submit();
    assert(capture_state == "draining");
    work("render.present", .003);
    endCPUFrame();
    near(pending.back().cpu_times.at("frame"), 8);
    assert(pending.back().cpu_times.count("avatar.animation") == 0);
    near(pending.front().cpu_times.at("frame"), 19);
    gpu_ready = true;
    collect();
    assert(samples.size() == 2 && capture_state == "complete" && !recording_cpu);
    LLSD result = captureResult(true);
    const auto& animation = result["cpu_ms"]["avatar.animation"];
    near(animation["mean"].asReal(), 2.5); // Absent frames count as zero.
    near(animation["median"].asReal(), 2.5);
    near(animation["p95"].asReal(), 5);
    near(animation["p99"].asReal(), 5);
    near(animation["min"].asReal(), 0);
    near(animation["max"].asReal(), 5);
    near(animation["active_frames"].asReal(), 1);
    near(result["cpu_ms"]["frame"]["active_frames"].asReal(), 2);
    near(result["gpu_ms"]["frame"]["median"].asReal(), 1);
    near(result["render_submit_ms"]["median"].asReal(), 4);
    near(result["frame_interval_ms"]["median"].asReal(), 20);
    near(result["samples"].items[0]["cpu_ms"]["render.post_present"].asReal(), 2);
    assert(!captureResult(false)["samples"].isDefined());

    // A loop without a render must not overwrite an older queued frame.
    pending.emplace_back(); pending.back().cpu_times["sentinel"] = 7;
    capture_state = "capturing";
    beginCPUFrame(); work("skipped_render", .003); endCPUFrame();
    assert(pending.back().cpu_times.size() == 1 && pending.back().cpu_times.at("sentinel") == 7);
    // Cancellation/failure can happen inside a scope; no dangling accumulator write.
    beginCPUFrame();
    { CPUScope scope("cancelled"); releaseQueries(); }
    endCPUFrame();
    assert(cpu_times.empty() && pending.empty());
    beginCPUFrame();
    { CPUScope scope("failed"); failCapture("test"); }
    endCPUFrame();
    assert(capture_state == "failed" && cpu_times.empty());
}
'''
    with tempfile.TemporaryDirectory() as folder:
        cpp = Path(folder) / "viewer_mcp_cpu.cpp"
        exe = Path(folder) / "viewer_mcp_cpu.exe"
        cpp.write_text(code)
        subprocess.run(["g++", "-std=c++17", "-pthread", "-I", str(ROOT / "indra/newview"),
                        str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("PASS: CPU scope accumulation, nesting, warmup, worker exclusion, frame pairing, "
          "GPU backlog, cancellation/failure, raw samples and percentile coverage")


if __name__ == "__main__":
    main()
