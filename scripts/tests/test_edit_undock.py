"""Exercise the production Edit floater dock transition against changed window bounds."""
from pathlib import Path
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[2] / "indra/newview/llfloatertools.cpp").read_text()
start = source.index("void LLFloaterTools::setEditDocked(bool docked)")
opening = source.index("{", start)
depth, end = 1, opening + 1
while depth:
    depth += (source[end] == "{") - (source[end] == "}")
    end += 1
transition = source[start:end]

harness = r"""
#include <algorithm>
#include <cassert>
#include <string>
struct LLRect {
    int mLeft=0,mTop=0,mRight=0,mBottom=0;
    LLRect()=default;
    LLRect(int l,int t,int r,int b):mLeft(l),mTop(t),mRight(r),mBottom(b){}
    int getWidth() const{return mRight-mLeft;}
    int getHeight() const{return mTop-mBottom;}
};
struct LLFloaterTools;
struct View {LLFloaterTools* child=nullptr;void addChild(LLFloaterTools* p){child=p;}};
struct Root {View dock;View* getChildView(const char*){return &dock;}};
struct ViewerWindow {Root root;Root* getRootView(){return &root;}} viewer;
ViewerWindow* gViewerWindow=&viewer;
struct FloaterView:View {
    int width=1920,height=1080,adjustments=0;
    void adjustToFitScreen(LLFloaterTools* floater,bool allow_partial);
} floaters;
FloaterView* gFloaterView=&floaters;
struct SavedSettings {bool getBOOL(const char*){return false;}} gSavedSettings;
struct LLResizeBar {enum {RIGHT=0};bool visible=true,enabled=true;
    void setVisible(bool v){visible=v;}void setEnabled(bool v){enabled=v;}};
struct LLFloaterTools {
    bool mEditDocked=false,background=true,can_drag=true,can_minimize=true;
    int stored=0,min_width=0,min_height=0;
    LLRect rect,mFloatingRect,stored_rect;
    std::string mRectControl="EditRect",mFloatingRectControl;
    std::string mPosXControl="EditX",mFloatingPosXControl;
    std::string mPosYControl="EditY",mFloatingPosYControl;
    LLResizeBar right;LLResizeBar* mResizeBar[1]{&right};
    void setMinimized(bool){}
    void storeRectControl(){if(!mRectControl.empty()){stored_rect=rect;++stored;}}
    LLRect getRect() const{return rect;}
    void setBackgroundVisible(bool v){background=v;}
    void setCanDrag(bool v){can_drag=v;}
    void setCanMinimize(bool v){can_minimize=v;}
    void enableResizeCtrls(bool,bool,bool){}
    void setResizeLimits(int w,int h){min_width=w;min_height=h;}
    void setShape(LLRect r){rect=r;}
    void setEditDocked(bool);
};
void FloaterView::adjustToFitScreen(LLFloaterTools* floater,bool allow_partial){
    assert(!allow_partial && child==floater);
    ++adjustments;
    LLRect r=floater->rect;
    // LLFloaterView first shrinks resizable windows to the visible area.
    r.mRight=r.mLeft+std::min(r.getWidth(),width);
    r.mBottom=r.mTop-std::min(r.getHeight(),height);
    r.mLeft=std::clamp(r.mLeft,0,width-r.getWidth());
    r.mRight=r.mLeft+std::min(floater->rect.getWidth(),width);
    r.mBottom=std::clamp(r.mBottom,0,height-r.getHeight());
    r.mTop=r.mBottom+std::min(floater->rect.getHeight(),height);
    floater->setShape(r);
}
""" + transition + r"""
void check(LLFloaterTools& f){
    assert(f.rect.mLeft>=0 && f.rect.mRight<=floaters.width);
    assert(f.rect.mBottom>=0 && f.rect.mTop<=floaters.height);
    assert(f.mFloatingRect.mLeft==f.rect.mLeft && f.mFloatingRect.mTop==f.rect.mTop);
    assert(f.stored_rect.mLeft==f.rect.mLeft && f.stored_rect.mTop==f.rect.mTop);
    assert(f.mRectControl=="EditRect" && f.mFloatingRectControl.empty());
    assert(f.background && f.can_drag && f.can_minimize && f.right.visible);
}
int main(){
    LLFloaterTools f;
    f.rect={1500,1050,2060,130};
    f.setEditDocked(true);
    assert(f.mEditDocked && f.stored==1 && f.stored_rect.mLeft==1500);
    assert(f.mRectControl.empty() && f.mFloatingRectControl=="EditRect");
    f.rect={1360,720,1920,0}; // dock geometry must not become the floating position
    floaters.width=1280;floaters.height=720;
    f.setEditDocked(false);check(f);
    assert(floaters.adjustments==1 && f.stored==2);
    f.rect={-240,780,320,-140};
    f.setEditDocked(true);
    f.rect={720,720,1280,0};
    f.setEditDocked(false);check(f);
    assert(floaters.adjustments==2 && f.stored==4);
}
"""
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / "edit_undock.cpp"
    exe = Path(directory) / "edit_undock.exe"
    cpp.write_text(harness)
    subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("Edit undock: saved floating rect restored, fitted onscreen, and persisted after window changes.")
