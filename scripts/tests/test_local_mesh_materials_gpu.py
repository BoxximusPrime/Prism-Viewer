"""Local mesh PBR regressions using production GLTF shaders on a hidden GPU.

Exercises actual material/transform UBOs, tint, normal maps, alpha, GGX and IBL.
Probe samples and the BRDF LUT are controlled fixtures, not an in-world test.
"""
import ctypes as C
import math
from test_taa_gpu import GPU, ROOT, SHADERS, W, H, context
from test_exact_oit_gpu import U, I, F, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT
from test_alpha_lighting_gpu import function
from test_specular_aa_gpu import VERTEX


def run(sdl, gl):
    gpu = GPU(sdl, gl)
    for name, result, args in (
        ('GetUniformBlockIndex', U, [U, C.c_char_p]),
        ('UniformBlockBinding', None, [U, U, U]),
        ('GetAttribLocation', I, [U, C.c_char_p]),
        ('DisableVertexAttribArray', None, [U]),
    ):
        setattr(gl, name, C.WINFUNCTYPE(result, *args)(sdl.SDL_GL_GetProcAddress(('gl'+name).encode())))
    read = lambda path: (SHADERS/path).read_text()
    defines = '#define MAX_UBO_VEC4S 12\n#define MAX_NODES_PER_GLTF_OBJECT 3\n#define GBUFFER_FLAG_HAS_PBR 1.0\n'
    vertex = defines + read('class1/gltf/pbrmetallicroughnessV.glsl')
    fragment = defines + read('class1/gltf/pbrmetallicroughnessF.glsl')
    global_source = read('class1/deferred/globalF.glsl')
    common = '''
vec3 srgb_to_linear(vec3 c){return c;}
vec3 linear_to_srgb(vec3 c){return c;}
void mirrorClip(vec3 p){}
'''
    common += function(global_source, 'float filterPBRRoughness(')
    common += 'uniform float sss_object; uniform float ssgi_avatar;\n' + function(global_source, 'vec4 encodeNormal(')
    material_data = [0.] * 48
    for i in range(0, 40, 8):
        material_data[i:i+2] = [1, 1]
    material_data[6:8] = material_data[14:16] = [1, 1]
    material_data[43:48] = [1, 1, .5, 0, -1]
    material_buffer = gpu.obj(gl.GenBuffers)
    node_buffer = gpu.obj(gl.GenBuffers)
    gl.BindBuffer(0x8A11, node_buffer)
    gl.BufferData(0x8A11, 48, (F*12)(1,0,0,0, 0,1,0,0, 0,0,1,0), 0x88E4)
    gl.BindBufferBase(0x8A11, 1, node_buffer)

    def upload():
        gl.BindBuffer(0x8A11, material_buffer)
        gl.BufferData(0x8A11, 192, (F*48)(*material_data), 0x88E4)
        gl.BindBufferBase(0x8A11, 0, material_buffer)

    def bind_blocks(prog):
        for name, index in [('GLTFMaterials', 0), ('GLTFNodes', 1)]:
            block = gl.GetUniformBlockIndex(prog, name.encode())
            if block != 0xffffffff:
                gl.UniformBlockBinding(prog, block, index)
        gpu.uniform(prog, 'gltf_material_id', 0, integer=True)

    output = gpu.texture()
    middle = (W*(H//2)+W//2)*4
    pixel = lambda target: gpu.read(target)[middle:middle+4]
    checks = 0

    def check(actual, expected, label, epsilon=.003):
        nonlocal checks
        assert max(abs(a-b) for a,b in zip(actual, expected)) < epsilon, (label, actual, expected)
        checks += 1

    # Actual vertex shader: nonuniform and mirrored node/prim transforms must
    # keep normals perpendicular and preserve tangent handedness.
    inspect = gpu.program('''
in vec3 vary_normal, vary_tangent; flat in float vary_sign; in vec4 vertex_color;
uniform int test_mode; out vec4 frag_color;
void main(){frag_color=test_mode==0 ? vec4(vary_normal,vary_sign) :
    test_mode==1 ? vec4(vary_tangent,dot(vary_normal,vary_tangent)) : vertex_color;}
''', vertex)
    bind_blocks(inspect)
    identity = [[float(r==c) for c in range(4)] for r in range(4)]
    gpu.matrix(inspect, 'projection_matrix', identity)
    positions = (F*9)(-1,-1,0, 3,-1,0, -1,3,0)
    vbo = gpu.obj(gl.GenBuffers)
    gl.BindBuffer(0x8892, vbo)
    gl.BufferData(0x8892, C.sizeof(positions), positions, 0x88E4)
    gl.EnableVertexAttribArray(0)
    gl.VertexAttribPointer(0,3,0x1406,False,0,None)

    def attribute(name, values):
        location = gl.GetAttribLocation(inspect, name.encode())
        if location >= 0:
            gl.DisableVertexAttribArray(location)
            gl.VertexAttrib4f(location, *values)

    s = math.sqrt(.5)
    attribute('normal', (s,0,s,0))
    attribute('tangent', (s,0,-s,1))
    attribute('diffuse_color', (.2,.4,.6,.5))
    material_data[6:8], material_data[14:16] = [.5,.25], [1,.5]
    upload()
    for xscale in (2., -2.):
        modelview = [row[:] for row in identity]
        modelview[0][0], modelview[2][2] = xscale, .5
        gpu.matrix(inspect, 'modelview_matrix', modelview)
        length = math.sqrt(.25+4)
        gpu.uniform(inspect, 'test_mode', 0, integer=True)
        gpu.draw(inspect, output)
        check(pixel(output), [(.5 if xscale>0 else -.5)/length,0,2/length,1 if xscale>0 else -1], 'normal and handedness')
        gpu.uniform(inspect, 'test_mode', 1, integer=True)
        gpu.draw(inspect, output)
        check(pixel(output)[3:], [0], 'tangent perpendicular to normal')
        gpu.uniform(inspect, 'test_mode', 2, integer=True)
        gpu.draw(inspect, output)
        check(pixel(output), [.1,.1,.6,.25], 'unbaked tint applied once')
    gl.DisableVertexAttribArray(0)

    # The opaque shader must write world-PBR inputs, including alpha masking,
    # normal strength and AO. Vertex fixture supplies a known .6 alpha.
    fixture = VERTEX.replace('vertex_color=vec4(1);', 'vertex_color=vec4(1,1,1,.6);')
    opaque = gpu.program(fragment+common, fixture)
    bind_blocks(opaque)
    targets = [gpu.texture() for _ in range(4)]
    white = gpu.texture([1,1,1,1]*(W*H))
    albedo = gpu.texture([.8,.4,.2,.5]*(W*H))
    normals = gpu.texture([.75,.5,1,1]*(W*H))
    orm = gpu.texture([.2,.8,.6,1]*(W*H))

    def bind_maps(prog):
        for unit,(name,tex) in enumerate([('diffuseMap',albedo),('normalMap',normals),
                ('metallicRoughnessMap',orm),('occlusionMap',orm),('emissiveMap',white)]):
            gpu.bind(prog,name,unit,tex)

    def opaque_draw(cutoff, normal_scale, ao):
        material_data[43:48] = [ao,normal_scale,.5,.5,cutoff]
        upload()
        for i,tex in enumerate(targets):
            gpu.upload(tex,[-1]*W*H*4)
            gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT+i,TEXTURE,tex,0)
        gl.DrawBuffers(4,(U*4)(*(COLOR_ATTACHMENT+i for i in range(4))))
        bind_maps(opaque)
        gl.UseProgram(opaque)
        gl.DrawArrays(4,0,3)
        return pixel(targets[0]), pixel(targets[1]), pixel(targets[2])

    a,b,n = opaque_draw(.2,0,.5)
    check(a[:3],[.8,.4,.2],'base color')
    check(b[:3],[.6,.4,.3],'occlusion/roughness/metallic')
    masked,_,_ = opaque_draw(.4,1,1)
    check(masked,[-1]*4,'alpha mask uses texture times factor')
    _,_,tilted = opaque_draw(.2,1,1)
    assert abs(n[0]-tilted[0])>.05, 'normal scale must affect the world normal'
    checks += 1

    # Real production GGX + IBL, with a controlled reflection-probe sample.
    util=read('class1/deferred/deferredUtil.glsl')
    lighting = '''
#define M_PI 3.141592653589793
uniform int classic_mode;
vec2 BRDF(float nv,float gloss){return vec2(1,0);}
uniform float test_probe, test_sun;
void sampleReflectionProbes(inout vec3 a,inout vec3 g,vec2 tc,vec3 p,vec3 n,float gloss,bool transparent,vec3 ambient)
{a=vec3(0);g=vec3(test_probe);}
void calcAtmosphericVarsLinear(vec3 p,vec3 n,vec3 l,out vec3 sun,out vec3 ambient,out vec3 additive,out vec3 atten)
{sun=vec3(test_sun);ambient=vec3(0);additive=vec3(0);atten=vec3(1);}
vec4 applySkyAndWaterFog(vec3 p,vec3 a,vec3 t,vec4 c){return c;}
vec4 applyVolumeFogAlpha(vec3 p,vec4 c){return c;}
vec3 pbrCalcPointLightOrSpotLight(int i,vec3 d,vec3 s,float r,float m,vec3 n,vec3 p,vec3 v,vec3 lp,vec3 ld,vec3 lc,float ls,float f,float pt,float a){return vec3(0);}
'''
    lighting += function(util,'void pbrIbl(')
    lighting += util[util.index('struct PBRInfo'):util.index('bool hasAlphaProjector(')]
    lighting += function(util,'void calcDiffuseSpecular(')+function(util,'vec3 pbrBaseLight(')
    forward = gpu.program('#define ALPHA_BLEND 1\n'+fragment+common+lighting, fixture)
    bind_blocks(forward)
    for i in range(1,4): gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT+i,TEXTURE,0,0)
    gpu.uniform(forward,'sun_up_factor',1,integer=True)
    gpu.uniform(forward,'sun_dir',0,0,1)
    for r in (.2,.8):
        material_data[43:48]=[1,0,r,1,-1]
        upload()
        bind_maps(forward)
        gpu.uniform(forward,'test_probe',0)
        gpu.uniform(forward,'test_sun',0)
        gpu.draw(forward,output)
        dark=pixel(output)
        check(dark,[0,0,0,.3],'alpha factor is applied once')
        gpu.uniform(forward,'test_probe',1)
        gpu.draw(forward,output)
        reflected=pixel(output)
        assert reflected[0]>.05 and reflected[1]>0, 'probe radiance must reach local mesh'
        checks+=1
        gpu.uniform(forward,'test_probe',0)
        gpu.uniform(forward,'test_sun',.01)
        gpu.draw(forward,output)
        lit=pixel(output)
        if r==.2: glossy=lit
        else: assert glossy[0]>lit[0]*2, ('roughness must change GGX highlights',glossy,lit)
    checks+=1
    print(f'PASS: {checks} local mesh GPU checks (tint, normals, alpha, ORM, specular and probe response).')


if __name__ == '__main__':
    sdl,window,ctx,gl=context()
    try: run(sdl,gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
