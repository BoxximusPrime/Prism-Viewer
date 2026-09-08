"""Exercise the production drag-mode dispatch: python scripts/tests/test_rotate_aim.py.
Requires g++ on PATH. Scene picking and transforms are deterministic stand-ins.
"""
from pathlib import Path
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[2] / "indra/newview/llmaniprotate.cpp").read_text()
start = source.index("    const bool aim =")
end = source.index("    bool damped =", start)
dispatch = source[start:end]
harness = r"""
#include <cassert>
using S32 = int;
using MASK = int;
constexpr int MASK_SHIFT=1, LL_ROT_GENERAL=1, SELECT_TYPE_HUD=2;
constexpr int SELECT_ACTION_TYPE_ROTATE=1;
struct LLQuaternion { static constexpr int DEFAULT=0; };
struct Selection { int type=0; int getSelectType() { return type; } };
struct LLSelectMgr {
    int saves=0;
    static LLSelectMgr* getInstance() { static LLSelectMgr mgr; return &mgr; }
    void saveSelectedObjectTransform(int) { ++saves; }
};
struct Agent { int getPosAgentFromGlobal(int p) { return p; } } gAgent;
struct Manip {
    Selection selection;
    Selection* mObjectSelection=&selection;
    int mManipPart=LL_ROT_GENERAL, mRotation=0, mRotationCenter=0;
    int mMouseDown=0, mRadiusMeters=1, applied=0, sphere=0, ring=0;
    bool mAimMode=false, mAimHit=false, hit=true;
    int intersectMouseWithSphere(int x,int,int,int) { return x; }
    bool aimAtCursor(int,int) { mAimHit=hit; if(hit) mRotation=42; return hit; }
    int dragUnconstrained(int x,int) { ++sphere; return x-mMouseDown; }
    int dragConstrained(int,int) { ++ring; return 7; }
    void drag(int x,int y,int mask) {
""" + dispatch + r"""
        ++applied;
    }
};
int main() {
    Manip m;
    m.drag(10,0,0); assert(m.sphere==1 && !m.mAimMode);
    m.drag(10,0,MASK_SHIFT); assert(m.mAimHit && m.mRotation==42);
    int applied=m.applied;
    m.hit=false;
    m.drag(20,0,MASK_SHIFT);
    assert(!m.mAimHit && m.mRotation==42 && m.applied==applied);
    m.drag(20,0,0); assert(!m.mAimMode && m.mRotation==0);
    m.drag(21,0,0); assert(m.mRotation==1);
    assert(LLSelectMgr::getInstance()->saves==2);
    Manip ring; ring.mManipPart=3; ring.drag(10,0,MASK_SHIFT);
    assert(ring.ring==1 && !ring.mAimMode);
    Manip hud; hud.selection.type=SELECT_TYPE_HUD; hud.drag(10,0,MASK_SHIFT);
    assert(hud.sphere==1 && !hud.mAimMode);
}
"""
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / "rotate_aim.cpp"
    exe = Path(directory) / "rotate_aim.exe"
    cpp.write_text(harness)
    subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("Rotation aim transitions, miss retention, axis and HUD guards passed.")
