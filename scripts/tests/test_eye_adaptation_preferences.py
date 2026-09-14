"""Check EyeAd settings offline, or run via --leap after the Release build.

Offline: .venv/Scripts/python.exe scripts/tests/test_eye_adaptation_preferences.py --validate
Live: use --leap with isolated user settings; exercises enable, sliders, Default,
category isolation and Cancel, and captures the actual graphics tab.
"""
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
PREFIX='RenderEyeAdaptation'
DEFAULTS={'Enabled':True,'MaxBoost':1.3,'MaxDarken':2.7,'Compensation':-.05,
          'Highlights':.65,'DarkTime':2.,'LightTime':.6}
PANEL='graphics_eye_adaptation_panel'


def validate():
    entries=list(ET.parse(ROOT/'indra/newview/app_settings/settings.xml').getroot().find('map'))
    settings={entries[i].text:entries[i+1] for i in range(0,len(entries),2)}
    assert len(settings)*2==len(entries),'Duplicate setting declarations'
    root=ET.parse(ROOT/'indra/newview/skins/default/xui/en/panel_preferences_graphics1.xml').getroot()
    tabs=root.find('tab_container')
    panel=tabs.find(f"panel[@name='{PANEL}']")
    assert panel is not None and panel.get('label')=='EyeAd'
    assert tabs.find("panel[@name='graphics_skin_scattering_panel']").get('label')=='SSS'
    controls={node.get('control_name'):node for node in panel if node.get('control_name')}
    assert set(controls)=={PREFIX+key for key in DEFAULTS},controls
    for suffix,value in DEFAULTS.items():
        name=PREFIX+suffix
        children=list(settings[name])
        definition={children[i].text:children[i+1].text for i in range(0,len(children),2)}
        assert definition['Persist']=='1',name
        assert definition['Type']==('Boolean' if suffix=='Enabled' else 'F32'),name
        assert float(definition['Value'])==value,name
        control=controls[name]
        assert control.get('name')==name
        if suffix!='Enabled':
            assert float(control.get('min_val'))<=value<=float(control.get('max_val')),name
            assert float(control.get('increment'))>0,name
        assert int(control.get('left'))+int(control.get('width'))<=int(panel.get('width')),name
        assert int(control.get('top'))+int(control.get('height'))<=int(panel.get('height')),name
    callback=panel.find("button/button.commit_callback")
    assert callback.get('function')=='Pref.GraphicsCategoryDefaults'
    assert callback.get('parameter')==PANEL
    print('PASS: EyeAd/SSS labels, seven persistent settings, defaults, control ranges and panel bounds.',file=sys.stderr)


def live():
    import time
    import llsd
    def receive():
        header=bytearray()
        while True:
            char=sys.stdin.buffer.read(1)
            if not char: raise EOFError()
            if char==b':': break
            header+=char
        return llsd.parse(sys.stdin.buffer.read(int(header)))
    reply=receive()['pump']
    log=(ROOT/'tmp/eye-adaptation-preferences.jsonl').open('w',encoding='utf8')
    serial=0
    def send(pump,data):
        packet=llsd.format_notation(dict(pump=pump,data=data))
        sys.stdout.buffer.write(str(len(packet)).encode()+b':'+packet)
        sys.stdout.buffer.flush()
    def request(pump,op,**data):
        nonlocal serial
        serial+=1
        send(pump,dict(data,op=op,reply=reply,reqid=serial))
        while True:
            result=receive().get('data',{})
            if result.get('reqid')==serial:
                log.write(json.dumps(dict(op=op,**result),default=str)+'\n');log.flush()
                assert 'error' not in result,result
                return result
    def setting(name,value):
        request('LLViewerControl','set',group='Global',key=name,value=value)
    def get(name):
        result=request('LLViewerControl','get',group='Global',key=name)
        return {'F32':float,'Boolean':bool}[result['type']](result['value'])
    def button(name):
        request('LLFloaterReg','clickButton',name='preferences',button=name)
    def open_tab():
        send('LLFloaterReg',dict(op='showInstance',name='preferences',focus=True))
        button('vtab_display');button('htab_'+PANEL)
    base='/main_view/menu_stack/world_panel/Floater View/Preferences/pref core/display/graphics_tab_container/'+PANEL+'/'
    def click_enable():
        for op in ('mouseDown','mouseUp'):
            request('LLWindow',op,path=base+PREFIX+'Enabled/CheckboxCtrl Button',button='LEFT')
    def key(path,keysym):
        request('LLWindow','keyDown',path=path,keysym=keysym)
        request('LLWindow','keyUp',keysym=keysym)

    time.sleep(2)
    original={'Enabled':False,'MaxBoost':3.,'MaxDarken':1.,'Compensation':.5,
              'Highlights':.4,'DarkTime':3.,'LightTime':1.}
    setting('RenderHDREnabled',True)
    for suffix,value in original.items(): setting(PREFIX+suffix,value)
    # The reset must not affect another graphics category.
    setting('BoxxySSSStrength',1.23)
    open_tab()
    for suffix in DEFAULTS:
        info=request('LLWindow','getInfo',path=base+PREFIX+suffix)
        assert info['visible'] and bool(info['enabled'])==(suffix=='Enabled'),info
    click_enable()
    assert get(PREFIX+'Enabled')
    for suffix in DEFAULTS:
        assert request('LLWindow','getInfo',path=base+PREFIX+suffix)['enabled']
    for suffix in ('MaxBoost','MaxDarken','Compensation','Highlights','DarkTime','LightTime'):
        before=get(PREFIX+suffix)
        key(base+PREFIX+suffix+'/slider_bar','RIGHT')
        assert get(PREFIX+suffix)>before,(suffix,before,get(PREFIX+suffix))
    time.sleep(.5)
    assert request('LLViewerWindow','saveSnapshot',
        filename=str(ROOT/'tmp/eye-adaptation-preferences.png'),showui=True,showhud=False)['ok']
    button('EyeAdaptationDefaults')
    for suffix,value in DEFAULTS.items():
        assert abs(get(PREFIX+suffix)-value)<.001,suffix
    assert abs(get('BoxxySSSStrength')-1.23)<.001
    button('Cancel')
    for suffix,value in original.items():
        assert abs(get(PREFIX+suffix)-value)<.001,('Cancel',suffix)
    log.write(json.dumps({'result':'PASS: EyeAd enable, six slider commits, scoped Default, Cancel and tab screenshot'})+'\n')
    log.close()
    send('LLAppViewer',dict(op='requestQuit'))


if __name__=='__main__':
    validate()
    if '--validate' not in sys.argv: live()
