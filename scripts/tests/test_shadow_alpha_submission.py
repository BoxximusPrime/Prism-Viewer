"""Run the production alpha-shadow submission function with recording draw/GL stubs.

Requires g++ on PATH. Checks routing and pass state, not actual GPU rendering.
Run: python scripts/tests/test_shadow_alpha_submission.py
"""

from pathlib import Path
import shutil
import subprocess
import tempfile


STUBS = r'''
#include <cassert>
#include <cstdint>
#include <vector>
#include <cstddef>
using U32 = uint32_t;
using U64 = uint64_t;
using S32 = int32_t;
#define LL_PROFILE_ZONE_SCOPED_CATEGORY_PIPELINE
constexpr float ALPHA_BLEND_CUTOFF = 0.598f;
struct LLVOAvatar {};
struct LLDrawInfo { int id; bool mGLTFMaterial; const LLVOAvatar* mAvatar; bool mSkinInfo = true; };
struct LLShaderMgr { enum { SUN_UP_FACTOR, DEFERRED_SHADOW_TARGET_WIDTH }; };
struct LLRenderTarget { inline static U32 sCurResX = 2048; };
struct LLEnvironment {
    bool sun = true;
    static LLEnvironment& instance() { static LLEnvironment e; return e; }
    bool getIsSunUp() { return sun; }
};
struct LLGLSLShader {
    LLGLSLShader* mRiggedVariant = nullptr;
    inline static LLGLSLShader* sCurBoundShaderPtr = nullptr;
    int binds = 0, sun = -1, setups = 0;
    float width = 0, cutoff = 0;
    void bind() { sCurBoundShaderPtr = this; ++binds; }
    void uniform1i(int, int x) { sun = x; }
    void uniform1f(int, float x) { width = x; }
    void setMinimumAlpha(float x) { cutoff = x; ++setups; }
};
LLGLSLShader legacy_rigged, pbr_rigged;
LLGLSLShader gDeferredShadowAlphaMaskProgram{&legacy_rigged};
LLGLSLShader gDeferredShadowGLTFAlphaBlendProgram{&pbr_rigged};
std::vector<int> draws;
void record(LLDrawInfo& p) {
    auto* expected = p.mGLTFMaterial ? &gDeferredShadowGLTFAlphaBlendProgram : &gDeferredShadowAlphaMaskProgram;
    if (p.mAvatar) expected = expected->mRiggedVariant;
    assert(LLGLSLShader::sCurBoundShaderPtr == expected);
    assert(expected->sun == int(LLEnvironment::instance().sun));
    assert(expected->width == LLRenderTarget::sCurResX);
    assert(expected->cutoff == ALPHA_BLEND_CUTOFF);
    draws.push_back(p.id);
}
struct LLRenderPass {
    enum { PASS_ALPHA };
    static bool uploadMatrixPalette(const LLVOAvatar*, bool skin, const LLVOAvatar*&, U64&, bool&) { return skin; }
    static void pushBatch(LLDrawInfo& p, bool, bool) { assert(!p.mGLTFMaterial); record(p); }
    static void pushGLTFBatch(LLDrawInfo& p) { assert(p.mGLTFMaterial); record(p); }
    static void pushRiggedGLTFBatch(LLDrawInfo& p, const LLVOAvatar*&, U64&, bool&) {
        if (p.mSkinInfo) pushGLTFBatch(p);
    }
};
struct LLCullResult {
    using drawinfo_iterator = LLDrawInfo**;
    static void increment_iterator(drawinfo_iterator& i, drawinfo_iterator) { ++i; }
};
struct GL { void loadMatrix(int) {} } gGL;
int gGLModelView = 0;
void* gGLLastMatrix = nullptr;
struct LLPipeline {
    int mSSSDepthPass = 0;
    bool mSSSDepthOpaque = true;
    LLRenderPass pool;
    LLRenderPass* mSimplePool = &pool;
    std::vector<LLDrawInfo*> inputs;
    void assertInitialized() {}
    LLDrawInfo** beginRenderMap(U32) { return inputs.data(); }
    LLDrawInfo** endRenderMap(U32) { return inputs.data() + inputs.size(); }
    void renderAlphaObjects(bool rigged);
} gPipeline;
'''

CHECKS = r'''
int main() {
    LLVOAvatar avatar;
    LLDrawInfo input[] = {
        {1, false, nullptr}, {2, false, nullptr}, {3, true, nullptr},
        {4, true, nullptr}, {5, false, nullptr},
        {6, false, &avatar}, {7, false, &avatar}, {8, true, &avatar},
        {9, true, &avatar}, {10, false, &avatar, false}, {11, true, &avatar, false}
    };
    for (auto& p : input) gPipeline.inputs.push_back(&p);
    // A preceding alpha-mask draw can leave the same shader bound with another cutoff.
    gDeferredShadowAlphaMaskProgram.bind();
    gDeferredShadowAlphaMaskProgram.cutoff = 0.9f;
    gPipeline.renderAlphaObjects(false);
    assert((draws == std::vector<int>{1, 2, 3, 4, 5}));
    assert(gPipeline.mSSSDepthOpaque);
    assert(gDeferredShadowAlphaMaskProgram.setups == 2);
    assert(gDeferredShadowGLTFAlphaBlendProgram.setups == 1);
    draws.clear();
    gPipeline.renderAlphaObjects(true);
    assert((draws == std::vector<int>{6, 7, 8, 9}));
    assert(legacy_rigged.setups == 2 && pbr_rigged.setups == 2);
    // A new map must refresh state even if it starts with the already-bound shader.
    LLRenderTarget::sCurResX = 1024;
    LLEnvironment::instance().sun = false;
    draws.clear();
    gPipeline.renderAlphaObjects(false);
    assert((draws == std::vector<int>{1, 2, 3, 4, 5}));
    for (bool opaque : {false, true}) {
        gPipeline.mSSSDepthOpaque = opaque;
        gPipeline.mSSSDepthPass = 1;
        draws.clear();
        gPipeline.renderAlphaObjects(false);
        assert((draws == std::vector<int>{1, 2, 3, 4, 5}));
        assert(gPipeline.mSSSDepthOpaque == opaque);
        gPipeline.mSSSDepthPass = 2;
        draws.clear();
        auto* shader = LLGLSLShader::sCurBoundShaderPtr;
        const int binds = legacy_rigged.binds + pbr_rigged.binds +
            gDeferredShadowAlphaMaskProgram.binds + gDeferredShadowGLTFAlphaBlendProgram.binds;
        gPipeline.renderAlphaObjects(false);
        gPipeline.renderAlphaObjects(true);
        assert(draws.empty() && gPipeline.mSSSDepthOpaque == opaque);
        assert(LLGLSLShader::sCurBoundShaderPtr == shader);
        assert(binds == legacy_rigged.binds + pbr_rigged.binds +
            gDeferredShadowAlphaMaskProgram.binds + gDeferredShadowGLTFAlphaBlendProgram.binds);
    }
    gPipeline.mSSSDepthPass = 0;
    gPipeline.inputs.clear();
    draws.clear();
    gPipeline.renderAlphaObjects(false);
    gPipeline.renderAlphaObjects(true);
    assert(draws.empty());
}
'''


def main():
    compiler = shutil.which("g++")
    if compiler is None:
        raise SystemExit("g++ must be on PATH")
    root = Path(__file__).resolve().parents[2]
    source = (root / "indra/newview/pipeline.cpp").read_text()
    start = source.index("void LLPipeline::renderAlphaObjects(bool rigged)")
    end = source.index("\n// Currently only used for shadows", start)
    with tempfile.TemporaryDirectory(prefix="boxxy-shadow-submission-") as directory:
        cpp = Path(directory) / "check.cpp"
        exe = Path(directory) / "check.exe"
        cpp.write_text(STUBS + source[start:end] + CHECKS)
        subprocess.run([compiler, "-std=c++17", str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("Passed shadow alpha routing, shader reuse, pass refresh, and empty-pass checks")


if __name__ == "__main__":
    main()
