"""Check the rebindable fullscreen action. Run with Python; requires g++."""
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[2]
source = (root / 'indra/newview/llviewerinput.cpp').read_text()
start = source.index('bool toggle_borderless_fullscreen(EKeystate s)')
end = source.index('\n}\n', start) + 3
handler = source[start:end]
assert 'REGISTER_KEYBOARD_GLOBAL_ACTION("toggle_borderless_fullscreen", toggle_borderless_fullscreen);' in source
start = source.index('bool LLViewerInput::handleGlobalBindsKeyDown(')
end = source.index('\n}\n', start) + 3
assert 'gKeyboard->getKeyRepeated(key)' in source[start:end]
assert 'LLSetKeyBindDialog::isRecording()' in source[start:end]

bindings = ET.parse(root / 'indra/newview/app_settings/key_bindings.xml').getroot()
for mode in ('first_person', 'third_person', 'sitting', 'edit_avatar'):
    matches = [b for b in bindings.find(mode) if b.get('command') == 'toggle_borderless_fullscreen']
    assert len(matches) == 1
    assert matches[0].get('key') == 'F11' and matches[0].get('mask') == 'NONE'
rows = ET.parse(root / 'indra/newview/skins/default/xui/en/control_table_contents_media.xml').getroot()
row = next(r for r in rows if r.get('value') == 'toggle_borderless_fullscreen')
assert row.get('enabled') != 'false'
assert row.find('columns').get('value') == 'Toggle Borderless Fullscreen'

harness = '''
#include <cassert>
#include <string>
enum EKeystate { KEYSTATE_DOWN, KEYSTATE_UP, KEYSTATE_LEVEL };
struct Settings {
    bool enabled = false; int changes = 0;
    bool getBOOL(const std::string& name) { assert(name == "BorderlessFullscreen"); return enabled; }
    void setBOOL(const std::string& name, bool value) {
        assert(name == "BorderlessFullscreen"); enabled = value; ++changes;
    }
} gSavedSettings;
''' + handler + '''
int main() {
    assert(toggle_borderless_fullscreen(KEYSTATE_DOWN) && gSavedSettings.enabled);
    assert(toggle_borderless_fullscreen(KEYSTATE_LEVEL) && gSavedSettings.enabled);
    assert(toggle_borderless_fullscreen(KEYSTATE_UP) && gSavedSettings.enabled);
    assert(gSavedSettings.changes == 1);
    assert(toggle_borderless_fullscreen(KEYSTATE_DOWN) && !gSavedSettings.enabled);
    assert(gSavedSettings.changes == 2);
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp, binary = Path(directory) / 'check.cpp', Path(directory) / 'check.exe'
    cpp.write_text(harness)
    subprocess.run(['g++', '-std=c++17', str(cpp), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print('Fullscreen toggle, global repeat guard, default bindings and Controls row passed.')
