"""Check production OIT surface lighting on a hidden OpenGL context (Windows).

Run: .venv/Scripts/python.exe scripts/tests/test_alpha_lighting_gpu.py
Reuses the OIT GPU harness. Environment/BRDF inputs are controlled, and capture
is redirected to a float pixel so we can inspect the color sent to OIT. This
does not test in-world appearance, shadows, or the OIT list/compositor itself.
"""

import ctypes as C
import math
from pathlib import Path

from test_exact_oit_gpu import context, U, I, F, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT, RGBA, FLOAT

ROOT = Path(__file__).resolve().parents[2]
SHADERS = ROOT / "indra/newview/app_settings/shaders"


def function(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end] + "\n"


STUBS = """
uniform float test_ambient;
vec3 srgb_to_linear(vec3 c) { return c; }
vec3 linear_to_srgb(vec3 c) { return c; }
void mirrorClip(vec3 p) {}
void waterClip(vec3 p) {}
float sampleDirectionalShadow(vec3 p, vec3 n, vec2 tc) { return 1.0; }
void calcAtmosphericVarsLinear(vec3 p, vec3 n, vec3 l,
    out vec3 sunlit, out vec3 amblit, out vec3 additive, out vec3 atten)
{ sunlit=vec3(0); amblit=vec3(test_ambient); atten=vec3(0.7); additive=vec3(0.2); }
vec4 applySkyAndWaterFog(vec3 p, vec3 additive, vec3 atten, vec4 c)
{ return vec4(c.rgb * atten + additive, c.a); }
void sampleReflectionProbesLegacy(inout vec3 a, inout vec3 g, inout vec3 e,
    vec2 tc, vec3 p, vec3 n, float gloss, float env, bool t, vec3 amb) {}
void sampleReflectionProbes(inout vec3 a, inout vec3 g,
    vec2 tc, vec3 p, vec3 n, float gloss, bool t, vec3 amb) {}
void applyGlossEnv(inout vec3 c, vec3 g, vec4 s, vec3 p, vec3 n) {}
void applyLegacyEnv(inout vec3 c, vec3 e, vec4 s, vec3 p, vec3 n, float i) {}
void calcDiffuseSpecular(vec3 b, float m, inout vec3 d, inout vec3 s)
{ d=b; s=vec3(0); }
vec3 pbrBaseLight(vec3 d, vec3 s, float m, vec3 p, vec3 n, float r,
    vec3 l, vec3 sun, float shadow, vec3 rad, vec3 irr, vec3 e, float ao,
    vec3 additive, vec3 atten) { return irr; }
void pbrPunctual(vec3 d, vec3 s, float r, float m, vec3 n, vec3 v, vec3 l,
    out float nl, out vec3 diff, out vec3 spec)
{ nl=max(dot(n,l),0.0); diff=d; spec=vec3(0); }
#ifdef EXACT_OIT
layout(location=0) out vec4 test_output;
void exact_oit_store(vec4 c) { test_output=c; }
#endif
"""

VERTEX = """
uniform float test_normal_length;
uniform vec3 test_position;
out vec3 vary_fragcoord, vary_position, vary_norm, vary_normal, vary_tangent;
out vec2 vary_texcoord0, vary_texcoord1, vary_texcoord2;
out vec2 base_color_texcoord, normal_texcoord, metallic_roughness_texcoord, emissive_texcoord;
out vec4 vertex_color;
flat out float vary_sign;
void main() {
    vec2 corners[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
    gl_Position=vec4(corners[gl_VertexID],0,1);
    vary_fragcoord=vec3(0,0,1); vary_position=test_position;
    vary_norm=vec3(0,0,test_normal_length); vary_normal=vary_norm;
    vary_tangent=vec3(1,0,0); vary_sign=1.0;
    vary_texcoord0=vary_texcoord1=vary_texcoord2=vec2(0.5);
    base_color_texcoord=normal_texcoord=metallic_roughness_texcoord=emissive_texcoord=vec2(0.5);
    vertex_color=vec4(1,1,1,0.6);
}
"""


def run(sdl, gl, projectors=False):
    for name, args in {"Uniform2f": [I, F, F], "Uniform3f": [I, F, F, F],
                       "Uniform4f": [I, F, F, F, F], "DeleteProgram": [U],
                       "ActiveTexture": [U], "UniformMatrix4fv": [I, I, C.c_ubyte, C.POINTER(F)]}.items():
        setattr(gl, name, C.WINFUNCTYPE(None, *args)(sdl.SDL_GL_GetProcAddress(("gl" + name).encode())))

    def obj(generator):
        value = U()
        generator(1, C.byref(value))
        return value.value

    def program(fragment):
        result = gl.CreateProgram()
        projector = (SHADERS / "class1/deferred/projectorUtil.glsl").read_text()
        stages = [(0x8B31, VERTEX), (0x8B30, fragment)]
        if projectors:
            projector = "#define ALPHA_PROJECTORS 1\n#define SPOT_SHADOW 1\n" + projector
            stages.append((0x8B30, "#define SPOT_SHADOW 1\n" +
                           (SHADERS / "class1/deferred/shadowUtil.glsl").read_text()))
        stages.append((0x8B30, projector))
        for kind, source in stages:
            shader = gl.CreateShader(kind)
            source = C.c_char_p(("#version 430 core\n" + source).encode())
            gl.ShaderSource(shader, 1, C.byref(source), None)
            gl.CompileShader(shader)
            ok, log = I(), C.create_string_buffer(16384)
            gl.GetShaderiv(shader, 0x8B81, C.byref(ok))
            gl.GetShaderInfoLog(shader, len(log), None, log)
            assert ok.value, log.value.decode()
            gl.AttachShader(result, shader)
            gl.DeleteShader(shader)
        gl.LinkProgram(result)
        gl.GetProgramiv(result, 0x8B82, C.byref(ok))
        gl.GetProgramInfoLog(result, len(log), None, log)
        assert ok.value, log.value.decode()
        return result

    def uniform(prog, name, *values, integer=False):
        loc = gl.GetUniformLocation(prog, name.encode())
        getattr(gl, "Uniform1i" if integer else f"Uniform{len(values)}f")(loc, *values)

    def matrix(prog, name, rows):
        values = (F * 16)(*(rows[r][c] for c in range(4) for r in range(4)))
        gl.UniformMatrix4fv(gl.GetUniformLocation(prog, name.encode()), 1, 0, values)

    def pixel():
        gl.DrawArrays(0x0004, 0, 3)
        result = (F * 4)()
        gl.ReadPixels(0, 0, 1, 1, RGBA, FLOAT, result)
        return tuple(result)

    def texture(values):
        result = obj(gl.GenTextures)
        gl.BindTexture(TEXTURE, result)
        gl.TexParameteri(TEXTURE, 0x2801, 0x2600)
        gl.TexParameteri(TEXTURE, 0x2800, 0x2600)
        gl.TexImage2D(TEXTURE, 0, 0x8814, 1, 1, 0, RGBA, FLOAT, (F * 4)(*values))
        return result

    gl.ActiveTexture(0x84C0)
    gl.BindVertexArray(obj(gl.GenVertexArrays))
    target = texture([0, 0, 0, 0])
    gl.BindFramebuffer(FRAMEBUFFER, obj(gl.GenFramebuffers))
    gl.FramebufferTexture2D(FRAMEBUFFER, COLOR_ATTACHMENT, TEXTURE, target, 0)
    assert gl.CheckFramebufferStatus(FRAMEBUFFER) == 0x8CD5
    # A flat normal map; its blue albedo channel is also exactly one.
    texture([0.5, 0.5, 1.0, 1.0])
    gl.Viewport(0, 0, 1, 1)

    projector_colors = [(0.25, 0.5, 0.75, 0.5)] * 5 + [(1.0, 0.2, 0.1, 0.8)]
    if projectors:
        projector_textures = []
        for i, color in enumerate(projector_colors):
            gl.ActiveTexture(0x84C0 + i + 1)
            projector_textures.append(texture(color))
        gl.ActiveTexture(0x84C1)
        focus_texture = obj(gl.GenTextures)
        gl.BindTexture(TEXTURE, focus_texture)
        gl.TexParameteri(TEXTURE, 0x2801, 0x2700)  # NEAREST_MIPMAP_NEAREST
        gl.TexParameteri(TEXTURE, 0x2800, 0x2600)
        for level, color in enumerate(((1,0,0,1), (0,1,0,1), (0,0,1,1))):
            size = 4 >> level
            gl.TexImage2D(TEXTURE, level, 0x8814, size, size, 0, RGBA, FLOAT,
                          (F * (4 * size * size))(*(color * (size * size))))
        gl.BindTexture(TEXTURE, projector_textures[0])
        for i, depth in enumerate((0.4, 0.7)):
            gl.ActiveTexture(0x84C0 + 7 + i)
            gl.BindTexture(TEXTURE, obj(gl.GenTextures))
            gl.TexParameteri(TEXTURE, 0x2801, 0x2600)
            gl.TexParameteri(TEXTURE, 0x2800, 0x2600)
            gl.TexParameteri(TEXTURE, 0x884C, 0x884E)  # COMPARE_REF_TO_TEXTURE
            gl.TexParameteri(TEXTURE, 0x884D, 0x0203)  # LEQUAL
            gl.TexImage2D(TEXTURE, 0, 0x8CAC, 1, 1, 0, 0x1902, FLOAT, (F * 1)(depth))
        gl.ActiveTexture(0x84C0)

    util = (SHADERS / "class1/deferred/deferredUtil.glsl").read_text()
    half_vectors = function(util, "void calcHalfVectors(")
    attenuation = function(util, "float calcLegacyDistanceAttenuation(")
    punctual = util[util.index("bool hasAlphaProjector("):util.index("vec3 pbrCalcPointLightOrSpotLight(")]
    punctual += function(util, "vec3 pbrCalcPointLightOrSpotLight(")
    checks = 0
    projector_checks = 0
    for name, path in [("alpha", "class2/deferred/alphaF.glsl"),
                       ("material", "class3/deferred/materialF.glsl"),
                       ("pbr", "class2/deferred/pbralphaF.glsl")]:
        for oit in (False, True):
            defines = "#define USE_DIFFUSE_TEX 1\n#define USE_VERTEX_COLOR 1\n#define DIFFUSE_ALPHA_MODE 1\n"
            defines += "#define EXACT_OIT 1\n" if oit else ""
            stubs = STUBS
            if projectors:
                stubs = stubs.replace("float sampleDirectionalShadow(vec3 p, vec3 n, vec2 tc) { return 1.0; }", "")
            source = defines + (SHADERS / path).read_text() + stubs + half_vectors + attenuation
            if name == "pbr":
                source += punctual
            prog = program(source)
            gl.UseProgram(prog)
            uniform(prog, "test_position", 0, 0, -5)
            if projectors:
                for i in range(6):
                    uniform(prog, f"alphaProjectionMap{i}", i + 1, integer=True)
                    matrix(prog, f"alpha_projector_matrix[{i}]",
                           [(1,0,-0.5,0), (0,1,-0.5,0), (0,0,-1,-1), (0,0,-1,0)])
                    uniform(prog, f"alpha_projector_normal[{i}]", 0, 0, -1)
                    uniform(prog, f"alpha_projector_params[{i}]", 0, 0, 9, 0)
                    uniform(prog, f"alpha_projector_shadow[{i}]", -1, 1)
                for i in range(2):
                    uniform(prog, f"shadowMap{i + 4}", i + 7, integer=True)
                    matrix(prog, f"shadow_matrix[{i + 4}]",
                           [(0.1,0,0,0.5), (0,0.1,0,0.5), (0,0,-0.1,0), (0,0,0,1)])
                uniform(prog, "proj_shadow_res", 1, 1)
                uniform(prog, "shadow_clip", 1, 1, 1, 100)
            for i in range(8):
                uniform(prog, f"light_position[{i}]", 0, 0, 0, 1)
                # Radius=10, raw falloff=1: la=9/10, fa=1+1/2.
                uniform(prog, f"light_attenuation[{i}]", 0.9, 1.5, 1, 0)
                uniform(prog, f"light_deferred_attenuation[{i}]", 10, 0.5)
            uniform(prog, "test_ambient", 0.1)
            for classic in (0, 1):
                uniform(prog, "classic_mode", classic, integer=True)
                for normal_length in (1.0, 0.5, 0.1):
                    uniform(prog, "test_normal_length", normal_length)
                    samples = []
                    for strength in (0.0, 1.0):
                        uniform(prog, "light_diffuse[2]", strength, strength, strength)
                        actual_pixel = pixel()
                        samples.append(actual_pixel[2])
                        assert abs(actual_pixel[3] - 0.6) < 2e-5, (name, oit, actual_pixel)
                    # Same opaque point-light coefficient, independent of normal
                    # interpolation length and the Classic environment boost.
                    expected = (2 / 9) * (3.25 if name == "pbr" else 1) * (0.9 if classic else 1) * 0.7
                    actual = samples[1] - samples[0]
                    assert abs(actual - expected) < 2e-5, (name, oit, classic, normal_length, actual, expected)
                    ambient = 0.09 if classic and name != "pbr" else 0.1
                    base = (ambient * 0.7 + 0.2) * (1.1 if classic else 1)
                    assert abs(samples[0] - base) < 2e-5, (name, oit, classic, samples[0], base)
                    checks += 1
            if projectors:
                # Each tuple: label, position, map slot, shadow index/fade,
                # expected visibility, virtual projector origin.
                cases = [
                    ("textured", (0,0,-5), 0, -1, 1, 1, (0,0,0)),
                    ("last light slot", (0,0,-5), 5, -1, 1, 1, (0,0,0)),
                    ("off axis inside beam", (1,0,-5), 0, -1, 1, 1, (0,0,0)),
                    ("outside beam", (3,0,-5), 0, -1, 1, 0, (0,0,0)),
                    ("behind projector", (0,0,2), 0, -1, 1, 0, (0,0,0)),
                    ("before near plane", (0,0,-0.5), 0, -1, 1, 0, (0,0,0)),
                    ("beyond radius", (0,0,-11), 0, -1, 1, 0, (0,0,0)),
                    ("blocked by first shadow", (0,0,-5), 0, 0, 0, 0, (0,0,0)),
                    ("receiver before occluder", (0,0,-3), 0, 0, 0, 1, (0,0,0)),
                    ("second shadow map", (0,0,-5), 0, 1, 0, 1, (0,0,0)),
                    ("shadow fading out", (0,0,-5), 0, 0, 0.25, 0.25, (0,0,0)),
                    ("offset virtual origin", (0,0,-5), 0, -1, 1, 1, (3,0,0)),
                ]
                uniform(prog, "test_normal_length", 0.5)
                for classic in (0, 1):
                    uniform(prog, "classic_mode", classic, integer=True)
                    for label, pos, slot, shadow, fade, visibility, origin in cases:
                        for i in range(8):
                            uniform(prog, f"light_diffuse[{i}]", 0, 0, 0)
                        uniform(prog, "test_position", *pos)
                        uniform(prog, "alpha_projector_mask", 1 << slot, integer=True)
                        uniform(prog, f"alpha_projector_origin[{slot}]", *origin)
                        uniform(prog, f"alpha_projector_shadow[{slot}]", shadow, fade)
                        dark = pixel()
                        uniform(prog, f"light_diffuse[{slot + 2}]", 1, 1, 1)
                        lit = pixel()
                        dist = math.sqrt(sum(x*x for x in pos))
                        direction = [a-b for a,b in zip(origin,pos)]
                        nl = max(direction[2] / math.sqrt(sum(x*x for x in direction)), 0)
                        factor = 2 * max((1 - dist / 10) / 1.5, 0)**2 * nl * visibility * 0.7
                        factor *= (3.25 if name == "pbr" else 1) * (0.9 if classic else 1)
                        color = projector_colors[slot]
                        expected = [factor * color[i] * color[3] * (1 if i == 2 else 0.5) for i in range(3)]
                        actual = [a-b for a,b in zip(lit[:3], dark[:3])]
                        assert max(abs(a-b) for a,b in zip(actual, expected)) < 2e-5, (name, oit, classic, label, actual, expected)
                        assert abs(lit[3] - 0.6) < 2e-5, (name, label, lit)
                        projector_checks += 1
                # Explicit mip selection and softened beam edges use the same
                # sampling functions as the opaque projector pass.
                uniform(prog, "classic_mode", 0, integer=True)
                uniform(prog, "test_normal_length", 1)
                uniform(prog, "alpha_projector_mask", 1, integer=True)
                uniform(prog, "alpha_projector_origin[0]", 0, 0, 0)
                uniform(prog, "alpha_projector_shadow[0]", -1, 1)
                gl.ActiveTexture(0x84C1)
                gl.BindTexture(TEXTURE, focus_texture)
                for label, focus, x, color, edge in [
                    ("focused", 5, 0, (1,0,0), 1),
                    ("defocused", 0, 0, (0,1,0), 1),
                    ("maximum blur", -4, 0, (0,0,1), 1),
                    ("soft beam edge", 0, 2.25, (0,1,0), 0.04),
                ]:
                    uniform(prog, "test_position", x, 0, -5)
                    uniform(prog, "alpha_projector_params[0]", focus, 2, 9, 0)
                    uniform(prog, "light_diffuse[2]", 0, 0, 0)
                    dark = pixel()
                    uniform(prog, "light_diffuse[2]", 1, 1, 1)
                    lit = pixel()
                    dist = math.hypot(x, 5)
                    factor = 2 * ((1 - dist / 10) / 1.5)**2 * (5 / dist) * 0.7 * edge
                    factor *= 3.25 if name == "pbr" else 1
                    expected = [factor * color[i] * (1 if i == 2 else 0.5) for i in range(3)]
                    actual = [a-b for a,b in zip(lit[:3], dark[:3])]
                    assert max(abs(a-b) for a,b in zip(actual, expected)) < 2e-5, (name, oit, label, actual, expected)
                    projector_checks += 1
                gl.BindTexture(TEXTURE, projector_textures[0])
                gl.ActiveTexture(0x84C0)
                # Projector ambiance is intentionally unshadowed in the opaque
                # pass, and differs between legacy and PBR materials.
                uniform(prog, "test_position", 0, 0, -5)
                uniform(prog, "alpha_projector_params[0]", 0, 0, 9, 0.2)
                uniform(prog, "alpha_projector_shadow[0]", 0, 0)
                for normal_length in (1, -1):
                    uniform(prog, "test_normal_length", normal_length)
                    uniform(prog, "light_diffuse[2]", 0, 0, 0)
                    dark = pixel()
                    uniform(prog, "light_diffuse[2]", 1, 1, 1)
                    lit = pixel()
                    coefficient = (0.6 * 3.25 if normal_length > 0 else 0) if name == "pbr" else (0.4 if normal_length < 0 else 0)
                    expected_blue = coefficient * (2 / 9) * 0.75 * 0.5 * 0.7
                    assert abs(lit[2] - dark[2] - expected_blue) < 2e-5, (name, oit, "ambiance", normal_length, lit, dark)
                    projector_checks += 1
            gl.DeleteProgram(prog)
    assert gl.GetError() == 0
    print(f"Passed {checks} GPU lighting cases: OIT/fallback, Classic/modern, interpolated normals, PBR intensity, fog/base preservation, alpha preservation")
    if projectors:
        print(f"Passed {projector_checks} GPU projector cases: texture color/alpha, beam/near/radius clipping, receiver-depth shadows, both shadow maps/fading, light slots, origin offset, focus/mips/soft edges, ambiance")


if __name__ == "__main__":
    sdl, window, ctx, gl = context()
    try:
        run(sdl, gl)
        run(sdl, gl, projectors=True)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
