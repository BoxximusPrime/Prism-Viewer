"""Exercise the production collection swap planner and UI wiring without a login."""
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "indra/newview/llprismcollections.cpp").read_text(encoding="utf-8")
header = (ROOT / "indra/newview/llprismcollections.h").read_text(encoding="utf-8")
start = source.index("Change planChange(")
end = source.index("\nvoid error(", start)
model = header[header.index("struct Selection"):header.index("Change planChange(")]
transition_start = source.index('    auto active = selected.find(category);')
transition_end = source.index('    auto worn = wornItems();', transition_start)
# The fixture uses integer IDs, with zero standing in for a null LLUUID.
transition = source[transition_start:transition_end].replace('set.isNull()', 'set == 0')
harness = r'''#include <algorithm>
#include <cassert>
#include <map>
#include <set>
#include <vector>
using LLUUID = int;
using uuid_vec_t = std::vector<int>;
namespace LLAssetType { enum { AT_CLOTHING, AT_OBJECT, AT_BODYPART }; }
namespace LLWearableType { using EType = int; }
struct Item { int type, wearable; int getType() const { return type; } int getWearableType() const { return wearable; } };
struct Inventory { std::map<int, Item> items; const Item* getItem(int id) const { auto i=items.find(id); return i == items.end() ? nullptr : &i->second; } } gInventory;
''' + model + source[start:end] + r'''
bool prepareTransition(Selections& selected, std::set<LLUUID>& managed, LLUUID category, LLUUID set, const uuid_vec_t& items)
{
''' + transition + r'''
    return true;
}
int main()
{
    for (int id = 0; id < 1000; ++id) gInventory.items[id] = {LLAssetType::AT_CLOTHING, 1};
    Selections selections = {{1, {10, {101, 102}}}};
    // First activation manages the entire set but only adds absent items.
    auto change = planChange(selections, {}, {101, 999}, {101, 102});
    assert(change.add == uuid_vec_t{102});
    assert(change.remove.empty());
    assert(change.managed == (std::set<int>{101, 102}));
    // Swap makeup, including pre-worn set members; protect unrelated items.
    selections[1] = {11, {103}};
    change = planChange(selections, change.managed, {101, 102, 999}, {103});
    assert(change.add == uuid_vec_t{103});
    assert(change.remove == (uuid_vec_t{101, 102}));
    // Shared links stay worn, and ownership survives removing the first category.
    selections = {{1, {10, {101, 102}}}, {2, {20, {102, 201}}}};
    selections.erase(1);
    change = planChange(selections, {101, 102, 201}, {101, 102, 201, 999}, {});
    assert(change.remove == uuid_vec_t{101});
    assert(change.managed == (std::set<int>{102, 201}));
    change = planChange({}, change.managed, {102, 201, 999}, {});
    assert(change.remove == (uuid_vec_t{102, 201}));
    assert(change.managed.empty());
    // Switching one category must not re-wear manually removed items in another.
    selections = {{1, {10, {101}}}, {2, {20, {201}}}};
    change = planChange(selections, {201}, {}, {101});
    assert(change.add == uuid_vec_t{101});
    // Re-wearing an already worn set requires no duplicate additions.
    change = planChange({{1, {10, {101}}}}, {101}, {101}, {101});
    assert(change.managed == std::set<int>{101});
    assert(change.add.empty());
    change = planChange({}, change.managed, {101}, {});
    assert(change.remove == uuid_vec_t{101});
    // Retain failed detach ownership so retrying can finish the old removal.
    change = planChange({{1, {11, {103}}}}, {101, 102, 103}, {101}, {103});
    assert(change.remove == uuid_vec_t{101});
    assert(change.add == uuid_vec_t{103});
    // Overlap, duplicate links and repeated activation are harmless.
    selections = {{1, {10, {101, 102, 102}}}};
    change = planChange(selections, {101}, {101}, {101, 102, 102});
    assert(change.add == uuid_vec_t{102});
    assert(change.remove.empty());
    change = planChange(selections, change.managed, {101, 102}, {101, 102});
    assert(change.add.empty() && change.remove.empty());
    // Body parts replace their type through wearItemsOnAvatar, never through detach.
    gInventory.items[301] = {LLAssetType::AT_BODYPART, 0};
    gInventory.items[302] = {LLAssetType::AT_BODYPART, 0};
    gInventory.items[303] = {LLAssetType::AT_BODYPART, 1};
    change = planChange({{1, {11, {302}}}}, {301}, {301, 999}, {302});
    assert(change.remove.empty() && change.add == uuid_vec_t{302});
    assert(change.managed == std::set<int>{302});
    change = planChange({}, {302}, {302, 999}, {});
    assert(change.remove.empty() && change.add.empty() && change.managed.empty());
    change = planChange({{1, {12, {102}}}}, {302}, {302}, {102});
    assert(change.remove.empty() && change.add == uuid_vec_t{102});
    assert(validBodyParts({301, 303, 101, 102}));
    assert(!validBodyParts({301, 302}));
    assert(validBodyParts({}));
    // Explicit Remove Active includes items worn before activation, but leaves unrelated items.
    selections = {{1, {10, {101, 102, 301}}}};
    std::set<int> managed;
    gInventory.items[102] = {LLAssetType::AT_OBJECT, 0};
    assert(prepareTransition(selections, managed, 1, 0, {}));
    change = planChange(selections, managed, {101, 102, 301, 999}, {});
    assert(change.remove == (uuid_vec_t{101, 102}));
    assert(change.add.empty() && change.managed.empty());
    // Another active category retains ownership of a shared item until it too is removed.
    selections = {{1, {10, {101, 102}}}, {2, {20, {102}}}};
    managed.clear();
    assert(prepareTransition(selections, managed, 1, 0, {}));
    change = planChange(selections, managed, {101, 102, 999}, {});
    assert(change.remove == uuid_vec_t{101});
    assert(change.managed == std::set<int>{102});
    managed = change.managed;
    assert(prepareTransition(selections, managed, 2, 0, {}));
    change = planChange(selections, managed, {102, 999}, {});
    assert(change.remove == uuid_vec_t{102});
    selections.clear(); managed.clear();
    assert(!prepareTransition(selections, managed, 1, 0, {}));
    assert(selections.empty() && managed.empty());
    // Switching an active set saved by an older build adopts its pre-worn members too.
    selections = {{1, {10, {101, 102}}}, {2, {20, {102}}}};
    managed.clear();
    assert(prepareTransition(selections, managed, 1, 11, {103}));
    change = planChange(selections, managed, {101, 102, 999}, {103});
    assert(change.remove == uuid_vec_t{101});
    assert(change.add == uuid_vec_t{103});
    assert(change.managed == (std::set<int>{102, 103}));
    // Editing/reapplying an active set drops its old members, keeps overlap and adds missing members.
    selections = {{1, {10, {101, 102}}}};
    managed.clear();
    assert(prepareTransition(selections, managed, 1, 10, {102, 103}));
    change = planChange(selections, managed, {101, 102, 999}, {102, 103});
    assert(change.remove == uuid_vec_t{101});
    assert(change.add == uuid_vec_t{103});
    // First activation with everything already worn must still manage all included items.
    selections.clear(); managed.clear();
    assert(prepareTransition(selections, managed, 1, 10, {101, 102}));
    change = planChange(selections, managed, {101, 102, 999}, {101, 102});
    assert(change.add.empty() && change.remove.empty());
    assert(change.managed == (std::set<int>{101, 102}));
    // No transition is allowed to remove an item Collections did not manage.
    for (int a = 0; a < 16; ++a) for (int b = 0; b < 16; ++b) {
        std::set<int> managed, worn;
        for (int id = 0; id < 4; ++id) {
            if (a & (1 << id)) managed.insert(id);
            if (b & (1 << id)) worn.insert(id);
        }
        auto p = planChange({{1, {10, {1, 2}}}}, managed, worn, {1, 2});
        for (int id : p.remove) assert(managed.count(id) && worn.count(id) && id != 1 && id != 2);
    }
}
'''
ui = ROOT / 'indra/newview/skins/default/xui/en'
for filename in ['panel_prism_collections.xml', 'floater_prism_collection.xml',
                 'panel_prism_collection_card.xml', 'panel_outfits_inventory.xml', 'notifications.xml']:
    ET.parse(ui / filename)
settings = ET.parse(ROOT / 'indra/newview/app_settings/settings_per_account.xml').getroot().find('map')
assert sum(k.text == 'PrismCollectionsState' for k in settings.findall('key')) == 1
panel = ET.parse(ui / 'panel_prism_collections.xml').getroot()
editor = ET.parse(ui / 'floater_prism_collection.xml').getroot()
card = ET.parse(ui / 'panel_prism_collection_card.xml').getroot()
# Referenced panels build children before initializing their own layout.
# Every positioned control must therefore declare its coordinate convention.
for root in (panel, editor, card):
    for child in root:
        if child.tag in {'text', 'button', 'combo_box', 'scroll_list', 'line_editor', 'check_box'}:
            assert child.get('layout') == 'topleft', (root.get('name'), child.get('name'))
            assert child.get('follows'), (root.get('name'), child.get('name'))
            if child.get('top') is not None and child.tag != 'scroll_list':
                assert child.get('follows') == 'all' or 'top' in child.get('follows').split('|'), child.attrib
for name in ['new_category', 'rename_category', 'delete_category']:
    assert panel.find(f".//*[@name='{name}']").get('follows') == 'left|top', name
for name in ['categories', 'sets', 'new_category', 'rename_category', 'delete_category',
             'new_set', 'edit_set', 'delete_set', 'wear_set', 'remove_set', 'gallery_mode', 'gallery', 'gallery_content', 'set_photo']:
    assert panel.find(f".//*[@name='{name}']") is not None, name
for name in ['set_name', 'items', 'refresh_worn', 'move_up', 'move_down', 'activate', 'save', 'cancel', 'set_photo']:
    assert editor.find(f".//*[@name='{name}']") is not None, name
impl = (ROOT / 'indra/newview/llpanelprismcollections.cpp').read_text(encoding='utf-8')
assert [c.get('name') for c in editor.find(".//*[@name='items']").findall('scroll_list.columns')] == ['include', 'icon', 'name', 'type', 'status']
assert 'LLInventoryIcon::getIconName(item->getType(), item->getInventoryType(), item->getFlags())' in impl
assert 'mItems->sortOnce(3, true)' in impl
assert 'mItems->swapWithPrevious(index)' in impl and 'mItems->swapWithNext(index)' in impl
cells = (ROOT / 'indra/llui/llscrolllistcell.cpp').read_text(encoding='utf-8')
assert 'checkbox_p.rect = LLRect(0, height, p.width, 0)' in cells
assert 'checkbox_p.label_text.rect = LLRect(0, height, 0, 0)' in cells
assert 'return mCheckBox->getRect().getHeight();' in cells
assert 'gInventory.removeCategory(id)' in impl  # Trash, never purge originals.
assert 'item->getActualType() == LLAssetType::AT_LINK' in impl
assert 'if (!links.count(id))' in impl and impl.index('if (!links.count(id))') < impl.index('for (const LLUUID& id : old_links)')
assert 'wearItemsOnAvatar(mChange.add, true, false)' in source  # Add layers/attachments; the viewer replaces body parts by type.
assert source.index('if (!capacity(change))') < source.index('new Swap(')
assert 'pending.insert(mChange.remove.begin(), mChange.remove.end())' in source
assert 'saveState(selections(), mChange.managed)' in source
assert 'PC::validBodyParts(items)' in impl and 'validBodyParts(result)' in source
assert 'type != DAD_BODYPART' in impl
assert 'LLInspectTextureUtil::createInventoryToolTip' in impl
assert 'category->getThumbnailUUID()' in impl
assert 'showInstance("change_item_thumbnail", LLSD(id))' in impl
wearable_menu = ET.parse(ui / 'menu_wearable_list_item.xml').getroot()
for name in ('collection_add', 'collection_remove'):
    assert wearable_menu.find(f".//*[@name='{name}']").get('visible') == 'false'
wearable_impl = (ROOT / 'indra/newview/llwearableitemslist.cpp').read_text(encoding='utf-8')
assert 'setRightMouseDownCallback' in impl and 'mItems->hitItem(x, y)' in impl
assert 'showForCollection(mItems, id, x, y, included, PC::validItem(id)' in impl
assert 'self->mSaving || self->mCategory != category || self->mSet != set' in impl
assert 'item->getColumn(0)->setValue(!included)' in impl
assert 'show(spawning_view, uuid_vec_t{id}, x, y)' in wearable_impl
assert 'setMenuItemEnabled(menu, "show_original", gInventory.getItem(id) != nullptr)' in wearable_impl
assert 'included ? "collection_remove" : "collection_add"' in wearable_impl
with tempfile.TemporaryDirectory() as directory:
    cpp, exe = Path(directory) / 'check.cpp', Path(directory) / 'check.exe'
    cpp.write_text(harness, encoding='utf-8')
    subprocess.run(['g++', '-std=c++17', str(cpp), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

    # Exercise the actual layer-movement guard with a small inventory/list fixture.
    start = impl.index('bool LLFloaterPrismCollection::canMoveLayer(')
    end = impl.index('\nvoid LLFloaterPrismCollection::updateLayerButtons', start)
    cpp.write_text(r'''#include <cassert>
#include <map>
#include <vector>
using S32 = int;
namespace LLAssetType { enum { AT_CLOTHING, AT_OBJECT, AT_BODYPART }; }
namespace LLWearableType { enum { WT_TATTOO = 12 }; }
struct Item { int type, wearable; int getType() const { return type; } int getWearableType() const { return wearable; } };
struct Inventory { std::map<int, Item> items; const Item* getItem(int id) const { auto i=items.find(id); return i == items.end() ? nullptr : &i->second; } } gInventory;
struct Value { int id; int asUUID() const { return id; } };
struct Row { int id; Value getValue() const { return {id}; } };
using LLScrollListItem = Row;
struct List { std::vector<Row*> rows; int selected=-1; auto getAllData() const { return rows; } int getFirstSelectedIndex() const { return selected; } };
struct LLFloaterPrismCollection { List* mItems; bool mSaving=false; bool canMoveLayer(S32 direction) const; };
''' + impl[start:end] + '\n' + impl[impl.index('        auto rank = '):impl.index('        return rank(a)')] + r'''
int main() {
    gInventory.items = {{1,{0,1}}, {2,{0,1}}, {3,{0,2}}, {4,{1,0}}, {5,{1,0}}};
    Row a{1}, b{2}, c{3}, d{4}, e{5}, missing{6};
    List list{{&a,&b,&c,&d,&e,&missing}};
    LLFloaterPrismCollection editor{&list};
    assert(!editor.canMoveLayer(-1) && !editor.canMoveLayer(1));
    list.selected=0; assert(!editor.canMoveLayer(-1) && editor.canMoveLayer(1));
    list.selected=1; assert(editor.canMoveLayer(-1) && !editor.canMoveLayer(1));
    editor.mSaving=true; assert(!editor.canMoveLayer(-1)); editor.mSaving=false;
    list.selected=2; assert(!editor.canMoveLayer(-1) && !editor.canMoveLayer(1));
    list.selected=3; assert(!editor.canMoveLayer(1));
    list.selected=4; assert(!editor.canMoveLayer(1));
    list.selected=5; assert(!editor.canMoveLayer(-1) && !editor.canMoveLayer(1));
    gInventory.items[7] = {LLAssetType::AT_CLOTHING, LLWearableType::WT_TATTOO};
    gInventory.items[8] = {LLAssetType::AT_BODYPART, 0};
    Row tattoo{7}, body{8};
    assert(rank(&tattoo) < rank(&a));
    assert(rank(&a) < rank(&d));
    assert(rank(&d) < rank(&body));
    assert(rank(&a) == rank(&b));
    assert(rank(&body) < rank(&missing));
}
''', encoding='utf-8')
    subprocess.run(['g++', '-std=c++17', str(cpp), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('Collections swap ownership, overlaps, independent categories, removal, XML and save wiring passed.')
