"""Exercise production spinner handlers and clipboard permissions; requires g++."""
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]


def function(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


spin = (ROOT / "indra/llui/llspinctrl.cpp").read_text()
panel = (ROOT / "indra/newview/llpanelobject.cpp").read_text()
harness = r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdlib>
#include <functional>
#include <string>
using F32=float; using F64=double; using S32=int; using MASK=int; using KEY=int;
constexpr int MASK_NONE=0, MASK_SHIFT=1, MASK_CONTROL=2, MASK_ALT=4;
constexpr int KEY_ESCAPE=27, KEY_UP=38, KEY_DOWN=40, LL_PCODE_VOLUME=9;
template<class T> T llmin(T a,T b) {return std::min(a,b);}
template<class T> T llmax(T a,T b) {return std::max(a,b);}
double ll_round(double v) {return std::floor(v+0.5);}
struct LLSD {
    float number=0; std::string text;
    LLSD()=default; LLSD(float v):number(v){} LLSD(const char* s):text(s){}
    float asReal() const {return number;} std::string asString() const {return text;}
    bool isMap() const {return false;} int size() const {return 0;}
};
struct LLLocale {enum {USER_LOCALE}; LLLocale(int) {}};
struct Keyboard {MASK mask=0; MASK currentMask(bool) {return mask;}} keyboard;
Keyboard* gKeyboard=&keyboard;
struct LLLineEditor {
    std::string text="2"; bool focus=true;
    std::string getText() {return text;} bool hasFocus() {return focus;}
    void setFocus(bool v) {focus=v;} void resetScrollPosition() {}
    static bool postvalidateFloat(const std::string& s) {
        char* end; std::strtof(s.c_str(),&end); return !s.empty() && *end=='\0';
    }
};
struct LLSpinCtrl {
    float value=2, mIncrement=1, mMinValue=-100, mMaxValue=100;
    int mPrecision=3, commits=0, invalid=0; bool enabled=true;
    LLLineEditor editor; LLLineEditor* mEditor=&editor;
    std::function<bool(LLSpinCtrl*,float)>* mValidateSignal=nullptr;
    bool getEnabled() const {return enabled;} LLSD getValue() {return value;}
    void setValue(float v) {value=v;} void updateEditor() {editor.text=std::to_string(value);}
    void reportInvalidData() {++invalid;} void onCommit() {++commits;}
    float getModifiedIncrement() const;
    void onUpBtn(const LLSD&); void onDownBtn(const LLSD&);
    bool handleScrollWheel(S32,S32,S32); bool handleKeyHere(KEY,MASK);
};
struct Selection {int count=1; int getObjectCount(){return count;}} selection;
struct LLSelectMgr {
    bool move=true, modify=true, volume=true;
    static LLSelectMgr* getInstance(){static LLSelectMgr mgr; return &mgr;}
    Selection* getSelection(){return &selection;}
    bool selectionAllPCode(int){return volume;}
    void selectGetEditMoveLinksetPermissions(bool& a,bool& b){a=move;b=modify;}
};
struct LLPanelObject {
    LLSpinCtrl pos, size, rot;
    LLSpinCtrl *mCtrlPosX=&pos, *mCtrlScaleX=&size, *mCtrlRotX=&rot;
    bool mHasClipboardPos=false, mHasClipboardSize=false, mHasClipboardRot=false;
    LLSD mClipboardParams;
    bool menuEnableItem(const LLSD&);
};
'''
for signature in ["F32 clamp_precision(", "F32 LLSpinCtrl::getModifiedIncrement(",
                  "void LLSpinCtrl::onUpBtn(", "void LLSpinCtrl::onDownBtn(",
                  "bool LLSpinCtrl::handleScrollWheel(", "bool LLSpinCtrl::handleKeyHere("]:
    harness += function(spin, signature) + "\n"
harness += function(panel, "bool LLPanelObject::menuEnableItem(")
harness += r'''
void near(float actual,float expected){assert(std::abs(actual-expected)<0.00001f);}
int main(){
    for(int mask=0;mask<8;++mask){
        keyboard.mask=mask;
        float step=(mask&MASK_ALT)?10.f:(mask&MASK_CONTROL)?.1f:(mask&MASK_SHIFT)?.01f:1.f;
        LLSpinCtrl s; s.handleScrollWheel(0,0,-2); near(s.value,2+2*step);
        s.handleScrollWheel(0,0,1); near(s.value,2+step);
        s.handleKeyHere(KEY_DOWN,mask); near(s.value,2); assert(s.commits==4);
        s.handleKeyHere(KEY_UP,mask); near(s.value,2+step);
        near(s.mIncrement,1); // Modifiers never change the configured base step.
    }
    LLSpinCtrl fine; keyboard.mask=MASK_SHIFT; fine.mIncrement=.01f;
    fine.onUpBtn({}); near(fine.value,2.001f);
    LLSpinCtrl integer; integer.mPrecision=0; integer.onDownBtn({}); near(integer.value,1);
    LLSpinCtrl bounds; keyboard.mask=MASK_ALT; bounds.mMaxValue=3;
    bounds.onUpBtn({}); near(bounds.value,3); bounds.mMinValue=1;
    bounds.onDownBtn({}); near(bounds.value,1);
    LLSpinCtrl disabled; disabled.enabled=false; disabled.handleScrollWheel(0,0,-1);
    near(disabled.value,2); assert(disabled.commits==0);
    LLSpinCtrl invalid; invalid.editor.text="invalid"; invalid.onUpBtn({});
    near(invalid.value,2); assert(invalid.commits==0);
    std::function<bool(LLSpinCtrl*,float)> reject=[](LLSpinCtrl*,float){return false;};
    LLSpinCtrl rejected; rejected.mValidateSignal=&reject; rejected.onUpBtn({});
    near(rejected.value,2); assert(rejected.commits==0 && rejected.invalid==1);
    gKeyboard=nullptr; near(rejected.getModifiedIncrement(),1); gKeyboard=&keyboard;
    LLPanelObject p;
    assert(p.menuEnableItem("pos_copy") && !p.menuEnableItem("pos_paste"));
    p.mHasClipboardPos=true; assert(p.menuEnableItem("pos_paste"));
    assert(!p.menuEnableItem("size_paste") && !p.menuEnableItem("rot_paste"));
    p.mHasClipboardSize=p.mHasClipboardRot=true; assert(p.menuEnableItem("psr_paste"));
    p.pos.enabled=p.size.enabled=p.rot.enabled=false;
    for(const char* command:{"pos_copy","pos_paste","size_copy","size_paste","rot_copy","rot_paste"})
        assert(!p.menuEnableItem(command));
    LLSelectMgr::getInstance()->move=false; assert(!p.menuEnableItem("psr_paste"));
    LLSelectMgr::getInstance()->move=true; selection.count=2;
    assert(!p.menuEnableItem("psr_copy") && !p.menuEnableItem("psr_paste"));
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / "controls.cpp"
    exe = Path(directory) / "controls.exe"
    cpp.write_text(harness)
    subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

# Check the redesigned Object tab's relative layout and callback wiring.
xui = ROOT / "indra/newview/skins/default/xui/en"
root = ET.parse(xui / "floater_tools.xml").getroot()
tabs = root.find(".//tab_container[@name='Object Info Tabs']")
obj = tabs.find("panel[@name='Object']")
assert obj.get("width") == "536" and obj.get("height") == "620"
assert obj.get("left") == "0" and obj.get("top") == "0" and obj.get("follows") == "all"
scroll = obj.find("scroll_container[@name='object_scroll']")
assert scroll is not None and scroll.get("follows") == "all"

rects = {}
def collect_rects(parent, origin=(0, 0)):
    for child in parent:
        a = child.attrib
        if {"name", "left", "top", "width", "height"} <= a.keys():
            left, top = origin[0] + int(a["left"]), origin[1] + int(a["top"])
            rects[a["name"]] = (left, top, left + int(a["width"]), top + int(a["height"]))
            collect_rects(child, (left, top))
        else:
            collect_rects(child, origin)
collect_rects(obj)

for group, prefix in [("pos", "Pos"), ("size", "Scale"), ("rot", "Rot")]:
    fields = [rects[f"{prefix} {axis}"] for axis in "XYZ"]
    assert fields[0][0] < fields[1][0] < fields[2][0]
    assert len({field[1] for field in fields}) == 1
    assert all(fields[i][2] < fields[i + 1][0] for i in range(2))
    border = rects[f"{'size' if group == 'size' else 'position' if group == 'pos' else 'rotation'}_border"]
    assert all(border[0] < field[0] and field[2] < border[2] and
               border[1] < field[1] and field[3] < border[3] for field in fields)
    actions = [rects[f"copy_{group}"], rects[f"paste_{group}"], rects[f"clipboard_{group}_btn"]]
    assert all(actions[i][2] < actions[i + 1][0] for i in range(2))
    assert actions[-1][2] < border[2]
    for action in ["copy", "paste"]:
        callback = obj.find(f".//button[@name='{action}_{group}']/button.commit_callback")
        assert callback.get("function") == "PanelObject.menuDoToSelected"
        assert callback.get("parameter") == f"{group}_{action}"

shape = rects["shape_border"]
for name in ["cut begin", "cut end", "Scale 1", "Skew", "hole", "Twist Begin",
             "Twist End", "Taper Scale X", "Taper Scale Y", "Shear X", "Shear Y",
             "Path Limit Begin", "Path Limit End", "Taper X", "Taper Y",
             "Radius Offset", "Revolutions", "sculpt texture control",
             "sculpt mirror control", "sculpt invert control", "sculpt type control"]:
    rect = rects[name]
    assert shape[0] < rect[0] and rect[2] < shape[2]
    assert shape[1] < rect[1] and rect[3] < shape[3]
assert rects["sculpt texture control"][2] < rects["sculpt mirror control"][0]
for action in ("copy", "paste"):
    callback = obj.find(f".//button[@name='{action}_shape']/button.commit_callback")
    assert callback.get("function") == "PanelObject.menuDoToSelected"
    assert callback.get("parameter") == f"params_{action}"
print("Spinner modifiers, wheel/key routing, precision, bounds, validation, clipboard permissions and layout passed.")
