"""A stable guide must keep its hair vertices; collision recovery must not launch a rope."""
import ctypes as C
import math
import struct
from test_taa_gpu import GPU, SHADERS, W, H, F
from test_exact_oit_gpu import context, U, SSBO


def run(sdl, gl):
    gpu=GPU(sdl,gl)
    gl.TexBuffer=C.WINFUNCTYPE(None,U,U,U)(sdl.SDL_GL_GetProcAddress(b'glTexBuffer'))
    common=(SHADERS/'class1/deferred/hairCollision.glsl').read_text()
    identity=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
    def buffer(data):
        b,t=gpu.obj(gl.GenBuffers),gpu.obj(gl.GenTextures)
        raw=struct.pack(f'{len(data)*4}f',*(x for p in data for x in p))
        gl.BindBuffer(SSBO,b);gl.BufferData(SSBO,len(raw),C.create_string_buffer(raw),0x88E8)
        gl.BindTexture(0x8C2A,t);gl.TexBuffer(0x8C2A,0x8814,b)
        return b,t
    def texture(unit,pair):
        gl.ActiveTexture(0x84C0+unit);gl.BindTexture(0x8C2A,pair[1])
    def read(pair,n):
        gl.BindBuffer(SSBO,pair[0]);raw=C.create_string_buffer(n*16)
        gl.GetBufferSubData(SSBO,0,len(raw),raw)
        return list(struct.iter_unpack('4f',raw.raw))
    def dispatch():
        gl.DispatchCompute(1,1,1);gl.MemoryBarrier(0x2000|0x8|0x200)

    guides=[]
    for chain in range(16):
        angle=chain*math.tau/16
        rest=[(.15*math.cos(angle),.15*math.sin(angle),-i*.1,1) for i in range(9)]
        guides.extend(rest+rest+[(0,0,0,0)]*9)
    guides[0]=(*guides[0][:3],16)
    # Opposing normals above and below a protrusion, with a node initially behind it.
    grid=21*21*32;offset=14
    shell=[(-.02,-1,-.8,1.5),(.18,1,0,2)]
    for z,sign in ((0,1),(-.8,-1)):
        normal=(1/math.sqrt(1.25),0,sign*.5/math.sqrt(1.25),0)
        for p in ((.18,-1,-.4),(.18,1,-.4),(-.02,0,z)):
            shell.extend([(*p,0),normal])
    shell.extend([(-.6,-.6,-1.56,.06)])
    shell.extend([(3 if -1.56+(i//441)*.06>=-.4 else 9,0,0,0) for i in range(grid)])
    mesh=buffer(shell);old=buffer(guides);out=buffer(guides)
    program=gpu.compute((SHADERS/'class1/deferred/hairGuideC.glsl').read_text(),common)
    for name in ('guide_from_previous','hair_mesh_from_local'):gpu.matrix(program,name,identity)
    for name,value in {'hair_previous_guides':29,'hair_mesh':30,'hair_mesh_nodes':1,'hair_mesh_contact':offset,'guide_history':1}.items():
        gpu.uniform(program,name,value,integer=True)
    for name,value in {'guide_dt':1/120,'hair_root_radius':.08,'hair_root_gradient':.1,'guide_retention':0}.items():gpu.uniform(program,name,value)
    texture(29,old);texture(30,mesh);gl.BindBufferBase(SSBO,5,out[0]);dispatch()
    result=read(out,len(guides))
    speed=max(math.sqrt(sum(v*v for v in result[c*27+18+i][:3])) for c in range(16) for i in range(9))
    print('Velocity created by static fold recovery (m/s):',speed)

    # Submillimetre breathing of the same protrusion must not cause intermittent rope launches.
    previous_mesh=buffer(shell)
    gl.BufferSubData=C.WINFUNCTYPE(None,U,C.c_ssize_t,C.c_ssize_t,C.c_void_p)(sdl.SDL_GL_GetProcAddress(b'glBufferSubData'))
    def move_surface(pair,shift):
        geometry=list(shell[:offset])
        for index in (0,1,2,4,6,8,10,12):
            p=geometry[index];geometry[index]=(p[0]+shift,*p[1:])
        raw=struct.pack(f'{offset*4}f',*(v for p in geometry for v in p))
        gl.BindBuffer(SSBO,pair[0]);gl.BufferSubData(SSBO,0,len(raw),C.create_string_buffer(raw))
    gpu.uniform(program,'hair_previous_mesh',31,integer=True)
    gpu.uniform(program,'guide_mesh_history',1,integer=True)
    gpu.uniform(program,'guide_dt',1/60);gpu.uniform(program,'guide_stiffness',6);gpu.uniform(program,'guide_retention',.5)
    for elasticity in (0,.25,1):
        gpu.uniform(program,'guide_elasticity',elasticity)
        old,out=buffer(guides),buffer(guides)
        previous_points=None;peak_step=peak_speed=0
        for frame in range(420):
            move_surface(previous_mesh,.0005*math.sin(frame*.035))
            move_surface(mesh,.0005*math.sin((frame+1)*.035))
            texture(29,old);texture(30,mesh);texture(31,previous_mesh)
            gl.BindBufferBase(SSBO,5,out[0]);dispatch()
            if frame>=300:
                values=read(out,len(guides))
                points=[p[:3] for c in range(16) for p in values[c*27+9:c*27+18]]
                velocities=[v[:3] for c in range(16) for v in values[c*27+18:c*27+27]]
                if previous_points:peak_step=max(peak_step,max(math.dist(a,b) for a,b in zip(points,previous_points)))
                peak_speed=max(peak_speed,max(math.sqrt(sum(x*x for x in v)) for v in velocities))
                previous_points=points
            old,out=out,old
        print('Breathing fold elasticity / max settled frame step / speed:',elasticity,peak_step,peak_speed)
        assert peak_step<.003 and peak_speed<.3, 'small moving fold caused a rope spasm'

    # Give under load, then recover without permanently changing rest lengths, at both frame rates.
    gpu.uniform(program,'hair_mesh_contact',0,integer=True)
    # Keep the recovery solver active, with the actual BVH safely away from the rope.
    move_surface(mesh,10);move_surface(previous_mesh,10)
    gpu.uniform(program,'guide_retention',0);gpu.uniform(program,'guide_bend',0)
    lengths={}
    for mesh_mode in (0,1):
        gpu.uniform(program,'hair_mesh_nodes',mesh_mode,integer=True)
        for elasticity,rate in ((0,60),(.25,60),(1,60),(.25,30)):
            gpu.uniform(program,'guide_elasticity',elasticity);gpu.uniform(program,'guide_dt',1/rate)
            old,out=buffer(guides),buffer(guides)
            for gravity in (-9.81,0):
                gpu.uniform(program,'guide_gravity',0,0,gravity)
                for _ in range(rate*4):
                    texture(29,old);texture(30,mesh);texture(31,previous_mesh)
                    gl.BindBufferBase(SSBO,5,out[0]);dispatch();old,out=out,old
                values=read(old,len(guides))
                length=sum(math.dist(values[9+i][:3],values[10+i][:3]) for i in range(8))
                if gravity: lengths[mesh_mode,elasticity,rate]=length
                else: assert abs(length-.8)<.001, ('elastic rope did not recover',mesh_mode,elasticity,length)
            print('Elastic loading mesh / elasticity / Hz / loaded length / recovered:',mesh_mode,elasticity,rate,lengths[mesh_mode,elasticity,rate],length)
        assert lengths[mesh_mode,0,60]<lengths[mesh_mode,.25,60]<lengths[mesh_mode,1,60]<.88
        assert abs(lengths[mesh_mode,.25,30]-lengths[mesh_mode,.25,60])<.001

    # Frozen head-local skin palette follows the same reference pose used to fit the guides.
    bind_offset=len(guides)
    data=guides+[(1,0,0,0)]+[tuple(row) for row in identity]
    # Different neighbouring guide displacements expose lookup changes caused by breathing.
    for chain in range(16):
        for i in range(1,9):
            p=data[chain*27+9+i]
            data[chain*27+9+i]=(p[0]+.04*math.sin(chain*.7)*i/8,p[1],p[2],1)
    bound=buffer(data)
    skin='#define MAX_JOINTS_PER_MESH_OBJECT 4\n'+(SHADERS/'class1/avatar/objectSkinV.glsl').read_text()
    vertex='''uniform vec3 sample_position;out vec3 moved;
mat4 getObjectSkinnedTransform();mat4 getHairSkinnedTransform(mat4 skin,vec3 position);
void main(){moved=(getHairSkinnedTransform(getObjectSkinnedTransform(),sample_position)*vec4(sample_position,1)).xyz;
vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));gl_Position=vec4(p[gl_VertexID],0,1);}
'''
    render=gpu.program('in vec3 moved;out vec4 frag_color;void main(){frag_color=vec4(moved,1);}',vertex,skin)
    for name in ('hair_local_from_model','hair_model_from_local'):gpu.matrix(render,name,identity)
    for name,value in {'hair_guides':29,'hair_guide_active':1,'hair_guide_bind':bind_offset}.items():gpu.uniform(render,name,value,integer=True)
    gpu.uniform(render,'hair_root_radius',.08);gpu.uniform(render,'hair_root_gradient',.1)
    gpu.uniform(render,'sample_position',.14,.02,-.43)
    gl.VertexAttrib4f(1,.5,0,0,0)
    target=gpu.texture()
    gl.TexImage2D(0x0DE1,0,0x8814,W,H,0,0x1908,0x1406,None)
    texture(29,bound)
    samples=[]
    for shift in (0,.012,-.012):
        palette=(F*12)(1,0,0,0,0,1,0,shift,0,0,1,shift)
        gl.UseProgram(render);gl.UniformMatrix3x4fv(gl.GetUniformLocation(render,b'matrixPalette'),1,False,palette)
        gpu.draw(render,target);pixels=gpu.read(target);pixel=(H//2*W+W//2)*4
        samples.append(pixels[pixel:pixel+3])
    slip=max(math.dist(samples[0],p) for p in samples[1:])
    print('Hair displacement with fixed guides and animated torso palette (m):',slip)
    assert speed<1.e-4, 'collision/length recovery injected kinetic energy on a static surface'
    assert slip<1.e-6, 'animated skinning changes guide binding and moves hair independently of guides'
    head=[row[:] for row in identity];head[0][3]=.1
    inverse=[row[:] for row in identity];inverse[0][3]=-.1
    gpu.matrix(render,'hair_model_from_local',head);gpu.matrix(render,'hair_local_from_model',inverse)
    gpu.draw(render,target);moved=gpu.read(target)[pixel:pixel+3]
    assert math.dist(moved,(samples[0][0]+.1,*samples[0][1:]))<1.e-6, ('bound hair stopped following the head',samples,moved)
    gpu.uniform(render,'hair_guide_active',0,integer=True);gpu.uniform(render,'hair_root_radius',0)
    gpu.draw(render,target);fallback=gpu.read(target)[pixel:pixel+3]
    assert math.dist(fallback,(.14,.008,-.442))<1.e-6, 'disabling guides did not restore skeletal animation'

    # The actual motion pass must use the same frozen binding for its previous frame too.
    motion=(SHADERS/'class1/deferred/taaMotionV.glsl').read_text()
    motion=motion.replace('in vec3 position;','uniform vec3 sample_position;\n#define position sample_position')
    motion=motion.replace('void main()','void motionMain()')
    motion='#define HAS_SKIN 1\n#define MAX_JOINTS_PER_MESH_OBJECT 4\n'+motion+'''
out vec3 binding_motion;
void main(){motionMain();binding_motion=gl_Position.xyz-previous_clip.xyz;
vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));gl_Position=vec4(p[gl_VertexID],0,1);}
'''
    taa=gpu.program('in vec3 binding_motion;out vec4 frag_color;void main(){frag_color=vec4(binding_motion,1);}',motion,skin)
    for name in ('modelview_matrix','projection_matrix','taa_previous_mvp','taa_previous_modelview',
                 'hair_local_from_model','hair_model_from_local','hair_previous_local_from_model','hair_previous_model_from_local'):
        gpu.matrix(taa,name,identity)
    for name,value in {'hair_guides':29,'hair_previous_guides':28,'hair_guide_active':1,'hair_previous_guide_active':1,
                       'hair_guide_bind':bind_offset,'hair_previous_guide_bind':bind_offset}.items():gpu.uniform(taa,name,value,integer=True)
    for name in ('hair_root_radius','hair_previous_root_radius'):gpu.uniform(taa,name,.08)
    for name in ('hair_root_gradient','hair_previous_root_gradient'):gpu.uniform(taa,name,.1)
    gpu.uniform(taa,'sample_position',.14,.02,-.43)
    gl.UseProgram(taa)
    gl.UniformMatrix3x4fv(gl.GetUniformLocation(taa,b'matrixPalette'),1,False,palette)
    previous_palette=(F*12)(1,0,0,0,0,1,0,.012,0,0,1,.012)
    gl.UniformMatrix3x4fv(gl.GetUniformLocation(taa,b'taa_previous_palette'),1,False,previous_palette)
    texture(29,bound);texture(28,bound);gpu.draw(taa,target)
    motion=gpu.read(target)[pixel:pixel+3]
    assert math.dist(motion,(0,0,0))<1.e-6,('TAA saw false breathing motion in guide-bound hair',motion)
    assert gl.GetError()==0
    print('PASS: static contact recovery creates no launch; frozen guide binding ignores torso breathing')


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try:run(sdl,gl)
    finally:sdl.SDL_GL_DestroyContext(ctx);sdl.SDL_DestroyWindow(window);sdl.SDL_Quit()
