"""Run the worn-attachment filter and hover logic without a region connection."""
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "indra/newview/llfloaterwornattachments.cpp").read_text()


def function(signature):
    start = source.index(signature)
    return source[start:source.index("\n}\n", start) + 2]


harness = r'''
#include <algorithm>
#include <cassert>
#include <cctype>
#include <map>
#include <set>
#include <string>
#include <vector>
using LLUUID = std::string;
using S32 = int;
struct LLSD {
    std::string text;
    LLUUID asUUID() const { return text; }
};
struct LLStringUtil {
    static inline const std::string null;
    static void toLower(std::string& s) {
        std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return std::tolower(c); });
    }
    static void trim(std::string& s) {
        auto first = s.find_first_not_of(" \t\r\n");
        s = first == s.npos ? "" : s.substr(first, s.find_last_not_of(" \t\r\n") - first + 1);
    }
};
struct LLScrollListItem {
    LLUUID creator, object;
    LLSD getAltValue() { return {object}; }
};
struct LLNameListCtrl {
    enum { INDIVIDUAL };
    struct Cell {
        std::string name, text;
        Cell& column(const char* s) { name = s; return *this; }
        Cell& value(const std::string& s) { text = s; return *this; }
    };
    struct Columns : std::vector<Cell> { Cell& add() { emplace_back(); return back(); } };
    struct NameItem { LLUUID value, alt_value; int target; Columns columns; };
    std::vector<LLScrollListItem> rows;
    std::vector<NameItem> data;
    void addNameItemRow(const NameItem& row) {
        rows.push_back({row.value, row.alt_value}); data.push_back(row);
    }
    void deleteAllItems() { rows.clear(); data.clear(); }
    S32 getItemCount() { return rows.size(); }
    LLScrollListItem* hitItem(S32 x, S32 y) {
        return x >= 0 && y >= 0 && y < rows.size() ? &rows[y] : nullptr;
    }
};
struct LLFilterEditor { std::string text; std::string getText() { return text; } };
struct LLTextBox { std::string text; void setText(const std::string& s) { text = s; } };
struct LLViewerObject;
using LLVOAvatar = LLViewerObject;
struct Drawable {
    bool dead = false, volume = true;
    bool isDead() { return dead; }
    Drawable* getVOVolume() { return volume ? this : nullptr; }
};
struct LLViewerObject {
    LLUUID id;
    bool dead = false, attachment = true, hud = false, is_avatar = false, region = true;
    LLVOAvatar* owner = nullptr;
    Drawable* mDrawable = nullptr;
    std::vector<LLViewerObject*> children;
    bool isDead() { return dead; }
    bool isAttachment() { return attachment; }
    bool isHUDAttachment() { return hud; }
    LLVOAvatar* asAvatar() { return is_avatar ? this : nullptr; }
    LLVOAvatar* getAvatar() { return owner; }
    LLUUID getID() { return id; }
    void* getRegion() { return region ? this : nullptr; }
    void addThisAndNonJointChildren(std::vector<LLViewerObject*>& objects) {
        objects.push_back(this); objects.insert(objects.end(), children.begin(), children.end());
    }
};
struct ObjectList {
    std::map<LLUUID, LLViewerObject*> objects;
    LLViewerObject* findObject(const LLUUID& id) {
        auto i = objects.find(id); return i == objects.end() ? nullptr : i->second;
    }
} gObjectList;
struct FocusMgr { bool focus = true; bool getAppHasFocus() { return focus; } } gFocusMgr;
struct LLUI {
    S32 x = 0, y = 0;
    static LLUI* getInstance() { static LLUI ui; return &ui; }
    void getMousePositionLocal(LLNameListCtrl*, S32* a, S32* b) { *a = x; *b = y; }
};
struct LLFloaterWornAttachments {
    struct PendingAttachment {
        std::string mPointName, mName;
        LLUUID mCreatorID;
        bool mTransientSelection = false;
    };
    LLUUID mAvatarID;
    LLNameListCtrl* mAttachmentList;
    LLFilterEditor* mFilterEditor;
    LLTextBox* mStatusText;
    std::string mFilter;
    bool mMouseOverList = true, visible = true, minimized = false;
    std::map<LLUUID, PendingAttachment> mPendingAttachments;
    std::set<LLUUID> mReceivedAttachments;
    std::vector<LLUUID> released;
    bool getVisible() { return visible; }
    bool isShown() { return visible && !minimized; }
    std::string getString(const char* key) { return key; }
    void releaseTransientSelection(const LLUUID& id) { released.push_back(id); }
    static void processObjectProperties(const LLUUID&, const LLUUID&, const std::string&);
    void filterAttachments();
    void updateStatus();
    static LLViewerObject* getHoveredAttachment();
    void addAttachment(const LLUUID&, const LLUUID&, const std::string&);
};
struct LLFloaterReg {
    static inline LLFloaterWornAttachments* instance = nullptr;
    template<typename T> static T* findTypedInstance(const char*) { return instance; }
};
'''
for name, result in [
    ("processObjectProperties", "void"), ("filterAttachments", "void"),
    ("updateStatus", "void"), ("getHoveredAttachment", "LLViewerObject*"),
    ("addAttachment", "void"),
]:
    harness += function(f"{result} LLFloaterWornAttachments::{name}(") + "\n"

# Exercise the actual render-dispatch block as well; the Release build checks
# its integration with the existing posed-mesh renderer and graphics types.
selection_source = (ROOT / "indra/newview/llselectmgr.cpp").read_text()
start = selection_source.index("    // Preview worn attachments")
end = selection_source.index("    if (mSelectedObjects->getNumNodes())", start)
harness += r'''
struct LLSelectNode {
    bool transient = false, all = false;
    LLSelectNode(LLViewerObject*, bool) {}
    void setTransient(bool b) { transient = b; }
    void selectAllTEs(bool b) { all = b; }
};
std::vector<LLUUID> rendered;
const int sHighlightInspectColor = 1;
void renderMeshSelection_f(LLSelectNode* node, LLViewerObject* object, int) {
    assert(node->transient && node->all); rendered.push_back(object->id);
}
void render(bool for_hud) {
'''
harness += selection_source[start:end] + "}\n"
harness += r'''
int main() {
    LLNameListCtrl list;
    LLFilterEditor filter;
    LLTextBox status;
    LLFloaterWornAttachments f;
    f.mAttachmentList = &list; f.mFilterEditor = &filter; f.mStatusText = &status;
    LLFloaterReg::instance = &f;
    f.mAvatarID = "avatar";
    LLViewerObject avatar, other_avatar, boots, hair, unnamed, child, bad_child;
    avatar.id = "avatar"; avatar.is_avatar = true;
    other_avatar.id = "other"; other_avatar.is_avatar = true;
    boots.id = "boots"; hair.id = "hair"; unnamed.id = "unnamed";
    boots.owner = hair.owner = unnamed.owner = &avatar;
    gObjectList.objects = {{avatar.id, &avatar}, {boots.id, &boots}, {hair.id, &hair}, {unnamed.id, &unnamed}};
    f.mPendingAttachments = {{"boots", {"Left Foot"}}, {"hair", {"Skull"}}, {"unnamed", {"Chest"}}};
    f.updateStatus(); assert(status.text == "loading");
    filter.text = "  BOOT  "; f.filterAttachments();
    f.processObjectProperties("hair", "same-creator", "Long Hair");
    assert(list.getItemCount() == 0 && status.text == "loading");
    f.processObjectProperties("boots", "same-creator", "Leather Boots");
    assert(list.getItemCount() == 1 && list.rows[0].object == "boots");
    assert(list.rows[0].creator == "same-creator" && status.text == "loading");
    f.processObjectProperties("unnamed", "third-creator", "");
    assert(status.text.empty());
    f.processObjectProperties("boots", "wrong", "Duplicate");
    f.processObjectProperties("unrequested", "wrong", "Unknown");
    assert(f.released.size() == 3 && list.getItemCount() == 1);
    filter.text = "sKuLl"; f.filterAttachments();
    assert(list.getItemCount() == 1 && list.rows[0].object == "hair");
    filter.text = "no match"; f.filterAttachments();
    assert(list.getItemCount() == 0 && status.text == "no_matches");
    assert(!f.getHoveredAttachment());
    filter.text = "unnamed"; f.filterAttachments();
    assert(list.getItemCount() == 1 && list.rows[0].object == "unnamed");
    filter.text = "   "; f.filterAttachments();
    assert(list.getItemCount() == 3 && status.text.empty() && f.released.size() == 3);
    assert(f.getHoveredAttachment() == &boots);
    // Distinct objects retain their identity even when their creator is the same.
    std::swap(list.rows[0], list.rows[1]);
    assert(f.getHoveredAttachment() == &hair);
    LLUI::getInstance()->y = 1;
    assert(f.getHoveredAttachment() == &boots);
    LLUI::getInstance()->y = 10; assert(!f.getHoveredAttachment());
    LLUI::getInstance()->y = 1;
    f.mMouseOverList = false; assert(!f.getHoveredAttachment()); f.mMouseOverList = true;
    f.visible = false; assert(!f.getHoveredAttachment()); f.visible = true;
    f.minimized = true; assert(!f.getHoveredAttachment()); f.minimized = false;
    gFocusMgr.focus = false; assert(!f.getHoveredAttachment()); gFocusMgr.focus = true;
    boots.dead = true; assert(!f.getHoveredAttachment()); boots.dead = false;
    boots.attachment = false; assert(!f.getHoveredAttachment()); boots.attachment = true;
    boots.hud = true; assert(!f.getHoveredAttachment()); boots.hud = false;
    boots.owner = &other_avatar; assert(!f.getHoveredAttachment()); boots.owner = &avatar;
    avatar.dead = true; assert(!f.getHoveredAttachment()); avatar.dead = false;
    gObjectList.objects.erase("boots"); assert(!f.getHoveredAttachment()); gObjectList.objects["boots"] = &boots;
    Drawable drawable;
    boots.mDrawable = child.mDrawable = &drawable;
    child.id = "child"; bad_child.id = "not-loaded";
    boots.children = {&child, &bad_child};
    render(false); assert((rendered == std::vector<LLUUID>{"boots", "child"}));
    rendered.clear(); render(true); assert(rendered.empty());
    boots.region = false; child.dead = true;
    render(false); assert(rendered.empty());
    boots.region = true; child.dead = false; drawable.dead = true;
    render(false); assert(rendered.empty()); drawable.dead = false;
    drawable.volume = false; render(false); assert(rendered.empty());
    f.mPendingAttachments.clear(); f.mReceivedAttachments.clear();
    f.filterAttachments(); assert(status.text == "no_attachments");
    gObjectList.objects.erase("avatar"); f.filterAttachments();
    assert(status.text == "avatar_unavailable");
    LLFloaterReg::instance = nullptr; assert(!f.getHoveredAttachment());
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / "worn_attachments.cpp"
    exe = Path(directory) / "worn_attachments.exe"
    cpp.write_text(harness)
    subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

ui = ET.parse(ROOT / "indra/newview/skins/default/xui/en/floater_worn_attachments.xml").getroot()
search = ui.find("filter_editor[@name='attachment_filter']")
rows = ui.find("name_list[@name='attachments']")
assert int(search.get("top")) + int(search.get("height")) <= int(rows.get("top"))
assert search.get("left") == rows.get("left") and search.get("right") == rows.get("right")
assert search.get("follows") == "left|right|top" and rows.get("follows") == "all"
print("Worn attachments: filtering, late replies, clear/no matches, creator identity, hover lifecycle, linkset rendering dispatch, and search layout passed.")
