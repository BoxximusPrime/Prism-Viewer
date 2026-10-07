"""Execute production local-mesh validation and placement with fake GL storage.

Requires g++; uses the checkout's GLM. No viewer, simulator or uploads involved.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "indra/newview/llfloaterlocalmesh.cpp").read_text()
asset_source = (ROOT / "indra/newview/gltf/asset.cpp").read_text()


def function(text, signature):
    start = text.index(signature)
    opening = text.index("{", start)
    end, depth = opening + 1, 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


harness = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <string>
#include <vector>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/type_ptr.hpp>
using U8=uint8_t; using U16=uint16_t; using S32=int32_t; using U32=uint32_t; using U64=uint64_t; using F32=float;
using mat4=glm::mat4; using vec3=glm::vec3; using vec4=glm::vec4;
constexpr int INVALID_INDEX=-1, S32_MAX=INT32_MAX;
constexpr float F_PI_BY_TWO=1.5707963267948966f;
template<class T> T llmax(T a,T b,T c){return std::max({a,b,c});}
struct LLSkinningUtil { static int getMaxGLTFJointCount(){return 64;} };
struct { U32 mMaxUniformBlockSize=16384; } gGLManager;
struct Point { float p[4]{}; const float* getF32ptr()const{return p;} };
using LLVector4a=Point;
struct LLVector2 {float v[2]{};float& operator[](int i){return v[i];}};
struct LLVertexBuffer {
    U32 vertices=0,indices=0,mask; explicit LLVertexBuffer(U32 m):mask(m){}
    bool allocateBuffer(U32 v,U32 i){vertices=v;indices=i;return true;}
    void setBuffer(){} void unmapBuffer(){} static void unbind(){}
};
template<class T> struct LLPointer:std::shared_ptr<T> {
    using std::shared_ptr<T>::shared_ptr;
    LLPointer(T* p):std::shared_ptr<T>(p){}
    operator T*()const{return this->get();}
};
struct Buffer { int mByteLength=36; std::vector<U8> mData; };
struct BufferView { int mBuffer=0,mByteOffset=0,mByteLength=36,mByteStride=0; };
struct Accessor {
    enum class Type{SCALAR,VEC2,VEC3,VEC4,MAT4};
    enum class ComponentType{BYTE,UNSIGNED_BYTE,SHORT,UNSIGNED_SHORT,UNSIGNED_INT,FLOAT};
    int mBufferView=0,mCount=3,mByteOffset=0;
    Type mType=Type::VEC3; ComponentType mComponentType=ComponentType::FLOAT;
};
struct TextureInfo { int mIndex=-1; };
struct Material {
    struct PBR {TextureInfo mBaseColorTexture,mMetallicRoughnessTexture;vec4 mBaseColorFactor{1};float mMetallicFactor=1,mRoughnessFactor=1;} mPbrMetallicRoughness;
    std::string mName;
    TextureInfo mNormalTexture,mOcclusionTexture,mEmissiveTexture;
    bool mDoubleSided=false;
    bool multiUV=false; bool isMultiUV()const{return multiUV;}
    struct {bool mPresent=false;} mUnlit;
    enum class AlphaMode {OPAQUE,BLEND}; AlphaMode mAlphaMode=AlphaMode::OPAQUE;
};
struct Image {int mBufferView=-1;std::string mUri,mName;bool mLoadIntoTexturePipe=false;};
struct Texture {int mSource=0,mSampler=-1;};
struct Primitive {
    enum class Mode{TRIANGLES,LINES}; Mode mMode=Mode::TRIANGLES;
    int mMaterial=-1,mIndices=-1,mShaderVariant=0,mAttributeMask=7;
    U32 mVertexOffset=0,mIndexOffset=0;
    std::map<std::string,int> mAttributes{{"POSITION",0}};
    std::vector<Point> mPositions{{{-1,0,0,0}},{{1,0,0,0}},{{0,4,0,0}}};
    std::vector<U32> mIndexArray{0,1,2};
    LLVertexBuffer* mVertexBuffer=nullptr;
    U32 getVertexCount()const{return mPositions.size();}
    U32 getIndexCount()const{return mIndexArray.size();}
    void upload(LLVertexBuffer* b){assert(b->vertices==getVertexCount());assert(b->indices==getIndexCount()*2);mVertexBuffer=b;}
};
struct Mesh {std::vector<double> mWeights; std::vector<Primitive> mPrimitives;std::string mName;};
struct Node {
    int mMesh=0,mSkin=-1; std::vector<int> mChildren;
    mat4 mMatrix{1},mAssetMatrix{1}; bool mMatrixValid=true,mTRSValid=true;
    std::string mName;
};
struct Scene {std::vector<int> mNodes;};
struct Batch {struct Data {int mPrimitiveIndex,mNodeIndex;}; std::vector<Data> mPrimitives;};
struct RenderData {std::array<std::vector<Batch>,32> mBatches;};
struct Asset {
    std::vector<int> mSkins,mAnimations,mSamplers;
    std::vector<Buffer> mBuffers{Buffer{}};
    std::vector<BufferView> mBufferViews{BufferView{}};
    std::vector<Accessor> mAccessors{Accessor{}};
    std::vector<Mesh> mMeshes{Mesh{}};
    std::vector<Node> mNodes{Node{}};
    std::vector<Scene> mScenes{Scene{}};
    std::vector<Material> mMaterials;
    std::vector<Image> mImages;
    std::vector<Texture> mTextures;
    int mScene=0;
    mat4 mLocalMeshTransform{1}; RenderData mRenderData[2];
    Asset(){mMeshes[0].mPrimitives.emplace_back();mScenes[0].mNodes={0};for(auto& rd:mRenderData)for(auto& batches:rd.mBatches)batches.resize(4);}
    void updateNode(int i,mat4 p){auto& n=mNodes[i];n.mAssetMatrix=p*n.mMatrix;for(int c:n.mChildren)updateNode(c,n.mAssetMatrix);}
    void updateTransforms(){for(const auto& s:mScenes)for(int i:s.mNodes)updateNode(i,mat4(1));}
    void uploadMaterials(){}
};
struct LLImportMaterial {
    struct {float mV[4]{1,1,1,1};} mDiffuseColor;
    bool mFullbright=false;std::string mDiffuseMapFilename,mDiffuseMapLabel;
};
struct LLVolumeFace {
    int mNumIndices=3,mNumVertices=3;U16* mIndices=nullptr;
    Point* mPositions=nullptr;Point* mNormals=nullptr;LLVector2* mTexCoords=nullptr;
};
struct LLModel {
    std::vector<int> mSkinWeights;struct {std::vector<std::string> mJointNames;} mSkinInfo;
    std::vector<std::string> mMaterialList;std::vector<LLVolumeFace> faces;
    int getNumVolumeFaces()const{return faces.size();}
    const LLVolumeFace& getVolumeFace(int i)const{return faces[i];}
};
struct Instance {
    LLModel* mModel=nullptr;std::string mLabel;
    struct {float mMatrix[4][4]{{1,0,0,0},{0,1,0,0},{0,0,1,0},{2,3,4,1}};} mTransform;
    std::map<std::string,LLImportMaterial> mMaterial;
};
struct LLModelLoader {using scene=std::map<int,std::vector<Instance>>;};
struct LLGLSLShader {struct GLTFVariant {enum {UNLIT=1,MULTI_UV=2,ALPHA_BLEND=4};};};
struct PreviewMaterial {int id=0;bool mApplied=false;};
struct LocalMeshAsset:Asset {
    std::vector<Material> mImportedMaterials;
    std::vector<PreviewMaterial> mPreviewMaterials;
    int mPreviewTextureStart=0;bool mMaterialsDirty=false;
};
void updateLocalMeshMaterials(Asset&){}
''' + "\n".join([function(asset_source, "static bool validLocalMeshInput("),
                  function(source, "void rebuildMaterialBatches("),
                  function(source, "bool initializeMaterials("),
                  function(source, "S32 addPreviewAccessor("),
                  function(source, "bool convertDAEScene("),
                  function(source, "bool preparePreview(")]) + r'''
int cases=0;
template<class F>void rejects(F mutate){Asset a;mutate(a);assert(!validLocalMeshInput(a));++cases;}
bool near(vec3 a,vec3 b){return glm::length(a-b)<1e-5f;}
int main(){
    Asset good; assert(validLocalMeshInput(good));++cases;
    rejects([](auto&a){a.mSkins.push_back(0);});
    rejects([](auto&a){a.mAnimations.push_back(0);});
    rejects([](auto&a){a.mBuffers[0].mByteLength=-1;});
    rejects([](auto&a){a.mBufferViews[0].mBuffer=5;});
    rejects([](auto&a){a.mBufferViews[0].mByteOffset=1;});
    rejects([](auto&a){a.mAccessors[0].mCount=4;});
    rejects([](auto&a){a.mAccessors[0].mCount=INT32_MAX;});
    rejects([](auto&a){a.mAccessors[0].mBufferView=-1;});
    rejects([](auto&a){a.mAccessors[0].mByteOffset=-4;});
    rejects([](auto&a){a.mBufferViews[0].mByteStride=8;});
    rejects([](auto&a){a.mAccessors[0].mType=Accessor::Type::SCALAR;});
    rejects([](auto&a){a.mMeshes[0].mPrimitives[0].mAttributes["POSITION"]=20;});
    rejects([](auto&a){a.mMeshes[0].mPrimitives[0].mMaterial=0;});
    rejects([](auto&a){a.mMeshes[0].mPrimitives[0].mIndices=20;});
    rejects([](auto&a){a.mMeshes[0].mPrimitives[0].mMode=Primitive::Mode::LINES;});
    rejects([](auto&a){a.mAccessors[0].mCount=2;});
    rejects([](auto&a){a.mImages.emplace_back();a.mImages.back().mBufferView=4;});
    rejects([](auto&a){a.mTextures.push_back({0,-1});});
    rejects([](auto&a){a.mMaterials.emplace_back();a.mMaterials[0].mNormalTexture.mIndex=0;});
    rejects([](auto&a){a.mMeshes[0].mWeights.push_back(.5);});
    rejects([](auto&a){a.mNodes[0].mSkin=0;});
    rejects([](auto&a){a.mMeshes[0].mPrimitives[0].mAttributes["JOINTS_0"]=0;});
    rejects([](auto&a){a.mAccessors.emplace_back();a.mAccessors[1].mCount=1;a.mMeshes[0].mPrimitives[0].mAttributes["NORMAL"]=1;});
    Asset fit;assert(preparePreview(fit,nullptr));++cases;
    assert(near(vec3(fit.mNodes[0].mAssetMatrix*vec4(0,0,0,1)),{0,0,-.5}));++cases;
    assert(near(vec3(fit.mNodes[0].mAssetMatrix*vec4(0,4,0,1)),{0,0,.5}));++cases;
    Asset reload;reload.mMeshes[0].mPrimitives[0].mPositions[2].p[1]=8;
    assert(preparePreview(reload,&fit));
    assert(near(vec3(reload.mNodes[0].mAssetMatrix*vec4(0,0,0,1)),{0,0,-.5}));++cases;
    assert(near(vec3(reload.mNodes[0].mAssetMatrix*vec4(0,8,0,1)),{0,0,1.5}));++cases;
    Asset cycle;cycle.mNodes[0].mChildren={0};assert(!preparePreview(cycle,nullptr));++cases;
    Asset shared;shared.mScenes[0].mNodes={0,0};assert(!preparePreview(shared,nullptr));++cases;
    Asset missing;missing.mScenes[0].mNodes={99};assert(!preparePreview(missing,nullptr));++cases;
    Asset empty;empty.mMeshes[0].mPrimitives[0].mPositions.clear();assert(!preparePreview(empty,nullptr));++cases;
    Asset nan;nan.mMeshes[0].mPrimitives[0].mPositions[0].p[0]=NAN;assert(!preparePreview(nan,nullptr));++cases;
    Asset huge;huge.mNodes.resize(65);assert(!preparePreview(huge,nullptr));++cases;
    Asset materials;materials.mMaterials.resize(86);assert(!preparePreview(materials,nullptr));++cases;
    Asset multi;multi.mMaterials.resize(2);multi.mMaterials[1].mDoubleSided=true;
    multi.mMeshes[0].mPrimitives.resize(2);multi.mMeshes[0].mPrimitives[0].mMaterial=0;
    multi.mMeshes[0].mPrimitives[1].mMaterial=1;multi.mMeshes[0].mPrimitives[1].mShaderVariant=2;
    assert(preparePreview(multi,nullptr));
    assert(multi.mRenderData[0].mBatches[0][1].mPrimitives.size()==1);
    assert(multi.mRenderData[1].mBatches[2][2].mPrimitives.size()==1);++cases;
    Asset unused;unused.mNodes.emplace_back();assert(preparePreview(unused,nullptr));
    assert(unused.mNodes[1].mMesh==-1);++cases;
    auto blank=[](){Asset a;a.mBuffers.clear();a.mBufferViews.clear();a.mAccessors.clear();a.mMeshes.clear();a.mScenes.clear();a.mNodes.clear();return a;};
    Point vertices[3]{{{-1,0,0,0}},{{1,0,0,0}},{{0,0,4,0}}};
    U16 indices[3]{2,0,1};LLVector2 uv[3]{{{0,.25}},{{1,.25}},{{.5,.75}}};
    LLModel model;model.faces.push_back({3,3,indices,vertices,nullptr,uv});model.mMaterialList={"paint"};
    Instance instance;instance.mModel=&model;instance.mLabel="pyramid";
    instance.mMaterial["paint"].mDiffuseColor.mV[0]=.2;
    instance.mMaterial["paint"].mDiffuseColor.mV[3]=.5;
    instance.mMaterial["paint"].mFullbright=true;
    instance.mMaterial["paint"].mDiffuseMapFilename="C:/textures/paint.png";
    LLModelLoader::scene dae_scene{{0,{instance}}};
    Asset dae=blank();assert(convertDAEScene(dae,dae_scene));assert(validLocalMeshInput(dae));++cases;
    assert(dae.mScenes[0].mNodes==std::vector<int>{0});
    assert(dae.mMeshes[0].mPrimitives.size()==1 && dae.mNodes[0].mName=="pyramid");++cases;
    const mat4 upright=glm::rotate(mat4(1),F_PI_BY_TWO,vec3(1,0,0));
    assert(near(vec3(upright*dae.mNodes[0].mMatrix*vec4(0,0,4,1)),{2,3,8}));++cases;
    const auto& dp=dae.mMeshes[0].mPrimitives[0];
    const auto& pos=dae.mAccessors[dp.mAttributes.at("POSITION")];
    assert(pos.mCount==3 && dae.mBufferViews[pos.mBufferView].mByteStride==16);++cases;
    const auto& iv=dae.mBufferViews[dae.mAccessors[dp.mIndices].mBufferView];
    U16 first_index;std::memcpy(&first_index,dae.mBuffers[iv.mBuffer].mData.data(),sizeof(first_index));assert(first_index==2);++cases;
    const auto& tv=dae.mBufferViews[dae.mAccessors[dp.mAttributes.at("TEXCOORD_0")].mBufferView];
    float flipped_v;std::memcpy(&flipped_v,dae.mBuffers[tv.mBuffer].mData.data()+sizeof(float),sizeof(float));assert(flipped_v==.75f);++cases;
    assert(dae.mMaterials[0].mPbrMetallicRoughness.mBaseColorFactor.x==.2f);
    assert(dae.mMaterials[0].mPbrMetallicRoughness.mMetallicFactor==0);
    assert(dae.mMaterials[0].mPbrMetallicRoughness.mRoughnessFactor==.5f);
    assert(dae.mMaterials[0].mUnlit.mPresent && dae.mMaterials[0].mAlphaMode==Material::AlphaMode::BLEND);++cases;
    assert(dae.mImages[dae.mTextures[0].mSource].mUri=="C:/textures/paint.png");++cases;
    dae_scene[0].push_back(instance);dae_scene[0][1].mMaterial["paint"].mDiffuseColor.mV[0]=.8;
    Asset instanced=blank();assert(convertDAEScene(instanced,dae_scene));
    assert(instanced.mNodes.size()==2 && instanced.mMaterials[1].mPbrMetallicRoughness.mBaseColorFactor.x==.8f);++cases;
    dae_scene[0][0].mMaterial.clear();Asset fallback=blank();assert(convertDAEScene(fallback,dae_scene));
    assert(fallback.mMaterials[0].mPbrMetallicRoughness.mBaseColorFactor==vec4(1));++cases;
    model.mSkinWeights.push_back(1);Asset skinned=blank();assert(!convertDAEScene(skinned,dae_scene));++cases;model.mSkinWeights.clear();
    indices[0]=99;Asset bad_index=blank();assert(!convertDAEScene(bad_index,dae_scene));++cases;indices[0]=2;
    Asset no_scene=blank();assert(!convertDAEScene(no_scene,{}));++cases;
    bool overflow=false;try{addPreviewAccessor(no_scene,vertices,INT32_MAX,16,Accessor::Type::VEC3,Accessor::ComponentType::FLOAT);}catch(const std::runtime_error&){overflow=true;}
    assert(overflow);++cases;
    LocalMeshAsset original;
    original.mMaterials.resize(3);
    original.mMaterials[0].mName="Paint";
    original.mMaterials[1].mName="Glass";
    original.mMaterials[2].mName="Paint";
    original.mMeshes[0].mPrimitives[0].mMaterial=0;
    assert(initializeMaterials(original,nullptr));
    original.mPreviewMaterials={{10,true},{20,true},{30,true}};
    LocalMeshAsset reordered;
    reordered.mMaterials={original.mMaterials[1],original.mMaterials[0],original.mMaterials[2]};
    reordered.mMeshes[0].mPrimitives[0].mMaterial=0;
    assert(initializeMaterials(reordered,&original));
    assert(reordered.mPreviewMaterials[0].id==20 && reordered.mPreviewMaterials[1].id==10 && reordered.mPreviewMaterials[2].id==30);++cases;
    assert(!reordered.mPreviewMaterials[0].mApplied && reordered.mMaterialsDirty);++cases;
    assert(reordered.mImages.size()==12 && reordered.mTextures.size()==12);++cases;
    LocalMeshAsset replacement;replacement.mMaterials.resize(1);replacement.mMaterials[0].mName="New surface";
    replacement.mMeshes[0].mPrimitives[0].mMaterial=0;
    assert(initializeMaterials(replacement,&original));assert(replacement.mPreviewMaterials[0].id==0);++cases;
    LocalMeshAsset no_material;
    assert(initializeMaterials(no_material,nullptr));assert(no_material.mMeshes[0].mPrimitives[0].mMaterial==0);++cases;
    LocalMeshAsset full_materials;full_materials.mMaterials.resize(85);
    assert(!initializeMaterials(full_materials,nullptr));++cases;
    reordered.mMaterials[0].mDoubleSided=true;
    reordered.mMaterials[0].mAlphaMode=Material::AlphaMode::BLEND;
    reordered.mMaterials[0].multiUV=true;
    rebuildMaterialBatches(reordered);
    assert(reordered.mRenderData[1].mBatches[6][1].mPrimitives.size()==1);++cases;
    reordered.mMaterials[0].mDoubleSided=false;
    reordered.mMaterials[0].mAlphaMode=Material::AlphaMode::OPAQUE;
    reordered.mMaterials[0].multiUV=false;
    rebuildMaterialBatches(reordered);
    assert(reordered.mRenderData[1].mBatches[6][1].mPrimitives.empty());
    assert(reordered.mRenderData[0].mBatches[0][1].mPrimitives.size()==1);++cases;
    std::cout<<cases<<" native local mesh validation/placement/batching cases passed\n";
}
'''
compiler = shutil.which("g++")
assert compiler, "g++ required"
with tempfile.TemporaryDirectory() as directory:
    cpp, exe = Path(directory) / "local_mesh.cpp", Path(directory) / "local_mesh.exe"
    cpp.write_text(harness)
    subprocess.run([compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror",
                    "-I" + str(ROOT / "build-vc170-64/packages/include"), str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

xml = ET.parse(ROOT / "indra/newview/skins/default/xui/en/floater_local_mesh.xml").getroot()
names = {node.get("name") for node in xml.iter()}
assert {"load", "reload", "remove", "status", "filename", "target"} <= names
settings = ET.parse(ROOT / "indra/newview/app_settings/settings.xml")
assert "LocalMeshRendering" in {node.text for node in settings.iter("key")}
print("Local Mesh XUI and settings XML parsed successfully.")
