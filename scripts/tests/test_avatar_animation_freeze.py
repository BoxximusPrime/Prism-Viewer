"""Run production motion-update methods with a deterministic clock: python this_file.py.

Requires g++ on PATH. Rendering/motion callbacks are counted instead of rendered.
"""
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "indra/llcharacter/llmotioncontroller.cpp").read_text()


def method(name):
    start = source.index("void LLMotionController::" + name + "(")
    end = source.index("\n}", start) + 2
    return source[start:end]


harness = r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#define LL_PROFILE_ZONE_SCOPED_CATEGORY_AVATAR
using F32 = float;
using S32 = int;
using std::max;
#define llmax std::max
int llfloor(float x) { return int(std::floor(x)); }
struct LLMotionController {
    float mTimeStep=0, mPrevTimerElapsed=0, mLastTime=0, mAnimTime=7;
    float mTimeFactor=1, mLastInterp=0;
    int mTimeStepCount=0, callbacks=0;
    bool mPaused=false, mFrozen=false, mHasRunOnce=false;
    struct Timer {
        float now=0;
        float getElapsedTimeF32() { return now; }
    } mTimer;
    struct Blender {
        int writes=0;
        void interpolate(float) { ++writes; }
        void blendAndCache(bool) { ++writes; }
        void blendAndApply() { ++writes; }
    } mPoseBlender;
    void purgeExcessMotions() { ++callbacks; }
    void updateLoadingMotions() { ++callbacks; }
    void resetJointSignatures() { ++callbacks; }
    void updateIdleActiveMotions() { ++callbacks; }
    void updateAdditiveMotions() { ++callbacks; }
    void updateRegularMotions() { ++callbacks; }
    void deactivateStoppedMotions() { ++callbacks; }
    void clearBlenders() { ++callbacks; }
    void updateMotions(bool);
    void updateMotionsMinimal(bool);
};
'''
harness += method("updateMotions") + "\n" + method("updateMotionsMinimal")
harness += r'''
int main() {
    for (int mode=0; mode<4; ++mode) {
        LLMotionController c;
        auto update = [&]() {
            if (mode<2) c.updateMotions(mode==1);
            else c.updateMotionsMinimal(mode==2);
        };
        c.mFrozen=true;
        for (int frame=1; frame<=100; ++frame) {
            c.mTimer.now=float(frame);
            update();
            assert(c.mAnimTime==7);
            assert(c.callbacks==0 && c.mPoseBlender.writes==0);
        }
        c.mFrozen=false;
        c.mTimer.now=101;
        update();
        assert(c.mAnimTime==(mode==3 ? 7 : 8));
        assert(c.callbacks>0);
        // Existing pause owners still hold their animation clock after unfreezing.
        c.mPaused=true;
        c.mTimer.now=102;
        update();
        assert(c.mAnimTime==(mode==3 ? 7 : 8));
    }
}
'''

menu = ET.parse(ROOT / "indra/newview/skins/default/xui/en/menu_viewer.xml")
item = menu.find(".//menu[@name='Avatar']/menu_item_check[@name='Freeze All Avatar Animations']")
assert item is not None
for event in ("on_check", "on_click"):
    assert item.find("menu_item_check." + event).get("parameter") == "BoxxyFreezeAvatarAnimations"
ET.parse(ROOT / "indra/newview/app_settings/settings.xml")

with tempfile.TemporaryDirectory() as temp:
    cpp = Path(temp) / "freeze.cpp"
    exe = Path(temp) / "freeze.exe"
    cpp.write_text(harness)
    subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("PASS: freeze/resume in normal, forced, hidden sync and hidden non-sync updates; menu wiring")
