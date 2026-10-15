"""Production finite contacts, continuous corner normals, and complete moving ropes."""
import ctypes as C
import json
import math
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/tests'))
from test_taa_gpu import GPU, SHADERS
from test_exact_oit_gpu import context, U, SSBO


def run(sdl, gl):
    gpu = GPU(sdl, gl)
    gl.TexBuffer = C.WINFUNCTYPE(None, U, U, U)(sdl.SDL_GL_GetProcAddress(b'glTexBuffer'))
    gl.BufferSubData = C.WINFUNCTYPE(None,U,C.c_ssize_t,C.c_ssize_t,C.c_void_p)(sdl.SDL_GL_GetProcAddress(b'glBufferSubData'))
    identity = [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
    common = (SHADERS / 'class1/deferred/hairCollision.glsl').read_text()
    source = (SHADERS / 'class1/deferred/hairGuideC.glsl').read_text()
    cache = gpu.compute((SHADERS / 'class1/deferred/hairContactC.glsl').read_text(), common)
    probe = gpu.compute(source.replace('void main()', 'void simulationMain()') + '''
uniform vec3 query;
void main(){if(gl_GlobalInvocationID.x!=0u)return;
GuideContact c=sampleGuideContact(query);
guide_out[0]=vec4(projectGuideContact(query,c),1);
guide_out[1]=c.plane[0];guide_out[2]=c.plane[1];
guide_out[3]=probe_nearest;guide_out[4]=probe_motion;
guide_out[5]=vec4(query+hairMeshMovement(query,vec3(0),hair_mesh,hair_mesh_from_local,0,hair_mesh_contact),1);
}
''', common)

    def buffer(values):
        b, t = gpu.obj(gl.GenBuffers), gpu.obj(gl.GenTextures)
        raw = struct.pack(f'{len(values)*4}f', *(x for row in values for x in row))
        gl.BindBuffer(SSBO, b); gl.BufferData(SSBO, len(raw), C.create_string_buffer(raw), 0x88E8)
        gl.BindTexture(0x8C2A, t); gl.TexBuffer(0x8C2A, 0x8814, b)
        return b, t

    def texture(unit, pair):
        gl.ActiveTexture(0x84C0+unit); gl.BindTexture(0x8C2A, pair[1])

    def dispatch(program, groups=1):
        gl.UseProgram(program); gl.DispatchCompute(groups,1,1)
        gl.MemoryBarrier(0x2000 | 0x8 | 0x200)

    def read(pair, count):
        gl.BindBuffer(SSBO, pair[0]); raw = C.create_string_buffer(count*16)
        gl.GetBufferSubData(SSBO, 0, len(raw), raw)
        return list(struct.iter_unpack('4f',raw.raw))

    gpu.matrix(cache, 'contact_to_mesh', identity)
    gpu.matrix(probe, 'hair_mesh_from_local', identity)
    for program in (cache, probe): gpu.uniform(program, 'hair_mesh', 30, integer=True)
    gpu.uniform(cache, 'mesh_node_count', 1, integer=True)
    gpu.uniform(probe, 'hair_mesh_nodes', 1, integer=True)
    gpu.uniform(probe, 'guide_diagnostics', 1, integer=True)
    output = buffer([(0,0,0,0)]*6)

    def scene(triangles, previous=None):
        nodes=[]; ordered=[]
        def tree(tris):
            index=len(nodes); nodes.append(None)
            points=[p for tri,n,kind in tris for p in tri]
            low=tuple(min(p[k] for p in points) for k in range(3))
            high=tuple(max(p[k] for p in points) for k in range(3))
            if len(tris)>4:
                axis=max(range(3),key=lambda k:high[k]-low[k])
                tris=sorted(tris,key=lambda t:sum(p[axis] for p in t[0]))
                tree(tris[:len(tris)//2]);tree(tris[len(tris)//2:]);leaf=0
            else:
                leaf=len(ordered)*8+len(tris);ordered.extend(tris)
            marker=len(nodes)+(0.5 if any(kind==0 for tri,n,kind in tris) else 0)
            if any(kind for tri,n,kind in tris):marker=-marker
            nodes[index]=[(*low,marker),(*high,leaf)]
        tree(triangles)
        data=[row for node in nodes for row in node]
        for tri,n,kind in ordered:
            for p in tri: data.extend(((*p,kind),(*n,0)))
        offset = len(data)
        data.extend([(0,0,0,0)]*(21*21*32+1))
        mesh = buffer(data); texture(30, mesh)
        texture(31, previous if previous else mesh)
        gpu.uniform(cache, 'hair_previous_mesh', 31, integer=True)
        gpu.uniform(cache, 'contact_history', int(previous is not None), integer=True)
        gpu.uniform(cache, 'contact_offset', offset, integer=True)
        gpu.uniform(cache, 'mesh_node_count', len(nodes), integer=True)
        gl.BindBufferBase(SSBO, 4, mesh[0]); dispatch(cache, (21*21*32+127)//128)
        gpu.uniform(probe, 'hair_mesh_contact', offset, integer=True)
        gpu.uniform(probe, 'hair_mesh_nodes', len(nodes), integer=True)
        return mesh, offset

    def sample(query):
        gpu.uniform(probe, 'query', *query)
        gl.BindBufferBase(SSBO, 5, output[0]); dispatch(probe)
        out = read(output,6)
        return {'query': query, 'projected':out[0][:3], 'plane':out[1], 'hand_plane':out[2],
                'nearest':out[3][:3], 'distance':out[4][3],
                'push_m':math.dist(query,out[0][:3]), 'sweep_helper':out[5][:3]}

    print('GPU:',gl.GetString(0x1F01).decode())
    # The point is beside a finite patch, never crossing or approaching its triangle.
    for kind in (0,1):
        scene([(((.08,.05,-.43),(.08,.09,-.43),(.08,.07,-.37)),(1,0,0),kind)])
        result=sample((.02,0,-.4)); result['kind']=kind
        print('FINITE_PATCH',json.dumps(result))
        assert result['push_m']<1.e-6, 'finite patch acts as an infinite plane'
        assert math.dist(result['query'],result['sweep_helper'])<1.e-6, 'sweep helper extends a finite patch'
        if kind==1:
            outside=sample((.02,-.049458788,-.4));inside=sample((.02,-.049456777,-.4))
            print('RANGE_ACTIVATION',json.dumps({'outside':outside,'inside':inside,
                  'input_delta_m':math.dist(outside['query'],inside['query']),
                  'output_delta_m':math.dist(outside['projected'],inside['projected'])}))
            assert max(outside['push_m'],inside['push_m'])<1.e-6

    # Two perpendicular nearby contacts. A 2.8-micrometre query movement must not
    # select completely different normals, as the old winner filter did.
    corner_mesh, corner_offset = scene([(((0,-.2,-.7),(0,.2,-.7),(0,0,-.1)),(1,0,0),0),
           (((-.2,0,-.7),(.2,0,-.7),(0,0,-.1)),(0,1,0),0)])
    a=sample((.002001,.001999,-.4)); b=sample((.001999,.002001,-.4))
    print('CORNER_SWITCH',json.dumps({'a':a,'b':b,'input_delta_m':math.dist(a['query'],b['query']),
                                    'output_delta_m':math.dist(a['projected'],b['projected'])}))
    assert math.dist(a['projected'],b['projected'])<.00001, 'nearest-normal selection jumps at the corner'
    assert math.dist(a['sweep_helper'],b['sweep_helper'])<.00001
    for result in (a,b):
        assert min(result['projected'][:2])>=.00499, 'corner lost clearance'
        assert min(result['sweep_helper'][:2])>=.00499
    # Both sides of thin closed sections remain clear; opposite normals never amplify a push.
    for thickness in (.05,.005,.001):
        scene([(((x,-1,-2),(x,1,-2),(x,0,1)),(sign,0,0),0)
               for x,sign in ((-thickness/2,-1),(thickness/2,1))])
        for sign in (-1,1):
            result=sample((sign*(thickness/2+.006),0,-.4))
            assert result['push_m']<1.e-6, ('opposite surface creates a false push',thickness,result)
    # Fine body triangles between coarse grid corners still need actual collision coverage.
    tiles=[]
    for y in range(12):
        for z in range(12):
            a=(0,-.06+y*.01,-.46+z*.01); b=(0,a[1]+.01,a[2])
            c=(0,a[1]+.01,a[2]+.01); d=(0,a[1],a[2]+.01)
            tiles.extend((( (a,b,c),(1,0,0),0),((a,c,d),(1,0,0),0)))
    scene(tiles)
    result=sample((.002,.027,-.403))
    assert result['projected'][0]>=.00499 and result['sweep_helper'][0]>=.00499, ('cache left a hole in the body',result)
    previous=None; history=[]
    for x in (.104,.103,.102,.101,.100,.099,.098,.0971,.0969):
        previous,_=scene([(((px,-1,-2),(px,1,-2),(px,0,1)),(1,0,0),0) for px in (x,.102)],previous)
        result=sample((.09,0,-.4))
        history.append({'surface_x':x,'projected_x':result['projected'][0]})
    print('CACHE_RELEASE',json.dumps(history))
    assert max(abs(b['projected_x']-a['projected_x']) for a,b in zip(history,history[1:]))<.00101
    def unit(p):
        length=math.sqrt(sum(x*x for x in p));return tuple(x/length for x in p)
    faces=[((x,0,0),(0,y,0),(0,0,z)) for x in (-1,1) for y in (-1,1) for z in (-1,1)]
    for _ in range(2):
        split=[]
        for a,b,c in faces:
            ab=unit(tuple(x+y for x,y in zip(a,b)));bc=unit(tuple(x+y for x,y in zip(b,c)))
            ca=unit(tuple(x+y for x,y in zip(c,a)))
            split.extend(((a,ab,ca),(ab,b,bc),(ca,bc,c),(ab,bc,ca)))
        faces=split
    # A faceted curved body exercises transitions across many separate triangles.
    curved=[]; face_planes=[]
    for face in faces:
        triangle=tuple((v[0]*.2,v[1]*.2,v[2]*.2-.5) for v in face)
        # scene() accepts a constant normal; flat face normals exercise actual faceted contact.
        a,b,c=triangle;ab=tuple(y-x for x,y in zip(a,b));ac=tuple(y-x for x,y in zip(a,c))
        n=unit((ab[1]*ac[2]-ab[2]*ac[1],ab[2]*ac[0]-ab[0]*ac[2],ab[0]*ac[1]-ab[1]*ac[0]))
        if sum(n[k]*(a[k]+(.5 if k==2 else 0)) for k in range(3))<0:n=tuple(-x for x in n)
        curved.append((triangle,n,0));face_planes.append((a,n))
    curved_mesh,curved_offset=scene(curved)
    curved_nodes=(curved_offset-len(curved)*6)//2
    finite_mesh,finite_offset=scene([(((.08,.05,-.43),(.08,.09,-.43),(.08,.07,-.37)),(1,0,0),0)])
    # Restore the corner for the full-rope check.
    texture(30,corner_mesh)
    # Run complete ropes against that stationary corner, including all production
    # length, midpoint, ray and velocity constraints, at the user's current tuning.
    solver=gpu.compute(source,common)
    for name in ('hair_mesh_from_local','guide_from_previous'):gpu.matrix(solver,name,identity)
    for name,value in {'hair_mesh':30,'hair_previous_guides':29,'hair_mesh_nodes':1,
                       'hair_mesh_contact':corner_offset,'guide_history':1}.items():
        gpu.uniform(solver,name,value,integer=True)
    for name,value in {'guide_stiffness':8,'guide_retention':0,'guide_bend':0,'guide_elasticity':0,
                       'guide_damping':3,'guide_friction':0,'guide_travel':2.25,
                       'hair_root_radius':.08,'hair_root_gradient':.27}.items():gpu.uniform(solver,name,value)
    gpu.uniform(solver,'guide_gravity',0,0,-9.81*.6)
    # Moving a pinned root across a midpoint plane must not enable a centimetre-scale correction.
    pinned_mesh,pinned_offset=scene([(((.125,-.04,-.05),(.125,.04,-.05),(.125,0,-.025)),(1,0,0),0)])
    gpu.uniform(solver,'hair_mesh_contact',pinned_offset,integer=True)
    gpu.uniform(solver,'hair_root_gradient',.01);gpu.uniform(solver,'guide_gravity',0,0,0)
    pinned_results=[]
    for shift in (-.000001,.000001):
        pinned_rest=[(.13+shift,0,0,1)]+[(.106,0,-i*.08,1) for i in range(1,9)]
        initial=pinned_rest+pinned_rest+[(0,0,0,0)]*9
        old=buffer(initial);out=buffer(initial)
        texture(30,pinned_mesh);texture(29,old);gl.BindBufferBase(SSBO,5,out[0])
        gpu.uniform(solver,'guide_dt',1/60);dispatch(solver)
        values=read(out,27);pinned_results.append(values[9:18])
        assert math.dist(values[9][:3],pinned_rest[0][:3])<1.e-6
        assert values[10][0]>.1299, 'free endpoint lost midpoint clearance beside a pinned root'
        assert max(math.dist(v[:3],(0,0,0)) for v in values[18:27])<1.e-5, 'root recovery created velocity'
    pinned_delta=max(math.dist(a[:3],b[:3]) for a,b in zip(*pinned_results))
    print('PINNED_ROOT: 2 micrometre input / full-rope output difference (m):',pinned_delta)
    assert pinned_delta<.00001, 'pinned-root midpoint contact switched on abruptly'
    gpu.uniform(solver,'hair_root_gradient',.27);gpu.uniform(solver,'guide_gravity',0,0,-9.81*.6)
    gpu.uniform(solver,'hair_mesh_contact',corner_offset,integer=True)
    texture(30,corner_mesh)
    rest=[(.002,.002,-i*.08,1) for i in range(9)]
    data=rest+rest+[(0,0,0,0)]*9
    corner_geometry=read(corner_mesh,corner_offset)
    def move_geometry(pair,shift,base=corner_geometry,nodes=1,curved=False):
        geometry=list(base)
        for i,row in enumerate(geometry):
            if i<nodes*2 or i%2==0:
                if curved:
                    scale=1+shift/.2
                    geometry[i]=(row[0]*scale,row[1]*scale,(row[2]+.5)*scale-.5,row[3])
                else:geometry[i]=(row[0]+shift,row[1]-shift,*row[2:])
        raw=struct.pack(f'{len(geometry)*4}f',*(x for row in geometry for x in row))
        gl.BindBuffer(SSBO,pair[0]);gl.BufferSubData(SSBO,0,len(raw),C.create_string_buffer(raw))
    animated=[buffer(read(corner_mesh,corner_offset+21*21*32+1)) for _ in range(2)]
    curved_geometry=read(curved_mesh,curved_offset)
    curved_animated=[buffer(read(curved_mesh,curved_offset+21*21*32+1)) for _ in range(2)]
    gpu.uniform(solver,'hair_previous_mesh',31,integer=True)
    for label,times in [('120Hz',[1/120]),('60Hz',[1/60]),('variable',[.0165,.0168]),
                        ('breathing',[1/60]),('root_pull',[.0165,.0168]),('curved_breathing',[.0165,.0168]),
                        ('beside_finite_patch',[1/60])]:
        active_rest=([(.18,0,-i*.08,1) for i in range(9)] if label=='curved_breathing' else
                     [(.02,0,-i*.08,1) for i in range(9)] if label=='beside_finite_patch' else rest)
        initial=active_rest+active_rest+[(0,0,0,0)]*9
        ropes=[buffer(initial),buffer(initial)];texture(30,corner_mesh)
        gpu.uniform(solver,'hair_mesh_nodes',curved_nodes if label=='curved_breathing' else 1,integer=True)
        gpu.uniform(solver,'hair_mesh_contact',curved_offset if label=='curved_breathing' else corner_offset,integer=True)
        if label=='beside_finite_patch':
            texture(30,finite_mesh);gpu.uniform(solver,'hair_mesh_contact',finite_offset,integer=True)
        gpu.matrix(solver,'hair_mesh_from_local',identity);gpu.matrix(solver,'guide_from_previous',identity)
        gpu.uniform(solver,'guide_mesh_history',int('breathing' in label),integer=True)
        points=[]; elapsed=0.0; previous_shift=0.0
        for frame in range(720):
            dt=times[frame%len(times)];elapsed+=dt
            shift=(.005 if label=='curved_breathing' else .0005)*math.sin(math.tau*elapsed/3)
            if label=='breathing':
                move_geometry(animated[0],shift);move_geometry(animated[1],previous_shift)
                texture(30,animated[0]);texture(31,animated[1])
            if label=='curved_breathing':
                move_geometry(curved_animated[0],shift,curved_geometry,curved_nodes,True)
                move_geometry(curved_animated[1],previous_shift,curved_geometry,curved_nodes,True)
                texture(30,curved_animated[0]);texture(31,curved_animated[1])
            if label=='root_pull':
                transform=[row[:] for row in identity];transform[0][3]=shift;transform[1][3]=-shift
                gpu.matrix(solver,'hair_mesh_from_local',transform)
                transform[0][3]=previous_shift-shift;transform[1][3]=shift-previous_shift
                gpu.matrix(solver,'guide_from_previous',transform)
            texture(29,ropes[1-frame%2]);gl.BindBufferBase(SSBO,5,ropes[frame%2][0])
            gpu.uniform(solver,'guide_dt',dt)
            dispatch(solver)
            values=read(ropes[frame%2],27)
            assert all(math.isfinite(v) for row in values for v in row)
            assert math.dist(values[9][:3],active_rest[0][:3])<1.e-6
            if label=='beside_finite_patch':
                assert max(abs(row[0]-.02) for row in values[9:18])<1.e-6, 'finite patch pulls a complete rope sideways'
            if frame>=600:
                points.append([row[:3] for row in values[9:18]])
                for point in points[-1][2:]:
                    if label=='curved_breathing':
                        scale=1+shift/.2
                        clearance=max(sum((point[k]-((a[k]+(.5 if k==2 else 0))*scale-(.5 if k==2 else 0)))*n[k]
                                          for k in range(3)) for a,n in face_planes)
                        assert clearance>.003, ('curved rope penetrates body',point,clearance)
                    elif label!='beside_finite_patch':
                        sx=shift if label=='breathing' else -shift if label=='root_pull' else 0
                        assert min(point[0]-sx,point[1]+sx)>.004, ('full rope lost body clearance',label,point)
            previous_shift=shift
        peak=max((math.dist(points[f][i],points[f-1][i]),f,i) for f in range(1,len(points)) for i in range(1,9))
        distance,frame,node=peak
        print('FULL_ROPE',json.dumps({'case':label,'max_step_m':distance,'node':node,
              'before':points[frame-1][node],'after':points[frame][node]}))
        assert distance<(.001 if label=='curved_breathing' else .0005), ('full rope oscillates',label,distance)
    assert gl.GetError()==0
    print('PASS: finite contact support, corner continuity, dense shell coverage and complete moving ropes')


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try:run(sdl,gl)
    finally:sdl.SDL_GL_DestroyContext(ctx);sdl.SDL_DestroyWindow(window);sdl.SDL_Quit()
