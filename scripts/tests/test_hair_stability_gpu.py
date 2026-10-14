"""Animated contact continuity, final rendered clearance and separating guide motion."""
import ctypes as C
import json
import math
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/tests'))
from test_taa_gpu import GPU, SHADERS, W, H
from test_exact_oit_gpu import context, U, SSBO


def run(sdl, gl):
    gpu = GPU(sdl, gl)
    gl.TexBuffer = C.WINFUNCTYPE(None, U, U, U)(sdl.SDL_GL_GetProcAddress(b'glTexBuffer'))
    common = (SHADERS / 'class1/deferred/hairCollision.glsl').read_text()
    deformation = (SHADERS / 'class1/deferred/hairDeformV.glsl').read_text()
    contact_source = (SHADERS / 'class1/deferred/hairContactC.glsl').read_text()
    guide_source = (SHADERS / 'class1/deferred/hairGuideC.glsl').read_text()
    cache = gpu.compute(contact_source, common)
    identity = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    count, offset = 21*21*32, 14

    def buffer(values):
        b, t = gpu.obj(gl.GenBuffers), gpu.obj(gl.GenTextures)
        upload(b, values)
        gl.BindTexture(0x8C2A, t)
        gl.TexBuffer(0x8C2A, 0x8814, b)
        return b, t

    def upload(b, values):
        raw = struct.pack(f'{len(values)*4}f', *(x for p in values for x in p))
        gl.BindBuffer(SSBO, b)
        gl.BufferData(SSBO, len(raw), C.create_string_buffer(raw), 0x88E8)

    def read(b, first, n):
        gl.BindBuffer(SSBO, b)
        out = C.create_string_buffer(n*16)
        gl.GetBufferSubData(SSBO, first*16, len(out), out)
        return list(struct.iter_unpack('4f', out.raw))

    def texture(unit, pair):
        gl.ActiveTexture(0x84C0+unit)
        gl.BindTexture(0x8C2A, pair[1])

    def dispatch(program, groups=1):
        gl.UseProgram(program)
        gl.DispatchCompute(groups, 1, 1)
        gl.MemoryBarrier(0x2000 | 0x8 | 0x200)

    shells = [buffer([(0, 0, 0, 0)]*(offset+count+1)) for _ in range(2)]
    gpu.matrix(cache, 'contact_to_mesh', identity)
    for name, value in {'mesh_node_count': 1, 'contact_offset': offset, 'hair_mesh': 30, 'hair_previous_mesh': 31}.items():
        gpu.uniform(cache, name, value, integer=True)

    # Upload only geometry; retain each shell's previously computed contact grid.
    gl.BufferSubData = C.WINFUNCTYPE(None, U, C.c_ssize_t, C.c_ssize_t, C.c_void_p)(sdl.SDL_GL_GetProcAddress(b'glBufferSubData'))
    def field_step(frame, geometry, history):
        slot = frame % 2
        raw = struct.pack(f'{len(geometry)*4}f', *(x for p in geometry for x in p))
        gl.BindBuffer(SSBO, shells[slot][0])
        gl.BufferSubData(SSBO, 0, len(raw), C.create_string_buffer(raw))
        texture(30, shells[slot]); texture(31, shells[1-slot])
        gl.BindBufferBase(SSBO, 4, shells[slot][0])
        for prog in (cache,):
            gpu.uniform(prog, 'contact_history', int(history), integer=True)
            dispatch(prog, (count+127)//128)
        return slot

    render = gpu.compute('''layout(local_size_x=1) in;
layout(std430,binding=5) buffer Output { vec4 result[]; };
uniform vec3 sample_position;
vec3 getHairDeformedPosition(vec3 position);
void main(){result[0]=vec4(getHairDeformedPosition(sample_position),1);}
''', deformation)
    output = buffer([(0, 0, 0, 0)])[0]
    for name in ('hair_local_from_model', 'hair_model_from_local', 'hair_mesh_from_local'):
        gpu.matrix(render, name, identity)
    for name, value in {'hair_mesh': 30, 'hair_mesh_nodes': 1, 'hair_mesh_contact': offset, 'hair_guides': 29}.items():
        gpu.uniform(render, name, value, integer=True)
    gpu.uniform(render, 'hair_root_radius', .12)
    gpu.uniform(render, 'hair_root_gradient', .1)
    def rendered(p):
        gl.BindBufferBase(SSBO, 5, output)
        gpu.uniform(render, 'sample_position', *p)
        dispatch(render)
        return read(output, 0, 1)[0][:3]

    plane = [(.145, -1, -1, 1.5), (.145, 1, 1, 2)]
    for tri in (((.145, -1, -1), (.145, 1, -1), (.145, 1, 1)), ((.145, -1, -1), (.145, 1, 1), (.145, -1, 1))):
        for p in tri: plane.extend([(*p, 0), (1, 0, 0, 0)])

    # Actual guide solver, with a plane crossing the near-root travel limit.
    guide = gpu.compute(guide_source, common)
    for name in ('guide_from_previous', 'hair_mesh_from_local'): gpu.matrix(guide, name, identity)
    for name, value in {'hair_previous_guides': 29, 'hair_mesh': 30, 'hair_previous_mesh': 31, 'hair_mesh_nodes': 1, 'hair_mesh_contact': offset}.items():
        gpu.uniform(guide, name, value, integer=True)
    for name, value in {'guide_dt': 1/60, 'guide_travel': .3, 'hair_root_radius': .12, 'hair_root_gradient': .1, 'guide_stiffness': 6, 'guide_retention': 1, 'hair_collision_smoothing': .05}.items():
        gpu.uniform(guide, name, value)
    initial = []
    for chain in range(16):
        angle = math.tau*chain/16
        rest = [(.15*math.cos(angle), .15*math.sin(angle), -i*.1, 1) for i in range(9)]
        initial.extend(rest+rest+[(0, 0, 0, 0)]*9)
    initial[0]=(*initial[0][:3],16)
    guides = [buffer(initial) for _ in range(2)]
    plane = [(p[0]+.07, *p[1:]) if i < 2 or i % 2 == 0 else p for i, p in enumerate(plane)]
    field_step(0, plane, False)
    for i in range(120):
        texture(29, guides[1-i%2]); texture(30, shells[0])
        gpu.uniform(guide, 'guide_history', int(i > 0), integer=True)
        gl.BindBufferBase(SSBO, 5, guides[i%2][0])
        dispatch(guide)
    node = read(guides[119%2][0], 10, 1)[0]
    print(json.dumps({'probe': 'guide travel limit overrides collision, retention=1 stiffness=6', 'surface_x': .215, 'node': node, 'penetration_m': .215-node[0]}))
    assert node[0] >= .22-1.e-5, 'guide travel limit undoes contact'
    # A shallower plane is feasible, but the renderer attenuates the solved displacement.
    plane = [(p[0]-.03, *p[1:]) if i < 2 or i % 2 == 0 else p for i, p in enumerate(plane)]
    field_step(0, plane, False)
    for pair in guides: upload(pair[0], initial)
    for i in range(120):
        texture(29, guides[1-i%2]); texture(30, shells[0])
        gpu.uniform(guide, 'guide_history', int(i > 0), integer=True)
        gl.BindBufferBase(SSBO, 5, guides[i%2][0])
        dispatch(guide)
    node = read(guides[119%2][0], 10, 1)[0]
    texture(29, guides[119%2])
    gpu.uniform(render, 'hair_guide_active', 1, integer=True)
    actual = rendered((.15, 0, -.1))
    print(json.dumps({'probe': 'guide root fade after collision', 'surface_x': .185, 'solved_x': node[0], 'rendered_x': actual[0], 'penetration_m': .185-actual[0]}))
    assert node[0] >= .185 and actual[0] >= .185, 'root fade undoes guide contact'
    # An already-separating point in the soft band should keep its outward velocity.
    plane = [(p[0]-.04, *p[1:]) if i < 2 or i % 2 == 0 else p for i, p in enumerate(plane)]
    field_step(0, plane, False)
    initial[13] = (.151, 0, -.4, 1)
    initial[22] = (.5, 0, 0, 0)
    gpu.uniform(guide, 'guide_dt', 1/120)
    gpu.uniform(guide, 'guide_history', 1, integer=True)
    gpu.uniform(guide, 'guide_retention', 0)
    speeds = []
    for active in (0, 1):
        for pair in guides: upload(pair[0], initial)
        texture(29, guides[0]); texture(30, shells[0])
        gl.BindBufferBase(SSBO, 5, guides[1][0])
        gpu.uniform(guide, 'hair_mesh_nodes', active, integer=True)
        dispatch(guide)
        speeds.append(read(guides[1][0], 22, 1)[0][0])
    print(json.dumps({'probe': 'outward guide velocity, already outside stationary plane', 'without_contact_m_s': speeds[0], 'with_contact_m_s': speeds[1]}))
    assert speeds[0] > .2 and speeds[1] > .2, 'soft contact swallows separating velocity'

    # With shape retention disabled, stiffness still resists local kinks through bending constraints.
    gpu.uniform(guide, 'guide_elasticity', 0)  # Isolate bending while preserving rigid segment lengths.
    for chain in range(16):
        for i in range(9):
            initial[chain*27+9+i]=(.15+.06*(i%2), 0, -.08*i, 1)
            initial[chain*27+18+i]=(0, 0, 0, 0)
    gpu.uniform(guide, 'hair_mesh_nodes', 0, integer=True)
    gpu.uniform(guide, 'guide_dt', 1/60)
    bends=[]
    for stiffness in (1, 12):
        for pair in guides: upload(pair[0], initial)
        gpu.uniform(guide, 'guide_stiffness', stiffness)
        texture(29, guides[1])
        gl.BindBufferBase(SSBO, 5, guides[0][0])
        dispatch(guide)
        points=read(guides[0][0], 9, 9)
        lengths=[math.dist(a[:3],b[:3]) for a,b in zip(points,points[1:])]
        assert max(abs(x-.1) for x in lengths)<.004, ('bend stretched rope',lengths)
        edges=[tuple((b[k]-a[k])/length for k in range(3)) for a,b,length in zip(points,points[1:],lengths)]
        bends.append(sum(math.dist(a,b)**2 for a,b in zip(edges,edges[1:])))
    print(json.dumps({'probe': 'bending with shape retention zero', 'soft_curvature': bends[0], 'firm_curvature': bends[1]}))
    assert bends[1]<bends[0]*.98, 'stiffness does not resist guide kinks'

    # A nonzero rope displacement must preserve the authored shading basis.
    values=list(initial)
    for chain in range(16):
        for node in range(1,9):
            p=values[chain*27+node]
            values[chain*27+9+node]=(p[0]+.1*node/8,p[1],p[2],1)
    upload(guides[0][0],values)
    texture(29,guides[0])
    assert math.dist(rendered((.12,0,-.42)),(.12,0,-.42))>.01, 'normal fixture must actually move'

    # Exercise each real skinned lighting entry point, not just the deformation helper.
    target=gpu.texture();pixel=(H//2*W+W//2)*4
    for name,varying in (('diffuse','vary_normal'),('bump','vary_mat2'),('alpha','vary_norm'),
                         ('material','vary_normal'),('pbropaque','vary_normal'),('pbralpha','vary_normal'),
                         ('fullbrightShiny','vary_texcoord1')):
        production=(SHADERS/f'class1/deferred/{name}V.glsl').read_text()
        vertex='#define HAS_SKIN 1\n#define USE_VERTEX_COLOR 1\n#define main productionMain\n'+production+'''
#undef main
void main(){productionMain();vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));gl_Position=vec4(p[gl_VertexID],0,1);}
'''
        extras=(SHADERS/'class1/deferred/textureUtilV.glsl').read_text()+'''
uniform mat4 test_skin;
mat4 getObjectSkinnedTransform(){return test_skin;}
void calcAtmospherics(vec3 p){}
void passTextureIndex(){}
'''
        # Bump stores the basis in rows; its normal occupies the third component of each row.
        fragment='in vec3 vary_mat0,vary_mat1,vary_mat2;out vec4 frag_color;void main(){frag_color=vec4(vary_mat0.z,vary_mat1.z,vary_mat2.z,1);}' if name=='bump' else f'in vec3 {varying};out vec4 frag_color;void main(){{frag_color=vec4({varying},1);}}'
        shader=gpu.program(fragment,vertex,extras)
        gl.GetAttribLocation=C.WINFUNCTYPE(C.c_int,U,C.c_char_p)(sdl.SDL_GL_GetProcAddress(b'glGetAttribLocation'))
        for attribute,value in {'position':(.12,0,-.42,1),'normal':(1,0,0,0),'tangent':(0,0,1,1)}.items():
            location=gl.GetAttribLocation(shader,attribute.encode())
            if location>=0: gl.VertexAttrib4f(location,*value)
        for matrix in ('modelview_matrix','projection_matrix','hair_local_from_model','hair_model_from_local'):gpu.matrix(shader,matrix,identity)
        for uniform,value in {'hair_guides':29,'hair_guide_active':1}.items():gpu.uniform(shader,uniform,value,integer=True)
        gpu.uniform(shader,'hair_root_radius',.12);gpu.uniform(shader,'hair_root_gradient',.1)
        for angle in (0,.4):
            c,s=math.cos(angle),math.sin(angle)
            gpu.matrix(shader,'test_skin',[[c,-s,0,0],[s,c,0,0],[0,0,1,0],[0,0,0,1]])
            texture(29,guides[0]);gpu.draw(shader,target)
            actual=gpu.read(target)[pixel:pixel+3]
            expected=(c,s,0)
            assert math.dist(actual,expected)<.002, ('authored normal after skinning',name,actual,expected)
    print('PASS: all seven skinned lighting paths preserve authored normals after skinning')
    assert gl.GetError() == 0


if __name__ == '__main__':
    sdl, window, ctx, gl = context()
    try: run(sdl, gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
