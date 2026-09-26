"""Independently check production SSGI donor MRTs on a hidden OpenGL context.

Run: .venv/Scripts/python.exe scripts/tests/test_ssgi_donor_gpu.py
Lighting/material inputs are controlled; actual color conversions and lighting
entry points run on GPU. This checks source isolation, not in-world appearance.
"""
import ctypes as C
import math
from pathlib import Path

from test_exact_oit_gpu import context, U, I, F, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT, RGBA, FLOAT
from test_sss_shadow_gpu import PREAMBLE, STUBS
from test_ssgi_gpu import PREFACE

PREAMBLE = PREFACE.split("uniform sampler2D normalMap;")[0] + "\n".join(
    line for line in PREAMBLE.splitlines() if not line.startswith("#define"))

SHADERS = Path(__file__).resolve().parents[2] / 'indra/newview/app_settings/shaders'


def run(sdl, gl):
    for name, args in {
        'ActiveTexture': [U], 'Uniform3f': [I, F, F, F], 'Uniform4f': [I, F, F, F, F],
        'DrawBuffers': [I, C.POINTER(U)], 'ReadBuffer': [U], 'Clear': [U],
        'DeleteProgram': [U],
    }.items():
        setattr(gl, name, C.WINFUNCTYPE(None, *args)(sdl.SDL_GL_GetProcAddress(('gl' + name).encode())))

    def obj(fn):
        value = U(); fn(1, C.byref(value)); return value.value

    def uniform(prog, name, *values, integer=False):
        loc = gl.GetUniformLocation(prog, name.encode())
        getattr(gl, 'Uniform1i' if integer else f'Uniform{len(values)}f')(loc, *values)

    stubs = STUBS.replace('vec3 srgb_to_linear(vec3 c) { return c; }', '')
    stubs = stubs.replace('vec3 linear_to_srgb(vec3 c) { return c; }', '')
    stubs = 'uniform vec3 test_sun, test_ambient;\n' + stubs
    stubs = stubs.replace('sun=vec3(1); amb=vec3(0);', 'sun=test_sun; amb=test_ambient;')
    stubs = stubs.replace('d=b*(1.0-m); s=vec3(0);', 'd=b*(1.0-m); s=vec3(0.04);')
    stubs = stubs.replace('return max(dot(n,l),0.0)*d*shadow;',
                          'return irr*d*ao + rad*s + e + max(dot(n,l),0.0)*d*shadow*sun;')
    stubs += (SHADERS / 'class1/environment/srgbF.glsl').read_text().split('vec3 ColorFromRadiance')[0]

    def program(name, multi=False):
        screen = name in ('softenLightF', 'ssgiDebugF')
        vertex = ('out vec2 vary_fragcoord;' if screen else
                  'out vec4 vary_fragcoord; out vec3 trans_center;')
        vertex += 'void main(){vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));gl_Position=vec4(p[gl_VertexID],0,1);'
        vertex += ('vary_fragcoord=vec2(.5);}' if screen else
                   'vary_fragcoord=gl_Position; trans_center=vec3(0);}')
        flags = '#define HAS_EMISSIVE 1\n#define HAS_SSAO 1\n#define LIGHT_COUNT 1\n'
        if multi: flags += '#define MULTI_SPOTLIGHT 1\n'
        if name == 'ssgiDebugF':
            fragments = [(SHADERS / 'class1/deferred/ssgiDebugF.glsl').read_text()]
        else:
            fragments = [(SHADERS / f'class3/deferred/{name}.glsl').read_text(), stubs]
            fragments += [(SHADERS / f'class1/deferred/{n}.glsl').read_text()
                          for n in ('gbufferUtil', 'sssDepthUtil', 'shadowUtil')]
        prog = gl.CreateProgram()
        for kind, source in [(0x8B31, vertex)] + [(0x8B30, f) for f in fragments]:
            shader = gl.CreateShader(kind)
            text = C.c_char_p(('#version 430 core\n' + flags + PREAMBLE + source).encode())
            gl.ShaderSource(shader, 1, C.byref(text), None); gl.CompileShader(shader)
            ok, log = I(), C.create_string_buffer(16384)
            gl.GetShaderiv(shader, 0x8B81, C.byref(ok)); gl.GetShaderInfoLog(shader, len(log), None, log)
            assert ok.value, (name, log.value.decode())
            gl.AttachShader(prog, shader); gl.DeleteShader(shader)
        gl.LinkProgram(prog)
        gl.GetProgramiv(prog, 0x8B82, C.byref(ok)); gl.GetProgramInfoLog(prog, len(log), None, log)
        assert ok.value, (name, log.value.decode())
        gl.UseProgram(prog)
        for sampler, unit in [('diffuseRect', 0), ('specularRect', 2), ('lightMap', 3), ('emissiveRect', 14)]:
            uniform(prog, sampler, unit, integer=True)
        for i in range(6): uniform(prog, f'shadowMap{i}', 4 + i, integer=True)
        for i in range(3): uniform(prog, f'sssDepthMap{i}', 10 + i, integer=True)
        uniform(prog, 'test_pos', 0, 0, -2)
        uniform(prog, 'test_normal', 0, 0, 1)
        uniform(prog, 'sun_dir', 0, 0, 1); uniform(prog, 'moon_dir', 0, 0, 1)
        uniform(prog, 'sun_up_factor', 1, integer=True)
        uniform(prog, 'far_z', -100)
        uniform(prog, 'size', 4); uniform(prog, 'light_size', 4)
        uniform(prog, 'color', 1, .5, .25)
        uniform(prog, 'light[0]', 0, 0, 0, 4)
        uniform(prog, 'light_col[0]', 1, .5, .25, 0)
        uniform(prog, 'sss_params', 0, 1, .5, 40)
        uniform(prog, 'sss_lighting', 0, 0, 8.5)
        return prog

    def texture(unit, values):
        gl.ActiveTexture(0x84C0 + unit)
        tex = obj(gl.GenTextures); gl.BindTexture(TEXTURE, tex)
        for param in (0x2800, 0x2801): gl.TexParameteri(TEXTURE, param, 0x2600)
        gl.TexImage2D(TEXTURE, 0, 0x8814, 1, 1, 0, RGBA, FLOAT, (F * 4)(*values))
        return tex

    gl.BindVertexArray(obj(gl.GenVertexArrays))
    gl.BindFramebuffer(FRAMEBUFFER, obj(gl.GenFramebuffers)); gl.Viewport(0, 0, 1, 1)
    for i in range(5):
        tex = texture(0, [0, 0, 0, 0])
        gl.FramebufferTexture2D(FRAMEBUFFER, COLOR_ATTACHMENT + i, TEXTURE, tex, 0)
    gl.DrawBuffers(5, (U * 5)(*(COLOR_ATTACHMENT + i for i in range(5))))
    assert gl.CheckFramebufferStatus(FRAMEBUFFER) == 0x8CD5
    texture(0, [1, .5, .25, 0]); texture(2, [1, .5, 0, 0]); texture(3, [1, 1, 1, 1])
    emission = texture(14, [0, 0, 0, 0])

    def emit(values):
        gl.ActiveTexture(0x84C0 + 14); gl.BindTexture(TEXTURE, emission)
        gl.TexImage2D(TEXTURE, 0, 0x8814, 1, 1, 0, RGBA, FLOAT, (F * 4)(*values))

    def draw(prog, capture):
        uniform(prog, 'ssgi_capture', capture, integer=True)
        gl.Clear(0x4000); gl.DrawArrays(4, 0, 3)
        result = []
        for attachment in range(5):
            gl.ReadBuffer(COLOR_ATTACHMENT + attachment)
            pixel = (F * 4)(); gl.ReadPixels(0, 0, 1, 1, RGBA, FLOAT, pixel)
            assert all(math.isfinite(v) for v in pixel), tuple(pixel)
            result.append(tuple(pixel))
        assert gl.GetError() == 0
        return result

    checks = 0
    for name, multi in [('softenLightF', False), ('pointLightF', False), ('multiPointLightF', False),
                        ('spotLightF', False), ('spotLightF', True)]:
        prog = program(name, multi)
        reference = {}
        for classic in (0, 1):
            uniform(prog, 'classic_mode', classic, integer=True)
            for flag in (.34, .67, .46, .79, .38, .71, .50, .83):
                uniform(prog, 'test_flag', flag)
                uniform(prog, 'test_sun', 1, .5, .25)
                uniform(prog, 'test_ambient', 4, 2, 1)
                uniform(prog, 'sss_params', .8 if flag in (.46, .79, .50, .83) else 0, 1, .5, 40)
                off, on = draw(prog, 0), draw(prog, 1)
                assert off[:4] == on[:4], ('capture changed existing lighting', name, classic, flag)
                assert off[4] == (0, 0, 0, 0)
                assert on[4][0] > 0, ('missing direct donor', name, classic, flag, on)
                if flag in (.38, .71, .50, .83):
                    assert on == reference[(classic, round(flag-.04,2))], ('avatar tag changed lighting or donors',name,flag)
                    checks += 1
                else: reference[(classic,flag)] = on
                checks += 3
                if name != 'softenLightF': continue
                uniform(prog, 'test_sun', 0, 0, 0)
                for ambient in (0, .1, 1, 16):
                    uniform(prog, 'test_ambient', ambient, ambient * .5, ambient * .25)
                    result = draw(prog, 1)
                    assert max(map(abs, result[4])) < 1e-6, ('ambient leaked into donor', classic, flag, ambient, result[4])
                    if ambient > 0: assert result[0][0] > 0, 'ambient fixture must illuminate scene'
                    checks += 1
                if flag in (.67, .79, .71, .83):
                    emit([2, .5, .125, 0])
                    result = draw(prog, 1)[4]
                    scale = 1.1 if classic else 1
                    assert max(abs(result[i] - value * scale) for i, value in enumerate((2, .5, .125))) < 1e-5
                    emit([0, 0, 0, 0]); checks += 1
        for flag in (0, 1):
            uniform(prog, 'test_flag', flag)
            assert max(map(abs, draw(prog, 1)[4])) < 1e-6, ('sky donor', name, flag)
            checks += 1
        gl.DeleteProgram(prog)
    print(f'PASS: {checks} independent SSGI donor checks; five light variants, legacy/PBR/classic/skin, ambient isolation, emission, sky and unchanged MRTs; {gl.GetString(0x1F01).decode()}')

    # Incoming/applied light is already captured with strength by the composite.
    prog = program('ssgiDebugF')
    gl.DrawBuffers(1, (U * 1)(COLOR_ATTACHMENT)); gl.ReadBuffer(COLOR_ATTACHMENT)
    for unit, (sampler, color) in enumerate((('ssgiSource', (.2,.1,.04,0)),
                                            ('depthMap', (.5,0,0,0)))):
        texture(unit, color); uniform(prog, sampler, unit, integer=True)
    debug_checks = 0
    for mode in (1,2,3,4):
        uniform(prog, 'ssgi_debug', mode, integer=True)
        for strength in (0,.65,1,2,15,30):
            # Simulate the appropriate captured source, not a second display gain.
            scale=strength if mode in (1,3) else 1
            texture(0, [.2*scale,.1*scale,.04*scale,0])
            gl.DrawArrays(4,0,3)
            pixel=(F*4)(); gl.ReadPixels(0,0,1,1,RGBA,FLOAT,pixel)
            for i,base in enumerate((.2,.1,.04)):
                value = base * scale
                mapped = min(1,max(0,value)) if mode == 4 else value/(1+value)
                expected = 12.92*mapped if mapped <= .0031308 else 1.055*mapped**(1/2.4)-.055
                assert abs(pixel[i]-expected)<2e-5, (mode,strength,i,pixel[i],expected)
            debug_checks+=1
    assert gl.GetError()==0
    gl.DeleteProgram(prog)
    print(f'PASS: {debug_checks} diagnostic presentation checks; captured incoming/applied bounce is not scaled twice, donors stay unscaled, material response uses direct sRGB display')


if __name__ == '__main__':
    sdl, window, ctx, gl = context()
    try:
        run(sdl, gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx); sdl.SDL_DestroyWindow(window); sdl.SDL_Quit()
