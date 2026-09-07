"""Run production appearance writes and face-area caching against recording stubs.

Run: python scripts/tests/test_texture_appearance_updates.py (g++ on PATH).
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

APPEARANCE = r'''
#include <array>
#include <cassert>
#include <map>
#include <vector>
#define LL_PROFILE_ZONE_SCOPED_CATEGORY_AVATAR
using U32 = unsigned;
using F32 = float;
using LLUUID = int;
using ETextureIndex = int;
using ESex = int;
using texture_vec_t = std::vector<int>;
namespace LLWearableType { enum EType { SHAPE, SKIN, WT_COUNT, WT_INVALID = 255 }; }
constexpr int FTT_DEFAULT = 0;
struct LLGLTexture { enum { BOOST_NONE }; };
struct LLViewerTexture { enum { LOD_TEXTURE }; int id; int getID() const { return id; } };
struct LLViewerTextureManager {
    inline static std::map<int, LLViewerTexture> images;
    inline static int fetches = 0;
    static LLViewerTexture* getFetchedTexture(int id, int, bool, int, int) {
        ++fetches; return &images.insert_or_assign(id, LLViewerTexture{id}).first->second;
    }
};
struct Dictionary {
    struct Entry { int mWearableType; };
    Entry a{0}, b{1}, c{0}, baked{255};
    std::map<int, Entry*> entries{{0,&a},{1,&b},{2,&c},{3,&baked}};
    int scans = 0;
    const auto& getTextures() { ++scans; return entries; }
};
struct LLAvatarAppearance {
    virtual ~LLAvatarAppearance() = default;
    int sex = 0;
    int getSex() { return sex; }
    static Dictionary* getDictionary() { static Dictionary d; return &d; }
};
struct LLViewerVisualParam {
    bool cross = false; int id = 42, type = 0, writes = 0; float weight = 0;
    bool getCrossWearable() const { return cross; }
    int getWearableType() const { return type; }
    int getID() const { return id; }
    void setWeight(float w) { weight = w; ++writes; }
};
struct LLVOAvatarSelf : LLAvatarAppearance {
    bool valid = true; int sex_updates = 0, texture_updates = 0;
    LLViewerTexture initial{0};
    LLViewerTexture* textures[4]{&initial,&initial,&initial,&initial};
    bool isValid() { return valid; }
    LLViewerTexture* getTEImage(int te) { return textures[te]; }
    void setLocalTextureTE(int te, LLViewerTexture* image, int) {
        if (textures[te]->id != image->id) { textures[te] = image; ++texture_updates; }
    }
    void updateSexDependentLayerSets() { ++sex_updates; }
    bool setParamWeight(LLViewerVisualParam*, float);
};
struct LLWearable {
    int base_writes = 0; bool change_sex = false;
    void writeToAvatar(LLAvatarAppearance* a) { ++base_writes; if (change_sex) a->sex = 1; }
};
struct LocalTexture { int id; int getID() { return id; } };
struct LLViewerWearable : LLWearable {
    using te_map_t = std::map<int, LocalTexture*>;
    te_map_t mTEMap;
    int mType = 0, driven_writes = 0;
    float driven_weight = 0;
    int getDefaultTextureImageID(int te) { return 100+te; }
    void setVisualParamWeight(int, float w) { ++driven_writes; driven_weight = w; }
    void writeToAvatar(LLAvatarAppearance*);
};
struct {
    std::vector<LLViewerWearable*> layers;
    U32 getWearableCount(LLWearableType::EType) { return layers.size(); }
    LLViewerWearable* getViewerWearable(LLWearableType::EType, U32 n) { return layers[n]; }
} gAgentWearables;
'''

APPEARANCE_CHECKS = r'''
int main() {
    LLVOAvatarSelf avatar;
    LLViewerWearable shape, skin;
    skin.mType = 1;
    LocalTexture changed{201}; skin.mTEMap[1] = &changed;
    shape.writeToAvatar(&avatar); skin.writeToAvatar(&avatar);
    assert(avatar.textures[0]->id == 100 && avatar.textures[1]->id == 201 && avatar.textures[2]->id == 102);
    assert(avatar.textures[3]->id == 0 && LLViewerTextureManager::fetches == 3);
    for (int i=0; i<100; ++i) { shape.writeToAvatar(&avatar); skin.writeToAvatar(&avatar); }
    assert(LLAvatarAppearance::getDictionary()->scans == 1);
    assert(LLViewerTextureManager::fetches == 3 && avatar.texture_updates == 3);
    assert(shape.base_writes == 101 && skin.base_writes == 101); // driver writes remain active
    changed.id = 202; skin.writeToAvatar(&avatar);
    assert(avatar.textures[1]->id == 202 && LLViewerTextureManager::fetches == 4);
    skin.mTEMap.clear(); skin.writeToAvatar(&avatar);
    assert(avatar.textures[1]->id == 101); // default restored
    shape.change_sex = true; shape.writeToAvatar(&avatar);
    assert(avatar.sex_updates == 1);
    int writes = shape.base_writes;
    avatar.valid = false; shape.writeToAvatar(&avatar);
    LLAvatarAppearance other; shape.writeToAvatar(&other); shape.writeToAvatar(nullptr);
    assert(shape.base_writes == writes);
    LLViewerVisualParam param;
    assert(!avatar.setParamWeight(nullptr, .5f));
    assert(avatar.setParamWeight(&param, .5f) && param.writes == 1);
    param.cross = true; gAgentWearables.layers = {&shape, nullptr, &skin};
    avatar.setParamWeight(&param, .7f); avatar.setParamWeight(&param, .7f);
    assert(param.writes == 3 && shape.driven_writes == 2 && skin.driven_writes == 2);
    assert(shape.driven_weight == .7f && skin.driven_weight == .7f);
}
'''

FACE = r'''
#include <algorithm>
#include <cassert>
#include <cfloat>
#include <cmath>
#include <vector>
using F32 = float;
using S32 = int;
#define LL_PROFILE_ZONE_SCOPED_CATEGORY_FACE
#define LL_PROFILE_ZONE_NAMED_CATEGORY_FACE(x)
template<class T> T llmax(T a,T b) { return std::max(a,b); }
float gFrameTimeSeconds = 0;
float ll_frand() { return .5f; }
struct Scalar { float v; float getF32() const { return v; } operator float() const { return v; } };
struct LLVector3 { float mV[3]; };
struct LLVector4a {
    float v[3];
    LLVector4a(float x=0,float y=0,float z=0) : v{x,y,z} {}
    void load3(const float* p) { std::copy(p,p+3,v); }
    void setAdd(const LLVector4a& a,const LLVector4a& b) { for(int i=0;i<3;++i)v[i]=a.v[i]+b.v[i]; }
    void setSub(const LLVector4a& a,const LLVector4a& b) { for(int i=0;i<3;++i)v[i]=a.v[i]-b.v[i]; }
    void setMin(const LLVector4a& a,const LLVector4a& b) { for(int i=0;i<3;++i)v[i]=std::min(a.v[i],b.v[i]); }
    void setMax(const LLVector4a& a,const LLVector4a& b) { for(int i=0;i<3;++i)v[i]=std::max(a.v[i],b.v[i]); }
    void mul(float s) { for(float& f:v)f*=s; }
    Scalar dot3(const LLVector4a& b) const { return {v[0]*b.v[0]+v[1]*b.v[1]+v[2]*b.v[2]}; }
    Scalar getLength3() const { return {std::sqrt(dot3(*this).v)}; }
    void normalize3fast() { mul(1.f/getLength3().v); }
};
struct LLMatrix4a { void loadu(float*) {} };
void matMulBoundBox(const LLMatrix4a&, const LLVector4a* in, LLVector4a* out) { out[0]=in[0];out[1]=in[1]; }
struct LLJoint { struct Matrix { float mMatrix[4][4]; } mat; Matrix& getWorldMatrix() { return mat; } };
struct RigInfo {
    bool isRiggedTo() { return false; }
    LLVector4a* getRiggedExtents() { static LLVector4a e[2];return e; }
};
struct RigTable : std::vector<RigInfo> { bool needsUpdate() { return false; } };
struct LLVolumeFace { RigTable mJointRiggingInfoTab; };
struct LLVolume { LLVolumeFace face; LLVolumeFace& getVolumeFace(int) { return face; } };
struct LLMeshSkinInfo {};
struct LLSpatialGroup { LLVector4a e[2]; const LLVector4a* getExtents() { return e; } };
struct LLDrawable { inline static float sCurPixelAngle = 100; LLSpatialGroup* getSpatialGroup() { return nullptr; } };
struct LLVOAvatar { LLDrawable* mDrawable = nullptr; LLJoint* getJoint(int) { return nullptr; } };
struct LLViewerObject {
    LLVOAvatar* getAvatar() { return nullptr; }
    LLVolume* getVolume() { return nullptr; }
    int getPartitionType() { return 0; }
};
struct LLVOVolume : LLViewerObject { const LLMeshSkinInfo* getSkinInfo() { return nullptr; } };
namespace LLSkinningUtil { void updateRiggingInfo(const LLMeshSkinInfo*,LLVOAvatar*,LLVolumeFace&) {} }
struct LLViewerRegion { enum { PARTITION_PARTICLE = 1 }; };
struct Pointer {
    LLViewerObject* p = nullptr;
    bool notNull() { return p; } LLViewerObject* get() { return p; } LLViewerObject* operator->() { return p; }
};
struct LLViewerCamera {
    LLVector3 origin{{0,0,0}}, axis{{1,0,0}};
    bool visible = true; int checks = 0;
    static LLViewerCamera* getInstance() { static LLViewerCamera c;return &c; }
    const LLVector3& getOrigin() { return origin; } const LLVector3& getXAxis() { return axis; }
    float getCosHalfFov() { return .8f; }
    bool AABBInFrustum(const LLVector4a&,const LLVector4a&) { ++checks;return visible; }
};
struct LLFace {
    enum { RIGGED = 1 };
    int state = 0, mTEOffset = 0; bool media = false;
    Pointer mVObjp;
    LLDrawable* mDrawablep = nullptr;
    LLVector4a mRiggedExtents[2],mExtents[2]{{-1,-1,-1},{1,1,1}};
    LLVector3 position{{10,3,0}};
    float mPixelArea = 0, mImportanceToCamera = 0, mBoundingSphereRadius = 0;
    bool isState(int flag) { return state&flag; } bool hasMedia() { return media; }
    LLVector3 getPositionAgent() { return position; }
    static float calcImportanceToCamera(float a,float) { return a; }
    bool calcPixelArea(float&,float&);
'''

FACE_CHECKS = r'''
int main() {
    LLFace face;
    float a=-999,r=-999;
    assert(face.calcPixelArea(a,r) && r>0 && a>0 && a<1); // first call at time zero
    float saved_a=a,saved_r=r,area=face.mPixelArea;
    gFrameTimeSeconds=.05f; face.position={{20,8,0}}; a=r=-999;
    assert(face.calcPixelArea(a,r) && a==saved_a && r==saved_r && face.mPixelArea==area);
    auto* camera=LLViewerCamera::getInstance();
    face.media=true; camera->visible=false; gFrameTimeSeconds=.2f;
    assert(!face.calcPixelArea(a,r) && face.mImportanceToCamera==0);
    saved_a=a;saved_r=r;int checks=camera->checks;
    gFrameTimeSeconds=.25f;camera->visible=true;a=r=-999;
    assert(!face.calcPixelArea(a,r) && a==saved_a && r==saved_r && camera->checks==checks);
    gFrameTimeSeconds=.4f;
    assert(face.calcPixelArea(a,r) && a==1.f && camera->checks==checks+1);
    saved_r=r;gFrameTimeSeconds=.45f;a=r=-999;
    assert(face.calcPixelArea(a,r) && a==1.f && r==saved_r); // cache post-media angle
    face.state=LLFace::RIGGED;gFrameTimeSeconds=.6f;
    assert(!face.calcPixelArea(a,r)); // missing rigged bounds remain rejected
}
'''


def extract(source, start, end):
    return source[source.index(start):source.index(end, source.index(start))]


def main():
    compiler = shutil.which("g++")
    if compiler is None:
        raise SystemExit("g++ must be on PATH")
    root = Path(__file__).resolve().parents[2] / "indra/newview"
    appearance = extract((root / "llviewerwearable.cpp").read_text(),
                         "void LLViewerWearable::writeToAvatar(", "// Updates the user's avatar's appearance, replacing")
    parameter = extract((root / "llvoavatarself.cpp").read_text(),
                        "bool LLVOAvatarSelf::setParamWeight(", "/*virtual*/\nvoid LLVOAvatarSelf::updateVisualParams()")
    area = extract((root / "llface.cpp").read_text(),
                   "bool LLFace::calcPixelArea(", "//the projection of the face partially overlaps")
    fields = extract((root / "llface.h").read_text(),
                     "    F32         mLastPixelAreaUpdate", "    // virtual size of face")
    cases = [("appearance", APPEARANCE + appearance + parameter + APPEARANCE_CHECKS),
             ("face", FACE + fields + "};\n" + area + FACE_CHECKS)]
    with tempfile.TemporaryDirectory(prefix="boxxy-texture-appearance-") as directory:
        for name, source in cases:
            cpp, exe = Path(directory) / f"{name}.cpp", Path(directory) / f"{name}.exe"
            cpp.write_text(source)
            subprocess.run([compiler, "-std=c++17", str(cpp), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)
    print("Passed appearance propagation, unchanged texture fetch suppression, slot indexing, and complete face-area cache outputs")


if __name__ == "__main__":
    main()
