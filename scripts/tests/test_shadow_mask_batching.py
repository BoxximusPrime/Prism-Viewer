"""Execute the production masked-batch loop against a per-index state recorder.

Run: python scripts/tests/test_shadow_mask_batching.py (g++ on PATH).
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

STUBS = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <tuple>
#include <vector>
using U32 = uint32_t;
using U64 = uint64_t;
using F32 = float;
template<typename T> T llmin(T a, T b) { return std::min(a, b); }
template<typename T> T llmax(T a, T b) { return std::max(a, b); }
#define LL_PROFILE_ZONE_SCOPED_CATEGORY_DRAWPOOL
struct LLGLSLShader {
    inline static LLGLSLShader* sCurBoundShaderPtr;
    float alpha = -1.f;
    int updates = 0;
    void setMinimumAlpha(float a) { alpha = a; ++updates; }
};
LLGLSLShader gDeferredShadowAlphaMaskProgram, gDeferredShadowFullbrightAlphaMaskProgram;
LLGLSLShader gDeferredTreeShadowProgram, other_shader;
struct { int mGLMaxVertexRange = 65535, mGLMaxIndexRange = 65535; } gGLManager;
struct LLDrawInfo {
    U32 mStart, mEnd, mCount, mOffset;
    int mVertexBuffer = 1, mModelMatrix = 0;
    bool mAvatar = false;
    const int* mSSSObject = nullptr;
    bool mFullbright = false;
    float mAlphaMaskCutoff = .33f;
    int mTexture = 1, mTextureMatrix = 0;
    std::vector<int> mTextureList{1, 2};
};
struct LLCullResult {
    using drawinfo_iterator = LLDrawInfo**;
    static void increment_iterator(drawinfo_iterator& i, drawinfo_iterator) { ++i; }
};
struct LLPipeline {
    inline static bool sShadowRender = true;
    int mSSSDepthPass = 0;
    bool mSSSDepthOpaque = true;
    std::vector<LLDrawInfo*> inputs;
    LLDrawInfo** beginRenderMap(U32) { return inputs.data(); }
    LLDrawInfo** endRenderMap(U32) { return inputs.data() + inputs.size(); }
} gPipeline;
using Record = std::tuple<int, int, U32, float, int, int, std::vector<int>, const int*>;
std::vector<Record> submitted;
int draws = 0;
struct LLRenderPass {
    void pushMaskBatches(U32, bool, bool);
    static bool skipSSSDepth(const LLDrawInfo&);
    void pushBatchRange(LLDrawInfo& p, bool indexed, U32 start, U32 end, U32 count) {
        if (!count) return;
        ++draws;
        assert(start <= p.mOffset && end >= p.mOffset + count - 1);
        for (U32 n = p.mOffset; n < p.mOffset + count; ++n)
            submitted.emplace_back(p.mVertexBuffer, p.mModelMatrix, n,
                LLGLSLShader::sCurBoundShaderPtr->alpha, p.mTexture, p.mTextureMatrix,
                indexed ? p.mTextureList : std::vector<int>{},
                gPipeline.mSSSDepthPass && gPipeline.mSSSDepthOpaque && !p.mFullbright ? p.mSSSObject : nullptr);
    }
    void pushBatch(LLDrawInfo& p, bool, bool indexed) {
        pushBatchRange(p, indexed, p.mStart, p.mEnd, p.mCount);
    }
};
'''

CHECKS = r'''
int main() {
    LLRenderPass pass;
    for (bool indexed : {false, true}) {
        // Each variation isolates a boundary that must prevent merging.
        for (int boundary = 0; boundary < 10; ++boundary) {
            LLDrawInfo a{0,5,6,0}, b{6,11,6,6}, c{12,17,6,12};
            switch (boundary) {
                case 1: b.mVertexBuffer = 2; break;
                case 2: b.mModelMatrix = 2; break;
                case 3: b.mAlphaMaskCutoff = .7f; break;
                case 4: b.mTexture = 2; break;
                case 5: b.mTextureMatrix = 2; break;
                case 6: b.mTextureList = {2,1}; break;
                case 7: b.mAvatar = true; break;
                case 8: b.mOffset = b.mStart = 24; b.mEnd = 29; break;
                case 9: b.mCount = 0; break;
            }
            gPipeline.inputs = {&a, &b, &c, nullptr};
            auto* shader = &gDeferredShadowAlphaMaskProgram;
            LLGLSLShader::sCurBoundShaderPtr = shader;
            LLPipeline::sShadowRender = false;
            submitted.clear(); draws = 0; shader->updates = 0;
            pass.pushMaskBatches(0, true, indexed);
            auto expected = submitted;
            int original_draws = draws;
            assert(shader->updates == (boundary == 3 ? 3 : 1));
            for (auto* active : {shader, &gDeferredShadowFullbrightAlphaMaskProgram,
                                &gDeferredTreeShadowProgram, &other_shader}) {
                LLGLSLShader::sCurBoundShaderPtr = active;
                LLPipeline::sShadowRender = true;
                submitted.clear(); draws = 0;
                pass.pushMaskBatches(0, true, indexed);
                assert(submitted == expected);
                bool compatible = boundary == 0 || (boundary == 6 && !indexed);
                assert(draws == (compatible && active != &other_shader ? 1 : original_draws));
            }
            assert(a.mCount == 6 && a.mEnd == 5 && b.mOffset == (boundary == 8 ? 24u : 6u));
#if LL_DARWIN
            LLGLSLShader::sCurBoundShaderPtr = shader;
            for (bool limit_indices : {false, true}) {
                gGLManager.mGLMaxIndexRange = limit_indices ? 6 : 65535;
                gGLManager.mGLMaxVertexRange = limit_indices ? 65535 : 5;
                submitted.clear(); draws = 0;
                pass.pushMaskBatches(0, true, indexed);
                assert(submitted == expected && draws == original_draws);
            }
            gGLManager.mGLMaxIndexRange = gGLManager.mGLMaxVertexRange = 65535;
#endif
        }
    }
    int skin_a = 1, skin_b = 2;
    for (bool indexed : {false, true}) {
        for (int phase : {0, 1, 2}) {
            for (int boundary = 0; boundary < 4; ++boundary) {
                LLDrawInfo a{0,5,6,0}, b{6,11,6,6};
                a.mSSSObject = b.mSSSObject = &skin_a;
                if (boundary == 1) b.mSSSObject = &skin_b;
                if (boundary == 2) b.mSSSObject = nullptr;
                if (boundary == 3) b.mFullbright = true;
                gPipeline.inputs = {&a, &b}; gPipeline.mSSSDepthPass = phase;
                for (auto* shader : {&gDeferredShadowAlphaMaskProgram,
                                    &gDeferredShadowFullbrightAlphaMaskProgram,
                                    &gDeferredTreeShadowProgram}) {
                    LLGLSLShader::sCurBoundShaderPtr = shader;
                    submitted.clear(); draws = 0;
                    pass.pushMaskBatches(0, true, indexed);
                    const bool omit_b = phase == 2 && boundary >= 2;
                    assert(submitted.size() == (omit_b ? 6u : 12u));
                    for (size_t i = 0; i < submitted.size(); ++i) {
                        const int* expected = phase == 0 ? nullptr :
                            (i < 6 || boundary == 0 ? &skin_a : boundary == 1 ? &skin_b : nullptr);
                        assert(std::get<2>(submitted[i]) == i && std::get<7>(submitted[i]) == expected);
                    }
                    assert(draws == (phase == 0 || boundary == 0 || omit_b ? 1 : 2));
                    assert(a.mCount == 6 && b.mOffset == 6);
                }
            }
        }
    }
    gPipeline.inputs.clear(); submitted.clear(); draws = 0;
    pass.pushMaskBatches(0, true, true);
    assert(draws == 0 && submitted.empty());
}
'''


def main():
    compiler = shutil.which("g++")
    if compiler is None:
        raise SystemExit("g++ must be on PATH")
    root = Path(__file__).resolve().parents[2]
    source = (root / "indra/newview/lldrawpool.cpp").read_text()
    start = source.index("void LLRenderPass::pushMaskBatches(")
    end = source.index("void LLRenderPass::pushRiggedMaskBatches(", start)
    helper_start = source.index("bool LLRenderPass::skipSSSDepth(")
    helper_end = source.index("void LLRenderPass::pushUntexturedBatches(", helper_start)
    with tempfile.TemporaryDirectory(prefix="boxxy-shadow-mask-") as directory:
        cpp, exe = Path(directory) / "check.cpp", Path(directory) / "check.exe"
        cpp.write_text(STUBS + source[helper_start:helper_end] + source[start:end] + CHECKS)
        for darwin in (0, 1):
            subprocess.run([compiler, "-std=c++17", f"-DLL_DARWIN={darwin}",
                            str(cpp), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)
    print("Passed masked shadow batching: per-index state/SSS identity, zero-ID exit skips, compatible draws, boundaries and platform limits")


if __name__ == "__main__":
    main()
