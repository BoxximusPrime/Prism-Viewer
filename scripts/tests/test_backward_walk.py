"""Exercise production backward-walk input and packet preparation with Python + g++."""
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "indra/newview/llagent.cpp").read_text()
constants = (ROOT / "indra/llcommon/indra_constants.h").read_text()


def function(signature, text=source):
    start = text.index(signature)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


harness = r'''
#include <cassert>
#include <cstdint>
#include <initializer_list>
#include <cmath>
#include <algorithm>
#include <type_traits>
using U32 = uint32_t;
using S32 = int;
using F32 = float;
constexpr float F_PI = 3.14159265f;
constexpr float DEG_TO_RAD = F_PI / 180;
constexpr int VZ=2, CAMERA_MODE_THIRD_PERSON=0, CAMERA_MODE_FOLLOW=1, SELECT_TYPE_HUD=1;
struct Settings {bool relative=false;} gSavedSettings;
template<class T> struct LLCachedControl {
    T fallback;
    LLCachedControl(Settings&,const char*,T value):fallback(value) {}
    operator T() const {
        if constexpr(std::is_same_v<T,bool>) return gSavedSettings.relative;
        else return fallback;
    }
};
struct Avatar {bool sitting=false;bool isSitting() const {return sitting;}} avatar;
Avatar* gAgentAvatarp=&avatar;
bool avatar_valid=true;
bool isAgentAvatarValid() {return avatar_valid;}
struct LLPoseStudio {
    bool active=false;
    static bool instanceExists() {return true;}
    static LLPoseStudio& instance() {static LLPoseStudio p;return p;}
    bool isActive() const {return active;}
};
template<class T> T llclamp(T x,T lo,T hi) {return std::clamp(x,lo,hi);}
float clamp_rescale(float x,float lo,float hi,float a,float b) {
    return a+(b-a)*std::clamp((x-lo)/(hi-lo),0.f,1.f);
}
struct LLVector3 {
    float mV[3];
    LLVector3(float x=0,float y=0,float z=0):mV{x,y,z}{}
    LLVector3 operator+(LLVector3 b) const {return {mV[0]+b.mV[0],mV[1]+b.mV[1],mV[2]+b.mV[2]};}
    LLVector3 operator*(float s) const {return {mV[0]*s,mV[1]*s,mV[2]*s};}
    float operator*(LLVector3 b) const {return mV[0]*b.mV[0]+mV[1]*b.mV[1]+mV[2]*b.mV[2];}
    LLVector3 operator%(LLVector3 b) const {return {mV[1]*b.mV[2]-mV[2]*b.mV[1],mV[2]*b.mV[0]-mV[0]*b.mV[2],mV[0]*b.mV[1]-mV[1]*b.mV[0]};}
    float normalize() {float n=std::sqrt(*this * *this); if(n>0)*this=*this*(1/n);return n;}
    void rotVec(float a,LLVector3 axis) { *this=*this*std::cos(a)+(axis%*this)*std::sin(a)+axis*((axis * *this)*(1-std::cos(a))); }
    void rotVec(float a,float x,float y,float z) {rotVec(a,{x,y,z});}
    void setVec(LLVector3 v) {*this=v;}
    static const LLVector3 z_axis;
};
const LLVector3 LLVector3::z_axis{0,0,1};
using LLVector3d=LLVector3;
struct LLCoordFrame {
    LLVector3 at{1,0,0},left{0,1,0};
    LLVector3 getAtAxis() const {return at;}
    LLVector3 getLeftAxis() const {return left;}
    void rotate(float a,LLVector3 axis) {at.rotVec(a,axis);left.rotVec(a,axis);}
    void pitch(float a) {rotate(a,left);}
};
struct LLViewerCamera {
    LLVector3 at{1,0,0};
    static LLViewerCamera& instance(){static LLViewerCamera camera;return camera;}
    static LLViewerCamera* getInstance(){return &instance();}
    LLVector3 getAtAxis() const{return at;}
    LLVector3 getLeftAxis() const{return LLVector3::z_axis%at;}
};
struct Selection {int getObjectCount(){return 0;} int getSelectType(){return 0;}} selection;
using LLObjectSelectionHandle=Selection*;
struct LLSelectMgr {
    static LLSelectMgr* getInstance(){static LLSelectMgr s;return &s;}
    Selection* getSelection(){return &selection;}
};
struct LLUIUsage {
    static LLUIUsage& instance() { static LLUIUsage value; return value; }
    void logCommand(const char*) {}
};
struct LLFirstUse { static void notMoving(bool) {} };
struct LLAgentCamera {
    int at = 0, walk = 0, left = 0;
    static int directionToKey(int direction) { return (direction > 0) - (direction < 0); }
    void setAtKey(int value) { at = value; }
    void setWalkKey(int value) { walk = value; }
    void setLeftKey(int value) { left = value; }
    int getAtKey() const { return at; }
    int getWalkKey() const { return walk; }
    int getLeftKey() const { return left; }
    int resets=0;
    void resetView() {++resets;if(!mFocusOnAvatar){mFocusOnAvatar=true;mCameraAnimating=true;}}
    bool mFocusOnAvatar=true;
    bool mCameraAnimating=false,mReturningToAvatarBeforeMovement=false;
    bool returnToAvatarBeforeMovement();
    void stopCameraAnimation();
    int mCameraMode=CAMERA_MODE_THIRD_PERSON;
    int getCameraMode() const {return mCameraMode;}
    mutable LLCoordFrame mThirdPersonFrame;
    mutable bool mCameraRelativeActive=false;
    LLVector3 mCameraFocusOffsetTarget{-3,0,1};
    float mOrbitAroundRadians=0,mOrbitOverAngle=0;
    void cameraZoomIn(float) {}
    const LLCoordFrame& getThirdPersonFrame() const;
    void cameraOrbitAround(float);
    void cameraOrbitOver(float);
    void slamLookAt(const LLVector3&);
} gAgentCamera;
struct LLAgent {
    struct Timer { void reset() {} } mMoveTimer;
    bool enabled = true, mFacingBackwardWalk = false;
    bool flying=false,autopilot=false,grabbed=false,locked=false;
    LLCoordFrame frame;
    U32 mControlFlags = 0;
    int heading = 1, turns = 0;
    void ageChat() {}
    bool shouldFaceBackwardWalk() const { return enabled; }
    LLVector3 getReferenceUpVector() { return LLVector3::z_axis; }
    void rotate(float angle, LLVector3 axis) { heading = -heading; ++turns; frame.rotate(angle,axis); }
    void yaw(float angle) {frame.rotate(angle,LLVector3::z_axis);}
    void pitch(float angle) {frame.pitch(angle);}
    bool useCameraRelativeMovement() const;
    bool mCameraRelativeTurning=false;
    void setCameraRelativeTurning(bool turning) {mCameraRelativeTurning=turning;}
    bool getFlying() const {return flying;}
    bool getAutoPilot() const {return autopilot;}
    bool rotateGrabbed() const {return grabbed;}
    bool isMovementLocked() const {return locked;}
    bool isFacingBackwardWalk() const {return mFacingBackwardWalk;}
    const LLCoordFrame& getFrameAgent() const {return frame;}
    void resetAxes(LLVector3 at) {frame.at=at;frame.left=LLVector3::z_axis%at;}
    void setControlFlags(U32 flags) { mControlFlags |= flags; }
    void moveAt(S32 direction, bool reset = true);
    void moveAtNudge(S32 direction);
    void moveLeft(S32 direction);
    void moveLeftNudge(S32 direction);
    void updateBackwardWalk();
    U32 prepareControlFlagsForUpdate();
};
LLAgent gAgent;
'''
harness += "\n".join(re.findall(
    r"constexpr U32 (?:CONTROL_\w+|AGENT_CONTROL_\w+)\s*=.*?;", constants)) + "\n"
for name in ("void LLAgent::moveAt(", "void LLAgent::moveAtNudge(",
             "void LLAgent::moveLeft(", "void LLAgent::moveLeftNudge(",
             "void LLAgent::updateBackwardWalk(", "bool LLAgent::useCameraRelativeMovement(",
             "U32 LLAgent::prepareControlFlagsForUpdate("):
    harness += function(name) + "\n"
camera = (ROOT / "indra/newview/llagentcamera.cpp").read_text()
for signature in ("bool LLAgentCamera::returnToAvatarBeforeMovement(", "void LLAgentCamera::stopCameraAnimation(", "void LLAgentCamera::slamLookAt(", "const LLCoordFrame& LLAgentCamera::getThirdPersonFrame(",
                  "void LLAgentCamera::cameraOrbitAround(", "void LLAgentCamera::cameraOrbitOver("):
    harness += function(signature, camera) + "\n"
avatar_source = (ROOT / "indra/newview/llvoavatar.cpp").read_text()
start = avatar_source.index('            static LLCachedControl<F32> s_pelvis_rot_threshold_slow')
end = avatar_source.index('            pelvis_rot_threshold *= DEG_TO_RAD;', start)
threshold = avatar_source[start:end].replace('isSelf()', 'self')
harness += '''
constexpr float MOUSELOOK_PELVIS_FOLLOW_FACTOR=.5f;
float pelvisThreshold(LLAgent& agent,float speed,bool self,bool self_in_mouselook=false) {
''' + threshold + '\nreturn pelvis_rot_threshold;\n}\n'
start = avatar_source.index('            if (isSelf() && !mTurning)')
end = avatar_source.index('            if (isSelf() && mTurning)', start)
harness += 'void finishFacing(LLAgent& agent,bool self,bool mTurning) {\n' + avatar_source[start:end].replace('isSelf()', 'self') + '\n}\n'
window_source = (ROOT / 'indra/newview/llviewerwindow.cpp').read_text()
start = window_source.index('    // Consume the entire face-camera gesture')
end = window_source.index('    // Handle non-consuming global keybindings', start)
harness += r'''
enum EMouseClickType {CLICK_LEFT, CLICK_RIGHT, CLICK_MIDDLE};
using MASK=int;
constexpr MASK MASK_NONE=0;
struct LLMouseHandler {};
struct LLToolCamera : LLMouseHandler {
    static LLToolCamera* getInstance() {static LLToolCamera t;return &t;}
};
struct LLToolPie : LLMouseHandler {
    static LLToolPie* getInstance() {static LLToolPie t;return &t;}
};
struct LLToolMgr {
    LLMouseHandler* current=LLToolPie::getInstance();
    static LLToolMgr* getInstance() {static LLToolMgr m;return &m;}
    LLMouseHandler* getCurrentTool() {return current;}
};
struct FocusMgr {
    LLMouseHandler* captor=nullptr;
    LLMouseHandler* getMouseCapture() {return captor;}
} gFocusMgr;
struct LLViewerWindow {
    bool mLeftMouseDown=false,mRightMouseDown=false,mCameraRelativeRightClick=false;
    bool click(EMouseClickType clicktype,bool down,MASK mask=MASK_NONE) {
''' + window_source[start:end] + 'return false;\n}\n};\n'
harness += r'''
constexpr U32 lateral = AGENT_CONTROL_LEFT_POS | AGENT_CONTROL_LEFT_NEG |
    AGENT_CONTROL_NUDGE_LEFT_POS | AGENT_CONTROL_NUDGE_LEFT_NEG | AGENT_CONTROL_FAST_LEFT;
constexpr U32 unrelated = AGENT_CONTROL_UP_POS | AGENT_CONTROL_YAW_POS | AGENT_CONTROL_LBUTTON_DOWN;
void beginFrame(LLAgent& agent) {
    agent.mControlFlags = unrelated;
    gAgentCamera.at=gAgentCamera.walk=gAgentCamera.left=0;
}
U32 packet(LLAgent& agent) {
    const U32 raw = agent.mControlFlags;
    const U32 result = agent.prepareControlFlagsForUpdate();
    const int turns = agent.turns;
    assert(agent.prepareControlFlagsForUpdate() == result);
    assert(agent.turns == turns && agent.mControlFlags == raw);
    assert((result & unrelated) == unrelated);
    return result;
}
int main() {
    // Detached-camera taps return the camera; only continuing input moves afterward.
    for(int control=0;control<4;++control) for(int direction : {-1,1}) {
        gAgent={};gAgentCamera={};gSavedSettings.relative=true;
        gAgentCamera.mFocusOnAvatar=false;
        auto press=[&] {
            switch(control) {
                case 0:gAgent.moveAt(direction);break;
                case 1:gAgent.moveAtNudge(direction);break;
                case 2:gAgent.moveLeft(direction);break;
                case 3:gAgent.moveLeftNudge(direction);break;
            }
        };
        beginFrame(gAgent);press();
        assert(packet(gAgent)==unrelated);
        assert(gAgentCamera.mFocusOnAvatar && gAgentCamera.mCameraAnimating);
        assert(gAgentCamera.resets==1);
        for(int frame=0;frame<10;++frame) {
            beginFrame(gAgent);press();
            assert(packet(gAgent)==unrelated);
            assert(gAgentCamera.resets==1); // Held input never restarts the return.
        }
        gAgentCamera.mCameraAnimating=false;
        beginFrame(gAgent);
        assert(packet(gAgent)==unrelated); // Releasing during return queues no movement.
        press();
        assert(packet(gAgent)&(AGENT_CONTROL_AT_POS | AGENT_CONTROL_NUDGE_AT_POS));
        assert(!gAgentCamera.mReturningToAvatarBeforeMovement);
    }
    gAgent={};gAgentCamera={};gSavedSettings.relative=true;
    gAgentCamera.mFocusOnAvatar=false;
    beginFrame(gAgent);gAgent.moveAt(1);
    gAgentCamera.stopCameraAnimation();
    assert(!gAgentCamera.mReturningToAvatarBeforeMovement);
    gAgentCamera.mCameraAnimating=true;
    beginFrame(gAgent);gAgent.moveAt(1);
    assert(packet(gAgent)&AGENT_CONTROL_AT_POS); // An ended return cannot gate a later animation.
    gAgent={};gAgentCamera={};gSavedSettings.relative=true;
    gAgentCamera.mCameraAnimating=true;
    beginFrame(gAgent);gAgent.moveAt(1);
    assert(packet(gAgent)&AGENT_CONTROL_AT_POS); // Other camera animations add no delay.
    gAgentCamera={};gAgentCamera.mFocusOnAvatar=false;gSavedSettings.relative=false;
    beginFrame(gAgent);gAgent.moveAt(1);
    assert(packet(gAgent)&AGENT_CONTROL_AT_POS); // Default controls retain immediate movement.
    // The chord turns only the body and consumes its release in either order.
    {
        gAgent={};gAgentCamera={};gSavedSettings.relative=true;
        gAgentCamera.cameraOrbitAround(F_PI/2);
        LLViewerCamera::instance().at={0,1,0};
        LLViewerWindow window;
        assert(!window.click(CLICK_RIGHT,true));
        window.mLeftMouseDown=true;
        assert(!window.click(CLICK_MIDDLE,true)); // Voice button passes through.
        assert(!window.click(CLICK_RIGHT,true,1));
        LLMouseHandler ui;
        gFocusMgr.captor=&ui;
        assert(!window.click(CLICK_RIGHT,true));
        gFocusMgr.captor=LLToolCamera::getInstance();
        assert(window.click(CLICK_RIGHT,true));
        assert(gAgent.mCameraRelativeTurning);
        assert(gAgent.frame.at.mV[1]>.9999f && gAgent.mControlFlags==0);
        assert(gAgentCamera.getThirdPersonFrame().at.mV[1]>.9999f);
        window.mLeftMouseDown=false;gSavedSettings.relative=false;
        assert(window.click(CLICK_RIGHT,false));
        assert(!window.mRightMouseDown && !window.mCameraRelativeRightClick);
        assert(!window.click(CLICK_RIGHT,true));
        window.mLeftMouseDown=true;
        assert(!window.click(CLICK_RIGHT,true)); // Disabled mode passes through.
        gSavedSettings.relative=true;
        LLViewerCamera::instance().at={0,0,1};
        assert(window.click(CLICK_RIGHT,true)); // Vertical view falls back to orbit frame.
        assert(gAgent.frame.at.mV[1]>.9999f && gAgent.frame.at.mV[2]==0);
        assert(window.click(CLICK_RIGHT,false)); // Left can remain held on release.
        assert(!window.click(CLICK_RIGHT,false));
        gFocusMgr.captor=nullptr;
        assert(window.click(CLICK_RIGHT,true)); // World click before starting a drag.
        assert(window.click(CLICK_RIGHT,false));
        const U32 turn_flags=AGENT_CONTROL_TURN_LEFT | AGENT_CONTROL_TURN_RIGHT;
        beginFrame(gAgent);gAgent.setControlFlags(turn_flags);
        assert(packet(gAgent)==(unrelated | turn_flags)); // Chord permits turn animation.
        finishFacing(gAgent,false,false);
        assert(gAgent.mCameraRelativeTurning); // Other avatars cannot end our turn.
        finishFacing(gAgent,true,true);
        assert(gAgent.mCameraRelativeTurning);
        finishFacing(gAgent,true,false);
        assert(packet(gAgent)==unrelated); // Permission ends once hips finish turning.
        gAgent.setCameraRelativeTurning(true);
        gAgent.moveAt(1);
        assert(!(packet(gAgent)&turn_flags)); // Movement cancels a chord turn.
        assert(!gAgent.mCameraRelativeTurning);
        beginFrame(gAgent);gAgent.setControlFlags(turn_flags);
        assert(packet(gAgent)==unrelated); // Release cannot trigger a catch-up animation.
        gSavedSettings.relative=false;
        assert(packet(gAgent)==(unrelated | turn_flags)); // Default mode remains unchanged.
    }
    gAgent={};gAgentCamera={};gSavedSettings.relative=false;
    // Packet preparation must survive the camera clearing its transient keys.
    // This fails against the original backward-walk implementation.
    {
        LLAgent agent;
        for(int frame=0;frame<120;++frame) {
            beginFrame(agent); agent.moveAt(-1);
            gAgentCamera.at=gAgentCamera.walk=gAgentCamera.left=0;
            assert(packet(agent)&AGENT_CONTROL_AT_POS);
            assert(agent.heading==-1 && agent.turns==1);
        }
        beginFrame(agent); packet(agent);
        assert(agent.heading==1 && agent.turns==2);
    }
    // Hold S throughout A -> overlap -> D -> overlap -> A. Exercise either
    // input scan order and every combination of new (nudge) and held keys.
    for (bool at_first : {false, true}) {
        LLAgent agent;
        for (int cycle = 0; cycle < 100; ++cycle) {
            for (int direction : {1, -1}) {
                for (bool old_nudge : {false, true})
                for (bool new_nudge : {false, true}) {
                    beginFrame(agent);
                    if (at_first) agent.moveAt(-1);
                    if (old_nudge) agent.moveLeftNudge(-direction);
                    else agent.moveLeft(-direction);
                    if (new_nudge) agent.moveLeftNudge(direction);
                    else agent.moveLeft(direction);
                    if (!at_first) agent.moveAt(-1);
                    U32 flags = packet(agent);
                    assert((flags & lateral) == 0); // Opposites cancel, regardless of strength.
                    assert(flags & AGENT_CONTROL_AT_POS);
                    assert(agent.heading == -1 && agent.turns == 1);

                    // Release the old direction. A newly pressed key has the
                    // same strength as a held key during an ongoing S walk.
                    beginFrame(agent);
                    if (at_first) agent.moveAt(-1);
                    if (new_nudge) agent.moveLeftNudge(direction);
                    else agent.moveLeft(direction);
                    if (!at_first) agent.moveAt(-1);
                    flags = packet(agent);
                    const U32 expected = (direction > 0 ? AGENT_CONTROL_LEFT_NEG : AGENT_CONTROL_LEFT_POS)
                        | AGENT_CONTROL_FAST_LEFT;
                    assert((flags & lateral) == expected);
                    const int body_left = bool(flags & AGENT_CONTROL_LEFT_POS) - bool(flags & AGENT_CONTROL_LEFT_NEG);
                    assert(agent.heading * body_left == direction);
                    assert(agent.turns == 1);
                }
            }
        }
        // Releasing S must not flip the body and reverse the lateral control
        // during a continuous strafe (mouse-steer A/D routes to moveLeft).
        beginFrame(agent);
        agent.moveLeft(1);
        assert((packet(agent) & lateral) == (AGENT_CONTROL_LEFT_NEG | AGENT_CONTROL_FAST_LEFT));
        assert(agent.heading == -1 && agent.mFacingBackwardWalk && agent.turns == 1);
        beginFrame(agent); // Finish the strafe before restoring the heading.
        assert(packet(agent) == unrelated);
        assert(agent.heading == 1 && !agent.mFacingBackwardWalk && agent.turns == 2);
    }
    for (int direction : {1, -1}) {
        for (bool nudge : {false, true}) {
            LLAgent agent;
            beginFrame(agent);
            agent.moveAt(-1);
            agent.moveLeft(direction);
            const U32 diagonal = packet(agent);
            for (int frame = 0; frame < 60; ++frame) {
                beginFrame(agent); // S released; keep the same strafe held.
                if (nudge) agent.moveLeftNudge(direction);
                else agent.moveLeft(direction);
                const U32 flags = packet(agent);
                assert(agent.heading == -1 && agent.turns == 1);
                const int body_left = bool(flags & (AGENT_CONTROL_LEFT_POS | AGENT_CONTROL_NUDGE_LEFT_POS))
                    - bool(flags & (AGENT_CONTROL_LEFT_NEG | AGENT_CONTROL_NUDGE_LEFT_NEG));
                assert(agent.heading * body_left == direction);
                if (!nudge) assert((flags & lateral) == (diagonal & lateral));
                assert(!(flags & (AGENT_CONTROL_AT_POS | AGENT_CONTROL_AT_NEG |
                                  AGENT_CONTROL_NUDGE_AT_POS | AGENT_CONTROL_NUDGE_AT_NEG)));
            }
            beginFrame(agent);
            agent.moveAt(1); // W ends the retained backward-facing strafe.
            agent.moveLeft(direction);
            const U32 flags = packet(agent);
            assert(agent.heading == 1 && agent.turns == 2);
            assert(flags & AGENT_CONTROL_AT_POS);
            assert((flags & lateral) == ((direction > 0 ? AGENT_CONTROL_LEFT_POS : AGENT_CONTROL_LEFT_NEG)
                                        | AGENT_CONTROL_FAST_LEFT));
        }
    }
    for (bool enabled : {false, true}) {
        LLAgent agent;
        agent.enabled = enabled;
        beginFrame(agent);
        agent.moveAtNudge(-1);
        agent.moveLeftNudge(1);
        U32 flags = packet(agent);
        if (enabled) {
            assert(agent.heading == -1);
            assert(flags == (unrelated | AGENT_CONTROL_NUDGE_AT_POS | AGENT_CONTROL_NUDGE_LEFT_NEG));
            agent.enabled = false; // Option/camera/flight eligibility changed.
            assert(packet(agent) == agent.mControlFlags && agent.heading == 1);
        } else {
            assert(flags == agent.mControlFlags && agent.heading == 1);
        }
    }
    // All eight camera-relative directions, including mixed tap/held diagonals.
    for (float yaw : {0.f,90.f,180.f,270.f}) {
        gAgent={};gSavedSettings.relative=true;gAgentCamera={};
        gAgentCamera.cameraOrbitAround(yaw*DEG_TO_RAD);
        const LLVector3 camera_at=gAgentCamera.getThirdPersonFrame().getAtAxis();
        LLViewerCamera::instance().at=camera_at;
        assert(gAgent.frame.at.mV[0]==1); // Orbit does not turn the body.
        for (int at : {-1,0,1}) for(int left : {-1,0,1}) {
            if(!at && !left)continue;
            for(bool nudge : {false,true}) for(bool left_nudge : {false,true})
            for(bool at_first : {false,true}) {
                beginFrame(gAgent);
                auto move_at=[&]{if(nudge)gAgent.moveAtNudge(at);else gAgent.moveAt(at);};
                if(at_first)move_at();
                if(left_nudge)gAgent.moveLeftNudge(left);else gAgent.moveLeft(left);
                if(!at_first)move_at();
                U32 flags=packet(gAgent);
                LLVector3 expected=camera_at*float(at)+(LLVector3::z_axis%camera_at)*float(left);
                expected.normalize();
                assert(gAgent.frame.at*expected>.9999f);
                assert(!(flags&(lateral|AGENT_CONTROL_AT_NEG|AGENT_CONTROL_NUDGE_AT_NEG)));
                const bool held=(!nudge && at) || (!left_nudge && left);
                assert(flags==(unrelated | (held ? AGENT_CONTROL_AT_POS | AGENT_CONTROL_FAST_AT : AGENT_CONTROL_NUDGE_AT_POS)));
                assert(gAgentCamera.getThirdPersonFrame().getAtAxis()*camera_at>.9999f);
                for(int idle=0;idle<10;++idle) {
                    beginFrame(gAgent); assert(packet(gAgent)==unrelated);
                    assert(gAgent.frame.at*expected>.9999f); // Release retains facing.
                }
            }
        }
        beginFrame(gAgent);
        gAgent.moveAt(1);gAgent.moveAtNudge(-1);
        gAgent.moveLeft(1);gAgent.moveLeftNudge(-1);
        assert(packet(gAgent)==unrelated); // Opposite keys cancel at either strength.
    }
    // Backward-walk -> independent mode retains the same camera frame.
    gAgent={};gAgentCamera={};gSavedSettings.relative=false;
    beginFrame(gAgent);gAgent.moveAt(-1);packet(gAgent);
    gSavedSettings.relative=true;
    assert(gAgentCamera.getThirdPersonFrame().getAtAxis().mV[0]>.9999f);
    LLViewerCamera::instance().at={1,0,0};
    packet(gAgent);beginFrame(gAgent);packet(gAgent);
    assert(gAgent.frame.at.mV[0]<-.9999f && !gAgent.mFacingBackwardWalk);
    // Pitch stays bounded, stays out of the body, and does not tilt movement.
    gAgentCamera.cameraOrbitOver(100);
    assert(std::abs(gAgentCamera.getThirdPersonFrame().at.mV[2])<.999f);
    assert(gAgent.frame.at.mV[0]<-.9999f);
    gAgentCamera.cameraOrbitOver(-100);
    LLViewerCamera::instance().at={0,0,1}; // vertical view has a stable fallback.
    beginFrame(gAgent);gAgent.moveAt(1);packet(gAgent);
    assert(gAgent.frame.at.mV[0]>.9999f && gAgent.frame.at.mV[2]==0);
    gSavedSettings.relative=false;
    assert(gAgentCamera.getThirdPersonFrame().at*gAgent.frame.at>.9999f);
    assert(!gAgentCamera.mCameraRelativeActive);
    gSavedSettings.relative=true;
    assert(pelvisThreshold(gAgent,0,true)==2); // Explicit idle facing turns the hips.
    assert(pelvisThreshold(gAgent,0,false)==60); // Other avatars keep normal idle behavior.
    gSavedSettings.relative=false;
    assert(pelvisThreshold(gAgent,0,true)==60);
    assert(pelvisThreshold(gAgent,2,true)==2);
    assert(pelvisThreshold(gAgent,0,true,true)==30);
    gSavedSettings.relative=true;
    for(bool* blocked : {&gAgent.flying,&gAgent.autopilot,&gAgent.grabbed,&gAgent.locked,
                         &avatar.sitting,&LLPoseStudio::instance().active}) {
        assert(gAgent.useCameraRelativeMovement());
        *blocked=true;
        assert(!gAgent.useCameraRelativeMovement());
        *blocked=false;
    }
    avatar_valid=false;assert(!gAgent.useCameraRelativeMovement());avatar_valid=true;
    for(int mode : {1,2,3}) {gAgentCamera.mCameraMode=mode;assert(!gAgent.useCameraRelativeMovement());}
}
'''

with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / "backward_walk.cpp"
    exe = Path(directory) / "backward_walk.exe"
    cpp.write_text(harness)
    subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
settings=ET.parse(ROOT/'indra/newview/app_settings/settings.xml').getroot().find('map')
entries=list(settings)
entry=entries[next(i for i,e in enumerate(entries) if e.tag=='key' and e.text=='BoxxyCameraRelativeMovement')+1]
assert entry.find("./integer[last()]").text=='0'
panel=ET.parse(ROOT/'indra/newview/skins/default/xui/en/panel_preferences_move.xml')
assert panel.find('.//check_box[@control_name="BoxxyCameraRelativeMovement"]') is not None
assert 'updateBackwardWalk();' not in function('void LLAgent::propagate(')
print("PASS: backward-walk input snapshots, immediate camera-relative movement, detached-camera return with tap/hold checks, retained facing, independent orbit/pitch, face-camera mouse chord, gesture-only turn animation, release ordering, UI/modifier guards and voice-button pass-through.")
