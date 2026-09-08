"""Regress SSS matrix cancellation at SL skybox heights using bundled GLM.

Compiles the production storage/composition expressions; no viewer login needed.
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
    auto proj=glm::perspective(1.f,1.f,.01f,8.f);
    for(float height:{15.f,1500.f,4000.f}) {
        glm::vec3 subject(128,128,height), origin=subject+glm::vec3(0,0,5);
        auto lightView=glm::lookAt(origin,subject,glm::vec3(0,1,0));
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
}
'''
    for name, value in [('STORAGE', storage), ('SAVE', save), ('INVERSE', inverse), ('TRANSFORM', transform)]:
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
