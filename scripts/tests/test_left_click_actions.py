"""Check the production blocker and linkset action resolution. Requires Python + g++."""
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[2]
source = (root / "indra/newview/lltoolpie.cpp").read_text()
constants = (root / "indra/llcommon/indra_constants.h").read_text()


def function(signature):
    start = source.index(signature)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


harness = r"""
#include <cassert>
#include <cstddef>
using U8=unsigned char; using MASK=int;
constexpr int MASK_NONE=0;
struct Settings {bool enabled=true;} gSavedSettings;
template<class T> struct LLCachedControl {
    Settings& settings;
    LLCachedControl(Settings& s,const char*,bool):settings(s){}
    operator bool() const{return settings.enabled;}
};
struct LLPrimitive {static bool isPrimitive(int code){return code==1;}};
struct LLViewerObject {
    U8 action=0; bool avatar=false,attachment=false,hud=false; int code=1;
    LLViewerObject* parent=nullptr;
    bool isAvatar(){return avatar;} bool isAttachment(){return attachment||hud;}
    bool isHUDAttachment(){return hud;} int getPCode(){return code;}
    U8 getClickAction(){return action;}
    LLViewerObject* getRootEdit(){return parent?parent:this;}
};
struct LLToolPie {
    bool useClickAction(MASK,LLViewerObject*,LLViewerObject*);
    bool shouldBlockClickAction(MASK,LLViewerObject*,LLViewerObject*);
};
"""
harness += "\n".join(re.findall(r"constexpr U8 CLICK_ACTION_\w+ = \d+;", constants)) + "\n"
for name in ("bool LLToolPie::useClickAction", "U8 final_click_action", "bool LLToolPie::shouldBlockClickAction"):
    harness += function(name) + "\n"
harness += r"""
int main(){
    LLToolPie tool; LLViewerObject object,parent;
    object.parent=&parent;
    int checks=0;
    for(bool enabled:{false,true})for(int child=0;child<=9;++child)for(int root=0;root<=9;++root){
        gSavedSettings.enabled=enabled; object.action=child;parent.action=root;
        for(int mask=0;mask<8;++mask){
            const int effective=child?child:(root==CLICK_ACTION_DISABLED?CLICK_ACTION_TOUCH:root);
            const bool actionable=(child&&child!=CLICK_ACTION_DISABLED)||(root&&root!=CLICK_ACTION_DISABLED);
            const bool expected=enabled&&mask==MASK_NONE&&actionable&&effective!=CLICK_ACTION_PAY&&effective!=CLICK_ACTION_TOUCH&&effective!=CLICK_ACTION_BUY;
            assert(tool.shouldBlockClickAction(mask,&object,&parent)==expected); ++checks;
        }
    }
    assert(checks==1600);
    gSavedSettings.enabled=true;
    parent.action=CLICK_ACTION_BUY;object.action=CLICK_ACTION_PAY;
    assert(!tool.shouldBlockClickAction(0,&object,&parent)); // explicit child Pay beats root Buy
    object.action=CLICK_ACTION_TOUCH;parent.action=CLICK_ACTION_PAY;
    assert(!tool.shouldBlockClickAction(0,&object,&parent)); // inherited Pay
    parent.action=CLICK_ACTION_TOUCH;assert(!tool.shouldBlockClickAction(0,&object,&parent));
    object.action=CLICK_ACTION_BUY;parent.action=CLICK_ACTION_PAY;
    assert(!tool.shouldBlockClickAction(0,&object,&parent)); // Buy is allowed on child prims
    object.avatar=true;assert(!tool.shouldBlockClickAction(0,&object,&parent));object.avatar=false;
    object.hud=true;assert(!tool.shouldBlockClickAction(0,&object,&parent));object.hud=false;
    object.attachment=true;assert(!tool.shouldBlockClickAction(0,&object,&parent));object.attachment=false;
    object.code=0;assert(!tool.shouldBlockClickAction(0,&object,&parent));
    assert(!tool.shouldBlockClickAction(0,nullptr,nullptr));
}
"""
harness = harness.replace("#include <cstddef>", "#include <cstddef>\n#include <initializer_list>")
assert source.count("shouldBlockClickAction(mask, object, parent)") == 2
ET.parse(root / "indra/newview/skins/default/xui/en/panel_preferences_boxxyviewer.xml")
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / "left_click_actions.cpp"
    exe = Path(directory) / "left_click_actions.exe"
    cpp.write_text(harness)
    subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("Left-click blocker: 1,600 action/modifier/settings combinations, inherited Pay/Buy/Touch, child overrides and HUD/avatar/attachment exceptions passed.")
