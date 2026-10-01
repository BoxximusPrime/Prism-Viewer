"""Check production Ctrl+D focus routing without a viewer. Requires g++."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'indra/newview/llviewerwindow.cpp').read_text()
start = source.index('static bool handle_inventory_delete_shortcut(')
end = source.index('bool LLViewerWindow::handleInventoryHoverKey(', start)
harness = r'''
#include <cassert>
using KEY=int; using MASK=int;
constexpr int MASK_CONTROL=1,MASK_NONE=0,KEY_DELETE=127;
struct LLView {LLView* parent=nullptr; bool visible=true,enabled=true; int deletes=0;
    virtual ~LLView()=default; LLView* getParent(){return parent;}
    bool isInVisibleChain(){return visible;} bool isInEnabledChain(){return enabled;}
    virtual bool handleKeyHere(KEY key,MASK mask){assert(key==KEY_DELETE&&mask==MASK_NONE); ++deletes; return false;}};
struct LLUICtrl:LLView {bool text=false; bool acceptsTextInput(){return text;}};
struct LLInventoryPanel:LLUICtrl {};
struct LLInventoryGallery:LLUICtrl {};
struct LLPanelMainInventory:LLUICtrl {bool gallery=false; LLInventoryPanel* panel=nullptr; LLInventoryGallery* grid=nullptr;
    bool isGalleryViewMode(){return gallery;} LLInventoryPanel* getActivePanel(){return panel;}
    template<class T>T* findChild(const char*){return dynamic_cast<T*>(grid);}};
struct LLFloater:LLUICtrl {LLPanelMainInventory* main=nullptr;
    template<class T>T* findChild(const char*){return dynamic_cast<T*>(main);}};
struct FocusMgr {LLUICtrl* focus=nullptr; bool locked=false,only=false;
    LLUICtrl* getKeyboardFocus(){return focus;} bool focusLocked(){return locked;} bool getKeystrokesOnly(){return only;}} gFocusMgr;
struct FloaterView {LLFloater* floater=nullptr; LLFloater* getParentFloater(LLView*){return floater;}} floaterView,*gFloaterView=&floaterView;
struct Keyboard {bool repeat=false; bool getKeyRepeated(KEY){return repeat;}} keyboard,*gKeyboard=&keyboard;
'''
harness += source[start:end]
harness += r'''
int main(){
    LLInventoryPanel panel; LLInventoryGallery gallery; LLUICtrl row,toolbar,editor;
    LLPanelMainInventory main; LLFloater floater;
    main.panel=&panel; main.grid=&gallery; floater.main=&main; floaterView.floater=&floater;
    row.parent=&panel; gFocusMgr.focus=&row;
    assert(handle_inventory_delete_shortcut('D',MASK_CONTROL)&&panel.deletes==1);
    assert(!handle_inventory_delete_shortcut('D',MASK_NONE)&&panel.deletes==1);
    keyboard.repeat=true; assert(handle_inventory_delete_shortcut('D',MASK_CONTROL)&&panel.deletes==1);
    keyboard.repeat=false; editor.text=true; editor.parent=&panel; gFocusMgr.focus=&editor;
    assert(!handle_inventory_delete_shortcut('D',MASK_CONTROL)&&panel.deletes==1);
    gFocusMgr.focus=&toolbar; assert(handle_inventory_delete_shortcut('D',MASK_CONTROL)&&panel.deletes==2);
    main.gallery=true; assert(handle_inventory_delete_shortcut('D',MASK_CONTROL)&&gallery.deletes==1);
    row.parent=&gallery; gFocusMgr.focus=&row;
    assert(handle_inventory_delete_shortcut('D',MASK_CONTROL)&&gallery.deletes==2);
    gallery.visible=false; assert(!handle_inventory_delete_shortcut('D',MASK_CONTROL)); gallery.visible=true;
    gallery.enabled=false; assert(!handle_inventory_delete_shortcut('D',MASK_CONTROL)); gallery.enabled=true;
    gFocusMgr.locked=true; assert(!handle_inventory_delete_shortcut('D',MASK_CONTROL)); gFocusMgr.locked=false;
    gFocusMgr.only=true; assert(!handle_inventory_delete_shortcut('D',MASK_CONTROL)); gFocusMgr.only=false;
    row.parent=nullptr; floater.main=nullptr; assert(!handle_inventory_delete_shortcut('D',MASK_CONTROL));
    gFocusMgr.focus=nullptr; assert(!handle_inventory_delete_shortcut('D',MASK_CONTROL));
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp, binary = Path(directory) / 'check.cpp', Path(directory) / 'check.exe'
    cpp.write_text(harness)
    subprocess.run(['g++', '-std=c++17', str(cpp), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print('Ctrl+D inventory focus, gallery, text-entry, repeat and visibility checks passed.')
