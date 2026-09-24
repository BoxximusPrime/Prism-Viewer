"""Exercise swimming decisions without rebuilding or running the viewer.

Uses the production C++ policy; requires Python and g++ on PATH.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
NEWVIEW = ROOT / "indra/newview"

HARNESS = r'''
#include "llswimpolicy.h"
#include <cassert>
#include <cmath>
#include <iostream>

// CONTROL_GUARD_HARNESS

using Flight = LLSwimPolicy::Flight;
LLSwimPolicy::Input water()
{
    LLSwimPolicy::Input in;
    in.enabled = in.ready = in.allowed = true;
    in.in_air = true;
    in.depth = 2.f;
    in.ground_depth = 10.f;
    return in;
}

int main()
{
    // Regression: vertical NUDGE controls barely moved in the user's SL test,
    // and horizontal nudges did not lower flight speed. Use ordinary controls
    // again. This verifies encoding, not simulator speed or smoothness.
    const U32 movement = AGENT_CONTROL_AT_POS | AGENT_CONTROL_AT_NEG |
        AGENT_CONTROL_LEFT_POS | AGENT_CONTROL_LEFT_NEG |
        AGENT_CONTROL_UP_POS | AGENT_CONTROL_UP_NEG |
        AGENT_CONTROL_FAST_AT | AGENT_CONTROL_FAST_LEFT | AGENT_CONTROL_FAST_UP |
        AGENT_CONTROL_NUDGE_AT_POS | AGENT_CONTROL_NUDGE_AT_NEG |
        AGENT_CONTROL_NUDGE_LEFT_POS | AGENT_CONTROL_NUDGE_LEFT_NEG |
        AGENT_CONTROL_NUDGE_UP_POS | AGENT_CONTROL_NUDGE_UP_NEG;
    const U32 unrelated = ~movement; // Includes flight, stop, turning and mouse controls.
    sPolicy.update(water());
    for (int forward = -1; forward <= 1; ++forward)
    for (int left = -1; left <= 1; ++left)
    for (int up = -1; up <= 1; ++up)
    {
        LLSwimPolicy::Output out{Flight::KEEP, forward, left, up};
        U32 expected = unrelated;
        if (forward) expected |= forward > 0 ? AGENT_CONTROL_AT_POS : AGENT_CONTROL_AT_NEG;
        if (left) expected |= left > 0 ? AGENT_CONTROL_LEFT_POS : AGENT_CONTROL_LEFT_NEG;
        if (up) expected |= up > 0 ? AGENT_CONTROL_UP_POS : AGENT_CONTROL_UP_NEG;
        gAgent.controls = unrelated | movement;
        for (int frame = 0; frame < 200; ++frame)
        {
            applySwimControls(out);
            assert(gAgent.controls == expected);
        }
        applySwimControls({}); // Key release clears movement; nothing is latched.
        assert(gAgent.controls == unrelated);
    }
    sPolicy = {};
    gAgent.controls = unrelated | movement;
    applySwimControls({});
    assert(gAgent.controls == (unrelated | movement)); // Ordinary movement is unchanged.
    gAgent = {};
    // Regression: an attachment watching any key with PassToAgent used to
    // disable swimming, even though ordinary walking/flying remained usable.
    for (U32 control = 0; control < TOTAL_CONTROLS; ++control)
    {
        gAgent = {};
        gAgent.mControlsTakenPassedOnCount[control] = 1;
        assert(gAgent.anyControlGrabbed()); // The old gate rejects this case.
        assert(!movementControlsGrabbed());
        LLSwimPolicy policy;
        auto in = water();
        in.allowed = !movementControlsGrabbed();
        assert(policy.update(in).flight == Flight::START);
    }
    for (S32 control : {CONTROL_LBUTTON_DOWN_INDEX, CONTROL_LBUTTON_UP_INDEX,
                       CONTROL_ML_LBUTTON_DOWN_INDEX, CONTROL_ML_LBUTTON_UP_INDEX})
    {
        gAgent = {};
        gAgent.mControlsTakenCount[control] = 1;
        assert(gAgent.anyControlGrabbed() && !movementControlsGrabbed());
    }
    for (S32 control : {CONTROL_AT_POS_INDEX, CONTROL_AT_NEG_INDEX,
                       CONTROL_LEFT_POS_INDEX, CONTROL_LEFT_NEG_INDEX,
                       CONTROL_UP_POS_INDEX, CONTROL_UP_NEG_INDEX,
                       CONTROL_YAW_POS_INDEX, CONTROL_YAW_NEG_INDEX,
                       CONTROL_FLY_INDEX, CONTROL_STOP_INDEX,
                       CONTROL_NUDGE_UP_POS_INDEX, CONTROL_NUDGE_UP_NEG_INDEX})
    {
        gAgent = {};
        gAgent.mControlsTakenCount[control] = 1;
        assert(movementControlsGrabbed());
        LLSwimPolicy policy;
        auto in = water();
        policy.update(in);
        in.flying = true;
        in.allowed = !movementControlsGrabbed();
        assert(policy.update(in).flight == Flight::STOP && !policy.swimming());
    }
    gAgent = {};
    // Opt-in, sufficient depth, and normal flight permissions are mandatory.
    for (int blocked = 0; blocked < 5; ++blocked)
    {
        LLSwimPolicy policy;
        auto in = water();
        if (blocked == 0) in.enabled = false;
        if (blocked == 1) in.ready = false;
        if (blocked == 2) in.allowed = false;
        if (blocked == 3) in.depth = 0.2f;
        if (blocked == 4) in.ground_depth = 1.f;
        assert(policy.update(in).flight == Flight::KEEP && !policy.swimming());
    }
    // Starting flight is a one-time transition. Neutral deep-water input hovers.
    {
        LLSwimPolicy policy;
        auto in = water();
        assert(policy.update(in).flight == Flight::START && policy.swimming());
        in.flying = true;
        for (int frame = 0; frame < 500; ++frame)
        {
            auto out = policy.update(in);
            assert(out.flight == Flight::KEEP && out.up == 0 && policy.swimming());
        }
    }
    // Disabling, teleporting/disconnecting, restrictions and shore/air exits
    // release only flight enabled by swimming, preserving pre-existing flight.
    for (bool already_flying : {false, true})
    {
        for (int exit = 0; exit < 6; ++exit)
        {
            LLSwimPolicy policy;
            auto in = water();
            in.flying = already_flying;
            policy.update(in);
            in.flying = true;
            if (exit == 0) in.enabled = false;
            if (exit == 1) in.ready = false;
            if (exit == 2) in.allowed = false;
            if (exit == 3) in.ground_depth = 1.f;
            if (exit == 4) in.depth = -0.3f;
            if (exit == 5) in.in_air = false;
            assert(policy.update(in).flight == (already_flying ? Flight::KEEP : Flight::STOP));
            assert(!policy.swimming());
        }
    }
    // Entering while standing on a submerged seabed can take off; touching
    // bottom after swimming leaves swim mode instead of repeatedly taking off.
    {
        LLSwimPolicy policy;
        auto in = water();
        in.in_air = false;
        assert(policy.update(in).flight == Flight::START);
        in.flying = true;
        assert(policy.update(in).flight == Flight::KEEP && policy.swimming());
        in.in_air = true;
        policy.update(in);
        in.in_air = false;
        assert(policy.update(in).flight == Flight::STOP);
        in.flying = false;
        assert(policy.update(in).flight == Flight::KEEP && !policy.swimming());
    }
    // Explicit Stop Flying stays stopped underwater, until dry or option reset.
    for (bool use_callback : {false, true})
    {
        LLSwimPolicy policy;
        auto in = water();
        policy.update(in);
        if (use_callback) policy.flightDisabled();
        for (int frame = 0; frame < 50; ++frame)
            assert(policy.update(in).flight == Flight::KEEP && !policy.swimming());
        in.depth = -0.5f;
        policy.update(in);
        in.depth = 2.f;
        assert(policy.update(in).flight == Flight::START);
        policy.flightDisabled();
        in.enabled = false;
        policy.update(in);
        in.enabled = true;
        assert(policy.update(in).flight == Flight::START);
    }
    // Holding a direction must remain continuous across speed reports. The old
    // limiter alternated movement/idle near 2.1 and 1.5 m/s, causing both speed
    // surges and simulator/AO animation transitions visible to observers.
    for (int forward = -1; forward <= 1; ++forward)
    for (int left = -1; left <= 1; ++left)
    {
        if (!forward && !left) continue;
        LLSwimPolicy policy;
        auto in = water();
        policy.update(in);
        in.flying = true;
        in.forward = forward;
        in.left = left;
        assert(policy.update(in).forward == forward);
        assert(policy.update(in).left == left);
        const float length = std::hypot(float(forward), float(left));
        for (int frame = 0; frame < 600; ++frame)
        {
            const float speed = 2.f + 1.5f * std::sin(float(frame) * 0.1f);
            in.forward_velocity = speed * forward / length;
            in.left_velocity = speed * left / length;
            auto out = policy.update(in);
            assert(out.forward == forward && out.left == left && out.up == 0);
            assert(out.flight == Flight::KEEP && policy.swimming());
        }
        in.forward = -forward;
        in.left = -left;
        auto out = policy.update(in);
        assert(out.forward == -forward && out.left == -left);
        // Releasing the keys stops immediately; this is not an animation or
        // movement latch that keeps swimming after the user lets go.
        in.forward = in.left = 0;
        out = policy.update(in);
        assert(out.forward == 0 && out.left == 0);
        // Surface-height corrections must not interrupt horizontal input.
        in.forward = forward;
        in.left = left;
        in.depth = 0.44f;
        for (float vertical : {-0.8f, 0.f, 0.8f})
        {
            in.up_velocity = vertical;
            out = policy.update(in);
            assert(out.forward == forward && out.left == left);
        }
    }
    // Surface target scales with avatar height, holds an idle swimmer, resists
    // held Jump, and always permits Crouch to dive. No fly/land oscillation.
    for (float height : {0.5f, 2.f, 4.f})
    {
        LLSwimPolicy policy;
        auto in = water();
        in.height = height;
        policy.update(in);
        in.flying = true;
        in.depth = 0.22f * height;
        for (int frame = 0; frame < 100; ++frame)
        {
            in.depth = 0.22f * height + 0.02f * height * std::sin(float(frame));
            auto out = policy.update(in);
            assert(policy.swimming() && out.flight == Flight::KEEP && out.up == 0);
        }
        in.depth = 0.22f * height;
        in.up = 1;
        assert(policy.update(in).up == 0);
        in.up_velocity = 0.8f;
        assert(policy.update(in).up == -1); // Predicted overshoot brakes early.
        in.up = -1;
        assert(policy.update(in).up == -1);
        in.depth = 2.f;
        in.up = 1;
        in.up_velocity = 1.1f;
        assert(policy.update(in).up == 1);
        in.up_velocity = 0.8f;
        assert(policy.update(in).up == 1);
        in.up_velocity = 0.5f;
        assert(policy.update(in).up == 1);
        in.up = -1;
        assert(policy.update(in).up == -1);
        in.up_velocity = -1.5f;
        assert(policy.update(in).up == -1);
        in.stop = true;
        in.up = 0;
        in.depth = 0.f;
        assert(policy.update(in).up == 0); // Stop never injects a surface correction.
    }
    std::cout << "PASS: attachment pass-through/mouse controls and consumed movement controls; "
        "swim entry/exit, ownership, manual stop, seabed, restrictions, "
        "lifecycle, ordinary movement controls on all axes, continuous movement across speed changes, "
        "surface hold, dive and avatar sizes\n";
}
'''


def main():
    source = (NEWVIEW / "llboxxyswim.cpp").read_text()
    agent = (NEWVIEW / "llagent.cpp").read_text()

    def function(text, signature):
        start = text.index(signature)
        return text[start:text.index("\n}", start) + 2]

    controls = r'''
#define LL_COMMON_API
#include "indra_constants.h"
#include <array>
struct LLAgent {
    U32 controls = 0;
    void setControlFlags(U32 flags) { controls |= flags; }
    void clearControlFlags(U32 flags) { controls &= ~flags; }
    std::array<S32, TOTAL_CONTROLS> mControlsTakenCount{};
    std::array<S32, TOTAL_CONTROLS> mControlsTakenPassedOnCount{};
    bool anyControlGrabbed() const;
    bool isControlGrabbed(S32 control_index) const;
} gAgent;
'''
    controls += function(agent, "bool LLAgent::anyControlGrabbed() const") + "\n"
    controls += function(agent, "bool LLAgent::isControlGrabbed(S32 control_index) const") + "\n"
    controls += function(source, "bool movementControlsGrabbed()") + "\n"
    # Compile the production control-writing block, including its swim guard.
    adapter_start = source.index("    if (sPolicy.swimming())\n    {")
    adapter_end = source.index("    updateAnimation();", adapter_start)
    controls += "LLSwimPolicy sPolicy;\nvoid applySwimControls(const LLSwimPolicy::Output& output)\n{\n"
    controls += source[adapter_start:adapter_end] + "}\n"
    assert re.search(r"else if \(movementControlsGrabbed\(\)\) status =", source)
    assert "gAgent.anyControlGrabbed()" not in source
    with tempfile.TemporaryDirectory(prefix="prism-swimming-") as temporary:
        cpp = Path(temporary) / "swimming.cpp"
        exe = Path(temporary) / "swimming.exe"
        cpp.write_text(HARNESS.replace("// CONTROL_GUARD_HARNESS", controls))
        subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-pedantic",
                        "-I", str(NEWVIEW), "-I", str(ROOT / "indra/llcommon"),
                        str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)

    settings = ET.parse(NEWVIEW / "app_settings/settings.xml").getroot().find("map")
    keys = [node.text for node in settings if node.tag == "key"]
    assert len(keys) == len(set(keys)), "Duplicate saved setting"
    entries = list(settings)
    setting = entries[next(i for i, node in enumerate(entries)
                           if node.tag == "key" and node.text == "BoxxyExperimentalSwimming") + 1]
    values = {setting[i].text: setting[i + 1].text for i in range(0, len(setting), 2)}
    assert values["Type"] == "Boolean" and values["Value"] == "0" and values["Persist"] == "1"
    panel = ET.parse(NEWVIEW / "skins/default/xui/en/panel_preferences_move.xml").getroot()
    prism = panel.find(".//panel[@name='boxxy_options']")
    check = prism.find("check_box[@control_name='BoxxyExperimentalSwimming']")
    assert check is not None and "experimental" in check.get("label").lower()
    bottom = 0
    for child in prism:
        top = int(child.get("top", bottom + int(child.get("top_pad", "0"))))
        bottom = top + int(child.get("height", "0"))
        assert bottom <= int(prism.get("height")), child.get("name")
        assert int(child.get("left", "0")) + int(child.get("width", "0")) <= int(prism.get("width"))
    print("PASS: unique persisted/off-by-default setting, experimental Prism checkbox and panel bounds")


if __name__ == "__main__":
    main()
