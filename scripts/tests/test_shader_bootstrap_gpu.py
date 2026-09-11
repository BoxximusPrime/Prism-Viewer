"""Verify the UI shader can load before any shared shader feature objects.

Run: .venv/Scripts/python.exe scripts/tests/test_shader_bootstrap_gpu.py
Uses the viewer's bundled SDL3 on a hidden OpenGL context; no login required.
"""
import ctypes as C
from pathlib import Path

from test_exact_oit_gpu import context, I

SHADERS = Path(__file__).resolve().parents[2] / "indra/newview/app_settings/shaders/class1/interface"

sdl, window, ctx, gl = context()
try:
    program = gl.CreateProgram()
    for filename, kind in [("uiV.glsl", 0x8B31), ("uiF.glsl", 0x8B30)]:
        shader = gl.CreateShader(kind)
        source = C.c_char_p(("#version 430 core\n" + (SHADERS / filename).read_text()).encode())
        gl.ShaderSource(shader, 1, C.byref(source), None)
        gl.CompileShader(shader)
        ok, log = I(), C.create_string_buffer(4096)
        gl.GetShaderiv(shader, 0x8B81, C.byref(ok))
        gl.GetShaderInfoLog(shader, len(log), None, log)
        assert ok.value, (filename, log.value.decode())
        gl.AttachShader(program, shader)
        gl.DeleteShader(shader)

    # No basic, lighting, indexed-texture, or other feature objects are attached.
    for index, name in enumerate([b"position", b"texcoord0", b"diffuse_color"]):
        gl.BindAttribLocation(program, index, name)
    gl.LinkProgram(program)
    gl.GetProgramiv(program, 0x8B82, C.byref(ok))
    gl.GetProgramInfoLog(program, len(log), None, log)
    assert ok.value, log.value.decode()
    gl.UseProgram(program)
    for name in [b"diffuseMap", b"texture_matrix0", b"modelview_projection_matrix"]:
        assert gl.GetUniformLocation(program, name) >= 0, name
    assert gl.GetError() == 0
    print("PASS: standalone UI shader compiles and links with all text-rendering uniforms on", gl.GetString(0x1F01).decode())
finally:
    sdl.SDL_GL_DestroyContext(ctx)
    sdl.SDL_DestroyWindow(window)
    sdl.SDL_Quit()
