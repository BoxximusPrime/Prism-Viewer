"""Bounded production segment rays: crossings, fallback, real executed budgets and large meshes."""
from array import array
import ctypes as C
import math
import statistics
import struct
import time
from test_taa_gpu import GPU, SHADERS
from test_exact_oit_gpu import context, U, SSBO


def run(sdl, gl):
    gpu=GPU(sdl,gl)
    print('GPU:',gl.GetString(0x1F01).decode(),gl.GetString(0x1F02).decode())
    gl.TexBuffer=C.WINFUNCTYPE(None,U,U,U)(sdl.SDL_GL_GetProcAddress(b'glTexBuffer'))
    source=(SHADERS/'class1/deferred/hairGuideC.glsl').read_text()
    common=(SHADERS/'class1/deferred/hairCollision.glsl').read_text()
    identity=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]

    def buffer(data):
        values=data if isinstance(data,array) else array('f',(x for p in data for x in p))
        b,t=gpu.obj(gl.GenBuffers),gpu.obj(gl.GenTextures)
        gl.BindBuffer(SSBO,b);gl.BufferData(SSBO,len(values)*4,values.buffer_info()[0],0x88E8)
        gl.BindTexture(0x8C2A,t);gl.TexBuffer(0x8C2A,0x8814,b)
        return b,t

    def texture(unit,pair):
        gl.ActiveTexture(0x84C0+unit);gl.BindTexture(0x8C2A,pair[1])

    def read(pair,n):
        gl.BindBuffer(SSBO,pair[0]);raw=C.create_string_buffer(n*16)
        gl.GetBufferSubData(SSBO,0,len(raw),raw)
        values=list(struct.iter_unpack('4f',raw.raw))
        assert all(math.isfinite(x) for p in values for x in p)
        return values

    def dispatch(program,out,groups=1):
        gl.UseProgram(program);gl.BindBufferBase(SSBO,5,out[0])
        gl.DispatchCompute(groups,1,1);gl.MemoryBarrier(0x2000|0x8|0x200)

    # Loose bounds are intentional: every overlapping node remains a candidate in the worst case.
    def mesh(tris,repeats=1,leaf_size=4):
        points=[p for tri,n in tris for p in tri]
        low=tuple(min(p[k] for p in points) for k in range(3))
        high=tuple(max(p[k] for p in points) for k in range(3))
        data=array('f')
        def tree(first,count):
            start=len(data);data.extend([0]*8)
            leaf=0
            if count<=leaf_size:leaf=first*8+count
            else:
                middle=count//2;tree(first,middle);tree(first+middle,count-middle)
            data[start:start+8]=array('f',(*low,len(data)//8+.5,*high,leaf))
        tree(0,len(tris)*repeats)
        nodes=len(data)//8
        geometry=array('f')
        for tri,n in tris:
            for p in tri:geometry.extend((*p,0,*n,0))
        data.extend(geometry*repeats)
        offset=len(data)//4
        # Empty grid proves rays add coverage independently of existing point/midpoint candidates.
        data.extend(array('f',[0])*(21*21*32*4))
        data.extend((-.6,-.6,-1.56,.06))
        data.extend(array('f',[0])*(21*21*32*4))
        return buffer(data),nodes,offset

    # Count actual executed production operations; instrumentation is confined to this test.
    instrumented=source.replace('GuideRayContact traceGuideSegment',
        'int query_count=0,node_count=0,triangle_count=0;\nGuideRayContact traceGuideSegment')
    instrumented=instrumented.replace('    GuideRayContact empty=', '    ++query_count;\n    GuideRayContact empty=')
    instrumented=instrumented.replace('        vec4 low=texelFetch', '        ++node_count;\n        vec4 low=texelFetch')
    instrumented=instrumented.replace('            ++tested;', '            ++tested; ++triangle_count;')
    probe=gpu.compute(instrumented.replace('void main()', 'void simulationMain()')+'''
uniform vec3 a,b;
uniform float phase,ma,mb;
uniform int project;
void main(){if(gl_GlobalInvocationID.x!=0u)return;contact_fraction=phase;
GuideRayContact hit=traceGuideSegment(a,b);
guide_out[0]=hit.plane;guide_out[1]=hit.velocity;
guide_out[2]=vec4(query_count,node_count,triangle_count,0);
vec3 pa=a,pb=b,ca=vec3(0),cb=vec3(0),sa=vec3(0),sb=vec3(0);float wa=0,wb=0;
if(project!=0)for(int i=0;i<16;++i)projectGuideRay(hit,pa,pb,ma,mb,ca,cb,sa,sb,wa,wb);
guide_out[3]=vec4(pa,wa);guide_out[4]=vec4(pb,wb);
}
''',common)
    output=buffer([(0,0,0,0)]*5)
    gpu.matrix(probe,'hair_mesh_from_local',identity)
    for name,value in {'hair_mesh':30,'hair_previous_mesh':31}.items():gpu.uniform(probe,name,value,integer=True)
    gpu.uniform(probe,'guide_dt',1/60)

    def query(scene,a,b,previous=None,phase=1,origin=(0,0,0),ma=1,mb=1,project=False):
        pair,nodes,offset=scene
        texture(30,pair);texture(31,previous[0] if previous else pair)
        for name,value in {'hair_mesh_nodes':nodes,'hair_mesh_contact':offset,'guide_mesh_history':int(previous is not None),'project':int(project)}.items():gpu.uniform(probe,name,value,integer=True)
        for name,value in {'a':a,'b':b,'guide_previous_mesh_offset':origin}.items():gpu.uniform(probe,name,*value)
        for name,value in {'phase':phase,'ma':ma,'mb':mb}.items():gpu.uniform(probe,name,value)
        dispatch(probe,output)
        result=read(output,5)
        assert result[2][0]==1 and result[2][1]<=64 and result[2][2]<=32, result[2]
        return result

    def plane(x):return [(((x,-1,-1),(x,1,-1),(x,0,1)),(1,0,0))]
    flat=mesh(plane(0))
    hit=query(flat,(.02,0,0),(-.02,0,0),project=True)
    assert abs(hit[0][3]-.0005)<1.e-6 and abs(hit[1][3]-1)<1.e-6,hit
    assert hit[3][0]>=.01999 and hit[4][0]>=.00049, ('contact failed',hit)
    reverse=query(flat,(-.02,0,0),(.02,0,0))
    assert reverse[0][0]>.999, ('backface/inside exit missed',reverse)
    for a,b in (((.02,.99,.99),(-.02,.99,.99)),((.02,0,0),(.01,0,0)),((.02,-.1,0),(.02,.1,0)),((0,0,0),(0,0,0))):
        assert query(flat,a,b)[0]==(0,0,0,0), ('false segment hit',a,b)
    pin=query(flat,(.02,0,0),(-.02,0,0),ma=0,project=True)
    assert abs(pin[3][0]-.02)<1.e-6 and pin[4][0]>=.00049, ('pin moved or blocked free node',pin)
    embedded=query(flat,(-.02,0,0),(.02,0,0),ma=0,project=True)
    assert math.dist(embedded[3][:3],(-.02,0,0))<1.e-6 and math.dist(embedded[4][:3],(.02,0,0))<1.e-6
    assert abs(query(mesh(plane(-.015)+plane(0)),(.02,0,0),(-.02,0,0))[0][3]-.0005)<1.e-6
    assert query(mesh([(((0,0,0),)*3,(1,0,0))]),(.02,0,0),(-.02,0,0))[0]==(0,0,0,0)
    moved=mesh(plane(.04))
    animated=query(moved,(.06,0,0),(-.02,0,0),previous=flat,phase=.25)
    assert abs(animated[0][3]-.0105)<1.e-6 and abs(animated[1][0]-2.4)<1.e-5, animated
    rebased=query(moved,(.06,0,0),(.02,0,0),previous=flat,phase=.5,origin=(.04,0,0))
    assert abs(rebased[0][3]-.0405)<1.e-6 and abs(rebased[1][0])<1.e-6,rebased
    finite=mesh([(((0,-.02,.23),(0,.02,.23),(0,0,.27)),(1,0,0))])
    interior=query(finite,(.01,0,0),(-.03,0,1),project=True)
    assert abs(interior[1][3]-.27)<1.e-5,('contact extends beyond finite triangle',interior)
    assert interior[3][0]>.01 and -.03<interior[4][0]<-.02,('infinite plane displaces a distant endpoint',interior)
    print('PASS: two-sided finite rays, nearest hit, pinned/shared recovery, animation and origin compensation')

    # Completed hits alone may create constraints; truncated searches must fall back unchanged.
    dense=mesh(plane(0),repeats=128)
    limited=query(dense,(.02,0,0),(-.02,0,0),project=True)
    assert limited[0]==(0,0,0,0) and limited[2][2]==32,limited
    assert math.dist(limited[3][:3],(.02,0,0))<1.e-6 and math.dist(limited[4][:3],(-.02,0,0))<1.e-6
    # Ray is within every box but misses the finite triangle: no early hit hides the budget.
    miss=[(((0,-1,1),(0,1,-1),(0,1,1)),(1,0,0))]
    nodes_limited=query(mesh(miss,repeats=1024,leaf_size=1),(.02,-.9,-.9),(-.02,-.9,-.9))
    assert nodes_limited[2][1]==64 and nodes_limited[0]==(0,0,0,0),nodes_limited
    print('Executed work, triangle/node saturation:',limited[2],nodes_limited[2])

    wrapper='''
layout(std430,binding=6) buffer Counters { vec4 counters[]; };
void main(){simulationMain();if(gl_GlobalInvocationID.x>=uint(clamp(guide_out[0].w,0.0,64.0)))return;
counters[gl_GlobalInvocationID.x]=vec4(query_count,node_count,triangle_count,0);}
'''
    started=time.perf_counter()
    measured_common='''layout(std430,binding=7) buffer CandidateCounters { vec4 candidate_counts[]; };
uniform int guide_first;
'''+common
    measured_common=measured_common.replace('    body=hands=ivec4(-1);',
        '    candidate_counts[guide_first+int(gl_GlobalInvocationID.x)].x+=1.0;\n    body=hands=ivec4(-1);')
    measured_common=measured_common.replace('        vec4 lo=texelFetch(mesh,node*2)',
        '        candidate_counts[guide_first+int(gl_GlobalInvocationID.x)].y+=1.0;\n        vec4 lo=texelFetch(mesh,node*2)')
    measured_common=measured_common.replace('    vec4 a=texelFetch(mesh,offset)',
        '    candidate_counts[guide_first+int(gl_GlobalInvocationID.x)].z+=1.0;\n    vec4 a=texelFetch(mesh,offset)')
    program=gpu.compute(instrumented.replace('void main()', 'void simulationMain()')+wrapper,measured_common)
    print('Instrumented solver compile seconds:',time.perf_counter()-started)
    baseline=gpu.compute(source.replace('bool trace_segments=(step+1)*guide_ray_substeps/steps>step*guide_ray_substeps/steps;',
        'bool trace_segments=false;'),common)
    counters=buffer([(0,0,0,0)]*64);gl.BindBufferBase(SSBO,6,counters[0])
    candidate_counters=buffer([(0,0,0,0)]*64);gl.BindBufferBase(SSBO,7,candidate_counters[0])
    for p in (program,baseline):
        for name in ('hair_mesh_from_local','guide_from_previous'):gpu.matrix(p,name,identity)
        for name,value in {'hair_mesh':30,'hair_previous_guides':29,'guide_history':1}.items():gpu.uniform(p,name,value,integer=True)
        for name,value in {'guide_dt':1/120,'guide_retention':0,'guide_bend':0,'guide_elasticity':1,'hair_root_radius':.03,'hair_root_gradient':.01}.items():gpu.uniform(p,name,value)
    patch=mesh([(((.1,-.02,-.24),(.1,.02,-.24),(.1,0,-.22)),(1,0,0))])
    rest=[(.12 if i<3 else .06,0,-i*.1,1) for i in range(9)]
    data=rest+rest+[(0,0,0,0)]*9;data[0]=(*data[0][:3],1)
    old,out=buffer(data),buffer(data)
    for p in (baseline,program):
        texture(30,patch[0]);texture(29,old)
        gpu.uniform(p,'hair_mesh_nodes',patch[1],integer=True);gpu.uniform(p,'hair_mesh_contact',patch[2],integer=True)
        dispatch(p,out)
        result=read(out,27)
        if p==baseline:assert abs(result[12][0]-.06)<1.e-6, result[12]
        else:
            a,b=result[11],result[12]
            t=(.1-a[0])/(b[0]-a[0]);z=a[2]+(b[2]-a[2])*t
            assert t<0 or t>1 or z<-.24 or z>-.22,('segment still crosses the finite triangle',result[9:18])
            assert result[11][0]>.12 and result[12][0]>.06, 'interior contact failed to move both neighbours'
            assert math.dist(result[9][:3],rest[0][:3])<1.e-6
            assert max(math.dist(v[:3],(0,0,0)) for v in result[18:27])<1.e-5, 'ray recovery created a kick'
    print('PASS: full solver clears a crossing missed by point/midpoint contacts, without moving pins or adding velocity')

    # Half a million overlapping triangles, all 64 ropes, and the maximum 30 physics substeps.
    large=mesh(miss,repeats=524288)
    for nodes in (9,17,32):
        one=[((.05 if i%2 else -.05),-.9,-.9-i*.001,1) for i in range(nodes)]
        data=(one+one+[(0,0,0,0)]*nodes)*64;data[0]=(*data[0][:3],64);data[1]=(*data[1][:3],nodes)
        old,out=buffer(data),buffer(data)
        texture(30,large[0]);texture(29,old)
        gpu.uniform(program,'hair_mesh_nodes',large[1],integer=True);gpu.uniform(program,'hair_mesh_contact',large[2],integer=True)
        for dt in (0,1/120,1/60,1/30,.25):
            gl.BindBuffer(SSBO,candidate_counters[0]);gl.BufferData(SSBO,64*16,C.create_string_buffer(64*16),0x88E8)
            gpu.uniform(program,'guide_dt',dt);dispatch(program,out,4)
            counts=read(counters,64)
            assert all(v[0]<=2*(nodes-1) and v[1]<=2*(nodes-1)*64 and v[2]<=2*(nodes-1)*32 for v in counts),counts
            assert sum(v[0] for v in counts)==64*((nodes-1) if dt<=1/120 else 2*(nodes-1))
            print('Frame dt / total rays / node visits / triangle tests:',dt,*(sum(v[k] for v in counts) for k in range(3)))
            candidates=read(candidate_counters,64)
            assert all(v[0]<=4*(nodes-1) and v[1]<=v[0]*64 and v[2]<=v[0]*48 for v in candidates),candidates
            assert sum(v[0] for v in candidates)==64*(2*(nodes-1) if dt<=1/120 else 4*(nodes-1)),candidates
            print('Frame dt / finite-contact queries / nodes / triangles:',dt,*(sum(v[k] for v in candidates) for k in range(3)))
        result=read(out,len(data))
        assert max(math.dist(result[c*nodes*3+nodes+i][:3],one[i][:3]) for c in range(64) for i in range(nodes))<1.e-5
        # No throughput assertion: timers measure this hardware, while operation counts prove the limit.
        query_id=gpu.obj(gl.GenQueries);times=[]
        for frame in range(15):
            gl.BeginQuery(0x88BF,query_id);dispatch(program,out,4);gl.EndQuery(0x88BF)
            elapsed=C.c_uint64();gl.GetQueryObjectui64v(query_id,0x8866,C.byref(elapsed))
            if frame>=5:times.append(elapsed.value/1.e6)
        print('Worst-case fixture GPU ms, median/max over 10 after 5 warmup:',statistics.median(times),max(times))
        assert gl.GetError()==0
        print('PASS: bounded segment-ray work at vertices per rope:',nodes)
        print('PASS: bounded point/midpoint work at vertices per rope:',nodes)



if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try:run(sdl,gl)
    finally:sdl.SDL_GL_DestroyContext(ctx);sdl.SDL_DestroyWindow(window);sdl.SDL_Quit()
