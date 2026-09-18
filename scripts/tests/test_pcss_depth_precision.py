"""Compile production shadow matrix composition and regress skybox precision.

Run: .venv/Scripts/python.exe scripts/tests/test_pcss_depth_precision.py
Uses bundled GLM and g++; no viewer login required.
"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def projection_cases():
    """Run the production depth fit; return matrices for rasterized GPU checks."""
    source = (ROOT / 'indra/newview/pipeline.cpp').read_text()
    helper = source[source.index('static glm::mat4 extendSunShadowDepth('):source.index('void LLPipeline::generateSunShadow(')]
    cpp = r'''
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdio>
using F32 = float;
using S32 = int;
@HELPER@
int main() {
    for (float near : {.03f,.1f,.4f,1.f,4.f}) for (float warp : {0.f,-.3f,.3f,1.f,2.f}) {
        auto before=glm::ortho(-1.5f,1.5f,-1.5f,1.5f,-near,8.f);
        before[1][3]=warp;
        if(warp>=1) {
            // The viewer's actual perspective-along-Y projection, with a
            // 64:1 or 640:1 homogeneous denominator range across the map.
            float yn=warp==1 ? 1.f : .1f, yf=64.f;
            before=glm::mat4(2,0,0,0, 0,(yf+yn)/(yn-yf),0,-1,
                            0,0,-4/near,0, 0,2*yf*yn/(yn-yf),0,0);
            before*=glm::translate(glm::mat4(1),glm::vec3(0,-4,0));
        }
        auto after=extendSunShadowDepth(before,64.f);
        // XY/W and the old far plane must be unchanged: no resolution,
        // coverage or culling increase is hidden in the depth extension.
        for (int c=0;c<4;++c) for (int r : {0,1,3}) assert(before[c][r]==after[c][r]);
        for (float x : {-1.f,0.f,1.f}) for (float y : {-1.f,0.f,1.f}) {
            glm::vec4 p=glm::inverse(before)*glm::vec4(x,y,1,1); p/=p.w;
            auto far=after*p;
            assert(std::abs(far.z/far.w-1)<1e-5f);
            p.z=63.99f;
            auto clip=after*p;
            assert(clip.z/clip.w>=-1.f && clip.z/clip.w<1.f);
            // Quantization stays within one D24 step. Extreme perspective
            // fits have coarser precision at their far end; don't conceal it
            // behind an absolute millimetre tolerance.
            auto inv=glm::inverse(glm::dmat4(after));
            auto projected=glm::dmat4(after)*glm::dvec4(p);
            double d=std::round((projected.z/projected.w*.5+.5)*16777215.)/16777215.;
            auto restored=inv*glm::dvec4(projected.x/projected.w,projected.y/projected.w,d*2-1,1);
            auto a=inv*glm::dvec4(x,y,-1,1), b=inv*glm::dvec4(x,y,1,1);
            double step=glm::length(glm::dvec3(a/a.w-b/b.w))/16777215.;
            assert(glm::length(glm::dvec3(restored/restored.w-glm::dvec4(p)))<step+1e-6);
        }
        printf("%.9g %.9g",near,warp);
        for (auto matrix : {before,after}) for (int r=0;r<4;++r) for (int c=0;c<4;++c) printf(" %.9g",matrix[c][r]);
        puts("");
    }
}
'''.replace('@HELPER@', helper)
    compiler = shutil.which('g++')
    assert compiler, 'g++ must be on PATH'
    with tempfile.TemporaryDirectory(prefix='pcss-projection-') as directory:
        src, exe = Path(directory) / 'check.cpp', Path(directory) / 'check.exe'
        src.write_text(cpp)
        subprocess.run([compiler, '-std=c++17', '-I', str(ROOT/'build-vc170-64/packages/include'),
                        str(src), '-o', str(exe)], check=True)
        output = subprocess.check_output([str(exe)], text=True)
    cases = []
    for line in output.splitlines():
        values = list(map(float, line.split()))
        assert len(values) == 34
        cases.append((values[0], values[1], [[values[2+m*16+r*4:2+m*16+(r+1)*4] for r in range(4)] for m in range(2)]))
    return cases


def main():
    source = (ROOT / 'indra/newview/pipeline.cpp').read_text()
    helper = source[source.index('static glm::mat4 extendSunShadowDepth('):source.index('void LLPipeline::generateSunShadow(')]
    source = source[source.index('void LLPipeline::generateSunShadow('):]
    inverse = re.search(r'(?:const )?glm::\w+ inv_view = [^;]+;', source)[0]
    sun = re.search(r'mSunShadowMatrix\[j\] = [^;]+;', source)[0]
    spot = re.search(r'mSunShadowMatrix\[i \+ 4\] = [^;]+;', source)[0]
    sun_inverse = re.search(r'mPCSSInverseMatrix\[j\] = [^;]+;', source)[0]
    spot_inverse = re.search(r'mPCSSInverseMatrix\[i \+ 4\] = [^;]+;', source)[0]
    cpp = r'''
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <cmath>
#include <cstdio>
#include <cassert>
#include <algorithm>
#include <initializer_list>
using F32 = float;
using S32 = int;
@DEPTH_HELPER@
int main() {
    auto trans=glm::translate(glm::mat4(1),glm::vec3(.5))*glm::scale(glm::mat4(1),glm::vec3(.5));
    int checks=0;
    for (float height : {0.f,1500.f,3000.f,4000.f}) {
        double worst=0, oldWorst=0;
        glm::vec3 subject(128,128,height), sunDir=glm::normalize(glm::vec3(.6,.3,.7));
        for (int mode=0; mode<5; ++mode) {
            double modeWorst=0, modeOldWorst=0;
            glm::mat4 proj[6],view[6],mSunShadowMatrix[6],mPCSSInverseMatrix[6];
            int j=0,i=0,slot=mode==2?4:0;
            view[slot]=glm::lookAt(subject+sunDir*50.f,subject,glm::vec3(0,1,0));
            proj[slot]=mode==2 ? glm::perspective(1.2f,1.4f,.5f,100.f) : glm::ortho(-64.f,64.f,-64.f,64.f,.1f,128.f);
            if(mode==1 || mode==4) { // Sun's perspective warp is transverse to its rays.
                glm::mat4 warp(1); warp[1][3]=.005f;
                proj[slot]=proj[slot]*warp;
            }
            if(mode>=3) proj[slot]=extendSunShadowDepth(proj[slot],2048.f);
            for(int frame=0;frame<200;++frame) {
                float angle=.003f*frame, distance=3.f+frame*.08f;
                auto saved_view=glm::lookAt(subject+glm::vec3(distance*std::sin(angle),-distance*std::cos(angle),2.f),subject,glm::vec3(0,0,1));
                @INVERSE@
                if(mode==2) { @SPOT@ @SPOT_INVERSE@ }
                else { @SUN@ @SUN_INVERSE@ }
                // Independent light-space result: transform the receiver
                // first, rather than forming a projected world translation.
                glm::dvec4 world(subject,1);
                glm::vec4 eye=glm::dmat4(saved_view)*world;
                glm::vec4 direction=saved_view*glm::vec4(sunDir,0);
                auto expected=glm::dmat4(trans)*glm::dmat4(proj[slot])*(glm::dmat4(view[slot])*world);
                auto actual=mSunShadowMatrix[slot]*eye;
                auto step=mSunShadowMatrix[slot]*direction;
                double derivative=(step.z-double(actual.z/actual.w)*step.w)/actual.w;
                double error=std::abs((double(actual.z)/actual.w-expected.z/expected.w)/derivative);
                worst=std::max(worst,error);
                modeWorst=std::max(modeWorst,error);
                auto old=trans*proj[slot]*view[slot]*glm::inverse(saved_view);
                auto oldActual=old*eye;
                oldWorst=std::max(oldWorst,std::abs((double(oldActual.z)/oldActual.w-expected.z/expected.w)/derivative));
                modeOldWorst=std::max(modeOldWorst,std::abs((double(oldActual.z)/oldActual.w-expected.z/expected.w)/derivative));
                assert(std::isfinite(error));
                // One millimetre stays below the default 3.5 mm bias.
                assert(error<.001);
                auto roundtrip=mPCSSInverseMatrix[slot]*actual;
                assert(glm::length(glm::vec3(roundtrip)/roundtrip.w-glm::vec3(eye))<.002f);
                ++checks;
            }
            const char* names[]={"sun","warped sun","projector","extended sun","extended warped sun"};
            if(height==3000) printf("  3000 m %s: %.4f mm (old %.4f mm)\n",names[mode],modeWorst*1000,modeOldWorst*1000);
        }
        printf("Height %.0f m: maximum depth error %.4f mm (old float composition %.4f mm)\n",height,worst*1000,oldWorst*1000);
    }
    printf("PASS: %d PCSS sun/warped/projector altitude checks\n",checks);
}
'''
    for token, code in (('DEPTH_HELPER', helper), ('INVERSE', inverse), ('SUN', sun), ('SPOT', spot),
                        ('SUN_INVERSE', sun_inverse), ('SPOT_INVERSE', spot_inverse)):
        cpp = cpp.replace('@' + token + '@', code)
    compiler = shutil.which('g++')
    assert compiler, 'g++ must be on PATH'
    with tempfile.TemporaryDirectory(prefix='pcss-depth-precision-') as directory:
        src, exe = Path(directory) / 'check.cpp', Path(directory) / 'check.exe'
        src.write_text(cpp)
        subprocess.run([compiler, '-std=c++17', '-I', str(ROOT/'build-vc170-64/packages/include'),
                        str(src), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
