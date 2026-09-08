"""Run the actual Exact OIT scheduling/capture/composite shaders on a hidden GL context.

Windows, Python stdlib only; uses the viewer's bundled SDL3 and an OpenGL 4.3 GPU.
Run: .venv/Scripts/python.exe scripts/tests/test_exact_oit_gpu.py
No viewer process or login is needed. This checks GPU correctness, not in-world FPS.
"""

import ctypes as C
from pathlib import Path
import random
import struct
import statistics
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SHADERS = ROOT / "indra/newview/app_settings/shaders/class1/deferred"
U, I, P, F = C.c_uint, C.c_int, C.c_void_p, C.c_float
SSBO, INDIRECT = 0x90D2, 0x8F3F
TEXTURE, RED_INTEGER, UINT, FLOAT = 0x0DE1, 0x8D94, 0x1405, 0x1406
FRAMEBUFFER, COLOR_ATTACHMENT, RGBA = 0x8D40, 0x8CE0, 0x1908
STORAGE_BARRIER, IMAGE_BARRIER, COMMAND_BARRIER, BUFFER_BARRIER = 0x2000, 0x20, 0x40, 0x200
NULL = 0xFFFFFFFF


def context():
    sdl = C.CDLL(str(ROOT / "build-vc170-64/packages/lib/release/SDL3.dll"))
    for name, ret, args in [
        ("SDL_Init", C.c_bool, [U]),
        ("SDL_GL_SetAttribute", C.c_bool, [I, I]),
        ("SDL_CreateWindow", P, [C.c_char_p, I, I, C.c_uint64]),
        ("SDL_GL_CreateContext", P, [P]),
        ("SDL_GL_GetProcAddress", P, [C.c_char_p]),
        ("SDL_GL_DestroyContext", C.c_bool, [P]),
        ("SDL_DestroyWindow", None, [P]),
        ("SDL_Quit", None, []),
        ("SDL_GetError", C.c_char_p, []),
    ]:
        fn = getattr(sdl, name)
        fn.restype, fn.argtypes = ret, args
    assert sdl.SDL_Init(0x20), sdl.SDL_GetError()
    assert sdl.SDL_GL_SetAttribute(17, 4)
    assert sdl.SDL_GL_SetAttribute(18, 3)
    assert sdl.SDL_GL_SetAttribute(20, 1)
    window = sdl.SDL_CreateWindow(b"Exact OIT shader checks", 32, 32, 0x2 | 0x8)
    assert window, sdl.SDL_GetError()
    ctx = sdl.SDL_GL_CreateContext(window)
    assert ctx, sdl.SDL_GetError()
    signatures = {
        "GetString": (C.c_char_p, U), "GetError": (U,),
        "CreateShader": (U, U), "ShaderSource": (None, U, I, P, P),
        "CompileShader": (None, U), "GetShaderiv": (None, U, U, P),
        "GetShaderInfoLog": (None, U, I, P, P), "DeleteShader": (None, U),
        "CreateProgram": (U,), "AttachShader": (None, U, U),
        "BindAttribLocation": (None, U, U, C.c_char_p), "LinkProgram": (None, U),
        "GetProgramiv": (None, U, U, P), "GetProgramInfoLog": (None, U, I, P, P),
        "UseProgram": (None, U), "GetUniformLocation": (I, U, C.c_char_p),
        "Uniform1i": (None, I, I), "Uniform1ui": (None, I, U),
        "Uniform1f": (None, I, F), "GenBuffers": (None, I, P),
        "BindBuffer": (None, U, U), "BindBufferBase": (None, U, U, U),
        "BufferData": (None, U, C.c_ssize_t, P, U),
        "GetBufferSubData": (None, U, C.c_ssize_t, C.c_ssize_t, P),
        "CopyBufferSubData": (None, U, U, C.c_ssize_t, C.c_ssize_t, C.c_ssize_t),
        "GenTextures": (None, I, P), "BindTexture": (None, U, U),
        "TexParameteri": (None, U, U, I),
        "TexImage2D": (None, U, I, I, I, I, I, U, U, P),
        "BindImageTexture": (None, U, U, I, C.c_ubyte, I, U, U),
        "GenFramebuffers": (None, I, P), "BindFramebuffer": (None, U, U),
        "FramebufferTexture2D": (None, U, U, U, U, I),
        "CheckFramebufferStatus": (U, U),
        "Viewport": (None, I, I, I, I), "ColorMask": (None, I, I, I, I),
        "GenVertexArrays": (None, I, P), "BindVertexArray": (None, U),
        "EnableVertexAttribArray": (None, U),
        "VertexAttribPointer": (None, U, I, U, C.c_ubyte, I, P),
        "DispatchCompute": (None, U, U, U), "MemoryBarrier": (None, U),
        "DrawArrays": (None, U, I, I), "DrawArraysIndirect": (None, U, P),
        "ReadPixels": (None, I, I, I, I, U, U, P),
        "GenQueries": (None, I, P), "BeginQuery": (None, U, U),
        "EndQuery": (None, U), "GetQueryObjectuiv": (None, U, U, P),
        "GetQueryObjectui64v": (None, U, U, P),
        "BeginConditionalRender": (None, U, U), "EndConditionalRender": (None,),
        "FenceSync": (P, U, U), "ClientWaitSync": (U, P, U, C.c_uint64),
        "DeleteSync": (None, P), "Flush": (None,),
    }
    funcs = {}
    for name, (ret, *args) in signatures.items():
        address = sdl.SDL_GL_GetProcAddress(("gl" + name).encode())
        assert address, name
        funcs[name] = C.WINFUNCTYPE(ret, *args)(address)
    return sdl, window, ctx, SimpleNamespace(**funcs)


def run(gl):
    print("GPU:", gl.GetString(0x1F01).decode(), gl.GetString(0x1F02).decode())

    def obj(generator):
        value = U()
        generator(1, C.byref(value))
        return value.value

    def program(stages):
        result = gl.CreateProgram()
        for kind, source in stages:
            shader = gl.CreateShader(kind)
            text = C.c_char_p(("#version 430 core\n" + source).encode())
            gl.ShaderSource(shader, 1, C.byref(text), None)
            gl.CompileShader(shader)
            ok, log = I(), C.create_string_buffer(16384)
            gl.GetShaderiv(shader, 0x8B81, C.byref(ok))
            gl.GetShaderInfoLog(shader, len(log), None, log)
            assert ok.value, log.value.decode()
            gl.AttachShader(result, shader)
            gl.DeleteShader(shader)
        gl.BindAttribLocation(result, 0, b"position")
        gl.LinkProgram(result)
        gl.GetProgramiv(result, 0x8B82, C.byref(ok))
        gl.GetProgramInfoLog(result, len(log), None, log)
        assert ok.value, log.value.decode()
        return result

    def uniform(prog, name, value):
        gl.Uniform1i(gl.GetUniformLocation(prog, name.encode()), value)

    def upload(buffer, data):
        gl.BindBuffer(SSBO, buffer)
        gl.BufferData(SSBO, len(data), C.create_string_buffer(data), 0x88E8)

    def read(buffer, size):
        data = C.create_string_buffer(size)
        gl.BindBuffer(SSBO, buffer)
        gl.GetBufferSubData(SSBO, 0, size, data)
        return data.raw

    def image(texture, width, height, data, integer=True):
        gl.BindTexture(TEXTURE, texture)
        gl.TexParameteri(TEXTURE, 0x2801, 0x2600)
        gl.TexParameteri(TEXTURE, 0x2800, 0x2600)
        gl.TexImage2D(TEXTURE, 0, 0x8236 if integer else 0x8814,
                      width, height, 0, RED_INTEGER if integer else RGBA,
                      UINT if integer else FLOAT, C.create_string_buffer(data))
        if texture in (heads, counts):
            gl.BindImageTexture(0 if texture == heads else 1, texture, 0, 0, 0, 0x88BA, 0x8236)

    vertex = (SHADERS / "postDeferredNoTCV.glsl").read_text()
    graphics = lambda source: program([(0x8B31, vertex), (0x8B30, source)])
    control_prog = program([(0x91B9, (SHADERS / "exactOITControlC.glsl").read_text())])
    composite_prog = graphics((SHADERS / "exactOITCompositeF.glsl").read_text())
    overflow_prog = graphics((SHADERS / "exactOITOverflowF.glsl").read_text())
    fallback_prog = graphics("out vec4 frag_color; void main(){frag_color=vec4(0.9,0.2,0.4,0.7);}")
    capture_prog = graphics((SHADERS / "exactOITCaptureF.glsl").read_text() +
                            "\nout vec4 frag_color; void main(){exact_oit_store(vec4(1,0,0,0.5)); frag_color=vec4(0);}")
    # Link both actual glow capture shaders with their viewer helpers supplied.
    program([(0x8B31, vertex + "\nout vec4 vertex_color; out vec2 vary_texcoord0;"),
             (0x8B30, "vec4 diffuseLookup(vec2 uv){return vec4(1);}\n" +
              (SHADERS / "exactOITEmissiveF.glsl").read_text())])
    program([(0x8B31, vertex + "\nout vec4 vertex_emissive; out vec2 base_color_texcoord; out vec2 emissive_texcoord;"),
             (0x8B30, "vec3 srgb_to_linear(vec3 c){return c;}\n" +
              (SHADERS / "exactOITPbrGlowF.glsl").read_text())])

    nodes, control, commands, staging = [obj(gl.GenBuffers) for _ in range(4)]
    for binding, buffer in [(0, nodes), (1, control), (4, commands)]:
        gl.BindBufferBase(SSBO, binding, buffer)
    upload(control, struct.pack("4I", 0, 4096, 0, 0))
    upload(commands, bytes(27 * 16))
    upload(staging, bytes(16))
    heads, counts, background, output = [obj(gl.GenTextures) for _ in range(4)]
    fbo = obj(gl.GenFramebuffers)
    gl.BindFramebuffer(FRAMEBUFFER, fbo)
    vao = obj(gl.GenVertexArrays)
    gl.BindVertexArray(vao)
    vbo = obj(gl.GenBuffers)
    gl.BindBuffer(0x8892, vbo)
    vertices = struct.pack("9f", -1, -1, 0, 3, -1, 0, -1, 3, 0)
    gl.BufferData(0x8892, len(vertices), C.create_string_buffer(vertices), 0x88E4)
    gl.VertexAttribPointer(0, 3, FLOAT, 0, 0, None)
    gl.EnableVertexAttribArray(0)
    query = obj(gl.GenQueries)

    width, height = 17, 19 # Deliberately not multiples of the reduction tile size.
    pixels = width * height
    opaque = struct.pack("4f", 0.15, 0.25, 0.35, 0.1)
    image(background, width, height, opaque * pixels, False)
    image(output, width, height, bytes(16 * pixels), False)
    gl.FramebufferTexture2D(FRAMEBUFFER, COLOR_ATTACHMENT, TEXTURE, output, 0)
    assert gl.CheckFramebufferStatus(FRAMEBUFFER) == 0x8CD5

    def control_pass(mode, capacity=4096):
        gl.UseProgram(control_prog)
        uniform(control_prog, "oitControlPass", mode)
        uniform(control_prog, "oitCapacity", capacity)
        gl.DispatchCompute((width + 15) // 16 if mode == 1 else 1,
                           (height + 15) // 16 if mode == 1 else 1, 1)
        gl.MemoryBarrier(STORAGE_BARRIER | COMMAND_BARRIER | BUFFER_BARRIER)

    # Actual capture verifies both the reduction and original-atomic paths.
    for reduce_max, capacity in ((0, 4096), (1, 4096), (0, 8), (1, 8)):
        upload(nodes, bytes(4096 * 32))
        image(heads, width, height, struct.pack(f"{pixels}I", *([NULL] * pixels)))
        image(counts, width, height, bytes(pixels * 4))
        control_pass(0, capacity)
        gl.Viewport(0, 0, 1, 1)
        gl.ColorMask(0, 0, 0, 0)
        gl.UseProgram(capture_prog)
        uniform(capture_prog, "oitReduceMaximum", reduce_max)
        for _ in range(65): gl.DrawArrays(4, 0, 3)
        gl.MemoryBarrier(STORAGE_BARRIER | IMAGE_BARRIER)
        if reduce_max: control_pass(1)
        gl.MemoryBarrier(BUFFER_BARRIER)
        captured = struct.unpack("4I", read(control, 16))
        assert captured == (65, capacity, int(capacity < 65), min(65, capacity)), (reduce_max, captured, hex(gl.GetError()))
        # Actual allocation overflow must generate an executable fallback predicate.
        gl.UseProgram(overflow_prog)
        gl.BeginQuery(0x8C2F, query)
        gl.DrawArrays(4, 0, 3)
        gl.EndQuery(0x8C2F)
        result = U()
        gl.GetQueryObjectuiv(query, 0x8866, C.byref(result))
        assert bool(result.value) == (capacity < 65)

    # Command generation at every boundary, including the full 2-GiB node limit,
    # requires no huge allocation to prove that every necessary pass is enabled.
    for depth in [0, 1] + [n for p in range(1, 27) for n in ((1 << p) - 1, 1 << p)]:
        upload(control, struct.pack("4I", depth, 1 << 26, 0, depth))
        control_pass(2)
        words = struct.unpack("108I", read(commands, 432))
        assert [words[p*4] for p in range(26)] == [3 if (1 << p) < depth else 0 for p in range(26)]
        assert words[104] == 3

    if "--benchmark" in sys.argv:
        # Isolate max-atomic versus reduction cost with identical actual capture
        # shader invocations. This is deliberately not an in-world FPS estimate.
        saved_size = width, height
        width = height = 256
        capacity = width * height * 64
        upload(nodes, bytes(capacity * 32))
        image(output, width, height, bytes(width * height * 16), False)
        timer = obj(gl.GenQueries)
        timings = {0: [], 1: []}
        for iteration in range(10):
            for reduce_max in ((0, 1) if iteration % 2 == 0 else (1, 0)):
                image(heads, width, height, struct.pack("I", NULL) * (width * height))
                image(counts, width, height, bytes(width * height * 4))
                control_pass(0, capacity)
                gl.Viewport(0, 0, width, height)
                gl.ColorMask(0, 0, 0, 0)
                gl.UseProgram(capture_prog)
                uniform(capture_prog, "oitReduceMaximum", reduce_max)
                gl.BeginQuery(0x88BF, timer)
                for _ in range(64): gl.DrawArrays(4, 0, 3)
                gl.MemoryBarrier(STORAGE_BARRIER | IMAGE_BARRIER)
                if reduce_max: control_pass(1)
                gl.EndQuery(0x88BF)
                elapsed = C.c_uint64()
                gl.GetQueryObjectui64v(timer, 0x8866, C.byref(elapsed))
                gl.MemoryBarrier(BUFFER_BARRIER)
                assert struct.unpack("4I", read(control, 16)) == (capacity, capacity, 0, 64)
                if iteration >= 2: timings[reduce_max].append(elapsed.value / 1e6)
        print("Synthetic 256x256x64 capture + maximum (GPU ms, 8 alternating samples):",
              {name: round(statistics.median(timings[mode]), 3)
               for mode, name in [(0, "per-fragment atomic"), (1, "tiled reduction")]})
        width, height = saved_size
        assert gl.GetError() == 0

    lengths = [0, 1, 2, 3, 4, 5, 7, 8, 9, 16, 17, 31, 32, 33, 64, 65, 127, 128, 129, 257, 513]
    checks = 4
    for cutoff in (0, 1):
        rng = random.Random(731)
        records, starts, sizes, expected = [], [], [], []
        for pixel in range(pixels):
            n = lengths[pixel] if pixel < len(lengths) else 0
            starts.append(len(records) if n else NULL)
            sizes.append(n)
            first = len(records)
            for layer in range(n):
                alpha = 1.0 if cutoff and layer == n // 2 else rng.choice([0.125, 0.5, 0.75])
                color = [rng.random(), rng.random(), rng.random(), alpha]
                glow = rng.choice([0.0, 0.125])
                depth = rng.choice([0.25, 0.5, 0.75]) # Equal-depth tie ordering too.
                blend = NULL if layer % 11 == 3 else 7 | (9 << 8) | (1 << 16) | (9 << 24)
                following = len(records) + 1 if layer + 1 < n else NULL
                records.append(struct.pack("6f2I", *color, glow, depth, following, blend))
            order = sorted(range(first, first + n), key=lambda i: (-struct.unpack("6f2I", records[i])[5], i))
            dst = list(struct.unpack("4f", opaque))
            glow = dst[3]
            for index in order:
                *color, node_glow, _, _, blend = struct.unpack("6f2I", records[index])
                if blend == NULL:
                    glow += node_glow
                else:
                    alpha = color[3]
                    dst[:3] = [color[c] * alpha + dst[c] * (1-alpha) for c in range(3)]
                    dst[3] *= 1-alpha
                    glow = node_glow + glow * (1-alpha)
            dst[3] = max(dst[3], glow)
            expected.extend(dst)

        for overflow in (False, True):
            upload(nodes, b"".join(records))
            upload(control, struct.pack("4I", len(records), 4096, int(overflow), 0))
            image(heads, width, height, struct.pack(f"{pixels}I", *starts))
            image(counts, width, height, struct.pack(f"{pixels}I", *sizes))
            image(output, width, height, opaque * pixels, False)
            control_pass(1)
            control_pass(2)
            draw_words = struct.unpack("108I", read(commands, 432))
            assert [draw_words[p*4] for p in range(26)] == [3 if not overflow and (1 << p) < max(lengths) else 0 for p in range(26)]
            assert draw_words[104] == (0 if overflow else 3)

            # Copy stats, then overwrite live control later: staging must retain
            # the originating capture, independently of future resets.
            gl.BindBuffer(0x8F36, control)
            gl.BindBuffer(0x8F37, staging)
            gl.CopyBufferSubData(0x8F36, 0x8F37, 0, 0, 16)
            fence = gl.FenceSync(0x9117, 0)
            gl.Flush()

            gl.Viewport(0, 0, 1, 1)
            gl.ColorMask(0, 0, 0, 0)
            gl.UseProgram(overflow_prog)
            gl.BeginQuery(0x8C2F, query)
            gl.DrawArrays(4, 0, 3)
            gl.EndQuery(0x8C2F)
            gl.Viewport(0, 0, width, height)
            gl.ColorMask(1, 1, 1, 1)
            gl.UseProgram(fallback_prog)
            gl.BeginConditionalRender(query, 0x8E13)
            gl.DrawArrays(4, 0, 3)
            gl.EndConditionalRender()

            gl.UseProgram(composite_prog)
            uniform(composite_prog, "oitPass", 1)
            gl.BindBuffer(INDIRECT, commands)
            gl.ColorMask(0, 0, 0, 0)
            for p in range(26):
                uniform(composite_prog, "oitFirstSortPass", cutoff if p == 0 else 0)
                gl.DrawArraysIndirect(4, P(p * 16))
                gl.MemoryBarrier(STORAGE_BARRIER | IMAGE_BARRIER)
            uniform(composite_prog, "oitPass", 2)
            uniform(composite_prog, "diffuseRect", 0)
            gl.BindTexture(TEXTURE, background)
            gl.ColorMask(1, 1, 1, 1)
            gl.DrawArraysIndirect(4, P(26 * 16))
            gl.BindBuffer(INDIRECT, 0)
            actual = (F * (pixels * 4))()
            gl.ReadPixels(0, 0, width, height, RGBA, FLOAT, actual)
            reference = [0.9, 0.2, 0.4, 0.7] * pixels if overflow else expected
            error = max(abs(a-b) for a, b in zip(actual, reference))
            assert error < 2e-5, (cutoff, overflow, error)
            result = U()
            gl.GetQueryObjectuiv(query, 0x8866, C.byref(result))
            assert bool(result.value) == overflow
            assert gl.ClientWaitSync(fence, 0, 0) in (0x911A, 0x911C)
            control_pass(0)
            assert struct.unpack("4I", read(staging, 16)) == (len(records), 4096, int(overflow), max(lengths))
            gl.DeleteSync(fence)
            assert gl.GetError() == 0
            checks += 1
    print(f"Passed {checks} GPU scenarios: capture A/B, reduction edges, deep/equal-depth lists, cutoff, exact blend/glow, overflow fallback, and staged statistics")


if __name__ == "__main__":
    sdl, window, ctx, gl = context()
    try:
        run(gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
