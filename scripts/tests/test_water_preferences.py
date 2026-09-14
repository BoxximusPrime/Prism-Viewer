"""Exercise the Water graphics page through the viewer's --leap API.

Use isolated viewer settings. Tests real control commits, dependencies, scoped
Default, OK/Cancel and captures the panel in tmp/water-preferences.png.
On Windows, pass --leap twice, with --noop on the second invocation; the
viewer's single-value --leap option otherwise expects LLSD notation.
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
log = (ROOT / 'tmp/water-preferences.jsonl').open('w', encoding='utf-8')
serial = 0


def send(pump, data):
    packet = llsd.format_notation(dict(pump=pump, data=data))
    sys.stdout.buffer.write(str(len(packet)).encode() + b':' + packet)
    sys.stdout.buffer.flush()


def request(pump, op, **data):
    global serial
    serial += 1
    send(pump, dict(data, op=op, reply=reply, reqid=serial))
    while True:
        result = receive().get('data', {})
        if result.get('reqid') == serial:
            log.write(json.dumps(dict(op=op, **result), default=str) + '\n')
            log.flush()
            assert 'error' not in result, result
            return result


def setting(name, value):
    request('LLViewerControl', 'set', group='Global', key=name, value=value)


def get(name):
    result = request('LLViewerControl', 'get', group='Global', key=name)
    return {'F32': float, 'Boolean': bool, 'Color4': list}[result['type']](result['value'])


def button(name):
    request('LLFloaterReg', 'clickButton', name='preferences', button=name)


page = '/main_view/menu_stack/world_panel/Floater View/Preferences/pref core/display/graphics_tab_container/graphics_water_panel/'
base = page + 'WaterScroll/WaterContent/'


def scroll(keysym):
    request('LLWindow', 'keyDown', path=page+'WaterScroll', keysym=keysym)
    request('LLWindow', 'keyUp', keysym=keysym)


def open_tab():
    send('LLFloaterReg', dict(op='showInstance', name='preferences', focus=True))
    button('vtab_display')
    button('htab_graphics_water_panel')
    scroll('HOME')


def click(name):
    for op in ('mouseDown', 'mouseUp'):
        request('LLWindow', op, path=base + name + '/CheckboxCtrl Button', button='LEFT')


def key(name, keysym):
    request('LLWindow', 'keyDown', path=base + name + '/slider_bar', keysym=keysym)
    request('LLWindow', 'keyUp', keysym=keysym)


def enabled(name):
    return request('LLWindow', 'getInfo', path=base + name)['enabled']


def values_match(expected):
    for name, value in expected.items():
        actual=get(name)
        error=max(abs(a-b) for a,b in zip(actual,value)) if isinstance(value,list) else abs(actual-value)
        assert error < .001, (name, value, actual)


time.sleep(2)
for notice in request('LLNotifications', 'listChannelNotifications', channel='AlertModal').get('notifications', []):
    if notice.get('name') == 'FoundLegacyNsisInstallation':
        send('LLNotifications', dict(op='cancel', uuid=notice['id']))

defaults = dict(RenderWaterProceduralWaves=True, RenderWaterWaveStrength=.20, RenderWaterWaveScale=.08,
    RenderWaterCrossSwellStrength=1.20, RenderWaterLocalReflections=True, RenderWaterReflectionStrength=1.,
    RenderWaterRoughnessScale=0., RenderWaterDensityScale=1.20, RenderWaterSunScatteringScale=1., RenderWaterSkyScatteringScale=.95,
    RenderWaterDisplacement=5., RenderWaterShallowDamping=1.,
    RenderWaterDisplacementEnabled=True, RenderWaterDisplacementDistance=64., RenderWaterWindSpeed=.95,
    RenderWaterClarity=.45, RenderWaterRefractionStrength=2., RenderWaterCausticsStrength=2.05, RenderWaterSubmergedLighting=True,
    RenderWaterCustomColors=False, RenderWaterAbsorptionColor=[.0156,.149,.2509,1.],
    RenderWaterScatteringColor=[.0156,.149,.2509,1.])
original = dict(defaults, RenderWaterDisplacementDistance=48., RenderWaterWindSpeed=.8, RenderWaterDisplacement=.75, RenderWaterShallowDamping=.4, RenderWaterProceduralWaves=False, RenderWaterWaveStrength=.8,
    RenderWaterWaveScale=.85, RenderWaterCrossSwellStrength=.4, RenderWaterReflectionStrength=.8,
    RenderWaterRoughnessScale=1.2, RenderWaterDensityScale=.9, RenderWaterSunScatteringScale=.8,
    RenderWaterSkyScatteringScale=1.1, RenderWaterLocalReflections=False,
    RenderWaterClarity=.9, RenderWaterRefractionStrength=.8, RenderWaterCausticsStrength=.8, RenderWaterSubmergedLighting=False,
    RenderWaterCustomColors=True, RenderWaterAbsorptionColor=[.1,.3,.4,1.],
    RenderWaterScatteringColor=[.03,.12,.24,1.])
setting('RenderWater', True)
setting('RenderTransparentWater', True)
setting('RenderVolumeFogIntensity', 1.23)
for name, value in original.items():
    setting(name, value)
open_tab()
waves = ('RenderWaterWaveStrength', 'RenderWaterWaveScale', 'RenderWaterCrossSwellStrength', 'RenderWaterDisplacement', 'RenderWaterShallowDamping', 'RenderWaterDisplacementEnabled', 'RenderWaterDisplacementDistance')
for name in defaults:
    info = request('LLWindow', 'getInfo', path=base + name)
    assert info['visible'] and bool(info['enabled']) == (name not in waves and name != 'RenderWaterCausticsStrength'), info
click('RenderWaterProceduralWaves')
assert get('RenderWaterProceduralWaves') and all(enabled(name) for name in waves)
for name, value in original.items():
    if isinstance(value, float):
        key(name, 'RIGHT')
        step = 1 if name == 'RenderWaterDisplacementDistance' else .01 if name == 'RenderWaterWaveScale' else .05
        assert abs(get(name) - value - step) < .001, name
scroll('HOME')
click('RenderWaterLocalReflections')
assert get('RenderWaterLocalReflections')
scroll('END')
click('RenderWaterSubmergedLighting')
assert get('RenderWaterSubmergedLighting')
click('RenderWaterCustomColors')
assert not enabled('RenderWaterAbsorptionColor') and not enabled('RenderWaterScatteringColor')
click('RenderWaterCustomColors')
assert enabled('RenderWaterAbsorptionColor') and enabled('RenderWaterScatteringColor')
for name in ('RenderWaterAbsorptionColor','RenderWaterScatteringColor'):
    before=get(name)
    for op in ('mouseDown','mouseUp'):
        request('LLWindow',op,path=base+name,button='LEFT')
    paths=request('LLWindow','getPaths')['paths']
    spinner=next(path for path in paths if path.endswith('/rspin'))
    editor=next(path for path in paths if path.startswith(spinner+'/') and path.endswith('/SpinCtrl Editor'))
    request('LLWindow','keyDown',path=editor,keysym='UP')
    request('LLWindow','keyUp',keysym='UP')
    for op in ('mouseDown','mouseUp'):
        request('LLWindow',op,path=spinner.rsplit('/',1)[0]+'/select_btn',button='LEFT')
    assert get(name)[0]>before[0], (name,before,get(name))
assert request('LLViewerWindow', 'saveSnapshot', filename=str(ROOT / 'tmp/water-depth-preferences.png'),
    showui=True, showhud=False)['ok']

scroll('HOME')
height=get('RenderWaterDisplacement')
click('RenderWaterDisplacementEnabled')
assert not get('RenderWaterDisplacementEnabled') and get('RenderWaterDisplacement')==height
for name in ('RenderWaterDisplacement','RenderWaterDisplacementDistance','RenderWaterShallowDamping'):
    assert not enabled(name)
assert enabled('RenderWaterWindSpeed')
click('RenderWaterDisplacementEnabled')
assert get('RenderWaterDisplacement')==height
for name in ('RenderWaterDisplacement','RenderWaterDisplacementDistance','RenderWaterShallowDamping'):
    assert enabled(name)
for name,low,high,step in (('RenderWaterDisplacementDistance',8,128,1),('RenderWaterWindSpeed',0,3,.05)):
    setting(name,low+step)
    key(name,'LEFT');key(name,'LEFT')
    assert abs(get(name)-low)<.001
    setting(name,high-step)
    key(name,'RIGHT');key(name,'RIGHT')
    assert abs(get(name)-high)<.001
setting('RenderWaterDisplacement', .05)
key('RenderWaterDisplacement', 'LEFT')
assert get('RenderWaterDisplacement') == 0 and not enabled('RenderWaterShallowDamping')
key('RenderWaterDisplacement', 'RIGHT')
assert enabled('RenderWaterShallowDamping')
setting('RenderWaterDisplacement', 4.95)
key('RenderWaterDisplacement', 'RIGHT')
key('RenderWaterDisplacement', 'RIGHT')
assert get('RenderWaterDisplacement') == 5
setting('RenderWaterShallowDamping', .05)
key('RenderWaterShallowDamping', 'LEFT')
assert get('RenderWaterShallowDamping') == 0
setting('RenderWaterShallowDamping', .95)
key('RenderWaterShallowDamping', 'RIGHT')
key('RenderWaterShallowDamping', 'RIGHT')
assert get('RenderWaterShallowDamping') == 1
setting('RenderWaterRoughnessScale', .05)
key('RenderWaterRoughnessScale', 'LEFT')
key('RenderWaterRoughnessScale', 'LEFT')
assert get('RenderWaterRoughnessScale') == 0

# Test both requested endpoints through real slider commits, including clamping.
setting('RenderWaterWaveScale', .02)
key('RenderWaterWaveScale', 'LEFT')
key('RenderWaterWaveScale', 'LEFT')
assert abs(get('RenderWaterWaveScale') - .01) < .0001
setting('RenderWaterCrossSwellStrength', 2.95)
key('RenderWaterCrossSwellStrength', 'RIGHT')
key('RenderWaterCrossSwellStrength', 'RIGHT')
assert get('RenderWaterCrossSwellStrength') == 3

# Commit through the sliders so enable/disable callbacks also execute.
for _ in range(17):
    key('RenderWaterReflectionStrength', 'LEFT')
assert get('RenderWaterReflectionStrength') == 0
assert not enabled('RenderWaterRoughnessScale') and not enabled('RenderWaterLocalReflections')
key('RenderWaterReflectionStrength', 'RIGHT')
assert enabled('RenderWaterRoughnessScale') and enabled('RenderWaterLocalReflections')
for _ in range(19):
    key('RenderWaterDensityScale', 'LEFT')
assert get('RenderWaterDensityScale') == 0
assert not enabled('RenderWaterSunScatteringScale') and not enabled('RenderWaterSkyScatteringScale')
assert not enabled('RenderWaterClarity') and not enabled('RenderWaterSubmergedLighting')
key('RenderWaterDensityScale', 'RIGHT')
assert enabled('RenderWaterSunScatteringScale') and enabled('RenderWaterSkyScatteringScale')

scroll('HOME')
button('WaterDefaults')
values_match(defaults)
assert abs(get('RenderVolumeFogIntensity') - 1.23) < .001
assert all(enabled(name)==(name not in ('RenderWaterAbsorptionColor','RenderWaterScatteringColor')) for name in defaults)
time.sleep(.5)
assert request('LLViewerWindow', 'saveSnapshot', filename=str(ROOT / 'tmp/water-preferences.png'),
    showui=True, showhud=False)['ok']
button('Cancel')
values_match(original)

open_tab()
button('WaterDefaults')
button('OK')
open_tab()
key('RenderWaterWaveScale', 'RIGHT')
click('RenderWaterLocalReflections')
button('Cancel')
values_match(defaults)
log.write(json.dumps(dict(result='PASS: Water tab, wave size 0.01, crossing swell 3, roughness 0, fifteen sliders (including displacement 0-5, distance 8-128 m, wind speed 0-3 and shallow damping 0-1), five toggles, two colour-picker commits, dependencies, scoped Default, Cancel and saved OK baseline')) + '\n')
log.close()
send('LLAppViewer', dict(op='requestQuit'))
