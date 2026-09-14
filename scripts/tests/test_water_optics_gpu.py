"""Production water receiver lighting, segment transport and depth refraction.
Analytic scene intersections/Beer-Lambert references; hidden GL, no login.
Run: .venv/Scripts/python.exe scripts/tests/test_water_optics_gpu.py
"""
import math
from pathlib import Path
from test_eye_adaptation_gpu import EyeGPU
from test_taa_gpu import context
from test_water_gpu import function, combine, FIXTURES, VERTEX
from test_gtao_gpu import inverse

ROOT=Path(__file__).resolve().parents[2]
SH=ROOT/'indra/newview/app_settings/shaders'


def run(sdl,gl):
    gpu=EyeGPU(sdl,gl); count=0
    def check(ok,label):
        nonlocal count
        assert ok,label
        count+=1
    def near(a,b,tol=3e-5): return all(abs(x-y)<tol for x,y in zip(a,b))
    def normalize(v):
        length=math.sqrt(sum(x*x for x in v)); return [x/length for x in v]
    def linear(x): return x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4
    def srgb(x): return x*12.92 if x<=.0031308 else 1.055*x**(1/2.4)-.055
    fog=(SH/'class1/environment/waterFogF.glsl').read_text()
    colors=function((SH/'class1/environment/srgbF.glsl').read_text(),'vec3 srgb_to_linear(')
    source=colors+fog+FIXTURES
    output=gpu.tex(1,1,internal=0x8814)
    mask=gpu.tex(1,1,[1,1,1,1])
    def medium(p,density=2):
        gpu.uniform(p,'waterPlane',0,0,1,2)
        gpu.uniform(p,'waterFogDensity',density)
        gpu.uniform(p,'waterAbsorptionColor',.02,.2,.4)
        gpu.uniform(p,'waterScatteringColor',.02,.08,.12)
        gpu.uniform(p,'waterFogLightDir',0,0,1)
        gpu.uniform(p,'waterFogSkyColor',1,1,1)
        gpu.uniform(p,'waterFogSunColor',1,1,1)
    def render(p):
        gpu.render(p,output); result=gpu.pixels(output)
        check(all(math.isfinite(x) for x in result),'finite optical result')
        return result[:3]
    lighting=gpu.program(source+'''
        uniform vec3 fixture_point, fixture_light, fixture_color;
        uniform int fixture_sky, fixture_classic;
        out vec4 frag_color;
        void main(){frag_color=vec4(fixture_sky != 0 ?
            waterLitAmbient(fixture_point,fixture_color,fixture_classic) :
            waterLitSun(fixture_point,fixture_light,fixture_color,fixture_classic),1);}
    ''')
    sigma=[2*.020202707*(1+2*(1-c/.4)) for c in (.02,.2,.4)]
    medium(lighting)
    gpu.uniform(lighting,'water_lighting_enabled',1,integer=True)
    for classic in (0,1):
        gpu.uniform(lighting,'fixture_classic',classic,integer=True)
        for sky in (0,1):
            gpu.uniform(lighting,'fixture_sky',sky,integer=True)
            for light in ((0,0,1),(.8,0,.6),(1,0,0)):
                gpu.uniform(lighting,'fixture_light',*light)
                for depth in (-2,0,.1,3,20):
                    gpu.uniform(lighting,'fixture_point',0,0,-2-depth)
                    color=[2,1,.5];gpu.uniform(lighting,'fixture_color',*color)
                    gpu.bind(lighting,'exclusionTex',0,mask)
                    result=render(lighting)
                    mu=math.sqrt(1-(1/1.333)**2*(1-light[2]**2))
                    transmission=[math.exp(-s*max(depth,0)*(1.2 if sky else 1/mu)) for s in sigma]
                    expected=[srgb(linear(c)*t) if classic else c*t for c,t in zip(color,transmission)]
                    check(near(result,expected),'incoming sunlight/sky agrees with Beer-Lambert, including Classic HDR')
                    if depth<=0: check(result==color,'above-water and boundary lighting stays unchanged')
    gpu.uniform(lighting,'fixture_point',0,0,-20)
    for enabled,excluded in ((0,False),(1,True)):
        gpu.uniform(lighting,'water_lighting_enabled',enabled,integer=True)
        gpu.upload_tex(mask,1,1,[0 if excluded else 1]*4)
        gpu.bind(lighting,'exclusionTex',0,mask)
        check(render(lighting)==[2,1,.5],'disabled lighting/exclusion preserves HDR illumination')
    gpu.upload_tex(mask,1,1,[1]*4)

    segment=gpu.program(source+'''
        uniform vec3 fixture_start, fixture_point;
        uniform int fixture_mode;
        out vec4 frag_color;
        void main(){vec3 t,s;getWaterFogSegment(fixture_start,fixture_point,t,s);
            frag_color=vec4(fixture_mode==0?t:s,1);}
    ''')
    medium(segment)
    gpu.uniform(segment,'fixture_mode',0,integer=True)
    for start,end,length in (((0,0,0),(0,0,-12),10),((0,0,-2),(6,0,-10),10),
                             ((0,0,-12),(0,0,5),10),((0,0,-5),(4,0,-8),5)):
        gpu.uniform(segment,'fixture_start',*start);gpu.uniform(segment,'fixture_point',*end)
        check(near(render(segment),[math.exp(-s*length) for s in sigma]),'arbitrary segment clips only water distance')
    gpu.uniform(segment,'fixture_start',0,0,-2);gpu.uniform(segment,'fixture_point',0,0,-12)
    reference=render(segment)
    gpu.uniform(segment,'waterScatteringColor',.8,.1,.02)
    check(near(render(segment),reference),'scattered light tint does not recolour transmission')
    gpu.uniform(segment,'waterFogDensity',1)
    check(near(render(segment),[math.sqrt(x) for x in reference]),'doubling clarity doubles visibility distance')
    gpu.uniform(segment,'fixture_mode',1,integer=True)
    warm=render(segment)
    gpu.uniform(segment,'waterScatteringColor',.02,.1,.8)
    cool=render(segment)
    check(warm[0]>cool[0]*20 and cool[2]>warm[2]*20,'scattering colour has an independent visible response')

    # Compose a raw receiver through the old path, then compare its corrected
    # result with direct integration along the bent path. Never fog twice.
    correction=gpu.program(source+'''
        uniform vec3 fixture_start, fixture_point, fixture_color;
        uniform int fixture_reference;
        out vec4 frag_color;
        void main(){vec3 t,s;getWaterFogTransport(fixture_point,t,s);
            vec3 old_color=fixture_color*t+s;
            getWaterFogSegment(fixture_start,fixture_point,t,s);
            frag_color=vec4(fixture_reference != 0 ? fixture_color*t+s :
                waterRefractTransport(old_color,fixture_start,fixture_point),1);}
    ''')
    medium(correction)
    for start,end in (((0,0,-2),(3,0,-7)),((2,0,-2),(1,0,-5)),((0,0,-2),(0,0,-12))):
        gpu.uniform(correction,'fixture_start',*start);gpu.uniform(correction,'fixture_point',*end)
        gpu.uniform(correction,'fixture_color',3,2,1)
        gpu.uniform(correction,'fixture_reference',0,integer=True);actual=render(correction)
        gpu.uniform(correction,'fixture_reference',1,integer=True);expected=render(correction)
        check(near(actual,expected),'refracted transport matches direct integration without double haze')
    gpu.uniform(correction,'fixture_reference',0,integer=True)
    gpu.uniform(correction,'fixture_point',100,0,-1000)
    check(all(0<=x<4 for x in render(correction)),'opaque deep water never amplifies missing detail')

    water=combine((SH/'class1/environment/waterWavesF.glsl').read_text(),
                  (SH/'class3/environment/waterF.glsl').read_text())
    util=(SH/'class1/deferred/deferredUtil.glsl').read_text()
    depth_helpers='uniform mat4 inv_proj;\n'+function(util,'vec3 getPositionWithNDC(')
    trace=gpu.program(combine('#define TRANSPARENT_WATER 1\n',source,depth_helpers,
        water.replace('void main()', 'void waterMain()'))+'''
        uniform vec3 fixture_point, fixture_normal;
        uniform float fixture_depth, fixture_mask;
        void main(){frag_color=waterRefractedScene(fixture_point,fixture_normal,vec2(.5),fixture_mask,fixture_depth);}
    ''',VERTEX)
    projection=[[1,0,0,0],[0,1,0,0],[0,0,-1.020202,-2.020202],[0,0,-1,0]]
    gpu.matrix(trace,'inv_proj',inverse(projection));gpu.matrix(trace,'projection_matrix',projection)
    gradient=gpu.tex(512,512,[v for y in range(512) for x in range(512) for v in ((x+.5)/512,)*3+(1,)],internal=0x8814)
    depth_tex=gpu.tex(1,1);mask=gpu.tex(1,1,[1]*4)
    medium(trace);gpu.uniform(trace,'refScale',.03);gpu.uniform(trace,'water_refraction_strength',1)
    gpu.uniform(trace,'fixture_point',0,0,-2)
    gpu.uniform(trace,'fixture_mask',1)
    def trace_result(z,normal):
        gpu.upload_tex(depth_tex,1,1,[(1.020202+2.020202/z)*.5+.5]*3+[1],internal=0x8814)
        gpu.bind(trace,'depthMap',0,depth_tex);gpu.bind(trace,'screenTex',1,gradient);gpu.bind(trace,'exclusionTex',2,mask)
        gpu.uniform(trace,'fixture_normal',*normal);gpu.uniform(trace,'fixture_depth',-z-2)
        return render(trace)
    for z in (-3,-8,-20):
        for slope in (0,.15,.5):
            n=normalize([slope,0,1]);eta=1/1.333;d=-n[2]
            root=math.sqrt(1-eta*eta*(1-d*d))
            ray=[-(eta*d+root)*n[0],0,-eta-(eta*d+root)*n[2]]
            hit_x=ray[0]*(z+2)/ray[2]
            expected=.5+max(-20/1080,min(20/1080,.5*hit_x/-z))
            check(near(trace_result(z,n),[expected]*3,.0005),'normal-incidence wave refraction agrees with Snell, within the screen displacement budget')
    # A flat surface must not lift the scene at oblique camera angles.
    for plane in ((0,1,0,1),(0,.8,.6,1.2)):
        gpu.uniform(trace,'waterPlane',*plane)
        gpu.uniform(trace,'fixture_point',0,0,-2)
        check(near(trace_result(-8,plane[:3]),[.5]*3,.0005),
              'flat-interface registration remains unchanged at oblique angles')
    gpu.uniform(trace,'waterPlane',0,0,1,2)
    # Mid-confidence must warp one coordinate, not blend two distant colours.
    stripes=gpu.tex(512,512,[v for y in range(512) for x in range(512)
        for v in ((1 if x%8<4 else 0),)*3+(1,)],internal=0x8814)
    gl.BindTexture(0x0DE1,stripes);gl.TexParameteri(0x0DE1,0x2801,0x2600);gl.TexParameteri(0x0DE1,0x2800,0x2600)
    gpu.uniform(trace,'fixture_mask',.5)
    gpu.upload_tex(depth_tex,1,1,[(1.020202-2.020202/8)*.5+.5]*3+[1],internal=0x8814)
    gpu.bind(trace,'depthMap',0,depth_tex);gpu.bind(trace,'screenTex',1,stripes);gpu.bind(trace,'exclusionTex',2,mask)
    gpu.uniform(trace,'fixture_depth',6);gpu.uniform(trace,'fixture_normal',.2,0,math.sqrt(.96))
    check(render(trace)[0] in (0,1),'partial strength never blends a ghost of the original image')
    gpu.uniform(trace,'fixture_mask',1)

    # Generate an already-fogged scene exactly as the pre-water haze pass does,
    # then exercise correction through the complete refraction helper.
    scene_program=gpu.program(source+'''
        out vec4 frag_color;
        void main(){vec2 uv=gl_FragCoord.xy/128.0;
            vec3 p=vec3((uv*2.0-1.0)*8.0,-8.0);
            frag_color=applyWaterFogViewLinear(p,vec4(.6,.4,.2,1));}
    ''')
    medium(scene_program)
    fogged=gpu.tex(128,128);gpu.render(scene_program,fogged,128,128)
    n=normalize([.5,0,1]);dot=-n[2]
    ray=[-(eta*dot+math.sqrt(1-eta*eta*(1-dot*dot)))*n[0],0,
         -eta-(eta*dot+math.sqrt(1-eta*eta*(1-dot*dot)))*n[2]]
    gpu.uniform(trace,'fixture_normal',*n);gpu.uniform(trace,'fixture_depth',6)
    gpu.uniform(trace,'water_refraction_fog',1,integer=True)
    gpu.upload_tex(depth_tex,1,1,[(1.020202-2.020202/8)*.5+.5]*3+[1],internal=0x8814)
    gpu.bind(trace,'depthMap',0,depth_tex)
    gpu.bind(trace,'screenTex',1,fogged)
    gpu.bind(trace,'exclusionTex',2,mask)
    actual=render(trace)
    gpu.uniform(correction,'fixture_start',0,0,-2)
    gpu.uniform(correction,'fixture_point',max(-40/1080*8,min(40/1080*8,ray[0]*-6/ray[2])),0,-8)
    gpu.uniform(correction,'fixture_color',.6,.4,.2)
    gpu.uniform(correction,'fixture_reference',1,integer=True)
    check(near(actual,render(correction),.001),'full refraction applies bent-path colour without double fog')
    gpu.uniform(trace,'water_refraction_fog',0,integer=True)
    gpu.uniform(trace,'water_refraction_strength',0)
    check(near(trace_result(-8,normalize([.5,0,1])),[.5]*3),'zero refraction is an exact visual fallback')
    gpu.uniform(trace,'water_refraction_strength',1)
    gpu.upload_tex(mask,1,1,[0]*4)
    check(near(trace_result(-8,normalize([.5,0,1])),[.5]*3),'exclusion cannot supply refracted colour')
    gpu.upload_tex(mask,1,1,[1]*4)
    for z in (-1,):
        check(near(trace_result(z,normalize([.5,0,1])),[.5]*3),'foreground ray uses safe fallback')
    gpu.uniform(trace,'cube_snapshot',1,integer=True)
    check(near(trace_result(-8,normalize([.5,0,1])),[.5]*3),'probe capture does not reuse screen refraction')
    print(f'Passed {count} depth/refraction/receiver-lighting GPU checks on {gl.GetString(0x1F01).decode()}')


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try:run(sdl,gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx);sdl.SDL_DestroyWindow(window);sdl.SDL_Quit()
