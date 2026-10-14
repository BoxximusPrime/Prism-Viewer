"""Production collision-cache persistence: near ties, movement, independent hands and reset."""
import ctypes as C
from array import array
import math
import statistics
import struct
from test_taa_gpu import GPU, SHADERS
from test_exact_oit_gpu import context, U, SSBO


def run(sdl, gl):
    gpu=GPU(sdl,gl)
    gl.TexBuffer=C.WINFUNCTYPE(None,U,U,U)(sdl.SDL_GL_GetProcAddress(b'glTexBuffer'))
    sources=[(SHADERS/'class1/deferred'/name).read_text() for name in ('hairContactC.glsl','hairCollision.glsl')]
    shader=gpu.compute(*sources)
    grid=21*21*32; offset=26; index=12+21*(10+21*19)
    identity=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
    gpu.matrix(shader,'contact_to_mesh',identity)
    for name,value in {'hair_mesh':30,'hair_previous_mesh':31,'mesh_node_count':1,'contact_offset':offset}.items():
        gpu.uniform(shader,name,value,integer=True)
    slots=[]
    for channel in (30,31):
        buffer,texture=gpu.obj(gl.GenBuffers),gpu.obj(gl.GenTextures)
        gl.ActiveTexture(0x84C0+channel);gl.BindTexture(0x8C2A,texture)
        gl.BindBuffer(SSBO,buffer);gl.BufferData(SSBO,(offset+1)*16,None,0x88E8)
        gl.TexBuffer(0x8C2A,0x8814,buffer)
        slots.append(buffer)
    def upload(buffer,planes,retained=(3,15)):
        values=[(min(planes),-1,-1.5,-1.5),(max(planes),1,1,4)]
        for i,x in enumerate(planes):
            for y,z in ((-1,-1.5),(1,-1.5),(0,1)):
                values.extend(((x,y,z,1 if i>=2 else 0),(1 if i<2 else -1,0,0,0)))
        values.extend([(-.6,-.6,-1.56,.06)]+[(*retained,0,0)]*grid)
        packed=struct.pack(f'{len(values)*4}f',*(v for p in values for v in p))
        gl.BindBuffer(SSBO,buffer);gl.BufferData(SSBO,len(packed),C.create_string_buffer(packed),0x88E8)
    def dispatch(program,batched=False):
        gl.UseProgram(program)
        for first in range(0,grid,1024 if batched else grid):
            gpu.uniform(program,'contact_first',first,integer=True)
            gl.DispatchCompute((min(1024 if batched else grid,grid-first)+127)//128,1,1)
        gl.MemoryBarrier(0x2000|0x200|0x8)

    def sample(history,planes=(.1,.102,.14,.138),retained=(3,15),batched=False):
        upload(slots[0],planes);upload(slots[1],(.1,.102,.14,.138),retained)
        gl.BindBufferBase(SSBO,4,slots[0])
        gpu.uniform(shader,'contact_history',int(history),integer=True)
        dispatch(shader,batched)
        gl.BindBuffer(SSBO,slots[0]);out=C.create_string_buffer(16)
        gl.GetBufferSubData(SSBO,(offset+1+index)*16,16,out)
        result=tuple(round(v) for v in struct.unpack('4f',out.raw)[:2])
        # The 6 cm grid ends in a partial workgroup; its last cell must still be updated.
        gl.GetBufferSubData(SSBO,(offset+1+grid-1)*16,16,out)
        assert struct.unpack('4f',out.raw)[:2]==(0.,0.), 'last grid cell was not dispatched'
        return result
    assert sample(False)==(9,21), 'fresh cache must select nearest body and hand'
    assert sample(True)==(3,15), 'near ties must retain both contact identities'
    assert sample(True,(.08,.102,.16,.138))==(9,21), 'animated surfaces that moved away must release'
    assert sample(True,retained=(999999,0))==(9,21), 'invalid history offsets must be ignored'
    assert sample(False,retained=(3,15))==(9,21), 'reset must discard persistence'
    assert sample(True,retained=(4,16))==(9,21), 'unaligned history offsets must be ignored'
    assert sample(True,retained=(15,3))==(9,21), 'history cannot swap body and hand groups'
    sample(True)
    whole=C.create_string_buffer(grid*16);gl.GetBufferSubData(SSBO,(offset+1)*16,len(whole),whole)
    sample(True,batched=True)
    batches=C.create_string_buffer(grid*16);gl.GetBufferSubData(SSBO,(offset+1)*16,len(batches),batches)
    assert whole.raw==batches.raw, 'batching changed cache results or missed cells'

    # Instrument actual executed operations, including the two retained-triangle seed evaluations.
    source=sources[0].replace('void main()', 'int node_visits=0,triangle_tests=0;\nvoid main()')
    source=source.replace('        vec4 lo=texelFetch', '        ++node_visits;\n        vec4 lo=texelFetch')
    source=source.replace('vec4 a=texelFetch', '++triangle_tests; vec4 a=texelFetch')
    source=source.replace('vec4(vec2(nearest+1),0,0)', 'vec4(vec2(nearest+1),node_visits,triangle_tests)')
    bounded=gpu.compute(source,sources[1])
    gpu.matrix(bounded,'contact_to_mesh',identity)
    data=array('f')
    leaf_size=4
    def tree(first,n):
        start=len(data);data.extend([0]*8)
        if n>leaf_size:
            middle=n//2;tree(first,middle);tree(first+middle,n-middle)
        data[start:start+8]=array('f',(-1,-1,-2,len(data)//8+.5,1,1,1,first*8+n if n<=leaf_size else 0))
    tree(0,524288)
    nodes=len(data)//8
    triangle=array('f',(-1,-1,-2,0,0,0,1,0,1,1,-2,0,0,0,1,0,1,-1,1,0,0,0,1,0))
    data.extend(triangle*524288);large_offset=len(data)//4
    data.extend((-.6,-.6,-1.56,.06))
    data.extend(array('f',[nodes*2+1,0,0,0])*grid)
    for slot in slots:
        gl.BindBuffer(SSBO,slot);gl.BufferData(SSBO,len(data)*4,data.buffer_info()[0],0x88E8)
    for name,value in {'hair_mesh':30,'hair_previous_mesh':31,'mesh_node_count':nodes,'contact_offset':large_offset,'contact_history':1}.items():
        gpu.uniform(bounded,name,value,integer=True)
    gl.BindBufferBase(SSBO,4,slots[0]);dispatch(bounded,True)
    gl.BindBuffer(SSBO,slots[0]);raw=C.create_string_buffer(grid*16)
    gl.GetBufferSubData(SSBO,(large_offset+1)*16,len(raw),raw)
    counts=list(struct.iter_unpack('4f',raw.raw))
    assert all(all(math.isfinite(x) for x in row) and 0<=row[2]<=128 and 0<=row[3]<=66 for row in counts)
    assert max(row[3] for row in counts)>=64, 'stress fixture did not exhaust its triangle budget'
    print('524288 overlapping triangles / 14112 cells: max node visits / total triangle evaluations per cell:',
          max(row[2] for row in counts),max(row[3] for row in counts))
    query=gpu.obj(gl.GenQueries);times=[]
    for frame in range(15):
        gl.BeginQuery(0x88BF,query);dispatch(bounded,True);gl.EndQuery(0x88BF)
        elapsed=C.c_uint64();gl.GetQueryObjectui64v(query,0x8866,C.byref(elapsed))
        if frame>=5:times.append(elapsed.value/1.e6)
    print('Instrumented whole-cache GPU ms, 5 warmup / 10 measured:',times)
    print('Median / max:',statistics.median(times),max(times))
    # Single-triangle leaves reach the independent node ceiling before the triangle ceiling.
    data=array('f');leaf_size=1;tree(0,1024);nodes=len(data)//8
    data.extend(triangle*1024);large_offset=len(data)//4
    data.extend((-.6,-.6,-1.56,.06))
    data.extend(array('f',[nodes*2+1,0,0,0])*grid)
    for slot in slots:
        gl.BindBuffer(SSBO,slot);gl.BufferData(SSBO,len(data)*4,data.buffer_info()[0],0x88E8)
    gpu.uniform(bounded,'mesh_node_count',nodes,integer=True)
    gpu.uniform(bounded,'contact_offset',large_offset,integer=True)
    dispatch(bounded,True)
    gl.BindBuffer(SSBO,slots[0]);gl.GetBufferSubData(SSBO,(large_offset+1)*16,len(raw),raw)
    counts=list(struct.iter_unpack('4f',raw.raw))
    assert all(0<=row[2]<=128 and 0<=row[3]<=66 for row in counts)
    assert max(row[2] for row in counts)==128, 'node budget was not exercised'
    print('PASS: independent 128-node ceiling, including seeded history')
    assert gl.GetError()==0
    print('PASS: production contact-cache near ties, animated release, independent hands and history reset')


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try: run(sdl,gl)
    finally: sdl.SDL_GL_DestroyContext(ctx);sdl.SDL_DestroyWindow(window);sdl.SDL_Quit()
