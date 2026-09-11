"""Check the production field-reset routine with grouped, scrollable forms."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "indra/llui/llpanel.cpp").read_text()
start = source.index("void LLPanel::clearCtrls()")
end = source.index("\nvoid LLPanel::setCtrlsEnabled", start)

harness = r'''
#include <cassert>
#include <vector>
struct LLView {
    using child_list_t = std::vector<LLView*>;
    child_list_t children;
    LLView* parent = nullptr;
    bool enabled = true;
    virtual ~LLView() = default;
    virtual bool isCtrl() const { return false; }
    const child_list_t* getChildList() const { return &children; }
    void add(LLView& child) { children.push_back(&child); child.parent = this; }
    bool canClick() const { return enabled && (!parent || parent->canClick()); }
};
struct LLUICtrl : LLView {
    bool focused = true;
    int clearCount = 0;
    bool isCtrl() const override { return true; }
    void setFocus(bool value) { focused = value; }
    void setEnabled(bool value) { enabled = value; }
    void clear() { ++clearCount; }
};
struct LLPanel : LLUICtrl {
    using ctrl_list_t = std::vector<LLUICtrl*>;
    ctrl_list_t getCtrlList() const {
        ctrl_list_t result;
        for (auto* child : children)
            if (child->isCtrl()) result.push_back(static_cast<LLUICtrl*>(child));
        return result;
    }
    void clearCtrls();
};
struct LLScrollContainer : LLUICtrl {
    LLView* content = nullptr;
    LLView* getScrolledView() const { return content; }
};
'''
harness += source[start:end]
harness += r'''
int main() {
    // Object has direct fields in a scrolled panel; Features/Texture add sections.
    for (bool grouped : {false, true}) {
        LLPanel tab, body, section;
        LLScrollContainer scroll;
        LLUICtrl scrollbar, field, restrictedField, spinnerArrow;
        tab.add(scroll); scroll.add(scrollbar); scroll.add(body); scroll.content = &body;
        if (grouped) body.add(section);
        LLPanel& owner = grouped ? section : body;
        owner.add(field); owner.add(restrictedField); field.add(spinnerArrow);
        for (int cycle = 0; cycle < 3; ++cycle) {
            // No selection clears fields; layout and scrollbars stay usable.
            tab.clearCtrls();
            assert(scroll.canClick() && body.canClick());
            assert(!field.canClick() && !restrictedField.canClick());
            assert(!field.focused && field.clearCount == cycle + 1);
            assert(scrollbar.enabled && scrollbar.clearCount == 0);
            assert(spinnerArrow.enabled && spinnerArrow.clearCount == 0);
            // Existing selection code re-enables permitted fields individually.
            field.setEnabled(true);
            assert(field.canClick() && spinnerArrow.canClick());
            assert(!restrictedField.canClick());
        }
    }
    // Preserve the original flat-panel behavior used by parcel audio/media.
    LLPanel flat;
    LLUICtrl field;
    flat.add(field); flat.clearCtrls();
    assert(!field.enabled && !field.focused && field.clearCount == 1);
    field.setEnabled(true); assert(field.canClick());
    // Empty layout containers are harmless.
    LLPanel empty;
    LLScrollContainer scroll;
    empty.add(scroll); empty.clearCtrls();
    assert(scroll.enabled);
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / "panel_clear.cpp"
    exe = Path(directory) / "panel_clear.exe"
    cpp.write_text(harness)
    subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("Grouped field reset/re-enable cycles, permissions, scrollbars, composite controls, and flat panels passed.")
