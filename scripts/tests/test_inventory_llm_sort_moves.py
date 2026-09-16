"""Exercise production inventory guards and review lifecycle with an in-memory model."""
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "indra/newview/llfloaterinventoryllmsort.cpp").read_text(encoding="utf-8")
header = (ROOT / "indra/newview/llfloaterinventoryllmsort.h").read_text(encoding="utf-8")
def function(signature):
    start = source.index(signature)
    return source[start:source.index("\n}\n", start) + 3]
members = header[header.index("    enum class State"):header.index("    void chooseRoot")]
program = r'''
#include <string>
#include <vector>
#include <set>
#include <map>
#include <algorithm>
#include <cassert>
#include <iostream>
#include <functional>
#include <memory>
using U32 = unsigned;
struct LLUUID {
    int n=0; LLUUID(int v=0):n(v){} bool isNull() const{return n==0;} bool notNull()const{return n!=0;}
    void setNull(){n=0;}
    bool operator==(LLUUID b)const{return n==b.n;} bool operator!=(LLUUID b)const{return n!=b.n;}
    bool operator<(LLUUID b)const{return n<b.n;}
};
struct LLFolderType { enum EType { FT_NONE, FT_ROOT_INVENTORY, FT_CLOTHING, FT_TRASH,
    FT_CURRENT_OUTFIT, FT_MY_OUTFITS, FT_OUTFIT, FT_MARKETPLACE_LISTINGS, FT_MARKETPLACE_STOCK,
    FT_MARKETPLACE_VERSION, FT_INBOX, FT_FAVORITE, FT_CALLINGCARD }; };
struct Object {
    LLUUID id, parent; std::string name;
    LLUUID getUUID()const{return id;} LLUUID getParentUUID()const{return parent;}
    std::string getName()const{return name;}
};
struct Category : Object {
    LLUUID owner=7; LLFolderType::EType type=LLFolderType::FT_NONE;
    Category(LLUUID i=0,LLUUID p=0,LLUUID o=7,std::string n="Category",LLFolderType::EType t=LLFolderType::FT_NONE)
        :Object{i,p,n},owner(o),type(t){}
    LLUUID getOwnerID()const{return owner;} auto getPreferredType()const{return type;}
};
struct Permissions { LLUUID owner=7; LLUUID getOwner()const{return owner;} };
struct Item : Object {
    Item():Object{100,3,"Shirt"}{} bool finished=true, link=false; Permissions permissions;
    bool isFinished()const{return finished;} bool getIsLinkType()const{return link;}
    LLUUID getParentUUID()const{return parent;} std::string getName()const{return name;}
    const Permissions& getPermissions()const{return permissions;}
};
struct Agent { LLUUID id=7; LLUUID getID()const{return id;} } gAgent;
struct LLApp { inline static bool quitting=false; static bool isQuitting(){return quitting;} };
struct Inventory {
    std::map<LLUUID,Category> cats; std::map<LLUUID,Item> items; int moves=0; bool usable=true;
    using cat_array_t=std::vector<Category*>; using item_array_t=std::vector<Item*>;
    cat_array_t children; bool complete=true; std::function<void(const LLUUID&)> created;
    bool isCategoryComplete(LLUUID)const{return complete;}
    void getDirectDescendentsOf(LLUUID root,cat_array_t*& result,item_array_t*& items){
        children.clear();for(auto& [id,cat]:cats)if(cat.parent==root)children.push_back(&cat);
        result=&children;items=nullptr;
    }
    void createNewCategory(LLUUID,LLFolderType::EType,const std::string&,std::function<void(const LLUUID&)> callback){created=callback;}
    LLUUID getRootFolderID()const{return 1;} bool isInventoryUsable()const{return usable;}
    Category* getCategory(LLUUID id){auto i=cats.find(id);return i==cats.end()?nullptr:&i->second;}
    Item* getItem(LLUUID id){auto i=items.find(id);return i==items.end()?nullptr:&i->second;}
    Object* getObject(LLUUID id){if(auto* c=getCategory(id))return c;return getItem(id);}
    bool isObjectDescendentOf(LLUUID id,LLUUID ancestor){
        std::set<LLUUID> seen;
        while(id.notNull()&&seen.insert(id).second){if(id==ancestor)return true;auto* o=getObject(id);if(!o)return false;id=o->parent;}
        return false;
    }
    void changeItemParent(Item* item, LLUUID dest, bool restamp){assert(!restamp);++moves;item->parent=dest;}
    void changeCategoryParent(Category* cat, LLUUID dest, bool restamp){assert(!restamp);++moves;cat->parent=dest;}
} gInventory;
using LLInventoryModel = Inventory;
struct LLSD {
    std::vector<LLSD> values; LLUUID id;
    LLSD()=default; LLSD(LLUUID value):id(value){}
    LLSD& operator[](const char*){return *this;} const LLSD& operator[](const char*)const{return *this;}
    LLSD& operator=(const char*){return *this;} void append(LLUUID value){values.emplace_back(value);}
    LLUUID asUUID()const{return id;}
};
namespace llsd {const auto& inArray(const LLSD& value){return value.values;}}
struct Widget {
    bool visible=true,enabled=true; int scroll=0; std::string text; std::function<void()> retiring;
    void setVisible(bool v){visible=v;} void setEnabled(bool v){enabled=v;}
    void setText(const std::string& v){text=v;} std::string getText()const{return text;}
    void setToolTip(const std::string&){} void setSelection(LLUUID,bool){}
    void goToTop(){scroll=0;} void deleteAllChildren(){if(retiring){auto f=retiring;retiring={};f();}}
    template<class T>T* getChild(const char*){return this;}
};
using LLPanel=Widget; using LLTextBox=Widget; using LLScrollContainer=Widget;
using LLInventoryPanel=Widget; using LLLineEditor=Widget;
struct LLFloater {virtual ~LLFloater()=default;};
template<class T>struct LLHandle {T* value; T* get()const{return value;}};
struct Request {int cancellations=0;void cancelSuspendedOperation(){++cancellations;}};
struct LLTimer {static double getTotalSeconds(){return 100;}};
struct LLInventoryModelBackgroundFetch {
    int fetches=0; static auto& instance(){static LLInventoryModelBackgroundFetch f;return f;}
    void scheduleFolderFetch(LLUUID,bool){++fetches;}
};
template<class... T>std::string llformat(const char*,T...){return "formatted";}
namespace LLNotificationsUtil {int alerts=0;void add(const char*,const LLSD&){++alerts;}}
namespace LLInventoryLLMSort {
    constexpr size_t MAX_ITEMS=200;
    std::string trim(std::string v){return v;}
    bool validFolderName(const std::string& v){return !v.empty();}
}
class LLFloaterInventoryLLMSort;
LLFloaterInventoryLLMSort* instance=nullptr;
struct LLFloaterReg {template<class T>static T* getTypedInstance(const char*){return instance;}};
struct LLStringUtil {
    static void trim(std::string& s){auto a=s.find_first_not_of(" \n\t");s=a==s.npos?"":s.substr(a,s.find_last_not_of(" \n\t")-a+1);}
    static void toLower(std::string& s){std::transform(s.begin(),s.end(),s.begin(),[](unsigned char c){return std::tolower(c);});}
};
''' + function("bool sameName(") + function("std::string folderPath(") + r'''
class LLFloaterInventoryLLMSort : public LLFloater { public:
''' + members + r'''
    LLUUID mRoot=2,mLastRoot,mAgent=7; std::string mRootPath; bool mDirty=false; std::vector<Row> mRows;
    std::vector<Category> mCategories; std::vector<LLPanel*> mPanels;
    bool mSorting=false,mCreating=false,mLoading=false,mAttention=false,visible=false,mAutoSort=false;
    U32 mGeneration=0; double mLoadStarted=0; int renders=0,loads=0;
    std::shared_ptr<Request> mRequest; std::map<std::string,Widget> widgets;
    Widget* getChildView(const char* name){return &widgets[name];}
    template<class T>T* getChild(const char* name){return &widgets[name];}
    LLHandle<LLFloater> getHandle(){return {this};}
    bool getVisible()const{return visible;} void setFrontmost(bool){}
    void openFloater(const LLSD& key){visible=true;onOpen(key);}
    void status(const std::string& text){widgets["status"].text=text;}
    void renderRows(){++renders;mDirty=false;}
    void loadCategories(){++loads;mLoading=!gInventory.complete;}
    static void show(const std::vector<LLUUID>&);
    void onOpen(const LLSD&);void onClose(bool);void cancelSort();void chooseRoot();void setRoot(const LLUUID&);
    void approve(size_t);
    static bool folderAllowed(const LLUUID&); static bool canSort(const LLUUID&);
    bool unchanged(const Row&)const; bool rootAllowed(const LLUUID&)const; void moveItem(size_t,const LLUUID&);
};
''' + "\n".join(function(signature) for signature in (
    "bool LLFloaterInventoryLLMSort::folderAllowed(", "bool LLFloaterInventoryLLMSort::canSort(",
    "bool LLFloaterInventoryLLMSort::rootAllowed(",
    "bool LLFloaterInventoryLLMSort::unchanged(", "void LLFloaterInventoryLLMSort::moveItem(",
    "void LLFloaterInventoryLLMSort::show(", "void LLFloaterInventoryLLMSort::onOpen(",
    "void LLFloaterInventoryLLMSort::onClose(", "void LLFloaterInventoryLLMSort::cancelSort(",
    "void LLFloaterInventoryLLMSort::chooseRoot(", "void LLFloaterInventoryLLMSort::setRoot(",
    "void LLFloaterInventoryLLMSort::approve(")) + r'''
using Sort = LLFloaterInventoryLLMSort;
Sort setup() {
    gInventory={}; gAgent.id=7; LLApp::quitting=false;
    gInventory.cats[1]={1,0,7,"My Inventory",LLFolderType::FT_ROOT_INVENTORY};
    gInventory.cats[2]={2,1,7,"Clothing"}; gInventory.cats[3]={3,1,7,"Unsorted"};
    gInventory.cats[4]={4,2,7,"Tops"}; gInventory.cats[5]={5,2,7,"Shoes"};
    gInventory.items[100]=Item{};
    Sort s; s.mRootPath=folderPath(2);
    Sort::Row row; row.id=100;row.parent=3;row.name="Shirt";row.destination=4;row.folderName="Tops";row.state=Sort::State::Ready;
    s.mRows.push_back(row);return s;
}
Sort setupFolder() {
    auto s=setup();gInventory.cats[6]={6,3,7,"Shirt folder"};gInventory.cats[7]={7,6,7,"Extras"};
    gInventory.items[100].parent=6;
    s.mRows[0].id=6;s.mRows[0].name="Shirt folder";s.mRows[0].folder=true;
    return s;
}
int main() {
    int checks=0;
    {auto s=setup();assert(Sort::canSort(100));s.moveItem(0,4);assert(gInventory.moves==1&&gInventory.items[100].parent==LLUUID(4));++checks;}
    for(int scenario=0;scenario<15;++scenario) {
        auto s=setup();
        switch(scenario) {
        case 0:gInventory.items.erase(100);break;
        case 1:gInventory.items[100].parent=4;break;
        case 2:gInventory.items[100].name="Renamed";break;
        case 3:gInventory.items[100].link=true;break;
        case 4:gInventory.items[100].finished=false;break;
        case 5:gInventory.items[100].permissions.owner=9;break;
        case 6:gInventory.cats[4].name="Different category";break;
        case 7:gInventory.cats[4].parent=3;break;
        case 8:gInventory.cats.erase(4);break;
        case 9:gInventory.cats[2].name="Renamed root";break;
        case 10:gInventory.cats[2].parent=3;break;
        case 11:gAgent.id=9;break;
        case 12:gInventory.usable=false;break;
        case 13:gInventory.cats[3].parent=3;break;
        case 14:LLApp::quitting=true;break;
        }
        s.moveItem(0,4);assert(gInventory.moves==0);assert(s.mRows[0].state==Sort::State::Error);++checks;
    }
    for(auto type:{LLFolderType::FT_TRASH,LLFolderType::FT_CURRENT_OUTFIT,LLFolderType::FT_MY_OUTFITS,
         LLFolderType::FT_OUTFIT,LLFolderType::FT_MARKETPLACE_LISTINGS,LLFolderType::FT_MARKETPLACE_STOCK,
         LLFolderType::FT_MARKETPLACE_VERSION,LLFolderType::FT_INBOX,LLFolderType::FT_FAVORITE,LLFolderType::FT_CALLINGCARD}) {
        auto s=setup();gInventory.cats[3].type=type;assert(!Sort::canSort(100));++checks;
        s=setup();gInventory.cats[2].type=type;s.moveItem(0,4);assert(gInventory.moves==0);++checks;
    }
    {auto s=setup();s.mRows[0].state=Sort::State::Creating;s.mRows[0].newName="Shoes";s.moveItem(0,5);assert(gInventory.moves==1);++checks;}
    {auto s=setup();s.mRows[0].state=Sort::State::Creating;s.mRows[0].newName="Boots";s.moveItem(0,5);assert(gInventory.moves==0);++checks;}
    {auto s=setup();s.moveItem(0,5);assert(gInventory.moves==0);++checks;}
    // Sorting a clothing folder moves just that folder; all child UUIDs and parents stay intact.
    {auto s=setupFolder();assert(Sort::canSort(6));s.moveItem(0,4);
     assert(gInventory.moves==1&&gInventory.cats[6].parent==LLUUID(4));
     assert(gInventory.items[100].parent==LLUUID(6)&&gInventory.cats[7].parent==LLUUID(6));++checks;}
    for(int scenario=0;scenario<7;++scenario) {
        auto s=setupFolder();
        switch(scenario) {
        case 0:gInventory.cats.erase(6);break;
        case 1:gInventory.cats[6].parent=4;break;
        case 2:gInventory.cats[6].name="Renamed folder";break;
        case 3:gInventory.cats[6].owner=9;break;
        case 4:gInventory.cats[6].type=LLFolderType::FT_CLOTHING;break;
        case 5:gInventory.cats[6].parent=6;break;
        case 6:gInventory.cats[3].owner=9;break;
        }
        s.moveItem(0,4);assert(gInventory.moves==0&&s.mRows[0].state==Sort::State::Error);++checks;
    }
    for(auto type:{LLFolderType::FT_ROOT_INVENTORY,LLFolderType::FT_CLOTHING,LLFolderType::FT_TRASH,
        LLFolderType::FT_CURRENT_OUTFIT,LLFolderType::FT_MY_OUTFITS,LLFolderType::FT_OUTFIT,
        LLFolderType::FT_MARKETPLACE_LISTINGS,LLFolderType::FT_MARKETPLACE_STOCK,
        LLFolderType::FT_MARKETPLACE_VERSION,LLFolderType::FT_INBOX,LLFolderType::FT_FAVORITE,LLFolderType::FT_CALLINGCARD}) {
        auto s=setupFolder();gInventory.cats[6].type=type;assert(!Sort::canSort(6));++checks;
    }
    for(auto root:{6,7}) {
        auto s=setupFolder();assert(!s.rootAllowed(root));s.mRoot=root;s.mRootPath=folderPath(root);
        s.moveItem(0,4);assert(gInventory.moves==0);++checks;
    }
    {auto s=setupFolder();s.mRoot=3;s.mRootPath=folderPath(3);s.mRows[0].destination=6;s.mRows[0].folderName="Shirt folder";
     s.moveItem(0,6);assert(gInventory.moves==0);++checks;}
    {auto s=setupFolder();s.mRows[0].state=Sort::State::Creating;s.mRows[0].newName="Shoes";
     s.moveItem(0,5);assert(gInventory.moves==1&&gInventory.cats[6].parent==LLUUID(5));++checks;}
    {auto s=setupFolder();gInventory.cats[6].parent=4;s.mRows[0].parent=4;
     s.moveItem(0,4);assert(gInventory.moves==0&&s.mRows[0].state==Sort::State::Moved);++checks;}
    std::cout<<checks<<" production eligibility / move checks passed\n";
    checks=0;
    {auto s=setup();instance=&s;s.mRoot.setNull();Sort::show({100});
     assert(s.widgets["root_picker"].visible&&s.mRoot.isNull());++checks;
     s.setRoot(2);assert(s.mLastRoot==LLUUID(2)&&s.mRoot==LLUUID(2)&&s.loads==1&&s.mAutoSort);++checks;
     s.onClose(false);assert(!s.mAutoSort);s.visible=false;Sort::show({100});
     assert(s.mRoot==LLUUID(2)&&s.mLastRoot==LLUUID(2)&&!s.widgets["root_picker"].visible&&s.loads==2);++checks;
     s.setRoot(3);s.onClose(false);Sort::show({100});assert(s.mRoot==LLUUID(3)&&s.mLastRoot==LLUUID(3));++checks;}
    for(int scenario=0;scenario<5;++scenario) {
        auto s=setup();instance=&s;s.setRoot(2);
        switch(scenario) {
        case 0:gInventory.cats.erase(2);break;
        case 1:gInventory.cats[2].type=LLFolderType::FT_TRASH;break;
        case 2:gInventory.cats[2].owner=9;break;
        case 3:gInventory.cats[2].parent=6;gInventory.cats[6]={6,1,7,"Selected ancestor"};break;
        case 4:break;
        }
        Sort::show(scenario==3?std::vector<LLUUID>{6}:scenario==4?std::vector<LLUUID>{2}:std::vector<LLUUID>{100});
        assert(s.mRoot.isNull()&&s.widgets["root_picker"].visible&&!s.mAutoSort);++checks;
        // A selection that temporarily excludes the remembered root does not forget it.
        if(scenario>=3){Sort::show({100});assert(s.mRoot==LLUUID(2));++checks;}
    }
    {auto s=setup();instance=&s;s.setRoot(2);gAgent.id=9;
     for(auto& [id,cat]:gInventory.cats)cat.owner=9;gInventory.items[100].permissions.owner=9;
     Sort::show({100});assert(s.mLastRoot.isNull()&&s.mRoot.isNull()&&s.widgets["root_picker"].visible);++checks;}
    {auto s=setup();instance=&s;s.setRoot(2);gInventory.complete=false;
     const int fetches=LLInventoryModelBackgroundFetch::instance().fetches;
     Sort::show({100});assert(s.mRoot==LLUUID(2)&&s.mLoading&&s.mAutoSort);
     assert(LLInventoryModelBackgroundFetch::instance().fetches==fetches+1);++checks;}
    for(int state=0;state<3;++state) {
        auto s=setup();instance=&s;s.setRoot(2);s.visible=true;
        s.mRows.resize(13,s.mRows.front());s.mAttention=true;s.widgets["row_scroll"].scroll=400;
        s.mRows[0].state=Sort::State::Moved;s.mRows[1].state=Sort::State::Skipped;
        gInventory.items[101]=Item{};gInventory.items[101].id=101;gInventory.items[101].name="Jeans";
        s.mSorting=state==1;s.mCreating=state==2;
        s.mRequest=std::make_shared<Request>();auto request=s.mRequest;const auto generation=s.mGeneration;
        s.widgets["rows"].retiring=[&s]{assert(s.mRows.size()==13&&s.mRows.back().id==LLUUID(100));};
        Sort::show({101});
        assert(s.mRows.size()==1&&s.mRows[0].id==LLUUID(101)&&s.mRows[0].name=="Jeans");
        assert(s.mRows[0].state==Sort::State::Waiting&&s.mRows[0].destination.isNull());
        assert(s.mRoot==LLUUID(2)&&s.mGeneration>generation&&request->cancellations==1&&!s.mRequest);
        assert(!s.mSorting&&!s.mCreating&&!s.mAttention&&s.mAutoSort&&s.renders==1&&s.widgets["row_scroll"].scroll==0);++checks;
        const auto accepted=s.mGeneration;
        Sort::show({999});assert(s.mRows[0].id==LLUUID(101)&&s.mGeneration==accepted);++checks;
    }
    // Deliver actual category-creation callbacks out of order across review replacement.
    {auto s=setup();instance=&s;s.setRoot(2);s.mRows[0].state=Sort::State::NewFolder;s.mRows[0].newName="Hats";
     s.approve(0);assert(s.mCreating);auto old=gInventory.created;
     Sort::show({100});s.mRows[0].state=Sort::State::NewFolder;s.mRows[0].newName="Gloves";
     s.approve(0);assert(s.mCreating);auto current=gInventory.created;
     gInventory.cats[8]={8,2,7,"Hats"};old(8);
     assert(s.mCreating&&gInventory.moves==0&&s.mRows[0].state==Sort::State::Creating);++checks;
     gInventory.cats[9]={9,2,7,"Gloves"};current(9);
     assert(!s.mCreating&&gInventory.moves==1&&gInventory.items[100].parent==LLUUID(9));++checks;}
    {auto s=setup();instance=&s;s.setRoot(2);s.mRows.resize(13,s.mRows.front());
     s.mRows[12].state=Sort::State::NewFolder;s.mRows[12].newName="Hats";s.approve(12);auto old=gInventory.created;
     Sort::show({100});old(0);assert(s.mRows.size()==1&&s.mRows[0].state==Sort::State::Waiting&&!s.mCreating);++checks;}
    std::cout<<checks<<" production session / replacement / async callback checks passed\n";
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / "moves.cpp"
    exe = Path(directory) / "moves.exe"
    cpp.write_text(program, encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
