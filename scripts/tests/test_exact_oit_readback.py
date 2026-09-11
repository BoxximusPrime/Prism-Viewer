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
#include <set>
#include <vector>
using U32 = unsigned;
using GLenum = unsigned;
using GLuint = unsigned;
using GLbitfield = unsigned;
using GLsync = void*;
constexpr GLenum GL_TIMEOUT_EXPIRED=1, GL_ALREADY_SIGNALED=2,
    GL_CONDITION_SATISFIED=3, GL_WAIT_FAILED=4, GL_COPY_READ_BUFFER=5,
    GL_COPY_WRITE_BUFFER=6, GL_BUFFER_UPDATE_BARRIER_BIT=7,
    GL_SYNC_GPU_COMMANDS_COMPLETE=8;
constexpr GLenum GL_NO_ERROR=0, GL_STREAM_READ=9;
constexpr GLbitfield GL_MAP_READ_BIT=1, GL_MAP_PERSISTENT_BIT=64, GL_MAP_COHERENT_BIT=128;
#define LL_PROFILE_ZONE_NAMED(x)
struct Log { template<class T> Log& operator<<(const T&) { return *this; } };
#define LL_WARNS_ONCE(x) Log{}
#define LL_ENDL ""
template<class T> T llmax(T a,T b) { return std::max(a,b); }
std::map<GLuint,std::array<U32,4>> buffers;
std::map<GLsync,GLenum> fences;
std::set<GLuint> immutable;
GLuint read_binding=0, write_binding=0;
unsigned copies=0, reads=0, polls=0;
uintptr_t next_fence=1;
bool fail_fence=false;
bool fail_storage=false, fail_mapping=false, fail_mutable=false;
GLenum allocation_error=0;
GLuint next_buffer=100;
unsigned storage_calls=0, map_calls=0;
struct { float mGLVersion=4.6f; } gGLManager;
GLenum glGetError() { auto result=allocation_error; allocation_error=0; return result; }
void glGenBuffers(unsigned count, GLuint* names) {
    while(count--) { *names=next_buffer++; buffers[*names++]={}; }
}
void glDeleteBuffers(unsigned count, const GLuint* names) {
    while(count--) { immutable.erase(*names); buffers.erase(*names++); }
}
void bufferStorage(GLenum, size_t size, const void*, GLbitfield flags) {
    ++storage_calls;
    assert(size==16 && flags==(GL_MAP_READ_BIT|GL_MAP_PERSISTENT_BIT|GL_MAP_COHERENT_BIT));
    if(fail_storage) { allocation_error=1000; return; }
    immutable.insert(write_binding);
}
void* mapBufferRange(GLenum, size_t offset, size_t size, GLbitfield flags) {
    ++map_calls;
    assert(offset==0 && size==16 && immutable.count(write_binding));
    assert(flags==(GL_MAP_READ_BIT|GL_MAP_PERSISTENT_BIT|GL_MAP_COHERENT_BIT));
    if(fail_mapping) { allocation_error=1001; return nullptr; }
    return buffers.at(write_binding).data();
}
auto glBufferStorage=&bufferStorage;
auto glMapBufferRange=&mapBufferRange;
void glBufferData(GLenum, size_t size, const void*, GLenum) {
    assert(size==16 && !immutable.count(write_binding));
    if(fail_mutable) allocation_error=1002;
}
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
        struct Readback { GLuint buffer=0; GLsync fence=nullptr; const U32* mapped=nullptr; bool mouselook=false; };
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
    static bool allocateReadback(Resources::Readback&);
    static void releaseReadbacks();
    static void recordCaptureStats(U32 nodes,U32 depth,bool camera) { samples.push_back({nodes,depth,U32(camera)}); }
    static void growNodePool(U32 demand) { if(demand>sResources.capacity) sResources.capacity=demand; }
};
FSExactOIT::Resources FSExactOIT::sResources;
std::vector<std::array<U32,3>> FSExactOIT::samples;
'''

CHECKS = r'''
void checkRing(bool mapped) {
    FSExactOIT::sResources=FSExactOIT::Resources{};
    FSExactOIT::samples.clear(); buffers.clear(); fences.clear(); immutable.clear();
    copies=reads=polls=0; fail_fence=false;
    gGLManager.mGLVersion=mapped ? 4.6f : 4.3f;
    auto& r=FSExactOIT::sResources;
    for(auto& sample : r.readbacks) {
        assert(FSExactOIT::allocateReadback(sample));
        assert(bool(sample.mapped)==mapped);
    }
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
    assert(reads==(mapped ? 0u : 2u) && r.readbackPending==1 && r.capacity==32);
    assert((FSExactOIT::samples==std::vector<std::array<U32,3>>{{10,2,0},{11,3,1}}));
    assert(r.overflowCount==2);
    fences[r.readbacks[2].fence]=GL_WAIT_FAILED;
    FSExactOIT::collectStats(); // failed fence drops its sample without reading
    assert(reads==(mapped ? 0u : 2u) && r.readbackPending==0 && fences.empty());
    FSExactOIT::queueStats(false); // wrapped slot can now be reused
    fences[r.readbacks[0].fence]=GL_ALREADY_SIGNALED;
    FSExactOIT::collectStats();
    assert(reads==(mapped ? 0u : 3u) && r.capacity==999 && r.overflowCount==3);
    fail_fence=true;
    FSExactOIT::queueStats(true);
    assert(r.readbackPending==0);
    FSExactOIT::collectStats();
    assert(reads==(mapped ? 0u : 3u));
    fail_fence=false;
    FSExactOIT::queueStats(false); // teardown with a pending copy/fence
    FSExactOIT::releaseReadbacks();
    assert(fences.empty() && immutable.empty());
    for(const auto& sample : r.readbacks) assert(!sample.buffer && !sample.fence && !sample.mapped);
}
int main() {
    checkRing(false); checkRing(true);
    for(int failure=0; failure<4; ++failure) {
        FSExactOIT::Resources::Readback sample;
        fail_storage=failure==0;
        fail_mapping=failure>=1;
        fail_mutable=failure==2;
        if(failure==3) glBufferStorage=nullptr;
        const auto old_storage=storage_calls;
        assert(FSExactOIT::allocateReadback(sample)==!fail_mutable);
        assert(!sample.mapped && !immutable.count(sample.buffer));
        assert(glGetError()==GL_NO_ERROR);
        if(failure==3) assert(storage_calls==old_storage);
        glDeleteBuffers(1, &sample.buffer);
    }
}
'''


def method(source, name):
    prefix = "bool" if name == "allocateReadback" else "void"
    start = source.index(f"{prefix} FSExactOIT::{name}(")
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
        release = source.index("for (auto& sample : sResources.readbacks)", source.index("void FSExactOIT::releaseResources(bool"))
        release_end = source.index("    sResources.commands = 0;", release)
        cleanup = "void FSExactOIT::releaseReadbacks() {\n" + source[release:release_end] + "}\n"
        cpp.write_text(STUBS + method(source, "allocateReadback") + method(source, "collectStats") +
                       method(source, "queueStats") + cleanup + CHECKS)
        subprocess.run([compiler, "-std=c++17", str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("Passed production readback ring: mapped/4.3 paths, allocation/mapping failures, busy/full, FIFO/camera identity, historical capacity, wraparound, failed fences and teardown")


if __name__ == "__main__":
    main()
