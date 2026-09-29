"""Run via the viewer's --leap option with separate smoke-test settings.

Exercises real preference controls at the login screen, including Cancel.
Output: tmp/cloud-preferences.jsonl and tmp/cloud-preferences.png.
"""
import json
from pathlib import Path
import sys
import time
import llsd

ROOT = Path(__file__).resolve().parents[2]


def receive():
    header = bytearray()
    while True:
        char = sys.stdin.buffer.read(1)
        if not char: raise EOFError()
        if char == b':': break
        header += char
    return llsd.parse(sys.stdin.buffer.read(int(header)))


reply = receive()['pump']
if '--noop' in sys.argv:
    sys.exit(0)
log = (ROOT/'tmp/cloud-preferences.jsonl').open('w', encoding='utf-8')
serial = 0


def send(pump, data):
    packet = llsd.format_notation(dict(pump=pump, data=data))
    sys.stdout.buffer.write(str(len(packet)).encode()+b':'+packet)
    sys.stdout.buffer.flush()


def request(pump, op, **data):
    global serial
    serial += 1
    send(pump, dict(data, op=op, reply=reply, reqid=serial))
    while True:
        result = receive().get('data', {})
        if result.get('reqid') == serial:
            log.write(json.dumps(dict(op=op, **result), default=str)+'\n'); log.flush()
            assert 'error' not in result, result
            return result


def setting(key, value):
    request('LLViewerControl', 'set', group='Global', key=key, value=value)


def get_setting(key):
    result = request('LLViewerControl', 'get', group='Global', key=key)
    # XUI combo values are LLSD strings; the viewer's typed accessors convert
    # them to the declared setting type on read. Mirror those accessors here.
    convert = {'S32': int, 'U32': int, 'F32': float, 'Boolean': bool}
    return convert[result['type']](result['value'])


base = '/main_view/menu_stack/world_panel/Floater View/Preferences/pref core/display/graphics_tab_container/graphics_clouds_panel/'


def key(path, keysym):
    data={'char':keysym} if len(keysym)==1 else {'keysym':keysym}
    request('LLWindow', 'keyDown', path=path, **data)
    # Return can close a popup; release without forcing focus onto that hidden
    # view again (or back to the combo parent after it focused its popup).
    request('LLWindow', 'keyUp', **data)



def dismiss_startup_notices():
    # Keep the existing settings in this isolated test profile. Keyboard focus
    # avoids relying on screen coordinates when the desktop uses UI scaling.
    for path in request('LLWindow', 'getPaths').get('paths', []):
        if path.endswith(('/OK_okbutton','/Keep')):
            message=request('LLWindow', 'getInfo', path=path.rsplit('/',1)[0]+'/Alert message')
            text=str(message.get('value','')).lower()
            if ('older version' in text and path.endswith('/OK_okbutton')) or ('new graphics feature settings' in text and path.endswith('/Keep')):
                key(path,'ENTER')

try:
    time.sleep(4)
    dismiss_startup_notices()
    setting('RenderVolumeClouds',True)
    sliders={'RenderVolumeCloudDensity':(.6,.8),'RenderVolumeCloudSunlight':(.7,1)}
    for name,(initial,default) in sliders.items():
        setting(name,initial)
    send('LLFloaterReg',dict(op='showInstance',name='preferences',focus=True))
    request('LLFloaterReg','clickButton',name='preferences',button='vtab_display')
    request('LLFloaterReg','clickButton',name='preferences',button='htab_graphics_clouds_panel')
    for name,(initial,default) in sliders.items():
        info=request('LLWindow','getInfo',path=base+name)
        assert info['visible'] and info['enabled'],info
        key(base+name+'/slider_bar','RIGHT')
        assert abs(get_setting(name)-(initial+.05))<.001
        setting(name,0)
        key(base+name+'/slider_bar','LEFT')
        assert get_setting(name)==0
        setting(name,2)
        key(base+name+'/slider_bar','RIGHT')
        assert get_setting(name)==2
    key(base+'RenderVolumeClouds/CheckboxCtrl Button',' ')
    assert not get_setting('RenderVolumeClouds')
    for name in sliders:
        assert not request('LLWindow','getInfo',path=base+name)['enabled']
    key(base+'RenderVolumeClouds/CheckboxCtrl Button',' ')
    assert get_setting('RenderVolumeClouds')
    for name in sliders:
        assert request('LLWindow','getInfo',path=base+name)['enabled']
    request('LLFloaterReg','clickButton',name='preferences',button='CloudDefaults')
    for name,(initial,default) in sliders.items():
        assert abs(get_setting(name)-default)<.001
    request('LLFloaterReg','clickButton',name='preferences',button='Cancel')
    for name,(initial,default) in sliders.items():
        assert abs(get_setting(name)-initial)<.001
    assert get_setting('RenderVolumeClouds')
    send('LLFloaterReg',dict(op='showInstance',name='preferences',focus=True))
    request('LLFloaterReg','clickButton',name='preferences',button='htab_graphics_clouds_panel')
    time.sleep(.3)
    dismiss_startup_notices()
    assert request('LLViewerWindow','saveSnapshot',filename=str(ROOT/'tmp/cloud-preferences.png'),showui=True,showhud=False)['ok']
    request('LLFloaterReg','clickButton',name='preferences',button='Cancel')
    log.write(json.dumps(dict(result='PASS: Density and Sunlight sliders, steps and endpoints, enable dependencies, Default and Cancel'))+'\n')
finally:
    log.close()
    send('LLAppViewer',dict(op='requestQuit'))
