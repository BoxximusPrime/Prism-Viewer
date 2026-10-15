"""Compare production SSS masked fragment output for separate and batched draws.

Run: .venv/Scripts/python.exe scripts/tests/test_sss_batch_gpu.py
Uses the bundled hidden OpenGL harness; no viewer or login required.
"""
import ctypes as C
from pathlib import Path

from test_exact_oit_gpu import context, U, I, F, P, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT, RGBA, FLOAT

ROOT = Path(__file__).resolve().parents[2]
FRAGMENT = (ROOT / "indra/newview/app_settings/shaders/class1/deferred/treeShadowF.glsl").read_text()
VERTEX = r'''
uniform int width, reverse_facing, clipped;
out vec2 vary_texcoord0;
void main() {
    int primitive = gl_VertexID / 3;
    int corner = gl_VertexID % 3;
    if (reverse_facing != 0) corner = 2 - corner;
    vec2 points[3] = vec2[3](vec2(0,0), vec2(1,0), vec2(.5,2));
    vec2 p = points[corner] + vec2(primitive, 0);
    if (clipped != 0 && primitive % 7 == 0) p.x -= float(width + 1);
    gl_Position = vec4(p.x / float(width) * 2.0 - 1.0, p.y * 2.0 - 1.0,
                       float(primitive % 5) * .1, 1);
    vary_texcoord0 = vec2((float(primitive) + .5) / float(width), .5);
}
'''


def run(sdl, gl):
    for name, args in {"Uniform2fv": [I, I, P], "DrawBuffers": [I, P],
                       "ClearColor": [F, F, F, F], "Clear": [U], "Disable": [U],
                       "DeleteTextures": [I, P], "DeleteProgram": [U]}.items():
        setattr(gl, name, C.WINFUNCTYPE(None, *args)(sdl.SDL_GL_GetProcAddress(("gl" + name).encode())))

    def obj(fn):
        value = U()
        fn(1, C.byref(value))
        return value.value

    def program(version):
        prog = gl.CreateProgram()
        for kind, source in ((0x8B31, VERTEX), (0x8B30, FRAGMENT +
                "\nbool hairDepthCapture(float a, out vec4 result) { return false; }\n")):
            shader = gl.CreateShader(kind)
            code = (f"#version {version}\n" + source).encode()
            pointer = C.c_char_p(code)
            gl.ShaderSource(shader, 1, C.byref(pointer), None)
            gl.CompileShader(shader)
            ok = I()
            gl.GetShaderiv(shader, 0x8B81, C.byref(ok))
            log = C.create_string_buffer(8192)
            gl.GetShaderInfoLog(shader, len(log), None, log)
            assert ok.value, log.value.decode()
            gl.AttachShader(prog, shader)
            gl.DeleteShader(shader)
        gl.LinkProgram(prog)
        ok = I()
        gl.GetProgramiv(prog, 0x8B82, C.byref(ok))
        log = C.create_string_buffer(8192)
        gl.GetProgramInfoLog(prog, len(log), None, log)
        assert ok.value, log.value.decode()
        gl.UseProgram(prog)
        return prog

    def uniform(prog, name, value, integer=False):
        fn = gl.Uniform1i if integer else gl.Uniform1f
        fn(gl.GetUniformLocation(prog, name.encode()), value)

    def texture(width, data):
        tex = obj(gl.GenTextures)
        gl.BindTexture(TEXTURE, tex)
        gl.TexParameteri(TEXTURE, 0x2801, 0x2600)
        gl.TexParameteri(TEXTURE, 0x2800, 0x2600)
        gl.TexImage2D(TEXTURE, 0, 0x8814, width, 1, 0, RGBA, FLOAT, data)
        return tex

    gl.BindVertexArray(obj(gl.GenVertexArrays))
    gl.BindFramebuffer(FRAMEBUFFER, obj(gl.GenFramebuffers))
    gl.DrawBuffers(1, (U * 1)(COLOR_ATTACHMENT))
    gl.Disable(0x0B71)  # No depth conflicts between the disjoint test triangles.
    gl.Disable(0x0B44)
    gl.Disable(0x0BE2)
    checks = 0
    for version in (330, 430):
        prog = program(version)
        uniform(prog, "diffuseMap", 0, True)
        uniform(prog, "minimum_alpha", .5)
        for section_count in (1, 2, 3, 8, 31, 32):
            counts = [1 + n % 3 for n in range(section_count)]
            # Start beyond zero to verify IDs are relative to the draw, not gl_VertexID.
            prefix = 3
            width = prefix + sum(counts)
            identities = [0 if n % 5 == 0 else 16777215 if n == 1 else n + 100 for n in range(section_count)]
            table, end = [], 0
            for count, identity in zip(counts, identities):
                end += count
                table.extend((end, identity))
            color = texture(width, None)
            gl.FramebufferTexture2D(FRAMEBUFFER, COLOR_ATTACHMENT, TEXTURE, color, 0)
            assert gl.CheckFramebufferStatus(FRAMEBUFFER) == 0x8CD5
            alpha = (F * (width * 4))(*(v for n in range(width) for v in
                                      (1, 1, 1, .25 if n % 4 == 0 else 1)))
            diffuse = texture(width, alpha)
            gl.Viewport(0, 0, width, 1)
            uniform(prog, "width", width, True)
            gl.Uniform2fv(gl.GetUniformLocation(prog, b"sss_depth_batches"), section_count, (F * len(table))(*table))

            def pixels(batched, phase, reverse, clipped):
                uniform(prog, "sss_depth_pass", phase, True)
                uniform(prog, "reverse_facing", reverse, True)
                uniform(prog, "clipped", clipped, True)
                uniform(prog, "sss_depth_batch_count", section_count if batched else 0, True)
                gl.ClearColor(0, 0, 0, 0)
                gl.Clear(0x4000)
                if batched:
                    uniform(prog, "sss_depth_id", 999)  # Must be overridden for every section.
                    gl.DrawArrays(0x0004, prefix * 3, sum(counts) * 3)
                else:
                    first = prefix
                    for count, identity in zip(counts, identities):
                        uniform(prog, "sss_depth_id", identity)
                        gl.DrawArrays(0x0004, first * 3, count * 3)
                        first += count
                data = (F * (width * 4))()
                gl.ReadPixels(0, 0, width, 1, RGBA, FLOAT, data)
                return tuple(data)

            for phase in (0, 1, 2):
                for reverse in (0, 1):
                    for clipped in (0, 1):
                        expected = pixels(False, phase, reverse, clipped)
                        if phase == 0 or (phase == 1 and reverse == 0):
                            assert any(expected), "The fixture must rasterize visible fragments"
                        assert pixels(True, phase, reverse, clipped) == expected, (version, section_count, phase, reverse, clipped)
                        # A following unbatched draw must ignore the previously uploaded table.
                        assert pixels(False, phase, reverse, clipped) == expected
                        checks += 1
            gl.DeleteTextures(1, C.byref(U(color)))
            gl.DeleteTextures(1, C.byref(U(diffuse)))
        gl.DeleteProgram(prog)
    assert gl.GetError() == 0
    print(f"Passed {checks} SSS GPU batch comparisons: 1–32 sections, exact IDs/depth, clipping, cutouts, facing, zero-ID exits and ordinary shadows (GLSL 330/430).")


if __name__ == "__main__":
    sdl, window, ctx, gl = context()
    try:
        run(sdl, gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
