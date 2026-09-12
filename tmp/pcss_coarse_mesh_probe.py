"""Check PCSS on a rasterized curved mesh and across a finite light's horizon.

Run: .venv/Scripts/python.exe scripts/tests/test_pcss_mesh_gpu.py [--images]
Uses the production PCSS/shadow helpers, real D24 camera/shadow rasterization,
and both deferred and forward receivers. Python stdlib + bundled SDL3 only.
"""
import ctypes as C
import math
from pathlib import Path
import struct
import sys
import zlib

ROOT = Path(r'E:/BoxxyViewer')
sys.path.insert(0,str(ROOT/'scripts/tests'))
from test_exact_oit_gpu import context, U, I, F

SIZE = 256
SHADERS = ROOT / 'indra/newview/app_settings/shaders/class1/deferred'


def inverse(rows):
    rows = [list(row) + [float(i == j) for j in range(4)] for i, row in enumerate(rows)]
    for i in range(4):
        j = max(range(i, 4), key=lambda j: abs(rows[j][i]))
        rows[i], rows[j] = rows[j], rows[i]
        pivot = rows[i][i]
        rows[i] = [v / pivot for v in rows[i]]
        for j in range(4):
            if i != j:
                scale = rows[j][i]
                rows[j] = [a - scale*b for a, b in zip(rows[j], rows[i])]
    return [row[4:] for row in rows]


def png(path, pixels):
    data = b''.join(b'\0' + bytes(pixels[y*SIZE*3:(y+1)*SIZE*3]) for y in reversed(range(SIZE)))
    def chunk(kind, value):
        return struct.pack('!I', len(value)) + kind + value + struct.pack('!I', zlib.crc32(kind + value))
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', SIZE, SIZE, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(data)) + chunk(b'IEND', b''))


def run(sdl, gl):
    for name, args in {
        'ActiveTexture': [U], 'GenSamplers': [I, C.POINTER(U)], 'BindSampler': [U, U],
        'SamplerParameteri': [U, U, I], 'Uniform2f': [I, F, F], 'Uniform3f': [I, F, F, F],
        'Uniform4f': [I, F, F, F, F], 'UniformMatrix4fv': [I, I, C.c_ubyte, C.POINTER(F)],
        'ClearDepth': [C.c_double], 'ClearColor': [F, F, F, F], 'Clear': [U], 'DepthFunc': [U], 'DepthMask': [C.c_ubyte],
        'Enable': [U], 'Disable': [U], 'DrawBuffer': [U], 'ReadBuffer': [U],
    }.items():
        setattr(gl, name, C.WINFUNCTYPE(None, *args)(sdl.SDL_GL_GetProcAddress(('gl' + name).encode())))

    def obj(gen):
        value = U()
        gen(1, C.byref(value))
        return value.value

    def uniform(prog, name, *values, integer=False):
        loc = gl.GetUniformLocation(prog, name.encode())
        getattr(gl, 'Uniform1i' if integer else f'Uniform{len(values)}f')(loc, *values)

    def matrix(prog, name, rows):
        values = (F * 16)(*(rows[r][c] for c in range(4) for r in range(4)))
        gl.UniformMatrix4fv(gl.GetUniformLocation(prog, name.encode()), 1, 0, values)

    def program(vertex, fragment, helpers=False):
        prog = gl.CreateProgram()
        sources = [(0x8B31, vertex), (0x8B30, fragment)]
        if helpers:
            sources += [(0x8B30, ((ROOT/'tmp/pcss-before-wall-fix'/ (name+'.glsl')) if '--before' in sys.argv and name in ('pcssUtil','shadowUtil') else SHADERS/(name+'.glsl')).read_text()) for name in ('shadowUtil', 'pcssUtil', 'sssDepthUtil')]
        for kind, source in sources:
            shader = gl.CreateShader(kind)
            src = C.c_char_p(('#version 430 core\n#define SUN_SHADOW\n#define PCSS_SHADOW\n' + source).encode())
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
        return prog

    vertex = '''layout(location=0) in vec3 position;
        uniform mat4 projection; uniform float camera_distance, model_scale;
        out vec3 vpos;
        void main() { vpos=position*model_scale-vec3(0,0,camera_distance); gl_Position=projection*vec4(vpos,1); }'''
    capture = program(vertex, '''in vec3 vpos; out vec4 color;
        void main() { color=vec4(normalize(cross(dFdx(vpos),dFdy(vpos))),1); }''')
    get_pos = '''uniform sampler2D cameraDepth, geometryNormal;
        uniform mat4 inv_proj;
        vec4 getPosition(vec2 uv) { vec4 p=inv_proj*vec4(uv*2-1,texture(cameraDepth,uv).r*2-1,1); return vec4(p.xyz/p.w,1); }
        float sampleDirectionalShadow(vec3 p, vec3 n, vec2 uv);
        void preparePCSSDepth(vec3 p, vec3 n, vec2 uv);
        uniform vec3 sun_dir; uniform float camera_distance;
    '''
    lighting = program('''void main() { vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3)); gl_Position=vec4(p[gl_VertexID],0,1); }''',
        get_pos + '''out vec4 color; void main() {
            vec2 uv=gl_FragCoord.xy/256.0;
            if (texture(cameraDepth,uv).r>=1) { color=vec4(0); return; }
            vec3 p=getPosition(uv).xyz;
            vec3 n=texture(geometryNormal,uv).xyz;
            vec3 smoothNormal=normalize(p+vec3(0,0,camera_distance));
            preparePCSSDepth(p,smoothNormal,uv);
            float s=sampleDirectionalShadow(p,smoothNormal,uv);
            color=vec4(s,dot(n,sun_dir),dot(n,-p),1);
        }''', True)
    forward = program(vertex, get_pos + '''in vec3 vpos; out vec4 color; void main() {
            vec3 n=normalize(cross(dFdx(vpos),dFdy(vpos)));
            vec3 smoothNormal=normalize(vpos+vec3(0,0,camera_distance));
            float s=sampleDirectionalShadow(vpos,smoothNormal,gl_FragCoord.xy/256.0);
            color=vec4(s,dot(n,sun_dir),dot(n,-vpos),1);
        }''', True)

    points = []
    def point(x,y):
        theta, phi = 2*math.pi*x/32, math.pi*y/24
        return (math.sin(phi)*math.cos(theta), math.cos(phi), math.sin(phi)*math.sin(theta))
    for y in range(24):
        for x in range(32):
            for a,b in ((x,y),(x+1,y),(x,y+1),(x+1,y),(x+1,y+1),(x,y+1)):
                points.extend(point(a,b))
    gl.BindVertexArray(obj(gl.GenVertexArrays))
    gl.BindBuffer(0x8892, obj(gl.GenBuffers))
    values = (F*len(points))(*points)
    gl.BufferData(0x8892, C.sizeof(values), values, 0x88E4)
    gl.EnableVertexAttribArray(0)
    gl.VertexAttribPointer(0, 3, 0x1406, 0, 0, None)

    def texture(depth=False):
        tex = obj(gl.GenTextures)
        gl.BindTexture(0x0DE1, tex)
        gl.TexImage2D(0x0DE1, 0, 0x81A6 if depth else 0x8814, SIZE, SIZE, 0,
                      0x1902 if depth else 0x1908, 0x1406, None)
        for param,value in ((0x2801,0x2600),(0x2800,0x2600),(0x2802,0x812F),(0x2803,0x812F)):
            gl.TexParameteri(0x0DE1,param,value)
        return tex
    def framebuffer(color, depth):
        fbo = obj(gl.GenFramebuffers)
        gl.BindFramebuffer(0x8D40, fbo)
        gl.FramebufferTexture2D(0x8D40,0x8CE0,0x0DE1,color,0)
        gl.FramebufferTexture2D(0x8D40,0x8D00,0x0DE1,depth,0)
        assert gl.CheckFramebufferStatus(0x8D40)==0x8CD5
        return fbo
    shadow, view_depth, geom, color = texture(True), texture(True), texture(), texture()
    shadow_fbo, camera_fbo, output_fbo = framebuffer(geom,shadow), framebuffer(geom,view_depth), framebuffer(color,0)
    raw = obj(gl.GenSamplers)
    compare = obj(gl.GenSamplers)
    for sampler, mode in ((raw,0),(compare,0x884E)):
        for param,value in ((0x884C,mode),(0x884D,0x0203),(0x2801,0x2600),(0x2800,0x2600),(0x2802,0x812F),(0x2803,0x812F)):
            gl.SamplerParameteri(sampler,param,value)
    gl.Viewport(0,0,SIZE,SIZE)
    gl.DepthFunc(0x0201)

    results = {}
    cases = 0
    # The small mesh has the same projected geometry as the first case but
    # 1/100 of its world-space derivative lengths. An absolute normal-area
    # threshold incorrectly fell back to smooth shading normals at this size.
    for angle in (5,15,25,35,45,55,65,75,85,89.9):
        scale,distance=1,3.0
        near, far = .1*scale, 1024
        f = 2.5
        proj = [[f,0,0,0],[0,f,0,0],[0,0,-(far+near)/(far-near),-2*far*near/(far-near)],[0,0,-1,0]]
        lx,lz=math.sin(math.radians(angle)),math.cos(math.radians(angle))
        extent, depth_range=32*scale,128*scale
        light = [[lz/extent,0,-lx/extent,.5-lx*distance/extent],
                 [0,1/extent,0,.5],[-lx/depth_range,0,-lz/depth_range,.5-lz*distance/depth_range],[0,0,0,1]]
        clip_light = [[2*a-b for a,b in zip(row,light[3])] for row in light[:3]]+[light[3]]
        gl.UseProgram(capture)
        uniform(capture,'camera_distance',distance)
        uniform(capture,'model_scale',scale)
        gl.Enable(0x0B71)
        gl.DepthMask(1)
        for fbo,projection in ((shadow_fbo,clip_light),(camera_fbo,proj)):
            gl.BindFramebuffer(0x8D40,fbo)
            gl.ClearColor(0,0,0,0)
            gl.ClearDepth(1)
            gl.Clear(0x4100)
            matrix(capture,'projection',projection)
            gl.DrawArrays(4,0,len(points)//3)
        for unit, tex, sampler in ((0,shadow,compare),(1,shadow,raw),(2,view_depth,raw),(3,geom,raw)):
            gl.ActiveTexture(0x84C0+unit)
            gl.BindTexture(0x0DE1,tex)
            gl.BindSampler(unit,sampler)
        for prog, mode in ((lighting,'deferred'),(forward,'forward')):
            gl.UseProgram(prog)
            for i in range(4):
                uniform(prog,f'shadowMap{i}',0,integer=True)
                uniform(prog,f'pcssDepthMap{i}',1,integer=True)
                matrix(prog,f'shadow_matrix[{i}]',light)
                matrix(prog,f'pcss_inverse_matrix[{i}]',inverse(light))
            uniform(prog,'cameraDepth',2,integer=True)
            uniform(prog,'geometryNormal',3,integer=True)
            uniform(prog,'sun_dir',lx,0,lz)
            uniform(prog,'moon_dir',lx,0,lz)
            uniform(prog,'sun_up_factor',1,integer=True)
            uniform(prog,'shadow_clip',8,16,32,64)
            uniform(prog,'shadow_res',SIZE,SIZE)
            uniform(prog,'screen_res',SIZE,SIZE)
            uniform(prog,'pcss_params',math.tan(math.radians(.53)*.5),scale,.005*scale,.02)
            uniform(prog,'pcss_quality',2,integer=True)
            matrix(prog,'inv_proj',inverse(proj))
            matrix(prog,'projection',proj)
            uniform(prog,'camera_distance',distance)
            uniform(prog,'model_scale',scale)
            gl.BindFramebuffer(0x8D40,output_fbo)
            gl.FramebufferTexture2D(0x8D40,0x8D00,0x0DE1,view_depth if mode=='forward' else 0,0)
            gl.ClearColor(0,0,0,0)
            gl.Clear(0x4000)
            if mode=='forward':
                gl.Enable(0x0B71)
                gl.DepthFunc(0x0203)
                gl.DepthMask(0)
            else:
                gl.Disable(0x0B71)
            gl.DrawArrays(4,0,len(points)//3 if mode=='forward' else 3)
            output=(F*(SIZE*SIZE*4))()
            gl.ReadPixels(0,0,SIZE,SIZE,0x1908,0x1406,output)
            assert gl.GetError()==0
            assert all(math.isfinite(v) for v in output)
            visible=[output[i] for i in range(0,len(output),4) if output[i+3]>.5 and output[i+1]>.2]
            count=sum(v<.99 for v in visible)
            print(angle, mode, 'front shadow', count, '/', len(visible), 'peak', max(visible), flush=True)
            cases+=1
            if '--images' in sys.argv:
                pixels=[]
                for i in range(0,len(output),4):
                    s,_,_,alpha=output[i:i+4]
                    v=int(max(0,min(1,.15+.85*s))*255) if alpha else 0
                    pixels.extend([v]*3)
                directory=ROOT/'tmp'
                directory.mkdir(exist_ok=True)
                png(directory/f'pcss-wall-{angle}-{mode}.png',pixels)



if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try:
        run(sdl,gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
