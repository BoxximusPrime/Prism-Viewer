"""Run the production appearance deferral guards and release method with fake faces.

Requires g++ on PATH. Checks latest-update coalescing, resume, and removed faces.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root/'indra/newview/llvovolume.cpp').read_text()


def method(signature):
    start = source.index(signature)
    return source[start:source.index('\n}', start)+2]


code = r'''
#include <cassert>
#include <unordered_map>
using U8=unsigned char;
using S32=int;
using LLUUID=int;
using LLColor4=float;
struct Settings {
    bool frozen=false;
    bool getBOOL(const char*) { return frozen; }
} gSavedSettings;
struct LLVOVolume {
    bool mDrawable=true, dead=false;
    int faces=2, writes=0;
    int textures[2]={10,20};
    float colors[2]={1,1};
    std::unordered_map<U8,LLUUID> mPhotoPendingTextures;
    std::unordered_map<U8,LLColor4> mPhotoPendingColors;
    bool getTE(U8 face) { return face<faces; }
    int getNumTEs() { return faces; }
    bool isDead() { return dead; }
    S32 setTETexture(U8, const LLUUID&);
    S32 setTEColor(U8, const LLColor4&);
    void resumePhotoAppearance();
};
'''
# Use the actual guards, substituting only the downstream rendering work.
for signature, boundary, assignment in (
    ('S32 LLVOVolume::setTETexture(const U8 te, const LLUUID &uuid)',
     '    S32 res =', 'textures[te]=uuid;'),
    ('S32 LLVOVolume::setTEColor(const U8 te, const LLColor4& color)',
     '    S32 retval =', 'colors[te]=color;'),
):
    body = method(signature)
    code += body[:body.index(boundary)] + assignment + ' ++writes; return 1;\n}\n'
code += method('void LLVOVolume::resumePhotoAppearance()')
code += r'''
int main() {
    LLVOVolume v;
    gSavedSettings.frozen=true;
    v.setTEColor(0,0.f);
    v.setTEColor(0,.5f);
    v.setTETexture(0,0);
    v.setTETexture(0,99);
    v.setTETexture(1,88);
    assert(v.colors[0]==1 && v.textures[0]==10 && v.writes==0);
    assert(v.mPhotoPendingTextures.size()==2);
    v.faces=1; // Changed topology must not apply an update to a removed face.
    gSavedSettings.frozen=false;
    v.resumePhotoAppearance();
    assert(v.colors[0]==.5f && v.textures[0]==99 && v.writes==2);
    assert(v.mPhotoPendingTextures.empty() && v.mPhotoPendingColors.empty());
    v.resumePhotoAppearance();
    assert(v.writes==2);
    v.setTEColor(0,1.f);
    assert(v.colors[0]==1 && v.writes==3);
}
'''
with tempfile.TemporaryDirectory(prefix='photo-appearance-') as temp:
    cpp = Path(temp)/'test.cpp'
    exe = Path(temp)/'test.exe'
    cpp.write_text(code)
    subprocess.run(['g++','-std=c++17',str(cpp),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('PASS: appearance holds, latest values resume once, removed faces are skipped')
