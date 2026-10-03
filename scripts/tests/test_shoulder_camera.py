"""Run the production shoulder-offset calculation with Python + g++."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'indra/newview/llagentcamera.cpp').read_text()
start = source.index('LLVector3 LLAgentCamera::getDynamicShoulderOffset() const')
end = source.index('{', start) + 1
depth = 1
while depth:
    depth += (source[end] == '{') - (source[end] == '}')
    end += 1

harness = r'''
#include <cassert>
#include <cmath>
#include <algorithm>
using F32=float;
constexpr int VX=0,VY=1,VZ=2,CAMERA_MODE_THIRD_PERSON=0,CAMERA_PRESET_REAR_VIEW=0;
constexpr float F_SQRT2=1.41421356237f;
template<class T> T llclamp(T v,T a,T b){return std::clamp(v,a,b);}
struct Settings {bool enabled=true;} gSavedSettings;
template<class T> struct LLCachedControl {
    LLCachedControl(Settings&,const char*,T){}
    operator T() const{return gSavedSettings.enabled;}
};
struct LLVector3 {
    float mV[3];
    LLVector3(float x=0,float y=0,float z=0):mV{x,y,z}{}
    void normalize(){float n=std::sqrt(mV[0]*mV[0]+mV[1]*mV[1]+mV[2]*mV[2]);if(n)for(float& v:mV)v/=n;}
    static const LLVector3 zero;
};
const LLVector3 LLVector3::zero{};
struct Joint {
    LLVector3 pos,scale{1,1,1};
    LLVector3 getPosition() const{return pos;}
    LLVector3 getScale() const{return scale;}
} head,skull,eye;
struct Avatar {
    bool sitting=false;
    LLVector3 mBodySize,mHeadOffset;
    float pelvis_to_foot=1;
    Joint *mHeadp=&head,*mSkullp=&skull,*mEyeLeftp=&eye;
    bool isSitting() const{return sitting;}
    float getPelvisToFoot() const{return pelvis_to_foot;}
} avatar;
Avatar* gAgentAvatarp=&avatar;
bool valid=true;
bool isAgentAvatarValid(){return valid;}
struct Frame {LLVector3 left{0,1,0};LLVector3 getLeftAxis() const{return left;}};
struct LLAgentCamera {
    int mCameraMode=0,mCameraPreset=0;
    bool mFocusOnAvatar=true;
    float mCurrentCameraDistance=1;
    Frame frame;
    const Frame& getThirdPersonFrame() const{return frame;}
    LLVector3 getDynamicShoulderOffset() const;
};
void near(float actual,float expected){assert(std::abs(actual-expected)<.00001f);}
''' + source[start:end] + r'''
int main(){
    LLAgentCamera camera;
    // Different avatar proportions get their own neutral eye height.
    for(float scale : {.5f,1.f,2.f}) {
        head.scale={1,1,scale};skull.pos={0,0,.1f};eye.pos={0,0,.03f};
        avatar.pelvis_to_foot=scale;
        avatar.mBodySize={0,0,1.8f*scale+F_SQRT2*.1f*scale};
        const float normal=.83f*scale;
        for(float drop : {-.2f,0.f,.05f,.1f,.3f,.6f}) {
            avatar.mHeadOffset={0,0,normal-drop};
            for(float distance : {1.f,2.f,3.f,5.f}) {
                camera.mCurrentCameraDistance=distance;
                const float b=distance<=1?1:distance>=3?0:.5f;
                const auto offset=camera.getDynamicShoulderOffset();
                near(offset.mV[0],0);near(offset.mV[1],-.65f*b);
                near(offset.mV[2],(-.33f-std::clamp(drop-.1f,0.f,normal))*b);
            }
        }
        avatar.mHeadOffset={0,0,normal};camera.mCurrentCameraDistance=1;
        near(camera.getDynamicShoulderOffset().mV[2],-.33f); // Stand up restores height.
    }
    camera.frame.left={1,0,1};
    const auto rotated=camera.getDynamicShoulderOffset();
    near(rotated.mV[0],-.65f);near(rotated.mV[1],0);near(rotated.mV[2],-.33f);
    avatar.mHeadOffset={0,0,-100};
    near(camera.getDynamicShoulderOffset().mV[2],-.33f-1.66f); // Bounded extreme pose.
    avatar.mHeadp=nullptr;
    near(camera.getDynamicShoulderOffset().mV[2],-.33f); // Incomplete skeleton.
    avatar.mHeadp=&head;
    avatar.mBodySize={};
    near(camera.getDynamicShoulderOffset().mV[2],-.33f); // Uninitialized body size.
    for(bool* enabled : {&gSavedSettings.enabled,&camera.mFocusOnAvatar,&valid}) {
        *enabled=false;near(camera.getDynamicShoulderOffset().mV[2],0);*enabled=true;
    }
    avatar.sitting=true;near(camera.getDynamicShoulderOffset().mV[2],0);avatar.sitting=false;
    camera.mCameraMode=1;near(camera.getDynamicShoulderOffset().mV[2],0);camera.mCameraMode=0;
    camera.mCameraPreset=1;near(camera.getDynamicShoulderOffset().mV[2],0);
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / 'shoulder_camera.cpp'
    exe = Path(directory) / 'shoulder_camera.exe'
    cpp.write_text(harness)
    subprocess.run(['g++', '-std=c++17', str(cpp), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('PASS: shoulder-camera crouch tracking, idle deadband, avatar proportions, zoom blend, stand-up recovery, bounded poses and inactive modes.')
