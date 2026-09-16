"""Exercise production Shift-snap policy and transform math. Run with Python + g++."""
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[2]
base = (root / "indra/newview/llmanip.cpp").read_text()
move = (root / "indra/newview/llmaniptranslate.cpp").read_text()
scale = (root / "indra/newview/llmanipscale.cpp").read_text()
rotate = (root / "indra/newview/llmaniprotate.cpp").read_text()


def between(text, start, end, offset=0):
    a = text.index(start, offset)
    return text[a:text.index(end, a)]


policy = between(base, "bool LLManip::updateSnapMode", "bool LLManip::getMousePointOnPlaneAgent")
move_math = between(move, "    F64 axis_magnitude =", "    // Clamp to arrow direction")
corner_math = between(scale, "    bool snap_enabled = isSnapEnabled();", "    F32 max_scale_factor")
face_math = between(scale, "    bool snap_enabled = isSnapEnabled();", "    LLVector3 dir_agent;", scale.index("void LLManipScale::dragFace"))
rotation_math = between(rotate, "    if (mTemporarySnap)", "    bool damped =")
rotation_precision = between(rotate, "    if (!mTemporarySnap)", "    return LLQuaternion( angle, constraint_axis );")
copy_condition = re.search(r"if \((mask == MASK_COPY[^\n]+)\)", move)[1]
move_stationary = re.search(r"if\( (x == mLastHoverMouseX[^\n]+)\)", move)[1]
scale_refresh = between(scale, "    if (updateSnapMode(mask))", "    if( hasMouseCapture() )")

harness = r"""
#include <cassert>
#include <cmath>
#include <algorithm>
#include <string>
using F32=float; using F64=double; using S32=int; using MASK=int;
constexpr int MASK_NONE=0,MASK_SHIFT=1,MASK_CONTROL=2,MASK_ALT=4,MASK_COPY=MASK_SHIFT;
enum {LL_NO_PART,LL_X_ARROW,LL_Y_ARROW,LL_Z_ARROW,LL_YZ_PLANE,LL_XZ_PLANE,LL_XY_PLANE,LL_TRANSLATE_CENTER,LL_ROT_GENERAL,LL_ROT_Z,LL_FACE_POSX,LL_CORNER_PPP};
constexpr int VX=0,VY=1,VZ=2;
constexpr float DEG_TO_RAD=3.14159265358979323846f/180, SNAP_ANGLE_INCREMENT=5.625f;
enum ESnapRegimes {SNAP_REGIME_NONE=0,SNAP_REGIME_UPPER=1,SNAP_REGIME_LOWER=2};
template<class T> T llclamp(T a,T lo,T hi){return std::clamp(a,lo,hi);}
float llabs(float a){return std::abs(a);} float ll_round(float a,float step){return std::floor(a/step+.5f)*step;}
struct Vec {
    float mV[3]{}; Vec()=default; Vec(float x,float y,float z):mV{x,y,z}{}
    Vec operator+(Vec b)const{return {mV[0]+b.mV[0],mV[1]+b.mV[1],mV[2]+b.mV[2]};}
    Vec operator-(Vec b)const{return {mV[0]-b.mV[0],mV[1]-b.mV[1],mV[2]-b.mV[2]};}
    Vec operator*(float s)const{return {mV[0]*s,mV[1]*s,mV[2]*s};}
    float operator*(Vec b)const{return mV[0]*b.mV[0]+mV[1]*b.mV[1]+mV[2]*b.mV[2];}
    Vec operator%(Vec b)const{return {mV[1]*b.mV[2]-mV[2]*b.mV[1],mV[2]*b.mV[0]-mV[0]*b.mV[2],mV[0]*b.mV[1]-mV[1]*b.mV[0]};}
    Vec& operator-=(Vec b){return *this=*this-b;} Vec& operator*=(float s){return *this=*this*s;}
    float normVec(){float n=std::sqrt(*this * *this);if(n)*this*=1/n;return n;}
    void scaleVec(Vec b){for(int i=0;i<3;++i)mV[i]*=b.mV[i];}
    void abs(){for(auto& v:mV)v=std::abs(v);} void rotVec(int){} void setVec(Vec v){*this=v;} void set(Vec v){*this=v;}
};
Vec operator*(Vec v,int){return v;} // identity grid rotation in these scenes
Vec operator*(float s,Vec v){return v*s;}
using LLVector3=Vec; using LLVector3d=Vec;
Vec projected_vec(Vec a,Vec b){return b*(a*b);}
float dist_vec(Vec a,Vec b){return (a-b).normVec();}
bool near(float a,float b){return std::abs(a-b)<.00001f;}
struct LLQuaternion {
    float angle=0; Vec axis{0,0,1}; LLQuaternion()=default; LLQuaternion(float a,Vec v):angle(a),axis(v){}
    void getAngleAxis(float* a,Vec& v){*a=angle;v=axis;}
};
struct Settings {bool snap=false; bool getBOOL(const char*){return snap;} float getF32(const char*){return 1.f;}} gSavedSettings;
struct Agent {Vec getPosAgentFromGlobal(Vec p){return p;}} gAgent;
struct LLViewerCamera {static LLViewerCamera* getInstance(){static LLViewerCamera c;return &c;} Vec getAtAxis(){return {1,1,1};}};
struct LLManip {
    bool mTemporarySnap=false,capture=true,mInSnapRegime=false; int mManipPart=LL_X_ARROW,grid_updates=0;
    bool hasMouseCapture(){return capture;} void updateGridSettings(){++grid_updates;}
    bool updateSnapMode(MASK); bool isSnapEnabled() const;
};
""" + policy + r"""
struct Manip:LLManip {
    Vec mGridOrigin,mGridScale{1,1,1},mSnapOffsetAxis{0,1,0},mManipNormal{0,0,1}; int mGridRotation=0;
    Vec mDragSelectionStartGlobal,mDragCursorStartGlobal,plane_point;
    float mSubdivisions=4,mSnapOffsetMeters=1,mScaleSnapUnit1=1,mScaleSnapUnit2=2,mScaleSnappedValue=0;
    float mTickPixelSpacing1=1,mTickPixelSpacing2=1,mSnapRegimeOffset=1;
    Vec mScaleDir{1,0,0},mScaleCenter,mSnapGuideDir1{0,1,0},mSnapGuideDir2{0,-1,0};
    ESnapRegimes mSnapRegime=SNAP_REGIME_NONE;
    static constexpr float sGridMinSubdivisionLevel=1,sGridMaxSubdivisionLevel=32;
    float getMinGridScale(){return 1;}
    Vec getPivotPoint(){return {};}
    float getSubdivisionLevel(Vec,Vec,float,int=0){return 4;}
    bool getMousePointOnPlaneGlobal(Vec& p,int,int,Vec,Vec){p=plane_point;return true;}
    float moveAxis(float distance){
        bool axis_exists=mManipPart<=LL_Z_ARROW; int x=0,y=0;
        Vec relative_move{distance,0,0},axis_d{1,0,0},axis_f=axis_d,current_pos_global;
        plane_point={distance,distance,distance};
""" + move_math + r"""
        return axis_exists ? axis_magnitude : relative_move.mV[VX];
    }
    float scaleCorner(float distance,bool uniform=true,float upper=0,float lower=0){
        Vec projected_drag_pos1{distance,0,0},projected_drag_pos2{distance,0,0};
        Vec mouse_on_plane1{distance,upper,0},mouse_on_plane2{distance,-lower,0};
        Vec drag_start_point_agent{1,0,0},drag_start_center_agent;
        float min_scale=.1f,max_scale=10.f,scale_factor=1.f,t=distance;
""" + corner_math + r"""
        return scale_factor;
    }
    float scaleFace(float distance,bool uniform=true,float offset=0){
        float dist_from_scale_line=offset,dist_along_scale_line=distance,min_drag_dist=.1f,max_drag_dist=10.f;
        Vec scale_center_to_mouse{distance,offset,0},drag_start_point_agent{1,0,0};
        Vec drag_delta{(distance-1)*(uniform?2.f:1.f),0,0};
""" + face_math + r"""
        return drag_delta.mV[0];
    }
    float rotateAngle(float degrees,bool constrained){
        F32 angle=degrees*DEG_TO_RAD;
        if(constrained){
""" + rotation_precision + r"""
        }
        LLQuaternion mRotation(angle,{0,0,1}); bool mSmoothRotate=true;
""" + rotation_math + r"""
        return mRotation.angle/DEG_TO_RAD;
    }
    bool shouldCopy(MASK mask){return """ + copy_condition + r""";}
    bool suppressMove(int x,int y,bool snap_mode_changed){
        int mLastHoverMouseX=10,mLastHoverMouseY=20; bool rotated=false;
        return """ + move_stationary + r""";
    }
    bool refreshScale(MASK mask){
        int mLastMouseX=10,mLastMouseY=20;
""" + scale_refresh + r"""
        return mLastMouseX==-1 && mLastMouseY==-1;
    }
};
int main(){
    Manip m;
    const int parts[]={LL_NO_PART,LL_TRANSLATE_CENTER,LL_X_ARROW,LL_XY_PLANE,LL_ROT_GENERAL,LL_ROT_Z,LL_FACE_POSX,LL_CORNER_PPP};
    for(bool saved:{false,true})for(bool capture:{false,true})for(int part:parts)for(int mask=0;mask<8;++mask){
        gSavedSettings.snap=saved;m.capture=capture;m.mManipPart=part;
        bool before=m.mTemporarySnap;
        bool expected=!saved&&capture&&mask==MASK_SHIFT&&part!=LL_NO_PART&&part!=LL_TRANSLATE_CENTER;
        assert(m.updateSnapMode(mask)==(before!=expected));
        assert(m.mTemporarySnap==expected && m.isSnapEnabled()==(saved||expected));
        assert(gSavedSettings.snap==saved); // no checkbox/persisted-setting mutation
    }
    m.capture=true;m.mManipPart=LL_X_ARROW;gSavedSettings.snap=false;m.updateSnapMode(0);
    assert(near(m.moveAxis(1.13f),1.13f));
    assert(m.updateSnapMode(MASK_SHIFT));
    assert(!m.shouldCopy(MASK_SHIFT));
    for(float d:{-2.12f,-1.13f,-.26f,.13f,1.13f,2.12f})assert(near(m.moveAxis(d),ll_round(d,.25f)));
    m.mManipPart=LL_XY_PLANE;assert(near(m.moveAxis(1.13f),1.25f));
    m.mManipPart=LL_X_ARROW;m.updateSnapMode(0);assert(near(m.moveAxis(1.13f),1.13f));
    assert(m.suppressMove(10,20,false)&&!m.suppressMove(10,20,true));
    gSavedSettings.snap=true;m.updateSnapMode(MASK_SHIFT);assert(m.shouldCopy(MASK_SHIFT));
    gSavedSettings.snap=false;m.mManipPart=LL_CORNER_PPP;
    assert(m.refreshScale(MASK_SHIFT));assert(!m.refreshScale(MASK_SHIFT));
    assert(near(m.scaleCorner(1.13f),1.25f));assert(near(m.scaleCorner(2.6f,false),1.25f));
    assert(m.refreshScale(0));assert(near(m.scaleCorner(1.13f),1.13f));
    gSavedSettings.snap=true;m.updateSnapMode(0);
    assert(near(m.scaleCorner(1.13f),1.13f)); // saved snapping still needs a ruler
    assert(near(m.scaleCorner(1.13f,true,2),1.25f));
    assert(near(m.scaleCorner(1.13f,true,0,2),1.f)); // lower ruler uses its own step
    gSavedSettings.snap=false;m.mManipPart=LL_FACE_POSX;m.updateSnapMode(MASK_SHIFT);
    assert(near(m.scaleFace(1.13f),.5f));assert(near(m.scaleFace(1.13f,false),.25f));
    assert(near(m.scaleFace(11.f),9.f));assert(near(m.scaleFace(.05f),-.9f));
    m.updateSnapMode(0);assert(near(m.scaleFace(1.13f),.26f));
    m.mManipPart=LL_ROT_Z;m.updateSnapMode(MASK_SHIFT);
    for(bool constrained:{false,true})for(float angle:{-170.f,-45.f,-2.9f,0.f,2.7f,2.9f,44.f,170.f})
        assert(near(m.rotateAngle(angle,constrained),ll_round(angle,5.625f)));
    m.updateSnapMode(0);assert(near(m.rotateAngle(2.9f,true),2.f));assert(near(m.rotateAngle(2.9f,false),2.9f));
    m.mManipPart=LL_TRANSLATE_CENTER;m.updateSnapMode(MASK_SHIFT);assert(!m.mTemporarySnap);
}
"""

ET.parse(root / "indra/newview/skins/default/xui/en/floater_tools.xml")
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / "shift_snap.cpp"
    exe = Path(directory) / "shift_snap.exe"
    cpp.write_text(harness)
    subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("Shift snap: 256 modifier/context cases, signed grid moves, planar moves, both scale rulers, clamps, rotation steps, copy conflict and stationary modifier changes passed.")
