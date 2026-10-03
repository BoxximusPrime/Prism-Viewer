"""Run the production final-camera smoothing methods with small viewer API stubs.

Run: python scripts/tests/test_camera_smoothing.py (requires g++ on PATH).
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def function(path, signature):
    source = (ROOT / path).read_text()
    start = source.index(signature)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def main():
    camera = 'indra/newview/llviewercamera.cpp'
    header = (ROOT / 'indra/newview/llviewercamera.h').read_text()
    fields = header[header.index('    // World-space history'):header.index('\npublic:\n};')]
    code = r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include <initializer_list>
using F32 = float;
constexpr float DEFAULT_FIELD_OF_VIEW = 1.f;
template<class T> T llclamp(T v, T lo, T hi) { return std::clamp(v, lo, hi); }
template<class T> T llmax(T a, T b) { return std::max(a, b); }
struct LLVector3d {
    double x=0, y=0, z=0;
    LLVector3d operator+(LLVector3d b) const { return {x+b.x,y+b.y,z+b.z}; }
    LLVector3d operator-(LLVector3d b) const { return {x-b.x,y-b.y,z-b.z}; }
    LLVector3d operator*(float t) const { return {x*t,y*t,z*t}; }
};
template<class T> T lerp(T a, T b, float t) { return a+(b-a)*t; }
struct LLQuaternion { float mQ[4]={0,0,0,1}; };
struct LLAgent {
    enum { TELEPORT_NONE, TELEPORT_MOVING };
    int teleport=TELEPORT_NONE;
    LLVector3d region;
    LLVector3d getPosGlobalFromAgent(LLVector3d p) { return p+region; }
    LLVector3d getPosAgentFromGlobal(LLVector3d p) { return p-region; }
    int getTeleportState() { return teleport; }
} gAgent;
struct Settings {
    float smoothing=.1f;
    Settings& operator=(float value) { smoothing=value; return *this; }
    float getF32(const char*) const { return .4f; } // ZoomTime
} gSavedSettings;
bool gCubeSnapshot=false;
struct { bool animated=false; bool useAnimatedMouselook() const { return animated; } } gAgentCamera;
template<class T> struct LLCachedControl {
    LLCachedControl(Settings&, const char*) {}
    operator T() const { return gSavedSettings.smoothing; }
};
struct LLSmoothInterpolation {
    static inline float sTimeDelta=.1f;
    static float calcInterpolant(float);
    static float getInterpolant(float half_life, bool) { return calcInterpolant(half_life); }
};
struct LLViewerCamera {
    static inline LLViewerCamera* instance=nullptr;
    static LLViewerCamera* getInstance() { return instance; }
    LLVector3d origin;
    LLQuaternion rotation;
    float fov=1, mCosHalfCameraFOV=0;
    LLVector3d getOrigin() const { return origin; }
    LLQuaternion getQuaternion() const { return rotation; }
    float getView() const { return fov; }
    float getAspect() const { return 1.5f; }
    void setOrigin(LLVector3d p) { origin=p; }
    void setAxes(LLQuaternion q) { rotation=q; }
    void setViewNoBroadcast(float v) { fov=v; }
    void prepareCameraSmoothing();
    void applyCameraSmoothing();
    void resetCameraSmoothing();
    LLVector3d getTargetPositionGlobal() const;
''' + fields + '\n};\n'
    code += function('indra/llmath/llquaternion.cpp', 'LLQuaternion slerp( F32 u,')
    code += '\n' + function('indra/llcommon/llcriticaldamp.cpp', 'F32 LLSmoothInterpolation::calcInterpolant(')
    for name in ('resetCameraSmoothing', 'prepareCameraSmoothing', 'applyCameraSmoothing'):
        code += '\n' + function(camera, f'void LLViewerCamera::{name}(')
    code += '\n' + function(camera, 'LLVector3d LLViewerCamera::getTargetPositionGlobal(')
    code += r'''
struct LLAgentCamera {
    LLVector3d mAnimationCameraStartGlobal, mAnimationFocusStartGlobal, mFocusGlobal;
    bool mCameraAnimating=false;
    float mAnimationDuration=0;
    struct Timer { int resets=0; void reset() { ++resets; } } mAnimationTimer;
    void setAnimationDuration(float duration) { mAnimationDuration=duration; }
    LLVector3d getCameraPositionGlobal() const { return gAgent.getPosGlobalFromAgent(LLViewerCamera::getInstance()->getOrigin()); }
    void startCameraAnimation();
};
'''
    code += '\n' + function('indra/newview/llagentcamera.cpp', 'void LLAgentCamera::startCameraAnimation(')
    code += r'''
bool near(double a, double b) { return std::abs(a-b)<.0001; }
LLQuaternion yaw(float degrees) {
    float half=degrees*3.14159265358979323846f/360;
    return {{0,0,sinf(half),cosf(half)}};
}
void sameRotation(LLQuaternion a, LLQuaternion b) {
    float dot=0, norm=0;
    for (int i=0;i<4;++i) { dot+=a.mQ[i]*b.mQ[i]; norm+=a.mQ[i]*a.mQ[i]; }
    assert(near(std::abs(dot),1) && near(norm,1));
}
void target(LLViewerCamera& c) { c.origin={10,20,30}; c.rotation=yaw(90); c.fov=.5f; }
int main() {
    LLViewerCamera c;
    LLViewerCamera::instance=&c;
    c.origin={100,200,300};
    c.applyCameraSmoothing();
    assert(near(c.origin.x,100)); // First frame never flies in from the origin.
    c={}; c.applyCameraSmoothing(); target(c); c.applyCameraSmoothing();
    assert(near(c.origin.x,5) && near(c.origin.y,10) && near(c.origin.z,15));
    sameRotation(c.rotation,yaw(45)); assert(near(c.fov,.75));
    c.prepareCameraSmoothing(); // Idle controller must retain its unsmoothed target.
    assert(near(c.origin.x,10) && near(c.fov,.5)); sameRotation(c.rotation,yaw(90));
    c.applyCameraSmoothing();
    assert(near(c.origin.x,7.5)); sameRotation(c.rotation,yaw(67.5));
    assert(near(c.fov,.625));

    // An Alt-click arrives between frames, while the rendered camera is still
    // catching up. The legacy transition must not rebase onto that lagged pose.
    c={}; c.applyCameraSmoothing(); target(c); c.applyCameraSmoothing();
    LLAgentCamera agent_camera;
    agent_camera.mFocusGlobal={20,30,0};
    for (int click=0;click<4;++click) {
        agent_camera.startCameraAnimation();
        assert(near(agent_camera.mAnimationCameraStartGlobal.x,10));
        assert(near(agent_camera.mAnimationFocusStartGlobal.x,20));
        assert(agent_camera.mCameraAnimating && near(agent_camera.mAnimationDuration,.4));
        c.prepareCameraSmoothing();
        // The first frame of each newly started legacy transition has t=0.
        c.origin=lerp(agent_camera.mAnimationCameraStartGlobal,LLVector3d{10,20,30},0.f);
        c.applyCameraSmoothing();
        assert(near(c.origin.x,10*(1-std::pow(.5,click+2))));
    }
    assert(agent_camera.mAnimationTimer.resets==4);
    gSavedSettings=0;
    c.prepareCameraSmoothing(); c.applyCameraSmoothing();
    assert(near(c.origin.x,10) && near(c.fov,.5)); sameRotation(c.rotation,yaw(90));
    c.origin={30,40,50}; c.applyCameraSmoothing(); assert(near(c.origin.x,30));
    agent_camera.startCameraAnimation();
    assert(near(agent_camera.mAnimationCameraStartGlobal.x,30)); // Disabled = ordinary camera pose.
    gSavedSettings=.1f; c.origin={40,50,60}; c.applyCameraSmoothing();
    assert(near(c.origin.x,35)); // Enabling live uses current history.

    // Same response at different frame rates, including after input stops.
    for (int fps : {30,60,144}) {
        c={}; c.applyCameraSmoothing(); target(c);
        LLSmoothInterpolation::sTimeDelta=1.f/fps;
        for (int frame=0;frame<fps;++frame) {
            c.prepareCameraSmoothing(); c.applyCameraSmoothing();
        }
        const float remaining=std::pow(2.f,-10.f);
        assert(near(c.origin.x,10*(1-remaining)));
        assert(near(c.fov,.5+.5*remaining));
        sameRotation(c.rotation,yaw(90*(1-remaining)));
    }
    LLSmoothInterpolation::sTimeDelta=.1f;
    c={}; c.rotation=yaw(179); c.applyCameraSmoothing();
    c.rotation=yaw(-179); c.applyCameraSmoothing();
    sameRotation(c.rotation,yaw(180)); // Short path across the angle wrap.
    c={}; c.applyCameraSmoothing(); c.rotation=yaw(180); c.applyCameraSmoothing();
    sameRotation(c.rotation,yaw(-90)); // No zero-length look direction at a half-turn.

    c={}; c.applyCameraSmoothing(); target(c); c.applyCameraSmoothing();
    gAgent.region={256,0,0}; c.prepareCameraSmoothing();
    assert(near(gAgent.getPosGlobalFromAgent(c.origin).x,10));
    c.applyCameraSmoothing(); assert(near(gAgent.getPosGlobalFromAgent(c.origin).x,7.5));
    agent_camera.startCameraAnimation();
    assert(near(agent_camera.mAnimationCameraStartGlobal.x,10)); // Region origin must not leak into the target.
    gAgent.region={};
    c.resetCameraSmoothing(); c.origin={10000,20000,30000}; c.fov=1.2f;
    c.prepareCameraSmoothing(); c.applyCameraSmoothing();
    assert(near(c.origin.x,10000) && near(c.fov,1.2f)); // Teleport snap.
    gAgent.teleport=LLAgent::TELEPORT_MOVING;
    c.origin={10010,20000,30000}; c.applyCameraSmoothing(); assert(near(c.origin.x,10010));
    gAgent.teleport=LLAgent::TELEPORT_NONE;

    c={}; c.applyCameraSmoothing(); target(c); c.applyCameraSmoothing();
    gCubeSnapshot=true; c.origin={99,99,99}; c.rotation=yaw(30); c.fov=1.3f;
    c.prepareCameraSmoothing(); c.applyCameraSmoothing();
    assert(near(c.origin.x,99) && near(c.fov,1.3f)); sameRotation(c.rotation,yaw(30));
    gCubeSnapshot=false; c.prepareCameraSmoothing(); c.applyCameraSmoothing();
    assert(near(c.origin.x,7.5)); // Capture did not alter history.
    gAgentCamera.animated=true; gSavedSettings=.5f;
    c={}; c.applyCameraSmoothing(); target(c); c.applyCameraSmoothing();
    assert(near(c.origin.x,10)); sameRotation(c.rotation,yaw(90));
    gAgentCamera.animated=false;
    for (float setting : {-1.f,0.f,1.f,5.f}) {
        gSavedSettings=setting; c={}; c.applyCameraSmoothing(); target(c); c.applyCameraSmoothing();
        const float blend=setting<=0 ? 1.f : 1.f-std::pow(2.f,-.1f);
        assert(near(c.origin.x,10*blend));
    }
}
'''
    with tempfile.TemporaryDirectory(prefix='camera-smoothing-') as directory:
        source = Path(directory) / 'check.cpp'
        executable = Path(directory) / 'check.exe'
        source.write_text(code)
        subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(executable)], check=True)
        subprocess.run([str(executable)], check=True)
    app = (ROOT / 'indra/newview/llappviewer.cpp').read_text()
    begin = app.index('->prepareCameraSmoothing();')
    end = app.index('->applyCameraSmoothing();')
    for controller in ('gAgentPilot.moveCamera();', '->moveFlycam();', 'gAgentCamera.updateCamera();'):
        assert begin < app.index(controller, begin) < end
    print('PASS: position/rotation/FOV, repeated focus-change continuity, idle settling, live enable/disable, 30/60/144 FPS, angle wrap, region crossing, teleport reset, capture isolation, range limits, and controller coverage')


if __name__ == '__main__':
    main()
