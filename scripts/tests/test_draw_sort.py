"""Check the production clean-group mesh fast path with a counting partition.

Requires g++ on PATH; no running viewer or GPU is used.
"""
from pathlib import Path
import subprocess
import tempfile

from test_camera_smoothing import function


def main():
    code = r'''
#include <cassert>
#include <iostream>
struct LLSpatialGroup;
struct Partition {
    unsigned calls = 0, updates = 0;
    virtual ~Partition() = default;
    virtual void rebuildMesh(LLSpatialGroup* group);
};
struct LLSpatialGroup {
    enum { MESH_DIRTY = 1, GEOM_DIRTY = 2, ALPHA_DIRTY = 4 };
    bool dead = false;
    unsigned flags = 0;
    Partition* partition = nullptr;
    bool isDead() const { return dead; }
    bool hasState(unsigned mask) const { return (flags & mask) != 0; }
    Partition* getSpatialPartition() { assert(!dead && partition); return partition; }
    void rebuildMesh();
};
void Partition::rebuildMesh(LLSpatialGroup* group) {
    ++calls;
    // The existing volume partition defers mesh-only work until full geometry is ready.
    if (group->hasState(LLSpatialGroup::MESH_DIRTY) && !group->hasState(LLSpatialGroup::GEOM_DIRTY)) {
        ++updates;
        group->flags &= ~LLSpatialGroup::MESH_DIRTY;
    }
}
'''
    code += function("indra/newview/llspatialpartition.cpp", "void LLSpatialGroup::rebuildMesh()")
    code += r'''
int main() {
    for (unsigned flags = 0; flags < 8; ++flags) {
        Partition partition;
        LLSpatialGroup group{false, flags, &partition};
        group.rebuildMesh();
        assert(partition.calls == unsigned((flags & LLSpatialGroup::MESH_DIRTY) != 0));
        assert(partition.updates == unsigned((flags & 3) == LLSpatialGroup::MESH_DIRTY));
        assert(group.flags == (partition.updates ? flags & ~LLSpatialGroup::MESH_DIRTY : flags));
        LLSpatialGroup dead{true, flags, nullptr};
        dead.rebuildMesh(); // Must not touch a dead group's partition, even when dirty.
    }
    Partition partition;
    LLSpatialGroup group{false, LLSpatialGroup::MESH_DIRTY, &partition};
    group.rebuildMesh();
    assert(partition.calls == 1 && partition.updates == 1);
    for (int view = 0; view < 24; ++view) group.rebuildMesh();
    assert(partition.calls == 1); // Clean shadow/reflection revisits do no dispatch.
    group.flags |= LLSpatialGroup::MESH_DIRTY;
    group.rebuildMesh();
    assert(partition.calls == 2 && partition.updates == 2); // New dirtiness in the same frame is honored.
    group.flags |= LLSpatialGroup::GEOM_DIRTY | LLSpatialGroup::MESH_DIRTY;
    group.rebuildMesh();
    assert(partition.updates == 2 && group.flags == 3);
    group.flags &= ~LLSpatialGroup::GEOM_DIRTY;
    group.rebuildMesh();
    assert(partition.updates == 3 && group.flags == 0);
    std::cout << "PASS: clean/dead groups, all dirty-flag combinations, repeated views, "
                 "same-frame re-dirtying and deferred geometry updates\n";
}
'''
    with tempfile.TemporaryDirectory() as folder:
        cpp = Path(folder) / "draw_sort.cpp"
        exe = Path(folder) / "draw_sort.exe"
        cpp.write_text(code)
        subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
