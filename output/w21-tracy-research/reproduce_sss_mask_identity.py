"""Research diagnostic: expose SSS identity loss in the original baseline loop.

This deliberately expects the unfixed mismatch; it is not a regression test.
No viewer is launched and no production source is changed.
"""
from pathlib import Path
import ast
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REVISION = "52d375475d080ec8dad2c67b783ef4103ad12f9e"
baseline = subprocess.check_output(["git", "show", f"{REVISION}:scripts/tests/test_shadow_mask_batching.py"], cwd=ROOT, text=True)
baseline_stubs = next(ast.literal_eval(node.value) for node in ast.parse(baseline).body
                      if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "STUBS" for t in node.targets))
stubs = baseline_stubs.replace(
    "bool mAvatar = false;",
    "bool mAvatar = false; int mSSSObject = 0; bool mFullbright = false;")
stubs = stubs.replace(
    "std::vector<int>>;", "std::vector<int>, int>;")
stubs = stubs.replace(
    "indexed ? p.mTextureList : std::vector<int>{});",
    "indexed ? p.mTextureList : std::vector<int>{}, p.mFullbright ? 0 : p.mSSSObject);")
checks = r'''
#include <iostream>
int main() {
    LLRenderPass pass;
    for (bool indexed : {false, true}) {
        for (int boundary = 0; boundary < 3; ++boundary) {
            LLDrawInfo a{0,5,6,0}, b{6,11,6,6};
            a.mSSSObject = b.mSSSObject = 11;
            if (boundary == 0) b.mSSSObject = 22;
            if (boundary == 1) b.mSSSObject = 0;
            if (boundary == 2) b.mFullbright = true;
            gPipeline.inputs = {&a, &b};
            for (auto* shader : {&gDeferredShadowAlphaMaskProgram,
                                &gDeferredShadowFullbrightAlphaMaskProgram,
                                &gDeferredTreeShadowProgram}) {
                LLGLSLShader::sCurBoundShaderPtr = shader;
                LLPipeline::sShadowRender = false; // original per-draw submission reference
                submitted.clear(); draws = 0;
                pass.pushMaskBatches(0, true, indexed);
                const auto expected = submitted;
                assert(draws == 2);
                LLPipeline::sShadowRender = true;
                submitted.clear(); draws = 0;
                pass.pushMaskBatches(0, true, indexed);
                assert(draws == 1 && submitted != expected);
                assert(std::get<7>(submitted[6]) == 11);
                assert(std::get<7>(expected[6]) == (boundary == 0 ? 22 : 0));
            }
        }
    }
    std::cout << "Reproduced 18 identity mismatches: tagged/tagged, tagged/untagged, "
                 "effective fullbright zero; indexed/nonindexed; all three mask shaders.\n";
}
'''

# This is a historical reproduction; the current tree has a real regression test.
source = subprocess.check_output(["git", "show", f"{REVISION}:indra/newview/lldrawpool.cpp"], cwd=ROOT, text=True)
start = source.index("void LLRenderPass::pushMaskBatches(")
end = source.index("void LLRenderPass::pushRiggedMaskBatches(", start)
compiler = shutil.which("g++")
assert compiler, "g++ must be on PATH"
with tempfile.TemporaryDirectory(prefix="boxxy-sss-identity-") as folder:
    cpp, exe = Path(folder) / "check.cpp", Path(folder) / "check.exe"
    cpp.write_text(stubs + source[start:end] + checks)
    subprocess.run([compiler, "-std=c++17", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
