"""Exercise production hair shading, G-buffer flags and forward coverage on the GPU.

Run: .venv/Scripts/python.exe scripts/tests/test_hair_gpu.py
Uses the existing hidden SDL/OpenGL harness; no login or performance claims.
"""
import ctypes as C
import math
import re
import xml.etree.ElementTree as ET

from test_taa_gpu import GPU, ROOT, SHADERS, W, H, context
from test_exact_oit_gpu import U, I, F, FRAMEBUFFER, COLOR_ATTACHMENT, TEXTURE
from test_alpha_lighting_gpu import STUBS, VERTEX, function
from test_sss_shadow_gpu import STUBS as DEFERRED_STUBS

FLAGS = '\n'.join(re.findall(r'strdup\("(#define (?:GBUFFER_|GET_GBUFFER_).*?)\\n"\)',
    (ROOT / 'indra/llrender/llshadermgr.cpp').read_text()))
read = lambda name: (SHADERS / name).read_text()


def run(sdl, gl):
    gpu = GPU(sdl, gl)
    checks = 0
    def check(condition, message):
        nonlocal checks
        assert condition, message
        checks += 1

    def program(fragment, vertex=None, extras=(), defines=''):
        result = gl.CreateProgram()
        stages = [(0x8B31, vertex or gpu.vertex), (0x8B30, fragment)]
        stages += [(0x8B30, read('class1/deferred/hairUtil.glsl'))]
        stages += [(0x8B30, '#define HAIR_DENSITY_MAPS 1\n'+read('class1/deferred/hairDepthUtil.glsl'))]
        stages += [(0x8B30, text) for text in extras]
        for kind, source in stages:
            shader = gl.CreateShader(kind)
            code = C.c_char_p(('#version 430 core\n' + FLAGS + '\n' + defines + source).encode())
            gl.ShaderSource(shader, 1, C.byref(code), None)
            gl.CompileShader(shader)
            ok, log = I(), C.create_string_buffer(16384)
            gl.GetShaderiv(shader, 0x8B81, C.byref(ok))
            gl.GetShaderInfoLog(shader, len(log), None, log)
            check(ok.value, log.value.decode())
            gl.AttachShader(result, shader)
            gl.DeleteShader(shader)
        gl.LinkProgram(result)
        gl.GetProgramiv(result, 0x8B82, C.byref(ok))
        gl.GetProgramInfoLog(result, len(log), None, log)
        check(ok.value, log.value.decode())
        gpu.uniform(result, 'hair_variation_strength', 1)
        return result

    target = gpu.texture()
    gl.ColorMask(1,1,1,1)
    gl.Disable(0x0B71)
    gl.Disable(0x0BE2)
    middle = (H // 2 * W + W // 2) * 4
    def pixel(prog):
        gpu.draw(prog, target)
        values = gpu.read(target)[middle:middle+4]
        check(all(math.isfinite(v) and v >= 0 for v in values), ('finite nonnegative', values))
        return values

    lighting = program('''
uniform vec3 base, n, t, v, l;
uniform float variation;
vec3 hairDirect(vec3 base, vec3 n, vec3 t, vec3 v, vec3 l, float variation);
out vec4 frag_color;
void main() { frag_color = vec4(hairDirect(base, n, t, v, l, variation), 1); }
''')
    def response(base=(.1,.04,.015), light=(0,0,1), tangent=(0,1,0), roughness=.35,
                 shine=.7, transmission=.5, thickness=1, normal=(0,0,1), variation=.5, variation_strength=1,
                 brightness=0):
        for name, value in [('base',base),('n',normal),('t',tangent),('v',(0,0,1)),('l',light)]:
            gpu.uniform(lighting, name, *value)
        gpu.uniform(lighting, 'variation', variation)
        gpu.uniform(lighting, 'hair_variation_strength', variation_strength)
        gpu.uniform(lighting, 'hair_brightness_compensation', brightness)
        gpu.uniform(lighting, 'hair_params', roughness, shine, transmission, thickness)
        return pixel(lighting)

    for base in [(0,0,0),(.004,.002,.001),(.1,.02,.005),(.8,.6,.2),(1,1,1),(.05,.2,.8)]:
        for roughness in (.12,.35,1):
            for light in [(0,0,1),(0,0,-1),(0,1,0),(.6,0,.8)]:
                c = response(base, light, roughness=roughness)
                check(max(c[:3]) < 6, ('bounded highlight', c))
        thin = response(base, (0,0,-1), thickness=.25)
        thick = response(base, (0,0,-1), thickness=4)
        check(all(a >= b for a,b in zip(thin,thick)), 'thickness attenuates all colours')
    off = response(light=(0,0,-1), transmission=0)
    on = response(light=(0,0,-1), transmission=1)
    check(max(off[:3]) == 0 and on[0] > on[1] > on[2], ('backlight is tinted and switchable', off, on))
    check(response(normal=(0,0,-1)) == response(), 'two-sided hair response')
    no_shine = response(shine=0)
    shine = response(shine=2)
    check(all(a>b for a,b in zip(shine[:3],no_shine[:3])), 'shine increases the highlight')
    check(response(light=(.6,0,.8)) != response(light=(.6,0,.8), tangent=(1,0,0)), 'strand anisotropy')

    check(response(base=(0,0,0), light=(0,0,-1), shine=0, thickness=.25)[:3]==[0,0,0],
        'black dye cannot acquire transmission from an artificial colour floor')
    for normal in ((0,0,1),(.8,0,.6),(-.8,0,.6)):
        broad=response(base=(.8,.6,.2),light=(.6,0,-.8),normal=normal,shine=0,transmission=1)
        unscattered=response(base=(.8,.6,.2),light=(.6,0,-.8),normal=normal,shine=0,transmission=0)
        check(broad[0]>unscattered[0], 'off-axis scattering survives without specular on cards and curved surfaces')
    check(response(base=(1,1,1),shine=0,transmission=1)==response(base=(1,1,1),shine=0,transmission=0),
        'white front lighting redistributes energy instead of adding a white fill')
    for variation in (0,.5,1):
        check(response(shine=0,variation=variation)==response(shine=0), 'strand finish changes highlights, not pigment')
        for angle in range(0,181,15):
            a=math.radians(angle)
            c=response(light=(math.sin(a),0,math.cos(a)),variation=variation,thickness=.25,roughness=.12)
            check(max(c[:3])<1.5,'grazing and backlit lobes stay bounded at minimum roughness')
    check(response(variation=0)[0]>response(variation=1)[0], 'rough strands spread their highlight')
    check(response(variation=0,variation_strength=0)==response(variation=1,variation_strength=0),
        'zero strand strength completely disables texture-driven highlight variation')
    for finish in (0,1):
        neutral=response(variation=finish,variation_strength=0)[0]
        normal_strength=response(variation=finish,variation_strength=1)[0]
        stronger=response(variation=finish,variation_strength=2)[0]
        check(abs(stronger-neutral)>abs(normal_strength-neutral)>0,
            'strand strength increases breakup on both bright and dark strands')
        check(response(shine=0,variation=finish,variation_strength=2)==response(shine=0,variation_strength=0),
            'strand control leaves diffuse scattering unchanged')

    for base in ((0,0,0),(.005,.005,.005),(.18,.18,.18),(.75,.75,.75),(1,1,1),(.05,.2,.8)):
        original=response(base=base)
        compensated=[response(base=base,brightness=s) for s in (.5,1,2,4)]
        if base[0]<.18 and base[1]<.18:
            check(original[0]>compensated[0][0]>compensated[1][0]>compensated[2][0]>compensated[3][0],
                  'more compensation progressively softens dark-hair highlights')
            check(compensated[-1][0]>0,'black hair retains a bounded surface reflection')
        if base[0]>.18 and base[1]>.18:
            check(original[0]<compensated[0][0]<compensated[1][0]<compensated[2][0]<compensated[3][0],
                  'more compensation progressively strengthens light-hair highlights')
        if base==(.18,.18,.18):
            check(max(abs(a-b) for c in compensated for a,b in zip(c,original))<.001,
                  'medium grey remains neutral at all strengths')
        for light in ((0,0,1),(.6,0,-.8)):
            check(response(base=base,light=light,shine=0,brightness=4)==response(base=base,light=light,shine=0),
                  'brightness compensation leaves pigment and internal scattering unchanged')
        check(response(base=base,brightness=-1)==original,'negative compensation clamps to off')
        check(response(base=base,brightness=5)==compensated[-1],'oversized compensation clamps to the slider maximum')

    finish=program('''
uniform vec4 center, alongL, alongR, acrossL, acrossR;
uniform float footprint;
float hairStrandVariation(vec4 c,vec4 al,vec4 ar,vec4 cl,vec4 cr,float footprint);
out vec4 frag_color;
void main() { frag_color=vec4(vec3(hairStrandVariation(center,alongL,alongR,acrossL,acrossR,footprint)),1); }
''')
    def strand_finish(heights,coverage=1,footprint=0):
        for name,h in zip(('center','alongL','alongR','acrossL','acrossR'),heights):
            gpu.uniform(finish,name,h,h,h,coverage)
        gpu.uniform(finish,'footprint',footprint)
        return pixel(finish)[0]
    check(strand_finish([.3]*5)==.5,'uniform texture keeps the nominal roughness')
    gradient=[math.exp(v) for v in (-1,-1.1,-.9,-1.3,-.7)]
    check(abs(strand_finish(gradient)-.5)<.001,'painted broad gradients do not become strand finish')
    ridges=[.6,.6,.6,.2,.2]
    ridge=strand_finish(ridges)
    check(ridge>.8 and strand_finish([.2,.2,.2,.6,.6])<.2,'local strands vary the finish in both directions')
    check(strand_finish(ridges,coverage=0)==.5,'transparent RGB cannot change the finish')
    check(abs(strand_finish(ridges,footprint=16)-.5)<abs(ridge-.5)*.02,'subpixel variation fades without random shimmer')
    check(strand_finish([.3,.2,.4,.1,.5])==strand_finish([.3,.4,.2,.5,.1]),'opposite strand signs give the same finish')

    packing = program('''
uniform vec3 n, t;
uniform float flag;
vec4 encodeHairNormal(vec3 n, float env, float flag, vec3 t);
vec3 decodeHairTangent(vec3 n, float angle);
out vec4 frag_color;
void main() {
    vec4 encoded = encodeHairNormal(n, .37, flag, t);
    // Reproduce the actual UNORM16 normal attachment, including the angle and flags.
    encoded = round(encoded * 65535.0) / 65535.0;
    vec3 tangent = decodeHairTangent(n, encoded.z);
    frag_color = vec4(GBUFFER_HAIR_FLAG(encoded.w), GBUFFER_SSS_FLAG(encoded.w),
        GBUFFER_AVATAR_FLAG(encoded.w), GET_GBUFFER_FLAG(encoded.w, flag) ? 1.0 : 0.0);
}
''', extras=[read('class1/deferred/globalF.glsl')])
    for hair in (0,1):
        for skin in (0,1):
            for avatar in (0,1):
                for flag in (.34,.67):
                    for name,val in [('hair_object',hair),('sss_object',skin),('ssgi_avatar',avatar),('flag',flag)]:
                        gpu.uniform(packing,name,val)
                    gpu.uniform(packing,'n',0,0,1)
                    gpu.uniform(packing,'t',0,1,0)
                    check(pixel(packing)==[hair, skin*(1-hair), avatar, 1], 'independent surface and avatar flags')

    tangent = program('''
uniform vec3 n;
uniform vec2 uv_scale;
uniform float position_scale;
uniform float face_angle;
vec3 hairTangent(vec3 p, vec2 uv, vec3 n);
vec4 encodeHairNormal(vec3 n, float env, float flag, vec3 t);
vec3 decodeHairTangent(vec3 n, float angle);
out vec4 frag_color;
void main() {
    vec2 p = gl_FragCoord.xy;
    vec3 pos=vec3(p.x*cos(face_angle),p.y,p.x*sin(face_angle))*position_scale;
    vec3 t = hairTangent(pos, p * uv_scale, n);
    vec4 encoded = encodeHairNormal(n, 0.0, .34, t);
    float angle = round(encoded.z * 65535.0) / 65535.0;
    vec3 decoded = decodeHairTangent(n, angle);
    frag_color = vec4(t * .5 + .5, dot(t, decoded));
}
''', extras=[read('class1/deferred/globalF.glsl')])
    gpu.uniform(tangent,'n',0,0,1)
    gpu.uniform(tangent,'hair_object',1)
    gpu.uniform(tangent,'position_scale',1)
    for uv in [(1,1),(-1,1),(1,-1),(0,0)]:
        gpu.uniform(tangent,'uv_scale',*uv)
        for angle in (0,45,90,135,180):
            gpu.uniform(tangent,'hair_direction',math.radians(angle))
            c = pixel(tangent)
            check(c[3]>.999,'quantized tangent round trip, including mirrored/degenerate UVs')
            if uv==(1,1) and angle==0: check(c[:3]==[.5,1,.5],'default follows V')
            if uv==(1,1) and angle==90: check(abs(c[0]-1)<.001 and abs(c[1]-.5)<.001,'rotation follows U')

    # Real close-ups have submillimetre position and UV derivatives. Their
    # magnitude must not switch the strand to an unrelated fallback basis.
    gpu.uniform(tangent,'hair_direction',0)
    for scale in (1., .01, .001, .0001):
        gpu.uniform(tangent,'position_scale',scale)
        for uv in ((scale,scale),(-scale,scale),(scale,-scale)):
            gpu.uniform(tangent,'uv_scale',*uv)
            c = pixel(tangent)
            check(abs(c[0]-.5)<.001 and abs(c[1]-(1 if uv[1]>0 else 0))<.001,
                ('strand direction is independent of screen/UV scale',scale,uv,c))

    # Adjacent curved quads can have different face tilts but the same smooth
    # shading normal. Projecting their frame shears diagonal strands differently.
    gpu.uniform(tangent,'hair_direction',math.pi/4)
    gpu.uniform(tangent,'uv_scale',.001,.001)
    for degrees in (-70,-45,-20,0,20,45,70):
        gpu.uniform(tangent,'face_angle',math.radians(degrees))
        t=[(v-.5)*2 for v in pixel(tangent)[:3]]
        check(abs(t[0]-t[1])<.002 and abs(t[2])<.002,
            ('smooth strand angle is independent of polygon tilt',degrees,t))

    # Mesh tangents must hide changes in triangle shape/UV gradients while
    # keeping the diffuse texture's rotation, scale and mirror transforms.
    mesh_frame = program('''
uniform vec4 uv_transform;
uniform vec2 triangle_shape, axis;
uniform float handedness, face_angle, derivative_scale;
mat3 hairMeshFrame(vec3 p,vec2 uv,vec2 meshUV,vec3 n,vec4 tangent);
out vec4 frag_color;
void main() {
    vec2 p=(gl_FragCoord.xy-vec2(48.5,32.5))*derivative_scale;
    vec2 meshUV=vec2(p.x*triangle_shape.x+p.y*triangle_shape.y,p.y);
    vec2 uv=mat2(uv_transform)*meshUV;
    vec3 pos=vec3(p.x*cos(face_angle),p.y,p.x*sin(face_angle));
    mat3 frame=hairMeshFrame(pos,uv,meshUV,vec3(0,0,1),vec4(1,0,0,handedness));
    vec3 t=normalize(frame[0]*axis.x+frame[1]*axis.y);
    frag_color=vec4(t*.5+.5,1);
}
''')
    for transform in ((1,0,0,1),(0,1,-1,0),(-2,0,0,.5),(1,.3,.2,2)):
        a,b,c,d=transform
        determinant=a*d-b*c
        for hand in (1,-1):
            expected=((d-c)/determinant,hand*(a-b)/determinant,0)
            magnitude=math.sqrt(sum(v*v for v in expected))
            expected=[v/magnitude for v in expected]
            for shape,tilt,scale in (((1,0),0,.001),((.4,.7),-50,1e-7),((3,-.8),60,.02)):
                gpu.uniform(mesh_frame,'uv_transform',*transform)
                gpu.uniform(mesh_frame,'triangle_shape',*shape)
                gpu.uniform(mesh_frame,'face_angle',math.radians(tilt))
                gpu.uniform(mesh_frame,'derivative_scale',scale)
                gpu.uniform(mesh_frame,'handedness',hand)
                gpu.uniform(mesh_frame,'axis',1,1)
                actual=[v*2-1 for v in pixel(mesh_frame)[:3]]
                check(max(abs(x-y) for x,y in zip(actual,expected))<.002,
                    ('continuous mesh frame with transformed UVs',transform,shape,tilt,actual,expected))

    # Link every changed production vertex path, including skinned variants.
    frame_probe='''in vec4 vary_hair_tangent; in vec2 vary_hair_texcoord;
out vec4 frag_color;
void main() { frag_color=vary_hair_tangent+vec4(vary_hair_texcoord,0,0); }'''
    for name in ('diffuseV','alphaV','materialV','bumpV','pbropaqueV','pbralphaV'):
        for skin in (False,True):
            defines='#define USE_VERTEX_COLOR 1\n#define USE_INDEXED_TEX 1\n'
            if skin: defines+='#define HAS_SKIN 1\n'
            vertex=read('class1/deferred/'+name+'.glsl')
            vertex+='\nvoid passTextureIndex() {}\nmat4 getObjectSkinnedTransform() { return mat4(1); }\n'
            if name.startswith('pbr'): vertex+=read('class1/deferred/textureUtilV.glsl')
            program(frame_probe,vertex,defines=defines)

    detail = program('''
uniform vec4 heights;
uniform vec2 uv_scale;
uniform vec2 strand_axis;
uniform float face_angle;
uniform float coverage;
mat3 hairMeshFrame(vec3 p,vec2 uv,vec2 meshUV,vec3 n,vec4 tangent);
vec3 hairDetailNormal(mat3 frame,vec3 n,vec2 axis,float footprint,vec4 c,vec4 a,vec4 b,vec4 d,vec4 e);
out vec4 frag_color;
void main() {
    vec2 p=gl_FragCoord.xy;
    vec3 pos=vec3(p.x*cos(face_angle),p.y,p.x*sin(face_angle))*.001;
    mat3 frame=hairMeshFrame(pos,p*uv_scale,p*uv_scale,vec3(0,0,1),vec4(0));
    vec3 n=hairDetailNormal(frame,vec3(0,0,1),strand_axis,1024.0*length(uv_scale),vec4(.5,.5,.5,coverage),
        vec4(vec3(heights.x),coverage),vec4(vec3(heights.y),coverage),
        vec4(vec3(heights.z),coverage),vec4(vec3(heights.w),coverage));
    frag_color=vec4(n*.5+.5,1);
}
''')
    def detail_normal(heights, coverage=1, uv=(.0001,.0001), axis=(0,1), tilt=0):
        gpu.uniform(detail,'hair_detail',.35,1,1)
        gpu.uniform(detail,'heights',*heights)
        gpu.uniform(detail,'coverage',coverage)
        gpu.uniform(detail,'uv_scale',*uv)
        gpu.uniform(detail,'strand_axis',*axis)
        gpu.uniform(detail,'face_angle',math.radians(tilt))
        return [(v-.5)*2 for v in pixel(detail)[:3]]
    for brightness in (0,.01,.1,.8,1):
        check(detail_normal([brightness]*4)==[0,0,1], 'flat artwork adds no bump')
    ramp = [.4*math.exp(k) for k in (-.1,.1,-.4,.4)]
    check(abs(detail_normal(ramp)[0])<.001, 'broad log-brightness slope is suppressed')
    ridges = [.08,.65,.3,.3]
    bumped = detail_normal(ridges)
    check(-.45 <= bumped[0] < -.05 and bumped[2] > .89, 'strand contrast gives bounded normal detail')
    check(detail_normal(ridges,coverage=0)==[0,0,1], 'transparent RGB cannot raise ridges')
    check(abs(detail_normal(ridges,uv=(.01,.01))[0])<abs(bumped[0])*.1, 'unresolved detail fades')
    mirrored=detail_normal(ridges,uv=(-.0001,.0001))
    check(abs(mirrored[0]+bumped[0])<.001, 'mirrored UVs preserve bump direction')
    check(detail_normal(ridges,uv=(0,0))==[0,0,1], 'degenerate UVs stay flat')
    diagonal=(math.sqrt(.5),math.sqrt(.5))
    for tilt in (-70,-45,0,45,70):
        n=detail_normal(ridges,axis=diagonal,tilt=tilt)
        check(abs(n[0]+n[1])<.002 and n[0]<-.02,
            ('generated ridges also preserve their angle across polygon tilts',tilt,n))

    flow = program('''
uniform vec4 row0, row1, row2;
uniform vec2 step_uv;
vec3 hairFlowAxis(vec4 a,vec4 b,vec4 c,vec2 stepUV,vec2 fallback);
out vec4 frag_color;
void main() {
    vec3 f=hairFlowAxis(row0,row1,row2,step_uv,vec2(0,1));
    frag_color=vec4(f.xy*.5+.5,f.z,1);
}
''')
    def flow_axis(rows, step=(1,1), coverage=1, smoothing=.75):
        gpu.uniform(flow,'hair_flow',1,2,smoothing)
        gpu.uniform(flow,'step_uv',*step)
        for i,row in enumerate(rows): gpu.uniform(flow,f'row{i}',*row,coverage)
        c=pixel(flow)
        return [(c[0]-.5)*2,(c[1]-.5)*2,c[2]]
    for degrees in range(0,180,15):
        a=math.radians(degrees)
        axis=(math.cos(a),math.sin(a))
        for step in ((1,1),(1,2)):
            rows=[[.2*(-x*axis[1]*step[0]+y*axis[0]*step[1]) for x in (-1,0,1)] for y in (-1,0,1)]
            f=flow_axis(rows,step)
            check(abs(f[0]*axis[0]+f[1]*axis[1])/math.hypot(*f[:2])>.999 and f[2]>.99,
                ('detect rotated strands and non-square texels',degrees,step,f))
            inverse=flow_axis([[-v for v in row] for row in rows],step)
            check(max(abs(x-y) for x,y in zip(f,inverse))<.002,('bright/dark ridges have the same line axis',f,inverse))
    for rows,coverage in [([[0]*3]*3,1),([[-1,1,-1],[1,-1,1],[-1,1,-1]],1),
                          ([[-.2,0,.2]]*3,0),([[-.001,0,.001]]*3,1)]:
        check(flow_axis(rows,coverage=coverage)==[0,1,0],'flat, isotropic, transparent and weak patterns fall back')

    # Sample a curved strand texture through the same surface entry point as all materials.
    surface = program('''
uniform vec2 offset, uv_scale, texture_size;
uniform int generate_normal, output_normal;
vec3 hairSurface(vec3 p,vec2 uv,inout vec3 n,vec4 c,bool generateNormal,out vec3 preview,out float variation);
mat3 hairMeshFrame(vec3 p,vec2 uv,vec2 meshUV,vec3 n,vec4 tangent);
mat3 hairVertexFrame() {
    vec2 p=gl_FragCoord.xy-vec2(48.5,32.5);
    return hairMeshFrame(vec3(p*.001,-5),offset+p*uv_scale,p*vec2(.0001),vec3(0,0,1),vec4(1,0,0,1));
}
vec2 hairTextureSize() { return texture_size; }
vec4 hairDiffuseLookup(vec2 uv) { return vec4(vec3(exp(-1.0+.5*sin(40.0*length(uv)))),1); }
out vec4 frag_color;
void main() {
    vec2 p=gl_FragCoord.xy-vec2(48.5,32.5);
    vec2 uv=offset+p*uv_scale;
    vec3 n=vec3(0,0,1), preview; float variation;
    vec3 t=hairSurface(vec3(p*.001,-5),uv,n,hairDiffuseLookup(uv),generate_normal!=0,preview,variation);
    frag_color=vec4((output_normal!=0 ? n : t)*.5+.5,preview.r);
}
''')
    gpu.uniform(surface,'hair_object',1)
    gpu.uniform(surface,'hair_flow',1,2,.75)
    gpu.uniform(surface,'hair_debug',2,integer=True)
    gpu.uniform(surface,'uv_scale',.0001,.0001)
    for size in ((128,128),(256,128)):
        gpu.uniform(surface,'texture_size',*size)
        for degrees in (0,30,60,90,120,150):
            a=math.radians(degrees)
            gpu.uniform(surface,'offset',.3*math.cos(a),.3*math.sin(a))
            c=pixel(surface)
            t=[(v-.5)*2 for v in c[:3]]
            check(abs(-t[0]*math.sin(a)+t[1]*math.cos(a))>.98 and c[3]>.9,
                ('direction follows curved strands locally',size,degrees,c))
    gpu.uniform(surface,'offset',.3,0)
    gpu.uniform(surface,'uv_scale',-.0001,.0001)
    check(pixel(surface)[1]>.99,'mirrored UVs preserve the strand axis')
    gpu.uniform(surface,'hair_flow',0,2,.75)
    gpu.uniform(surface,'hair_direction',math.pi/2)
    check(pixel(surface)[0]<.001,'manual fallback remains adjustable')
    gpu.uniform(surface,'hair_direction',0)
    gpu.uniform(surface,'output_normal',1,integer=True)
    gpu.uniform(surface,'hair_detail',1,1,0)
    check(pixel(surface)[:3]==[.5,.5,1],'authored normals bypass extraction')
    gpu.uniform(surface,'generate_normal',1,integer=True)
    check(abs(pixel(surface)[0]-.5)>.01,'normal strength enables extracted detail')
    gpu.uniform(surface,'hair_detail',0,1,0)
    check(pixel(surface)[:3]==[.5,.5,1],'zero strength disables extracted detail')
    gpu.uniform(lighting,'hair_flow',1,2,.75)
    for degrees in range(0,180,30):
        a=math.radians(degrees)
        t=(math.cos(a),math.sin(a),0)
        positive=response(light=(.6,0,.8),tangent=t)
        negative=response(light=(.6,0,.8),tangent=tuple(-v for v in t))
        check(max(abs(x-y) for x,y in zip(positive,negative))<.00001,'automatic line axis has no root/tip lighting seams')
    gpu.uniform(lighting,'hair_flow',0,2,.75)

    # Actual alpha programs, sorted and OIT, must preserve coverage while sharing lighting.
    util = read('class1/deferred/deferredUtil.glsl')
    common = 'uniform int classic_mode;\n' + STUBS + function(util,'void calcHalfVectors(') + function(util,'float calcLegacyDistanceAttenuation(')
    common += function(read('class1/deferred/globalF.glsl'),'float filterPBRRoughness(')
    common += read('class1/deferred/sssOverlayUtil.glsl')
    punctual = util[util.index('bool hasAlphaProjector('):util.index('vec3 pbrCalcPointLightOrSpotLight(')]
    punctual += function(util,'vec3 pbrCalcPointLightOrSpotLight(')
    # Give the derivative quad a real UV/position basis while testing one fixed center pixel.
    vertex = VERTEX.replace('vary_position=test_position;',
        'vary_position=test_position+vec3((corners[gl_VertexID]*.5+.5-vec2(48.5/96.0,32.5/64.0))*.1,0);')
    vertex = vertex.replace('vec2(0.5);','corners[gl_VertexID]*.5+.5;')
    albedo = gpu.texture([.1,.04,.015,.4]*(W*H))
    normal = gpu.texture([.5,.5,1,1]*(W*H))
    orm = gpu.texture([1,.5,0,.5]*(W*H))
    strand_texels=[c for y in range(H) for x in range(W)
        for c in (*[b*(.5+.5*math.cos(2*math.pi*(x-W//2)/16)) for b in (.1,.04,.015)],.4)]
    patterned=gpu.texture(strand_texels)
    expected_finish=strand_finish([.1,.1,.1,.05,.05],coverage=.4,footprint=1)
    opaque_vertex='out vec3 vary_mat0, vary_mat1, vary_mat2;\n'+vertex.replace('gl_Position=',
        'vary_mat0=vec3(1,0,0);vary_mat1=vec3(0,1,0);vary_mat2=vec3(0,0,1);gl_Position=')
    packing_helper='uniform float sss_object, ssgi_avatar;\n'+function(read('class1/deferred/globalF.glsl'),'vec4 encodeNormal(')
    gbuffer=[gpu.texture() for _ in range(4)]
    for entry in ('diffuseF','diffuseIndexedF','diffuseAlphaMaskF','diffuseAlphaMaskIndexedF','bumpF','pbropaqueF','materialF'):
        path=('class3' if entry=='materialF' else 'class1')+'/deferred/'+entry+'.glsl'
        indexed=('uniform sampler2D diffuseMap;\nvec4 diffuseLookup(vec2 uv){return texture(diffuseMap,uv);}\n'
            'vec2 diffuseLookupSize(){return vec2(textureSize(diffuseMap,0));}\n') if 'Indexed' in entry else ''
        prog=program(indexed+read(path),opaque_vertex,[common+packing_helper],
            '#define USE_DIFFUSE_TEX 1\n#define USE_VERTEX_COLOR 1\n#define DIFFUSE_ALPHA_MODE 2\n')
        for unit,(name,tex) in enumerate((('diffuseMap',patterned),('bumpMap',normal),('specularMap',orm))):
            gpu.bind(prog,name,unit,tex)
        gpu.uniform(prog,'test_position',0,0,-5)
        gpu.uniform(prog,'test_normal_length',1)
        gpu.uniform(prog,'hair_object',1)
        gpu.uniform(prog,'roughnessFactor',1)
        gpu.uniform(prog,'metallicFactor',1)
        for i,tex in enumerate(gbuffer): gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT+i,TEXTURE,tex,0)
        gl.DrawBuffers(4,(U*4)(*(COLOR_ATTACHMENT+i for i in range(4))))
        gl.UseProgram(prog); gl.DrawArrays(4,0,3)
        for i in range(1,4): gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT+i,TEXTURE,0,0)
        gl.DrawBuffers(1,(U*1)(COLOR_ATTACHMENT))
        packed=gpu.read(gbuffer[1])[middle:middle+4]
        check(abs(packed[3]-expected_finish)<.001,(entry,'opaque/masked finish survives G-buffer packing',packed,expected_finish))
        if entry=='pbropaqueF': check(packed[:3]==[1,.5,0],'hair finish preserves PBR occlusion and material channels')
    samples = []
    varied_samples = []
    compensated_samples = []
    for name,path in [('alpha','class2/deferred/alphaF.glsl'),('material','class3/deferred/materialF.glsl'),('pbr','class2/deferred/pbralphaF.glsl')]:
        for oit in (False,True):
            defines='#define USE_DIFFUSE_TEX 1\n#define USE_VERTEX_COLOR 1\n#define DIFFUSE_ALPHA_MODE 1\n'
            if oit: defines+='#define EXACT_OIT 1\n'
            prog = program(read(path), vertex, [common+(punctual if name=='pbr' else ''),
                read('class1/deferred/projectorUtil.glsl')], defines)
            for unit,(tex_name,tex) in enumerate([('diffuseMap',albedo),('bumpMap',normal),('specularMap',orm)]):
                gpu.bind(prog,tex_name,unit,tex)
            gpu.uniform(prog,'test_position',0,0,-5)
            gpu.uniform(prog,'test_normal_length',1)
            gpu.uniform(prog,'hair_object',1)
            gpu.uniform(prog,'hair_flow',1,2,.75)
            gpu.uniform(prog,'hair_detail',.35,1,1)
            gpu.uniform(prog,'hair_params',.35,.7,.5,1)
            gpu.uniform(prog,'light_position[2]',0,0,0,1)
            gpu.uniform(prog,'light_attenuation[2]',.9,1.5,1,0)
            gpu.uniform(prog,'light_deferred_attenuation[2]',10,.5)
            gpu.uniform(prog,'light_diffuse[2]',1,1,1)
            c = pixel(prog)
            check(abs(c[3]-.24)<.001, (name,oit,'coverage',c))
            samples.append(c)
            gpu.uniform(prog,'hair_brightness_compensation',1)
            compensated=pixel(prog)
            compensated_samples.append(compensated)
            check(compensated[0]<c[0] and compensated[3]==c[3],
                (name,oit,'dark-hair compensation reduces highlights without changing coverage'))
            gpu.uniform(prog,'hair_brightness_compensation',0)
            check(pixel(prog)==c,(name,oit,'zero brightness compensation restores the original rendering'))
            gpu.uniform(prog,'hair_object',0)
            ordinary=pixel(prog)
            gpu.uniform(prog,'hair_brightness_compensation',2)
            check(pixel(prog)==ordinary,(name,oit,'brightness compensation only affects tagged hair'))
            gpu.uniform(prog,'hair_object',1)
            gpu.uniform(prog,'hair_brightness_compensation',0)
            gpu.bind(prog,'diffuseMap',0,patterned)
            gpu.uniform(prog,'hair_detail',0,1,1)
            varied=pixel(prog)
            varied_samples.append(varied)
            check(abs(varied[3]-.24)<.001 and abs(varied[0]-c[0])>.0001,
                (name,oit,'texture finish works without generated normals and preserves coverage',varied,c))
            gpu.uniform(prog,'hair_variation_strength',0)
            uniform_finish=pixel(prog)
            check(max(abs(a-b) for a,b in zip(c,uniform_finish))<.001,
                (name,oit,'zero strength restores uniform finish and original alpha',uniform_finish,c))
            gpu.uniform(prog,'hair_variation_strength',1)
            gpu.bind(prog,'diffuseMap',0,albedo)
            gpu.uniform(prog,'hair_debug',2,integer=True)
            preview=pixel(prog)
            check(preview[:3]==[0,0,0] and abs(preview[3]-.24)<.001,
                (name,oit,'confidence preview preserves alpha coverage',preview))
            gpu.uniform(prog,'hair_debug',0,integer=True)
            gpu.uniform(prog,'minimum_alpha',.5)
            gl.ClearColor(0,0,0,0); gl.Clear(0x4000)
            # Ordinary blended materials do not alpha-test unless their shader requires it.
            if name=='alpha': check(pixel(prog)==[0,0,0,0],'transparent texels remain discarded')
    for c in samples[1:]:
        check(max(abs(a-b) for a,b in zip(samples[0],c))<.001,'legacy/material/PBR and OIT parity')
    for c in varied_samples[1:]:
        check(max(abs(a-b) for a,b in zip(varied_samples[0],c))<.001,'strand finish agrees across forward materials and OIT')
    for c in compensated_samples[1:]:
        check(max(abs(a-b) for a,b in zip(compensated_samples[0],c))<.001,'brightness compensation agrees across forward materials and OIT')

    # Exercise each real deferred light entry point with the same inputs as forward hair.
    deferred_stubs = DEFERRED_STUBS.replace('vec4(test_normal, test_flag)', 'vec4(.5,.5,.75,test_flag)')
    deferred_stubs = deferred_stubs.replace('vec4 decodeNormal(vec4 n) { return n; }',
        'vec4 decodeNormal(vec4 n) { return vec4(test_normal,n.w); }')
    deferred_stubs = deferred_stubs.replace('float calcLegacyDistanceAttenuation(float d, float f) { return 1.0; }',
        function(util,'float calcLegacyDistanceAttenuation('))
    deferred_stubs = 'uniform int classic_mode;\n' + deferred_stubs
    struct = 'struct GBufferInfo { vec4 albedo; vec4 specular; vec3 normal; vec4 emissive; float gbufferFlag; float envIntensity; float sss; };\n'
    common_deferred = [deferred_stubs] + [read('class1/deferred/'+name+'.glsl')
        for name in ('gbufferUtil','sssDepthUtil','shadowUtil')]
    opaque_albedo = gpu.texture([.1,.04,.015,0]*(W*H))
    for entry in ('softenLightF','pointLightF','multiPointLightF','spotLightF'):
        local = entry != 'softenLightF'
        vertex = ('out vec4 vary_fragcoord; out vec3 trans_center;\n' + gpu.vertex.replace('}',
            'vary_fragcoord=vec4(0,0,0,1); trans_center=vec3(0); }')) if entry in ('pointLightF','spotLightF') else (
            'out vec2 vary_fragcoord;\n' + gpu.vertex.replace('}', 'vary_fragcoord=vec2(.5); }'))
        prog = program(read('class3/deferred/'+entry+'.glsl'), vertex, common_deferred,
            '#define LIGHT_COUNT 1\n'+struct)
        gpu.bind(prog,'diffuseRect',0,opaque_albedo)
        gpu.bind(prog,'specularRect',1,orm)
        for i in range(6): gpu.uniform(prog,f'shadowMap{i}',10+i,integer=True)
        gpu.uniform(prog,'test_pos',0,0,-5)
        gpu.uniform(prog,'test_normal',0,0,1)
        gpu.uniform(prog,'hair_params',.35,.7,.5,1)
        gpu.uniform(prog,'sun_dir',0,0,1)
        gpu.uniform(prog,'sun_up_factor',1,integer=True)
        gpu.uniform(prog,'size',10)
        gpu.uniform(prog,'falloff',.5)
        gpu.uniform(prog,'color',1,1,1)
        gpu.uniform(prog,'light[0]',0,0,0,10)
        gpu.uniform(prog,'light_col[0]',1,1,1,.5)
        gpu.uniform(prog,'far_z',-100)
        gpu.uniform(prog,'proj_origin',0,0,0)
        gpu.uniform(prog,'proj_shadow_idx',-1,integer=True)
        for flag in (.22,.26,.55,.59):
            gpu.uniform(prog,'test_flag',flag)
            actual = pixel(prog)
            expected = [(v-.2)/.7 for v in samples[0][:3]] if local else response()[:3]
            check(max(abs(a-b) for a,b in zip(actual,expected))<.001,
                (entry,flag,'opaque/forward hair parity',actual,expected))
            gpu.uniform(prog,'hair_brightness_compensation',1)
            actual=pixel(prog)
            expected=[(v-.2)/.7 for v in compensated_samples[0][:3]] if local else response(brightness=1)[:3]
            check(max(abs(a-b) for a,b in zip(actual,expected))<.001,
                (entry,flag,'opaque/forward brightness compensation parity',actual,expected))
            gpu.uniform(prog,'hair_brightness_compensation',0)
        gpu.upload(orm,[1,.5,0,expected_finish]*(W*H))
        gpu.bind(prog,'specularRect',1,orm)
        actual=pixel(prog)
        expected=[(v-.2)/.7 for v in varied_samples[0][:3]] if local else response(variation=expected_finish)[:3]
        check(max(abs(a-b) for a,b in zip(actual,expected))<.001,
            (entry,'opaque/forward textured finish parity',actual,expected))
        gpu.upload(orm,[1,.5,0,.5]*(W*H))

    panel=ET.parse(ROOT/'indra/newview/skins/default/xui/en/panel_preferences_graphics1.xml')
    controls=panel.find('.//panel[@name="graphics_hair_panel"]')
    check(controls is not None,'Hair tab exists')
    names={node.get('control_name') for node in controls.iter() if node.get('control_name')}
    settings=ET.parse(ROOT/'indra/newview/app_settings/settings.xml')
    keys={node.text for node in settings.findall('./map/key')}
    check(len(names)==17 and names <= keys,'all Hair controls have settings')
    variation=controls.find('.//slider[@name="BoxxyHairStrandVariation"]')
    check(variation is not None and variation.get('min_val')=='0' and variation.get('max_val')=='2',
        'strand variation exposes its full supported range')
    values=list(settings.find('./map'))
    config=values[next(i for i,n in enumerate(values) if n.tag=='key' and n.text=='BoxxyHairStrandVariation')+1]
    pairs=dict(zip([n.text for n in list(config)[::2]],[n.text for n in list(config)[1::2]]))
    check(pairs['Value']=='1.0' and pairs['Persist']=='1','strand variation defaults to the existing look and persists')
    check('"BoxxyHairStrandVariation", {0, 2}' in (ROOT/'indra/newview/llviewerautomation_settings.inc').read_text(),
        'automation matches the slider range')
    check('"BoxxyHairStrandVariation"' in (ROOT/'indra/newview/llfloaterpreference.cpp').read_text(),
        'Hair defaults includes strand variation')
    brightness=controls.find('.//slider[@name="BoxxyHairBrightnessCompensation"]')
    check(brightness is not None and brightness.get('min_val')=='0' and brightness.get('max_val')=='4',
        'brightness compensation exposes the shader range')
    config=values[next(i for i,n in enumerate(values) if n.tag=='key' and n.text=='BoxxyHairBrightnessCompensation')+1]
    pairs=dict(zip([n.text for n in list(config)[::2]],[n.text for n in list(config)[1::2]]))
    check(pairs['Value']=='0.0' and pairs['Persist']=='1','brightness compensation preserves the existing appearance by default and persists')
    check('"BoxxyHairBrightnessCompensation", {0, 4}' in (ROOT/'indra/newview/llviewerautomation_settings.inc').read_text(),
        'brightness automation matches the slider bounds')
    check('"BoxxyHairBrightnessCompensation"' in (ROOT/'indra/newview/llfloaterpreference.cpp').read_text(),
        'graphics defaults reset brightness compensation')
    print(f'Passed {checks} hair GPU/config checks on {gl.GetString(0x1F01).decode()}')


if __name__ == '__main__':
    sdl, window, ctx, gl = context()
    try:
        run(sdl,gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
