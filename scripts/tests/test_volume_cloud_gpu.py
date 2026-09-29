"""Production cloud shader checks on the viewer's SDL/OpenGL runtime.

Run: .venv/Scripts/python.exe scripts/tests/test_volume_cloud_gpu.py (g++ on PATH).
No viewer login needed. --preview writes a synthetic sky to tmp/cloud-preview.png;
add --near to inspect billows and shading from just below a thicker layer.
"""
import ctypes as C
import math
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from test_exact_oit_gpu import context, U, I, F, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT, RGBA, FLOAT

ROOT = Path(__file__).resolve().parents[2]


def camera_uploads():
    """Exercise production camera uploads and sunlight scaling in native code."""
    body=(ROOT/'indra/newview/pipeline.cpp').read_text().split('void LLPipeline::renderVolumeClouds()')[1]
    calculation=re.search(r'const glm::mat[34] view_to_world = [^;]+;',body)[0]
    upload=next(line for line in body.splitlines() if '"vc_view_to_world"' in line)
    sunlight='\n'.join(re.search(r'const F32 '+name+r' = [^;]+;',body)[0] for name in ('sunlight_scale','strength'))
    cases=[]
    for yaw,pitch,roll in ((0,20,0),(90,45,0),(180,70,30),(270,10,90),(37,-40,180)):
        y,p,r=map(math.radians,(yaw,pitch,roll))
        forward=(math.cos(p)*math.cos(y),math.cos(p)*math.sin(y),math.sin(p))
        right=(math.sin(y),-math.cos(y),0)
        up=(-math.sin(p)*math.cos(y),-math.sin(p)*math.sin(y),math.cos(p))
        rolled_right=[a*math.cos(r)+b*math.sin(r) for a,b in zip(right,up)]
        rolled_up=[b*math.cos(r)-a*math.sin(r) for a,b in zip(right,up)]
        for eye in ((200,400,-100),(513,-127,100)):
            cases.append([*rolled_right,0,*rolled_up,0,*[-v for v in forward],0,*eye,1])
    rows=',\n'.join('{'+','.join(format(v,'.9g') for v in m)+'}' for m in cases)
    source=r'''
#include <glm/glm.hpp>
#include <glm/gtc/type_ptr.hpp>
#include <cassert>
#include <algorithm>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>
using F32 = float;
F32 llclamp(F32 x, F32 lo, F32 hi) { return std::clamp(x,lo,hi); }
struct Environment {
    bool sun;
    bool getIsSunUp() const { return sun; }
} environment;
struct Settings {
    bool hdr;
    F32 amount;
    bool getBOOL(const char*) const { return hdr; }
    F32 getF32(const std::string& key) const {
        if (key=="RenderVolumeCloudSunlight") return amount;
        return key=="RenderHDRSkySunlightScale" ? 2.f : .5f;
    }
} gSavedSettings;
glm::mat4 view;
glm::mat4 get_current_modelview() { return view; }
using LLStaticHashedString = const char*;
std::vector<float> uploaded;
void glUniformMatrix3fv(int, int, bool, const float* p) { uploaded.assign(p,p+9); }
struct Shader {
    int getUniformLocation(const char*) { return 0; }
    void uniformMatrix4fv(const char*, int, bool, const float* p) { uploaded.assign(p,p+16); }
} shader;
int main() {
    static_assert(sizeof(glm::mat3)==12*sizeof(float), "Use the viewer's padded GLM ABI");
    const float cases[][16]={CASES};
    std::cout << std::setprecision(9);
    for (const auto& camera : cases) {
        view=glm::inverse(glm::make_mat4(camera));
        CALCULATION
        UPLOAD
        for (float value : uploaded) std::cout << value << ' ';
        std::cout << '\n';
    }
    for (bool sun : {false,true}) for (bool hdr : {false,true}) {
        environment.sun=sun;
        gSavedSettings.hdr=hdr;
        for (F32 amount : {-2.f,0.f,.5f,1.f,2.f,9.f}) {
            gSavedSettings.amount=amount;
            SUNLIGHT
            assert(strength==(hdr ? 2.f : .5f)*(sun ? std::clamp(amount,0.f,2.f) : 1.f));
        }
    }
}
'''.replace('CASES',rows).replace('CALCULATION',calculation).replace('UPLOAD',upload).replace('SUNLIGHT',sunlight)
    compiler=shutil.which('g++')
    assert compiler,'g++ must be on PATH for the native camera upload regression'
    with tempfile.TemporaryDirectory(prefix='prism-cloud-camera-') as directory:
        folder=Path(directory); cpp=folder/'camera.cpp'; exe=folder/'camera.exe'
        cpp.write_text(source)
        subprocess.run([compiler,'-std=c++17','-DGLM_FORCE_DEFAULT_ALIGNED_GENTYPES=1',
                        '-DGLM_FORCE_SSE2=1','-DGLM_ENABLE_EXPERIMENTAL=1',
                        '-I',str(ROOT/'build-vc170-64/packages/include'),str(cpp),'-o',str(exe)],check=True)
        result=subprocess.run([str(exe)],capture_output=True,text=True,check=True)
    return [(reference,list(map(float,line.split()))) for reference,line in zip(cases,result.stdout.splitlines(),strict=True)]


def run(sdl, gl):
    for name, args in {
        'ActiveTexture': [U], 'Uniform3f': [I,F,F,F], 'Uniform2f': [I,F,F],
        'UniformMatrix4fv': [I,I,C.c_ubyte,C.c_void_p],
        'Disable': [U],
        'TexImage3D': [U,I,I,I,I,I,I,U,U,C.c_void_p],
        'GenerateMipmap': [U],
    }.items():
        setattr(gl, name, C.WINFUNCTYPE(None,*args)(sdl.SDL_GL_GetProcAddress(('gl'+name).encode())))

    def obj(generator):
        result=U(); generator(1,C.byref(result)); return result.value

    program=gl.CreateProgram()
    vertex='void main(){vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));gl_Position=vec4(p[gl_VertexID],0,1);}'
    fragment=(ROOT/'indra/newview/app_settings/shaders/class1/deferred/volumeCloudF.glsl').read_text()
    for kind,source in ((0x8B31,vertex),(0x8B30,fragment)):
        shader=gl.CreateShader(kind)
        source=C.c_char_p(('#version 330 core\n'+source).encode())
        gl.ShaderSource(shader,1,C.byref(source),None); gl.CompileShader(shader)
        ok,log=I(),C.create_string_buffer(16384)
        gl.GetShaderiv(shader,0x8B81,C.byref(ok)); gl.GetShaderInfoLog(shader,len(log),None,log)
        assert ok.value,log.value.decode()
        gl.AttachShader(program,shader); gl.DeleteShader(shader)
    gl.LinkProgram(program)
    gl.GetProgramiv(program,0x8B82,C.byref(ok)); gl.GetProgramInfoLog(program,len(log),None,log)
    assert ok.value,log.value.decode()
    gl.UseProgram(program)
    gl.BindVertexArray(obj(gl.GenVertexArrays))
    gl.Disable(0x0BE2); gl.Disable(0x0B71)
    def loc(name): return gl.GetUniformLocation(program,name.encode())
    def scalar(name,value): gl.Uniform1f(loc(name),value)
    def vector(name,*value): gl.Uniform3f(loc(name),*value)
    def integer(name,value): gl.Uniform1i(loc(name),value)
    def camera_matrix(values): gl.UniformMatrix4fv(loc('vc_view_to_world'),1,False,(F*16)(*values))
    def mat3(values): camera_matrix([*values[:3],0,*values[3:6],0,*values[6:],0,0,0,0,1])
    def texture(unit,red):
        gl.ActiveTexture(0x84C0+unit)
        tex=obj(gl.GenTextures); gl.BindTexture(TEXTURE,tex)
        gl.TexImage2D(TEXTURE,0,0x8814,1,1,0,RGBA,FLOAT,(F*4)(red,red,red,1))
        for param,value in ((0x2801,0x2600),(0x2800,0x2600),(0x2802,0x2901),(0x2803,0x2901)):
            gl.TexParameteri(TEXTURE,param,value)
        return tex
    depth=texture(0,1); weather=texture(1,.7); next_weather=texture(2,.2)
    volume=obj(gl.GenTextures)
    def noise(data):
        gl.ActiveTexture(0x84C3); gl.BindTexture(0x806F,volume)
        gl.TexImage3D(0x806F,0,0x8229,64,64,64,0,0x1903,0x1401,(C.c_ubyte*len(data)).from_buffer_copy(data))
        for param,value in ((0x2801,0x2601),(0x2800,0x2601),(0x2802,0x2901),(0x2803,0x2901),(0x8072,0x2901)):
            gl.TexParameteri(0x806F,param,value)
    noise(bytes([128])*(64**3))
    output=texture(4,0)
    gl.BindFramebuffer(FRAMEBUFFER,obj(gl.GenFramebuffers))
    gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT,TEXTURE,output,0)
    assert gl.CheckFramebufferStatus(FRAMEBUFFER)==0x8CD5
    for name,unit in [('depthMap',0),('cloud_noise_texture',1),('cloud_noise_texture_next',2),('diffuseMap',3)]:
        integer(name,unit)
    near,far=.1,100000.
    a=(far+near)/(near-far); b=2*far*near/(near-far)
    inverse=[1,0,0,0, 0,1,0,0, 0,0,0,1/b, 0,0,-1,a/b]
    gl.UniformMatrix4fv(loc('inv_proj'),1,False,(F*16)(*inverse))
    up=[1,0,0,0,-1,0,0,0,-1]
    down=[1,0,0,0,1,0,0,0,1]
    horizontal=[1,0,0,0,0,1,0,-1,0]
    mat3(up)
    gl.Uniform2f(loc('vc_target_size'),1,1); gl.Viewport(0,0,1,1)
    scalar('vc_thickness',250); scalar('vc_scale',2500)
    vector('vc_density',0,0,1); vector('vc_detail',0,0,0)
    gl.Uniform2f(loc('vc_scroll'),0,0)
    scalar('vc_coverage',.27); scalar('vc_amount',1); scalar('vc_variance',0); scalar('vc_blend',0)
    integer('vc_steps',64)
    vector('vc_camera',0,0,-100); vector('vc_sun_direction',0,0,1)
    vector('vc_sun_color',0,0,0); vector('vc_ambient',1,1,1); vector('vc_tint',1,1,1)

    def render(wall=None):
        d=1 if wall is None else (-a+b/wall)*.5+.5
        gl.ActiveTexture(0x84C0); gl.BindTexture(TEXTURE,depth)
        gl.TexImage2D(TEXTURE,0,0x8814,1,1,0,RGBA,FLOAT,(F*4)(d,0,0,1))
        gl.DrawArrays(4,0,3)
        pixel=(F*4)(); gl.ReadPixels(0,0,1,1,RGBA,FLOAT,pixel)
        assert gl.GetError()==0
        assert all(math.isfinite(v) for v in pixel) and 0<=pixel[3]<=1, list(pixel)
        return list(pixel)

    checks=0
    def check(name,actual,wanted,tolerance=2e-4):
        nonlocal checks
        assert max(abs(x-y) for x,y in zip(actual,wanted))<tolerance,(name,actual,wanted)
        checks+=1
    clear=[0,0,0,1]
    full=render(); assert full[3]<.8,full
    check('wall before layer',render(50),clear)
    assert full[3]<render(200)[3]<1
    mat3(down); check('looking away below layer',render(),clear)
    vector('vc_camera',0,0,400); mat3(up); check('looking away above layer',render(),clear)
    mat3(down); assert render()[3]<.8
    mat3(horizontal); check('parallel outside',render(),clear)
    vector('vc_camera',0,0,100)
    # Constant noise, fixed height, no direct light: independent Beer-Lambert reference.
    density=.025 # the uniform shape is above the fully dense threshold
    trans=math.exp(-density*100)
    top_fade=((.6-.55)/.45)**2*(3-2*(.6-.55)/.45)
    overhead=(1-top_fade)*.025*100
    source=(.55+.45*.4)*(.35+.65*math.exp(-overhead))
    # Integrate the shader's gradual atmospheric blend as well as extinction.
    rate=density+1/18000
    scattered=1-trans+(source-1)*density/rate*(1-math.exp(-rate*100))
    check('inside horizontal analytic transport',render(100),[scattered]*3+[trans],.001)
    for samples in (16,32,64,96,128):
        integer('vc_steps',samples)
        check('step independent '+str(samples),render(100),[scattered]*3+[trans],.001)
    scalar('vc_coverage',0); check('no coverage',render(),clear); scalar('vc_coverage',.27)
    vector('vc_density',0,0,0); check('no density',render(),clear); vector('vc_density',0,0,1)
    scalar('vc_scale',0); check('no scale',render(),clear); scalar('vc_scale',2500)
    scalar('vc_blend',1); check('texture transition endpoint',render(100),clear)
    scalar('vc_blend',.37); middle=render(100); assert trans<middle[3]<1, middle
    scalar('vc_blend',0)
    vector('vc_tint',0,0,0); black=render(100); check('black tint absorbs',black,[0,0,0,trans],.001)
    vector('vc_tint',1,1,1)
    unlit=render(100); vector('vc_sun_color',2,1,.5); lit=render(100)
    assert lit[0]>unlit[0] and lit[0]>lit[1]>lit[2]
    check('light preserves opacity',[lit[3]],[unlit[3]])
    for gain in (0,.25,.5,1,2):
        vector('vc_sun_color',2*gain,gain,.5*gain)
        check('sunlight gain preserves ambient and opacity',render(100),
              [unlit[i]+gain*(lit[i]-unlit[i]) for i in range(3)]+[lit[3]])
    vector('vc_sun_color',2,1,.5)

    # Sunlight scattered inside the cloud must reach its shaded underside.
    # With neutral light/tint it stays neutral; warm sunsets and dim moonlight
    # must retain their authored color and intensity instead of gaining white.
    scalar('vc_coverage',1); vector('vc_density',0,0,2)
    vector('vc_camera',0,0,125); vector('vc_ambient',0,0,0)
    vector('vc_sun_color',1,1,1); noon=render(100)
    assert noon[0]>.25,('shaded daylight underside',noon)
    check('daylight underside stays neutral',noon[:3],[noon[0]]*3)
    vector('vc_sun_color',.01,.01,.01)
    check('moonlight remains dim',render(100),[v*.01 for v in noon[:3]]+[noon[3]])
    vector('vc_sun_color',0,0,0)
    check('no artificial daylight at night',render(100),[0,0,0,noon[3]])
    vector('vc_sun_direction',.9701425,0,.2425356); vector('vc_sun_color',2,.5,.1)
    sunset=render(100)
    check('sunset color preserved',[sunset[0],sunset[0]],[sunset[1]*4,sunset[2]*20])
    vector('vc_sun_direction',0,0,1); vector('vc_sun_color',2,1,.5)
    vector('vc_ambient',1,1,1); vector('vc_density',0,0,1); scalar('vc_coverage',.27)
    mat3(up); vector('vc_camera',0,0,-100)
    previous=1.0
    for amount in (0,.25,.5,.8,1,1.5,2):
        scalar('vc_amount',amount); value=render()
        assert value[3]<=previous+.0001,(amount,previous,value)
        previous=value[3]; checks+=1
        if amount==0: check('density zero clears clouds',value,clear)
    scalar('vc_amount',1)

    def weather_image(unit,tex,width,height,values):
        gl.ActiveTexture(0x84C0+unit); gl.BindTexture(TEXTURE,tex)
        gl.TexImage2D(TEXTURE,0,0x822E,width,height,0,0x1903,FLOAT,(F*len(values))(*values))
        gl.GenerateMipmap(TEXTURE)
        gl.TexParameteri(TEXTURE,0x2801,0x2703); gl.TexParameteri(TEXTURE,0x2800,0x2601)

    # Constant-texture cases from Linden's cloudsF.glsl alpha threshold. Even
    # maximally dense 3D noise and the local slider must not fill authored gaps.
    noise(bytes([255])*(64**3)); mat3(up); vector('vc_camera',0,0,-100)
    for weather_value,cover,detail_strength,variance,cloudy in (
        (.4,.27,0,0,False), (.45,.25,0,0,False), (.2,.35,0,0,False),
        (.4,.32,1,0,False), (.4,.7,0,1,False),
        (.7,.27,0,0,True), (.6,.15,2,0,True), (1,0,2,0,True), (.65,.1,0,1,True)):
        weather_image(1,weather,1,1,[weather_value])
        scalar('vc_coverage',cover); scalar('vc_variance',variance)
        vector('vc_detail',0,0,detail_strength)
        for amount in (.5,1,2):
            scalar('vc_amount',amount); result=render()
            if cloudy:
                assert result[3]<.8,('EEP cloud bank',weather_value,cover,detail_strength,variance,amount,result)
                checks+=1
            else:
                check('EEP clear sky cannot grow procedural clouds',result,clear)
    noise(bytes([128])*(64**3)); scalar('vc_amount',1); scalar('vc_coverage',.27)
    scalar('vc_variance',0); vector('vc_detail',0,0,0)

    # Fine 2D stripes must average into weather coverage instead of becoming
    # vertical density columns. Compare to an independent uniform mean under
    # overhead and low-angle sunlight, including differently sized EEP maps.
    mat3(up); vector('vc_camera',0,0,-100)
    for sun in ((0,0,1),(.9701425,0,.2425356)):
        vector('vc_sun_direction',*sun)
        weather_image(1,weather,1,1,[.6]); weather_image(2,next_weather,1,1,[.6])
        scalar('vc_blend',0); averaged=render()
        weather_image(1,weather,512,128,[.4 if x%2==0 else .8 for y in range(128) for x in range(512)])
        weather_image(2,next_weather,128,512,[.8 if x%2==0 else .4 for y in range(512) for x in range(128)])
        for blend in (0,.5,1):
            scalar('vc_blend',blend)
            for phase in range(8):
                vector('vc_camera',-(phase+.5)*2500/512,0,-100)
                check('no extruded weather stripes',render(),averaged,.0005)
    # Large EEP features must still control coverage after filtering.
    scalar('vc_blend',0)
    weather_image(1,weather,512,128,[.4 if x<256 else .8 for y in range(128) for x in range(512)])
    for y in range(4):
        for x in range(8):
            vector('vc_camera',-(x+.5)*2500,(y+.5)*5000,-100)
            if x<4:
                check('contiguous EEP opening across billows',render(),clear)
            else:
                assert render()[3]<.8,('contiguous EEP bank',x,y)
                checks+=1
    weather_image(1,weather,1,1,[.7]); weather_image(2,next_weather,1,1,[.2])
    vector('vc_sun_direction',0,0,1)

    # A narrow cloud must shadow its far side. The old first shadow sample
    # jumped past both edges, lighting both sides identically.
    noise(bytes(255 if x==1 else 0 for z in range(64) for y in range(64) for x in range(64)))
    scalar('vc_scale',128); scalar('vc_coverage',1); mat3(horizontal)
    vector('vc_camera',-8,0,100); vector('vc_ambient',0,0,0); vector('vc_sun_color',1,1,1)
    vector('vc_sun_direction',1,0,0); near_light=render(5)
    vector('vc_sun_direction',-1,0,0); far_light=render(5)
    assert near_light[0]>far_light[0]*1.1,('nearby billow self-shadow',near_light,far_light)
    check('light direction preserves cloud silhouette',[near_light[3]],[far_light[3]])
    checks+=1
    scalar('vc_scale',2500); scalar('vc_coverage',.27)
    vector('vc_ambient',1,1,1); vector('vc_sun_color',2,1,.5); vector('vc_sun_direction',0,0,1)

    data=bytearray(); state=0x729a4b31
    for _ in range(64**3):
        state^=(state<<13)&0xffffffff; state^=state>>17; state^=(state<<5)&0xffffffff
        data.append(state>>24)
    noise(data)
    # The new slider must create actual clear gaps across a 3D cloud field.
    weather_image(1,weather,1,1,[.5])
    mat3(up); gaps={.8:0,1:0}
    for y in range(8):
        for x in range(8):
            vector('vc_camera',x*333,y*333,-100)
            for amount in gaps:
                scalar('vc_amount',amount)
                gaps[amount]+=render()[3]>.995
    assert gaps[.8]>gaps[1],gaps
    checks+=1
    scalar('vc_amount',1); weather_image(1,weather,1,1,[.7])
    for reference,uploaded in camera_uploads():
        # The raw GL upload must survive GLM's column padding, including turns,
        # pitch, roll and translation. Directions must ignore matrix translation.
        assert len(uploaded)==16,'Cloud camera upload must contain 16 contiguous floats'
        assert max(abs(a-b) for a,b in zip(uploaded,reference))<.001,(uploaded,reference)
        vector('vc_camera',*reference[12:15])
        camera_matrix(reference); expected=render(4000)
        camera_matrix(uploaded)
        check('native camera rotation and translation',render(4000),expected,.0005)
        untranslated=reference[:12]+[0,0,0,1]
        camera_matrix(untranslated)
        check('ray excludes camera translation',render(4000),expected,.0005)
    mat3(horizontal)
    vector('vc_camera',200,400,100); original=render(400)
    vector('vc_camera',320200,320400,100); check('world period remains seamless',render(400),original,.0002)
    vector('vc_camera',200,400,100)
    gl.Uniform2f(loc('vc_scroll'),0,.1); scrolled=render(400)
    gl.Uniform2f(loc('vc_scroll'),0,0); vector('vc_camera',200,2400,100)
    check('wind advection matches world displacement',render(400),scrolled,.0002)
    vector('vc_camera',200,400,100)
    vector('vc_detail',.3,.6,1); detailed=render(400)
    assert detailed[3]>=original[3]
    for height in (-1,0,0.01,125,249.99,250,251):
        vector('vc_camera',0,0,height)
        for matrix in (up,down,horizontal):
            mat3(matrix); render(); checks+=1
    print(f'PASS: {checks} cloud GPU checks; {gl.GetString(0x1F01).decode()}')

    if '--preview' in sys.argv:
        width,height=960,540
        # The shipped cloud image is an uncompressed 8-bit paletted TGA.
        tga=(ROOT/'indra/newview/app_settings/windlight/clouds2.tga').read_bytes()
        assert tga[1:3]==bytes([1,1]) and tga[16]==8
        tw,th=struct.unpack_from('<HH',tga,12)
        start=18+tga[0]; palette=tga[start:start+768]
        red=bytes(palette[index*3+2] for index in tga[start+768:start+768+tw*th])
        gl.ActiveTexture(0x84C1); gl.BindTexture(TEXTURE,weather)
        gl.TexImage2D(TEXTURE,0,0x8229,tw,th,0,0x1903,0x1401,(C.c_ubyte*len(red)).from_buffer_copy(red))
        gl.GenerateMipmap(TEXTURE)
        gl.TexParameteri(TEXTURE,0x2801,0x2703); gl.TexParameteri(TEXTURE,0x2800,0x2601)
        gl.ActiveTexture(0x84C4); gl.BindTexture(TEXTURE,output)
        gl.TexImage2D(TEXTURE,0,0x8814,width,height,0,RGBA,FLOAT,None)
        # Depth is deliberately full size, as in the viewer.
        gl.ActiveTexture(0x84C0); gl.BindTexture(TEXTURE,depth)
        gl.TexImage2D(TEXTURE,0,0x8814,width,height,0,RGBA,FLOAT,(F*(width*height*4))(*([1,0,0,1]*(width*height))))
        gl.Viewport(0,0,width,height); gl.Uniform2f(loc('vc_target_size'),width,height)
        angle=math.radians(20); c,s=math.cos(angle),math.sin(angle)
        mat3([1,0,0,0,-s,c,0,-c,-s])
        inv=list(inverse); inv[0]=width/height*.7; inv[5]=.7
        gl.UniformMatrix4fv(loc('inv_proj'),1,False,(F*16)(*inv))
        vector('vc_camera',0,0,-1000); vector('vc_sun_direction',.4,.5,.768)
        vector('vc_sun_color',1.7,1.5,1.2); vector('vc_ambient',.45,.55,.7)
        vector('vc_density',1,.526,1); vector('vc_detail',1,.526,1)
        scalar('vc_variance',0); scalar('vc_thickness',250); scalar('vc_scale',.4199*6000)
        vector('vc_tint',.82,.82,.82); scalar('vc_coverage',.27); scalar('vc_amount',.8); integer('vc_steps',96)
        if '--near' in sys.argv:
            vector('vc_camera',0,0,-350); scalar('vc_thickness',540)
            vector('vc_sun_direction',.93,0,.3676); vector('vc_sun_color',1.4,1.1,.9)
        gl.DrawArrays(4,0,3)
        pixels=(F*(width*height*4))(); gl.ReadPixels(0,0,width,height,RGBA,FLOAT,pixels)
        integer('vc_steps',64)
        query=obj(gl.GenQueries); timings=[]
        for _ in range(5):
            gl.BeginQuery(0x88BF,query); gl.DrawArrays(4,0,3); gl.EndQuery(0x88BF)
            elapsed=C.c_uint64(); gl.GetQueryObjectui64v(query,0x8866,C.byref(elapsed))
            timings.append(elapsed.value/1e6)
        print(f'Synthetic 960x540, 64 samples: {sorted(timings)[2]:.2f} ms GPU (cloud trace only)')
        rows=bytearray()
        for y in reversed(range(height)):
            rows.append(0)
            for x in range(width):
                index=(y*width+x)*4; t=pixels[index+3]
                sky=(.18+.15*(1-y/height),.38+.15*(1-y/height),.72)
                for i in range(3):
                    value=max(0,pixels[index+i]+sky[i]*t)
                    # Fixed Reinhard preview: retain HDR cloud shading instead
                    # of clipping it to white. The viewer has its own tonemap.
                    rows.append(round((value/(1+value))**(1/2.2)*255))
        def chunk(kind,data):
            return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data))
        png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',width,height,8,2,0,0,0))
        path=ROOT/'tmp/cloud-preview.png'; path.parent.mkdir(exist_ok=True)
        path.write_bytes(png+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b''))
        print(path)


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try: run(sdl,gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx); sdl.SDL_DestroyWindow(window); sdl.SDL_Quit()
