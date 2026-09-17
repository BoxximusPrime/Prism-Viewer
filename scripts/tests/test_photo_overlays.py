"""Compile production overlay geometry/draw code with a recording GL stub."""
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT/'indra/newview/llviewerdisplay.cpp').read_text()
start = source.index('static std::vector<std::array<F32, 4>> photoCompositionLines(')
end = source.index('void render_ui(F32 zoom_factor, int subfield)', start)
production = source[start:end]
code = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <string>
#include <vector>
using F32 = float;
using S32 = int;
template<class T> T llclamp(T v,T low,T high) { return std::clamp(v,low,high); }
bool gSnapshot=false, gDisplaySwapBuffers=true;
struct LLFloaterSnapshot { static bool active; static bool photoActive(){return active;} };
bool LLFloaterSnapshot::active=true;
struct Settings {
    int guide=1; float alpha=.6f; bool white=true;
    int getS32(const char*) {return guide;}
    float getF32(const char*) {return alpha;}
    bool getBOOL(const char*) {return white;}
} gSavedSettings;
struct LLRect {int mLeft=21,mBottom=37,w=1920,h=1080;int getWidth()const{return w;}int getHeight()const{return h;}};
struct Window {LLRect rect; LLRect getWorldViewRectRaw(){return rect;}void setup2DRender(){}} window;
Window* gViewerWindow=&window;
struct Program {void bind(){} void unbind(){}} gUIProgram;
struct LLTexUnit {enum{TT_TEXTURE}; void unbind(int){}} tex;
struct LLRender {enum{LINES};};
struct GL {
    std::vector<std::array<float,2>> points;
    std::array<float,4> color;
    float width=0;
    LLTexUnit* getTexUnit(int){return &tex;}
    void color4f(float r,float g,float b,float a){color={r,g,b,a};}
    void setLineWidth(float w){width=w;}
    void begin(int){}void end(){}void flush(){}
    void vertex2f(float x,float y){points.push_back({x,y});}
} gGL;
''' + production + r'''
bool near(float a,float b,float e=.001f){return std::abs(a-b)<=e;}
int main(){
    assert(photoCompositionLines(0,1920,1080).empty());
    assert(photoCompositionLines(99,1920,1080).empty());
    assert(photoCompositionLines(1,0,1080).empty());
    assert(photoCompositionLines(1,1920,-1).empty());
    for(auto size: {std::array<float,2>{1920,1080},{1080,1920},{1000,1000},{3440,1440},{5120,1440},{1,1}}){
        const float w=size[0],h=size[1];
        for(int guide=1;guide<=6;++guide){
            auto lines=photoCompositionLines(guide,w,h);
            assert(lines.size()==(guide==1||guide==4?4:guide>=5?3:2));
            for(auto l:lines){
                for(int i=0;i<4;++i) assert(l[i]>=0 && l[i]<=(i%2?h:w));
            }
            auto doubled=photoCompositionLines(guide,w*2,h*2);
            for(size_t i=0;i<lines.size();++i)for(int j=0;j<4;++j)
                assert(near(doubled[i][j],lines[i][j]*2));
            if(guide>=5){
                auto d=lines[0];float dx=d[2]-d[0],dy=d[3]-d[1];
                for(int i=1;i<3;++i){
                    auto l=lines[i];float x=l[2]-l[0],y=l[3]-l[1];
                    assert(std::abs((dx*x+dy*y)/(std::hypot(dx,dy)*std::hypot(x,y)))<.00001f);
                    assert(std::abs((l[2]-d[0])*dy-(l[3]-d[1])*dx)/(w*h)<.00001f);
                }
            }
        }
        auto thirds=photoCompositionLines(1,w,h);
        assert(near(thirds[0][0],w/3));assert(near(thirds[1][1],h/3));
        auto golden=photoCompositionLines(4,w,h);
        assert(near(golden[0][0]/w,.381966f));assert(near(golden[2][0]/w,.618034f));
        window.rect.w=int(w);window.rect.h=int(h);gGL.points.clear();
        render_photo_overlays();assert(gGL.points.size()==8);assert(gGL.width==1);
        assert(near(gGL.points[0][0],window.rect.mLeft+w/3));
        assert(gGL.points[0][1]==window.rect.mBottom);
    }
    // These are the real production guards, executed before any GL output.
    for(int mode=0;mode<4;++mode){
        gGL.points.clear();gSnapshot=mode==0;gDisplaySwapBuffers=mode!=1;
        LLFloaterSnapshot::active=mode!=2;gSavedSettings.guide=mode==3?0:1;
        render_photo_overlays();assert(gGL.points.empty());
    }
    gSnapshot=false;gDisplaySwapBuffers=true;LLFloaterSnapshot::active=true;gSavedSettings.guide=1;
    gSavedSettings.alpha=0;render_photo_overlays();assert(gGL.points.empty());
    gSavedSettings.alpha=.25f;gSavedSettings.white=false;render_photo_overlays();
    assert(gGL.points.size()==8 && gGL.color[0]==0 && gGL.color[3]==.25f);
    gSavedSettings.alpha=2;gSavedSettings.white=true;render_photo_overlays();
    assert(gGL.color[0]==1 && gGL.color[3]==1);
}
'''
with tempfile.TemporaryDirectory(prefix='photo-overlays-') as directory:
    cpp=Path(directory)/'test.cpp'; exe=Path(directory)/'test.exe'
    cpp.write_text(code)
    subprocess.run(['g++','-std=c++17',str(cpp),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
xml=ET.parse(ROOT/'indra/newview/skins/default/xui/en/floater_snapshot.xml')
panel=xml.find(".//panel[@name='photo_overlays']")
assert panel is not None
assert len(panel.find('combo_box').findall('combo_box.item'))==7
# The hook must stay outside the UI-enabled branch and before UI compositing.
assert 'render_photo_overlays();\n\n        if (render_ui)' in source
print('PASS: six guides across six viewport shapes, uniform resize, triangle right angles, viewport offsets, fixed line width, colors/alpha, capture/closed/off guards and XUI wiring')
