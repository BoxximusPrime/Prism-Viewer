"""Replay native combo/container wheel handlers with the review's XUI setting."""
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
combo = (ROOT / "indra/llui/llcombobox.cpp").read_text(encoding="utf-8")
container = (ROOT / "indra/llui/llscrollcontainer.cpp").read_text(encoding="utf-8")
row = ET.parse(ROOT / "indra/newview/skins/default/xui/en/panel_inventory_llm_sort_row.xml")
allow_wheel = row.find("combo_box[@name='destination']").get("allow_scroll_wheel")
assert allow_wheel == "false"
assert 'allow_scroll_wheel("allow_scroll_wheel", true)' in combo
assert 'mAllowScrollWheel(p.allow_scroll_wheel)' in combo


def function(source, signature):
    start = source.index(signature)
    return source[start:source.index("\n}\n", start) + 3]


program = r'''
#include <cassert>
#include <iostream>
using S32 = int;
struct LLScrollbar {
    bool visible=true,enabled=true,selected=true; int position=0;
    bool getVisible()const{return visible;} bool getEnabled()const{return enabled;}
    bool getFirstSelected()const{return selected;}
    bool handleScrollWheel(int,int,int clicks){position+=clicks;return true;}
};
struct LLComboBox {
    LLScrollbar list; LLScrollbar* mList=&list;
    bool mAllowScrollWheel=true,mAllowTextEntry=false; int index=2,commits=0;
    LLComboBox(){list.visible=false;}
    int getCurrentIndex()const{return index;}
    bool selectNextItem(){if(index==4)return false;++index;return true;}
    bool selectPrevItem(){if(index==0)return false;--index;return true;}
    void prearrangeList(){} void onCommit(){++commits;}
    bool handleScrollWheel(S32,S32,S32);
};
struct LLUICtrl {
    LLComboBox child;
    bool handleScrollWheel(int x,int y,int clicks){return child.handleScrollWheel(x,y,clicks);}
};
struct LLScrollContainer : LLUICtrl {
    enum {VERTICAL,HORIZONTAL};
    LLScrollbar vertical,horizontal; LLScrollbar* mScrollbar[2]={&vertical,&horizontal};
    int updates=0; void updateScroll(){++updates;}
    bool handleScrollWheel(S32,S32,S32);
};
''' + function(combo, "bool LLComboBox::handleScrollWheel(") + function(
    container, "bool LLScrollContainer::handleScrollWheel(") + r'''
int main() {
    LLScrollContainer review;
    review.child.mAllowScrollWheel=ALLOW_WHEEL;
    // Hovering the closed destination scrolls the review; it never commits a value.
    for(int clicks:{1,-1,3,-3}) {
        const int before=review.vertical.position;
        assert(review.handleScrollWheel(10,10,clicks));
        assert(review.child.index==2&&review.child.commits==0);
        assert(review.vertical.position==before+clicks);
    }
    assert(review.updates==4);
    // Opening the dropdown permits scrolling its choices without selecting one.
    review.child.list.visible=true;
    for(int clicks:{2,-2}) {
        const int before=review.child.list.position;
        assert(review.handleScrollWheel(10,10,clicks));
        assert(review.child.list.position==before+clicks);
        assert(review.child.index==2&&review.child.commits==0&&review.updates==4);
    }
    // Other combos retain the default native wheel behavior.
    LLScrollContainer ordinary;
    assert(ordinary.handleScrollWheel(10,10,1));
    assert(ordinary.child.index==3&&ordinary.child.commits==1&&ordinary.updates==0);
    assert(ordinary.handleScrollWheel(10,10,-1));
    assert(ordinary.child.index==2&&ordinary.child.commits==2&&ordinary.updates==0);
    std::cout<<"8 native wheel routing / selection checks passed\n";
}
'''
program = program.replace("ALLOW_WHEEL", allow_wheel)
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / "wheel.cpp"
    exe = Path(directory) / "wheel.exe"
    cpp.write_text(program, encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
