"""Exercise production TAAU with independently sized render/output grids.

Run: .venv/Scripts/python.exe scripts/tests/test_taau_gpu.py
Uses a hidden GL context; no login or viewer settings changes.
"""
import ctypes as C
import math
import statistics
import xml.etree.ElementTree as ET

import test_taa_gpu as base
from test_taa_gpu import GPU, SHADERS, ROOT, inverse, context
from test_exact_oit_gpu import F, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT, RGBA, FLOAT

# Odd output dimensions exercise the rounding used by window resizing.
base.W, base.H = W, H = 97, 65
IW, IH = (W * 3 + 2) // 4, (H * 3 + 2) // 4


def run(sdl, gl):
    gpu = GPU(sdl, gl)
    source = lambda name: (SHADERS / 'class1/deferred' / name).read_text()
    resolve, camera, copy = [gpu.program(source(name)) for name in
                            ('taaResolveF.glsl', 'taaCameraF.glsl', 'taaCopyF.glsl')]
    checks = 0

    def check(condition, message):
        nonlocal checks
        assert condition, message
        checks += 1

    def upload(tex, values, depth=False, width=IW, height=IH):
        gl.BindTexture(TEXTURE, tex)
        gl.TexImage2D(TEXTURE, 0, 0x81A6 if depth else 0x881A, width, height, 0,
                      0x1902 if depth else RGBA, FLOAT, (F * len(values))(*values))

    def low_texture(values, depth=False):
        tex = gpu.texture(depth=depth)
        upload(tex, values, depth)
        return tex

    def read_low(tex):
        gl.FramebufferTexture2D(FRAMEBUFFER, COLOR_ATTACHMENT, TEXTURE, tex, 0)
        values = (F * (IW * IH * 4))()
        gl.ReadPixels(0, 0, IW, IH, RGBA, FLOAT, values)
        check(gl.GetError() == 0, 'low-resolution readback GL error')
        return list(values)

    projection = [[1,0,0,0], [0,1,0,0], [0,0,-1.002002,-.2002002], [0,0,-1,0]]
    identity = [[float(r == c) for c in range(4)] for r in range(4)]
    d = lambda z: (1.002002 - .2002002 / z) * .5 + .5
    current = low_texture([.2,.4,.6,.37] * (IW * IH))
    opaque = low_texture([.2,.4,.6,.37] * (IW * IH))
    motion = low_texture([0,0,2,-1] * (IW * IH))
    depth = low_texture([d(2)] * (IW * IH), True)
    history, output, scratch, presentation = [gpu.texture() for _ in range(4)]
    gpu.uniform(resolve, 'taa_rcp_res', 1/W, 1/H)
    gpu.uniform(resolve, 'taa_history_weight', .9)
    gpu.uniform(resolve, 'taa_clip_gamma', 2)
    gpu.uniform(resolve, 'taa_motion_protection', 0)
    gpu.uniform(resolve, 'taa_transparency', 0)
    gpu.uniform(resolve, 'taa_static_details', 0, integer=True)
    gpu.matrix(resolve, 'taa_inv_projection', inverse(projection))
    gpu.matrix(resolve, 'taa_previous_inv_projection', inverse(projection))
    gpu.matrix(resolve, 'taa_current_from_previous', identity)

    def bind(old=history):
        gpu.viewer_bind('resolveTAA', resolve, {
            'mRT->screen': current, 'mTAAHistory[1 - mTAAIndex]': old,
            'mTAAMotion': motion, 'mTAAOpaque': opaque, 'mRT->deferredScreen': depth})

    # Flat HDR signals, borders, and an explicit history reset remain exact.
    for color in ([.2,.4,.6,.37], [80,40,20,.7]):
        upload(current, color * (IW * IH)); upload(opaque, color * (IW * IH))
        gpu.uniform(resolve, 'taa_history_valid', 0, integer=True)
        for jitter in ((0,0), (.375,-.25), (-.4375,4/9)):
            gpu.uniform(resolve, 'taa_jitter', jitter[0]/IW, jitter[1]/IH)
            bind(); gl.Viewport(0,0,W,H); gpu.draw(resolve,output)
            pixels = gpu.read(output)
            check(max(abs(pixels[i]-color[i%4]) for i in range(len(pixels)) if i%4 < 3) < .08,
                  f'constant HDR signal across unequal grids: {color}, {jitter}')
            check(all(math.isfinite(v) for v in pixels), 'finite output including borders')

    # History depth validity has a boundary in OUTPUT pixels, not input pixels.
    upload(current, [.2,.4,.6,.37] * (IW * IH))
    upload(opaque, [.2,.4,.6,.37] * (IW * IH))
    gpu.upload(history, [v for y in range(H) for x in range(W)
                        for v in [.2,.4,.6,2 if x >= W//2 else 8]])
    gpu.uniform(resolve, 'taa_jitter', 0,0)
    gpu.uniform(resolve, 'taa_history_valid', 1, integer=True)
    gpu.uniform(resolve, 'taa_debug_mode', 2, integer=True)
    bind(); gpu.draw(resolve,output); pixels=gpu.read(output)
    for x in (3,W//2-2,W//2+2,W-4):
        check(abs(pixels[(H//2*W+x)*4+1] - (.9 if x >= W//2 else 0)) < .002,
              f'history lookup must address output pixels: x={x}')
    # UV motion shifts that same boundary by exactly seven OUTPUT pixels.
    upload(motion, [7/W,0,2,0] * (IW * IH))
    bind(); gpu.draw(resolve,output); pixels=gpu.read(output)
    for x in (W//2-9,W//2-5,W-2):
        expected = .9 if W//2 <= x+7 < W else 0
        check(abs(pixels[(H//2*W+x)*4+1]-expected) < .002, f'reprojection/disocclusion: x={x}')
    upload(motion, [0,0,2,1] * (IW * IH))
    bind(); gpu.draw(resolve,output)
    check(max(gpu.read(output)[1::4]) == 0, 'reactive pixels reject stale history')

    # Camera motion is produced in a render-sized corner of the output scratch.
    gpu.uniform(camera, 'taa_rcp_res', 1/IW,1/IH)
    gpu.matrix(camera, 'taa_previous_from_view', identity)
    gpu.matrix(camera, 'taa_previous_projection', projection)
    for jx,jy in ((.375,.25),(-.4375,-.25)):
        jittered=[row[:] for row in projection]
        jittered[0][2] -= 2*jx/IW; jittered[1][2] -= 2*jy/IH
        gpu.matrix(camera, 'taa_inv_projection', inverse(jittered))
        gpu.uniform(camera, 'taa_jitter', jx/IW,jy/IH)
        gpu.bind(camera, 'depthMap', 0, depth)
        gl.Viewport(0,0,IW,IH); gpu.draw(camera,scratch)
        gpu.bind(copy,'taa_source',0,scratch)
        gpu.bind(copy,'taa_original',1,current)
        gpu.uniform(copy,'taa_copy_mode',5,integer=True)
        gpu.uniform(copy,'taa_rcp_res',1/IW,1/IH)
        gpu.draw(copy,motion); vectors=read_low(motion)
        check(max(abs(vectors[i]) for i in range(len(vectors)) if i%4<2) < .00001,
              'stationary jitter must not produce camera motion')
        check(max(abs(vectors[i]-2) for i in range(2,len(vectors),4)) < .002,
              'motion scratch copy preserves every render pixel and depth')
    gl.Viewport(0,0,W,H)

    # Accumulation must improve a subpixel edge over single-frame reconstruction.
    gpu.uniform(resolve,'taa_debug_mode',0,integer=True)
    upload(motion,[0,0,2,-1]*(IW*IH))
    roi=[y*W+x for y in range(5,H-5) for x in range(5,W-5)]
    edge=lambda x,y: x > .37*y + W*.37
    truth={i:sum(edge(i%W+(sx+.5)/8,i//W+(sy+.5)/8) for sy in range(8) for sx in range(8))/64*.5 for i in roi}
    def halton(i,b):
        f=1; value=0
        while i: f/=b; value+=f*(i%b); i//=b
        return value
    temporal_errors=[]; spatial_errors=[]
    for frame in range(80):
        jx,jy=halton(frame%16+1,2)-.5,halton(frame%16+1,3)-.5
        values=[v for y in range(IH) for x in range(IW)
                for v in ([1,1,1,.37] if edge((x+.5-jx)*W/IW,(y+.5-jy)*H/IH) else [0,0,0,.37])]
        upload(current,values); upload(opaque,values)
        gpu.uniform(resolve,'taa_jitter',jx/IW,jy/IH)
        bind(history); gpu.uniform(resolve,'taa_history_valid',int(frame>0),integer=True)
        gpu.draw(resolve,output); pixels=gpu.read(output)
        if frame>=48:
            temporal_errors.append(statistics.mean((pixels[i*4]/(1+pixels[i*4])-truth[i])**2 for i in roi))
            gpu.uniform(resolve,'taa_history_valid',0,integer=True)
            gpu.draw(resolve,presentation); spatial=gpu.read(presentation)
            spatial_errors.append(statistics.mean((spatial[i*4]/(1+spatial[i*4])-truth[i])**2 for i in roi))
        history,output=output,history
    temporal,spatial=statistics.mean(temporal_errors),statistics.mean(spatial_errors)
    print(f'75% reconstruction edge MSE: temporal={temporal:.7f}, single frame={spatial:.7f}')
    check(temporal < spatial*.7, 'temporal accumulation must improve subpixel reconstruction')
    # Presentation keeps original scene alpha despite different texture sizes.
    gpu.bind(copy,'taa_source',0,history); gpu.bind(copy,'taa_original',1,current)
    gpu.uniform(copy,'taa_rcp_res',1/W,1/H)
    gpu.uniform(copy,'taa_jitter',jx/IW,jy/IH)
    gpu.uniform(copy,'taa_copy_mode',1,integer=True)
    gpu.uniform(copy,'taa_sharpen',0)
    gpu.draw(copy,presentation)
    check(max(abs(a-.37) for a in gpu.read(presentation)[3::4])<.001,'full-resolution glow alpha')

    # Post effects consume full-resolution color and jittered render-resolution depth.
    vertex='''out vec2 vary_fragcoord;
    void main(){vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
    gl_Position=vec4(p[gl_VertexID],0,1);vary_fragcoord=p[gl_VertexID]*.5+.5;}'''
    cof=gpu.program(source('cofF.glsl'),vertex)
    final_source=source('postDeferredNoDoFF.glsl').replace('gl_FragDepth =','frag_color.a =')
    final_source+='\nvec3 clampHDRRange(vec3 color){return clamp(color,vec3(0),vec3(65000));}'
    finals=[gpu.program(prefix+final_source,vertex) for prefix in ('','#define HAS_NOISE 1\n')]
    gpu.matrix(cof,'inv_proj',inverse(projection))
    for name,value in [('focal_distance',-2),('blur_constant',1),('tan_pixel_angle',.01),
                       ('magnification',1),('max_cof',10)]: gpu.uniform(cof,name,value)
    depths=[d(2 if (x+y)%2 else 8) for y in range(IH) for x in range(IW)]
    upload(depth,depths,True)
    gpu.upload(history,[.2,.4,.6,.37]*(W*H))
    def alpha(x,y):
        x=max(0,min(IW-1,x)); y=max(0,min(IH-1,y))
        return .5 if (x+y)%2 else 0
    for jx,jy in ((0,0),(.375,.25),(-.4375,-.25)):
        for prog in [cof]+finals:
            gpu.bind(prog,'diffuseRect',0,history); gpu.bind(prog,'depthMap',1,depth)
            gpu.uniform(prog,'screen_res',W,H)
            gpu.uniform(prog,'taa_depth_jitter',jx/IW,jy/IH)
            gpu.draw(prog,output); pixels=gpu.read(output)
            for x,y in ((0,0),(W//2,H//2),(W-1,H-1)):
                px,py=(x+.5)*IW/W+jx-.5,(y+.5)*IH/H+jy-.5
                if prog==cof:
                    ix,iy=math.floor(px),math.floor(py); fx,fy=px-ix,py-iy
                    expected=((alpha(ix,iy)*(1-fx)+alpha(ix+1,iy)*fx)*(1-fy)+
                              (alpha(ix,iy+1)*(1-fx)+alpha(ix+1,iy+1)*fx)*fy)
                else:
                    ix=max(0,min(IW-1,int(px+.5))); iy=max(0,min(IH-1,int(py+.5)))
                    expected=depths[iy*IW+ix]
                check(abs(pixels[(y*W+x)*4+3]-expected)<.002, f'post depth alignment: {x,y,jx,jy}')

    # Fog also uses the render-sized corner of the larger resolve scratch.
    fog_program=gpu.program(source('volumeFogCompositeF.glsl'))
    fog=low_texture([.05,.02,.01,.6]*(IW*IH))
    upload(opaque,[.2,.4,.6,.37]*(IW*IH))
    gpu.bind(fog_program,'diffuseRect',0,opaque); gpu.bind(fog_program,'diffuseMap',1,fog)
    gpu.bind(fog_program,'depthMap',2,depth)
    gl.Viewport(0,0,IW,IH); gpu.draw(fog_program,scratch)
    gpu.bind(copy,'taa_source',0,scratch); gpu.bind(copy,'taa_original',1,current)
    gpu.uniform(copy,'taa_copy_mode',5,integer=True)
    gpu.draw(copy,opaque); pixels=read_low(opaque)
    expected=[.2*.6+.05,.4*.6+.02,.6*.6+.01,.37*.6]
    check(max(abs(value-expected[i%4]) for i,value in enumerate(pixels))<.001,
          'fog reference must stay aligned with render pixels and preserve alpha')
    gl.Viewport(0,0,W,H)

    # UI binding ensures preference Cancel and per-page Default discover the control.
    ui=ET.parse(ROOT/'indra/newview/skins/default/xui/en/panel_preferences_graphics1.xml')
    control=ui.find('.//check_box[@name="RenderTAAUpscale"]')
    check(control is not None and control.get('control_name')=='RenderTAAUpscale','bound TAAU toggle')
    print(f'PASS: {checks} TAAU GPU/integration checks ({IW}x{IH} -> {W}x{H})')


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try: run(sdl,gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx); sdl.SDL_DestroyWindow(window); sdl.SDL_Quit()
