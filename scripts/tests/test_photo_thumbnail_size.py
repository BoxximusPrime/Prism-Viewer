"""Exercise production thumbnail sizing against minimized and degenerate rectangles."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root/'indra/newview/llsnapshotlivepreview.cpp').read_text()
start = source.index('bool LLSnapshotLivePreview::setThumbnailImageSize()')
method = source[start:source.index('\n}', start)+2]
code = r'''
#include <cassert>
#include <cmath>
#include <initializer_list>
using S32=int;
using F32=float;
int ll_round(float v) { return int(std::round(v)); }
struct Rect {
    int w=555,h=175;
    int getWidth() { return w; }
    int getHeight() { return h; }
    void set(int,int,int,int) {}
};
struct Image { int getWidth(){return 640;} int getHeight(){return 480;} };
struct Window {
    int w=3440,h=1369;
    int getWindowWidthRaw(){return w;}
    int getWindowHeightRaw(){return h;}
} window;
Window* gViewerWindow=&window;
struct LLSnapshotLivePreview {
    bool mThumbnailSubsampled=false,mKeepAspectRatio=true;
    Image* mPreviewImage=nullptr;
    Rect mThumbnailPlaceholderRect,mPreviewRect;
    int mThumbnailWidth=555,mThumbnailHeight=175;
    int getWidth(){return 640;} int getHeight(){return 480;}
    bool setThumbnailImageSize();
};
'''+method+r'''
int main() {
    LLSnapshotLivePreview p;
    assert(p.setThumbnailImageSize());
    for(auto size : {Rect{0,175}, Rect{555,0}, Rect{-45,-401}, Rect{1,175}}) {
        p.mThumbnailPlaceholderRect=size;
        assert(!p.setThumbnailImageSize());
    }
    p.mThumbnailPlaceholderRect={555,175};
    window.h=0;
    assert(!p.setThumbnailImageSize());
    window.h=1369;
    assert(p.setThumbnailImageSize());
    assert(p.mThumbnailWidth>0 && p.mThumbnailHeight>0);
    p.mThumbnailSubsampled=true;
    assert(!p.setThumbnailImageSize());
    Image image; p.mPreviewImage=&image;
    assert(p.setThumbnailImageSize());
}
'''
with tempfile.TemporaryDirectory(prefix='photo-thumbnail-') as directory:
    cpp=Path(directory)/'test.cpp';exe=Path(directory)/'test.exe'
    cpp.write_text(code)
    subprocess.run(['g++','-std=c++17',str(cpp),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('PASS: minimized, zero, thin, missing-image and restored thumbnail sizing')
