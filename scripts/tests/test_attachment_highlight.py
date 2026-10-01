"""Exercise the production outline transforms and face dispatch. Requires g++."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
selection = (root / "indra/newview/llselectmgr.cpp").read_text()
faces = (root / "indra/newview/llface.cpp").read_text()
outline = selection.split("    auto renderMeshSelection_f = ", 1)[1].split("\n    };", 1)[0] + "\n    };"
start = faces.index("void renderFace(LLDrawable* drawable, LLFace *face)")
face_draw = faces[start:faces.index("\n}\n", start) + 2]
program = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <vector>
using F32 = float; using S32 = int; using U16 = unsigned short;
#define llmin std::min
constexpr int GL_FRONT_AND_BACK=0, GL_LINE=1, GL_FILL=2;
constexpr int LL_PROFILE_ZONE_SCOPED_CATEGORY_FACE=0;
struct LLVector4a { float x=0,y=0,z=0; };
struct LLVector3 { float mV[3]; };
struct Matrix {
    float mMatrix[16]{};
    Matrix() { for (int i=0;i<4;++i) mMatrix[5*i]=1; }
    Matrix operator*(const Matrix& b) const {
        Matrix c;
        for(int row=0;row<4;++row) for(int col=0;col<4;++col) {
            c.mMatrix[4*col+row]=0;
            for(int k=0;k<4;++k) c.mMatrix[4*col+row]+=mMatrix[4*k+row]*b.mMatrix[4*col+k];
        }
        return c;
    }
    LLVector4a apply(LLVector4a p) const {
        return {mMatrix[0]*p.x+mMatrix[4]*p.y+mMatrix[8]*p.z+mMatrix[12],
                mMatrix[1]*p.x+mMatrix[5]*p.y+mMatrix[9]*p.z+mMatrix[13],
                mMatrix[2]*p.x+mMatrix[6]*p.y+mMatrix[10]*p.z+mMatrix[14]};
    }
};
Matrix transform(float angle,float x,float y,float z) {
    Matrix m; m.mMatrix[0]=m.mMatrix[5]=std::cos(angle);
    m.mMatrix[1]=std::sin(angle); m.mMatrix[4]=-std::sin(angle);
    m.mMatrix[12]=x; m.mMatrix[13]=y; m.mMatrix[14]=z; return m;
}
struct GL {
    enum { MM_MODELVIEW }; Matrix current; std::vector<Matrix> stack;
    void matrixMode(int) {} void loadIdentity() { current=Matrix{}; }
    void pushMatrix() { stack.push_back(current); }
    void popMatrix() { assert(!stack.empty()); current=stack.back(); stack.pop_back(); }
    void multMatrix(Matrix m) { current=current*m; }
    void multMatrix(float* p) { Matrix m; std::copy(p,p+16,m.mMatrix); multMatrix(m); }
    void translatef(float x,float y,float z) { multMatrix(transform(0,x,y,z)); }
    void setLineWidth(float) {}
} gGL;
struct LLRender { enum { MM_MODELVIEW, TRIANGLES }; };
Matrix gGLModelView;
void glPolygonMode(int,int) {}
struct LLGLSLShader {
    static inline LLGLSLShader* sCurBoundShaderPtr=nullptr;
    void bind() { sCurBoundShaderPtr=this; }
} gDebugProgram;
struct LLColor4 {};
struct LLSelectMgr { static inline bool sRenderHiddenSelections=false; };
struct LLVolumeFace {
    LLVector4a point; U16 indices[3]{0,0,0};
    LLVector4a* mPositions=&point; U16* mIndices=indices; int mNumIndices=3;
};
struct LLVolume { LLVolumeFace face; const LLVolumeFace& getVolumeFace(int) { return face; } };
struct LLVOVolume {
    LLVolume bind, posed; LLVector4a animatedPoint; Matrix relative;
    int updates=0;
    Matrix& getRelativeXform() { return relative; }
    void updateRiggedVolume(bool force) { assert(force); ++updates; posed.face.point=animatedPoint; }
    LLVolume* getRiggedVolume() { return &posed; }
    LLVolume* getVolume() { return &bind; }
};
struct LLFace;
struct LLDrawable {
    enum { RIGGED }; bool rigged=false,active=true; LLVOVolume* volume; LLFace* face;
    bool isState(int) { return rigged; } bool isActive() { return active; }
    LLVOVolume* getVOVolume() { return volume; }
    LLFace* getFace(int) { return face; }
};
struct Region { LLVector3 getOriginAgent() { return {{100,200,0}}; } } region;
struct LLViewerObject {
    LLDrawable* mDrawable; Matrix model; bool hud=false;
    bool isHUDAttachment() { return hud; } Matrix& getRenderMatrix() { return model; }
    Region* getRegion() { return &region; } int getNumTEs() { return 1; } int getNumFaces() { return 1; }
};
struct LLSelectNode { bool isTransient() { return true; } bool isTESelected(int) { return true; } };
void renderFace(LLDrawable*,LLFace*);
struct LLFace {
    LLDrawable* drawable; int getTEOffset() { return 0; }
    void renderOneWireframe(LLColor4,float,bool,bool,bool) { renderFace(drawable,this); }
};
LLVector4a drawn;
struct LLVertexBuffer {
    static void unbind() {}
    static void drawElements(int,const LLVector4a* pos,void*,int,const U16*) { drawn=gGL.current.apply(*pos); }
};
// Production renderFace uses this primitive constant.
'''
program += face_draw + r'''
void highlight(LLViewerObject* object) {
    float fogCfx=0; bool wireframe_selection=false;
    auto renderMeshSelection_f = ''' + outline + r'''
    LLSelectNode node; renderMeshSelection_f(&node,object,LLColor4{});
}
void equal(LLVector4a a, LLVector4a b) {
    assert(std::fabs(a.x-b.x)<.001f && std::fabs(a.y-b.y)<.001f && std::fabs(a.z-b.z)<.001f);
}
int main() {
    LLVOVolume volume; LLDrawable drawable{true,true,&volume,nullptr};
    LLFace face{&drawable}; drawable.face=&face;
    LLViewerObject object{&drawable};
    volume.bind.face.point={1,2,3}; volume.relative=transform(-.8f,20,30,40);
    gGLModelView=transform(.4f,-7,8,-9);
    LLGLSLShader original; original.bind();
    // Attachment transforms keep changing as the avatar animates. The CPU
    // skinning output is already in agent space and must receive only the view.
    for(bool active : {false,true}) for(int frame=0;frame<20;++frame) {
        drawable.active=active;
        object.model=transform(frame*.13f,frame*2,5-frame,frame*.5f);
        volume.animatedPoint=transform(frame*.31f,70-frame,20+frame,frame*.2f).apply(volume.bind.face.point);
        Matrix previous=transform(.9f,9,10,11); gGL.current=previous;
        original.bind();
        highlight(&object);
        equal(drawn,gGLModelView.apply(volume.animatedPoint));
        equal(gGL.current.apply({}),previous.apply({}));
        assert(gGL.stack.empty() && LLGLSLShader::sCurBoundShaderPtr==&original);
    }
    assert(volume.updates==40);
    // Unrigged attachments, world objects and HUDs retain their local transforms.
    drawable.rigged=false;
    for(bool hud : {false,true}) for(bool active : {false,true}) {
        object.hud=hud; drawable.active=active;
        Matrix previous=transform(.9f,9,10,11); gGL.current=previous;
        Matrix expected=hud?previous:gGLModelView;
        if(active) expected=expected*object.model;
        else if(!hud) expected=expected*transform(0,100,200,0);
        expected=expected*volume.relative;
        highlight(&object); equal(drawn,expected.apply(volume.bind.face.point));
        assert(gGL.stack.empty() && volume.updates==40);
    }
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp=Path(directory)/"outline.cpp"
    exe=Path(directory)/"outline.exe"
    cpp.write_text(program)
    subprocess.run(["g++","-std=c++17",str(cpp),"-o",str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print("Attachment outlines: 40 animated rigged poses, unrigged world/attachment/HUD transforms and render-state restoration passed")
