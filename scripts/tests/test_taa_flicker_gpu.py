"""Stationary-camera HDR and faint-composition TAA flicker regressions.

Runs production GLSL through the viewer sampler bindings on a hidden SDL context.
Uses the settings from the reported case, including presentation sharpening 1.5.
Run: .venv/Scripts/python.exe scripts/tests/test_taa_flicker_gpu.py
"""
import json
import math
import statistics
from test_taa_gpu import GPU, ROOT, SHADERS, W, H, inverse, context


def run(sdl, gl):
    gpu = GPU(sdl, gl)
    resolve = gpu.program((SHADERS/'class1/deferred/taaResolveF.glsl').read_text())
    copy = gpu.program((SHADERS/'class1/deferred/taaCopyF.glsl').read_text())
    camera = gpu.program((SHADERS/'class1/deferred/taaCameraF.glsl').read_text())
    projection = [[1,0,0,0],[0,1,0,0],[0,0,-1.002002,-.2002002],[0,0,-1,0]]
    identity = [[float(r==c) for c in range(4)] for r in range(4)]
    current, opaque, history, output, vectors, presentation = [gpu.texture() for _ in range(6)]
    depth = gpu.texture(depth=True)
    roi = [y*W+x for y in range(4,H-4) for x in range(4,W-4)]
    def halton(i,b):
        f=1; v=0
        while i: f/=b; v+=f*(i%b); i//=b
        return v
    def d(z): return (1.002002-.2002002/z)*.5+.5
    for prog in (resolve,camera,copy):
        gpu.uniform(prog,'taa_rcp_res',1/W,1/H)
    gpu.matrix(camera,'taa_previous_projection',projection)
    gpu.matrix(camera,'taa_previous_from_view',identity)
    gpu.matrix(resolve,'taa_previous_inv_projection',inverse(projection))
    gpu.matrix(resolve,'taa_current_from_previous',identity)
    for uniform,value in [('taa_history_weight',.97),('taa_motion_protection',.85),
                          ('taa_clip_gamma',1.2),('taa_transparency',.5)]:
        gpu.uniform(resolve,uniform,value)
    gpu.uniform(resolve,'taa_static_details',1,integer=True)
    gpu.uniform(copy,'taa_copy_mode',1,integer=True)
    results=[]
    checks=0
    def check(condition, message):
        nonlocal checks
        assert condition, message
        checks+=1
    cases=[('bars',4,0,0),('bars',4,.01,0),('bars',4,.04,0),('bars',4,0,.25),
           ('dots',4,0,0),('dots',64,0,0),('dots',1024,0,0),('dense',4,0,0),
           ('texture',4,0,0)]
    for shape, peak, fog, texture in cases:
        frames={s:[] for s in (0,.2,1.5)}
        rejected=[]; eligible=[]; means=[]
        for frame in range(96):
            jx,jy=halton(frame%8+1,2)-.5,halton(frame%8+1,3)-.5
            colors=[]; opaques=[]; depths=[]
            for y in range(H):
                for x in range(W):
                    px=x+.5-jx; py=y+.5-jy
                    bar=abs((px-py*.018)%4.7-2.35)<.325
                    if shape=='dots': bar=bar and abs(py%4.7-2.35)<.325
                    if shape=='dense': bar=abs((px-py*.018)%1.4-.7)<.325
                    if shape=='texture': bar=(int(px*1.3)+int(py*1.3))%2==0
                    base=.05+texture*(.5+.5*math.sin(px*1.7+py*.4))
                    color=(peak,peak*.625,peak*.2) if bar else (base,base,base)
                    opaques.extend((*color,.37))
                    colors.extend((*(c*(1-fog)+.5*fog for c in color),.37))
                    depths.append(d(2 if bar or shape in ('dots','texture') else 8))
            gpu.upload(current,colors); gpu.upload(opaque,opaques); gpu.upload(depth,depths,True)
            jp=[row[:] for row in projection]
            for c in range(4):
                jp[0][c]+=2*jx/W*projection[3][c]
                jp[1][c]+=2*jy/H*projection[3][c]
            for prog in (resolve,camera):
                gpu.matrix(prog,'taa_inv_projection',inverse(jp))
                gpu.uniform(prog,'taa_jitter',jx/W,jy/H)
            gpu.bind(camera,'depthMap',0,depth); gpu.draw(camera,vectors)
            gpu.viewer_bind('resolveTAA',resolve,{'mRT->screen':current,'mTAAHistory[1 - mTAAIndex]':history,
                'mTAAMotion':vectors,'mTAAOpaque':opaque,'mRT->deferredScreen':depth})
            gpu.uniform(resolve,'taa_history_valid',int(frame>0),integer=True)
            gpu.draw(resolve,output)
            if frame>=80:
                pixels=gpu.read(output)
                rejected.extend(pixels[i*4+3]<0 for i in roi)
                metadata=gpu.read(gpu.detail_target(output))
                eligible.extend(metadata[i*4]>=0 for i in roi)
                means.append(statistics.mean(pixels[i*4]/(1+pixels[i*4]) for i in roi))
                for strength in frames:
                    gpu.viewer_bind('copyTAA',copy,{'src':output,'mMainRT.screen':current})
                    gpu.uniform(copy,'taa_jitter',jx/W,jy/H)
                    gpu.uniform(copy,'taa_sharpen',strength)
                    gpu.draw(copy,presentation); shown=gpu.read(presentation)
                    frames[strength].append([shown[i*4]/(1+shown[i*4]) for i in roi])
            history,output=output,history
        result={'shape':shape,'peak':peak,'fog':fog,'texture':texture,
                'rejected':statistics.mean(rejected),'eligible':statistics.mean(eligible),
                'mean':statistics.mean(means),
                'flicker':{s:statistics.mean(max(v)-min(v) for v in zip(*values)) for s,values in frames.items()}}
        results.append(result)
        print(json.dumps(result),flush=True)
        if shape=='bars' and texture==0:
            check(result['flicker'][1.5]<.025, 'static thin geometry must settle even under faint compositing')
            check(result['rejected']<.02, 'faint composition must not disable thin-edge history')
            foreground=peak*(1-fog)+.5*fog
            background=.05*(1-fog)+.5*fog
            expected=(.65/4.7)*foreground/(1+foreground)+(1-.65/4.7)*background/(1+background)
            check(abs(result['mean']-expected)<.012, 'stability must preserve mean detail coverage')
        if shape=='dots':
            check(result['flicker'][1.5]<.006, 'HDR specks must not dominate a bilinear footprint')
            coverage=(.65/4.7)**2
            expected=coverage*peak/(1+peak)+(1-coverage)*.05/1.05
            check(abs(result['mean']-expected)<.004, 'bright specks must retain their display-like coverage')
        if shape=='bars' and texture:
            check(result['flicker'][1.5]<.09, 'textured backgrounds must not regress')
        if shape in ('dense','texture'):
            check(result['flicker'][1.5]<.065, 'high-frequency detail must not regress')
    # A quarter-pixel of an HDR highlight should contribute a quarter of its
    # bounded color. Raw-HDR interpolation used to turn this into near-white.
    middle=(H//2)*W+W//2
    colors=[0,0,0,.37]*(W*H)
    for y in range(H):
        colors[(y*W+W//2+1)*4:(y*W+W//2+1)*4+3]=[1024]*3
    gpu.upload(current,colors); gpu.upload(opaque,colors)
    gpu.upload(depth,[d(2)]*(W*H),True)
    gpu.upload(vectors,[0,0,2,-1]*(W*H))
    gpu.matrix(resolve,'taa_inv_projection',inverse(projection))
    gpu.uniform(resolve,'taa_history_valid',0,integer=True)
    def bind_resolve():
        gpu.viewer_bind('resolveTAA',resolve,{'mRT->screen':current,'mTAAHistory[1 - mTAAIndex]':history,
            'mTAAMotion':vectors,'mTAAOpaque':opaque,'mRT->deferredScreen':depth})
    gpu.uniform(resolve,'taa_jitter',.25/W,0)
    bind_resolve(); gpu.draw(resolve,output)
    value=gpu.read(output)[middle*4]
    check(abs(value/(1+value)-.25*1024/1025)<.001,
          'current reconstruction must bound each HDR tap before interpolating')

    old=colors[:]; old[3::4]=[2]*(W*H)
    gpu.upload(history,old)
    gpu.upload(gpu.detail_target(history),[8,2,2,0]*(W*H))
    gpu.upload(vectors,[.25/W,0,2,-1]*(W*H))
    gpu.uniform(resolve,'taa_jitter',0,0)
    gpu.uniform(resolve,'taa_history_valid',1,integer=True)
    gpu.uniform(resolve,'taa_motion_protection',0)
    bind_resolve(); gpu.draw(resolve,output)
    value=gpu.read(output)[middle*4]
    check(abs(value/(1+value)-.97*.25*1024/1025)<.001,
          'history reprojection must bound each accepted HDR tap before interpolating')
    gpu.uniform(resolve,'taa_motion_protection',.85)

    # Clamp-to-edge reconstruction must keep its full weight at image borders.
    gpu.upload(current,[12,3,.5,.37]*(W*H))
    gpu.upload(opaque,[12,3,.5,.37]*(W*H))
    gpu.uniform(resolve,'taa_history_valid',0,integer=True)
    for jx,jy in ((-.49,-.49),(.49,-.49),(-.49,.49),(.49,.49)):
        gpu.uniform(resolve,'taa_jitter',jx/W,jy/H)
        bind_resolve(); gpu.draw(resolve,output)
        pixels=gpu.read(output)
        check(max(abs(value-(12,3,.5)[i%4]) for i,value in enumerate(pixels) if i%4<3)<.04,
              'jittered reconstruction must preserve flat HDR color, including image borders')
    gpu.uniform(resolve,'taa_history_valid',1,integer=True)
    gpu.uniform(resolve,'taa_jitter',0,0)

    # Sweep the old abrupt .01 cutoff, then through the fade to strong reaction.
    # Old foreground at z=2 disappeared into the known background at z=8.
    gpu.upload(current,[.3,.3,.3,.37]*(W*H))
    gpu.upload(depth,[d(8)]*(W*H),True)
    gpu.upload(vectors,[0,0,8,-1]*(W*H))
    protections=[]
    for reactive in (0,.009,.011,.03,.049,.051,.08,.15,.24,.26,1):
        compressed_opaque=.3/1.3+reactive/2
        opaque_value=compressed_opaque/(1-compressed_opaque)
        gpu.upload(opaque,([opaque_value]*3+[.37])*(W*H))
        gpu.upload(history,[2,2,2,2]*(W*H))
        gpu.upload(gpu.detail_target(history),[8,2,8,.3/1.3]*(W*H))
        gpu.uniform(resolve,'taa_debug_mode',4,integer=True)
        bind_resolve(); gpu.draw(resolve,output)
        protection=gpu.read(output)[middle*4+1]
        protections.append(protection)
        if reactive<=.049:
            check(protection>.99, 'faint composition must keep validated static-detail protection')
        elif reactive>=.26:
            check(protection==0, 'strong composition must cancel static-detail protection')
        else:
            check(0<protection<1, 'moderate reaction must fade protection smoothly')
        gpu.uniform(resolve,'taa_debug_mode',2,integer=True)
        gpu.draw(resolve,output)
        weight=gpu.read(output)[middle*4+1]
        check(weight<=.97*(1-reactive)+.002, 'detail protection must not bypass reactive blend reduction')
    check(all(a>=b for a,b in zip(protections,protections[1:])),
          'increasing reaction must never increase detail protection')

    # Weak composition cannot grant static retention to tracked animated or
    # untracked geometry. A removed static detail still expires within 9 frames.
    gpu.upload(opaque,[.32,.32,.32,.37]*(W*H))
    gpu.uniform(resolve,'taa_debug_mode',0,integer=True)
    for alpha in (0,1):
        gpu.upload(vectors,[0,0,8,alpha]*(W*H))
        bind_resolve(); gpu.draw(resolve,output)
        check(abs(gpu.read(output)[middle*4]-.3)<.001,
              'animated or untracked geometry must reject the old foreground immediately')
        check(gpu.read(gpu.detail_target(output))[middle*4]<0,
              'animated or untracked geometry must not acquire a lock')
    gpu.upload(vectors,[0,0,8,-1]*(W*H))
    gpu.upload(history,[2,2,2,2]*(W*H))
    gpu.upload(gpu.detail_target(history),[8,2,8,.3/1.3]*(W*H))
    for frame in range(9):
        bind_resolve(); gpu.draw(resolve,output)
        history,output=output,history
    check(abs(gpu.read(history)[middle*4]-.3)<.001,
          'faint composition must not extend removed-detail lifetime past one jitter cycle')
    print(f'PASS: {checks} stationary TAA flicker GPU checks')
    return {'gpu':gl.GetString(0x1F01).decode(), 'checks':checks, 'results':results}


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try:
        result=run(sdl,gl)
        (ROOT/'tmp/taa-tests').mkdir(parents=True,exist_ok=True)
        (ROOT/'tmp/taa-tests/flicker-results.json').write_text(json.dumps(result,indent=2)+'\n')
    finally:
        sdl.SDL_GL_DestroyContext(ctx); sdl.SDL_DestroyWindow(window); sdl.SDL_Quit()
