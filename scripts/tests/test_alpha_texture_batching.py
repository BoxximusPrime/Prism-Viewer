"""Exercise the production texture-slot selection block with a four-slot limit.

Run with Python and g++ on PATH. Checks batch capacity and texture indices,
not viewer draw counts or GPU performance.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    root = Path(__file__).resolve().parents[2]
    source = (root / "indra/newview/llvovolume.cpp").read_text()
    start = source.index("if (facep->getTexture() != tex)",
                         source.index("U32 LLVolumeGeometryManager::genDrawInfo("))
    end = source.index("if (geom_count + facep->getGeomCount()", start)
    selection = source[start:end]
    harness = r'''
#include <cassert>
#include <vector>
using U32 = unsigned;
using U8 = unsigned char;
struct Texture {};
struct Face { Texture* texture; Texture* getTexture() { return texture; } };
struct Result { std::vector<U8> indices; U32 slots; };
Result select(const std::vector<Texture*>& initial,
              const std::vector<Texture*>& incoming, bool distance_sort) {
    constexpr U32 MAX_TEXTURE_COUNT = 32;
    const int texture_index_channels = 4;
    Texture* texture_list[MAX_TEXTURE_COUNT] = {};
    U32 texture_count = initial.size();
    for (U32 i = 0; i < texture_count; ++i) texture_list[i] = initial[i];
    Texture* tex = initial.back();
    U8 cur_tex = texture_count - 1;
    Result result;
    for (Texture* next : incoming) {
        Face face{next};
        Face* facep = &face;
''' + selection + r'''
        result.indices.push_back(cur_tex);
        assert(cur_tex < texture_count);
        assert(texture_list[cur_tex] == next);
    }
    result.slots = texture_count;
    return result;
}
int main() {
    Texture a, b, c, d, e;
    // A/B are already present; revisiting A must leave space for C and D.
    auto r = select({&a, &b}, {&a, &c, &d}, true);
    assert((r.indices == std::vector<U8>{0, 2, 3}));
    assert(r.slots == 4);
    // A full table can still revisit every existing texture, in input order.
    r = select({&a, &b, &c, &d}, {&a, &c, &b, &d, &a}, true);
    assert((r.indices == std::vector<U8>{0, 2, 1, 3, 0}));
    assert(r.slots == 4);
    // A fifth distinct texture must still cut the batch before that face.
    r = select({&a, &b, &c}, {&a, &d, &e}, true);
    assert((r.indices == std::vector<U8>{0, 3}));
    assert(r.slots == 4);
    // Long alternating sequences must not inflate the slot count.
    std::vector<Texture*> repeated;
    for (int i = 0; i < 100; ++i) repeated.push_back(i % 2 ? &b : &a);
    r = select({&a, &b}, repeated, true);
    assert(r.indices.size() == repeated.size() && r.slots == 2);
    // Existing null sentinel for distance-sorted batches stays undisturbed.
    r = select({nullptr, &a, &b}, {&a, &c}, true);
    assert((r.indices == std::vector<U8>{1, 3}) && r.slots == 4);
    // Texture-sorted opaque batches retain their sequential indexing.
    r = select({&a}, {&a, &b, &b, &c, &d, &e}, false);
    assert((r.indices == std::vector<U8>{0, 1, 1, 2, 3}));
    assert(r.slots == 4);
}
'''
    compiler = shutil.which("g++")
    if not compiler:
        raise SystemExit("g++ must be on PATH")
    with tempfile.TemporaryDirectory(prefix="prism-alpha-texture-batching-") as directory:
        cpp = Path(directory) / "check.cpp"
        exe = Path(directory) / "check.exe"
        cpp.write_text(harness)
        subprocess.run([compiler, "-std=c++17", str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("Passed alpha texture batching: repeated slots, ordering, four-slot capacity, "
          "overflow boundary, null sentinel, and texture-sorted batches")


if __name__ == "__main__":
    main()
