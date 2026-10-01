"""Exercise production Received Items moves and folder removal. Requires g++."""
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[2]
source = (root / 'indra/newview/llinventorybridge.cpp').read_text()


def block(start):
    start = source.index('{', start)
    end, depth = start + 1, 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


harness = r'''
#include <cassert>
#include <vector>
struct LLUUID {int value=0; bool isNull()const{return value==0;}
    bool operator==(LLUUID b)const{return value==b.value;}};
namespace LLAssetType {enum {AT_OBJECT,AT_CLOTHING,AT_BODYPART,AT_GESTURE};}
namespace LLFolderType {enum {FT_INBOX}; bool lookupIsProtectedType(int type){return type!=0;}}
struct LLViewerInventoryCategory {int type=0; LLUUID id{3};
    int getPreferredType(){return type;} LLUUID getLinkedUUID(){return id;}};
struct LLViewerInventoryItem {LLUUID id; int type; bool worn;
    int getType(){return type;} LLUUID getUUID(){return id;}};
struct LLFindWearablesEx {LLFindWearablesEx(bool worn,bool body){assert(worn&&!body);}};
using uuid_vec_t=std::vector<LLUUID>;
struct LLInventoryModel {
    using cat_array_t=std::vector<LLViewerInventoryCategory*>;
    using item_array_t=std::vector<LLViewerInventoryItem*>;
    LLUUID inbox{1},root{2}; bool received=true; int moves=0; bool category=false;
    LLViewerInventoryCategory cat; LLViewerInventoryItem item{{4},LLAssetType::AT_OBJECT,true};
    item_array_t contents;
    LLUUID findCategoryUUIDForType(int){return inbox;} LLUUID getRootFolderID(){return root;}
    bool isObjectDescendentOf(LLUUID,LLUUID){return received;}
    LLViewerInventoryCategory* getCategory(LLUUID){return category?&cat:nullptr;}
    LLViewerInventoryItem* getItem(LLUUID){return &item;}
    void changeCategoryParent(LLViewerInventoryCategory*,LLUUID dest,bool stamp){assert(dest==root&&!stamp); ++moves;}
    void changeItemParent(LLViewerInventoryItem*,LLUUID dest,bool stamp){assert(dest==root&&!stamp); ++moves;}
    void collectDescendentsIf(LLUUID,cat_array_t&,item_array_t& items,bool trash,LLFindWearablesEx&){
        assert(!trash);
        for(auto* item:contents) if(item->worn&&item->type!=LLAssetType::AT_BODYPART) items.push_back(item);
    }
};
int notifications=0; void set_dad_inbox_object(LLUUID){++notifications;}
struct LLAppearanceMgr {uuid_vec_t removed; int calls=0;
    static LLAppearanceMgr& instance(){static LLAppearanceMgr mgr; return mgr;}
    void removeItemsFromAvatar(const uuid_vec_t& ids){removed=ids; ++calls;}};
struct LLFolderBridge {LLViewerInventoryCategory cat;
    LLViewerInventoryCategory* getCategory(){return &cat;} void detach(LLInventoryModel* model);};
'''
signature = 'static void move_received_item_to_inventory('
start = source.index(signature)
harness += source[start:source.index('{', start)] + block(start) + '\n'
start = source.index('if (action == "detach_folder")')
harness += 'void LLFolderBridge::detach(LLInventoryModel* model)' + block(start) + '\n'
harness += r'''
int main(){
    LLInventoryModel model;
    move_received_item_to_inventory(&model,{4}); assert(model.moves==1 && notifications==1);
    model.category=true;
    move_received_item_to_inventory(&model,{3}); assert(model.moves==2 && notifications==2);
    model.cat.type=1;
    move_received_item_to_inventory(&model,{3}); assert(model.moves==2);
    model.cat.type=0; model.received=false;
    move_received_item_to_inventory(&model,{3}); assert(model.moves==2);
    model.received=true;
    move_received_item_to_inventory(&model,model.inbox); assert(model.moves==2);
    model.root={0}; move_received_item_to_inventory(&model,{3}); assert(model.moves==2);
    move_received_item_to_inventory(nullptr,{3});
    LLFolderBridge folder; auto& appearance=LLAppearanceMgr::instance();
    folder.detach(&model); assert(appearance.calls==0);
    LLViewerInventoryItem attached{{10},LLAssetType::AT_OBJECT,true};
    LLViewerInventoryItem unworn{{11},LLAssetType::AT_OBJECT,false};
    LLViewerInventoryItem clothing{{12},LLAssetType::AT_CLOTHING,true};
    LLViewerInventoryItem body{{13},LLAssetType::AT_BODYPART,true};
    LLViewerInventoryItem gesture{{14},LLAssetType::AT_GESTURE,true};
    model.contents={&unworn,&body,&gesture}; folder.detach(&model); assert(appearance.calls==0);
    model.contents={&attached,&unworn,&clothing,&body,&gesture}; folder.detach(&model);
    assert(appearance.calls==1 && appearance.removed.size()==2);
    assert(appearance.removed[0]==attached.id && appearance.removed[1]==clothing.id);
}
'''
menu = ET.parse(root / 'indra/newview/skins/default/xui/en/menu_inventory.xml').getroot()
entry = next(node for node in menu if node.get('name') == 'Move to Inventory')
assert entry.find('menu_item_call.on_click').get('parameter') == 'move_to_inventory'
assert source.count('move_received_item_to_inventory(model, mUUID);') == 2
assert '"detach_folder"' in (root / 'indra/newview/llviewerwindow.cpp').read_text()
with tempfile.TemporaryDirectory() as directory:
    cpp, binary = Path(directory) / 'check.cpp', Path(directory) / 'check.exe'
    cpp.write_text(harness)
    subprocess.run(['g++', '-std=c++17', str(cpp), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print('Received-item moves, protected folders and worn-only folder removal passed.')
