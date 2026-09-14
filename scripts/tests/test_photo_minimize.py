"""Offline Photo Tools minimize/restore regression, run via LEAP with isolated settings."""
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
log = (ROOT/'tmp/photo-minimize.jsonl').open('w', encoding='utf-8')
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

time.sleep(6)
for notice in request('LLNotifications','listChannelNotifications',channel='AlertModal').get('notifications',[]):
    if notice.get('name')=='FoundLegacyNsisInstallation':
        send('LLNotifications',dict(op='cancel',uuid=notice['id']))
setting('AutoSnapshot',False)
send('LLFloaterReg',dict(op='showInstance',name='snapshot',focus=True))
time.sleep(2)
base=next(p for p in request('LLWindow','getPaths')['paths'] if p.endswith('/Snapshot'))+'/'
expanded=request('LLWindow','getInfo',path=base.rstrip('/'))['rect']
setting('PhotoFreezeVisuals',True)
setting('AutoSnapshot',True)
for i in range(3):
    click('llfloater_minimize_btn')
    time.sleep(2)
    info=request('LLWindow','getInfo',path=base.rstrip('/'))
    assert info['rect']['top']-info['rect']['bottom']<50
    assert get_setting('PhotoFreezeVisuals')
    # Keep focus off the login text fields after minimizing.
    key(base+'llfloater_restore_btn','F')
    assert not get_setting('PhotoFreezeVisuals')
    # Keep focus off the login text fields after minimizing.
    key(base+'llfloater_restore_btn','F')
    assert get_setting('PhotoFreezeVisuals')
    # The floater registry rejects minimized windows; click its visible title-bar control.
    click_path(base+'llfloater_restore_btn')
    time.sleep(1)
    restored=request('LLWindow','getInfo',path=base.rstrip('/'))['rect']
    assert restored['top']-restored['bottom']==expanded['top']-expanded['bottom']
    click('new_snapshot_btn')
    time.sleep(1)
send('LLFloaterReg',dict(op='hideInstance',name='snapshot'))
assert not get_setting('PhotoFreezeVisuals')
log.write(json.dumps(dict(result='PASS: three minimize/restore cycles, F while minimized, preview refresh and close'))+'\n');log.close()
send('LLAppViewer',dict(op='requestQuit'))
