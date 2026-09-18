"""Production PBR material/BRDF + TAA highlight regressions on a hidden GL context.

Run: .venv/Scripts/python.exe scripts/tests/test_specular_aa_gpu.py
The reference disables only normal-variance filtering; both paths use the same
production opaque shader, GGX BRDF, RGBA16F buffers and TAA/presentation shaders.
"""
import ctypes as C
import json
import math
import statistics
from test_taa_gpu import GPU, ROOT, SHADERS, W, H, inverse, context
from test_exact_oit_gpu import U, I, F, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT
from test_alpha_lighting_gpu import function, STUBS


VERTEX = """
uniform vec2 sample_offset;
uniform float normal_slope;
out vec3 vary_position, vary_normal, vary_tangent, vary_fragcoord;
out vec4 vertex_color;
flat out float vary_sign;
out vec2 base_color_texcoord, normal_texcoord, metallic_roughness_texcoord, emissive_texcoord;
out vec2 base_color_uv, normal_uv, metallic_roughness_uv, occlusion_uv, emissive_uv;
void main() {
    vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
    gl_Position=vec4(p[gl_VertexID],0,1);
    vec2 uv=p[gl_VertexID]*.5+.5;
    base_color_texcoord=normal_texcoord=metallic_roughness_texcoord=emissive_texcoord=uv;
    normal_texcoord-=sample_offset/vec2(96,64);
    base_color_uv=metallic_roughness_uv=occlusion_uv=emissive_uv=uv;
    normal_uv=normal_texcoord;
    vec2 pixel=uv*vec2(96,64)-sample_offset;
    vary_normal=vec3((pixel-vec2(48.37,32.19))*normal_slope,1);
    vary_tangent=vec3(1,0,0); vary_sign=1;
    vary_position=vec3(0,0,-2); vary_fragcoord=vec3(0,0,1); vertex_color=vec4(1);
}
"""


def run(sdl, gl):
    gpu=GPU(sdl,gl)
    read=lambda p:(SHADERS/p).read_text()
    helper=function(read('class1/deferred/globalF.glsl'),'float filterPBRRoughness(')
    global_source=read('class1/deferred/globalF.glsl')
    # Unrelated fog and color-space inputs are identity fixtures. Actual normal
    # encoding, material sampling/factors, roughness and GGX are exercised.
    helpers='uniform float sss_object;\n'+function(global_source,'vec4 encodeNormal(')
    helpers+='vec3 srgb_to_linear(vec3 c){return c;}\nvoid mirrorClip(vec3 p){}\n'
    opaque_source='#define GBUFFER_FLAG_HAS_PBR 1.0\n'+read('class1/deferred/pbropaqueF.glsl')
    materials=[gpu.program(opaque_source+helpers+h,VERTEX) for h in (
        'float filterPBRRoughness(float r,vec3 n){return r;}\n',helper)]
    util=read('class1/deferred/deferredUtil.glsl')
    brdf=util[util.index('struct PBRInfo'):util.index('bool hasAlphaProjector(')]
    lighting=gpu.program('#define M_PI 3.141592653589793\n'+brdf+
        function(global_source,'vec4 decodeNormal(')+"""
uniform sampler2D material_orm, material_normal;
out vec4 frag_color;
void main() {
    ivec2 p=ivec2(gl_FragCoord.xy);
    float r=texelFetch(material_orm,p,0).g;
    vec3 n=decodeNormal(texelFetch(material_normal,p,0)).xyz;
    float nl; vec3 diff,spec;
    pbrPunctual(vec3(0),vec3(.8,.5,.16),r,1,n,vec3(0,0,1),vec3(0,0,1),nl,diff,spec);
    frag_color=vec4(min(vec3(.05)+nl*spec,vec3(65000)),.37);
}
""")
    resolve=gpu.program(read('class1/deferred/taaResolveF.glsl'))
    copy=gpu.program(read('class1/deferred/taaCopyF.glsl'))
    gbuffer=[gpu.texture() for _ in range(4)]
    albedo=gpu.texture([1,1,1,1]*(W*H))
    normals=gpu.texture([.5,.5,1,1]*(W*H))
    orm=gpu.texture([.7,1,.8,1]*(W*H))
    current,history,output,present=[gpu.texture() for _ in range(4)]
    vectors=gpu.texture([0,0,2,-1]*(W*H))
    depth=gpu.texture([(1.002002-.2002002/2)*.5+.5]*(W*H),True)
    projection=[[1,0,0,0],[0,1,0,0],[0,0,-1.002002,-.2002002],[0,0,-1,0]]
    identity=[[float(r==c) for c in range(4)] for r in range(4)]
    gpu.matrix(resolve,'taa_current_from_previous',identity)
    gpu.matrix(resolve,'taa_previous_inv_projection',inverse(projection))
    for prog in (resolve,copy): gpu.uniform(prog,'taa_rcp_res',1/W,1/H)
    for name,value in [('taa_motion_protection',.85),('taa_clip_gamma',1.2),('taa_transparency',.5)]:
        gpu.uniform(resolve,name,value)
    gpu.uniform(resolve,'taa_static_details',1,integer=True)
    gpu.uniform(copy,'taa_copy_mode',1,integer=True)
    gpu.uniform(copy,'taa_sharpen',1.5)
    checks=0
    def check(condition,message):
        nonlocal checks
        assert condition,message
        checks+=1

    # Terrain chooses its ORM representation and texture mapping at compile
    # time. Compile every combination, including its normal-free low tier.
    for detail in (-3,-2,-1,0):
        for mapping in (1,3):
            for paint in (0,1):
                source=('#version 150 core\n#define GBUFFER_FLAG_HAS_PBR 1.0\n'
                        f'#define TERRAIN_PBR_DETAIL {detail}\n#define TERRAIN_PLANAR_TEXTURE_SAMPLE_COUNT {mapping}\n'
                        f'#define TERRAIN_PAINT_TYPE {paint}\n'+read('class1/deferred/pbrterrainF.glsl')+helper)
                shader=gl.CreateShader(0x8B30); code=C.c_char_p(source.encode())
                gl.ShaderSource(shader,1,C.byref(code),None); gl.CompileShader(shader)
                ok=I(); log=C.create_string_buffer(16384)
                gl.GetShaderiv(shader,0x8B81,C.byref(ok)); gl.GetShaderInfoLog(shader,len(log),None,log)
                check(ok.value, f'terrain {detail}/{mapping}/{paint}: '+log.value.decode())
                gl.DeleteShader(shader)

    def material(prog,roughness,slope,offset=(0,0),gltf=False):
        for unit,(name,tex) in enumerate((('diffuseMap',albedo),('normalMap' if gltf else 'bumpMap',normals),
                ('metallicRoughnessMap' if gltf else 'specularMap',orm),('emissiveMap',albedo),('occlusionMap',orm))):
            gpu.bind(prog,name,unit,tex)
        gpu.uniform(prog,'roughnessFactor',roughness)
        gpu.uniform(prog,'metallicFactor',.5)
        gpu.uniform(prog,'minimum_alpha',.5)
        gpu.uniform(prog,'normal_slope',slope)
        gpu.uniform(prog,'sample_offset',*offset)
        for i,tex in enumerate(gbuffer):
            gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT+i,TEXTURE,tex,0)
        gl.DrawBuffers(4,(U*4)(*(COLOR_ATTACHMENT+i for i in range(4))))
        assert gl.CheckFramebufferStatus(FRAMEBUFFER)==0x8CD5, 'material framebuffer'
        gl.ClearColor(-1,-1,-1,-1); gl.Clear(0x4000)
        gl.UseProgram(prog); gl.DrawArrays(4,0,3)
        for i in range(1,4): gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT+i,TEXTURE,0,0)
        gl.DrawBuffers(1,(U*1)(COLOR_ATTACHMENT))

    middle=(H//2*W+W//2)*4
    for roughness in (0,.04,.15,.5,1):
        material(materials[1],roughness,0)
        pixel=gpu.read(gbuffer[1])[middle:middle+4]
        check(abs(pixel[1]-roughness)<.001,'flat normals must preserve authored roughness, including mirrors')
        check(abs(pixel[0]-.7)<.001 and abs(pixel[2]-.4)<.001,'filter must preserve occlusion and metallic')
        material(materials[1],roughness,.08)
        value=gpu.read(gbuffer[1])[middle+1]
        check(roughness-.001<=value<=min(roughness**4+.04,1)**.25+.001,
              'filter must only broaden the lobe within its variance cap')

    material(materials[1],.04,.08)
    unmasked=gpu.read(gbuffer[1])
    mask=[float((x+y)%2) for y in range(H) for x in range(W)]
    gpu.upload(albedo,[c for a in mask for c in (1,1,1,a)])
    material(materials[1],.04,.08)
    masked=gpu.read(gbuffer[1])
    check(max(abs(masked[i*4+1]-unmasked[i*4+1]) for i,a in enumerate(mask) if a) < .001,
          'partially discarded quads must keep the same filtered roughness')
    check(all(masked[i*4+1]==-1 for i,a in enumerate(mask) if not a),
          'material filtering must preserve alpha-mask holes')
    gpu.upload(albedo,[1,1,1,1]*(W*H))

    # Forward/OIT and imported glTF must consume exactly the same filtered
    # material as deferred lighting. Return BRDF parameters as RGB to inspect
    # the arguments at the production lighting call (other lighting is zero).
    forward_stubs=STUBS.replace('return irr;', 'return vec3(r,m,ao);')
    forward_stubs=forward_stubs.replace('return vec4(c.rgb * atten + additive, c.a);', 'return c;')
    forward_stubs=forward_stubs.replace('layout(location=0) out', 'out')
    forward_stubs+='''
bool isSSSOverlay(vec3 p){return false;}
vec3 pbrCalcPointLightOrSpotLight(int i,vec3 d,vec3 s,float r,float m,
    vec3 n,vec3 p,vec3 v,vec3 lp,vec3 ld,vec3 lc,float ls,float f,float pt,float a){return vec3(0);}
'''
    gl.GetUniformBlockIndex=C.WINFUNCTYPE(U,U,C.c_char_p)(sdl.SDL_GL_GetProcAddress(b'glGetUniformBlockIndex'))
    gl.UniformBlockBinding=C.WINFUNCTYPE(None,U,U,U)(sdl.SDL_GL_GetProcAddress(b'glUniformBlockBinding'))
    material_data=[0.0]*48
    material_data[44:48]=[0,.2,.5,-1.5]
    ubo=gpu.obj(gl.GenBuffers)
    gl.BindBuffer(0x8A11,ubo)
    gl.BufferData(0x8A11,48*C.sizeof(F),(F*48)(*material_data),0x88E4)
    gl.BindBufferBase(0x8A11,0,ubo)
    for unlit in (False,True):
        defines='#define MAX_UBO_VEC4S 12\n#define GBUFFER_FLAG_HAS_PBR 1.0\n'
        if unlit: defines+='#define UNLIT 1\n'
        prog=gpu.program(defines+read('class1/gltf/pbrmetallicroughnessF.glsl')+helpers+helper,VERTEX)
        gl.UniformBlockBinding(prog,gl.GetUniformBlockIndex(prog,b'GLTFMaterials'),0)
        gpu.uniform(prog,'gltf_material_id',0,integer=True)
        material(prog,.2,.04,gltf=True)
        if not unlit:
            actual=gpu.read(gbuffer[1])[middle:middle+4]
            material(materials[1],.2,.04)
            expected=gpu.read(gbuffer[1])[middle:middle+4]
            check(max(abs(a-b) for a,b in zip(actual,expected))<.002,
                  'imported opaque glTF must use the same filtered ORM as the viewer PBR path')
        for depth_mode in (1,2):
            gpu.uniform(prog,'sss_depth_pass',depth_mode,integer=True)
            material(prog,.2,.04,gltf=True)
            pixel=gpu.read(gbuffer[0])[middle:middle+4]
            expected=[.5,0,.5,0] if depth_mode==1 else [-1]*4
            check(max(abs(a-b) for a,b in zip(pixel,expected))<.001,
                  f'glTF depth-only mode {depth_mode}, unlit={unlit} must keep its original coverage/output')
    for path,gltf in [('class2/deferred/pbralphaF.glsl',False),
                      ('class1/gltf/pbrmetallicroughnessF.glsl',True)]:
        for oit in (False,True):
            defines='#define MAX_UBO_VEC4S 12\n#define ALPHA_BLEND 1\n#define HAS_ALPHA_MASK 1\n'
            if oit: defines+='#define EXACT_OIT 1\n'
            prog=gpu.program(defines+read(path)+helper+forward_stubs,VERTEX)
            if gltf:
                block=gl.GetUniformBlockIndex(prog,b'GLTFMaterials')
                gl.UniformBlockBinding(prog,block,0)
                gpu.uniform(prog,'gltf_material_id',0,integer=True)
            gpu.uniform(prog,'roughnessFactor',.2); gpu.uniform(prog,'metallicFactor',.5)
            for slope in (0,.04):
                material(materials[1],.2,slope)
                expected=gpu.read(gbuffer[1])[middle:middle+4]
                # The opaque draw changed the active texture units; bind again.
                for unit,(name,tex) in enumerate((('diffuseMap',albedo),('normalMap' if gltf else 'bumpMap',normals),
                        ('metallicRoughnessMap' if gltf else 'specularMap',orm),('emissiveMap',albedo),('occlusionMap',orm))):
                    gpu.bind(prog,name,unit,tex)
                gpu.uniform(prog,'normal_slope',slope)
                gpu.draw(prog,current); actual=gpu.read(current)[middle:middle+4]
                check(max(abs(a-b) for a,b in zip(actual[:3],(expected[1],expected[2],expected[0])))<.002,
                      f'{path}, OIT={oit}: roughness and factors must match the opaque material')
                check(abs(actual[3]-1)<.001,'specular filtering must preserve alpha')

    def halton(i,b):
        f=1; v=0
        while i: f/=b; v+=f*(i%b); i//=b
        return v
    # Identical 16x16 highlight window for both paths, including the broadened
    # lobe. A per-variant mask would unfairly reward spreading the same error.
    roi=[y*W+x for y in range(H//2-8,H//2+8) for x in range(W//2-8,W//2+8)]
    results=[]
    for roughness,slope,mapped in ((.04,.04,False),(.08,.08,False),(.15,.035,False),(.04,.04,True)):
        normal_values=[]
        for y in range(H):
            for x in range(W):
                nx=(x+.5-48.37)*slope if mapped else 0
                ny=(y+.5-32.19)*slope if mapped else 0
                length=math.sqrt(nx*nx+ny*ny+1)
                normal_values.extend((nx/length*.5+.5,ny/length*.5+.5,1/length*.5+.5,1))
        gpu.upload(normals,normal_values)
        for history_weight in (.76,.97):
            pair=[]
            for filtered,prog in enumerate(materials):
                frames=[]
                for frame in range(96):
                    jitter=[halton(frame%8+1,2)-.5,halton(frame%8+1,3)-.5]
                    material(prog,roughness,0 if mapped else slope,jitter)
                    gpu.bind(lighting,'material_orm',0,gbuffer[1])
                    gpu.bind(lighting,'material_normal',1,gbuffer[2])
                    gpu.draw(lighting,current)
                    jp=[row[:] for row in projection]
                    for c in range(4):
                        jp[0][c]+=2*jitter[0]/W*projection[3][c]
                        jp[1][c]+=2*jitter[1]/H*projection[3][c]
                    gpu.matrix(resolve,'taa_inv_projection',inverse(jp))
                    gpu.uniform(resolve,'taa_jitter',jitter[0]/W,jitter[1]/H)
                    gpu.uniform(resolve,'taa_history_weight',history_weight)
                    gpu.uniform(resolve,'taa_history_valid',int(frame>0),integer=True)
                    gpu.viewer_bind('resolveTAA',resolve,{'mRT->screen':current,'mTAAHistory[1 - mTAAIndex]':history,
                        'mTAAMotion':vectors,'mTAAOpaque':current,'mRT->deferredScreen':depth})
                    gpu.draw(resolve,output)
                    if frame>=80:
                        gpu.viewer_bind('copyTAA',copy,{'src':output,'mMainRT.screen':current})
                        gpu.uniform(copy,'taa_jitter',jitter[0]/W,jitter[1]/H)
                        gpu.draw(copy,present); pixels=gpu.read(present)
                        frames.append([pixels[i*4]/(1+pixels[i*4]) for i in roi])
                    history,output=output,history
                flicker=statistics.mean(max(v)-min(v) for v in zip(*frames))
                peak_flicker=max(max(v)-min(v) for v in zip(*frames))
                energy=statistics.mean(sum(max(c-.05/1.05,0) for c in v) for v in frames)
                result=dict(roughness=roughness,slope=slope,normal_map=mapped,history=history_weight,
                            filtered=bool(filtered),flicker=flicker,peak_flicker=peak_flicker,display_energy=energy)
                pair.append(result); results.append(result)
                print(json.dumps(result),flush=True)
            check(pair[1]['peak_flicker']<pair[0]['peak_flicker']*.6,'pixel-footprint filtering must reduce sharp-highlight flicker')
            check(pair[1]['display_energy']>pair[0]['display_energy']*.8,'stability must not come from erasing the highlight')
    print(f'PASS: {checks} PBR specular AA GPU checks')
    return dict(gpu=gl.GetString(0x1F01).decode(),checks=checks,results=results)


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try:
        result=run(sdl,gl)
        path=ROOT/'tmp/taa-tests/specular-results.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(result,indent=2)+'\n')
    finally:
        sdl.SDL_GL_DestroyContext(ctx); sdl.SDL_DestroyWindow(window); sdl.SDL_Quit()
