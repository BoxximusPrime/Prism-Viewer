"""Exercise the production neutral sampler with small joint/geometry doubles."""
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "indra/newview/llfloaterhoverheight.cpp").read_text()
start = source.index("    class ShoeHeightSkeleton")
end = source.index("\n}\n\nbool LLFloaterShoeHeight::postBuild", start)
sampler = source[start:end]
height_calculation = next(line.strip() for line in source.splitlines() if line.strip().startswith("const F32 height ="))
world_source = (ROOT / "indra/newview/llworld.cpp").read_text()
world_start = world_source.index("F32 LLWorld::resolveStepHeightGlobal(")
world_end = world_source.index("\nLLSurfacePatch * LLWorld::resolveLandPatchGlobal", world_start)
ground_resolver = world_source[world_start:world_end]

harness = r'''
#include <cassert>
#include <cmath>
#include <map>
#include <memory>
#include <vector>
#include <string>
#include <limits>
#include <algorithm>
#include <sstream>
#define LL_INFOS(category) std::ostringstream()
#define LL_ENDL std::endl
std::string llformat(const char*,float value){return std::to_string(value);}
using F32=float; using S32=int; using U32=unsigned;
constexpr int VX=0,VY=1,VZ=2,LL_MAX_JOINTS_PER_MESH_OBJECT=8;
using LLUUID=int;
struct LLVector3 {
    float mV[3];
    LLVector3(float x=0,float y=0,float z=0):mV{x,y,z}{}
    explicit LLVector3(const float* p):mV{p[0],p[1],p[2]}{}
    float operator[](int n) const{return mV[n];}
    LLVector3& operator+=(LLVector3 b){for(int n=0;n<3;++n)mV[n]+=b.mV[n];return *this;}
    void set(const float* p){for(int n=0;n<3;++n)mV[n]=p[n];}
    void setVec(float x,float y,float z){mV[0]=x;mV[1]=y;mV[2]=z;}
    bool isFinite() const{return std::isfinite(mV[0])&&std::isfinite(mV[1])&&std::isfinite(mV[2]);}
    static const LLVector3 zero;
};
const LLVector3 LLVector3::zero{};
LLVector3 operator+(LLVector3 a,LLVector3 b){return a+=b;}
LLVector3 operator-(LLVector3 a,LLVector3 b){for(int n=0;n<3;++n)a.mV[n]-=b.mV[n];return a;}
float operator*(LLVector3 a,LLVector3 b){return a.mV[0]*b.mV[0]+a.mV[1]*b.mV[1]+a.mV[2]*b.mV[2];}
LLVector3 operator*(LLVector3 a,float b){for(float& v:a.mV)v*=b;return a;}
struct LLQuaternion {enum{XYZ};float angle=0;};
LLQuaternion mayaQ(float x,float y,float z,int){return {x+y+z};}
struct LLVector4a {
    float v[4]={0,0,0,0};
    LLVector4a(float z=0){v[2]=z;}
    const float* getF32ptr() const{return v;}
    float* getF32ptr(){return v;}
    void load3(const float* p){for(int n=0;n<3;++n)v[n]=p[n];}
};
struct LLMatrix4a {
    LLVector3 translation;
    void affineTransform(const LLVector4a& in,LLVector4a& out) const{
        for(int n=0;n<3;++n)out.v[n]=in.v[n]+translation.mV[n];
    }
};
using LLMatrix4=LLMatrix4a;
void matMul(const LLMatrix4a& a,const LLMatrix4a& b,LLMatrix4a& result){result.translation=a.translation+b.translation;}
LLVector3 operator*(LLVector3 a,const LLMatrix4& b){return a+b.translation;}
template<class T>T llmin(T a,T b){return std::min(a,b);}
struct LLJoint {
    std::string name; LLJoint* parent=nullptr;
    LLVector3 position,rest,scale{1,1,1},override_position;
    LLQuaternion rotation; bool overridden=false; LLMatrix4a matrix;
    void setup(const std::string& n,LLJoint* p){name=n;parent=p;}
    LLJoint* getParent(){return parent;}
    const std::string& getName(){return name;}
    LLVector3 getDefaultPosition(){return rest;}
    LLVector3 getPosition(){return position;}
    LLVector3 getScale(){return scale;}
    LLQuaternion getRotation(){return rotation;}
    void setPosition(LLVector3 p){position=p;}
    void setScale(LLVector3 s){scale=s;}
    void setRotation(LLQuaternion r){rotation=r;}
    bool hasAttachmentPosOverride(LLVector3& p,LLUUID&){p=override_position;return overridden;}
    const LLMatrix4a& getWorldMatrix4a(){
        matrix.translation=position+(parent?parent->getWorldMatrix4a().translation:LLVector3{});return matrix;
    }
};
struct LLJointData {std::string mName;LLVector3 mRotation;std::vector<LLJointData> mChildren;};
struct LLVisualParam {virtual ~LLVisualParam()=default;};
struct LLPolySkeletalDistortion:LLVisualParam {
    std::map<LLJoint*,LLVector3> offsets;
    LLVector3 getJointPositionOffset(LLJoint* j)const{auto i=offsets.find(j);return i==offsets.end()?LLVector3{}:i->second;}
};
struct LLVOAvatarSelf {
    LLJoint* mPelvisp=nullptr;
    LLVector3 hover;
    LLVector3 getHoverOffset(){return hover;}
    LLVector3 center,mBodySize{.5f,.5f,2.f};
    LLVector3 getRenderPosition(){return center;}
    struct Plane {float mV[4]={0,0,0,0};bool isExactlyClear()const{return mV[0]==0&&mV[1]==0&&mV[2]==0&&mV[3]==0;}} mFootPlane;
    struct LLViewerRegion* getRegion()const;
    std::vector<LLJointData> bones;std::map<std::string,LLJoint*> joints;
    LLVisualParam* shape=nullptr;
    void getJointMatricesAndHierarhy(std::vector<LLJointData>& b){b=bones;}
    LLVisualParam* getFirstVisualParam(){return shape;}
    LLVisualParam* getNextVisualParam(){return nullptr;}
    LLJoint* getJoint(const std::string& n){auto i=joints.find(n);return i==joints.end()?nullptr:i->second;}
};
struct LLMeshSkinInfo {std::vector<std::string> mJointNames;std::vector<LLMatrix4a> mInvBindMatrix;LLMatrix4a mBindShapeMatrix;};
namespace LLSkinningUtil {
    U32 getMeshJointCount(const LLMeshSkinInfo* s){return s->mJointNames.size();}
    void getPerVertexSkinMatrix(float* w,const LLMatrix4a* p,bool,LLMatrix4a& result,U32 count){
        result.translation={};float total=0;
        for(int k=0;k<4;++k)total+=w[k]-std::floor(w[k]);
        assert(total>0);
        for(int k=0;k<4;++k){int joint=int(w[k]);assert(joint<int(count));result.translation+=p[joint].translation*((w[k]-joint)/total);}
    }
}
struct LLVolumeFace {LLVector4a* mPositions=nullptr;LLVector4a* mWeights=nullptr;int mNumVertices=0;};
struct LLVolume {
    std::vector<LLVolumeFace> faces;bool loaded=true;
    bool isMeshAssetLoaded(){return loaded;}
    int getNumVolumeFaces(){return faces.size();}
    const LLVolumeFace& getVolumeFace(int i){return faces[i];}
};
struct LLViewerObject {
    virtual ~LLViewerObject()=default;bool dead=false;std::vector<LLViewerObject*> children;
    bool avatar=false,attachment=false;
    bool isAvatar(){return avatar;}bool isAttachment(){return attachment;}
    bool isDead(){return dead;}const auto& getChildren(){return children;}
};
struct LLVOVolume:LLViewerObject {
    LLVolume volume;bool mesh=true,rigged=true;LLMeshSkinInfo* skin=nullptr;LLVector3 render_position;
    LLVolume* getVolume(){return &volume;}bool isMesh(){return mesh;}bool isRiggedMesh(){return rigged;}
    const LLMeshSkinInfo* getSkinInfo(){return skin;}
    LLVector3 volumePositionToAgent(LLVector3 p){return p+render_position;}
};
void near(float a,float b){assert(std::abs(a-b)<.00001f);}
struct LLVector3d {
    double mdV[3];LLVector3d(double x=0,double y=0,double z=0):mdV{x,y,z}{}
    double length()const{return std::sqrt(mdV[0]*mdV[0]+mdV[1]*mdV[1]+mdV[2]*mdV[2]);}
};
LLVector3d operator+(LLVector3d a,LLVector3d b){for(int n=0;n<3;++n)a.mdV[n]+=b.mdV[n];return a;}
LLVector3d operator-(LLVector3d a,LLVector3d b){for(int n=0;n<3;++n)a.mdV[n]-=b.mdV[n];return a;}
LLVector3d operator*(float s,LLVector3d a){for(double& v:a.mdV)v*=s;return a;}
template<class T>T llmax(T a,T b){return std::max(a,b);}
template<class T>T llclamp(T x,T a,T b){return std::clamp(x,a,b);}
struct LLViewerRegion {
    struct Land {float altitude=0;float resolveHeightGlobal(LLVector3d){return altitude;}} land;
    Land& getLand(){return land;}
    LLVector3 getPosRegionFromGlobal(LLVector3d p){return {float(p.mdV[0]),float(p.mdV[1]),float(p.mdV[2])};}
} region;
LLViewerRegion* LLVOAvatarSelf::getRegion()const{return &region;}
using LLVOAvatar=LLVOAvatarSelf;
struct LLWorld {
    static LLWorld* getInstance(){static LLWorld world;return &world;}
    LLViewerRegion* getRegionFromPosGlobal(LLVector3d){return &region;}
    LLVector3 resolveLandNormalGlobal(LLVector3d){return {0,0,1};}
    float resolveStepHeightGlobal(const LLVOAvatar*,const LLVector3d&,const LLVector3d&,LLVector3d&,LLVector3&,LLViewerObject**);
};
struct Agent {
    LLVector3d getPosGlobalFromAgent(LLVector3 p){return {p.mV[0],p.mV[1],p.mV[2]};}
    LLVector3 getPosAgentFromGlobal(LLVector3d p){return {float(p.mdV[0]),float(p.mdV[1]),float(p.mdV[2])};}
} gAgent;
struct Pipeline {
    std::vector<std::pair<LLViewerObject*,float>> surfaces;
    template<class Filter> LLViewerObject* lineSegmentIntersectInWorld(
        const LLVector4a& start,const LLVector4a& end,bool transparent,bool rigged,bool unselectable,bool probes,
        void*,void*,void*,LLVector4a* hit,void*,void*,void*,void*,const Filter& filter){
        assert(!transparent&&!rigged&&unselectable&&!probes);
        LLViewerObject* found=nullptr;float closest=end.v[VZ];
        for(auto [object,z]:surfaces)if(filter(object)&&z<=start.v[VZ]&&z>=closest){
            closest=z;found=object;*hit=LLVector4a(z);
        }
        return found;
    }
} gPipeline;
constexpr int VW=3;
''' + ground_resolver + sampler + '\nfloat computedHeight(LLVOAvatarSelf* gAgentAvatarp, LLVector3 ground, float lowest){' + height_calculation + 'return height;}\n' + r'''
int main(){
    LLJoint root,pelvis,foot,point;
    root.setup("root",nullptr);root.position={0,0,11};
    pelvis.setup("pelvis",&root);pelvis.rest={0,0,PELVIS_BIND_Z};
    foot.setup("foot",&pelvis);foot.rest={0,0,-1};foot.scale={1,1,1.3f};
    point.setup("point",&foot);point.position={0,0,.03f};point.rotation.angle=.4f;
    LLPolySkeletalDistortion shape;shape.offsets[&foot]={0,0,-.1f};
    LLVOAvatarSelf avatar;avatar.mPelvisp=&pelvis;avatar.bones={{"pelvis",{},{{"foot",{}, {}}}}};
    avatar.joints={{"pelvis",&pelvis},{"foot",&foot}};avatar.shape=&shape;
    LLMeshSkinInfo skin;skin.mJointNames={"foot"};skin.mInvBindMatrix.resize(1);
    skin.mInvBindMatrix[0].translation={0,0,.2f};skin.mBindShapeMatrix.translation={0,0,.05f};
    LLVector4a positions[]={LLVector4a(-.15f),LLVector4a(-.1f)};
    LLVector4a weights[2];weights[0].v[0]=weights[1].v[0]=.75f;
    LLVOVolume shoe;shoe.skin=&skin;shoe.volume.faces={{positions,weights,2}};
    for(int pose=0;pose<30;++pose){
        pelvis.position={0,0,float(pose)};foot.position={0,0,-float(pose)};
        pelvis.rotation.angle=pose*.1f;foot.rotation.angle=pose*.2f;
        ShoeHeightSkeleton sample(avatar);
        LLJoint* neutral=sample.joint(&foot);
        near(neutral->getWorldMatrix4a().translation[VZ],9.9f);
        near(neutral->rotation.angle,0);near(neutral->scale[VZ],1.3f);
        near(sample.joint(&point)->getWorldMatrix4a().translation[VZ],9.93f);
        near(sample.joint(&point)->rotation.angle,.4f);
        assert(sample.joint(&foot)==neutral);
        float lowest=std::numeric_limits<float>::infinity();
        assert(lowestAttachmentVertex(&shoe,sample,{},lowest));near(lowest,10.f);
        // A lower child in a rigid attachment must contribute after remapping.
        LLVOVolume child;child.rigged=false;child.render_position={0,0,8};
        child.volume.faces={{positions,nullptr,2}};shoe.children={&child};
        LLMatrix4 remap;remap.translation={0,0,.5f};lowest=INFINITY;
        assert(lowestAttachmentVertex(&shoe,sample,remap,lowest));near(lowest,8.35f);
        child.volume.loaded=false;assert(!lowestAttachmentVertex(&shoe,sample,remap,lowest));
        shoe.children.clear();shoe.volume.loaded=false;
        assert(!lowestAttachmentVertex(&shoe,sample,{},lowest));shoe.volume.loaded=true;
        shoe.volume.faces[0].mWeights=nullptr;assert(!lowestAttachmentVertex(&shoe,sample,{},lowest));
        shoe.volume.faces[0].mWeights=weights;
        // The sampler has not changed live animation translations or rotations.
        near(pelvis.position[VZ],float(pose));near(foot.position[VZ],-float(pose));
        near(pelvis.rotation.angle,pose*.1f);near(foot.rotation.angle,pose*.2f);
    }
    // The correction must be independent of both ground altitude and the
    // existing (including badly sunken) hover value, and remain repeatable.
    positions[0]=LLVector4a(-.35f);
    for(float altitude : {-1.f,100.f,3000.f})for(float hover : {-1.1f,0.f,.3f,.2f}){
        root.position={0,0,altitude+1.f+hover};avatar.hover={0,0,hover};
        ShoeHeightSkeleton neutral(avatar);float lowest=INFINITY;
        assert(lowestAttachmentVertex(&shoe,neutral,{},lowest));
        assert(std::abs(computedHeight(&avatar,{0,0,altitude},lowest)-.2f)<.001f);
    }
    root.position={0,0,11};
    // Exercise the actual production floor-plane resolver, including its clamp.
    // The old +/-0.5 m probe fabricates a floor half a meter above this platform.
    region.land.altitude=0;avatar.center={0,0,1365.91f};avatar.mBodySize={.5f,.5f,2.f};
    avatar.mFootPlane={{0,0,1,1364.91f}};
    LLVector3d old_floor;LLVector3 normal;
    auto center=gAgent.getPosGlobalFromAgent(avatar.center);
    LLWorld::getInstance()->resolveStepHeightGlobal(&avatar,center+LLVector3d(0,0,.5),center-LLVector3d(0,0,.5),old_floor,normal,nullptr);
    assert(old_floor.mdV[VZ]>1365.4); // Reproduces the reported hovering bug.
    LLVector3 floor;
    LLViewerObject platform,body_object,shoe_object,overhead;
    body_object.avatar=true;shoe_object.attachment=true;
    gPipeline.surfaces={{&platform,1364.901f},{&body_object,1365.0f},{&shoe_object,1364.96f},{&overhead,1365.3f}};
    assert(findShoeGround(avatar,floor));assert(std::abs(floor.mV[VZ]-1364.901f)<.001f);
    // A floor 9 mm below the raw physics plane is 41 mm ABOVE the old
    // step-solver result. Align to that visible surface, not either plane.
    avatar.hover={0,0,.132f};
    assert(std::abs(computedHeight(&avatar,floor,1364.918f)-.115f)<.001f);
    gPipeline.surfaces.clear();assert(!findShoeGround(avatar,floor));
    for(float body : {1.f,2.f,3.f})for(float altitude : {0.f,1365.f}){
        region.land.altitude=altitude-10;avatar.mBodySize={.5f,.5f,body};
        avatar.center={0,0,altitude+body*.5f};avatar.mFootPlane={{0,0,1,altitude}};
        for(float mesh_offset:{-.009f,0.f,.018f}){
            gPipeline.surfaces={{&platform,altitude+mesh_offset},{&body_object,altitude+.04f},{&shoe_object,altitude+.02f}};
            assert(findShoeGround(avatar,floor));assert(std::abs(floor.mV[VZ]-(altitude+mesh_offset))<.001f);
        }
        // Clear foot plane: terrain is the floor and needs no Havok adjustment.
        avatar.mFootPlane={};region.land.altitude=altitude;
        gPipeline.surfaces={{&platform,altitude}};
        assert(findShoeGround(avatar,floor));assert(std::abs(floor.mV[VZ]-altitude)<.001f);
    }
    foot.overridden=true;foot.override_position={0,0,-.8f};
    ShoeHeightSkeleton sample(avatar);near(sample.joint(&foot)->getWorldMatrix4a().translation[VZ],10.2f);
    LLMatrix4a palette[8];skin.mJointNames={"unknown"};assert(!sample.palette(&skin,palette,1));
    skin.mJointNames={"foot"};skin.mInvBindMatrix.clear();assert(!sample.palette(&skin,palette,1));
}
'''
# The skeleton's bind pelvis is NOT its runtime local pelvis origin. Keep the
# real asset value here so a fixture cannot hide the meter-sized discrepancy.
skeleton_asset = ET.parse(ROOT / "indra/newview/character/avatar_skeleton.xml")
pelvis_bind_z = float(skeleton_asset.find("bone[@name='mPelvis']").get("pos").split()[2])
assert pelvis_bind_z > 1.0
harness = harness.replace("PELVIS_BIND_Z", repr(pelvis_bind_z) + "f")
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / "shoe_height.cpp"
    exe = Path(directory) / "shoe_height.exe"
    cpp.write_text(harness)
    subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

for name in ("floater_shoe_height.xml", "floater_edit_hover_height.xml", "floater_quick_preferences.xml"):
    ET.parse(ROOT / "indra/newview/skins/default/xui/en" / name)
print("PASS: neutral sampler, pelvis origin, repeatable meter correction, production floor clamp, rendered floor versus 5 cm step bias, collision/mesh differences, avatar/attachment filtering, missing floor, platform/terrain heights, and XUI XML.")
