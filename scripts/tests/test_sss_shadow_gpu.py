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
    for name, args in {"Clear": [U], "Enable": [U], "Disable": [U], "DepthFunc": [U], "Uniform3f": [I, F, F, F], "Uniform4f": [I, F, F, F, F],
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

    def program(fragment, flags, spot=False, vertex_override=None):
        vertex = "out vec4 vary_fragcoord; out vec3 trans_center;" if spot else "out vec2 vary_fragcoord;"
        vertex += "void main() { vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3)); gl_Position=vec4(p[gl_VertexID],0,1);"
        vertex += "vary_fragcoord=vec4(0,0,0,1); trans_center=vec3(0); }" if spot else "vary_fragcoord=vec2(0.5); }"
        if vertex_override is not None:
            vertex = vertex_override
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
        uniform(result, "sss_point_transmission_boost", 1)
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
            if i < 6:
                gl.TexImage2D(TEXTURE, 0, 0x8CAC, 1, 1, 0, 0x1902, FLOAT, (F*1)(d))
            else:
                exit_depth = (rows[2][2]*z + rows[2][3]) / (rows[3][2]*z + rows[3][3])
                gl.TexImage2D(TEXTURE, 0, 0x8814, 1, 1, 0, RGBA, FLOAT, (F*4)(d,1,exit_depth,1))
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
                        if path_index == 0:
                            gl.TexImage2D(TEXTURE,0,0x81A6 if near<1 else 0x8CAC,2,2,0,0x1902,FLOAT,(F*4)(*depths))
                        else:
                            exit_depth = a-b/5 if perspective else 0.5
                            packed=[c for d in depths for c in (d,1,d-depth+exit_depth,1)]
                            gl.TexImage2D(TEXTURE,0,0x8814,2,2,0,RGBA,FLOAT,(F*16)(*packed))
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
    # Only an explicit opt-out uses estimated thickness; missing depth stays dark.
    expected = math.exp(-0.165*8.5)*0.9*0.4*0.3
    uniform(prog, "sss_shadow_thickness", 0, integer=True)
    assert abs(pixel()[0]-expected) < 1e-6
    uniform(prog, "sss_shadow_thickness", 1, integer=True)
    uniform(prog, "test_index", -1, integer=True)
    assert pixel()[0] == 0
    gl.DeleteProgram(prog)
    for defines in ("", "#define SUN_SHADOW 1\n"):
        prog = program(PROBE, defines)
        uniform(prog, "test_index", 0, integer=True)
        setup_depth(prog,0.005)
        assert pixel()[0] == 0
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
            expected_gray = 1-thickness/0.3
            assert all(abs(c-expected_gray)<0.0001 for c in actual[:3]), actual
            assert actual[3] == 1
            checks += 1
        valid = [1,1,1]; valid[light] = 0
        uniform(prog, "sss_depth_valid", *valid)
        assert pixel() == (1.0,0.0,1.0,1.0)
        checks += 1
    uniform(prog, "sss_debug_light", 0, integer=True)
    uniform(prog, "sss_depth_valid", 1, 1, 1)
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
                        assert thin == thick == 0, (name,"uncertified ordinary depth transmitted",thin,thick)
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
                            assert faded[0] == 0 and pixel()[0] > 0, "Shadow slot fade enabled an implicit estimate"
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
    # Boost every local-light path, including projectors and estimated mode;
    # never change front lighting or resurrect a blocked measured path.
    for name, defines in (("pointLightF", ""), ("multiPointLightF", ""),
                          ("spotLightF", ""), ("spotLightF", "#define MULTI_SPOTLIGHT 1\n")):
        prog = program((SHADERS / f"class3/deferred/{name}.glsl").read_text(),
                       "#define LIGHT_COUNT 1\n" + defines, spot=True)
        uniform(prog,"color",1,1,1)
        uniform(prog,"size",10)
        uniform(prog,"far_z",-100)
        uniform(prog,"light[0]",0,0,0,10)
        uniform(prog,"light_col[0]",1,1,1,0.5)
        uniform(prog,"sss_depth_valid",1,1,1)
        uniform(prog,"sss_depth_focus",0,0,-5,2.5)
        uniform(prog,"sss_penetration",0.3)
        uniform(prog,"proj_shadow_idx",-1,integer=True)
        for flag in (0.46,0.79):
            uniform(prog,"test_flag",flag)
            for measured in (0,1):
                uniform(prog,"sss_point_depth",measured,integer=True)
                uniform(prog,"sss_shadow_thickness",measured,integer=True)
                uniform(prog,"sss_point_transmission_boost",1)
                setup_depth(prog,0.005,perspective=True)
                normal=pixel()[0]
                assert normal>0, (name,"boost test has no baseline transmission")
                uniform(prog,"sss_point_transmission_boost",4)
                assert abs(pixel()[0]-normal*4)<1e-5, (name,"boost scaling")
                uniform(prog,"test_normal",0,0,1)
                front=pixel()
                uniform(prog,"sss_point_transmission_boost",0)
                assert pixel()==front, (name,"boost affected front lighting")
                uniform(prog,"test_normal",0,0,-1)
                assert pixel()[0]==0, (name,"zero boost")
                checks+=3
            uniform(prog,"sss_point_depth",1,integer=True)
            uniform(prog,"sss_shadow_thickness",1,integer=True)
            uniform(prog,"sss_point_transmission_boost",16)
            setup_depth(prog,0.2,perspective=True)
            assert pixel()[0]>0, (name,"200 mm path still capped at 80 mm")
            uniform(prog,"sss_penetration",0.08)
            assert pixel()[0]==0, (name,"penetration limit ignored")
            uniform(prog,"sss_penetration",0.3)
            setup_depth(prog,0.4,perspective=True)
            assert pixel()[0]==0, (name,"blocked path amplified")
            checks+=3
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
            assert pixel()[0] == 0, (name,"missing depth invented tissue")
            uniform(prog,"sss_depth_valid",1,1,1)
            uniform(prog,"sss_depth_focus",10,0,-5,2.5)
            assert pixel()[0] == 0, (name,"outside focus invented tissue")
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
                    if i < 6:
                        gl.TexImage2D(TEXTURE,0,0x81A6,2,2,0,0x1902,FLOAT,(F*4)(*depths))
                    else:
                        packed=[c for d in depths for c in (d,1,d+thickness,1)]
                        gl.TexImage2D(TEXTURE,0,0x8814,2,2,0,RGBA,FLOAT,(F*16)(*packed))
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
        if unit == 8:
            gl.TexImage2D(TEXTURE,0,0x81A6,4,4,0,0x1902,FLOAT,(F*16)(*depths))
        else:
            packed=[c for d in depths for c in (d,1,0.5,1)]
            gl.TexImage2D(TEXTURE,0,0x8814,4,4,0,RGBA,FLOAT,(F*64)(*packed))
        uniform(prog,"test_index",index,integer=True)
        value=pixel()
        assert value[0] == 0 and abs(value[3]-(0.3 if index==-3 else 0.08))<1e-6, ("faceted self-depth hotspot",index,value)
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
        if unit == 8:
            gl.TexImage2D(TEXTURE,0,0x81A6,16,1,0,0x1902,FLOAT,(F*16)(*(0.5-p for p in paths)))
        else:
            packed=[c for p in paths for c in (0.5-p,1,0.5,1)]
            gl.TexImage2D(TEXTURE,0,0x8814,16,1,0,RGBA,FLOAT,(F*64)(*packed))
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
    packed=[c for d in [0.496]*8+[0.1]*8 for c in (d,1,0.5,1)]
    gl.TexImage2D(TEXTURE,0,0x8814,16,1,0,RGBA,FLOAT,(F*64)(*packed))
    edge=[curve((i+0.5)/64,-3) for i in range(64)]
    assert all(b>=a-1e-7 for a,b in zip(edge,edge[1:])), edge
    assert abs(edge[0]-0.004)<1e-6 and abs(edge[-1]-0.3)<1e-6
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
        # Quantize the captured entry and exit to the depth attachment's D24 precision.
        q=lambda d: round(d*16777215)/16777215
        gl.TexImage2D(TEXTURE,0,0x8814,1,1,0,RGBA,FLOAT,(F*4)(q(depth),1,q(a-b/distance),1))
        measured=pixel()[3]
        assert abs(measured-0.004)<tolerance, ("raw projector depth precision",distance,measured)
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
            values=[]
            for thickness in (0.004,0.02):
                setup_depth(prog,thickness)
                values.append(pixel()[0])
            assert values[0]>values[1]>0, (name,flag,values)
            checks+=1
        gl.DeleteProgram(prog)
    prog=program(PROBE,flags)
    uniform(prog,"test_index",0,integer=True)
    uniform(prog,"sss_penetration",0.02)
    for thickness in (0.03,0.25):
        setup_depth(prog,thickness)
        assert pixel()[0]==0, "Measured penetration/opaque depth transmitted"
        checks+=1
    gl.DeleteProgram(prog)
    # A 100 mm faceted arm sampled by a 512-pixel, 5 m-wide map. Its curved
    # exit differs from the receiver tangent plane over the filter footprint;
    # that uncertainty must not be reported as hundreds of millimeters of skin.
    prog=program(PROBE, "")
    uniform(prog,"test_index",-3,integer=True)
    uniform(prog,"sss_depth_valid",1,0,0)
    uniform(prog,"sss_depth_focus",0,0,-5,2.5)
    uniform(prog,"sss_penetration",0.3)
    uniform(prog,"test_light",0,0,-1)
    uniform(prog,"sss_lighting",0,1,0) # isolate matching confidence from absorption
    radius, span, resolution = 0.05, 5.0, 512
    vertices=[(radius*math.sin(i*math.pi/32),radius*math.cos(i*math.pi/32)) for i in range(-16,17)]
    def arm_surface(x):
        for (x0,z0),(x1,z1) in zip(vertices,vertices[1:]):
            if x0<=x<=x1:
                slope=(z1-z0)/(x1-x0)
                return z0+slope*(x-x0),slope
        return None
    row=[]
    for i in range(resolution):
        surface=arm_surface(((i+0.5)/resolution-0.5)*span)
        row.extend((0.5-surface[0],1,0.5+surface[0],1) if surface else (1,0,1,0))
    gl.ActiveTexture(0x84C0+10)
    gl.TexImage2D(TEXTURE,0,0x8814,resolution,resolution,0,RGBA,FLOAT,
                  (F*(4*resolution*resolution))(*(row*resolution)))
    matrix(prog,"sss_depth_matrix[0]",[[1/span,0,0,0.5],[0,1/span,0,0.5],[0,0,1,5.5],[0,0,0,1]])
    arm_errors,arm_coverage=[],[]
    for i in range(-40,41):
        x=i*0.001
        z,slope=arm_surface(x)
        uniform(prog,"test_pos",x,0,-5+z)
        uniform(prog,"test_surface_dx",0.0001,0,slope*0.0001)
        uniform(prog,"test_surface_dy",0,0.0001,0)
        value=pixel()
        measured=value[3]
        arm_errors.append(abs(measured-2*z))
        assert abs(measured-2*z)<0.01, ("faceted arm became false thick tissue",x,2*z,measured)
        t=measured/0.3
        coverage=value[0]/(0.9*(1-t*t*(3-2*t)))
        arm_coverage.append(coverage)
        assert coverage>0.8, ("faceted arm lost transmission coverage",x,coverage)
        checks+=1
    uniform(prog,"test_pos",0,0,-5+radius+0.03)
    uniform(prog,"test_surface_dx",0.0001,0,0)
    assert pixel()[0]==0, "Footprint tolerance admitted a separate surface 30 mm behind the arm"
    checks+=1
    print(f"100 mm arm: maximum reconstruction error {max(arm_errors)*1000:.2f} mm; minimum coverage {min(arm_coverage):.3f}")
    gl.DeleteProgram(prog)
    # Certified depth must be one closed object, and the receiver its first exit.
    prog=program(PROBE, "")
    uniform(prog,"test_index",-3,integer=True)
    uniform(prog,"sss_depth_valid",1,0,0)
    uniform(prog,"sss_depth_focus",0,0,-5,2.5)
    setup_depth(prog,0.004)
    baseline=pixel()[0]
    assert baseline > 0.01
    for entry_id,exit_id,exit_depth in ((0,1,0.5),(1,0,0.5),(1,2,0.5),
                                        (1,1,0.49),(1,1,0.51),(0,0,1)):
        gl.ActiveTexture(0x84C0+10)
        gl.TexImage2D(TEXTURE,0,0x8814,1,1,0,RGBA,FLOAT,(F*4)(0.496,entry_id,exit_depth,exit_id))
        assert pixel()[0] == 0, ("opaque/mismatched/disconnected layer transmitted",entry_id,exit_id,exit_depth,pixel())
        checks+=1
    # Receiver-depth uncertainty must fade conservatively instead of creating a new hard edge.
    exit_values=[]
    for gap in (0.0009,0.0011,0.0015,0.0021):
        gl.ActiveTexture(0x84C0+10)
        gl.TexImage2D(TEXTURE,0,0x8814,1,1,0,RGBA,FLOAT,(F*4)(0.496,1,0.5-gap,1))
        exit_values.append(pixel())
    assert all(abs(v[3]-0.004)<1e-6 for v in exit_values[:-1]), exit_values
    assert [v[0] for v in exit_values]==sorted((v[0] for v in exit_values),reverse=True)
    assert exit_values[-1][0]==0 and abs(exit_values[-1][3]-0.3)<1e-6
    checks+=1
    setup_depth(prog,0.004)
    # Both temporal confidence and spatial coverage continuously approach zero.
    for confidence in (0,0.001,0.1,0.49,0.5,0.51,0.9,1):
        uniform(prog,"sss_depth_valid",confidence,0,0)
        assert abs(pixel()[0]-baseline*confidence)<1e-6, ("map confidence snapped",confidence,pixel())
        checks+=1
    for offset,weight in ((0,1),(1.999,1),(2,1),(2.25,0.5),(2.5,0),(2.501,0)):
        uniform(prog,"sss_depth_focus",offset,0,-5,2.5)
        assert abs(pixel()[0]-baseline*weight)<1e-6, ("focus edge snapped",offset,pixel())
        checks+=1
    uniform(prog,"sss_depth_focus",2.499,0,-5,2.5)
    assert pixel()[0]<1e-5
    uniform(prog,"sss_penetration",0.029)
    setup_depth(prog,0.07)
    for offset in (2.499,2.501):
        uniform(prog,"sss_depth_focus",offset,0,-5,2.5)
        assert pixel()[0]==0, "Leaving depth coverage made thick tissue glow"
        checks+=1
    gl.DeleteProgram(prog)

    # Render the real capture fragments, with depth testing and the exact RG/BA
    # color masks used by the viewer, including masked and double-sided geometry.
    vertex = """
    uniform float test_capture_z;
    uniform int test_reverse;
    out vec4 post_pos, vertex_color;
    out float target_pos_x, pos_w;
    out vec2 vary_texcoord0;
    void main() {
        vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
        int index=test_reverse!=0 ? 2-gl_VertexID:gl_VertexID;
        gl_Position=vec4(p[index],test_capture_z*2.0-1.0,1);
        post_pos=gl_Position; vertex_color=vec4(1); pos_w=1;
        target_pos_x=1; vary_texcoord0=vec2(0.5);
    }
    """
    gl.ActiveTexture(0x84C0+15)
    capture_depth=obj(gl.GenTextures); gl.BindTexture(TEXTURE,capture_depth)
    gl.TexImage2D(TEXTURE,0,0x81A6,1,1,0,0x1902,FLOAT,None)
    gl.FramebufferTexture2D(FRAMEBUFFER,0x8D00,TEXTURE,capture_depth,0)
    assert gl.CheckFramebufferStatus(FRAMEBUFFER)==0x8CD5
    gl.Enable(0x0B71); gl.DepthFunc(0x0201)
    color_texture(0,[1,1,1,1])
    for name in ("shadowF","shadowAlphaMaskF","treeShadowF","pbrShadowAlphaMaskF",
                 "pbrShadowAlphaBlendF","avatarShadowF","avatarAlphaShadowF","avatarAlphaMaskShadowF"):
        fragment=(SHADERS/f"class1/deferred/{name}.glsl").read_text()
        if name=="shadowAlphaMaskF":
            fragment="uniform sampler2D diffuseRect; vec4 diffuseLookup(vec2 tc) { return texture(diffuseRect,tc); }\n"+fragment
        prog=program(fragment,"",vertex_override=vertex)
        uniform(prog,"minimum_alpha",0.5)
        uniform(prog,"color",1,1,1,1)
        for identity in (0,11):
            gl.ColorMask(1,1,1,1); gl.Clear(0x4100)
            uniform(prog,"sss_depth_pass",1,integer=True)
            uniform(prog,"sss_depth_id",identity)
            uniform(prog,"test_capture_z",0.3)
            uniform(prog,"test_reverse",0,integer=True)
            gl.ColorMask(1,1,0,0); gl.DrawArrays(0x0004,0,3)
            gl.Clear(0x0100)
            uniform(prog,"sss_depth_pass",2,integer=True)
            uniform(prog,"test_reverse",1,integer=True)
            gl.ColorMask(0,0,1,1)
            # An enclosing room's backface can precede the skin's first entry.
            # It must not replace the exit of the transmissive skin layer.
            uniform(prog,"sss_depth_id",0)
            uniform(prog,"test_capture_z",0.1)
            gl.DrawArrays(0x0004,0,3)
            uniform(prog,"sss_depth_id",11)
            uniform(prog,"test_capture_z",0.6)
            gl.DrawArrays(0x0004,0,3)
            gl.ReadBuffer(COLOR_ATTACHMENT)
            values=(F*4)(); gl.ReadPixels(0,0,1,1,RGBA,FLOAT,values)
            assert max(abs(a-b) for a,b in zip(values,(0.3,identity,0.6,11)))<1e-6, (name,tuple(values))
            checks+=1
        gl.ColorMask(1,1,1,1)
        uniform(prog,"test_reverse",0,integer=True)
        gl.Clear(0x0100)
        assert pixel()==(0,0,0,0), (name,"exit pass accepted front face")
        uniform(prog,"sss_depth_pass",0,integer=True)
        gl.Clear(0x0100)
        assert pixel()==(1,1,1,1), (name,"ordinary shadow output changed")
        checks+=2
        uniform(prog,"sss_depth_pass",1,integer=True)
        uniform(prog,"test_reverse",1,integer=True)
        gl.Clear(0x0100)
        assert pixel()==(0,0,0,0), (name,"entry pass accepted back face")
        checks+=1
        # A tighter focused near plane must not clip away an opaque light-side blocker.
        gl.Enable(0x864F) # GL_DEPTH_CLAMP, as used for both focused passes
        uniform(prog,"test_reverse",0,integer=True)
        uniform(prog,"test_capture_z",-0.1)
        uniform(prog,"sss_depth_id",0)
        gl.Clear(0x0100)
        blocker=pixel()
        # gl_FragCoord.z is the unclamped value; the depth attachment is clamped.
        assert max(abs(a-b) for a,b in zip(blocker,(-0.1,0,-0.1,0)))<1e-6, (name,blocker)
        # Prove it wrote depth, rather than being clipped and leaving the clear depth.
        uniform(prog,"test_capture_z",0.3)
        uniform(prog,"sss_depth_id",11)
        gl.DrawArrays(0x0004,0,3)
        values=(F*4)(); gl.ReadPixels(0,0,1,1,RGBA,FLOAT,values)
        assert tuple(values)==blocker, (name,"near blocker failed to occlude skin")
        gl.Disable(0x864F)
        checks+=1
        if name not in ("shadowF","avatarShadowF"):
            uniform(prog,"test_reverse",0,integer=True)
            color_texture(0,[1,1,1,0])
            gl.Clear(0x0100)
            assert pixel()==(0,0,0,0), (name,"transparent texel wrote a skin boundary")
            color_texture(0,[1,1,1,1])
            checks+=1
        gl.DeleteProgram(prog)
    gl.Disable(0x0B71)
    gl.FramebufferTexture2D(FRAMEBUFFER,0x8D00,TEXTURE,0,0)
    assert gl.GetError() == 0
    print(f"Passed {checks} SSS GPU checks: paths, explicit estimates, sun/spot/point composition, matched layers, coverage fades and real shadow capture fragments.")


if __name__ == "__main__":
    sdl, window, ctx, gl = context()
    try:
        print("GPU:", gl.GetString(0x1F01).decode())
        run(sdl,gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
