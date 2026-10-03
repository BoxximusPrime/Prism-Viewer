"""Exercise production batch-bound accumulation and glTF preparation blocks."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def block(text, signature):
    start = text.index(signature)
    opening = text.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main():
    volume = (ROOT / "indra/newview/llvovolume.cpp").read_text()
    particle = (ROOT / "indra/newview/llvopartgroup.cpp").read_text()
    primitive = (ROOT / "indra/newview/gltf/primitive.cpp").read_text()
    volume_bounds = block(volume, "    if (type == LLRenderPass::PASS_ALPHA && !rigged)")
    particle_bounds = block(particle, "        for (U32 corner = 0; corner < 4; ++corner)")
    preparation = primitive[primitive.index("    mAlphaBounds = {};"):primitive.index("    createOctree();", primitive.index("    mAlphaBounds = {};"))]
    harness = r'''
#include "llalphalightselection.h"
#include <cassert>
#include <cstdint>
#include <iostream>
using F32 = float;
using U32 = uint32_t;
using U64 = uint64_t;
struct LLVector3 {
    float v[3]{};
    LLVector3(float x=0,float y=0,float z=0):v{x,y,z}{}
    float operator[](int i) const { return v[i]; }
    static const LLVector3 zero;
};
const LLVector3 LLVector3::zero;
struct LLVector4a {
    float v[4]{};
    LLVector4a(float x=0,float y=0,float z=0,float w=0):v{x,y,z,w}{}
    const float* getF32ptr() const { return v; }
};
struct Region { LLVector3 origin; LLVector3 getOriginAgent() const { return origin; } };
struct Drawable { bool active; Region region; bool isActive() const { return active; } const Region* getRegion() const { return &region; } };
struct Face { LLVector4a mExtents[2]; };
struct Draw { LLAlphaLightSelection::Bounds mAlphaLightBounds; };
struct LLRenderPass { enum { PASS_ALPHA=1, PASS_OPAQUE=2 }; };
void addVolume(int type, bool rigged, const Drawable* drawable, const Face* facep, Draw* info) {
''' + volume_bounds + r'''
}
void addParticle(LLVector4a* light_vertices, const std::vector<Draw*>& draw_vec) {
''' + particle_bounds + r'''
}
struct Primitive {
    std::vector<LLVector4a> mPositions, mWeights;
    std::vector<U64> mJoints;
    LLAlphaLightSelection::Bounds mAlphaBounds;
    std::vector<LLAlphaLightSelection::Bounds> mAlphaJointBounds;
    bool mAlphaSkinBoundsValid=false, mAlphaWeightRoundoff=false;
    float mAlphaWeightMaxSum=1;
    void prepBounds() {
''' + preparation + r'''
    }
};
using namespace LLAlphaLightSelection;
bool contains(const Bounds& b, Vec3 p) {
    for (int axis=0;axis<3;++axis) if (p[axis]<b.min[axis] || p[axis]>b.max[axis]) return false;
    return b.valid();
}
int main() {
    // Static face boxes already include the region offset; vertices do not.
    Drawable static_object{false, {{256,-512,32}}};
    Face a{{{257,-510,35}, {259,-508,37}}}, b{{{261,-516,30}, {266,-509,42}}};
    Draw batch;
    addVolume(LLRenderPass::PASS_ALPHA,false,&static_object,&a,&batch);
    addVolume(LLRenderPass::PASS_ALPHA,false,&static_object,&b,&batch);
    assert((batch.mAlphaLightBounds.min == Vec3{1,-4,-2}));
    assert((batch.mAlphaLightBounds.max == Vec3{10,4,10}));
    std::array<float,16> model{1,0,0,0, 0,1,0,0, 0,0,1,0, 256,-512,32,1};
    Bounds agent = transform(batch.mAlphaLightBounds,model);
    assert(contains(agent,{257,-510,35}) && contains(agent,{266,-509,42}));
    // Moving geometry keeps its root-local box, then follows the current model.
    Drawable moving{true, {{256,-512,32}}};
    Face local{{{-2,-1,-3}, {2,1,3}}};
    Draw active;
    addVolume(LLRenderPass::PASS_ALPHA,false,&moving,&local,&active);
    model = {0,2,0,0, -3,0,0,0, 0,0,.5f,0, 10,20,30,1};
    agent = transform(active.mAlphaLightBounds,model);
    assert(contains(agent,{7,24,31.5f}) && contains(agent,{13,16,28.5f}));
    Draw skipped;
    addVolume(LLRenderPass::PASS_OPAQUE,false,&moving,&local,&skipped);
    addVolume(LLRenderPass::PASS_ALPHA,true,&moving,&local,&skipped);
    assert(!skipped.mAlphaLightBounds.valid()); // live avatar bounds supply rigged coverage
    // The full ribbon/quad corners from two particles stay in the existing batch.
    LLVector4a corners[4]={{-3,-2,1},{3,-2,1},{3,2,1},{-3,2,1}};
    LLVector4a ribbon[4]={{-4,0,-1},{-4,1,-1},{8,1,9},{8,0,9}};
    Draw particles;
    addParticle(corners,{&particles}); addParticle(ribbon,{&particles});
    assert((particles.mAlphaLightBounds.min == Vec3{-4,-2,-1}));
    assert((particles.mAlphaLightBounds.max == Vec3{8,2,9}));
    Primitive skin;
    skin.mPositions={{1,2,3},{-4,5,6}};
    skin.mWeights={{.25f,.75f,0,0},{1,0,0,0}};
    skin.mJoints={U64(1)<<16, 1}; // packed four uint16 indices
    skin.prepBounds();
    assert(skin.mAlphaSkinBoundsValid && skin.mAlphaJointBounds.size()==2);
    assert(contains(skin.mAlphaJointBounds[0],{1,2,3}));
    assert(contains(skin.mAlphaJointBounds[1],{-4,5,6}));
    assert(!skin.mAlphaWeightRoundoff && skin.mAlphaWeightMaxSum==1);
    skin.mWeights[0].v[0]=.25001f; skin.prepBounds();
    assert(skin.mAlphaSkinBoundsValid && skin.mAlphaWeightRoundoff && skin.mAlphaWeightMaxSum>1);
    skin.mWeights[0].v[0]=-.25f; skin.prepBounds(); assert(!skin.mAlphaSkinBoundsValid);
    skin.mWeights[0].v[0]=.5f; skin.prepBounds(); assert(!skin.mAlphaSkinBoundsValid);
    skin.mWeights[0].v[0]=.25f; skin.mJoints.pop_back(); skin.prepBounds(); assert(!skin.mAlphaSkinBoundsValid);
    skin.mPositions[0].v[0]=std::numeric_limits<float>::quiet_NaN(); skin.prepBounds();
    assert(!skin.mAlphaBounds.valid() && !skin.mAlphaSkinBoundsValid);
    std::cout << "Passed production receiver bounds: static region offsets, moving/rotated/scaled batches, "
                 "particle/ribbon unions, glTF packed joints/weights and malformed fallback\n";
}
'''
    compiler = shutil.which("g++")
    if not compiler:
        raise SystemExit("g++ required")
    with tempfile.TemporaryDirectory(prefix="alpha-receiver-bounds-") as directory:
        cpp, exe = Path(directory) / "bounds.cpp", Path(directory) / "bounds.exe"
        cpp.write_text(harness)
        subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "indra/newview"), str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
