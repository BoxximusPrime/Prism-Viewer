"""Exercise production diffusion and transmission blur on a hidden GL context (no login).
Run: .venv/Scripts/python.exe scripts/tests/test_sss_blur_gpu.py
"""
import ctypes as C
import statistics
from pathlib import Path
from test_exact_oit_gpu import context, U, I, F, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT, RGBA, FLOAT
from test_sss_shadow_gpu import PREAMBLE


def run(sdl, gl):
    for name, args in {'ActiveTexture':[U], 'Uniform2f':[I,F,F], 'Uniform4f':[I,F,F,F,F],
                       'UniformMatrix4fv':[I,I,C.c_ubyte,C.POINTER(F)]}.items():
        setattr(gl,name,C.WINFUNCTYPE(None,*args)(sdl.SDL_GL_GetProcAddress(('gl'+name).encode())))
    def obj(fn):
        value=U(); fn(1,C.byref(value)); return value.value
    def compile_shader(kind, source):
        shader=gl.CreateShader(kind)
        text=C.c_char_p(('#version 430 core\n'+PREAMBLE+source).encode())
        gl.ShaderSource(shader,1,C.byref(text),None); gl.CompileShader(shader)
        ok=I(); log=C.create_string_buffer(8192)
        gl.GetShaderiv(shader,0x8B81,C.byref(ok)); gl.GetShaderInfoLog(shader,len(log),None,log)
        assert ok.value,log.value.decode()
        return shader
    vertex='''out vec2 vary_fragcoord;
    void main() { vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
    gl_Position=vec4(p[gl_VertexID],0,1); vary_fragcoord=p[gl_VertexID]*0.5+0.5; }'''
    stubs='''uniform sampler2D test_surface;
    uniform int test_edges;
    vec3 srgb_to_linear(vec3 c) { return c; }
    GBufferInfo getGBuffer(vec2 tc) {
        GBufferInfo g;
        g.albedo=vec4(texture(test_surface,tc).rgb,1);
        g.gbufferFlag=0.79; g.sss=test_edges==1 && tc.x>=0.5 ? 0.0:1.0;
        float ripple=test_edges==4 ? 0.0:mod(floor(tc.x*64.0),2.0)*0.3;
        g.normal=normalize(vec3(ripple,0,1));
        if (test_edges==3) {
            float y=(tc.y-0.5)/0.125;
            g.sss=abs(y)<1.0 ? 1.0:0.0;
            g.normal=vec3(0,clamp(y,-1.0,1.0),sqrt(max(0.0,1.0-y*y)));
        }
        return g;
    }
    vec4 getPosition(vec2 tc) {
        float z=test_edges==2 && tc.x>=0.5 ? -2.0:-1.0;
        if (test_edges==3) {
            float y=(tc.y-0.5)/0.125;
            z+=0.0125*sqrt(max(0.0,1.0-y*y));
        }
        return vec4((tc-0.5)*0.1,z,1);
    }'''
    source=Path('indra/newview/app_settings/shaders/class1/deferred/sssDiffusionF.glsl').read_text()
    prog=gl.CreateProgram()
    for kind,code in ((0x8B31,vertex),(0x8B30,source),(0x8B30,stubs)):
        shader=compile_shader(kind,code); gl.AttachShader(prog,shader); gl.DeleteShader(shader)
    gl.LinkProgram(prog); ok=I(); log=C.create_string_buffer(8192)
    gl.GetProgramiv(prog,0x8B82,C.byref(ok)); gl.GetProgramInfoLog(prog,len(log),None,log)
    assert ok.value,log.value.decode()
    gl.UseProgram(prog)
    def uniform(name,*values,integer=False):
        location=gl.GetUniformLocation(prog,name.encode())
        getattr(gl,'Uniform1i' if integer else f'Uniform{len(values)}f')(location,*values)
    uniform('screen_res',64,64); uniform('sss_params',0.9,2,0.75,44)
    uniform('sss_smoothing_pass',1,integer=True)
    for name,unit in (('diffuseMap',0),('altDiffuseMap',1),('test_surface',2)):
        uniform(name,unit,integer=True)
    matrix=(F*16)(1,0,0,0,0,0.1,0,0,0,0,1,0,0,0,0,1)
    gl.UniformMatrix4fv(gl.GetUniformLocation(prog,b'inv_proj'),1,0,matrix)
    gl.BindVertexArray(obj(gl.GenVertexArrays)); gl.Viewport(0,0,64,64)
    fbo=obj(gl.GenFramebuffers); gl.BindFramebuffer(FRAMEBUFFER,fbo)
    def texture(values=None):
        tex=obj(gl.GenTextures); gl.BindTexture(TEXTURE,tex)
        for param in (0x2801,0x2800): gl.TexParameteri(TEXTURE,param,0x2600)
        for param in (0x2802,0x2803): gl.TexParameteri(TEXTURE,param,0x812F)
        gl.TexImage2D(TEXTURE,0,0x8814,64,64,0,RGBA,FLOAT,(F*len(values))(*values) if values else None)
        return tex
    scratch=texture(); result=texture()
    def filter_image(light,albedo,edge=0,radius=0.02,channel=0):
        uniform('sss_depth',radius); uniform('test_edges',edge,integer=True)
        def rgba(values): return [channel for value in values for channel in (value,value,value,0)]
        gl.ActiveTexture(0x84C2); surface=texture(rgba(albedo))
        gl.ActiveTexture(0x84C1); original=texture(rgba(light))
        gl.ActiveTexture(0x84C0); gl.BindTexture(TEXTURE,original)
        gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT,TEXTURE,scratch,0)
        assert gl.CheckFramebufferStatus(FRAMEBUFFER)==0x8CD5
        uniform('sss_pass',0,integer=True); gl.DrawArrays(0x0004,0,3)
        gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT,TEXTURE,result,0)
        gl.BindTexture(TEXTURE,scratch)
        uniform('sss_pass',1,integer=True); gl.DrawArrays(0x0004,0,3)
        pixels=(F*(64*64*4))(); gl.ReadPixels(0,0,64,64,RGBA,FLOAT,pixels)
        return [light[i]+pixels[i*4+channel] for i in range(64*64)]
    flat=[0.4]*4096; white=[1.0]*4096
    assert max(abs(v-0.4) for v in filter_image(flat,white))<1e-5
    noise=[0.1 if (x//2+y//2)%2 else 0.8 for y in range(64) for x in range(64)]
    smooth=filter_image(noise,white)
    inner=[y*64+x for y in range(8,56) for x in range(8,56)]
    before=statistics.pvariance(noise[i] for i in inner)
    after=statistics.pvariance(smooth[i] for i in inner)
    assert after<before*0.1,(before,after)
    assert max(abs(a-b) for a,b in zip(filter_image(noise,white,radius=0),noise))<1e-6
    # The blur must preserve texture detail, even with varying surface normals.
    albedo=[0.2 if (x//2+y//2)%2 else 0.9 for y in range(64) for x in range(64)]
    textured=[a*0.5 for a in albedo]
    assert max(abs(a-b) for a,b in zip(filter_image(textured,albedo),textured))<1e-5
    split=[1.0 if x<32 else 0.0 for y in range(64) for x in range(64)]
    for edge in (1,2):
        assert max(abs(a-b) for a,b in zip(filter_image(split,white,edge=edge),split))<1e-5,edge
    # A narrow cylindrical finger with a bright stripe must produce a continuous
    # broad filter, not the repeated isolated stripes from 13 widely spaced taps.
    stripe=[1.0 if x==32 and 24<=y<40 else 0.0 for y in range(64) for x in range(64)]
    finger=filter_image(stripe,white,edge=3,radius=0.1)
    row=finger[32*64:33*64]
    assert min(row[16:49])>1e-5, 'Wide filter leaves gaps on the curved finger'
    assert max(abs(row[x-1]-2*row[x]+row[x+1]) for x in range(17,48))<0.001, 'Finger filter has visible steps'
    assert max(abs(finger[y*64+x]) for y in list(range(24))+list(range(40,64)) for x in range(64))<1e-6
    # Ordinary diffusion must carry illumination past a beam edge, with red
    # spreading farther than green/blue, while preserving the skin boundary.
    uniform('sss_smoothing_pass',0,integer=True)
    colors=[filter_image(split,white,channel=c) for c in range(3)]
    pixel=32*64+34
    assert colors[0][pixel]>colors[1][pixel]>colors[2][pixel]>0.0, [c[pixel] for c in colors]
    assert all(abs(c[32*64+48])<1e-6 for c in colors), 'Diffusion exceeded its radius'
    assert max(abs(a-b) for a,b in zip(filter_image(split,white,edge=1),split))<1e-5
    assert max(abs(a-b) for a,b in zip(filter_image(textured,albedo),textured))<1e-5
    # A close-up can project 6 mm to 24 pixels. The meter control must keep
    # widening the actual beam-edge profile above that value, up to 100 mm.
    matrix[5]=0.008
    gl.UniformMatrix4fv(gl.GetUniformLocation(prog,b'inv_proj'),1,0,matrix)
    uniform('sss_params',1,2,0.75,44)
    radii=(0.006,0.014,0.028,0.06,0.1)
    for smoothing in (0,1):
        uniform('sss_smoothing_pass',smoothing,integer=True)
        spread=[filter_image(split,white,radius=r)[32*64+48] for r in radii]
        print(('Transmission' if smoothing else 'Diffuse')+' close-up beam edge:',list(zip(radii,spread)))
        assert all(b>a+0.001 for a,b in zip(spread,spread[1:])), 'Scattering radius silently plateaued'
        assert spread[-1]>spread[0]+0.2, 'Maximum radius barely widened the beam edge'
        assert max(abs(v-0.4) for v in filter_image(flat,white,radius=0.1))<1e-5
        for edge in (1,2):
            assert max(abs(a-b) for a,b in zip(filter_image(split,white,edge=edge,radius=0.1),split))<0.001
        narrow=[1.0 if x==32 else 0.0 for y in range(64) for x in range(64)]
        row=filter_image(narrow,white,edge=4,radius=0.1)[32*64:33*64]
        assert min(row)>0.001, 'Wide-radius sampling left gaps around a one-pixel light'
        assert max(abs(row[x-1]-2*row[x]+row[x+1]) for x in range(1,63))<0.002
    assert gl.GetError()==0
    print('Passed 27 diffusion/transmission blur GPU checks: close-up radius progression through 100 mm, beam-edge spread and color response, bounded radius, mottling, constants, zero radius, texture detail, skin/depth boundaries, and continuous thin-feature filtering.')
    print(f'Interior mottling variance: {before:.6f} -> {after:.6f}')

if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try: run(sdl,gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx); sdl.SDL_DestroyWindow(window); sdl.SDL_Quit()
