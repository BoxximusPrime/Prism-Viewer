"""Run production PCSS shaders against synthetic blockers on a hidden GL context.

Run: .venv/Scripts/python.exe scripts/tests/test_pcss_gpu.py
Checks contact hardening, controls, warped cascades, receiver slope, fallback,
and simultaneous raw/comparison sampling of one depth texture. No login needed.
"""
import ctypes as C
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from test_exact_oit_gpu import context, U, I, F, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT, RGBA, FLOAT

ROOT = Path(__file__).resolve().parents[2]
SHADERS = ROOT / "indra/newview/app_settings/shaders/class1/deferred"
WIDTH, SIZE = 256, 256


def run(sdl, gl):
    for name, args in {
        "ActiveTexture": [U], "GenSamplers": [I, C.POINTER(U)],
        "BindSampler": [U, U], "SamplerParameteri": [U, U, I],
        "Uniform2f": [I, F, F], "Uniform3f": [I, F, F, F], "Uniform4f": [I, F, F, F, F],
        "UniformMatrix4fv": [I, I, C.c_ubyte, C.POINTER(F)],
    }.items():
        setattr(gl, name, C.WINFUNCTYPE(None, *args)(sdl.SDL_GL_GetProcAddress(("gl" + name).encode())))

    def obj(gen):
        value = U()
        gen(1, C.byref(value))
        return value.value

    def uniform(prog, name, *values, integer=False):
        loc = gl.GetUniformLocation(prog, name.encode())
        getattr(gl, "Uniform1i" if integer else f"Uniform{len(values)}f")(loc, *values)

    def matrix(prog, name, rows):
        values = (F * 16)(*(rows[r][c] for c in range(4) for r in range(4)))
        gl.UniformMatrix4fv(gl.GetUniformLocation(prog, name.encode()), 1, 0, values)

    vertex = """out vec2 vary_fragcoord; void main() {
        vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
        gl_Position=vec4(p[gl_VertexID],0,1);
        vary_fragcoord = p[gl_VertexID] * 0.5 + 0.5;
    }"""
    fragment = """
        uniform float test_z, test_y, test_slope, test_view_scale;
        uniform int test_quantized;
        uniform int test_spot;
        uniform int test_discontinuity, test_prepared;
        uniform mat4 shadow_matrix[6];
        uniform sampler2DShadow shadowMap0;
        float sampleDirectionalShadow(vec3 pos, vec3 norm, vec2 screen);
        float sampleSpotShadow(vec3 pos, vec3 norm, int index, vec2 screen);
        float pcfSpotShadow(sampler2DShadow map, vec4 tc, float bias, vec2 screen);
        float pcfShadow(sampler2DShadow map, vec3 norm, vec4 tc, float bias, vec2 screen, vec3 light);
        void preparePCSSDepth(vec3 pos, vec3 norm, vec2 screen);
        vec4 getPosition(vec2 uv) {
            float x = (uv.x - 0.5) * 2.0 * test_view_scale;
            float z = test_z + test_slope * x;
            if (test_discontinuity != 0 && uv.x * 256.0 < 129.0) z += 2.0;
            float dy = test_quantized != 0 ? 2.0 / 256.0 : 0.001;
            vec3 p = vec3(x, test_y + (uv.y * 256.0 - 1.5) * dy * test_view_scale, z);
            if (test_quantized != 0) {
                float d = (1.0 + 0.25 / z) * (1024.0 / 1023.75);
                d = floor(d * 16777215.0 + 0.5) / 16777215.0;
                float reconstructed = -256.0 / (1024.0 - d * 1023.75);
                p *= reconstructed / z;
            }
            return vec4(p, 1);
        }
        out vec4 frag_color;
        void main() {
            vec3 pos = getPosition(gl_FragCoord.xy / 256.0).xyz;
            vec3 normal = normalize(vec3(-test_slope, 0, 1));
            if (test_prepared != 0) preparePCSSDepth(pos, normal, gl_FragCoord.xy / 256.0);
            float shadow = sampleDirectionalShadow(pos, normal, gl_FragCoord.xy / 256.0);
            float old = pcfShadow(shadowMap0, normal, shadow_matrix[0]*vec4(pos,1), 1.0, gl_FragCoord.xy/256.0, vec3(0,0,1));
            if (test_spot != 0) {
                shadow = sampleSpotShadow(pos, normal, test_spot - 1, gl_FragCoord.xy);
                old = pcfSpotShadow(shadowMap0, shadow_matrix[4]*vec4(pos,1), 0.8, pos.xy);
            }
            frag_color = vec4(shadow, old, 0, 1);
        }
    """

    def program(flags, fragment_source=fragment, helpers=("sssDepthUtil", "shadowUtil", "pcssUtil"), version=430):
        prog = gl.CreateProgram()
        stages = [(0x8B31, vertex), (0x8B30, fragment_source)] + [
            (0x8B30, (SHADERS / (name + ".glsl")).read_text())
            for name in helpers]
        for kind, source in stages:
            shader = gl.CreateShader(kind)
            src = C.c_char_p((f"#version {version} core\n" + flags + source).encode())
            gl.ShaderSource(shader, 1, C.byref(src), None)
            gl.CompileShader(shader)
            ok, log = I(), C.create_string_buffer(16384)
            gl.GetShaderiv(shader, 0x8B81, C.byref(ok))
            gl.GetShaderInfoLog(shader, len(log), None, log)
            assert ok.value, log.value.decode()
            gl.AttachShader(prog, shader)
            gl.DeleteShader(shader)
        gl.LinkProgram(prog)
        gl.GetProgramiv(prog, 0x8B82, C.byref(ok))
        gl.GetProgramInfoLog(prog, len(log), None, log)
        assert ok.value, log.value.decode()
        gl.UseProgram(prog)
        for i in range(6):
            uniform(prog, f"shadowMap{i}", i, integer=True)
            uniform(prog, f"pcssDepthMap{i}", i + 6, integer=True)
        uniform(prog, "sun_up_factor", 1, integer=True)
        uniform(prog, "sun_dir", 0, 0, 1)
        uniform(prog, "moon_dir", 0, 0, 1)
        uniform(prog, "shadow_clip", 8, 16, 32, 64)
        uniform(prog, "shadow_res", SIZE, SIZE)
        uniform(prog, "proj_shadow_res", SIZE, SIZE)
        uniform(prog, "screen_res", 256, 256)
        uniform(prog, "shadow_bias", -0.002)
        uniform(prog, "spot_shadow_bias", -0.002)
        return prog

    programs = [program(flags) for flags in (
        "#define SUN_SHADOW\n#define PCSS_SHADOW\n",
        "#define SUN_SHADOW\n", "",
        "#define SUN_SHADOW\n#define SPOT_SHADOW\n#define PCSS_SHADOW\n",
        "#define SUN_SHADOW\n#define SPOT_SHADOW\n")]
    programs.append(program("#define SUN_SHADOW\n#define SPOT_SHADOW\n#define PCSS_SHADOW\n", version=330))
    gl.BindVertexArray(obj(gl.GenVertexArrays))
    gl.ActiveTexture(0x84C0 + 12)
    target = obj(gl.GenTextures)
    gl.BindTexture(TEXTURE, target)
    gl.TexImage2D(TEXTURE, 0, 0x8814, WIDTH, 3, 0, RGBA, FLOAT, None)
    gl.BindFramebuffer(FRAMEBUFFER, obj(gl.GenFramebuffers))
    gl.FramebufferTexture2D(FRAMEBUFFER, COLOR_ATTACHMENT, TEXTURE, target, 0)
    assert gl.CheckFramebufferStatus(FRAMEBUFFER) == 0x8CD5
    gl.Viewport(0, 0, WIDTH, 3)

    raw_sampler = obj(gl.GenSamplers)
    for param, value in ((0x884C, 0), (0x2801, 0x2600), (0x2800, 0x2600), (0x2802, 0x812F), (0x2803, 0x812F)):
        gl.SamplerParameteri(raw_sampler, param, value)
    depths = [obj(gl.GenTextures) for _ in range(6)]
    cases = 0

    def render(gap=1.0, angle=5.0, radius=1.0, quality=1, warp=0.0,
               extent=4.0, z=-4.0, slope=0.0, fill="edge", prog=None, bias=.005,
               minimum=0.0, spot=0, emitter=.1, discontinuity=False, prepared=False,
               quantized=False, view_scale=1.0):
        nonlocal cases
        prog = programs[3 if spot else 0] if prog is None else prog
        gl.UseProgram(prog)
        uniform(prog, "test_z", z)
        uniform(prog, "test_y", 0.3)
        uniform(prog, "test_slope", slope)
        uniform(prog, "test_view_scale", view_scale)
        uniform(prog, "test_quantized", int(quantized), integer=True)
        matrix(prog, "inv_proj", [[1,0,0,0], [0,1,0,0], [0,0,0,-1],
                                  [0,0,-1023.75/512,1024.25/512]] if quantized else [[0]*4 for _ in range(4)])
        uniform(prog, "shadow_clip", *( (256, 512, 768, 1024) if quantized else (8, 16, 32, 64) ))
        uniform(prog, "test_spot", spot, integer=True)
        uniform(prog, "test_discontinuity", int(discontinuity), integer=True)
        uniform(prog, "test_prepared", int(prepared), integer=True)
        uniform(prog, "pcss_params", math.tan(math.radians(angle) * 0.5), radius, bias, min(minimum, radius))
        uniform(prog, "pcss_projector_radius", emitter * .5)
        uniform(prog, "pcss_quality", quality, integer=True)
        # This projection warps along Y, as the viewer's sun cascades do.
        depth_range = 1024.0 if quantized else 128.0
        rows = [[1/extent, .5*warp, 0, .5], [0, 1/extent+.5*warp, 0, .5],
                [0, .5*warp, -1/depth_range, .5], [0, warp, 0, 1]]
        inverse = [[extent, 0, 0, -.5*extent], [0, extent, 0, -.5*extent],
                   [0, 0, -depth_range, .5*depth_range],
                   [0, -warp*extent, 0, 1+.5*warp*extent]]
        if spot:
            rows = [[.5, 0, -.5, 0], [0, .5, -.5, 0], [0, 0, -64/63, -64/63], [0, 0, -1, 0]]
            inverse = [[2, 0, 0, -1], [0, 2, 0, -1], [0, 0, 0, -1], [0, 0, -63/64, 1]]
        data = []
        for iy in range(SIZE):
            v = (iy + .5) / SIZE
            w_inv = 1 - warp * extent * (v - .5)
            y = extent * (v - .5) / w_inv
            w = 1 + warp * y
            for ix in range(SIZE):
                x = extent * ((ix + .5) / SIZE - .5) * w
                blocked = fill == "all" or fill == "self" or (fill == "edge" and x < 0)
                caster_z = z + (0 if fill == "self" else gap) + slope * x
                if spot:
                    caster_z = (z + (0 if fill == "self" else gap)) / (1 + slope * 2 * ((ix+.5)/SIZE-.5))
                    data.append(64/63 * (1 + 1/caster_z) if blocked and caster_z < -1 else 1.0)
                else:
                    data.append(.5 - caster_z/(depth_range*w) if blocked else 1.0)
        pixels = (F * len(data))(*data)
        for i, texture in enumerate(depths):
            matrix(prog, f"shadow_matrix[{i}]", rows)
            matrix(prog, f"pcss_inverse_matrix[{i}]", inverse)
            gl.ActiveTexture(0x84C0 + i)
            gl.BindTexture(TEXTURE, texture)
            # Match the viewer's DEPTH_COMPONENT24 sun and projector maps.
            gl.TexImage2D(TEXTURE, 0, 0x81A6, SIZE, SIZE, 0, 0x1902, FLOAT, pixels)
            for param, value in ((0x884C, 0x884E), (0x884D, 0x0203), (0x2801, 0x2601),
                                 (0x2800, 0x2601), (0x2802, 0x812F), (0x2803, 0x812F)):
                gl.TexParameteri(TEXTURE, param, value)
            gl.ActiveTexture(0x84C0 + i + 6)
            gl.BindTexture(TEXTURE, texture)
            gl.BindSampler(i + 6, raw_sampler)
        gl.DrawArrays(4, 0, 3)
        output = (F * (WIDTH * 4))()
        gl.ReadPixels(0, 1, WIDTH, 1, RGBA, FLOAT, output)
        assert gl.GetError() == 0
        result = list(output)[::4]
        assert all(math.isfinite(v) and -.001 <= v <= 1.001 for v in result), result
        cases += 1
        return result, list(output)[1::4]

    def width(row):
        return sum(.08 < value < .92 for value in row)

    for quality in range(3):
        assert min(render(fill="empty", quality=quality)[0]) == 1.0
        assert max(render(fill="all", quality=quality)[0]) == 0.0
        near = render(gap=.03, quality=quality)[0]
        assert min(near) == 0.0, "close contacts must survive the legacy normalized-depth bias"
        far = render(gap=3, quality=quality)[0]
        assert width(far) > width(near) + 10, (quality, width(near), width(far))
        small = render(gap=3, angle=1, quality=quality)[0]
        assert width(far) > width(small) + 8
        capped = render(gap=3, radius=.05, quality=quality)[0]
        assert width(capped) < width(far)

    reference = render(gap=3, quality=2)[0]
    for extent in (3.0, 6.0, 9.0):
        for warp in (0.0, .07, -.09):
            warped = render(gap=3, quality=2, extent=extent, warp=warp)[0]
            assert abs(width(reference) - width(warped)) <= 5, (extent, warp, width(reference), width(warped))
            assert max(abs(a-b) for a, b in zip(reference, warped)) < .22
            assert min(render(fill="self", slope=.4, extent=extent, warp=warp)[0]) > .999
    for z in (-5.9, -6.1, -9.9, -10.1, -14, -20.1, -28):
        row = render(gap=3, quality=2, z=z)[0]
        assert max(abs(a-b) for a, b in zip(reference, row)) < .01, z

    assert max(render(gap=.02, bias=.03, fill="all")[0]) == 1.0
    assert max(render(gap=.02, bias=.005, fill="all")[0]) == 0.0
    # A close occluder over sloping faces must not disappear when the hardware
    # bilinear footprint spans more depth than the gap (the polygon light leaks).
    for slope in (.4, 2.0, 8.0):
        row = render(gap=.03, slope=slope, fill="all", z=-16)[0]
        assert max(row) < .001, ("grazing contact leak", slope, max(row))
    disabled, old = render(angle=0)
    assert disabled == old, "off must preserve existing PCF exactly"
    legacy, old = render(prog=programs[1])
    assert legacy == old, "hardware fallback must preserve PCF"
    assert min(render(prog=programs[2])[0]) == 1.0, "shadows-off variant"
    assert min(render(z=-80)[0]) == 1.0, "beyond final cascade"
    # Minimum softness widens contacts, including pixels where the sparse
    # blocker search misses the caster, without exceeding the maximum.
    for quality in range(3):
        hard = render(gap=.03, quality=quality)[0]
        soft = render(gap=.03, minimum=.12, quality=quality)[0]
        assert width(soft) > width(hard) + 10
        capped = render(gap=.03, minimum=.5, radius=.05, quality=quality)[0]
        assert width(capped) < width(soft)
        flat = render(fill="self", minimum=.12, slope=2, z=-16)[0]
        assert min(flat) > .999, ("minimum self shadow", min(flat), flat[120:130])

    for spot in (1, 2):
        for quality in range(3):
            assert min(render(spot=spot, fill="empty", quality=quality)[0]) == 1.0
            assert max(render(spot=spot, fill="all", quality=quality)[0]) == 0.0
            near = render(spot=spot, gap=.03, emitter=.5, quality=quality)[0]
            far = render(spot=spot, gap=2, emitter=.5, quality=quality)[0]
            assert width(far) > width(near) + 12, (spot, quality, width(near), width(far))
            small = render(spot=spot, gap=2, emitter=.05, quality=quality)[0]
            assert width(far) > width(small) + 10
            soft = render(spot=spot, gap=.03, minimum=.12, quality=quality)[0]
            assert width(soft) > width(near) + 10
            assert min(render(spot=spot, fill="self", slope=.4, quality=quality, minimum=.12)[0]) > .999
        disabled, old = render(spot=spot, angle=0)
        assert disabled == old, "projector off preserves PCF"
        fallback, old = render(spot=spot, prog=programs[4])
        assert fallback == old, "projector hardware fallback preserves PCF"
        assert min(render(spot=spot, z=-80)[0]) == 1.0
        gather = render(spot=spot, gap=2, emitter=.5)[0]
        fetch = render(spot=spot, gap=2, emitter=.5, prog=programs[5])[0]
        assert max(abs(a-b) for a,b in zip(gather, fetch)) < .001, "GLSL 330 filtering agrees with gather"

    for spot in (0, 1, 2):
        for slope in (0.0, .4):
            row = render(spot=spot, fill="all", gap=.03, minimum=.02, slope=slope,
                         discontinuity=True, prepared=True)[0]
            assert max(row[129:]) < .001, ("silhouette quad leak", spot, slope, max(row[129:]))

    # Camera D24 quantization is separate from shadow-map precision. Small
    # camera moves used to make fully lit far terrain flip to full shadow.
    for distance in (40, 80, 160):
        for phase in (-.005, 0, .005):
            for slope in (.1, .4, 2.0):
                z = -distance + phase
                row = render(fill="self", z=z, slope=slope, extent=128, minimum=.14,
                             bias=.004, quantized=True, view_scale=16, prepared=True)[0]
                assert min(row) > .999, ("distant terrain acne", z, slope, min(row))
                row = render(fill="all", gap=.5, z=z, slope=slope, extent=128, minimum=.14,
                             bias=.004, quantized=True, view_scale=16, prepared=True)[0]
                assert max(row) < .001, ("distant cast shadow lost", z, slope, max(row))

    for z in (-4, -12, -24):
        row = render(fill="all", gap=.03, z=z, slope=.4, extent=8, minimum=.02,
                     bias=.004, quantized=True, prepared=True)[0]
        assert max(row) < .001, ("near contact lost to precision correction", z, max(row))

    for i in range(6, 12):
        gl.BindSampler(i, 0)

    # Preserve PCSS contacts in RBA while continuing to blur AO in G.
    blur = program("", (SHADERS / "blurLightF.glsl").read_text() + """
        vec4 getPosition(vec2 tc) { return vec4(tc, -4, 1); }
        vec4 getNorm(vec2 tc) { return vec4(0,0,1,0); }
    """, helpers=())
    gl.ActiveTexture(0x84C0 + 13)
    gl.BindTexture(TEXTURE, obj(gl.GenTextures))
    input_values = [float(x % 2) for y in range(3) for x in range(WIDTH) for channel in range(4)]
    gl.TexImage2D(TEXTURE, 0, 0x8814, WIDTH, 3, 0, RGBA, FLOAT, (F * len(input_values))(*input_values))
    for param, value in ((0x2801, 0x2600), (0x2800, 0x2600), (0x2802, 0x812F), (0x2803, 0x812F)):
        gl.TexParameteri(TEXTURE, param, value)
    uniform(blur, "lightMap", 13, integer=True)
    uniform(blur, "screen_res", WIDTH, 3)
    uniform(blur, "delta", 1, 0)
    uniform(blur, "kern_scale", 1)
    for i in range(4):
        uniform(blur, f"kern[{i}]", 1/(i+1), 1/(i+1), i*.5)
    outputs = []
    for enabled in (0, 1):
        uniform(blur, "pcss_enabled", enabled, integer=True)
        gl.DrawArrays(4, 0, 3)
        output = (F * (WIDTH * 4))()
        gl.ReadPixels(0, 1, WIDTH, 1, RGBA, FLOAT, output)
        outputs.append(list(output))
        assert gl.GetError() == 0
        cases += 1
    assert outputs[1][::4] == [float(x % 2) for x in range(WIDTH)]
    assert any(.1 < value < .9 for value in outputs[0][::4])
    for channel in (2, 3):
        assert outputs[1][channel::4] == outputs[1][::4]
    assert outputs[0][1::4] == outputs[1][1::4]
    print(f"PASS: {cases} PCSS GPU cases on {gl.GetString(0x1F01).decode()}")


if __name__ == "__main__":
    # The preferences are ordinary saved controls, so Apply/Cancel and graphics
    # preset capture follow the existing panel's recursive control collection.
    settings = ET.parse(ROOT / "indra/newview/app_settings/settings.xml").getroot().find("map")
    keys = [element.text for element in settings if element.tag == "key"]
    assert len(keys) == len(set(keys)), "duplicate saved setting"
    panel = ET.parse(ROOT / "indra/newview/skins/default/xui/en/panel_preferences_graphics1.xml")
    for name in ("RenderPCSSEnabled", "RenderPCSSLightSize", "RenderPCSSMaxSoftness", "RenderPCSSMinSoftness", "RenderPCSSProjectorSize", "RenderPCSSBias", "RenderPCSSQuality"):
        assert name in keys and panel.find(f".//*[@control_name='{name}']") is not None
    sdl, window, ctx, gl = context()
    try:
        run(sdl, gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
