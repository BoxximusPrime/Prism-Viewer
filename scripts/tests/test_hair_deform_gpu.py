"""Rope deformation preserves pins and shading across every production geometry path."""
import ctypes as C
import math
import struct
from test_taa_gpu import GPU, SHADERS, W, H, context
from test_gtao_gpu import inverse
from test_exact_oit_gpu import TEXTURE, RGBA, FLOAT, U, SSBO

def point(a,p):
    return [sum(a[r][k]*(*p,1)[k] for k in range(4)) for r in range(3)]

def run(sdl,gl):
    gpu=GPU(sdl,gl)
    read=lambda name:(SHADERS/'class1'/name).read_text()
    gl.TexBuffer=C.WINFUNCTYPE(None,U,U,U)(sdl.SDL_GL_GetProcAddress(b'glTexBuffer'))
    identity=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
    model=[[0,-2,0,.8],[.5,0,0,-.4],[0,0,1.5,.2],[0,0,0,1]]
    probe='''uniform vec3 sample_position;
uniform mat4 test_skin;
uniform int rigged;
vec3 getHairDeformedPosition(vec3 position);
mat4 getHairSkinnedTransform(mat4 skin, vec3 position);
out vec3 moved;
void main(){moved=rigged!=0 ? (getHairSkinnedTransform(test_skin,sample_position)*vec4(sample_position,1)).xyz : getHairDeformedPosition(sample_position);
vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));gl_Position=vec4(p[gl_VertexID],0,1);}'''
    prog=gpu.program('in vec3 moved;out vec4 frag_color;void main(){frag_color=vec4(moved,1);}',probe)
    target=gpu.texture();gl.TexImage2D(TEXTURE,0,0x8814,W,H,0,RGBA,FLOAT,None)
    b,t=gpu.obj(gl.GenBuffers),gpu.obj(gl.GenTextures)
    checks=0
    def check(condition,message):
        nonlocal checks
        assert condition,message
        checks+=1
    pixel=(H//2*W+W//2)*4
    def sample(p,rigged=False):
        gpu.uniform(prog,'sample_position',*p);gpu.uniform(prog,'rigged',int(rigged),integer=True)
        gpu.draw(prog,target)
        return gpu.read(target)[pixel:pixel+3]
    for count in (4,16,31,64):
        guides=[]
        for chain in range(count):
            angle=chain*math.tau/count
            rest=[(.15*math.cos(angle),.15*math.sin(angle),-n*.1,1) for n in range(9)]
            moved=[(p[0]+.02*n,p[1]-.01*n,p[2],1) for n,p in enumerate(rest)]
            guides.extend(rest+moved+[(0,0,0,0)]*9)
        guides[0]=(*guides[0][:3],count)
        raw=struct.pack(f'{len(guides)*4}f',*(v for p in guides for v in p))
        gl.BindBuffer(SSBO,b);gl.BufferData(SSBO,len(raw),C.create_string_buffer(raw),0x88E8)
        gl.ActiveTexture(0x84C0+29);gl.BindTexture(0x8C2A,t);gl.TexBuffer(0x8C2A,0x8814,b)
        gpu.uniform(prog,'hair_guides',29,integer=True);gpu.uniform(prog,'hair_guide_active',1,integer=True)
        for draw_model in (identity,model):
            gpu.matrix(prog,'hair_local_from_model',draw_model);gpu.matrix(prog,'hair_model_from_local',inverse(draw_model))
            gpu.matrix(prog,'test_skin',model)
            for radius in (.03,.15,.35):
                gpu.uniform(prog,'hair_root_radius',radius)
                for local in ((0,0,.02),(.1,0,0),(.14,-.00001,-.4),(.14,.00001,-.4),(.05,.12,-.73)):
                    original=point(inverse(draw_model),local)
                    n=min(max(-local[2]*10,0),8)
                    moved=local if math.dist(local,(0,0,0))<=radius else (local[0]+.02*n,local[1]-.01*n,local[2])
                    expected=point(inverse(draw_model),moved)
                    check(math.dist(sample(original),expected)<2.e-6,('rope interpolation',count,local,sample(original),expected))
                    check(math.dist(sample(point(inverse(model),original),True),expected)<2.e-6,'rigged and unrigged positions differ')
        gpu.uniform(prog,'hair_root_radius',0)
        check(math.dist(sample((.2,.3,-.8)),(.2,.3,-.8))<1.e-6,'disabled root radius must pass through')
        gpu.uniform(prog,'hair_root_radius',.15);gpu.uniform(prog,'hair_guide_active',0,integer=True)
        check(math.dist(sample((.2,.3,-.8)),(.2,.3,-.8))<1.e-6,'missing guide frame must pass through')

    # Link every affected geometry path with the real skin and deformation helpers.
    files = ['deferred/'+n+'V.glsl' for n in ('diffuse','diffuseNoColor','bump','alpha','material',
        'pbropaque','pbralpha','fullbright','fullbrightShiny','emissive','pbrglow','shadow',
        'shadowAlphaMask','pbrShadowAlphaMask','shadowSkinned','treeShadowSkinned')]+['objects/bumpV.glsl']
    for file in files:
        for skin in (False, True):
            if file.endswith(('shadowSkinnedV.glsl','treeShadowSkinnedV.glsl')) and not skin:
                continue
            defines = '#define USE_VERTEX_COLOR 1\n#define USE_INDEXED_TEX 1\n#define MAX_JOINTS_PER_MESH_OBJECT 2\n'
            if skin: defines += '#define HAS_SKIN 1\n'
            extras = read('deferred/textureUtilV.glsl')+'\nvoid passTextureIndex() {}\nvoid calcAtmospherics(vec3 p) {}\n'
            if skin: extras += defines+read('avatar/objectSkinV.glsl')
            gpu.program('out vec4 frag_color; void main(){frag_color=vec4(1);}', defines+read(file), extras)
            checks += 1
    check(gl.GetError()==0, 'no GL errors')
    print(f'PASS: {checks} pinned-root GPU checks, including all colour/glow/shadow paths')


if __name__ == '__main__':
    sdl, window, ctx, gl = context()
    try:
        run(sdl, gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
