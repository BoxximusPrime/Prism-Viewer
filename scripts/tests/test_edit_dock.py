"""Compile the production dock geometry and check its viewport boundaries."""
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'indra/newview/llfloatertools.cpp').read_text()
start = source.index('static LLRect edit_dock_rect(')
end = source.index('\n}\n', start) + 2
geometry = source[start:end]

harness = r'''
#include <algorithm>
#include <cassert>
using S32 = int;
template<class T> T llclamp(T value, T low, T high) { return std::clamp(value, low, high); }
struct LLRect {
    int mLeft=0, mTop=0, mRight=0, mBottom=0;
    LLRect()=default;
    LLRect(int l,int t,int r,int b):mLeft(l),mTop(t),mRight(r),mBottom(b){}
    int getWidth() const { return mRight-mLeft; }
    int getHeight() const { return mTop-mBottom; }
    bool isEmpty() const { return getWidth()<=0 || getHeight()<=0; }
};
'''
harness += geometry
harness += r'''
int main() {
    for (int width : {640, 879, 880, 1024, 1200, 1920, 3440})
    for (int height : {300, 459, 460, 768, 1440})
    for (int preferred : {-100, 0, 560, 720, 20000}) {
        // Include a nonzero origin, as with menu bars and scaled UI layouts.
        LLRect available(30, height+50, width+30, 50);
        LLRect dock=edit_dock_rect(available, preferred);
        if(width<880 || height<460) { assert(dock.isEmpty()); continue; }
        assert(dock.mRight==available.mRight && dock.mBottom==available.mBottom);
        assert(dock.mTop==available.mTop && dock.getWidth()>=560);
        assert(dock.mLeft-available.mLeft>=320);
        assert(dock.getWidth()+(dock.mLeft-available.mLeft)==width);
        assert(dock.getWidth()==std::clamp(preferred, 560, width-320));
    }
    assert(edit_dock_rect(LLRect(0,1000,1920,0),720).mLeft==1200);
    assert(edit_dock_rect(LLRect(0,1000,1024,0),720).mLeft==320);
    // A temporary narrow window does not alter the preferred width.
    assert(edit_dock_rect(LLRect(0,1000,1920,0),720).getWidth()==720);
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / 'dock.cpp'
    exe = Path(directory) / 'dock.exe'
    cpp.write_text(harness)
    subprocess.run(['g++', '-std=c++17', str(cpp), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

xui = ROOT / 'indra/newview/skins/default/xui/en'
floater = ET.parse(xui / 'floater_tools.xml').getroot()
assert floater.find("button[@name='edit_dock_toggle']") is not None
assert ET.parse(xui / 'main_view.xml').find(".//panel[@name='edit_dock_holder']") is not None
settings = ET.parse(ROOT / 'indra/newview/app_settings/settings.xml').getroot().find('map')
keys = [e.text for e in settings.findall('key')]
assert len(keys) == len(set(keys)), 'Duplicate settings keys'
assert {'BuildEditDocked', 'BuildEditDockWidth'} <= set(keys)
print('Dock geometry: minimum world area, width bounds, offsets, resize recovery, and UI/settings wiring passed.')
