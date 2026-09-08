"""Run production readback-ring methods against controllable fences (g++ on PATH)."""
from pathlib import Path
import shutil
import subprocess
import tempfile

STUBS = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <map>
#include <vector>
using U32 = unsigned;
using GLenum = unsigned;
using GLuint = unsigned;
using GLsync = void*;
constexpr GLenum GL_TIMEOUT_EXPIRED=1, GL_ALREADY_SIGNALED=2,
    GL_CONDITION_SATISFIED=3, GL_WAIT_FAILED=4, GL_COPY_READ_BUFFER=5,
    GL_COPY_WRITE_BUFFER=6, GL_BUFFER_UPDATE_BARRIER_BIT=7,
    GL_SYNC_GPU_COMMANDS_COMPLETE=8;
#define LL_PROFILE_ZONE_NAMED(x)
struct Log { template<class T> Log& operator<<(const T&) { return *this; } };
#define LL_WARNS_ONCE(x) Log{}
#define LL_ENDL ""
template<class T> T llmax(T a,T b) { return std::max(a,b); }
std::map<GLuint,std::array<U32,4>> buffers;
std::map<GLsync,GLenum> fences;
GLuint read_binding=0, write_binding=0;
unsigned copies=0, reads=0, polls=0;
uintptr_t next_fence=1;
bool fail_fence=false;
GLenum glClientWaitSync(GLsync fence, unsigned flags, uint64_t timeout) {
    assert(flags==0 && timeout==0); ++polls; return fences.at(fence);
}
void glBindBuffer(GLenum target, GLuint buffer) {
    (target==GL_COPY_READ_BUFFER ? read_binding : write_binding)=buffer;
}
void glGetBufferSubData(GLenum, unsigned, unsigned size, void* data) {
    ++reads; assert(size==16); std::memcpy(data,buffers.at(read_binding).data(),16);
}
void glCopyBufferSubData(GLenum,GLenum,unsigned,unsigned,unsigned size) {
    ++copies; assert(size==16); buffers[write_binding]=buffers.at(read_binding);
}
void glMemoryBarrier(GLenum) {}
GLsync glFenceSync(GLenum,unsigned) {
    if(fail_fence) return nullptr;
    auto fence=reinterpret_cast<void*>(next_fence++);
    fences[fence]=GL_TIMEOUT_EXPIRED;
    return fence;
}
void glDeleteSync(GLsync fence) { fences.erase(fence); }
struct FSExactOIT {
    struct Resources {
        struct Readback { GLuint buffer=0; GLsync fence=nullptr; bool mouselook=false; };
        Readback readbacks[3];
        U32 readbackRead=0, readbackWrite=0, readbackPending=0;
        GLuint control=99;
        U32 overflowCount=0, capacity=32;
        bool available=true;
    };
    static Resources sResources;
    static std::vector<std::array<U32,3>> samples;
    static void collectStats();
    static void queueStats(bool);
    static void recordCaptureStats(U32 nodes,U32 depth,bool camera) { samples.push_back({nodes,depth,U32(camera)}); }
    static void growNodePool(U32 demand) { if(demand>sResources.capacity) sResources.capacity=demand; }
};
FSExactOIT::Resources FSExactOIT::sResources;
std::vector<std::array<U32,3>> FSExactOIT::samples;
'''

CHECKS = r'''
int main() {
    auto& r=FSExactOIT::sResources;
    for(U32 i=0;i<3;++i) r.readbacks[i].buffer=i+1;
    FSExactOIT::collectStats();
    assert(polls==0 && reads==0);
    for(U32 i=0;i<3;++i) {
        // All three overflowed their original pool; current pool is already larger.
        buffers[99]={10+i,8,1,2+i};
        FSExactOIT::queueStats(i==1);
    }
    assert(copies==3 && r.readbackPending==3);
    FSExactOIT::queueStats(false); // full ring skips sampling
    assert(copies==3);
    FSExactOIT::collectStats(); // all busy: zero readbacks
    assert(reads==0 && r.readbackPending==3 && r.capacity==32);
    fences[r.readbacks[1].fence]=GL_ALREADY_SIGNALED;
    FSExactOIT::collectStats(); // later completion must not reorder camera samples
    assert(reads==0);
    buffers[99]={999,32,1,999}; // reset/new frame cannot alter the immutable samples
    fences[r.readbacks[0].fence]=GL_CONDITION_SATISFIED;
    FSExactOIT::collectStats();
    assert(reads==2 && r.readbackPending==1 && r.capacity==32);
    assert((FSExactOIT::samples==std::vector<std::array<U32,3>>{{10,2,0},{11,3,1}}));
    assert(r.overflowCount==2);
    fences[r.readbacks[2].fence]=GL_WAIT_FAILED;
    FSExactOIT::collectStats(); // failed fence drops its sample without reading
    assert(reads==2 && r.readbackPending==0 && fences.empty());
    FSExactOIT::queueStats(false); // wrapped slot can now be reused
    fences[r.readbacks[0].fence]=GL_ALREADY_SIGNALED;
    FSExactOIT::collectStats();
    assert(reads==3 && r.capacity==999 && r.overflowCount==3);
    fail_fence=true;
    FSExactOIT::queueStats(true);
    assert(r.readbackPending==0);
    FSExactOIT::collectStats();
    assert(reads==3);
}
'''


def method(source, name):
    start = source.index(f"void FSExactOIT::{name}(")
    brace = source.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end] + "\n"


def main():
    compiler = shutil.which("g++")
    if compiler is None:
        raise SystemExit("g++ must be on PATH")
    root = Path(__file__).resolve().parents[2]
    source = (root / "indra/newview/fsexactoit.cpp").read_text()
    with tempfile.TemporaryDirectory(prefix="boxxy-oit-ring-") as folder:
        cpp, exe = Path(folder) / "check.cpp", Path(folder) / "check.exe"
        cpp.write_text(STUBS + method(source, "collectStats") + method(source, "queueStats") + CHECKS)
        subprocess.run([compiler, "-std=c++17", str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("Passed production readback ring: busy/full, FIFO/camera identity, historical capacity, wraparound, failed fences")


if __name__ == "__main__":
    main()
