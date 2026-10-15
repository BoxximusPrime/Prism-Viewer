"""Variable rope topology: solver storage, rendering, debug vertices and settings."""
import ctypes as C
import math
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
from test_taa_gpu import GPU, SHADERS
from test_exact_oit_gpu import context, U, SSBO

ROOT=Path(__file__).resolve().parents[2]

def run(sdl,gl):
    gpu=GPU(sdl,gl)
    gl.TexBuffer=C.WINFUNCTYPE(None,U,U,U)(sdl.SDL_GL_GetProcAddress(b'glTexBuffer'))
    identity=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
    def buffer(values):
        b,t=gpu.obj(gl.GenBuffers),gpu.obj(gl.GenTextures)
        raw=struct.pack(f'{len(values)*4}f',*(v for row in values for v in row))
        gl.BindBuffer(SSBO,b);gl.BufferData(SSBO,len(raw),C.create_string_buffer(raw),0x88E8)
        gl.BindTexture(0x8C2A,t);gl.TexBuffer(0x8C2A,0x8814,b)
        return b,t
    def texture(unit,pair):
        gl.ActiveTexture(0x84C0+unit);gl.BindTexture(0x8C2A,pair[1])
    def read(pair,count):
        gl.BindBuffer(SSBO,pair[0]);raw=C.create_string_buffer(count*16)
        gl.GetBufferSubData(SSBO,0,len(raw),raw)
        return list(struct.iter_unpack('4f',raw.raw))
    def dispatch(program,out,groups=1):
        gl.UseProgram(program);gl.BindBufferBase(SSBO,5,out[0]);gl.DispatchCompute(groups,1,1)
        gl.MemoryBarrier(0x2000|0x200|0x8)
    common=(SHADERS/'class1/deferred/hairCollision.glsl').read_text()
    solver=gpu.compute((SHADERS/'class1/deferred/hairGuideC.glsl').read_text(),common)
    for name in ('hair_mesh_from_local','guide_from_previous'):gpu.matrix(solver,name,identity)
    for name,value in {'hair_previous_guides':29,'hair_mesh':30,'hair_mesh_nodes':1,'hair_mesh_contact':8,
                       'guide_history':1,'guide_diagnostics':1}.items():gpu.uniform(solver,name,value,integer=True)
    for name,value in {'guide_stiffness':1,'guide_retention':0,'guide_bend':0,'guide_elasticity':0,
                       'guide_damping':16.5,'guide_friction':0,'guide_travel':0,
                       'hair_root_radius':.08,'hair_root_gradient':.27}.items():gpu.uniform(solver,name,value)
    gpu.uniform(solver,'guide_gravity',0,0,-5.886)
    # All ropes touch a real plane; the unused suffix detects writes past either buffer.
    shell=[(0,-2,-2,1.5),(0,2,1,1)]
    for p in ((0,-2,-2),(0,2,-2),(0,0,1)):shell.extend(((*p,0),(1,0,0,0)))
    shell.extend([(-.6,-.6,-1.56,.06)]+[(3,0,0,0)]*(21*21*32))
    mesh=buffer(shell);texture(30,mesh)
    sentinel=(31,41,59,26)
    for nodes in (9,17,32,9):
        chains=64;stride=nodes*3;data=[]
        for chain in range(chains):
            rest=[(.002,(chain-32)*.003,-i*.64/(nodes-1),1) for i in range(nodes)]
            data.extend(rest+rest+[(0,0,0,0)]*nodes)
        data[0]=(*data[0][:3],chains);data[1]=(*data[1][:3],nodes)
        ropes=[buffer(data+[sentinel]*4),buffer(data+[sentinel]*4)]
        diagnostics=buffer([(0,0,0,0)]*(chains*nodes*7)+[sentinel]*4)
        gl.BindBufferBase(SSBO,6,diagnostics[0])
        texture(30,mesh)
        for frame in range(90):
            texture(29,ropes[1-frame%2]);gpu.uniform(solver,'guide_dt',.25 if frame==0 else (.0165 if frame%2 else .0168))
            # Match the viewer's batches, including the offset on the second dispatch.
            for first in (0,32):
                gpu.uniform(solver,'guide_first',first,integer=True);dispatch(solver,ropes[frame%2],2)
        result=read(ropes[frame%2],len(data)+4)
        assert result[-4:]==[sentinel]*4
        assert read(diagnostics,chains*nodes*7+4)[-4:]==[sentinel]*4
        assert all(math.isfinite(v) for row in result for v in row)
        for chain in range(chains):
            base=chain*stride
            assert math.dist(result[base+nodes][:3],data[base][:3])<1.e-6
            for node in range(1,nodes):
                if math.dist(data[base+node][:3],(0,0,0))>.08001:
                    assert result[base+nodes+node][0]>.0049, (nodes,chain,node,result[base+nodes+node])
            assert max(math.dist(row[:3],(0,0,0)) for row in result[base+nodes*2:base+stride])<=3.001
        print(f'PASS: {chains} ropes x {nodes} vertices; pins, plane clearance, finite state, bounded velocity and guarded output/probe buffers')

    # Exercise the actual deformation helper against independent previous/current topologies.
    deform=(SHADERS/'class1/deferred/hairDeformV.glsl').read_text()
    render=gpu.compute(deform+'''
layout(local_size_x=1) in;
layout(std430,binding=5) buffer Result {vec4 result[];};
uniform samplerBuffer previous_guides;
uniform vec3 query;
void main(){result[0]=vec4(hairGuidePosition(query,mat4(1),mat4(1),.08,hair_guides),1);
result[1]=vec4(hairGuidePosition(query,mat4(1),mat4(1),.08,previous_guides),1);}
''')
    gpu.uniform(render,'hair_guides',29,integer=True);gpu.uniform(render,'previous_guides',30,integer=True)
    def render_data(nodes,amount):
        data=[]
        for chain in range(4):
            angle=chain*math.tau/4
            rest=[(.15*math.cos(angle),.15*math.sin(angle),-.64*i/(nodes-1),1) for i in range(nodes)]
            data.extend(rest+[(x+amount*i/(nodes-1),y,z,w) for i,(x,y,z,w) in enumerate(rest)]+[(0,0,0,0)]*nodes)
        data[0]=(*data[0][:3],4);data[1]=(*data[1][:3],nodes)
        return buffer(data),data
    output=buffer([(0,0,0,0)]*2)
    for current_nodes,previous_nodes in ((9,32),(17,9),(32,17)):
        current,values=render_data(current_nodes,.1);previous,_=render_data(previous_nodes,.04)
        texture(29,current);texture(30,previous)
        for fraction in (0,.13,.5,.999,1):
            query=(.15,0,-.64*fraction);gpu.uniform(render,'query',*query);dispatch(render,output)
            result=read(output,2)
            for row,amount in zip(result,(.1,.04)):
                assert math.dist(row[:3],(query[0]+amount*fraction,query[1],query[2]))<1.e-5
        # Run the production debug vertex indexing as a compute probe.
        debug=(SHADERS/'class1/deferred/hairMeshDebugV.glsl').read_text()
        debug=debug.replace('out vec3','vec3').replace('out vec4','vec4').replace('void main()','void debugVertex()')
        debug='uniform int debug_vertex;vec4 debug_position;float debug_size;\n'+debug
        debug=debug.replace('gl_VertexID','debug_vertex').replace('gl_Position','debug_position').replace('gl_PointSize','debug_size')
        debug=gpu.compute(debug+'''layout(local_size_x=1) in;layout(std430,binding=5) buffer Result{vec4 result[];};
void main(){debugVertex();result[0]=debug_position;result[1]=guide_color;}''')
        gpu.uniform(debug,'hair_guides',29,integer=True);gpu.matrix(debug,'modelview_projection_matrix',identity)
        for mode in (2,3):
            gpu.uniform(debug,'guide_debug',mode,integer=True)
            per_chain=current_nodes if mode==3 else (current_nodes-1)*2
            for vertex in (0,per_chain-1,per_chain,4*per_chain-1):
                gpu.uniform(debug,'debug_vertex',vertex,integer=True);dispatch(debug,output)
                chain=vertex//per_chain
                node=vertex%per_chain if mode==3 else (vertex%per_chain)//2+(vertex&1)
                assert math.dist(read(output,2)[0][:3],values[chain*current_nodes*3+current_nodes+node][:3])<1.e-6
    assert gl.GetError()==0
    print('PASS: current/previous deformation use their own topology; rope line/point overlays address first/last vertices across chains')

    setting='BoxxyHairPhysicsRopeVertices'
    tree=ET.parse(ROOT/'indra/newview/app_settings/settings.xml').getroot().find('map')
    pairs=list(tree);settings={pairs[i].text:pairs[i+1] for i in range(0,len(pairs),2)}
    fields=list(settings[setting]);fields={fields[i].text:fields[i+1].text for i in range(0,len(fields),2)}
    assert fields['Type']=='S32' and fields['Value']=='9' and fields['Persist']=='1'
    panel=ET.parse(ROOT/'indra/newview/skins/default/xui/en/panel_preferences_graphics1.xml')
    control=panel.find(f'.//slider[@name="{setting}"]')
    assert control is not None and control.get('min_val')=='9' and control.get('max_val')=='32'
    print('PASS: persistent default 9, UI range 9-32')

if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try:run(sdl,gl)
    finally:sdl.SDL_GL_DestroyContext(ctx);sdl.SDL_DestroyWindow(window);sdl.SDL_Quit()
