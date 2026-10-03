// Recording adapter for test_alpha_receiver_binding.py. Methods below are
// extracted from production files at runtime, never copied implementations.
#include <glm/glm.hpp>
#include <glm/gtc/type_ptr.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include "llalphalightselection.h"
#include <map>
#include <string>
#include <iostream>
#include <chrono>
#include <stdexcept>
#include <numeric>
#include <algorithm>
#include <array>
#include <vector>
#include <cmath>
#define LL_PROFILE_ZONE_NAMED_CATEGORY_PIPELINE(x)
using F32 = float; using U32 = uint32_t; using S32 = int;
constexpr int LL_NUM_LIGHT_UNITS = 8, DEFERRED_LIGHT_FALLOFF = 1;
template<class T> T llclamp(T v,T a,T b) { return std::clamp(v,a,b); }
template<class T> T llmax(T a,T b) { return std::max(a,b); }
bool enabled = true, gCubeSnapshot = false;
int gSavedSettings;
template<class T> struct LLCachedControl {
    std::string name; T value;
    LLCachedControl(int&,const char* n,T v):name(n),value(v) {}
    operator T() const { return name == "RenderAlphaReceiverLights" ? T(enabled) : value; }
};
struct LLVector3 {
    float mV[3]{};
    LLVector3()=default; LLVector3(float a,float b,float c):mV{a,b,c} {}
    LLVector3(const glm::vec3& v):mV{v.x,v.y,v.z} {}
    float operator[](int i)const{return mV[i];}
    void set(const float* p){std::copy_n(p,3,mV);} void setVec(const float* p){set(p);}
    operator glm::vec3() const{return {mV[0],mV[1],mV[2]};}
    static const LLVector3 zero;
};
const LLVector3 LLVector3::zero{};
LLVector3 operator*(const LLVector3& v,const glm::mat3& m){return LLVector3(m*glm::vec3(v));}
struct LLVector4 {
    float mV[4]{};
    LLVector4()=default; LLVector4(float a,float b,float c,float d):mV{a,b,c,d}{}
    LLVector4(const LLVector3& v,float w):mV{v[0],v[1],v[2],w}{}
    void set(const float* p){std::copy_n(p,4,mV);}
    void set(float a,float b,float c,float d){mV[0]=a;mV[1]=b;mV[2]=c;mV[3]=d;}
    operator glm::vec4() const{return {mV[0],mV[1],mV[2],mV[3]};}
};
struct LLVector2 {float mV[2]{};void set(float a,float b){mV[0]=a;mV[1]=b;}};
struct LLColor4 : LLVector4 {
    using LLVector4::LLVector4;
    float& operator[](int i){return mV[i];}
    LLColor4 operator*(float s)const{return {mV[0]*s,mV[1]*s,mV[2]*s,mV[3]*s};}
    bool operator!=(const LLColor4& v)const{return !std::equal(mV,mV+4,v.mV);}
    static const LLColor4 black;
};
const LLColor4 LLColor4::black{0,0,0,1};
using LLStaticHashedString = std::string;
struct LLShaderMgr {enum {ALPHA_PROJECTION0=100,LIGHT_POSITION=200,LIGHT_DIRECTION,
    LIGHT_ATTENUATION,LIGHT_DEFERRED_ATTENUATION,LIGHT_DIFFUSE,LIGHT_AMBIENT,
    SUN_UP_FACTOR,AMBIENT,SUNLIGHT_COLOR,MOONLIGHT_COLOR};};
struct LLGLSLShader {
    inline static LLGLSLShader* sCurBoundShaderPtr = nullptr;
    U32 mLightHash=~0u; bool mCanBindFast=true, projectorUniform=true;
    int calls=0; std::map<std::string,std::vector<float>> values;
    static std::string key(int n){return std::to_string(n);} static std::string key(const std::string& n){return n;}
    int getUniformLocation(const std::string&){return projectorUniform ? 0 : -1;}
    int enableTexture(int n){return n-LLShaderMgr::ALPHA_PROJECTION0;}
    template<class T> void record(T n,int width,int count,const float* p){++calls;values[key(n)]={p,p+width*count};}
    template<class T> void uniform1i(T n,int v){float f=float(v);record(n,1,1,&f);}
    template<class T> void uniform2fv(T n,int c,const float*p){record(n,2,c,p);}
    template<class T> void uniform3fv(T n,int c,const float*p){record(n,3,c,p);}
    template<class T> void uniform4fv(T n,int c,const float*p){record(n,4,c,p);}
    template<class T> void uniformMatrix4fv(T n,int c,bool,const float*p){record(n,16,c,p);}
};
struct LLViewerTexture {int id=0;int getWidth()const{return 256;}};
struct LLViewerFetchedTexture {inline static LLViewerTexture white{-1}; inline static LLViewerTexture* sWhiteImagep=&white;};
struct TexUnit {LLViewerTexture* current=nullptr;int attempts=0,changes=0;void bind(LLViewerTexture* p){++attempts;if(current!=p){++changes;current=p;}}};
struct LLLightState {
    LLVector4 mPosition;LLVector3 mSpotDirection;LLColor4 mDiffuse,mDiffuseB,mAmbient,mSpecular;
    float mLinearAtten=0,mQuadraticAtten=0,mConstantAtten=0,mSize=0,mFalloff=0,mSpotCutoff=0,mSpotExponent=0;
    bool mSunIsPrimary=false;
    void setPosition(const LLVector4&,const glm::mat4&);
    void setSpotDirection(const LLVector3&,const glm::mat4&);
    void setDiffuse(const LLColor4&);void setAmbient(const LLColor4&);void setSpecular(const LLColor4&);
    void setSize(float);void setFalloff(float);void setConstantAttenuation(const float&);
    void setLinearAttenuation(const float&);void setQuadraticAttenuation(const float&);void setSpotCutoff(const float&);void setSpotExponent(const float&);
};
struct LLRender {
private:
    U32 mLightHash=0;
    friend struct LLLightState;
public:
    LLLightState mLightState[8];LLColor4 mAmbientLightColor;TexUnit units[6];
    U32 recordedLightHash()const{return mLightHash;}
    // PRODUCTION_INVALIDATE_LIGHT_STATE
    glm::mat4 modelview{1.f};inline static bool sClassicMode=false;
    LLLightState* getLight(int n){return &mLightState[n];} TexUnit* getTexUnit(int n){return &units[n];}
    glm::mat4 getModelviewMatrix(){return modelview;}void syncLightState();
} gGL;
glm::mat4 camera{1.f};glm::mat4 get_current_modelview(){return camera;}
struct LLVOVolume {
    int id=0;bool spot=false,noShadow=false;LLViewerTexture texture;
    LLColor4 getLightLinearColor()const{return {float(id+1),float(id+2),float(id+3),1};}
    float getLightRadius()const{return 10+id;}float getLightFalloff(int=0)const{return .2f;}
    LLVector3 getRenderPosition()const{return {float(id+1),float(id+2),float(id+3)};}
    glm::mat3 getRenderRotation()const{return glm::mat3(1.f);}
    LLVector3 getSpotLightParams()const{return {1,2,.3f};}
    bool isLightSpotlight()const{return spot;}bool projectorShadowsDisabled()const{return noShadow;}
    LLViewerTexture* getLightTexture(){return &texture;}
};
struct LLDrawable {
    enum{ACTIVE=1};LLVOVolume* volume=nullptr;bool dead=false,active=false;
    bool isDead()const{return dead;}bool isState(int)const{return active;}
    LLVOVolume* getVOVolume()const{return volume;}
};
template<class T> struct LLPointer {
    T* ptr=nullptr;LLPointer()=default;LLPointer(T* p):ptr(p){}
    T* get()const{return ptr;}operator T*()const{return ptr;}T* operator->()const{return ptr;}
    LLPointer& operator=(T* p){ptr=p;return *this;}
};
struct ProjectorParams {glm::mat4 matrix{1.f};glm::vec3 plane,normal,origin;float focus=1,range=2,ambiance=3;};
struct LLPipeline {
    inline static bool sRenderDeferred=true,sRenderingHUDs=false,sImpostorRender=false;
    U32 mAlphaLightDepth=0,mLightMovingMask=0,mAlphaSavedMovingMask=0;int snapshots=0,projectionCalls=0;
    std::array<LLLightState,6> mAlphaSavedLights;std::array<LLColor4,6> mAlphaSavedColors;
    std::array<LLPointer<LLDrawable>,6> mAlphaSavedDrawables;
    LLColor4 mHWLightColors[8];LLPointer<LLDrawable> mHWLightDrawable[8];
    LLAlphaLightSelection::Selector mAlphaLightSelector;std::vector<LLPointer<LLDrawable>> mAlphaLightCandidates;
    glm::mat4 mAlphaLightView{1.f};bool mAlphaLightsBound=false;
    LLAlphaLightSelection::Selection mAlphaBoundLights;LLGLSLShader* mAlphaProjectorShader=nullptr;
    std::vector<LLGLSLShader*> mAlphaLightShaders;
    struct AlphaProjectorData {glm::mat4 matrix;LLVector3 plane,normal,origin;glm::vec4 params;glm::vec2 shadow;};
    std::map<LLDrawable*,AlphaProjectorData> mAlphaProjectorCache;
    struct {float mLightScale=.25f;}mReflectionMapManager;
    LLDrawable* mShadowSpotLight[2]{};float mSpotLightFade[2]{.2f,.7f};
    void updateAlphaLights(){++snapshots;}
    ProjectorParams getProjectorParams(LLDrawable* d){++projectionCalls;float n=float(d->volume->id+1);
        ProjectorParams p;p.matrix=glm::translate(glm::mat4(1.f),glm::vec3(n,n*2,n*3));
        p.plane={n,n+1,n+2};p.normal={n+3,n+4,n+5};p.origin={n+6,n+7,n+8};return p;}
    bool beginAlphaLights();void endAlphaLights();void restoreAlphaLightBaseline();
    void bindAlphaLights(LLGLSLShader&,const LLAlphaLightSelection::Bounds&);
    void bindAlphaLightSelection(LLGLSLShader&,const LLAlphaLightSelection::Selection&);
    void bindAlphaProjectors(LLGLSLShader&,bool);
};

// PRODUCTION_METHODS

void check(bool b,const char* why){if(!b)throw std::runtime_error(why);}
bool equal(const float* a,const float* b,int n){for(int i=0;i<n;++i)if(std::abs(a[i]-b[i])>1e-5f)return false;return true;}
bool equal(const LLLightState& a,const LLLightState& b){
    return equal(a.mPosition.mV,b.mPosition.mV,4)&&equal(a.mSpotDirection.mV,b.mSpotDirection.mV,3)&&
        equal(a.mDiffuse.mV,b.mDiffuse.mV,4)&&equal(a.mDiffuseB.mV,b.mDiffuseB.mV,4)&&
        equal(a.mAmbient.mV,b.mAmbient.mV,4)&&equal(a.mSpecular.mV,b.mSpecular.mV,4)&&
        a.mLinearAtten==b.mLinearAtten&&a.mQuadraticAtten==b.mQuadraticAtten&&a.mConstantAtten==b.mConstantAtten&&
        a.mSize==b.mSize&&a.mFalloff==b.mFalloff&&a.mSpotCutoff==b.mSpotCutoff&&
        a.mSpotExponent==b.mSpotExponent&&a.mSunIsPrimary==b.mSunIsPrimary;
}
LLAlphaLightSelection::Selection selection(std::initializer_list<int> ids){LLAlphaLightSelection::Selection s;s.count=ids.size();std::copy(ids.begin(),ids.end(),s.ids.begin());return s;}
struct Fixture {
    LLPipeline p;LLVOVolume volumes[12];LLDrawable drawables[12],baselineDrawables[8];
    std::array<LLLightState,8> baseline;std::array<LLColor4,8> colors;
    Fixture(){gGL=LLRender{};camera=glm::translate(glm::mat4(1.f),glm::vec3(3,4,5))*glm::rotate(glm::mat4(1.f),.7f,glm::vec3(0,1,0));
        // Receiver object transform is deliberately far from camera transform.
        gGL.modelview=camera*glm::translate(glm::mat4(1.f),glm::vec3(100,200,300));
        for(int i=0;i<12;++i){volumes[i].id=i;volumes[i].texture.id=i;drawables[i].volume=&volumes[i];drawables[i].active=(i%2)==0;p.mAlphaLightCandidates.emplace_back(&drawables[i]);}
        for(int i=0;i<8;++i){auto& l=gGL.mLightState[i];float n=float(i+10);
            l.mPosition={n,n+1,n+2,n+3};l.mSpotDirection={n+4,n+5,n+6};
            l.mDiffuse={n+7,n+8,n+9,n+10};l.mDiffuseB={n+11,n+12,n+13,n+14};
            l.mAmbient={n+15,n+16,n+17,n+18};l.mSpecular={n+19,n+20,n+21,n+22};
            l.mLinearAtten=n+23;l.mQuadraticAtten=n+24;l.mConstantAtten=n+25;l.mSize=n+26;
            l.mFalloff=n+27;l.mSpotCutoff=n+28;l.mSpotExponent=n+29;l.mSunIsPrimary=i%2;
            baseline[i]=l;p.mHWLightColors[i]={n+30,n+31,n+32,n+33};colors[i]=p.mHWLightColors[i];
            baselineDrawables[i].volume=&volumes[i];p.mHWLightDrawable[i]=&baselineDrawables[i];}
        p.mLightMovingMask=0xa5;
        std::vector<LLAlphaLightSelection::Candidate> candidates;
        for(int i=0;i<12;++i){LLAlphaLightSelection::Candidate c;c.id=i;c.radius=10;c.strength=1;
            c.position={float(i<6?0:100),0,0};candidates.push_back(c);}
        p.mAlphaLightSelector.build(std::move(candidates));
    }
    void restored(){check(p.mLightMovingMask==0xa5,"moving mask restoration");for(int i=0;i<8;++i){
        check(equal(gGL.mLightState[i],baseline[i]),"all eight full light states restored/preserved");
        check(equal(p.mHWLightColors[i].mV,colors[i].mV,4),"all eight colors restored/preserved");
        check(p.mHWLightDrawable[i].get()==&baselineDrawables[i],"all eight drawable identities restored/preserved");}}
};
void upload(LLGLSLShader& s){LLGLSLShader::sCurBoundShaderPtr=&s;gGL.syncLightState();}
void regression(){
    Fixture f;LLGLSLShader a,b;auto A=selection({0,1,2,3,4,5}),B=selection({6,7,8,9,10,11});
    for(auto& v:f.volumes)v.spot=true;f.p.mShadowSpotLight[0]=&f.drawables[1];f.p.mShadowSpotLight[1]=&f.drawables[4];
    check(f.p.beginAlphaLights(),"scope begin");check(f.p.beginAlphaLights(),"nested begin");check(f.p.snapshots==1,"nested snapshot runs only once");
    f.p.bindAlphaLightSelection(a,A);upload(a);check(a.values["alpha_projector_mask"][0]==63,"six projectors supported");
    auto sh=a.values["alpha_projector_shadow"];for(int i=0;i<6;++i)check(sh[i*2]==(i==1?0.f:i==4?1.f:-1.f),"two shadow slots exact drawable identity");
    check(std::abs(sh[3]-.8f)<1e-5f&&std::abs(sh[9]-.3f)<1e-5f,"shadow fade");
    auto expected=camera*glm::vec4(glm::vec3(f.volumes[0].getRenderPosition()),1);
    check(equal(gGL.mLightState[2].mPosition.mV,glm::value_ptr(expected),4),"explicit camera-only position ignores receiver model");
    glm::vec3 direction=glm::mat3(camera)*glm::vec3(0,0,-1);
    check(equal(gGL.mLightState[2].mSpotDirection.mV,glm::value_ptr(direction),3),"explicit camera-only spotlight direction");
    int before=a.calls,projectionBefore=f.p.projectionCalls;U32 hash=gGL.recordedLightHash();
    auto reversed=selection({5,4,3,2,1,0});f.p.bindAlphaLightSelection(a,reversed);upload(a);
    check(a.calls==before&&gGL.recordedLightHash()==hash,"repeated identity set skips light and projector uniform arrays");
    check(f.p.projectionCalls==projectionBefore,"projector cache avoids repeated projection computation");
    for(auto& t:gGL.units)check(t.attempts==2&&t.changes==1,"texture attempts preserve texunit deduplication");
    f.p.bindAlphaLightSelection(b,A);upload(b);check(b.calls==14,"same selected set refreshes new shader arrays");
    check(b.values["alpha_projector_matrix"]==a.values["alpha_projector_matrix"],"new shader receives same matrices");
    f.p.bindAlphaLightSelection(a,B);upload(a);check(gGL.recordedLightHash()!=hash,"receiver selection changes light hash");
    check(a.values["alpha_projector_matrix"][12]==7,"receiver B projector matrix updated on same shader");
    check(a.values[std::to_string(LLShaderMgr::LIGHT_DIFFUSE)][6]==7,"receiver B light IDs uploaded on same shader");
    check(f.p.mLightMovingMask==0x54,"moving mask follows chosen light slots");
    sh=a.values["alpha_projector_shadow"];for(int i=0;i<6;++i)check(sh[i*2]==-1,"unselected shadow identities do not leak");
    f.p.bindAlphaLights(a,LLAlphaLightSelection::Bounds{});f.restored();upload(a);
    check(a.values[std::to_string(LLShaderMgr::LIGHT_POSITION)][8]==12,"invalid direct bounds restore baseline uniforms");
    f.p.endAlphaLights();check(f.p.mAlphaLightDepth==1,"nested end preserves outer scope");
    f.p.endAlphaLights();f.restored();check(!a.mCanBindFast&&!b.mCanBindFast,"all touched shader fast binds invalidated");
    for(auto& d:f.p.mAlphaSavedDrawables)check(d.get()==nullptr,"saved drawable references cleared");
    std::cout<<"PASS state: receiver changes, shader changes, repeated sets, nested scopes, full baseline restoration, camera transforms\n";
}
void specialCases(){
    for(int mode=0;mode<4;++mode){Fixture f;enabled=mode!=0;LLPipeline::sRenderDeferred=mode!=1;LLPipeline::sRenderingHUDs=mode==2;LLPipeline::sImpostorRender=mode==3;
        check(!f.p.beginAlphaLights(),"disabled/deferred/HUD/impostor scope is noop");check(f.p.snapshots==0&&f.p.mAlphaLightDepth==0,"noop does not snapshot or increase nesting");f.restored();}
    enabled=true;LLPipeline::sRenderDeferred=true;LLPipeline::sRenderingHUDs=false;LLPipeline::sImpostorRender=false;
    for(int mode=0;mode<2;++mode){Fixture f;LLGLSLShader s;f.volumes[0].spot=true;f.volumes[0].noShadow=mode==0;
        gCubeSnapshot=mode==1;f.p.mShadowSpotLight[0]=&f.drawables[0];f.p.beginAlphaLights();f.p.bindAlphaLightSelection(s,selection({0}));
        check(s.values["alpha_projector_shadow"][0]==-1,"no-shadow/cube snapshot suppresses projector shadow");
        check(s.values["alpha_projector_mask"][0]==1,"one projector mask");check(s.values["alpha_projector_matrix"][16]==1,"empty slot matrix identity");f.p.endAlphaLights();}
    gCubeSnapshot=false;
    {Fixture f;LLGLSLShader s;f.p.beginAlphaLights();f.p.bindAlphaLightSelection(s,selection({0,1,2,3,4,5}));
        check(s.values["alpha_projector_mask"][0]==0,"point lights have no projector mask");for(auto& t:gGL.units)check(t.current==LLViewerFetchedTexture::sWhiteImagep,"point slots use white texture");f.p.endAlphaLights();}
    {Fixture f;LLGLSLShader s;s.projectorUniform=false;f.p.beginAlphaLights();f.p.bindAlphaLightSelection(s,selection({0}));upload(s);
        check(s.calls==7,"shader without projector uniforms uploads only lighting");f.p.endAlphaLights();check(!s.mCanBindFast,"shader without projector uniform invalidated");}
    {Fixture f;LLGLSLShader fallback;f.p.beginAlphaLights();f.p.bindAlphaLights(fallback,LLAlphaLightSelection::Bounds{});
        upload(fallback);f.p.endAlphaLights();f.restored();check(!fallback.mCanBindFast,"fallback-only touched shader fast bind invalidated");}
    {Fixture f;LLGLSLShader s;f.p.beginAlphaLights();LLAlphaLightSelection::Bounds receiver;
        receiver.min={99,-1,-1};receiver.max={101,1,1};f.p.bindAlphaLights(s,receiver);upload(s);
        check(f.p.mAlphaBoundLights.ids==selection({6,7,8,9,10,11}).ids,"actual Bounds overload invokes actual selector");
        f.drawables[6].dead=true;f.p.mAlphaLightsBound=false;f.p.bindAlphaLightSelection(s,selection({6}));
        check(f.p.mHWLightDrawable[2].get()==nullptr&&gGL.mLightState[2].mSize==0,"dead candidate slot cleared");f.p.endAlphaLights();f.restored();}
    std::cout<<"PASS special cases: disabled, nondeferred, HUD, impostor, point lights, absent projector uniform, no-shadow, cube snapshot, fallback-only shader invalidation, actual Bounds selector, dead candidates\n";
}
void benchmark(const char* label,int kind){
    Fixture f;LLGLSLShader s;for(int i=0;i<12;++i)f.volumes[i].spot=kind==1||(kind==2&&i%2==0);
    auto A=selection({0,1,2,3,4,5}),B=selection({6,7,8,9,10,11});std::vector<double> samples;
    int uniformCalls=0,attempts=0,changes=0;
    for(int run=0;run<31;++run){f.p.beginAlphaLights();int before=s.calls;int ta=0,tc=0;for(auto& t:gGL.units){ta+=t.attempts;tc+=t.changes;}
        auto start=std::chrono::steady_clock::now();for(int i=0;i<1000;++i){f.p.bindAlphaLightSelection(s,(i/10)%2?B:A);upload(s);}
        auto end=std::chrono::steady_clock::now();samples.push_back(std::chrono::duration<double,std::micro>(end-start).count());
        uniformCalls=s.calls-before;attempts=-ta;changes=-tc;for(auto& t:gGL.units){attempts+=t.attempts;changes+=t.changes;}f.p.endAlphaLights();}
    std::sort(samples.begin(),samples.end());
    check(uniformCalls==1400,"100 changed selections upload 14 actual recorded uniform calls each");
    check(attempts==6000,"six texture attempts per receiver draw");
    std::cout<<"CPU mock-stage benchmark "<<label<<": 1000 draws, 10 repeated draws/set, median_us="<<samples[15]
        <<", p95_us="<<samples[29]<<", uniform_calls="<<uniformCalls<<", texture_attempts="<<attempts
        <<", deduplicated_texture_changes="<<changes<<", added_draw_calls=0 (harness has no draw submission)\n";
}
int main(){try{regression();specialCases();benchmark("six points",0);benchmark("six projectors",1);benchmark("mixed",2);
    std::cout<<"LIMIT: adapters mock settings, projector parameter calculation, texture units and shader uploads; production selector, binding methods, all used light setters, explicit-view position/direction and syncLightState are compiled unchanged. No GPU/driver performance claim.\n";
    return 0;}catch(const std::exception& e){std::cerr<<"FAIL alpha receiver binding: "<<e.what()<<'\n';return 1;}}
