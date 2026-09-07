"""Compare production extent traversal with the original exhaustive traversal.

Run: python scripts/tests/test_shadow_visible_extents.py (g++ on PATH).
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

STUBS = r'''
#include <algorithm>
#include <cassert>
#include <vector>
#define llassert assert
using S32 = int;
struct LLVector4a { int x; };
void update_min_max(LLVector4a& a, LLVector4a& b, LLVector4a v) {
    a.x = std::min(a.x, v.x); b.x = std::max(b.x, v.x);
}
struct LLCamera {};
struct LLSpatialGroup;
struct OctreeNode {
    LLSpatialGroup* group;
    OctreeNode* parent = nullptr;
    int elements = 1;
    std::vector<OctreeNode*> children;
    LLSpatialGroup* getListener(int) const { return group; }
    OctreeNode* getParent() const { return parent; }
    int getElementCount() const { return elements; }
};
struct LLSpatialGroup {
    enum { OCCLUDED = 1, SKIP_FRUSTUM_CHECK = 2, DIRTY = 4 };
    OctreeNode* node;
    int flags = 0, frustum = 2, objects_frustum = 2;
    LLVector4a extents[2], objects[2];
    OctreeNode* getOctreeNode() { return node; }
    bool isOcclusionState(int mask) const { return flags & mask; }
    bool hasState(int mask) const { return flags & mask; }
    bool isEmpty() const { return node->elements == 0; }
    const LLVector4a* getExtents() const { return extents; }
    const LLVector4a* getObjectExtents() const { return objects; }
};
using LLViewerOctreeGroup = LLSpatialGroup;
struct LLPipeline { inline static int sUseOcclusion = 1; };
struct OctreeTraveler {
    int visits = 0;
    virtual void visit(const OctreeNode*) = 0;
    virtual void traverse(const OctreeNode* n) {
        ++visits;
        visit(n);
        for (auto* child : n->children) traverse(child);
    }
};
struct LLOctreeCullShadow : OctreeTraveler {
    int mRes = 0;
    LLOctreeCullShadow(LLCamera*) {}
    virtual bool earlyFail(LLViewerOctreeGroup*) { return false; }
    int frustumCheck(const LLViewerOctreeGroup* g) { return g->frustum; }
    int AABBInFrustumObjectBounds(const LLViewerOctreeGroup* g) { return g->objects_frustum; }
    virtual void processGroup(LLViewerOctreeGroup*) = 0;
    void visit(const OctreeNode* n) override {
        if (n->elements && (n->children.empty() || mRes != 1 || n->group->objects_frustum))
            processGroup(n->group);
    }
};
'''

CHECKS = r'''
struct Reference : LLOctreeCullVisExtents {
    using LLOctreeCullVisExtents::LLOctreeCullVisExtents;
    void traverse(const OctreeNode* n) override {
        auto* group = n->group;
        if (earlyFail(group)) return;
        if ((mRes && group->hasState(LLSpatialGroup::SKIP_FRUSTUM_CHECK)) || mRes == 2) {
            OctreeTraveler::traverse(n);
        } else {
            mRes = frustumCheck(group);
            if (mRes) OctreeTraveler::traverse(n);
            mRes = 0;
        }
    }
};
int main() {
    // Exhaust boundary combinations, including an empty internal node and an
    // occluded child whose bounds are already included by its nonempty parent.
    for (int root_result = 0; root_result <= 2; ++root_result)
    for (int root_elements = 0; root_elements <= 1; ++root_elements)
    for (int child_result = 0; child_result <= 2; ++child_result)
    for (int flags = 0; flags < 4; ++flags)
    for (int occlusion = 0; occlusion <= 1; ++occlusion) {
        OctreeNode n[4];
        LLSpatialGroup g[4];
        for (int i = 0; i < 4; ++i) { n[i].group = &g[i]; g[i].node = &n[i]; }
        n[0].children = {&n[1], &n[3]};
        n[1].children = {&n[2]};
        n[1].parent = n[3].parent = &n[0]; n[2].parent = &n[1];
        n[0].elements = root_elements;
        g[0].extents[0] = {-100}; g[0].extents[1] = {100};
        g[1].extents[0] = {-50}; g[1].extents[1] = {20};
        g[2].extents[0] = {-20}; g[2].extents[1] = {10};
        g[3].extents[0] = {50}; g[3].extents[1] = {90};
        for (auto& group : g) {
            group.objects[0] = group.extents[0]; group.objects[1] = group.extents[1];
        }
        g[0].frustum = root_result; g[1].frustum = child_result;
        g[1].flags = flags; g[2].flags = LLSpatialGroup::OCCLUDED;
        LLPipeline::sUseOcclusion = occlusion;
        LLVector4a amin{1000}, amax{-1000}, bmin{1000}, bmax{-1000};
        Reference reference(nullptr, amin, amax);
        LLOctreeCullVisExtents actual(nullptr, bmin, bmax);
        reference.traverse(&n[0]); actual.traverse(&n[0]);
        assert(reference.mEmpty == actual.mEmpty);
        assert(amin.x == bmin.x && amax.x == bmax.x);
        assert(reference.mRes == actual.mRes);
        if (root_result == 2 && root_elements) assert(actual.visits < reference.visits);
    }
}
'''


def main():
    compiler = shutil.which("g++")
    if compiler is None:
        raise SystemExit("g++ must be on PATH")
    root = Path(__file__).resolve().parents[2]
    source = (root / "indra/newview/llspatialpartition.cpp").read_text()
    start = source.index("class LLOctreeCullVisExtents:")
    end = source.index("class LLOctreeCullDetectVisible:", start)
    with tempfile.TemporaryDirectory(prefix="boxxy-shadow-extents-") as directory:
        cpp, exe = Path(directory) / "check.cpp", Path(directory) / "check.exe"
        cpp.write_text(STUBS + source[start:end] + CHECKS)
        subprocess.run([compiler, "-std=c++17", str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("Passed visible extents: 144 traversal scenarios preserve bounds, empty state and sibling state")


if __name__ == "__main__":
    main()
