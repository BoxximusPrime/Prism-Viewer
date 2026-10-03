"""Exercise the production borderless switch with simulated Win32 calls. Requires g++."""
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[2]
source = (root / 'indra/llwindow/llwindowwin32.cpp').read_text()
start = source.index('bool LLWindowWin32::setBorderlessFullscreen(')
end = source.index('\n}\n', start) + 3
method = source[start:end]
assert 'wgl' not in method and 'recreateWindow(' not in method
harness = r'''
#include <cassert>
#include <future>
#include <iostream>
using LONG_PTR=long long; using HWND=void*;
constexpr int GWL_STYLE=1,GWL_EXSTYLE=2,ERROR_SUCCESS=0,MONITOR_DEFAULTTONEAREST=2,SW_RESTORE=9;
constexpr LONG_PTR WS_OVERLAPPEDWINDOW=15,WS_POPUP=16,WS_MAXIMIZE=32,WS_MINIMIZE=64,WS_EX_WINDOWEDGE=1,WS_EX_CLIENTEDGE=2;
constexpr int SWP_FRAMECHANGED=1,SWP_NOOWNERZORDER=2,SWP_NOMOVE=4,SWP_NOSIZE=8,SWP_NOZORDER=16,SWP_NOACTIVATE=32;
HWND HWND_TOP=reinterpret_cast<HWND>(1);
struct RECT {int left=0,top=0,right=0,bottom=0;};
struct WINDOWPLACEMENT {unsigned length=0; int showCmd=1; RECT rcNormalPosition;};
struct MONITORINFO {unsigned cbSize=0; RECT rcMonitor;};
struct Native {
    WINDOWPLACEMENT placement{sizeof(WINDOWPLACEMENT),1,{80,100,1080,800}};
    LONG_PTR style=WS_OVERLAPPEDWINDOW,exstyle=WS_EX_WINDOWEDGE|WS_EX_CLIENTEDGE;
    RECT bounds{-1920,0,0,1080}; int error=0,fail=0,calls=0;
    bool allow(int step){++calls;if(fail==step){fail=0;error=5;return false;}return true;}
} native;
void SetLastError(int code){native.error=code;} int GetLastError(){return native.error;}
bool GetWindowPlacement(HWND,WINDOWPLACEMENT* p){if(!native.allow(1))return false;*p=native.placement;return true;}
int MonitorFromWindow(HWND,int){return 1;}
bool GetMonitorInfo(int,MONITORINFO* m){if(!native.allow(2))return false;m->rcMonitor=native.bounds;return true;}
LONG_PTR GetWindowLongPtr(HWND,int index){return index==GWL_STYLE?native.style:native.exstyle;}
LONG_PTR SetWindowLongPtr(HWND,int index,LONG_PTR value){
    if(!native.allow(index==GWL_STYLE?3:4))return 0;
    auto& field=index==GWL_STYLE?native.style:native.exstyle; auto old=field;field=value;return old;
}
void ShowWindow(HWND,int){native.placement.showCmd=1;}
bool SetWindowPos(HWND,HWND,int x,int y,int width,int height,int flags){
    if(!native.allow(5))return false;
    assert(flags&SWP_FRAMECHANGED);
    if(!(flags&SWP_NOMOVE))native.placement.rcNormalPosition={x,y,x+width,y+height};
    return true;
}
bool SetWindowPlacement(HWND,const WINDOWPLACEMENT* placement){if(!native.allow(6))return false;native.placement=*placement;return true;}
struct Thread {template<class F>void post(F work){work();}} thread;
#define LL_WARNS(x) std::cerr
#define LL_ENDL std::endl
struct LLWindowWin32 {
    HWND mWindowHandle=reinterpret_cast<HWND>(2); bool mFullscreen=false,mBorderlessFullscreen=false;
    LONG_PTR mWindowedStyle=0,mWindowedExStyle=0; WINDOWPLACEMENT mWindowedPlacement{};
    Thread* mWindowThread=&thread; bool setBorderlessFullscreen(bool);
};
bool same(RECT a,RECT b){return a.left==b.left&&a.top==b.top&&a.right==b.right&&a.bottom==b.bottom;}
int main();
'''
harness += method
harness += r'''
int main(){
    for(int show:{1,3}){
        native=Native{}; native.placement.showCmd=show;
        if(show==3)native.style|=WS_MAXIMIZE;
        auto original=native; LLWindowWin32 window;
        assert(window.setBorderlessFullscreen(true)&&window.mBorderlessFullscreen);
        assert(same(native.placement.rcNormalPosition,native.bounds));
        assert(native.style==WS_POPUP&&native.exstyle==0);
        int calls=native.calls; assert(window.setBorderlessFullscreen(true)&&native.calls==calls);
        assert(window.setBorderlessFullscreen(false)&&!window.mBorderlessFullscreen);
        assert(native.style==original.style&&native.exstyle==original.exstyle);
        assert(native.placement.showCmd==show&&same(native.placement.rcNormalPosition,original.placement.rcNormalPosition));
    }
    for(int failure:{1,2,3,4,5}){
        native=Native{};auto original=native; native.fail=failure;LLWindowWin32 window;
        assert(!window.setBorderlessFullscreen(true)&&!window.mBorderlessFullscreen);
        assert(native.style==original.style&&native.exstyle==original.exstyle);
        assert(same(native.placement.rcNormalPosition,original.placement.rcNormalPosition));
    }
    for(int failure:{3,4,5,6}){
        native=Native{};LLWindowWin32 window;assert(window.setBorderlessFullscreen(true));
        auto original=native;native.fail=failure;
        assert(!window.setBorderlessFullscreen(false)&&window.mBorderlessFullscreen);
        assert(native.style==original.style&&native.exstyle==original.exstyle);
        assert(same(native.placement.rcNormalPosition,original.placement.rcNormalPosition));
    }
    LLWindowWin32 exclusive;exclusive.mFullscreen=true;assert(!exclusive.setBorderlessFullscreen(true));
    LLWindowWin32 missing;missing.mWindowHandle=nullptr;assert(!missing.setBorderlessFullscreen(true));
}
'''
ui = ET.parse(root / 'indra/newview/skins/default/xui/en/panel_preferences_graphics1.xml').getroot()
general = next(n for n in ui.iter('panel') if n.get('name') == 'graphics_general_panel')
checkbox = next(n for n in general if n.get('name') == 'BorderlessFullscreen')
assert checkbox.get('control_name') == 'BorderlessFullscreen'
ET.parse(root / 'indra/newview/app_settings/settings.xml')
viewer = (root / 'indra/newview/llviewerwindow.cpp').read_text()
assert 'if (!maximized && !mWindow->getBorderlessFullscreen())' in viewer
app = (root / 'indra/newview/llappviewer.cpp').read_text()
assert '!gSavedSettings.getBOOL("BorderlessFullscreen")' in app
assert 'if (!maximized && !gViewerWindow->getWindow()->getBorderlessFullscreen())' in app
with tempfile.TemporaryDirectory() as directory:
    cpp, binary = Path(directory) / 'check.cpp', Path(directory) / 'check.exe'
    cpp.write_text(harness)
    subprocess.run(['g++', '-std=c++17', str(cpp), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print('Monitor bounds, normal/maximized restoration, repeated toggles, rollback and UI/settings checks passed.')
