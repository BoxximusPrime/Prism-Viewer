"""Compile the production SSS selection math against bundled GLM, without login.

Run: .venv/Scripts/python.exe scripts/tests/test_sss_selection.py
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    source = (ROOT / 'indra/newview/pipeline.cpp').read_text()
    start = source.index('F32 advanceSSSDepthFade(')
    end = source.index('\n}\n\nvoid LLPipeline::updateSSSDepthFocus(', start)
    functions = source[start:end]
    cpp = r'''
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <initializer_list>
using F32 = float;
using U32 = unsigned;
template<class T> T llclamp(T v, T lo, T hi) { return std::clamp(v, lo, hi); }
struct LLColor3 { float mV[3]; };
@FUNCTIONS@
int main() {
    auto bias = glm::translate(glm::mat4(1), glm::vec3(.5f)) *
                glm::scale(glm::mat4(1), glm::vec3(.5f));
    auto projection = bias * glm::perspective(glm::radians(90.f), 1.f, .1f, 20.f);
    assert(sssProjectorIntersectsSphere(projection, {0,0,-5}, .2f));
    assert(!sssProjectorIntersectsSphere(projection, {0,0,5}, .2f));
    assert(!sssProjectorIntersectsSphere(projection, {10,0,-5}, .2f));
    assert(!sssProjectorIntersectsSphere(projection, {0,10,-5}, .2f));
    assert(!sssProjectorIntersectsSphere(projection, {0,0,-30}, .2f));
    // A sphere intersecting the edge remains eligible even if its center is outside.
    assert(sssProjectorIntersectsSphere(projection, {5.1f,0,-5}, .5f));
    auto away = projection * glm::lookAt(glm::vec3(0), glm::vec3(0,0,1), glm::vec3(0,1,0));
    assert(!sssProjectorIntersectsSphere(away, {0,0,-5}, .2f));
    assert(sssProjectorIntersectsSphere(away, {0,0,5}, .2f));
    const LLColor3 white{{1,1,1}}, half{{.5f,.5f,.5f}}, red{{1,0,0}}, green{{0,1,0}};
    const float near = sssLightScore(white, 2, 10, .5f);
    assert(near > sssLightScore(white, 8, 10, .5f));
    assert(std::abs(sssLightScore(half, 2, 10, .5f) * 2 - near) < 1e-6);
    assert(sssLightScore(green, 2, 10, .5f) > sssLightScore(red, 2, 10, .5f));
    assert(sssLightScore(white, 10, 10, .5f) == 0);
    assert(sssLightScore(white, 20, 10, .5f) == 0);
    assert(sssLightScore(white, 0, 0, .5f) == 0);
    for (int hz : {30,60,144}) {
        float fade = 0;
        for (int i=0; i<hz; ++i) {
            float next = advanceSSSDepthFade(fade, true, 1.f/hz);
            assert(next >= fade && next-fade <= 5.f/hz + 1e-6);
            fade = next;
        }
        assert(fade == 1);
        for (int i=0; i<hz; ++i) {
            float next = advanceSSSDepthFade(fade, false, 1.f/hz);
            assert(next <= fade && fade-next <= 5.f/hz + 1e-6);
            fade = next;
        }
        assert(fade == 0);
    }
    assert(advanceSSSDepthFade(0, true, 10) == .5f); // bounded after a stall
    assert(advanceSSSDepthFade(.4f, false, -1) == .4f);
    puts("Passed SSS projector frustum, linear attenuation ranking and 30/60/144 Hz transition checks");
}
'''.replace('@FUNCTIONS@', functions)
    compiler = shutil.which('g++')
    assert compiler, 'g++ is required'
    with tempfile.TemporaryDirectory(prefix='boxxy-sss-selection-') as directory:
        src, exe = Path(directory) / 'test.cpp', Path(directory) / 'test.exe'
        src.write_text(cpp)
        subprocess.run([compiler, '-std=c++17', '-I', str(ROOT / 'build-vc170-64/packages/include'),
                        str(src), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
