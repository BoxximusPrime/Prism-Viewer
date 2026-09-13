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


def main():
    source = (ROOT / 'indra/newview/pipeline.cpp').read_text()
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
int main() {
    auto trans=glm::translate(glm::mat4(1),glm::vec3(.5))*glm::scale(glm::mat4(1),glm::vec3(.5));
    int checks=0;
    for (float height : {0.f,1500.f,3000.f,4000.f}) {
        double worst=0, oldWorst=0;
        glm::vec3 subject(128,128,height), sunDir=glm::normalize(glm::vec3(.6,.3,.7));
        for (int mode=0; mode<3; ++mode) {
            double modeWorst=0, modeOldWorst=0;
            glm::mat4 proj[6],view[6],mSunShadowMatrix[6],mPCSSInverseMatrix[6];
            int j=0,i=0,slot=mode==2?4:0;
            view[slot]=glm::lookAt(subject+sunDir*50.f,subject,glm::vec3(0,1,0));
            proj[slot]=mode==2 ? glm::perspective(1.2f,1.4f,.5f,100.f) : glm::ortho(-64.f,64.f,-64.f,64.f,.1f,128.f);
            if(mode==1) { // Sun's perspective warp is transverse to its rays.
                glm::mat4 warp(1); warp[1][3]=.005f;
                proj[slot]=proj[slot]*warp;
            }
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
            if(height==3000) printf("  3000 m %s: %.4f mm (old %.4f mm)\n",mode==0?"sun":mode==1?"warped sun":"projector",modeWorst*1000,modeOldWorst*1000);
        }
        printf("Height %.0f m: maximum depth error %.4f mm (old float composition %.4f mm)\n",height,worst*1000,oldWorst*1000);
    }
    printf("PASS: %d PCSS sun/warped/projector altitude checks\n",checks);
}
'''
    for token, code in (('INVERSE', inverse), ('SUN', sun), ('SPOT', spot),
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
