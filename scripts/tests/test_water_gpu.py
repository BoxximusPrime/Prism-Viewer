"""Run production water/fog shaders on a hidden OpenGL context (no login).
Tests optical transport, HDR, exclusion, refraction rejection and shader variants.
Atmosphere/probe inputs are controlled fixtures; this is not an in-world visual test.
Run: .venv/Scripts/python.exe scripts/tests/test_water_gpu.py
"""
import math
import re
from pathlib import Path
from test_eye_adaptation_gpu import EyeGPU
from test_taa_gpu import context

ROOT = Path(__file__).resolve().parents[2]
SHADERS = ROOT / 'indra/newview/app_settings/shaders'

def function(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    level = 1
    end = brace + 1
    while level:
        level += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]

def combine(*parts):
    # Production links utility shader objects; this harness concatenates them.
    seen = set()
    def uniform(match):
        line = match.group(0)
        if line in seen:
            return ''
        seen.add(line)
        return line
    return re.sub(r'^uniform [^;]+;', uniform, '\n'.join(parts), flags=re.M)

VERTEX = """
uniform vec3 fixture_point;
uniform vec3 fixture_light;
out vec4 refCoord, littleWave, view;
out vec3 vary_position, vary_normal, vary_tangent, vary_light_dir;
out vec2 water_position;
out vec2 crossingWave;
void main() {
    vec2 p[3] = vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
    gl_Position = vec4(p[gl_VertexID],0,1);
    refCoord = vec4(p[gl_VertexID],1,0);
    littleWave = vec4(0); view = vec4(0);
    water_position = vec2(0);
    crossingWave = vec2(0);
    vary_position = fixture_point;
    vary_normal = vec3(0,0,1); vary_tangent = vec3(1,0,0);
    vary_light_dir = fixture_light;
}
"""
HAZE_VERTEX = """
out vec4 vary_fragcoord;
void main() {
    vec2 p[3] = vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
    gl_Position = vec4(p[gl_VertexID],0,1); vary_fragcoord = gl_Position;
}
"""
FIXTURES = """
uniform vec3 fixture_sun, fixture_probe;
uniform float fixture_shadow;
uniform int fixture_probe_glossiness;
void mirrorClip(vec3 p) {}
vec3 atmosFragLighting(vec3 c, vec3 a, vec3 t) { return c*t+a; }
void calcAtmosphericVarsLinear(vec3 p, vec3 n, vec3 l,
    out vec3 s, out vec3 a, out vec3 add, out vec3 t) {
    s=fixture_sun; a=vec3(0); add=vec3(0); t=vec3(1);
}
void sampleReflectionProbesWater(inout vec3 a, inout vec3 r,
    vec2 tc, vec3 p, vec3 n, float g, vec3 amb) {
    r=fixture_probe_glossiness != 0 ? vec3(g) : fixture_probe;
}
float sampleDirectionalShadow(vec3 p, vec3 n, vec2 tc) { return fixture_shadow; }
"""

def run(sdl, gl):
    gpu = EyeGPU(sdl, gl)
    read = lambda p: (SHADERS / p).read_text()
    srgb = function(read('class1/environment/srgbF.glsl'), 'vec3 srgb_to_linear(')
    fog = read('class1/environment/waterFogF.glsl')
    water = combine(read('class1/environment/waterWavesF.glsl'), read('class3/environment/waterF.glsl'))
    util = read('class1/deferred/deferredUtil.glsl')
    optical = srgb + fog + FIXTURES
    depth_brdf = ('uniform mat4 inv_proj; uniform sampler2D brdfLut;\n' +
        function(util, 'vec3 getPositionWithNDC(') + function(util, 'vec2 BRDF('))
    # Keep quadrature comparisons independent of half-float target quantization.
    output = gpu.tex(1,1,internal=0x8814)
    bindings = {}
    bind = gpu.bind
    def remember_binding(program, name, unit, tex):
        bindings.setdefault(program, {})[name] = (unit, tex)
        bind(program, name, unit, tex)
    gpu.bind = remember_binding
    count = 0
    def check(ok, label):
        nonlocal count
        assert ok, label
        count += 1
    def render(program):
        for name, (unit, tex) in bindings.get(program, {}).items():
            bind(program, name, unit, tex)
        gpu.render(program, output)
        result = gpu.pixels(output)
        check(all(math.isfinite(v) for v in result), 'finite output')
        return result
    def near(a,b,tol=.002):
        return all(abs(x-y)<tol for x,y in zip(a,b))
    def medium(program, plane=(0,0,1,2), density=2, tint=(.0156,.149,.2509,1)):
        gpu.uniform(program,'waterPlane',*plane)
        gpu.uniform(program,'waterFogDensity',density)
        gpu.uniform(program,'waterFogColor',*tint)
        linear_tint=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in tint[:3]]
        gpu.uniform(program,'waterAbsorptionColor',*linear_tint)
        gpu.uniform(program,'waterScatteringColor',*linear_tint)
        gpu.uniform(program,'waterFogKS',1)
        gpu.uniform(program,'waterFogSunColor',0,0,0)
        gpu.uniform(program,'waterFogSkyColor',1,1,1)
        gpu.uniform(program,'waterFogLightDir',0,0,1)
    transport = gpu.program(optical + """
        uniform vec3 fixture_point; uniform int mode;
        out vec4 frag_color;
        void main() {
            vec3 t,s; getWaterFogTransport(fixture_point,t,s);
            frag_color=vec4(mode==0?t:s,1);
        }""")
    def sample(point, plane=(0,0,1,2), density=2, mode=0, tint=(.0156,.149,.2509,1)):
        medium(transport,plane,density,tint)
        gpu.uniform(transport,'fixture_point',*point)
        gpu.uniform(transport,'mode',mode,integer=True)
        return render(transport)[:3]
    check(near(sample((0,0,-2)),(1,1,1)), 'zero water thickness is clear')
    check(near(sample((0,0,-100),density=0),(1,1,1)), 'zero density is clear')
    check(near(sample((0,0,-1)),(1,1,1)), 'above-water ray is clear')
    previous = [1]*3
    for depth in (0.01,.1,1,5,20,100,1000):
        t=sample((0,0,-2-depth))
        check(all(0<=x<=y+.001 for x,y in zip(t,previous)), 'monotonic attenuation')
        check(t[0]<=t[1]<=t[2], 'blue preset absorbs red first')
        previous=t
    for tint in ((0,0,0,1),(1,1,1,1),(.8,.2,.1,1)):
        for density in (0,.001,2,100):
            for point in ((0,0,0),(0,0,-2),(1000,0,-2),(0,0,-10000)):
                for mode in (0,1):
                    check(all(0<=x<=1 for x in sample(point,density=density,mode=mode,tint=tint)), 'bounded transport')
    # Equal submerged path lengths, independent of the air segment and ray direction.
    reference=sample((0,0,-12))
    check(near(reference,sample((0,0,-110),plane=(0,0,1,100))), 'air distance does not absorb')
    check(near(reference,sample((0,0,20),plane=(0,0,1,-10))), 'underwater exit clips path')
    check(near(reference,sample((0,0,-10),plane=(0,0,1,-10))), 'fully submerged path')

    # Compare the analytic lighting integral with independent numerical ray
    # integration, including horizontal, downward and upward water segments.
    integral = gpu.program(optical + '''
        uniform vec4 fixture_segment;
        out vec4 frag_color;
        void main() {
            frag_color=vec4(waterLitIntegral(vec3(.08,.12,.2),fixture_segment.x,
                fixture_segment.y,fixture_segment.z,fixture_segment.w),1);
        }
    ''')
    for length,d0,d1,q in ((0,0,0,1.2),(20,0,10,1.1),(10,5,5,1.2),
                           (12,10,0,1.2),(12.0001,10,0,1.2),(20,10,0,1.5),(1000,100,800,1.2)):
        gpu.uniform(integral,'fixture_segment',length,d0,d1,q)
        steps=4096
        expected=[sum(sigma*length/steps*math.exp(-sigma*(length*(i+.5)/steps+
            q*(d0+(d1-d0)*(i+.5)/steps))) for i in range(steps)) for sigma in (.08,.12,.2)]
        actual=render(integral)[:3]
        check(near(actual,expected,1e-5), f'lit integral agrees with numerical ray integration: {actual} vs {expected}')

    def lit(sky=(0,0,0),sun=(0,0,0),direction=(0,0,1),point=(0,0,-12),plane=(0,0,1,2),mode=1):
        medium(transport,plane,tint=(.5,.5,.5,1))
        for name,value in (('waterFogSkyColor',sky),('waterFogSunColor',sun),
                           ('waterFogLightDir',direction),('fixture_point',point)):
            gpu.uniform(transport,name,*value)
        gpu.uniform(transport,'mode',mode,integer=True)
        return render(transport)[:3]
    check(near(lit(),(0,0,0)), 'unlit water does not glow')
    check(near(lit(sky=(5,4,3),sun=(8,7,6),point=(0,0,-2)),(0,0,0)), 'lighting preserves clear zero-length ray')
    sky=lit(sky=(1,1,1));sun=lit(sun=(1,1,1))
    check(all(v>0 for v in sky+sun), 'sky and sun independently illuminate the medium')
    check(near(lit(sky=(1,1,1),sun=(1,1,1)),[a+b for a,b in zip(sky,sun)]), 'sun and sky add in linear space')
    check(near(lit(sky=(2,2,2)),[2*v for v in sky]), 'sky intensity scales scattering')
    check(near(lit(sun=(2,2,2)),[2*v for v in sun]), 'sun intensity scales scattering')
    check(near(lit(sky=(1,.5,.1)),[v*s for v,s in zip(sky,(1,.5,.1))]), 'sky colour reaches the water body')
    check(near(lit(sun=(.1,.5,1)),[v*s for v,s in zip(sun,(.1,.5,1))]), 'sun or moon colour reaches the water body')
    check(near(lit(mode=0),lit(sky=(50,30,10),sun=(90,60,30),mode=0)), 'lighting never changes absorption')
    check(max(lit(sun=(100,100,100)))>1, 'body lighting preserves HDR energy')
    check(near(lit(sun=(1,1,1),direction=(1,0,0)),(0,0,0)), 'grazing incidence admits no direct flux')
    check(near(lit(sun=(1,1,1),direction=(0,0,-1)),(0,0,0)), 'light below water horizon contributes no direct flux')
    a=lit(sky=(1,1,1),sun=(1,1,1),point=(10,0,0),plane=(0,0,1,-1))
    b=lit(sky=(1,1,1),sun=(1,1,1),point=(10,0,0),plane=(0,0,1,-20))
    check(all(x>y for x,y in zip(a,b)), 'incoming light dims with depth at fixed viewing distance')
    a=lit(sun=(1,1,1),direction=(.8,0,.6),point=(20,0,-12))
    b=lit(sun=(1,1,1),direction=(.8,0,.6),point=(-20,0,-12))
    check(all(x>y for x,y in zip(a,b)), 'body scattering brightens toward the light')
    check(near(a,lit(sun=(1,1,1),direction=(.8,.6,0),point=(20,-12,0),plane=(0,1,0,2))),
          'view-space rotation preserves water lighting')

    # Deferred composition must match forward transparent-object fog exactly.
    haze_fixture = """
        uniform vec3 fixture_point; uniform float fixture_depth;
        vec4 getPositionWithDepth(vec2 uv,float d) { return vec4(fixture_point,1); }
        float getDepth(vec2 uv) { return fixture_depth; }
    """
    haze = gpu.program(combine(optical,haze_fixture,read('class3/deferred/waterHazeF.glsl')), HAZE_VERTEX)
    gpu.program(combine(optical,haze_fixture,read('class3/deferred/waterHazeF.glsl')),
        read('class3/deferred/waterHazeV.glsl') +
        '\nvoid setAtmosAttenuation(vec3 c) {}\nvoid setAdditiveColor(vec3 c) {}')
    forward = gpu.program(optical + """
        uniform vec3 fixture_point; uniform vec4 fixture_color;
        out vec4 frag_color;
        void main() { frag_color=applyWaterFogViewLinear(fixture_point,fixture_color); }
    """)
    scene=gpu.tex(1,1,[4,2,1,.4]); mask=gpu.tex(1,1,[1,1,1,1])
    gpu.bind(haze,'screenTex',0,scene); gpu.bind(haze,'exclusionTex',1,mask)
    gpu.uniform(haze,'above_water',1,integer=True); gpu.uniform(haze,'fixture_depth',.8)
    for point in ((0,0,-2),(0,0,-3),(0,0,-12),(0,0,-100)):
        for p in (haze,forward):
            medium(p); gpu.uniform(p,'fixture_point',*point)
        gpu.uniform(forward,'fixture_color',4,2,1,.4)
        check(near(render(haze)[:3],render(forward)[:3]), 'deferred/forward optical agreement')
    gpu.upload_tex(mask,1,1,[0]*4)
    gpu.upload_tex(output,1,1,[.7,.6,.5,.4],internal=0x8814)
    check(near(render(haze),[.7,.6,.5,.4]), 'haze exclusion preserves scene')
    gpu.upload_tex(mask,1,1,[1]*4)

    # Compile complete surface variants, including production vertex shader.
    programs=[]
    for transparent in (False,True):
        for shadows in (False,True):
            defines=('#define TRANSPARENT_WATER 1\n' if transparent else '') + ('#define HAS_SUN_SHADOW 1\n' if shadows else '')
            source=combine(defines,optical,depth_brdf,water)
            programs.append(gpu.program(source,VERTEX))
            gpu.program(source,combine(read('class1/environment/waterV.glsl'), read('class1/environment/waterDisplacementV.glsl'))+'\nvoid calcAtmospherics(vec3 p) {}')
            check(True,'water vertex/fragment variant links')
        gpu.program(combine('#define TRANSPARENT_WATER 1\n' if transparent else '',
            optical,read('class1/environment/waterWavesF.glsl'),read('class3/environment/underWaterF.glsl')),
            combine(read('class1/environment/waterV.glsl'), read('class1/environment/waterDisplacementV.glsl'))+'\nvoid calcAtmospherics(vec3 p) {}')
        check(True,'underwater variant links')
    # A controlled LUT separates integration from the independent BRDF checks.
    lut=gpu.tex(1,1,[1,0,0,1]); normal=gpu.tex(1,1,[.5,.5,1,1])
    depth=gpu.tex(1,1,[.9,.9,.9,1])
    gpu.upload_tex(scene,1,1,[.5,.5,.5,.4])
    p=programs[-1]
    for unit,(name,tex) in enumerate((('screenTex',scene),('depthMap',depth),('exclusionTex',mask),('bumpMap',normal),('brdfLut',lut))):
        gpu.bind(p,name,unit,tex)
    # Standard finite perspective; z=.9 is behind the test surface at z=-2.
    from test_gtao_gpu import inverse
    projection=[[1,0,0,0],[0,1,0,0],[0,0,-1.020202,-2.020202],[0,0,-1,0]]
    gpu.matrix(p,'inv_proj',inverse(projection))
    gpu.matrix(p,'projection_matrix',projection)
    medium(p)
    for name,values in dict(fixture_point=(0,0,-2),fixture_light=(0,0,1),fixture_probe=(1,1,1),fixture_sun=(0,0,0),normScale=(2,2,2)).items():
        gpu.uniform(p,name,*values)
    for name,value in dict(blend_factor=0,blurMultiplier=.08,refScale=.03,fresnelOffset=.5,fresnelScale=.3999,fixture_shadow=1,water_reflection_strength=1,water_roughness_scale=1,water_wave_scale=1,water_refraction_strength=1).items():
        gpu.uniform(p,name,value)
    check(near(render(p)[:3],[.510185]*3), 'dielectric reflection/transmission energy split')
    gpu.uniform(p,'fixture_sun',1,1,1)
    bright=render(p)
    check(min(bright[:3])>1 and bright[3]==0,'HDR sun glint with no authored emission')
    gpu.uniform(p,'water_reflection_strength',0)
    check(near(render(p)[:3],[.5]*3), 'zero reflection strength removes probe reflections and sun glints')
    gpu.uniform(p,'water_reflection_strength',.5)
    check(near(render(p)[:3],[.5+(v-.5)*.5 for v in bright[:3]]), 'reflection control preserves complementary transmission')
    gpu.uniform(p,'water_reflection_strength',1)
    gpu.uniform(p,'fixture_shadow',0)
    check(near(render(p)[:3],[.510185]*3),'sun shadow removes direct glint')
    gpu.uniform(p,'fixture_shadow',1); gpu.uniform(p,'fixture_light',0,0,-1)
    check(near(render(p)[:3],[.510185]*3),'below-surface light does not leak')
    gpu.upload_tex(mask,1,1,[0]*4)
    check(near(render(p)[:3],[.5]*3),'surface exclusion preserves scene')
    gpu.upload_tex(mask,1,1,[1]*4)
    gpu.uniform(p,'fixture_light',0,0,1)
    for roughness in (-1,0,.04,.5,1,4):
        gpu.uniform(p,'blurMultiplier',roughness)
        check(all(x>=0 for x in render(p)),'roughness extremes remain finite and positive')
    # Recover the glossiness passed to reflection probes from the full shader.
    # This catches a disconnected UI uniform or roughness lost in composition.
    gpu.uniform(p,'fixture_sun',0,0,0)
    gpu.uniform(p,'fixture_probe_glossiness',1,integer=True)
    for preset in (0,.08,.3):
        gpu.uniform(p,'blurMultiplier',preset)
        gloss=[]
        for scale in (.25,1,2,3):
            gpu.uniform(p,'water_roughness_scale',scale)
            gloss.append((render(p)[0]-.5*(1-.02037))/.02037)
        check(all(a>b for a,b in zip(gloss,gloss[1:])),
              'roughness slider changes probe filtering even with a zero-blur preset')
        check(abs(gloss[1]-(1-max(.06,preset)))<.002 and abs(gloss[-1])<.002,
              f'neutral roughness keeps the preset; maximum reaches fully rough probes: {preset}, {gloss}')
    gpu.uniform(p,'blurMultiplier',.3)
    zero_gloss=[]
    for scale in (0,.25):
        gpu.uniform(p,'water_roughness_scale',scale)
        zero_gloss.append((render(p)[0]-.5*(1-.02037))/.02037)
    check(zero_gloss[0]>zero_gloss[1]+.04,'zero roughness sharpens below the former minimum')
    gpu.uniform(p,'fixture_probe_glossiness',0,integer=True)
    gpu.uniform(p,'blurMultiplier',.08)
    gpu.uniform(p,'fixture_sun',1,1,1)
    peaks=[];shoulders=[]
    for scale in (.25,1,2,3):
        gpu.uniform(p,'water_roughness_scale',scale)
        gpu.uniform(p,'fixture_light',0,0,1);peaks.append(render(p)[0])
        gpu.uniform(p,'fixture_light',.6,0,.8);shoulders.append(render(p)[0])
    check(peaks[0]>peaks[1]*10 and peaks[1]>peaks[2]*10 and peaks[2]>peaks[3],
          'roughness visibly reduces and broadens the sun highlight')
    check(shoulders[2]>shoulders[1]+.001,'rough water scatters sunlight beyond the sharp glint')
    # Preserve filtering of unresolved normals; the default response is unchanged.
    filtered=gpu.program('uniform float blurMultiplier, water_roughness_scale;\n'+
        function(water,'float waterSurfaceRoughness(')+'''
        out vec4 frag_color;
        void main(){frag_color=vec4(waterSurfaceRoughness(normalize(vec3(gl_FragCoord.xy*.3,1))));}
    ''')
    gpu.uniform(filtered,'blurMultiplier',.08)
    filter_target=gpu.tex(4,4,internal=0x8814);filtered_values=[]
    for scale in (.25,1,2,3):
        gpu.uniform(filtered,'water_roughness_scale',scale)
        gpu.render(filtered,filter_target,4,4)
        filtered_values.append(gpu.pixels(filter_target,4,4)[0])
    check(filtered_values[0]>.2,'smooth setting retains the subpixel specular filter')
    check(filtered_values[2]>filtered_values[1]+.15 and filtered_values[3]==1,
          'upper roughness settings remain effective with normal variance')
    gpu.uniform(p,'water_roughness_scale',1)
    gpu.uniform(p,'normScale',0,0,0)
    render(p)
    # An actual spatial lookup: a sloped normal displaces the sampled scene.
    # Invalid foreground/excluded samples must return to the unshifted pixel.
    gradient=[v for y in range(32) for x in range(32) for v in (x/31,x/31,x/31,0)]
    gpu.upload_tex(scene,32,32,gradient)
    gpu.upload_tex(normal,1,1,[1,.5,1,1])
    gpu.uniform(p,'normScale',2,2,2)
    gpu.uniform(p,'fixture_sun',0,0,0)
    gpu.uniform(p,'fixture_probe',0,0,0)
    gpu.uniform(p,'refScale',.03)
    gpu.uniform(p,'blurMultiplier',.08)
    # Wave refraction uses one depth-aware lookup within its screen budget.
    refracted_value=render(p)[0]
    check(.44<refracted_value<.485,f'bounded wave refraction displaces the scene lookup: {refracted_value}')
    foreground=[v for x in range(32) for v in ((.1 if x<16 else .9),)*3+(1,)]
    gpu.upload_tex(depth,32,1,foreground)
    # Match the viewer's point-sampled depth attachment at the discontinuity.
    for param in (0x2800,0x2801): gl.TexParameteri(0x0DE1,param,0x2600)
    check(abs(render(p)[0]-.489815)<.003,'foreground refraction falls back to surface pixel')
    gpu.upload_tex(depth,1,1,[.9,.9,.9,1])
    excluded=[v for x in range(128) for v in ((0 if x<63 else 1),)*4]
    gpu.upload_tex(mask,128,1,excluded)
    check(abs(render(p)[0]-.489815)<.003,'excluded refraction falls back to surface pixel')
    gpu.upload_tex(mask,1,1,[1]*4)
    shallow=(1.020202-2.020202/2.001)*.5+.5
    gpu.upload_tex(depth,1,1,[shallow]*3+[1])
    check(abs(render(p)[0]-.489815)<.003,'shallow refraction smoothly loses distortion')
    # Direct Fresnel values independent of the integration LUT fixture.
    helper=gpu.program(combine(optical,depth_brdf,water.replace('void main()', 'void waterMain()')) + """
        uniform float cosine;
        void main() { frag_color=vec4(waterFresnel(cosine,0.02037)); }
    """,VERTEX)
    for cosine,expected in ((1,.02037),(0,1),(.5,.0509834375)):
        gpu.uniform(helper,'cosine',cosine)
        check(abs(render(helper)[0]-expected)<.001,'water Fresnel reference')

    # Trace a known visible wall at z=-8, reflected in water at y=-1.
    # This exercises the real march, hit refinement and scene-colour sampling.
    reflection=gpu.program(combine('#define TRANSPARENT_WATER 1\n',optical,depth_brdf,
        water.replace('void main()', 'void waterMain()')) + """
        uniform vec3 fixture_point, fixture_normal;
        uniform float fixture_roughness;
        void main() {
            frag_color=waterLocalReflection(fixture_point,fixture_normal,fixture_roughness);
        }
    """,VERTEX)
    for unit,(name,tex) in enumerate((('screenTex',scene),('depthMap',depth))):
        gpu.bind(reflection,name,unit,tex)
    gpu.matrix(reflection,'projection_matrix',projection)
    gpu.matrix(reflection,'inv_proj',inverse(projection))
    gpu.uniform(reflection,'waterPlane',0,1,0,1)
    gpu.uniform(reflection,'fixture_point',0,-1,-4)
    gpu.uniform(reflection,'fixture_normal',0,1,0)
    gpu.uniform(reflection,'fixture_roughness',.08)
    gpu.uniform(reflection,'water_local_reflections',1,integer=True)
    gpu.upload_tex(scene,1,1,[.025,.05,.1,0])
    wall_depth=(1.020202-2.020202/8)*.5+.5
    gpu.upload_tex(depth,1,1,[wall_depth]*3+[1])
    hit=render(reflection)
    check(near(hit[:3],[.025,.05,.1]) and hit[3]>.95,'nearby dark wall reflects with full confidence')
    gpu.uniform(reflection,'fixture_roughness',.3)
    blurred=render(reflection)
    check(0<blurred[3]<hit[3],'rough reflections smoothly fade to probes')
    gpu.uniform(reflection,'fixture_roughness',.5)
    check(render(reflection)[3]==0,'very rough water skips local trace')
    gpu.uniform(reflection,'fixture_roughness',.08)
    gpu.uniform(reflection,'water_local_reflections',0,integer=True)
    check(render(reflection)[3]==0,'reflection performance toggle skips local trace')
    gpu.uniform(reflection,'water_local_reflections',1,integer=True)
    gpu.uniform(reflection,'cube_snapshot',1,integer=True)
    check(render(reflection)[3]==0,'probe captures skip screen reflections')
    gpu.uniform(reflection,'cube_snapshot',0,integer=True)
    gpu.uniform(reflection,'waterPlane',0,1,0,-20)
    check(render(reflection)[3]==0,'submerged scene is not a land reflection')
    gpu.uniform(reflection,'waterPlane',0,1,0,1)
    gpu.upload_tex(depth,1,1,[1]*4)
    check(render(reflection)[3]==0,'sky depth falls back to probes')
    gpu.upload_tex(depth,1,1,[wall_depth]*3+[1])
    for point in ((20,-1,-4),(0,-1,-200)):
        gpu.uniform(reflection,'fixture_point',*point)
        check(render(reflection)[3]==0,'offscreen/distant rays fall back to probes')

    detail_program=gpu.program(combine(optical,depth_brdf,
        water.replace('void main()', 'void waterMain()')) + """
        uniform vec2 fixture_position;
        uniform float fixture_distance;
        void main() { frag_color=vec4(waterDetailWeight(fixture_position,fixture_distance)); }
    """,VERTEX)
    weights=[]
    for position in ((0,0),(40,40),(80,30),(140,80),(210,140)):
        gpu.uniform(detail_program,'fixture_position',*position)
        gpu.uniform(detail_program,'fixture_distance',10)
        weights.append(render(detail_program)[0])
    check(max(weights)-min(weights)>.2,'fine ripples vary across broad wind patches')
    gpu.uniform(detail_program,'fixture_distance',250)
    check(render(detail_program)[0]==0,'subpixel fine detail disappears in distance')

    # Exercise the production vertex animation, using a full-screen triangle
    # only for coverage. Identical EEP directions must still produce cross seas.
    wave_vertex=combine(read('class1/environment/waterV.glsl'), read('class1/environment/waterDisplacementV.glsl')).replace(
        'gl_Position = oPosition;',
        'vec2 corners[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));'
        'gl_Position=vec4(corners[gl_VertexID],0,1);')
    motion=gpu.program('''
        in vec4 refCoord, view;
        in vec2 crossingWave;
        out vec4 frag_color;
        void main() { frag_color=vec4(refCoord.w,view.w,crossingWave); }
    ''',wave_vertex+'\nvoid calcAtmospherics(vec3 p) {}')
    gl.VertexAttrib4f(0,10,20,0,1)
    gpu.uniform(motion,'eyeVec',0,0,10)
    gpu.uniform(motion,'waterHeight',10)
    for direction in ((1,1),(1,0),(-.5,1)):
        gpu.uniform(motion,'waveDir1',*direction)
        gpu.uniform(motion,'waveDir2',*direction)
        gpu.uniform(motion,'time',0)
        a=render(motion)
        gpu.uniform(motion,'time',4)
        b=render(motion)
        d=[y-x for x,y in zip(a,b)]
        cosine=(d[0]*d[2]+d[1]*d[3])/(math.hypot(*d[:2])*math.hypot(*d[2:]))
        check(abs(cosine)<.01,'swell bands move crosswise with identical EEP directions')
    gpu.uniform(motion,'waveDir1',0,0)
    gpu.uniform(motion,'waveDir2',0,0)
    gpu.uniform(motion,'time',0)
    a=render(motion)
    gpu.uniform(motion,'time',20)
    check(near(a,render(motion)), 'stationary EEP water remains stationary')

    # Exercise the new branch through the complete optical shader, not only its
    # slope helper. Flat generated slopes must preserve the dielectric solution.
    wave_texture = gpu.tex(1,1,[0,0,0,0])
    gpu.upload_tex(normal,1,1,[.5,.5,1,1])
    gpu.upload_tex(scene,1,1,[.5,.5,.5,.4])
    gpu.upload_tex(depth,1,1,[.9,.9,.9,1])
    gpu.upload_tex(mask,1,1,[1,1,1,1])
    gpu.bind(p,'waterWaveSlopes',5,wave_texture)
    gpu.uniform(p,'water_procedural_waves',1,integer=True)
    gpu.uniform(p,'water_wave_direction',1,0)
    gpu.uniform(p,'water_wave_origin',0,0)
    gpu.uniform(p,'water_wave_strength',1)
    gpu.uniform(p,'fixture_probe',1,1,1)
    gpu.uniform(p,'fixture_sun',0,0,0)
    gpu.uniform(p,'normScale',2,2,2)
    medium(p)
    check(near(render(p)[:3],[.510185]*3), 'flat procedural field preserves optical energy')
    gpu.upload_tex(wave_texture,1,1,[.2,-.1,.04,.03])
    check(all(x>=0 for x in render(p)), 'procedural slopes render through full water optics')
    print(f'Passed {count} water GPU checks on {gl.GetString(0x1F01).decode()}')

if __name__ == '__main__':
    sdl,window,ctx,gl=context()
    try: run(sdl,gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx); sdl.SDL_DestroyWindow(window); sdl.SDL_Quit()
