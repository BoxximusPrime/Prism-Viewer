"""Exercise the production GPU skinning blend with local and high-altitude palettes.

Run: .venv/Scripts/python.exe scripts/tests/test_avatar_render_precision_gpu.py
Uses a hidden SDL context; does not change viewer settings or world content.
"""
import ctypes as C

from test_eye_adaptation_gpu import EyeGPU, SHADERS
from test_taa_gpu import context, F


def run(sdl, gl):
    gpu = EyeGPU(sdl, gl)
    skin = (SHADERS/'class1/avatar/objectSkinV.glsl').read_text()
    vertex = '''uniform mat4 modelview_matrix;
    out vec3 measured_position;
    mat4 getObjectSkinnedTransform();
    void main() {
        vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
        gl_Position=vec4(p[gl_VertexID],0,1);
        measured_position=(modelview_matrix*getObjectSkinnedTransform()*vec4(.123,.234,.345,1)).xyz;
    }'''
    program = gpu.program('in vec3 measured_position; out vec4 frag_color; '
                          'void main(){frag_color=vec4(measured_position,1);}', vertex,
                          '#define MAX_JOINTS_PER_MESH_OBJECT 4\n'+skin)
    output = gpu.tex(1, 1, internal=0x8814)  # RGBA32F preserves submillimetre differences.
    gl.VertexAttrib4f(1, .1, 1.2, 2.3, 3.4)
    encoded = [F(x).value for x in (.1, 1.2, 2.3, 3.4)]
    weights = [x-int(x) for x in encoded]
    weights = [x/sum(weights) for x in weights]
    worst_new = worst_old = 0.
    cases = 0
    for altitude in (0., 1368., 4000., 4096., 8192., 30000.):
        for frame in range(40):
            offsets = [F(.173+j*.057+frame*.000013).value for j in range(4)]
            expected = F(.345).value + sum(w*z for w, z in zip(weights, offsets))-2
            for local in (False, True):
                view = [[float(r == c) for c in range(4)] for r in range(4)]
                view[2][3] = -2 if local else -altitude-2
                gpu.matrix(program, 'modelview_matrix', view)
                palette = []
                for offset in offsets:
                    palette.extend((1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1,
                                    offset if local else altitude+offset))
                gl.UniformMatrix3x4fv(gl.GetUniformLocation(program, b'matrixPalette'),
                                     4, False, (F*len(palette))(*palette))
                gpu.render(program, output)
                error = abs(gpu.pixels(output)[2]-expected)
                if local:
                    worst_new = max(worst_new, error)
                    assert error < 3e-7, (altitude, frame, error)
                else:
                    worst_old = max(worst_old, error)
                cases += 1
    assert worst_old > .0005, worst_old
    assert gl.GetError() == 0
    print(f'{cases} GPU skinning cases passed; maximum local error {worst_new:.9f} m, '
          f'old world blend {worst_old:.6f} m')


if __name__ == '__main__':
    sdl, window, ctx, gl = context()
    try:
        run(sdl, gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
