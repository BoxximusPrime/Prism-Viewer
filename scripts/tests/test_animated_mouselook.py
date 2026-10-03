"""Check production eye-camera math and mode guards. Run with Python; requires g++."""
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[2]
def function(path, signature):
    source = (root / path).read_text()
    start = source.index(signature)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]

harness = r'''
#include <cassert>
#include <cmath>
#include <cstring>
#include <initializer_list>
using F32=float;
constexpr int VX=0,VY=1,VZ=2,VW=3;
struct LLQuaternion {
    float mQ[4];
    LLQuaternion(float x=0,float y=0,float z=0,float w=1):mQ{x,y,z,w}{}
    LLQuaternion operator~() const { return {-mQ[0],-mQ[1],-mQ[2],mQ[3]}; }
    LLQuaternion& operator*=(const LLQuaternion&);
};
struct LLVector3 {
    float mV[3];
    LLVector3(float x=0,float y=0,float z=0):mV{x,y,z}{}
    LLVector3 operator+(const LLVector3& b) const {return {mV[0]+b.mV[0],mV[1]+b.mV[1],mV[2]+b.mV[2]};}
    LLVector3 operator-(const LLVector3& b) const {return {mV[0]-b.mV[0],mV[1]-b.mV[1],mV[2]-b.mV[2]};}
    LLVector3 operator*(float k) const {return {k*mV[0],k*mV[1],k*mV[2]};}
    float operator*(const LLVector3& b) const {return mV[0]*b.mV[0]+mV[1]*b.mV[1]+mV[2]*b.mV[2];}
    float normalize(){float length=std::sqrt(*this * *this);if(length>0)*this=*this*(1/length);return length;}
    static const LLVector3 x_axis,z_axis;
};
const LLVector3 LLVector3::x_axis{1,0,0},LLVector3::z_axis{0,0,1};
using LLVector3d=LLVector3;
LLVector3 operator*(float k,LLVector3 p){return {k*p.mV[0],k*p.mV[1],k*p.mV[2]};}
'''
harness += function('indra/llmath/llquaternion.cpp', 'LLQuaternion    operator*(const LLQuaternion &a,')
harness += function('indra/llmath/llquaternion.cpp', 'LLVector3       operator*(const LLVector3 &a,')
harness += r'''
LLQuaternion& LLQuaternion::operator*=(const LLQuaternion& b){*this=*this*b;return *this;}
struct Joint {
    LLQuaternion rotation; LLVector3 position;
    LLQuaternion getWorldRotation() const{return rotation;}
    LLVector3 getWorldPosition() const{return position;}
} root_joint,head,left_eye,right_eye;
struct LLViewerObject {
    bool decoupled=false; LLQuaternion rotation;
    bool flagCameraDecoupled() const{return decoupled;}
    LLQuaternion getRenderRotation() const{return rotation;}
} parent;
struct Avatar {
    struct {bool valid=true;bool notNull()const{return valid;}} mDrawable;
    Joint *mRoot=&root_joint,*mHeadp=&head,*mEyeLeftp=&left_eye,*mEyeRightp=&right_eye;
    LLViewerObject* parent=nullptr;
    LLViewerObject* getParent(){return parent;}
    LLViewerObject* getRoot(){return parent;}
} avatar;
Avatar* gAgentAvatarp=&avatar;
bool isAgentAvatarValid(){return gAgentAvatarp!=nullptr;}
struct Settings{bool enabled=true,level=true;}gSavedSettings;
template<class T>struct LLCachedControl{
    bool* value;
    LLCachedControl(Settings&,const char* name):value(std::strcmp(name,"BoxxyAnimatedMouselook")==0?&gSavedSettings.enabled:&gSavedSettings.level){}
    operator T()const{return *value;}
};
struct LLViewerJoystick {
    bool override_camera=false;
    static LLViewerJoystick* getInstance(){static LLViewerJoystick j;return &j;}
    bool getOverrideCamera()const{return override_camera;}
};
struct Agent {
    struct Frame{LLQuaternion rotation;LLQuaternion getQuaternion(){return rotation;}}frame;
    Frame& getFrameAgent(){return frame;}
    LLVector3 getPositionGlobal(){return {256,512,0};}
    LLVector3 getPosGlobalFromAgent(LLVector3 p){return p+LLVector3(256,512,0);}
}gAgent;
struct LLAgentCamera {
    bool mouselook=true;
    bool cameraMouselook()const{return mouselook;}
    bool useAnimatedMouselook()const;
    LLQuaternion getMouselookRotation()const;
    LLVector3 upVector();
    LLVector3 focusPosition();
    LLVector3 mFocusTargetGlobal;
    LLVector3 calcCameraPositionTargetGlobal(){return eyePosition(nullptr);}
    LLVector3 mCameraUpVector;
    LLVector3 eyePosition(bool* hit_limit){
'''
camera_source = (root / 'indra/newview/llagentcamera.cpp').read_text()
start = camera_source.index('        if (useAnimatedMouselook())', camera_source.index('LLVector3d LLAgentCamera::calcCameraPositionTargetGlobal'))
end = camera_source.index('        head_offset.clearVec();', start)
harness += camera_source[start:end] + 'return {};\n}\n};\n'
start = camera_source.index('    if (camera_mode == CAMERA_MODE_MOUSELOOK && useAnimatedMouselook())')
end = camera_source.index('    else if (isAgentAvatarValid()', start)
harness += 'LLVector3 LLAgentCamera::upVector(){ int camera_mode=1; const int CAMERA_MODE_MOUSELOOK=1; mCameraUpVector=LLVector3::z_axis;\n'
harness += camera_source[start:end] + 'return mCameraUpVector;\n}\n'
start = camera_source.index('        LLVector3d at_axis(1.0, 0.0, 0.0);', camera_source.index('LLVector3d LLAgentCamera::calcFocusPositionTargetGlobal'))
end = camera_source.index('    else if (mCameraMode == CAMERA_MODE_CUSTOMIZE_AVATAR)', start)
harness += 'LLVector3 LLAgentCamera::focusPosition(){\n' + camera_source[start:end]

for signature in ('bool LLAgentCamera::useAnimatedMouselook() const', 'LLQuaternion LLAgentCamera::getMouselookRotation() const'):
    harness += function('indra/newview/llagentcamera.cpp', signature)
harness += r'''
LLQuaternion axis(float radians,int n){float v[3]={};v[n]=std::sin(radians/2);return {v[0],v[1],v[2],std::cos(radians/2)};}
void same(LLQuaternion a,LLQuaternion b){float dot=0;for(int i=0;i<4;++i)dot+=a.mQ[i]*b.mQ[i];assert(std::abs(std::abs(dot)-1)<.0001f);}
void same(LLVector3 a,LLVector3 b){for(int i=0;i<3;++i)assert(std::abs(a.mV[i]-b.mV[i])<.0001f);}
int main(){
    LLAgentCamera camera;
    assert(camera.useAnimatedMouselook());
    gSavedSettings.level=false;
    for(int frame=0;frame<60;++frame){
        float t=frame*.05f;
        root_joint.rotation=axis(t,VZ);
        head.rotation=axis(std::sin(t)*.3f,VY)*axis(.15f,VX)*root_joint.rotation;
        gAgent.frame.rotation=root_joint.rotation;
        same(camera.getMouselookRotation(),head.rotation); // No mouse offset follows the head.
        head.rotation=root_joint.rotation;
        gAgent.frame.rotation=axis(.4f,VY)*axis(t+.2f,VZ);
        same(camera.getMouselookRotation(),gAgent.frame.rotation); // Neutral animation preserves input.
        auto offset=gAgent.frame.rotation*~root_joint.rotation;
        head.rotation=axis(.3f,VY)*axis(.2f,VX)*root_joint.rotation;
        same(camera.getMouselookRotation(),offset*head.rotation);
        left_eye.position={t,-.03f,1.7f+std::sin(t)*.1f};right_eye.position={t,.03f,left_eye.position.mV[2]};
        bool hit=true;
        same(camera.eyePosition(&hit),{256+t,512,left_eye.position.mV[2]});assert(!hit);
        left_eye.rotation=axis(t,VY);right_eye.rotation=axis(-t,VZ);
        same(camera.getMouselookRotation(),offset*head.rotation); // Eye rotations cannot steer it.
        same(camera.focusPosition(),camera.eyePosition(nullptr)+LLVector3::x_axis*camera.getMouselookRotation());
    }
    // Stabilized direction follows input, ignores animated head turns, and stays
    // normalized at vertical poles without changing the animated eye position.
    gSavedSettings.level=true;
    gAgent.frame.rotation={};root_joint.rotation={};
    for(float pitch : {-.5f,0.f,.5f,1.5707963f,-1.5707963f}){
        for(float roll : {-.8f,0.f,.8f,3.1415926f}){
            head.rotation=axis(roll,VX)*axis(pitch,VY)*axis(.4f,VZ);
            gAgent.frame.rotation=axis(pitch,VY)*axis(.4f,VZ);
            auto rotation=camera.getMouselookRotation();auto forward=LLVector3::x_axis*rotation;
            same(rotation,gAgent.frame.rotation);
            same(camera.focusPosition(),gAgent.getPositionGlobal()+forward*100.f);
            auto eyes=camera.eyePosition(nullptr);auto up=camera.upVector();
            assert(std::abs(up*forward)<.0001f && std::abs(up*up-1)<.0001f);
            if(std::abs(forward.mV[VZ])<.999f)assert(up.mV[VZ]>0);
            same(camera.getMouselookRotation(),rotation);same(camera.eyePosition(nullptr),eyes);
            gSavedSettings.level=false;same(camera.upVector(),LLVector3::z_axis*camera.getMouselookRotation());
            gSavedSettings.level=true;
        }
    }
    // A 10 cm sideways eye movement rotates the stabilized view by under .002
    // radians; the target itself is independent of the eyes and animated head.
    gAgent.frame.rotation={};left_eye.position={0,-.03f,1.7f};right_eye.position={0,.03f,1.7f};
    auto target=camera.focusPosition();auto before=target-camera.eyePosition(nullptr);before.normalize();
    left_eye.position.mV[VY]+=.1f;right_eye.position.mV[VY]+=.1f;
    head.rotation=axis(.6f,VZ)*axis(.3f,VY);
    same(camera.focusPosition(),target);
    auto after=target-camera.eyePosition(nullptr);after.normalize();
    assert((before-after).normalize()<.002f);
    avatar.parent=&parent;parent.rotation=axis(.7f,VZ);root_joint.rotation=parent.rotation;head.rotation=root_joint.rotation;
    same(camera.getMouselookRotation(),gAgent.frame.rotation*parent.rotation);
    parent.decoupled=true;same(camera.getMouselookRotation(),gAgent.frame.rotation);
    gSavedSettings.enabled=false;assert(!camera.useAnimatedMouselook());same(camera.getMouselookRotation(),gAgent.frame.rotation);
    gSavedSettings.enabled=true;camera.mouselook=false;assert(!camera.useAnimatedMouselook());camera.mouselook=true;
    LLViewerJoystick::getInstance()->override_camera=true;assert(!camera.useAnimatedMouselook());
    LLViewerJoystick::getInstance()->override_camera=false;avatar.mEyeLeftp=nullptr;assert(!camera.useAnimatedMouselook());
    avatar.mEyeLeftp=&left_eye;avatar.mDrawable.valid=false;assert(!camera.useAnimatedMouselook());
    avatar.mDrawable.valid=true;gAgentAvatarp=nullptr;assert(!camera.useAnimatedMouselook());
}
'''
assert 'cameraMouselook() && !useAnimatedMouselook()' in camera_source
agent = (root / 'indra/newview/llagent.cpp').read_text()
assert '? LLViewerCamera::getInstance()->getQuaternion() : LLQuaternion(look_dir, left, up)' in agent
assert '? mFrameAgent.getAtAxis() : agent_focus_pos - viewer_camera_pos' in agent
avatar_source = (root / 'indra/newview/llvoavatar.cpp').read_text()
assert '? agent.getAtAxis() : LLViewerCamera::getInstance()->getAtAxis()' in avatar_source

lookat = (root / 'indra/newview/llhudeffectlookat.cpp').read_text()
assert 'source_avatar->isSelf() && gAgentCamera.useAnimatedMouselook()' in lookat
viewer = (root / 'indra/newview/llviewercamera.cpp').read_text()
assert 'useAnimatedMouselook() ? 0.f' in viewer and '!gAgentCamera.useAnimatedMouselook() && zpos' in viewer
ui = ET.parse(root / 'indra/newview/skins/default/xui/en/panel_preferences_move.xml').getroot()
prism = next(n for n in ui.iter('panel') if n.get('name') == 'boxxy_options')
assert any(n.get('control_name') == 'BoxxyAnimatedMouselook' for n in prism)
assert any(n.get('control_name') == 'BoxxyAnimatedMouselookLevelHorizon' for n in prism)
with tempfile.TemporaryDirectory() as directory:
    cpp,binary=Path(directory)/'check.cpp',Path(directory)/'check.exe'
    cpp.write_text(harness)
    subprocess.run(['g++','-std=c++17',str(cpp),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
print('Animated eyes, distant-target stabilization, head/input rotation, parenting and fallback guards passed.')
