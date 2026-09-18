"""Compile production world/octree/glTF/attachment picking against a tiny scene.
Run: python scripts/tests/test_pick_filter.py (requires g++).
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2] / "indra/newview"


def function(text, signature):
    start = text.index(signature)
    opening = text.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


spatial = (root / "llspatialpartition.cpp").read_text()
octree = spatial[spatial.index("class alignas(16) LLOctreeIntersect") :]
# Keep the production constructor, fields and candidate intersection. Only tree
# traversal and mesh triangles are stand-ins; all filtering and closest-hit logic runs.
octree_fields = octree[octree.index("public:") : octree.index("    virtual void visit")]
harness = r"""
#include <cassert>
#include <cmath>
#include <functional>
#include <map>
#include <vector>
#include <algorithm>
using S32=int; using U32=unsigned; using F32=float;
struct LLVector2 {};
struct LLVector4a {
    float x=0;
    void setSub(LLVector4a a,LLVector4a b){x=a.x-b.x;}
    LLVector4a getLength3(){return {std::abs(x)};}
    float getF32(){return x;} void clear(){x=0;}
};
template<class T> struct LLPointer {
    T* p=nullptr; LLPointer()=default; LLPointer(T* v):p(v){}
    T* get() const{return p;} T* operator->() const{return p;}
    operator T*() const{return p;} bool notNull() const{return p;}
};
struct LLViewerObject; struct LLSpatialPartition; struct LLSpatialBridge;
using Filter=std::function<bool(LLViewerObject*)>;
struct LLDrawable {
    LLViewerObject* object=nullptr; LLSpatialPartition* partition=nullptr;
    bool visible=true;
    int getRenderType(){return 0;} bool isVisible(){return visible;}
    bool isSpatialBridge(){return partition;}
    LLSpatialPartition* asPartition(){return partition;}
    LLPointer<LLViewerObject> getVObj(){return object;}
};
struct LLViewerOctreeEntry {
    LLDrawable* drawable; LLDrawable* getDrawable(){return drawable;}
};
struct LLViewerObject {
    virtual ~LLViewerObject()=default;
    LLDrawable drawable{this}; LLPointer<LLDrawable> mDrawable{&drawable};
    LLPointer<int> mGLTFAsset; float depth=0,hit_normal=1;
    bool dead=false,avatar=false,attachment=false,selected=false,probe=false;
    int calls=0;
    bool isDead(){return dead;} bool isAvatar(){return avatar;}
    bool isAttachment(){return attachment;} bool isReflectionProbe(){return probe;}
    int getClickAction(){return 0;} bool getVolume(){return true;}
    virtual bool lineSegmentIntersect(const LLVector4a& start,const LLVector4a& end,
        S32,bool,bool,bool,S32* face,LLVector4a* p,LLVector2*,LLVector4a* n,LLVector4a*){
        ++calls;
        if(depth<start.x||depth>end.x)return false;
        *p={depth}; if(n)*n={hit_normal}; if(face)*face=int(depth); return true;
    }
};
using LLVOVolume=LLViewerObject;
struct NameTag {
    float depth=0;
    bool lineSegmentIntersect(const LLVector4a& start,const LLVector4a& end,LLVector4a& p){
        if(depth<start.x||depth>end.x)return false;p={depth};return true;
    }
};
struct LLCharacter {static inline std::vector<LLCharacter*> sInstances;};
struct LLViewerJointAttachment {
    using attachedobjs_vec_t=std::vector<LLPointer<LLViewerObject>>;
    attachedobjs_vec_t mAttachedObjects;
};
struct LLVOAvatar:LLCharacter,LLViewerObject {
    using attachment_map_t=std::map<int,LLViewerJointAttachment*>;
    attachment_map_t mAttachmentPoints; LLPointer<NameTag> mNameText;
    LLVOAvatar(){avatar=true;}
    bool isSelf(){return true;} bool lineSegmentBoundingBox(LLVector4a,LLVector4a){return true;}
    LLViewerObject* lineSegmentIntersectRiggedAttachments(const LLVector4a&,const LLVector4a&,
        S32,bool,bool,bool,S32*,LLVector4a*,LLVector2*,LLVector4a*,LLVector4a*,const Filter&);
};
struct LLControlAvatar:LLVOAvatar {
    LLVOVolume* mRootVolp=nullptr; std::vector<LLVOVolume*> volumes;
    void getAnimatedVolumes(std::vector<LLVOVolume*>& out){out=volumes;}
    LLViewerObject* lineSegmentIntersectRiggedAttachments(const LLVector4a&,const LLVector4a&,
        S32,bool,bool,bool,S32*,LLVector4a*,LLVector2*,LLVector4a*,LLVector4a*,const Filter&);
};
struct Agent {bool needsRenderAvatar(){return true;}} gAgent;
struct LLFloater {static bool isVisible(int){return true;}};
int gFloaterTools=0; constexpr int CLICK_ACTION_IGNORE=1;
struct LLSpatialPartition {
    std::vector<LLViewerOctreeEntry*> entries;
    std::vector<LLViewerOctreeEntry*>* mOctree=&entries; int mDrawableType=0;
    LLSpatialBridge* asBridge();
    LLDrawable* lineSegmentIntersect(const LLVector4a&,const LLVector4a&,bool,bool,bool,bool,
        S32*,LLVector4a*,LLVector2*,LLVector4a*,LLVector4a*,const Filter& ={});
};
struct LLSpatialBridge:LLSpatialPartition {};
LLSpatialBridge* LLSpatialPartition::asBridge(){return static_cast<LLSpatialBridge*>(this);}
struct LLViewerRegion {
    enum {PARTITION_VOLUME,PARTITION_BRIDGE,PARTITION_AVATAR,PARTITION_CONTROL_AV,
          PARTITION_TERRAIN,PARTITION_TREE,PARTITION_GRASS,NUM_PARTITIONS};
    LLSpatialPartition* parts[NUM_PARTITIONS]{};
    LLSpatialPartition* getSpatialPartition(int i){return parts[i];}
};
struct LLWorld {
    using region_list_t=std::vector<LLViewerRegion*>; region_list_t regions;
    static LLWorld* getInstance(){static LLWorld w;return &w;}
    region_list_t& getRegionList(){return regions;}
};
struct LLPipeline {
    bool sPickAvatar=false; bool hasRenderType(int){return true;}
    LLViewerObject* lineSegmentIntersectInWorld(const LLVector4a&,const LLVector4a&,bool,bool,bool,bool,
        S32*,S32*,S32*,LLVector4a*,LLVector2*,LLVector4a*,LLVector4a*,bool*,const Filter& ={});
} gPipeline;
namespace LL {
struct GLTFSceneManager {
    std::vector<LLPointer<LLViewerObject>> mObjects;
    static GLTFSceneManager& instance(){static GLTFSceneManager g;return g;}
    LLDrawable* lineSegmentIntersect(const LLVector4a&,const LLVector4a&,bool,bool,bool,bool,
        S32*,S32*,LLVector4a*,LLVector2*,LLVector4a*,LLVector4a*,const Filter& ={});
    bool lineSegmentIntersect(LLVOVolume* o,int*,const LLVector4a& a,const LLVector4a& b,S32 f,
        bool pt,bool pr,bool pu,S32* node,S32* primitive,LLVector4a* p,LLVector2* tc,LLVector4a* n,LLVector4a* t){
        return o->lineSegmentIntersect(a,b,f,pt,pr,pu,node,p,tc,n,t);
    }
};
}
using LL::GLTFSceneManager;
struct LLOctreeIntersect {
""" + octree_fields + function(octree, "virtual bool check(LLViewerOctreeEntry* entry)") + r"""
    LLDrawable* check(std::vector<LLViewerOctreeEntry*>* entries){
        for(auto e:*entries)check(e);return mHit;
    }
};
"""
for filename, signature in (
    ("llspatialpartition.cpp", "LLDrawable* LLSpatialPartition::lineSegmentIntersect"),
    ("llvoavatar.cpp", "LLViewerObject* LLVOAvatar::lineSegmentIntersectRiggedAttachments"),
    ("llcontrolavatar.cpp", "LLViewerObject* LLControlAvatar::lineSegmentIntersectRiggedAttachments"),
    ("gltfscenemanager.cpp", "LLDrawable* GLTFSceneManager::lineSegmentIntersect"),
    ("pipeline.cpp", "LLViewerObject* LLPipeline::lineSegmentIntersectInWorld"),
):
    harness += function((root / filename).read_text(), signature) + "\n"
harness += r"""
int main(){
    LLViewerObject base,table,floor; base.selected=true; base.depth=table.depth=8; floor.depth=12;
    table.hit_normal=3; floor.hit_normal=5;
    LLViewerOctreeEntry eb{&base.drawable},et{&table.drawable},ef{&floor.drawable};
    LLSpatialPartition part; part.entries={&eb,&et,&ef};
    LLViewerRegion region; region.parts[LLViewerRegion::PARTITION_VOLUME]=&part;
    LLWorld::getInstance()->regions={&region};
    LLVector4a point,normal; bool name=false;
    const Filter surface=[](LLViewerObject* o){return !o->selected&&!o->avatar&&!o->attachment;};
    auto pick=[&](const Filter& filter){return gPipeline.lineSegmentIntersectInWorld(
        {.1f},{512},false,false,true,false,nullptr,nullptr,nullptr,&point,nullptr,&normal,nullptr,&name,filter);};
    // Excluded geometry never shortens the ray, regardless of octree ordering.
    for(int order=0;order<2;++order){
        if(order)std::reverse(part.entries.begin(),part.entries.end());
        for(float gap:{0.f,.0001f,-.0001f}){
            base.depth=8-gap; base.calls=0;
            assert(pick(surface)==&table && point.x==8 && normal.x==3 && base.calls==0);
        }
    }
    base.depth=7; assert(pick({})==&base && point.x==7); // ordinary selection still sees it
    part.entries.assign(300,&eb); part.entries.push_back(&et);
    assert(pick(surface)==&table); // no selected-face traversal limit
    // Same predicate reaches nested spatial bridges and other regions/partitions.
    LLSpatialBridge bridge; bridge.entries={&eb,&et};
    LLDrawable bridge_drawable; bridge_drawable.partition=&bridge;
    LLViewerOctreeEntry ebridge{&bridge_drawable}; part.entries={&ebridge,&ef};
    assert(pick(surface)==&table);
    part.entries={&eb,&ef}; LLSpatialPartition terrain; terrain.entries={&et};
    LLViewerRegion region2; region2.parts[LLViewerRegion::PARTITION_TERRAIN]=&terrain;
    LLWorld::getInstance()->regions.push_back(&region2);
    assert(pick(surface)==&table);
    LLWorld::getInstance()->regions.pop_back(); part.entries={&eb,&et,&ef};
    // Avatar geometry and names cannot replace a valid support point.
    LLVOAvatar avatar; avatar.depth=4; NameTag tag{2}; avatar.mNameText=&tag;
    LLViewerOctreeEntry ea{&avatar.drawable}; LLSpatialPartition avatars; avatars.entries={&ea};
    region.parts[LLViewerRegion::PARTITION_AVATAR]=&avatars;
    LLCharacter::sInstances={&avatar};
    assert(pick(surface)==&table && !name);
    assert(pick({})==&avatar && name && point.x==2);
    LLCharacter::sInstances.clear(); region.parts[LLViewerRegion::PARTITION_AVATAR]=nullptr;
    // glTF uses the same filter before its own nearest-hit pass.
    int asset=1; LLViewerObject gltf_base,gltf_target;
    gltf_base.mGLTFAsset=&asset; gltf_base.selected=true; gltf_base.depth=6;
    gltf_target.mGLTFAsset=&asset; gltf_target.depth=6;
    GLTFSceneManager::instance().mObjects={&gltf_base,&gltf_target};
    assert(pick(surface)==&gltf_target && point.x==6 && gltf_base.calls==0);
    GLTFSceneManager::instance().mObjects.clear();
    // Filtering selected rigged children happens before shortening inside an avatar.
    LLViewerJointAttachment attachments; attachments.mAttachedObjects={&base,&table};
    avatar.mAttachmentPoints[0]=&attachments;
    const Filter unselected=[](LLViewerObject* o){return !o->selected;};
    assert(avatar.lineSegmentIntersectRiggedAttachments({.1f},{512},-1,false,true,true,
        nullptr,&point,nullptr,&normal,nullptr,unselected)==&table && point.x==8);
    LLControlAvatar control; control.mRootVolp=&base; control.volumes={&base,&table};
    assert(control.lineSegmentIntersectRiggedAttachments({.1f},{512},-1,false,true,true,
        nullptr,&point,nullptr,&normal,nullptr,unselected)==&table && point.x==8);
    part.entries={&eb}; assert(pick(surface)==nullptr); // selected-only ray is a miss
}
"""
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / "pick_filter.cpp"
    exe = Path(directory) / "pick_filter.exe"
    cpp.write_text(harness)
    subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=30)
print("Production picking: coplanar contacts, submillimetre gaps, hit ordering, dense selections, bridges, terrain, avatars, name tags, glTF and rigged children passed.")
