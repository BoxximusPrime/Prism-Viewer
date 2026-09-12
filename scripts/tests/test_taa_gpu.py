"""Exercise production TAA shaders on the bundled hidden SDL/OpenGL context.

No viewer login. Checks subpixel convergence, camera/skinned motion, D24 motion
coverage, disocclusion, reactive transparency, history reset and HDR/alpha safety.
Run: .venv/Scripts/python.exe scripts/tests/test_taa_gpu.py
"""
import ctypes as C
import math
from pathlib import Path
import re
import statistics
import sys

from test_exact_oit_gpu import context, U, I, F, P, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT, RGBA, FLOAT
from test_gtao_gpu import inverse, png

ROOT = Path(__file__).resolve().parents[2]
SHADERS = ROOT / 'indra/newview/app_settings/shaders'
W, H = 96, 64


class GPU:
    def __init__(self, sdl, gl):
        self.gl = gl
        # Use the viewer's actual registry; arbitrary GLSL sampler names do not
        # receive channels from LLGLSLShader::mapUniform(). Direct test-only
        # glUniform1i bindings previously hid missing registry entries.
        self.reserved = re.findall(r'mReservedUniforms\.push_back\("([^"]+)"\)',
            (ROOT / 'indra/llrender/llshadermgr.cpp').read_text())
        self.sampler_channels = {}
        self.detail_targets = {}
        for name, args in {
            'ActiveTexture': [U], 'Uniform2f': [I,F,F], 'Uniform3f': [I,F,F,F],
            'Uniform4f': [I,F,F,F,F], 'UniformMatrix4fv': [I,I,C.c_ubyte,P],
            'UniformMatrix3x4fv': [I,I,C.c_ubyte,P], 'Enable': [U], 'Disable': [U],
            'DepthFunc': [U], 'DepthMask': [C.c_ubyte], 'Clear': [U],
            'ClearColor': [F,F,F,F], 'VertexAttrib4f': [U,F,F,F,F],
            'GetActiveUniform': [U,U,I,P,P,P,P], 'GetUniformiv': [U,I,P],
            'DrawBuffers': [I,P], 'GetIntegerv': [U,P],
        }.items():
            setattr(gl,name,C.WINFUNCTYPE(None,*args)(sdl.SDL_GL_GetProcAddress(('gl'+name).encode())))
        self.vao = self.obj(gl.GenVertexArrays)
        gl.GetFragDataLocation=C.WINFUNCTYPE(I,U,C.c_char_p)(sdl.SDL_GL_GetProcAddress(b'glGetFragDataLocation'))
        gl.BindVertexArray(self.vao)
        self.fbo = self.obj(gl.GenFramebuffers)
        gl.BindFramebuffer(FRAMEBUFFER,self.fbo)
        gl.Viewport(0,0,W,H)
        self.vertex = 'void main(){vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3)); gl_Position=vec4(p[gl_VertexID],0,1);}'

    def obj(self, fn):
        value=U(); fn(1,C.byref(value)); return value.value

    def program(self, fragment, vertex=None, extra_vertex=''):
        gl=self.gl; prog=gl.CreateProgram()
        stages=[(0x8B31,vertex or self.vertex),(0x8B30,fragment)]
        if extra_vertex: stages.append((0x8B31,extra_vertex))
        for kind,source in stages:
            shader=gl.CreateShader(kind); text=C.c_char_p(('#version 150 core\n'+source).encode())
            gl.ShaderSource(shader,1,C.byref(text),None); gl.CompileShader(shader)
            ok,log=I(),C.create_string_buffer(16384)
            gl.GetShaderiv(shader,0x8B81,C.byref(ok)); gl.GetShaderInfoLog(shader,len(log),None,log)
            assert ok.value,log.value.decode()
            gl.AttachShader(prog,shader); gl.DeleteShader(shader)
        gl.BindAttribLocation(prog,0,b'position'); gl.BindAttribLocation(prog,1,b'weight4')
        gl.LinkProgram(prog); gl.GetProgramiv(prog,0x8B82,C.byref(ok)); gl.GetProgramInfoLog(prog,len(log),None,log)
        assert ok.value,log.value.decode()
        if 'taa_detail' in fragment:
            assert gl.GetFragDataLocation(prog,b'frag_data[0]')==0
            assert gl.GetFragDataLocation(prog,b'frag_data[1]')==1
        if 'taa_' in fragment:
            channels = {}
            active = I()
            gl.GetProgramiv(prog,0x8B86,C.byref(active))
            gl.UseProgram(prog)
            for index in range(active.value):
                name,size,kind=C.create_string_buffer(256),I(),U()
                gl.GetActiveUniform(prog,index,len(name),None,C.byref(size),C.byref(kind),name)
                if kind.value != 0x8B5E:  # sampler2D
                    continue
                sampler=name.value.decode()
                assert sampler in self.reserved, f'TAA sampler is absent from viewer registry: {sampler}'
                channel=len(channels)
                gl.Uniform1i(gl.GetUniformLocation(prog,name.value),channel)
                channels[sampler]=channel
            self.sampler_channels[prog]=channels
        return prog

    def uniform(self, prog, name, *values, integer=False):
        gl=self.gl; gl.UseProgram(prog); loc=gl.GetUniformLocation(prog,name.encode())
        getattr(gl,'Uniform1i' if integer else f'Uniform{len(values)}f')(loc,*values)

    def matrix(self, prog, name, matrix):
        self.gl.UseProgram(prog)
        self.gl.UniformMatrix4fv(self.gl.GetUniformLocation(prog,name.encode()),1,False,
            (F*16)(*(matrix[r][c] for c in range(4) for r in range(4))))

    def texture(self, values=None, depth=False):
        gl=self.gl; tex=self.obj(gl.GenTextures); gl.BindTexture(TEXTURE,tex)
        for p in (0x2800,0x2801): gl.TexParameteri(TEXTURE,p,0x2600 if depth else 0x2601)
        for p in (0x2802,0x2803): gl.TexParameteri(TEXTURE,p,0x812F)
        gl.TexImage2D(TEXTURE,0,0x81A6 if depth else 0x881A,W,H,0,0x1902 if depth else RGBA,FLOAT,
                      (F*len(values))(*values) if values is not None else None)
        return tex

    def upload(self, tex, values, depth=False):
        gl=self.gl; gl.BindTexture(TEXTURE,tex)
        gl.TexImage2D(TEXTURE,0,0x81A6 if depth else 0x881A,W,H,0,0x1902 if depth else RGBA,FLOAT,(F*len(values))(*values))

    def bind(self, prog, name, unit, tex):
        if prog in self.sampler_channels:
            # The registry/driver, rather than the test's caller, chooses units.
            unit=self.sampler_channels[prog][name]
        self.gl.ActiveTexture(0x84C0+unit); self.gl.BindTexture(TEXTURE,tex)
        self.uniform(prog,name,unit,integer=True)

    def viewer_bind(self, method, prog, textures):
        """Exercise the production pass's declared input wiring and registry keys."""
        pipeline=(ROOT/'indra/newview/pipeline.cpp').read_text()
        code=pipeline.split('LLPipeline::'+method+'(',1)[1].split('\n}\n',1)[0]
        header=(ROOT/'indra/llrender/llshadermgr.h').read_text()
        # Reserved enum values and names are kept in parallel by LLShaderMgr.
        names=dict(re.findall(r'\b(\w+),\s*//\s*"([^"]+)"',header))
        bindings=re.findall(r'\b(?:shader|camera)\.bindTexture\(([^,]+),\s*&([^,\)]+)',code)
        assert bindings,method
        for enum,target in bindings:
            assert enum.startswith('LLShaderMgr::'), f'{method}: texture binding must use a reserved index, not a GL location: {enum}'
            name=names[enum.split('::')[1]]
            tex=textures[target]
            if name=='taa_detail':
                assert re.search(r'bindTexture\(LLShaderMgr::TAA_DETAIL,\s*&mTAAHistory\[1 - mTAAIndex\],\s*false,\s*LLTexUnit::TFO_POINT,\s*1\)',code), 'detail history must bind attachment 1'
                tex=self.detail_target(tex)
            self.bind(prog,name,0,tex)
        bound={names[enum.split('::')[1]] for enum,_ in bindings}
        assert bound==set(self.sampler_channels[prog]), f'{method}: missing or unexpected input textures'
        values=[]
        for name in bound:
            value=I(); self.gl.GetUniformiv(prog,self.gl.GetUniformLocation(prog,name.encode()),C.byref(value))
            values.append(value.value)
        assert len(values)==len(set(values)), f'{method}: aliased sampler units'

    def detail_target(self, target):
        if target not in self.detail_targets:
            binding=I(); self.gl.GetIntegerv(0x8069,C.byref(binding))
            self.detail_targets[target]=self.texture([-1,0,0,0]*(W*H))
            self.gl.BindTexture(TEXTURE,binding.value)
        return self.detail_targets[target]

    def draw(self, prog, target, vertices=3):
        gl=self.gl; gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT,TEXTURE,target,0)
        temporal='taa_detail' in self.sampler_channels.get(prog,{})
        extra=self.detail_target(target) if temporal else 0
        gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT+1,TEXTURE,extra,0)
        gl.DrawBuffers(2 if temporal else 1,(U*2)(COLOR_ATTACHMENT,COLOR_ATTACHMENT+1))
        assert gl.CheckFramebufferStatus(FRAMEBUFFER)==0x8CD5
        gl.UseProgram(prog); gl.DrawArrays(4,0,vertices)

    def read(self, target):
        gl=self.gl; gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT,TEXTURE,target,0)
        values=(F*(W*H*4))(); gl.ReadPixels(0,0,W,H,RGBA,FLOAT,values)
        assert gl.GetError()==0
        return list(values)


def run(sdl,gl):
    gpu=GPU(sdl,gl)
    print('GPU:',gl.GetString(0x1F01).decode())
    source=lambda name:(SHADERS/'class1/deferred'/name).read_text()
    resolve=gpu.program(source('taaResolveF.glsl'))
    camera=gpu.program(source('taaCameraF.glsl'))
    copy=gpu.program(source('taaCopyF.glsl'))
    motion=gpu.program(source('taaMotionF.glsl'),source('taaMotionV.glsl'))
    skin_def='#define HAS_SKIN 1\n#define MAX_JOINTS_PER_MESH_OBJECT 110\n'
    skinned=gpu.program(source('taaMotionF.glsl'),skin_def+source('taaMotionV.glsl'),
        skin_def+(SHADERS/'class1/avatar/objectSkinV.glsl').read_text())
    count=0
    def check(condition, message):
        nonlocal count
        assert condition,message
        count+=1
    identity=[[float(r==c) for c in range(4)] for r in range(4)]
    projection=[[1,0,0,0],[0,1,0,0],[0,0,-1.002002,-.2002002],[0,0,-1,0]]
    inv_proj=inverse(projection)
    d=lambda z:(1.002002-.2002002/z)*.5+.5
    constant=lambda rgba:list(rgba)*(W*H)
    current=gpu.texture(constant((.2,.4,.6,.37)))
    opaque=gpu.texture(constant((.2,.4,.6,.37)))
    history=gpu.texture(constant((float('nan'),)*4))
    output=gpu.texture()
    vectors=gpu.texture(constant((0,0,2,0)))
    depth=gpu.texture([d(2)]*(W*H),True)
    def bind_resolve():
        gpu.viewer_bind('resolveTAA',resolve,{'mRT->screen':current,'mTAAHistory[1 - mTAAIndex]':history,
            'mTAAMotion':vectors,'mTAAOpaque':opaque,'mRT->deferredScreen':depth})
    bind_resolve()
    gpu.matrix(resolve,'taa_inv_projection',inv_proj)
    gpu.uniform(resolve,'taa_rcp_res',1/W,1/H); gpu.uniform(resolve,'taa_jitter',0,0)
    for name,value in [('taa_history_weight',.9),('taa_motion_protection',.85),('taa_clip_gamma',1),('taa_transparency',1)]:
        gpu.uniform(resolve,name,value)
    gpu.uniform(resolve,'taa_history_valid',0,integer=True)
    gpu.uniform(resolve,'taa_static_details',1,integer=True)
    gpu.draw(resolve,output); initial=gpu.read(output)
    check(all(math.isfinite(x) for x in initial),'uninitialized history must never produce NaNs')
    check(max(abs(initial[i]-[.2,.4,.6,.37][i%4]) for i in range(len(initial)) if i%4!=3)<.001,'reset must show current color')
    gpu.uniform(resolve,'taa_history_valid',1,integer=True)
    gpu.upload(history,constant((.2,.4,.6,2)))
    bind_resolve(); gpu.draw(resolve,output); stable=gpu.read(output)
    check(min(stable[3::4])>1.99,'static history should be reused')
    check(max(abs(a-b) for i,(a,b) in enumerate(zip(initial,stable)) if i%4!=3)<.001,'static color must remain stable')
    gpu.upload(history,constant((1,0,0,1)))
    bind_resolve(); gpu.draw(resolve,output); exposed=gpu.read(output)
    check(max(exposed[3::4])<0,'newly revealed depth must reject history')
    check(max(abs(a-b) for i,(a,b) in enumerate(zip(initial,exposed)) if i%4!=3)<.001,'occluder color must not trail behind')
    gpu.upload(vectors,constant((2,0,2,0))); gpu.upload(history,constant((1,1,1,2)))
    bind_resolve(); gpu.draw(resolve,output)
    check(max(gpu.read(output)[3::4])<0,'offscreen history must be rejected')

    # Unused bilinear neighbors cannot invalidate a pixel-center history lookup;
    # a contributing foreground tap must still reject newly exposed background.
    hp=(H//2)*W+W//2
    mixed_history=constant((.2,.4,.6,2))
    mixed_history[(hp+1)*4:(hp+1)*4+4]=[1,0,0,1]
    gpu.upload(history,mixed_history); gpu.upload(vectors,constant((0,0,2,0)))
    bind_resolve(); gpu.draw(resolve,output); pixel=gpu.read(output)[hp*4:hp*4+4]
    check(pixel[3]>0,'zero-weight foreground neighbor must not reject stationary history')
    for offset in (.25,.75):
        gpu.upload(vectors,constant((offset/W,0,2,0)))
        bind_resolve(); gpu.draw(resolve,output); pixel=gpu.read(output)[hp*4:hp*4+4]
        check(pixel[3]<0,f'contributing mismatched depth must reject history at fraction {offset}')
        check(max(abs(a-b) for a,b in zip(pixel[:3],(.2,.4,.6)))<.001,
              f'foreground history must not bleed through at fraction {offset}')

    # Camera reprojection includes jitter exactly once; sky ignores translation.
    gpu.viewer_bind('renderTAAMotion',camera,{'mRT->deferredScreen':depth})
    gpu.matrix(camera,'taa_inv_projection',inv_proj)
    gpu.matrix(camera,'taa_previous_projection',projection)
    moved=[r[:] for r in identity]; moved[0][3]=.2
    gpu.matrix(camera,'taa_previous_from_view',moved)
    gpu.uniform(camera,'taa_rcp_res',1/W,1/H); gpu.uniform(camera,'taa_jitter',.25/W,-.25/H)
    gpu.draw(camera,output); cm=gpu.read(output)
    check(max(abs(v-(.05+.25/W)) for v in cm[0::4])<.0001,'camera translation and jitter sign')
    check(max(abs(v+.25/H) for v in cm[1::4])<.0001,'camera vertical jitter')
    gpu.upload(depth,[1]*(W*H),True); gpu.draw(camera,output); sky=gpu.read(output)
    check(max(abs(v-.25/W) for v in sky[0::4])<.0001,'sky must ignore camera translation')
    check(max(sky[2::4])==0,'sky stores zero geometry depth')
    gpu.upload(depth,[d(2)]*(W*H),True)
    # A nearby classic-avatar mask must not disable temporal AA on distant world
    # geometry when its bounds cross the near plane (especially in mouselook).
    gpu.uniform(camera,'taa_reactive_depth_range',0,3)
    gpu.draw(camera,output)
    check(min(gpu.read(output)[3::4])==1,'legacy geometry within avatar depth bounds is reactive')
    gpu.upload(depth,[d(10)]*(W*H),True)
    gpu.upload(output,constant((0,0,0,0)))
    gpu.bind(camera,'depthMap',0,depth); gpu.draw(camera,output)
    check(max(gpu.read(output)[3::4])==0,'distant background survives near-camera avatar mask')
    gpu.uniform(camera,'taa_reactive_depth_range',0,0)
    gpu.upload(depth,[d(2)]*(W*H),True)

    # Temporal convergence of a jittered slanted edge, compared with a 64-sample
    # analytic coverage reference. Includes the real HDR compression and clipping.
    edge=gpu.program('''out vec4 frag_color; uniform vec2 jitter; uniform float shift;
    void main(){vec2 p=gl_FragCoord.xy-jitter; float c=p.x>p.y*.37+shift ? 1.0:0.0; frag_color=vec4(c,c,c,.37);}''')
    gpu.upload(vectors,constant((0,0,2,0)))
    gpu.uniform(resolve,'taa_transparency',0)
    def halton(i,b):
        f=1; v=0
        while i: f/=b; v+=f*(i%b); i//=b
        return v
    truth=[]
    for y in range(H):
        for x in range(W):
            truth.append(sum(x+(sx+.5)/8>(y+(sy+.5)/8)*.37+23.2 for sy in range(8) for sx in range(8))/64)
    gpu.uniform(edge,'shift',23.2); gpu.uniform(edge,'jitter',0,0); gpu.draw(edge,current)
    raw=gpu.read(current)[0::4]
    raw_error=sum((a-b)**2 for a,b in zip(raw,truth))
    for frame in range(40):
        jx,jy=halton(frame%8+1,2)-.5,halton(frame%8+1,3)-.5
        gpu.uniform(edge,'jitter',jx,jy); gpu.draw(edge,current)
        bind_resolve(); gpu.uniform(resolve,'taa_jitter',jx/W,jy/H)
        gpu.uniform(resolve,'taa_history_valid',int(frame>0),integer=True)
        gpu.draw(resolve,output); history,output=output,history
    converged=gpu.read(history)
    taa_error=sum((a-b)**2 for a,b in zip(converged[0::4],truth))
    check(taa_error<raw_error*.65,f'TAA must improve subpixel edge coverage: raw={raw_error} taa={taa_error}')
    print(f'Edge squared error: raw {raw_error:.4f}, TAA {taa_error:.4f}')
    out_dir=ROOT/'tmp/taa-tests'
    png(out_dir/'convergence.png',W,H,bytes(round(min(max(c,0),1)*255) for y in reversed(range(H)) for x in range(W) for c in converged[(y*W+x)*4:(y*W+x)*4+3]))

    # A real silhouette changes depth as well as color. A flat-depth texture edge
    # cannot catch history rejection caused by mismatched surface ownership.
    # Use the production camera shader with the actual jittered inverse matrix.
    edge_pixels=[y*W+x for y in range(3,H-3) for x in range(3,W-3)
                 if abs(x+.5-(y+.5)*.37-23.2)<.8]
    for background_depth,history_weight in ((8,.9),(0,.9),(8,.97)):
        gpu.uniform(resolve,'taa_history_weight',history_weight)
        frames=[]; rejected=[]
        for frame in range(64):
            jx,jy=halton(frame%8+1,2)-.5,halton(frame%8+1,3)-.5
            colors=[]; depths=[]
            for y in range(H):
                for x in range(W):
                    foreground=x+.5-jx>(y+.5-jy)*.37+23.2
                    colors.extend((1,1,1,.37) if foreground else (0,0,0,.37))
                    z=2 if foreground else background_depth
                    depths.append(d(z) if z else 1)
            gpu.upload(current,colors); gpu.upload(opaque,colors); gpu.upload(depth,depths,True)
            jitter_projection=[row[:] for row in projection]
            for c in range(4):
                jitter_projection[0][c]+=2*jx/W*projection[3][c]
                jitter_projection[1][c]+=2*jy/H*projection[3][c]
            gpu.matrix(camera,'taa_inv_projection',inverse(jitter_projection))
            gpu.matrix(camera,'taa_previous_from_view',identity)
            gpu.uniform(camera,'taa_jitter',jx/W,jy/H)
            gpu.bind(camera,'depthMap',0,depth); gpu.draw(camera,vectors)
            gpu.matrix(resolve,'taa_inv_projection',inverse(jitter_projection))
            gpu.uniform(resolve,'taa_jitter',jx/W,jy/H)
            gpu.uniform(resolve,'taa_history_valid',int(frame>0),integer=True)
            bind_resolve(); gpu.draw(resolve,output)
            if frame>=48:
                result=gpu.read(output)
                frames.append([result[i*4] for i in edge_pixels])
                rejected.extend(result[i*4+3]<0 for i in edge_pixels)
            history,output=output,history
        crawl=statistics.mean(max(values)-min(values) for values in zip(*frames))
        rejection=statistics.mean(rejected)
        print(f'Stationary silhouette (background depth {background_depth}, history {history_weight}): crawl {crawl:.4f}, rejected {rejection:.1%}')
        check(rejection<.05,f'stationary silhouette must retain valid history: {rejection:.1%}')
        check(crawl<.12,f'stationary silhouette must settle across jitter phases: {crawl:.4f}')
        if background_depth==8 and history_weight==.9: default_crawl=crawl
        if history_weight==.97:
            check(crawl<default_crawl*.6,'raising history weight must improve stationary edge stability')
    gpu.uniform(resolve,'taa_history_weight',.9)
    gpu.matrix(resolve,'taa_inv_projection',inv_proj)

    # A moving foreground silhouette with consistent geometry motion. Every newly
    # revealed background pixel must be clean on the very next frame.
    gpu.uniform(resolve,'taa_jitter',0,0)
    old_left=20
    for frame in range(12):
        left=20+frame*3
        colors=[]; z=[]; mv=[]
        for y in range(H):
            for x in range(W):
                inside=left<=x<left+12 and 15<=y<48
                colors.extend((.85,.25,.1,.4) if inside else (.1,.1,.1,.4))
                z.append(d(2 if inside else 8))
                mv.extend(((old_left-left)/W if inside else 0,0,2 if inside else 8,0))
        gpu.upload(current,colors); gpu.upload(opaque,colors); gpu.upload(depth,z,True); gpu.upload(vectors,mv)
        bind_resolve(); gpu.uniform(resolve,'taa_history_valid',int(frame>0),integer=True)
        gpu.draw(resolve,output); rendered=gpu.read(output)
        if frame:
            trail=[abs(rendered[(y*W+x)*4]-.1) for y in range(17,46) for x in range(old_left,left)]
            check(max(trail)<.002,f'dancing silhouette trail on frame {frame}: {max(trail)}')
        history,output=output,history; old_left=left

    # Reactive transparency overrides an otherwise plausible high-contrast history.
    gpu.upload(depth,[d(2)]*(W*H),True); gpu.upload(vectors,constant((0,0,2,0)))
    checker=[v for y in range(H) for x in range(W) for v in ((.8,.8,.8,.4) if (x+y)%2 else (.2,.2,.2,.4))]
    gpu.upload(current,checker); gpu.upload(opaque,constant((0,0,0,0))); gpu.upload(history,constant((.5,.5,.5,2)))
    gpu.uniform(resolve,'taa_history_valid',1,integer=True); gpu.uniform(resolve,'taa_clip_gamma',2)
    gpu.uniform(resolve,'taa_transparency',1); bind_resolve(); gpu.draw(resolve,output)
    protected=gpu.read(output)
    gpu.uniform(resolve,'taa_transparency',0); gpu.draw(resolve,output); unprotected=gpu.read(output)
    check(sum(abs(a-b) for i,(a,b) in enumerate(zip(protected,checker)) if i%4!=3)<sum(abs(a-b) for i,(a,b) in enumerate(zip(unprotected,checker)) if i%4!=3)*.2,'reactivity must favor current transparent shading')
    gpu.upload(vectors,constant((0,0,2,1))); bind_resolve(); gpu.draw(resolve,output)
    check(max(gpu.read(output)[3::4])<0,'untracked geometry mask must reject history')

    # HDR survives accumulation; history depth cannot overwrite scene glow alpha.
    gpu.upload(current,constant((12,3,.5,.37))); gpu.upload(history,constant((12,3,.5,2)))
    gpu.upload(vectors,constant((0,0,2,0))); bind_resolve(); gpu.draw(resolve,output)
    hdr=gpu.read(output)
    check(abs(hdr[0]-12)<.04,'HDR must not clamp to display white')
    gpu.viewer_bind('copyTAA',copy,{'src':output,'mMainRT.screen':current})
    gpu.uniform(copy,'taa_copy_mode',1,integer=True); gpu.uniform(copy,'taa_rcp_res',1/W,1/H)
    gpu.uniform(copy,'taa_jitter',0,0); gpu.uniform(copy,'taa_sharpen',1)
    gpu.draw(copy,history); copied=gpu.read(history)
    check(abs(copied[3]-.37)<.001,'presentation must preserve glow alpha')
    check(abs(copied[0]-12)<.04,'sharpening must preserve flat HDR areas')

    # Local maxima/minima are precisely the soft details sharpening should
    # restore. Clamping to the original immediate-neighbor range used to erase
    # the entire adjustment on these patterns, despite a correctly wired slider.
    for label,signal in (
        ('thin line',lambda x:.5 if x==W//2 else .2),
        ('fine stripes',lambda x:.5 if x%2 else .2),
        ('soft edge',lambda x:.2+.6/(1+math.exp(-(x-W//2))))):
        pixels=[v for y in range(H) for x in range(W) for v in (signal(x),)*3+(.37,)]
        gpu.upload(output,pixels)
        gpu.viewer_bind('copyTAA',copy,{'src':output,'mMainRT.screen':current})
        results=[]
        for strength in (0,.2,1,2):
            gpu.uniform(copy,'taa_sharpen',strength)
            gpu.draw(copy,history); results.append(gpu.read(history))
        off,normal,full,strong=results
        check(max(abs(a-b) for i,(a,b) in enumerate(zip(off,pixels)) if i%4!=3)<.001,
              f'zero sharpening must preserve {label}')
        normal_change=max(abs(a-b) for i,(a,b) in enumerate(zip(normal,off)) if i%4!=3)
        full_change=max(abs(a-b) for i,(a,b) in enumerate(zip(full,off)) if i%4!=3)
        print(f'Sharpening {label}: default change {normal_change:.4f}, full change {full_change:.4f}')
        check(full_change>.015,f'sharpening must visibly affect {label}')
        check(0<normal_change<full_change,f'sharpening slider must have a graduated response on {label}')
        check(min(full[0::4])>=.1 and max(full[0::4])<=.9,f'sharpening must bound halos on {label}')
        check(max(abs(x-.37) for x in full[3::4])<.001,'sharpening must retain scene glow alpha')
        strong_change=max(abs(a-b) for i,(a,b) in enumerate(zip(strong,off)) if i%4!=3)
        check(strong_change>full_change*1.5,f'sharpening 2 must exceed the old maximum on {label}')
        check(all(math.isfinite(x) and x>=0 for x in strong),f'sharpening 2 must remain finite and nonnegative on {label}')

    # Production skinned shader: two joints move independently, not just the root.
    # A D24 prepass uses the production PBR transform order and GL_EQUAL motion.
    skin_helper=skin_def+(SHADERS/'class1/avatar/objectSkinV.glsl').read_text()
    # Texture transforms are irrelevant to coverage; use the actual PBR vertex
    # source with inert texture-coordinate helpers and the real skinning helper.
    depth_vertex=skin_def+source('pbrOpaqueV.glsl')
    texture_helpers='''
    vec2 texture_transform(vec2 uv,vec4 k[2],mat4 m){return uv;}
    vec4 tangent_space_transform(vec4 t,vec3 n,vec4 k[2],mat4 m){return t;}
    '''
    depth_prog=gpu.program('out vec4 frag_color; void main(){frag_color=vec4(1);}',depth_vertex,skin_helper+texture_helpers)
    vbo=gpu.obj(gl.GenBuffers); gl.BindBuffer(0x8892,vbo)
    vertex_data=(F*18)(-1,-1,-2,1,-1,-2,1,1,-2,-1,-1,-2,1,1,-2,-1,1,-2)
    gl.BufferData(0x8892,C.sizeof(vertex_data),vertex_data,0x88E4)
    gl.VertexAttribPointer(0,3,FLOAT,False,0,None); gl.EnableVertexAttribArray(0)
    gl.VertexAttrib4f(1,0.5,1.5,0,0)
    def palette(prog,name,angle):
        # joint 0 fixed; joint 1 rotates and translates the limb.
        c,s=math.cos(angle),math.sin(angle)
        data=[1,0,0,0,0,1,0,0,0,0,1,0,c,s,0,.3,-s,c,0,.1,0,0,1,0]
        gl.UseProgram(prog); gl.UniformMatrix3x4fv(gl.GetUniformLocation(prog,name.encode()),2,False,(F*24)(*data))
    for prog in (depth_prog,skinned):
        gpu.matrix(prog,'modelview_matrix',identity); gpu.matrix(prog,'projection_matrix',projection)
    gpu.matrix(skinned,'taa_previous_modelview',identity); gpu.matrix(skinned,'taa_previous_mvp',projection)
    gpu.uniform(skinned,'taa_rcp_res',1/W,1/H); gpu.uniform(skinned,'taa_jitter',0,0); gpu.uniform(skinned,'taa_reactive',0)
    gl.FramebufferTexture2D(FRAMEBUFFER,0x8D00,TEXTURE,depth,0)
    for angle in (.15,.7,1.4,2.5):
        palette(depth_prog,'matrixPalette',angle); palette(skinned,'matrixPalette',angle)
        palette(skinned,'taa_previous_palette',angle-.1)
        gl.Enable(0x0B71); gl.DepthMask(True); gl.DepthFunc(0x0201)
        gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT,TEXTURE,current,0)
        gl.ClearColor(0,0,0,0); gl.Clear(0x4000|0x0100); gpu.draw(depth_prog,current,6)
        visible=gpu.read(current)
        gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT,TEXTURE,output,0)
        gl.ClearColor(0,0,0,1); gl.Clear(0x4000)
        gl.DepthMask(False); gl.DepthFunc(0x0202); gpu.draw(skinned,output,6)
        moved=gpu.read(output)
        pixels=[i for i in range(0,len(visible),4) if visible[i]>.5]
        coverage=sum(moved[i+3]<.5 for i in pixels)/len(pixels)
        check(coverage>.995,f'skinned motion must cover visible D24 geometry: {coverage}')
        check(max(math.hypot(moved[i]*W,moved[i+1]*H) for i in pixels)>.3,'joint rotation must generate local motion')
        check(max(abs(moved[i+2]-2) for i in pixels if moved[i+3]<.5)<.005,'previous skinned view depth')
    gl.DepthMask(True); gl.Disable(0x0B71)
    gl.FramebufferTexture2D(FRAMEBUFFER,0x8D00,TEXTURE,0,0)
    check(gl.GetError()==0,'final GL error')
    print(f'PASS: {count} TAA GPU checks')


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try: run(sdl,gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx); sdl.SDL_DestroyWindow(window); sdl.SDL_Quit()
