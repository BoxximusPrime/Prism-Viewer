"""Exercise photo readiness, collection filtering and mannequin controls with API stubs."""
from pathlib import Path
import re
import subprocess
import tempfile
from test_camera_smoothing import function

ROOT = Path(__file__).resolve().parents[2]
PATH = 'indra/newview/llfloaterquickphoto.cpp'
source = (ROOT / PATH).read_text(encoding='utf-8')
code = r'''
#include <cassert>
#include <cstdio>
#include <map>
#include <set>
#include <string>
#include <vector>
using LLUUID = int;
using S32 = int;
namespace LLFolderType { enum { FT_NONE, FT_OUTFIT, FT_TRASH }; }
namespace LLAssetType { enum { AT_OBJECT, AT_CLOTHING, AT_BODYPART, AT_NOTECARD }; }
struct Category {
    int id=10, parent=20, type=LLFolderType::FT_NONE;
    int getUUID() const { return id; }
    int getParentUUID() const { return parent; }
    int getPreferredType() const { return type; }
};
struct Item {
    int id, type; std::string name; bool broken=false;
    bool getIsBrokenLink() const { return broken; }
    int getType() const { return type; }
    int getLinkedUUID() const { return id; }
    std::string getName() const { return name; }
};
struct LLInventoryModel {
    using cat_array_t = std::vector<Category*>;
    using item_array_t = std::vector<Item*>;
    enum { EXCLUDE_TRASH };
    Category folder;
    item_array_t items;
    cat_array_t cats;
    bool exists=true, trashed=false;
    std::set<int> incomplete;
    Category* getCategory(int) { return exists ? &folder : nullptr; }
    int findCategoryUUIDForType(int) { return 99; }
    int getRootFolderID() { return 1; }
    bool isObjectDescendentOf(int, int parent) { return parent==1 || trashed; }
    bool isCategoryComplete(int id) { return !incomplete.count(id); }
    void collectDescendents(int, cat_array_t& c, item_array_t& i, int) { c=cats; i=items; }
} gInventory;
struct Avatar {
    bool loaded=true, sitting=false;
    bool isFullyLoaded() { return loaded; }
    bool isSitting() { return sitting; }
} avatar, *gAgentAvatarp=&avatar;
bool isAgentAvatarValid() { return gAgentAvatarp; }
struct Agent {
    bool visible=true;
    bool needsRenderAvatar() { return visible; }
    bool needsRenderHead() { return visible; }
} gAgent;
struct LLAppearanceMgr {
    bool locked=false;
    static LLAppearanceMgr& instance() { static LLAppearanceMgr mgr; return mgr; }
    bool isOutfitLocked() { return locked; }
};
namespace LLPrismCollections {
    bool changing=false;
    bool busy() { return changing; }
    bool isCategory(int id) { return id==20; }
}
std::set<int> worn;
bool get_is_item_worn(int id) { return worn.count(id); }
template<class... Args> std::string llformat(const char* fmt, Args... args) {
    char buffer[256]; std::snprintf(buffer, sizeof(buffer), fmt, args...); return buffer;
}
struct Value {
    int value=0;
    int asUUID() const { return value; }
    bool asBoolean() const { return value!=0; }
};
struct LLView { bool visible=true; void setVisible(bool v) { visible=v; } };
struct LLCheckBoxCtrl : LLView { bool value=false; bool get() { return value; } };
struct Cell {
    Value value; bool enabled=true;
    Value getValue() { return value; }
    void setValue(bool v) { value.value=v; }
    void setEnabled(bool v) { enabled=v; }
};
struct Row {
    Value id; Cell cells[2];
    Value getValue() { return id; }
    Cell* getColumn(int i) { return &cells[i]; }
};
struct Column {
    int width=42; LLView header, *mHeader=&header;
    void setWidth(int w) { width=w; }
};
struct List {
    Column body; std::vector<Row*> rows;
    Column* getColumn(const char*) { return &body; }
    void updateColumns(bool) {}
    std::vector<Row*> getAllData() { return rows; }
};
struct LLFloaterQuickPhoto {
    int mFolder=10, previews=0;
    std::set<int> mMembers;
    LLCheckBoxCtrl mannequin, isolate;
    LLView help;
    List list, *mAttachments=&list;
    template<class T> T* getChild(const std::string& name) {
        LLView* view = name=="mannequin" ? &mannequin : name=="isolate" ? &isolate : &help;
        return static_cast<T*>(view);
    }
    void refreshPreview() { ++previews; }
    bool folderReady(std::string&);
    void isolateAttachments();
    void updateMannequinControls();
};
'''
for signature in ('bool LLFloaterQuickPhoto::folderReady(std::string& reason)',
                  'void LLFloaterQuickPhoto::isolateAttachments()',
                  'void LLFloaterQuickPhoto::updateMannequinControls()'):
    code += function(PATH, signature) + '\n'

# Also exercise the refresh expression, which must not retain a stale Show choice
# when a set is isolated, but must preserve manual choices in ordinary photos.
show = re.search(r'const bool show = ([^;]+);', source).group(1)
code += r'''
int main() {
    LLFloaterQuickPhoto photo;
    std::string reason;
    Item shirt{1,LLAssetType::AT_OBJECT,"Shirt"}, pants{2,LLAssetType::AT_CLOTHING,"Pants"},
         skin{3,LLAssetType::AT_BODYPART,"Skin"}, shoes{4,LLAssetType::AT_OBJECT,"Shoes"},
         note{5,LLAssetType::AT_NOTECARD,"Instructions"};
    gInventory.items={&shirt,&pants,&skin,&shoes,&shirt,&note};
    assert(!photo.folderReady(reason));
    assert(reason=="Not wearing 4 set item(s): Shirt, Pants, Skin (+1 more). Wear the outfit / set, then refresh.");
    assert(photo.mMembers==std::set<int>({1,2,3,4})); // Duplicates and non-wearables ignored.
    worn={1,2,3,4};
    assert(photo.folderReady(reason) && reason.empty());
    worn.erase(2);
    assert(!photo.folderReady(reason) && reason.find("1 set item(s): Pants.")!=std::string::npos);
    gInventory.folder.parent=30; // Ordinary folder may photograph its currently worn subset.
    assert(photo.folderReady(reason));
    gInventory.folder.type=LLFolderType::FT_OUTFIT;
    assert(!photo.folderReady(reason) && reason.find("1 outfit item(s): Pants.")!=std::string::npos);
    gInventory.folder={}; worn.insert(2);
    shirt.broken=true;
    assert(!photo.folderReady(reason) && reason.find("Repair its link")!=std::string::npos);
    shirt.broken=false;
    Category child{11}; gInventory.cats={&child}; gInventory.incomplete.insert(11);
    assert(!photo.folderReady(reason) && reason=="Loading folder contents...");
    gInventory.incomplete.clear();
    LLPrismCollections::changing=true;
    assert(!photo.folderReady(reason) && reason.find("outfit change")!=std::string::npos);
    LLPrismCollections::changing=false;
    Row member{{1}}, unrelated{{6}}, body{{7}};
    body.cells[1].setValue(true);
    photo.list.rows={&member,&unrelated,&body};
    photo.isolate.value=true; photo.isolateAttachments();
    assert(member.cells[0].getValue().asBoolean());
    assert(!unrelated.cells[0].getValue().asBoolean());
    assert(body.cells[0].getValue().asBoolean());
    photo.isolate.value=false; photo.isolateAttachments();
    for (auto* row: photo.list.rows) assert(row->cells[0].getValue().asBoolean());
    for (bool enabled: {false,true,false}) {
        photo.mannequin.value=enabled; photo.updateMannequinControls();
        assert(photo.list.body.width==(enabled ? 42 : -1));
        assert(photo.list.body.header.visible==enabled && photo.help.visible==enabled);
        for (auto* row: photo.list.rows) assert(row->cells[1].enabled==enabled);
        assert(body.cells[1].getValue().asBoolean()); // Hidden controls retain body classification.
    }
    const int id=9;
    for (bool isolate: {false,true}) for (bool body: {false,true})
    for (bool member: {false,true}) for (bool existing: {false,true})
    for (bool previously_shown: {false,true}) {
        std::set<int> mMembers; if (member) mMembers.insert(id);
        std::map<int,std::pair<bool,bool>> previous;
        if (existing) previous[id]={previously_shown,body};
        const auto old=previous.find(id);
        const bool show = ''' + show + r''';
        assert(show==(isolate ? body || member : !existing || previously_shown));
    }
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp, exe = Path(directory) / 'selection.cpp', Path(directory) / 'selection.exe'
    cpp.write_text(code, encoding='utf-8')
    subprocess.run(['g++', '-std=c++17', str(cpp), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

opened = function(PATH, 'void LLFloaterQuickPhoto::onOpen(const LLSD& key)')
assert 'getChild<LLCheckBoxCtrl>("isolate")->set(LLPrismCollections::isCategory(folder->getParentUUID()))' in opened
assert 'updateMannequinControls();' in function(PATH, 'void LLFloaterQuickPhoto::refreshAttachments()')
assert 'setToolTip(message)' in function(PATH, 'void LLFloaterQuickPhoto::status(const std::string& message)')
print('Missing set/outfit items, deduplication, collection isolation/refresh, and conditional Body controls passed.')
