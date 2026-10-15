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
#include <map>
using U32 = uint32_t;
using U64 = uint64_t;
using F32 = float;
template<typename T> T llmin(T a, T b) { return std::min(a, b); }
template<typename T> T llmax(T a, T b) { return std::max(a, b); }
#define LL_PROFILE_ZONE_SCOPED_CATEGORY_DRAWPOOL
#define llassert(x)
struct LLVOAvatar {} avatar_a, avatar_b;
struct Skin { bool loaded = true; U64 hash = 1; } skin_a, skin_b{true, 2}, unloaded_skin{false, 3}, skin_copy;
const LLVOAvatar* uploaded_avatar = nullptr;
const Skin* uploaded_skin = nullptr;
struct LLGLSLShader {
    inline static LLGLSLShader* sCurBoundShaderPtr;
    float alpha = -1.f;
    int updates = 0;
    LLGLSLShader* mRiggedVariant = nullptr;
    bool rigged = false;
    void setMinimumAlpha(float a) { alpha = a; ++updates; }
};
LLGLSLShader gDeferredShadowAlphaMaskProgram, gDeferredShadowFullbrightAlphaMaskProgram;
LLGLSLShader gDeferredTreeShadowProgram, other_shader;
struct { int mGLMaxVertexRange = 65535, mGLMaxIndexRange = 65535; } gGLManager;
struct LLDrawInfo {
    U32 mStart, mEnd, mCount, mOffset;
    int mVertexBuffer = 1, mModelMatrix = 0;
    const LLVOAvatar* mAvatar = nullptr;
    const int* mSSSObject = nullptr;
    bool mFullbright = false;
    float mAlphaMaskCutoff = .33f;
    int mTexture = 1, mTextureMatrix = 0;
    std::vector<int> mTextureList{1, 2};
    bool mHair = false;
    const int* mHairObject = nullptr;
    const Skin* mSkinInfo = &skin_a;
    int mModelXform = 0;
    U64 getSkinHash() const { return mSkinInfo ? mSkinInfo->hash : 0; }
};
struct LLCullResult {
    using drawinfo_iterator = LLDrawInfo**;
    static void increment_iterator(drawinfo_iterator& i, drawinfo_iterator) { ++i; }
};
struct LLPipeline {
    inline static bool sShadowRender = true;
    int mSSSDepthPass = 0;
    int mHairDepthPass = 0;
    bool mSSSDepthOpaque = true;
    std::vector<LLDrawInfo*> inputs;
    std::map<const int*, F32> ids;
    F32 getSSSDepthID(const int* object) {
        if (!object || !mSSSDepthOpaque) return 0;
        return ids.emplace(object, F32(ids.size() + 1)).first->second;
    }
    const int* objectForID(F32 id) {
        if (id == 0) return nullptr;
        for (auto [object, value] : ids) if (value == id) return object;
        assert(false); return nullptr;
    }
    LLDrawInfo** beginRenderMap(U32) { return inputs.data(); }
    LLDrawInfo** endRenderMap(U32) { return inputs.data() + inputs.size(); }
} gPipeline;
using Record = std::tuple<int, int, U32, float, int, int, std::vector<int>, const int*,
                          const LLVOAvatar*, U64, int, const int*>;
std::vector<Record> submitted;
int draws = 0;
struct LLRenderPass {
    void pushMaskBatches(U32, bool, bool);
    void pushRiggedMaskBatches(U32, bool, bool);
    static bool skipSSSDepth(const LLDrawInfo&);
    bool uploadMatrixPalette(const LLVOAvatar* avatar, const Skin* skin, const LLVOAvatar*&, U64&, bool&) {
        if (!avatar || !skin || !skin->loaded) return false;
        uploaded_avatar = avatar; uploaded_skin = skin;
        return true;
    }
    void pushBatchRange(LLDrawInfo& p, bool indexed, U32 start, U32 end, U32 count,
                        const F32* batches = nullptr, U32 batch_count = 0) {
        if (!count) return;
        if (LLGLSLShader::sCurBoundShaderPtr->rigged) {
            assert(uploaded_avatar == p.mAvatar && uploaded_skin->hash == p.getSkinHash());
        }
        ++draws;
        assert(start <= p.mOffset && end >= p.mOffset + count - 1);
        assert(batch_count <= 32);
        for (U32 n = p.mOffset; n < p.mOffset + count; ++n) {
            const int* identity = gPipeline.mSSSDepthPass && gPipeline.mSSSDepthOpaque && !p.mFullbright ? p.mSSSObject : nullptr;
            if (batch_count) {
                U32 slot = 0;
                while (slot + 1 < batch_count && (n - p.mOffset) / 3 >= batches[slot * 2]) ++slot;
                assert((n - p.mOffset) / 3 < batches[slot * 2]);
                identity = gPipeline.objectForID(batches[slot * 2 + 1]);
            }
            submitted.emplace_back(p.mVertexBuffer, p.mModelMatrix, n,
                LLGLSLShader::sCurBoundShaderPtr->alpha, p.mTexture, p.mTextureMatrix,
                indexed ? p.mTextureList : std::vector<int>{},
                identity, p.mAvatar, p.getSkinHash(), p.mModelXform, p.mHairObject);
        }
    }
    void pushBatch(LLDrawInfo& p, bool, bool indexed) {
        pushBatchRange(p, indexed, p.mStart, p.mEnd, p.mCount);
    }
};
void checkRigged();
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
                case 7: b.mAvatar = &avatar_a; break;
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
    gPipeline.mSSSDepthPass = 0;
    for (int phase : {1,2,3}) {
        for (bool fullbright : {false,true}) {
            LLDrawInfo a{0,5,6,0}, b{6,11,6,6};
            a.mHair = true; a.mFullbright = fullbright;
            gPipeline.inputs = {&a,&b}; gPipeline.mHairDepthPass = phase;
            submitted.clear(); draws = 0;
            pass.pushMaskBatches(0,true,true);
            assert(submitted.size() == (phase == 1 ? (fullbright ? 12u : 6u) : (fullbright ? 0u : 6u)));
            for (const auto& r : submitted)
                assert(fullbright || (phase == 1 ? std::get<2>(r) >= 6 : std::get<2>(r) < 6));
        }
    }
    gPipeline.mHairDepthPass = 0;
    for (bool same_hair : {false, true}) {
        LLDrawInfo a{0,5,6,0}, b{6,11,6,6};
        a.mHairObject = &skin_a; b.mHairObject = same_hair ? &skin_a : &skin_b;
        gPipeline.inputs = {&a,&b}; submitted.clear(); draws = 0;
        pass.pushMaskBatches(0,true,true);
        assert(draws == (same_hair ? 1 : 2));
    }
    gPipeline.inputs.clear(); submitted.clear(); draws = 0;
    pass.pushMaskBatches(0, true, true);
    assert(draws == 0 && submitted.empty());
    checkRigged();
}
'''

RIGGED_CHECKS = r'''
void checkRigged() {
    LLRenderPass pass;
    LLGLSLShader variants[3];
    gDeferredShadowAlphaMaskProgram.mRiggedVariant = &variants[0];
    gDeferredShadowFullbrightAlphaMaskProgram.mRiggedVariant = &variants[1];
    gDeferredTreeShadowProgram.mRiggedVariant = &variants[2];
    other_shader.rigged = true;
    int identity_a = 1, identity_b = 2;
    for (bool indexed : {false, true}) {
        for (int phase : {0, 1, 2}) {
            for (int boundary = 0; boundary < 18; ++boundary) {
                LLDrawInfo a{0,5,6,0}, b{6,11,6,6}, c{12,17,6,12};
                a.mAvatar = b.mAvatar = c.mAvatar = &avatar_a;
                a.mSSSObject = b.mSSSObject = c.mSSSObject = &identity_a;
                switch (boundary) {
                    case 1: b.mVertexBuffer = 2; break;
                    case 2: b.mModelMatrix = 2; break;
                    case 3: b.mAlphaMaskCutoff = .7f; break;
                    case 4: b.mTexture = 2; break;
                    case 5: b.mTextureMatrix = 2; break;
                    case 6: b.mTextureList = {2,1}; break;
                    case 7: b.mAvatar = &avatar_b; break;
                    case 8: b.mOffset = b.mStart = 24; b.mEnd = 29; break;
                    case 9: b.mCount = 0; break;
                    case 10: b.mSkinInfo = &skin_b; break;
                    case 11: b.mSSSObject = &identity_b; break;
                    case 12: b.mSSSObject = nullptr; break;
                    case 13: b.mFullbright = true; break;
                    case 14: b.mModelXform = 2; break;
                    case 15: b.mHairObject = &identity_b; break;
                    case 16: b.mSkinInfo = &unloaded_skin; break;
                    case 17: b.mSkinInfo = &skin_copy; break;
                }
                gPipeline.inputs = {&a, &b, &c, nullptr};
                gPipeline.mSSSDepthPass = phase;
                LLGLSLShader::sCurBoundShaderPtr = &other_shader;
                submitted.clear(); draws = 0;
                pass.pushRiggedMaskBatches(0, true, indexed);
                auto expected = submitted;
                const int original_draws = draws;
                assert(original_draws == (boundary == 9 || boundary == 16 ||
                    (phase == 2 && (boundary == 12 || boundary == 13)) ? 2 : 3));
                for (auto& shader : variants) {
                    shader.rigged = true;
                    LLGLSLShader::sCurBoundShaderPtr = &shader;
                    submitted.clear(); draws = 0;
                    pass.pushRiggedMaskBatches(0, true, indexed);
                    assert(submitted == expected);
                    const bool gpu_ids = &shader == &variants[2] && phase != 0;
                    const bool compatible = boundary == 0 || boundary == 17 || (boundary == 6 && !indexed) ||
                        (boundary >= 11 && boundary <= 13 &&
                         (phase == 0 || (gpu_ids && (boundary == 11 || phase == 1))));
                    assert(draws == (compatible ? 1 : original_draws));
                    assert(a.mCount == 6 && a.mEnd == 5 && c.mOffset == 12);
#if LL_DARWIN
                    for (bool indices : {false, true}) {
                        gGLManager.mGLMaxIndexRange = indices ? 6 : 65535;
                        gGLManager.mGLMaxVertexRange = indices ? 65535 : 5;
                        submitted.clear(); draws = 0;
                        pass.pushRiggedMaskBatches(0, true, indexed);
                        assert(submitted == expected && draws == original_draws);
                    }
                    gGLManager.mGLMaxIndexRange = gGLManager.mGLMaxVertexRange = 65535;
#endif
                }
            }
        }
    }
    gPipeline.mSSSDepthPass = 0;
    for (int phase : {1,2,3}) {
        for (bool fullbright : {false,true}) {
            LLDrawInfo a{0,5,6,0}, b{6,11,6,6};
            a.mAvatar = b.mAvatar = &avatar_a;
            a.mHair = true; a.mFullbright = fullbright;
            gPipeline.inputs = {&a,&b}; gPipeline.mHairDepthPass = phase;
            submitted.clear(); draws = 0;
            pass.pushRiggedMaskBatches(0,true,true);
            assert(submitted.size() == (phase == 1 ? (fullbright ? 12u : 6u) : (fullbright ? 0u : 6u)));
            for (const auto& r : submitted)
                assert(fullbright || (phase == 1 ? std::get<2>(r) >= 6 : std::get<2>(r) < 6));
        }
    }
    gPipeline.mHairDepthPass = 0;
    // More than one uniform table: preserve all identities and reset primitive offsets at each draw.
    LLGLSLShader::sCurBoundShaderPtr = &variants[2];
    std::vector<LLDrawInfo> sections;
    int identities[70];
    for (int n = 0; n < 70; ++n) {
        LLDrawInfo p{U32(n*6),U32(n*6+5),6,U32(n*6)};
        p.mAvatar = &avatar_a; p.mSSSObject = &identities[n];
        p.mSkinInfo = n % 2 ? &skin_a : &skin_copy;
        sections.push_back(p);
    }
    gPipeline.inputs.clear();
    for (auto& p : sections) gPipeline.inputs.push_back(&p);
    for (int phase : {1,2}) {
        gPipeline.mSSSDepthPass = phase;
        submitted.clear(); draws = 0;
        pass.pushRiggedMaskBatches(0,true,false);
        assert(draws == 3 && submitted.size() == 420);
        for (size_t n = 0; n < submitted.size(); ++n)
            assert(std::get<7>(submitted[n]) == &identities[n/6]);
    }
    gPipeline.mSSSDepthPass = 0;
    gPipeline.inputs.clear(); submitted.clear(); draws = 0;
    pass.pushRiggedMaskBatches(0,true,true);
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
    end = source.index("void LLRenderPass::applyModelMatrix(", start)
    helper_start = source.index("bool LLRenderPass::skipSSSDepth(")
    helper_end = source.index("void LLRenderPass::pushUntexturedBatches(", helper_start)
    with tempfile.TemporaryDirectory(prefix="boxxy-shadow-mask-") as directory:
        cpp, exe = Path(directory) / "check.cpp", Path(directory) / "check.exe"
        cpp.write_text(STUBS + source[helper_start:helper_end] + source[start:end] + CHECKS + RIGGED_CHECKS)
        for darwin in (0, 1):
            subprocess.run([compiler, "-std=c++17", f"-DLL_DARWIN={darwin}",
                            str(cpp), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)
    print("Passed static/rigged masked shadow batching: per-index state, palettes, SSS/hair identity, exit skips, compatible draws, boundaries and platform limits")


if __name__ == "__main__":
    main()
