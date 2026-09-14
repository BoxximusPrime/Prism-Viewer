"""Native fixed-grid/clock invariants and production vertex displacement on the GPU.

Run: .venv/Scripts/python.exe scripts/tests/test_water_displacement_gpu.py
Uses configured MSVC and the bundled SDL context. No viewer login/settings changes.
"""
import ctypes as C
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile

from test_eye_adaptation_gpu import EyeGPU
from test_taa_gpu import context, U, I, F
from test_water_gpu import function, combine

ROOT=Path(__file__).resolve().parents[2]
SHADERS=ROOT/'indra/newview/app_settings/shaders/class1'


def native_grid():
    source=function((ROOT/'indra/newview/llvowater.cpp').read_text(encoding='utf-8'),
                    'std::vector<F64> waterMeshAxis(')
    clock_source=(ROOT/'indra/newview/lldrawpoolwater.cpp').read_text(encoding='utf-8')
    clock_source=clock_source[clock_source.index('void LLDrawPoolWater::updateWaveField()'):]
    clock_source=clock_source[:clock_source.index('    const U32 frame')]+'}\n'
    # Compile the production clock integration against a controlled clock and
    # settings provider. Speed changes must not rephase or catch up after pauses.
    clock_fixture='''
#include <string>
using F32=float;
#define LL_PROFILE_GPU_ZONE(x)
template<class T> T llclamp(T v,T lo,T hi) {return std::clamp(v,lo,hi);}
template<class T> T llmax(T a,T b) {return std::max(a,b);}
double test_now=0; float test_wind=1, test_speed=2; bool test_enabled=true;
struct LLFrameTimer {static double getElapsedSeconds(){return test_now;}};
int gSavedSettings=0;
template<class T> struct LLCachedControl {
    std::string name;
    LLCachedControl(int,const char* key,T):name(key){}
    T operator()() const {return T(name=="RenderWaterWindSpeed" ? test_wind : float(test_enabled));}
    operator T() const {return operator()();}
};
struct Waves {bool isComplete(){return true;}};
struct Pipeline {Waves mWaterWaves;} gPipeline;
struct Direction {float length(){return test_speed;}};
struct Water {Direction getWave1Dir(){return {};} Direction getWave2Dir(){return {};}};
struct LLEnvironment {
    static LLEnvironment& instance(){static LLEnvironment e;return e;}
    Water* getCurrentWater(){static Water w;return &w;}
};
struct LLDrawPoolWater {
    double mWaveTime=0,mWaveDetailTime=0,mWaveLastTime=-1;
    void updateWaveField();
};
'''
    cache=(ROOT/'build-vc170-64/CMakeCache.txt').read_text(encoding='utf-8')
    vs=Path(re.search(r'^CMAKE_GENERATOR_INSTANCE:[^=]+=(.+)$',cache,re.M)[1].strip())
    # Capture the compiler environment privately; never print its contents.
    command=f'"{vs / "VC/Auxiliary/Build/vcvars64.bat"}" >nul && set'
    result=subprocess.run(command,shell=True,capture_output=True,text=True)
    assert result.returncode==0,'MSVC environment setup failed'
    env=dict(os.environ)
    for line in result.stdout.splitlines():
        if '=' in line:
            key,value=line.split('=',1);env[key]=value
    with tempfile.TemporaryDirectory(prefix='prism-water-grid-') as directory:
        folder=Path(directory)
        (folder/'grid.cpp').write_text('''#include <algorithm>
#include <cmath>
#include <vector>
#include <cassert>
#include <iostream>
using F64=double;
'''+clock_fixture+clock_source+source+'''
int main() {
    LLDrawPoolWater clock;
    clock.updateWaveField();
    test_now=1;clock.updateWaveField();
    assert(clock.mWaveTime==2 && clock.mWaveDetailTime==1);
    test_wind=0;test_now=101;clock.updateWaveField();
    assert(clock.mWaveTime==2 && clock.mWaveDetailTime==1);
    test_wind=0.5;test_now=103;clock.updateWaveField();
    assert(clock.mWaveTime==4 && clock.mWaveDetailTime==2);
    test_enabled=false;test_now=203;clock.updateWaveField();
    assert(clock.mWaveTime==4 && clock.mWaveDetailTime==52);
    test_enabled=true;test_now=204;clock.updateWaveField();
    assert(clock.mWaveTime==5 && clock.mWaveDetailTime==52.5);
    test_wind=10;test_now=205;clock.updateWaveField();
    assert(clock.mWaveTime==11 && clock.mWaveDetailTime==55.5);
    test_wind=-1;test_now=206;clock.updateWaveField();
    assert(clock.mWaveTime==11 && clock.mWaveDetailTime==55.5);
    int cases=0; size_t largest=0;
    for(double center : {-100000.0,-272.0,-16.0,0.0,16.0,128.0,240.0,256.0,100000.0}) {
        for(double radius : {8.0,32.0,64.0,97.0,128.0}) {
            for(double width : {256.0,512.0,2048.0,8192.0,1000000.0}) {
                auto a=waterMeshAxis(center-width/2,center+width/2,center,radius);
                assert(a.front()==center-width/2 && a.back()==center+width/2);
                for(size_t i=1;i<a.size();++i) {
                    assert(a[i]>a[i-1]);
                    if(a[i]>center-radius && a[i-1]<center+16+radius)
                        assert(a[i]-a[i-1]<=0.25);
                }
                // Production splits each axis at 128 cells, repeating only the
                // shared border vertices. Count every cell once; U16 stays safe.
                size_t cells=0;
                for(size_t y=0;y<a.size()-1;y+=128)
                    for(size_t x=0;x<a.size()-1;x+=128) {
                        size_t nx=std::min(size_t(129),a.size()-x);
                        size_t ny=std::min(size_t(129),a.size()-y);
                        assert(nx*ny<=65535);
                        largest=std::max(largest,nx*ny);
                        cells+=(nx-1)*(ny-1);
                    }
                assert(cells==(a.size()-1)*(a.size()-1));
                ++cases;
            }
            auto wide=waterMeshAxis(-512,512,center,radius);
            for(double low : {-512.0,-256.0,0.0,256.0}) {
                auto small=waterMeshAxis(low,low+256,center,radius);
                for(double value:small) if(std::abs(value-center)<radius)
                    assert(std::find(wide.begin(),wide.end(),value)!=wide.end());
                ++cases;
            }
            // Every visible vertex survives a 16 m recenter unchanged. At the
            // transition both old/new grids enclose the continuous fade circle.
            auto old=waterMeshAxis(-1000000,1000000,center,radius);
            auto next=waterMeshAxis(-1000000,1000000,center+16,radius);
            for(double value:old) if(std::abs(value-(center+16))<=radius)
                assert(std::find(next.begin(),next.end(),value)!=next.end());
            for(double value:next) if(std::abs(value-(center+16))<=radius)
                assert(std::find(old.begin(),old.end(),value)!=old.end());
            ++cases;
        }
    }
    auto a=waterMeshAxis(-256,256,0,64);
    auto b=waterMeshAxis(256,768,512,64);
    assert(a.size()==b.size());
    for(size_t i=0;i<a.size();++i) assert(std::abs(a[i]+512-b[i])<1e-10);
    std::cout << "PASS: " << cases+1 << " native grid cases and 7 production wave-clock checks; largest chunk " << largest << " vertices\\n";
}''',encoding='utf-8')
        compiler=sorted((vs/'VC/Tools/MSVC').glob('*/bin/Hostx64/x64/cl.exe'))[-1]
        result=subprocess.run([str(compiler),'/nologo','/EHsc','/std:c++17','grid.cpp','/Fe:grid.exe'],
                              cwd=folder,env=env,capture_output=True,text=True)
        assert result.returncode==0,result.stdout+result.stderr
        result=subprocess.run([str(folder/'grid.exe')],capture_output=True,text=True)
        assert result.returncode==0,result.stdout+result.stderr
        print(result.stdout.strip())


def run(sdl,gl):
    gpu=EyeGPU(sdl,gl)
    read=lambda name:(SHADERS/name).read_text(encoding='utf-8')
    helper=read('environment/waterDisplacementV.glsl')
    fullscreen='vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3)); gl_Position=vec4(p[gl_VertexID],0,1);'
    surface_vertex=combine(read('environment/waterV.glsl'),helper)+'\nvoid calcAtmospherics(vec3 p) {}'
    mask_vertex=combine(read('environment/waterMaskV.glsl'),helper)
    surface=gpu.program('in vec3 vary_position; out vec4 frag_color; void main(){frag_color=vec4(vary_position,1);}',
                        surface_vertex.replace('gl_Position = oPosition;',fullscreen))
    mask=gpu.program('in vec4 vertex_position; out vec4 frag_color; void main(){frag_color=vertex_position;}',
                     mask_vertex.replace('gl_Position = vertex_position;',fullscreen))
    output=gpu.tex(1,1,internal=0x8814)
    heights=gpu.tex(256,256,[2,.5,0,0]*65536,internal=0x822F)
    gpu.reduce(heights)
    for parameter in (0x2802,0x2803): gl.TexParameteri(0x0DE1,parameter,0x2901)
    depth=gpu.tex(1,1,[1,1,1,1],internal=0x822E)
    identity=[[float(r==c) for c in range(4)] for r in range(4)]
    cases=0
    def check(ok,label):
        nonlocal cases
        assert ok,label
        cases+=1
    def sample(program,position=(0,0,0),scale=.05,strength=.1,amount=1,damping=0,scene_depth=1,
               origin=(0,0),center=(0,0),normal=(1,1,1),projection=None,inverse=None,radius=64):
        gpu.upload_tex(depth,1,1,[scene_depth]*4,internal=0x822E)
        gpu.bind(program,'waterWaveHeights',0,heights)
        gpu.bind(program,'waterGeometryDepth',1,depth)
        gpu.uniform(program,'water_wave_scale',scale)
        gpu.uniform(program,'water_wave_strength',strength)
        gpu.uniform(program,'water_displacement',amount)
        gpu.uniform(program,'water_displacement_distance',radius)
        gpu.uniform(program,'water_shallow_damping',damping)
        gpu.uniform(program,'water_wave_direction',1,0)
        gpu.uniform(program,'water_wave_origin',*origin)
        gpu.uniform(program,'water_mesh_center',*center)
        gpu.uniform(program,'normScale',*normal)
        gpu.uniform(program,'eyeVec',0,0,5)
        gpu.matrix(program,'modelview_matrix',identity)
        gpu.matrix(program,'modelview_projection_matrix',projection or identity)
        gpu.matrix(program,'inv_modelview',identity)
        gpu.matrix(program,'inv_proj',inverse or identity)
        gl.VertexAttrib4f(0,*position,1)
        gpu.render(program,output)
        result=gpu.pixels(output)
        assert gl.GetError()==0
        return result
    for scale in (.01,.05,.5,2):
        for amount in (0,.5,1,5):
            for program in (surface,mask):
                actual=sample(program,scale=scale,amount=amount)
                expected=2.275*scale*.1*amount
                check(abs(actual[2]-expected)<2e-6,'physical height scale and surface/mask match')
    check(sample(surface,strength=0)[2]==0,'zero strength is flat')
    check(sample(surface,normal=(0,0,1))[2]==0,'zero normal scale is flat')
    check(sample(surface,amount=5,scale=2,strength=3)[2]==8,'positive culling bound')
    for radius in (8,32,64,128):
        near=sample(surface,radius=radius)[2]
        for program in (surface,mask):
            check(sample(program,position=(radius,0,0),radius=radius)[2]==0,'radius ends with flat water')
            check(abs(sample(program,position=(radius*.6,0,0),radius=radius)[2]-near)<1e-6,'full height throughout inner radius')
            check(0<sample(program,position=(radius*.8,0,0),radius=radius)[2]<near,'gradual edge fade')
            before=sample(program,position=(radius*.8,0,0),center=(15.999,0),radius=radius)[2]
            after=sample(program,position=(radius*.8,0,0),center=(16.001,0),radius=radius)[2]
            check(abs(before-after)<.0001,'continuous fade across CPU window step')
    # Orthographic test camera covers [-5,5] in z; flat water is at zero.
    projection=[row[:] for row in identity];projection[2][2]=.2
    inverse=[row[:] for row in identity];inverse[2][2]=5
    full=sample(surface)[2]
    for water_depth in (0,.01,.1,.75,1.5,5):
        d=.5-water_depth*.1
        x=min(water_depth/1.5,1); expected=x*x*(3-2*x)
        for damping in (0,.5,1):
            for program in (surface,mask):
                actual=sample(program,damping=damping,scene_depth=d,projection=projection,inverse=inverse)[2]
                # Mask output is clip-space z; surface output is eye-space z.
                if program==mask:actual*=5
                check(abs(actual-full*(1-damping+damping*expected))<2e-6,'depth damping and mask agree')
    for scene_depth in (.75,1):
        check(abs(sample(surface,damping=1,scene_depth=scene_depth)[2]-full)<1e-6,
              'foreground objects and sky are not shallow bottoms')
    check(abs(sample(surface,position=(1,0,0),damping=1,scene_depth=.5)[2]-full)<1e-6,
          'offscreen depth lookup is rejected')

    # Run production FFT and new height resolve, independently checking that its
    # packed channels really contain the real swell/chop fields, not imaginary data.
    seed=gpu.program(read('environment/waterWaveFieldF.glsl'))
    fft=gpu.program(read('environment/waterWaveFFTF.glsl'))
    resolve=gpu.program(read('environment/waterWaveResolveF.glsl'))
    scratch=[gpu.tex(256,256,internal=0x8814) for _ in range(2)]
    def generate(time):
        gpu.uniform(seed,'water_wave_time',time)
        gpu.uniform(seed,'water_cross_swell',2.3)
        gpu.uniform(seed,'water_wave_scale',.05)
        gpu.render(seed,scratch[0],256,256)
        source=0
        for axis in (0,1):
            gpu.uniform(fft,'water_fft_axis',axis,integer=True)
            for stage in range(1,9):
                gpu.bind(fft,'waterWaveSpectrum',0,scratch[source])
                gpu.uniform(fft,'water_fft_stage',stage,integer=True)
                gpu.render(fft,scratch[1-source],256,256);source=1-source
        gpu.bind(resolve,'waterWaveSpectrum',0,scratch[source])
        gpu.uniform(resolve,'water_wave_resolve_height',1,integer=True)
        gpu.render(resolve,heights,256,256);gpu.reduce(heights)
        return gpu.pixels(scratch[source],256,256),gpu.pixels(heights,256,256)
    raw,packed=generate(0)
    for i in (0,17,321,30281,65535):
        check(abs(raw[i*4]-packed[i*4])<.001 and abs(raw[i*4+2]-packed[i*4+1])<.001,
              'height resolve preserves both real FFT fields')
    check(max(abs(v) for v in gpu.pixels(heights,level=8)[:2])<.0001,'height mips converge to mean level')
    # The real spectral heights no longer disappear a few metres from the eye.
    for radius in (32,64,128):
        at=radius*.5
        fixed=sample(surface,position=(at,2,0),radius=radius)[2]
        centered=sample(surface,position=(at,2,0),center=(at,0),radius=radius)[2]
        check(abs(fixed-centered)<1e-6,'resolvable FFT heights retained throughout detailed area')
    original=sample(surface,position=(1,2,0))[2]
    shifted=sample(surface,position=(1-256,2+256,0),center=(-256,256),
                   origin=(math.fmod(256/.05,256),math.fmod(-256/.05,256)))[2]
    check(abs(original-shifted)<.0001,'region-origin shift preserves height/phase')
    generate(.7)
    check(abs(sample(surface,position=(1,2,0))[2]-original)>.00001,'geometry evolves with FFT time')
    print(f'PASS: {cases} displacement GPU checks on {gl.GetString(0x1F01).decode()}')


if __name__=='__main__':
    native_grid()
    sdl,window,ctx,gl=context()
    try:run(sdl,gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx);sdl.SDL_DestroyWindow(window);sdl.SDL_Quit()
