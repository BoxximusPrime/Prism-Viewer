"""Feed the production cleanup passes into both production spotlight variants.

Run: .venv/Scripts/python.exe scripts/tests/test_projector_cleanup_gpu.py
Uses RGBA16F intermediates, independent B/A shadows, and legacy/PBR receivers.
Lighting/material inputs are controlled; this is not a live viewer capture.
"""
import ctypes as C
import math
from pathlib import Path

from test_exact_oit_gpu import context, U, I, F, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT, RGBA, FLOAT
from test_sss_shadow_gpu import PREAMBLE, STUBS

ROOT = Path(__file__).resolve().parents[2]
SHADERS = ROOT / 'indra/newview/app_settings/shaders'
SIZE = 128


def run(sdl, gl):
    for name, args in {
        'ActiveTexture': [U], 'Uniform2f': [I,F,F], 'Uniform3f': [I,F,F,F],
        'Uniform4f': [I,F,F,F,F], 'Disable': [U],
    }.items():
        setattr(gl, name, C.WINFUNCTYPE(None,*args)(sdl.SDL_GL_GetProcAddress(('gl'+name).encode())))

    def obj(gen):
        value = U()
        gen(1,C.byref(value))
        return value.value

    def uniform(prog, name, *values, integer=False):
        location = gl.GetUniformLocation(prog,name.encode())
        getattr(gl,'Uniform1i' if integer else f'Uniform{len(values)}f')(location,*values)

    def program(vertex, fragments, flags=''):
        prog = gl.CreateProgram()
        for kind, source in [(0x8B31,vertex)] + [(0x8B30,s) for s in fragments]:
            shader = gl.CreateShader(kind)
            text = C.c_char_p(('#version 430 core\n'+flags+source).encode())
            gl.ShaderSource(shader,1,C.byref(text),None)
            gl.CompileShader(shader)
            ok, log = I(), C.create_string_buffer(16384)
            gl.GetShaderiv(shader,0x8B81,C.byref(ok))
            gl.GetShaderInfoLog(shader,len(log),None,log)
            assert ok.value, log.value.decode()
            gl.AttachShader(prog,shader)
            gl.DeleteShader(shader)
        gl.LinkProgram(prog)
        gl.GetProgramiv(prog,0x8B82,C.byref(ok))
        gl.GetProgramInfoLog(prog,len(log),None,log)
        assert ok.value, log.value.decode()
        return prog

    triangle = 'vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3)); gl_Position=vec4(p[gl_VertexID],0,1);'
    blur = program('out vec2 vary_fragcoord; void main(){'+triangle+'vary_fragcoord=p[gl_VertexID]*.5+.5;}',
        [(SHADERS/'class1/deferred/blurLightF.glsl').read_text(),
         'vec4 getPosition(vec2 uv){return vec4(uv*2-1,-4,1);} vec4 getNorm(vec2 uv){return vec4(0,0,1,0);}'])
    spots = []
    for multi in (False,True):
        vertex = 'out vec4 vary_fragcoord; out vec3 trans_center; void main(){'+triangle+'vary_fragcoord=gl_Position; trans_center=vec3(0);}'
        stubs = STUBS.replace('return vec2(0.5);', f'return gl_FragCoord.xy/{float(SIZE)};')
        fragments = [(SHADERS/'class3/deferred/spotLightF.glsl').read_text(),stubs] + [
            (SHADERS/f'class1/deferred/{name}.glsl').read_text() for name in ('gbufferUtil','sssDepthUtil','shadowUtil')]
        spots.append(program(vertex,[PREAMBLE+s for s in fragments], '#define MULTI_SPOTLIGHT\n' if multi else ''))

    gl.BindVertexArray(obj(gl.GenVertexArrays))
    gl.Disable(0x0BE2)
    gl.Disable(0x0B71)
    gl.Viewport(0,0,SIZE,SIZE)
    fbo = obj(gl.GenFramebuffers)
    gl.BindFramebuffer(FRAMEBUFFER,fbo)

    def texture(values=None, size=SIZE):
        tex = obj(gl.GenTextures)
        gl.BindTexture(TEXTURE,tex)
        pixels = None if values is None else (F*len(values))(*values)
        gl.TexImage2D(TEXTURE,0,0x881A,size,size,0,RGBA,FLOAT,pixels)
        for param,value in ((0x2801,0x2600),(0x2800,0x2600),(0x2802,0x812F),(0x2803,0x812F)):
            gl.TexParameteri(TEXTURE,param,value)
        return tex

    def target(tex):
        gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT,TEXTURE,tex,0)
        assert gl.CheckFramebufferStatus(FRAMEBUFFER) == 0x8CD5

    gl.ActiveTexture(0x84C0)
    raw = texture([v for y in range(SIZE) for x in range(SIZE)
                   for v in (.23,.61,float(x>=SIZE//2),float(y>=SIZE//2))])
    scratch, cleaned, result = texture(),texture(),texture()
    gl.ActiveTexture(0x84C1)
    texture([1,1,1,1],1)
    gl.ActiveTexture(0x84C2)
    texture([0,.5,0,0],1)

    def clean(sigma):
        gl.UseProgram(blur)
        uniform(blur,'lightMap',0,integer=True)
        uniform(blur,'pcss_enabled',1,integer=True)
        uniform(blur,'pcss_cleanup_only',1,integer=True)
        uniform(blur,'pcss_cleanup',sigma)
        for source,dest,direction in ((raw,scratch,(1,0)),(scratch,cleaned,(0,1))):
            gl.ActiveTexture(0x84C0)
            gl.BindTexture(TEXTURE,source)
            target(dest)
            uniform(blur,'delta',*direction)
            gl.DrawArrays(4,0,3)

    def ramp(x):
        t = max(0.0,min(1.0,(x-24)/80))
        return t*t*(3-2*t)

    checks = 0
    for profile in ('hard','broad'):
        gl.ActiveTexture(0x84C0)
        gl.BindTexture(TEXTURE,raw)
        values = [v for y in range(SIZE) for x in range(SIZE) for v in
                  (.23,.61,float(x>=SIZE//2) if profile=='hard' else ramp(x),
                   float(y>=SIZE//2) if profile=='hard' else ramp(y))]
        gl.TexImage2D(TEXTURE,0,0x881A,SIZE,SIZE,0,RGBA,FLOAT,(F*len(values))(*values))
        clean(3)
        differences = []
        for multi,prog in enumerate(spots):
            gl.UseProgram(prog)
            uniform(prog,'diffuseRect',1,integer=True)
            uniform(prog,'specularRect',2,integer=True)
            uniform(prog,'lightMap',0,integer=True)
            uniform(prog,'test_pos',0,0,-4)
            uniform(prog,'test_normal',0,0,1)
            uniform(prog,'proj_origin',0,0,0)
            for flag in (0,.67):
                uniform(prog,'test_flag',flag)
                for slot in (0,1):
                    uniform(prog,'proj_shadow_idx',slot,integer=True)
                    outputs = []
                    for source in (raw,cleaned):
                        gl.ActiveTexture(0x84C0)
                        gl.BindTexture(TEXTURE,source)
                        target(result)
                        gl.DrawArrays(4,0,3)
                        pixels = (F*(SIZE*SIZE*4))()
                        gl.ReadPixels(0,0,SIZE,SIZE,RGBA,FLOAT,pixels)
                        assert gl.GetError() == 0
                        assert all(math.isfinite(v) for v in pixels)
                        outputs.append(list(pixels)[::4])
                    hard,soft = outputs
                    delta = max(abs(a-b) for a,b in zip(hard,soft))
                    differences.append(delta)
                    assert (delta > .3 if profile == 'hard' else .0001 < delta < .02), ('projector cleanup response',profile,multi,flag,slot,delta)
                    assert max(hard) > .9
                    assert soft[16*SIZE+16] == hard[16*SIZE+16] == 0
                    assert abs(soft[112*SIZE+112]-hard[112*SIZE+112]) < .002
                    checks += 1
        print(f'{profile} projector cleanup maximum lighting changes: {min(differences):.4f} to {max(differences):.4f}')
    print(f'PASS: {checks} projector cleanup integration cases on {gl.GetString(0x1F01).decode()}')


if __name__ == '__main__':
    sdl,window,ctx,gl = context()
    try:
        run(sdl,gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
