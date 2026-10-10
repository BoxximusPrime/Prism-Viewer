"""Exercise production quick-bind text-entry guards and stale state. Requires g++."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "indra/newview/llviewerwindow.cpp").read_text(encoding="utf-8")


def body_after(signature):
    start = source.index("{", source.index(signature)) + 1
    end, depth = start, 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end - 1]


key_body = body_after("bool LLViewerWindow::handleKey(KEY")
key_block = key_body[key_body.index("    if (key == 'E'"):
                     key_body.index("    LLFocusableElement* keyboard_focus")]
char_guard = body_after("bool LLViewerWindow::handleUnicodeChar(").split("    // HACK:")[0]
hover_guard = body_after("bool LLViewerWindow::handleInventoryHoverKey(").split("    const bool collapse_all")[0]

harness = r"""
#include <cassert>
using KEY = int; using MASK = int; using S32 = int; using llwchar = int;
struct LLFocusableElement { virtual ~LLFocusableElement() = default; };
struct LLUICtrl : LLFocusableElement {
    bool text = false;
    bool acceptsTextInput() const { return text; }
};
struct FocusMgr {
    LLFocusableElement* focus = nullptr;
    LLFocusableElement* getKeyboardFocus() { return focus; }
} gFocusMgr;
bool mInventoryShortcutKeyHandled[4] = {};
bool mInventoryShortcutCharHandled[4] = {};
int actions = 0;
bool handle_inventory_action_shortcut(KEY, MASK) { ++actions; return true; }
"""
harness += "bool handleInventoryHoverKey(KEY, MASK) {" + hover_guard + "++actions; return true;}\n"
harness += "bool routeKey(KEY key, MASK mask) {" + key_block + "return false;}\n"
harness += "bool suppressChar(llwchar uni_char) {" + char_guard + "return false;}\n"
harness += r"""
int main() {
    LLUICtrl editor, inventory;
    editor.text = true;
    const char keys[] = {'E', 'T', 'D', 'B'};
    for (int i = 0; i < 4; ++i) {
        for (int mask = 0; mask < 4; ++mask) {
            gFocusMgr.focus = &inventory;
            mInventoryShortcutKeyHandled[i] = false;
            assert(routeKey(keys[i], mask));
            assert(suppressChar(keys[i]));
            const int before = actions;
            assert(routeKey(keys[i], mask) && actions == before); // repeat
            gFocusMgr.focus = &editor;
            assert(!suppressChar(keys[i])); // editor gains focus before character delivery
            assert(!suppressChar(keys[i] + 'a' - 'A'));
            assert(!routeKey(keys[i], mask)); // stale handled flag must not steal input
            assert(!mInventoryShortcutKeyHandled[i] && !mInventoryShortcutCharHandled[i]);
            assert(!routeKey(keys[i], mask) && actions == before);
            assert(!handleInventoryHoverKey(keys[i], mask) && actions == before);
        }
    }
    gFocusMgr.focus = nullptr;
    assert(routeKey('E', 0)); // quick binds still work without a focused editor
}
"""
with tempfile.TemporaryDirectory() as directory:
    cpp, binary = Path(directory) / "check.cpp", Path(directory) / "check.exe"
    cpp.write_text(harness, encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print("Quick-bind text entry, focus changes, repeat routing and character guards passed.")
