"""Exercise production backward-walk input and packet preparation with Python + g++."""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "indra/newview/llagent.cpp").read_text()
constants = (ROOT / "indra/llcommon/indra_constants.h").read_text()


def function(signature):
    start = source.index(signature)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


harness = r'''
#include <cassert>
#include <cstdint>
#include <initializer_list>
using U32 = uint32_t;
using S32 = int;
constexpr float F_PI = 3.14159265f;
struct LLUIUsage {
    static LLUIUsage& instance() { static LLUIUsage value; return value; }
    void logCommand(const char*) {}
};
struct LLFirstUse { static void notMoving(bool) {} };
struct LLAgentCamera {
    int at = 0, walk = 0, left = 0;
    static int directionToKey(int direction) { return (direction > 0) - (direction < 0); }
    void setAtKey(int value) { at = value; }
    void setWalkKey(int value) { walk = value; }
    void setLeftKey(int value) { left = value; }
    int getAtKey() const { return at; }
    int getWalkKey() const { return walk; }
    int getLeftKey() const { return left; }
    void resetView() {}
} gAgentCamera;
struct LLAgent {
    struct Timer { void reset() {} } mMoveTimer;
    bool enabled = true, mFacingBackwardWalk = false;
    U32 mControlFlags = 0;
    int heading = 1, turns = 0;
    void ageChat() {}
    bool shouldFaceBackwardWalk() const { return enabled; }
    int getReferenceUpVector() { return 0; }
    void rotate(float, int) { heading = -heading; ++turns; }
    void setControlFlags(U32 flags) { mControlFlags |= flags; }
    void moveAt(S32 direction, bool reset = true);
    void moveAtNudge(S32 direction);
    void moveLeft(S32 direction);
    void moveLeftNudge(S32 direction);
    void updateBackwardWalk();
    U32 prepareControlFlagsForUpdate();
};
'''
harness += "\n".join(re.findall(
    r"constexpr U32 (?:CONTROL_\w+|AGENT_CONTROL_\w+)\s*=.*?;", constants)) + "\n"
for name in ("void LLAgent::moveAt(", "void LLAgent::moveAtNudge(",
             "void LLAgent::moveLeft(", "void LLAgent::moveLeftNudge(",
             "void LLAgent::updateBackwardWalk(", "U32 LLAgent::prepareControlFlagsForUpdate("):
    harness += function(name) + "\n"
harness += r'''
constexpr U32 lateral = AGENT_CONTROL_LEFT_POS | AGENT_CONTROL_LEFT_NEG |
    AGENT_CONTROL_NUDGE_LEFT_POS | AGENT_CONTROL_NUDGE_LEFT_NEG | AGENT_CONTROL_FAST_LEFT;
constexpr U32 unrelated = AGENT_CONTROL_UP_POS | AGENT_CONTROL_YAW_POS | AGENT_CONTROL_LBUTTON_DOWN;
void beginFrame(LLAgent& agent) { agent.mControlFlags = unrelated; gAgentCamera = {}; }
U32 packet(LLAgent& agent) {
    const U32 raw = agent.mControlFlags;
    const U32 result = agent.prepareControlFlagsForUpdate();
    const int turns = agent.turns;
    assert(agent.prepareControlFlagsForUpdate() == result);
    assert(agent.turns == turns && agent.mControlFlags == raw);
    assert((result & unrelated) == unrelated);
    return result;
}
int main() {
    // Hold S throughout A -> overlap -> D -> overlap -> A. Exercise either
    // input scan order and every combination of new (nudge) and held keys.
    for (bool at_first : {false, true}) {
        LLAgent agent;
        for (int cycle = 0; cycle < 100; ++cycle) {
            for (int direction : {1, -1}) {
                for (bool old_nudge : {false, true})
                for (bool new_nudge : {false, true}) {
                    beginFrame(agent);
                    if (at_first) agent.moveAt(-1);
                    if (old_nudge) agent.moveLeftNudge(-direction);
                    else agent.moveLeft(-direction);
                    if (new_nudge) agent.moveLeftNudge(direction);
                    else agent.moveLeft(direction);
                    if (!at_first) agent.moveAt(-1);
                    U32 flags = packet(agent);
                    assert((flags & lateral) == 0); // Opposites cancel, regardless of strength.
                    assert(flags & AGENT_CONTROL_AT_POS);
                    assert(agent.heading == -1 && agent.turns == 1);

                    // Release the old direction. A newly pressed key has the
                    // same strength as a held key during an ongoing S walk.
                    beginFrame(agent);
                    if (at_first) agent.moveAt(-1);
                    if (new_nudge) agent.moveLeftNudge(direction);
                    else agent.moveLeft(direction);
                    if (!at_first) agent.moveAt(-1);
                    flags = packet(agent);
                    const U32 expected = (direction > 0 ? AGENT_CONTROL_LEFT_NEG : AGENT_CONTROL_LEFT_POS)
                        | AGENT_CONTROL_FAST_LEFT;
                    assert((flags & lateral) == expected);
                    const int body_left = bool(flags & AGENT_CONTROL_LEFT_POS) - bool(flags & AGENT_CONTROL_LEFT_NEG);
                    assert(agent.heading * body_left == direction);
                    assert(agent.turns == 1);
                }
            }
        }
        // Releasing S must not flip the body and reverse the lateral control
        // during a continuous strafe (mouse-steer A/D routes to moveLeft).
        beginFrame(agent);
        agent.moveLeft(1);
        assert((packet(agent) & lateral) == (AGENT_CONTROL_LEFT_NEG | AGENT_CONTROL_FAST_LEFT));
        assert(agent.heading == -1 && agent.mFacingBackwardWalk && agent.turns == 1);
        beginFrame(agent); // Finish the strafe before restoring the heading.
        assert(packet(agent) == unrelated);
        assert(agent.heading == 1 && !agent.mFacingBackwardWalk && agent.turns == 2);
    }
    for (int direction : {1, -1}) {
        for (bool nudge : {false, true}) {
            LLAgent agent;
            beginFrame(agent);
            agent.moveAt(-1);
            agent.moveLeft(direction);
            const U32 diagonal = packet(agent);
            for (int frame = 0; frame < 60; ++frame) {
                beginFrame(agent); // S released; keep the same strafe held.
                if (nudge) agent.moveLeftNudge(direction);
                else agent.moveLeft(direction);
                const U32 flags = packet(agent);
                assert(agent.heading == -1 && agent.turns == 1);
                const int body_left = bool(flags & (AGENT_CONTROL_LEFT_POS | AGENT_CONTROL_NUDGE_LEFT_POS))
                    - bool(flags & (AGENT_CONTROL_LEFT_NEG | AGENT_CONTROL_NUDGE_LEFT_NEG));
                assert(agent.heading * body_left == direction);
                if (!nudge) assert((flags & lateral) == (diagonal & lateral));
                assert(!(flags & (AGENT_CONTROL_AT_POS | AGENT_CONTROL_AT_NEG |
                                  AGENT_CONTROL_NUDGE_AT_POS | AGENT_CONTROL_NUDGE_AT_NEG)));
            }
            beginFrame(agent);
            agent.moveAt(1); // W ends the retained backward-facing strafe.
            agent.moveLeft(direction);
            const U32 flags = packet(agent);
            assert(agent.heading == 1 && agent.turns == 2);
            assert(flags & AGENT_CONTROL_AT_POS);
            assert((flags & lateral) == ((direction > 0 ? AGENT_CONTROL_LEFT_POS : AGENT_CONTROL_LEFT_NEG)
                                        | AGENT_CONTROL_FAST_LEFT));
        }
    }
    for (bool enabled : {false, true}) {
        LLAgent agent;
        agent.enabled = enabled;
        beginFrame(agent);
        agent.moveAtNudge(-1);
        agent.moveLeftNudge(1);
        U32 flags = packet(agent);
        if (enabled) {
            assert(agent.heading == -1);
            assert(flags == (unrelated | AGENT_CONTROL_NUDGE_AT_POS | AGENT_CONTROL_NUDGE_LEFT_NEG));
            agent.enabled = false; // Option/camera/flight eligibility changed.
            assert(packet(agent) == agent.mControlFlags && agent.heading == 1);
        } else {
            assert(flags == agent.mControlFlags && agent.heading == 1);
        }
    }
}
'''

with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / "backward_walk.cpp"
    exe = Path(directory) / "backward_walk.exe"
    cpp.write_text(harness)
    subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("Backward walk: S+A/S+D to continuous strafe, forward/stop transitions, mixed nudge/held overlap, input order and disabled mode passed.")
