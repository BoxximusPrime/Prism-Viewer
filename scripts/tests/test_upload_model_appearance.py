"""Native preview-slot/lifecycle checks plus upload/XUI isolation. Requires g++."""
from pathlib import Path
import argparse
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
root = parser.parse_args().root
model = (root/'indra/newview/llmodelpreview.cpp').read_text(encoding='utf-8')
floater = (root/'indra/newview/llfloatermodelpreview.cpp').read_text(encoding='utf-8')
header = (root/'indra/newview/llmodelpreview.h').read_text(encoding='utf-8')

def function(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 1
    end = brace+1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]

bodies = '\n'.join(function(model, signature) for signature in (
    'std::vector<LLModelPreview::PreviewSlot> LLModelPreview::getPreviewSlots() const',
    'void LLModelPreview::setPreviewAppearance(',
    'void LLModelPreview::clearPreviewAppearance(',
    'const LLModelPreview::PreviewAppearance* LLModelPreview::getPreviewAppearance('))
bodies += '\n'+function(floater, 'std::vector<LLModelPreview::PreviewSlot> selected_preview_slots(')

# Exercise the production bodies with small fixture types, without starting a
# viewer, connecting to a grid, allocating GL resources or invoking uploads.
harness = r'''
#include <algorithm>
#include <cassert>
#include <map>
#include <memory>
#include <string>
#include <vector>
using S32=int;
struct LLModel { std::vector<std::string> mMaterialList; };
struct LLModelInstance { std::shared_ptr<LLModel> mModel; std::map<std::string,std::string> mMaterial; };
struct Floater { bool textures=false; void childSetValue(const char* name,bool enabled) {
    assert(std::string(name)=="show_textures"); textures=enabled;
} };
struct LLModelPreview {
    using PreviewSlot=std::pair<LLModel*,std::string>;
    struct PreviewAppearance { std::string label; };
    std::vector<LLModelInstance> mUploadData;
    std::map<PreviewSlot,PreviewAppearance> mPreviewAppearance;
    std::map<std::string,bool> mViewOption;
    Floater* mFMP;
    int camera=23, previewLOD=3, renders=0;
    bool includeTextures=false;
    void refresh() { ++renders; }
    std::vector<PreviewSlot> getPreviewSlots() const;
    void setPreviewAppearance(const std::vector<PreviewSlot>&,const PreviewAppearance&);
    void clearPreviewAppearance(const std::vector<PreviewSlot>& slots={});
    const PreviewAppearance* getPreviewAppearance(const PreviewSlot&) const;
};
''' + bodies + r'''
int main() {
    Floater ui;
    LLModelPreview preview; preview.mFMP=&ui;
    auto lantern=std::make_shared<LLModel>(); lantern->mMaterialList={"opaque","glass"};
    auto base=std::make_shared<LLModel>(); base->mMaterialList={"opaque"};
    preview.mUploadData={{lantern,{{"opaque","original"},{"glass","original"}}},
        {lantern,{{"opaque","original"},{"glass","original"}}},{base,{{"opaque","original"}}}};
    const auto slots=preview.getPreviewSlots(); assert(slots.size()==3);
    assert(slots[0].first==lantern.get() && slots[1].second=="glass" && slots[2].first==base.get());
    assert(selected_preview_slots(&preview,0)==slots);
    assert(selected_preview_slots(&preview,2)==std::vector<LLModelPreview::PreviewSlot>{slots[1]});
    assert(selected_preview_slots(&preview,-1).empty() && selected_preview_slots(&preview,4).empty());
    preview.setPreviewAppearance(slots,{"local image"});
    assert(preview.mPreviewAppearance.size()==3 && ui.textures && preview.mViewOption["show_textures"]);
    preview.setPreviewAppearance({slots[1]},{"glass PBR"});
    assert(preview.getPreviewAppearance(slots[0])->label=="local image");
    assert(preview.getPreviewAppearance(slots[1])->label=="glass PBR");
    assert(preview.getPreviewAppearance(slots[2])->label=="local image");
    preview.previewLOD=1; assert(preview.getPreviewSlots()==slots);
    preview.clearPreviewAppearance({slots[1]});
    assert(!preview.getPreviewAppearance(slots[1]) && preview.mPreviewAppearance.size()==2);
    preview.clearPreviewAppearance(); assert(preview.mPreviewAppearance.empty());
    assert(preview.camera==23 && !preview.includeTextures);
    for (const auto& instance:preview.mUploadData)
        for(const auto& material:instance.mMaterial) assert(material.second=="original");
    assert(preview.renders==4);
}
'''
compiler = shutil.which('g++')
assert compiler, 'g++ required for native fixture checks'
with tempfile.TemporaryDirectory() as directory:
    cpp, binary = Path(directory)/'preview.cpp', Path(directory)/'preview.exe'
    cpp.write_text(harness, encoding='utf-8')
    subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)

# Guard the payment boundary and obsolete picker callbacks in the actual code.
for source, signature in ((model,'void LLModelPreview::rebuildUploadData('),
    (model,'void LLModelPreview::saveUploadData(const std::string&'),
    (floater,'void LLFloaterModelPreview::onClickCalculateBtn('),
    (floater,'void LLFloaterModelPreview::onUpload(')):
    assert 'PreviewAppearance' not in function(source,signature)
picker = function(floater,'void LLFloaterModelPreview::onPreviewImage(')
assert 'handle.get()' in picker and 'mPreviewAppearanceRequest != request' in picker
assert '++mPreviewAppearanceRequest' in function(floater,'void LLFloaterModelPreview::clearPreviewAppearance(')
assert 'clearPreviewAppearance()' in function(floater,'void LLFloaterModelPreview::onClose(')
assert 'clearPreviewAppearance()' in function(model,'void LLModelPreview::loadModel(')
assert 'slots != mPreviewSlots' in function(floater,'void LLFloaterModelPreview::updatePreviewAppearanceControls(')
for signature in ('void LLFloaterModelPreview::onPreviewMaterial(', 'void LLFloaterModelPreview::onPreviewImage(',
                  'void LLFloaterModelPreview::onPreviewChecker('):
    body=function(floater,signature)
    assert all(word not in body for word in ('queueApply','queueModify','uploadModel','onUpload','upload_textures'))

xml=ET.parse(root/'indra/newview/skins/default/xui/en/floater_model_preview.xml').getroot()
controls={node.get('name'):node for node in xml.iter() if node.get('name')}
for name in ('preview_material_slot','preview_image','preview_material','preview_checker','preview_clear','preview_appearance_status'):
    assert name in controls
assert controls['preview_material'].get('no_commit_on_selection')=='true'
assert 'base color only' in controls['preview_rigged_fallback'].text
assert 'LLPointer<LLFetchedGLTFMaterial> material;' in header
print('Native all/per-slot assignment, model identity, LOD retention, clear/camera/upload isolation, stale callbacks and XUI checks passed.')
