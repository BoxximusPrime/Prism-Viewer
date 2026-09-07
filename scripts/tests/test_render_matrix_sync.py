"""Exercise production matrix synchronization using bundled GLM and uniform stubs.

Run: python scripts/tests/test_render_matrix_sync.py (g++ and build packages required).
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

STUBS = r'''
#include <glm/glm.hpp>
#include <glm/gtc/type_ptr.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtx/transform.hpp>
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#define STOP_GLERROR
#define LL_PROFILE_ZONE_SCOPED_CATEGORY_DISPLAY
using U32 = uint32_t;
using S32 = int;
using F32 = float;
constexpr bool GL_FALSE = false;
struct LLShaderMgr { enum {
    MODELVIEW_MATRIX, PROJECTION_MATRIX, TEXTURE_MATRIX0, TEXTURE_MATRIX1,
    TEXTURE_MATRIX2, TEXTURE_MATRIX3, NORMAL_MATRIX, INVERSE_MODELVIEW_MATRIX,
    MODELVIEW_PROJECTION_MATRIX, INVERSE_PROJECTION_MATRIX, IDENTITY_MATRIX, COUNT
}; };
int inversions = 0;
glm::mat4 counted_inverse(const glm::mat4& m) { ++inversions; return glm::inverse(m); }
struct LLGLSLShader {
    inline static LLGLSLShader* sCurBoundShaderPtr;
    std::array<U32, 6> mMatHash{~0u,~0u,~0u,~0u,~0u,~0u};
    bool active[LLShaderMgr::COUNT]{};
    glm::mat4 matrices[LLShaderMgr::COUNT];
    glm::mat3 normal;
    struct { bool hasLighting = false, calculatesLighting = false, calculatesAtmospherics = false; } mFeatures;
    int getUniformLocation(int n) { return active[n] ? n : -1; }
    void uniformMatrix4fv(int n, int, bool, const float* p) {
        if (active[n]) matrices[n] = glm::make_mat4(p);
    }
    void uniformMatrix3fv(int n, int, bool, const float* p) {
        if (active[n]) normal = glm::make_mat3(p);
    }
};
struct LLRender {
    enum { MM_MODELVIEW, MM_PROJECTION, MM_TEXTURE0, MM_TEXTURE1, MM_TEXTURE2, MM_TEXTURE3, NUM_MATRIX_MODES };
    U32 mMatHash[6]{0,0,0,0,0,0};
    int mMatIdx[6]{};
    glm::mat4 mMatrix[6][1];
    void syncLightState() {}
    void syncMatrices();
};
void equal(const glm::mat4& a, const glm::mat4& b) {
    for (int i=0; i<4; ++i) for (int j=0; j<4; ++j) assert(std::abs(a[i][j]-b[i][j]) < .00001f);
}
'''

CHECKS = r'''
int main() {
    LLRender render;
    for (auto& m : render.mMatrix) m[0] = glm::mat4(1.f);
    LLGLSLShader depth, lit, inverse_only;
    depth.active[LLShaderMgr::MODELVIEW_PROJECTION_MATRIX] = true;
    lit.active[LLShaderMgr::NORMAL_MATRIX] = true;
    lit.active[LLShaderMgr::INVERSE_MODELVIEW_MATRIX] = true;
    inverse_only.active[LLShaderMgr::INVERSE_MODELVIEW_MATRIX] = true;
    for (int frame = 1; frame <= 3; ++frame) {
        auto matrix = glm::translate(glm::mat4(1.f), glm::vec3(frame, 2, 3)) *
                      glm::scale(glm::mat4(1.f), glm::vec3(2, 3, frame + 1));
        render.mMatrix[0][0] = matrix; ++render.mMatHash[0];
        LLGLSLShader::sCurBoundShaderPtr = &depth;
        int before = inversions;
        render.syncMatrices();
        assert(inversions == before);
        equal(depth.matrices[LLShaderMgr::MODELVIEW_PROJECTION_MATRIX], matrix);
        LLGLSLShader::sCurBoundShaderPtr = &lit;
        render.syncMatrices();
        assert(inversions == before + 1);
        auto inverse = glm::inverse(matrix);
        equal(lit.matrices[LLShaderMgr::INVERSE_MODELVIEW_MATRIX], inverse);
        auto normal = glm::mat3(glm::transpose(inverse));
        for (int i=0; i<3; ++i) for (int j=0; j<3; ++j) assert(std::abs(lit.normal[i][j]-normal[i][j]) < .00001f);
        LLGLSLShader::sCurBoundShaderPtr = &inverse_only;
        render.syncMatrices(); render.syncMatrices();
        assert(inversions == before + 1);
        equal(inverse_only.matrices[LLShaderMgr::INVERSE_MODELVIEW_MATRIX], inverse);
    }
    LLGLSLShader::sCurBoundShaderPtr = nullptr;
    render.syncMatrices();
}
'''


def main():
    compiler = shutil.which("g++")
    if compiler is None:
        raise SystemExit("g++ must be on PATH")
    root = Path(__file__).resolve().parents[2]
    source = (root / "indra/llrender/llrender.cpp").read_text()
    start = source.index("void LLRender::syncMatrices()")
    end = source.index("void LLRender::translatef(", start)
    # Count the production inverse calls while retaining GLM's actual arithmetic.
    method = source[start:end].replace("glm::inverse(", "counted_inverse(")
    with tempfile.TemporaryDirectory(prefix="boxxy-matrix-sync-") as directory:
        cpp, exe = Path(directory) / "check.cpp", Path(directory) / "check.exe"
        cpp.write_text(STUBS + method + CHECKS)
        subprocess.run([compiler, "-std=c++17", "-DGLM_ENABLE_EXPERIMENTAL",
                        "-I", str(root / "build-vc170-64/packages/include"),
                        str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("Passed matrix sync: depth skips inverse, lit/inverse-only shaders receive correct matrices and share cache")


if __name__ == "__main__":
    main()
