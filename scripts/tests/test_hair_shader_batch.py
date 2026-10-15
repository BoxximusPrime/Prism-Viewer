"""Exercise the production hair shader loader's batch/fallback lifetime."""
from pathlib import Path
import shutil
import subprocess
import tempfile

from test_shader_source_cache import function


STUBS = r'''
#include <cassert>
#include <iostream>
#include <string>
#include <utility>
#include <vector>
#define LL_DARWIN 0
#define LL_WARNS(x) std::cerr
#define LL_ENDL std::endl
constexpr int GL_COMPUTE_SHADER = 1, GL_VERTEX_SHADER = 2, GL_FRAGMENT_SHADER = 3;
struct { float mGLVersion = 4.6f; } gGLManager;
bool glDispatchCompute = true, sReady = false;
bool parallel = true, batching = false, batchOK = true;
int submitted = 0, finished = 0, failAt = -1, unloads = 0;
struct LLGLSLShader {
    std::string mName;
    struct { bool attachNothing = false; } mFeatures;
    std::vector<std::pair<std::string, int>> mShaderFiles;
    int mShaderLevel = 0;
    void clearPermutations() {}
    void addPermutation(const char*, const char*) {}
    bool createShader() {
        const bool ok = submitted++ != failAt;
        if (batching) { batchOK &= ok; return true; }
        return ok;
    }
} sSkinShader, sRefitShader, sCacheShader, sGuideShader, sDebugShader;
struct LLShaderMgr {
    static LLShaderMgr* instance() { static LLShaderMgr mgr; return &mgr; }
    void beginShaderBatch() { assert(!batching); batching = parallel; batchOK = true; }
    bool finishShaderBatch() {
        assert(submitted == 4); batching = false; ++finished; return batchOK;
    }
};
struct LLHairMesh {
    static void loadShaders();
    static void unloadShaders() { assert(!batching); sReady = false; ++unloads; }
};
int main() {
    for (bool async : {false, true}) {
        parallel = async;
        for (int failure = -1; failure < 5; ++failure) {
            failAt = failure; submitted = finished = unloads = 0;
            LLHairMesh::loadShaders();
            const bool coreOK = failure < 0 || failure == 4;
            assert(sReady == coreOK && !batching && finished == 1);
            assert(submitted == (coreOK ? 5 : 4));
            assert(unloads == (coreOK ? 1 : 2));
        }
    }
    submitted = finished = 0; glDispatchCompute = false;
    LLHairMesh::loadShaders();
    assert(!sReady && !batching && submitted == 0 && finished == 0);
    std::cout << "PASS: hair jobs batched, drained before unload, optional preview failure and unsupported GPU\n";
}
'''


def main():
    root = Path(__file__).resolve().parents[2]
    source = (root / "indra/newview/llhairmesh.cpp").read_text()
    method = function(source, "void LLHairMesh::loadShaders(")
    compiler = shutil.which("g++")
    assert compiler, "g++ must be on PATH"
    with tempfile.TemporaryDirectory(prefix="prism-hair-shader-batch-") as directory:
        cpp = Path(directory) / "check.cpp"
        exe = Path(directory) / "check.exe"
        cpp.write_text(STUBS + method)
        subprocess.run([compiler, "-std=c++20", str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
