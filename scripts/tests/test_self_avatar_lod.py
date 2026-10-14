"""Compile the production self-LOD decisions and avatar-parent lookup with small scene mocks."""
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
volume = (ROOT/'indra/newview/llvovolume.cpp').read_text()
avatar = (ROOT/'indra/newview/llvoavatar.cpp').read_text()
objects = (ROOT/'indra/newview/llviewerobject.cpp').read_text()
ancestor = objects.split('LLVOAvatar* LLViewerObject::getAvatarAncestor()', 1)[1].split('bool LLViewerObject::isParticleSource()', 1)[0]
lod = volume.split('bool LLVOVolume::calcLOD()', 1)[1].split('    F32 radius;', 1)[0]
request = volume.split('bool LLVOVolume::setVolume(', 1)[1].split('    LLVOAvatar* wearer', 1)[1].split('    S32 lod = mLOD;', 1)[0]
joint = avatar.split('bool LLVOAvatar::updateJointLODs()', 1)[1].split('        // now select meshes', 1)[0]

code = r'''
#include <cassert>
#include <algorithm>
#include <iostream>
using F32=float; using S32=int;
#define LL_PROFILE_ZONE_SCOPED_CATEGORY_AVATAR
constexpr float AVATAR_LOD_TWEAK_RANGE=.7f;
float clamp_rescale(float v,float a,float b,float c,float d) {return c+(d-c)*std::clamp((v-a)/(b-a),0.f,1.f);}
struct LLVOAvatar;
struct LLViewerObject {
    LLViewerObject* parent=nullptr;
    LLViewerObject* getParent()const{return parent;}
    virtual LLVOAvatar* asAvatar(){return nullptr;}
    LLVOAvatar* getAvatarAncestor() const;
};
struct LLVOAvatar:LLViewerObject {
    bool self=false,mIsDummy=false;
    float mPixelArea=1,mAdjustedPixelArea=0,sLODFactor=1;
    int sNumVisibleAvatars=100;
    bool isSelf(){return self;}
    LLVOAvatar* asAvatar()override{return this;}
    float jointLOD() @JOINT@ return mAdjustedPixelArea; }
};
LLVOAvatar* LLViewerObject::getAvatarAncestor() @ANCESTOR@
struct LLVOVolume:LLViewerObject {
    struct {bool isNull(){return false;}} mDrawable;
    void* mGLTFAsset=nullptr;
    int mLOD=0,distanceLOD=0;
    bool calcLOD() @LOD@ bool changed=mLOD!=distanceLOD; mLOD=distanceLOD; return changed; }
    int requestLOD(){LLVOAvatar* wearer @REQUEST@ return mLOD;}
};
int main(){
    LLVOAvatar self,other; self.self=true;
    LLVOVolume root,child,world,remote;
    root.parent=&self;child.parent=&root;remote.parent=&other;
    for(auto* v:{&root,&child}){
        assert(v->requestLOD()==3);
        for(int detail:{0,1,2,3,1,0}){
            v->distanceLOD=detail;
            assert(!v->calcLOD() && v->mLOD==3);
        }
        v->mLOD=0;assert(v->calcLOD() && v->mLOD==3);
    }
    for(auto* v:{&world,&remote})
        for(int detail:{0,1,2,3,1,0}){
            v->distanceLOD=detail;v->calcLOD();assert(v->mLOD==detail);
            assert(v->requestLOD()==detail);
        }
    child.parent=nullptr;child.distanceLOD=0;assert(child.calcLOD() && child.mLOD==0);
    for(float pixels:{0.f,10.f,1000000.f}) for(float factor:{0.f,.5f,1.f}){
        self.mPixelArea=other.mPixelArea=pixels;self.sLODFactor=other.sLODFactor=factor;
        assert(self.jointLOD()==100000000.f);
        assert(other.jointLOD()<100000000.f);
    }
    std::cout<<"PASS: local body, linked attachments, initial requests, zoom changes, remote/world LOD, detachment\n";
}
'''.replace('@JOINT@',joint).replace('@ANCESTOR@',ancestor).replace('@LOD@',lod).replace('@REQUEST@',request)
with tempfile.TemporaryDirectory(dir=ROOT/'.logs') as directory:
    cpp,exe=Path(directory)/'self_lod.cpp',Path(directory)/'self_lod.exe'
    cpp.write_text(code)
    subprocess.run(['g++','-std=c++17',str(cpp),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

ui=ET.parse(ROOT/'indra/newview/skins/default/xui/en/panel_preferences_graphics1.xml')
slider=next(e for e in ui.iter('slider') if e.get('name')=='BoxxyHairPhysicsTravelLimit')
assert float(slider.get('max_val'))==20
assert '"BoxxyHairPhysicsTravelLimit", {0, 20}' in (ROOT/'indra/newview/llviewerautomation_settings.inc').read_text()
assert '"guide_travel"), llclamp(F32(travel), 0.f, 20.f)' in (ROOT/'indra/newview/llhairmesh.cpp').read_text()
print('PASS: guide travel range agrees across UI, automation and solver upload')
