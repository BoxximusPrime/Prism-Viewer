"""Regress SSS projector coverage and precision at skybox heights using bundled GLM.

Compiles production camera selection and matrix composition; no viewer login needed.
Run: .venv/Scripts/python.exe scripts/tests/test_sss_depth_precision.py
"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    source = (ROOT / 'indra/newview/pipeline.cpp').read_text()
    header = (ROOT / 'indra/newview/pipeline.h').read_text()
    bind = source[source.index('void LLPipeline::bindSSSDepth('):source.index('void LLPipeline::generateSSSDepth(')]
    generate = source[source.index('void LLPipeline::generateSSSDepth('):source.index('void LLPipeline::generateSunShadow(')]
    camera = generate[generate.index('        glm::vec3 origin;'):generate.index('        LLRenderTarget& target = mSSSDepth[i];')]
    storage = re.search(r'(glm::\w+)\s+mSSSDepthMatrix', header)[1]
    save = re.search(r'mSSSDepthMatrix\[i\] = [^;]+;', generate)[0]
    inverse = re.search(r'const glm::\w+ inverseView = [^;]+;', bind)[0]
    transform = re.search(r'transforms\[i\] = [^;]+;', bind)[0]
    cpp = r'''
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <initializer_list>
#include <algorithm>
using F32 = float;
using U32 = unsigned;
constexpr int VX = 0, VY = 1;
float llmax(float a, float b) { return std::max(a,b); }
float llmin(float a, float b) { return std::min(a,b); }
float llclamp(float v, float lo, float hi) { return std::clamp(v,lo,hi); }
struct LLVector3 { float mV[3]; };
struct LLVOVolume {
    bool spot = true;
    LLVector3 scale{{1,1,1}}, params{{1,0,0}};
    glm::mat4 agentView{1};
    bool isLightSpotlight() { return spot; }
    LLVector3 getScale() { return scale; }
    LLVector3 getSpotLightParams() { return params; }
};
struct LLDrawable {
    LLVOVolume* volume;
    LLVOVolume* getVOVolume() { return volume; }
};
struct ProjectorParams { glm::mat4 agentView; };
ProjectorParams getProjectorParams(LLDrawable* light) { return {light->volume->agentView}; }
struct LLEnvironment {
    static LLEnvironment instance() { return {}; }
    bool getIsSunUp() { return true; }
};
struct Capture { bool valid; glm::mat4 proj, view; };
Capture capture(glm::vec3 center, glm::vec3 lightOrigin, LLVOVolume& volume, bool sun=false) {
    const float radius=2.5f, RenderFarClip=64;
    const glm::vec3 mSunDir(0,0,1), mMoonDir(0,0,-1);
    glm::vec3 mSSSDepthOrigin[1]={lightOrigin};
    LLDrawable light{&volume}; LLDrawable* lights[1]={&light};
    for(U32 i=sun?0:1; i<(sun?1u:2u); ++i) {
        @CAMERA@
        return {true,proj,view};
    }
    return {false,glm::mat4(1),glm::mat4(1)};
}
bool covered(const Capture& c, glm::vec3 p) {
    auto clip=c.proj*c.view*glm::vec4(p,1);
    return c.valid && clip.w>0 && glm::all(glm::lessThan(glm::abs(glm::vec3(clip)),glm::vec3(clip.w)));
}
// Same 24-bit comparison-depth/search operations used by the focused maps.
float path(glm::mat4 m, glm::vec3 pos, glm::vec3 dir, float depth) {
    auto start=m*glm::vec4(pos,1), step=m*glm::vec4(dir,0);
    if(start.z/start.w<=depth) return .08f;
    float lo=0, hi=.08f;
    for(int i=0;i<10;i++) {
        float mid=(lo+hi)*.5f;
        auto p=start+step*mid;
        if(p.z/p.w<=depth) hi=mid; else lo=mid;
    }
    return hi;
}
int main() {
    auto bias=glm::translate(glm::mat4(1),glm::vec3(.5))*glm::scale(glm::mat4(1),glm::vec3(.5));
    LLVOVolume volume;
    for(float height:{15.f,1500.f,4000.f}) {
        glm::vec3 subject(128,128,height), origin=subject+glm::vec3(0,0,5);
        auto distant=capture(subject,origin,volume);
        assert(distant.valid);
        auto proj=distant.proj, lightView=distant.view;
        auto entry=bias*proj*(lightView*glm::vec4(subject+glm::vec3(0,0,.004f),1));
        float depth=std::round(double(entry.z/entry.w)*16777215.)/16777215.;
        @STORAGE@ mSSSDepthMatrix[1];
        constexpr int i=0;
        { auto view=lightView; @SAVE@ }
        float minimum=1, maximum=0;
        for(int frame=0;frame<200;frame++) {
            float angle=.0001f*frame;
            auto view=glm::lookAt(subject+glm::vec3(3*std::sin(angle),-3*std::cos(angle),.5),subject,glm::vec3(0,0,1));
            glm::vec3 eye=glm::dmat4(view)*glm::dvec4(subject,1), dir=view*glm::vec4(0,0,1,0);
            @INVERSE@
            glm::mat4 transforms[1];
            @TRANSFORM@
            float measured=path(transforms[0],eye,dir,depth);
            assert(std::abs(measured-.004f)<.001f);
            minimum=glm::min(minimum,measured); maximum=glm::max(maximum,measured);
        }
        printf("Height %.0f m: 4 mm tissue measured %.3f..%.3f mm across 200 camera positions\n",height,1000*minimum,1000*maximum);
    }
    int closeChecks=0;
    for(float height:{15.f,1500.f,4000.f})
    for(float offset:{0.f,.02f,.5f})
    for(float fov:{30.f,90.f,160.f})
    for(float aspect:{.25f,1.f,4.f}) {
        glm::vec3 subject(128,128,height), origin=subject+glm::vec3(0,0,offset);
        // The beam points above the focus: the old center-facing map looks away.
        auto beam=glm::lookAt(origin,origin+glm::vec3(0,0,1),glm::vec3(0,1,0));
        volume.agentView=beam; volume.params.mV[0]=glm::radians(fov); volume.scale.mV[0]=aspect;
        auto c=capture(subject,origin,volume);
        assert(c.valid);
        for(float u:{-.8f,0.f,.8f})
        for(float v:{-.8f,0.f,.8f}) {
            glm::vec3 ray(u*aspect*tanf(glm::radians(fov)*.5f),v*tanf(glm::radians(fov)*.5f),-1);
            auto point=glm::vec3(glm::inverse(beam)*glm::vec4(glm::normalize(ray)*.5f,1));
            assert(covered(c,point));
            ++closeChecks;
        }
    }
    // Distant focus coverage survives the switch back to a subject-facing camera.
    glm::vec3 subject(0), receiver(.05f,0,.2f);
    for(float distance:{2.58f,2.60f,5.f}) {
        glm::vec3 origin(0,0,distance);
        volume.agentView=glm::lookAt(origin,subject,glm::vec3(0,1,0));
        volume.params.mV[0]=glm::radians(90.f); volume.scale.mV[0]=1;
        assert(covered(capture(subject,origin,volume),receiver));
        volume.spot=false;
        assert(covered(capture(subject,origin,volume),receiver));
        volume.spot=true;
    }
    volume.spot=false;
    assert(!capture(subject,subject,volume).valid); // point-light singularity guard
    assert(covered(capture(subject,subject,volume,true),receiver));
    printf("Passed %d close-projector coverage checks plus sun, point and transition checks\n",closeChecks);
}
'''
    for name, value in [('CAMERA', camera), ('STORAGE', storage), ('SAVE', save), ('INVERSE', inverse), ('TRANSFORM', transform)]:
        cpp = cpp.replace('@' + name + '@', value)
    compiler = shutil.which('g++')
    assert compiler, 'g++ is required'
    with tempfile.TemporaryDirectory(prefix='boxxy-sss-precision-') as directory:
        src, exe = Path(directory)/'test.cpp', Path(directory)/'test.exe'
        src.write_text(cpp)
        subprocess.run([compiler, '-std=c++17', '-I', str(ROOT/'build-vc170-64/packages/include'), str(src), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print('Passed 600 SSS altitude/camera precision checks')


if __name__ == '__main__':
    main()
