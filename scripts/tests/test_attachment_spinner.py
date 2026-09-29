"""Exercise production pending-state and spinner drawing code with small API stubs.

Run: python scripts/tests/test_attachment_spinner.py (requires g++ on PATH).
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def function(path, signature):
    source = (ROOT / path).read_text()
    start = source.index(signature)
    opening = source.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def main():
    pending = function('indra/newview/llattachmentsmgr.cpp',
                       'bool LLAttachmentsMgr::isAttachmentPending(')
    draw = function('indra/llui/llloadingindicator.cpp',
                    'void LLLoadingIndicator::drawSmall(')
    code = r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include <map>
#include <vector>
using F32 = float; using F64 = double; using S32 = int; using LLUUID = int;
constexpr F32 MAX_ATTACHMENT_REQUEST_LIFETIME = 30.f;
constexpr F32 F_PI_BY_TWO = 1.570796327f, F_TWO_PI = 6.283185307f;
template<class T> T llmin(T a, T b) { return std::min(a, b); }
struct Timer { F32 age = 0; F32 getElapsedTimeF32() const { return age; } };
struct Inventory {
    std::map<int,int> links;
    int getLinkedItemID(int id) const {
        auto it = links.find(id); return it == links.end() ? id : it->second;
    }
} gInventory;
struct LLAttachmentsMgr {
    std::map<int,Timer> mAttachmentRequests;
    bool isAttachmentPending(const LLUUID&) const;
};
struct LLRect {
    int mLeft, mTop, mRight, mBottom;
    int getWidth() const { return mRight-mLeft; }
    int getHeight() const { return mTop-mBottom; }
};
struct LLFrameTimer { static double now; static double getElapsedSeconds() { return now; } };
double LLFrameTimer::now = 0;
struct Circle { float x, y, r, brightness, alpha; };
std::vector<Circle> circles;
struct GL {
    float brightness = 0, alpha = 0;
    void color4f(float r, float, float, float a) { brightness = r; alpha = a; }
} gGL;
void gl_circle_2d(float x, float y, float r, int, bool) {
    circles.push_back({x,y,r,gGL.brightness,gGL.alpha});
}
struct LLLoadingIndicator { static void drawSmall(const LLRect&, F32); };
''' + pending + '\n' + draw + r'''
int main() {
    LLAttachmentsMgr manager;
    gInventory.links[101] = 1;
    assert(!manager.isAttachmentPending(1));
    manager.mAttachmentRequests[1].age = 0; // queued, before network send
    assert(manager.isAttachmentPending(1) && manager.isAttachmentPending(101));
    assert(!manager.isAttachmentPending(2));
    manager.mAttachmentRequests[1].age = 6; // beyond duplicate-request grace period
    assert(manager.isAttachmentPending(101));
    manager.mAttachmentRequests[1].age = 30.01f;
    assert(!manager.isAttachmentPending(1));
    manager.mAttachmentRequests[1].age = 0; // retried
    assert(manager.isAttachmentPending(101));
    manager.mAttachmentRequests.erase(1); // arrival clears request
    assert(!manager.isAttachmentPending(1) && !manager.isAttachmentPending(101));
    for (int size : {16,20}) {
        for (int frame = 0; frame < 8; ++frame) {
            circles.clear();
            LLFrameTimer::now = frame * 0.1 + 0.01;
            LLLoadingIndicator::drawSmall({3,7+size,3+size,7}, 0.4f);
            assert(circles.size() == 9); // backing and eight dots
            assert(std::abs(circles[frame+1].brightness - 1.f) < 0.001f);
            for (auto c : circles) {
                assert(c.x-c.r >= 3 && c.x+c.r <= 3+size);
                assert(c.y-c.r >= 7 && c.y+c.r <= 7+size);
                assert(c.alpha > 0 && c.alpha <= 0.4f);
            }
        }
    }
    circles.clear();
    LLLoadingIndicator::drawSmall({0,0,0,0}, 1.f);
    assert(circles.empty());
}
'''
    with tempfile.TemporaryDirectory(prefix='attachment-spinner-') as directory:
        source = Path(directory) / 'check.cpp'
        executable = Path(directory) / 'check.exe'
        source.write_text(code)
        subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                        str(source), '-o', str(executable)], check=True)
        subprocess.run([str(executable)], check=True)
    print('Attachment state, link resolution, expiry, animation, and 16/20px bounds: PASS')


if __name__ == '__main__':
    main()
