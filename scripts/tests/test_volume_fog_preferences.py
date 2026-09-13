"""Run via the viewer's --leap option with separate smoke-test settings.

Exercises real preference controls at the login screen, including Cancel.
Output: tmp/volume-fog-preferences.jsonl and tmp/volume-fog-preferences.png.
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
log = (ROOT/'tmp/volume-fog-preferences.jsonl').open('w', encoding='utf-8')
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


base = '/main_view/menu_stack/world_panel/Floater View/Preferences/pref core/display/graphics_tab_container/graphics_volume_fog_panel/'


def click(control):
    # LEAP routes mouse events to the exact target, so use the checkbox's
    # actual toggle button rather than its composite LLCheckBoxCtrl parent.
    path = base+control+'/CheckboxCtrl Button'
    for op in ('mouseDown', 'mouseUp'):
        request('LLWindow', op, path=path, button='LEFT')


def key(path, keysym):
    request('LLWindow', 'keyDown', path=path, keysym=keysym)
    # Return can close a popup; release without forcing focus onto that hidden
    # view again (or back to the combo parent after it focused its popup).
    request('LLWindow', 'keyUp', keysym=keysym)


time.sleep(2)
defaults = dict(RenderVolumeFog=True, RenderVolumeFogIntensity=1., RenderVolumeFogQuality=1,
                RenderVolumeFogLightCount=8, RenderVolumeFogShadows=True)
for name, value in defaults.items(): setting(name, value)
setting('RenderVolumeFogSteps',0)
send('LLFloaterReg', dict(op='showInstance', name='preferences', focus=True))
request('LLFloaterReg', 'clickButton', name='preferences', button='vtab_display')
request('LLFloaterReg', 'clickButton', name='preferences', button='htab_graphics_volume_fog_panel')
for name in defaults:
    info = request('LLWindow', 'getInfo', path=base+name)
    assert info['enabled'] and info['visible'], info
time.sleep(.5)
assert request('LLViewerWindow', 'saveSnapshot', filename=str(ROOT/'tmp/volume-fog-preferences.png'),
               showui=True, showhud=False)['ok']
click('RenderVolumeFog')
assert not get_setting('RenderVolumeFog')
for name in defaults:
    if name != 'RenderVolumeFog':
        assert not request('LLWindow', 'getInfo', path=base+name)['enabled']
click('RenderVolumeFog')
assert get_setting('RenderVolumeFog')
# Keyboard commits exercise the quality combobox rather than only changing the
# backing setting, and the sliders support ordinary arrow-key input.
for level in range(4):
    for op in ('mouseDown', 'mouseUp'):
        request('LLWindow', op, path=base+'RenderVolumeFogQuality/Drop Down Button', button='LEFT')
    popup = base+'RenderVolumeFogQuality/ComboBox'
    key(popup, 'HOME')
    for _ in range(level): key(popup, 'DOWN')
    key(popup, 'ENTER')
    assert get_setting('RenderVolumeFogQuality') == level
key(base+'RenderVolumeFogIntensity/slider_bar', 'RIGHT')
assert abs(get_setting('RenderVolumeFogIntensity')-1.05) < .001
key(base+'RenderVolumeFogLightCount/slider_bar', 'LEFT')
assert get_setting('RenderVolumeFogLightCount') == 7
click('RenderVolumeFogShadows')
assert not get_setting('RenderVolumeFogShadows')
request('LLFloaterReg', 'clickButton', name='preferences', button='Cancel')
for name, value in defaults.items(): assert get_setting(name) == value, name
log.write(json.dumps(dict(result='PASS: fog tab, five live controls, four quality levels, enable dependencies and Cancel restore'))+'\n')
log.close()
send('LLAppViewer', dict(op='requestQuit'))
