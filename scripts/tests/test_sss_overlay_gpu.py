"""Production skin overlay capture/composite on a hidden GL context; no login.
Run: .venv/Scripts/python.exe scripts/tests/test_sss_overlay_gpu.py
"""
import ctypes as C
from pathlib import Path
from test_exact_oit_gpu import context, U, I, F, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT, RGBA, FLOAT
from test_sss_shadow_gpu import PREAMBLE

ROOT = Path(__file__).resolve().parents[2]
SH = ROOT / 'indra/newview/app_settings/shaders'

def function(path, signature):
    source = path.read_text()
    start = source.index(signature + '\n{')
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]

def run(sdl, gl):
    for name, args in {'ActiveTexture':[U], 'Uniform3f':[I,F,F,F], 'Uniform4f':[I,F,F,F,F],
                       'DrawBuffers':[I,C.POINTER(U)], 'ReadBuffer':[U],
                       'Enable':[U], 'Disable':[U], 'BlendFuncSeparate':[U,U,U,U],
                       'ClearColor':[F,F,F,F], 'Clear':[U]}.items():
        setattr(gl,name,C.WINFUNCTYPE(None,*args)(sdl.SDL_GL_GetProcAddress(('gl'+name).encode())))
    def obj(fn):
        x=U(); fn(1,C.byref(x)); return x.value
    def program(vertex, fragments, defines=''):
        prog=gl.CreateProgram()
        for kind, source in [(0x8B31,vertex)] + [(0x8B30,f) for f in fragments]:
            shader=gl.CreateShader(kind)
            text=C.c_char_p(('#version 430 core\n'+PREAMBLE+defines+'\nvec4 diffuseLookup(vec2 tc);\n'+source).encode())
            gl.ShaderSource(shader,1,C.byref(text),None); gl.CompileShader(shader)
            ok=I(); log=C.create_string_buffer(16000)
            gl.GetShaderiv(shader,0x8B81,C.byref(ok)); gl.GetShaderInfoLog(shader,len(log),None,log)
            assert ok.value,log.value.decode()
            gl.AttachShader(prog,shader); gl.DeleteShader(shader)
        gl.LinkProgram(prog); ok=I(); log=C.create_string_buffer(16000)
        gl.GetProgramiv(prog,0x8B82,C.byref(ok)); gl.GetProgramInfoLog(prog,len(log),None,log)
        assert ok.value,log.value.decode()
        return prog
    def uniform(prog,name,*values,integer=False):
        gl.UseProgram(prog)
        getattr(gl,'Uniform1i' if integer else 'Uniform'+str(len(values))+'f')(
            gl.GetUniformLocation(prog,name.encode()),*values)
    def tex(values,fmt=0x8814,channels=4):
        result=obj(gl.GenTextures); gl.BindTexture(TEXTURE,result)
        for p in (0x2800,0x2801): gl.TexParameteri(TEXTURE,p,0x2600)
        for p in (0x2802,0x2803): gl.TexParameteri(TEXTURE,p,0x812F)
        gl.TexImage2D(TEXTURE,0,fmt,8,1,0,RGBA if channels==4 else 0x1903,FLOAT,(F*len(values))(*values))
        return result
    def bind(prog,name,texture,unit):
        gl.ActiveTexture(0x84C0+unit); gl.BindTexture(TEXTURE,texture)
        uniform(prog,name,unit,integer=True)
    def target(*textures):
        for i in range(2):
            gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT+i,TEXTURE,textures[i] if i<len(textures) else 0,0)
        gl.DrawBuffers(len(textures),(U*len(textures))(*(COLOR_ATTACHMENT+i for i in range(len(textures)))))
        assert gl.CheckFramebufferStatus(FRAMEBUFFER)==0x8CD5
    def read(attachment=0):
        gl.ReadBuffer(COLOR_ATTACHMENT+attachment)
        pixels=(F*32)(); gl.ReadPixels(0,0,8,1,RGBA,FLOAT,pixels)
        return [tuple(pixels[4*i:4*i+4]) for i in range(8)]
    def draw(prog):
        gl.UseProgram(prog); gl.DrawArrays(4,0,3)
        assert gl.GetError()==0
    def close(a,b,tolerance=2e-5):
        assert max(abs(x-y) for x,y in zip(a,b))<tolerance,(a,b)
    def linear(x): return x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4
    def srgb(x): return 12.92*x if x<=.0031308 else 1.055*x**(1/2.4)-.055
    srgb_source=(SH/'class1/environment/srgbF.glsl').read_text()
    util=(SH/'class1/deferred/sssOverlayUtil.glsl').read_text()
    capture=(SH/'class1/deferred/sssOverlayF.glsl').read_text()
    composite=(SH/'class1/deferred/sssOverlayCompositeF.glsl').read_text()
    # Use production packed-normal sampling. Position is synthetic so cases can
    # include distant and occluded receivers without a scene or a viewer login.
    readers='''uniform sampler2D normalMap;
    uniform float test_skin_z;
    vec4 getPosition(vec2 tc) { return vec4(0,0,test_skin_z,1); }
    '''+function(SH/'class1/deferred/deferredUtil.glsl','vec4 getNormRaw(vec2 screenpos)')
    vertex='''out vec2 vary_fragcoord, vary_texcoord0, base_color_texcoord;
    out vec4 vertex_color;
    out vec3 vary_position;
    uniform vec3 test_pos;
    uniform vec4 test_tint;
    void main() {
        vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
        gl_Position=vec4(p[gl_VertexID],0,1);
        vary_fragcoord=p[gl_VertexID]*.5+.5;
        vary_texcoord0=base_color_texcoord=vary_fragcoord;
        vertex_color=test_tint; vary_position=test_pos;
    }'''
    lookup='uniform sampler2D diffuseMap; vec4 diffuseLookup(vec2 tc) { return texture(diffuseMap,tc); }\n'
    comp=program(vertex,[composite,readers,srgb_source])
    caps=[program(vertex,[capture,util,srgb_source]+([lookup] if kind==0 else []),
        '#define USE_INDEXED_TEX 1\n' if kind==0 else '#define SSS_OVERLAY_PBR 1\n' if kind==2 else '') for kind in range(3)]
    fallback=program(vertex,[util,'''in vec3 vary_position; out vec4 frag_color;
    bool isSSSOverlay(vec3 positionEye);
    void main() { if (isSSSOverlay(vary_position)) discard; frag_color=vec4(1); }'''])
    # Link all six actual static/skinned vertex variants, including PBR UV transforms.
    for kind in range(3):
        for rigged in (False,True):
            actual=(SH/('class1/deferred/pbralphaV.glsl' if kind==2 else 'class1/deferred/alphaV.glsl')).read_text()
            actual += '\nvoid passTextureIndex() {}\nmat4 getObjectSkinnedTransform() { return mat4(1); }\n'
            actual += (SH/'class1/deferred/textureUtilV.glsl').read_text()
            defs='#define USE_VERTEX_COLOR 1\n'+('#define HAS_SKIN 1\n' if rigged else '')
            defs+='#define USE_INDEXED_TEX 1\n' if kind==0 else '#define SSS_OVERLAY_PBR 1\n' if kind==2 else ''
            program(actual,[capture,util,srgb_source]+([lookup] if kind==0 else []),defs)

    gl.BindVertexArray(obj(gl.GenVertexArrays)); gl.BindFramebuffer(FRAMEBUFFER,obj(gl.GenFramebuffers))
    gl.Viewport(0,0,8,1)
    base_rgb=(.45,.28,.20); sleeve_rgb=(.65,.36,.26); tint=(.8,.9,1,.8)
    alphas=(0,.01,.125,.25,.5,.75,.9,1)
    original=tex([v for _ in range(8) for v in (*base_rgb,.37)])
    sleeve=tex([v for a in alphas for v in (*sleeve_rgb,a)])
    base=tex([0]*32); guide=tex([0]*8,0x822E,1); colors=tex([0]*32,0x881A); result=tex([0]*32)
    dummy=tex([0]*32)
    checks=0
    for flag in (.46,.79,.34,.67,0):
        normals=tex([v for _ in range(8) for v in (.5,.5,0,flag)])
        for z in (-.5,-44):
            target(base,guide)
            bind(comp,'diffuseRect',original,0); bind(comp,'normalMap',normals,1)
            bind(comp,'diffuseMap',dummy,2); bind(comp,'altDiffuseMap',dummy,3)
            uniform(comp,'sss_overlay_pass',0,integer=True); uniform(comp,'sss_overlay_distance',43)
            uniform(comp,'test_skin_z',z); draw(comp)
            close(read()[0],(*base_rgb,.37)); checks+=1
            expected_depth=z if flag in (.46,.79) and z>-43 else 0
            close((read(1)[0][0],),(expected_depth,)); checks+=1
            for kind,cap in enumerate(caps):
                for pos in ((0,0,-.49),(0,0,-.51),(0,0,-.45),(2,0,-.49)):
                    accepts=expected_depth<0 and pos[2]>=z and (pos[2]-z)*sum(c*c for c in pos)**.5/-pos[2]<=.03
                    target(colors); gl.ClearColor(0,0,0,0); gl.Clear(0x4000)
                    bind(cap,'diffuseMap',sleeve,0); bind(cap,'sssOverlayGuide',guide,1)
                    uniform(cap,'sss_overlay',1,integer=True); uniform(cap,'test_pos',*pos); uniform(cap,'test_tint',*tint)
                    gl.Enable(0x0BE2); gl.BlendFuncSeparate(0x0302,0x0303,1,0x0303); draw(cap); gl.Disable(0x0BE2)
                    captured=read()
                    rgb=tuple(linear(sleeve_rgb[i])*tint[i] if kind==2 else linear(sleeve_rgb[i]*tint[i]) for i in range(3))
                    for i,a in enumerate(alphas):
                        a=a*tint[3] if accepts and a*tint[3]>=.004 else 0
                        close(captured[i],(*(v*a for v in rgb),a),.001); checks+=1
                    target(result)
                    bind(comp,'diffuseRect',dummy,0); bind(comp,'normalMap',normals,1)
                    bind(comp,'diffuseMap',colors,2); bind(comp,'altDiffuseMap',base,3)
                    uniform(comp,'sss_overlay_pass',1,integer=True); draw(comp)
                    final=read()
                    for i,a in enumerate(alphas):
                        a=a*tint[3] if accepts and a*tint[3]>=.004 else 0
                        expected=tuple((base_rgb[c] if flag in (.79,.67) else linear(base_rgb[c]))*(1-a)+rgb[c]*a for c in range(3))
                        if flag not in (.79,.67): expected=tuple(srgb(v) for v in expected)
                        close(final[i],(*expected,.37),.001); checks+=1
                    # Complementary fallback: rejected receivers still render normally.
                    gl.ClearColor(0,0,0,0); gl.Clear(0x4000)
                    bind(fallback,'sssOverlayGuide',guide,0); uniform(fallback,'sss_overlay',1,integer=True)
                    uniform(fallback,'test_pos',*pos); draw(fallback)
                    close(read()[0],(0,0,0,0) if accepts else (1,1,1,1)); checks+=1
                    uniform(fallback,'sss_overlay',0,integer=True); draw(fallback)
                    close(read()[0],(1,1,1,1)); checks+=1
    print(f'Passed {checks} skin overlay GPU checks and all six production vertex variants on '+gl.GetString(0x1F01).decode())

if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try: run(sdl,gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx); sdl.SDL_DestroyWindow(window); sdl.SDL_Quit()
