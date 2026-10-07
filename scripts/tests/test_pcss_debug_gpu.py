"""Exercise the production white-shadow diagnostic on a hidden GL context.

Run: .venv/Scripts/python.exe scripts/tests/test_pcss_debug_gpu.py
Checks shadow channels, projector slot fades, AO isolation and the geometry mask.
"""
import ctypes as C
from pathlib import Path

from test_exact_oit_gpu import context, U, I, F, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT, RGBA, FLOAT

ROOT = Path(__file__).resolve().parents[2]
SHADERS = ROOT / "indra/newview/app_settings/shaders/class1/deferred"


def run(sdl, gl):
    for name, args in {"ActiveTexture": [U], "Uniform2f": [I, F, F]}.items():
        setattr(gl, name, C.WINFUNCTYPE(None, *args)(sdl.SDL_GL_GetProcAddress(("gl" + name).encode())))

    def obj(fn):
        value = U()
        fn(1, C.byref(value))
        return value.value

    prog = gl.CreateProgram()
    vertex = """out vec2 vary_fragcoord; void main(){
        vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
        gl_Position=vec4(p[gl_VertexID],0,1); vary_fragcoord=p[gl_VertexID]*0.5+0.5;}"""
    for kind, source in [(0x8B31, vertex), (0x8B30, (SHADERS / "pcssDebugF.glsl").read_text())]:
        shader = gl.CreateShader(kind)
        text = C.c_char_p(("#version 150 core\n" + source).encode())
        gl.ShaderSource(shader, 1, C.byref(text), None)
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
    gl.BindVertexArray(obj(gl.GenVertexArrays))
    gl.BindFramebuffer(FRAMEBUFFER, obj(gl.GenFramebuffers))
    gl.Viewport(0, 0, 1, 1)
    shadows, depth, output = [obj(gl.GenTextures) for _ in range(3)]

    def upload(texture, rgba):
        gl.BindTexture(TEXTURE, texture)
        for param in (0x2800, 0x2801):
            gl.TexParameteri(TEXTURE, param, 0x2600)
        gl.TexImage2D(TEXTURE, 0, 0x8814, 1, 1, 0, RGBA, FLOAT, (F * 4)(*rgba))

    upload(output, (0, 0, 0, 0))
    gl.FramebufferTexture2D(FRAMEBUFFER, COLOR_ATTACHMENT, TEXTURE, output, 0)
    assert gl.CheckFramebufferStatus(FRAMEBUFFER) == 0x8CD5
    for unit, name in enumerate(("diffuseMap", "depthMap")):
        gl.Uniform1i(gl.GetUniformLocation(prog, name.encode()), unit)

    # Expected values are display references for white, black and sRGB gray;
    # G deliberately varies independently because it contains ambient occlusion.
    cases = [
        ("unshadowed", (1, 1, 1, 1), (0, 0), 0.5, 1),
        ("sun umbra", (0, 1, 1, 1), (0, 0), 0.5, 0),
        ("sun penumbra", (0.5, 1, 1, 1), (0, 0), 0.5, 0.73535698),
        ("AO excluded", (1, 0, 1, 1), (0, 0), 0.5, 1),
        ("projector 0", (1, 1, 0, 1), (0, 0), 0.5, 0),
        ("projector 1", (1, 1, 1, 0), (0, 0), 0.5, 0),
        ("inactive slots", (1, 1, 0, 0), (1, 1), 0.5, 1),
        ("fading slot", (1, 1, 0, 1), (0.5, 0), 0.5, 0.73535698),
        ("darkest overlap", (0.5, 0, 0.21404114, 0.75), (0, 0), 0.5, 0.5),
        ("background", (0, 0, 0, 0), (0, 0), 1, 0.18),
        ("near far plane", (1, 0, 1, 1), (0, 0), 0.99999, 1),
        ("near black", (0.001, 1, 1, 1), (0, 0), 0.5, 0.01292),
    ]
    for label, values, fade, z, expected in cases:
        for unit, tex, rgba in [(0, shadows, values), (1, depth, (z, 0, 0, 1))]:
            gl.ActiveTexture(0x84C0 + unit)
            upload(tex, rgba)
        gl.Uniform2f(gl.GetUniformLocation(prog, b"projector_fade"), *fade)
        gl.DrawArrays(0x0004, 0, 3)
        pixel = (F * 4)()
        gl.ReadPixels(0, 0, 1, 1, RGBA, FLOAT, pixel)
        assert all(abs(pixel[i] - expected) < 2e-5 for i in range(3)), (label, list(pixel), expected)
        assert pixel[3] == 0, (label, "diagnostic must not add glow")
        assert gl.GetError() == 0, label
    print(f"PASS: {len(cases)} PCSS diagnostic GPU cases")


if __name__ == "__main__":
    sdl, window, ctx, gl = context()
    try:
        run(sdl, gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
