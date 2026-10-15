"""Exercise photo framing and depth-based mannequin compositing, plus entry-point wiring."""
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from test_camera_smoothing import function

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / 'indra/newview/skins/default/xui/en'
pipeline = (ROOT / 'indra/newview/pipeline.cpp').read_text(encoding='utf-8')
post_sort = pipeline.split('void LLPipeline::postSort(', 1)[1]
alpha_guard = re.search(r'if \(([^\n]+hasRenderType\(LLPipeline::RENDER_TYPE_PASS_ALPHA\))\)', post_sort).group(1)
with tempfile.TemporaryDirectory() as directory:
    cpp, exe = Path(directory) / 'photo.cpp', Path(directory) / 'photo.exe'
    cpp.write_text(r'''
#include "llquickphotomath.h"
#include <cassert>
int main() {
    using namespace LLQuickPhoto;
    assert(frame(0).height == 256 && frame(2).height == 256);
    assert(frame(1).height == 512 && frame(3).height == 512);
    assert(frame(0).yaw > 0 && frame(1).yaw == 0);
    for (int preset=0; preset<4; ++preset) {
        for (float height: {0.5f, 1.3f, 2.f, 3.f, 5.f}) {
            const auto crop = frame(preset);
            const float d = distance(height, preset, .65f, 1.f);
            const float view_height = 2.f*d*std::tan(.65f*.5f);
            assert(view_height + .00001f >= height*(crop.top-crop.bottom));
            if (preset == 1) assert(view_height*.5f + .00001f >= height*.54f);
            assert(std::abs(distance(height, preset, .65f, .5f)-2*d)<.00001f);
        }
    }
    unsigned char rgb[] = {255,0,0, 0,255,0, 0,0,255, 100,100,100};
    float scene[] = {.5f,.2f,1.f,.4f};
    float body[] = {.5f,.6f,1.f,1.f};
    desaturate(rgb,scene,body,4);
    assert(rgb[0]==53 && rgb[1]==53 && rgb[2]==53); // Visible body.
    assert(rgb[3]==0 && rgb[4]==255 && rgb[5]==0); // Clothing in front stays coloured.
    assert(rgb[6]==0 && rgb[7]==0 && rgb[8]==255); // Background stays untouched.
    assert(rgb[9]==100 && rgb[10]==100 && rgb[11]==100); // No body underneath.
}
''', encoding='utf-8')
    # Exercise the actual group-collection guard: impostors also set the shadow flag.
    with cpp.open('a', encoding='utf-8') as output:
        output.write('''
int viewport_width=256, viewport_height=512;
void glClearColor(float, float, float, float) {}
struct WaterMask {
    int binds=0;
    void bindTarget() { ++binds; viewport_width=3440; viewport_height=1369; }
    void clear() {}
    // LLRenderTarget::flush rebinds the previous target at its full size.
    void flush() { viewport_width=viewport_height=512; }
};
struct WaterPool { int draws=0; void render() { ++draws; } } water_pool;
struct LLPipeline {
    enum { RENDER_TYPE_PASS_ALPHA };
    static inline bool sImpostorRender=false;
    WaterMask mWaterExclusionMask;
    WaterPool* mWaterExclusionPool=&water_pool;
    void doWaterExclusionMask();
};
''' + function('indra/newview/pipeline.cpp', 'void LLPipeline::doWaterExclusionMask()') + '''
bool collects_alpha(bool sShadowRender, bool sImpostorRender, bool enabled) {
    auto hasRenderType = [enabled](int) { return enabled; };
    return ''' + alpha_guard + ''';
}
struct CheckAlphaPasses {
    CheckAlphaPasses() {
        assert(collects_alpha(false, false, true)); // World.
        assert(!collects_alpha(true, false, true)); // Real shadow map.
        assert(collects_alpha(true, true, true)); // Avatar preview / impostor.
        assert(collects_alpha(false, true, true));
        for (bool shadow : {false, true}) for (bool impostor : {false, true})
            assert(!collects_alpha(shadow, impostor, false));
        LLPipeline pipe;
        LLPipeline::sImpostorRender=true;
        for (int height : {256, 512}) {
            viewport_width=256; viewport_height=height;
            pipe.doWaterExclusionMask();
            assert(viewport_width==256 && viewport_height==height);
            assert(pipe.mWaterExclusionMask.binds==0 && water_pool.draws==0);
        }
        LLPipeline::sImpostorRender=false;
        pipe.doWaterExclusionMask();
        assert(pipe.mWaterExclusionMask.binds==1 && water_pool.draws==1);
    }
} check_alpha_passes;
''')
    subprocess.run(['g++', '-std=c++17', '-I', str(ROOT / 'indra/newview'), str(cpp), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

for name, callback in [('menu_outfit_tab.xml','Outfit.QuickPhoto'),
                       ('menu_gallery_outfit_tab.xml','Outfit.QuickPhoto'),
                       ('menu_outfit_gear.xml','Gear.QuickPhoto')]:
    entry = next(n for n in ET.parse(UI / name).getroot() if n.get('name') == 'quick_photo')
    assert entry.find('on_click').get('function') == callback
for name in ('floater_change_item_thumbnail.xml','panel_prism_collections.xml','floater_prism_collection.xml'):
    assert ET.parse(UI / name).find('.//*[@name="quick_photo"]') is not None
entry = ET.parse(UI / 'menu_inventory.xml').find('.//*[@name="quick_photo"]/menu_item_call.on_click')
assert entry.get('function') == 'Inventory.DoToSelected' and entry.get('parameter') == 'quick_photo'
folder_action = function('indra/newview/llinventorybridge.cpp', 'void LLFolderBridge::performAction(')
assert 'LLFloaterReg::showInstance("quick_photo", LLSD(mUUID))' in folder_action
folder_menu = function('indra/newview/llinventorybridge.cpp', 'void LLFolderBridge::buildContextMenuOptions(')
agent_menu = folder_menu.split('else if(isAgentInventory())', 1)[1].split('// Preemptively disable', 1)[0]
assert re.search(r'if \(\(flags & ITEM_IN_MULTI_SELECTION\) == 0\)\s*\{\s*items.push_back\(std::string\("quick_photo"\)\)', agent_menu)
ui = ET.parse(UI / 'floater_quick_photo.xml').getroot()
names = [n.get('name') for n in ui if n.get('name')]
assert len(names) == len(set(names))
assert len(ui.find('.//*[@name="preset"]')) == 4
assert len(ui.find('.//*[@name="background"]')) == 3
for node in ui:
    if all(k in node.attrib for k in ('left','top','width','height')):
        assert int(node.get('left')) + int(node.get('width')) <= int(ui.get('width'))
        assert int(node.get('top')) + int(node.get('height')) <= int(ui.get('height'))
source = (ROOT / 'indra/newview/llfloaterquickphoto.cpp').read_text(encoding='utf-8')
assert 'sendAnimationRequest' not in source
assert 'if (mUploadedAsset.notNull()) { uploadThumbnail(); return; }' in source
assert 'thumbnail->scale(128, 256)' in source and 'square->setSubImage(64, 0, 128, 256' in source
assert 'setViewNoBroadcast' in source and 'LLViewerDynamicTexture::postRender(false)' in source
assert 'if (!mPreview->currentLook())' in source
print('Photo framing, mannequin depth masking, alpha collection and viewport preservation, tall thumbnail padding and UI bindings passed.')
