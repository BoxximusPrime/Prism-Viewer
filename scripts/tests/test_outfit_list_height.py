"""Exercise the production inventory refresh state machine without launching the viewer.

Requires Python and g++. Checks that outfit content and its parent height stay
in sync as inventory arrives in batches, including updates after first load.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'indra/newview/llinventoryitemslist.cpp').read_text(encoding='utf-8')
start = source.index('void LLInventoryItemsList::refresh()')
end = source.index('\nvoid LLInventoryItemsList::computeDifference(', start)
refresh = source[start:end]

harness = r'''
#include <algorithm>
#include <cassert>
#include <cstdio>
#include <list>
#include <map>
#include <string>
#include <utility>
#include <vector>
#define LL_PROFILE_ZONE_SCOPED
#define LL_PROFILE_ZONE_NAMED(name)
#define llassert(condition) assert(condition)
using LLUUID=int;
using uuid_vec_t=std::vector<LLUUID>;
struct LLSD {LLSD& with(const char*,const std::string&){return *this;}};
struct LLStringUtil {static void toUpper(std::string&) {}};
struct LLViewerInventoryItem {int id;int getUUID(){return id;}};
struct Inventory {
    std::map<int,LLViewerInventoryItem> items;
    LLViewerInventoryItem* getItem(int id){return &items.at(id);}
} gInventory;
struct LLPanel {
    int id; bool visible=true; void* parent=nullptr;
    void* getParent(){return parent;}
};
struct LLInventoryItemsList {
    enum State {REFRESH_ALL,REFRESH_LIST_ERASE,REFRESH_LIST_APPEND,REFRESH_LIST_SORT,REFRESH_COMPLETE};
    using item_pair_t=std::pair<LLPanel*,int>;
    using pairs_list_t=std::list<item_pair_t*>;
    using pairs_const_iterator_t=pairs_list_t::const_iterator;
    State mRefreshState=REFRESH_COMPLETE;
    bool mNeedsArrange=true,visible=true,force=false;
    int filter=0,contentHeight=0,parentHeight=0,notifications=0,maxBatch=0;
    uuid_vec_t ids,mAddedItems,mRemovedItems;
    pairs_list_t rows;
    ~LLInventoryItemsList(){for(auto p:rows){delete p->first;delete p;}}
    auto& getIDs(){return ids;}
    bool getVisible(){return visible;}
    std::string getFilterSubString(){return filter?"FILTER":"";}
    void setForceRefresh(bool b){force=b;}
    void updateSelection(){}
    void computeDifference(const uuid_vec_t& next,uuid_vec_t& added,uuid_vec_t& removed){
        for(int id:next)if(std::none_of(rows.begin(),rows.end(),[id](auto p){return p->second==id;}))added.push_back(id);
        for(auto p:rows)if(std::find(next.begin(),next.end(),p->second)==next.end())removed.push_back(p->second);
    }
    LLPanel* createNewItem(LLViewerInventoryItem* item){return new LLPanel{item->id};}
    bool addItemPairs(pairs_list_t added,bool){
        maxBatch=std::max(maxBatch,int(added.size()));
        for(auto p:added){rows.push_back(p);p->first->parent=this;}
        return !added.empty();
    }
    void removeItemByUUID(int id,bool){
        for(auto it=rows.begin();it!=rows.end();++it)if((*it)->second==id){
            delete (*it)->first;delete *it;rows.erase(it);return;
        }
    }
    // Like LLFlatListViewEx, already-visible matching rows report no visibility change.
    bool updateItemVisibility(LLPanel* panel,const LLSD&){
        bool show=filter==0||(filter==1&&panel->id%2==0);
        bool changed=panel->visible!=show;panel->visible=show;return changed;
    }
    void rearrangeItems(){
        contentHeight=0;
        for(auto p:rows)if(p->first->visible)contentHeight+=21;
    }
    void notifyParentItemsRectChanged(){parentHeight=contentHeight;++notifications;}
    bool filterItems(bool sort,bool notify){
        bool changed=false;
        for(auto p:rows)changed|=updateItemVisibility(p->first,LLSD());
        // LLFlatListView::sort rearranges the inner list but doesn't notify its parent.
        if(sort)rearrangeItems();
        if(changed&&notify){rearrangeItems();notifyParentItemsRectChanged();return true;}
        return false;
    }
    void refresh();
    void load(int first,int count){
        ids.clear();
        for(int id=first;id<first+count;++id){gInventory.items[id]={id};ids.push_back(id);}
        mRefreshState=REFRESH_ALL;
        int steps=0;
        while(mRefreshState!=REFRESH_COMPLETE){
            refresh();assert(++steps<1000);
            // Every visible incremental layout must fit its newly added rows.
            if(visible)assert(parentHeight==contentHeight);
        }
        assert(!force);assert(maxBatch<=25);assert(rows.size()==ids.size());
        assert(parentHeight==contentHeight);
        int expected=0;
        for(int id:ids)if(filter==0||(filter==1&&id%2==0))expected+=21;
        assert(contentHeight==expected);
    }
};
'''
harness += refresh
harness += r'''
int main(){
    int cases=0;
    // At/beyond the 25-row boundary, large outfits, matching/hidden rows,
    // and refreshes performed while their accordion is collapsed.
    for(int count:{0,1,24,25,26,49,50,51,100,251})
    for(bool visible:{true,false})
    for(int filter:{0,1,2}){
        LLInventoryItemsList list;list.visible=visible;list.filter=filter;
        list.load(1,count);++cases;
        list.visible=true; // expanding must use the full recorded content height
        assert(list.parentHeight==list.contentHeight);
        list.load(1,count+1);++cases; // add to an already finished outfit
        list.load(5,count+27);++cases; // remove and add in the same refresh
        int notifications=list.notifications;
        list.load(5,count+27);++cases; // a no-op doesn't trigger more parent resizes
        assert(list.notifications==notifications);
        list.load(1,0);++cases;
    }
    std::printf("Outfit list height: %d batch, incremental, collapsed, filtered and no-op cases passed.\n",cases);
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / 'outfit_list_height.cpp'
    exe = Path(directory) / 'outfit_list_height.exe'
    cpp.write_text(harness, encoding='utf-8')
    subprocess.run(['g++', '-std=c++17', str(cpp), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
