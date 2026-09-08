"""Exercise production SSS depth/lighting shaders on the viewer's hidden GL harness.

Run: .venv/Scripts/python.exe scripts/tests/test_sss_shadow_gpu.py
Synthetic depths check distance reconstruction and actual sun/spot/point
composition with ordinary shadows both enabled and disabled. This does not measure in-world appearance or frame time.
"""

import ctypes as C
import math
from pathlib import Path

from test_exact_oit_gpu import context, U, I, F, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT, RGBA, FLOAT

ROOT = Path(__file__).resolve().parents[2]
SHADERS = ROOT / "indra/newview/app_settings/shaders"
PREAMBLE = """
#define GBUFFER_FLAG_SKIP_ATMOS 0.0
#define GBUFFER_FLAG_HAS_PBR 0.67
#define GBUFFER_FLAG_HAS_HDRI 1.0
#define GBUFFER_SSS_FLAG(d) ((abs((d)-0.46)<0.025 || abs((d)-0.79)<0.025) ? 1.0 : 0.0)
#define GET_GBUFFER_FLAG(d,f) (abs((d)-0.12*GBUFFER_SSS_FLAG(d)-(f))<0.1)
struct GBufferInfo { vec4 albedo; vec4 specular; vec3 normal; vec4 emissive;
    float gbufferFlag; float envIntensity; float sss; };
"""

# Controlled inputs around the production lighting and transmission code.
STUBS = """
uniform vec3 test_pos, test_normal;
uniform vec3 test_surface_dx, test_surface_dy;
uniform float test_flag;
vec4 getNormRaw(vec2 tc) { return vec4(test_normal, test_flag); }
vec4 decodeNormal(vec4 n) { return n; }
float getDepth(vec2 tc) { return 0.5; }
vec4 getPosition(vec2 tc) { return vec4(test_pos + test_surface_dx*(gl_FragCoord.x-0.5) + test_surface_dy*(gl_FragCoord.y-0.5),1); }
vec4 getPositionWithDepth(vec2 tc, float d) { return getPosition(tc); }
vec3 srgb_to_linear(vec3 c) { return c; }
vec3 linear_to_srgb(vec3 c) { return c; }
vec3 clampHDRRange(vec3 c) { return c; }
void calcAtmosphericVarsLinear(vec3 p, vec3 n, vec3 l,
    out vec3 sun, out vec3 amb, out vec3 atten, out vec3 additive)
{ sun=vec3(1); amb=vec3(0); atten=vec3(1); additive=vec3(0); }
void sampleReflectionProbes(inout vec3 a, inout vec3 g,
    vec2 tc, vec3 p, vec3 n, float gloss, bool t, vec3 amb) {}
void sampleReflectionProbesLegacy(inout vec3 a, inout vec3 g, inout vec3 e,
    vec2 tc, vec3 p, vec3 n, float gloss, float env, bool t, vec3 amb) {}
void applyGlossEnv(inout vec3 c, vec3 g, vec4 s, vec3 p, vec3 n) {}
void applyLegacyEnv(inout vec3 c, vec3 e, vec4 s, vec3 p, vec3 n, float i) {}
void calcDiffuseSpecular(vec3 b, float m, inout vec3 d, inout vec3 s)
{ d=b*(1.0-m); s=vec3(0); }
void pbrIbl(vec3 d, vec3 s, vec3 r, vec3 irr, float ao, float nv, float rough,
    out vec3 diffuseOut, out vec3 specularOut) { diffuseOut=vec3(0); specularOut=vec3(0); }
void pbrPunctual(vec3 d, vec3 s, float rough, float m, vec3 n, vec3 v, vec3 l,
    out float nl, out vec3 diff, out vec3 spec)
{ nl=max(dot(n,l),0.0); diff=d/3.14159265; spec=vec3(0); }
vec3 pbrBaseLight(vec3 d, vec3 s, float m, vec3 p, vec3 n, float rough,
    vec3 l, vec3 sun, float shadow, vec3 rad, vec3 irr, vec3 e, float ao,
    vec3 additive, vec3 atten) { return max(dot(n,l),0.0)*d*shadow; }
vec2 getScreenCoord(vec4 clip) { return vec2(0.5); }
float calcLegacyDistanceAttenuation(float d, float f) { return 1.0; }
bool clipProjectedLightVars(vec3 c, vec3 p, out float d, out float ld,
    out vec3 lv, out vec4 tc) { d=0.5; ld=1; lv=-p; tc=vec4(0.5,0.5,0.5,1); return false; }
void calcHalfVectors(vec3 lv, vec3 n, vec3 v, out vec3 h, out vec3 l,
    out float nh, out float nl, out float nv, out float vh, out float ld)
{ l=normalize(lv); h=normalize(l+v); nh=dot(n,h); nl=max(dot(n,l),0.0);
  nv=dot(n,v); vh=dot(v,h); ld=length(lv); }
vec3 getProjectedLightDiffuseColor(float d, vec2 tc) { return vec3(1); }
vec3 getProjectedLightAmbiance(float a, float atten, float lit, float nl, float noise, vec2 tc)
{ return vec3(0); }
vec4 texture2DLodSpecular(vec2 tc, float lod) { return vec4(0); }
"""

PROBE = """
uniform vec3 test_pos, test_light;
uniform vec3 test_surface_dx, test_surface_dy;
uniform int test_index;
uniform float test_shadow;
void prepareSSSDepth(vec3 pos);
bool useSSSShadowThickness(float nl, float strength);
float sampleDirectionalSSSPath(vec3 p);
float sampleFocusedSunSSSPath(vec3 p, vec3 l);
float sampleSpotSSSPath(vec3 p, vec3 l, int index);
vec3 getSSSTransmissionWithDepth(float nl, float nv, float strength, float path, float shadow);
out vec4 frag_color;
void main() {
    prepareSSSDepth(test_pos + test_surface_dx*(gl_FragCoord.x-0.5) + test_surface_dy*(gl_FragCoord.y-0.5));
    float path=-1.0;
    if (useSSSShadowThickness(-1.0, 0.9))
        path=test_index == -3 ? sampleFocusedSunSSSPath(test_pos,test_light) :
             test_index == -2 ? sampleDirectionalSSSPath(test_pos) :
                               sampleSpotSSSPath(test_pos, test_light, test_index);
    frag_color=vec4(getSSSTransmissionWithDepth(-1.0, 1.0, 0.9, path, test_shadow),path);
}
"""


def run(sdl, gl):
    for name, args in {"Clear": [U], "Uniform3f": [I, F, F, F], "Uniform4f": [I, F, F, F, F],
                       "DeleteProgram": [U], "ActiveTexture": [U], "ReadBuffer": [U],
                       "DrawBuffers": [I, C.POINTER(U)],
                       "UniformMatrix4fv": [I, I, C.c_ubyte, C.POINTER(F)]}.items():
        setattr(gl, name, C.WINFUNCTYPE(None, *args)(sdl.SDL_GL_GetProcAddress(("gl" + name).encode())))

    def obj(generator):
        value = U()
        generator(1, C.byref(value))
        return value.value

    def uniform(prog, name, *values, integer=False):
        loc = gl.GetUniformLocation(prog, name.encode())
        getattr(gl, "Uniform1i" if integer else f"Uniform{len(values)}f")(loc, *values)

    def matrix(prog, name, rows):
        values = (F * 16)(*(rows[r][c] for c in range(4) for r in range(4)))
        gl.UniformMatrix4fv(gl.GetUniformLocation(prog, name.encode()), 1, 0, values)

    def program(fragment, flags, spot=False):
        vertex = "out vec4 vary_fragcoord; out vec3 trans_center;" if spot else "out vec2 vary_fragcoord;"
        vertex += "void main() { vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3)); gl_Position=vec4(p[gl_VertexID],0,1);"
        vertex += "vary_fragcoord=vec4(0,0,0,1); trans_center=vec3(0); }" if spot else "vary_fragcoord=vec2(0.5); }"
        result = gl.CreateProgram()
        for kind, source in [(0x8B31, vertex), (0x8B30, fragment), (0x8B30, STUBS)] + [
            (0x8B30, (SHADERS / f"class1/deferred/{name}.glsl").read_text())
            for name in ("gbufferUtil", "sssDepthUtil", "shadowUtil")
        ]:
            shader = gl.CreateShader(kind)
            source = C.c_char_p(("#version 430 core\n" + flags + PREAMBLE + source).encode())
            gl.ShaderSource(shader, 1, C.byref(source), None)
            gl.CompileShader(shader)
            ok, log = I(), C.create_string_buffer(16384)
            gl.GetShaderiv(shader, 0x8B81, C.byref(ok))
            gl.GetShaderInfoLog(shader, len(log), None, log)
            assert ok.value, log.value.decode()
            gl.AttachShader(result, shader)
            gl.DeleteShader(shader)
        gl.LinkProgram(result)
        gl.GetProgramiv(result, 0x8B82, C.byref(ok))
        gl.GetProgramInfoLog(result, len(log), None, log)
        assert ok.value, log.value.decode()
        gl.UseProgram(result)
        for name, unit in (("diffuseRect",0), ("specularRect",2), ("lightMap",3)):
            uniform(result, name, unit, integer=True)
        for i in range(6):
            uniform(result, f"shadowMap{i}", 4+i, integer=True)
        for i in range(3):
            uniform(result, f"sssDepthMap{i}", 10+i, integer=True)
        uniform(result, "sss_params", 0.9, 2, 0.75, 44)
        uniform(result, "sss_lighting", 0, 0.4, 8.5)
        uniform(result, "sss_penetration", 0.08)
        uniform(result, "sss_clamp_knee", 0.004)
        uniform(result, "sss_shadow_thickness", 1, integer=True)
        uniform(result, "sun_dir", 0, 0, 1)
        uniform(result, "moon_dir", 0, 0, 1)
        uniform(result, "sun_up_factor", 1, integer=True)
        uniform(result, "shadow_clip", 8, 16, 32, 64)
        uniform(result, "test_normal", 0, 0, -1)
        uniform(result, "test_light", 0, 0, 1)
        uniform(result, "test_shadow", 0.3)
        return result

    def color_texture(unit, values):
        gl.ActiveTexture(0x84C0 + unit)
        tex = obj(gl.GenTextures)
        gl.BindTexture(TEXTURE, tex)
        gl.TexParameteri(TEXTURE, 0x2801, 0x2600)
        gl.TexParameteri(TEXTURE, 0x2800, 0x2600)
        gl.TexImage2D(TEXTURE, 0, 0x8814, 1, 1, 0, RGBA, FLOAT, (F*4)(*values))
        return tex

    gl.BindVertexArray(obj(gl.GenVertexArrays))
    gl.BindFramebuffer(FRAMEBUFFER, obj(gl.GenFramebuffers))
    for i in range(3):
        target = color_texture(0, [0,0,0,0])
        gl.FramebufferTexture2D(FRAMEBUFFER, COLOR_ATTACHMENT+i, TEXTURE, target, 0)
    gl.DrawBuffers(3, (U*3)(COLOR_ATTACHMENT, COLOR_ATTACHMENT+1, COLOR_ATTACHMENT+2))
    assert gl.CheckFramebufferStatus(FRAMEBUFFER) == 0x8CD5
    color_texture(0, [1,1,1,0])
    color_texture(2, [0,0.5,0,0])
    color_texture(3, [0,1,0,0]) # completely shadowed sun and both spotlights
    for i in range(9):
        gl.ActiveTexture(0x84C0+4+i)
        gl.BindTexture(TEXTURE, obj(gl.GenTextures))
        gl.TexParameteri(TEXTURE, 0x2801, 0x2601) # linear comparisons, as in the viewer
        gl.TexParameteri(TEXTURE, 0x2800, 0x2601)
        gl.TexParameteri(TEXTURE, 0x884C, 0x884E if i < 6 else 0)
        gl.TexParameteri(TEXTURE, 0x884D, 0x0203)
    gl.Viewport(0, 0, 1, 1)

    def setup_depth(prog, thickness, perspective=False, z=-5, slot_depths=None):
        rows = [[1,0,0,0.5], [0,1,0,0.5], [0,0,-1,0.5+z], [0,0,0,1]]
        if perspective:
            rows = [[1,0,-0.5,0], [0,1,-0.5,0], [0,0,-10/9,-10/9], [0,0,-1,0]]
        for i in range(9):
            matrix(prog, f"shadow_matrix[{i}]" if i < 6 else f"sss_depth_matrix[{i-6}]", rows)
            t = thickness if slot_depths is None else slot_depths[min(i,len(slot_depths)-1)]
            entry_z = z + t
            d = (rows[2][2]*entry_z + rows[2][3]) / (rows[3][2]*entry_z + rows[3][3])
            gl.ActiveTexture(0x84C0+4+i)
            gl.TexImage2D(TEXTURE, 0, 0x8CAC, 1, 1, 0, 0x1902, FLOAT, (F*1)(d))
        uniform(prog, "test_pos", 0, 0, z)

    def pixel(attachment=0):
        gl.Clear(0x4000)
        gl.DrawArrays(0x0004, 0, 3)
        gl.ReadBuffer(COLOR_ATTACHMENT+attachment)
        value = (F*4)()
        gl.ReadPixels(0, 0, 1, 1, RGBA, FLOAT, value)
        assert all(math.isfinite(v) for v in value), tuple(value)
        return tuple(value)

    flags = "#define SUN_SHADOW 1\n#define SPOT_SHADOW 1\n#define HAS_SUN_SHADOW 1\n"
    prog = program(PROBE, flags)
    checks = 0
    for index in (-2,0,1):
        uniform(prog, "test_index", index, integer=True)
        for perspective in (False, True):
            reds = []
            for thickness in (0.002,0.008,0.03,0.06,0.12,0.25):
                setup_depth(prog, thickness, perspective)
                value = pixel()
                expected = min(thickness,0.08)
                assert abs(value[3]-expected) < 0.00008, (index,perspective,thickness,value)
                if thickness >= 0.08:
                    assert value[0] == 0, value
                reds.append(value[0])
                checks += 1
            assert reds == sorted(reds, reverse=True), reds
    # Small light-map UV shifts must not switch instantly between thin tissue
    # and an adjacent opaque blocker, with either nearest or linear map filtering.
    uniform(prog, "test_index", 0, integer=True)
    for perspective in (False, True):
        for filtering, boundary in ((0x2600, 0.5), (0x2601, 0.2505)):
            setup_depth(prog, 0.008, perspective)
            gl.ActiveTexture(0x84C0+8) # spotlight shadowMap4
            gl.TexParameteri(TEXTURE, 0x2801, filtering)
            gl.TexParameteri(TEXTURE, 0x2800, filtering)
            def entry_depth(path):
                z=-5+path
                return ((-10/9)*z-10/9)/(-z) if perspective else -z-4.5
            gl.TexImage2D(TEXTURE, 0, 0x8CAC, 2, 2, 0, 0x1902, FLOAT,
                          (F*4)(entry_depth(0.008),entry_depth(0.25),entry_depth(0.008),entry_depth(0.25)))
            def phase(uv):
                rows = [[1,0,-uv,0],[0,1,-0.5,0],[0,0,-10/9,-10/9],[0,0,-1,0]] if perspective else \
                       [[1,0,0,uv],[0,1,0,0.5],[0,0,-1,-4.5],[0,0,0,1]]
                matrix(prog, "shadow_matrix[4]", rows)
                return pixel()
            colors=[phase(uv)[0] for uv in (boundary-0.0001,boundary+0.0001)]
            assert abs(colors[0]-colors[1]) < 0.001, ("micro-movement transmission jump",perspective,filtering,colors)
            checks += 1
            # Both filter modes must reconstruct the same continuous path ramp.
            for uv in (0.25,0.375,0.5,0.625,0.75):
                f=(uv-0.25)*2
                expected_path=0.008*(1-f)+0.08*f
                assert abs(phase(uv)[3]-expected_path)<0.00008, (perspective,filtering,uv,phase(uv))
                checks += 1
    # Sloping receiver/entry planes: neighboring texel depths must not turn the
    # receiver's own slope into a thin-tissue hotspot. True thin layers survive.
    uniform(prog,"sss_depth_valid",1,1,1)
    uniform(prog,"sss_depth_focus",0,0,-5,2.5)
    for path_index in (0,-3):
        uniform(prog,"test_index",path_index,integer=True)
        uniform(prog,"test_light",0,0,-1) # physical entry behind the visible receiver
        for perspective, near in ((False,1.0),(True,1.0),(True,0.01)):
            a,b = 10/(10-near),10*near/(10-near)
            slope_scale = b/(10/9) if perspective else 1.0
            for filtering in (0x2600,0x2601):
                for u in (0.26,0.3,0.49,0.68,0.74):
                    for thickness in (0.0,0.004):
                        setup_depth(prog,thickness,perspective)
                        uniform(prog,"test_surface_dx",0.01,0,0.0009 if perspective else 0.0002)
                        uniform(prog,"test_surface_dy",0,0.01,0.00135 if perspective else 0.0003)
                        rows = [[1,0,-u,0],[0,1,-0.3,0],[0,0,-a,-b],[0,0,-1,0]] if perspective else \
                               [[1,0,0,u],[0,1,0,0.3],[0,0,-1,-4.5],[0,0,0,1]]
                        rows=[[row[0],row[1],-row[2],row[3]-10*row[2]] for row in rows]
                        matrix(prog,"shadow_matrix[4]" if path_index==0 else "sss_depth_matrix[0]",rows)
                        z=-5+thickness
                        depth=(-a*z-b)/(-z) if perspective else -z-4.5
                        depths=[depth+slope_scale*(0.02*(x-u)+0.03*(y-0.3)) for y in (0.25,0.75) for x in (0.25,0.75)]
                        gl.ActiveTexture(0x84C0+(8 if path_index==0 else 10))
                        gl.TexParameteri(TEXTURE,0x2801,filtering)
                        gl.TexParameteri(TEXTURE,0x2800,filtering)
                        gl.TexImage2D(TEXTURE,0,0x81A6 if near<1 else 0x8CAC,2,2,0,0x1902,FLOAT,(F*4)(*depths))
                        result=pixel()
                        if thickness==0:
                            assert result[0]==0, ("sloping self-surface hotspot",perspective,filtering,u,result)
                        else:
                            tolerance=0.0008 if near<1 else 0.0001
                            assert abs(result[3]-thickness)<tolerance, ("sloping thin layer lost",perspective,near,u,result)
                        checks+=1
    uniform(prog,"test_surface_dx",0,0,0)
    uniform(prog,"test_surface_dy",0,0,0)
    uniform(prog,"test_light",0,0,1)
    uniform(prog,"test_index",0,integer=True)
    # The self-depth rejection must ease into valid transmission, rather than
    # jump from opaque to full brightness at the half-millimeter threshold.
    ramp=[]
    for thickness in (0.00049,0.00051,0.0007,0.00085,0.001):
        setup_depth(prog,thickness)
        ramp.append(pixel()[0])
    assert max(ramp[:2])<1e-6, ramp
    assert ramp==sorted(ramp), ramp
    assert 0<ramp[3]<ramp[4], ramp
    checks+=3
    setup_depth(prog, 0.008)
    # Invalid entries must not become bright zero-thickness surfaces.
    for thickness in (-0.1,0):
        setup_depth(prog, thickness)
        assert pixel()[0] == 0
        checks += 1
    uniform(prog, "test_index", -2, integer=True)
    uniform(prog, "shadow_clip", 4,8,16,32)
    setup_depth(prog, 0, z=-4, slot_depths=[0.01,0.03,0.03,0.03,0.03,0.03])
    assert abs(pixel()[3]-0.02) < 0.00008
    checks += 1
    # Off, missing spotlight slot, and disabled shadow permutations use the old response.
    expected = math.exp(-0.165*8.5)*0.9*0.4*0.3
    uniform(prog, "sss_shadow_thickness", 0, integer=True)
    assert abs(pixel()[0]-expected) < 1e-6
    uniform(prog, "sss_shadow_thickness", 1, integer=True)
    uniform(prog, "test_index", -1, integer=True)
    assert abs(pixel()[0]-expected) < 1e-6
    gl.DeleteProgram(prog)
    for defines in ("", "#define SUN_SHADOW 1\n"):
        prog = program(PROBE, defines)
        uniform(prog, "test_index", 0, integer=True)
        setup_depth(prog,0.005)
        assert abs(pixel()[0]-expected) < 1e-6
        gl.DeleteProgram(prog)
    checks += 4

    # The debug overlay must display measured paths independently of lighting,
    # and distinguish missing coverage from a valid opaque measurement.
    prog = program((SHADERS / "class1/deferred/sssMaskF.glsl").read_text(), "")
    uniform(prog, "test_flag", 0.46)
    uniform(prog, "sss_debug_depth", 1, integer=True)
    uniform(prog, "sss_debug_sun", 0, 0, 1)
    uniform(prog, "sss_depth_focus", 0, 0, -5, 2.5)
    uniform(prog, "sss_depth_origin[0]", 0, 0, 0)
    uniform(prog, "sss_depth_origin[1]", 0, 0, 1)
    for light in range(3):
        uniform(prog, "sss_debug_light", light, integer=True)
        uniform(prog, "sss_depth_valid", 1, 1, 1)
        for thickness in (0.004, 0.04, 0.08):
            setup_depth(prog, thickness)
            actual = pixel()
            expected_gray = 1-thickness/0.08
            assert all(abs(c-expected_gray)<0.0001 for c in actual[:3]), actual
            assert actual[3] == 1
            checks += 1
        valid = [1,1,1]; valid[light] = 0
        uniform(prog, "sss_depth_valid", *valid)
        assert pixel() == (1.0,0.0,1.0,1.0)
        checks += 1
    uniform(prog, "sss_debug_light", 0, integer=True)
    uniform(prog, "sss_depth_valid", 1, 1, 1)
    setup_depth(prog,0.004)
    uniform(prog,"sss_minimum_thickness",0.008)
    assert all(abs(c-(1-0.008/0.08))<1e-6 for c in pixel()[:3]), "Depth debug omits soft clamp"
    uniform(prog,"sss_minimum_thickness",0)
    checks+=1
    uniform(prog, "sss_debug_light", 3, integer=True)
    uniform(prog, "diffuseMap", 1, integer=True)
    color_texture(1, [0.23,0.07,0.012,0])
    uniform(prog, "sss_debug_captured", 1, integer=True)
    assert all(abs(a-b)<1e-6 for a,b in zip(pixel(), (0.23,0.07,0.012,1)))
    uniform(prog, "sss_debug_captured", 0, integer=True)
    assert pixel() == (0.0,0.0,0.0,1.0)
    checks += 2
    uniform(prog, "sss_debug_depth", 0, integer=True)
    assert all(abs(a-b)<1e-6 for a,b in zip(pixel(), (1,0,0.6,0.8)))
    checks += 1
    gl.DeleteProgram(prog)

    for name in ("softenLightF", "spotLightF"):
        for multi in ((False,True) if name == "spotLightF" else (False,)):
            source = (SHADERS / f"class3/deferred/{name}.glsl").read_text()
            for defines in ("",flags):
                prog = program(source, defines + ("#define MULTI_SPOTLIGHT 1\n" if multi else ""), name == "spotLightF")
                for flag in (0.46,0.79):
                    uniform(prog,"test_flag",flag)
                    for classic in (0,1):
                        uniform(prog,"classic_mode",classic,integer=True)
                        uniform(prog,"proj_shadow_idx",0,integer=True)
                        uniform(prog,"shadow_fade",0)
                        uniform(prog,"sss_shadow_thickness",1,integer=True)
                        setup_depth(prog,0.005)
                        thin = pixel()[0]
                        assert abs(thin-pixel(1)[0]) < 1e-6, "Transmission missing from diffusion buffer"
                        setup_depth(prog,0.25)
                        thick = pixel()[0]
                        if defines:
                            assert thin > 0.01 and thick == 0, (name,multi,flag,classic,thin,thick)
                        else:
                            assert thin == thick, (name,thin,thick)
                        setup_depth(prog,0.005)
                        uniform(prog,"sss_shadow_thickness",0,integer=True)
                        old = pixel()[0]
                        if defines or name == "spotLightF":
                            assert old == 0, (name,"toggle",old)
                        checks += 1
                        # Directly lit surfaces must not change with the depth toggle.
                        uniform(prog,"test_normal",0,0,1)
                        before = pixel()
                        uniform(prog,"sss_shadow_thickness",1,integer=True)
                        assert pixel() == before, (name,"front lighting changed")
                        uniform(prog,"test_normal",0,0,-1)
                        checks += 1
                        if name == "spotLightF" and defines:
                            uniform(prog,"shadow_fade",1)
                            faded = pixel()
                            uniform(prog,"sss_shadow_thickness",0,integer=True)
                            assert max(abs(a-b) for a,b in zip(pixel(),faded)) < 1e-6
                            checks += 1
                gl.DeleteProgram(prog)
    # A valid focused map must be independent of camera-driven ordinary cascade
    # depths, projector slot selection, and shadow-slot fades.
    for name in ("softenLightF", "spotLightF"):
        prog = program((SHADERS / f"class3/deferred/{name}.glsl").read_text(),
                       flags, spot=name == "spotLightF")
        uniform(prog,"sss_depth_valid",1,1,1)
        uniform(prog,"sss_depth_focus",0,0,-5,2.5)
        for flag in (0.46,0.79):
            uniform(prog,"test_flag",flag)
            setup_depth(prog,0.005)
            baseline = pixel()
            assert baseline[0] > 0.01
            for depth, index, fade in ((0.25,0,0), (0.002,1,0.5), (0.06,-1,1)):
                setup_depth(prog,0.005,slot_depths=[depth]*6+[0.005]*3)
                uniform(prog,"proj_shadow_idx",index,integer=True)
                uniform(prog,"shadow_fade",fade)
                assert pixel() == baseline, (name,"ordinary shadow changed focused transmission")
                checks += 1
        gl.DeleteProgram(prog)
    # Point lights share the optical helper but must retain their existing fallback.
    for name in ("pointLightF", "multiPointLightF"):
        prog = program((SHADERS / f"class3/deferred/{name}.glsl").read_text(),
                       flags + "#define LIGHT_COUNT 1\n", spot=True)
        uniform(prog,"color",1,1,1)
        uniform(prog,"size",10)
        uniform(prog,"far_z",-100)
        uniform(prog,"light_count",1,integer=True)
        uniform(prog,"light[0]",0,0,0,10)
        uniform(prog,"light_col[0]",1,1,1,0.5)
        for flag in (0.46,0.79):
            uniform(prog,"test_flag",flag)
            setup_depth(prog,0.005)
            uniform(prog,"sss_shadow_thickness",1,integer=True)
            before = pixel()
            assert before[0] > 0.01, (name,"point transmission lost",before)
            setup_depth(prog,0.25)
            uniform(prog,"sss_shadow_thickness",0,integer=True)
            assert pixel() == before, (name,"point response changed")
            checks += 1
        gl.DeleteProgram(prog)
    # Independent maps: production shaders without any ordinary shadow defines.
    for name in ("softenLightF", "spotLightF", "pointLightF", "multiPointLightF"):
        prog = program((SHADERS / f"class3/deferred/{name}.glsl").read_text(),
                       "#define LIGHT_COUNT 1\n", spot=name != "softenLightF")
        uniform(prog,"color",1,1,1)
        uniform(prog,"size",10)
        uniform(prog,"far_z",-100)
        uniform(prog,"light[0]",0,0,0,10)
        uniform(prog,"light_col[0]",1,1,1,0.5)
        uniform(prog,"proj_shadow_idx",-1,integer=True)
        uniform(prog,"shadow_fade",1) # must not fade independent projector depth
        uniform(prog,"sss_point_depth",1,integer=True)
        uniform(prog,"sss_depth_valid",1,1,1)
        uniform(prog,"sss_depth_focus",0,0,-5,2.5)
        for flag in (0.46,0.79):
            uniform(prog,"test_flag",flag)
            setup_depth(prog,0.005,perspective=True)
            thin = pixel()[0]
            assert thin > 0.01, (name,"independent thin",thin)
            assert abs(thin-pixel(1)[0]) < 1e-6, (name,"independent MRT")
            setup_depth(prog,0.25,perspective=True)
            assert pixel()[0] == 0, (name,"independent thick",pixel())
            uniform(prog,"sss_shadow_thickness",0,integer=True)
            fallback = pixel()
            uniform(prog,"sss_shadow_thickness",1,integer=True)
            uniform(prog,"sss_depth_valid",0,0,0)
            assert pixel() == fallback, (name,"no map fallback")
            uniform(prog,"sss_depth_valid",1,1,1)
            uniform(prog,"sss_depth_focus",10,0,-5,2.5)
            assert pixel() == fallback, (name,"outside focus fallback")
            uniform(prog,"sss_depth_focus",0,0,-5,2.5)
            if "Point" in name or name == "pointLightF":
                uniform(prog,"sss_point_depth",0,integer=True)
                assert pixel() == fallback, (name,"point toggle")
                uniform(prog,"sss_point_depth",1,integer=True)
            uniform(prog,"test_normal",0,0,1)
            front = pixel()
            uniform(prog,"sss_shadow_thickness",0,integer=True)
            assert pixel() == front, (name,"front independent")
            uniform(prog,"sss_shadow_thickness",1,integer=True)
            uniform(prog,"test_normal",0,0,-1)
            checks += 7
        gl.DeleteProgram(prog)
    # Exercise derivative preparation in every production lighting main(), not
    # just in the path probe. A light-facing geometric surface must stay dark
    # even when its shading normal and depth texture suggest thin backlit tissue.
    for name in ("softenLightF", "spotLightF", "pointLightF", "multiPointLightF"):
        prog = program((SHADERS / f"class3/deferred/{name}.glsl").read_text(),
                       flags + "#define LIGHT_COUNT 1\n", spot=name != "softenLightF")
        uniform(prog,"color",1,1,1)
        uniform(prog,"size",10)
        uniform(prog,"far_z",-100)
        uniform(prog,"light[0]",0,0,0,10)
        uniform(prog,"light_col[0]",1,1,1,0.5)
        uniform(prog,"sss_point_depth",1,integer=True)
        uniform(prog,"sss_depth_valid",1,1,1)
        uniform(prog,"sss_depth_focus",0,0,-5,2.5)
        uniform(prog,"test_surface_dx",0.01,0,-0.0002)
        uniform(prog,"test_surface_dy",0,0.01,-0.0003)
        for flag in (0.46,0.79):
            uniform(prog,"test_flag",flag)
            for thickness in (0,0.004):
                setup_depth(prog,thickness)
                for i in range(9):
                    matrix(prog,f"shadow_matrix[{i}]" if i<6 else f"sss_depth_matrix[{i-6}]",
                           [[1,0,0,0.26],[0,1,0,0.3],[0,0,-1,-4.5],[0,0,0,1]])
                    depths=[0.5-thickness+0.02*(x-0.26)+0.03*(y-0.3) for y in (0.25,0.75) for x in (0.25,0.75)]
                    gl.ActiveTexture(0x84C0+4+i)
                    gl.TexImage2D(TEXTURE,0,0x81A6,2,2,0,0x1902,FLOAT,(F*4)(*depths))
                value=pixel()[0]
                assert value==0, (name,"geometric front-face rejection",thickness,value)
                checks+=1
        gl.DeleteProgram(prog)
    # Grazing measured transmission should be subdued on every light path,
    # while stronger backlighting (including thin ears) retains its response.
    for name in ("softenLightF", "spotLightF", "pointLightF", "multiPointLightF"):
        prog = program((SHADERS / f"class3/deferred/{name}.glsl").read_text(),
                       flags + "#define LIGHT_COUNT 1\n", spot=name != "softenLightF")
        uniform(prog,"color",1,1,1)
        uniform(prog,"size",10)
        uniform(prog,"far_z",-100)
        uniform(prog,"light[0]",0,0,0,10)
        uniform(prog,"light_col[0]",1,1,1,0.5)
        uniform(prog,"sss_point_depth",1,integer=True)
        uniform(prog,"sss_depth_valid",1,1,1)
        uniform(prog,"sss_depth_focus",0,0,-5,2.5)
        setup_depth(prog,0.004)
        for flag in (0.46,0.79):
            uniform(prog,"test_flag",flag)
            uniform(prog,"test_normal",0,0,-1)
            reference=pixel()[0]
            assert reference>0.01
            for backlight in (0.05,0.125,0.25,0.5,1.0):
                uniform(prog,"test_normal",math.sqrt(1-backlight*backlight),0,-backlight)
                value=pixel()[0]
                original=reference*backlight
                if backlight==0.05:
                    assert 0<value<original*0.2, (name,"grazing hotspot",value,original)
                elif backlight==0.125:
                    assert original*0.2<value<original*0.7, (name,"angle transition",value,original)
                else:
                    assert abs(value-original)<1e-5, (name,"strong backlighting changed",value,original)
                checks+=1
        gl.DeleteProgram(prog)
    # Isolating transmission must conserve scene and diffuse lighting. Front-lit
    # pixels must never leak into the transmission buffer, for every light path.
    for name in ("softenLightF", "spotLightF", "pointLightF", "multiPointLightF"):
        prog = program((SHADERS / f"class3/deferred/{name}.glsl").read_text(),
                       flags + "#define LIGHT_COUNT 1\n", spot=name != "softenLightF")
        uniform(prog,"color",1,1,1)
        uniform(prog,"size",10)
        uniform(prog,"far_z",-100)
        uniform(prog,"light[0]",0,0,0,10)
        uniform(prog,"light_col[0]",1,1,1,0.5)
        uniform(prog,"sss_point_depth",1,integer=True)
        uniform(prog,"sss_depth_valid",1,1,1)
        uniform(prog,"sss_depth_focus",0,0,-5,2.5)
        for flag in (0.46,0.79):
            uniform(prog,"test_flag",flag)
            for classic in (0,1):
                uniform(prog,"classic_mode",classic,integer=True)
                for normal in ((0,0,-1),(0,0,1)):
                    uniform(prog,"test_normal",*normal)
                    setup_depth(prog,0.005)
                    uniform(prog,"sss_transmission_smoothing",0,integer=True)
                    original, diffuse = pixel(), pixel(1)
                    assert pixel(2) == (0,0,0,0)
                    uniform(prog,"sss_transmission_smoothing",1,integer=True)
                    assert pixel() == original, (name,"scene changed before blur")
                    split, transmitted = pixel(1), pixel(2)
                    assert max(abs(diffuse[i]-split[i]-transmitted[i]) for i in range(3)) < 1e-6
                    if normal[2] < 0:
                        assert transmitted[0] > 0.01, (name,"transmission was not isolated",transmitted)
                    else:
                        assert max(transmitted[:3]) < 1e-6, (name,"front light was isolated")
                    checks += 1
        gl.DeleteProgram(prog)
    # Brightness scales output, while penetration rejects long measured paths
    # regardless of brightness or absorption.
    prog = program(PROBE, flags)
    uniform(prog, "test_index", -2, integer=True)
    uniform(prog, "sss_penetration", 0.02)
    setup_depth(prog, 0.005)
    baseline = pixel()[0]
    for brightness in (0.0, 0.2, 0.8, 2.0, 4.0):
        uniform(prog, "sss_lighting", 0, brightness, 8.5)
        assert abs(pixel()[0] - baseline * brightness / 0.4) < 1e-5
        checks += 1
    for absorption in (0.5, 8.5, 20.0):
        uniform(prog, "sss_lighting", 0, 4.0, absorption)
        setup_depth(prog, 0.03)
        assert pixel()[0] == 0, "Brightness/absorption bypassed penetration cutoff"
        checks += 1
    uniform(prog, "sss_lighting", 0, 0.4, 8.5)
    values = []
    for thickness in (0.01, 0.014, 0.017, 0.02):
        setup_depth(prog, thickness)
        values.append(pixel()[0])
    assert values[0] > values[1] > values[2] > values[3] == 0, values
    checks += 1
    # Low absorption exposes the cutoff itself: halfway through the measured
    # range should already be half faded, not an almost full-strength island.
    uniform(prog, "sss_lighting", 0, 1.0, 0.0)
    setup_depth(prog, 0.01)
    assert abs(pixel()[0] - 0.45) < 0.01, "Penetration retained a bright plateau"
    checks += 1
    uniform(prog, "test_index", -1, integer=True)
    before = pixel()
    uniform(prog, "sss_penetration", 0.005)
    assert pixel() == before, "Penetration changed the unmeasured fallback"
    checks += 1
    gl.DeleteProgram(prog)
    # A faceted shallow groove faces the light. The 4x4 footprint misses its
    # narrow center face and samples raised neighbors; extrapolating the center
    # plane must not mistake those parts of the same surface for tissue entry.
    prog=program(PROBE,flags)
    setup_depth(prog,0)
    uniform(prog,"sss_depth_valid",1,1,1)
    uniform(prog,"sss_depth_focus",0,0,-5,2.5)
    uniform(prog,"test_surface_dx",0.0001,0,-0.002)
    uniform(prog,"test_surface_dy",0,0.0001,0)
    rows=[[25,0,0,0.5],[0,25,0,0.5],[0,0,-1,-4.5],[0,0,0,1]]
    for index,unit,matname in ((0,8,"shadow_matrix[4]"),(-3,10,"sss_depth_matrix[0]")):
        matrix(prog,matname,rows)
        coords=[(i+0.5)/100-0.02 for i in range(4)]
        depths=[0.5-(-20*x+0.6*max(abs(y)-0.001,0)) for y in coords for x in coords]
        gl.ActiveTexture(0x84C0+unit)
        gl.TexImage2D(TEXTURE,0,0x81A6,4,4,0,0x1902,FLOAT,(F*16)(*depths))
        uniform(prog,"test_index",index,integer=True)
        value=pixel()
        assert value[0] == 0 and abs(value[3]-0.08)<1e-6, ("faceted self-depth hotspot",index,value)
        checks+=1
    gl.DeleteProgram(prog)
    # A sampled curved thickness profile must lose the sharp changes in slope
    # at texel boundaries without overshooting into thinner/brighter values.
    prog=program(PROBE,flags)
    setup_depth(prog,0.004)
    uniform(prog,"sss_depth_valid",1,1,1)
    uniform(prog,"sss_depth_focus",0,0,-5,2.5)
    paths=[0.008+0.006*math.cos(i*math.pi/4) for i in range(16)]
    for unit in (8,10):
        gl.ActiveTexture(0x84C0+unit)
        gl.TexImage2D(TEXTURE,0,0x81A6,16,1,0,0x1902,FLOAT,(F*16)(*(0.5-p for p in paths)))
    def curve(u,index):
        uniform(prog,"test_index",index,integer=True)
        rows=[[1,0,0,u],[0,1,0,0.5],[0,0,-1,-4.5],[0,0,0,1]]
        matrix(prog,"shadow_matrix[4]" if index==0 else "sss_depth_matrix[0]",rows)
        return pixel()[3]
    center=8.5/16
    epsilon=0.002/16
    old=[curve(center+d,0) for d in (-epsilon,0,epsilon)]
    filtered=[curve(center+d,-3) for d in (-epsilon,0,epsilon)]
    old_kink=abs(old[0]-2*old[1]+old[2])
    new_kink=abs(filtered[0]-2*filtered[1]+filtered[2])
    assert new_kink<old_kink*0.1, ("curved thickness still has interpolation seams",old_kink,new_kink)
    values=[curve((i+0.5)/64,-3) for i in range(64)]
    assert min(values)>=min(paths)-1e-6 and max(values)<=max(paths)+1e-6
    # Filtering must remain conservative at an opaque silhouette.
    gl.ActiveTexture(0x84C0+10)
    gl.TexImage2D(TEXTURE,0,0x81A6,16,1,0,0x1902,FLOAT,(F*16)(*([0.496]*8+[0.25]*8)))
    edge=[curve((i+0.5)/64,-3) for i in range(64)]
    assert all(b>=a-1e-7 for a,b in zip(edge,edge[1:])), edge
    assert abs(edge[0]-0.004)<1e-6 and abs(edge[-1]-0.08)<1e-6
    checks+=4
    # Direct reconstruction must also handle the focused projector's short near
    # plane and D24 quantization, without turning thin tissue into opaque depth.
    for distance,tolerance in ((1.0,0.0001),(5.0,0.0008),(15.0,0.003)):
        setup_depth(prog,0.004,z=-distance)
        uniform(prog,"sss_depth_focus",0,0,-distance,2.5)
        a,b=20/19.99,0.2/19.99
        matrix(prog,"sss_depth_matrix[0]",[[1,0,-0.5,0],[0,1,-0.5,0],[0,0,-a,-b],[0,0,-1,0]])
        depth=a-b/(distance-0.004)
        gl.ActiveTexture(0x84C0+10)
        gl.TexImage2D(TEXTURE,0,0x81A6,1,1,0,0x1902,FLOAT,(F*1)(depth))
        measured=pixel()[3]
        assert abs(measured-0.004)<tolerance, ("raw projector depth precision",distance,measured)
        checks+=1
    gl.DeleteProgram(prog)
    # Soft floor is identity when off, continuous at its knee, monotonic, and
    # never reduces thickness or changes the unavailable-depth sentinel.
    floor_source = """
    uniform float test_path;
    float getSSSClampedPath(float path);
    out vec4 frag_color;
    void main() { frag_color = vec4(getSSSClampedPath(test_path)); }
    """
    prog=program(floor_source, "")
    for minimum in (0.0,0.004,0.02):
        uniform(prog,"sss_minimum_thickness",minimum)
        for path in (-1.0,0.0,0.001,0.004,0.00799,0.008,0.00801,0.02,0.04,0.08):
            uniform(prog,"test_path",path)
            width=min(minimum,0.004)
            expected=path if path<0 or minimum==0 or path>=minimum+width else minimum if path<=minimum-width else minimum+(path-minimum+width)**2/(4*width)
            assert abs(pixel()[0]-expected)<1e-7, (minimum,path,pixel())
            checks+=1
    for lower,upper,knee in ((0,0.02,0),(0,0.02,0.004),(0.004,0.02,0.004),(0.01,0.012,0.02),(0.02,0.01,0.004)):
        uniform(prog,"sss_minimum_thickness",lower)
        uniform(prog,"sss_maximum_thickness",upper)
        uniform(prog,"sss_clamp_knee",knee)
        values=[]
        for path in (0,0.001,0.005,0.01,0.015,0.02,0.03,0.07):
            uniform(prog,"test_path",path)
            value=pixel()[0]
            assert lower-1e-7<=value<=max(lower,upper)+1e-7
            values.append(value)
        assert all(a<=b+1e-7 for a,b in zip(values,values[1:])), values
        for sentinel in (-1,0.08):
            uniform(prog,"test_path",sentinel)
            assert abs(pixel()[0]-sentinel)<1e-7
        checks+=3
    # The upper knee joins the identity and plateau with matching slopes.
    uniform(prog,"sss_minimum_thickness",0)
    uniform(prog,"sss_maximum_thickness",0.02)
    uniform(prog,"sss_clamp_knee",0.004)
    for center,slope in ((0.016,1),(0.024,0)):
        samples=[]
        for path in (center-0.00001,center,center+0.00001):
            uniform(prog,"test_path",path); samples.append(pixel()[0])
        assert all(abs((b-a)/0.00001-slope)<0.003 for a,b in zip(samples,samples[1:])), samples
        checks+=1
    gl.DeleteProgram(prog)
    # Exercise the optical response in every production light path.
    for name in ("softenLightF", "spotLightF", "pointLightF", "multiPointLightF"):
        prog=program((SHADERS / f"class3/deferred/{name}.glsl").read_text(),
                     flags+"#define LIGHT_COUNT 1\n",spot=name!="softenLightF")
        uniform(prog,"color",1,1,1)
        uniform(prog,"size",10)
        uniform(prog,"far_z",-100)
        uniform(prog,"light[0]",0,0,0,10)
        uniform(prog,"light_col[0]",1,1,1,0.5)
        uniform(prog,"sss_point_depth",1,integer=True)
        uniform(prog,"sss_depth_valid",1,1,1)
        uniform(prog,"sss_depth_focus",0,0,-5,2.5)
        for flag in (0.46,0.79):
            uniform(prog,"test_flag",flag)
            for thickness in (0.004,0.02):
                setup_depth(prog,thickness)
                uniform(prog,"sss_minimum_thickness",0)
                original=pixel()[0]
                uniform(prog,"sss_minimum_thickness",0.008)
                limited=pixel()[0]
                assert original>0 and (0<limited<original if thickness<0.016 else abs(limited-original)<1e-7), (name,original,limited)
                checks+=1
                if thickness==0.02:
                    uniform(prog,"sss_minimum_thickness",0)
                    uniform(prog,"sss_maximum_thickness",0.008)
                    assert pixel()[0]>original, (name,"upper clamp did not limit absorption")
                    uniform(prog,"sss_maximum_thickness",0)
                    checks+=1
        gl.DeleteProgram(prog)
    prog=program(PROBE,flags)
    uniform(prog,"test_index",-1,integer=True)
    original=pixel()
    uniform(prog,"sss_minimum_thickness",0.02)
    assert pixel()==original, "Minimum thickness changed the artistic fallback"
    checks+=1
    gl.DeleteProgram(prog)
    prog=program(PROBE,flags)
    uniform(prog,"test_index",0,integer=True)
    uniform(prog,"sss_penetration",0.02)
    uniform(prog,"sss_maximum_thickness",0.004)
    uniform(prog,"sss_clamp_knee",0.001)
    for thickness in (0.03,0.25):
        setup_depth(prog,thickness)
        assert pixel()[0]==0, "Maximum clamp bypassed measured penetration/opaque depth"
        checks+=1
    gl.DeleteProgram(prog)
    assert gl.GetError() == 0
    print(f"Passed {checks} SSS GPU checks: paths, cascades, fallback, sun/spot/point PBR and legacy composition, independent maps and point toggle.")


if __name__ == "__main__":
    sdl, window, ctx, gl = context()
    try:
        print("GPU:", gl.GetString(0x1F01).decode())
        run(sdl,gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
