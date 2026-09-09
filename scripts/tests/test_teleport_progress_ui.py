"""Check teleport progress layering and run its real routing/focus methods.

Python stdlib and g++/clang++; no viewer login or messages are sent.
The small C++ doubles supply UI state, not copies of the production methods.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
VIEWER = ROOT / "indra/newview"


def method(filename, signature):
    source = (VIEWER / filename).read_text()
    start = source.index(signature)
    body = source.index("{", start)
    depth = 1
    end = body + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


def main():
    root = ET.parse(VIEWER / "skins/default/xui/en/main_view.xml").getroot()
    world = root.find(".//*[@name='world_panel']")
    world_order = [node.get("name") for node in world]
    # XUI children are drawn in document order, hit-tested in reverse order.
    assert world_order.index("teleport_progress_holder") < world_order.index("Floater View")
    modal = root.find("./*[@name='modal_progress_holder']")
    assert list(root).index(modal) > list(root).index(root.find("./layout_stack"))
    assert list(root).index(modal) < list(root).index(root.find("./menu_holder"))
    progress = modal.find("./*[@name='progress_view']")
    assert progress.get("mouse_opaque") == "true"  # world clicks remain blocked
    assert progress.get("filename") == "panel_progress.xml"
    assert len(root.findall(".//*[@name='progress_view']")) == 1
    for name in ("modal_progress_holder", "teleport_progress_holder"):
        holder = root.find(f".//*[@name='{name}']")
        assert holder.get("mouse_opaque") == "false"  # hidden progress cannot block clicks
        assert holder.get("follows") == "all"

    harness = r'''
#include <cassert>
#include <map>
#include <string>
struct LLView;
LLView* keyboard_focus = nullptr;
struct LLView {
    LLView* parent = nullptr;
    bool visible = false;
    int rect = 0, additions = 0;
    std::map<std::string, LLView*> children;
    LLView* getChildView(const std::string& name) { return children.at(name); }
    template<class T> T* getChild(const std::string& name) { return static_cast<T*>(getChildView(name)); }
    LLView* getParent() { return parent; }
    void addChild(LLView* child) { child->parent = this; ++additions; }
    int getLocalRect() { return rect; }
    void setShape(int value) { rect = value; }
    void setVisible(bool value) { visible = value; }
    bool getVisible() { return visible; }
    void setFocus(bool value) { if (value) keyboard_focus = this; }
};
using LLPanel = LLView;
struct LLTextBox : LLView { void setText(const std::string&) {} };
struct Timer { bool started = false; bool getStarted() { return started; } void stop() { started = false; } };
enum { STATE_LOGIN_WAIT, STATE_STARTED };
struct LLStartUp { static int state; static int getStartupState() { return state; } };
int LLStartUp::state = STATE_LOGIN_WAIT;
bool gTeleportDisplay = false;
struct LLAppViewer {
    static LLAppViewer* instance() { static LLAppViewer app; return &app; }
    std::string getSecondLifeTitle() { return "Prism"; }
};
struct LLProgressView : LLPanel {
    Timer mFadeFromLoginTimer, mFadeToWorldTimer;
    LLView media;
    LLView* mMediaCtrl = &media;
    std::string getString(const std::string& name) { return name; }
    void setVisible(bool visible);
};
struct LLViewerWindow {
    LLView* mRootView;
    LLProgressView* mProgressView;
    void setShowProgress(const bool show);
};
'''
    harness += method("llprogressview.cpp", "void LLProgressView::setVisible(bool visible)")
    harness += method("llviewerwindow.cpp", "void LLViewerWindow::setShowProgress(const bool show)")
    harness += r'''
int main() {
    LLView root, modal, teleport, editor, card;
    LLTextBox title;
    LLProgressView progress;
    progress.children = {{"stack1", &card}, {"title_text", &title}};
    modal.rect = 768;
    teleport.rect = 700;
    root.children = {{"modal_progress_holder", &modal}, {"teleport_progress_holder", &teleport}};
    LLViewerWindow window{&root, &progress};

    // Login remains modal, even if the teleport display flag was left set.
    gTeleportDisplay = true;
    window.setShowProgress(true);
    assert(progress.parent == &modal && keyboard_focus == &progress && progress.visible);
    window.setShowProgress(false);

    // Starting and repeatedly updating travel preserve the DM editor's focus.
    LLStartUp::state = STATE_STARTED;
    keyboard_focus = &editor;
    window.setShowProgress(true);
    assert(progress.parent == &teleport && progress.rect == teleport.rect);
    assert(keyboard_focus == &editor && progress.visible);
    window.setShowProgress(true);
    assert(teleport.additions == 1 && keyboard_focus == &editor);
    window.setShowProgress(false);
    assert(!progress.visible && keyboard_focus == &editor);

    // A second teleport is still interactive; subsequent logout/recovery is modal.
    window.setShowProgress(true);
    assert(keyboard_focus == &editor);
    window.setShowProgress(false);
    gTeleportDisplay = false;
    window.setShowProgress(true);
    assert(progress.parent == &modal && progress.rect == modal.rect);
    assert(keyboard_focus == &progress && progress.visible);
}
'''
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        raise SystemExit("Install g++ or clang++ to run the production-method checks")
    with tempfile.TemporaryDirectory(prefix="prism-teleport-ui-") as temp:
        source = Path(temp) / "check.cpp"
        binary = Path(temp) / "check.exe"
        source.write_text(harness)
        subprocess.run([compiler, "-std=c++17", str(source), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
    print("PASS: teleport layering, world click barrier, focus preservation, repeat travel, and modal fallback")


if __name__ == "__main__":
    main()
