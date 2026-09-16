"""Replay the production draw/reshape functions with a large hidden inventory tree.

This measures UI work counts, not rendering FPS. --measure SOURCE can compare an
older implementation without enforcing the regression assertions.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
measure = len(sys.argv) == 3 and sys.argv[1] == "--measure"
source = Path(sys.argv[2]) if measure else ROOT / "indra/newview/llfloaterinventoryllmsort.cpp"

def function(text, signature):
    start = text.index(signature)
    return text[start:text.index("\n}\n", start) + 3]

code = source.read_text(encoding="utf-8")
view = (ROOT / "indra/llui/llview.cpp").read_text(encoding="utf-8")
counts_start = code.index("    size_t attention = 0, reviewed = 0, visible = 0")
row_counts = code[counts_start:code.index("    const S32 width", counts_start)]
program = r'''
#include <algorithm>
#include <cassert>
#include <iostream>
#include <memory>
#include <string>
#include <string_view>
#include <vector>
using S32 = int;
static size_t visits=0;
#define LL_PROFILE_ZONE_SCOPED_CATEGORY_UI ++visits
#define llassert assert
struct Rect { int w=1120,h=880; int getWidth()const{return w;} int getHeight()const{return h;} };
struct LLView {
    std::string name; std::vector<LLView*> mChildList; Rect rect;
    virtual ~LLView()=default;
    const std::string& getName()const{return name;}
    const Rect& getRect()const{return rect;}
    LLView* findChildView(std::string_view,bool recurse=true)const;
    LLView* getChildView(std::string_view n){auto* p=findChildView(n);assert(p);return p;}
    void setVisible(bool){} void setEnabled(bool){}
};
struct LLFloater : LLView {
    int draws=0;
    virtual void draw(){++draws;}
    virtual void reshape(S32 w,S32 h,bool=true){rect={w,h};}
};
struct LLTimer { static double getTotalSeconds(){return 100;} };
struct UUID {bool notNull()const{return true;}};
class LLFloaterInventoryLLMSort : public LLFloater {public:
    enum class State{Waiting,Ready,NewFolder,Unsure,Error,Creating,Moved,Skipped}; struct Row{State state=State::Ready;};
    std::vector<Row> mRows=std::vector<Row>(13); UUID mRoot;
    bool mLoading=false,mDirty=true,mSorting=false,mCreating=false,finishLoading=false;
    bool mAutoSort=false,mAttention=false; int starts=0; size_t visibleRows=0,reviewedRows=0;
    double mLoadStarted=100; int rebuilds=0;
    // Widget construction/rendering is outside this frame-scheduling regression.
    void renderRows(){mDirty=false;++rebuilds;
''' + row_counts + r'''
        visibleRows=visible;reviewedRows=reviewed;
    }
    void startSort(){++starts;}
    void loadCategories(){if(finishLoading){mLoading=false;mDirty=true;}}
    void status(const std::string&){}
    void draw()override; void reshape(S32,S32,bool=true)override;
};
''' + function(view, "LLView* LLView::findChildView(") + function(code, "void LLFloaterInventoryLLMSort::draw(") + function(code, "void LLFloaterInventoryLLMSort::reshape(") + r'''
int main(int argc,char**) {
    const bool measure=argc>1;
    LLFloaterInventoryLLMSort f;
    LLView picker,review,sort,stop,change;picker.name="root_picker";review.name="review";
    sort.name="sort";stop.name="stop";change.name="change_root";
    // XUI inserts newer children first: the hidden picker precedes the review.
    f.mChildList={&picker,&review};review.mChildList={&sort,&stop,&change};
    std::vector<LLView> inventory(65000);
    for(auto& entry:inventory){entry.name="inventory_entry";picker.mChildList.push_back(&entry);}
    f.draw();visits=0;const int initial=f.rebuilds;
    for(int frame=0;frame<120;++frame)f.draw();
    std::cout<<"120 idle frames: "<<visits<<" recursive view visits, "<<f.rebuilds-initial<<" row rebuilds\n";
    if(!measure){assert(visits==0);assert(f.rebuilds==initial);}
    visits=0;const int before=f.rebuilds;
    for(int frame=0;frame<120;++frame){f.reshape(1120,880);f.draw();}
    std::cout<<"120 same-size screen-fit frames: "<<visits<<" recursive view visits, "<<f.rebuilds-before<<" row rebuilds\n";
    if(!measure){assert(visits==0);assert(f.rebuilds==before);}
    if(measure)return 0;
    f.reshape(1200,880);assert(f.mDirty);f.draw();assert(f.rebuilds==before+1);
    f.reshape(1200,960);assert(f.mDirty);f.draw();assert(f.rebuilds==before+2);
    f.mDirty=true;f.draw();assert(f.rebuilds==before+3); // New suggestion/filter/approval.
    f.mLoading=true;f.finishLoading=true;f.draw();assert(!f.mLoading&&f.rebuilds==before+4);
    f.mLoading=true;f.finishLoading=false;f.mLoadStarted=0;f.draw();
    assert(!f.mLoading&&f.rebuilds==before+5); // Loading timeout updates controls.
    f.draw();assert(f.rebuilds==before+5);
    std::cout<<"Idle, unchanged size, real resizes, state changes, loading completion and timeout passed\n";
    // Auto-submit exactly once, including roots that finish loading later.
    f.mAutoSort=true;f.draw();assert(f.starts==1&&!f.mAutoSort);
    for(int frame=0;frame<120;++frame)f.draw();assert(f.starts==1);
    f.mAutoSort=true;f.mLoading=true;f.mLoadStarted=100;f.draw();
    assert(f.starts==1&&f.mAutoSort);
    f.finishLoading=true;f.draw();assert(f.starts==2&&!f.mAutoSort);
    f.mAutoSort=true;f.mLoading=true;f.finishLoading=false;f.mLoadStarted=0;f.draw();
    assert(f.starts==2&&!f.mAutoSort); // Timeout must not cause an automatic retry loop.
    // Approved rows disappear from All and attention counts; remaining indices stay stable.
    f.mRows={{LLFloaterInventoryLLMSort::State::Moved},{LLFloaterInventoryLLMSort::State::Ready},
             {LLFloaterInventoryLLMSort::State::NewFolder},{LLFloaterInventoryLLMSort::State::Error},
             {LLFloaterInventoryLLMSort::State::Skipped}};
    f.renderRows();assert(f.visibleRows==4&&f.reviewedRows==2&&f.mRows.size()==5);
    f.mAttention=true;f.renderRows();assert(f.visibleRows==2&&f.reviewedRows==2);
    f.mRows.assign(13,{LLFloaterInventoryLLMSort::State::Moved});f.mAttention=false;
    f.renderRows();assert(f.visibleRows==0&&f.reviewedRows==13);
    std::cout<<"Auto-submit, delayed loading, timeout, and approved-row visibility checks passed\n";
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / "idle.cpp"
    exe = Path(directory) / "idle.exe"
    cpp.write_text(program, encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", "-O2", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)] + (["measure"] if measure else []), check=True)
