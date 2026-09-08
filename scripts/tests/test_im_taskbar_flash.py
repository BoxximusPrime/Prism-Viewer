"""Exercise production taskbar guards with C++ stubs; no viewer build required."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
im = (root / "indra/newview/llimview.cpp").read_text(encoding="utf-8")
win = (root / "indra/llwindow/llwindowwin32.cpp").read_text(encoding="utf-8")
processing = (root / "indra/newview/llimprocessing.cpp").read_text(encoding="utf-8")
guard = im.split("        // Only accepted resident chat requests attention,", 1)[1]
guard = guard[guard.index("        if ("):guard.index("\n    }\n")]
flash = win.split("void LLWindowWin32::flashIcon(F32 seconds)", 1)[1].split("\nF32 LLWindowWin32::getGamma", 1)[0]
focus = win.split("        case WM_SETFOCUS:", 1)[1]
focus = focus[focus.index("            FLASHWINFO"):focus.index("            WINDOW_IMP_POST")]
assert "flashIcon" not in processing
assert "LLStringUtil::null, dialog);" in processing  # Auto-responses retain their type.
assert "false, timestamp, LLUUID::null, SYSTEM_FROM);" in processing
program = r'''
#include <cassert>
#include <functional>
#include <string>
using F32 = float; using UINT = unsigned; using DWORD = unsigned long;
constexpr int FLASHW_STOP = 0, FLASHW_TRAY = 2;
constexpr float ICON_FLASH_TIME = .5f;
struct FLASHWINFO { unsigned cbSize; int hwnd; unsigned dwFlags, uCount, dwTimeout; };
int foreground = 2, flashes = 0, last_flag = -1;
int GetForegroundWindow() { return foreground; }
void FlashWindowEx(FLASHWINFO* f) { ++flashes; last_flag = f->dwFlags; }
struct Thread { std::function<void()> queued; void post(std::function<void()> f) { queued = f; } } thread;
struct Window { int mWindowHandle = 1; Thread* mWindowThread = &thread; void flashIcon(F32 seconds);
    Window* getWindow() { return this; } } viewer;
Window* gViewerWindow = &viewer;
void Window::flashIcon(F32 seconds)
''' + flash + r'''
void focus_window() { int h_wnd = 1;
''' + focus + r'''
}
struct ID { int value; bool notNull() const { return value != 0; }
    bool operator!=(int rhs) const { return value != rhs; } };
constexpr int gAgentID = 1, IM_NOTHING_SPECIAL = 0, IM_SESSION_INVITE = 13, IM_SESSION_SEND = 17;
const std::string SYSTEM_FROM = "Second Life";
struct Agent { bool dnd = false; bool isDoNotDisturb() { return dnd; } } gAgent;
bool session_exists = true;
bool hasSession(int) { return session_exists; }
void receive(int dialog, ID display_id = {2}, std::string message_display_name = "Resident",
    bool is_region_msg = false, std::string msg = "Hello") {
    int new_session_id = 1;
''' + guard + r'''
}
bool requested(int dialog, ID sender = {2}, std::string name = "Resident", bool region = false,
    std::string msg = "Hello") {
    thread.queued = nullptr;
    receive(dialog, sender, name, region, msg);
    return bool(thread.queued);
}
int main() {
    for (int dialog = 0; dialog < 50; ++dialog)
        assert(requested(dialog) == (dialog == 0 || dialog == 13 || dialog == 17));
    assert(!requested(0, {1})); // Self echo.
    assert(!requested(0, {0})); // System sender.
    assert(!requested(0, {2}, SYSTEM_FROM));
    assert(!requested(0, {2}, "Resident", true));
    assert(!requested(0, {2}, "Resident", false, ""));
    gAgent.dnd = true; assert(!requested(0)); gAgent.dnd = false;
    session_exists = false; assert(!requested(0)); session_exists = true;
    gViewerWindow = nullptr; assert(!requested(0)); gViewerWindow = &viewer;
    assert(requested(0)); thread.queued(); assert(flashes == 1 && last_flag == FLASHW_TRAY);
    focus_window(); assert(flashes == 2 && last_flag == FLASHW_STOP);
    foreground = 2; assert(requested(0)); foreground = 1;
    thread.queued(); assert(flashes == 2); // Focus acquired while request was queued.
    assert(requested(17)); thread.queued(); assert(flashes == 2); // Already foreground.
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / "test.cpp"
    exe = Path(directory) / "test.exe"
    cpp.write_text(program, encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("IM taskbar message filtering and focus checks passed")
