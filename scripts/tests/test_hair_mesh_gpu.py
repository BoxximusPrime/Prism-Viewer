"""Production GPU shell skinning/refit, triangle contact, pinned roots and temporal poses."""
import ctypes as C
import math
import struct
from test_taa_gpu import GPU, SHADERS, W, H
from test_exact_oit_gpu import context, U, I, F, P, SSBO


def run(sdl, gl):
    gpu = GPU(sdl, gl)
    gl.TexBuffer = C.WINFUNCTYPE(None,U,U,U)(sdl.SDL_GL_GetProcAddress(b'glTexBuffer'))
    source=(SHADERS/'class1/deferred/hairMeshC.glsl').read_text()
    programs=[]
    for mode in ('MESH_SKIN','MESH_REFIT'):
        shader=gl.CreateShader(0x91B9)
        code=C.c_char_p(('#version 430\n#define '+mode+' 1\n'+source).encode())
        gl.ShaderSource(shader,1,C.byref(code),None);gl.CompileShader(shader)
        ok,log=I(),C.create_string_buffer(16384)
        gl.GetShaderiv(shader,0x8B81,C.byref(ok));gl.GetShaderInfoLog(shader,len(log),None,log)
        assert ok.value,log.value.decode()
        p=gl.CreateProgram();gl.AttachShader(p,shader);gl.LinkProgram(p)
        gl.GetProgramiv(p,0x8B82,C.byref(ok));gl.GetProgramInfoLog(p,len(log),None,log)
        assert ok.value,log.value.decode()
        programs.append(p)
    identity=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
    cache=gpu.compute(*[(SHADERS/'class1/deferred'/name).read_text() for name in ('hairContactC.glsl','hairCollision.glsl')])
    gpu.matrix(cache,'contact_to_mesh',identity)
    gpu.uniform(cache,'hair_mesh',30,integer=True)
    gpu.uniform(cache,'mesh_node_count',7,integer=True)
    gpu.uniform(cache,'contact_offset',92,integer=True)
    vertices=[]
    for axis in range(3):
        for side in (-1,1):
            normal=[0.,0.,0.];normal[axis]=side
            corners=[]
            for u,v in ((-1,-1),(1,-1),(1,1),(-1,1)):
                p=[0.,0.,0.];p[axis]=side*.3
                p[(axis+1)%3]=u*.3;p[(axis+2)%3]=v*.3
                corners.append(p)
            for indices in ((0,1,2),(0,2,3)):
                for index in indices: vertices.append((*corners[index],1,*normal,.25 if axis==0 and side==1 else 0,.25,.75,0,0,0,1,0,0))
    vertices += [(0,0,0,1,0,0,0,0,.25,.75,0,0,0,1,0,0)]*3
    nodes=[(1,0,7,4),(2,0,4,3),(0,3,3,0),(3,3,4,0),(5,0,7,6),(6,3,6,0),(9,4,7,0)]
    levels=[0,1,4,2,3,5,6]
    buffers=[gpu.obj(gl.GenBuffers) for _ in range(4)]
    def upload(buffer,data):
        gl.BindBuffer(SSBO,buffer);gl.BufferData(SSBO,len(data),C.create_string_buffer(data),0x88E8)
    upload(buffers[0],b''.join(struct.pack('12f4I',*v) for v in vertices))
    upload(buffers[1],b''.join(struct.pack('4I',*v) for v in nodes))
    upload(buffers[2],struct.pack('7I',*levels))
    shells=[]
    size=(len(nodes)*2+13*6+21*21*32+1)*16
    for _ in range(2):
        buffer,texture=gpu.obj(gl.GenBuffers),gpu.obj(gl.GenTextures)
        gl.BindBuffer(SSBO,buffer);gl.BufferData(SSBO,size,C.create_string_buffer(size),0x88E8)
        gl.BindTexture(0x8C2A,texture);gl.TexBuffer(0x8C2A,0x8814,buffer)
        shells.append((buffer,texture))
    checks=0
    def rebuild(slot,shift,scale,padding=0):
        nonlocal checks
        # Two bones with different translations exercise weighted skinning, including nonuniform fitted scaling.
        matrices=[]
        for x in (shift-.075,shift+.025):
            matrices.extend((scale[0],0,0,x,0,scale[1],0,0,0,0,scale[2],0))
        upload(buffers[3],struct.pack('24f',*matrices))
        for i,b in enumerate(buffers):gl.BindBufferBase(SSBO,i,b)
        gl.BindBufferBase(SSBO,4,shells[slot][0])
        gpu.uniform(programs[0],'mesh_node_count',7,integer=True)
        gpu.uniform(programs[0],'mesh_vertex_count',39,integer=True)
        gpu.uniform(programs[0],'mesh_padding',padding)
        gl.DispatchCompute(1,1,1);gl.MemoryBarrier(0x2000)
        for first,count in ((3,4),(1,2),(0,1)):
            gpu.uniform(programs[1],'mesh_node_count',7,integer=True)
            gpu.uniform(programs[1],'mesh_level_first',first,integer=True)
            gpu.uniform(programs[1],'mesh_level_count',count,integer=True)
            gl.DispatchCompute(1,1,1);gl.MemoryBarrier(0x2000)
        gl.MemoryBarrier(0x8)
        gl.ActiveTexture(0x84C0+30);gl.BindTexture(0x8C2A,shells[slot][1])
        gl.UseProgram(cache);gl.DispatchCompute((21*21*32+127)//128,1,1);gl.MemoryBarrier(0x2000|0x8)
        gl.BindBuffer(SSBO,shells[slot][0]);data=C.create_string_buffer(size)
        gl.GetBufferSubData(SSBO,0,size,data)
        values=struct.unpack(f'{size//4}f',data.raw)
        for i,v in enumerate(vertices):
            actual=values[56+i*8:56+i*8+3]
            expected=[v[a]*scale[a]+(shift if a==0 else 0)+v[4+a]*min(.1,max(0,padding)) for a in range(3)]
            assert max(abs(a-b) for a,b in zip(actual,expected))<1.e-6,(actual,expected)
            assert values[56+i*8+3]==v[7]
            actual_normal=values[60+i*8:60+i*8+3]
            assert max(abs(actual_normal[a]-v[4+a]/scale[a]) for a in range(3))<1.e-6
            checks+=1
        for i,n in enumerate(nodes):
            lo,hi=values[i*8:i*8+3],values[i*8+4:i*8+7]
            assert all(a<=b for a,b in zip(lo,hi))
            hand = any(vertices[v][7]>.15 for v in range(n[0]*3,(n[0]+n[1])*3)) if n[1] else values[n[0]*8+3]<0 or values[n[3]*8+3]<0
            body = any(max(vertices[v+j][7] for j in range(3))<=.15 for v in range(n[0]*3,(n[0]+n[1])*3,3)) if n[1] else abs(values[n[0]*8+3])%1>0 or abs(values[n[3]*8+3])%1>0
            escape=n[2]+(.5 if body else 0)
            assert values[i*8+3]==(-escape if hand else escape)
            if n[1]:
                assert values[i*8+7]==n[0]*8+n[1]
                for v in range(n[0]*3,(n[0]+n[1])*3):
                    assert all(lo[a]-1.e-6<=values[56+v*8+a]<=hi[a]+1.e-6 for a in range(3))
            else:
                for child in (n[0],n[3]):
                    assert all(lo[a]<=values[child*8+a] and hi[a]>=values[child*8+4+a] for a in range(3))
            checks+=1
        assert gl.GetError()==0
    # Padding is measured after fitted scaling; refitted bounds enclose the expanded shell.
    for padding in (.025,.1,.2,-.1): rebuild(0,0,(.8,1.2,.6),padding)
    rebuild(0,0,(1,1,1));rebuild(1,.18,(.8,1.2,.6))
    identity=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
    probe='''uniform vec3 sample_position, sample_movement;
uniform samplerBuffer hair_mesh; uniform mat4 hair_mesh_from_local;
uniform int hair_mesh_nodes, hair_mesh_contact; uniform float hair_collision_smoothing;
vec3 hairMeshMovement(vec3 original, vec3 movement, samplerBuffer mesh, mat4 from_local, float smoothing, int cache);
out vec3 moved;
void main(){ moved=sample_position+hairMeshMovement(sample_position,sample_movement,hair_mesh,hair_mesh_from_local,hair_collision_smoothing,hair_mesh_contact);
vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));gl_Position=vec4(p[gl_VertexID],0,1); }'''
    program=gpu.program('in vec3 moved;out vec4 frag_color;void main(){frag_color=vec4(moved,1);}',probe,
                        (SHADERS/'class1/deferred/hairCollision.glsl').read_text())
    target=gpu.texture()
    gpu.matrix(program,'hair_mesh_from_local',identity)
    gpu.uniform(program,'hair_mesh_nodes',7,integer=True)
    gpu.uniform(program,'hair_mesh_contact',92,integer=True)
    gl.ActiveTexture(0x84C0+30);gl.BindTexture(0x8C2A,shells[0][1])
    pixel=(H//2*W+W//2)*4
    for soft in (0,.005,.05,.15):
        gpu.uniform(program,'hair_collision_smoothing',soft)
        for original,movement in (((.7,0,0),(-1.4,0,0)),((.7,0,0),(-.6,.12,0)),
                                  ((.4,0,0),(.4,0,0)),((.29,0,0),(0,0,0)),
                                  ((.3,0,0),(0,.15,0)),((.6,0,0),(0,0,0)),
                                  ((.6,.6,0),(-.4,0,0))):
            gpu.uniform(program,'sample_position',*original);gpu.uniform(program,'sample_movement',*movement)
            gpu.draw(program,target);actual=gpu.read(target)[pixel:pixel+3]
            if original[1]==0 and (movement[0]<0 or original[0]<=.3):
                assert actual[0]>=.3-1.e-3,(original,movement,soft,actual)
                assert abs(actual[1]-movement[1])<.002,actual
            else:
                assert max(abs(actual[k]-original[k]-movement[k]) for k in range(3))<.001,actual
            checks+=1
    # Moving shell pushes stationary hair; no oscillator motion is needed.
    gpu.uniform(program,'sample_position',.4,0,0);gpu.uniform(program,'sample_movement',0,0,0)
    gl.ActiveTexture(0x84C0+30);gl.BindTexture(0x8C2A,shells[1][1])
    gpu.draw(program,target);assert gpu.read(target)[pixel]>.419
    checks+=1
    # A stationary vertex deeper than the old 10 cm cutoff must escape the body.
    gl.ActiveTexture(0x84C0+30);gl.BindTexture(0x8C2A,shells[0][1])
    gpu.uniform(program,'sample_position',-.16,0,0);gpu.uniform(program,'sample_movement',0,0,0)
    gpu.draw(program,target);actual=gpu.read(target)[pixel:pixel+3]
    assert actual[0]<=-.3 and abs(actual[1])+abs(actual[2])<.001, ('trapped inside body',actual)
    checks+=1
    # Rigid head-local coordinates must give the same contact as avatar-relative coordinates.
    rotation=[[0,-1,0,0],[1,0,0,0],[0,0,1,0],[0,0,0,1]]
    gpu.matrix(cache,'contact_to_mesh',rotation)
    gl.BindBufferBase(SSBO,4,shells[0][0]);gl.ActiveTexture(0x84C0+30);gl.BindTexture(0x8C2A,shells[0][1])
    gl.UseProgram(cache);gl.DispatchCompute((21*21*32+127)//128,1,1);gl.MemoryBarrier(0x2000|0x8)
    gpu.matrix(program,'hair_mesh_from_local',rotation)
    gpu.uniform(program,'sample_position',0,-.7,0);gpu.uniform(program,'sample_movement',0,.6,0)
    gl.ActiveTexture(0x84C0+30);gl.BindTexture(0x8C2A,shells[0][1])
    gpu.draw(program,target);assert gpu.read(target)[pixel+1]<-.3
    checks+=1
    gpu.matrix(cache,'contact_to_mesh',identity)
    gl.UseProgram(cache);gl.DispatchCompute((21*21*32+127)//128,1,1);gl.MemoryBarrier(0x2000|0x8)
    # A sweep intersects the finite triangle or its 5 mm thickness, never an 8 cm extended paddle.
    patch_buffer,patch_texture=gpu.obj(gl.GenBuffers),gpu.obj(gl.GenTextures)
    patch_data=[.3,.04,-.005,1.5,.3,.05,.005,1]
    for p in ((.3,.04,-.005),(.3,.05,-.005),(.3,.045,.005)):
        patch_data.extend((*p,0,1,0,0,0))
    patch_data.extend([0.]*(21*21*32+1)*4)
    upload(patch_buffer,struct.pack(f'{len(patch_data)}f',*patch_data))
    gl.ActiveTexture(0x84C0+30);gl.BindTexture(0x8C2A,patch_texture);gl.TexBuffer(0x8C2A,0x8814,patch_buffer)
    gl.BindBufferBase(SSBO,4,patch_buffer)
    gpu.uniform(cache,'mesh_node_count',1,integer=True);gpu.uniform(cache,'contact_offset',8,integer=True)
    gl.DispatchCompute((21*21*32+127)//128,1,1);gl.MemoryBarrier(0x2000|0x8)
    gpu.matrix(program,'hair_mesh_from_local',identity)
    gpu.uniform(program,'hair_mesh_nodes',1,integer=True);gpu.uniform(program,'hair_mesh_contact',8,integer=True)
    gpu.uniform(program,'hair_collision_smoothing',0)
    gpu.uniform(program,'sample_movement',-.7,0,0)
    for y,contact in ((.045,True),(.039,True),(0,False),(-.2,False)):
        gpu.uniform(program,'sample_position',.5,y,0);gpu.draw(program,target)
        actual=gpu.read(target)[pixel:pixel+3]
        assert actual[0]>=.3 if contact else abs(actual[0]+.2)<.001, ('gravity sweep missed patch',y,actual)
        assert abs(actual[1]-y)<.001 and abs(actual[2])<.001,actual
        checks+=1
    gpu.program((SHADERS/'class1/deferred/hairMeshDebugF.glsl').read_text(),(SHADERS/'class1/deferred/hairMeshDebugV.glsl').read_text())
    assert gl.GetError()==0
    print(f'PASS: {checks} shell skinning, fitted scaling, refit, swept contact, moving shell, bounded query GPU checks')


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try:run(sdl,gl)
    finally:sdl.SDL_GL_DestroyContext(ctx);sdl.SDL_DestroyWindow(window);sdl.SDL_Quit()
