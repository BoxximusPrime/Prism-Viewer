"""Execute production draw setup across hair/non-hair and physics transitions.

Run: python scripts/tests/test_hair_draw_setup.py (requires g++).
The retained radius reset must make stale guide bindings harmless, while active
hair still receives its complete deformation setup.
"""
from pathlib import Path
import subprocess
import tempfile

from test_alpha_lighting_gpu import function

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'indra/newview/lldrawpool.cpp').read_text()
draw = function(source, 'void LLRenderPass::applyModelMatrix(const LLDrawInfo& params)')
draw = draw[draw.index('    applyModelMatrix(params.mModelMatrix, params.mModelXform);'):]
reset = function(source, 'void LLRenderPass::applyModelMatrix(const LLMatrix4* model_matrix, const LLXformMatrix* model_xform)')
reset = reset[reset.index('{') + 1:reset.index('    if (model_matrix != gGLLastMatrix)')]
text = r'''
#include <cassert>
using LLStaticHashedString=const char*;
struct { bool physics=false; } gSavedSettings;
template<class T> struct LLCachedControl {
    LLCachedControl(decltype(gSavedSettings)&,const char*,bool) {}
    operator bool() const { return gSavedSettings.physics; }
};
struct LLGLSLShader {
    inline static LLGLSLShader* sCurBoundShaderPtr=nullptr;
    bool supports=true; float radius=0; int lookups=0;
    int getUniformLocation(const char*) { ++lookups; return supports?1:-1; }
    void uniform1f(const char*,float value) { radius=value; }
};
struct LLDrawInfo { bool mHair=false; void* mModelMatrix=nullptr; void* mModelXform=nullptr; };
struct LLRenderPass {
    inline static int setups=0;
    static float getHairDeform(const LLDrawInfo&) { return .15f; }
    static void applyHairDeform(float radius) { ++setups; LLGLSLShader::sCurBoundShaderPtr->radius=radius; }
    static void applyModelMatrix(void*,void*) {
''' + reset + r'''
    }
    static void applyModelMatrix(const LLDrawInfo& params) {
''' + draw + r'''
};
int main() {
    LLGLSLShader shader; LLGLSLShader::sCurBoundShaderPtr=&shader;
    LLDrawInfo hair{true}, ordinary{false};
    gSavedSettings.physics=true;
    LLRenderPass::applyModelMatrix(hair);
    assert(shader.radius==.15f && LLRenderPass::setups==1);
    int lookups=shader.lookups;
    LLRenderPass::applyModelMatrix(ordinary);
    assert(shader.radius==0 && LLRenderPass::setups==1 && shader.lookups==lookups);
    LLRenderPass::applyModelMatrix(hair);
    assert(shader.radius==.15f && LLRenderPass::setups==2);
    gSavedSettings.physics=false; lookups=shader.lookups;
    LLRenderPass::applyModelMatrix(hair);
    assert(shader.radius==0 && LLRenderPass::setups==2 && shader.lookups==lookups);
    gSavedSettings.physics=true; shader.supports=false;
    LLRenderPass::applyModelMatrix(hair);
    assert(shader.radius==0 && LLRenderPass::setups==2);
    shader.supports=true;
    LLRenderPass::applyModelMatrix(hair);
    assert(shader.radius==.15f && LLRenderPass::setups==3);
    LLGLSLShader::sCurBoundShaderPtr=nullptr;
    LLRenderPass::applyModelMatrix(hair);
    assert(LLRenderPass::setups==3);
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp, exe = Path(directory) / 'hair.cpp', Path(directory) / 'hair.exe'
    cpp.write_text(text)
    subprocess.run(['g++', '-std=c++17', str(cpp), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('Hair setup, ordinary draws, physics toggles and shader transitions passed.')
