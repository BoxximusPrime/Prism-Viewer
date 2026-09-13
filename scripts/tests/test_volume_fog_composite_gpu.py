"""Depth-aware fog reconstruction on the production GLSL, without a viewer login."""
import ctypes as C
import math
from pathlib import Path
from test_exact_oit_gpu import context, U, I, F, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT, RGBA, FLOAT

ROOT = Path(__file__).resolve().parents[2]


def object_id(generator):
    value = U()
    generator(1, C.byref(value))
    return value.value


class Composite:
    """Shared by the reconstruction checks and the complete fog-pass benchmark."""
    def __init__(self, sdl, gl):
        self.gl = gl
        for name, args in {'ActiveTexture': [U], 'UniformMatrix4fv': [I,I,C.c_ubyte,C.c_void_p]}.items():
            setattr(gl, name, C.WINFUNCTYPE(None, *args)(sdl.SDL_GL_GetProcAddress(('gl'+name).encode())))
        self.program = gl.CreateProgram()
        vertex = 'void main(){vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));gl_Position=vec4(p[gl_VertexID],0,1);}'
        fragment = (ROOT/'indra/newview/app_settings/shaders/class1/deferred/volumeFogCompositeF.glsl').read_text()
        for kind, source in ((0x8B31, vertex), (0x8B30, fragment)):
            shader = gl.CreateShader(kind)
            source = C.c_char_p(('#version 330 core\n'+source).encode())
            gl.ShaderSource(shader, 1, C.byref(source), None); gl.CompileShader(shader)
            ok, log = I(), C.create_string_buffer(16384)
            gl.GetShaderiv(shader, 0x8B81, C.byref(ok)); gl.GetShaderInfoLog(shader, len(log), None, log)
            assert ok.value, log.value.decode()
            gl.AttachShader(self.program, shader); gl.DeleteShader(shader)
        gl.LinkProgram(self.program)
        gl.GetProgramiv(self.program, 0x8B82, C.byref(ok)); gl.GetProgramInfoLog(self.program, len(log), None, log)
        assert ok.value, log.value.decode()
        self.framebuffer = object_id(gl.GenFramebuffers)
        self.output = object_id(gl.GenTextures)
        self.size = None
        # Fixed units avoid disturbing the marcher: scene 0, depth 1, fog 12.
        gl.UseProgram(self.program)
        for name, unit in (('diffuseRect',0), ('depthMap',1), ('diffuseMap',12)):
            location = gl.GetUniformLocation(self.program, name.encode())
            assert location >= 0, name
            gl.Uniform1i(location, unit)

    def draw(self, scene, depth, fog, inverse, width, height):
        gl = self.gl
        gl.UseProgram(self.program)
        if self.size != (width, height):
            gl.ActiveTexture(0x84C0+15); gl.BindTexture(TEXTURE, self.output)
            gl.TexImage2D(TEXTURE, 0, 0x881A, width, height, 0, RGBA, FLOAT, None)
            gl.TexParameteri(TEXTURE, 0x2801, 0x2600); gl.TexParameteri(TEXTURE, 0x2800, 0x2600)
            self.size = width, height
        gl.BindFramebuffer(FRAMEBUFFER, self.framebuffer)
        gl.FramebufferTexture2D(FRAMEBUFFER, COLOR_ATTACHMENT, TEXTURE, self.output, 0)
        assert gl.CheckFramebufferStatus(FRAMEBUFFER) == 0x8CD5
        for unit, texture in ((0,scene), (1,depth), (12,fog)):
            gl.ActiveTexture(0x84C0+unit); gl.BindTexture(TEXTURE, texture)
        gl.UniformMatrix4fv(gl.GetUniformLocation(self.program, b'inv_proj'), 1, False, (F*16)(*inverse))
        gl.Viewport(0, 0, width, height); gl.DrawArrays(4, 0, 3)


def run(sdl, gl):
    composite = Composite(sdl, gl)
    gl.BindVertexArray(object_id(gl.GenVertexArrays))
    scene, depth, fog = [object_id(gl.GenTextures) for _ in range(3)]
    near, far = .1, 100.
    a, b = (far+near)/(near-far), 2*far*near/(near-far)
    inverse = [1,0,0,0, 0,1,0,0, 0,0,0,1/b, 0,0,-1,a/b]

    def render(width, height, fw, fh, colors, depths, factors):
        for texture, w, h, data in ((scene,width,height,colors), (depth,width,height,depths), (fog,fw,fh,factors)):
            gl.ActiveTexture(0x84C0+14); gl.BindTexture(TEXTURE,texture)
            gl.TexImage2D(TEXTURE,0,0x8814,w,h,0,RGBA,FLOAT,(F*len(data))(*data))
            gl.TexParameteri(TEXTURE,0x2801,0x2600); gl.TexParameteri(TEXTURE,0x2800,0x2600)
        composite.draw(scene, depth, fog, inverse, width, height)
        pixels = (F*(width*height*4))()
        gl.ReadPixels(0,0,width,height,RGBA,FLOAT,pixels)
        assert gl.GetError() == 0
        return list(pixels)

    def z(distance): return ((-a+b/distance)*.5+.5, 0, 0, 0)
    checks = 0

    def check(name, actual, expected, tolerance=.001):
        nonlocal checks
        assert len(actual) == len(expected)
        assert all(math.isfinite(v) for v in actual)
        assert max(abs(x-y) for x,y in zip(actual,expected)) < tolerance, (name,actual,expected)
        checks += 1

    # Scene checker detail and glow remain full resolution at every fog size,
    # including non-divisible viewport dimensions and a one-pixel target.
    for width,height,fw,fh in ((4,4,4,4),(4,4,2,2),(5,3,3,2),(1,1,1,1),(8,4,4,2)):
        colors = [v for i in range(width*height) for v in ((i%2)*.8,.2,.3,(i%3)*.25)]
        clear = (0,0,0,1)*(fw*fh)
        check('clear '+str((width,height,fw,fh)),render(width,height,fw,fh,colors,z(20)*(width*height),clear),colors)
        factors = (.2,.1,.3,.4)*(fw*fh)
        expected = [v for i in range(width*height) for v in
                    (colors[i*4]*.4+.2,colors[i*4+1]*.4+.1,colors[i*4+2]*.4+.3,colors[i*4+3]*.4)]
        check('constant fog '+str((width,height,fw,fh)),render(width,height,fw,fh,colors,z(20)*(width*height),factors),expected)

    # Vertical foreground/background discontinuity: only the matching path can
    # contribute. The red background fog must never spill onto the foreground.
    colors = (.1,.2,.3,.4)*8
    depths = (z(2)*2 + z(20)*2)*2
    factors = (0,0,0,1, .6,0,0,.2)
    expected = ((.1,.2,.3,.4)*2+(.62,.04,.06,.08)*2)*2
    check('depth edge',render(4,2,2,1,colors,depths,factors),expected)
    check('sky depth edge',render(4,2,2,1,colors,(z(2)*2+(1,0,0,0)*2)*2,factors),expected)
    # A one-pixel occluder missed by all low-res guide samples stays clear.
    depths = (z(2)+z(20)*3)*2
    expected = ((.1,.2,.3,.4)+(.62,.04,.06,.08)*3)*2
    check('thin occluder rejection',render(4,2,2,1,colors,depths,(.6,0,0,.2)*2),expected)
    check('HDR finite',render(1,1,1,1,(1000,2000,3000,.5),z(20),(65000,65000,65000,.5)),
          (64992,64992,64992,.25),.1) # 65000 rounded to the RGBA16F output
    print(f'PASS: {checks} production fog composite GPU checks (GLSL 330, RGBA16F)')


if __name__ == '__main__':
    sdl, window, ctx, gl = context()
    try: run(sdl, gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx); sdl.SDL_DestroyWindow(window); sdl.SDL_Quit()
