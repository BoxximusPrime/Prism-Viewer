"""Thin shoulder contacts must not create ghost planes when grid corners see opposite faces."""
import ctypes as C
import math
import struct
from test_taa_gpu import GPU, SHADERS
from test_exact_oit_gpu import context, U, SSBO


def run(sdl, gl):
    gpu=GPU(sdl,gl)
    gl.TexBuffer=C.WINFUNCTYPE(None,U,U,U)(sdl.SDL_GL_GetProcAddress(b'glTexBuffer'))
    common=(SHADERS/'class1/deferred/hairCollision.glsl').read_text()
    guide=(SHADERS/'class1/deferred/hairGuideC.glsl').read_text()
    cache=gpu.compute((SHADERS/'class1/deferred/hairContactC.glsl').read_text(),common)
    probe=gpu.compute(guide.replace('void main()', 'void guideMain()')+'''
uniform vec3 probe_position;
void main(){if(gl_GlobalInvocationID.x!=0u)return;
GuideContact contact=sampleGuideContact(probe_position);
guide_out[0]=vec4(projectGuideContact(probe_position,contact),1);
guide_out[1]=contact.plane[0];
guide_out[2]=vec4(probe_position+hairMeshMovement(probe_position,vec3(0),hair_mesh,hair_mesh_from_local,0,hair_mesh_contact),1);}
''',common)
    identity=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
    def buffer(values):
        b,t=gpu.obj(gl.GenBuffers),gpu.obj(gl.GenTextures)
        raw=struct.pack(f'{len(values)*4}f',*(v for p in values for v in p))
        gl.BindBuffer(SSBO,b);gl.BufferData(SSBO,len(raw),C.create_string_buffer(raw),0x88E8)
        gl.BindTexture(0x8C2A,t);gl.TexBuffer(0x8C2A,0x8814,b)
        return b,t
    grid=21*21*32;offset=14
    shell=[(-.025,-1,-2,1.5),(.025,1,1,2)]
    # Opposite sides of a 5 cm thick shoulder section straddle one 6 cm cache cell.
    for x,n in ((-.025,-1),(.025,1)):
        for y,z in ((-1,-2),(1,-2),(0,1)):
            shell.extend(((x,y,z,0),(n,0,0,0)))
    shell.extend([(0,0,0,0)]*(grid+1))
    mesh=buffer(shell);out=buffer([(0,0,0,0)]*3)
    gl.ActiveTexture(0x84C0+30);gl.BindTexture(0x8C2A,mesh[1])
    for p in (cache,probe):gpu.uniform(p,'hair_mesh',30,integer=True)
    gpu.matrix(cache,'contact_to_mesh',identity)
    gpu.uniform(cache,'mesh_node_count',1,integer=True);gpu.uniform(cache,'contact_offset',offset,integer=True)
    gl.UseProgram(cache);gl.BindBufferBase(SSBO,4,mesh[0])
    gl.DispatchCompute((grid+127)//128,1,1);gl.MemoryBarrier(0x2000|0x8|0x200)
    gpu.matrix(probe,'hair_mesh_from_local',identity)
    gpu.uniform(probe,'hair_mesh_nodes',1,integer=True);gpu.uniform(probe,'hair_mesh_contact',offset,integer=True)
    gl.BindBufferBase(SSBO,5,out[0])
    def sample(x):
        gpu.uniform(probe,'probe_position',x,0,-.4)
        gl.DispatchCompute(1,1,1);gl.MemoryBarrier(0x2000|0x200)
        gl.BindBuffer(SSBO,out[0]);raw=C.create_string_buffer(48)
        gl.GetBufferSubData(SSBO,0,48,raw)
        return list(struct.iter_unpack('4f',raw.raw))
    points=[.0359,.0361,.04,.05,.07,-.0359,-.0361,-.04,-.05,-.07]
    shifts=[math.dist(sample(x)[0][:3],(x,0,-.4)) for x in points]
    print('Outside shoulder x / spurious push (m):',list(zip(points,shifts)))
    assert max(shifts)<1.e-5, 'opposite cached faces create a phantom contact outside the shell'
    assert max(math.dist(sample(x)[2][:3],(x,0,-.4)) for x in points)<1.e-5, 'sweep helper creates a phantom contact'
    for x,expected in ((.022,.03),(-.022,-.03)):
        result=sample(x)
        assert abs(result[0][0]-expected)<1.e-5, ('near-surface penetration was not recovered',x,result)
        assert abs(result[2][0]-expected)<1.e-5, ('sweep penetration was not recovered',x,result)
    # The same submillimetre head motion must not become a centimetre-scale rope displacement.
    solver=gpu.compute(guide,common)
    rest=[(.0359,0,-i*.08,1) for i in range(9)]
    old=buffer(rest+rest+[(0,0,0,0)]*9);solved=buffer(rest+rest+[(0,0,0,0)]*9)
    gl.ActiveTexture(0x84C0+30);gl.BindTexture(0x8C2A,mesh[1])
    gl.ActiveTexture(0x84C0+29);gl.BindTexture(0x8C2A,old[1])
    for name,value in {'hair_previous_guides':29,'hair_mesh':30,'hair_mesh_nodes':1,'hair_mesh_contact':offset,'guide_history':1}.items():
        gpu.uniform(solver,name,value,integer=True)
    for name,value in {'guide_dt':1/120,'guide_stiffness':5.5,'guide_retention':1,'guide_bend':2.4,'guide_elasticity':.15,
                       'hair_root_radius':.1,'hair_root_gradient':1}.items():gpu.uniform(solver,name,value)
    shifted=[row[:] for row in identity];shifted[0][3]=.0002
    gpu.matrix(solver,'guide_from_previous',shifted);gpu.matrix(solver,'hair_mesh_from_local',identity)
    gl.BindBufferBase(SSBO,5,solved[0]);gl.DispatchCompute(1,1,1);gl.MemoryBarrier(0x2000|0x8|0x200)
    gl.BindBuffer(SSBO,solved[0]);raw=C.create_string_buffer(27*16);gl.GetBufferSubData(SSBO,0,len(raw),raw)
    values=list(struct.iter_unpack('4f',raw.raw))
    displacement=max(math.dist(values[9+i][:3],rest[i][:3]) for i in range(9))
    print('Full rope maximum movement for 0.2 mm head motion (m):',displacement)
    assert displacement<.001, 'shoulder contact turned slight motion into a rope jump'
    assert math.dist(values[9][:3],rest[0][:3])<1.e-6, 'root pin moved'
    # Capture diagnostics must preserve simulation results and stay within their per-rope slice.
    diagnostics=buffer([(0,0,0,0)]*63+[(123,456,789,321)])
    gl.ActiveTexture(0x84C0+29);gl.BindTexture(0x8C2A,old[1])
    gl.BindBufferBase(SSBO,6,diagnostics[0])
    gpu.uniform(solver,'guide_diagnostics',1,integer=True)
    gl.BindBufferBase(SSBO,5,solved[0]);gl.DispatchCompute(1,1,1);gl.MemoryBarrier(0x2000|0x200)
    gl.BindBuffer(SSBO,solved[0]);gl.GetBufferSubData(SSBO,0,len(raw),raw)
    assert values==list(struct.iter_unpack('4f',raw.raw)), 'diagnostics changed rope motion'
    gl.BindBuffer(SSBO,diagnostics[0]);probe_raw=C.create_string_buffer(64*16)
    gl.GetBufferSubData(SSBO,0,len(probe_raw),probe_raw)
    probes=list(struct.iter_unpack('4f',probe_raw.raw))
    assert probes[63]==(123,456,789,321), 'diagnostic output overran its slice'
    assert abs(probes[57][0]-1)<1.e-6 and abs(probes[57][3]-.03)<1.e-5, probes[57]
    assert abs(probes[59][0]-.025)<1.e-5 and probes[59][3]>0, probes[59]
    assert max(abs(v) for v in probes[60][:3])<1.e-6, probes[60]
    assert max(abs(probes[i][0]-1) for i in (61,62))<1.e-6, ('incorrect normal probe',probes[61:63])
    print('PASS: bounded contact probe preserves simulation and records the actual supporting plane')
    # An offset surface can win a neighbouring grid corner without touching this point.
    # Its parallel plane must not shove a rope already clear of its nearest surface.
    patch=[(0,-1,-2,1.5),(.08,1,1,2)]
    for triangle in (((0,-1,-2),(0,1,-2),(0,0,1)),
                     ((.08,.035,-.43),(.08,.065,-.43),(.08,.05,-.37))):
        for vertex in triangle:patch.extend(((*vertex,0),(1,0,0,0)))
    patch.extend([(0,0,0,0)]*(grid+1))
    raised=buffer(patch)
    gl.ActiveTexture(0x84C0+30);gl.BindTexture(0x8C2A,raised[1])
    gl.UseProgram(cache);gl.BindBufferBase(SSBO,4,raised[0])
    gl.DispatchCompute((grid+127)//128,1,1);gl.MemoryBarrier(0x2000|0x8|0x200)
    gl.BindBufferBase(SSBO,5,out[0])
    shifts=[math.dist(sample(x)[0][:3],(x,0,-.4)) for x in (.006,.01,.02)]
    print('Clear point beside a raised patch / false correction (m):',shifts)
    assert max(shifts)<1.e-5, 'a distant finite patch invents a contact at its extended plane'
    assert max(math.dist(sample(x)[2][:3],(x,0,-.4)) for x in (.006,.01,.02))<1.e-5, 'shared helper extends a distant patch'
    assert gl.GetError()==0
    print('PASS: opposite-side cache blending creates no shoulder jump and retains surface recovery')


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try:run(sdl,gl)
    finally:sdl.SDL_GL_DestroyContext(ctx);sdl.SDL_DestroyWindow(window);sdl.SDL_Quit()
