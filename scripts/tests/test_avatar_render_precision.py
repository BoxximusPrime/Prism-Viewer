"""Run production relative transforms and matrix-cache code against altitude regressions.

Requires g++ and the configured viewer's GLM headers. No viewer state is changed.
"""
import subprocess
import tempfile
from pathlib import Path

from test_camera_smoothing import ROOT, function


def main():
    code = r'''
#include <cassert>
#include <cmath>
#include <cstring>
#include <iostream>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/type_ptr.hpp>
#include <glm/gtc/quaternion.hpp>
using F32=float; using U32=unsigned; using S32=int;
#define STOP_GLERROR
#define LL_PROFILE_ZONE_SCOPED_CATEGORY_DISPLAY
constexpr bool GL_FALSE=false;
struct LLVector3 {
    float mV[3]{};
    LLVector3()=default;
    LLVector3(float x,float y,float z):mV{x,y,z}{}
    explicit LLVector3(glm::vec3 v):LLVector3(v.x,v.y,v.z){}
    glm::vec3 vec() const { return {mV[0],mV[1],mV[2]}; }
    bool operator!=(const LLVector3& b) const { return vec()!=b.vec(); }
    bool isExactlyZero() const { return vec()==glm::vec3(0); }
    void clear() { *this=LLVector3(); }
    void scaleVec(const LLVector3& b) { *this=LLVector3(vec()*b.vec()); }
    LLVector3 operator+(const LLVector3& b) const { return LLVector3(vec()+b.vec()); }
    LLVector3 operator-(const LLVector3& b) const { return LLVector3(vec()-b.vec()); }
    LLVector3 operator*(const glm::quat& q) const { return LLVector3(q*vec()); }
    LLVector3& operator+=(const LLVector3& b) { return *this=*this+b; }
    LLVector3& operator*=(const glm::quat& q) { return *this=*this*q; }
};
struct LLXform {
    LLVector3 mPosition, mWorldPosition, mScale{1,1,1};
    glm::quat mRotation{1,0,0,0}, mWorldRotation{1,0,0,0};
    LLXform* mParent=nullptr;
    bool scaleChildren=false;
    LLVector3 getWorldPositionRelativeTo(const LLVector3&) const;
    bool getScaleChildOffset() const { return scaleChildren; }
    const LLVector3& getScale() const { return mScale; }
    const LLVector3& getPosition() const { return mPosition; }
    const LLVector3& getWorldPosition() const { return mWorldPosition; }
    glm::quat getWorldRotation() const { return mWorldRotation; }
    const LLXform* getRoot() const { auto p=this; while(p->mParent) p=p->mParent; return p; }
};
struct LLXformMatrix:LLXform { void update(); };
struct LLMatrix4 {
    float mMatrix[4][4]{};
    LLMatrix4() { for(int i=0;i<4;++i) mMatrix[i][i]=1; }
    void setTranslation(LLVector3 p) { for(int i=0;i<3;++i) mMatrix[3][i]=p.mV[i]; }
};
struct LLRenderPass {
    static LLMatrix4 getModelMatrix(const LLMatrix4*, const LLXformMatrix*, LLVector3&);
};
struct LLRender {
    enum {MM_MODELVIEW,MM_PROJECTION,MM_TEXTURE0,NUM_MATRIX_MODES=6};
    glm::mat4 mMatrix[6][1];
    unsigned mMatHash[6]{1,1,1,1,1,1},mMatIdx[6]{};
    LLRender() { for(auto& m:mMatrix) m[0]=glm::mat4(1); }
    void syncMatrices();
    void syncLightState() {}
};
struct LLShaderMgr {
    enum {MODELVIEW_MATRIX,PROJECTION_MATRIX,TEXTURE_MATRIX0,TEXTURE_MATRIX1,
        TEXTURE_MATRIX2,TEXTURE_MATRIX3,NORMAL_MATRIX,INVERSE_MODELVIEW_MATRIX,
        MODELVIEW_PROJECTION_MATRIX,INVERSE_PROJECTION_MATRIX,IDENTITY_MATRIX};
};
struct LLGLSLShader {
    static inline LLGLSLShader* sCurBoundShaderPtr=nullptr;
    unsigned mMatHash[6]{~0U,~0U,~0U,~0U,~0U,~0U};
    LLVector3 mMatrixPaletteOrigin;
    struct {bool hasLighting=false,calculatesLighting=false,calculatesAtmospherics=false;} mFeatures;
    glm::mat4 uploaded[11];
    unsigned uploads=0;
    void setMatrixPaletteOrigin(const LLVector3&);
    int getUniformLocation(int i) { return i; }
    void uniformMatrix4fv(int i,int,bool,const float* p) { uploaded[i]=glm::make_mat4(p); ++uploads; }
    void uniformMatrix3fv(int,int,bool,const float*) {}
};
'''
    for path, signature in (
        ('indra/llmath/xform.cpp', 'LLVector3 LLXform::getWorldPositionRelativeTo'),
        ('indra/llmath/xform.cpp', 'void LLXformMatrix::update()'),
        ('indra/newview/lldrawpool.cpp', 'LLMatrix4 LLRenderPass::getModelMatrix'),
        ('indra/llrender/llglslshader.cpp', 'void LLGLSLShader::setMatrixPaletteOrigin'),
        ('indra/llrender/llrender.cpp', 'void LLRender::syncMatrices()'),
    ):
        code += '\n' + function(path, signature) + '\n'
    code += r'''
bool near(glm::mat4 a,glm::mat4 b) {
    for(int c=0;c<4;++c) for(int r=0;r<4;++r)
        if(std::abs(a[c][r]-b[c][r])>1e-5f) return false;
    return true;
}
int main() {
    unsigned cases=0; float old_error=0,new_error=0;
    for(float altitude:{0.f,1368.f,4000.f,8192.f,30000.f}) {
        LLXformMatrix seat,root,bone,attachment;
        seat.mPosition={15,242,altitude}; seat.mRotation=glm::angleAxis(.37f,glm::vec3(0,1,0));
        seat.update();
        root.mParent=&seat; root.mPosition={.2f,.1f,.8f}; root.scaleChildren=true;
        root.mScale={.7f,1.2f,1.5f}; root.update();
        bone.mParent=&root; attachment.mParent=&bone; attachment.mPosition={.031f,.071f,.113f};
        for(int i=0;i<100;++i) {
            bone.mPosition={.1f,.2f,.3f+i*.000013f}; bone.update(); attachment.update();
            // Independent double reference with the viewer's scale-child-offset rule.
            glm::dvec3 expected=glm::dvec3((root.mPosition*seat.mWorldRotation).vec());
            LLVector3 scaled=bone.mPosition; scaled.scaleVec(root.mScale);
            expected+=glm::dvec3((scaled*root.mWorldRotation).vec());
            expected+=glm::dvec3((attachment.mPosition*bone.mWorldRotation).vec());
            auto relative=attachment.getWorldPositionRelativeTo(seat.mPosition);
            float error=float(glm::length(glm::dvec3(relative.vec())-expected));
            new_error=std::max(new_error,error); assert(error<3e-7f);
            old_error=std::max(old_error,float(glm::length(glm::dvec3((attachment.mWorldPosition-seat.mPosition).vec())-expected)));
            LLMatrix4 world; world.setTranslation(attachment.mWorldPosition);
            LLVector3 origin;
            auto local=LLRenderPass::getModelMatrix(&world,&attachment,origin);
            assert(!(origin!=seat.mPosition));
            assert(glm::length(glm::vec3(local.mMatrix[3][0],local.mMatrix[3][1],local.mMatrix[3][2])-relative.vec())<1e-7f);
            // An ordinary world object and a null model retain their existing space.
            auto unchanged=LLRenderPass::getModelMatrix(&world,nullptr,origin);
            assert(origin.isExactlyZero() && std::memcmp(&world,&unchanged,sizeof world)==0);
            LLRenderPass::getModelMatrix(nullptr,nullptr,origin); assert(origin.isExactlyZero());
            ++cases;
        }
    }
    assert(old_error>1e-3f && new_error<3e-7f);
    LLRender render; LLGLSLShader first,second,world;
    auto check=[&](LLGLSLShader& shader,LLVector3 origin) {
        shader.setMatrixPaletteOrigin(origin); LLGLSLShader::sCurBoundShaderPtr=&shader;
        render.syncMatrices();
        auto expected=glm::mat4(glm::translate(glm::dmat4(render.mMatrix[0][0]),glm::dvec3(origin.vec())));
        assert(near(shader.uploaded[LLShaderMgr::MODELVIEW_MATRIX],expected));
        assert(near(shader.uploaded[LLShaderMgr::MODELVIEW_PROJECTION_MATRIX],render.mMatrix[1][0]*expected));
        assert(near(shader.uploaded[LLShaderMgr::INVERSE_MODELVIEW_MATRIX],glm::inverse(expected)));
        auto count=shader.uploads; render.syncMatrices(); assert(count==shader.uploads);
        ++cases;
    };
    for(int frame=0;frame<100;++frame) {
        float phase=frame*.003f;
        render.mMatrix[0][0]=glm::lookAt(glm::vec3(14+phase,240,4002),glm::vec3(15,242,4001),glm::vec3(0,0,1));
        ++render.mMatHash[0];
        check(first,{15,242,4000}); check(second,{17,243,4001}); check(world,{});
        check(first,{15,242,4000}); // Revisit a shader whose matrices are already current.
        render.mMatrix[1][0]=glm::perspective(.8f+phase,1.5f,.1f,1000.f); ++render.mMatHash[1];
        check(first,{15,242,4000}); // Projection-only change must retain the origin.
        check(first,{15,242,4001}); // Palette changes without a modelview hash change.
        check(world,{}); check(second,{17,243,4001});
    }
    std::cout << cases << " production transform/cache cases passed; worst relative error "
              << new_error << " m, old world accumulation " << old_error << " m\n";
}
'''
    with tempfile.TemporaryDirectory(prefix='avatar-precision-', dir=ROOT/'build-vc170-64') as directory:
        path = Path(directory)
        (path/'test.cpp').write_text(code)
        subprocess.run(['g++', '-std=c++17', '-O2', '-I', str(ROOT/'build-vc170-64/packages/include'),
                        str(path/'test.cpp'), '-o', str(path/'test.exe')], check=True)
        subprocess.run([str(path/'test.exe')], check=True)


if __name__ == '__main__':
    main()
