"""Exercise production link numbers and part cycling without logging into a region."""
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'indra/newview/llfloatertools.cpp').read_text()
start = source.index('static S32 selected_link_number(')
end = source.index('\n}\n', start) + 2
harness = r'''
#include <cassert>
#include <algorithm>
#include <list>
#include <string>
#include <vector>
using S32 = int;
struct LLViewerObject {
    using child_list_t = std::list<LLViewerObject*>;
    bool avatar = false;
    bool selected = false;
    LLViewerObject* parent = nullptr;
    child_list_t children;
    bool isAvatar() const { return avatar; }
    bool isSelected() const { return selected; }
    S32 getNumTEs() const { return 3; }
    LLViewerObject* getRootEdit() {
        return parent && !parent->isAvatar() ? parent->getRootEdit() : this;
    }
    const auto& getChildren() const { return children; }
};
struct LLSD {
    std::string value;
    LLSD(const char* text) : value(text) {}
    std::string asString() const { return value; }
};
struct view_listener_t {
    virtual bool handleEvent(const LLSD&) = 0;
};
struct LLSelectNode {
    LLViewerObject* object;
    S32 face;
    LLViewerObject* getObject() { return object; }
    S32 getLastOperatedTE() { return face; }
};
struct LLObjectSelection {
    std::vector<LLSelectNode> nodes;
    S32 getObjectCount() { return static_cast<S32>(nodes.size()); }
    LLSelectNode* getFirstNode() { return nodes.empty() ? nullptr : &nodes.front(); }
    LLViewerObject* getFirstObject() { return nodes.empty() ? nullptr : nodes.front().object; }
};
struct LLSelectMgr {
    LLObjectSelection selection;
    static LLSelectMgr* getInstance() { static LLSelectMgr instance; return &instance; }
    LLObjectSelection* getSelection() { return &selection; }
    void deselectAll() {
        for (auto& node : selection.nodes) node.object->selected = false;
        selection.nodes.clear();
    }
    void addAsIndividual(LLViewerObject* object, S32 face, bool) {
        for (auto& node : selection.nodes) {
            if (node.object == object) { node.face = face; return; }
        }
        selection.nodes.push_back({object, face});
        object->selected = true;
    }
    void selectObjectOnly(LLViewerObject* object, S32 face = -1) {
        addAsIndividual(object, face, true);
    }
};
struct LLToolFace {
    static LLToolFace* getInstance() { static LLToolFace instance; return &instance; }
};
struct LLToolMgr {
    void* tool = nullptr;
    static LLToolMgr* getInstance() { static LLToolMgr instance; return &instance; }
    void* getCurrentTool() { return tool; }
};
struct Settings {
    bool linked = true;
    bool getBOOL(const char*) { return linked; }
} gSavedSettings;
struct FocusMgr {
    bool focused = true;
    int commits = 0;
    bool childHasKeyboardFocus(void*) { return focused; }
    void setKeyboardFocus(void*) { focused = false; ++commits; }
} gFocusMgr;
void* gFloaterTools = nullptr;
'''
harness += source[start:end]
menu_source = (ROOT / 'indra/newview/llviewermenu.cpp').read_text()
start = menu_source.index('class LLToolsSelectNextPartFace :')
end = menu_source.index('\nclass LLToolsStopAllAnimations', start)
harness += menu_source[start:end]
start = source.index('    bool can_cycle_links = false;')
end = source.index('    for (const char* name :', start)
harness += '\nbool linksEnabled(LLObjectSelection* selection, S32 link_number) {\n'
harness += source[start:end] + 'return can_cycle_links;\n}\n'
harness += r'''
int main() {
    LLViewerObject root, first, second, third, missing, avatar;
    avatar.avatar = true;
    assert(selected_link_number(nullptr, true, 0) == -1);
    assert(selected_link_number(&avatar, true, 1) == -1);
    assert(selected_link_number(&root, true, 1) == 0);
    root.children = {&first, &second, &third};
    first.parent = second.parent = third.parent = missing.parent = &root;
    assert(selected_link_number(&root, true, 1) == 1);
    assert(selected_link_number(&first, true, 1) == 2);
    assert(selected_link_number(&second, true, 1) == 3);
    assert(selected_link_number(&third, true, 1) == 4);
    assert(selected_link_number(&second, false, 1) == -1);
    assert(selected_link_number(&second, true, 0) == -1);
    assert(selected_link_number(&second, true, 2) == -1);
    assert(selected_link_number(&missing, true, 1) == -1);
    // Attachment roots stop at the avatar; seated avatars follow the prims.
    root.parent = &avatar;
    assert(selected_link_number(&root, true, 1) == 1);
    assert(selected_link_number(&third, true, 1) == 4);
    root.parent = nullptr;
    root.children.push_back(&avatar);
    assert(selected_link_number(&third, true, 1) == 4);
    // Relinking and unlinking must change the next lookup immediately.
    root.children = {&third, &first, &second};
    assert(selected_link_number(&third, true, 1) == 2);
    assert(selected_link_number(&second, true, 1) == 4);
    root.children.clear();
    second.parent = nullptr;
    assert(selected_link_number(&root, true, 1) == 0);
    assert(selected_link_number(&second, true, 1) == 0);

    auto* manager = LLSelectMgr::getInstance();
    auto* selection = manager->getSelection();
    LLToolsSelectNextPartFace command;
    view_listener_t& cycle = command;
    auto select = [&](LLViewerObject* object, S32 face = -1) {
        manager->deselectAll();
        manager->selectObjectOnly(object, face);
    };
    auto expect = [&](LLViewerObject* object, S32 face = -1) {
        assert(selection->getObjectCount() == 1);
        assert(selection->getFirstObject() == object);
        assert(selection->getFirstNode()->face == face);
    };
    select(&root);
    assert(!linksEnabled(selection, 0));
    root.children = {&avatar};
    assert(!linksEnabled(selection, 1));
    root.children = {&first, &second, &third, &avatar};
    first.parent = second.parent = third.parent = &root;
    assert(linksEnabled(selection, 1));
    cycle.handleEvent("next_linked"); expect(&first);
    assert(gFocusMgr.commits == 1); // Pending field edits commit before changing selection.
    cycle.handleEvent("next_linked"); expect(&second);
    cycle.handleEvent("previous_linked"); expect(&first);
    cycle.handleEvent("previous_linked"); expect(&root);
    cycle.handleEvent("previous_linked"); expect(&third); // Skip the seated avatar at the end.
    cycle.handleEvent("next_linked"); expect(&root); // Wrap to root.
    root.parent = &avatar;
    cycle.handleEvent("next_linked"); expect(&first);
    cycle.handleEvent("previous_linked"); expect(&root);
    root.parent = nullptr;

    // The new arrows select parts while the existing shortcuts still select faces.
    LLToolMgr::getInstance()->tool = LLToolFace::getInstance();
    select(&first, 1);
    cycle.handleEvent("next_linked"); expect(&second);
    cycle.handleEvent("previous_linked"); expect(&first);
    select(&first, 1);
    cycle.handleEvent("next"); expect(&first, 2);
    cycle.handleEvent("next"); expect(&second, 0);
    cycle.handleEvent("previous"); expect(&first, 2);
    gSavedSettings.linked = false;
    cycle.handleEvent("next_linked"); expect(&first, 2); // Off means no action, including in face mode.
    cycle.handleEvent("previous"); expect(&first, 1);
    gSavedSettings.linked = true;
    LLToolMgr::getInstance()->tool = nullptr;

    select(&root);
    cycle.handleEvent("includenext");
    assert(selection->getObjectCount() == 2 && root.selected && first.selected);
    cycle.handleEvent("next_linked");
    assert(selection->getObjectCount() == 2 && root.selected && first.selected);
    manager->deselectAll();
    cycle.handleEvent("previous_linked");
    assert(selection->getObjectCount() == 0);
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / 'link_number.cpp'
    exe = Path(directory) / 'link_number.exe'
    cpp.write_text(harness)
    subprocess.run(['g++', '-std=c++17', str(cpp), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

floater = ET.parse(ROOT / 'indra/newview/skins/default/xui/en/floater_tools.xml').getroot()
label = floater.find("text[@name='selection_link_number']")
checkbox = floater.find("check_box[@name='checkbox edit linked parts']")
link_button = floater.find("button[@name='link_btn']")
assert label is not None and label.get('visible') == 'false'
assert '[LINK_NUMBER]' in label.text
assert int(checkbox.get('left')) + int(checkbox.get('width')) <= int(label.get('left'))
assert int(label.get('left')) + int(label.get('width')) <= int(link_button.get('left'))
previous = floater.find("button[@name='select_previous_link']")
following = floater.find("button[@name='select_next_link']")
unlink_button = floater.find("button[@name='unlink_btn']")
row = [checkbox, previous, label, following, link_button, unlink_button]
for left, right in zip(row, row[1:]):
    assert int(left.get('left')) + int(left.get('width')) <= int(right.get('left'))
for button, action in [(previous, 'previous_linked'), (following, 'next_linked')]:
    assert button.get('visible') == 'false' and button.get('enabled') == 'false'
    callback = button.find('button.commit_callback')
    assert callback.get('function') == 'Tools.SelectNextPart' and callback.get('parameter') == action
print('Link numbers and cycling: root/child order, attachments, avatar skipping, wrapping, selection gating, face-mode compatibility, and row layout passed.')
