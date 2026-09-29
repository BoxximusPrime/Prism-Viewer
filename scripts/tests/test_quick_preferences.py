"""Run as a LeapCommand plugin with isolated --settings; tests real Quick Prefs controls."""
import atexit
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
log = (ROOT/'tmp/quick-preferences.jsonl').open('w', encoding='utf-8')
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


atexit.register(lambda: send('LLAppViewer', dict(op='requestQuit')))

base = '/main_view/menu_stack/world_panel/Floater View/quick_preferences/'

def key(path, keysym, mask=None):
    request('LLWindow', 'keyDown', path=path, keysym=keysym, mask=mask or [])
    request('LLWindow', 'keyUp', keysym=keysym, mask=mask or [])

def choose(index):
    key(base+'graphics', 'DOWN')
    key(base+'graphics/ComboBox', 'HOME')
    for _ in range(index): key(base+'graphics/ComboBox', 'DOWN')
    key(base+'graphics/ComboBox', 'ENTER')

def click(name):
    for op in ('mouseDown', 'mouseUp'):
        request('LLWindow', op, path=base+name+'/CheckboxCtrl Button', button='LEFT')

time.sleep(3)
for notice in request('LLNotifications', 'listChannelNotifications', channel='AlertModal').get('notifications', []):
    if notice.get('name') == 'FoundLegacyNsisInstallation':
        send('LLNotifications', dict(op='cancel', uuid=notice['id']))
names = ('RenderShadowResolutionScale', 'RenderPCSSQuality', 'RenderGTAOQuality')
config = llsd.parse((ROOT/'indra/newview/app_settings/settings.xml').read_bytes())
defaults = {n: config[n]['Value'] for n in names}
defaults['RenderPCSSQuality'] = 0  # Quick Prefs' Default is the Performance preset.
setting('RenderFarClip', 128.)
setting('RenderGTAOStrength', 1.25)
send('LLFloaterReg', dict(op='showInstance', name='quick_preferences', focus=True))
time.sleep(.5)
for name in ('graphics','draw_distance','camera_smoothing','camera_smoothing_default','name_tags','look_targets','sky','water','day','shared'):
    info = request('LLWindow', 'getInfo', path=base+name)
    assert info['visible'] and info['enabled'], info
request('LLViewerWindow', 'saveSnapshot', filename=str(ROOT/'tmp/quick-preferences.png'), showui=True, showhud=False)
choose(1)
for name in names: assert get_setting(name) == 2, name
assert get_setting('RenderGTAOStrength') == 1.25
choose(0)
for name in names: assert get_setting(name) == float(defaults[name]), name
assert get_setting('RenderGTAOStrength') == 1.25
setting('AvatarNameTagMode', 1)
time.sleep(.2)
click('name_tags')
assert get_setting('AvatarNameTagMode') == 0
click('name_tags')
assert get_setting('AvatarNameTagMode') == 1
old = get_setting('ShowLookAtTargets')
click('look_targets')
assert get_setting('ShowLookAtTargets') != old
key(base+'draw_distance/slider_bar', 'RIGHT')
assert get_setting('RenderFarClip') == 136
setting('BoxxyCameraSmoothing', .1)
setting('CameraPositionSmoothing', 3.)
setting('ZoomTime', .8)
key(base+'camera_smoothing/slider_bar', 'RIGHT')
assert abs(get_setting('BoxxyCameraSmoothing')-.11) < .0001
editor = base+'camera_smoothing/slider editor'
key(editor, 'A', ['CTL'])
for char in '0.37': key(editor, char)
key(editor, 'ENTER')
assert abs(get_setting('BoxxyCameraSmoothing')-.37) < .0001
request('LLFloaterReg', 'hideInstance', name='quick_preferences')
request('LLFloaterReg', 'showInstance', name='quick_preferences', focus=True)
assert abs(float(request('LLWindow', 'getInfo', path=editor)['value'])-.37) < .0001
for value, direction in ((0., 'LEFT'), (1., 'RIGHT')):
    setting('BoxxyCameraSmoothing', value)
    key(base+'camera_smoothing/slider_bar', direction)
    assert get_setting('BoxxyCameraSmoothing') == value
request('LLFloaterReg', 'clickButton', name='quick_preferences', button='camera_smoothing_default')
assert abs(get_setting('BoxxyCameraSmoothing')-config['BoxxyCameraSmoothing']['Value']) < .0001
assert abs(float(request('LLWindow', 'getInfo', path=editor)['value'])-config['BoxxyCameraSmoothing']['Value']) < .0001
assert get_setting('CameraPositionSmoothing') == 3. and abs(get_setting('ZoomTime')-.8) < .0001
assert not request('LLWindow', 'getInfo', path=base+'hover')['enabled']
request('LLFloaterReg', 'clickButton', name='quick_preferences', button='shared')
assert request('LLViewerWindow', 'saveSnapshot', filename=str(ROOT/'tmp/quick-preferences.png'), showui=True, showhud=False)['ok']
log.write(json.dumps(dict(result='PASS: layout, Ultra/Default, unrelated settings preserved, name tags, look targets, draw distance, camera smoothing slider/text/range/default/reopen, logged-out hover guard, shared reset'))+'\n')
log.close()
send('LLAppViewer', dict(op='requestQuit'))
