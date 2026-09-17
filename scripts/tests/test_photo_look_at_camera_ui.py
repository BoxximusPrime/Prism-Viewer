"""Photo Tools look-at-camera control; run as a LEAP plugin with isolated settings."""
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
log = (ROOT/'tmp/photo-look-at-ui.jsonl').open('w', encoding='utf-8')
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
setting('PhotoLookAtCamera',False)
send('LLFloaterReg',dict(op='showInstance',name='snapshot',focus=True))
time.sleep(1)
base=next(p for p in request('LLWindow','getPaths')['paths'] if p.endswith('/Snapshot'))+'/'
click('htab_photo_focus')
control=base+'photo_tabs/photo_focus/photo_look_at_camera'
assert request('LLWindow','getInfo',path=control)['available']
request('LLViewerWindow','saveSnapshot',filename=str(ROOT/'tmp/photo-look-at-ui.png'),showui=True,showhud=False)
time.sleep(.5)
click_path(control+'/CheckboxCtrl Button')
assert get_setting('PhotoLookAtCamera')
assert request('LLViewerWindow','saveSnapshot',filename=str(ROOT/'tmp/photo-look-at-ui.png'),showui=True,showhud=False)['ok']
click_path(control+'/CheckboxCtrl Button')
assert not get_setting('PhotoLookAtCamera')
setting('PhotoFreezeVisuals',True)
click_path(control+'/CheckboxCtrl Button')
assert get_setting('PhotoLookAtCamera') and get_setting('PhotoFreezeVisuals')
click('llfloater_minimize_btn')
assert get_setting('PhotoLookAtCamera')
click_path(base+'llfloater_restore_btn')
send('LLFloaterReg',dict(op='hideInstance',name='snapshot'))
assert not get_setting('PhotoLookAtCamera') and not get_setting('PhotoFreezeVisuals')
send('LLFloaterReg',dict(op='showInstance',name='snapshot',focus=True))
click('htab_photo_focus')
assert not request('LLWindow','getInfo',path=control)['value']
log.write(json.dumps(dict(result='PASS: Look at camera toggle, freeze compatibility, minimize/restore, close reset and unchecked on reopen'))+'\n');log.close()
