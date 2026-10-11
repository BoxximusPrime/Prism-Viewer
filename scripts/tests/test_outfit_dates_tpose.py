"""Check production outfit date sorting and pose cycling. Requires g++."""
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
outfits = (ROOT / 'indra/newview/lloutfitslist.cpp').read_text(encoding='utf-8')
poses = (ROOT / 'indra/newview/llfloaterboxxytpose.cpp').read_text(encoding='utf-8')


def method(source, signature):
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2] + '\n'


harness = r'''
#include <algorithm>
#include <cassert>
#include <ctime>
#include <string>
#include <vector>
using S32 = int; using F64 = double;
struct Settings { bool date = false; } gSavedSettings;
template<class T> struct LLCachedControl {
    LLCachedControl(Settings&, const char*, T) {}
    operator T() const { return gSavedSettings.date; }
};
struct LLStringUtil { static int compareDict(const std::string& a,const std::string& b) { return a.compare(b); } };
struct LLTrans { static std::string getString(const char*) { return "Unknown"; } };
struct LLDate {
    time_t date; LLDate(F64 value):date(value){}
    std::string toLocalDateString(const char*) { return std::to_string(date); }
};
struct LLTextBox { std::string text="Unknown"; void setText(std::string value) { text=value; } };
struct Item {
    time_t date; bool link;
    time_t getCreationDate() const { return date; }
    bool getIsLinkType() const { return link; }
};
struct LLInventoryModel {
    using cat_array_t=std::vector<int>;
    using item_array_t=std::vector<Item*>;
    enum { EXCLUDE_TRASH };
    item_array_t items;
    void collectDescendents(int,cat_array_t&,item_array_t& result,int) { result=items; }
} gInventory;
struct LLAccordionCtrlTab {
    std::string name;
    const std::string& getTitle() const { return name; }
};
struct LLOutfitAccordionCtrlTab:LLAccordionCtrlTab {
    int mFolderID=1; time_t mCreationDate=0; bool favorite=false;
    LLTextBox label; LLTextBox* mCreationDateLabel=&label;
    bool getFavorite() const { return favorite; }
    time_t getCreationDate() const { return mCreationDate; }
    bool refreshCreationDate();
};
struct LLOutfitTabNameComparator { bool compare(const LLAccordionCtrlTab*,const LLAccordionCtrlTab*) const; };
struct LLOutfitTabFavComparator { bool compare(const LLAccordionCtrlTab*,const LLAccordionCtrlTab*) const; };
static const LLOutfitTabNameComparator OUTFIT_TAB_NAME_COMPARATOR;
struct Combo {
    int count=11, index=0;
    int getItemCount() const { return count; }
    int getCurrentIndex() const { return index; }
    void setCurrentByIndex(int value) { assert(value>=0 && value<count); index=value; }
};
struct LLFloaterBoxxyTPose {
    Combo combo; Combo* mPoseCombo=&combo; int played=-1, calls=0;
    void onPoseSelected() { played=combo.index; ++calls; }
    void cyclePose(S32);
};
'''
for signature in ('bool LLOutfitTabNameComparator::compare', 'bool LLOutfitTabFavComparator::compare',
                  'bool LLOutfitAccordionCtrlTab::refreshCreationDate'):
    harness += method(outfits, signature)
harness += method(poses, 'void LLFloaterBoxxyTPose::cyclePose')
harness += r'''
int main() {
    LLOutfitAccordionCtrlTab a,b,unknown;
    a.name="Alpha"; b.name="Beta"; unknown.name="Unknown";
    Item old{100,true},recent{200,true},original{1,false},invalid{0,true},negative{-1,true};
    gInventory.items={&recent,&original,&invalid,&old,&negative};
    assert(a.refreshCreationDate() && a.getCreationDate()==100 && a.label.text=="100");
    assert(!a.refreshCreationDate());
    gInventory.items={&recent};
    assert(b.refreshCreationDate() && b.getCreationDate()==200);
    LLOutfitTabNameComparator names; LLOutfitTabFavComparator favorites;
    assert(names.compare(&a,&b));
    gSavedSettings.date=true;
    assert(names.compare(&b,&a) && !names.compare(&a,&b));
    assert(names.compare(&a,&unknown) && !names.compare(&unknown,&a));
    assert(favorites.compare(&b,&a));
    a.favorite=true;
    assert(favorites.compare(&a,&b));
    a.mCreationDate=200;
    assert(names.compare(&a,&b) && !names.compare(&a,&a)); // Equal dates use names.
    gInventory.items.clear();
    assert(a.refreshCreationDate() && a.label.text=="Unknown" && a.mCreationDate==0);
    assert(!a.refreshCreationDate());
    LLFloaterBoxxyTPose pose;
    pose.cyclePose(-1); assert(pose.played==10);
    pose.cyclePose(1); assert(pose.played==0);
    pose.cyclePose(1); assert(pose.played==1);
    pose.cyclePose(-1); assert(pose.played==0);
    const int calls=pose.calls;
    pose.combo.count=0; pose.cyclePose(1); assert(pose.calls==calls);
    pose.combo.count=1; pose.cyclePose(-1); assert(pose.played==0);
}
'''
ui = ROOT / 'indra/newview/skins/default/xui/en'
menu = ET.parse(ui / 'menu_outfit_list_sort.xml').getroot()
entry = next(n for n in menu if n.get('name') == 'sort_creation_date')
assert entry.find('on_click').get('parameter') == 'creation_date'
assert entry.find('on_check').get('parameter') == 'creation_date'
floater = ET.parse(ui / 'floater_boxxy_tpose.xml').getroot()
for name in ('pose_combo', 'pose_prev', 'pose_next'):
    node = next(n for n in floater if n.get('name') == name)
    assert int(node.get('left')) + int(node.get('width')) <= int(floater.get('width'))
assert 'date.font_halign = LLFontGL::RIGHT' in outfits
assert 'if (tab->refreshCreationDate()) sortOutfits();' in outfits
settings = ET.parse(ROOT / 'indra/newview/app_settings/settings.xml').getroot().find('map')
assert sum(n.text == 'OutfitListSortByCreationDate' for n in settings.findall('key')) == 1
with tempfile.TemporaryDirectory() as directory:
    cpp, exe = Path(directory) / 'check.cpp', Path(directory) / 'check.exe'
    cpp.write_text(harness, encoding='utf-8')
    subprocess.run(['g++', '-std=c++17', str(cpp), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('Outfit earliest-link dates, sorting/favorites/unknowns, XML wiring and T-pose cycling passed.')
