"""Check legacy glow's sampling footprint, including an optional captured frame.

Run: .venv/Scripts/python.exe scripts/tests/test_glow_sampling_gpu.py [glow-debug-directory]
"""
from array import array
from pathlib import Path
import sys

from test_eye_adaptation_gpu import EyeGPU, ROOT, SHADERS
from test_taa_gpu import context
from test_gtao_gpu import png


def run(sdl, gl):
    gpu = EyeGPU(sdl, gl)
    vertex = (SHADERS/'class1/effects/glowV.glsl').read_text().replace(
        'in vec3 position;', '''vec3 positions[3]=vec3[3](vec3(-1,-1,0),vec3(3,-1,0),vec3(-1,3,0));
        #define position positions[gl_VertexID]''')
    fragment = (SHADERS/'class1/effects/glowF.glsl').read_text()
    programs = [gpu.program(fragment.replace('textureLod(', 'texture(').replace(', lod)', ')'), vertex),
                gpu.program(fragment, vertex)]
    pipeline = (ROOT/'indra/newview/pipeline.cpp').read_text()
    assert 'mGlow[i].allocate(512, glow_res, glow_color_fmt, false,\n            LLTexUnit::TT_TEXTURE, LLTexUnit::TMG_AUTO)' in pipeline
    for target in ('mGlow[2]', 'mGlow[(i - 1) % 2]'):
        assert f'bindTexture(LLShaderMgr::DIFFUSE_MAP, &{target}, false, LLTexUnit::TFO_TRILINEAR)' in pipeline

    def render(values, w, h, delta, fmt=0x881A, strength=.325, passes=4):
        inputs = gpu.tex(w, h, values, fmt)
        targets = [gpu.tex(w, h, internal=fmt) for _ in range(2)]
        outputs = []
        for program in programs:
            source = inputs
            gpu.uniform(program, 'glowStrength', strength)
            for i in range(passes):
                gpu.reduce(source)  # Production TMG_AUTO flush + trilinear binding.
                gpu.bind(program, 'diffuseMap', 0, source)
                gpu.uniform(program, 'glowDelta', 0. if i%2 else delta, delta if i%2 else 0.)
                gpu.render(program, targets[i%2], w, h)
                source = targets[i%2]
            outputs.append(gpu.pixels(source, w, h))
        return outputs

    # Default spacing skips alternating pixels in BOTH axes. Constant-input
    # tests cannot detect it; a single bright texel must spread into a solid halo.
    w = h = 128
    impulse = [0.]*(w*h*4)
    impulse[(64*w+64)*4:(64*w+64)*4+4] = [1., 1., 1., 1.]
    for width in (1., 1.5, 2., 3., 4.):
        old, fixed = render(impulse, w, h, width/w)
        center = lambda values: [values[(y*w+x)*4] for y in range(62,67) for x in range(62,67)]
        energy = lambda values: sum(values[::4])
        print(f'width={width}: central minimum {min(center(old)):.6f} -> {min(center(fixed)):.6f}; '
              f'energy {energy(old):.5f} -> {energy(fixed):.5f}')
        assert min(center(fixed)) > 0, 'Filtered glow must not have holes inside its halo'
        assert abs(energy(fixed)/energy(old)-1) < .02, 'Retain authored glow energy'
        if width == 2:
            assert min(center(old)) == 0, 'Negative control must reproduce the captured grid'
        if width == 1:
            assert old == fixed, 'Unit-spacing blur must be unchanged'
    for fmt in (0x8058, 0x881A):
        old, fixed = render([.07,.04,.02,.1]*(w*h), w, h, 2/w, fmt)
        assert max(abs(a-b) for a,b in zip(old,fixed)) < .0001, 'Uniform glow gain must be unchanged'
        old, fixed = render(impulse, w, h, 2/w, fmt)
        assert min(center(fixed)) > 0, 'Both supported buffer formats must filter the holes'
        _, off = render(impulse, w, h, 2/w, fmt, strength=0.)
        assert max(off[::4]) == 0, 'Zero-strength glow must remain off'
    # The lower glow-resolution setting has a rectangular target: select the
    # footprint from the current axis in texels, not from normalized UV alone.
    h = 64
    impulse = [0.]*(w*h*4)
    impulse[(32*w+64)*4:(32*w+64)*4+4] = [1.,1.,1.,1.]
    old, fixed = render(impulse, w, h, 2/w)
    assert min(fixed[(y*w+x)*4] for y in range(30,35) for x in range(62,67)) > 0
    assert abs(sum(fixed[::4])/sum(old[::4])-1) < .02

    if len(sys.argv) > 1:
        import llsd
        directory = Path(sys.argv[1])
        metadata = llsd.parse((directory/'metadata.xml').read_bytes())
        settings, info = metadata['settings'], metadata['buffers']['extract']
        w, h = info['width'], info['height']
        pixels = array('f', (directory/'extract.rgba32f').read_bytes())
        delta = settings['RenderGlowWidth']/max(1, min(1024, 1 << settings['RenderGlowResolutionPow']))
        if settings['RenderGlowResolutionPow'] < 9: delta *= .5
        old, fixed = render(pixels, w, h, delta, info['format'], settings['RenderGlowStrength'],
                            settings['RenderGlowIterations']*2)
        captured = array('f', (directory/'blur.rgba32f').read_bytes())
        error = max(abs(a-b) for a,b in zip(old,captured))
        print(f'Captured legacy blur reproduction error: {error:.8f}')
        assert error < .0001, 'Reproduce the actual scene before evaluating the fix'
        print(f'Captured red-channel glow energy: {sum(old[::4]):.6f} -> {sum(fixed[::4]):.6f}')
        for name, data in [('before',old),('after',fixed)]:
            # Amplify both equally so low-energy halo sampling is visible.
            preview = bytearray(round(max(0,min(1,data[(y*w+x)*4+c]*8))*255)
                                for y in range(h-1,-1,-1) for x in range(w) for c in range(3))
            png(ROOT/f'tmp/glow-tests/sampling-{name}.png', w, h, preview)
    assert gl.GetError() == 0
    print('PASS: glow sampling regression on', gl.GetString(0x1F01).decode())


if __name__ == '__main__':
    sdl, window, ctx, gl = context()
    try:
        run(sdl, gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
