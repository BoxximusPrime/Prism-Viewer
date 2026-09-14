"""Offline Photo Tools smoke test. Run with --leap and isolated settings.
Checks actual tab/control visibility, setting commits, destinations and reopening.
World rendering and the native save dialog require an in-world check.
Local exports use a temporary directory without opening the file picker.
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
log = (ROOT/'tmp/photo-tools.jsonl').open('w', encoding='utf-8')
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
for notice in request('LLNotifications', 'listChannelNotifications', channel='AlertModal').get('notifications', []):
    if notice.get('name') == 'FoundLegacyNsisInstallation':
        send('LLNotifications', dict(op='cancel', uuid=notice['id']))
setting('AdvanceSnapshot', False)
setting('AutoSnapshot', False)
setting('RenderDepthOfField', False)
setting('RenderExposure', 1.)
send('LLFloaterReg', dict(op='showInstance', name='snapshot', focus=True))
time.sleep(1)
paths=request('LLWindow','getPaths')['paths']
base=next(p for p in paths if p.endswith('/Snapshot'))+'/'
advanced=base+'advanced_options_panel/'
# The freeze shortcut is scoped to the open photo window.
key(base+'new_snapshot_btn', 'F')
assert get_setting('PhotoFreezeVisuals')
key(base+'new_snapshot_btn', 'F')
assert not get_setting('PhotoFreezeVisuals')
setting('BoxxyFreezeAvatarAnimations', True)
click_path(advanced+'photo_freeze_visuals/CheckboxCtrl Button')
assert get_setting('PhotoFreezeVisuals')
assert not get_setting('FreezeTime')
for control, keysym, mask in (
    ('photo_show_ui', 'U', ['CTL', 'SHIFT']),
    ('photo_show_huds', 'H', ['ALT', 'SHIFT']),
):
    path=advanced+control
    assert request('LLWindow','getInfo',path=path)['value']
    click_path(path+'/CheckboxCtrl Button')
    time.sleep(.2)
    assert not request('LLWindow','getInfo',path=path)['value']
    # Login-screen menus do not dispatch in-world shortcuts. Verify the
    # checkbox round trip here; keyboard restoration needs an in-world check.
    click_path(path+'/CheckboxCtrl Button')
    time.sleep(.2)
    assert request('LLWindow','getInfo',path=path)['value']
send('LLFloaterReg',dict(op='hideInstance',name='snapshot'))
assert not get_setting('PhotoFreezeVisuals')
assert get_setting('BoxxyFreezeAvatarAnimations')
request('LLWindow','keyDown',keysym='F')
request('LLWindow','keyUp',keysym='F')
assert not get_setting('PhotoFreezeVisuals')
setting('BoxxyFreezeAvatarAnimations', False)
send('LLFloaterReg',dict(op='showInstance',name='snapshot',focus=True))
for tab in ('camera','focus','lighting','adjustments','color'):
    click('htab_photo_'+tab)
    for suffix in ('photo_tabs/photo_'+tab,'panel_container/panel_snapshot_local','new_snapshot_btn'):
        info=request('LLWindow','getInfo',path=base+suffix)
        assert info['visible'] and info['enabled'], info
    if tab=='camera':
        camera=base+'photo_tabs/photo_camera/'
        default_fov=get_setting('CameraAngle')
        key(camera+'photo_fov/slider_bar','RIGHT')
        assert abs(get_setting('CameraAngle')-default_fov)>.001
        click('photo_fov_reset')
        assert abs(get_setting('CameraAngle')-default_fov)<.001
        for angle in ('dutch','yaw','pitch'):
            key(camera+'photo_'+angle+'/slider_bar','RIGHT')
            assert float(request('LLWindow','getInfo',path=camera+'photo_'+angle)['value'])>0
            click('photo_'+angle+'_reset')
            assert float(request('LLWindow','getInfo',path=camera+'photo_'+angle)['value'])==0
    if tab=='focus':
        ctrl=base+'photo_tabs/photo_focus/'
        click('photo_pick_focus')
        assert request('LLWindow','getInfo',path=ctrl+'photo_pick_focus')['value']
        click('photo_pick_focus')
        assert not request('LLWindow','getInfo',path=ctrl+'photo_pick_focus')['value']
        click('photo_lock_focus')
        assert request('LLWindow','getInfo',path=ctrl+'photo_lock_focus')['value']
        click('photo_lock_focus')
        assert not request('LLWindow','getInfo',path=ctrl+'photo_lock_focus')['value']
        editor=ctrl+'photo_focus_distance/SpinCtrl Editor'
        key(editor,'F')
        assert not get_setting('PhotoFreezeVisuals') # Typing must not toggle freeze.
        request('LLWindow','keyDown',path=editor,keysym='A',mask=['CTL'])
        request('LLWindow','keyUp',keysym='A',mask=['CTL'])
        # LEAP also emits a literal A after Ctrl+A; remove that synthetic char.
        key(editor,'BACKSP')
        for char in '12.5': key(editor,char)
        key(editor,'ENTER')
        assert abs(float(request('LLWindow','getInfo',path=ctrl+'photo_focus_distance')['value'])-12.5)<.001

        assert not request('LLWindow','getInfo',path=ctrl+'photo_aperture')['enabled']
        click_path(ctrl+'photo_dof/CheckboxCtrl Button')
        assert get_setting('RenderDepthOfField')
        assert request('LLWindow','getInfo',path=ctrl+'photo_aperture')['enabled']
    if tab=='color':
        key(base+'photo_tabs/photo_color/photo_exposure/slider_bar','RIGHT')
        assert abs(get_setting('RenderExposure')-1.05)<.001
        grade=base+'photo_tabs/photo_color/'
        assert not request('LLWindow','getInfo',path=grade+'photo_grade_contrast')['enabled']
        click_path(grade+'photo_grade_enabled/CheckboxCtrl Button')
        assert get_setting('PhotoGradeEnabled')
        for suffix,setting_name in (('contrast','Contrast'),('saturation','Saturation'),('warmth','Warmth'),
                                    ('tint','Tint'),('lift','Lift'),('gamma','Gamma'),('gain','Gain')):
            before=get_setting('PhotoGrade'+setting_name)
            key(grade+'photo_grade_'+suffix+'/slider_bar','RIGHT')
            assert get_setting('PhotoGrade'+setting_name)>before
        click('photo_grade_reset')
        for setting_name,default in (('Contrast',1),('Saturation',1),('Warmth',0),('Tint',0),('Lift',0),('Gamma',1),('Gain',1)):
            assert abs(get_setting('PhotoGrade'+setting_name)-default)<.001
            assert abs(float(request('LLWindow','getInfo',path=grade+'photo_grade_'+setting_name.lower())['value'])-default)<.001
        assert abs(get_setting('RenderExposure')-1.05)<.001
        click_path(grade+'photo_grade_enabled/CheckboxCtrl Button')
        assert not get_setting('PhotoGradeEnabled')

    time.sleep(.5)
    assert request('LLViewerWindow','saveSnapshot',filename=str(ROOT/('tmp/photo-tools-'+tab+'.png')),showui=True,showhud=False)['ok']
click('photo_destinations')
assert request('LLWindow','getInfo',path=base+'panel_container/panel_snapshot_options')['visible']
click('save_to_computer_btn')
assert request('LLWindow','getInfo',path=base+'panel_container/panel_snapshot_local')['visible']
# Save through the real capture panel, using a temporary per-account path in
# this logged-out test process so the native file picker is not needed.
output=ROOT/'tmp/photo-tools-exports'
output.mkdir(exist_ok=True)
request('LLViewerControl','set',group='PerAccount',key='SnapshotBaseDir',value=str(output))
request('LLViewerControl','set',group='PerAccount',key='SnapshotBaseName',value='photo-smoke')
local=base+'panel_container/panel_snapshot_local/'
def select_combo(path,index):
    click_path(path+'/Drop Down Button')
    key(path+'/ComboBox','HOME')
    for _ in range(index): key(path+'/ComboBox','DOWN')
    key(path+'/ComboBox','ENTER')
select_combo(local+'local_size_combo',2) # 640 x 480
for index,extension in enumerate(('png','jpg','bmp')):
    select_combo(local+'local_format_combo',index)
    click('new_snapshot_btn')
    time.sleep(1)
    before=set(output.glob('*.'+extension))
    assert request('LLWindow','getInfo',path=local+'save_btn')['available']
    click('Save Photo')
    for _ in range(20):
        files=set(output.glob('*.'+extension))-before
        if files: break
        time.sleep(.1)
    assert len(files)==1, (extension,files)
    assert next(iter(files)).stat().st_size > 100
    log.write(json.dumps(dict(export=extension,size=[640,480]))+'\n');log.flush()
setting('CameraAngle', .7)
send('LLFloaterReg',dict(op='hideInstance',name='snapshot'))
assert abs(get_setting('CameraAngle')-default_fov)<.001
assert not get_setting('FreezeTime')
send('LLFloaterReg',dict(op='showInstance',name='snapshot',focus=True))
assert request('LLFloaterReg','instanceVisible',name='snapshot')['visible']
for angle in ('dutch','yaw','pitch'):
    assert float(request('LLWindow','getInfo',path=base+'photo_tabs/photo_camera/photo_'+angle)['value'])==0
log.write(json.dumps(dict(result='PASS: F shortcut, focus buttons, camera offset buttons/FOV reset lifecycle, visual freeze lifecycle, independent avatar freeze, UI/HUD toggles, five styled tabs, color-grade bindings/reset/bypass, capture controls, DoF dependency, exposure commit, destination navigation, PNG/JPEG/BMP exports, close/reopen'))+'\n');log.close()
send('LLAppViewer',dict(op='requestQuit'))
