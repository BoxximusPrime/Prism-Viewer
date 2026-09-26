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
#include <array>
#include <cassert>
#include <cmath>
#include <functional>
#include <iostream>
#include <limits>
#include <map>
#include <string>
#include <vector>
using F32=float; using U32=unsigned; using S32=int;
constexpr int VX=0,VY=1,VZ=2,VW=3,VS=3;
constexpr float DEG_TO_RAD=3.14159265358979323846f/180.f;
constexpr float F_PI=3.14159265358979323846f, F_PI_BY_TWO=F_PI/2, RAD_TO_DEG=180.f/F_PI, GIMBAL_THRESHOLD=0.000436f;
constexpr float F_TWO_PI=2.f*F_PI;
constexpr float FP_MAG_THRESHOLD=0.0000001f, ONE_PART_IN_A_MILLION=0.000001f;
#define LL_RELEASE 1
template<class T> T llmin(T a,T b){return std::min(a,b);}
template<class T> T llmax(T a,T b){return std::max(a,b);}
template<class T> T llclamp(T a,T b,T c){return std::clamp(a,b,c);}
#define llfinite std::isfinite
#define LL_INFOS(x) std::clog
#define LL_ENDL std::endl
#define LLSINGLETON(T) public: T(); private:
template<class T> struct LLSingleton {
    static T& instance() { static T v; return v; }
    static T* getInstance(){return &instance();}
    static bool instanceExists(){return true;}
};
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
    static const LLVector3 y_axis,z_axis;
    bool isFinite() const { return std::isfinite(mV[0])&&std::isfinite(mV[1])&&std::isfinite(mV[2]); }
    void clear() { *this=LLVector3(); }
    float normVec() { float n=std::sqrt(*this * *this); if(n>FP_MAG_THRESHOLD)for(float& v:mV) v/=n;else clear();return n; }
    float normalize(){return normVec();}
    float lengthSquared() const {return *this * *this;}
    float length() const {return std::sqrt(lengthSquared());}
    float magVec() const {return length();}
    float magVecSquared() const {return lengthSquared();}
    void setVec(float x,float y,float z){*this={x,y,z};}
    LLVector3& operator*=(float f){for(float& v:mV)v*=f;return *this;}
    friend LLVector3 operator-(LLVector3 a,LLVector3 b){return {a.mV[0]-b.mV[0],a.mV[1]-b.mV[1],a.mV[2]-b.mV[2]};}
    LLVector3& operator-=(LLVector3 b) { for(int i=0;i<3;++i)mV[i]-=b.mV[i];return *this; }
    friend float operator*(LLVector3 a,LLVector3 b) { return a.mV[0]*b.mV[0]+a.mV[1]*b.mV[1]+a.mV[2]*b.mV[2]; }
    friend LLVector3 operator*(LLVector3 a,float b) { return {a.mV[0]*b,a.mV[1]*b,a.mV[2]*b}; }
    friend LLVector3 operator+(LLVector3 a,LLVector3 b) { return {a.mV[0]+b.mV[0],a.mV[1]+b.mV[1],a.mV[2]+b.mV[2]}; }
    friend LLVector3 operator%(LLVector3 a,LLVector3 b) { return {a.mV[1]*b.mV[2]-a.mV[2]*b.mV[1],a.mV[2]*b.mV[0]-a.mV[0]*b.mV[2],a.mV[0]*b.mV[1]-a.mV[1]*b.mV[0]}; }
    friend std::ostream& operator<<(std::ostream& s,LLVector3 v) { return s<<v.mV[0]<<","<<v.mV[1]<<","<<v.mV[2]; }
};
const LLVector3 LLVector3::zero;
const LLVector3 LLVector3::y_axis{0,1,0},LLVector3::z_axis{0,0,1};
struct LLQuaternion {
    float mQ[4];
    LLQuaternion(); LLQuaternion(float,float,float,float);
    LLQuaternion(float,const LLVector3&);
    const LLQuaternion& setQuat(float,const LLVector3&);
    void shortestArc(const LLVector3&,const LLVector3&);
    void getEulerAngles(float*,float*,float*) const;
    void loadIdentity(){mQ[0]=mQ[1]=mQ[2]=0;mQ[3]=1;}
    friend LLQuaternion operator~(const LLQuaternion& q){return {-q.mQ[0],-q.mQ[1],-q.mQ[2],q.mQ[3]};}
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
        "LLQuaternion    operator*(const LLQuaternion &a", "LLVector3       operator*(const LLVector3 &a",
        "LLQuaternion::LLQuaternion(F32 angle, const LLVector3 &vec)",
        "const LLQuaternion& LLQuaternion::setQuat(F32 angle, const LLVector3 &vec)",
        "void LLQuaternion::shortestArc(", "void LLQuaternion::getEulerAngles("]),
    ("indra/llmath/v3math.h", ["inline F32 angle_between(", "inline bool are_parallel("]),
]:
    for signature in signatures:
        harness += function(path, signature)

harness += r'''
struct LLMatrix4 {LLQuaternion rot;};
LLVector3 rotate_vector(const LLVector3& v,const LLMatrix4& m){return v*m.rot;}
struct LLJoint {
    std::string name; LLJoint* parent=nullptr;
    LLVector3 pos,scale{1,1,1}; LLQuaternion rot;
    bool scale_child_offset=true;
    int writes=0, world_updates=0;
    LLJoint(std::string n,LLJoint* p=nullptr):name(n),parent(p){}
    const std::string& getName() const { return name; }
    LLVector3 getPosition() { return pos; } LLVector3 getScale() { return scale; }
    LLQuaternion getRotation() { return rot; }
    void setPosition(LLVector3 v) {pos=v;++writes;} void setScale(LLVector3 v) {scale=v;++writes;}
    void setRotation(LLQuaternion v) {rot=v;++writes;}
    void updateWorldMatrixChildren() {++world_updates;}
    LLQuaternion worldRotation() { return parent ? rot*parent->worldRotation() : rot; }
    LLVector3 worldPosition() {
        if(!parent)return pos;
        LLVector3 scaled=pos;
        if(parent->scale_child_offset)for(int axis=0;axis<3;++axis)scaled.mV[axis]*=parent->scale.mV[axis];
        return scaled*parent->worldRotation()+parent->worldPosition();
    }
    LLJoint* getParent(){return parent;}
    LLJoint* getXform(){return this;}bool getScaleChildOffset(){return scale_child_offset;}
    LLVector3 getWorldPosition(){return worldPosition();}
    LLQuaternion getWorldRotation(){return worldRotation();}
    void setWorldRotation(LLQuaternion q){setRotation(parent?q*~parent->worldRotation():q);}
    LLMatrix4 getWorldMatrix(){return {worldRotation()};}
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
harness += without_includes(read("indra/llcharacter/lljointsolverrp3.h"))
harness += without_includes(read("indra/llcharacter/lljointsolverrp3.cpp"))
harness += without_includes(read("indra/newview/llposestudio.h"))
harness += without_includes(read("indra/newview/llposestudio.cpp"))
# Run the real handle input methods with a camera/window and mouse-capture
# double. No GL or in-world input is needed for projection/drag routing checks.
harness += r'''
using MASK=int;using KEY=int;using LLVector3d=LLVector3;
constexpr int MASK_NONE=0,KEY_ESCAPE=27,UI_CURSOR_TOOLTRANSLATE=1,UI_CURSOR_TOOLROTATE=2;
int ll_round(float v){return int(std::lround(v));}
struct LLVector2 {
    float mV[2];LLVector2(float x=0,float y=0):mV{x,y}{}void set(float x,float y){mV[0]=x;mV[1]=y;}
    bool isFinite(){return std::isfinite(mV[0])&&std::isfinite(mV[1]);}
    float lengthSquared()const{return mV[0]*mV[0]+mV[1]*mV[1];}
    float normalize(){float n=std::sqrt(lengthSquared());if(n>0){mV[0]/=n;mV[1]/=n;}return n;}
    friend LLVector2 operator+(LLVector2 a,LLVector2 b){return {a.mV[0]+b.mV[0],a.mV[1]+b.mV[1]};}
    friend LLVector2 operator-(LLVector2 a,LLVector2 b){return {a.mV[0]-b.mV[0],a.mV[1]-b.mV[1]};}
    friend LLVector2 operator*(LLVector2 a,float b){return {a.mV[0]*b,a.mV[1]*b};}
    friend float operator*(LLVector2 a,LLVector2 b){return a.mV[0]*b.mV[0]+a.mV[1]*b.mV[1];}
};
struct LLRect {
    int left=100,bottom=50,width=1000,height=700;
    int getHeight()const{return height;}int getCenterX()const{return left+width/2;}int getCenterY()const{return bottom+height/2;}
    bool pointInRect(int x,int y)const{return x>=left&&x<left+width&&y>=bottom&&y<bottom+height;}
};
struct LLViewerCamera:LLSingleton<LLViewerCamera> {
    LLVector3 origin;LLQuaternion rotation;
    LLVector3 getOrigin()const{return origin;}LLVector3 getAtAxis()const{return LLVector3(1,0,0)*rotation;}
    LLVector3 getLeftAxis()const{return LLVector3(0,1,0)*rotation;}LLVector3 getUpAxis()const{return LLVector3(0,0,1)*rotation;}
    float getNear()const{return .1f;}float getView()const{return 1.f;}
};
struct ViewerWindow {
    LLRect rect;LLRect getWorldViewRectScaled(){return rect;}
    void setCursor(int){}
    LLVector3 ray(int x,int y) {
        auto& cam=LLViewerCamera::instance();
        LLVector3 ray=cam.getAtAxis()*(rect.height*.5f/std::tan(cam.getView()*.5f))
            +cam.getLeftAxis()*float(rect.getCenterX()-x)+cam.getUpAxis()*float(y-rect.getCenterY());ray.normalize();return ray;
    }
    LLVector3 mouseDirectionGlobal(int x,int y){return ray(x,y);}
    bool mousePointOnPlaneGlobal(LLVector3d& point,int x,int y,const LLVector3d& plane,const LLVector3& normal) {
        const auto origin=LLViewerCamera::instance().origin;auto direction=ray(x,y);float denom=direction*normal;
        if(std::abs(denom)<.00001f)return false;float t=((plane-origin)*normal)/denom;point=origin+direction*t;return t>0;
    }
} viewer_window;
ViewerWindow* gViewerWindow=&viewer_window;
struct {
    bool hidden=false,local_axes=false;
    bool getBOOL(const char* name){return std::string(name)=="PoseStudioLocalAxes"?local_axes:!hidden;}
} gSavedSettings;
struct {bool mouselook=false;bool cameraMouselook(){return mouselook;}} gAgentCamera;
struct LLAgent {
    LLVector3d getPosGlobalFromAgent(LLVector3 v){return v;}LLVector3 getPosAgentFromGlobal(LLVector3d v){return v;}
    struct Frame {float turned=0;void rotate(float angle,LLVector3){turned+=angle;}} mFrameAgent;
    bool rotateGrabbed(){return false;}LLVector3 getReferenceUpVector(){return {0,0,1};}
    void yaw(F32 angle);
} gAgent;
struct {void setKeyboardFocus(void*){}} gFocusMgr;
struct LLToolMgr:LLSingleton<LLToolMgr>{bool build=false;bool inBuildMode(){return build;}};
struct LLPipeline {enum {RENDER_DEBUG_FEATURE_UI};bool ui=true;bool hasRenderDebugFeatureMask(int){return ui;}} gPipeline;
bool gDisconnected=false;
struct LLFloaterPoseStudio {
    std::string selected;int changes=0;
    void onResetPose();
    void onPoseChanged(){++changes;}void selectJoint(const std::string& name){selected=name;}
} pose_floater;
struct LLFloaterReg {template<class T>static T* findTypedInstance(const char*){return &pose_floater;}};
struct LLSD {int option=1;};
struct LLNotificationsUtil {
    static inline std::function<void(const LLSD&,const LLSD&)> response;
    static void add(const char* name,LLSD,LLSD,std::function<void(const LLSD&,const LLSD&)> callback) {
        assert(std::string(name)=="PoseStudioConfirmReset");response=callback;
    }
    static int getSelectedOption(const LLSD&,const LLSD& value){return value.option;}
};
struct LLTool {
    bool captured=false;LLTool(const char*){}virtual ~LLTool()=default;
    virtual bool handleMouseDown(int,int,MASK){return false;}virtual bool handleMouseUp(int,int,MASK){return false;}
    virtual bool handleHover(int,int,MASK){return false;}virtual bool handleKey(KEY,MASK){return false;}
    virtual void onMouseCaptureLost(){}virtual void render(){}
    bool hasMouseCapture(){return captured;}void setMouseCapture(bool c){bool old=captured;captured=c;if(old&&!c)onMouseCaptureLost();}
};
'''
harness += function("indra/newview/llfloaterposestudio.cpp", "void LLFloaterPoseStudio::onResetPose(")
harness += function("indra/newview/llagent.cpp", "void LLAgent::yaw(")
harness += r'''
enum EKeystate {KEYSTATE_DOWN,KEYSTATE_UP,KEYSTATE_LEVEL};
using EMouseClickType=int;
struct LLKeyboardBinding {KEY mKey;MASK mMask;std::function<bool(EKeystate)> mFunction;std::string mFunctionName;};
struct LLMouseBinding {EMouseClickType mMouse;MASK mMask;std::function<bool(EKeystate)> mFunction;std::string mFunctionName;};
struct LLViewerInput {
    enum EMouseState {MOUSE_STATE_DOWN,MOUSE_STATE_CLICK,MOUSE_STATE_LEVEL,MOUSE_STATE_UP,MOUSE_STATE_SILENT};
    bool scanKey(const std::vector<LLKeyboardBinding>&,S32,KEY,MASK,bool,bool,bool,bool)const;
    bool scanMouse(const std::vector<LLMouseBinding>&,S32,EMouseClickType,MASK,EMouseState,bool)const;
};
'''
harness += function("indra/newview/llviewerinput.cpp", "bool poseBlocksMovement(")
harness += function("indra/newview/llviewerinput.cpp", "bool LLViewerInput::scanKey(const std::vector<LLKeyboardBinding>")
harness += function("indra/newview/llviewerinput.cpp", "bool LLViewerInput::scanMouse(\n    const std::vector<LLMouseBinding>")
# Expose input state only in this harness to check hover/drag routing without GL.
harness += without_includes(read("indra/newview/lltoolposeik.h")).replace("private:", "public:")
tool_source = read("indra/newview/lltoolposeik.cpp")
harness += tool_source[tool_source.index("namespace\n{"):tool_source.index("LLToolPoseIK::LLToolPoseIK()")]
harness += 'LLToolPoseIK::LLToolPoseIK() : LLTool("Pose Studio IK") {}\nvoid LLToolPoseIK::render() {}\n'
for signature in ("bool LLToolPoseIK::available(", "void LLToolPoseIK::selectJoint(", "bool LLToolPoseIK::selectedPose(", "LLToolPoseIK::Hit LLToolPoseIK::pick(",
                  "bool LLToolPoseIK::highlighted(",
                  "bool LLToolPoseIK::handleMouseDown(", "bool LLToolPoseIK::drag(",
                  "bool LLToolPoseIK::handleHover(", "bool LLToolPoseIK::handleMouseUp(",
                  "bool LLToolPoseIK::handleKey("):
    harness += function("indra/newview/lltoolposeik.cpp", signature)
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
    // Exercise all four actual limb mappings with rotated parent frames,
    // unequal lengths and edited local positions. Targets are in agent space.
    for(int posture=0;posture<2;++posture) for(int limb=0;limb<4;++limb) {
        LLJoint upper{IK_JOINTS[limb][0],&avatar.root}, lower{IK_JOINTS[limb][1],&upper}, end{IK_JOINTS[limb][2],&lower};
        LLJoint finger{"finger",&end};finger.pos={0.1f,0,0};
        const LLVector3 axis=limb<2 ? LLVector3(0,limb==0?1.f:-1.f,0) : LLVector3(0,0,-1);
        avatar.root.pos={10,20,30};avatar.root.rot=rotation(10,20,40);
        upper.pos={0.1f,0.2f,0.3f};upper.rot=rotation(20,-15,35);
        upper.scale={1.15f,.85f,1.2f};lower.scale={.9f,1.1f,.95f};
        lower.pos=axis*0.7f;lower.rot=posture?rotation(55,-25,40):rotation(0,0,0);
        end.pos=axis*0.55f;end.rot=rotation(25,45,-60);
        avatar.joints={&upper,&lower,&end,&finger};gObjectList.objects[1]=&avatar;
        assert(studio.begin(avatar));studio.afterUpdate(avatar);
        studio.setPositionOffset(end.name,axis*0.03f);
        studio.beforeUpdate(avatar);studio.afterUpdate(avatar);
        LLPoseStudio::IKPose seed;
        assert(studio.getIKPose(limb,seed));assert(!studio.getIKPose(-1,seed));assert(!studio.getIKPose(4,seed));
        const auto end_orientation=end.getWorldRotation();
        const auto end_position=end.pos;
        const float upper_length=(seed.positions[1]-seed.positions[0]).length();
        const float lower_length=(seed.positions[2]-seed.positions[1]).length();
        const float margin=std::min(upper_length,lower_length)*0.001f;
        for(int step=0;step<240;++step) {
            LLVector3 direction(std::cos(step*0.07f),std::sin(step*0.07f),std::sin(step*0.13f));direction.normalize();
            const float distance=(step%4==0)?4.f:((step%4==1)?0.01f:0.8f);
            const auto target=seed.positions[0]+direction*distance;
            assert(studio.setIKTarget(seed,target));
            const auto expected=seed.positions[0]+direction*std::clamp(distance,std::abs(upper_length-lower_length)+margin,upper_length+lower_length-margin);
            const float error=(end.getWorldPosition()-expected).length();
            if(error>0.003f) {std::cerr<<"IK miss limb "<<limb<<" step "<<step<<" error "<<error<<"\n";return 1;}
            assert(std::abs((lower.getWorldPosition()-upper.getWorldPosition()).length()-upper_length)<0.0001f);
            assert(std::abs((end.getWorldPosition()-lower.getWorldPosition()).length()-lower_length)<0.0001f);
            same(end.getWorldRotation(),end_orientation);near(end.pos,end_position);
            const auto held_position=end.getWorldPosition(), held_finger=finger.getWorldPosition();
            studio.beforeUpdate(avatar);upper.rot=rotation(50,20,10);lower.rot=rotation(5,10,80);
            studio.afterUpdate(avatar);
            near(end.getWorldPosition(),held_position);near(finger.getWorldPosition(),held_finger);
        }
        // A slider round-trip must preserve the IK pose (including wrist/ankle).
        const auto before=end.getWorldPosition();
        for(LLJoint* j : {&upper,&lower,&end})assert(studio.setRotationOffset(j->name,studio.getRotationOffset(j->name)));
        studio.beforeUpdate(avatar);studio.afterUpdate(avatar);near(end.getWorldPosition(),before);
        assert(!studio.setIKTarget(seed,{std::numeric_limits<float>::infinity(),0,0}));
        // Rotation rings change only the effector orientation. Parent joints,
        // every joint position and local finger articulation stay untouched.
        const auto upper_rotation=upper.rot,lower_rotation=lower.rot, finger_rotation=finger.rot;
        const auto upper_position=upper.getWorldPosition(),lower_position=lower.getWorldPosition(),end_world=end.getWorldPosition();
        LLPoseStudio::BonePose bone;assert(studio.getBonePose(LLPoseStudio::getIKJointName(limb),bone));
        for(const auto& axis : AXES)for(float angle : {-1.2f,.7f,2.5f}) {
            const auto wanted=end_orientation*LLQuaternion(angle,axis);
            assert(studio.setBoneRotation(bone,wanted));
            same(end.getWorldRotation(),wanted);same(upper.rot,upper_rotation);same(lower.rot,lower_rotation);same(finger.rot,finger_rotation);
            near(upper.getWorldPosition(),upper_position);near(lower.getWorldPosition(),lower_position);near(end.getWorldPosition(),end_world);
            const auto finger_position=finger.getWorldPosition();
            studio.beforeUpdate(avatar);end.rot=rotation(30,40,50);studio.afterUpdate(avatar);
            same(end.getWorldRotation(),wanted);near(finger.getWorldPosition(),finger_position);
            assert(studio.setRotationOffset(end.name,studio.getRotationOffset(end.name)));
            studio.beforeUpdate(avatar);studio.afterUpdate(avatar);
            // Euler round-trips can choose the antipodal quaternion (-q),
            // which is the same orientation. Compare rotated basis vectors.
            near(LLVector3(1,0,0)*end.getWorldRotation(),LLVector3(1,0,0)*wanted);
            near(LLVector3(0,1,0)*end.getWorldRotation(),LLVector3(0,1,0)*wanted);
        }
        studio.resetPose();studio.beforeUpdate(avatar);studio.afterUpdate(avatar);
        near(end.pos,axis*0.55f);same(upper.rot,rotation(20,-15,35));
        studio.end();assert(!studio.setIKTarget(seed,seed.positions[2]));
        assert(!studio.setBoneRotation(bone,LLQuaternion()));
        assert(studio.begin(avatar));studio.afterUpdate(avatar);
        assert(!studio.setIKTarget(seed,seed.positions[2])); // old drag from prior session
        assert(studio.getIKPose(limb,seed));++avatar.serial;
        assert(!studio.setIKTarget(seed,seed.positions[2]));studio.afterUpdate(avatar);
    }
    // Exact target at the root, exactly folded equal-length chain, and zero
    // length bones must not introduce NaNs or stretch the chain.
    LLPoseStudio::IKPose folded;
    folded.positions={LLVector3(0,0,0),LLVector3(1,0,0),LLVector3(0,0,0)};
    folded.rotations={LLQuaternion(),rotation(0,0,180),LLQuaternion()};folded.pole={0,1,0};
    std::array<LLQuaternion,3> solution;
    assert(folded.solve({0,0,0},solution));
    assert(solution[0].isFinite()&&solution[1].isFinite());
    assert(folded.solve({0,1,0},solution)); // goal parallel to original pole
    folded.positions[1]=folded.positions[0];assert(!folded.solve({0,1,0},solution));
    std::cout<<"PASS: 1920 straight/bent four-limb IK solves, clamped reach/lengths, hand/foot orientation, animation persistence, slider round-trip, reset and stale-drag rejection\n";
    // Handle projection must match mouse rays at different camera rotations,
    // viewport offsets and UI-scaled viewport sizes.
    auto& camera=LLViewerCamera::instance();LLVector2 screen;
    for(int size : {600,1000,1600})for(int angle : {0,45,90,175}) {
        viewer_window.rect.width=size;viewer_window.rect.height=size*7/10;
        camera.rotation=rotation(15,-25,float(angle));camera.origin={3,-5,7};
        const auto world=camera.origin+LLVector3(5,.4f,-.3f)*camera.rotation;
        assert(projectHandle(world,screen));
        LLVector3 hit;assert(viewer_window.mousePointOnPlaneGlobal(hit,ll_round(screen.mV[0]),ll_round(screen.mV[1]),world,camera.getAtAxis()));
        assert((world-hit).length()<.02f);
        assert(!projectHandle(camera.origin-camera.getAtAxis(),screen));
    }
    camera.origin={0,0,0};camera.rotation=LLQuaternion();viewer_window.rect=LLRect();
    LLVOAvatar ui_avatar;LLJoint ui_upper{"mShoulderLeft",&ui_avatar.root},ui_lower{"mElbowLeft",&ui_upper},ui_end{"mWristLeft",&ui_lower};
    ui_upper.pos={5,0,0};ui_lower.pos=ui_end.pos={0,0,-.5f};
    ui_avatar.joints={&ui_upper,&ui_lower,&ui_end};gObjectList.objects[1]=&ui_avatar;
    auto& session=LLPoseStudio::instance();assert(session.begin(ui_avatar));session.afterUpdate(ui_avatar);
    LLToolPoseIK tool;assert(projectHandle(ui_end.getWorldPosition(),screen));
    int x=ll_round(screen.mV[0]),y=ll_round(screen.mV[1]);
    assert(!tool.handleMouseDown(x,y,1));assert(!tool.handleMouseDown(x+40,y,0));
    gSavedSettings.hidden=true;assert(!tool.handleMouseDown(x,y,0));gSavedSettings.hidden=false;
    gAgentCamera.mouselook=true;assert(!tool.handleMouseDown(x,y,0));gAgentCamera.mouselook=false;
    LLToolMgr::instance().build=true;assert(!tool.handleMouseDown(x,y,0));LLToolMgr::instance().build=false;
    const auto before_click=ui_end.getWorldPosition();
    assert(tool.handleMouseDown(x,y,0));assert(tool.hasMouseCapture());
    assert(pose_floater.selected=="mWristLeft");
    assert(tool.handleHover(x,y,0));assert(tool.handleMouseUp(x,y,0));
    near(before_click,ui_end.getWorldPosition());assert(!tool.hasMouseCapture());
    assert(tool.handleMouseDown(x,y,0));assert(tool.handleHover(x+35,y+30,0));
    assert((ui_end.getWorldPosition()-before_click).length()>.1f);
    assert(tool.handleMouseUp(x+35,y+30,0));assert(!tool.hasMouseCapture());
    assert(projectHandle(ui_end.getWorldPosition(),screen));x=ll_round(screen.mV[0]);y=ll_round(screen.mV[1]);
    assert(tool.handleMouseDown(x,y,0));assert(tool.handleKey(KEY_ESCAPE,0));assert(!tool.hasMouseCapture());
    assert(tool.handleMouseDown(x,y,0));gSavedSettings.hidden=true;tool.handleHover(x,y,0);assert(!tool.hasMouseCapture());gSavedSettings.hidden=false;
    assert(tool.handleMouseDown(x,y,0));session.end();tool.handleHover(x,y,0);assert(!tool.hasMouseCapture());
    std::cout<<"PASS: camera projection, handle picking, camera/build/visibility guards, click-without-drag, drag/release, Escape and session cleanup\n";

    // Find a visible, unambiguous pixel on the actual rendered geometry.
    auto gizmo_point=[](LLVector3 origin,int part,LLQuaternion orientation=LLQuaternion()) {
        const auto segments=gizmoSegments(origin,orientation);LLVector2 center;assert(projectHandle(origin,center));
        for(const auto& s:segments)if(s.part==part)for(float t : {.35f,.65f,.85f}) {
            LLVector2 p=s.start+(s.end-s.start)*t;
            p.set(float(ll_round(p.mV[0])),float(ll_round(p.mV[1])));
            if((p-center).lengthSquared()<PICK_RADIUS*PICK_RADIUS)continue;
            bool clear=true;float fraction;
            for(const auto& other:segments)if(other.part!=part&&segmentDistanceSquared(p,other,fraction)<64.f){clear=false;break;}
            if(clear)return p;
        }
        std::cerr<<"No unambiguous gizmo point for part "<<part<<"\n";std::abort();
    };
    ui_lower.rot=rotation(0,45,0);
    camera.rotation=rotation(0,-25,35);
    camera.origin=ui_end.getWorldPosition()-camera.getAtAxis()*4.f;
    assert(session.begin(ui_avatar));session.afterUpdate(ui_avatar);
    LLToolPoseIK axes_tool;
    auto arrow=gizmo_point(ui_end.getWorldPosition(),MOVE_X+1);
    assert(!axes_tool.handleMouseDown(ll_round(arrow.mV[0]),ll_round(arrow.mV[1]),0)); // unselected: compact handle only
    projectHandle(ui_end.getWorldPosition(),screen);x=ll_round(screen.mV[0]);y=ll_round(screen.mV[1]);
    assert(axes_tool.handleMouseDown(x,y,0));assert(axes_tool.handleMouseUp(x,y,0));
    for(int axis=0;axis<3;++axis) {
        const auto origin=ui_end.getWorldPosition();const auto orientation=ui_end.getWorldRotation();
        const auto p=gizmo_point(origin,MOVE_X+axis);x=ll_round(p.mV[0]);y=ll_round(p.mV[1]);
        float start;assert(axisParameter(origin,AXES[axis],x,y,start));
        LLVector2 destination;assert(projectHandle(origin+AXES[axis]*(start+.04f),destination));
        assert(axes_tool.handleMouseDown(x,y,0));
        assert(axes_tool.handleHover(ll_round(destination.mV[0]),ll_round(destination.mV[1]),0));
        assert(axes_tool.handleMouseUp(ll_round(destination.mV[0]),ll_round(destination.mV[1]),0));
        const auto delta=ui_end.getWorldPosition()-origin;
        assert(delta.mV[axis]>.02f);
        for(int other=0;other<3;++other)if(other!=axis)assert(std::abs(delta.mV[other])<.001f);
        same(ui_end.getWorldRotation(),orientation);
    }
    for(int axis=0;axis<3;++axis) {
        const auto origin=ui_end.getWorldPosition();const auto orientation=ui_end.getWorldRotation();
        const auto parent_rotation=ui_lower.rot;
        const auto p=gizmo_point(origin,ROTATE_X+axis);x=ll_round(p.mV[0]);y=ll_round(p.mV[1]);
        LLVector3 radial;assert(rotationVector(origin,AXES[axis],x,y,radial));
        LLVector2 destination;assert(projectHandle(origin+(radial*LLQuaternion(.3f,AXES[axis]))*(RING_RADIUS*gizmoScale(origin)),destination));
        assert(axes_tool.handleMouseDown(x,y,0));
        assert(axes_tool.handleMouseUp(ll_round(destination.mV[0]),ll_round(destination.mV[1]),0));
        near(ui_end.getWorldPosition(),origin);same(ui_lower.rot,parent_rotation);
        LLVector3 expected=LLVector3(.3f,.4f,.5f)*(orientation*LLQuaternion(.3f,AXES[axis]));
        assert((LLVector3(.3f,.4f,.5f)*ui_end.getWorldRotation()-expected).length()<.02f);
    }
    // Edge-on ring drag takes the screen-tangent fallback, without moving the end.
    camera.rotation=LLQuaternion();camera.origin=ui_end.getWorldPosition()-LLVector3(4,0,0);
    const auto edge_origin=ui_end.getWorldPosition();const auto edge_rotation=ui_end.getWorldRotation();
    const auto edge=gizmo_point(edge_origin,ROTATE_X+2);x=ll_round(edge.mV[0]);y=ll_round(edge.mV[1]);
    LLVector3 radial;assert(!rotationVector(edge_origin,AXES[2],x,y,radial));
    assert(axes_tool.handleMouseDown(x,y,0));assert(axes_tool.handleMouseUp(x+15,y,0));
    near(ui_end.getWorldPosition(),edge_origin);
    assert((LLVector3(1,0,0)*ui_end.getWorldRotation()-LLVector3(1,0,0)*edge_rotation).length()>.05f);
    // Reach clamps must keep the target on the chosen line even far past reach.
    LLPoseStudio::IKPose axis_pose;assert(session.getIKPose(0,axis_pose));
    for(const auto& axis:AXES)for(float distance : {-100.f,100.f}) {
        auto target=axisTarget(axis_pose,axis,distance);
        auto delta=target-axis_pose.positions[2];near(delta,axis*(delta*axis));
        assert((target-axis_pose.positions[0]).length()<=1.0001f);
    }
    session.end();assert(session.begin(ui_avatar));session.afterUpdate(ui_avatar);
    // A selected gizmo from a previous session must not survive its capture.
    auto old_arrow=gizmo_point(ui_end.getWorldPosition(),MOVE_X+1);
    assert(!axes_tool.handleMouseDown(ll_round(old_arrow.mV[0]),ll_round(old_arrow.mV[1]),0));
    session.end();
    // Clicking a different handle moves the expanded gizmos to that limb only.
    LLJoint other_upper{"mShoulderRight",&ui_avatar.root},other_lower{"mElbowRight",&other_upper},other_end{"mWristRight",&other_lower};
    other_upper.pos=ui_upper.pos+LLVector3(0,1.5f,0);other_lower.pos=ui_lower.pos;other_end.pos=ui_end.pos;
    other_lower.rot=ui_lower.rot;
    ui_avatar.joints.insert(ui_avatar.joints.end(),{&other_upper,&other_lower,&other_end});
    assert(session.begin(ui_avatar));session.afterUpdate(ui_avatar);
    LLToolPoseIK switching_tool;
    projectHandle(ui_end.getWorldPosition(),screen);x=ll_round(screen.mV[0]);y=ll_round(screen.mV[1]);
    assert(switching_tool.handleMouseDown(x,y,0));assert(switching_tool.handleMouseUp(x,y,0));
    assert(pose_floater.selected=="mWristLeft");
    const auto left_arrow=gizmo_point(ui_end.getWorldPosition(),MOVE_X+1);
    assert(projectHandle(other_end.getWorldPosition(),screen));x=ll_round(screen.mV[0]);y=ll_round(screen.mV[1]);
    assert(switching_tool.handleMouseDown(x,y,0));assert(switching_tool.handleMouseUp(x,y,0));
    assert(pose_floater.selected=="mWristRight");
    assert(!switching_tool.handleMouseDown(ll_round(left_arrow.mV[0]),ll_round(left_arrow.mV[1]),0));
    const auto right_arrow=gizmo_point(other_end.getWorldPosition(),MOVE_X+1);
    assert(switching_tool.handleMouseDown(ll_round(right_arrow.mV[0]),ll_round(right_arrow.mV[1]),0));
    assert(switching_tool.handleMouseUp(ll_round(right_arrow.mV[0]),ll_round(right_arrow.mV[1]),0));
    // Selecting a wrist row uses direct editing; clicking its compact handle
    // switches back to IK and keeps the matching row selected.
    switching_tool.selectJoint("mWristRight");
    const auto wrist_origin=other_end.getWorldPosition(),wrist_local=other_end.pos;
    const auto elbow_rotation=other_lower.rot,shoulder_rotation=other_upper.rot;
    const auto direct_arrow=gizmo_point(wrist_origin,MOVE_X+1);
    x=ll_round(direct_arrow.mV[0]);y=ll_round(direct_arrow.mV[1]);
    float wrist_start;assert(axisParameter(wrist_origin,AXES[1],x,y,wrist_start));
    assert(projectHandle(wrist_origin+AXES[1]*(wrist_start+.05f),screen));
    assert(switching_tool.handleMouseDown(x,y,0));
    assert(switching_tool.handleMouseUp(ll_round(screen.mV[0]),ll_round(screen.mV[1]),0));
    assert((other_end.pos-wrist_local).length()>.02f);
    same(other_upper.rot,shoulder_rotation);same(other_lower.rot,elbow_rotation);
    assert(projectHandle(other_end.getWorldPosition(),screen));x=ll_round(screen.mV[0]);y=ll_round(screen.mV[1]);
    const auto new_wrist_local=other_end.pos;
    assert(switching_tool.handleMouseDown(x,y,0));assert(switching_tool.handleMouseUp(x+20,y+15,0));
    near(other_end.pos,new_wrist_local);assert(pose_floater.selected=="mWristRight");
    session.end();
    std::cout<<"PASS: select-only XYZ gizmos, constrained axis movement and reach, world-axis rotations, fixed wrist/ankle positions, edge-on rings and stale selection\n";

    // Direct bone gizmos invert rotated/scaled parents, preserve ancestors,
    // and let descendants inherit the edit without touching their local pose.
    LLVOAvatar fk_avatar;LLJoint fk_parent{"mTorso",&fk_avatar.root},fk_bone{"mSpine3",&fk_parent},fk_child{"mChest",&fk_bone};
    fk_avatar.joints={&fk_parent,&fk_bone,&fk_child};gObjectList.objects[1]=&fk_avatar;
    fk_avatar.root.pos={5,0,0};fk_avatar.root.rot=rotation(15,-10,25);
    fk_parent.rot=rotation(-35,20,10);fk_parent.scale={1.7f,.7f,-1.2f};
    fk_bone.pos={.1f,.2f,.3f};fk_bone.rot=rotation(10,5,-15);fk_child.pos={.3f,.15f,.4f};fk_child.rot=rotation(5,12,9);
    const auto captured_position=fk_bone.pos;const auto captured_rotation=fk_bone.rot;
    const auto captured_parent_rotation=fk_parent.rot,captured_child_rotation=fk_child.rot;
    for(bool scaled : {false,true}) {
        fk_parent.scale_child_offset=scaled;
        camera.rotation=rotation(0,-25,35);camera.origin=fk_bone.getWorldPosition()-camera.getAtAxis()*4.f;
        LLToolPoseIK fk_tool;assert(session.begin(fk_avatar));
        fk_tool.selectJoint("mSpine3"); // selection before the first pose update must survive
        const auto initial_arrow=gizmo_point(fk_bone.getWorldPosition(),MOVE_X+1);
        assert(!fk_tool.handleHover(ll_round(initial_arrow.mV[0]),ll_round(initial_arrow.mV[1]),0));
        session.afterUpdate(fk_avatar);
        LLPoseStudio::BonePose bone;
        assert(session.getBonePose("mSpine3",bone));assert(!session.getBonePose("missing",bone));
        for(int axis=0;axis<3;++axis) {
            const auto origin=fk_bone.getWorldPosition(),child=fk_child.getWorldPosition();
            const auto orientation=fk_bone.getWorldRotation();
            const auto p=gizmo_point(origin,MOVE_X+axis);x=ll_round(p.mV[0]);y=ll_round(p.mV[1]);
            float start;assert(axisParameter(origin,AXES[axis],x,y,start));
            assert(projectHandle(origin+AXES[axis]*(start+.05f),screen));
            assert(fk_tool.handleMouseDown(x,y,0));assert(fk_tool.handleMouseUp(ll_round(screen.mV[0]),ll_round(screen.mV[1]),0));
            const auto delta=fk_bone.getWorldPosition()-origin;assert(delta.mV[axis]>.03f);
            for(int other=0;other<3;++other)if(other!=axis)assert(std::abs(delta.mV[other])<.0001f);
            near(fk_child.getWorldPosition()-child,delta);same(fk_bone.getWorldRotation(),orientation);
            same(fk_parent.rot,captured_parent_rotation);near(fk_child.pos,{.3f,.15f,.4f});
            near(session.getPositionOffset("mSpine3"),fk_bone.pos-captured_position);
        }
        for(int axis=0;axis<3;++axis) {
            const auto origin=fk_bone.getWorldPosition(),child=fk_child.getWorldPosition();
            const auto orientation=fk_bone.getWorldRotation();
            const auto p=gizmo_point(origin,ROTATE_X+axis);x=ll_round(p.mV[0]);y=ll_round(p.mV[1]);
            LLVector3 radial;assert(rotationVector(origin,AXES[axis],x,y,radial));
            assert(projectHandle(origin+(radial*LLQuaternion(.3f,AXES[axis]))*(RING_RADIUS*gizmoScale(origin)),screen));
            assert(fk_tool.handleMouseDown(x,y,0));assert(fk_tool.handleMouseUp(ll_round(screen.mV[0]),ll_round(screen.mV[1]),0));
            near(fk_bone.getWorldPosition(),origin);same(fk_parent.rot,captured_parent_rotation);
            same(fk_child.rot,captured_child_rotation);assert((fk_child.getWorldPosition()-child).length()>.02f);
            const auto expected=LLVector3(.3f,.4f,.5f)*(orientation*LLQuaternion(.3f,AXES[axis]));
            assert((LLVector3(.3f,.4f,.5f)*fk_bone.getWorldRotation()-expected).length()<.02f);
        }
        const auto held_local=fk_bone.pos,held_child=fk_child.getWorldPosition();const auto held_rotation=fk_bone.rot;
        for(int frame=0;frame<20;++frame) {
            session.beforeUpdate(fk_avatar);fk_bone.pos={.7f,.8f,.9f};fk_bone.rot=rotation(45,30,60);
            session.afterUpdate(fk_avatar);near(fk_bone.pos,held_local);same(fk_bone.rot,held_rotation);near(fk_child.getWorldPosition(),held_child);
        }
        assert(!session.setBonePosition(bone,{std::numeric_limits<float>::infinity(),0,0}));
        assert(!session.setBoneRotation(bone,LLQuaternion(0,0,0,std::numeric_limits<float>::infinity())));
        if(scaled) {
            fk_parent.scale.mV[1]=0.f;assert(!session.setBonePosition(bone,bone.position));
            near(fk_bone.pos,held_local);fk_parent.scale.mV[1]=.7f;
        }
        // Free center movement stays direct; selecting a different row releases capture.
        projectHandle(fk_bone.getWorldPosition(),screen);x=ll_round(screen.mV[0]);y=ll_round(screen.mV[1]);
        assert(fk_tool.handleMouseDown(x,y,0));assert(fk_tool.handleMouseUp(x+20,y+15,0));
        same(fk_parent.rot,captured_parent_rotation);assert((fk_bone.pos-held_local).length()>.02f);
        projectHandle(fk_bone.getWorldPosition(),screen);
        assert(fk_tool.handleMouseDown(ll_round(screen.mV[0]),ll_round(screen.mV[1]),0));
        fk_tool.selectJoint("mChest");assert(!fk_tool.hasMouseCapture());
        session.resetJoint("mSpine3");session.beforeUpdate(fk_avatar);session.afterUpdate(fk_avatar);
        near(fk_bone.pos,captured_position);same(fk_bone.rot,captured_rotation);
        session.end();assert(!session.setBonePosition(bone,bone.position));assert(!session.setBoneRotation(bone,bone.rotation));
        assert(session.begin(fk_avatar));session.afterUpdate(fk_avatar);
        assert(!session.setBonePosition(bone,bone.position));assert(!session.setBoneRotation(bone,bone.rotation));
        assert(session.getBonePose("mSpine3",bone));++fk_avatar.serial;
        assert(!session.setBonePosition(bone,bone.position));assert(!session.setBoneRotation(bone,bone.rotation));
        session.afterUpdate(fk_avatar);assert(!session.isActive());
    }
    assert(pose_floater.changes>0);
    std::cout<<"PASS: direct bone XYZ/free movement and rotation, scaled/rotated parents, inherited child transforms, inspector offsets, animation persistence, FK/IK switching and stale-skeleton rejection\n";

    // Local arrows and rings must use the bone's orientation for both rendered
    // geometry and actual drags, including IK and nonuniform parent scales.
    gSavedSettings.local_axes=true;
    for(bool ik : {false,true}) {
        auto& rig=ik?ui_avatar:fk_avatar;auto& end=ik?ui_end:fk_bone;
        gObjectList.objects[1]=&rig;assert(session.begin(rig));session.afterUpdate(rig);
        LLToolPoseIK local_tool;
        camera.rotation=rotation(0,-25,35)*end.getWorldRotation();
        camera.origin=end.getWorldPosition()-camera.getAtAxis()*4.f;
        if(ik) {
            projectHandle(end.getWorldPosition(),screen);x=ll_round(screen.mV[0]);y=ll_round(screen.mV[1]);
            assert(local_tool.handleHover(x,y,0));assert(local_tool.highlighted(end.name,0));
            assert(local_tool.handleMouseDown(x,y,0));assert(local_tool.handleMouseUp(x,y,0));
        } else local_tool.selectJoint(end.name);
        for(int axis=0;axis<3;++axis) {
            const auto origin=end.getWorldPosition();const auto orientation=end.getWorldRotation();
            const auto direction=AXES[axis]*orientation;
            near(AXES[axis]*gizmoRotation(orientation),direction);
            const auto p=gizmo_point(origin,MOVE_X+axis,orientation);x=ll_round(p.mV[0]);y=ll_round(p.mV[1]);
            assert(local_tool.handleHover(x,y,0));assert(local_tool.highlighted(end.name,MOVE_X+axis));
            assert(!local_tool.highlighted(end.name,ROTATE_X+axis));assert(!local_tool.highlighted("missing",MOVE_X+axis));
            local_tool.clearHover();assert(!local_tool.highlighted(end.name,MOVE_X+axis)); // UI/menu intercepted hover
            assert(local_tool.handleHover(x,y,0));assert(!local_tool.handleHover(x,y,1));
            assert(!local_tool.highlighted(end.name,MOVE_X+axis)); // Alt camera control
            assert(local_tool.handleHover(x,y,0));assert(!local_tool.handleHover(0,0,0));
            assert(!local_tool.highlighted(end.name,MOVE_X+axis));
            float start;assert(axisParameter(origin,direction,x,y,start));
            assert(projectHandle(origin+direction*(start+.04f),screen));
            assert(local_tool.handleMouseDown(x,y,0));near(local_tool.mAxis,direction);
            // The grabbed axis stays highlighted when the cursor leaves it.
            local_tool.clearHover();assert(local_tool.highlighted(end.name,MOVE_X+axis));
            assert(local_tool.handleMouseUp(ll_round(screen.mV[0]),ll_round(screen.mV[1]),0));
            const auto delta=end.getWorldPosition()-origin;assert(delta*direction>.02f);
            assert((delta-direction*(delta*direction)).length()<.001f);same(end.getWorldRotation(),orientation);
        }
        for(int axis=0;axis<3;++axis) {
            const auto origin=end.getWorldPosition();const auto orientation=end.getWorldRotation();
            camera.rotation=rotation(0,-25,35)*orientation;camera.origin=origin-camera.getAtAxis()*4.f;
            const auto direction=AXES[axis]*orientation;
            const auto p=gizmo_point(origin,ROTATE_X+axis,orientation);x=ll_round(p.mV[0]);y=ll_round(p.mV[1]);
            assert(local_tool.handleHover(x,y,0));assert(local_tool.highlighted(end.name,ROTATE_X+axis));
            LLVector3 radial;assert(rotationVector(origin,direction,x,y,radial));
            assert(projectHandle(origin+(radial*LLQuaternion(.3f,direction))*(RING_RADIUS*gizmoScale(origin)),screen));
            assert(local_tool.handleMouseDown(x,y,0));near(local_tool.mAxis,direction);
            assert(local_tool.handleMouseUp(ll_round(screen.mV[0]),ll_round(screen.mV[1]),0));
            near(end.getWorldPosition(),origin);
            const auto expected=LLQuaternion(.3f,AXES[axis])*orientation;
            for(const auto& basis:AXES)assert((basis*end.getWorldRotation()-basis*expected).length()<.025f);
        }
        // A local ring viewed edge-on uses a tangent in the rotated frame.
        const auto edge_origin=end.getWorldPosition();const auto edge_orientation=end.getWorldRotation();
        camera.rotation=edge_orientation;camera.origin=edge_origin-camera.getAtAxis()*4.f;
        const auto edge_point=gizmo_point(edge_origin,ROTATE_X+2,edge_orientation);
        x=ll_round(edge_point.mV[0]);y=ll_round(edge_point.mV[1]);
        LLVector3 edge_radial;assert(!rotationVector(edge_origin,AXES[2]*edge_orientation,x,y,edge_radial));
        assert(local_tool.handleMouseDown(x,y,0));assert(!local_tool.mRotateInPlane);
        assert(local_tool.handleMouseUp(x+15,y,0));near(end.getWorldPosition(),edge_origin);
        assert((AXES[0]*end.getWorldRotation()-AXES[0]*edge_orientation).length()>.05f);
        // Mode changes don't edit the pose or leave a drag using old axes.
        const auto origin=end.getWorldPosition();const auto orientation=end.getWorldRotation();
        camera.rotation=rotation(0,-25,35)*orientation;camera.origin=origin-camera.getAtAxis()*4.f;
        auto p=gizmo_point(origin,MOVE_X+1,orientation);x=ll_round(p.mV[0]);y=ll_round(p.mV[1]);
        assert(local_tool.handleMouseDown(x,y,0));gSavedSettings.local_axes=false;
        assert(local_tool.handleHover(x+15,y+15,0));assert(!local_tool.hasMouseCapture());
        near(end.getWorldPosition(),origin);same(end.getWorldRotation(),orientation);
        for(const auto& basis:AXES)near(basis*gizmoRotation(orientation),basis);
        camera.rotation=rotation(0,-25,35);camera.origin=origin-camera.getAtAxis()*4.f;
        p=gizmo_point(origin,MOVE_X+1);x=ll_round(p.mV[0]);y=ll_round(p.mV[1]);
        assert(local_tool.handleHover(x,y,0));assert(local_tool.highlighted(end.name,MOVE_X+1));
        gSavedSettings.hidden=true;assert(!local_tool.handleHover(x,y,0));assert(!local_tool.highlighted(end.name,MOVE_X+1));
        gSavedSettings.hidden=false;session.end();gSavedSettings.local_axes=true;
    }
    gSavedSettings.local_axes=false;
    std::cout<<"PASS: local FK/IK axis geometry, movement and rotation, world/local switching, hover highlights and UI/modifier/hidden/drag cleanup\n";

    gObjectList.objects[1]=&fk_avatar;assert(session.begin(fk_avatar));session.afterUpdate(fk_avatar);
    gAgent.yaw(.4f);assert(gAgent.mFrameAgent.turned==0.f);
    LLViewerInput input;
    for(const std::string action : {"push_forward","push_backward","slide_left","slide_right","turn_left","turn_right",
        "jump","push_down","look_up","look_down","toggle_fly","toggle_sit","run_forward","run_backward","run_left",
        "run_right","toggle_run","walk_to","spin_around_ccw_sitting","spin_around_cw_sitting","spin_over_sitting",
        "spin_under_sitting","move_forward_sitting","move_backward_sitting"}) {
        int downs=0,ups=0,levels=0;
        auto handler=[&](EKeystate state){if(state==KEYSTATE_DOWN)++downs;else if(state==KEYSTATE_UP)++ups;else ++levels;return true;};
        std::vector<LLKeyboardBinding> keys={{42,0,handler,action}};
        assert(input.scanKey(keys,1,42,0,true,false,false,false));
        assert(input.scanKey(keys,1,42,0,false,false,true,false));
        assert(input.scanKey(keys,1,42,0,false,true,false,false));
        assert(input.scanKey(keys,1,42,0,true,true,false,false)); // press/release in one frame
        assert(downs==0&&levels==0&&ups==2);
        assert(!input.scanKey(keys,1,43,0,true,false,false,false));
        std::vector<LLMouseBinding> mouse={{1,0,handler,action}};
        for(auto state : {LLViewerInput::MOUSE_STATE_DOWN,LLViewerInput::MOUSE_STATE_LEVEL,LLViewerInput::MOUSE_STATE_CLICK,LLViewerInput::MOUSE_STATE_UP})
            assert(input.scanMouse(mouse,1,1,0,state,false));
        assert(downs==0&&levels==0&&ups==4);
    }
    for(const std::string action : {"start_chat","start_gesture","toggle_voice","voice_follow_key","spin_around_cw","pan_left","move_forward"}) {
        int invoked=0;std::vector<LLKeyboardBinding> keys={{42,0,[&](EKeystate){++invoked;return true;},action}};
        assert(input.scanKey(keys,1,42,0,true,false,false,false));assert(invoked==1);
    }
    assert(session.setRotationOffset("mSpine3",{10,20,30}));assert(session.setPositionOffset("mSpine3",{.1f,.2f,.3f}));
    pose_floater.onResetPose();assert(LLNotificationsUtil::response);
    near(session.getRotationOffset("mSpine3"),{10,20,30}); // opening dialog does not reset
    LLNotificationsUtil::response(LLSD(),LLSD{1});near(session.getPositionOffset("mSpine3"),{.1f,.2f,.3f}); // Cancel
    pose_floater.onResetPose();LLNotificationsUtil::response(LLSD(),LLSD{0});
    near(session.getRotationOffset("mSpine3"),{});near(session.getPositionOffset("mSpine3"),{});
    pose_floater.onResetPose();const auto old_confirmation=LLNotificationsUtil::response;
    session.end();assert(session.begin(fk_avatar));session.afterUpdate(fk_avatar);
    session.setRotationOffset("mSpine3",{5,15,25});old_confirmation(LLSD(),LLSD{0});
    near(session.getRotationOffset("mSpine3"),{5,15,25});
    pose_floater.onResetPose();session.end();LLNotificationsUtil::response(LLSD(),LLSD{0});
    near(session.getRotationOffset("mSpine3"),{5,15,25}); // closed session cannot reset
    int resumed=0;std::vector<LLKeyboardBinding> keys={{42,0,[&](EKeystate){++resumed;return true;},"push_forward"}};
    assert(input.scanKey(keys,1,42,0,true,false,false,false));assert(resumed==1);
    gAgent.yaw(.4f);assert(std::abs(gAgent.mFrameAgent.turned-.4f)<.0001f);
    std::cout<<"PASS: remapped movement keys/mouse actions blocked only while posing, release cleanup, chat/camera controls, reset confirmation/cancel and stale-session protection\n";
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
assert ui.find(".//check_box[@name='show_ik_handles']").get("control_name") == "PoseStudioShowIKHandles"
local_checkbox = ui.find(".//check_box[@name='local_axes']")
show_checkbox = ui.find(".//check_box[@name='show_ik_handles']")
assert local_checkbox.get("control_name") == "PoseStudioLocalAxes"
assert local_checkbox.get("top") == show_checkbox.get("top")
assert int(show_checkbox.get("left")) + int(show_checkbox.get("width")) <= int(local_checkbox.get("left"))
settings = ET.fromstring(read("indra/newview/app_settings/settings.xml")).find("map")
setting_keys = list(settings)
ik_setting = setting_keys[next(i for i,e in enumerate(setting_keys) if e.tag == "key" and e.text == "PoseStudioShowIKHandles")+1]
assert ik_setting.find("boolean").text == "true"
local_setting = setting_keys[next(i for i,e in enumerate(setting_keys) if e.tag == "key" and e.text == "PoseStudioLocalAxes")+1]
assert local_setting.find("boolean").text == "true"
notifications = ET.fromstring(read("indra/newview/skins/default/xui/en/notifications.xml"))
confirm = notifications.find(".//notification[@name='PoseStudioConfirmReset']")
assert confirm.get("type") == "alertmodal"
assert confirm.find(".//button[@index='1']").get("default") == "true"
assert confirm.find(".//button[@index='0']").get("text") == "Reset pose"
window = read("indra/newview/llviewerwindow.cpp")
assert window.index("mRootView->handleAnyMouseClick(x, y") < window.index("LLToolPoseIK::getInstance()->handleMouseDown") < window.index("LLFloaterSnapshot::photoWorldClick(x, y")
world_click_guard = window.index("if ((clicktype == CLICK_LEFT || clicktype == CLICK_DOUBLELEFT) && mask == MASK_NONE")
assert window.index("LLFloaterSnapshot::photoWorldClick(x, y") < world_click_guard < window.index("// Do not allow tool manager to handle mouseclicks")
assert "LLPoseStudio::instance().isActive()" in window[world_click_guard:world_click_guard+240]
update_ui = function("indra/newview/llviewerwindow.cpp", "void LLViewerWindow::updateUI(")
assert update_ui.index("LLToolPoseIK::instance().clearHover()") < update_ui.index("mRootView->handleHover(") < update_ui.index("LLToolPoseIK::getInstance()->handleHover(")
render_handles = function("indra/newview/lltoolposeik.cpp", "void LLToolPoseIK::render(")
assert render_handles.index("gSnapshot || !gDisplaySwapBuffers") < render_handles.index("gl_circle_2d(")

with tempfile.TemporaryDirectory(prefix="pose-studio-test-") as temp:
    cpp, exe = Path(temp)/"pose_studio.cpp", Path(temp)/"pose_studio.exe"
    cpp.write_text(harness, encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", "-O1", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("PASS: update ordering, teleport/disconnect wiring and XUI/menu structure")
