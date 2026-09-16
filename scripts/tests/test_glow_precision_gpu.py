"""Exercise authored glow extraction/blur with real 8-bit and float render targets.

Run: .venv/Scripts/python.exe scripts/tests/test_glow_precision_gpu.py
No viewer settings or in-world content are changed.
"""
import ctypes as C
from array import array
import math
from pathlib import Path
import random
import sys

import llsd

from test_eye_adaptation_gpu import EyeGPU, ROOT, SHADERS
from test_taa_gpu import context, U, I, F, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT
from test_gtao_gpu import png


def replay(sdl, gl, directory):
    """Compare a RenderGlowDebugDump capture against each production pass."""
    directory = Path(directory)
    metadata = llsd.parse((directory/'metadata.xml').read_bytes())
    settings, buffers = metadata['settings'], metadata['buffers']
    gpu = EyeGPU(sdl, gl)
    gl.BlendFunc = C.WINFUNCTYPE(None, U, U)(sdl.SDL_GL_GetProcAddress(b'glBlendFunc'))
    vertex = (SHADERS/'class1/effects/glowExtractV.glsl').read_text()
    blur_vertex = (SHADERS/'class1/effects/glowV.glsl').read_text()
    positions = '''vec3 positions[3]=vec3[3](vec3(-1,-1,0),vec3(3,-1,0),vec3(-1,3,0));
    #define position positions[gl_VertexID]'''
    vertex = vertex.replace('in vec3 position;', positions)
    blur_vertex = blur_vertex.replace('in vec3 position;', positions)
    extract = gpu.program(f'#define HAS_NOISE {int(settings["RenderGlowNoise"])}\n'+
                          (SHADERS/'class1/effects/glowExtractF.glsl').read_text(), vertex)
    blur = gpu.program((SHADERS/'class1/effects/glowF.glsl').read_text(), blur_vertex)
    combine = gpu.program((SHADERS/'class1/interface/glowcombineF.glsl').read_text(),
                          vertex.replace('vary_texcoord0', 'tc'))
    data, textures = {}, {}
    for name, info in buffers.items():
        data[name] = array('f', (directory/f'{name}.rgba32f').read_bytes())
        assert len(data[name]) == info['width']*info['height']*4, name
        textures[name] = gpu.tex(info['width'], info['height'], data[name], info['format'])
    noise = textures['noise']
    gl.BindTexture(TEXTURE, noise)
    for param in (0x2800, 0x2801): gl.TexParameteri(TEXTURE, param, 0x2600)
    for param in (0x2802, 0x2803): gl.TexParameteri(TEXTURE, param, 0x2901)
    w, h = buffers['extract']['width'], buffers['extract']['height']
    fmt = buffers['extract']['format']
    targets = [gpu.tex(w, h, internal=fmt) for _ in range(2)]

    differences = {}
    def compare(name, result):
        errors = [abs(a-b) for i, (a, b) in enumerate(zip(result, data[name])) if i%4 != 3]
        differences[name] = max(errors)
        print(f'{name}: format={buffers[name]["format"]:#x}, '
              f'max RGB error={max(errors):.8f}, mean={sum(errors)/len(errors):.8f}')

    gpu.uniform(extract, 'minLuminance', 9999.)
    gpu.uniform(extract, 'maxExtractAlpha', .25)
    gpu.uniform(extract, 'lumWeights', 1., 0., 0.)
    gpu.uniform(extract, 'warmthWeights', 1., .5, .7)
    gpu.uniform(extract, 'warmthAmount', 0.)
    gpu.uniform(extract, 'screen_res', w, h)
    gpu.bind(extract, 'glowNoiseMap', 1, noise)
    gpu.bind(extract, 'diffuseMap', 0, textures['scene'])
    gl.FramebufferTexture2D(FRAMEBUFFER, COLOR_ATTACHMENT, TEXTURE, targets[0], 0)
    gl.ClearColor(0., 0., 0., 0.)
    gl.Clear(0x4000)
    gl.Enable(0x0BE2)
    gl.BlendFunc(0x0302, 1)
    gpu.render(extract, targets[0], w, h)
    gl.Disable(0x0BE2)
    compare('extract', gpu.pixels(targets[0], w, h))

    # Start each stage with its captured input to isolate errors, not accumulate them.
    gpu.uniform(blur, 'glowStrength', settings['RenderGlowStrength'])
    resolution_pow = settings['RenderGlowResolutionPow']
    delta = settings['RenderGlowWidth']/max(1, min(1024, 1 << resolution_pow))
    if resolution_pow < 9: delta *= .5
    source = textures['extract']
    for i in range(settings['RenderGlowIterations']*2):
        gpu.reduce(source)
        gpu.bind(blur, 'diffuseMap', 0, source)
        gpu.uniform(blur, 'glowDelta', 0. if i%2 else delta, delta if i%2 else 0.)
        gpu.render(blur, targets[i%2], w, h)
        source = targets[i%2]
    compare('blur', gpu.pixels(source, w, h))

    info = buffers['composite']
    output = gpu.tex(info['width'], info['height'], internal=info['format'])
    gpu.bind(combine, 'diffuseRect', 0, textures['scene'])
    gpu.bind(combine, 'emissiveRect', 1, textures['blur'])
    gpu.render(combine, output, info['width'], info['height'])
    compare('composite', gpu.pixels(output, info['width'], info['height']))
    assert gl.GetError() == 0
    print('Captured settings:', settings)
    return differences


def run(sdl, gl):
    gpu = EyeGPU(sdl, gl)
    gl.BlendFunc = C.WINFUNCTYPE(None, U, U)(sdl.SDL_GL_GetProcAddress(b'glBlendFunc'))
    vertex = '''out vec2 vary_texcoord0;
    void main(){vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
    gl_Position=vec4(p[gl_VertexID],0,1); vary_texcoord0=p[gl_VertexID]*.5+.5;}'''
    # Use the production blur vertex shader, supplying its position attribute.
    blur_vertex = (SHADERS/'class1/effects/glowV.glsl').read_text().replace(
        'in vec3 position;', '''vec3 positions[3]=vec3[3](vec3(-1,-1,0),vec3(3,-1,0),vec3(-1,3,0));
        #define position positions[gl_VertexID]''')
    extract_source = (SHADERS/'class1/effects/glowExtractF.glsl').read_text()
    extracts = [gpu.program(f'#define HAS_NOISE {noise}\n'+extract_source, vertex) for noise in (0, 1)]
    blur = gpu.program((SHADERS/'class1/effects/glowF.glsl').read_text(), blur_vertex)
    combine = gpu.program((SHADERS/'class1/interface/glowcombineF.glsl').read_text(),
                          vertex.replace('vary_texcoord0', 'tc'))
    w = h = 512
    rng = random.Random(1)
    noise = gpu.tex(128, 128, [v for _ in range(128*128) for v in
                             [rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1), 1]])
    for param in (0x2800, 0x2801): gl.TexParameteri(TEXTURE, param, 0x2600)
    for param in (0x2802, 0x2803): gl.TexParameteri(TEXTURE, param, 0x2901)
    scene = []
    for y in range(h):
        for x in range(w):
            # Broad dim glow exposes quantization in low-energy halo gradients.
            alpha = .08 * math.exp(-((x-w/2)**2+(y-h/2)**2)/(2*48**2))
            scene.extend((.35, .22, .12, alpha))
    source = gpu.tex(w, h, scene, 0x8814)
    output = gpu.tex(w, h, internal=0x8814)
    gl.Disable(0x0BD0)  # Driver dithering cannot replace precision between blur passes.

    def render(internal, noise_enabled, source_internal=0x8814, output_internal=0x8814, capture=False):
        gpu.upload_tex(source, w, h, scene, source_internal)
        gpu.upload_tex(output, w, h, internal=output_internal)
        targets = [gpu.tex(w, h, internal=internal) for _ in range(3)]
        program = extracts[noise_enabled]
        gpu.uniform(program, 'minLuminance', 9999.)
        gpu.uniform(program, 'maxExtractAlpha', .25)
        gpu.uniform(program, 'lumWeights', 1., 0., 0.)
        gpu.uniform(program, 'warmthWeights', 1., .5, .7)
        gpu.uniform(program, 'warmthAmount', 0.)
        gpu.uniform(program, 'screen_res', w, h)
        gpu.bind(program, 'glowNoiseMap', 1, noise)
        gpu.bind(program, 'diffuseMap', 0, source)
        gl.FramebufferTexture2D(FRAMEBUFFER, COLOR_ATTACHMENT, TEXTURE, targets[2], 0)
        gl.ClearColor(0., 0., 0., 0.)
        gl.Clear(0x4000)
        gl.Enable(0x0BE2)
        gl.BlendFunc(0x0302, 1)  # Viewer BT_ADD_WITH_ALPHA: premultiply on extraction.
        gpu.render(program, targets[2], w, h)
        gl.Disable(0x0BE2)
        gpu.uniform(blur, 'glowStrength', .325)
        for i in range(4):
            blur_source = targets[2] if i == 0 else targets[(i-1)%2]
            gpu.reduce(blur_source)
            gpu.bind(blur, 'diffuseMap', 0, blur_source)
            gpu.uniform(blur, 'glowDelta', 2/w if i%2 == 0 else 0., 2/h if i%2 else 0.)
            gpu.render(blur, targets[i%2], w, h)
        glow = gpu.pixels(targets[1], w, h)
        gpu.bind(combine, 'diffuseRect', 0, source)
        gpu.bind(combine, 'emissiveRect', 1, targets[1])
        gpu.render(combine, output, w, h)
        if capture:
            directory = ROOT/'tmp/glow-tests/replay-fixture'
            directory.mkdir(parents=True, exist_ok=True)
            metadata = {'settings': {'RenderGlowStrength': .325, 'RenderGlowNoise': noise_enabled,
                                    'RenderGlowIterations': 2, 'RenderGlowWidth': 2.,
                                    'RenderGlowResolutionPow': 9}, 'buffers': {}}
            for name, tex, size, fmt in [('scene', source, w, source_internal),
                    ('extract', targets[2], w, internal), ('blur', targets[1], w, internal),
                    ('composite', output, w, output_internal), ('noise', noise, 128, 0x881A)]:
                metadata['buffers'][name] = {'width': size, 'height': size, 'format': fmt}
                (directory/f'{name}.rgba32f').write_bytes(array('f', gpu.pixels(tex, size, size)).tobytes())
            (directory/'metadata.xml').write_bytes(llsd.format_xml(metadata))
        return glow, gpu.pixels(output, w, h)

    for noise_enabled in (0, 1):
        low, _ = render(0x8058, noise_enabled)  # RGBA8
        high, _ = render(0x881A, noise_enabled)  # RGBA16F
        reference, _ = render(0x8814, noise_enabled)  # RGBA32F
        error = lambda data: max(abs(a-b) for i, (a, b) in enumerate(zip(data, reference)) if i%4 != 3)
        low_error, high_error = error(low), error(high)
        print(f'noise={noise_enabled}: RGBA8 max error={low_error:.6f}, RGBA16F={high_error:.6f}')
        assert high_error < low_error / 10, 'Float targets must retain smooth low-energy glow'
        if not noise_enabled:
            center_row = lambda data: [data[(h//2*w+x)*4] for x in range(w//2, w-30)]
            levels = [len(set(center_row(data))) for data in (low, high)]
            print(f'halo ramp distinct red levels: RGBA8={levels[0]}, RGBA16F={levels[1]}')
            assert levels[1] > levels[0] * 3
        # Display only glow, amplified equally so banding can be compared visually.
        preview = bytearray()
        for y in range(h):
            for data in (low, high):
                for x in range(w):
                    offset = (y*w+x)*4
                    preview.extend(round(max(0., min(1., v*6))*255) for v in data[offset:offset+3])
        png(ROOT/f'tmp/glow-tests/precision-noise-{noise_enabled}.png', w*2, h, preview)
    # RenderGlowHDR only changes the blur targets. Check the independent scene
    # and composite formats too: lost source precision cannot be recovered.
    _, reference = render(0x881A, 1)
    for label, src_fmt, dst_fmt in [('8-bit scene', 0x8058, 0x881A),
                                  ('8-bit composite', 0x881A, 0x8058),
                                  ('all 16-bit', 0x881A, 0x881A)]:
        _, result = render(0x881A, 1, src_fmt, dst_fmt)
        print(f'{label}: composite max RGB error={error(result):.6f}')
    assert gl.GetError() == 0
    render(0x881A, 1, 0x881A, 0x881A, capture=True)
    differences = replay(sdl, gl, ROOT/'tmp/glow-tests/replay-fixture')
    assert max(differences.values()) < .0001, differences
    print('PASS: authored glow precision reproduced on', gl.GetString(0x1F01).decode())


if __name__ == '__main__':
    sdl, window, ctx, gl = context()
    try:
        if len(sys.argv) > 1:
            replay(sdl, gl, sys.argv[1])
        else:
            run(sdl, gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
