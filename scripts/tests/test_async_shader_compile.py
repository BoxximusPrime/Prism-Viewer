"""Exercise production batch scheduling and the render-pause transport pump.

Run: python scripts/tests/test_async_shader_compile.py (g++ on PATH).
GL completion and sockets are deterministic fakes; the scheduler, ping decoder,
and heartbeat/ACK loop are extracted from the production C++.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

from test_shader_source_cache import function


STUBS = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <set>
#include <string>
#include <vector>
#include "llzerocode.h"
using GLuint = unsigned;
using GLenum = unsigned;
using GLint = int;
using TPACKETID = U32;
constexpr int GL_FALSE = 0, GL_TRUE = 1;
constexpr int LL_PACKET_ID_SIZE = 6, LL_MINIMUM_VALID_PACKET_SIZE = 7;
constexpr int PHL_OFFSET = 5, MAX_BUFFER_SIZE = 8192;
constexpr U8 LL_ACK_FLAG = 0x10, LL_ZERO_CODE_FLAG = 0x80;
#define llassert_always assert
#define LL_INFOS(x) std::cout
#define LL_ENDL std::endl
struct { std::set<std::string> mGLExtensions; } gGLManager;
int polls = 0, sleeps = 0, idle = 0;
std::map<GLuint, int> remaining;
void glGetProgramiv(GLuint id, GLenum token, GLint* result) {
    assert(token == 0x91B1); ++polls;
    *result = remaining[id]-- <= 0;
}
void glGetShaderiv(GLuint id, GLenum token, GLint* result) {
    glGetProgramiv(id, token, result);
}
void ms_sleep(int n) { assert(n == 1); ++sleeps; }
struct LLShaderFeatures { bool runtimeLighting = false; };
struct LLGLSLShader {
    GLuint mProgramObject;
    LLShaderFeatures mFeatures;
    bool fallbackSucceeds = true;
    int retried = 0, finished = 0;
    bool mapAttributes(bool link) { assert(!link); return true; }
    bool finishShader(bool success) {
        assert(remaining[mProgramObject] < 0); ++finished; return success;
    }
    bool createShaderInternal() {
        assert(!mFeatures.runtimeLighting); ++retried; return fallbackSucceeds;
    }
};
struct LLShaderMgr {
    struct PendingShader { LLGLSLShader* shader; LLShaderFeatures features; };
    std::vector<PendingShader> mPendingShaders;
    bool mShaderBatching = false, mShaderBatchSuccess = true;
    std::set<GLuint> badLinks;
    int processed = 0, failed = 0, cached = 0;
    void shaderCompileIdle() { ++idle; }
    void shaderProgramProcessed(LLGLSLShader*, bool success) { ++processed; failed += !success; }
    void saveCachedProgramBinary(LLGLSLShader*) { ++cached; }
    bool checkProgramLink(GLuint id) { waitForShader(id, true); return !badLinks.contains(id); }
    void beginShaderBatch();
    bool finishShaderBatch();
    bool isShaderPending(const LLGLSLShader*) const;
    void queueShader(LLGLSLShader*);
    void waitForShader(GLuint, bool);
    void flushShaderBatch();
};

using F64Seconds = double;
using LLHost = int;
constexpr int _PREHASH_StartPingCheck = 1, _PREHASH_CompletePingCheck = 2;
constexpr int _PREHASH_PacketAck = 3, _PREHASH_PingID = 4;
constexpr int _PREHASH_OldestUnacked = 5, _PREHASH_Packets = 6, _PREHASH_ID = 7;
struct LLTemplateMessageBuilder {
    int kind = 0;
    std::vector<U32> values;
    explicit LLTemplateMessageBuilder(int) {}
    void newMessage(int message) { kind = message; values.clear(); }
    void nextBlock(int) {}
    void addU8(int, U8 value) { values.push_back(value); }
    void addU32(int, U32 value) { values.push_back(value); }
};
struct LLCircuitData {
    bool alive = true;
    int host = 0, starts = 0;
    double mLastPingSendTime = 0, mHeartbeatInterval = 5, mAckCreationTime = 1;
    std::vector<U32> mAcks;
    bool isAlive() const { return alive; }
    void pingTimerStart() { ++starts; }
    U8 nextPingID() { return U8(starts); }
};
struct LLCircuit {
    using circuit_data_map = std::map<LLHost, LLCircuitData*>;
    circuit_data_map circuits, mSendAckMap;
    void getCircuitRange(LLHost, circuit_data_map::iterator& it, circuit_data_map::iterator& end) {
        it = circuits.begin(); end = circuits.end();
    }
};
template<class T> T llmin(T a, T b) { return std::min(a, b); }
struct LLMessageSystem {
    struct Sent { int host, kind; std::vector<U32> values; };
    std::vector<Sent> sent;
    LLCircuit mCircuitInfo;
    int mMessageTemplates = 0, received = 0, available = 0;
    double now = 10;
    // The normal message builder/reader represent a suspended scene callback.
    int currentBuilder = 123, currentReader = 456;
    double getMessageTimeSeconds(bool update) { assert(update); return now; }
    int bufferInboundPacket(bool transport) {
        assert(transport); if (available <= 0) return 0;
        --available; ++received; return 8;
    }
    void sendCircuitMessage(LLCircuitData* circuit, LLTemplateMessageBuilder& builder) {
        sent.push_back({circuit->host, builder.kind, builder.values});
    }
    void pumpCircuitKeepAlive();
};
'''

CHECKS = r'''
int main() {
    LLShaderMgr mgr;
    mgr.beginShaderBatch();
    assert(!mgr.mShaderBatching && mgr.finishShaderBatch());
    mgr.waitForShader(1, true);
    assert(polls == 0 && idle == 1); // unsupported drivers never receive the extension query
    for (const auto* extension : {"GL_ARB_parallel_shader_compile", "GL_KHR_parallel_shader_compile"}) {
        gGLManager.mGLExtensions = {extension};
        LLShaderMgr batch;
        batch.beginShaderBatch();
        std::vector<LLGLSLShader> shaders(35);
        for (GLuint i = 0; i < shaders.size(); ++i) {
            auto& shader = shaders[i]; shader.mProgramObject = i;
            remaining[i] = 3;
            batch.queueShader(&shader);
            shader.mFeatures.runtimeLighting = true; // loaders' post-compile overrides
            assert(batch.mPendingShaders.size() <= 16);
            if (i < 16) assert(batch.processed == 0);
        }
        assert(batch.finishShaderBatch());
        assert(batch.processed == 35 && batch.cached == 35 && !batch.mShaderBatching);
        assert(batch.mPendingShaders.empty());
        for (const auto& shader : shaders)
            assert(shader.finished == 1 && shader.mFeatures.runtimeLighting);
    }
    LLGLSLShader recover{101}, fail{102}; fail.fallbackSucceeds = false;
    mgr.badLinks = {101, 102};
    mgr.beginShaderBatch(); mgr.queueShader(&recover); mgr.queueShader(&fail);
    recover.mFeatures.runtimeLighting = fail.mFeatures.runtimeLighting = true;
    assert(!mgr.finishShaderBatch());
    assert(recover.retried == 1 && fail.retried == 1 && mgr.failed == 1);
    assert(recover.mFeatures.runtimeLighting && fail.mFeatures.runtimeLighting);
    mgr.beginShaderBatch(); assert(mgr.finishShaderBatch()); // failure doesn't poison the next reload
    const int previousIdle = idle;
    remaining[200] = 9; mgr.waitForShader(200, false);
    assert(idle > previousIdle + 8 && sleeps > 0);

    for (U8 message : {1, 2}) {
        std::vector<U8> ping(7 + (message == 1 ? 5 : 1), 0);
        ping[6] = message; ping[7] = 42;
        U8 id = 99;
        for (size_t size = 0; size < ping.size(); ++size)
            assert(circuitPing(ping.data(), int(size), id) == 0);
        assert(circuitPing(ping.data(), int(ping.size()), id) == message && id == 42);
        auto offset = ping; offset.insert(offset.begin() + 7, {21, 22, 23}); offset[5] = 3;
        assert(circuitPing(offset.data(), int(offset.size()), id) == message && id == 42);
        auto ack = ping; ack[0] |= LL_ACK_FLAG;
        ack.insert(ack.end(), {1, 2, 3, 4, 1});
        assert(circuitPing(ack.data(), int(ack.size()), id) == message && id == 42);
        ack.back() = 255;
        assert(circuitPing(ack.data(), int(ack.size()), id) == 0);
        auto extra = ping; extra.push_back(1);
        assert(circuitPing(extra.data(), int(extra.size()), id) == 0);
        ping[6] = 3;
        assert(circuitPing(ping.data(), int(ping.size()), id) == 0);
    }
    U8 compressed[] = {0x80,0,0,0,1,0,1,42,0,4};
    U8 id;
    assert(circuitPing(compressed, sizeof(compressed), id) == 1 && id == 42);
    assert(circuitPing(compressed, sizeof(compressed) - 1, id) == 0);
    std::vector<U8> overflow{0x80,0,0,0,1,0,1,42};
    for (int i = 0; i < 100; ++i) { overflow.push_back(0); overflow.push_back(255); }
    assert(circuitPing(overflow.data(), int(overflow.size()), id) == 0);

    LLMessageSystem messages;
    LLCircuitData live, dead; live.host = 1; dead.host = 2; dead.alive = false;
    messages.mCircuitInfo.circuits = {{1, &live}, {2, &dead}};
    live.mAcks.resize(501);
    for (U32 i = 0; i < live.mAcks.size(); ++i) live.mAcks[i] = i + 100;
    messages.mCircuitInfo.mSendAckMap = {{1, &live}};
    messages.available = 10000;
    messages.pumpCircuitKeepAlive();
    assert(messages.received == 256 && messages.sent.size() == 4);
    assert(messages.sent[0].kind == _PREHASH_StartPingCheck && messages.sent[0].values[1] == 0);
    assert(messages.sent[1].values.size() == 250 && messages.sent[2].values.size() == 250);
    assert(messages.sent[3].values == std::vector<U32>{600});
    assert(live.mAcks.empty() && messages.mCircuitInfo.mSendAckMap.empty());
    assert(messages.currentBuilder == 123 && messages.currentReader == 456);
    messages.pumpCircuitKeepAlive(); assert(messages.sent.size() == 4); // heartbeat throttled
    messages.now += 6; messages.pumpCircuitKeepAlive(); assert(messages.sent.size() == 5);
    assert(dead.starts == 0);
    std::cout << "PASS: bounded batches, extension fallback, polling, failures, runtime flags, ping validation, heartbeat and ACK scheduling\n";
}
'''


def main():
    root = Path(__file__).resolve().parents[2]
    renderer = (root / "indra/llrender/llshadermgr.cpp").read_text()
    network = (root / "indra/llmessage/message.cpp").read_text()
    methods = "\n".join(function(renderer, signature) for signature in (
        "void LLShaderMgr::beginShaderBatch(", "bool LLShaderMgr::isShaderPending(",
        "void LLShaderMgr::queueShader(", "void LLShaderMgr::waitForShader(",
        "void LLShaderMgr::flushShaderBatch(", "bool LLShaderMgr::finishShaderBatch("))
    methods += function(network, "static U8 circuitPing(")
    methods += function(network, "void LLMessageSystem::pumpCircuitKeepAlive(")
    compiler = shutil.which("g++")
    if compiler is None:
        raise SystemExit("g++ must be on PATH")
    with tempfile.TemporaryDirectory(prefix="prism-async-shaders-") as directory:
        source = Path(directory) / "check.cpp"
        executable = Path(directory) / "check.exe"
        source.write_text(STUBS + methods + CHECKS)
        subprocess.run([compiler, "-std=c++20", "-I" + str(root / "indra/llmessage"),
                        "-I" + str(root / "indra/llcommon"), str(source), "-o", str(executable)], check=True)
        subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    main()
