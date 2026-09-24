"""Exercise the production parcel-wall renderer and region dispatch without login.

Run: python scripts/tests/test_parcel_boundary_walls.py (requires g++).
"""
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[2]
source = (root / "indra/newview/llviewerparceloverlay.cpp").read_text()
world = (root / "indra/newview/llworld.cpp").read_text()


def function(text, signature):
    start = text.index(signature)
    opening = text.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


harness = r"""
#include <algorithm>
#include <cassert>
#include <cmath>
#include <list>
#include <vector>
using F32=float; using S32=int; using U8=unsigned char;
constexpr int VX=0,VY=1,VZ=2,GL_TRUE=1,GL_FALSE=0;
constexpr float PARCEL_GRID_STEP_METERS=4;
constexpr U8 PARCEL_WEST_LINE=0x40,PARCEL_SOUTH_LINE=0x80;
#define LL_PROFILE_ZONE_SCOPED
template<class T> T llmin(T a,T b){return std::min(a,b);}
template<class T> T llmax(T a,T b){return std::max(a,b);}
template<class T> T llclamp(T v,T a,T b){return std::clamp(v,a,b);}
struct LLVector3 {
    float mV[3]{};
    LLVector3()=default;
    LLVector3(float x,float y,float z):mV{x,y,z}{}
    LLVector3 operator-(LLVector3 b)const{return {mV[0]-b.mV[0],mV[1]-b.mV[1],mV[2]-b.mV[2]};}
};
float dist_vec_squared2D(LLVector3 a,LLVector3 b){
    return (a.mV[0]-b.mV[0])*(a.mV[0]-b.mV[0])+(a.mV[1]-b.mV[1])*(a.mV[1]-b.mV[1]);
}
struct LLSurface {
    bool slope=false;
    float resolveHeightRegion(float x,float y){return 20+(slope?x+y:0);}
};
struct LLViewerRegion {
    LLVector3 origin; LLSurface land; int draws=0;
    LLVector3 getOriginAgent(){return origin;}
    LLSurface& getLand(){return land;}
    void renderPropertyLines(){++draws;}
};
struct LLViewerCamera {
    LLVector3 position{4,4,1500}; float far=256;
    static LLViewerCamera* getInstance(){static LLViewerCamera c;return &c;}
    LLVector3 getOrigin(){return position;} float getFar(){return far;}
};
struct Agent {LLVector3 position{4,4,1500};LLVector3 getPositionAgent(){return position;}} gAgent;
struct LLGLSUIDefault {};
struct LLGLDepthTest {LLGLDepthTest(int enabled,int write){assert(enabled && !write);}};
struct LLTexUnit {enum {TT_TEXTURE};void unbind(int){}};
struct LLRender {enum {MM_MODELVIEW,TRIANGLES,LINES};};
struct Render {
    LLTexUnit tex; LLVector3 origin; int mode=-1,depth=0; float alpha=0;
    std::vector<LLVector3> triangles,lines;
    LLTexUnit* getTexUnit(int){return &tex;}
    void matrixMode(int){} void pushMatrix(){++depth;} void popMatrix(){--depth;}
    void translatef(float x,float y,float z){origin={x,y,z};}
    void color4f(float,float,float,float a){alpha=a;}
    void begin(int m){assert(mode==-1);mode=m;}
    void end(){mode=-1;}
    void vertex3fv(const float* v){
        assert(mode==LLRender::TRIANGLES || mode==LLRender::LINES);
        assert(alpha==(mode==LLRender::TRIANGLES?.2f:1.f));
        (mode==LLRender::TRIANGLES?triangles:lines).emplace_back(v[0]+origin.mV[0],v[1]+origin.mV[1],v[2]+origin.mV[2]);
    }
    void clear(){assert(!depth && mode==-1);triangles.clear();lines.clear();}
} gGL;
struct LLViewerParcelOverlay {
    LLViewerRegion* mRegion; int mParcelGridsPerEdge=2;
    // One parcel spanning all four cells, with outer west/south flags.
    U8 mOwnership[4]{0xc1,0x81,0x41,0x01};
    void renderPropertyWalls();
};
struct Settings {bool walls=true;} gSavedSettings;
template<class T> struct LLCachedControl {
    LLCachedControl(Settings&,const char*){} operator T()const{return gSavedSettings.walls;}
};
struct LLWorld {
    using region_list_t=std::list<LLViewerRegion*>;
    region_list_t mActiveRegionList,mVisibleRegionList;
    void renderPropertyLines();
};
""" + function(source, "void LLViewerParcelOverlay::renderPropertyWalls()") + function(
    world, "void LLWorld::renderPropertyLines()"
) + r"""
void check_height(float expected){
    assert(!gGL.lines.empty());
    for(auto v:gGL.lines) assert(std::abs(v.mV[VZ]-expected)<.001f);
    for(auto v:gGL.triangles) assert(v.mV[VZ]<=expected);
    assert(gGL.triangles.size()==3*gGL.lines.size());
}
int main(){
    LLViewerRegion region;
    LLViewerParcelOverlay overlay{&region};
    auto* camera=LLViewerCamera::getInstance();
    overlay.renderPropertyWalls();
    check_height(1510);
    assert(gGL.lines.size()==64); // 32 metres of perimeter, no internal seams
    for(auto v:gGL.lines) assert(v.mV[0]==0||v.mV[0]==8||v.mV[1]==0||v.mV[1]==8);

    // A real internal boundary appears exactly once and the altitude follows live.
    overlay.mOwnership[1]|=PARCEL_WEST_LINE;
    overlay.mOwnership[3]|=PARCEL_WEST_LINE;
    gAgent.position.mV[VZ]=3000;
    gGL.clear();overlay.renderPropertyWalls();check_height(3010);
    assert(gGL.lines.size()==80);

    // Free-camera altitude must not change the avatar-based ceiling.
    camera->position.mV[VZ]=4000;
    gGL.clear();overlay.renderPropertyWalls();check_height(3010);

    // Heights are converted from agent to region coordinates, including neighbours.
    region.origin={256,512,100};camera->position={260,516,1500};
    gAgent.position={260,516,1500};
    gGL.clear();overlay.renderPropertyWalls();check_height(1510);
    for(auto v:gGL.lines)assert(v.mV[0]>=256&&v.mV[0]<=264&&v.mV[1]>=512&&v.mV[1]<=520);

    // Low avatars and terrain slopes still get walls above terrain at every sample.
    region.origin={};region.land.slope=true;camera->position={4,4,0};gAgent.position={4,4,0};
    gGL.clear();overlay.renderPropertyWalls();
    for(auto v:gGL.lines)assert(v.mV[VZ]==30+v.mV[VX]+v.mV[VY]);

    // Draw distance uses XY, never the 1500-metre drop to terrain.
    camera->position={4,4,1500};gAgent.position.mV[VZ]=1500;camera->far=4;
    gGL.clear();overlay.renderPropertyWalls();check_height(1510);
    assert(gGL.lines.size()==16);
    camera->position={400,4,1500};camera->far=1024;
    gGL.clear();overlay.renderPropertyWalls();assert(gGL.lines.empty()&&gGL.triangles.empty());

    // Regions culled because their terrain is offscreen still dispatch walls.
    LLViewerRegion other;LLWorld world;
    world.mActiveRegionList={&region,&other};world.mVisibleRegionList={&other};
    world.renderPropertyLines();assert(region.draws==1&&other.draws==1);
    gSavedSettings.walls=false;
    world.renderPropertyLines();assert(region.draws==1&&other.draws==2);
}
"""

settings = ET.parse(root / "indra/newview/app_settings/settings.xml").getroot().find("map")
entries = list(settings)
wall_setting = next(entries[i + 1] for i, item in enumerate(entries) if item.text == "ShowParcelBoundaryWalls")
values = list(wall_setting)
config = {values[i].text: values[i + 1].text for i in range(0, len(values), 2)}
assert config["Type"] == "Boolean" and config["Persist"] == "1" and config["Value"] == "0"
menu = ET.parse(root / "indra/newview/skins/default/xui/en/menu_viewer.xml")
item = menu.find(".//menu[@name='LandShow']/menu_item_check[@name='Parcel Boundary Walls']")
assert item.find("menu_item_check.on_check").get("control") == "ShowParcelBoundaryWalls"
assert item.find("menu_item_check.on_click").get("parameter") == "ShowParcelBoundaryWalls"
build = ET.parse(root / "indra/newview/skins/default/xui/en/floater_tools.xml")
checkbox = build.find("./check_box[@name='checkbox parcel walls']")
assert checkbox.get("control_name") == "ShowParcelBoundaryWalls"
assert int(checkbox.get("top")) + int(checkbox.get("height")) <= int(build.find("./tab_container").get("top"))
dispatch = function(source, "void LLViewerParcelOverlay::renderPropertyLines()")
assert dispatch.index("if (show_walls)") < dispatch.index("if (!show)")

with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / "parcel_walls.cpp"
    exe = Path(directory) / "parcel_walls.exe"
    cpp.write_text(harness)
    subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("Parcel walls: altitude, terrain, shared edges, region offsets, XY culling, region dispatch, and menu/settings passed.")
