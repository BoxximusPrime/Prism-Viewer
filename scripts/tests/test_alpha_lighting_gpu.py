"""Check production OIT surface lighting on a hidden OpenGL context (Windows).

Run: .venv/Scripts/python.exe scripts/tests/test_alpha_lighting_gpu.py
Reuses the OIT GPU harness. Environment/BRDF inputs are controlled, and capture
is redirected to a float pixel so we can inspect the color sent to OIT. This
does not test in-world appearance, shadows, or the OIT list/compositor itself.
"""

import ctypes as C
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
out vec3 vary_fragcoord, vary_position, vary_norm, vary_normal, vary_tangent;
out vec2 vary_texcoord0, vary_texcoord1, vary_texcoord2;
out vec2 base_color_texcoord, normal_texcoord, metallic_roughness_texcoord, emissive_texcoord;
out vec4 vertex_color;
flat out float vary_sign;
void main() {
    vec2 corners[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
    gl_Position=vec4(corners[gl_VertexID],0,1);
    vary_fragcoord=vec3(0,0,1); vary_position=vec3(0,0,-5);
    vary_norm=vec3(0,0,test_normal_length); vary_normal=vary_norm;
    vary_tangent=vec3(1,0,0); vary_sign=1.0;
    vary_texcoord0=vary_texcoord1=vary_texcoord2=vec2(0.5);
    base_color_texcoord=normal_texcoord=metallic_roughness_texcoord=emissive_texcoord=vec2(0.5);
    vertex_color=vec4(1,1,1,0.6);
}
"""


def run(sdl, gl):
    for name, args in {"Uniform2f": [I, F, F], "Uniform3f": [I, F, F, F],
                       "Uniform4f": [I, F, F, F, F], "DeleteProgram": [U]}.items():
        setattr(gl, name, C.WINFUNCTYPE(None, *args)(sdl.SDL_GL_GetProcAddress(("gl" + name).encode())))

    def obj(generator):
        value = U()
        generator(1, C.byref(value))
        return value.value

    def program(fragment):
        result = gl.CreateProgram()
        for kind, source in [(0x8B31, VERTEX), (0x8B30, fragment)]:
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

    def texture(values):
        result = obj(gl.GenTextures)
        gl.BindTexture(TEXTURE, result)
        gl.TexParameteri(TEXTURE, 0x2801, 0x2600)
        gl.TexParameteri(TEXTURE, 0x2800, 0x2600)
        gl.TexImage2D(TEXTURE, 0, 0x8814, 1, 1, 0, RGBA, FLOAT, (F * 4)(*values))
        return result

    gl.BindVertexArray(obj(gl.GenVertexArrays))
    target = texture([0, 0, 0, 0])
    gl.BindFramebuffer(FRAMEBUFFER, obj(gl.GenFramebuffers))
    gl.FramebufferTexture2D(FRAMEBUFFER, COLOR_ATTACHMENT, TEXTURE, target, 0)
    assert gl.CheckFramebufferStatus(FRAMEBUFFER) == 0x8CD5
    # A flat normal map; its blue albedo channel is also exactly one.
    texture([0.5, 0.5, 1.0, 1.0])
    gl.Viewport(0, 0, 1, 1)

    util = (SHADERS / "class1/deferred/deferredUtil.glsl").read_text()
    half_vectors = function(util, "void calcHalfVectors(")
    punctual = function(util, "float calcLegacyDistanceAttenuation(")
    punctual += function(util, "vec3 pbrCalcPointLightOrSpotLight(")
    checks = 0
    for name, path in [("alpha", "class2/deferred/alphaF.glsl"),
                       ("material", "class3/deferred/materialF.glsl"),
                       ("pbr", "class2/deferred/pbralphaF.glsl")]:
        for oit in (False, True):
            defines = "#define USE_DIFFUSE_TEX 1\n#define USE_VERTEX_COLOR 1\n#define DIFFUSE_ALPHA_MODE 1\n"
            defines += "#define EXACT_OIT 1\n" if oit else ""
            source = defines + (SHADERS / path).read_text() + STUBS + half_vectors
            if name == "pbr":
                source += punctual
            prog = program(source)
            gl.UseProgram(prog)
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
                        gl.DrawArrays(0x0004, 0, 3)
                        pixel = (F * 4)()
                        gl.ReadPixels(0, 0, 1, 1, RGBA, FLOAT, pixel)
                        samples.append(pixel[2])
                        assert abs(pixel[3] - 0.6) < 2e-5, (name, oit, tuple(pixel))
                    # Same opaque point-light coefficient, independent of normal
                    # interpolation length and the Classic environment boost.
                    expected = (2 / 9) * (3.25 if name == "pbr" else 1) * (0.9 if classic else 1) * 0.7
                    actual = samples[1] - samples[0]
                    assert abs(actual - expected) < 2e-5, (name, oit, classic, normal_length, actual, expected)
                    ambient = 0.09 if classic and name != "pbr" else 0.1
                    base = (ambient * 0.7 + 0.2) * (1.1 if classic else 1)
                    assert abs(samples[0] - base) < 2e-5, (name, oit, classic, samples[0], base)
                    checks += 1
            gl.DeleteProgram(prog)
    assert gl.GetError() == 0
    print(f"Passed {checks} GPU lighting cases: OIT/fallback, Classic/modern, interpolated normals, PBR intensity, fog/base preservation, alpha preservation")


if __name__ == "__main__":
    sdl, window, ctx, gl = context()
    try:
        run(sdl, gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
