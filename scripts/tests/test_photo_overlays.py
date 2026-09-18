"""Compile production overlay geometry/draw code with a recording GL stub."""
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT/'indra/newview/llviewerdisplay.cpp').read_text()
start = source.index('static LLRect photoFrameRect(')
end = source.index('void render_ui(F32 zoom_factor, int subfield)', start)
production = source[start:end]
snapshot_source = (ROOT/'indra/newview/llfloatersnapshot.cpp').read_text()
size_start = snapshot_source.index('static bool photoViewSize(')
size_end = snapshot_source.index('void LLFloaterSnapshot::Impl::updateResolution(',size_start)
production = snapshot_source[size_start:size_end] + production

capture = (ROOT/'indra/newview/llviewerwindow.cpp').read_text()
crop_start = capture.index('    const F32 original_view =', capture.index('bool LLViewerWindow::rawSnapshot'))
crop_end = capture.index('    for (int subimage_y', crop_start)
projection = capture[crop_start:crop_end]
restore = 'LLViewerCamera::getInstance()->setViewNoBroadcast(original_view);'
assert capture.index(restore, crop_end) > capture.index('output_buffer_offset_y +=', crop_end)

code = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <string>
#include <vector>
using F32 = float; using F64 = double;
template<class T> T llmax(T a,T b){return std::max(a,b);}
using S32 = int;
int ll_round(float x){return int(std::round(x));}
template<class T> T llclamp(T v,T low,T high) { return std::clamp(v,low,high); }
bool gSnapshot=false, gDisplaySwapBuffers=true;
struct LLFloaterSnapshot { static bool active; static float aspect; static bool photoActive(){return active;} static float photoAspectRatio(){return aspect;} };
bool LLFloaterSnapshot::active=true;
float LLFloaterSnapshot::aspect=0;
struct Settings {
    int guide=1; float alpha=.6f; bool white=true;
    int getS32(const char*) {return guide;}
    float getF32(const char*) {return alpha;}
    bool getBOOL(const char*) {return white;}
} gSavedSettings;
struct LLRect {
    int mLeft,mTop,mRight,mBottom;
    LLRect(int l=21,int t=1117,int r=1941,int b=37):mLeft(l),mTop(t),mRight(r),mBottom(b){}
    int getWidth()const{return mRight-mLeft;}int getHeight()const{return mTop-mBottom;}
};
struct Window {LLRect rect; LLRect getWorldViewRectRaw(){return rect;}void setup2DRender(){}} window;
Window* gViewerWindow=&window;
struct Program {void bind(){} void unbind(){}} gUIProgram;
struct LLTexUnit {enum{TT_TEXTURE}; void unbind(int){}} tex;
struct LLRender {enum{LINES,TRIANGLE_FAN};};
struct GL {
    std::vector<std::array<float,2>> points;
    std::array<float,4> color;
    float width=0;
    LLTexUnit* getTexUnit(int){return &tex;}
    void color4f(float r,float g,float b,float a){color={r,g,b,a};}
    void setLineWidth(float w){width=w;}
    void begin(int){}void end(){}void flush(){}
    void vertex2f(float x,float y){points.push_back({x,y});}
    void vertex2i(int x,int y){vertex2f(float(x),float(y));}
} gGL;
F32 llmin(F32 a,F32 b){return std::min(a,b);}
struct LLViewerCamera {
    F32 view=1.f;
    static LLViewerCamera* getInstance(){static LLViewerCamera camera;return &camera;}
    F32 getView(){return view;}
    void setViewNoBroadcast(F32 v){view=v;}
};
''' + production + '''
F32 captureView(bool reset_deferred,bool keep_window_aspect,LLRect window_rect,int image_width,int image_height){
''' + projection + '''
    F32 captured=LLViewerCamera::getInstance()->getView();
    ''' + restore + '''
    return captured;
}
''' + r'''
bool near(float a,float b,float e=.001f){return std::abs(a-b)<=e;}
int main(){
    int width=0,height=0;
    const LLRect native(0,1440,3440,0);
    assert(photoViewSize(0,0,native,width,height) && width==3440 && height==1440);
    assert(photoViewSize(-16,-9,native,width,height) && width==2560 && height==1440);
    assert(photoViewSize(-4,-3,native,width,height) && width==1920 && height==1440);
    assert(photoViewSize(-2,-2,native,width,height) && width==1440 && height==1440);
    assert(photoViewSize(-16,-9,LLRect(0,1200,1600,0),width,height) && width==1600 && height==900);
    assert(photoViewSize(-16,-9,LLRect(0,1080,1920,0),width,height) && width==1920 && height==1080);
    assert(!photoViewSize(-1,-1,native,width,height) && width==1920 && height==1080);
    assert(!photoViewSize(1920,1080,native,width,height));

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
        window.rect=LLRect(21,37+int(h),21+int(w),37);gGL.points.clear();
        render_photo_overlays();assert(gGL.points.size()==8);assert(gGL.width==1);
        assert(near(gGL.points[0][0],window.rect.mLeft+w/3));
        assert(gGL.points[0][1]==window.rect.mBottom);
    }
    // High-resolution direct captures match the visible crop's field of view.
    for(auto out : {std::array<int,2>{3840,2160},{5120,2160},{2160,3840},{4096,4096}}){
        LLRect viewport(0,1080,1920,0);
        auto crop=photoFrameRect(viewport,float(out[0])/out[1]);
        float captured=captureView(true,false,viewport,out[0],out[1]);
        assert(near(std::tan(captured/2)/std::tan(.5f),float(crop.getHeight())/1080,.001f));
        assert(LLViewerCamera::getInstance()->getView()==1.f);
        assert(captureView(false,false,viewport,out[0],out[1])==1.f);
        assert(captureView(true,true,viewport,out[0],out[1])==1.f);
    }
    LLFloaterSnapshot::active=false;
    assert(captureView(true,false,LLRect(0,1080,1920,0),5120,2160)==1.f);
    LLFloaterSnapshot::active=true;
    // Crop masks use output aspect, independent of resolution, guide or opacity.
    window.rect=LLRect(21,1477,3461,37);
    LLFloaterSnapshot::aspect=16.f/9.f;
    auto crop=photoFrameRect(window.rect,LLFloaterSnapshot::aspect);
    assert(crop.mLeft==461 && crop.mRight==3021 && crop.mBottom==37 && crop.mTop==1477);
    gGL.points.clear();render_photo_overlays();assert(gGL.points.size()==16);
    assert(near(gGL.points[8][0],461+2560.f/3));assert(gGL.points[8][1]==37);
    gSavedSettings.guide=0;gGL.points.clear();render_photo_overlays();assert(gGL.points.size()==8);
    gSavedSettings.guide=1;gSavedSettings.alpha=0;gGL.points.clear();render_photo_overlays();assert(gGL.points.size()==8);
    gSavedSettings.alpha=.6f;
    auto wide=photoFrameRect(LLRect(0,1080,1920,0),21.f/9);
    assert(wide.getWidth()==1920 && wide.getHeight()==823 && wide.mBottom==128);
    auto portrait=photoFrameRect(LLRect(0,1080,1920,0),2.f/3);
    assert(portrait.mLeft==600 && portrait.getWidth()==720 && portrait.getHeight()==1080);
    auto square=photoFrameRect(window.rect,1);
    assert(square.getWidth()==1440 && square.getHeight()==1440);
    for(float aspect : {0.f,-1.f,3440.f/1440}){
        auto same=photoFrameRect(window.rect,aspect);
        assert(same.mLeft==21 && same.mTop==1477 && same.mRight==3461 && same.mBottom==37);
    }
    for(int guard=0;guard<3;++guard){
        gSnapshot=guard==0;gDisplaySwapBuffers=guard!=1;LLFloaterSnapshot::active=guard!=2;
        gGL.points.clear();render_photo_overlays();assert(gGL.points.empty());
    }
    LLFloaterSnapshot::aspect=0;
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
print('PASS: aspect crop masks, guide alignment, mask visibility/capture guards; six guides across six viewport shapes, uniform resize, triangle right angles, viewport offsets, fixed line width, colors/alpha, capture/closed/off guards and XUI wiring')

capture_panel = xml.find(".//panel[@name='panel_snapshot_local']")
assert capture_panel is not None and capture_panel.get('filename')
local = ET.parse(ROOT/'indra/newview/skins/default/xui/en'/capture_panel.get('filename'))
options = local.find("combo_box[@name='local_size_combo']").findall('combo_box.item')
assert [x.get('value') for x in options[:4]] == ['[i0,i0]','[i-16,i-9]','[i-4,i-3]','[i-2,i-2]']
assert options[-1].get('value') == '[i-1,i-1]'
print('PASS: native crop options, 3440x1440 output sizes, wider-output crop, viewport resize and fixed/custom preservation')
