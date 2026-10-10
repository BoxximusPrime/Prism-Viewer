"""Render production hair shadow fragments and sample their deep-opacity atlas.

Run: .venv/Scripts/python.exe scripts/tests/test_hair_density_gpu.py
Hidden real OpenGL tests, independent of a logged-in viewer or scene assets.
"""
import ctypes as C
import math
from test_taa_gpu import GPU, SHADERS, W, H, context
from test_exact_oit_gpu import U, I, F, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT


def run(sdl, gl):
    gpu = GPU(sdl, gl)
    for name,args in {'BlendFunc':[U,U], 'DepthMask':[C.c_ubyte], 'DepthFunc':[U]}.items():
        setattr(gl,name,C.WINFUNCTYPE(None,*args)(sdl.SDL_GL_GetProcAddress(('gl'+name).encode())))
    read=lambda name:(SHADERS/'class1/deferred'/f'{name}.glsl').read_text()
    checks=0
    def check(condition,message):
        nonlocal checks
        assert condition,message
        checks+=1

    vertex='''uniform float test_depth; uniform int reverse;
out vec2 vary_texcoord0; out vec4 vertex_color; out vec4 post_pos;
out float target_pos_x; out float pos_w;
void main() {
 vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
 int i=reverse!=0 ? 2-gl_VertexID : gl_VertexID;
 gl_Position=vec4(p[i],test_depth*2.0-1.0,1);
 vary_texcoord0=vec2(.5); vertex_color=vec4(1); post_pos=gl_Position;
 target_pos_x=0; pos_w=1;
}'''
    def program(fragment, enabled=True):
        p=gl.CreateProgram()
        for kind,source in [(0x8B31,vertex),(0x8B30,fragment),(0x8B30,read('hairDepthUtil'))]:
            shader=gl.CreateShader(kind)
            text=C.c_char_p(('#version 430 core\n'+('#define HAIR_DENSITY_MAPS 1\n' if enabled else '')+source).encode())
            gl.ShaderSource(shader,1,C.byref(text),None); gl.CompileShader(shader)
            ok=I(); log=C.create_string_buffer(8192)
            gl.GetShaderiv(shader,0x8B81,C.byref(ok)); gl.GetShaderInfoLog(shader,len(log),None,log)
            check(ok.value,log.value.decode())
            gl.AttachShader(p,shader); gl.DeleteShader(shader)
        gl.LinkProgram(p)
        gl.GetProgramiv(p,0x8B82,C.byref(ok)); gl.GetProgramInfoLog(p,len(log),None,log)
        check(ok.value,log.value.decode())
        for i in range(3): gpu.uniform(p,f'hair_depth_projection[{i}]',-2,-1,0,1)
        gpu.uniform(p,'test_depth',.2)
        return p

    bounds=gpu.texture(); density=gpu.texture(); output=gpu.texture()
    depth=gpu.texture(depth=True)
    white=gpu.texture([1,1,1,1]*(W*H))
    gl.FramebufferTexture2D(FRAMEBUFFER,0x8D00,TEXTURE,depth,0)
    gl.Disable(0x0B44); gl.Disable(0x0BE2); gl.Enable(0x0B71); gl.DepthFunc(0x0201)
    middle=((H//2)*W+W//2)*4
    def pixel(texture): return gpu.read(texture)[middle:middle+4]
    def attach(texture):
        gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT,TEXTURE,texture,0)
    def clear(texture,rgba):
        attach(texture); gl.ColorMask(1,1,1,1); gl.DepthMask(1)
        gl.ClearColor(*rgba); gl.Clear(0x4100)
    def capture(prog,phase,z,alpha=1,hair=True,reverse=False,blend=True):
        for name,value in [('hair_depth_pass',phase),('hair_depth_object',int(hair)),
                           ('hair_depth_blend',int(blend)),('reverse',int(reverse))]:
            gpu.uniform(prog,name,value,integer=True)
        gpu.uniform(prog,'test_depth',z); gpu.uniform(prog,'minimum_alpha',.5)
        gpu.uniform(prog,'color',1,1,1,1)
        gpu.upload(white,[1,1,1,alpha]*(W*H))
        gpu.bind(prog,'diffuseMap',0,white); gpu.bind(prog,'diffuseRect',0,white)
        gpu.bind(prog,'hairBoundsMap',1,bounds if phase==3 else white)
        if phase==3:
            gl.Disable(0x0B71); gl.DepthMask(0); gl.Enable(0x0BE2); gl.BlendFunc(1,1)
            gl.ColorMask(1,1,1,1); target=density
        else:
            gl.Enable(0x0B71); gl.DepthMask(1); gl.Disable(0x0BE2)
            gl.ColorMask(phase==2,phase==1,0,0); target=bounds
        gpu.draw(prog,target)

    opaque=program(read('shadowF'))
    blended=program('uniform sampler2D diffuseRect; vec4 diffuseLookup(vec2 tc) { return texture(diffuseRect,tc); }\n'+read('shadowAlphaMaskF'))
    pbr_blended=program(read('pbrShadowAlphaBlendF'))
    mask=program(read('pbrShadowAlphaMaskF'))
    avatar=program(read('avatarShadowF'))
    query=program('''uniform float fallback; uniform vec3 origin; uniform int local;
float hairSunShadow(vec3 pos,float fallback);
float hairLocalShadow(vec3 pos,vec3 origin,float fallback);
out vec4 frag_color;
void main() { float v=local!=0 ? hairLocalShadow(vec3(0),origin,fallback) : hairSunShadow(vec3(0),fallback);
 frag_color=vec4(v,v,v,1); }''')
    gpu.uniform(query,'hair_depth_focus',0,0,0,.032)
    gpu.uniform(query,'hair_params',.35,.7,1,1)
    gpu.uniform(query,'hair_depth_valid',1,1,1)
    gpu.uniform(query,'hair_depth_origin[0]',0,0,2)
    gpu.uniform(query,'hair_depth_origin[1]',0,0,3)
    def visibility(z,fallback=.03,local=0,origin=(0,0,2)):
        gl.Disable(0x0BE2); gl.Disable(0x0B71); gl.ColorMask(1,1,1,1)
        for i in range(3):
            gpu.matrix(query,f'hair_depth_matrix[{i}]',[[0,0,0,.5],[0,0,0,.5],[0,0,0,z],[0,0,0,1]])
        gpu.uniform(query,'fallback',fallback); gpu.uniform(query,'local',local,integer=True)
        gpu.uniform(query,'origin',*origin)
        gpu.bind(query,'hairBoundsMap',1,bounds); gpu.bind(query,'hairDensityMap',2,density)
        gpu.draw(query,output)
        value=pixel(output)[0]
        check(math.isfinite(value) and 0<=value<=1,('bounded visibility',value))
        return value

    def scene(prog,alpha=1,layers=(.2,),blocker=None,blend=True):
        clear(bounds,(10000,10000,0,0)); clear(density,(0,0,0,0))
        # Classifying hair cannot overwrite the solid-blocker channel.
        capture(prog,1,.1,alpha)
        if blocker is not None: capture(avatar,1,blocker,hair=False)
        attach(bounds); gl.DepthMask(1); gl.Clear(0x0100)
        for z in layers: capture(prog,2,z,alpha,blend=blend)
        for i,z in enumerate(layers): capture(prog,3,z,alpha,reverse=bool(i%2),blend=blend)

    for prog in (blended,pbr_blended):
        scene(prog,0)
        check(pixel(density)==[0,0,0,0],'transparent strands add no optical depth')
        check(visibility(.4)==1,'transparent strands transmit all available light')
        values=[]
        for alpha in (.1,.3,.7,1):
            scene(prog,alpha)
            values.append(visibility(.4))
            check(abs(values[-1]-(1-.85*alpha))<.002,'actual alpha controls optical depth continuously')
        check(all(a>b for a,b in zip(values,values[1:])),'denser strands transmit less')
        scene(prog,.3,(.2,.24,.28))
        check(abs(visibility(.6)-(1-.85*.3)**3)<.003,'overlapping cards multiply transmission')
        first=pixel(density)
        scene(prog,.3,(.28,.24,.2))
        check(max(abs(a-b) for a,b in zip(first,pixel(density)))<.002,'density is independent of draw order')
        scene(prog,.3,(.2,.7))
        check(visibility(.22)>visibility(.3)>visibility(.9),'receiver depth excludes hair behind it')
        scene(prog,.3,blocker=.15)
        check(visibility(.3)==0,'ordinary geometry blocks light before the hair')
        scene(prog,.3,blocker=.5)
        check(visibility(.3)>0 and visibility(.6)==0,'blocker behind the receiver does not darken its hair')
    scene(opaque,1,(.2,.28))
    check(visibility(.6)<.04,'both cylinder crossings add density without requiring a closed surface match')
    scene(mask,.1)
    check(pixel(density)==[0,0,0,0],'cutout threshold is preserved')
    scene(mask,.9)
    check(abs(visibility(.5)-.15)<.002,'surviving cutouts contribute a full crossing')
    scene(blended,.6,blend=False)
    check(abs(visibility(.5)-.15)<.002,'legacy cutouts preserve coverage without shadow stippling')
    scene(blended,.5)
    gpu.uniform(query,'hair_params',.35,.7,1,.25); thin=visibility(.5)
    gpu.uniform(query,'hair_params',.35,.7,1,4); thick=visibility(.5)
    check(thin>thick,'existing optical thickness controls density attenuation')
    gpu.uniform(query,'hair_params',.35,.7,1,1)
    check(visibility(.5,local=1)==visibility(.5),'selected local light and sun use the same density model')
    check(abs(visibility(.5,local=1,origin=(5,0,0))-.03)<.0001,'unmapped local lights retain ordinary visibility')
    gpu.uniform(query,'hair_depth_valid',0,0,0)
    check(abs(visibility(.5)-.03)<.0001,'missing maps use the existing shadow')
    gpu.uniform(query,'hair_depth_valid',1,1,1)
    gpu.uniform(query,'hair_params',.35,.7,0,1)
    check(abs(visibility(.5)-.03)<.0001,'zero transmission skips density sampling')
    gpu.uniform(query,'hair_params',.35,.7,1,1)
    check(abs(visibility(1.1)-.03)<.0001,'out-of-frustum receivers use the existing shadow')
    # Atlas taps cannot borrow density or blocker depth from the neighbouring light.
    gpu.upload(bounds,[v for y in range(H) for x in range(W) for v in (.2,.1 if x<W//3 else 10000,0,0)])
    check(visibility(.5)==0 and visibility(.5,local=1)>0,'light atlas tiles are isolated')
    gpu.upload(density,[float('inf')]*4*(W*H))
    check(visibility(.5,local=1)==0,'saturated density stays finite and opaque')
    # Reconstruct perspective depths in metres as well as orthographic sun depths.
    distance_query=program('''uniform float sample_depth; uniform vec4 sample_projection;
float hairDepthDistance(float depth,vec4 projection);
out vec4 frag_color;
void main() { frag_color=vec4(hairDepthDistance(sample_depth,sample_projection)); }''')
    for near,far in ((.01,5),(5,12),(50,70)):
        a=-(far+near)/(far-near); b=-2*far*near/(far-near)
        gpu.uniform(distance_query,'sample_projection',a,b,-1,0)
        for distance in (near,near+.001,(near+far)/2,far):
            gpu.uniform(distance_query,'sample_depth',(-a+b/distance)*.5+.5)
            gpu.draw(distance_query,output)
            check(abs(pixel(output)[0]-distance)<max(.001,distance*.001),
                  ('perspective axial distance',near,far,distance,pixel(output)[0]))
    fallback_query=program('''float hairSunShadow(vec3 p,float fallback);
float hairLocalShadow(vec3 p,vec3 l,float fallback);
out vec4 frag_color;
void main() { frag_color=vec4(hairSunShadow(vec3(0),.25),hairLocalShadow(vec3(0),vec3(1),.75),0,1); }''',False)
    gpu.draw(fallback_query,output)
    check(pixel(output)==[.25,.75,0,1],'smaller texture-unit GPUs retain existing shadows')
    for sampler in ('hairBoundsMap','hairDensityMap'):
        check(gl.GetUniformLocation(fallback_query,sampler.encode())==-1,'fallback consumes no extra samplers')
    print(f'Passed {checks} hair-density GPU checks on {gl.GetString(0x1F01).decode()}')


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try: run(sdl,gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx); sdl.SDL_DestroyWindow(window); sdl.SDL_Quit()
