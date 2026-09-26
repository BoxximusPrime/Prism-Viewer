"""Production SSS transmission across moving screen-space silhouettes, without TAA.

Run: .venv/Scripts/python.exe scripts/tests/test_sss_motion_gpu.py
"""
import math
import statistics
from pathlib import Path
from ctypes import c_float
from itertools import product

from test_exact_oit_gpu import context
from test_gtao_gpu import function
from test_taa_gpu import GPU, W, H

ROOT = Path(__file__).resolve().parents[2]
SHADERS = ROOT / 'indra/newview/app_settings/shaders/class1/deferred'


def run(sdl, gl):
    gpu = GPU(sdl, gl)
    source = '''
uniform sampler2D position_map;
uniform vec4 sss_params;
uniform vec3 sss_lighting;
uniform float sss_penetration;
uniform int sss_shadow_thickness;
vec4 getPosition(vec2 tc) { return texture(position_map, tc); }
'''
    source += (SHADERS / 'sssDepthUtil.glsl').read_text()
    for signature in ('vec3 getSSSTransmissionForPath(float nl, float strength, float path)',
                      'vec3 getSSSTransmission(float nl, float nv, float strength)',
                      'vec3 getSSSTransmissionWithDepth(float nl, float nv, float strength, float path, float shadow)'):
        source += function('gbufferUtil.glsl', signature)
    source += '''
out vec4 frag_color;
void main() {
    vec3 pos = getPosition(gl_FragCoord.xy / screen_res).xyz;
    prepareSSSDepth(pos);
    float path = sampleFocusedSunSSSPath(pos, vec3(0,0,-1));
    vec3 light = getSSSTransmissionWithDepth(-1.0, 1.0, 1.0, path, 1.0);
    frag_color = vec4(light.r, path, getSSSDepthCoverage(), 1.0);
}
'''
    prog = gpu.program(source)
    positions = gpu.texture()
    # An exact 4 mm closed layer. A uniform map isolates receiver reconstruction
    # from light-map rasterization and light/subject motion.
    depth = gpu.texture([.496, 1, .5, 1] * (W * H))
    output = gpu.texture()
    gpu.bind(prog, 'position_map', 0, positions)
    gpu.bind(prog, 'sssDepthMap0', 1, depth)
    gpu.uniform(prog, 'screen_res', W, H)
    gpu.uniform(prog, 'sss_params', 1, 2, 1, 44)
    gpu.uniform(prog, 'sss_lighting', 0, 4, 9)
    gpu.uniform(prog, 'sss_penetration', .08)
    gpu.uniform(prog, 'sss_shadow_thickness', 1, integer=True)
    gpu.uniform(prog, 'sss_depth_valid', 1, 0, 0)
    gpu.uniform(prog, 'sss_depth_focus', 0, 0, -5, 2.5)
    # Move a narrow planar strip by whole pixels: its geometry and lighting are
    # identical, but its edges alternate between derivative-quad alignments.
    # Test both axes, slopes, front/back neighbors, and viewport boundaries.
    checks = 0
    for vertical, slope, background, width, placement in product(
            (False, True), (0, .6), (-10, -4), (3, 6, 12), range(3)):
        sx, sy = (0, slope) if vertical else (slope, 0)
        gpu.matrix(prog, 'sss_depth_matrix[0]', [[1,0,0,.5],[0,1,0,.5],[-sx,-sy,1,5.5],[0,0,0,1]])
        axis_size = H if vertical else W
        start = (0, 30, axis_size-width-7)[placement]
        samples = []
        for offset in range(8):
            left = start + offset
            values = []
            for y in range(H):
                for x in range(W):
                    along, across = (y, x) if vertical else (x, y)
                    a = (along-left-width*.5)*.003
                    b = (across-(W if vertical else H)*.5)*.003
                    px, py = (b, a) if vertical else (a, b)
                    values.extend((px, py, -5+sx*px+sy*py if left <= along < left+width else background, 1))
            gl.ActiveTexture(0x84C0)
            gl.BindTexture(0x0DE1, positions)
            gl.TexImage2D(0x0DE1,0,0x8814,W,H,0,0x1908,0x1406,(c_float*len(values))(*values))
            gpu.bind(prog, 'position_map', 0, positions)
            gpu.bind(prog, 'sssDepthMap0', 1, depth)
            gpu.draw(prog, output)
            pixels = gpu.read(output)
            coords = [(a,b) if vertical else (b,a) for a in range(8,(W if vertical else H)-8)
                      for b in range(left,left+width)]
            samples.append([pixels[(y*W+x)*4] for x,y in coords])
        means = [statistics.mean(frame) for frame in samples]
        delta = math.sqrt(statistics.mean((a-b)**2 for p,q in zip(samples,samples[1:])
                                         for a,b in zip(p,q)))
        assert min(means) > 1, ('Valid thin tissue must keep transmission',vertical,slope,background,width,start,means)
        assert delta < .005, ('Screen-pixel alignment changed unchanged tissue lighting',vertical,slope,background,width,start,delta)
        checks += 1
    print(f'Passed {checks} moving-strip cases: both axes, slopes, foreground/background edges and viewport boundaries.',flush=True)


if __name__ == '__main__':
    sdl, window, ctx, gl = context()
    try:
        print('GPU:', gl.GetString(0x1F01).decode(), flush=True)
        run(sdl, gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
