"""Exercise production Pose Studio lifecycle and quaternion math with a small avatar.

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
    bool isFinite() const { return std::isfinite(mV[0])&&std::isfinite(mV[1])&&std::isfinite(mV[2]); }
    void clear() { *this=LLVector3(); }
    void normVec() { float n=std::sqrt(*this * *this); for(float& v:mV) v/=n; }
    LLVector3& operator-=(LLVector3 b) { for(int i=0;i<3;++i)mV[i]-=b.mV[i];return *this; }
    friend float operator*(LLVector3 a,LLVector3 b) { return a.mV[0]*b.mV[0]+a.mV[1]*b.mV[1]+a.mV[2]*b.mV[2]; }
    friend LLVector3 operator*(LLVector3 a,float b) { return {a.mV[0]*b,a.mV[1]*b,a.mV[2]*b}; }
    friend LLVector3 operator+(LLVector3 a,LLVector3 b) { return {a.mV[0]+b.mV[0],a.mV[1]+b.mV[1],a.mV[2]+b.mV[2]}; }
    friend LLVector3 operator%(LLVector3 a,LLVector3 b) { return {a.mV[1]*b.mV[2]-a.mV[2]*b.mV[1],a.mV[2]*b.mV[0]-a.mV[0]*b.mV[2],a.mV[0]*b.mV[1]-a.mV[1]*b.mV[0]}; }
    friend std::ostream& operator<<(std::ostream& s,LLVector3 v) { return s<<v.mV[0]<<","<<v.mV[1]<<","<<v.mV[2]; }
};
const LLVector3 LLVector3::zero;
struct LLQuaternion {
    float mQ[4];
    LLQuaternion(); LLQuaternion(float,float,float,float);
    bool isFinite() const;
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

harness += r'''
struct LLJoint {
    std::string name; LLJoint* parent=nullptr;
    LLVector3 pos,scale{1,1,1}; LLQuaternion rot;
    int writes=0, world_updates=0;
    const std::string& getName() const { return name; }
    LLVector3 getPosition() { return pos; } LLVector3 getScale() { return scale; }
    LLQuaternion getRotation() { return rot; }
    void setPosition(LLVector3 v) {pos=v;++writes;} void setScale(LLVector3 v) {scale=v;++writes;}
    void setRotation(LLQuaternion v) {rot=v;++writes;}
    void updateWorldMatrixChildren() {++world_updates;}
    LLQuaternion worldRotation() { return parent ? rot*parent->worldRotation() : rot; }
    LLVector3 worldPosition() { return parent ? pos*parent->worldRotation()+parent->worldPosition() : pos; }
};
struct LLViewerObject { virtual ~LLViewerObject()=default; };
struct LLVOAvatar : LLViewerObject {
    LLUUID id{1}; bool self=true,dead=false,built=true,appearance=false; unsigned serial=1;
    LLJoint root{"root"}; std::vector<LLJoint*> joints;
    bool mNeedsImpostorUpdate=false; int dirties=0;
    bool isSelf() const {return self;} bool isDead() const {return dead;} bool isBuilt() const {return built;}
    bool getIsAppearanceAnimating() const {return appearance;}
    LLUUID getID() const {return id;} LLJoint* getRootJoint() {return &root;}
    size_t getSkeletonJointCount() const {return joints.size();} LLJoint* getSkeletonJoint(int i) {return joints.at(i);}
    unsigned getSkeletonSerialNum() const {return serial;} void dirtyMesh() {++dirties;}
};
struct { std::map<int,LLViewerObject*> objects; LLViewerObject* findObject(LLUUID id) {return objects[id.value];} } gObjectList;
'''
harness += without_includes(read("indra/newview/llposestudio.h"))
harness += without_includes(read("indra/newview/llposestudio.cpp"))
harness += r'''
void near(LLVector3 a,LLVector3 b) { for(int i=0;i<3;++i)assert(std::abs(a.mV[i]-b.mV[i])<0.0001f); }
void same(LLQuaternion a,LLQuaternion b) { for(int i=0;i<4;++i)assert(std::abs(a.mQ[i]-b.mQ[i])<0.0001f); }
LLQuaternion rotation(float x,float y,float z) { LLQuaternion q;q.setEulerAngles(x*DEG_TO_RAD,y*DEG_TO_RAD,z*DEG_TO_RAD);return q; }
int main() {
    LLPoseStudio studio;
    LLVOAvatar avatar;
    LLJoint pelvis{"mPelvis",&avatar.root}, shoulder{"mShoulderLeft",&pelvis}, elbow{"mElbowLeft",&shoulder}, wrist{"mWristLeft",&elbow};
    elbow.pos=wrist.pos={1,0,0};
    pelvis.rot=rotation(0,0,90); shoulder.rot=rotation(90,0,0);
    const auto base=shoulder.rot;
    avatar.joints={&pelvis,&shoulder,&elbow,&wrist};gObjectList.objects[1]=&avatar;
    avatar.self=false;assert(!studio.begin(avatar));avatar.self=true;
    avatar.built=false;assert(!studio.begin(avatar));avatar.built=true;
    avatar.appearance=true;assert(!studio.begin(avatar));avatar.appearance=false;
    shoulder.pos.mV[0]=std::numeric_limits<float>::quiet_NaN();assert(!studio.begin(avatar));shoulder.pos.clear();
    assert(studio.begin(avatar));assert(!studio.begin(avatar));
    assert(!studio.setRotationOffset("missing",{0,0,90}));
    assert(!studio.setRotationOffset("mShoulderLeft",{0,0,std::numeric_limits<float>::infinity()}));
    assert(studio.setRotationOffset("mShoulderLeft",{0,0,90}));
    assert(!studio.setPositionOffset("missing",{0,0,0}));
    assert(!studio.setPositionOffset("mShoulderLeft",{std::numeric_limits<float>::infinity(),0,0}));
    assert(studio.setPositionOffset("mShoulderLeft",{0.25f,-0.5f,0.75f}));
    studio.afterUpdate(avatar);
    // Local delta is applied BEFORE a nonidentity base and parent rotation.
    near(elbow.pos,{1,0,0});same(elbow.rot,LLQuaternion());
    near(shoulder.pos,{0.25f,-0.5f,0.75f});
    const auto held=shoulder.rot;
    // Repeat frames, including frozen frames and a changing underlying animation.
    LLQuaternion underneath=base;
    for(int frame=0;frame<100;++frame) {
        studio.beforeUpdate(avatar);same(shoulder.rot,underneath);
        const int writes=shoulder.writes;studio.beforeUpdate(avatar);assert(writes==shoulder.writes);
        if(frame%2) { underneath=rotation(float(frame),20,30);shoulder.rot=underneath; }
        studio.afterUpdate(avatar);same(shoulder.rot,held);
        near(wrist.worldPosition(),{0.5f,0.25f,2.75f});
    }
    studio.resetJoint("mShoulderLeft");studio.beforeUpdate(avatar);studio.afterUpdate(avatar);same(shoulder.rot,base);near(shoulder.pos,{0,0,0});
    studio.setRotationOffset("mPelvis",{0,0,-90});studio.beforeUpdate(avatar);studio.afterUpdate(avatar);
    near(wrist.worldPosition(),{2,0,0});
    studio.resetPose();studio.beforeUpdate(avatar);studio.afterUpdate(avatar);near(wrist.worldPosition(),{0,2,0});
    studio.setRotationOffset("mShoulderLeft",{0,0,45});studio.beforeUpdate(avatar);studio.afterUpdate(avatar);
    studio.end();same(shoulder.rot,base);assert(!studio.isActive());assert(avatar.dirties==1);
    // No motion evaluation is needed for restoration with freeze still enabled.
    auto restored=shoulder.rot;studio.afterUpdate(avatar);same(shoulder.rot,restored);
    int writes=shoulder.writes;studio.end();assert(writes==shoulder.writes);
    // Appearance changes after unapplying must not restore stale scale values.
    assert(studio.begin(avatar));studio.afterUpdate(avatar);studio.beforeUpdate(avatar);
    shoulder.scale={2,3,4};++avatar.serial;studio.afterUpdate(avatar);
    assert(!studio.isActive());near(shoulder.scale,{2,3,4});same(shoulder.rot,base);
    assert(studio.getEndReason()==LLPoseStudio::EndReason::SKELETON_CHANGED);
    // Same-size skeleton replacement: check identity before touching old joints.
    assert(studio.begin(avatar)); LLJoint replacement{"mShoulderLeft"};avatar.joints[1]=&replacement;
    writes=shoulder.writes;studio.afterUpdate(avatar);assert(!studio.isActive());assert(writes==shoulder.writes);assert(replacement.writes==0);
    avatar.joints[1]=&shoulder;
    assert(studio.begin(avatar));studio.afterUpdate(avatar);
    LLVOAvatar other;other.id={2};other.joints=avatar.joints;
    writes=shoulder.writes;studio.beforeUpdate(other);studio.afterUpdate(other);assert(writes==shoulder.writes);
    studio.endForAvatar(other,LLPoseStudio::EndReason::TARGET_LOST);assert(studio.isActive());
    studio.endForAvatar(avatar,LLPoseStudio::EndReason::TELEPORT);assert(!studio.isActive());same(shoulder.rot,base);
    assert(studio.begin(avatar));studio.afterUpdate(avatar);writes=shoulder.writes;
    studio.endForAvatar(avatar,LLPoseStudio::EndReason::TARGET_LOST,false);assert(writes==shoulder.writes);assert(!studio.isActive());
    assert(studio.begin(avatar));gObjectList.objects.erase(1);writes=shoulder.writes;
    studio.end();assert(!studio.isActive());assert(writes==shoulder.writes);
    std::cout<<"PASS: capture, local rotation/descendants, 100 animation/freeze frames, resets, exact restoration, stale skeleton and target lifecycle\n";
}
'''

avatar_source = read("indra/newview/llvoavatar.cpp")
update = function("indra/newview/llvoavatar.cpp", "bool LLVOAvatar::updateCharacter(")
assert update.index("beforeUpdate(*this)") < update.index("updateMotions(")
assert update.rindex("updateMotions(") < update.index("afterUpdate(*this)") < update.index("updateHeadOffset()")
for path, text in [
    ("indra/newview/llagent.cpp", "LLPoseStudio::EndReason::TELEPORT"),
    ("indra/newview/llappviewer.cpp", "LLPoseStudio::EndReason::DISCONNECTED"),
]:
    assert text in read(path)
menu = ET.fromstring(read("indra/newview/skins/default/xui/en/menu_viewer.xml"))
assert menu.find(".//menu[@name='Avatar']/menu_item_call[@name='Pose Studio']/menu_item_call.on_click").get("parameter") == "pose_studio"
ui = ET.fromstring(read("indra/newview/skins/default/xui/en/floater_pose_studio.xml"))
names = [element.get("name") for element in ui.iter() if element.get("name")]
assert len(names) == len(set(names))
for field in ("position_x", "position_y", "position_z"):
    assert ui.find(f".//slider[@name='{field}']") is not None
assert int(ui.get("height")) > int(ui.find(".//slider[@name='rotation_z']").get("top"))

with tempfile.TemporaryDirectory(prefix="pose-studio-test-") as temp:
    cpp, exe = Path(temp)/"pose_studio.cpp", Path(temp)/"pose_studio.exe"
    cpp.write_text(harness, encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", "-O1", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("PASS: update ordering, teleport/disconnect wiring and XUI/menu structure")
