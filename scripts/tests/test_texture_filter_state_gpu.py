"""Exercise production LLTexUnit methods on real GL textures after cached binds.

Run: .venv/Scripts/python.exe scripts/tests/test_texture_filter_state_gpu.py
Compiles the actual C++ methods into a small DLL using the configured MSVC.
Only the draw queue (empty here) and GL capability globals are fixtures. Checks
UI white-texture sampling, R8 water masks and mip generation, without a login.
"""
import ctypes as C
from pathlib import Path
import re
import subprocess
import tempfile

from test_eye_adaptation_gpu import EyeGPU
from test_taa_gpu import context, U, I, F, P, TEXTURE
from test_water_gpu import function

ROOT = Path(__file__).resolve().parents[2]


def native_fixture(directory, sdl):
    source = (ROOT / 'indra/llrender/llrender.cpp').read_text(encoding='utf-8')
    signatures = ['void LLTexUnit::activate(', 'void LLTexUnit::enable(',
                  'void LLTexUnit::disable(', 'bool LLTexUnit::bindManual(',
                  'void LLTexUnit::unbind(', 'void LLTexUnit::setTextureFilteringOption(',
                  'void LLTexUnit::setTextureFilteringOptionFast(']
    methods = '\n'.join(function(source, signature) for signature in signatures)
    # Negative control: reproduce the previous missing-activation bug using the
    # same native methods, so a passing test must also demonstrate the failure.
    legacy = function(source, signatures[-2]).replace(
        'LLTexUnit::setTextureFilteringOption(', 'LLTexUnit::legacyFilter(').replace('activate();', '')
    scaffold = r'''
extern "C" { int _fltused=0; } // MSVC floating-point marker; fixture has no CRT.
using U32 = unsigned int; using S32 = int; using F32 = float;
const U32 GL_TEXTURE0=0x84C0, GL_TEXTURE_MAG_FILTER=0x2800, GL_TEXTURE_MIN_FILTER=0x2801;
const U32 GL_NEAREST=0x2600, GL_LINEAR=0x2601, GL_LINEAR_MIPMAP_LINEAR=0x2703;
const U32 GL_LINEAR_MIPMAP_NEAREST=0x2701, GL_NEAREST_MIPMAP_NEAREST=0x2700;
const U32 GL_TEXTURE_MAX_ANISOTROPY=0x84FE;
static const U32 sGLTextureType[]={0x0DE1,0x84F5,0x8513,0x9009,0x9100,0x806F};
void (__stdcall *glActiveTexture)(U32);
void (__stdcall *glBindTexture)(U32,U32);
void (__stdcall *glTexParameteri)(U32,U32,S32);
void (__stdcall *glTexParameterf)(U32,U32,F32);
void stop_glerror() {}
F32 llclamp(F32 x,F32 a,F32 b) {return x<a?a:x>b?b:x;}
struct LLRender {
    U32 mCurrTextureUnitIndex; bool mDirty;
    static F32 sAnisotropicFilteringLevel;
    void flush() {} // No queued geometry in this state regression.
} gGL;
F32 LLRender::sAnisotropicFilteringLevel=4.f;
struct {bool mHasAnisotropic; F32 mMaxAnisotropy;} gGLManager;
struct LLTexUnit {
    enum eTextureType {TT_TEXTURE,TT_RECT_TEXTURE,TT_CUBE_MAP,TT_CUBE_MAP_ARRAY,
                      TT_MULTISAMPLE_TEXTURE,TT_TEXTURE_3D,TT_NONE};
    enum eTextureFilterOptions {TFO_POINT,TFO_BILINEAR,TFO_TRILINEAR,TFO_ANISOTROPIC};
    S32 mIndex; U32 mCurrTexture; eTextureType mCurrTexType; bool mHasMipMaps;
    static U32 sWhiteTexture;
    void activate(); void enable(eTextureType); void disable(); void unbind(eTextureType);
    bool bindManual(eTextureType,U32,bool);
    void setTextureFilteringOption(eTextureFilterOptions);
    void setTextureFilteringOptionFast(eTextureFilterOptions,eTextureType);
    void legacyFilter(eTextureFilterOptions);
};
U32 LLTexUnit::sWhiteTexture;
static LLTexUnit units[4];
'''
    exports = r'''
#define EXPORT extern "C" __declspec(dllexport)
EXPORT void setup(void* active,void* bind,void* parami,void* paramf) {
    glActiveTexture=(decltype(glActiveTexture))active;
    glBindTexture=(decltype(glBindTexture))bind;
    glTexParameteri=(decltype(glTexParameteri))parami;
    glTexParameterf=(decltype(glTexParameterf))paramf;
    gGLManager.mHasAnisotropic=true; gGLManager.mMaxAnisotropy=4.f;
}
EXPORT void reset(U32 white) {
    gGL.mCurrTextureUnitIndex=999; gGL.mDirty=false;
    LLTexUnit::sWhiteTexture=white;
    for(int i=0;i<4;++i) {
        units[i].mIndex=i; units[i].mCurrTexture=0;
        units[i].mCurrTexType=LLTexUnit::TT_NONE; units[i].mHasMipMaps=false;
    }
}
EXPORT void bind(U32 unit,U32 texture,bool mips) {
    units[unit].bindManual(LLTexUnit::TT_TEXTURE,texture,mips);
}
EXPORT void unbind(U32 unit) {units[unit].unbind(LLTexUnit::TT_TEXTURE);}
EXPORT void filter(U32 unit,int option,bool legacy) {
    auto mode=(LLTexUnit::eTextureFilterOptions)option;
    if(legacy) units[unit].legacyFilter(mode); else units[unit].setTextureFilteringOption(mode);
}
'''
    cpp = directory / 'texture_state.cpp'
    cpp.write_text(scaffold + methods + legacy + exports, encoding='utf-8')
    cache = (ROOT / 'build-vc170-64/CMakeCache.txt').read_text(encoding='utf-8')
    vs = Path(re.search(r'^CMAKE_GENERATOR_INSTANCE:[^=]+=(.+)$', cache, re.M)[1].strip())
    compiler = sorted((vs / 'VC/Tools/MSVC').glob('*/bin/Hostx64/x64/cl.exe'))[-1]
    dll_path = directory / 'texture_state.dll'
    # Headerless fixture needs neither CRT nor SDK libraries. All GL entry
    # points come from the current SDL context; no separate context is created.
    result = subprocess.run([str(compiler), '/nologo', '/LD', '/GS-', '/Od',
                             str(cpp), '/link', '/NOENTRY', '/NODEFAULTLIB',
                             '/OUT:' + str(dll_path)], cwd=directory,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    dll = C.CDLL(str(dll_path))
    for name, args in {'setup': [P]*4, 'reset': [U], 'bind': [U,U,C.c_bool],
                       'unbind': [U], 'filter': [U,I,C.c_bool]}.items():
        getattr(dll, name).argtypes = args
        getattr(dll, name).restype = None
    dll.setup(*(sdl.SDL_GL_GetProcAddress(name) for name in
                (b'glActiveTexture', b'glBindTexture', b'glTexParameteri', b'glTexParameterf')))
    return dll


def run(sdl, gl, native):
    gpu = EyeGPU(sdl, gl)
    for name, args in {'GetTexParameteriv': [U,U,P], 'GetTexLevelParameteriv': [U,I,U,P]}.items():
        setattr(gl, name, C.WINFUNCTYPE(None,*args)(sdl.SDL_GL_GetProcAddress(('gl'+name).encode())))
    ui = gpu.program((ROOT / 'indra/newview/app_settings/shaders/class1/interface/uiF.glsl')
                     .read_text(encoding='utf-8'), '''
        out vec2 vary_texcoord0; out vec4 vertex_color;
        void main() {
            vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
            gl_Position=vec4(p[gl_VertexID],0,1);
            vary_texcoord0=vec2(.5); vertex_color=vec4(.2,.7,.4,1);
        }''')
    mask_shader = gpu.program('uniform sampler2D exclusionTex; out vec4 frag_color; '
                              'void main(){frag_color=vec4(texture(exclusionTex,vec2(.5)).r);}')
    output = gpu.tex(1,1)
    # The shipped non-mipmapped UI white.tga is 32x32. Water exclusion is R8.
    cases = 0
    for kind, internal, program, name in [('UI white',0x8814,ui,'diffuseMap'),
                                          ('water mask',0x8229,mask_shader,'exclusionTex')]:
        for option in range(4):
            for legacy in (True,False):
                waves = gpu.tex(32,32,[.1,.2,.3,1]*1024)
                gpu.reduce(waves)
                victim = gpu.tex(32,32,[1,1,1,1]*1024,internal)
                if kind == 'UI white':
                    # LLImageGL sets the maximum discard level from dimensions
                    # even for MIPMAP_NO; only level zero actually exists.
                    gl.TexParameteri(TEXTURE,0x813D,5)
                native.reset(victim)
                native.bind(2,waves,True)
                native.bind(0,victim,False)
                if kind == 'UI white':
                    native.unbind(0)  # Real solid-colour UI fallback binding.
                native.bind(2,waves,True)  # Cache hit leaves unit zero active.
                native.filter(2,option,legacy)
                active = I()
                gl.GetIntegerv(0x84E0,C.byref(active))
                assert active.value == 0x84C0 + (0 if legacy else 2)
                gl.ActiveTexture(0x84C0)
                minimum = I()
                gl.GetTexParameteriv(TEXTURE,0x2801,C.byref(minimum))
                assert minimum.value == ([0x2700,0x2701,0x2703,0x2703][option] if legacy else 0x2601)
                gpu.uniform(program,name,0,integer=True)
                gpu.render(program,output)
                actual = gpu.pixels(output)[:3]
                expected = [0,0,0] if legacy else ([.2,.7,.4] if kind == 'UI white' else [1,1,1])
                assert max(abs(a-b) for a,b in zip(actual,expected)) < .001, (kind,option,legacy,actual)
                assert gl.GetError() == 0
                cases += 1
    # RenderTarget::flush uses bindTexture/filter followed by glGenerateMipmap.
    # A cached target binding must leave mip generation on that target, too.
    for legacy in (True,False):
        target = gpu.tex(32,32,[.1,.2,.3,1]*1024)
        unrelated = gpu.tex(32,32,[1,1,1,1]*1024)
        native.reset(unrelated)
        native.bind(0,target,True)
        native.bind(3,unrelated,False)
        native.bind(0,target,True)
        native.filter(0,2,legacy)
        gl.GenerateMipmap(TEXTURE)
        for unit, expected in [(0,0 if legacy else 16),(3,16 if legacy else 0)]:
            gl.ActiveTexture(0x84C0+unit)
            width = I()
            gl.GetTexLevelParameteriv(TEXTURE,1,0x1000,C.byref(width))
            assert width.value == expected
        assert gl.GetError() == 0
        cases += 1
    print(f'PASS: {cases} native texture-state GPU cases; old code reproduces black UI/masks '
          f'and wrong mip target; current code preserves both on {gl.GetString(0x1F01).decode()}')


if __name__ == '__main__':
    sdl, window, ctx, gl = context()
    try:
        with tempfile.TemporaryDirectory(prefix='prism-texture-state-') as directory:
            native = native_fixture(Path(directory), sdl)
            try:
                run(sdl,gl,native)
            finally:
                free = C.WinDLL('kernel32').FreeLibrary
                free.argtypes = [P]
                free(native._handle)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
