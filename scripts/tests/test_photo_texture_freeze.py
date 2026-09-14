"""Exercise production texture animation and timer pause methods with a fake clock.

Run with Python and g++ on PATH. Tests flipbooks and smooth animation resuming
after a long photo freeze without advancing by the time spent frozen.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def method(file, signature):
    source = (ROOT / file).read_text()
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2]


harness = r'''
#include <algorithm>
#include <cassert>
#include <cmath>
using F32 = float;
using S32 = int;
#define llmax std::max
#define llmin std::min
#define llfloor std::floor
#define ll_round std::round
bool frozen = false;
int gSavedSettings;
template<class T> struct LLCachedControl {
    LLCachedControl(int&, const char*, bool) {}
    operator bool() const { return frozen; }
};
struct LLFrameTimer {
    static double sFrameTime;
    double mStartTime = sFrameTime;
    bool mStarted = true;
    void pause();
    void unpause();
    F32 getElapsedTimeF32() const {
        return mStarted ? F32(sFrameTime-mStartTime) : F32(mStartTime);
    }
    F32 getElapsedTimeAndResetF32() {
        F32 elapsed = F32(sFrameTime-mStartTime);
        mStartTime=sFrameTime;
        return elapsed;
    }
};
double LLFrameTimer::sFrameTime = 0;
struct LLViewerTextureAnim {
    enum { ON=1, LOOP=2, REVERSE=4, PING_PONG=8, SMOOTH=16,
           ROTATE=32, SCALE=64, TRANSLATE=128 };
    int mMode=ON|LOOP, mSizeX=4, mSizeY=4;
    F32 mLength=0, mRate=2, mStart=0, mLastTime=0, mLastFrame=-1;
    F32 mRot=0, mScaleS=1, mScaleT=1, mOffS=0, mOffT=0;
    LLFrameTimer mTimer;
    S32 animateTextures(F32&, F32&, F32&, F32&, F32&);
};
'''
harness += method('indra/llcommon/llframetimer.cpp', 'void LLFrameTimer::pause()')
harness += method('indra/llcommon/llframetimer.cpp', 'void LLFrameTimer::unpause()')
harness += method('indra/newview/llviewertextureanim.cpp', 'S32 LLViewerTextureAnim::animateTextures(')
harness += r'''
int main() {
    for (int mode : {0, int(LLViewerTextureAnim::SMOOTH),
                    LLViewerTextureAnim::SMOOTH|LLViewerTextureAnim::ROTATE,
                    LLViewerTextureAnim::SMOOTH|LLViewerTextureAnim::SCALE}) {
        LLViewerTextureAnim a;
        a.mMode |= mode;
        F32 s=0,t=0,ss=1,st=1,r=0;
        a.animateTextures(s,t,ss,st,r);
        LLFrameTimer::sFrameTime += 1.5;
        assert(a.animateTextures(s,t,ss,st,r));
        const F32 frame=a.mLastFrame;
        frozen=true;
        assert(!a.animateTextures(s,t,ss,st,r));
        LLFrameTimer::sFrameTime += 120;
        assert(!a.animateTextures(s,t,ss,st,r));
        assert(a.mLastFrame==frame);
        frozen=false;
        assert(!a.animateTextures(s,t,ss,st,r));
        assert(a.mLastFrame==frame);
        LLFrameTimer::sFrameTime += .5;
        assert(a.animateTextures(s,t,ss,st,r));
        assert(std::abs(a.mLastFrame-(frame+1))<.001);
    }
}
'''
with tempfile.TemporaryDirectory(prefix='photo-texture-freeze-') as temp:
    source = Path(temp) / 'test.cpp'
    binary = Path(temp) / 'test.exe'
    source.write_text(harness)
    subprocess.run(['g++', '-std=c++17', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print('PASS: flipbook, smooth, rotation and scale animations hold and resume without catch-up')
