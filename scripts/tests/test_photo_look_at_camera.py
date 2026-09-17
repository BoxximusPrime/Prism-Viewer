"""Exercise Photo Tools eye overrides and restoration using production quaternion math.

Runs the actual session implementation and the viewer's Euler/quaternion routines.
Avatar lookup, rendering and skeleton storage are test doubles. In-world checks
are still required for the real motion controller, skinning and XUI interaction.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def function(path, signature):
    source = read(path)
    start = source.index(signature)
    return source[start:source.index("\n}", start) + 2] + "\n"


def without_includes(source):
    return re.sub(r'^#include .*$', '', source, flags=re.MULTILINE)


harness = r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include <iostream>
#include <limits>
#include <map>
#include <string>
#include <vector>
using F32=float; using U32=unsigned; using S32=int;
constexpr int VX=0,VY=1,VZ=2,VW=3,VS=3;
constexpr float DEG_TO_RAD=3.14159265358979323846f/180.f;
constexpr float FP_MAG_THRESHOLD=0.0000001f, ONE_PART_IN_A_MILLION=0.000001f;
#define llfinite std::isfinite
#define LL_INFOS(x) std::clog
#define LL_ENDL std::endl
#define LLSINGLETON(T) public: T(); private:
template<class T> struct LLSingleton { static T& instance() { static T v; return v; } };
struct LLUUID {
    int value=0;
    bool notNull() const { return value!=0; }
    void setNull() { value=0; }
    bool operator==(const LLUUID& v) const { return value==v.value; }
};
struct LLVector3 {
    float mV[3];
    LLVector3(float x=0,float y=0,float z=0):mV{x,y,z} {}
    LLVector3(const float* p):mV{p[0],p[1],p[2]} {}
    static const LLVector3 zero;
    static const LLVector3 x_axis;
    bool isFinite() const { return std::isfinite(mV[0])&&std::isfinite(mV[1])&&std::isfinite(mV[2]); }
    void clear() { *this=LLVector3(); }
    float normVec() { float n=std::sqrt(*this * *this); if(n>0)for(float& v:mV) v/=n; return n; }
    float normalize(){return normVec();}
    friend LLVector3 operator-(LLVector3 a,LLVector3 b){return {a.mV[0]-b.mV[0],a.mV[1]-b.mV[1],a.mV[2]-b.mV[2]};}
    LLVector3& operator-=(LLVector3 b) { for(int i=0;i<3;++i)mV[i]-=b.mV[i];return *this; }
    friend float operator*(LLVector3 a,LLVector3 b) { return a.mV[0]*b.mV[0]+a.mV[1]*b.mV[1]+a.mV[2]*b.mV[2]; }
    friend LLVector3 operator*(LLVector3 a,float b) { return {a.mV[0]*b,a.mV[1]*b,a.mV[2]*b}; }
    friend LLVector3 operator+(LLVector3 a,LLVector3 b) { return {a.mV[0]+b.mV[0],a.mV[1]+b.mV[1],a.mV[2]+b.mV[2]}; }
    friend LLVector3 operator%(LLVector3 a,LLVector3 b) { return {a.mV[1]*b.mV[2]-a.mV[2]*b.mV[1],a.mV[2]*b.mV[0]-a.mV[0]*b.mV[2],a.mV[0]*b.mV[1]-a.mV[1]*b.mV[0]}; }
    friend std::ostream& operator<<(std::ostream& s,LLVector3 v) { return s<<v.mV[0]<<","<<v.mV[1]<<","<<v.mV[2]; }
};
const LLVector3 LLVector3::zero;
const LLVector3 LLVector3::x_axis{1,0,0};
struct LLQuaternion {
    float mQ[4];
    LLQuaternion(); LLQuaternion(float,float,float,float);
    bool isFinite() const;
    void shortestArc(const LLVector3&,const LLVector3&);
    void loadIdentity(){mQ[0]=mQ[1]=mQ[2]=0;mQ[3]=1;}
    friend LLQuaternion operator~(const LLQuaternion& q){return {-q.mQ[0],-q.mQ[1],-q.mQ[2],q.mQ[3]};}
    float normalize();
    const LLQuaternion& setEulerAngles(float,float,float);
    const LLQuaternion& setQuat(const float* p) { std::copy(p,p+4,mQ);normalize();return *this; }
};
struct LLMatrix3 {
    float mMatrix[3][3];
    LLMatrix3(float x,float y,float z) { setRot(x,y,z); }
    const LLMatrix3& setRot(float,float,float);
    const LLMatrix3& orthogonalize();
    LLQuaternion quaternion() const;
    void setRows(LLVector3 x,LLVector3 y,LLVector3 z) {
        std::copy(x.mV,x.mV+3,mMatrix[0]); std::copy(y.mV,y.mV+3,mMatrix[1]); std::copy(z.mV,z.mV+3,mMatrix[2]);
    }
};
'''
for path, signatures in [
    ("indra/llmath/llquaternion.h", ["inline LLQuaternion::LLQuaternion(void)",
        "inline LLQuaternion::LLQuaternion(F32 x, F32 y, F32 z, F32 w)",
        "inline bool LLQuaternion::isFinite() const", "inline F32  LLQuaternion::normalize()"]),
    ("indra/llmath/m3math.cpp", ["LLQuaternion    LLMatrix3::quaternion() const",
        "const LLMatrix3&    LLMatrix3::setRot(const F32 roll", "const LLMatrix3&    LLMatrix3::orthogonalize()"]),
    ("indra/llmath/llquaternion.cpp", ["const LLQuaternion& LLQuaternion::setEulerAngles(",
        "LLQuaternion    operator*(const LLQuaternion &a", "LLVector3       operator*(const LLVector3 &a"]),
]:
    for signature in signatures:
        harness += function(path, signature)


harness += function("indra/llmath/llquaternion.cpp", "void LLQuaternion::shortestArc(")
harness += r'''
struct Settings {bool enabled=true;} gSavedSettings;
template<class T> struct LLCachedControl {Settings& s;LLCachedControl(Settings& s,const char*,bool):s(s){}operator T() const{return s.enabled;}};
struct LLFloaterSnapshot {static bool active;static bool photoActive(){return active;}};
bool LLFloaterSnapshot::active=true;
struct {LLVector3 pos{10,3,2};LLVector3 getCameraPositionAgent(){return pos;}} gAgentCamera;
struct LLJoint {
    LLJoint* parent=nullptr;LLVector3 pos;LLQuaternion rot;int writes=0;
    LLJoint* getParent(){return parent;}LLVector3 getWorldPosition(){return pos;}
    LLQuaternion getWorldRotation(){return rot;}LLQuaternion getRotation(){return rot;}
    void setRotation(const LLQuaternion& q){rot=q;++writes;}void updateWorldMatrixChildren(){}
};
const char* const PHOTO_EYE_JOINTS[]={"mEyeLeft","mEyeRight","mFaceEyeAltLeft","mFaceEyeAltRight"};
struct LLVOAvatar {
    std::map<std::string,LLJoint*> joints;LLJoint root;LLJoint* mRoot=&root;
    LLJoint* mPhotoEyeJoints[4]={};LLQuaternion mPhotoEyeRotations[4];
    bool mNeedsSkin=false,mNeedsImpostorUpdate=false,mIsDummy=false,visible=true;
    LLJoint* getJoint(const char* name){return joints[name];}bool isVisible(){return visible;}
    void restorePhotoEyeRotations();void updatePhotoEyeRotations();
};
'''
harness += function("indra/newview/llvoavatar.cpp", "void LLVOAvatar::restorePhotoEyeRotations()")
harness += function("indra/newview/llvoavatar.cpp", "void LLVOAvatar::updatePhotoEyeRotations()")
harness += r'''
void near(LLVector3 a,LLVector3 b){for(int i=0;i<3;++i)assert(std::abs(a.mV[i]-b.mV[i])<.0001f);}
void same(LLQuaternion a,LLQuaternion b){for(int i=0;i<4;++i)assert(std::abs(a.mQ[i]-b.mQ[i])<.0001f);}
int main(){
    LLVOAvatar avatar;LLJoint head;LLJoint eyes[4];LLQuaternion underlying[4];
    head.rot.setEulerAngles(.4f,.7f,1.1f);
    for(int i=0;i<4;++i){
        eyes[i].parent=&head;eyes[i].pos={1,float(i)*.05f,1.8f};
        eyes[i].rot.setEulerAngles(.1f*i,-.2f,.3f);underlying[i]=eyes[i].rot;
        avatar.joints[PHOTO_EYE_JOINTS[i]]=&eyes[i];
    }
    const auto head_rotation=head.rot;
    for(int frame=0;frame<60;++frame){
        avatar.restorePhotoEyeRotations();
        for(int i=0;i<4;++i)same(eyes[i].rot,underlying[i]);
        // Alternate frozen frames with changing animation poses, including higher-priority eyes.
        if(frame%2)for(int i=0;i<4;++i){eyes[i].rot.setEulerAngles(.1f*frame,.2f*i,.5f);underlying[i]=eyes[i].rot;}
        gAgentCamera.pos={float(frame)-30.f,3.f,5.f};
        avatar.updatePhotoEyeRotations();
        for(auto& eye:eyes){LLVector3 aim=gAgentCamera.pos-eye.pos;aim.normalize();near(LLVector3::x_axis*eye.rot*head.rot,aim);}
        same(head.rot,head_rotation);
    }
    assert(avatar.mNeedsSkin && avatar.mNeedsImpostorUpdate);
    avatar.restorePhotoEyeRotations();gSavedSettings.enabled=false;avatar.updatePhotoEyeRotations();
    for(int i=0;i<4;++i)same(eyes[i].rot,underlying[i]);
    gSavedSettings.enabled=true;LLFloaterSnapshot::active=false;avatar.updatePhotoEyeRotations();
    for(int i=0;i<4;++i)assert(!avatar.mPhotoEyeJoints[i]);
    LLFloaterSnapshot::active=true;avatar.mIsDummy=true;avatar.updatePhotoEyeRotations();
    assert(!avatar.mPhotoEyeJoints[0]);avatar.mIsDummy=false;
    avatar.visible=false;avatar.updatePhotoEyeRotations();assert(!avatar.mPhotoEyeJoints[0]);avatar.visible=true;
    // Camera coincident with one eye, absent Bento eye, and orphan joint are safe.
    gAgentCamera.pos=eyes[0].pos;avatar.joints[PHOTO_EYE_JOINTS[2]]=nullptr;eyes[3].parent=nullptr;
    avatar.updatePhotoEyeRotations();assert(!avatar.mPhotoEyeJoints[0] && !avatar.mPhotoEyeJoints[2] && !avatar.mPhotoEyeJoints[3]);
    // Skeleton replacement must never write to the old or replacement joint on restore.
    LLJoint replacement;int writes=eyes[1].writes;avatar.joints[PHOTO_EYE_JOINTS[1]]=&replacement;
    avatar.restorePhotoEyeRotations();assert(eyes[1].writes==writes && replacement.writes==0);
}
'''
with tempfile.TemporaryDirectory(prefix="photo-eyes-") as directory:
    cpp=Path(directory)/"test.cpp";exe=Path(directory)/"test.exe"
    cpp.write_text(harness)
    subprocess.run(["g++","-std=c++17",str(cpp),"-o",str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
source=read("indra/newview/llvoavatar.cpp")
assert "bool detailed_update = updateCharacter(agent);\n    updatePhotoEyeRotations();" in source
assert "bool LLVOAvatar::updateCharacter(LLAgent &agent)\n{\n    restorePhotoEyeRotations();" in source
assert 'gSavedSettings.setBOOL("PhotoLookAtCamera", false);' in function("indra/newview/llfloatersnapshot.cpp","void LLFloaterSnapshot::onClose(bool app_quitting)")
print("PASS: camera aiming with rotated parents, four eye bones, moving camera, 60 frozen/animated frames, pose restoration, closed/disabled/dummy/hidden guards, absent/replaced joints")
