"""Check that hair skips unused lighting work without changing irradiance/depth.

Uses production entry points with instrumented probe/light dependencies.
Run: .venv/Scripts/python.exe scripts/tests/test_hair_shader_work_gpu.py
"""
import math

from test_taa_gpu import GPU, SHADERS, W, H, context
from test_alpha_lighting_gpu import function


def run(sdl, gl):
    gpu = GPU(sdl, gl)
    target = gpu.texture()
    checks = 0

    def pixel(prog):
        gpu.draw(prog, target)
        offset = (H // 2 * W + W // 2) * 4
        return gpu.read(target)[offset:offset + 4]

    def check(condition, label):
        nonlocal checks
        assert condition, label
        checks += 1

    for level in ('class2', 'class3'):
        source = (SHADERS / level / 'deferred/reflectionProbeF.glsl').read_text()
        common = '''
uniform int classic_mode, mode;
uniform float reflection_probe_ambiance;
uniform samplerCube environmentMap;
uniform mat3 env_mat;
float calls = 0.0;
float max_probe_lod = 8.0;
vec3 srgb_to_linear(vec3 c) { return c; }
void preProbeSample(vec3 p) { calls += 1.0; }
vec3 sampleProbeAmbient(vec3 p, vec3 n, vec3 a) { return a*.5 + abs(n)*.2; }
vec3 sampleProbes(vec3 p, vec3 n, float lod) { calls += 10.0; return vec3(.7); }
void tapHeroProbe(inout vec3 g, vec3 p, vec3 n, float gloss) { calls += 10.0; }
'''
        common += function(source, 'void sampleReflectionProbesAmbient(')
        if level == 'class3':
            common += function(source, 'void doProbeSample(')
        common += function(source, 'void sampleReflectionProbes(')
        common += function(source, 'void sampleReflectionProbesLegacy(')
        prog = gpu.program(common + '''
out vec4 frag_color;
void main() {
    vec3 a=vec3(.2,.3,.4), g=vec3(0), e=vec3(0), p=vec3(0,0,-1), n=vec3(0,0,1);
    if (mode == 0) sampleReflectionProbesAmbient(a,p,n,a);
    if (mode == 1) sampleReflectionProbes(a,g,vec2(.5),p,n,.9,true,a);
    if (mode == 2) sampleReflectionProbesLegacy(a,g,e,vec2(.5),p,n,.9,1.0,true,a);
    frag_color=vec4(a,calls);
}
''')
        for classic in (0, 1):
            gpu.uniform(prog, 'classic_mode', classic, integer=True)
            for ambiance in (0, .5, 1):
                gpu.uniform(prog, 'reflection_probe_ambiance', ambiance)
                gpu.uniform(prog, 'mode', 0, integer=True)
                ambient = pixel(prog)
                check(ambient[3] == (1 if level == 'class3' and classic == 0 else 0),
                      'ambient path only prepares probes when used')
                for mode in (1, 2):
                    gpu.uniform(prog, 'mode', mode, integer=True)
                    full = pixel(prog)
                    check(full[:3] == ambient[:3], (level, classic, ambiance, mode, 'same ambient result'))
                    if level == 'class3':
                        check(full[3] > ambient[3], 'ordinary path still evaluates glossy probes')

    source = (SHADERS / 'class1/deferred/projectorUtil.glsl').read_text()
    prog = gpu.program('''
uniform vec3 light_diffuse[8], light_direction[8];
uniform vec4 light_position[8], light_attenuation[8];
uniform vec2 light_deferred_attenuation[8];
uniform int classic_mode;
float calls=0.0;
float calcLegacyDistanceAttenuation(float d,float f) { return 1.0; }
vec3 hairSafeNormalize(vec3 v,vec3 fallback) { return normalize(v); }
float hairLocalShadow(vec3 p,vec3 o,float f) { calls+=1.0; return f; }
vec3 hairDirectVisibility(vec3 b,vec3 n,vec3 t,vec3 v,vec3 l,float a,float s,float tr)
{ calls+=1.0; return b; }
''' + function(source, 'vec3 hairLocalLight(') + '''
out vec4 frag_color;
void main() {
    vec3 color=hairLocalLight(1,vec3(.4),vec3(0,0,1),vec3(0,1,0),vec3(0,0,-1),.5);
    frag_color=vec4(color,calls);
}
''')
    gpu.uniform(prog, 'light_deferred_attenuation[1]', 10, .5)
    gpu.uniform(prog, 'light_attenuation[1]', 1, 1, 1, 0)
    check(pixel(prog) == [0, 0, 0, 0], 'black slots skip shadow and BRDF despite a retained radius')
    gpu.uniform(prog, 'light_diffuse[1]', 1, .5, .25)
    check(pixel(prog)[3] == 2, 'contributing slots keep shadow and BRDF')

    source = (SHADERS / 'class1/deferred/hairDepthUtil.glsl').read_text()
    prog = gpu.program('#define HAIR_DENSITY_MAPS 1\n' + source + '''
out vec4 frag_color;
void main() { if (!hairDepthCapture(.5,frag_color)) frag_color=vec4(-1); }
''')
    bounds = gpu.texture([1, 10, 0, 0] * (W * H))
    gpu.bind(prog, 'hairBoundsMap', 0, bounds)
    # At gl_FragCoord.z=.5 this projection reconstructs an axial distance of 2 m.
    gpu.uniform(prog, 'hair_capture_projection', -.5, -1, 0, 1)
    for mode in (1, 2, 3):
        gpu.uniform(prog, 'hair_depth_pass', mode, integer=True)
        gpu.uniform(prog, 'hair_depth_object', int(mode > 1), integer=True)
        expected = [2] * 4 if mode < 3 else [0, 0, 0, -math.log(1 - .85 * .5)]
        check(max(abs(a-b) for a, b in zip(pixel(prog), expected)) < .002,
              ('single capture projection preserves blocker/nearest/density depth', mode))
    print(f'Passed {checks} hair shader work/irradiance/depth checks')


if __name__ == '__main__':
    sdl, window, ctx, gl = context()
    try:
        run(sdl, gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
