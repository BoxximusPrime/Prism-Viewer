"""Check production shader-source fingerprinting and cache reinitialization.

Run: python scripts/tests/test_shader_source_cache.py (g++ on PATH).
The hash stub records inputs; XXH itself is an existing library, not under test.
"""

from pathlib import Path
import shutil
import subprocess
import tempfile


def function(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


STUBS = r'''
#include <algorithm>
#include <cassert>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <map>
#include <string>
#include <vector>
#define LL_WARNS(x) std::cerr
#define LL_INFOS(x) std::cerr
#define LL_ENDL std::endl
#define LL_PROFILE_ZONE_SCOPED
struct LLUUID {
    std::string value;
    std::string asString() const { return value; }
    bool operator==(const LLUUID& other) const { return value == other.value; }
};
struct HBXXH128 {
    std::string inputs;
    HBXXH128() = default;
    HBXXH128(std::istream& input) {
        inputs.assign(std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>());
    }
    void update(const std::string& text) {
        inputs += std::to_string(text.size()) + ":" + text;
    }
    void update(const char* data, size_t size) { update(std::string(data,size)); }
    LLUUID digest() const { return { inputs }; }
};
struct { double mGLVersion = 4.6; } gGLManager;
struct LLShaderMgr {
    bool mShaderCacheEnabled = false;
    LLUUID mShaderCacheVersion;
    std::map<int,int> mShaderBinaryCache;
    void initShaderCache(bool enabled, const LLUUID& old_cache_version,
                         const LLUUID& current_cache_version, bool second_instance);
};
'''

CHECKS = r'''
int main(int argc, char** argv) {
    namespace fs = std::filesystem;
    const fs::path root(argv[1]);
    auto write = [](const fs::path& path, const std::string& data) {
        fs::create_directories(path.parent_path());
        std::ofstream(path, std::ios::binary) << data;
    };
    auto fingerprint = [](const fs::path& path) {
        HBXXH128 hash;
        assert(hashShaderSources(hash, path));
        return hash.digest().asString();
    };
    write(root / "class3/deferred/main.glsl", "main");
    write(root / "class1/deferred/helper.glsl", "AAAA");
    const auto first = fingerprint(root);
    assert(fingerprint(root) == first);
    write(root / "README.txt", "ignored");
    assert(fingerprint(root) == first);
    const auto helper = root / "class1/deferred/helper.glsl";
    const auto timestamp = fs::last_write_time(helper);
    write(helper, "BBBB"); // same name, size, and timestamp; contents must drive invalidation
    fs::last_write_time(helper, timestamp);
    assert(fingerprint(root) != first);
    write(helper, "AAAA");
    assert(fingerprint(root) == first);
    write(root / "class2/fallback.glsl", "fallback");
    assert(fingerprint(root) != first);
    fs::remove(root / "class2/fallback.glsl");
    assert(fingerprint(root) == first);
    fs::rename(helper, root / "class1/deferred/renamed.glsl");
    assert(fingerprint(root) != first);
    fs::rename(root / "class1/deferred/renamed.glsl", helper);
    const fs::path copy = root.parent_path() / "relocated";
    fs::copy(root, copy, fs::copy_options::recursive);
    assert(fingerprint(copy) == first);
    HBXXH128 empty, missing;
    fs::create_directory(root / "empty");
    assert(!hashShaderSources(empty, root / "empty"));
    assert(!hashShaderSources(missing, root / "absent"));

    LLShaderMgr cache;
    const LLUUID oldVersion{"old"}, newVersion{"new"};
    cache.initShaderCache(true, oldVersion, oldVersion, false);
    cache.mShaderBinaryCache[1] = 42;
    cache.initShaderCache(true, oldVersion, oldVersion, false);
    assert(cache.mShaderBinaryCache.size() == 1); // normal reload retains matching binaries
    cache.initShaderCache(true, oldVersion, newVersion, false);
    assert(cache.mShaderBinaryCache.empty()); // changed sources discard in-memory binaries too
    assert(cache.mShaderCacheVersion == newVersion);
    cache.mShaderBinaryCache[2] = 43;
    cache.initShaderCache(false, newVersion, oldVersion, false);
    assert(!cache.mShaderCacheEnabled && cache.mShaderCacheVersion == newVersion);
    cache.initShaderCache(true, newVersion, oldVersion, false);
    assert(cache.mShaderBinaryCache.empty() && cache.mShaderCacheVersion == oldVersion);
    std::cout << "Source edits/additions/removals/renames, relocation, errors, and same-session cache invalidation passed.\n";
}
'''


def main():
    root = Path(__file__).resolve().parents[2]
    viewer = (root / "indra/newview/llviewershadermgr.cpp").read_text()
    renderer = (root / "indra/llrender/llshadermgr.cpp").read_text()
    fingerprint = function(viewer, "static bool hashShaderSources(")
    # Exercise the real version guard before the disk-cache/LLSD portion begins.
    init = function(renderer, "void LLShaderMgr::initShaderCache(")
    init = init[:init.index("    mShaderCacheDir =")] + "}\n"
    compiler = shutil.which("g++")
    if compiler is None:
        raise SystemExit("g++ must be on PATH")
    with tempfile.TemporaryDirectory(prefix="boxxy-shader-cache-") as directory:
        source = Path(directory) / "check.cpp"
        executable = Path(directory) / "check.exe"
        source.write_text(STUBS + fingerprint + init + CHECKS)
        subprocess.run([compiler, "-std=c++20", str(source), "-o", str(executable)], check=True)
        subprocess.run([str(executable), str(Path(directory) / "shaders")], check=True)


if __name__ == "__main__":
    main()
