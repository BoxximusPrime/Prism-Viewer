"""Production SSGI GPU checks with physical geometry and an independent integral.

Run: .venv/Scripts/python.exe scripts/tests/test_ssgi_gpu.py [--benchmark | --jitter]
Uses a hidden SDL/OpenGL context; no viewer login. Benchmarks are synthetic.
"""
import ctypes as C
import math
import re
from pathlib import Path
import statistics
import sys

from test_exact_oit_gpu import context, U, I, F, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT, RGBA, FLOAT
from test_gtao_gpu import inverse, function

ROOT = Path(__file__).resolve().parents[2]
SHADERS = ROOT / 'indra/newview/app_settings/shaders/class1/deferred'
PREFACE = '\n'.join(re.findall(r'strdup\("(#define (?:GBUFFER_|GET_GBUFFER_).*?)\\n"\)',
    (ROOT / 'indra/llrender/llshadermgr.cpp').read_text())) + """
uniform sampler2D normalMap;
vec4 getNorm(vec2 tc) { return texture(normalMap,tc); }
vec4 getNormRaw(vec2 tc) { return texture(normalMap,tc); }
"""
VERTEX = '''out vec2 vary_fragcoord;
void main() { vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
gl_Position=vec4(p[gl_VertexID],0,1); vary_fragcoord=p[gl_VertexID]*0.5+0.5; }'''

# The fixture is an actual camera ray/plane intersection, not a constant-depth
# surface with impossible sideways normals. The foreground sheet never crosses
# wall-to-wall paths. The x=.25 sheet really does intersect them.
SCENE = '''
layout(location=0) out vec4 scene_depth;
layout(location=1) out vec4 scene_normal;
layout(location=2) out vec4 scene_donor;
uniform mat4 projection_matrix;
uniform vec2 screen_res;
uniform int scene_mode, donor_mode, blocker, receiver_detail, normal_mode;
uniform vec3 energy;
uniform float half_gap;
void main() {
    vec2 ndc=2.0*gl_FragCoord.xy/screen_res-1.0;
    vec3 ray=vec3((ndc.x+projection_matrix[2][0])/projection_matrix[0][0],
                  (ndc.y+projection_matrix[2][1])/projection_matrix[1][1],-1);
    float t=abs(half_gap/ray.x);
    vec3 n=vec3(ray.x<0 ? 1 : -1,0,0);
    bool valid=t>2.5 && t<8;
    bool donor=ray.x>0 && valid;
    if (scene_mode==1) {
        float floor_t=ray.y<0 ? -1.1/ray.y : 1e6;
        vec3 chair=ray*3.0;
        donor=abs(chair.x)<.9 && chair.y> -1.1 && chair.y<.6 && 3.0<floor_t;
        t=donor ? 3.0 : min(floor_t,5.5);
        n=donor ? vec3(0,0,1) : floor_t<5.5 ? vec3(0,1,0) : vec3(0,0,1);
        valid=true;
    }
    if (scene_mode>=2) {
        t=scene_mode==4 ? 4.0/(1.0+.2*ray.x) : 4.0;
        n=normalize(scene_mode==4 ? vec3(-.2,0,1) : vec3(0,0,1));
        valid=scene_mode!=3;
        donor=valid;
    }
    bool a=(int(floor((t-2.5)*4.0)) & 1)==0;
    vec3 light=donor ? energy : vec3(0);
    if ((donor_mode==1 && !a) || (donor_mode==2 && a)) light=vec3(0);
    if (donor_mode==3) light*=a ? vec3(1,0,0) : vec3(0);
    if (donor_mode==4) light*=a ? vec3(0) : vec3(0,1,0);
    if (donor_mode==5) light*=a ? vec3(1,0,0) : vec3(0,1,0);
    if (donor_mode==6 && (t<3.5 || t>4.5)) light=vec3(0);
    if (blocker==1 && abs(gl_FragCoord.x/screen_res.x-.5)<.035) {
        t=1.5; n=vec3(0,0,1); light=vec3(0); valid=true;
    }
    if (blocker>=2 && ray.x>0) {
        float sheet=.25/ray.x;
        if (sheet>2.5 && sheet<8 && sheet<t) {
            t=sheet; n=vec3(blocker==3 ? 1 : -1,0,0); light=vec3(0); valid=true;
        }
    }
    vec4 clip=projection_matrix*vec4(ray*t,1);
    if (scene_mode==0 && ray.x<0 && receiver_detail!=0 && (int(gl_FragCoord.x) & 1)==0) n=vec3(0,0,1);
    if (normal_mode!=0 && (normal_mode==3 || (normal_mode==1)==donor)) {
        vec3 position=ray*t;
        vec3 bump=.2*sin(position.yzx*60.0);
        n=normalize(n+bump-n*dot(n,bump));
    }
    scene_depth=vec4(valid ? clip.z/clip.w*.5+.5 : 1,0,0,0);
    scene_normal=vec4(n,.67);
    scene_donor=vec4(light,0);
}'''


def wall_reference(width, height, fov=60, donor_z=(-8, -2.5)):
    """Area quadrature of two diffuse parallel walls: cosR*cosD*dA/(pi*r^2).

    Integrates visible donor area independently of the GPU's ray distribution,
    intersection code and sample budget. Unit radiance, radius 3 m.
    """
    f=1/math.tan(math.radians(fov)/2)
    totals=[]
    for iy in range(4):
        for ix in range(8):
            x=int(width*.38)+(ix+.5)*(int(width*.44)-int(width*.38))/8
            y=height//3+(iy+.5)*(2*height//3-height//3)/4
            z=-abs(.6/((2*(x+.5)/width-1)/(f/(width/height))))
            yy=(2*(y+.5)/height-1)/f*(-z)
            total=0
            dz=(donor_z[1]-donor_z[0])/180
            for iz in range(180):
                donor_z_pos=donor_z[0]+(iz+.5)*dz
                ymax=-donor_z_pos/f
                dy=2*ymax/96
                for jy in range(96):
                    donor_y=-ymax+(jy+.5)*dy
                    r2=1.2**2+(donor_z_pos-z)**2+(donor_y-yy)**2
                    t=max(0,min(1,(math.sqrt(r2)-2.4)/.6))
                    total+=1.2**2/(math.pi*r2*r2)*(1-t*t*(3-2*t))*dz*dy
            totals.append(total)
    return statistics.mean(totals)


def run(sdl, gl, benchmark=False):
    signatures={'ActiveTexture':[U], 'Uniform2f':[I,F,F], 'Uniform3f':[I,F,F,F],
                'Uniform4f':[I,F,F,F,F], 'UniformMatrix4fv':[I,I,C.c_ubyte,C.POINTER(F)],
                'DrawBuffers':[I,C.POINTER(U)], 'ReadBuffer':[U], 'ClearColor':[F,F,F,F],
                'Clear':[U], 'Enable':[U], 'Disable':[U], 'BlendFunc':[U,U],
                'ColorMask':[C.c_ubyte,C.c_ubyte,C.c_ubyte,C.c_ubyte]}
    for name,args in signatures.items():
        setattr(gl,name,C.WINFUNCTYPE(None,*args)(sdl.SDL_GL_GetProcAddress(('gl'+name).encode())))

    def obj(fn):
        value=U(); fn(1,C.byref(value)); return value.value

    def compile_source(fragment, library=None, version=430):
        prog=gl.CreateProgram()
        stages=[(0x8B31,VERTEX),(0x8B30,fragment)]
        if library is not None: stages.append((0x8B30,library))
        for kind,source in stages:
            shader=gl.CreateShader(kind)
            text=C.c_char_p((f'#version {version} core\n'+source).encode())
            gl.ShaderSource(shader,1,C.byref(text),None); gl.CompileShader(shader)
            ok,log=I(),C.create_string_buffer(16384)
            gl.GetShaderiv(shader,0x8B81,C.byref(ok)); gl.GetShaderInfoLog(shader,len(log),None,log)
            assert ok.value,log.value.decode()
            gl.AttachShader(prog,shader); gl.DeleteShader(shader)
        gl.LinkProgram(prog)
        gl.GetProgramiv(prog,0x8B82,C.byref(ok)); gl.GetProgramInfoLog(prog,len(log),None,log)
        assert ok.value,log.value.decode()
        return prog

    helpers='uniform mat4 inv_proj;\n'+'\n'.join(function('deferredUtil.glsl',name) for name in
        ('vec2 getScreenCoordinate(vec2 screenpos)','vec3 getPositionWithNDC(vec3 ndc)',
         'vec4 getPositionWithDepth(vec2 pos_screen, float depth)'))
    helpers+=(SHADERS.parent/'environment/srgbF.glsl').read_text().split('vec3 ColorFromRadiance')[0]
    helpers+='uniform float sss_object, ssgi_avatar;\n'+function('globalF.glsl','vec4 encodeNormal(vec3 n, float env, float gbuffer_flag)')
    helpers+=function('globalF.glsl','vec4 decodeNormal(vec4 norm)')
    programs=[]
    for name in ('ssgiTraceF','ssgiFilterF','ssgiCompositeF','ssgiDebugF','ssgiResolveF','ssgiTemporalF','ssgiGeometryF'):
        body=(SHADERS/(name+'.glsl')).read_text()
        prefix=PREFACE
        if name=='ssgiCompositeF':
            declaration='uniform sampler2D normalMap;'
            split=prefix.index(declaration)
            body=prefix[:split]+body+prefix[split+len(declaration):]
        else: body=prefix+body
        library=(SHADERS/'ssgiUtilF.glsl').read_text() if name in ('ssgiTraceF','ssgiResolveF') else None
        programs.append(compile_source(body+helpers,library))
    trace,blur,compose,debug,resolve,temporal,geometry_program=programs
    scene=compile_source(SCENE)
    camera=compile_source((SHADERS/'taaCameraF.glsl').read_text())
    gl.BindVertexArray(obj(gl.GenVertexArrays))
    gl.BindFramebuffer(FRAMEBUFFER,obj(gl.GenFramebuffers))

    def uniform(prog,name,*values,integer=False):
        gl.UseProgram(prog)
        loc=gl.GetUniformLocation(prog,name.encode())
        getattr(gl,'Uniform1i' if integer else f'Uniform{len(values)}f')(loc,*values)

    def matrix(prog,name,value):
        gl.UseProgram(prog)
        data=(F*16)(*(value[r][c] for c in range(4) for r in range(4)))
        gl.UniformMatrix4fv(gl.GetUniformLocation(prog,name.encode()),1,0,data)

    def upload(tex,w,h,values=None,internal=0x881A):
        gl.ActiveTexture(0x84C0+15); gl.BindTexture(TEXTURE,tex)
        for p in (0x2800,0x2801): gl.TexParameteri(TEXTURE,p,0x2600)
        for p in (0x2802,0x2803): gl.TexParameteri(TEXTURE,p,0x812F)
        data=(F*len(values))(*values) if values is not None else None
        gl.TexImage2D(TEXTURE,0,internal,w,h,0,RGBA,FLOAT,data)

    def bind(prog,name,unit,tex):
        gl.ActiveTexture(0x84C0+unit); gl.BindTexture(TEXTURE,tex)
        uniform(prog,name,unit,integer=True)

    def target(textures):
        nonlocal target_width,target_height
        for i in range(3):
            gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT+i,TEXTURE,textures[i] if i<len(textures) else 0,0)
        gl.DrawBuffers(len(textures),(U*len(textures))(*(COLOR_ATTACHMENT+i for i in range(len(textures)))))
        gl.ReadBuffer(COLOR_ATTACHMENT)
        assert gl.CheckFramebufferStatus(FRAMEBUFFER)==0x8CD5
        target_width,target_height=(gi_width,gi_height) if textures[0] in (raw,filtered) else (width,height)
        gl.Viewport(0,0,target_width,target_height)

    def draw(prog):
        gl.UseProgram(prog); gl.DrawArrays(4,0,3)

    def read(attachment=0):
        gl.ReadBuffer(COLOR_ATTACHMENT+attachment)
        pixels=(F*(target_width*target_height*4))()
        gl.ReadPixels(0,0,target_width,target_height,RGBA,FLOAT,pixels)
        assert gl.GetError()==0
        return pixels

    depth,normals,donors,raw,filtered,output,skin,albedo,material,resolved,motion=[obj(gl.GenTextures) for _ in range(11)]
    histories=[obj(gl.GenTextures) for _ in range(2)]
    guides=[obj(gl.GenTextures) for _ in range(2)]
    geometry_normals=obj(gl.GenTextures)
    history_index=0

    def resize(w,h,fov=60,half=False):
        nonlocal width,height,gi_width,gi_height
        width,height=w,h
        gi_width,gi_height=((w+1)//2,(h+1)//2) if half else (w,h)
        f=1/math.tan(math.radians(fov)/2)
        projection=[[f/(w/h),0,0,0],[0,f,0,0],[0,0,-100.1/99.9,-20/99.9],[0,0,-1,0]]
        for prog in (*programs,scene):
            uniform(prog,'screen_res',w,h)
            uniform(prog,'ssgi_half_res',gi_width,gi_height)
            matrix(prog,'inv_proj',inverse(projection)); matrix(prog,'projection_matrix',projection)
        matrix(camera,'taa_inv_projection',inverse(projection)); matrix(camera,'taa_previous_projection',projection)
        matrix(camera,'taa_previous_from_view',[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]])
        uniform(camera,'taa_rcp_res',1/w,1/h)
        for tex in (depth,normals,donors,raw,filtered,output,skin,resolved,motion,*histories,*guides):
            tw,th=(gi_width,gi_height) if tex in (raw,filtered) else (w,h)
            upload(tex,tw,th,internal=0x8814 if tex==depth else 0x881A)
        upload(albedo,1,1,(1,1,1,0)); upload(material,1,1,(1,.5,0,0))
        upload(geometry_normals,w,h,internal=0x822F) # GL_RG16F, as in the viewer.
        return projection

    width=height=gi_width=gi_height=target_width=target_height=0
    def prepare_geometry():
        bind(geometry_program,'depthMap',0,depth); bind(geometry_program,'normalMap',1,normals)
        # Match the viewer: attachment 0 retains donor radiance; the geometry
        # shader's output 0 is routed only to the RG16F second attachment.
        target((donors,geometry_normals))
        gl.DrawBuffers(1,(U*1)(COLOR_ATTACHMENT+1)); draw(geometry_program)

    def geometry(mode=0,donor=0,blocker=0,energy=(1,1,1),gap=.6,detail=False):
        for name,value in (('scene_mode',mode),('donor_mode',donor),('blocker',blocker),('receiver_detail',int(detail))):
            uniform(scene,name,value,integer=True)
        uniform(scene,'energy',*energy); uniform(scene,'half_gap',gap)
        target((depth,normals,donors)); draw(scene)
        prepare_geometry()
        bind(camera,'depthMap',0,depth); target((motion,)); draw(camera)

    def gather(quality=2,radius=3):
        bind(trace,'depthMap',0,depth); bind(trace,'normalMap',1,normals); bind(trace,'ssgiSource',2,donors)
        bind(trace,'ssgiGeometry',3,geometry_normals)
        uniform(trace,'ssgi_quality',quality,integer=True); uniform(trace,'ssgi_radius',radius)
        target((raw,)); draw(trace)

    def denoise(mode=1,radius=3):
        bind(blur,'depthMap',0,depth); bind(blur,'normalMap',1,normals)
        uniform(blur,'ssgi_radius',radius); uniform(blur,'ssgi_denoise_mode',mode,integer=True)
        for pass_index in range(1 if mode==0 else 3):
            src,dst=(raw,filtered) if pass_index%2==0 else (filtered,raw)
            bind(blur,'ssgiIndirect',2,src)
            uniform(blur,'ssgi_filter_stride',1<<pass_index,integer=True)
            target((dst,)); draw(blur)

    def receiver_resolve(quality=2):
        for unit,(name,tex) in enumerate((('depthMap',depth),('normalMap',normals),('ssgiIndirect',filtered),('ssgiSource',donors),('ssgiGeometry',geometry_normals))):
            bind(resolve,name,unit,tex)
        uniform(resolve,'ssgi_radius',3); uniform(resolve,'ssgi_quality',quality,integer=True)
        target((resolved,)); draw(resolve)

    def stabilize(valid=False,jitter=(0,0)):
        nonlocal history_index
        history_index=1-history_index
        for unit,(name,tex) in enumerate((('depthMap',depth),('normalMap',normals),('ssgiIndirect',resolved),
                ('ssgiHistory',histories[1-history_index]),('ssgiHistoryGuide',guides[1-history_index]),('taa_motion',motion),('ssgiGeometry',geometry_normals))):
            bind(temporal,name,unit,tex)
        uniform(temporal,'ssgi_radius',3); uniform(temporal,'ssgi_history_valid',int(valid),integer=True)
        uniform(temporal,'ssgi_jitter_delta',*jitter)
        matrix(temporal,'ssgi_previous_to_current',[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]])
        target((histories[history_index],guides[history_index])); draw(temporal)

    def composite(strength=1,diagnostic=0,sss=False,overlay=False,quality=2,avatar_strength=1,temporal_filter=False,history_valid=False):
        receiver_resolve(quality)
        if temporal_filter: stabilize(history_valid)
        for unit,(name,tex) in enumerate((('depthMap',depth),('normalMap',normals),
                ('ssgiIndirect',histories[history_index] if temporal_filter else resolved),
                ('diffuseRect',albedo),('specularRect',material))):
            bind(compose,name,unit,tex)
        uniform(compose,'ssgi_strength',strength); uniform(compose,'ssgi_debug',diagnostic,integer=True)
        uniform(compose,'ssgi_avatar_strength',avatar_strength)
        uniform(compose,'ssgi_sss_active',int(sss),integer=True); uniform(compose,'sss_params',1,2,.5,44)
        target((output,skin))
        if overlay:
            gl.ClearColor(.1,.2,.3,.7); gl.Clear(0x4000)
            gl.BlendFunc(1,1); gl.Enable(0x0BE2); gl.ColorMask(1,1,1,0)
        draw(compose)
        gl.ColorMask(1,1,1,1); gl.Disable(0x0BE2)

    def roi(pixels,channel=0):
        return [pixels[(y*width+x)*4+channel] for y in range(height//3,2*height//3)
                for x in range(int(width*.38),int(width*.44))]

    if benchmark:
        resize(3440,1440,half=True)
        query=obj(gl.GenQueries)
        for kind in (0,1):
            geometry(mode=kind,energy=(4,.8,.2))
            for quality in range(3):
                times=[]
                for frame in range(32):
                    gl.BeginQuery(0x88BF,query)
                    prepare_geometry()
                    gather(quality); denoise(); composite(quality=quality,temporal_filter=True,history_valid=frame>0)
                    gl.EndQuery(0x88BF)
                    ns=C.c_uint64(); gl.GetQueryObjectui64v(query,0x8866,C.byref(ns))
                    if frame>=16: times.append(ns.value/1e6)
                print(f'3440x1440 scene {kind}, quality {quality}, Balanced denoise: {statistics.median(times):.3f} ms',flush=True)
            stage_times=[]
            for frame in range(32):
                gl.BeginQuery(0x88BF,query); stabilize(True); gl.EndQuery(0x88BF)
                ns=C.c_uint64(); gl.GetQueryObjectui64v(query,0x8866,C.byref(ns))
                if frame>=16: stage_times.append(ns.value/1e6)
            print(f'  full-resolution spatial/temporal denoiser alone: {statistics.median(stage_times):.3f} ms',flush=True)
            assert max(read()[::4])>.01
        return

    if '--jitter' in sys.argv:
        taa=compile_source((SHADERS/'taaResolveF.glsl').read_text(),version=150)
        taa_buffers=[[obj(gl.GenTextures) for _ in range(3)] for _ in range(2)]
        def halton(index,base):
            result=0; fraction=1
            while index:
                fraction/=base; result+=fraction*(index%base); index//=base
            return result
        for kind,normal_mode in ((0,0),(1,0),(0,1),(0,2),(1,3)):
            uniform(scene,'normal_mode',normal_mode,integer=True)
            for denoise_mode in (0,1):
                projection=resize(256,192,half=True)
                for group in taa_buffers:
                    for tex in group: upload(tex,width,height)
                for name,value in (('taa_rcp_res',(1/width,1/height)),('taa_history_weight',(.97,)),
                        ('taa_motion_protection',(.4,)),('taa_clip_gamma',(1,)),('taa_transparency',(.2,))):
                    uniform(taa,name,*value)
                uniform(taa,'taa_static_details',1,integer=True)
                matrix(taa,'taa_previous_inv_projection',inverse(projection))
                matrix(taa,'taa_current_from_previous',[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]])
                previous_jitter=(0,0)
                sequences=[[],[],[]]
                for frame in range(48):
                    jitter=((halton(frame%8+1,2)-.5)/width,(halton(frame%8+1,3)-.5)/height)
                    jittered=[row[:] for row in projection]
                    for axis in (0,1): jittered[axis][2]-=2*jitter[axis]
                    for prog in (*programs,scene):
                        matrix(prog,'inv_proj',inverse(jittered)); matrix(prog,'projection_matrix',jittered)
                    matrix(camera,'taa_inv_projection',inverse(jittered))
                    uniform(camera,'taa_jitter',*jitter)
                    geometry(mode=kind,energy=(4,.8,.2)); gather(quality=1); denoise(denoise_mode); receiver_resolve(quality=1)
                    spatial=read()
                    stabilize(frame>0,tuple(a-b for a,b in zip(previous_jitter,jitter)))
                    accumulated=read(); ages=read(1)
                    for unit,(name,tex) in enumerate((('taa_current',histories[history_index]),
                            ('taa_opaque',histories[history_index]),('taa_history',taa_buffers[1-frame%2][0]),
                            ('taa_detail',taa_buffers[1-frame%2][1]),('taa_flicker',taa_buffers[1-frame%2][2]),
                            ('taa_motion',motion),('depthMap',depth))):
                        bind(taa,name,unit,tex)
                    matrix(taa,'taa_inv_projection',inverse(jittered))
                    uniform(taa,'taa_jitter',*jitter); uniform(taa,'taa_history_valid',int(frame>0),integer=True)
                    target(taa_buffers[frame%2]); draw(taa); final=read()
                    previous_jitter=jitter
                    if frame>=24:
                        indices=[(y*width+x)*4 for y in range(height//3,2*height//3)
                                 for x in range(int(width*.38),int(width*.44))] if kind==0 else [
                                 (y*width+x)*4 for y in range(8,height//4) for x in range(width//4,3*width//4)]
                        for collection,pixels in zip(sequences,(spatial,accumulated,final)):
                            collection.append([pixels[k] for k in indices])
                rms=lambda seq: math.sqrt(statistics.mean((a-b)**2 for p,q in zip(seq,seq[1:]) for a,b in zip(p,q)))
                avg=statistics.mean(v for seq in sequences[1] for v in seq)
                print(f'Actual jitter chain: scene {kind}, normal {normal_mode}, denoise {denoise_mode}: mean {avg:.6f}, spatial delta {rms(sequences[0]):.6f}, temporal delta {rms(sequences[1]):.6f}, final TAA delta {rms(sequences[2]):.6f}, age {statistics.mean(abs(ages[k+3]) for k in indices):.2f}',flush=True)
                assert avg>.1, 'Stability must not come from removing the bounce'
                assert rms(sequences[2])/avg<.006, 'Stationary geometry must not twinkle through the TAA sequence'
                assert min(abs(ages[k+3]) for k in indices)>15.9, 'Jitter must retain valid grazing-surface history'
        print('PASS: 30 complete SSGI-to-TAA jitter checks (Light and Balanced denoising)')
        return

    checks=0
    # Pixelwise superposition, hue preservation, real blockers, false blockers,
    # odd/even dimensions and comparison to an independent area integral.
    for w,h in ((256,192),(257,193)):
        resize(w,h)
        reference=wall_reference(w,h)
        for quality in range(3):
            cases={}
            for donor_mode in range(7):
                geometry(donor=donor_mode); gather(quality)
                cases[donor_mode]=read()
            baseline=statistics.mean(roi(cases[0]))
            error=abs(baseline/reference-1)
            print(f'{w}x{h} quality {quality}: wall {baseline:.6f}, reference {reference:.6f}, error {error:.2%}',flush=True)
            assert error<.10,(quality,baseline,reference)
            assert max(abs(a-b-c) for a,b,c in zip(cases[0][::4],cases[1][::4],cases[2][::4]))<.002
            assert max(abs(a-b) for a,b in zip(cases[3][::4],cases[5][::4]))<1e-6
            assert max(abs(a-b) for a,b in zip(cases[4][1::4],cases[5][1::4]))<1e-6
            patch=statistics.mean(roi(cases[6]))
            patch_ref=wall_reference(w,h,donor_z=(-4.5,-3.5))
            assert abs(patch/patch_ref-1)<.12,(patch,patch_ref)
            for blocker in (1,2,3):
                geometry(blocker=blocker); gather(quality)
                blocked=statistics.mean(roi(read()))
                print(f'  blocker {blocker}: {blocked/baseline:.2%} retained',flush=True)
                if blocker==1: assert abs(blocked/baseline-1)<.02
                else: assert blocked<baseline*.12
            geometry(energy=(32,8,2)); gather(quality)
            bright=read()
            assert max(abs(a-4*b) for a,b in zip(bright[::4],bright[1::4]))<.015
            checks+=9
        for kind in (2,3,4):
            geometry(mode=kind,energy=(8,8,8)); gather(); denoise(); composite()
            assert max(abs(v) for v in read()[::4])<1e-5,kind
            checks+=1

    # Resolution and FOV changes must preserve the geometric form factor.
    for w,h,fov in ((514,386,60),(257,193,50),(257,193,70)):
        resize(w,h,fov); geometry(); gather()
        measured=statistics.mean(roi(read())); ref=wall_reference(w,h,fov)
        print(f'{w}x{h}, FOV {fov}: {measured:.6f}, reference {ref:.6f}',flush=True)
        assert abs(measured/ref-1)<.08,(measured,ref)
        checks+=1

    # A 2 cm wall separation must not be erased by the former 4 cm rejection.
    resize(257,193,.6); geometry(gap=.01); gather(radius=.1)
    contact=statistics.mean(roi(read()))
    assert contact>.05,contact
    checks+=1

    # Exercise the actual half-resolution production path and its direct repair.
    # Orthogonal receiver normals missing from all four neighboring primary
    # samples must match their independently evaluated full-resolution rays.
    for w,h in ((256,192),(257,193)):
        resize(w,h); geometry(detail=True); gather(); direct=read()
        resize(w,h,half=True); geometry(detail=True); gather(); denoise(); composite()
        repaired=read()
        unsupported=[]
        for y in range(h//3,2*h//3):
            for x in range(int(w*.38),int(w*.44)):
                base=math.floor((x+.5)/w*gi_width-.5)
                sample_x=[math.floor((i+.5)/gi_width*w) for i in (base,base+1)]
                if all(sx%2!=x%2 for sx in sample_x): unsupported.append((y*w+x)*4)
        assert len(unsupported)>100
        assert statistics.mean(direct[i] for i in unsupported)>.05
        assert max(abs(repaired[i]-.96*direct[i]) for i in unsupported)<.001
        composite(diagnostic=3); assert tuple(read())==tuple(repaired)
        composite(diagnostic=1,strength=2); incoming=read()
        assert max(abs(incoming[i]-2*direct[i]) for i in unsupported)<.001
        print(f'{w}x{h}: {len(unsupported)} unsupported receivers match direct rays',flush=True)
        checks+=5

    # Full-resolution receiver coverage, filter energy/edges, materials and SSS.
    for w,h in ((64,48),(65,49)):
        resize(w,h); geometry(mode=2)
        normal_data=[v for y in range(h) for x in range(w) for v in ((1,0,0,.67) if x%2==0 else (0,0,1,.67))]
        upload(normals,w,h,normal_data)
        for mode in range(3):
            upload(raw,w,h,(1,.5,.25,1)*(w*h)); denoise(mode)
            composite(); pixels=read()
            assert min(pixels[::4])>.957 and max(pixels[::4])<.961,(w,h,mode,min(pixels[::4]),max(pixels[::4]))
            checks+=1
        for normal_edge in (True,False):
            ns=[v for y in range(h) for x in range(w) for v in (0,0,-1 if normal_edge and x>=w//2 else 1,.67)]
            ds=[v for y in range(h) for x in range(w) for v in ((.98 if x>=w//2 else .96),0,0,0)]
            upload(normals,w,h,ns)
            if not normal_edge: upload(depth,w,h,ds,0x8814)
            for mode in range(3):
                values=[v for y in range(h) for x in range(w) for v in (1 if x<w//2 else 0,0,0,1)]
                upload(raw,w,h,values); denoise(mode)
                pixels=read()
                assert max(pixels[(y*w+x)*4] for y in range(h) for x in range(w//2+2,w))<.001
                checks+=1
        geometry(mode=2)
        upload(filtered,w,h,(1,.5,.25,1)*(w*h))
        for flag,base,orm,expected in (
            (.67,(1,1,1,0),(1,.5,0,0),.96),
            (.67,(.04,.04,.04,0),(1,.5,0,0),.0384),
            (.67,(1,1,1,0),(1,.5,1,0),0),
            (.67,(1,1,1,0),(0,.5,0,0),0),
            (.67,(1,1,1,0),(.5,.5,.8,0),.096),
            (.34,(1,1,1,0),(1,.5,0,0),1),
            (.34,(1,1,1,1),(1,.5,0,0),0),
            (.79,(1,1,1,0),(1,.5,0,0),.96),
            (0,(1,1,1,0),(1,.5,0,0),0),
            (1,(1,1,1,0),(1,.5,0,0),0),
        ):
            upload(normals,w,h,(0,0,1,flag)*(w*h)); upload(albedo,1,1,base); upload(material,1,1,orm)
            composite(sss=True); applied=read(); skin_pixels=read(1)
            assert max(abs(v-expected) for v in applied[::4])<.001,(flag,orm,applied[0],expected)
            assert max(skin_pixels[::4])==0 if flag!=.79 else max(abs(a-b) for a,b in zip(applied,skin_pixels))<1e-5
            composite(diagnostic=3); assert tuple(read())==tuple(applied)
            composite(diagnostic=4); assert max(abs(v-expected) for v in read()[::4])<.001
            composite(diagnostic=1,strength=2)
            assert max(abs(v-(0 if flag in (0,1) else 2)) for v in read()[::4])<.001
            composite(strength=0); assert max(read()[::4])==0
            composite(strength=30,overlay=True); overlaid=read()
            assert max(abs(v-(.1+30*expected)) for v in overlaid[::4])<.04
            assert max(abs(v-.7) for v in overlaid[3::4])<.001
            checks+=8
    # Avatar identity is independent of SSS and respects legacy/PBR response.
    resize(64,48); geometry(mode=2)
    upload(filtered,width,height,(1,.5,.25,1)*(width*height))
    for flag in (.34,.46,.67,.79,.38,.50,.71,.83):
        is_avatar=flag in (.38,.50,.71,.83)
        is_skin=flag in (.46,.79,.50,.83)
        response=.96 if flag>.6 else 1
        upload(normals,width,height,(0,0,1,flag)*(width*height))
        upload(albedo,1,1,(1,1,1,0)); upload(material,1,1,(1,.5,0,0))
        for multiplier in (0,.5,1,2):
            composite(sss=True,avatar_strength=multiplier)
            expected=response*(multiplier if is_avatar else 1)
            assert max(abs(v-expected) for v in read()[::4])<.002,(flag,multiplier)
            assert max(abs(v-(expected if is_skin else 0)) for v in read(1)[::4])<.002
            checks+=2

    # Noisy lighting on a translating avatar, with and without subpixel jitter.
    # Compare against the known moving illumination field, excluding boundaries.
    # The GI-only filter must work without TAA and must not blur material color.
    resize(64,48); geometry(mode=2)
    upload(normals,width,height,(0,0,1,.71)*(width*height))
    ds=(100.1/99.9-20/99.9/2)*.5+.5
    upload(depth,width,height,(ds,0,0,0)*(width*height),0x8814)
    for speed,jittered in ((0,False),(.65,False),(.65,True),(2,True)):
        raw_errors=[]; spatial_errors=[]; temporal_errors=[]
        previous_jitter=0
        for frame in range(48):
            jitter=(0,.25,-.25,.375,-.125,.125,-.375,.4375)[frame%8] if jittered else 0
            clean=[]; noisy=[]
            for y in range(height):
                for x in range(width):
                    value=.6+.2*math.sin((x-speed*frame-jitter)*.15)
                    noise=math.sin(x*127.1+y*311.7+frame*74.7)*43758.5453
                    noise=(noise-math.floor(noise)-.5)*.8
                    clean.append(value)
                    noisy.extend((value+noise, (value+noise)*.5, (value+noise)*.25,1))
            upload(resolved,width,height,noisy)
            upload(motion,width,height,(-speed/width,0,2,0)*(width*height))
            # Separate histories are unnecessary for the stateless comparison:
            # run it into the next target then restore the index before accumulation.
            saved=history_index
            stabilize(False); spatial=read()
            history_index=saved
            stabilize(frame>0,((previous_jitter-jitter)/width,0)); stable=read()
            previous_jitter=jitter
            if frame>=12:
                for y in range(3,height-3):
                    for x in range(10,width-10):
                        k=y*width+x
                        raw_errors.append((noisy[k*4]-clean[k])**2)
                        spatial_errors.append((spatial[k*4]-clean[k])**2)
                        temporal_errors.append((stable[k*4]-clean[k])**2)
        rms=lambda values:math.sqrt(statistics.mean(values))
        ratio=rms(temporal_errors)/rms(raw_errors)
        print(f'GI history: motion {speed} px/frame, jitter {jittered}: raw RMS {rms(raw_errors):.5f}, spatial {rms(spatial_errors):.5f}, temporal {rms(temporal_errors):.5f}',flush=True)
        assert ratio<.28,(speed,jittered,ratio)
        assert rms(temporal_errors)<rms(spatial_errors)*.7
        checks+=2

    # A changed light clears immediately even when the surface's motion is valid.
    upload(resolved,width,height,(0,0,0,1)*(width*height))
    stabilize(True); assert max(read()[::4])==0
    checks+=1
    # History must be rejected for depth/normal/class mismatches, untracked
    # deformation, offscreen motion, and explicitly invalid/reset frames.
    for reason in ('depth','normal','avatar','reactive','offscreen','reset'):
        upload(histories[history_index],width,height,(.8,.4,.2,3 if reason=='depth' else 2)*(width*height))
        n=(1,0,0) if reason=='normal' else (0,0,1)
        upload(guides[history_index],width,height,(*n,16 if reason=='avatar' else -16)*(width*height))
        # Broad local range allows stale values through color clipping; geometry
        # rejection itself must prevent them from contributing.
        values=[v for y in range(height) for x in range(width) for v in ((.2 if x%2==0 else 1),.3,.1,0)]
        upload(resolved,width,height,values)
        upload(motion,width,height,(2 if reason=='offscreen' else 0,0,2,1 if reason=='reactive' else 0)*(width*height))
        stabilize(reason!='reset'); result=read()
        assert max(abs(result[k]-values[k]) for k in range(0,len(values),4))<.002,reason
        checks+=1
    # Spatial repair filtering cannot spread light across a normal boundary.
    ns=[v for y in range(height) for x in range(width) for v in (0,0,1 if x<width//2 else -1,.71)]
    values=[v for y in range(height) for x in range(width) for v in ((1 if x<width//2 else 0),0,0,1)]
    upload(normals,width,height,ns); upload(resolved,width,height,values)
    stabilize(False); result=read()
    assert max(result[(y*width+x)*4] for y in range(height) for x in range(width//2,width))==0
    checks+=1
    assert gl.GetError()==0
    print(f'PASS: {checks} SSGI GPU checks; physical transport, independent reference, blockers, contact, receiver coverage, filtering, materials, SSS and diagnostics')


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try:
        print('GPU:',gl.GetString(0x1F01).decode(),flush=True)
        run(sdl,gl,'--benchmark' in sys.argv)
    finally:
        sdl.SDL_GL_DestroyContext(ctx); sdl.SDL_DestroyWindow(window); sdl.SDL_Quit()
