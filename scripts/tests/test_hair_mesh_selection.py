"""Compile production collider selection and body/clothing visibility policies."""
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
    fields = list(controls['BoxxyHairPhysicsClothingNames'])
    fields = {fields[i].text: fields[i+1].text for i in range(0, len(fields), 2)}
    assert fields['Value'] in (None, '') and fields['Persist'] == '1'
    editor = next(e for e in ui.iter('line_editor') if e.get('name') == 'BoxxyHairPhysicsClothingNames')
    assert editor.get('control_name') == 'BoxxyHairPhysicsClothingNames'
    assert '"BoxxyHairPhysicsClothingNames"' in (ROOT / 'indra/newview/llfloaterpreference.cpp').read_text()
    panel = next(e for e in ui.iter('panel') if e.get('name') == 'HairPhysicsContent')
    previous_bottom = 0
    for child in panel:
        assert int(child.get('top')) >= previous_bottom, child.get('name')
        previous_bottom = int(child.get('top')) + int(child.get('height'))
    assert previous_bottom <= int(panel.get('height'))
    source = (ROOT / 'indra/newview/llhairmesh.cpp').read_text()
    start = source.find('bool matchesHairColliderName(')
    if start < 0:
        start = source.index('void collect(')
    collector = source[start:source.index('void upload(', start)]
    code = r'''
#include <algorithm>
#include <cassert>
#include <cctype>
#include <cstdio>
#include <map>
#include <sstream>
#include <string>
#include <vector>
using S32=int; using U8=unsigned char; using F32=float;
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
struct Color { float mV[4]={1,1,1,1}; };
struct LLGLTFMaterial {
    enum { ALPHA_MODE_OPAQUE, ALPHA_MODE_BLEND, ALPHA_MODE_MASK };
    int mAlphaMode=ALPHA_MODE_OPAQUE; float mAlphaCutoff=.5f; Color mBaseColor;
};
struct TextureEntry {
    Color color; LLGLTFMaterial* material=nullptr;
    const Color& getColor()const{return color;}
    const LLGLTFMaterial* getGLTFRenderMaterial()const{return material;}
};
struct Volume { int getNumVolumeFaces()const{return 3;} };
struct LLVOVolume:LLViewerObject {
    bool hair=false,mesh=true,skinned=true,overlay=false;
    Volume volume; TextureEntry te[3];
    bool isHairEnabled()const{return hair;} bool isMesh()const{return mesh;}
    const Volume* getVolume()const{return &volume;} bool getSkinInfo()const{return skinned;}
    const TextureEntry* getTE(int i)const{return &te[i];}
    bool isSSSEnabled()const{return true;} // Perky currently makes both clothes and body qualify.
    bool isSSSOverlayEnabled()const{return overlay;}
    static bool isHairInRange(LLVOVolume*){return true;}
};
@COLLECTOR@
int main() {
    gSavedSettings["BoxxyHairPhysicsColliderNames"]="body, head, hands, feet";
    gSavedSettings["BoxxyHairPhysicsClothingNames"]="";
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
    child.skinned=true;

    // A clothing fit label does not opt a garment in; its own phrase does.
    gSavedSettings["BoxxyHairPhysicsColliderNames"]="body, head, hands, feet";
    gSavedSettings["BoxxyHairPhysicsClothingNames"]="  SALEM TOP , ,";
    LLVOVolume lining; lining.root=&top; top.children={&lining};
    selected.clear();collect(&self,selected,selected_hair);
    assert(selected.size()==7 && std::count(selected.begin(),selected.end(),&top)==1);
    assert(std::find(selected.begin(),selected.end(),&lining)!=selected.end());
    top.hud=true;selected.clear();collect(&top,selected,selected_hair);assert(selected.empty());top.hud=false;
    top.skinned=false;lining.skinned=false;collect(&top,selected,selected_hair);assert(selected.empty());
    top.skinned=lining.skinned=true;
    top.overlay=lining.overlay=true;collect(&top,selected,selected_hair);assert(selected.empty());
    top.overlay=lining.overlay=false;
    hair.name="Salem Top Hair";collect(&hair,selected,selected_hair);assert(selected.empty());

    const std::vector<U8> full={1,1,1}, cut={1,0,0};
    // Cached masks drive shell bakes AND guide refits: body alpha must not change them.
    const auto before=colliderFaces(body);
    body.te[1].color.mV[3]=0.f;body.te[2].color.mV[3]=.0001f;
    assert(before==full && colliderFaces(body)==before);
    assert(visibleFaces(body)==cut); // hair visibility policy remains separate
    child.te[1].color.mV[3]=0.f;assert(colliderFaces(child)==full);
    top.te[1].color.mV[3]=0.f;top.te[2].color.mV[3]=.0001f;
    assert(colliderFaces(top)==cut);
    lining.te[1].color.mV[3]=0.f;assert(colliderFaces(lining)==std::vector<U8>({1,0,1}));
    top.te[1].color.mV[3]=1.f;assert(colliderFaces(top)!=cut); // garment variants still rebuild
    top.te[1].color.mV[3]=0.f;

    LLGLTFMaterial pbr;pbr.mBaseColor.mV[3]=0.f;
    for(auto* object:{&body,&top})object->te[1].material=&pbr;
    assert(colliderFaces(top)[1]); // opaque PBR ignores legacy/material alpha
    pbr.mAlphaMode=LLGLTFMaterial::ALPHA_MODE_BLEND;
    assert(!colliderFaces(top)[1] && colliderFaces(body)==before);
    pbr.mAlphaMode=LLGLTFMaterial::ALPHA_MODE_MASK;pbr.mBaseColor.mV[3]=.4f;
    assert(!colliderFaces(top)[1] && colliderFaces(body)==before);
    pbr.mBaseColor.mV[3]=.5f;assert(colliderFaces(top)[1]);

    gSavedSettings["BoxxyHairPhysicsColliderNames"]="body, salem top";
    selected.clear();collect(&top,selected,selected_hair);
    assert(selected.size()==2 && colliderFaces(top)==full); // body wins, no duplicate meshes
    gSavedSettings["BoxxyHairPhysicsClothingNames"]="";
    gSavedSettings["BoxxyHairPhysicsColliderNames"]="body";
    selected.clear();collect(&top,selected,selected_hair);assert(selected.empty());
    puts("PASS: independent body/clothing lists, defaults/reset/UI, hidden body continuity, garment alpha/PBR variants, precedence, linked pieces, hair/HUD/world exclusions");
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
