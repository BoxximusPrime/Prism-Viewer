"""Exercise the production photo OIT resource lifecycle without an avatar capture."""
from pathlib import Path
import subprocess
import tempfile
from test_camera_smoothing import function

ROOT = Path(__file__).resolve().parents[2]
source = r'''
#include <algorithm>
#include <cassert>
#include <cstring>
#include <functional>
#include <set>
#include <utility>
using U32=unsigned; using S32=int; using GLint=int; using GLenum=unsigned;
using uuid_set_t=std::set<int>;
enum { GL_RGBA, GL_SHADER_STORAGE_BUFFER_BINDING, GL_IMAGE_BINDING_NAME,
 GL_IMAGE_BINDING_LEVEL, GL_IMAGE_BINDING_LAYERED, GL_IMAGE_BINDING_LAYER,
 GL_IMAGE_BINDING_ACCESS, GL_IMAGE_BINDING_FORMAT, GL_BUFFER_UPDATE_BARRIER_BIT=16,
 GL_SHADER_STORAGE_BARRIER_BIT=32, GL_SHADER_IMAGE_ACCESS_BARRIER_BIT=64,
 GL_SHADER_STORAGE_BUFFER, GL_COLOR_ATTACHMENT0, GL_FRAMEBUFFER };
bool supported=true, allocate=true, can_grow=true;
int draws=0, composites=0, releases=0, storage=99, bindings[]={41,42};
int images[2][6]={{21,0,0,0,1,2},{22,0,0,0,1,2}};
U32 requested=3;
void glGetIntegerv(GLenum, GLint* p) { *p=storage; }
void glGetIntegeri_v(GLenum field, U32 i, GLint* p) {
 *p=field==GL_SHADER_STORAGE_BUFFER_BINDING?bindings[i]:images[i][field-GL_IMAGE_BINDING_NAME];
}
void glBindBuffer(GLenum, int value) { storage=value; }
void glBindBufferBase(GLenum, U32 i, int value) { bindings[i]=storage=value; }
void glBindImageTexture(U32 i, int name, int level, int layered, int layer, int access, int format) {
 int values[]={name,level,layered,layer,access,format}; std::copy(values,values+6,images[i]);
}
void glMemoryBarrier(U32) {}
void glDrawBuffers(int, const GLenum*) {}
void glBindFramebuffer(GLenum, int value) { assert(value==17); }
struct LLRenderTarget {
 static inline int sCurFBO=17;
 U32 getWidth() const { return 512; } U32 getHeight() const { return 512; }
 bool allocate(U32, U32, GLenum) { return ::allocate; }
};
struct { int triangle=1; int* mScreenTriangleVB=&triangle; } gPipeline;
const uuid_set_t* sPreviewBodies=nullptr;
std::function<void()> sPreviewBeforeAlpha;
bool sPreviewGrey=false;
struct FSExactOIT {
 struct Resources { int id=0, control=0; U32 capacity=0; bool available=false; };
 static Resources sResources;
 static inline bool sCaptureCompleted=true, sCaptureClearNeeded=false,
   sVanillaFallbackActive=true, sCaptureActive=false;
 static bool isSupported() { return supported; }
 static bool shadersReady() { return true; }
 static bool allocateCaptureImages(U32, U32) { return true; }
 static void allocateNodePool(U32, U32, bool) { sResources={18,55,4,true}; }
 static void beginFrame() { sCaptureCompleted=false; sCaptureClearNeeded=true; sVanillaFallbackActive=false; }
 static void growNodePool(U32 count) { if (can_grow) sResources.capacity=count; }
 static void composite(LLRenderTarget&, int&, U32 maximum, bool indirect, LLRenderTarget* background) {
   assert(maximum==requested && !indirect && background); ++composites;
 }
 static void releaseResources(bool preserve, bool release_opaque) {
   assert(!preserve && !release_opaque && sResources.id==18); ++releases; sResources={};
 }
 static bool renderPreview(LLRenderTarget&, const uuid_set_t&, const std::function<void()>&,
                           const std::function<void()>&);
};
FSExactOIT::Resources FSExactOIT::sResources={7,8,900,true};
void glGetBufferSubData(GLenum, int, int, U32* output) {
 output[0]=requested; output[1]=FSExactOIT::sResources.capacity;
 output[2]=requested>output[1]; output[3]=requested;
}
'''
source += function('indra/newview/fsexactoit.cpp',
                   'bool FSExactOIT::renderPreview(LLRenderTarget& target')
source += r'''
int main() {
 LLRenderTarget target;
 uuid_set_t bodies={12};
 int before_alpha=0;
 auto prepare=[&] { ++before_alpha; };
 auto render=[&] {
   assert(FSExactOIT::sResources.id==18 && sPreviewBodies==&bodies);
   assert(FSExactOIT::sCaptureClearNeeded && !FSExactOIT::sVanillaFallbackActive);
   sPreviewBeforeAlpha(); ++draws;
   FSExactOIT::sCaptureCompleted=true; FSExactOIT::sCaptureClearNeeded=false;
   sPreviewGrey=true;
   glBindBufferBase(GL_SHADER_STORAGE_BUFFER,0,55);
   glBindBufferBase(GL_SHADER_STORAGE_BUFFER,1,56);
   glBindImageTexture(0,77,1,0,0,2,3); glBindImageTexture(1,78,1,0,0,2,3);
 };
 auto restored=[] {
   assert(FSExactOIT::sResources.id==7 && FSExactOIT::sResources.control==8);
   assert(FSExactOIT::sResources.capacity==900 && FSExactOIT::sResources.available);
   assert(FSExactOIT::sCaptureCompleted && !FSExactOIT::sCaptureClearNeeded);
   assert(FSExactOIT::sVanillaFallbackActive && !FSExactOIT::sCaptureActive);
   assert(!sPreviewBodies && !sPreviewBeforeAlpha && !sPreviewGrey);
   assert(storage==99 && bindings[0]==41 && bindings[1]==42);
   int expected[2][6]={{21,0,0,0,1,2},{22,0,0,0,1,2}};
   assert(std::memcmp(images,expected,sizeof(images))==0);
 };
 assert(FSExactOIT::renderPreview(target,bodies,render,prepare)); restored();
 assert(draws==1 && before_alpha==1 && composites==1 && releases==1);
 requested=8; // First attempt overflows; complete recapture is composited after growth.
 assert(FSExactOIT::renderPreview(target,bodies,render,prepare)); restored();
 assert(draws==3 && composites==2 && releases==2);
 requested=20; can_grow=false; // Memory limit: no incomplete composite or resource loss.
 assert(!FSExactOIT::renderPreview(target,bodies,render,prepare)); restored();
 assert(draws==4 && composites==2 && releases==3);
 assert(!FSExactOIT::renderPreview(target,bodies,[]{},prepare)); restored();
 assert(composites==2 && releases==4); // Missing alpha traversal also fails cleanly.
 allocate=false;
 assert(!FSExactOIT::renderPreview(target,bodies,render,prepare)); restored();
 allocate=true; supported=false;
 assert(!FSExactOIT::renderPreview(target,bodies,render,prepare)); restored();
 assert(draws==4 && composites==2 && releases==4);
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp, exe = Path(directory) / 'photo_oit.cpp', Path(directory) / 'photo_oit.exe'
    cpp.write_text(source, encoding='utf-8')
    subprocess.run(['g++', '-std=c++17', str(cpp), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('Photo OIT success, overflow retry, failed capture/allocation, and world resource/state restoration passed.')
