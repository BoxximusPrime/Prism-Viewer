"""Compile the production name matcher and check hair/SSS selection boundaries."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    source = (ROOT / 'indra/newview/llvovolume.cpp').read_text()
    matcher = source[source.index('bool matchesSurfaceNames('):
                     source.index('bool isUsableSSSDescription(')]
    start = source.index('bool LLVOVolume::isHairInRange(')
    hair_range = source[start:source.index('bool LLVOVolume::isHairEnabled()', start)]
    start = source.index('bool LLVOVolume::isHairEnabled()')
    hair_physics = source[start:source.index('bool LLVOVolume::isSSSOverlayEnabled()', start)]
    cpp = r'''
#include <algorithm>
#include <cassert>
#include <cctype>
#include <cstdio>
#include <map>
#include <sstream>
#include <set>
#include <string>
#include <vector>
std::map<std::string, std::string> gSavedSettings;
template<class T> struct LLCachedControl {
    std::string key;
    LLCachedControl(decltype(gSavedSettings)&, const char* name) : key(name) {}
    operator const T&() const { return gSavedSettings[key]; }
};
struct LLStringUtil {
    static void toLower(std::string& s) {
        for (char& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    static void trim(std::string& s) {
        const auto first = s.find_first_not_of(" \t\r\n");
        s = first == std::string::npos ? "" : s.substr(first, s.find_last_not_of(" \t\r\n") - first + 1);
    }
    static std::vector<std::string> getTokens(const std::string& s, const char*) {
        std::vector<std::string> result;
        std::istringstream stream(s);
        for (std::string token; std::getline(stream, token, ',');) result.push_back(token);
        return result;
    }
};
using F32 = float;
template<class T> T llmax(T a, T b) { return std::max(a, b); }
template<> struct LLCachedControl<bool> {
    std::string key;
    LLCachedControl(decltype(gSavedSettings)&, const char* name, bool) : key(name) {}
    operator bool() const { return gSavedSettings[key] == "1"; }
};
template<> struct LLCachedControl<F32> {
    std::string key;
    LLCachedControl(decltype(gSavedSettings)&, const char* name, F32) : key(name) {}
    operator F32() const { return std::stof(gSavedSettings[key]); }
};
struct LLVector3 {
    float x = 0, y = 0, z = 0;
    LLVector3()=default;
    LLVector3(float a,float b,float c):x(a),y(b),z(c){}
    LLVector3 operator+(LLVector3 b) const { return {x+b.x,y+b.y,z+b.z}; }
    LLVector3 operator-(LLVector3 b) const { return {x-b.x,y-b.y,z-b.z}; }
    float lengthSquared() const { return x*x+y*y+z*z; }
};
struct LLQuaternion {};
LLVector3 operator*(LLVector3 p, LLQuaternion) {return p;}
struct LLJoint {
    LLVector3 getWorldPosition()const{return {1,2,3};}
    LLQuaternion getWorldRotation()const{return {};}
};
struct LLViewerCamera {
    LLVector3 position;
    static LLViewerCamera& instance() { static LLViewerCamera camera; return camera; }
    LLVector3 getOrigin() const { return position; }
};
struct LLVOAvatar;
struct LLViewerObject {
    bool dead = false, hud = false, avatar = false;
    LLVector3 position;
    LLVOAvatar* wearer = nullptr;
    int id=1;
    std::string name="Hair";
    bool cached=true;
    bool hasCachedObjectName()const{return cached;}
    const std::string& getCachedObjectName()const{return name;}
    const std::string& getAttachmentItemName()const{return name;}
    int getID()const{return id;}
    bool isDead() const { return dead; }
    bool isHUDAttachment() const { return hud; }
    bool isAvatar() const { return avatar; }
    LLVOAvatar* getAvatar() const { return wearer; }
    LLVector3 getRenderPosition() const { return position; }
};
struct LLVOAvatar : LLViewerObject {
    bool self = false;
    LLVOAvatar() { avatar = true; }
    bool isSelf() const { return self; }
    LLJoint head;
    LLJoint* mHeadp=&head;
};
std::set<int> sRenderQueuedObjectIDs;
struct Requests {void push_front(std::pair<int,int>) {}} sRenderPropertyRequests;
struct LLVOVolume:LLViewerObject {
    static bool isHairInRange(const LLViewerObject*);
    bool isHairEnabled()const;
    bool getHairPhysicsFrame(LLVector3&,LLQuaternion&)const;
    mutable bool mLastHairState=false;
    LLViewerObject* root=nullptr;
    const LLViewerObject* getRootEdit()const{return root ? root : this;}
    LLVOAvatar* getAvatarAncestor()const{return wearer;}
    bool isVisible()const{return true;}
    bool getRegion()const{return true;}
};
@RANGE@
@MATCHER@
@PHYSICS@
int main() {
    gSavedSettings["BoxxyHairNames"] = "hair";
    for (const char* name : {"hair", "HAIRSTYLE", "[Brand] hair - black", "Brand_hair", "chair hair"})
        assert(matchesSurfaceNames(name, 2));
    for (const char* name : {"chair", "armchair", "wheelchair", "", "ha ir", "1hair"})
        assert(!matchesSurfaceNames(name, 2));
    gSavedSettings["BoxxyHairNames"] = "  PONYTAIL , , hair  ";
    assert(matchesSurfaceNames("Brand Ponytail", 2));
    assert(matchesSurfaceNames("Hair", 2));
    assert(!matchesSurfaceNames("chair", 2));
    gSavedSettings["BoxxyHairNames"] = "";
    assert(!matchesSurfaceNames("Hair", 2));
    gSavedSettings["BoxxyHairNames"] = "wig";
    assert(!matchesSurfaceNames("Hair", 2));
    assert(matchesSurfaceNames("[WIG]", 2));
    // The shared cache must preserve SSS's existing substring semantics.
    gSavedSettings["BoxxySSSWhitelist"] = "body";
    gSavedSettings["BoxxySSSOverlayNames"] = "tattoo";
    assert(matchesSurfaceNames("eBODY"));
    assert(matchesSurfaceNames("eTattoo", 1));
    assert(!matchesSurfaceNames("eBODY", 2));
    assert(!matchesSurfaceNames("wig"));
    gSavedSettings["BoxxyHairEnabled"] = "1";
    gSavedSettings["BoxxyHairSelfOnly"] = "1";
    gSavedSettings["BoxxyHairMaxDistance"] = "10";
    LLVOAvatar self, other;
    self.self = true;
    LLViewerObject own_hair, other_hair, world;
    own_hair.wearer = &self; other_hair.wearer = &other;
    assert(LLVOVolume::isHairInRange(&own_hair));
    assert(LLVOVolume::isHairInRange(&self)); // depth focus uses the avatar
    assert(!LLVOVolume::isHairInRange(&other_hair));
    assert(!LLVOVolume::isHairInRange(&other));
    assert(!LLVOVolume::isHairInRange(&world));
    assert(!LLVOVolume::isHairInRange(nullptr));
    own_hair.position = {500,0,0}; // attachment-local position must not set the range
    assert(LLVOVolume::isHairInRange(&own_hair));
    self.position = {9.143f,0,0};
    assert(LLVOVolume::isHairInRange(&own_hair));
    self.position = {10.f * .9144f,0,0};
    assert(!LLVOVolume::isHairInRange(&own_hair));
    self.position = {10,0,0};
    assert(!LLVOVolume::isHairInRange(&self));
    LLViewerCamera::instance().position = {2,0,0};
    assert(LLVOVolume::isHairInRange(&self));
    own_hair.hud = true;
    assert(!LLVOVolume::isHairInRange(&own_hair));
    own_hair.hud = false; own_hair.dead = true;
    assert(!LLVOVolume::isHairInRange(&own_hair));
    gSavedSettings["BoxxyHairSelfOnly"] = "0";
    assert(LLVOVolume::isHairInRange(&other_hair));
    assert(LLVOVolume::isHairInRange(&world));
    gSavedSettings["BoxxyHairMaxDistance"] = "1";
    assert(!LLVOVolume::isHairInRange(&other_hair));
    gSavedSettings["BoxxyHairMaxDistance"] = "0";
    assert(!LLVOVolume::isHairInRange(&world));
    gSavedSettings["BoxxyHairMaxDistance"] = "10";
    gSavedSettings["BoxxyHairEnabled"] = "0";
    assert(!LLVOVolume::isHairInRange(&other_hair));
    gSavedSettings["BoxxyHairNames"] = "hair";
    LLVOVolume local, remote, loose;
    local.wearer=&self; remote.wearer=&other;
    LLVector3 pivot; LLQuaternion rotation;
    for(bool lighting:{false,true})for(bool physics:{false,true}) {
        gSavedSettings["BoxxyHairEnabled"]=lighting ? "1":"0";
        gSavedSettings["BoxxyHairPhysicsEnabled"]=physics ? "1":"0";
        assert(local.isHairEnabled()==(lighting||physics));
        assert(!local.mLastHairState); // Collision discovery must not hide a pending batch refresh.
        assert(remote.isHairEnabled()==lighting && loose.isHairEnabled()==lighting);
        assert(local.getHairPhysicsFrame(pivot,rotation)==physics);
        assert(!remote.getHairPhysicsFrame(pivot,rotation) && !loose.getHairPhysicsFrame(pivot,rotation));
        if(physics) assert(pivot.x==1 && pivot.y==2 && pivot.z>3.079f && pivot.z<3.081f);
    }
    gSavedSettings["BoxxyHairEnabled"]="0";
    gSavedSettings["BoxxyHairMaxDistance"]="0";
    assert(local.isHairEnabled() && !LLVOVolume::isHairInRange(&local));
    local.cached=false; local.root=&own_hair;
    assert(local.isHairEnabled()); // linked child uses its attachment root name
    local.hud=true;
    assert(!local.getHairPhysicsFrame(pivot,rotation));
    local.hud=false; local.dead=true;
    assert(!local.getHairPhysicsFrame(pivot,rotation));
    local.dead=false; self.mHeadp=nullptr;
    assert(!local.getHairPhysicsFrame(pivot,rotation));
    puts("Passed hair name boundaries, case, custom terms, cache invalidation SSS isolation, self-only ownership and camera-distance limits");
    puts("Passed all four lighting/physics combinations, local-only physics, linked hair, HUD and missing-head guards");
}
'''.replace('@MATCHER@', matcher).replace('@RANGE@', hair_range).replace('@PHYSICS@', hair_physics)
    compiler = shutil.which('g++')
    assert compiler, 'g++ is required'
    with tempfile.TemporaryDirectory(prefix='boxxy-hair-selection-', dir=ROOT/'.logs') as directory:
        src, exe = Path(directory) / 'test.cpp', Path(directory) / 'test.exe'
        src.write_text(cpp)
        subprocess.run([compiler, '-std=c++17', str(src), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
