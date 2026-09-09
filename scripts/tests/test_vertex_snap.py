"""Exercise production vertex-drag dispatch with deterministic scene/transform stand-ins.
Run: python scripts/tests/test_vertex_snap.py (requires g++).
"""
from pathlib import Path
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[2] / "indra/newview/llmaniptranslate.cpp").read_text()
start = source.index("    if (hasMouseCapture() && mVertexDrag)")
end = source.index("    // Translation tool only works", start)
harness = r"""
#include <cassert>
using F32=float;
struct Vec {
    double x=0,y=0,z=0;
    Vec operator+(Vec b) const {return {x+b.x,y+b.y,z+b.z};}
    Vec operator-(Vec b) const {return {x-b.x,y-b.y,z-b.z};}
    double lengthSquared() const {return x*x+y*y+z*z;}
};
using LLVector3=Vec; using LLVector3d=Vec;
struct LLViewerObject {virtual ~LLViewerObject()=default;};
struct LLVOVolume: LLViewerObject {Vec volumePositionToAgent(Vec v){return v;}};
template<class T> struct LLPointer {T* p=nullptr; T* get(){return p;}};
struct Agent {Vec getPosGlobalFromAgent(Vec v){return v+Vec{100000,200000,0};}} gAgent;
struct Settings {bool limited=false; float getF32(const char*){return 10;} bool getBOOL(const char*){return limited;}} gSavedSettings;
struct Window {void setCursor(int){}} window;
auto* gViewerWindow=&window; constexpr int UI_CURSOR_TOOLTRANSLATE=0;
struct LLViewerCamera {static LLViewerCamera* getInstance(){static LLViewerCamera c;return &c;} Vec getAtAxis(){return {0,0,1};}};
struct Manip {
    bool mVertexDrag=true,mVertexTarget=false,held=true,allowed=true,exists=true;
    bool hit=true,plane=true,clamp=false,capture=true;
    Vec mVertexStart{100001,200002,3},mVertexDestination,current=mVertexStart;
    Vec target{8,6,9},free_point{100004,200003,3};
    Vec delta; int writes=0;
    bool hasMouseCapture(){return capture;} bool vertexSnapHeld(){return held;}
    bool canAffectSelection(){return allowed;}
    bool vertexPoint(Vec& p){p=current; return exists;}
    bool findVertex(int,int,bool,LLPointer<LLViewerObject>& p,Vec& v){static LLVOVolume obj;p.p=&obj;v=target;return hit;}
    bool getMousePointOnPlaneGlobal(Vec& p,int,int,Vec,Vec){p=free_point;return plane;}
    void applyTranslation(Vec d){delta=d;++writes;current=mVertexStart+d;if(clamp)current.z-=1;}
    bool hover(int x=0,int y=0) {
""" + source[start:end] + r"""
        return false;
    }
};
int main() {
    Manip m;
    assert(m.hover() && m.mVertexTarget);
    assert((m.delta-Vec{7,4,6}).lengthSquared()<1e-12);
    m.hover(); assert(m.writes==2 && (m.delta-Vec{7,4,6}).lengthSquared()<1e-12);
    m.hit=false;m.hover();assert(!m.mVertexTarget && (m.current-m.free_point).lengthSquared()<1e-12);
    int writes=m.writes;m.plane=false;m.hover();assert(m.writes==writes);
    m.hit=true;m.held=false;m.hover();assert(m.writes==writes && !m.mVertexTarget);
    m.held=true;m.allowed=false;m.hover();assert(m.writes==writes);
    m.allowed=true;m.exists=false;m.hover();assert(m.writes==writes);
    m.exists=true;gSavedSettings.limited=true;m.target={30,30,30};m.hover();assert(m.writes==writes);
    m.target={2,3,4};m.hover();assert(m.writes==writes+1 && m.mVertexTarget);
    m.clamp=true;m.hover();assert(!m.mVertexTarget);
    m.mVertexDrag=false;assert(!m.hover());
}
"""
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / "vertex_snap.cpp"
    exe = Path(directory) / "vertex_snap.exe"
    cpp.write_text(harness)
    subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("Vertex offsets, repeated snaps, free dragging, release, permissions, missing source and limits passed.")
