"""Grazing water reflections: coherent depth hits, motion and edge rejection.

Compiles the production screen trace, with a synthetic wall and controlled rays.
Run: .venv/Scripts/python.exe scripts/tests/test_water_reflections_gpu.py
"""
import math
import ctypes as C
import statistics
from pathlib import Path
import sys

from test_eye_adaptation_gpu import EyeGPU
from test_taa_gpu import context, I, U
from test_water_gpu import function

ROOT=Path(__file__).resolve().parents[2]
SHADERS=ROOT/'indra/newview/app_settings/shaders'


def run(sdl,gl):
    gpu=EyeGPU(sdl,gl)
    paths=[arg for arg in sys.argv[1:] if not arg.startswith('--')]
    path=Path(paths[0]) if paths else SHADERS/'class3/environment/waterF.glsl'
    water=path.read_text(encoding='utf-8')
    util=(SHADERS/'class1/deferred/deferredUtil.glsl').read_text(encoding='utf-8')
    source='''uniform sampler2D depthMap,screenTex;
uniform mat4 projection_matrix,inv_proj;
uniform vec4 waterPlane;
uniform int water_local_reflections,cube_snapshot;
uniform float water_displacement;
'''
    functions=[('vec3 getPositionWithNDC(',util),('bool waterProject(',water),('vec3 waterScenePosition(',water)]
    if 'vec3 waterReflectionScenePosition(' in water:
        functions.append(('vec3 waterReflectionScenePosition(',water))
    functions.append(('vec4 waterLocalReflection(',water))
    for signature,code in functions:
        source+=function(code,signature)+'\n'
    source+='''
uniform vec3 fixture_point,fixture_normal,fixture_axis;
uniform float fixture_sweep,fixture_roughness;
out vec4 frag_color;
void main() {
    vec3 pos=fixture_point;
    pos+=fixture_axis*fixture_sweep*gl_FragCoord.x/512.0;
    frag_color=waterLocalReflection(pos,normalize(fixture_normal),fixture_roughness);
}'''
    program=gpu.program(source)
    # 90 degree, aspect 1, near 0.1 and far 200. Analytic inverse.
    a=-200.1/199.9;b=-40/199.9
    projection=[[1,0,0,0],[0,1,0,0],[0,0,a,b],[0,0,-1,0]]
    inverse=[[1,0,0,0],[0,1,0,0],[0,0,0,-1],[0,0,1/b,a/b]]
    output=gpu.tex(512,1,internal=0x8814)
    scene=gpu.tex(1024,1024,[.15,.3,.45,1]*1024**2)
    depth=gpu.tex(1024,1024,internal=0x822E)
    gpu.matrix(program,'projection_matrix',projection)
    gpu.matrix(program,'inv_proj',inverse)
    gpu.uniform(program,'water_local_reflections',1,integer=True)
    gpu.uniform(program,'cube_snapshot',0,integer=True)
    gpu.uniform(program,'fixture_roughness',.08)
    cases=0
    def check(ok,label):
        nonlocal cases
        assert ok,label
        cases+=1
    def wall(z,split=False):
        d=(-a+b/z)*.5+.5
        values=[v for y in range(1024) for x in range(1024)
                for v in ((1 if split and x>=512 else d),)*4]
        gpu.upload_tex(depth,1024,1024,values,internal=0x822E)
        for param in (0x2800,0x2801):gl.TexParameteri(0x0DE1,param,0x2600)
    def draw(point=(0,-1,-4),normal=(0,1,0),sweep=0,plane=None,axis=(0,0,-1),displacement=0):
        gpu.bind(program,'depthMap',0,depth)
        gpu.bind(program,'screenTex',1,scene)
        gpu.uniform(program,'waterPlane',*(plane or (0,1,0,-point[1])))
        gpu.uniform(program,'fixture_point',*point)
        gpu.uniform(program,'fixture_normal',*normal)
        gpu.uniform(program,'fixture_sweep',sweep)
        gpu.uniform(program,'fixture_axis',*axis)
        gpu.uniform(program,'water_displacement',displacement)
        gpu.render(program,output,512,1)
        pixels=gpu.pixels(output,512,1)
        check(all(math.isfinite(v) for v in pixels),'trace outputs stay finite')
        return pixels
    # A uniformly coloured, uninterrupted wall must not acquire scanlines from
    # the changing residual depth error of the exponential march/refinement.
    wall(65)
    alpha=draw(point=(0,-1,-22),sweep=24)[3::4]
    maximum_jump=max(abs(a-b) for a,b in zip(alpha,alpha[1:]))
    print(f'{path.name}: wall coverage {min(alpha):.6f}..{max(alpha):.6f}; adjacent jump {maximum_jump:.6f}')
    check(min(alpha)>.98,'uniform wall retains continuous reflection coverage')
    check(maximum_jump<.005,'march intervals do not produce scanlines')

    # A vertical colour gradient has an analytic reflected UV on this wall.
    # Check lookup position as well as coverage: inaccurate hits can shear the
    # image into stripes even when they happen to pass the depth tolerance.
    gradient=[v for y in range(2048) for v in ((y+.5)/2048,)*3+(1,)]
    gpu.upload_tex(scene,1,2048,gradient,internal=0x8814)
    for shift in (0,.002,.25):
        pixels=draw(point=(0,-1,-22-shift),sweep=24)
        errors=[]
        for x in range(512):
            distance=22+shift+24*(x+.5)/512
            expected=.5+.5*(65/distance-2.0)/65
            errors.append(abs(pixels[x*4]-expected))
        check(max(errors)<.00002,'reflected texture stays registered during camera motion')

    # Crossing the old 0.01 up-direction cutoff must be a smooth confidence
    # transition as the camera descends, rather than a whole-reflection switch.
    wall(8)
    values=[]
    for height in (.0396,.0398,.04,.0402,.0404):
        values.append(draw(point=(0,-height,-4))[3])
    check(max(abs(a-b) for a,b in zip(values,values[1:]))<.02,'grazing cutoff is continuous')
    check(values[-1]>.9,'valid grazing reflection is retained')
    check(draw(normal=(0,-1,0),point=(0,1,-4),plane=(0,1,0,1))[3]==0,'downward rays rejected')
    check(draw(plane=(0,1,0,-20))[3]==0,'submerged receiver rejected')
    wall(8,split=True)
    check(draw(point=(2,-1,-4))[3]==0,'sky/disocclusion rejected')
    check(draw(point=(-2,-1,-4))[3]>.9,'nearby silhouette keeps valid side')
    # A vertical wall meets the water at z=-8. Rays from the last few centimetres
    # of water must reflect the wall rather than falling through to the sky probe.
    wall(8)
    near_contact=[]
    for separation in (.5,.2,.1,.05,.02,.01,.001):
        near_contact.append(draw(point=(0,-1,-8+separation))[3])
    print(f'{path.name}: wall contact coverage '+', '.join(f'{v:.6f}' for v in near_contact))
    check(min(near_contact)>.98,'reflection reaches the water/vertical-wall contact without a sky strip')
    for offset in (-.25,-.05,0,.05,.25):
        for separation in (.05,.01,.001):
            pixel=draw(point=(0,-1+offset,-8+separation),plane=(0,1,0,1),displacement=1)
            check(pixel[3]>.98,'wall contact follows displaced crests and troughs')
    for pitch in (-.35,.35):
        n=(0,math.cos(pitch),math.sin(pitch))
        for separation in (.03,.001):
            z=-8+separation
            pixel=draw(point=(0,(-1-n[2]*z)/n[1],z),normal=n,plane=(*n,1))
            check(pixel[3]>.98,'pitched camera does not bias the ray through the contact wall')

    # Looking lengthwise under a dock: the underside is a continuous horizontal
    # plane 0.5 m above the eye, with water 0.4 m below it. Perspective makes
    # neighbouring depth rows represent very different distances near the horizon.
    for resolution in (512,1024,2048):
        height=.5
        values=[]
        for y in range(resolution):
            ndc=(y+.5)/resolution*2-1
            distance=height/ndc if ndc>0 else 10000
            d=(-a+b/distance)*.5+.5 if .1<distance<200 else 1
            values.extend((d,d,d,d))
        gpu.upload_tex(depth,1,resolution,values,internal=0x822E)
        for param in (0x2800,0x2801):gl.TexParameteri(0x0DE1,param,0x2600)
        pixels=draw(point=(0,-.4,-2),sweep=18)
        alpha=pixels[3::4]
        if '--benchmark' in sys.argv and resolution==512:
            for name,args in {'GenQueries':[I,C.POINTER(U)],'BeginQuery':[U,U],'EndQuery':[U],
                'GetQueryObjectui64v':[U,U,C.POINTER(C.c_uint64)],'DeleteQueries':[I,C.POINTER(U)]}.items():
                setattr(gl,name,C.WINFUNCTYPE(None,*args)(sdl.SDL_GL_GetProcAddress(('gl'+name).encode())))
            large_output=gpu.tex(1280,720,internal=0x8814)
            gpu.bind(program,'depthMap',0,depth);gpu.bind(program,'screenTex',1,scene)
            gpu.uniform(program,'fixture_sweep',18*512/1280)
            query=U();gl.GenQueries(1,C.byref(query));timings=[]
            for iteration in range(14):
                gl.BeginQuery(0x88BF,query.value)
                gpu.render(program,large_output,1280,720)
                gl.EndQuery(0x88BF)
                nanos=C.c_uint64();gl.GetQueryObjectui64v(query.value,0x8866,C.byref(nanos))
                if iteration>=4:timings.append(nanos.value/1e6)
            gl.DeleteQueries(1,C.byref(query))
            print(f'{path.name}: isolated 1280x720 dock trace {statistics.median(timings):.3f} ms')
        jump=max(abs(a-b) for a,b in zip(alpha,alpha[1:]))
        print(f'{path.name}: dock {resolution} coverage {min(alpha):.6f}..{max(alpha):.6f}; adjacent jump {jump:.6f}')
        check(min(alpha)>.98,'continuous dock underside retains reflection coverage')
        check(jump<.005,'dock depth rows do not produce scanlines')
    # Rolled/pitched cameras exercise both depth gradients. The reflected plane
    # is still continuous, even though its depth rows are now diagonal on screen.
    for pitch,roll in ((0,.4),(.25,-.3),(-.25,.3)):
        n=(math.sin(roll)*math.cos(pitch),math.cos(roll)*math.cos(pitch),math.sin(pitch))
        along=(math.sin(roll)*math.sin(pitch),math.cos(roll)*math.sin(pitch),-math.cos(pitch))
        values=[];resolution=512
        for y in range(resolution):
            for x in range(resolution):
                denominator=n[0]*((x+.5)*2/resolution-1)+n[1]*((y+.5)*2/resolution-1)-n[2]
                distance=.5/denominator if denominator>0 else 10000
                d=(-a+b/distance)*.5+.5 if .1<distance<200 else 1
                values.extend((d,d,d,d))
        gpu.upload_tex(depth,resolution,resolution,values,internal=0x822E)
        for param in (0x2800,0x2801):gl.TexParameteri(0x0DE1,param,0x2600)
        for shift in (0,.002,.1):
            point=tuple(-.4*up+(2+shift)*forward for up,forward in zip(n,along))
            alpha=draw(point=point,normal=n,plane=(*n,.4),axis=along,sweep=17)[3::4]
            check(min(alpha)>.98,'tilted camera keeps the dock continuous through subpixel motion')
    wall(8,split=True)
    gpu.uniform(program,'water_local_reflections',0,integer=True)
    check(draw(point=(-2,-1,-4))[3]==0,'local reflection toggle bypasses trace')
    if 'vec3 waterReflectionScenePosition(' in water:
        lookup=gpu.program(source.replace(
            'frag_color=waterLocalReflection(pos,normalize(fixture_normal),fixture_roughness);',
            'frag_color=vec4(waterReflectionScenePosition(fixture_point.xy),1.0);'))
        gpu.matrix(lookup,'inv_proj',inverse)
        # A one-pixel support post between distant surfaces must retain its own
        # depth; smoothing it into neighbours would produce false reflection hits.
        # Also cover a silhouette against sky at subpixel lookup positions.
        for distances in ((10,10,10,4,10,10,10,10),(4,4,4,4,200,200,200,200)):
            values=[v for distance in distances for v in ((-a+b/distance)*.5+.5,)*4]
            gpu.upload_tex(depth,8,1,values,internal=0x822E)
            for pixel in (2,3,4):
                for fraction in (.1,.5,.9):
                    gpu.bind(lookup,'depthMap',0,depth)
                    gpu.uniform(lookup,'fixture_point',(pixel+fraction)/8,.5,0)
                    gpu.render(lookup,output,1,1)
                    actual=gpu.pixels(output,512,1)[2]
                    check(abs(actual+distances[pixel])<.02,'subpixel depth preserves thin posts and silhouette boundaries')
    print(f'PASS: {cases} reflection stability GPU checks on {gl.GetString(0x1F01).decode()}')


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try:run(sdl,gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx);sdl.SDL_DestroyWindow(window);sdl.SDL_Quit()
