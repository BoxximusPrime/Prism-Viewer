"""Actual wave/caustic functions against flat and sinusoidal lens references.
No login. Also checks phase registration, exclusion, depth and HDR lighting.
"""
import math
from pathlib import Path
from test_eye_adaptation_gpu import EyeGPU
from test_taa_gpu import context
from test_water_gpu import function, FIXTURES

ROOT = Path(__file__).resolve().parents[2]
SH = ROOT / 'indra/newview/app_settings/shaders/class1/environment'


def run(sdl, gl):
    gpu = EyeGPU(sdl, gl)
    count = 0
    def check(ok, name):
        nonlocal count
        assert ok, name
        count += 1
    fog = (SH/'waterFogF.glsl').read_text()
    srgb = function((SH/'srgbF.glsl').read_text(), 'vec3 srgb_to_linear(')
    p = gpu.program(srgb + fog + FIXTURES + '''
        uniform vec3 fixture_point, fixture_light;
        uniform int fixture_mode;
        out vec4 frag_color;
        void main(){
            float c=waterCaustics(fixture_point,fixture_light);
            frag_color=vec4(fixture_mode == 0 ? vec3(c) :
                waterLitSun(fixture_point,fixture_light,vec3(2,1,.5),0),1);
        }
    ''')
    output = gpu.tex(1,1,internal=0x8814)
    waves = gpu.tex(256,256,internal=0x8814)
    mask = gpu.tex(1,1,[1]*4)
    generator = gpu.program('''
        uniform float amplitude, phase, tilt;
        out vec4 frag_color;
        void main(){float x=gl_FragCoord.x/256.0;
            frag_color=vec4(amplitude*sin(x*6.28318530718*8.0+phase)+tilt,0,0,0);}
    ''')
    def field(amplitude, phase=0, tilt=0):
        gpu.uniform(generator,'amplitude',amplitude)
        gpu.uniform(generator,'phase',phase)
        gpu.uniform(generator,'tilt',tilt)
        gpu.render(generator,waves,256,256)
        gpu.reduce(waves)
        gl.BindTexture(0x0DE1,waves)
        for name in (0x2802,0x2803): gl.TexParameteri(0x0DE1,name,0x2901)
    gpu.matrix(p,'water_inverse_view',[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]])
    gpu.uniform(p,'waterPlane',0,0,1,2)
    gpu.uniform(p,'water_wave_direction',1,0)
    gpu.uniform(p,'water_wave_origin',0,0)
    gpu.uniform(p,'water_wave_scale',.11)
    gpu.uniform(p,'water_wave_strength',1)
    gpu.uniform(p,'water_caustics_normal_scale',1,1,1)
    gpu.uniform(p,'water_caustics_strength',1)
    gpu.uniform(p,'fixture_light',0,0,1)
    def render(x=0,depth=1):
        gpu.uniform(p,'fixture_point',x,0,-2-depth)
        gpu.bind(p,'waterWaveSlopes',0,waves)
        gpu.bind(p,'exclusionTex',1,mask)
        gpu.render(p,output)
        result=gpu.pixels(output)
        check(all(math.isfinite(v) for v in result),'finite caustic output')
        return result[:3]
    for tilt in (0,.25,-.5):
        field(0,tilt=tilt)
        for depth in (.05,1,4,12):
            for light in ((0,0,1),(.6,0,.8)):
                gpu.uniform(p,'fixture_light',*light)
                check(abs(render(depth=depth)[0]-1)<.003,'flat and uniformly tilted interfaces never focus light')
    gpu.uniform(p,'fixture_light',0,0,1)
    field(.15)
    for depth in (.3,1,2):
        response=render(depth=depth)[0]
        shallow=.35+.65*max(0,min(1,depth/1.5))**2*(3-2*max(0,min(1,depth/1.5)))
        derivative=.15*2*math.pi/(32*.11)*shallow
        expected=1/(1-depth*(1-1/1.333)*derivative)
        check(abs(response-expected)<.015,'sinusoidal lens concentration agrees with the analytic Snell Jacobian')
    bright=render(depth=2)[0]
    dark=render(x=16*.11,depth=2)[0]
    check(bright>1.1 and dark<.9,'converging rays brighten and diverging rays darken')
    baseline=render(x=.35,depth=2)[0]
    field(.15,phase=math.pi/4)
    moved=render(x=.35-4*.11,depth=2)[0]
    check(abs(baseline-moved)<.004,f'wave phase advects the caustic pattern by the same displacement: {baseline}, {moved}')
    field(.15)
    for depth in (-1,0,16,40):
        check(render(depth=depth)==[1,1,1],'above-water and deep receivers have no caustics')
    gpu.uniform(p,'water_caustics_strength',0)
    check(render()==[1,1,1],'disabled caustics are an exact identity')
    gpu.uniform(p,'water_caustics_strength',1)
    gpu.upload_tex(mask,1,1,[0]*4)
    check(render()==[1,1,1],'exclusion prevents caustics')
    gpu.upload_tex(mask,1,1,[1]*4)
    gpu.uniform(p,'fixture_light',1,0,0)
    check(render()==[1,1,1],'light below the horizon cannot cast caustics')
    gpu.uniform(p,'fixture_light',0,0,1)
    gpu.uniform(p,'fixture_mode',1,integer=True)
    gpu.uniform(p,'water_lighting_enabled',0,integer=True)
    color=render(depth=2)
    check(abs(color[0]/2-color[1])<.0001 and abs(color[1]/2-color[2])<.0001,
          'caustics preserve directional light colour and HDR')
    gpu.uniform(p,'fixture_mode',0,integer=True)
    for amplitude in (.5,2,8):
        field(amplitude)
        for depth in (.1,1,3,8,15):
            value=render(.17,depth)[0]
            check(0<=value<=4.001,'folds and steep waves remain bounded')
    print(f'Passed {count} caustic GPU checks on {gl.GetString(0x1F01).decode()}')


if __name__ == '__main__':
    sdl,window,ctx,gl=context()
    try: run(sdl,gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx);sdl.SDL_DestroyWindow(window);sdl.SDL_Quit()
