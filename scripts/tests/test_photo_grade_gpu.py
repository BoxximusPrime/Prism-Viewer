"""Exercise the production final-scene grading shader on a hidden GPU context."""
import math
from test_taa_gpu import GPU, SHADERS, W, H, context


def run(sdl, gl):
    gpu = GPU(sdl, gl)
    vertex = '''out vec2 vary_fragcoord;
void main(){vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
gl_Position=vec4(p[gl_VertexID],0,1);vary_fragcoord=p[gl_VertexID]*.5+.5;}'''
    source = (SHADERS/'class1/deferred/postDeferredNoDoFF.glsl').read_text()
    source += '\nvec3 clampHDRRange(vec3 c){return clamp(c,vec3(0),vec3(65000));}\n'
    programs = [gpu.program(prefix+source, vertex) for prefix in ('', '#define HAS_NOISE 1\n')]
    texture, depth, output = gpu.texture(), gpu.texture(depth=True), gpu.texture()
    checks = 0

    def check(condition, message):
        nonlocal checks
        assert condition, message
        checks += 1

    def render(rgb, enabled=1, color=(1, 1, 0, 0), curve=(0, 1, 1), program=None,
               aberration=0, image=None):
        program = program or programs[0]
        gpu.upload(texture, image if image is not None else (list(rgb)+[.37])*(W*H))
        gpu.bind(program, 'diffuseRect', 0, texture)
        gpu.bind(program, 'depthMap', 1, depth)
        gpu.uniform(program, 'screen_res', W, H)
        gpu.uniform(program, 'photo_grade_enabled', enabled, integer=True)
        gpu.uniform(program, 'photo_grade_color', *color)
        gpu.uniform(program, 'photo_grade_curve', *curve)
        gpu.uniform(program, 'chromatic_aberration', aberration)
        gpu.draw(program, output)
        return gpu.read(output)

    for program in programs:
        # Disabling grading must restore the exact original output, including noise.
        off = render((.2, .4, .6), enabled=0, program=program)
        neutral = render((.2, .4, .6), program=program)
        check(max(abs(a-b) for a,b in zip(off,neutral))<.002, 'Neutral grade changed scene')
        changed = render((.2, .4, .6), color=(1.4, .5, .8, -.4), program=program)
        check(abs(changed[0]-neutral[0])>.01, 'Grade had no effect')
        restored = render((.2, .4, .6), enabled=0, color=(1.4, .5, .8, -.4), program=program)
        check(restored == off, 'Bypass did not restore original pixels')
        check(abs(changed[3]-.37)<.001, 'Grade changed alpha')
        check(render((1.5,2,.01),program=program)==render((1.5,2,.01),enabled=0,program=program),
              'Neutral grade must preserve over-range bloom before presentation')
    grey = render((.2,.4,.6), color=(1,0,0,0))
    check(max(grey[:3])-min(grey[:3])<.001, 'Zero saturation must be grey')
    warm = render((.4,.4,.4), color=(1,1,1,0))
    check(warm[0]>warm[1]>warm[2], 'Warmth direction incorrect')
    green = render((.4,.4,.4), color=(1,1,0,1))
    check(green[1]>green[0] and abs(green[0]-green[2])<.001, 'Tint direction incorrect')
    pivot = render((.5,.5,.5), color=(2,1,0,0))
    check(max(abs(x-.5) for x in pivot[:3])<.001, 'Contrast moved its midpoint')
    for curve in ((-.25,.5,.5), (.25,2,1.5), (0,1,1)):
        values = [render((v,v,v), curve=curve)[0] for v in (0,.1,.5,.9,1)]
        check(all(math.isfinite(v) and 0<=v<=1 for v in values), 'Nonfinite/out-of-range curve')
        check(values == sorted(values), 'Tonal curve reversed luminance order')
    # A neutral spatial ramp makes each channel's pixel displacement measurable.
    ramp = [v for y in range(H) for x in range(W)
            for v in ((x+.5)/W, (y+.5)/H, (x+.5)/W, .37)]
    for program in programs:
        off = render(None, enabled=0, image=ramp, program=program)
        shifted = render(None, enabled=0, image=ramp, aberration=4, program=program)
        # Presentation noise is color-seeded, so changed red/blue also reseed green noise.
        tolerance = .004 if program == programs[1] else .001
        center = ((H//2)*W+W//2)*4
        edge = ((H//2)*W+W-10)*4
        check(max(abs(a-b) for a,b in zip(off[1::4],shifted[1::4]))<tolerance,
              'Chromatic aberration changed green')
        check(off[3::4] == shifted[3::4], 'Chromatic aberration changed alpha')
        check(shifted[edge]>off[edge]+.01 and shifted[edge+2]<off[edge+2]-.01,
              'Chromatic aberration did not separate red/blue with grading disabled')
        check(abs(shifted[center]-off[center])<tolerance, 'Chromatic aberration moved the center')
        check(max(abs(a-b) for a,b in zip(off,ramp))<tolerance, 'Zero aberration changed pixels')
        check(render(None, enabled=0, image=ramp, program=program)==off,
              'Disabling aberration did not restore original pixels')
        check(render((.2,.4,.6), aberration=10, program=program)==
              render((.2,.4,.6), program=program), 'Aberration changed a constant image at borders')
        maximum = render(None, enabled=0, image=ramp, aberration=20, program=program)
        check(maximum[edge]-maximum[edge+2]>shifted[edge]-shifted[edge+2]+.02,
              'Special-effects strength did not extend channel separation')
        check(all(math.isfinite(v) and 0<=v<=1.004 for v in maximum),
              'Maximum chromatic aberration produced invalid pixels')
        check(render((.2,.4,.6), aberration=20, program=program)==
              render((.2,.4,.6), program=program), 'Maximum aberration broke border clamping')
        # CPU reference checks resolution-aware falloff, both sides and clamped borders.
        for x,y in ((0,0),(W-1,H-1),(W-10,H//2),(10,H//2)):
            dx,dy=x+.5-W/2,y+.5-H/2
            distance=math.hypot(dx,dy)
            offset=dx/max(distance,1)*4*(distance/math.hypot(W/2,H/2))**2/W
            for channel,direction in ((0,1),(2,-1)):
                expected=min(1-.5/W,max(.5/W,(x+.5)/W+direction*offset))
                check(abs(shifted[(y*W+x)*4+channel]-expected)<tolerance,
                      'Incorrect radial chromatic displacement or border clamp')
    print(f'PASS: {checks} grading/chromatic-aberration GPU checks (noise and plain variants)')


if __name__ == '__main__':
    sdl, window, ctx, gl = context()
    try:
        run(sdl, gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
