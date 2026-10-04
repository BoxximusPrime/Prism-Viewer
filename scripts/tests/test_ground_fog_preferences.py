"""LEAP test: run the Release viewer with a separate --settings profile.

Checks real ground-fog controls, shared lighting, Default/Cancel and saved values.
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
        if not char:
            raise EOFError()
        if char == b':':
            break
        header += char
    return llsd.parse(sys.stdin.buffer.read(int(header)))


reply = receive()['pump']
if '--noop' in sys.argv:
    sys.exit(0)
log = (ROOT/'tmp/ground-fog-preferences.jsonl').open('w', encoding='utf-8')
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
            log.write(json.dumps(dict(op=op, **result), default=str)+'\n')
            log.flush()
            assert 'error' not in result, result
            return result


def setting(key, value):
    request('LLViewerControl', 'set', group='Global', key=key, value=value)


def get(key):
    return request('LLViewerControl', 'get', group='Global', key=key)['value']


base = '/main_view/menu_stack/world_panel/Floater View/Preferences/pref core/display/graphics_tab_container/'
page = base + 'graphics_ground_fog_panel/GroundFogScroll/GroundFogContent/'


def key(path, keysym):
    data = {'char': keysym} if len(keysym) == 1 else {'keysym': keysym}
    request('LLWindow', 'keyDown', path=path, **data)
    request('LLWindow', 'keyUp', **data)


def button(name):
    request('LLFloaterReg', 'clickButton', name='preferences', button=name)


def show():
    send('LLFloaterReg', dict(op='showInstance', name='preferences', focus=True))
    button('vtab_display')
    button('htab_graphics_ground_fog_panel')


try:
    time.sleep(4)
    for path in request('LLWindow', 'getPaths').get('paths', []):
        if path.endswith(('/OK_okbutton', '/Keep')):
            info = request('LLWindow', 'getInfo', path=path.rsplit('/',1)[0]+'/Alert message')
            text = str(info.get('value', '')).lower()
            if ('older version' in text and path.endswith('/OK_okbutton')) or ('new graphics feature settings' in text and path.endswith('/Keep')):
                key(path, 'ENTER')
    # suffix: initial, default, min, max, increment
    sliders = {
        'Density': (.04, .025, 0, .2, .001),
        'Altitude': (30, 25, -500, 10000, 1),
        'Height': (20, 12, 1, 200, 1),
        'Distance': (128, 256, 16, 1024, 8),
        'Noise': (.6, .5, 0, 1, .05),
        'NoiseScale': (50, 40, 5, 200, 1),
        'Speed': (.5, .3, 0, 5, .05),
        'Brightness': (1.5, 1, 0, 3, .05),
    }
    setting('RenderGroundFog', True)
    setting('RenderGroundFogFollowEnvironment', False)
    setting('RenderGroundFogStrength', 1.25)
    setting('RenderVolumeFog', False)
    setting('RenderVolumeFogLightStrength', .12)
    setting('RenderVolumeFogLightCap', .018)
    setting('RenderGroundFogColor', [.5, .6, .7, 1])
    for suffix, (initial, *_) in sliders.items():
        setting('RenderGroundFog'+suffix, initial)
    show()
    for suffix, (initial, default, minimum, maximum, step) in sliders.items():
        name = 'RenderGroundFog'+suffix
        info = request('LLWindow', 'getInfo', path=page+name)
        assert info['visible'] and info['enabled'], info
        key(page+name+'/slider_bar', 'RIGHT')
        assert abs(float(get(name))-(initial+step)) < .0001, name
        setting(name, minimum)
        key(page+name+'/slider_bar', 'LEFT')
        assert abs(float(get(name))-minimum) < .0001, name
        setting(name, maximum)
        key(page+name+'/slider_bar', 'RIGHT')
        assert abs(float(get(name))-maximum) < .0001, name
    key(page+'RenderGroundFog/CheckboxCtrl Button', ' ')
    assert not get('RenderGroundFog')
    for suffix in (*sliders, 'Color', 'FollowEnvironment', 'Strength'):
        assert not request('LLWindow', 'getInfo', path=page+'RenderGroundFog'+suffix)['enabled']
    key(page+'RenderGroundFog/CheckboxCtrl Button', ' ')
    assert get('RenderGroundFog')
    button('htab_graphics_volume_fog_panel')
    for name in ('LightStrength', 'LightCap', 'LightSaturation', 'Quality', 'LightCount', 'Shadows'):
        assert request('LLWindow', 'getInfo', path=base+'graphics_volume_fog_panel/RenderVolumeFog'+name)['enabled']
    assert not request('LLWindow', 'getInfo', path=base+'graphics_volume_fog_panel/RenderVolumeFogIntensity')['enabled']
    button('htab_graphics_ground_fog_panel')
    before = get('RenderGroundFogColor')
    for op in ('mouseDown', 'mouseUp'):
        request('LLWindow', op, path=page+'RenderGroundFogColor', button='LEFT')
    paths = request('LLWindow', 'getPaths')['paths']
    spinner = next(path for path in paths if path.endswith('/rspin'))
    editor = next(path for path in paths if path.startswith(spinner+'/') and path.endswith('/SpinCtrl Editor'))
    key(editor, 'UP')
    for op in ('mouseDown', 'mouseUp'):
        request('LLWindow', op, path=spinner.rsplit('/',1)[0]+'/select_btn', button='LEFT')
    assert get('RenderGroundFogColor')[0] > before[0]
    custom_color = get('RenderGroundFogColor')
    key(page+'RenderGroundFogFollowEnvironment/CheckboxCtrl Button', ' ')
    assert get('RenderGroundFogFollowEnvironment')
    assert not request('LLWindow', 'getInfo', path=page+'RenderGroundFogDensity')['visible']
    assert request('LLWindow', 'getInfo', path=page+'RenderGroundFogStrength')['visible']
    assert not request('LLWindow', 'getInfo', path=page+'RenderGroundFogColor')['enabled']
    name = 'RenderGroundFogStrength'
    key(page+name+'/slider_bar', 'RIGHT')
    assert abs(float(get(name))-1.3) < .0001
    for value, direction in ((0, 'LEFT'), (4, 'RIGHT')):
        setting(name, value)
        key(page+name+'/slider_bar', direction)
        assert abs(float(get(name))-value) < .0001
    key(page+'RenderGroundFogFollowEnvironment/CheckboxCtrl Button', ' ')
    assert not get('RenderGroundFogFollowEnvironment')
    assert request('LLWindow', 'getInfo', path=page+'RenderGroundFogDensity')['visible']
    assert not request('LLWindow', 'getInfo', path=page+'RenderGroundFogStrength')['visible']
    assert request('LLWindow', 'getInfo', path=page+'RenderGroundFogColor')['enabled']
    assert abs(float(get('RenderGroundFogDensity'))-.2) < .0001
    assert get('RenderGroundFogColor') == custom_color
    button('GroundFogDefaults')
    assert not get('RenderGroundFog')
    assert get('RenderGroundFogFollowEnvironment')
    assert abs(float(get('RenderGroundFogStrength'))-1) < .0001
    for suffix, (_, default, *_) in sliders.items():
        assert abs(float(get('RenderGroundFog'+suffix))-default) < .0001, suffix
    assert abs(float(get('RenderVolumeFogLightStrength'))-.12) < .0001
    assert abs(float(get('RenderVolumeFogLightCap'))-.018) < .0001
    assert all(abs(a-b)<.0001 for a,b in zip(get('RenderGroundFogColor'), [.8,.85,.9,1]))
    button('Cancel')
    assert get('RenderGroundFog')
    assert not get('RenderGroundFogFollowEnvironment')
    assert abs(float(get('RenderGroundFogStrength'))-1.25) < .0001
    for suffix, (initial, *_) in sliders.items():
        assert abs(float(get('RenderGroundFog'+suffix))-initial) < .0001, suffix
    assert all(abs(a-b)<.0001 for a,b in zip(get('RenderGroundFogColor'), [.5,.6,.7,1]))
    show()
    assert request('LLViewerWindow', 'saveSnapshot', filename=str(ROOT/'tmp/ground-fog-custom-preferences.png'), showui=True, showhud=False)['ok']
    key(page+'RenderGroundFogFollowEnvironment/CheckboxCtrl Button', ' ')
    assert request('LLViewerWindow', 'saveSnapshot', filename=str(ROOT/'tmp/ground-fog-preferences.png'), showui=True, showhud=False)['ok']
    button('OK')
    log.write(json.dumps(dict(result='PASS: nine sliders and endpoints, environment/custom visibility and preservation, colour-picker commit, enable, shared controls, scoped Default, Cancel and OK'))+'\n')
finally:
    log.close()
    send('LLAppViewer', dict(op='requestQuit'))
