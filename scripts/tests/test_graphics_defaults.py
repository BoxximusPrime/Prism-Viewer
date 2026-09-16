"""Run the production startup migration with settings/notification test doubles.

Requires Python and g++; no viewer launch or user settings are modified.
"""
from pathlib import Path
import json
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'indra/newview/llstartup.cpp').read_text(encoding='utf-8')
production = source[source.index('struct PrismGraphicsDefaults :'):
                    source.index('void callback_cache_name(')]


def entries(element):
    children = list(element)
    return {children[i].text: children[i + 1] for i in range(0, len(children), 2)}


def literal(element):
    if element.tag == 'map':
        assert not list(element)
        return 'LLSD::emptyMap()'
    if element.tag == 'array':
        return 'LLSD::Array{' + ','.join(literal(v) for v in element) + '}'
    if element.tag == 'string':
        return json.dumps(element.text or '')
    if element.tag == 'real':
        return 'double(' + element.text + ')'
    if element.tag == 'boolean':
        return 'true' if element.text in ('true', '1') else 'false'
    assert element.tag == 'integer'
    return element.text


settings = entries(ET.parse(ROOT / 'indra/newview/app_settings/settings.xml').getroot().find('map'))
prefixes = ('BoxxySSS', 'RenderGTAO', 'RenderPCSS', 'RenderTAA', 'RenderWater',
            'RenderVolumeFog', 'RenderBloom', 'RenderEyeAdaptation', 'PrismGraphicsDefaults')
types = {'Boolean': 'TYPE_BOOLEAN', 'F32': 'TYPE_F32', 'Color4': 'TYPE_COL4'}
declarations = []
for name, element in settings.items():
    if name.startswith(prefixes) or name in ('RenderFSAAType', 'RenderGlowMinLuminance',
                                            'RenderFarClip', 'RenderShadowDetail', 'PresetGraphicActive'):
        fields = entries(element)
        declarations.append('add(' + json.dumps(name) + ', ' +
                            types.get(fields['Type'].text, 'TYPE_OTHER') + ', ' +
                            literal(fields['Value']) + ', ' + fields['Persist'].text + ');')

harness = r'''
#include <cassert>
#include <functional>
#include <map>
#include <string>
#include <variant>
#include <vector>
using F32=float; using F64=double; using S32=int;
struct LLSD {
    using Map=std::map<std::string,LLSD>; using Array=std::vector<LLSD>;
    std::variant<std::monostate,bool,int,double,std::string,Map,Array> value;
    LLSD()=default; LLSD(bool v):value(v){} LLSD(int v):value(v){} LLSD(double v):value(v){}
    LLSD(const char* v):value(std::string(v)){} LLSD(std::string v):value(v){}
    LLSD(Map v):value(v){} LLSD(Array v):value(v){}
    static LLSD emptyMap(){return Map{};}
    LLSD& operator[](const std::string& k){if(!std::holds_alternative<Map>(value))value=Map{};return std::get<Map>(value)[k];}
    bool asBoolean()const{return std::holds_alternative<bool>(value)?std::get<bool>(value):std::get<int>(value)!=0;}
    double asReal()const{return std::holds_alternative<double>(value)?std::get<double>(value):std::get<int>(value);}
    std::string asString()const{return std::get<std::string>(value);}
    bool operator==(const LLSD& b)const{return value==b.value;}
};
bool llsd_equals(const LLSD& a,const LLSD& b){return a==b;}
namespace llsd {const auto& inMap(const LLSD& a){return std::get<LLSD::Map>(a.value);}}
struct LLColor4 {
    LLSD v;
    LLColor4(LLSD a):v(a){for(auto& x:std::get<LLSD::Array>(v.value))x=double(float(x.asReal()));}
    LLSD getValue(){return v;}
};
enum {TYPE_OTHER,TYPE_BOOLEAN,TYPE_F32,TYPE_COL4};
struct LLControlVariable {
    int type=TYPE_OTHER; LLSD defaults,saved; bool persist=true; int signals=0;
    bool isType(int t){return type==t;} bool isPersisted(){return persist;}
    LLSD getDefault(){return defaults;} LLSD getSaveValue(){return saved;}
    void resetToDefault(bool signal){saved=defaults;signals+=signal;}
};
struct LLControlGroup {
    struct ApplyFunctor {virtual void apply(const std::string&,LLControlVariable*)=0;};
    std::map<std::string,LLControlVariable> controls;
    LLSD disk=LLSD::emptyMap(); int writes=0;
    LLControlVariable* getControl(const std::string& name){return &controls.at(name);}
    void applyToAll(ApplyFunctor* f){for(auto& e:controls)f->apply(e.first,&e.second);}
    LLSD getLLSD(const std::string& name){return getControl(name)->saved;}
    void setLLSD(const std::string& name,const LLSD& v){getControl(name)->saved=v;}
    std::string getString(const std::string& name){return getLLSD(name).asString();}
    void setString(const std::string& name,const std::string& v){setLLSD(name,v);}
    void saveToFile(const std::string&,bool){++writes;for(auto& e:controls)if(e.second.persist)disk[e.first]=e.second.saved;}
} gSavedSettings;
struct LLVersionInfo {
    std::string version="0.5.1";
    static LLVersionInfo& instance(){static LLVersionInfo v;return v;}
    std::string getShortVersion(){return version;}
};
struct LLPresetsManager {
    int signals=0;
    static LLPresetsManager* getInstance(){static LLPresetsManager p;return &p;}
    void triggerChangeSignal(){++signals;}
};
namespace LLNotificationsUtil {
    int prompts=0; std::function<void(const LLSD&,const LLSD&)> callback;
    int getSelectedOption(const LLSD&,const LLSD& r){return int(r.asReal());}
    void add(const std::string& name,const LLSD&,const LLSD&,decltype(callback) f){
        assert(name=="PrismGraphicsDefaultsUpdate"); ++prompts;callback=f;
    }
    void answer(int option){auto f=callback;callback={};f(LLSD(),LLSD(option));}
}
'''
harness += production
harness += r'''
void add(std::string name,int type,LLSD value,bool persist=true){
    gSavedSettings.controls[name]={type,value,value,persist};
}
void setup(){
    gSavedSettings=LLControlGroup();
    LLNotificationsUtil::prompts=0;LLNotificationsUtil::callback={};
    LLVersionInfo::instance().version="0.5.1";
    LLPresetsManager::getInstance()->signals=0;
    add("ClientSettingsFile",TYPE_OTHER,"test-only.xml");
'''
harness += '\n'.join(declarations) + '\n}\n'
harness += r'''
PrismGraphicsDefaults collect(){PrismGraphicsDefaults g;gSavedSettings.applyToAll(&g);return g;}
void custom(){gSavedSettings.setLLSD("RenderWaterWaveStrength",0.75);}
void checkRecorded(){
    assert(gSavedSettings.disk["PrismGraphicsDefaultsVersion"].asString()==LLVersionInfo::instance().version);
    assert(llsd_equals(gSavedSettings.disk["PrismGraphicsDefaultsSnapshot"],collect().defaults));
}
int main(){
    // Fresh install and old installs that already match advance silently.
    setup();show_graphics_defaults_if_required();
    assert(LLNotificationsUtil::prompts==0);checkRecorded();
    setup();gSavedSettings.setString("PrismGraphicsDefaultsVersion","0.4");
    show_graphics_defaults_if_required();assert(LLNotificationsUtil::prompts==0);checkRecorded();

    // A missing marker with customized settings requires an answer before saving.
    setup();custom();gSavedSettings.setString("PresetGraphicActive","My preset");
    const LLSD customized=collect().saved;
    show_graphics_defaults_if_required();assert(LLNotificationsUtil::prompts==1);
    assert(gSavedSettings.writes==0);LLNotificationsUtil::answer(1);checkRecorded();
    assert(llsd_equals(customized,collect().saved));
    assert(gSavedSettings.getString("PresetGraphicActive")=="My preset");
    assert(LLPresetsManager::getInstance()->signals==0);
    // Simulate restart by reloading the persisted settings.
    for(auto& e:gSavedSettings.controls)if(e.second.persist)e.second.saved=gSavedSettings.disk[e.first];
    show_graphics_defaults_if_required();assert(LLNotificationsUtil::prompts==1);
    LLVersionInfo::instance().version="0.6";
    show_graphics_defaults_if_required();assert(LLNotificationsUtil::prompts==1);checkRecorded();
    assert(llsd_equals(customized,collect().saved));

    // New defaults, including a change to an unrelated effect, offer the reset.
    LLVersionInfo::instance().version="0.7";
    gSavedSettings.getControl("RenderGTAOStrength")->defaults=0.85;
    show_graphics_defaults_if_required();assert(LLNotificationsUtil::prompts==2);
    gSavedSettings.setLLSD("RenderFarClip",777.0);
    gSavedSettings.setLLSD("RenderShadowDetail",0);
    gSavedSettings.setLLSD("RenderWater",false);
    LLNotificationsUtil::answer(0);checkRecorded();
    assert(llsd_equals(collect().defaults,collect().saved));
    assert(gSavedSettings.getLLSD("RenderFarClip").asReal()==777);
    assert(gSavedSettings.getLLSD("RenderShadowDetail").asReal()==0);
    assert(!gSavedSettings.getLLSD("RenderWater").asBoolean());
    assert(gSavedSettings.getString("PresetGraphicActive").empty());
    assert(LLPresetsManager::getInstance()->signals==1);
    for(auto& e:llsd::inMap(collect().defaults))assert(gSavedSettings.getControl(e.first)->signals==1);
    show_graphics_defaults_if_required();assert(LLNotificationsUtil::prompts==2);

    // Changes made after reviewing this release never cause another prompt.
    custom();gSavedSettings.getControl("RenderGTAOStrength")->defaults=0.9;
    show_graphics_defaults_if_required();assert(LLNotificationsUtil::prompts==2);

    // Closing an unanswered prompt leaves the previous version untouched.
    setup();custom();gSavedSettings.setString("PrismGraphicsDefaultsVersion","0.4");
    show_graphics_defaults_if_required();LLNotificationsUtil::answer(-1);
    assert(gSavedSettings.writes==0);
    assert(gSavedSettings.getString("PrismGraphicsDefaultsVersion")=="0.4");
    show_graphics_defaults_if_required();assert(LLNotificationsUtil::prompts==2);

    // Float slider/XML round trips, boolean encodings, and colours aren't edits.
    setup();
    for(auto& e:gSavedSettings.controls){
        auto& c=e.second;
        if(c.type==TYPE_F32)c.saved=double(float(c.saved.asReal()));
        if(c.type==TYPE_BOOLEAN)c.saved=c.saved.asBoolean();
        if(c.type==TYPE_COL4)c.saved=LLColor4(c.saved).getValue();
    }
    show_graphics_defaults_if_required();assert(LLNotificationsUtil::prompts==0);checkRecorded();

    // A new property is detected; new defaults already in use still stay quiet.
    setup();show_graphics_defaults_if_required();
    LLVersionInfo::instance().version="0.6";add("RenderWaterFutureSetting",TYPE_F32,0.5);
    custom();show_graphics_defaults_if_required();assert(LLNotificationsUtil::prompts==1);
    LLNotificationsUtil::answer(1);checkRecorded();
    LLVersionInfo::instance().version="0.7";
    add("RenderWaterAnotherSetting",TYPE_F32,0.5);
    for(auto& e:llsd::inMap(collect().defaults))gSavedSettings.getControl(e.first)->resetToDefault(false);
    show_graphics_defaults_if_required();assert(LLNotificationsUtil::prompts==1);checkRecorded();

    // Persisted custom colours are included, session diagnostics are excluded.
    setup();gSavedSettings.setLLSD("RenderWaterAbsorptionColor",LLSD::Array{0.1,0.2,0.3,1.0});
    show_graphics_defaults_if_required();assert(LLNotificationsUtil::prompts==1);
    setup();gSavedSettings.setLLSD("RenderTAADebug",3);
    add("BoxxySSSFullResolution",TYPE_BOOLEAN,true); // preserved legacy user setting
    show_graphics_defaults_if_required();assert(LLNotificationsUtil::prompts==0);
    assert(llsd::inMap(collect().defaults).count("BoxxySSSFullResolution")==0);
}
'''

# Check actual UI coverage and removal of the old SSS toggle.
panel = ET.parse(ROOT / 'indra/newview/skins/default/xui/en/panel_preferences_graphics1.xml')
covered = set()
for category in ('skin_scattering', 'gtao', 'pcss', 'taa', 'water', 'volume_fog', 'bloom', 'eye_adaptation'):
    page = panel.find(f'.//panel[@name="graphics_{category}_panel"]')
    assert page is not None
    for widget in page.iter():
        name = widget.get('control_name')
        # Shadow selection is a shared legacy setting on the PCSS page.
        if name in settings and name != 'RenderShadowDetail' and entries(settings[name])['Persist'].text == '1':
            covered.add(name)
coverage_checks = '\n'.join(
    f'assert(llsd::inMap(collect().defaults).count({json.dumps(name)})==1);' for name in sorted(covered))
harness = harness.replace('int main(){', 'int main(){\nsetup();\n' + coverage_checks)
assert 'BoxxySSSFullResolution' not in settings
assert not panel.findall('.//*[@control_name="BoxxySSSFullResolution"]')
notification = ET.parse(ROOT / 'indra/newview/skins/default/xui/en/notifications.xml').find(
    './/notification[@name="PrismGraphicsDefaultsUpdate"]')
assert notification.attrib['type'] == 'alertmodal'
assert notification.find('.//button[@index="1"]').attrib['default'] == 'true'
assert source.count('show_graphics_defaults_if_required();') == 1
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / 'graphics_defaults.cpp'
    exe = Path(directory) / 'graphics_defaults.exe'
    cpp.write_text(harness, encoding='utf-8')
    subprocess.run(['g++', '-std=c++17', str(cpp), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('Graphics defaults: silent upgrades, reset/keep persistence, unchanged releases, restart, '
      'same-version edits, unanswered prompts, added defaults, float/colour round trips and scope passed.')
