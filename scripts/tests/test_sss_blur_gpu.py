"""Exercise production diffusion and transmission blur on a hidden GL context (no login).
Run: .venv/Scripts/python.exe scripts/tests/test_sss_blur_gpu.py
"""
import ctypes as C
import math
import re
import statistics
from pathlib import Path
from test_exact_oit_gpu import context, U, I, F, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT, RGBA, FLOAT
from test_sss_shadow_gpu import PREAMBLE


def run(sdl, gl, reference=None, capture=None, size=64, benchmark=False, full_resolution=False):
    for name, args in {'ActiveTexture':[U], 'Uniform2f':[I,F,F], 'Uniform4f':[I,F,F,F,F],
                       'UniformMatrix4fv':[I,I,C.c_ubyte,C.POINTER(F)],
                       'DrawBuffers':[I,C.POINTER(U)], 'DeleteTextures':[I,C.POINTER(U)]}.items():
        setattr(gl,name,C.WINFUNCTYPE(None,*args)(sdl.SDL_GL_GetProcAddress(('gl'+name).encode())))
    def obj(fn):
        value=U(); fn(1,C.byref(value)); return value.value
    def compile_shader(kind, source):
        shader=gl.CreateShader(kind)
        text=C.c_char_p(('#version 430 core\n'+PREAMBLE+source).encode())
        gl.ShaderSource(shader,1,C.byref(text),None); gl.CompileShader(shader)
        ok=I(); log=C.create_string_buffer(8192)
        gl.GetShaderiv(shader,0x8B81,C.byref(ok)); gl.GetShaderInfoLog(shader,len(log),None,log)
        assert ok.value,log.value.decode()
        return shader
    vertex='''out vec2 vary_fragcoord;
    void main() { vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
    gl_Position=vec4(p[gl_VertexID],0,1); vary_fragcoord=p[gl_VertexID]*0.5+0.5; }'''
    # Use the viewer's actual G-buffer and packed-normal readers. Returning a
    # synthetic skin flag here used to hide a collision with normalMap.
    shaders=Path('indra/newview/app_settings/shaders/class1/deferred')
    def function(filename, signature):
        code=(shaders/filename).read_text()
        start=code.index(signature+'\n{')
        opening=code.index('{',start); depth=1; end=opening+1
        while depth:
            depth += (code[end]=='{') - (code[end]=='}')
            end += 1
        return code[start:end]
    gbuffer='''uniform sampler2D diffuseRect, specularRect, normalMap;
    vec4 getNormRaw(vec2 screenpos);
    vec4 decodeNormal(vec4 norm);
    '''+function('gbufferUtil.glsl','GBufferInfo getGBuffer(vec2 screenpos)')+ \
        function('deferredUtil.glsl','vec4 getNormRaw(vec2 screenpos)')+ \
        function('globalF.glsl','vec4 decodeNormal(vec4 norm)')
    # Follow the guide binding in the pipeline, including its registered sampler
    # name, so a C++ binding change cannot silently diverge from the GPU test.
    pipeline=Path('indra/newview/pipeline.cpp').read_text()
    guide_slot=re.search(r'shader.bindTexture\(LLShaderMgr::(\w+), &mSSSWide, false, LLTexUnit::TFO_POINT, 1\)',pipeline)[1]
    header=Path('indra/llrender/llshadermgr.h').read_text()
    guide_sampler=re.search(r'\b'+guide_slot+r',\s*//\s*"([^"]+)"',header)[1]
    normal_unit=3 if guide_sampler=='normalMap' and not reference else 5
    stubs='''
    uniform int test_edges;
    uniform float test_boundary, test_finger_width, test_finger_center;
    vec3 srgb_to_linear(vec3 c) { return c; }
    vec4 getPosition(vec2 tc) {
        float z=test_edges==2 && tc.x>=test_boundary ? -2.0:-1.0;
        if (test_edges==3) {
            float y=(tc.y-test_finger_center)/test_finger_width;
            z+=0.0125*sqrt(max(0.0,1.0-y*y));
        }
        return vec4((tc-0.5)*0.1,z,1);
    }'''
    source=Path(reference or 'indra/newview/app_settings/shaders/class1/deferred/sssDiffusionF.glsl').read_text()
    prog=gl.CreateProgram()
    for kind,code in ((0x8B31,vertex),(0x8B30,source),(0x8B30,gbuffer),(0x8B30,stubs)):
        shader=compile_shader(kind,code); gl.AttachShader(prog,shader); gl.DeleteShader(shader)
    gl.LinkProgram(prog); ok=I(); log=C.create_string_buffer(8192)
    gl.GetProgramiv(prog,0x8B82,C.byref(ok)); gl.GetProgramInfoLog(prog,len(log),None,log)
    assert ok.value,log.value.decode()
    gl.UseProgram(prog)
    values_by_uniform={}
    def uniform(name,*values,integer=False):
        values_by_uniform[name]=values
        location=gl.GetUniformLocation(prog,name.encode())
        getattr(gl,'Uniform1i' if integer else f'Uniform{len(values)}f')(location,*values)
    uniform('screen_res',size,size); uniform('sss_params',0.9,2,0.75,44)
    uniform('sss_smoothing_pass',1,integer=True)
    uniform('test_boundary',0.5); uniform('test_finger_width',0.125); uniform('test_finger_center',0.5)
    for name,unit in (('diffuseMap',0),('altDiffuseMap',1),('diffuseRect',2),('specularRect',2),
                      ('normalMap',normal_unit),('specularMap',4)):
        uniform(name,unit,integer=True)
    if not reference: uniform(guide_sampler,3,integer=True)
    matrix=(F*16)(1,0,0,0,0,0.1,0,0,0,0,1,0,0,0,0,1)
    gl.UniformMatrix4fv(gl.GetUniformLocation(prog,b'inv_proj'),1,0,matrix)
    gl.BindVertexArray(obj(gl.GenVertexArrays)); gl.Viewport(0,0,size,size)
    fbo=obj(gl.GenFramebuffers); gl.BindFramebuffer(FRAMEBUFFER,fbo)
    def texture(values=None, dimension=size):
        tex=obj(gl.GenTextures); gl.BindTexture(TEXTURE,tex)
        for param in (0x2801,0x2800): gl.TexParameteri(TEXTURE,param,0x2600)
        for param in (0x2802,0x2803): gl.TexParameteri(TEXTURE,param,0x812F)
        gl.TexImage2D(TEXTURE,0,0x8814,dimension,dimension,0,RGBA,FLOAT,(F*len(values))(*values) if values else None)
        return tex
    scratch=texture(); result=texture()
    small=(size+3)//4
    wide=texture(dimension=small); guide=texture(dimension=small)
    wide_scratch=texture(dimension=small); wide_result=texture(dimension=small)
    query=obj(gl.GenQueries)
    elapsed=[]
    benchmark_inputs=[]
    normal_inputs={}
    def filter_image(light,albedo,edge=0,radius=0.02,channel=0,full_resolution=full_resolution):
        uniform('sss_depth',radius); uniform('test_edges',edge,integer=True)
        uniform('sss_full_resolution',int(full_resolution),integer=True)
        boundary=values_by_uniform['test_boundary'][0]
        width=values_by_uniform['test_finger_width'][0]; center=values_by_uniform['test_finger_center'][0]
        key=(edge,boundary,width,center)
        gl.ActiveTexture(0x84C0+normal_unit)
        if key not in normal_inputs:
            packed=[]
            for y in range(size):
                for x in range(size):
                    skin=edge!=1 or (x+0.5)/size<boundary
                    ripple=0 if edge==4 else math.floor((x+0.5)/size*64)%2*0.3
                    length=math.sqrt(1+ripple*ripple)
                    nx,ny,nz=ripple/length,0,1/length
                    if edge==3:
                        fy=((y+0.5)/size-center)/width
                        skin=abs(fy)<1
                        nx,ny,nz=0,max(-1,min(1,fy)),math.sqrt(max(0,1-fy*fy))
                    f=math.sqrt(8*nz+8)
                    packed.extend((nx/f+0.5,ny/f+0.5,0,0.79 if skin else 0.67))
            normal_inputs[key]=texture(packed)
        gl.BindTexture(TEXTURE,normal_inputs[key])
        def rgba(values): return [channel for value in values for channel in (value,value,value,0)]
        if benchmark_inputs:
            surface,original=benchmark_inputs
            gl.ActiveTexture(0x84C2); gl.BindTexture(TEXTURE,surface)
            gl.ActiveTexture(0x84C1); gl.BindTexture(TEXTURE,original)
        else:
            gl.ActiveTexture(0x84C2); surface=texture(rgba(albedo))
            gl.ActiveTexture(0x84C1); original=texture(rgba(light))
            if benchmark: benchmark_inputs.extend((surface,original))
        gl.BeginQuery(0x88BF,query)
        if not reference and not full_resolution:
            if normal_unit!=3:
                gl.ActiveTexture(0x84C3); gl.BindTexture(TEXTURE,0)
            gl.ActiveTexture(0x84C4); gl.BindTexture(TEXTURE,0)
            gl.Viewport(0,0,small,small)
            gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT,TEXTURE,wide,0)
            gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT+1,TEXTURE,guide,0)
            gl.DrawBuffers(2,(U*2)(COLOR_ATTACHMENT,COLOR_ATTACHMENT+1))
            assert gl.CheckFramebufferStatus(FRAMEBUFFER)==0x8CD5
            uniform('sss_pass',2,integer=True); gl.DrawArrays(0x0004,0,3)
            gl.DrawBuffers(1,(U*1)(COLOR_ATTACHMENT))
            gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT+1,TEXTURE,0,0)
            gl.ActiveTexture(0x84C3); gl.BindTexture(TEXTURE,guide)
            gl.ActiveTexture(0x84C0); gl.BindTexture(TEXTURE,wide)
            gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT,TEXTURE,wide_scratch,0)
            uniform('sss_pass',3,integer=True); gl.DrawArrays(0x0004,0,3)
            gl.BindTexture(TEXTURE,wide_scratch)
            gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT,TEXTURE,wide_result,0)
            uniform('sss_pass',4,integer=True); gl.DrawArrays(0x0004,0,3)
            gl.ActiveTexture(0x84C4); gl.BindTexture(TEXTURE,wide_result)
            gl.Viewport(0,0,size,size)
        gl.ActiveTexture(0x84C0); gl.BindTexture(TEXTURE,original)
        gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT,TEXTURE,scratch,0)
        assert gl.CheckFramebufferStatus(FRAMEBUFFER)==0x8CD5
        uniform('sss_pass',0,integer=True); gl.DrawArrays(0x0004,0,3)
        gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT,TEXTURE,result,0)
        gl.BindTexture(TEXTURE,scratch)
        uniform('sss_pass',1,integer=True); gl.DrawArrays(0x0004,0,3)
        gl.EndQuery(0x88BF)
        ns=C.c_uint64(); gl.GetQueryObjectui64v(query,0x8866,C.byref(ns)); elapsed.append(ns.value/1e6)
        if benchmark: return
        pixels=(F*(size*size*4))(); gl.ReadPixels(0,0,size,size,RGBA,FLOAT,pixels)
        output=[light[i]+pixels[i*4+channel] for i in range(size*size)]
        if capture is not None: capture.append(output)
        gl.DeleteTextures(2,(U*2)(original,surface))
        return output
    if benchmark:
        uniform('sss_params',1,2,0.75,44)
        white=[1.0]*(size*size)
        beam=[1.0 if x<size//2 else 0.0 for y in range(size) for x in range(size)]
        for smoothing in (0,1):
            uniform('sss_smoothing_pass',smoothing,integer=True)
            for radius in (0.001,0.014,0.1):
                for projected in (2,8,32,128,512):
                    matrix[5]=radius*0.5*size/projected
                    gl.UniformMatrix4fv(gl.GetUniformLocation(prog,b'inv_proj'),1,0,matrix)
                    for _ in range(4): filter_image(beam,white,edge=4,radius=radius)
                    print(f'{"reference" if reference else "maximum quality" if full_resolution else "optimized"} {"transmission" if smoothing else "diffuse"} {radius:.3f}m {projected}px {size}x{size}: {statistics.median(elapsed[-3:]):.3f} ms',flush=True)
        return
    if size != 64:
        # Partial 4x4 tiles at odd viewport edges must not dim or shift light.
        matrix[5]=0.008
        gl.UniformMatrix4fv(gl.GetUniformLocation(prog,b'inv_proj'),1,0,matrix)
        constant=[0.4]*(size*size); white=[1.0]*(size*size)
        for smoothing in (0,1):
            uniform('sss_smoothing_pass',smoothing,integer=True)
            assert max(abs(v-0.4) for v in filter_image(constant,white,radius=0.1))<1e-5
        assert gl.GetError()==0
        print(f'Passed odd viewport conservation checks ({size}x{size}).')
        return
    flat=[0.4]*4096; white=[1.0]*4096
    assert max(abs(v-0.4) for v in filter_image(flat,white))<1e-5
    noise=[0.1 if (x//2+y//2)%2 else 0.8 for y in range(64) for x in range(64)]
    smooth=filter_image(noise,white)
    inner=[y*64+x for y in range(8,56) for x in range(8,56)]
    before=statistics.pvariance(noise[i] for i in inner)
    after=statistics.pvariance(smooth[i] for i in inner)
    assert after<before*0.1,(before,after)
    assert max(abs(a-b) for a,b in zip(filter_image(noise,white,radius=0),noise))<1e-6
    # The blur must preserve texture detail, even with varying surface normals.
    albedo=[0.2 if (x//2+y//2)%2 else 0.9 for y in range(64) for x in range(64)]
    textured=[a*0.5 for a in albedo]
    assert max(abs(a-b) for a,b in zip(filter_image(textured,albedo),textured))<1e-5
    split=[1.0 if x<32 else 0.0 for y in range(64) for x in range(64)]
    for edge in (1,2):
        assert max(abs(a-b) for a,b in zip(filter_image(split,white,edge=edge),split))<1e-5,edge
    # A narrow cylindrical finger with a bright stripe must produce a continuous
    # broad filter, not the repeated isolated stripes from 13 widely spaced taps.
    stripe=[1.0 if x==32 and 24<=y<40 else 0.0 for y in range(64) for x in range(64)]
    finger=filter_image(stripe,white,edge=3,radius=0.1)
    row=finger[32*64:33*64]
    assert min(row[16:49])>1e-5, 'Wide filter leaves gaps on the curved finger'
    assert max(abs(row[x-1]-2*row[x]+row[x+1]) for x in range(17,48))<0.001, 'Finger filter has visible steps'
    assert max(abs(finger[y*64+x]) for y in list(range(24))+list(range(40,64)) for x in range(64))<1e-6
    # Ordinary diffusion must carry illumination past a beam edge, with red
    # spreading farther than green/blue, while preserving the skin boundary.
    uniform('sss_smoothing_pass',0,integer=True)
    colors=[filter_image(split,white,channel=c) for c in range(3)]
    pixel=32*64+34
    assert colors[0][pixel]>colors[1][pixel]>colors[2][pixel]>0.0, [c[pixel] for c in colors]
    assert all(abs(c[32*64+48])<1e-6 for c in colors), 'Diffusion exceeded its radius'
    assert max(abs(a-b) for a,b in zip(filter_image(split,white,edge=1),split))<1e-5
    assert max(abs(a-b) for a,b in zip(filter_image(textured,albedo),textured))<1e-5
    # A close-up can project 6 mm to 24 pixels. The meter control must keep
    # widening the actual beam-edge profile above that value, up to 100 mm.
    matrix[5]=0.008
    gl.UniformMatrix4fv(gl.GetUniformLocation(prog,b'inv_proj'),1,0,matrix)
    uniform('sss_params',1,2,0.75,44)
    radii=(0.006,0.014,0.028,0.06,0.1)
    for smoothing in (0,1):
        uniform('sss_smoothing_pass',smoothing,integer=True)
        spread=[filter_image(split,white,radius=r)[32*64+48] for r in radii]
        print(('Transmission' if smoothing else 'Diffuse')+' close-up beam edge:',list(zip(radii,spread)))
        # Measured from the accepted full-resolution contiguous gather, before
        # optimization. Keep the same physical profile, including the 100 mm end.
        reference_spread=(0.004852,0.157499,0.368562,0.468460,0.488479) if smoothing else \
            (0.011349,0.200427,0.395604,0.475579,0.491112)
        assert max(abs(a-b) for a,b in zip(spread,reference_spread))<(1e-5 if full_resolution else 0.015)
        assert all(b>a+0.001 for a,b in zip(spread,spread[1:])), 'Scattering radius silently plateaued'
        assert spread[-1]>spread[0]+0.2, 'Maximum radius barely widened the beam edge'
        assert max(abs(v-0.4) for v in filter_image(flat,white,radius=0.1))<1e-5
        for edge in (1,2):
            assert max(abs(a-b) for a,b in zip(filter_image(split,white,edge=edge,radius=0.1),split))<0.001
        narrow=[1.0 if x==32 else 0.0 for y in range(64) for x in range(64)]
        row=filter_image(narrow,white,edge=4,radius=0.1)[32*64:33*64]
        assert min(row)>0.001, 'Wide-radius sampling left gaps around a one-pixel light'
        assert max(abs(row[x-1]-2*row[x]+row[x+1]) for x in range(1,63))<0.002
        # Boundaries deliberately cross preparation tiles instead of lining up
        # with their edges. Separate skin layers must still stay separate.
        for boundary in (33,35):
            uniform('test_boundary',boundary/64)
            off_grid=[1.0 if x<boundary else 0.0 for y in range(64) for x in range(64)]
            for edge in (1,2):
                actual=filter_image(off_grid,white,edge=edge,radius=0.1)
                assert max(abs(a-b) for a,b in zip(actual,off_grid))<1e-5
        uniform('test_boundary',0.5)
        uniform('test_finger_width',0.006); uniform('test_finger_center',32.5/64)
        one_pixel=[1.0 if x==32 and y==32 else 0.0 for y in range(64) for x in range(64)]
        thin=filter_image(one_pixel,white,edge=3,radius=0.1)
        assert min(thin[32*64:33*64])>0.001, 'Preparation lost a one-pixel skin surface/light'
        assert max(abs(thin[y*64+x]) for y in range(64) if y!=32 for x in range(64))<1e-6
        uniform('test_finger_width',0.125); uniform('test_finger_center',0.5)
    if not reference:
        # Switch both ways on the same program and buffers, as the live checkbox
        # does. Returning to normal quality must not retain screenshot state.
        for smoothing in (0,1):
            uniform('sss_smoothing_pass',smoothing,integer=True)
            ordinary=filter_image(split,white,radius=0.006,full_resolution=False)
            maximum=filter_image(split,white,radius=0.006,full_resolution=True)
            restored=filter_image(split,white,radius=0.006,full_resolution=False)
            assert max(abs(a-b) for a,b in zip(ordinary,restored))<1e-6
            assert max(abs(a-b) for a,b in zip(ordinary,maximum))>0.001
    assert gl.GetError()==0
    print('Passed 41 diffusion/transmission blur GPU checks: reference beam profiles, close-up radius progression through 100 mm, color response, bounded radius, mottling, constants, zero radius, texture detail, off-grid skin/depth boundaries, and continuous one-pixel surface/light filtering.')
    print(f'Interior mottling variance: {before:.6f} -> {after:.6f}')

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark',action='store_true',help='time the complete filter with GL_TIME_ELAPSED')
    parser.add_argument('--size',type=int,default=512,help='square benchmark patch size')
    parser.add_argument('--reference',help='optional original two-pass shader to compare')
    parser.add_argument('--full-resolution',action='store_true',help='benchmark screenshot quality instead of the optimized path')
    args=parser.parse_args()
    sdl,window,ctx,gl=context()
    try:
        if args.benchmark:
            run(sdl,gl,reference=args.reference,size=args.size,benchmark=True,full_resolution=args.full_resolution)
        else:
            for full_resolution in (False,True):
                print('Maximum quality' if full_resolution else 'Optimized quality')
                run(sdl,gl,reference=args.reference,full_resolution=full_resolution)
                run(sdl,gl,reference=args.reference,size=67,full_resolution=full_resolution)
    finally:
        sdl.SDL_GL_DestroyContext(ctx); sdl.SDL_DestroyWindow(window); sdl.SDL_Quit()
