"""Exercise the production backdrop shaders on the viewer's hidden GL context.

Run: .venv/Scripts/python.exe scripts/tests/test_ui_backdrop_gpu.py
Checks constant preservation, live updates, Gaussian spread, capture coordinates,
rounded corners and panel opacity. No login or third-party Python packages.
"""
import ctypes as C
from pathlib import Path

from test_exact_oit_gpu import context, U, I, F, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT, RGBA, FLOAT

SHADERS = Path(__file__).resolve().parents[2] / "indra/newview/app_settings/shaders/class1"


def run(sdl, gl):
    for name, args in {"Uniform2f": [I, F, F], "Uniform4f": [I, F, F, F, F],
                       "UniformMatrix4fv": [I, I, C.c_ubyte, C.POINTER(F)]}.items():
        setattr(gl, name, C.WINFUNCTYPE(None, *args)(sdl.SDL_GL_GetProcAddress(("gl" + name).encode())))

    def obj(generator):
        value = U()
        generator(1, C.byref(value))
        return value.value

    def program(vertex, fragment):
        prog = gl.CreateProgram()
        for kind, source in [(0x8B31, vertex), (0x8B30, fragment)]:
            shader = gl.CreateShader(kind)
            text = C.c_char_p(("#version 430 core\n" + source).encode())
            gl.ShaderSource(shader, 1, C.byref(text), None)
            gl.CompileShader(shader)
            ok, log = I(), C.create_string_buffer(4096)
            gl.GetShaderiv(shader, 0x8B81, C.byref(ok))
            gl.GetShaderInfoLog(shader, len(log), None, log)
            assert ok.value, log.value.decode()
            gl.AttachShader(prog, shader)
            gl.DeleteShader(shader)
        for index, name in enumerate([b"position", b"texcoord0", b"diffuse_color"]):
            gl.BindAttribLocation(prog, index, name)
        gl.LinkProgram(prog)
        gl.GetProgramiv(prog, 0x8B82, C.byref(ok))
        gl.GetProgramInfoLog(prog, len(log), None, log)
        assert ok.value, log.value.decode()
        gl.UseProgram(prog)
        gl.Uniform1i(gl.GetUniformLocation(prog, b"diffuseMap"), 0)
        gl.Uniform2f(gl.GetUniformLocation(prog, b"blur_uv_scale"), 1, 1)
        return prog

    blur = program((SHADERS / "deferred/postDeferredNoTCV.glsl").read_text(),
                   (SHADERS / "interface/uiBlurF.glsl").read_text())
    composite = program((SHADERS / "interface/uiV.glsl").read_text(),
                        (SHADERS / "interface/uiBackdropF.glsl").read_text())
    identity = (F * 16)(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
    for name in [b"texture_matrix0", b"modelview_projection_matrix"]:
        gl.UniformMatrix4fv(gl.GetUniformLocation(composite, name), 1, 0, identity)

    gl.BindVertexArray(obj(gl.GenVertexArrays))
    gl.BindBuffer(0x8892, obj(gl.GenBuffers))
    # Position, UV and half-opacity color, covering the viewport with one triangle.
    vertices = (F * 27)(-1, -1, 0, 0, 0, 1, 1, 1, .5,
                        3, -1, 0, 2, 0, 1, 1, 1, .5,
                       -1, 3, 0, 0, 2, 1, 1, 1, .5)
    gl.BufferData(0x8892, C.sizeof(vertices), vertices, 0x88E4)
    for index, size, offset in [(0, 3, 0), (1, 2, 12), (2, 4, 20)]:
        gl.EnableVertexAttribArray(index)
        gl.VertexAttribPointer(index, size, FLOAT, 0, 36, C.c_void_p(offset))

    size = 64
    textures = [obj(gl.GenTextures) for _ in range(3)]
    fbo = obj(gl.GenFramebuffers)
    gl.BindFramebuffer(FRAMEBUFFER, fbo)

    def upload(tex, pixels):
        gl.BindTexture(TEXTURE, tex)
        for param in [0x2801, 0x2800]:
            gl.TexParameteri(TEXTURE, param, 0x2601)  # linear
        for param in [0x2802, 0x2803]:
            gl.TexParameteri(TEXTURE, param, 0x812F)  # clamp to edge
        data = (F * len(pixels))(*pixels) if pixels else None
        gl.TexImage2D(TEXTURE, 0, 0x8814, size, size, 0, RGBA, FLOAT, data)

    for tex in textures:
        upload(tex, None)

    def uniform(prog, name, *values):
        getattr(gl, f"Uniform{len(values)}f")(gl.GetUniformLocation(prog, name.encode()), *values)

    def draw(prog, source, target, origin=(0, 0), extent=None):
        gl.UseProgram(prog)
        gl.FramebufferTexture2D(FRAMEBUFFER, COLOR_ATTACHMENT, TEXTURE, target, 0)
        assert gl.CheckFramebufferStatus(FRAMEBUFFER) == 0x8CD5
        gl.BindTexture(TEXTURE, source)
        gl.Viewport(*origin, *(extent or (size - origin[0], size - origin[1])))
        gl.DrawArrays(4, 0, 3)
        assert gl.GetError() == 0

    def read():
        pixels = (F * (size * size * 4))()
        gl.ReadPixels(0, 0, size, size, RGBA, FLOAT, pixels)
        return pixels

    def filtered(pixels, sigma):
        upload(textures[0], pixels)
        gl.UseProgram(blur)
        uniform(blur, "blur_step", sigma / (4 * size), 0)
        draw(blur, textures[0], textures[1])
        uniform(blur, "blur_step", 0, sigma / (4 * size))
        draw(blur, textures[1], textures[2])
        return read()

    checks = 0
    # Changing the source really changes the result; no stale image/feedback.
    for color in [(0.2, 0.4, 0.8, 1), (0.8, 0.1, 0.3, 1)]:
        for sigma in [0.25, 1, 5, 16]:
            pixels = filtered(list(color) * (size * size), sigma)
            assert max(abs(value - color[i % 4]) for i, value in enumerate(pixels)) < 2e-5
            checks += 1

    impulse = [0.0, 0.0, 0.0, 1.0] * (size * size)
    impulse[(32 * size + 32) * 4] = 1.0
    narrow = filtered(impulse, 2)
    wide = filtered(impulse, 5)
    center = (32 * size + 32) * 4
    assert 0 < wide[center] < narrow[center] < 1
    assert abs(sum(wide[::4]) - 1) < 0.015
    assert abs(wide[center + 12] - wide[center + 12 * size]) < 1e-6
    checks += 3

    # Solid source makes rounded coverage and inherited opacity unambiguous.
    upload(textures[0], [0.2, 0.4, 0.8, 1] * (size * size))
    gl.UseProgram(composite)
    uniform(composite, "capture_rect", 0, 0, size, size)
    uniform(composite, "panel_size", size, size)
    uniform(composite, "corner_radius", 12)
    draw(composite, textures[0], textures[1])
    pixels = read()
    assert pixels[3] == 0
    assert abs(pixels[center + 3] - .5) < 1e-6
    assert abs(pixels[center] - .2) < 1e-6
    checks += 3

    # Nonzero viewport/capture origins must sample the same screen location.
    upload(textures[0], [v for y in range(size) for x in range(size)
                         for v in (x / size, y / size, 0, 1)])
    uniform(composite, "capture_rect", 8, 4, size - 8, size - 4)
    uniform(composite, "corner_radius", 0)
    draw(composite, textures[0], textures[1], (8, 4))
    pixels = read()
    # Hardware bilinear weights may be quantized to eight fractional bits.
    assert abs(pixels[center] - (((32.5 - 8) / 56 * size - .5) / size)) < 1 / (256 * size)
    assert abs(pixels[center + 1] - (((32.5 - 4) / 60 * size - .5) / size)) < 1 / (256 * size)
    checks += 2

    # Reusing a larger scratch buffer must not leak stale pixels outside the
    # current capture, even at screen edges or with a very wide filter.
    upload(textures[0], [v for y in range(size) for x in range(size)
                         for v in ((.3, .5, .7, 1) if x < 32 and y < 32 else (9, 0, 9, 1))])
    gl.UseProgram(blur)
    uniform(blur, "blur_uv_scale", .5, .5)
    uniform(blur, "blur_step", .1, 0)
    draw(blur, textures[0], textures[1], extent=(32, 32))
    uniform(blur, "blur_step", 0, .1)
    draw(blur, textures[1], textures[2], extent=(32, 32))
    gl.UseProgram(composite)
    uniform(composite, "blur_uv_scale", .5, .5)
    uniform(composite, "capture_rect", 0, 0, size, size)
    draw(composite, textures[2], textures[1])
    pixels = read()
    assert max(abs(value - (.3, .5, .7)[i % 4]) for i, value in enumerate(pixels) if i % 4 < 3) < 2e-5
    checks += 1
    print(f"PASS: {checks} UI backdrop GPU checks on {gl.GetString(0x1F01).decode()}")


if __name__ == "__main__":
    sdl, window, ctx, gl = context()
    try:
        run(sdl, gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
