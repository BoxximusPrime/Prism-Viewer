"""Run production GTAO, denoising, composition and debug shaders without login.

Uses the bundled SDL3 hidden context and Python stdlib only. Synthetic ray/box
geometry supplies D24 depth and the viewer's packed normals. Writes a diagnostic
PNG under tmp/gtao-tests and checks meaningful image behavior, not shader text.
Run: .venv/Scripts/python.exe scripts/tests/test_gtao_gpu.py
"""
import ctypes as C
import math
from pathlib import Path
import statistics
import struct
import sys
import zlib

from test_exact_oit_gpu import context, U, I, F, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT, RGBA, FLOAT

ROOT = Path(__file__).resolve().parents[2]
SHADERS = ROOT / "indra/newview/app_settings/shaders"
WIDTH, HEIGHT = 256, 192


def function(filename, signature):
    source = (SHADERS / "class1/deferred" / filename).read_text()
    start = source.index(signature + "\n{")
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


def png(path, width, height, rgb):
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    scan = b''.join(b'\0' + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 2, 0, 0, 0)) +
                    chunk(b'IDAT', zlib.compress(scan)) + chunk(b'IEND', b''))


def inverse(matrix):
    rows = [list(row) + [float(i == j) for j in range(4)] for i, row in enumerate(matrix)]
    for col in range(4):
        pivot = max(range(col, 4), key=lambda i: abs(rows[i][col]))
        rows[col], rows[pivot] = rows[pivot], rows[col]
        scale = rows[col][col]
        rows[col] = [v / scale for v in rows[col]]
        for row in range(4):
            if row != col:
                scale = rows[row][col]
                rows[row] = [a - scale * b for a, b in zip(rows[row], rows[col])]
    return [row[4:] for row in rows]


def run(sdl, gl):
    for name, args in {
        'ActiveTexture': [U], 'Uniform2f': [I, F, F], 'Uniform3f': [I, F, F, F],
        'Uniform4f': [I, F, F, F, F], 'UniformMatrix4fv': [I, I, C.c_ubyte, C.POINTER(F)],
        'DeleteTextures': [I, C.POINTER(U)]
    }.items():
        setattr(gl, name, C.WINFUNCTYPE(None, *args)(sdl.SDL_GL_GetProcAddress(('gl' + name).encode())))
    def obj(fn):
        value = U(); fn(1, C.byref(value)); return value.value
    def program(sources):
        prog = gl.CreateProgram()
        vertex = '''out vec2 vary_fragcoord; void main(){
        vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
        gl_Position=vec4(p[gl_VertexID],0,1); vary_fragcoord=p[gl_VertexID]*0.5+0.5;}'''
        for kind, source in [(0x8B31, vertex)] + [(0x8B30, s) for s in sources]:
            shader = gl.CreateShader(kind)
            text = C.c_char_p(('#version 150 core\n' + source).encode())
            gl.ShaderSource(shader, 1, C.byref(text), None); gl.CompileShader(shader)
            ok, log = I(), C.create_string_buffer(16384)
            gl.GetShaderiv(shader, 0x8B81, C.byref(ok)); gl.GetShaderInfoLog(shader, len(log), None, log)
            assert ok.value, log.value.decode()
            gl.AttachShader(prog, shader); gl.DeleteShader(shader)
        gl.LinkProgram(prog)
        gl.GetProgramiv(prog, 0x8B82, C.byref(ok)); gl.GetProgramInfoLog(prog, len(log), None, log)
        assert ok.value, log.value.decode()
        return prog
    helpers = 'uniform mat4 inv_proj; uniform sampler2D normalMap;\n' + '\n'.join([
        function('globalF.glsl', 'vec4 decodeNormal(vec4 norm)'),
        function('deferredUtil.glsl', 'vec4 getNorm(vec2 screenpos)'),
        function('deferredUtil.glsl', 'vec2 getScreenCoordinate(vec2 screenpos)'),
        function('deferredUtil.glsl', 'vec3 getPositionWithNDC(vec3 ndc)'),
        function('deferredUtil.glsl', 'vec4 getPositionWithDepth(vec2 pos_screen, float depth)')])
    source = lambda name: (SHADERS / 'class1/deferred' / name).read_text()
    gtao = program([source('gtaoF.glsl'), helpers])
    blur = program([source('gtaoBlurF.glsl'), helpers])
    debug = program([source('gtaoDebugF.glsl')])
    sun = program([(SHADERS / 'class2/deferred/sunLightSSAOF.glsl').read_text(), '''
        vec4 getPosition(vec2 p){return vec4(0,0,-2,1);}
        vec4 getNorm(vec2 p){return vec4(0,0,1,0);}
        void preparePCSSDepth(vec3 p, vec3 n, vec2 s){}
        float sampleDirectionalShadow(vec3 p,vec3 n,vec2 s){return 0.7;}
        float sampleSpotShadow(vec3 p,vec3 n,int i,vec2 s){return i==0?0.4:0.2;}
        float calcAmbientOcclusion(vec4 p,vec3 n,vec2 s){return 0.63;}'''])
    def uniform(prog, name, *values, integer=False):
        gl.UseProgram(prog)
        loc = gl.GetUniformLocation(prog, name.encode())
        getattr(gl, 'Uniform1i' if integer else f'Uniform{len(values)}f')(loc, *values)
    gl.BindVertexArray(obj(gl.GenVertexArrays))
    framebuffer = obj(gl.GenFramebuffers)
    gl.BindFramebuffer(FRAMEBUFFER, framebuffer); gl.Viewport(0, 0, WIDTH, HEIGHT)
    def texture(values=None, depth=False, output=False):
        tex = obj(gl.GenTextures); gl.BindTexture(TEXTURE, tex)
        for param in (0x2800, 0x2801): gl.TexParameteri(TEXTURE, param, 0x2600)
        for param in (0x2802, 0x2803): gl.TexParameteri(TEXTURE, param, 0x812F)
        gl.TexImage2D(TEXTURE, 0, 0x81A6 if depth else (0x822F if output else 0x8814), WIDTH, HEIGHT, 0,
                      0x1902 if depth else RGBA, FLOAT, (F * len(values))(*values) if values else None)
        return tex
    raw, scratch, final = texture(output=True), texture(output=True), texture()
    def bind(prog, name, unit, tex):
        gl.ActiveTexture(0x84C0 + unit); gl.BindTexture(TEXTURE, tex)
        uniform(prog, name, unit, integer=True)
    def draw(prog, tex):
        gl.UseProgram(prog)
        gl.FramebufferTexture2D(FRAMEBUFFER, COLOR_ATTACHMENT, TEXTURE, tex, 0)
        assert gl.CheckFramebufferStatus(FRAMEBUFFER) == 0x8CD5
        gl.DrawArrays(4, 0, 3)
    def read(tex):
        gl.FramebufferTexture2D(FRAMEBUFFER, COLOR_ATTACHMENT, TEXTURE, tex, 0)
        output = (F * (WIDTH * HEIGHT * 4))()
        gl.ReadPixels(0, 0, WIDTH, HEIGHT, RGBA, FLOAT, output)
        assert gl.GetError() == 0
        return list(output)

    # Perspective camera looking toward -Z. Generate physically consistent
    # depth and surface normals using analytic planes and a box.
    def scene(kind='box', fov=60, scale=1, jitter=(0, 0)):
        near, far = 0.1 * scale, 1000 * scale
        f = 1 / math.tan(math.radians(fov) / 2)
        p = [[f / (WIDTH / HEIGHT), 0, jitter[0], 0], [0, f, jitter[1], 0],
             [0, 0, (far + near) / (near - far), 2 * far * near / (near - far)], [0, 0, -1, 0]]
        inv = inverse(p)
        depth, normal, points = [], [], []
        for y in range(HEIGHT):
            for x in range(WIDTH):
                ray = [((x + 0.5) / WIDTH * 2 - 1 + jitter[0]) / p[0][0],
                       ((y + 0.5) / HEIGHT * 2 - 1 + jitter[1]) / p[1][1], -1]
                t, n = (4 * scale, [0, 0, 1]) if kind != 'sky' else (far, [0, 0, 1])
                if kind == 'slope':
                    n = [0.6, 0, 0.8]
                    t = -2.4 * scale / sum(a * b for a, b in zip(n, ray))
                if kind in ('box', 'corner') and ray[1] < 0:
                    floor_t = -0.65 * scale / ray[1]
                    if 0 < floor_t < t: t, n = floor_t, [0, 1, 0]
                if kind == 'box':
                    lo, hi = [-0.35 * scale, -0.65 * scale, -3 * scale], [0.35 * scale, -0.05 * scale, -2.3 * scale]
                    entry, leave, axis, sign = -1e30, 1e30, 0, 0
                    for i in range(3):
                        if abs(ray[i]) < 1e-10:
                            if not lo[i] <= 0 <= hi[i]:
                                entry = 1e30
                                break
                            continue
                        a, b = lo[i] / ray[i], hi[i] / ray[i]
                        hit_sign = -1 if ray[i] > 0 else 1
                        if a > b: a, b = b, a
                        if a > entry: entry, axis, sign = a, i, hit_sign
                        leave = min(leave, b)
                    if 0 < entry < t and entry < leave:
                        t, n = entry, [0, 0, 0]; n[axis] = sign
                z = -t
                d = ((p[2][2] * z + p[2][3]) / -z) * 0.5 + 0.5
                depth.append(1 if kind == 'sky' else d)
                divisor = math.sqrt(8 * n[2] + 8)
                normal.extend([n[0] / divisor + 0.5, n[1] / divisor + 0.5, 0, 0])
                points.append(tuple(t * a for a in ray))
        return texture(depth, depth=True), texture(normal), inv, points

    def render(data, radius=0.5, quality=1, denoise=1, thin=0, falloff=0.6, noise=0):
        dep, norm, inv, _ = data
        for prog in (gtao, blur):
            bind(prog, 'depthMap', 0, dep); bind(prog, 'normalMap', 1, norm)
            uniform(prog, 'screen_res', WIDTH, HEIGHT)
            uniform(prog, 'gtao_params', radius, falloff, thin, denoise)
            matrix = (F * 16)(*(inv[r][c] for c in range(4) for r in range(4)))
            gl.UniformMatrix4fv(gl.GetUniformLocation(prog, b'inv_proj'), 1, 0, matrix)
        uniform(gtao, 'gtao_quality', quality, integer=True)
        uniform(gtao, 'gtao_noise_index', noise, integer=True)
        draw(gtao, raw)
        unfiltered = read(raw)
        if denoise:
            for src, dest, delta in [(raw, scratch, (1, 0)), (scratch, raw, (0, 1))]:
                bind(blur, 'diffuseMap', 2, src); uniform(blur, 'delta', *delta); draw(blur, dest)
        result = read(raw)
        assert all(math.isfinite(v) for v in result), 'non-finite visibility'
        assert all(0 <= v < 2 for v in result[::4]), (min(result[::4]), max(result[::4]))
        return result, unfiltered

    if '--benchmark' in sys.argv:
        data = scene('box')
        query = obj(gl.GenQueries)
        for quality in range(3):
            render(data, quality=quality)
            durations = []
            for frame in range(25):
                gl.BeginQuery(0x88BF, query)
                draw(gtao, raw)
                for src, dest, delta in [(raw, scratch, (1, 0)), (scratch, raw, (0, 1))]:
                    bind(blur, 'diffuseMap', 2, src); uniform(blur, 'delta', *delta); draw(blur, dest)
                gl.EndQuery(0x88BF)
                ns = C.c_uint64()
                gl.GetQueryObjectui64v(query, 0x8866, C.byref(ns))
                if frame >= 5: durations.append(ns.value / 1e6)
            print(f'{WIDTH}x{HEIGHT} quality {quality}: median {statistics.median(durations):.3f} ms (GTAO + two denoise passes)')
        assert gl.GetError() == 0
        return

    count = 0
    for kind in ('sky', 'plane', 'slope'):
        data = scene(kind)
        for quality in range(3):
            result, _ = render(data, quality=quality)
            avg = statistics.mean(min(1, v) for v in result[::4])
            print(kind, quality, 'visibility', round(avg, 5), 'minimum', min(result[::4]))
            assert avg > 0.995, (kind, quality, avg)
            assert all(v == (0 if kind == 'sky' else 1) for v in result[1::4])
            count += 1

    data = scene('box')
    result, unfiltered = render(data)
    # Floor contact region must darken, while the box's front face stays clear.
    contact = [i for i, (x, y, z) in enumerate(data[3]) if abs(y + 0.65) < 0.001 and abs(x) < 0.6 and -3.2 < z < -2.05]
    front = [i for i, (x, y, z) in enumerate(data[3]) if abs(z + 2.3) < 0.001 and abs(x) < 0.2 and -0.35 < y < -0.15]
    mean_at = lambda image, indices: statistics.mean(min(1, image[i * 4]) for i in indices)
    print('contact', mean_at(result, contact), 'front', mean_at(result, front))
    assert mean_at(result, contact) < 0.9
    assert mean_at(result, front) > 0.98
    again, _ = render(data)
    assert result == again, 'spatial noise changes between identical frames'
    temporal, _ = render(data, noise=1)
    assert result != temporal, 'future TAA noise index has no effect'
    wrapped, _ = render(data, noise=64)
    assert result == wrapped, 'noise index must wrap at 64'
    small, _ = render(data, radius=0.15)
    large, _ = render(data, radius=1)
    assert mean_at(large, contact) < mean_at(small, contact), 'radius has no useful effect'
    compensated, _ = render(data, thin=1)
    assert mean_at(compensated, contact) >= mean_at(result, contact), 'thin compensation darkens'
    faded, _ = render(data, falloff=1)
    assert mean_at(faded, contact) >= mean_at(result, contact), 'falloff darkens'
    for radius in (0.05, 3):
        for quality in range(3):
            render(data, radius=radius, quality=quality, denoise=2)
            count += 1
    raw_only, raw_copy = render(data, denoise=0)
    assert raw_only == raw_copy
    scaled = scene('box', scale=10)
    scaled_result, _ = render(scaled, radius=5)
    error = statistics.mean(abs(a - b) for a, b in zip(result[::4], scaled_result[::4]))
    assert error < 0.003, ('world scale changed GTAO', error)
    for fov in (35, 100):
        render(scene('box', fov=fov)); count += 1
    render(scene('box', jitter=(0.5 / WIDTH, -0.5 / HEIGHT)))

    # The actual sun shader must preserve its three shadow channels, apply
    # strength only to AO, and return to the old AO function when disabled.
    result, _ = render(data)
    bind(sun, 'gtaoMap', 2, raw)
    for enabled in (0, 1):
        for strength in (0, 1, 2):
            uniform(sun, 'gtao_enabled', enabled, integer=True); uniform(sun, 'gtao_strength', strength)
            draw(sun, final); combined = read(final)
            for i in range(WIDTH * HEIGHT):
                r, g, b, a = combined[i * 4:i * 4 + 4]
                assert abs(r - 0.7) < 1e-6 and abs(b - 0.4) < 1e-6 and abs(a - 0.2) < 1e-6
                expected = min(1, result[i * 4]) ** strength if enabled else 0.63
                assert abs(g - expected) < 1e-5
            count += 1
    bind(debug, 'diffuseMap', 2, raw)
    for strength in (0, 1, 2):
        uniform(debug, 'gtao_strength', strength); draw(debug, final); diagnostic = read(final)
        assert all(abs(r - g) < 1e-6 and abs(r - b) < 1e-6 for r, g, b in zip(diagnostic[::4], diagnostic[1::4], diagnostic[2::4]))
        assert all(v == 0 for v in diagnostic[3::4])
        if strength == 0: assert min(diagnostic[::4]) > 0.999
        if strength == 1:
            rgb = bytes(round(max(0, min(1, diagnostic[(y * WIDTH + x) * 4 + c])) * 255)
                        for y in reversed(range(HEIGHT)) for x in range(WIDTH) for c in range(3))
            png(ROOT / 'tmp/gtao-tests/white-geometry.png', WIDTH, HEIGHT, rgb)
        count += 1
    assert gl.GetError() == 0
    print(f'PASS: {count + 12} GTAO GPU scenarios; world-scale mean error {error:.6f};', gl.GetString(0x1F01).decode())


if __name__ == '__main__':
    if '--benchmark' in sys.argv:
        WIDTH, HEIGHT = 1920, 1080
    sdl, window, ctx, gl = context()
    try:
        run(sdl, gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx); sdl.SDL_DestroyWindow(window); sdl.SDL_Quit()
