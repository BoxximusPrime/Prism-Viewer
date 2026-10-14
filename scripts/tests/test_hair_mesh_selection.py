"""Compile the shell collector and reject clothing named for a compatible body."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]


def main():
    settings = list(ET.parse(ROOT / 'indra/newview/app_settings/settings.xml').getroot().find('map'))
    controls = {settings[i].text: settings[i+1] for i in range(0, len(settings), 2)}
    fields = list(controls['BoxxyHairPhysicsColliderNames'])
    assert {fields[i].text: fields[i+1].text for i in range(0, len(fields), 2)}['Value'] == 'body, head, hands, feet'
    ui = ET.parse(ROOT / 'indra/newview/skins/default/xui/en/panel_preferences_graphics1.xml')
    editor = next(e for e in ui.iter('line_editor') if e.get('name') == 'BoxxyHairPhysicsColliderNames')
    assert editor.get('control_name') == 'BoxxyHairPhysicsColliderNames'
    assert '"BoxxyHairPhysicsColliderNames"' in (ROOT / 'indra/newview/llfloaterpreference.cpp').read_text()
    source = (ROOT / 'indra/newview/llhairmesh.cpp').read_text()
    start = source.find('bool matchesHairColliderName(')
    if start < 0:
        start = source.index('void collect(')
    collector = source[start:source.index('std::vector<U8> visibleFaces(', start)]
    code = r'''
#include <algorithm>
#include <cassert>
#include <cctype>
#include <cstdio>
#include <map>
#include <sstream>
#include <string>
#include <vector>
std::map<std::string,std::string> gSavedSettings;
template<class T> struct LLCachedControl {
    std::string name;
    LLCachedControl(decltype(gSavedSettings)&, const char* n):name(n){}
    operator const T&() const { return gSavedSettings[name]; }
};
struct LLStringUtil {
    static void toLower(std::string& s) { for(char& c:s)c=char(std::tolower((unsigned char)c)); }
    static void trim(std::string& s) {
        auto first=s.find_first_not_of(" \t\r\n");
        s=first==std::string::npos ? "" : s.substr(first,s.find_last_not_of(" \t\r\n")-first+1);
    }
    static std::vector<std::string> getTokens(const std::string& s,const char*) {
        std::vector<std::string> result; std::istringstream stream(s);
        for(std::string t;std::getline(stream,t,',');)result.push_back(t); return result;
    }
};
struct LLViewerObject {
    virtual ~LLViewerObject()=default;
    bool dead=false,hud=false; std::string name; LLViewerObject* root=nullptr;
    std::vector<LLViewerObject*> children;
    bool isDead()const{return dead;} bool isHUDAttachment()const{return hud;}
    const auto& getChildren()const{return children;}
    LLViewerObject* getRootEdit(){return root ? root : this;}
    bool hasCachedObjectName()const{return !name.empty();}
    const std::string& getCachedObjectName()const{return name;}
    const std::string& getAttachmentItemName()const{return name;}
};
struct LLVOVolume:LLViewerObject {
    bool hair=false,mesh=true,skinned=true,overlay=false;
    bool isHairEnabled()const{return hair;} bool isMesh()const{return mesh;}
    bool getVolume()const{return true;} bool getSkinInfo()const{return skinned;}
    bool isSSSEnabled()const{return true;} // Perky currently makes both clothes and body qualify.
    bool isSSSOverlayEnabled()const{return overlay;}
    static bool isHairInRange(LLVOVolume*){return true;}
};
@COLLECTOR@
int main() {
    gSavedSettings["BoxxyHairPhysicsColliderNames"]="body, head, hands, feet";
    LLVOVolume body,head,hands,feet,top,hair,child,world;
    body.name="[BODY] Legacy (f) Perky (1.7.1)";
    head.name="/ HEAD / lel evox / AVALON 4.0";
    hands.name="[HANDS] Legacy"; feet.name="[FEET] Legacy";
    top.name="Addams // Salem Top with Necklaces // Perky";
    hair.name="Test hair"; hair.hair=true;
    child.root=&body; body.children={&child};
    world.name="World body collider";
    LLViewerObject self;self.children={&body,&head,&hands,&feet,&top,&hair};
    std::vector<LLVOVolume*> selected;LLVOVolume* selected_hair=nullptr;
    collect(&self,selected,selected_hair);
    assert(std::find(selected.begin(),selected.end(),&top)==selected.end());
    assert(std::find(selected.begin(),selected.end(),&world)==selected.end());
    assert(selected.size()==5 && selected_hair==&hair);
    top.name="Headphones"; selected.clear(); collect(&top,selected,selected_hair);assert(selected.empty());
    gSavedSettings["BoxxyHairPhysicsColliderNames"]="  salem top , ,";
    top.name="Addams // Salem Top with Necklaces // Perky";
    collect(&self,selected,selected_hair);assert(selected.size()==1 && selected[0]==&top);
    gSavedSettings["BoxxyHairPhysicsColliderNames"]="";
    selected.clear();collect(&self,selected,selected_hair);assert(selected.empty());
    gSavedSettings["BoxxyHairPhysicsColliderNames"]="body";
    body.hud=true;collect(&body,selected,selected_hair);assert(selected.empty());body.hud=false;
    child.skinned=false;collect(&body,selected,selected_hair);assert(selected.size()==1 && selected[0]==&body);
    puts("PASS: body/head/hands/feet, linked pieces, clothing rejection, word boundaries, editable names, HUD/world exclusion");
}
'''.replace('@COLLECTOR@', collector)
    compiler = shutil.which('g++')
    assert compiler, 'g++ is required'
    with tempfile.TemporaryDirectory(prefix='hair-mesh-selection-', dir=ROOT / '.logs') as directory:
        src, exe = Path(directory) / 'test.cpp', Path(directory) / 'test.exe'
        src.write_text(code)
        subprocess.run([compiler, '-std=c++17', str(src), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
