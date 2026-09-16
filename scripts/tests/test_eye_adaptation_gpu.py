"""Exercise the actual EyeAd/stock shaders on a hidden GPU context; no viewer restart.

Run: .venv/Scripts/python.exe scripts/tests/test_eye_adaptation_gpu.py
Covers metering, bounded exposure, highlights, temporal response, stock fallback,
shadow contrast, environment tone-map mixing, legacy/PBR presentation variants
and non-finite input. Uses production mixed-precision
textures and automatic mip reduction. Does not change viewer settings.
"""
import ctypes as C
import json
import math
from pathlib import Path
import re

from test_taa_gpu import GPU, context, U, I, F, P, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT, RGBA, FLOAT

ROOT = Path(__file__).resolve().parents[2]
SHADERS = ROOT / 'indra/newview/app_settings/shaders'
VERTEX = """out vec2 vary_fragcoord;
void main() {
    vec2 p[3] = vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
    gl_Position = vec4(p[gl_VertexID],0,1);
    vary_fragcoord = p[gl_VertexID]*0.5+0.5;
}"""


class EyeGPU(GPU):
    def __init__(self, sdl, gl):
        super().__init__(sdl, gl)
        for name, args in {
            'GenerateMipmap': [U],
            'GetTexImage': [U,I,U,U,P],
            'TexSubImage2D': [U,I,I,I,I,I,U,U,P],
        }.items():
            setattr(gl, name, C.WINFUNCTYPE(None, *args)(
                sdl.SDL_GL_GetProcAddress(('gl'+name).encode())))

    def tex(self, width, height, values=None, internal=0x881A):
        tex = self.obj(self.gl.GenTextures)
        self.upload_tex(tex, width, height, values, internal)
        return tex

    def upload_tex(self, tex, width, height, values=None, internal=0x881A):
        gl = self.gl
        gl.ActiveTexture(0x84C0)
        gl.BindTexture(TEXTURE, tex)
        for param in (0x2800,0x2801): gl.TexParameteri(TEXTURE,param,0x2601)
        for param in (0x2802,0x2803): gl.TexParameteri(TEXTURE,param,0x812F)
        gl.TexImage2D(TEXTURE,0,internal,width,height,0,RGBA,FLOAT,
            (F*len(values))(*values) if values is not None else None)

    def render(self, program, output, width=1, height=1):
        self.gl.Viewport(0,0,width,height)
        self.draw(program,output)

    def pixels(self, tex, width=1, height=1, level=0):
        gl=self.gl
        gl.ActiveTexture(0x84C0); gl.BindTexture(TEXTURE,tex)
        data=(F*(width*height*4))()
        gl.GetTexImage(TEXTURE,level,RGBA,FLOAT,data)
        assert gl.GetError()==0
        return list(data)

    def reduce(self, tex):
        gl=self.gl
        # Production flush generates the mip chain before restoring the FBO.
        gl.ActiveTexture(0x84C0); gl.BindTexture(TEXTURE,tex)
        gl.TexParameteri(TEXTURE,0x2801,0x2703)
        gl.GenerateMipmap(TEXTURE)


def run(sdl,gl):
    gpu=EyeGPU(sdl,gl)
    shader=lambda file:(SHADERS/'class1/deferred'/file).read_text()
    mgr=(ROOT/'indra/llrender/llshadermgr.cpp').read_text()
    macros='\n'.join(bytes(s,'utf8').decode('unicode_escape') for s in
        re.findall(r'strdup\("(#define (?:GBUFFER|GET_GBUFFER)[^"]*)"\)',mgr))
    meter_program=gpu.program(macros+shader('luminanceF.glsl'),VERTEX)
    exposures=[gpu.program(prefix+shader('exposureF.glsl'),VERTEX)
        for prefix in ('','#define USE_LAST_EXPOSURE 1\n')]
    source=gpu.tex(256,256)
    normal=gpu.tex(1,1,[0,0,1,.34])
    emissive=gpu.tex(1,1,[0,0,0,0])
    meter=gpu.tex(256,256)
    previous=gpu.tex(1,1,[1,0,0,1],0x822E)
    output=gpu.tex(1,1,internal=0x822E)
    cases=0
    summary={}
    def check(condition,message):
        nonlocal cases
        assert condition,message
        cases+=1

    def scene(function, advanced=True, glow=0., flag=.34, scale=.5):
        values=[v for y in range(256) for x in range(256)
            for v in (*function(x,y),1)]
        gpu.upload_tex(source,256,256,values)
        gpu.upload_tex(emissive,1,1,[glow,glow,glow,0])
        gpu.upload_tex(normal,1,1,[0,0,1,flag])
        gpu.bind(meter_program,'diffuseRect',0,source)
        gpu.bind(meter_program,'emissiveRect',1,emissive)
        gpu.bind(meter_program,'normalMap',2,normal)
        gpu.uniform(meter_program,'eye_adaptation',int(advanced),integer=True)
        gpu.uniform(meter_program,'diffuse_luminance_scale',scale)
        gpu.render(meter_program,meter,256,256)
        gpu.reduce(meter)
        return gpu.pixels(meter,level=8)

    def uniform_scene(value,**kwargs):
        return scene(lambda x,y:(value,)*3,**kwargs)

    def expose(advanced=True, history=False, prev=1., dt=1/60,
               boost=2., darken=2., compensation=.25, protection=.65,
               dark_time=2., light_time=.6, stock=(.5,.5,2.,.1), stock_time=2.):
        if prev is not None:
            gpu.upload_tex(previous,1,1,[prev,0,0,1],0x822E)
        program=exposures[int(history)]
        gpu.bind(program,'emissiveRect',0,meter)
        if history: gpu.bind(program,'exposureMap',1,previous)
        gpu.uniform(program,'eye_adaptation',int(advanced),integer=True)
        gpu.uniform(program,'eye_adaptation_limits',-darken,boost,compensation,protection)
        gpu.uniform(program,'eye_adaptation_times',dark_time,light_time)
        gpu.uniform(program,'dynamic_exposure_params',*stock)
        gpu.uniform(program,'dynamic_exposure_params2',1,.5,2,stock_time)
        gpu.uniform(program,'dt',dt)
        gpu.render(program,output)
        return gpu.pixels(output)[0]

    # Production half-float mip chain must preserve negative log luminance.
    for value in [0.,.0001,.001,.01,.05,.18,.5,1.,4.,16.,64.,1000.]:
        stats=uniform_scene(value)
        measured=2**(stats[0]/stats[2])
        expected=max(.0001,min(value,64.))
        check(abs(math.log2(measured/expected))<.035,('log meter',value,stats))
        exp=expose()
        check(math.isfinite(exp) and .25<=exp<=4.,('exposure bounds',value,exp))
        if value==.01: check(exp>3.95,'dark room should receive the configured boost')
        if value==4: check(exp<.3,'bright scene should reduce exposure')
    for value in [float('nan'),float('inf'),-float('inf'),-1.]:
        uniform_scene(value)
        check(math.isfinite(expose()),('nonfinite scene',value))

    uniform_scene(.001)
    for boost in [0,1,2,3,4]:
        check(abs(expose(boost=boost)-2**boost)<.015,('independent boost cap',boost))
    uniform_scene(64.)
    for darken in [0,1,2,3,4]:
        check(abs(expose(darken=darken)-2**-darken)<.002,('independent darken cap',darken))

    uniform_scene(.18)
    low=expose(compensation=-1,protection=0)
    high=expose(compensation=1,protection=0)
    check(abs(high/low-4)<.03,'target brightness should use exposure stops')

    # A window at the edge must count; the stock meter crops these pixels.
    edge=lambda x,y: (8.,)*3 if x>239 else (.015,)*3
    stats=scene(edge)
    geometric=2**(stats[0]/stats[2])
    check(geometric>.0155,('screen-edge window included',stats))
    unprotected=expose(protection=0)
    protected=expose(protection=1)
    check(.25<protected<unprotected,('highlight protection',protected,unprotected))
    summary['dark_room_with_edge_window']={'unprotected_exposure':unprotected,'protected_exposure':protected}
    # A solitary hot pixel should not black out the room.
    scene(lambda x,y:(64.,)*3 if (x,y)==(128,128) else (.015,)*3)
    check(expose(protection=1)>3.,'one hot pixel must not dominate')

    # Regression: a shadow-heavy room with substantial lit surfaces used to
    # request extra brightening even when those surfaces were already bright.
    # Interleaved samples keep the area fraction independent of center weighting.
    scene(lambda x,y:(.9,)*3 if x%4==0 else (.005,)*3)
    room_exposure=expose(boost=1.3,darken=2.7,compensation=-.05)
    raised_boost=expose(boost=4.,darken=2.7,compensation=-.05)
    summary['mixed_lit_room']={'exposure':room_exposure,'raised_boost_limit':raised_boost}
    check(room_exposure<1.,('lit room should darken, not boost',room_exposure,raised_boost))
    check(abs(room_exposure-raised_boost)<.001,'nonbinding brightening cap must not change the meter')

    # Most of this view is already normally lit: dark recesses must not cause
    # those surfaces to be washed out by another several stops of exposure.
    scene(lambda x,y:(.28,)*3 if x%4!=0 else (.0001,)*3)
    mostly_lit=[expose(boost=limit,darken=2.7,compensation=-.05) for limit in (1.3,4.)]
    check(.7<mostly_lit[0]<1. and abs(mostly_lit[0]-mostly_lit[1])<.001,
        ('mostly lit room with dark recesses',mostly_lit))
    summary['mostly_lit_room']={'exposure':mostly_lit[0],'raised_boost_limit':mostly_lit[1]}

    # Once a bright room really calls for darkening, the darkening cap must
    # constrain the final answer without influencing the scene measurement.
    scene(lambda x,y:(4.,)*3 if x%4==0 else (.005,)*3)
    darken_limits=[expose(boost=1.3,darken=limit,compensation=-.05) for limit in (0.,.5,2.7)]
    check(darken_limits[0]==1. and .70<darken_limits[1]<.71 and darken_limits[2]<.3,
        ('darkening limits on a mixed lit room',darken_limits))

    # Same lighting with more visible shadow should not trigger maximum boost.
    mixed=[]
    for divisor in (1,2,3,4):
        scene(lambda x,y:(.9,)*3 if x%divisor==0 else (.005,)*3)
        mixed.append(expose(boost=4.,darken=4.,compensation=-.05))
    check(all(a<b<1. for a,b in zip(mixed,mixed[1:])),('lit-area coverage',mixed))

    # An extreme isolated emitter should retain its area influence, without
    # its intensity overwhelming otherwise dark surroundings.
    sparse=[]
    for intensity in (4.,64.):
        scene(lambda x,y:(intensity,)*3 if x%16==0 and y%16==0 else (.015,)*3)
        sparse.append(expose(boost=4.,compensation=-.05))
    check(min(sparse)>3. and abs(sparse[0]-sparse[1])<.1,('sparse bright emitters',sparse))

    # EyeAd ignores the stock sky/diffuse coefficient and the separate glow texture.
    stats_a=uniform_scene(.1,glow=0,flag=.34,scale=.1)
    a=expose(stock=(.05,.01,16.,.9))
    stats_b=uniform_scene(.1,glow=10,flag=0.,scale=4.)
    b=expose(stock=(4.,1.,1.,.01))
    check(stats_a==stats_b and a==b,'stock environment/debug values must not drive EyeAd')

    # Stock off path: retain its diffuse scaling, emission and exact exposure curve.
    for value,flag,scale,glow in [(.1,.34,.5,0),(.1,0,.5,0),(.1,1,.5,0),
                                (.2,.79,.5,.01),(.6,.34,1.,0),(.01,.34,.5,.02)]:
        stats=uniform_scene(value,advanced=False,flag=flag,scale=scale,glow=glow)
        l=value*(1 if flag in (0,1) else scale)+glow
        check(abs(stats[0]-l)<.003,('stock meter',value,flag,stats,l))
        for history in [False,True]:
            actual=expose(advanced=False,history=history,prev=1.3,dt=.1)
            target=2-1.5*min(stats[0]/.5,1)**2
            expected=target if not history else 1.3+(target-1.3)*(1-math.exp(math.log(.1)*.1/2))
            check(abs(actual-expected)<.003,('stock exposure',history,actual,expected))

    # Time smoothing runs in EV; compare elapsed time, not frame count.
    def transition(value,start,seconds,fps,dark_time=2.,light_time=.6):
        nonlocal previous,output
        uniform_scene(value)
        gpu.upload_tex(previous,1,1,[start,0,0,1],0x822E)
        for _ in range(round(seconds*fps)):
            expose(history=True,prev=None,dt=1/fps,dark_time=dark_time,light_time=light_time)
            previous,output=output,previous
        return gpu.pixels(previous)[0]
    dark_results=[transition(.001,1.,2.,fps) for fps in (30,60,144)]
    light_results=[transition(16.,1.,.6,fps) for fps in (30,60,120)]
    check(max(dark_results)-min(dark_results)<.045,('frame-rate independence, dark',dark_results))
    check(max(light_results)-min(light_results)<.008,('frame-rate independence, light',light_results))
    check(all(abs(math.log2(v)-1.8)<.05 for v in dark_results),('90 percent dark adaptation',dark_results))
    check(all(abs(math.log2(v)+1.8)<.05 for v in light_results),('90 percent light adaptation',light_results))
    check(transition(.001,1.,.5,60,dark_time=.5)>transition(.001,1.,.5,60,dark_time=4.),'dark speed control')
    check(transition(16.,1.,.5,60,light_time=.2)<transition(16.,1.,.5,60,light_time=3.),'light speed control')
    summary['two_second_dark_transition']=dict(zip((30,60,144),dark_results))

    uniform_scene(.02)
    for prev in [0.,-1.,float('nan'),float('inf'),16.]:
        for dt in [0.,.016,10.,float('nan')]:
            value=expose(history=True,prev=prev,dt=dt)
            check(math.isfinite(value) and .25<=value<=4.,('history recovery',prev,dt,value))
    check(expose(history=True,prev=1.,dt=30)<2.,'resuming after a stall must not jump to maximum')

    # Compile and execute the actual presentation shader's stock, HDR and
    # legacy gamma variants. EyeAd selects an existing non-NO_POST variant.
    util=shader('tonemapUtilF.glsl').replace('in vec2 vary_fragcoord;','')
    srgb=(SHADERS/'class1/environment/srgbF.glsl').read_text()
    presentation=gpu.tex(8,1)
    colors=[v for l in (.001,.01,.04,.1,.5,1.,4.,16.) for v in (l,l*.8,l*.6,1)]
    color_tex=gpu.tex(8,1,colors)
    input_pixels=gpu.pixels(color_tex,8,1)
    gpu.upload_tex(previous,1,1,[2,0,0,1],0x822E)

    def present(prog,advanced,amount,scale=1.):
        gpu.upload_tex(previous,1,1,[scale,0,0,1],0x822E)
        gpu.bind(prog,'diffuseRect',0,color_tex)
        gpu.bind(prog,'exposureMap',1,previous)
        gpu.uniform(prog,'eye_adaptation',int(advanced),integer=True)
        gpu.uniform(prog,'tonemap_mix',amount)
        gpu.render(prog,presentation,8,1)
        return gpu.pixels(presentation,8,1)

    for defines in ['', '#define GAMMA_CORRECT 1\n',
                    '#define GAMMA_CORRECT 1\n#define LEGACY_GAMMA 1\n',
                    '#define NO_POST 1\n',
                    '#define NO_POST 1\n#define GAMMA_CORRECT 1\n',
                    '#define NO_POST 1\n#define GAMMA_CORRECT 1\n#define LEGACY_GAMMA 1\n']:
        prog=gpu.program(defines+shader('postDeferredTonemap.glsl')+util+srgb,VERTEX)
        for kind in (0,1):
            gpu.bind(prog,'diffuseRect',0,color_tex);gpu.bind(prog,'exposureMap',1,previous)
            gpu.uniform(prog,'exposure',1.)
            gpu.uniform(prog,'tonemap_type',kind,integer=True)
            gpu.uniform(prog,'tonemap_mix',1.)
            gpu.uniform(prog,'gamma',1.)
            pixels=present(prog,False,1.,2.)
            check(all(math.isfinite(x) and 0<=x<=1 for x in pixels),'finite tonemapped output')
            if 'NO_POST' not in defines:
                check(pixels[6*4]<pixels[7*4],('highlight gradation',defines,kind,pixels))
            else:
                # Artist no-post path must not apply the 2x exposure map.
                expected=.1 if 'GAMMA_CORRECT' not in defines else 1.055*.1**(1/2.4)-.055
                check(abs(pixels[3*4]-expected)<.002,'no-post snapshot/editor bypass')

            # Enabling EyeAd at unchanged exposure must not deepen shadows or
            # add contrast, whether the environment has no, partial or full tone mapping.
            for amount in (0.,.35,1.):
                stock=present(prog,False,amount)
                adapted=present(prog,True,amount)
                check(stock[:5*4]==adapted[:5*4],('shadow/midtone preservation',defines,kind,amount))
                if amount==1. or 'NO_POST' in defines:
                    check(stock==adapted,('preserve full artist curve/no-post',defines,kind))
                elif 'NO_POST' not in defines:
                    check(adapted[5*4]<adapted[6*4]<adapted[7*4]<1.,
                        ('smooth highlight gradation',defines,kind,amount,adapted))
                # A material preview/disabled call after an EyeAd call must use stock output.
                check(present(prog,False,amount)==stock,('toggle off',defines,kind,amount))

            if not defines:
                boosted=present(prog,True,0.,4.)
                check(all(abs(boosted[i]-4*input_pixels[i])<.0003
                    for pixel in range(4) for i in range(pixel*4,pixel*4+3)),
                    ('fourfold boost retains shadow detail',kind,boosted))
                # The shoulder must scale RGB together, not clip/desaturate colored lights.
                check(all(abs(boosted[pixel*4+c]/boosted[pixel*4]-
                    input_pixels[pixel*4+c]/input_pixels[pixel*4])<.002
                    for pixel in range(4,8) for c in (1,2)),('highlight hue',kind))
                if kind==1:
                    forced=present(prog,False,1.,4.)
                    summary['shadow_at_fourfold_exposure']={
                        'input':input_pixels[4], 'previous_forced_aces':forced[4],
                        'environment_curve_preserved':boosted[4]}

    # A dense ramp across the shoulder knee catches discontinuities or a
    # contrast kink that a few HDR swatches would miss. Exercise the real shader.
    ramp_values=[.76+i*.001 for i in range(81)]
    width=len(ramp_values)
    ramp_source=gpu.tex(width,1,[v for value in ramp_values for v in (value,value,value,1)])
    ramp_target=gpu.tex(width,1,internal=0x8814)  # read the slope without output half-float quantization
    prog=gpu.program(shader('postDeferredTonemap.glsl')+util+srgb,VERTEX)
    gpu.upload_tex(previous,1,1,[1,0,0,1],0x822E)
    gpu.bind(prog,'diffuseRect',0,ramp_source);gpu.bind(prog,'exposureMap',1,previous)
    gpu.uniform(prog,'exposure',1.)
    gpu.uniform(prog,'tonemap_mix',0.)
    gpu.uniform(prog,'eye_adaptation',1,integer=True)
    gpu.render(prog,ramp_target,width,1)
    ramp_in=gpu.pixels(ramp_source,width,1)[::4]
    ramp_out=gpu.pixels(ramp_target,width,1)[::4]
    check(all(abs(a-b)<.000001 for a,b in zip(ramp_in,ramp_out) if a<=.8),
        'identity below the shoulder knee')
    slopes=[(b-a)/(y-x) for x,y,a,b in zip(ramp_in,ramp_in[1:],ramp_out,ramp_out[1:])]
    check(all(0<s<=1.001 for s in slopes),'shoulder must be monotonic without increasing contrast')
    check(max(abs(b-a) for a,b in zip(slopes,slopes[1:]))<.015,'smooth slope at the knee')

    summary['checks']=cases
    summary['gpu']=gl.GetString(0x1F01).decode()
    path=ROOT/'tmp/eye-adaptation-gpu-results.json'
    path.write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))
    print(f'PASS: {cases} EyeAd and stock GPU checks.')


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try: run(sdl,gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
