"""Execute the production opaque-shadow batch loop with recording draw stubs.

Run: python scripts/tests/test_shadow_batching.py (requires g++ on PATH).
Verifies submitted indices/state and draw-count reduction, not GPU performance.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

STUBS = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <vector>
#include <tuple>
using U32 = uint32_t;
using U64 = uint64_t;
template<typename T> T llmin(T a, T b) { return std::min(a, b); }
template<typename T> T llmax(T a, T b) { return std::max(a, b); }
#define LL_PROFILE_ZONE_SCOPED_CATEGORY_DRAWPOOL
struct LLGLSLShader { inline static LLGLSLShader* sCurBoundShaderPtr = nullptr; };
LLGLSLShader gDeferredShadowProgram, other_shader;
struct { int mGLMaxVertexRange = 65535, mGLMaxIndexRange = 65535; } gGLManager;
struct LLRender { enum { TRIANGLES }; };
using Record = std::tuple<int, const int*, U32>;
std::vector<Record> submitted;
int draw_calls = 0;
const int* current_matrix = nullptr;
struct Buffer {
    int id;
    void setBuffer() {}
    void drawRange(int, U32 start, U32 finish, U32 count, U32 offset) {
        ++draw_calls;
        // Fixture indices are sequential, making incorrect vertex bounds detectable.
        assert(start <= offset && finish >= offset + count - 1);
        for (U32 i = offset; i < offset + count; ++i) submitted.emplace_back(id, current_matrix, i);
    }
};
struct LLDrawInfo {
    U32 mStart, mEnd, mCount, mOffset;
    Buffer* mVertexBuffer;
    const int* mModelMatrix;
    bool mAvatar = false;
};
struct LLCullResult {
    using drawinfo_iterator = LLDrawInfo**;
    static void increment_iterator(drawinfo_iterator& i, drawinfo_iterator) { ++i; }
};
struct LLPipeline {
    inline static bool sShadowRender = true;
    std::vector<LLDrawInfo*> inputs;
    LLDrawInfo** beginRenderMap(U32) { return inputs.data(); }
    LLDrawInfo** endRenderMap(U32) { return inputs.data() + inputs.size(); }
} gPipeline;
struct LLRenderPass {
    void pushUntexturedBatches(U32);
    static void applyModelMatrix(const LLDrawInfo& p) { current_matrix = p.mModelMatrix; }
    static void pushUntexturedBatch(LLDrawInfo& p) {
        if (!p.mCount) return;
        applyModelMatrix(p);
        p.mVertexBuffer->drawRange(0, p.mStart, p.mEnd, p.mCount, p.mOffset);
    }
};
'''

CHECKS = r'''
int main() {
    Buffer a{1}, b{2};
    int transform = 1;
    LLDrawInfo p[] = {
        {0,5,6,0,&a,nullptr}, {6,11,6,6,&a,nullptr}, {12,17,6,12,&a,nullptr},
        {24,29,6,24,&a,nullptr}, // a gap must not be drawn
        {30,35,6,30,&a,&transform}, // different transform
        {36,41,6,36,&b,&transform}, // different buffer
        {42,47,0,42,&b,&transform}, // empty draw
        {42,47,6,42,&b,&transform,true}, // rigged boundary
        {48,53,6,48,&b,&transform},
        {54,59,6,54,&b,&transform}
    };
    for (auto& x : p) gPipeline.inputs.push_back(&x);
    gPipeline.inputs.push_back(nullptr);
    LLRenderPass pass;
    // Reference submissions through the unchanged non-shadow path.
    LLGLSLShader::sCurBoundShaderPtr = &gDeferredShadowProgram;
    LLPipeline::sShadowRender = false;
    pass.pushUntexturedBatches(0);
    auto reference = submitted;
    assert(draw_calls == 9);
    LLPipeline::sShadowRender = true;
    submitted.clear(); draw_calls = 0;
    pass.pushUntexturedBatches(0);
    assert(submitted == reference && draw_calls == 6);
    assert(p[0].mCount == 6 && p[1].mOffset == 6); // no persistent batch mutation
    LLGLSLShader::sCurBoundShaderPtr = &other_shader;
    submitted.clear(); draw_calls = 0;
    pass.pushUntexturedBatches(0);
    assert(submitted == reference && draw_calls == 9);
#if LL_DARWIN
    LLGLSLShader::sCurBoundShaderPtr = &gDeferredShadowProgram;
    gGLManager.mGLMaxIndexRange = 6;
    submitted.clear(); draw_calls = 0;
    pass.pushUntexturedBatches(0);
    assert(submitted == reference && draw_calls == 9);
    gGLManager.mGLMaxIndexRange = 65535;
    gGLManager.mGLMaxVertexRange = 5;
    submitted.clear(); draw_calls = 0;
    pass.pushUntexturedBatches(0);
    assert(submitted == reference && draw_calls == 9);
#endif
    gPipeline.inputs.clear(); submitted.clear(); draw_calls = 0;
    pass.pushUntexturedBatches(0);
    assert(submitted.empty() && draw_calls == 0);
}
'''


def main():
    compiler = shutil.which("g++")
    if compiler is None:
        raise SystemExit("g++ must be on PATH")
    root = Path(__file__).resolve().parents[2]
    source = (root / "indra/newview/lldrawpool.cpp").read_text()
    start = source.index("void LLRenderPass::pushUntexturedBatches(U32 type)")
    end = source.index("void LLRenderPass::pushRiggedBatches(", start)
    with tempfile.TemporaryDirectory(prefix="boxxy-shadow-batching-") as directory:
        cpp = Path(directory) / "check.cpp"
        exe = Path(directory) / "check.exe"
        cpp.write_text(STUBS + source[start:end] + CHECKS)
        for darwin in (0, 1):
            subprocess.run([compiler, "-std=c++17", f"-DLL_DARWIN={darwin}",
                            str(cpp), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)
    print("Passed shadow batching: identical indices/transforms, 9 to 6 fixture draws, platform limits")


if __name__ == "__main__":
    main()
