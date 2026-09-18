"""Run production surface-snap geometry, picking and drag code with a small fake scene.
Run: python scripts/tests/test_surface_snap.py (requires g++).
"""
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[2]
source = (root / "indra/newview/llmaniptranslate.cpp").read_text()
composite = (root / "indra/newview/lltoolcomp.cpp").read_text()


def function(text, signature):
    start = text.index(signature)
    opening = text.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


start = source.index("    if (hasMouseCapture() && mCenterDrag)")
end = source.index("    // Translation tool only works", start)
harness = r"""
#include <cassert>
#include <cmath>
#include <cfloat>
#include <vector>
#include <algorithm>
#include <string>
#include <limits>
#include <functional>
#include <set>
using S32=int; using F32=float; using MASK=int;
constexpr int VX=0, VY=1, VZ=2, SELECT_TYPE_WORLD=0, SELECT_TYPE_HUD=1;
constexpr int MASK_CONTROL=1, MASK_SHIFT=2, MOUSE_DRAG_SLOP=2, CENTER_HANDLE_RADIUS=7;
constexpr int UI_CURSOR_TOOLTRANSLATE=0, UI_CURSOR_NOLOCKED=1;
constexpr float F32_MAX=FLT_MAX;
template<class T> T llmin(T a,T b){return std::min(a,b);}
template<class T> T llmax(T a,T b){return std::max(a,b);}
double llabs(double a){return std::abs(a);}
struct Vec {
    double mV[3]{};
    static const Vec z_axis;
    Vec()=default; Vec(double x,double y,double z):mV{x,y,z}{}
    explicit Vec(const double* p):Vec(p[0],p[1],p[2]){}
    Vec operator+(Vec b) const {return {mV[0]+b.mV[0],mV[1]+b.mV[1],mV[2]+b.mV[2]};}
    Vec operator-(Vec b) const {return {mV[0]-b.mV[0],mV[1]-b.mV[1],mV[2]-b.mV[2]};}
    Vec operator*(double b) const {return {mV[0]*b,mV[1]*b,mV[2]*b};}
    double operator*(Vec b) const {return mV[0]*b.mV[0]+mV[1]*b.mV[1]+mV[2]*b.mV[2];}
    double lengthSquared() const {return *this * *this;}
    bool isFinite() const {return std::isfinite(mV[0])&&std::isfinite(mV[1])&&std::isfinite(mV[2]);}
};
const Vec Vec::z_axis{0,0,1};
using LLVector3=Vec; using LLVector3d=Vec;
float dist_vec(Vec a,Vec b){return std::sqrt((a-b).lengthSquared());}
bool near(Vec a,Vec b){return (a-b).lengthSquared()<1e-10;}
struct LLVector4a {
    Vec v; void clear(){v={};} void load3(const double* p){v=Vec(p);} const double* getF32ptr() const{return v.mV;}
};
template<class T> struct LLPointer {
    T* p=nullptr; LLPointer()=default; LLPointer(T* t):p(t){}
    T* get() const{return p;} bool isNull() const{return !p;} bool notNull() const{return p;}
    operator bool() const{return p;}
};
struct LLVolumeFace {int mNumVertices=0; std::vector<LLVector4a> mPositions;};
struct LLVolume {
    bool loaded=true; std::vector<LLVolumeFace> faces;
    bool isMeshAssetLoaded() const{return loaded;}
    int getNumVolumeFaces() const{return faces.size();}
    const LLVolumeFace& getVolumeFace(int f) const{return faces[f];}
    void vertices(std::initializer_list<Vec> verts){faces={{}}; for(auto v:verts)faces[0].mPositions.push_back({v});faces[0].mNumVertices=verts.size();}
};
struct LLViewerObject {
    virtual ~LLViewerObject()=default;
    bool dead=false,selected=true,attachment=false,avatar=false;
    LLViewerObject* root=nullptr; Vec position;
    bool isDead() const{return dead;} bool isSelected() const{return selected;}
    bool isAttachment() const{return attachment;} bool isAvatar() const{return avatar;}
    LLViewerObject* getRootEdit(){return root?root:this;}
    Vec getPivotPositionAgent(){return position;}
};
struct LLVOVolume: LLViewerObject {
    bool rigged=false,mesh=true,mGLTFAsset=false;
    LLPointer<int> mDrawable{reinterpret_cast<int*>(1)};
    LLVolume geometry; Vec scale{1,1,1}; double angle=0;
    bool isRiggedMesh(){return rigged;} bool isMesh(){return mesh;}
    bool isHUDAttachment(){return false;}
    LLVolume* getVolume(){return &geometry;}
    Vec volumePositionToAgent(Vec v){
        double x=v.mV[0]*scale.mV[0], y=v.mV[1]*scale.mV[1], z=v.mV[2]*scale.mV[2];
        return position+Vec{x*std::cos(angle)+z*std::sin(angle),y,-x*std::sin(angle)+z*std::cos(angle)};
    }
};
struct LLSelectNode {
    LLViewerObject* object; int mSelectedGLTFNode=-1; bool mIndividualSelection=false;
    LLViewerObject* getObject(){return object;}
};
struct Selection {
    std::vector<LLSelectNode*> nodes; int type=SELECT_TYPE_WORLD;
    auto begin(){return nodes.begin();} auto end(){return nodes.end();}
    bool isEmpty(){return nodes.empty();} int getSelectType(){return type;}
    int getObjectCount(){return nodes.size();} LLViewerObject* getFirstObject(){return nodes[0]->object;}
    LLSelectNode* findNode(LLViewerObject* o){for(auto n:nodes)if(n->object==o)return n;return nullptr;}
} selection;
struct LLSelectMgr {
    static LLSelectMgr* getInstance(){static LLSelectMgr s;return &s;}
    Selection* getSelection(){return &selection;}
    LLSelectMgr& getBBoxOfSelection(){return *this;} Vec getCenterAgent(){return {0,0,10};}
};
struct Agent {
    Vec getPosGlobalFromAgent(Vec v){return v+Vec{100000,200000,0};}
    Vec getPositionAgent(){return {};}
} gAgent;
struct Settings {
    bool limited=false,select_limited=false;
    float getF32(const char*){return 10;}
    bool getBOOL(const char* s){return std::string(s)=="LimitSelectDistance"?select_limited:limited;}
} gSavedSettings;
struct LLCoordGL {int mX=0,mY=0;};
struct LLViewerCamera {
    static LLViewerCamera* getInstance(){static LLViewerCamera c;return &c;}
    Vec getOrigin(){return {};} float getNear(){return .1f;}
    bool projectPosAgentToScreen(Vec p,LLCoordGL& screen){screen={100,100};return p.mV[2]>0;}
};
struct Window {
    int cursor=0,x=100,y=100; void setCursor(int c){cursor=c;}
    Vec mouseDirectionGlobal(int,int){return {1,0,0};}
    int getCurrentMouseX(){return x;} int getCurrentMouseY(){return y;}
} window;
auto* gViewerWindow=&window;
struct Pipeline {
    std::vector<std::pair<LLViewerObject*,Vec>> hits; int calls=0;
    Vec hit_normal{0,0,1};
    LLViewerObject* lineSegmentIntersectInWorld(LLVector4a begin,LLVector4a end,
        bool transparent,bool rigged,bool unselectable,bool probe,void*,void*,void*,LLVector4a* p,void*,LLVector4a* normal,
        void* =nullptr,void* =nullptr,const std::function<bool(LLViewerObject*)>& filter={}){
        assert(!transparent&&!rigged&&unselectable&&!probe); ++calls;
        for(auto h:hits)if((!filter||filter(h.first))&&h.second.mV[0]>=begin.v.mV[0]&&h.second.mV[0]<=end.v.mV[0]){
            p->v=h.second;if(normal)normal->v=hit_normal;return h.first;
        }
        return nullptr;
    }
} gPipeline;
struct LLManipTranslate {
    Selection* mObjectSelection=&selection; LLPointer<LLViewerObject> mVertexObject;
    Vec mVertexLocal,mVertexStart,mVertexDestination;
    bool mCenterDrag=true,mVertexTarget=false,mMouseOutsideSlop=false;
    bool mSurfaceBoundsValid=false;
    Vec mSurfaceMin,mSurfaceMax,mSurfaceOffset;
    bool allowed=true,capture=true,plane=true,clamp=false;
    static inline bool vheld=false;
    int mMouseDownX=0,mMouseDownY=0,writes=0;
    Vec pivot{0,0,10},applied,mManipNormal{0,0,1};
    Vec mDragSelectionStartGlobal{100000,200000,10},mDragCursorStartGlobal{100000,200000,10};
    bool hasMouseCapture(){return capture;}
    bool canAffectSelection(){for(auto n:selection.nodes)if(n->object->isDead())return false;return allowed;}
    static bool vertexSnapHeld(){return vheld;}
    Vec getPivotPoint(){return pivot;}
    bool getMousePointOnPlaneGlobal(Vec& p,int x,int y,Vec origin,Vec){p={100000.+x,200000.+y,origin.mV[2]};return plane;}
    void applyTranslation(Vec delta){
        if(clamp)delta=delta+Vec{0,0,1};
        Vec change=delta-applied; pivot=pivot+change;
        for(auto n:selection.nodes)n->object->position=n->object->position+change;
        applied=delta; ++writes;
    }
    bool getCenterHandle(Vec&) const; bool centerHandleHit(int,int) const;
    bool updateSurfaceBounds(); Vec getSurfaceOffset(const Vec&) const;
    bool findSurface(int,int,Vec&,Vec&); bool vertexPoint(Vec&) const;
    bool findVertex(int,int,bool,LLPointer<LLViewerObject>&,Vec&);
    bool hover(int x,int y,MASK mask){
""" + source[start:end] + r"""
        return false;
    }
};
"""
for signature in (
    "bool LLManipTranslate::vertexPoint",
    "bool LLManipTranslate::getCenterHandle",
    "bool LLManipTranslate::centerHandleHit",
    "bool LLManipTranslate::updateSurfaceBounds",
    "LLVector3 LLManipTranslate::getSurfaceOffset",
    "bool LLManipTranslate::findSurface",
    "bool LLManipTranslate::findVertex",
):
    harness += function(source, signature) + "\n"
harness += r"""
struct LLTool {virtual ~LLTool()=default;};
struct LLToolComposite:LLTool {LLTool* getOverrideTool(MASK){return nullptr;}};
struct LLToolCompRotate:LLTool {static LLTool* getInstance(){static LLToolCompRotate t;return &t;}};
struct LLToolCompScale:LLTool {static LLTool* getInstance(){static LLToolCompScale t;return &t;}};
struct LLToolCompTranslate:LLToolComposite {
    LLManipTranslate* mManip; LLTool* getOverrideTool(MASK);
};
""" + function(composite, "LLTool* LLToolCompTranslate::getOverrideTool") + r"""
int main(){
    LLVOVolume a,b; LLSelectNode na{&a},nb{&b}; selection.nodes={&na,&nb};
    a.position={0,0,10}; b.position={0,0,7}; b.scale={2,3,4};
    a.geometry.vertices({{-1,-1,-1},{1,1,1}});
    b.geometry.vertices({{0,0,-1},{1,0,0},{0,0,1}});
    LLManipTranslate m;
    assert(m.updateSurfaceBounds() && m.mSurfaceBoundsValid);
    assert(near(m.mSurfaceOffset,{0,0,-7}));
    b.angle=std::acos(-1.)/2; assert(m.updateSurfaceBounds());
    assert(near(m.mSurfaceOffset,{0,0,-5}));
    b.angle=0; b.geometry.vertices({{2,0,-1},{0,0,-1}});
    assert(m.updateSurfaceBounds() && near(m.mSurfaceOffset,{0,0,-7}));
    selection.nodes={&na}; na.mIndividualSelection=true;
    assert(m.updateSurfaceBounds() && near(m.mSurfaceOffset,{0,0,-1})); // only edited part contributes
    selection.nodes={&na,&nb};
    b.geometry.loaded=false; assert(!m.updateSurfaceBounds() && !m.mSurfaceBoundsValid);
    b.geometry.loaded=true; b.rigged=true; assert(!m.updateSurfaceBounds()); b.rigged=false;
    b.mGLTFAsset=true; assert(!m.updateSurfaceBounds()); b.mGLTFAsset=false;
    b.attachment=true; assert(!m.updateSurfaceBounds()); b.attachment=false;
    b.geometry.vertices({{0,0,std::numeric_limits<double>::quiet_NaN()}});
    assert(!m.updateSurfaceBounds()); b.geometry.vertices({{2,3,-1}});
    assert(m.updateSurfaceBounds());
    // The lowest vertex is at (4,9,3), but floor contact keeps the origin's X/Y.
    assert(near(m.getSurfaceOffset({0,0,1}),{0,0,-7}));
    assert(near(m.getSurfaceOffset({0,0,-1}),{0,0,1}));
    assert(near(m.getSurfaceOffset({1,0,0}),{-1,0,0}));
    assert(near(m.getSurfaceOffset({-1,0,0}),{4,0,0}));
    assert(near(m.getSurfaceOffset({0,1,0}),{0,-1,0}));
    assert(near(m.getSurfaceOffset({0,-1,0}),{0,9,0}));
    assert(near(m.getSurfaceOffset({.4,.2,.9}),{0,0,-7}));
    assert(near(m.getSurfaceOffset({1,0,1}),{0,0,-7})); // stable Z tie-break

    // Modifier routing works even while the Move manipulator is deselected.
    LLToolCompTranslate tool; tool.mManip=&m; m.mObjectSelection=nullptr;
    assert(tool.getOverrideTool(3)==&tool);
    window.x=108; assert(tool.getOverrideTool(3)==LLToolCompScale::getInstance());
    window.x=100; assert(tool.getOverrideTool(1)==LLToolCompRotate::getInstance());
    assert(tool.getOverrideTool(0)==nullptr);
    selection.type=SELECT_TYPE_HUD; assert(!m.centerHandleHit(100,100)); selection.type=SELECT_TYPE_WORLD;
    LLManipTranslate::vheld=true; assert(!m.centerHandleHit(100,100)); LLManipTranslate::vheld=false;
    m.mObjectSelection=&selection;

    LLViewerObject target,avatar,sibling; target.selected=false; avatar.selected=false; avatar.avatar=true;
    sibling.selected=false; sibling.root=&a;
    Vec hit,normal;
    gPipeline.hits={{&a,{1,0,0}},{&b,{2,0,0}},{&avatar,{3,0,0}},{&target,{8,0,0}}};
    assert(m.findSurface(0,0,hit,normal) && near(hit,{100008,200000,0}) && gPipeline.calls==1);
    assert(near(normal,{0,0,1}));
    gPipeline.hits={{&sibling,{3,0,0}},{&target,{8,0,0}}};
    na.mIndividualSelection=false; assert(m.findSurface(0,0,hit,normal) && hit.mV[0]==100008);
    na.mIndividualSelection=true; assert(m.findSurface(0,0,hit,normal) && hit.mV[0]==100003);
    gPipeline.hit_normal={};assert(m.findSurface(0,0,hit,normal)&&near(normal,{0,0,1}));
    gPipeline.hit_normal={0,0,1};
    gPipeline.hits={}; assert(!m.findSurface(0,0,hit,normal));
    // A selected base/shadow card touching the tabletop must not hide that table.
    // Advancing past the selected hit skips the coincident support and picks the floor.
    gPipeline.hits={{&a,{8,0,0}},{&target,{8,0,0}},{&target,{12,0,0}}};
    assert(m.findSurface(0,0,hit,normal) && near(hit,{100008,200000,0}));
    // No traversal cap or epsilon gap: dense selected geometry cannot hide support.
    gPipeline.hits.assign(300,{&a,{8,0,0}});
    gPipeline.hits.push_back({&target,{8.0001,0,0}}); gPipeline.calls=0;
    assert(m.findSurface(0,0,hit,normal) && near(hit,{100008.0001,200000,0}) && gPipeline.calls==1);
    gPipeline.hits={{&a,{1,0,0}}}; gPipeline.calls=0;
    assert(!m.findSurface(0,0,hit,normal) && gPipeline.calls==1);

    gPipeline.hits={{&target,{8,0,0}}};
    assert(m.hover(0,0,0) && m.writes==0); // quick click does not teleport
    assert(m.hover(8,0,0) && m.mVertexTarget && near(m.applied,{8,0,-3}));
    m.hover(8,0,0); assert(m.mVertexTarget && near(m.applied,{8,0,-3})); // no cumulative drift
    // Repeated floor/table contact at and below the old 1 mm ray-step spacing.
    // Each frame puts the selected base directly on the newly chosen support.
    for(double height:{0.,2.})for(int frame=0;frame<128;++frame){
        double x=8.+frame*.000125;
        gPipeline.hits={{&a,{x,0,height}},{&target,{x,0,height}},{&target,{12,0,-2}}};
        m.hover(8,0,0);
        assert(m.mVertexTarget && near(m.applied,{x,0,height-3}));
    }
    gPipeline.hits={}; int writes=m.writes;
    m.hover(15,0,3); assert(m.writes==writes && !m.mVertexTarget); // sky holds position
    m.hover(15,0,0); assert(m.writes==writes); // no modifier: sky still holds position
    m.hover(17,0,0); assert(m.writes==writes);
    gPipeline.hits={{&target,{5,0,0}}}; m.hover(17,0,3);
    assert(near(m.applied,{5,0,-3}) && m.mVertexTarget); // modifier changes keep surface snapping active
    for(int mask=0;mask<8;++mask){m.hover(17,0,mask);assert(near(m.applied,{5,0,-3})&&m.mVertexTarget);}
    // Switching support axes keeps the two other coordinates at the origin.
    gPipeline.hit_normal={-1,0,0};m.hover(17,0,3);
    assert(near(m.applied,{1,0,-10})&&m.mVertexTarget);
    gPipeline.hit_normal={0,0,-1};m.hover(17,0,3);
    assert(near(m.applied,{5,0,-11})&&m.mVertexTarget);
    gPipeline.hit_normal={0,0,1};m.hover(17,0,3);
    assert(near(m.applied,{5,0,-3})&&m.mVertexTarget);
    writes=m.writes; m.allowed=false; m.hover(20,0,3); assert(m.writes==writes);
    m.allowed=true; gSavedSettings.limited=true; gPipeline.hits={{&target,{40,0,0}}};
    m.hover(40,0,3); assert(m.writes==writes && window.cursor==UI_CURSOR_NOLOCKED);
    gSavedSettings.limited=false; gPipeline.hits={{&target,{5,0,0}}}; m.clamp=true;
    m.hover(20,0,3); assert(!m.mVertexTarget); // no green success after a movement clamp
    m.clamp=false; b.dead=true; writes=m.writes; m.hover(20,0,3); assert(m.writes==writes);
    b.dead=false; m.mSurfaceBoundsValid=false; m.hover(20,0,0); assert(m.writes==writes);
    m.mCenterDrag=false; assert(!m.hover(20,0,3));
    // The sibling vertex picker also reaches a target touching the selection.
    LLVOVolume mesh_target; mesh_target.selected=false; mesh_target.position={8,0,5};
    mesh_target.geometry.vertices({{0,0,0},{1,0,0}});
    gPipeline.hits={{&a,{8,0,0}},{&mesh_target,{8,0,0}}}; gPipeline.calls=0;
    LLPointer<LLViewerObject> vertex_object; Vec local;
    assert(m.findVertex(100,100,false,vertex_object,local));
    assert(vertex_object.get()==&mesh_target && near(local,{0,0,0}) && gPipeline.calls==9);
}
"""

ET.parse(root / "indra/newview/skins/default/xui/en/floater_tools.xml")
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / "surface_snap.cpp"
    exe = Path(directory) / "surface_snap.exe"
    cpp.write_text(harness)
    subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("Surface snap: 256 repeated floor/table contact frames, shadow-card overlap, dense selections, submillimetre movement, floor/wall/ceiling bounds, linked parts, routing, limits and permissions passed.")
