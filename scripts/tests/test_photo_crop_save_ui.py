"""Native crop selection and Save Photo; run as a LEAP plugin with isolated settings."""
import atexit
import json
from pathlib import Path
import sys
import time
import llsd
import struct

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
log = (ROOT/'tmp/photo-crop-save-ui.jsonl').open('w', encoding='utf-8')
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


def key(path, keysym):
    request('LLWindow', 'keyDown', path=path, keysym=keysym)
    request('LLWindow', 'keyUp', keysym=keysym)

atexit.register(lambda: send('LLAppViewer', dict(op='requestQuit')))
time.sleep(6)
for notice in request('LLNotifications','listChannelNotifications',channel='AlertModal').get('notifications',[]):
    if notice.get('name')=='FoundLegacyNsisInstallation':
        send('LLNotifications',dict(op='cancel',uuid=notice['id']))
setting('AutoSnapshot',False)
setting('SnapshotFormat',0)
setting('PhotoCompositionGuide',0)
setting('PhotoCompositionWhite',True)
setting('PhotoCompositionAlpha',.6)
send('LLFloaterReg',dict(op='showInstance',name='snapshot',focus=True))
time.sleep(1)
paths=request('LLWindow','getPaths')['paths']
combo=next(p for p in paths if p.endswith('/local_size_combo'))
save=next(p for p in paths if p.endswith('/save_btn'))
request('LLViewerWindow','saveSnapshot',filename=str(ROOT/'tmp/photo-crop-save-ui.png'),showui=True,showhud=False)
for name, value in [('SnapshotBaseDir',str(ROOT/'tmp')), ('SnapshotBaseName','crop-save-regression')]:
    request('LLViewerControl','set',group='PerAccount',key=name,value=value)
panel=combo.rsplit('/',1)[0]+'/'
for index in (1,2,3,0):
    key(combo,'DOWN')
    key(combo+'/ComboBox','HOME')
    for _ in range(index):key(combo+'/ComboBox','DOWN')
    key(combo+'/ComboBox','ENTER')
    time.sleep(3)
    info=request('LLWindow','getInfo',path=save)
    log.write(json.dumps(dict(index=index,save_info=info))+'\n');log.flush()
    assert info['available'], (index,info)
    selected=request('LLWindow','getInfo',path=combo)['value']
    assert selected == ('[i0,i0]','[i-16,i-9]','[i-4,i-3]','[i-2,i-2]')[index], selected
    dims=tuple(int(request('LLWindow','getInfo',path=panel+'local_snapshot_'+axis)['value']) for axis in ('width','height'))
    before=set((ROOT/'tmp').glob('crop-save-regression_*'))
    request('LLFloaterReg','clickButton',name='snapshot',button='Save Photo')
    time.sleep(2)
    exported=set((ROOT/'tmp').glob('crop-save-regression_*'))-before
    assert len(exported)==1, exported
    data=exported.pop().read_bytes()
    assert data[:8]==b'\x89PNG\r\n\x1a\n'
    actual=struct.unpack('>II',data[16:24])
    # rawSnapshot retains the viewer's existing four-pixel BMP row padding.
    expected=((dims[0]+3)&~3,dims[1])
    assert actual==expected, (actual,expected)
    assert request('LLWindow','getInfo',path=save)['available']
log.write('PASS: all native crop choices leave Save enabled and export at the selected dimensions (with existing row padding)\n');log.flush()
