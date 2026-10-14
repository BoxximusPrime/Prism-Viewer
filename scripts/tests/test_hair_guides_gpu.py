"""Guide solver: production compute, constraints, inertia, gravity and reset."""
import ctypes as C
import math
import struct
from test_taa_gpu import GPU, SHADERS, W, H
from test_exact_oit_gpu import context, U, SSBO


def run(sdl, gl):
    gpu=GPU(sdl,gl)
    gl.TexBuffer=C.WINFUNCTYPE(None,U,U,U)(sdl.SDL_GL_GetProcAddress(b'glTexBuffer'))
    source=(SHADERS/'class1/deferred/hairCollision.glsl').read_text()
    program=gpu.compute((SHADERS/'class1/deferred/hairGuideC.glsl').read_text(),source)
    identity=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
    gpu.matrix(program,'guide_from_previous',identity)
    for name,value in {'hair_root_radius':.08,'hair_root_gradient':.1,'guide_stiffness':6.,'guide_retention':.5,'guide_dt':1/60}.items(): gpu.uniform(program,name,value)
    gpu.uniform(program,'hair_previous_guides',29,integer=True)
    gpu.uniform(program,'hair_mesh',30,integer=True)
    gpu.uniform(program,'hair_previous_mesh',31,integer=True)
    data=[]
    for chain in range(16):
        angle=chain*math.tau/16
        rest=[(.15*math.cos(angle),.15*math.sin(angle),-i*.1,1) for i in range(9)]
        data.extend(rest+rest+[(0,0,0,0)]*9)
    data[0]=(*data[0][:3],16)
    raw=struct.pack(f'{len(data)*4}f',*(x for p in data for x in p))
    buffers=[]
    for _ in range(2):
        buffer,texture=gpu.obj(gl.GenBuffers),gpu.obj(gl.GenTextures)
        gl.BindBuffer(SSBO,buffer);gl.BufferData(SSBO,len(raw),C.create_string_buffer(raw),0x88E8)
        gl.BindTexture(0x8C2A,texture);gl.TexBuffer(0x8C2A,0x8814,buffer)
        buffers.append((buffer,texture))
    frame=0
    def step(dt=1/60,history=True,move=0,gravity=(0,0,0),retention=.5,turn=0):
        nonlocal frame
        slot=frame%2;frame+=1
        gl.ActiveTexture(0x84C0+29);gl.BindTexture(0x8C2A,buffers[1-slot][1])
        gl.BindBufferBase(SSBO,5,buffers[slot][0])
        transform=[row[:] for row in identity];transform[0][3]=-move
        transform[0][0]=transform[2][2]=math.cos(turn)
        transform[0][2]=math.sin(turn);transform[2][0]=-math.sin(turn)
        gpu.matrix(program,'guide_from_previous',transform)
        gpu.uniform(program,'guide_dt',dt);gpu.uniform(program,'guide_history',int(history),integer=True)
        gpu.uniform(program,'guide_gravity',*gravity);gpu.uniform(program,'guide_retention',retention)
        gl.DispatchCompute(1,1,1);gl.MemoryBarrier(0x2000|0x8|0x200)
        gl.BindBuffer(SSBO,buffers[slot][0]);out=C.create_string_buffer(len(raw));gl.GetBufferSubData(SSBO,0,len(raw),out)
        result=list(struct.iter_unpack('4f',out.raw))
        assert all(math.isfinite(x) for p in result for x in p)
        for chain in range(16):
            base=chain*27
            assert math.dist(result[base][:3],result[base+9][:3])<1.e-6
        return result
    idle=step(0,False)
    for _ in range(60): idle=step()
    assert max(math.dist(idle[c*27+i][:3],idle[c*27+9+i][:3]) for c in range(16) for i in range(9))<1.e-5
    kicked=step(move=.03)
    assert kicked[17][0]<.13, kicked[17]
    for _ in range(240): settled=step()
    assert abs(settled[17][0]-.15)<.005, settled[17]
    step(0,False)
    for _ in range(120): sag=step(gravity=(9.81,0,0),retention=.1)
    assert sag[17][0]>.3, sag[17]
    lengths=[math.dist(sag[9+i][:3],sag[10+i][:3]) for i in range(8)]
    assert max(abs(x-.1) for x in lengths)<.004, lengths
    reset=step(0,False)
    assert math.dist(reset[17][:3],data[17][:3])<1.e-6
    def at_rate(rate):
        step(0,False)
        for _ in range(rate): result=step(1/rate,gravity=(5,0,0),retention=.3)
        return result[17][:3]
    assert math.dist(at_rate(30),at_rate(60))<.002
    # The optional artistic travel limit still bounds low-stiffness motion when explicitly enabled.
    gpu.uniform(program,'guide_travel',.3)
    gpu.uniform(program,'guide_stiffness',1.)
    step(0,False)
    peak_speed=peak_offset=0
    for frame_index in range(180):
        moved=step(1/30,move=.08*math.sin(frame_index*.45),gravity=(4,0,-7),retention=.6)
        peak_speed=max(peak_speed,max(math.sqrt(sum(x*x for x in p[:3])) for c in range(16) for p in moved[c*27+18:c*27+27]))
        peak_offset=max(peak_offset,max(math.dist(moved[c*27+i][:3],moved[c*27+9+i][:3]) for c in range(16) for i in range(9)))
    assert peak_speed<=3.001 and peak_offset<.4,('unbounded guide motion',peak_speed,peak_offset)
    print(f'Low-stiffness stress: peak speed {peak_speed:.3f} m/s; peak displacement {peak_offset:.3f} m')
    for n in range(90):
        rotated=step(1/60 if n%3 else 1/7,turn=.12*math.sin(n*.3),gravity=(0,0,-9.81),retention=0)
        assert max(math.dist(rotated[c*27+i][:3],rotated[c*27+9+i][:3]) for c in range(16) for i in range(9))<.281
    gpu.uniform(program,'guide_stiffness',6.)
    step(0,False)
    for _ in range(14): slow=step(1/7,gravity=(9.81,0,0),retention=0)
    assert max(math.dist(slow[9+i][:3],slow[10+i][:3]) for i in range(8))<.11
    gpu.uniform(program,'guide_travel',0.)
    # Root softness must resist sustained gravity with shape retention and travel limits off.
    gpu.uniform(program,'hair_root_radius',.16)
    def gradient_sag(width,rate=60,base=0):
        gpu.uniform(program,'hair_root_gradient',width)
        step(0,False)
        for _ in range(rate*4): result=step(1/rate,gravity=(2,0,0),retention=0)
        return [math.dist(result[base+i][:3],result[base+9+i][:3]) for i in range(9)]
    narrow=gradient_sag(.3)
    wide=gradient_sag(.6)
    print('Root gradient displacement (m):',wide)
    assert wide[0]<1.e-6 and 0<wide[1]<.005, ('near-root softness',wide)
    assert all(a<b for a,b in zip(wide,wide[1:])), ('gradient must release smoothly',wide)
    assert wide[3]<narrow[3]*.7 and wide[-1]>.05, ('gradient width must affect motion and leave free tips',narrow,wide)
    assert max(abs(a-b) for a,b in zip(wide,gradient_sag(.6,30)))<.002, 'gradient changed with frame rate'
    gpu.uniform(program,'hair_root_radius',.08)
    gpu.uniform(program,'hair_root_gradient',.1)
    # Flat avatar shell with production cached-triangle contact, independent of proxy mode.
    grid=21*21*32;offset=8
    shell=[(.12,-1,-1.5,1.5),(.12,1,1,1)]
    for p in ((.12,-1,-1.5),(.12,1,-1.5),(.12,0,1)):
        shell.extend([(*p,0),(1,0,0,0)])
    shell.extend([(-.6,-.6,-1.56,.06)]+[(3,0,0,0)]*grid)
    shellraw=struct.pack(f'{len(shell)*4}f',*(x for p in shell for x in p))
    buffer,texture=gpu.obj(gl.GenBuffers),gpu.obj(gl.GenTextures)
    gl.BindBuffer(SSBO,buffer);gl.BufferData(SSBO,len(shellraw),C.create_string_buffer(shellraw),0x88E8)
    gl.ActiveTexture(0x84C0+30);gl.BindTexture(0x8C2A,texture);gl.TexBuffer(0x8C2A,0x8814,buffer)
    gpu.matrix(program,'hair_mesh_from_local',identity)
    gpu.uniform(program,'hair_mesh_nodes',1,integer=True)
    gpu.uniform(program,'hair_mesh_contact',offset,integer=True)
    step(0,False)
    for _ in range(60): mesh=step(gravity=(-9.81,0,0),retention=.3)
    assert mesh[13][0]>.12,mesh[13]
    # Sustained pressure against a static shell must settle without contact creating bounce.
    for _ in range(240): mesh=step(gravity=(-9.81,0,-7),retention=.3)
    samples=[]
    for _ in range(60):
        mesh=step(gravity=(-9.81,0,-7),retention=.3)
        samples.append(mesh[13][:3])
    assert max(math.dist(a,b) for a in samples for b in samples)<.0005
    gl.BufferSubData=C.WINFUNCTYPE(None,U,C.c_ssize_t,C.c_ssize_t,C.c_void_p)(sdl.SDL_GL_GetProcAddress(b'glBufferSubData'))
    step(0,False)
    gl.BindBuffer(SSBO,buffers[(frame-1)%2][0])
    gl.BufferSubData(SSBO,13*16,16,C.create_string_buffer(struct.pack('4f',.09,0,-.4,1)))
    recovered=step(dt=1/120)
    assert recovered[13][0]>=.12, recovered[13]
    assert abs(recovered[22][0])<.01,('contact created bounce velocity',recovered[22])
    step(0,False)
    gl.BindBuffer(SSBO,buffers[(frame-1)%2][0])
    gl.BufferSubData(SSBO,13*16,16,C.create_string_buffer(struct.pack('4f',.121,0,-.4,1)))
    gl.BufferSubData(SSBO,22*16,16,C.create_string_buffer(struct.pack('4f',0,.5,0,0)))
    sliding=step(dt=1/120,gravity=(-9.81,0,0))
    assert sliding[22][1]>.1,('mesh contact swallowed tangential motion',sliding[22])
    # Animated shell interpolation and velocity use the same world-space surface points.
    old_buffer,old_texture=gpu.obj(gl.GenBuffers),gpu.obj(gl.GenTextures)
    gl.BindBuffer(SSBO,old_buffer);gl.BufferData(SSBO,len(shellraw),C.create_string_buffer(shellraw),0x88E8)
    gl.ActiveTexture(0x84C0+31);gl.BindTexture(0x8C2A,old_texture);gl.TexBuffer(0x8C2A,0x8814,old_buffer)
    def plane_at(target,x):
        values=list(shell)
        for i in (0,1,2,4,6): values[i]=(x,*values[i][1:])
        packed=struct.pack(f'{len(values)*4}f',*(v for p in values for v in p))
        gl.BindBuffer(SSBO,target);gl.BufferData(SSBO,len(packed),C.create_string_buffer(packed),0x88E8)
    guide_source=(SHADERS/'class1/deferred/hairGuideC.glsl').read_text().replace('void main()', 'void simulationMain()')
    moving_probe=gpu.compute(guide_source+'''
uniform float probe_fraction;
void main(){if(gl_GlobalInvocationID.x!=0u)return;contact_fraction=probe_fraction;
guide_out[0]=vec4(projectGuideContact(vec3(.1,0,-.4),sampleGuideContact(vec3(.1,0,-.4))),1);
guide_out[1]=vec4(contact_velocity,0);}
''',source)
    result_buffer=gpu.obj(gl.GenBuffers)
    gl.BindBuffer(SSBO,result_buffer);gl.BufferData(SSBO,32,None,0x88E8)
    gpu.matrix(moving_probe,'hair_mesh_from_local',identity)
    gpu.matrix(moving_probe,'guide_from_previous',identity)
    gpu.uniform(program,'hair_previous_mesh_contact',offset,integer=True)
    for name,value in {'hair_mesh':30,'hair_previous_mesh':31,'hair_mesh_nodes':1,'hair_mesh_contact':offset,'hair_previous_mesh_contact':offset,'guide_mesh_history':1}.items():
        gpu.uniform(moving_probe,name,value,integer=True)
    gpu.uniform(moving_probe,'guide_dt',1/60)
    plane_at(buffer,.16)
    def contact_probe(fraction):
        gl.BindBufferBase(SSBO,5,result_buffer)
        gpu.uniform(moving_probe,'probe_fraction',fraction)
        gl.DispatchCompute(1,1,1);gl.MemoryBarrier(0x2000|0x200)
        gl.BindBuffer(SSBO,result_buffer);out=C.create_string_buffer(32);gl.GetBufferSubData(SSBO,0,32,out)
        return struct.unpack('8f',out.raw)
    for fraction in (0,.25,.5,.75,1):
        result=contact_probe(fraction)
        assert abs(result[0]-(.125+.04*fraction))<1.e-5,('substep surface pose',fraction,result)
        assert abs(result[4]-2.4)<1.e-4,('animated surface velocity',result)
    # Different avatar-relative origins must not introduce fake surface motion.
    gpu.uniform(moving_probe,'guide_previous_mesh_offset',.04,0,0)
    result=contact_probe(.5)
    assert abs(result[0]-.165)<1.e-5 and abs(result[4])<1.e-4,('mesh origin mismatch',result)
    # Invalid history (rebuild, teleport or clearance change) uses only the current shell.
    gpu.uniform(moving_probe,'guide_mesh_history',0,integer=True)
    gpu.uniform(moving_probe,'guide_previous_mesh_offset',10,0,0)
    result=contact_probe(0)
    assert abs(result[0]-.165)<1.e-5 and abs(result[4])<1.e-6,('stale mesh history',result)
    # A pushing surface transfers outward velocity while retaining collision push-out.
    plane_at(buffer,.12)
    gpu.uniform(program,'guide_mesh_history',0,integer=True)
    step(0,False)
    gl.BindBuffer(SSBO,buffers[(frame-1)%2][0])
    gl.BufferSubData(SSBO,13*16,16,C.create_string_buffer(struct.pack('4f',.121,0,-.4,1)))
    plane_at(buffer,.13)
    gpu.uniform(program,'guide_mesh_history',1,integer=True)
    moving=step(dt=1/60,gravity=(-9.81,0,0))
    assert moving[13][0]>=.1349 and abs(moving[22][0]-.6)<.001,('moving surface response',moving[13],moving[22])
    gpu.uniform(program,'guide_mesh_history',0,integer=True)
    # A receding surface must not pull the rope inward through its soft contact band.
    plane_at(buffer,.13);plane_at(old_buffer,.13)
    step(0,False)
    gl.BindBuffer(SSBO,buffers[(frame-1)%2][0])
    gl.BufferSubData(SSBO,13*16,16,C.create_string_buffer(struct.pack('4f',.121,0,-.4,1)))
    plane_at(buffer,.12)
    gpu.uniform(program,'guide_mesh_history',1,integer=True)
    receding=step(dt=1/120,retention=0)
    print('Receding surface normal velocity:',receding[22][0])
    assert receding[22][0]>-.01,('receding surface pulled hair inward',receding[22])
    gpu.uniform(program,'guide_mesh_history',0,integer=True)
    # A tangentially moving surface without normal pressure cannot drag a free rope.
    plane_at(buffer,.12);plane_at(old_buffer,.12)
    step(0,False)
    gl.BindBuffer(SSBO,buffers[(frame-1)%2][0])
    gl.BufferSubData(SSBO,13*16,16,C.create_string_buffer(struct.pack('4f',.121,0,-.4,1)))
    gpu.uniform(program,'guide_mesh_history',1,integer=True)
    gpu.uniform(program,'guide_previous_mesh_offset',0,-.01,0)
    grazing=step(dt=1/60,retention=0)
    assert abs(grazing[22][1])<.001,('contact applied friction without normal pressure',grazing[22])
    gpu.uniform(program,'guide_previous_mesh_offset',0,0,0)
    gpu.uniform(program,'guide_mesh_history',0,integer=True)
    def animated_at_rate(rate):
        plane_at(buffer,.12);plane_at(old_buffer,.12)
        step(0,False)
        for _ in range(120): step(gravity=(-9.81,0,0))
        gpu.uniform(program,'guide_mesh_history',1,integer=True)
        samples=[]
        for i in range(rate*2):
            plane_at(old_buffer,.12+.015*math.sin(math.tau*i/rate))
            plane_at(buffer,.12+.015*math.sin(math.tau*(i+1)/rate))
            result=step(dt=1/rate,gravity=(-9.81,0,0))
            samples.append(result[13][:3])
            assert max(math.sqrt(sum(v*v for v in p[:3])) for p in result[18:27])<=3.001
        gpu.uniform(program,'guide_mesh_history',0,integer=True)
        return samples
    at30,at60=animated_at_rate(30),animated_at_rate(60)
    difference=max(math.dist(a,b) for a,b in zip(at30,at60[1::2]))
    print('Animated contact 30/60 Hz maximum position difference:',difference)
    assert difference<.003,('moving contact frame-rate mismatch',difference)
    print('PASS: substep mesh interpolation, surface velocity, origin shift, invalid history and moving rope contact')
    # A stationary ridge has two competing contact normals, like a body protrusion.
    ridge=[(0,0,0,1),(0,0,0,2)]
    for end_z,sign in ((0,1),(-.8,-1)):
        normal=(1/math.sqrt(1.25),0,sign*.5/math.sqrt(1.25),0)
        for p in ((.18,-1,-.4),(.18,1,-.4),(-.02,0,end_z)):
            ridge.extend([(*p,0),normal])
    ridge.extend([(-.6,-.6,-1.56,.06)])
    ridge.extend([(3 if -1.56+(i//441)*.06>=-.4 else 9,0,0,0) for i in range(grid)])
    ridge_raw=struct.pack(f'{len(ridge)*4}f',*(x for p in ridge for x in p))
    gl.BindBuffer(SSBO,buffer);gl.BufferData(SSBO,len(ridge_raw),C.create_string_buffer(ridge_raw),0x88E8)
    gpu.uniform(program,'hair_mesh_contact',14,integer=True)
    step(0,False)
    for _ in range(360): mesh=step(gravity=(-2,0,-7),retention=.6)
    ridge_samples=[]
    for i in range(90):
        mesh=step(dt=1/60 if i%2 else 1/45,gravity=(-2,0,-7),retention=.6)
        ridge_samples.append([p[:3] for p in mesh[9:18]])
    ridge_motion=max(math.dist(a[i],b[i]) for a,b in zip(ridge_samples,ridge_samples[1:]) for i in range(9))
    print('Static ridge frame movement:',ridge_motion)
    assert ridge_motion<.001,('stationary ridge jitter',ridge_motion)
    # Sample contact on either side of the ridge's triangle-selection boundary.
    guide_source=(SHADERS/'class1/deferred/hairGuideC.glsl').read_text().replace('void main()', 'void simulationMain()')
    probe=gpu.compute(guide_source+'''
uniform vec3 probe_position;
uniform int legacy_contact, fixed_contact;
void main(){if(fixed_contact!=0){guide_out[0]=vec4(projectGuideContact(probe_position,sampleGuideContact(vec3(.05,0,-.48))),1);return;}guide_out[0]=vec4(legacy_contact!=0 ? probe_position+hairMeshMovement(probe_position,vec3(0),hair_mesh,hair_mesh_from_local,hair_collision_smoothing,hair_mesh_contact) : projectGuideContact(probe_position,sampleGuideContact(probe_position)),1);}
''',source)
    gpu.uniform(probe,'hair_mesh',30,integer=True)
    gpu.uniform(probe,'hair_mesh_nodes',1,integer=True);gpu.uniform(probe,'hair_mesh_contact',14,integer=True)
    gpu.matrix(probe,'hair_mesh_from_local',identity)
    out_buffer=gpu.obj(gl.GenBuffers)
    gl.BindBuffer(SSBO,out_buffer);gl.BufferData(SSBO,16,None,0x88E8)
    gl.BindBufferBase(SSBO,5,out_buffer)
    edge_samples=[]
    for z in (-.40001,-.39999):
        gpu.uniform(probe,'probe_position',.15,0,z)
        gl.DispatchCompute(1,1,1);gl.MemoryBarrier(0x2000|0x200)
        gl.BindBuffer(SSBO,out_buffer);out=C.create_string_buffer(16);gl.GetBufferSubData(SSBO,0,16,out)
        edge_samples.append(struct.unpack('4f',out.raw)[:3])
    assert math.dist(*edge_samples)<.0001,('triangle-switch discontinuity',edge_samples)
    gpu.uniform(probe,'legacy_contact',1,integer=True)
    legacy_samples=[]
    for z in (-.40001,-.39999):
        gpu.uniform(probe,'probe_position',.15,0,z)
        gl.DispatchCompute(1,1,1);gl.MemoryBarrier(0x2000|0x200)
        gl.BindBuffer(SSBO,out_buffer);out=C.create_string_buffer(16);gl.GetBufferSubData(SSBO,0,16,out)
        legacy_samples.append(struct.unpack('4f',out.raw)[:3])
    print('Ridge contact discontinuity, sweep/guides:',math.dist(*legacy_samples),math.dist(*edge_samples))
    assert math.dist(*legacy_samples)<.0001, ('sweep triangle-switch discontinuity',legacy_samples)
    # Constraint iterations crossing the ridge must keep the sampled plane's direction.
    gpu.uniform(probe,'fixed_contact',1,integer=True)
    slopes=[]
    for z in (-.48,-.32):
        gpu.uniform(probe,'probe_position',.05,0,z)
        gl.DispatchCompute(1,1,1);gl.MemoryBarrier(0x2000|0x200)
        gl.BindBuffer(SSBO,out_buffer);out=C.create_string_buffer(16);gl.GetBufferSubData(SSBO,0,16,out)
        moved=struct.unpack('4f',out.raw)
        assert moved[0]>.05 and moved[2]<z,('fixed plane changed direction across ridge',moved,z)
        slopes.append((moved[2]-z)/(moved[0]-.05))
    assert abs(slopes[0]-slopes[1])<1.e-5,('constraint iteration rotated contact plane',slopes)
    print('PASS: fixed contact plane keeps its normal across a ridge during constraint projection')
    gpu.uniform(program,'hair_mesh_nodes',0,integer=True)
    gpu.uniform(program,'hair_mesh_contact',0,integer=True)
    # A local touch must move its neighbours through constraints, with no shared regional rotation.
    step(0,False)
    gl.BufferSubData=C.WINFUNCTYPE(None,U,C.c_ssize_t,C.c_ssize_t,C.c_void_p)(sdl.SDL_GL_GetProcAddress(b'glBufferSubData'))
    gl.BindBuffer(SSBO,buffers[(frame-1)%2][0])
    touched=struct.pack('4f',.2,0,-.4,1)
    gl.BufferSubData(SSBO,13*16,16,C.create_string_buffer(touched))
    pulled=step()
    assert pulled[12][0]>.1501 and pulled[14][0]>.1501,(pulled[12],pulled[14])
    # All visible passes use the same guide interpolation; turning it off restores the authored geometry.
    probe='''uniform vec3 sample_position;out vec3 moved;
vec3 getHairDeformedPosition(vec3 p);
void main(){moved=getHairDeformedPosition(sample_position);vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));gl_Position=vec4(p[gl_VertexID],0,1);}'''
    render=gpu.program('in vec3 moved;out vec4 frag_color;void main(){frag_color=vec4(moved,1);}',probe)
    for name in ('hair_local_from_model','hair_model_from_local'):gpu.matrix(render,name,identity)
    gpu.uniform(render,'hair_guides',29,integer=True)
    gpu.uniform(render,'hair_guide_active',1,integer=True)
    gpu.uniform(render,'hair_root_radius',.08);gpu.uniform(render,'hair_root_gradient',.1)
    gl.ActiveTexture(0x84C0+29);gl.BindTexture(0x8C2A,buffers[(frame-1)%2][1])
    target=gpu.texture();pixel=(H//2*W+W//2)*4
    def sample(p):
        gpu.uniform(render,'sample_position',*p);gpu.draw(render,target)
        return gpu.read(target)[pixel:pixel+3]
    assert math.dist(sample((.15,0,-.4)),pulled[13][:3])<.001
    assert math.dist(sample((0,0,.04)),(0,0,.04))<.0001
    a,b=sample((.15,-.00001,-.4)),sample((.15,.00001,-.4))
    assert math.dist(a,b)<.001,(a,b)
    gpu.uniform(render,'hair_guide_active',0,integer=True)
    assert math.dist(sample((.15,0,-.4)),(.15,0,-.4))<.001
    vertex='#define main productionMain\n'+(SHADERS/'class1/deferred/taaMotionV.glsl').read_text()+'''
#undef main
void main(){productionMain();vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));gl_Position=vec4(p[gl_VertexID],0,1);}'''
    temporal=gpu.program('in vec4 previous_clip;out vec4 frag_color;void main(){frag_color=previous_clip;}',vertex)
    for name in ('taa_previous_mvp','taa_previous_modelview','modelview_projection_matrix','hair_previous_local_from_model','hair_previous_model_from_local'):
        gpu.matrix(temporal,name,identity)
    gpu.uniform(temporal,'hair_previous_guide_active',1,integer=True)
    gpu.uniform(temporal,'hair_previous_guides',29,integer=True)
    gpu.uniform(temporal,'hair_previous_root_radius',.08);gpu.uniform(temporal,'hair_previous_root_gradient',.1)
    gl.VertexAttrib4f(0,.15,0,-.4,1)
    gpu.draw(temporal,target)
    assert math.dist(gpu.read(target)[pixel:pixel+3],pulled[13][:3])<.001
    assert gl.GetError()==0
    print('PASS: guides, pins, inertia, gravity, constraints, 30/60/7 Hz, reset, mesh collision, neighbour pull, render interpolation, seams and disabled pass-through')


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try: run(sdl,gl)
    finally: sdl.SDL_GL_DestroyContext(ctx); sdl.SDL_DestroyWindow(window); sdl.SDL_Quit()

