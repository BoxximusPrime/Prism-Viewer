"""Photo Tools overlay controls; run as a LEAP plugin with isolated settings."""
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
log = (ROOT/'tmp/photo-overlays-ui.jsonl').open('w', encoding='utf-8')
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



def key(path, keysym):
    request('LLWindow', 'keyDown', path=path, keysym=keysym)
    request('LLWindow', 'keyUp', keysym=keysym)

def click_path(path):
    for op in ('mouseDown', 'mouseUp'):
        request('LLWindow', op, path=path, button='LEFT')

def click(name):
    request('LLFloaterReg', 'clickButton', name='snapshot', button=name)

atexit.register(lambda: send('LLAppViewer', dict(op='requestQuit')))
time.sleep(6)
for notice in request('LLNotifications','listChannelNotifications',channel='AlertModal').get('notifications',[]):
    if notice.get('name')=='FoundLegacyNsisInstallation':
        send('LLNotifications',dict(op='cancel',uuid=notice['id']))
setting('AutoSnapshot',False)
setting('PhotoCompositionGuide',0)
setting('PhotoCompositionWhite',True)
setting('PhotoCompositionAlpha',.6)
send('LLFloaterReg',dict(op='showInstance',name='snapshot',focus=True))
time.sleep(1)
base=next(p for p in request('LLWindow','getPaths')['paths'] if p.endswith('/Snapshot'))+'/'
click('htab_photo_overlays')
controls=base+'photo_tabs/photo_overlays/'
for name in ('photo_composition_guide','photo_composition_white','photo_composition_alpha'):
    assert request('LLWindow','getInfo',path=controls+name)['available']
request('LLViewerWindow','saveSnapshot',filename=str(ROOT/'tmp/photo-overlays-ui.png'),showui=True,showhud=False)
combo=controls+'photo_composition_guide'
for index in range(7):
    click_path(combo+'/Drop Down Button')
    key(combo+'/ComboBox','HOME')
    for _ in range(index):key(combo+'/ComboBox','DOWN')
    key(combo+'/ComboBox','ENTER')
    assert get_setting('PhotoCompositionGuide')==index
click_path(controls+'photo_composition_white/CheckboxCtrl Button')
assert not get_setting('PhotoCompositionWhite')
click_path(controls+'photo_composition_white/CheckboxCtrl Button')
assert get_setting('PhotoCompositionWhite')
key(controls+'photo_composition_alpha/slider_bar','LEFT')
assert abs(get_setting('PhotoCompositionAlpha')-.55)<.001
assert request('LLViewerWindow','saveSnapshot',filename=str(ROOT/'tmp/photo-overlays-ui.png'),showui=True,showhud=False)['ok']
# The renderer's capture guards are executed separately by test_photo_overlays.py.
# Exercise actual exports with a guide selected and UI inclusion both on/off.
for show_ui in (False,True):
    assert request('LLViewerWindow','saveSnapshot',filename=str(ROOT/f'tmp/photo-overlays-export-{show_ui}.png'),width=640,height=480,showui=show_ui,showhud=False)['ok']
click('llfloater_minimize_btn')
time.sleep(.2)
assert request('LLWindow','getInfo',path=base.rstrip('/'))['rect']['top']-request('LLWindow','getInfo',path=base.rstrip('/'))['rect']['bottom']<50
click_path(base+'llfloater_restore_btn')
send('LLFloaterReg',dict(op='hideInstance',name='snapshot'))
send('LLFloaterReg',dict(op='showInstance',name='snapshot',focus=True))
click('htab_photo_overlays')
assert get_setting('PhotoCompositionGuide')==6
assert abs(get_setting('PhotoCompositionAlpha')-.55)<.001
log.write(json.dumps(dict(result='PASS: seven choices, white/black toggle, alpha slider, UI/non-UI exports, minimize/restore and close/reopen'))+'\n');log.close()
