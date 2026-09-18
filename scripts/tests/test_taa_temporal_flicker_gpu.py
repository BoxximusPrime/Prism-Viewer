"""Multi-frame luminance detection through the production resolve and bindings.

Run: .venv/Scripts/python.exe scripts/tests/test_taa_temporal_flicker_gpu.py
Tests spatially uniform aliasing which has no neighborhood contrast to protect.
"""
import json
import statistics
from test_taa_gpu import GPU, ROOT, SHADERS, W, H, inverse, context


def run(sdl,gl):
    gpu=GPU(sdl,gl)
    shader=gpu.program((SHADERS/'class1/deferred/taaResolveF.glsl').read_text())
    copy=gpu.program((SHADERS/'class1/deferred/taaCopyF.glsl').read_text())
    projection=[[1,0,0,0],[0,1,0,0],[0,0,-1.002002,-.2002002],[0,0,-1,0]]
    identity=[[float(r==c) for c in range(4)] for r in range(4)]
    for name in ('taa_inv_projection','taa_previous_inv_projection'): gpu.matrix(shader,name,inverse(projection))
    gpu.matrix(shader,'taa_current_from_previous',identity)
    for p in (shader,copy): gpu.uniform(p,'taa_rcp_res',1/W,1/H);gpu.uniform(p,'taa_jitter',0,0)
    for name,value in [('taa_history_weight',.76),('taa_motion_protection',.85),('taa_clip_gamma',1.2),('taa_transparency',.5)]:
        gpu.uniform(shader,name,value)
    gpu.uniform(shader,'taa_static_details',1,integer=True)
    gpu.uniform(copy,'taa_copy_mode',1,integer=True);gpu.uniform(copy,'taa_sharpen',1.5)
    current,opaque,motion,shown,debug=[gpu.texture() for _ in range(5)]
    depth=gpu.texture(depth=True)
    def d(z): return (1.002002-.2002002/z)*.5+.5
    roi=[y*W+x for y in range(4,H-4) for x in range(4,W-4)]
    middle=(H//2*W+W//2)*4
    checks=0
    def check(value,message):
        nonlocal checks
        assert value,message
        checks+=1
    def bind(history):
        gpu.viewer_bind('resolveTAA',shader,{'mRT->screen':current,'mTAAHistory[1 - mTAAIndex]':history,
            'mTAAMotion':motion,'mTAAOpaque':opaque,'mRT->deferredScreen':depth})
    def upload(value,z=8,alpha=-1,speed=0,reference=None):
        colors=[value,value,value,.37]*(W*H) if isinstance(value,(int,float)) else value
        gpu.upload(current,colors)
        gpu.upload(opaque,colors if reference is None else [reference,reference,reference,.37]*(W*H))
        gpu.upload(depth,[d(z)]*(W*H),True)
        gpu.upload(motion,[speed/W,0,z,alpha]*(W*H))
    def frame(history,output,value,valid=True,**kwargs):
        upload(value,**kwargs);bind(history)
        gpu.uniform(shader,'taa_debug_mode',0,integer=True)
        gpu.uniform(shader,'taa_history_valid',int(valid),integer=True)
        gpu.draw(shader,output)
        return output,history
    def measure(history):
        gpu.viewer_bind('copyTAA',copy,{'src':history,'mMainRT.screen':current})
        gpu.draw(copy,shown)
        pixels=gpu.read(shown)
        return [pixels[i*4]/(1+pixels[i*4]) for i in roi]
    results=[]
    patterns={'alternating':[.04,.8], 'repeated impulses':[.8]+[.04]*7,
              'eight-phase shading':[.4,.1,.8,.03,.6,.2,.95,.07]}
    for name,pattern in patterns.items():
        variants={}
        for enabled in (0,1):
            history,output=gpu.texture(),gpu.texture()
            gpu.uniform(shader,'taa_flicker_detection',enabled,integer=True)
            samples=[]
            for i in range(160):
                history,output=frame(history,output,pattern[i%len(pattern)],valid=i>0)
                if i>=128:samples.append(measure(history))
            variation=statistics.mean(max(v)-min(v) for v in zip(*samples))
            mean=statistics.mean(map(statistics.mean,samples))
            truth=statistics.mean(v/(1+v) for v in pattern)
            state=gpu.read(gpu.detail_target(history,2))[middle:middle+4]
            result={'pattern':name,'enabled':bool(enabled),'variation':variation,'mean':mean,'reference_mean':truth,'state':state}
            print(json.dumps(result),flush=True);results.append(result);variants[enabled]=result
            check(abs(mean-truth)<.012,'detection must preserve temporal mean brightness')
            if enabled:
                check(state[2]>=3,'repeated changes must build detector confidence')
                # Once the signal settles, its protection and old color expire.
                for _ in range(10):history,output=frame(history,output,.17)
                pixels=gpu.read(history);state=gpu.read(gpu.detail_target(history,2))
                check(max(abs(pixels[i*4]-.17) for i in roi)<.001,'settled shading must clear old color within ten frames')
                check(max(state[i*4+2] for i in roi)==0,'quiet shading must release flicker protection')
                # Old oscillation direction must expire too: an isolated flash
                # after a quiet interval must learn from scratch.
                strength=[]
                for value in (.8,.17):
                    history,output=frame(history,output,value)
                    strength.append(gpu.read(gpu.detail_target(history,2))[middle+2])
                check(max(strength)<=1,'a later isolated flash must not reuse expired evidence')
        check(variants[1]['variation']<variants[0]['variation']*.3,'temporal detection must reduce uniform aliasing by at least 70%')

    # Detection confidence is not an incremental contribution. A high-contrast
    # pattern can already have full static clipping protection, so a green
    # flicker diagnostic must coexist with identical normal output on/off.
    gpu.uniform(shader,'taa_flicker_detection',1,integer=True)
    history,output=gpu.texture(),gpu.texture()
    checker=lambda phase: [v for y in range(H) for x in range(W) for v in
                          ((.8 if (x+y+phase)%2 else .04),)*3+(.37,)]
    for i in range(32):history,output=frame(history,output,checker(i),valid=i>0)
    upload(checker(32));bind(history)
    gpu.uniform(shader,'taa_debug_mode',6,integer=True);gpu.draw(shader,debug)
    confidence=gpu.read(debug)[middle+1]
    check(confidence>.99,'existing detail protection must not hide detected flicker')
    gpu.uniform(shader,'taa_flicker_detection',0,integer=True)
    gpu.uniform(shader,'taa_debug_mode',4,integer=True);bind(history);gpu.draw(shader,debug)
    check(gpu.read(debug)[middle+1]>.99,'this pattern must already have full clipping protection')
    gpu.uniform(shader,'taa_debug_mode',2,integer=True);gpu.draw(shader,debug)
    check(abs(gpu.read(debug)[middle+1]-.97)<.001,'existing protection must already use the static history limit')
    presentations=[]
    for enabled in (0,1):
        bind(history);gpu.uniform(shader,'taa_debug_mode',0,integer=True)
        gpu.uniform(shader,'taa_flicker_detection',enabled,integer=True)
        gpu.draw(shader,output);presentations.append(measure(output))
    difference=max(abs(a-b) for a,b in zip(*presentations))
    check(difference==0,'redundant clipping protection must leave normal presentation unchanged')
    print(json.dumps({'pattern':'already protected checker','detector_confidence':confidence,
                      'presentation_difference':difference}),flush=True)

    # Warm a genuine learned state for each cancellation scenario.
    for label,kwargs in [('animated',{'alpha':0}),('untracked',{'alpha':1}),
                         ('moving',{'speed':5}),('new surface',{'z':2}),
                         ('reactive overlay',{'reference':0}),('camera cut',{'valid':False})]:
        gpu.uniform(shader,'taa_flicker_detection',1,integer=True)
        history,output=gpu.texture(),gpu.texture()
        for i in range(20):history,output=frame(history,output,[.04,.8][i%2],valid=i>0)
        history,output=frame(history,output,.6,**kwargs)
        pixels=gpu.read(history);state=gpu.read(gpu.detail_target(history,2))
        check(max(abs(pixels[i*4]-.6) for i in roi)<.002,f'{label} must cancel stale color')
        check(max(state[i*4+2] for i in roi)<=0,f'{label} must reset detection')

    # A single flash and a monotonic light fade cannot build repeated reversals.
    for name,values in [('single flash',[.1]*8+[.8]+[.1]*20),
                        ('light fade',[.02+i*.01 for i in range(40)])]:
        history,output=gpu.texture(),gpu.texture();strength=[]
        for i,value in enumerate(values):
            history,output=frame(history,output,value,valid=i>0)
            state=gpu.read(gpu.detail_target(history,2));strength.append(state[middle+2])
        check(max(strength)<=1,f'{name} must not activate flicker protection')

    # Disabled detection clears its metadata; re-enabling must learn afresh.
    gpu.uniform(shader,'taa_flicker_detection',0,integer=True)
    history,output=frame(history,output,.8)
    check(gpu.read(gpu.detail_target(history,2))[middle+2]<0,'disabled detector must invalidate its state')
    gpu.uniform(shader,'taa_flicker_detection',1,integer=True)
    history,output=frame(history,output,.04)
    check(gpu.read(gpu.detail_target(history,2))[middle+2]==0,'re-enabled detector must start without stale evidence')
    print(f'PASS: {checks} temporal flicker GPU checks')
    return {'checks':checks,'gpu':gl.GetString(0x1F01).decode(),'results':results}


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try:
        result=run(sdl,gl)
        path=ROOT/'tmp/taa-tests/temporal-flicker-results.json'
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(result,indent=2)+'\n')
    finally:
        sdl.SDL_GL_DestroyContext(ctx);sdl.SDL_DestroyWindow(window);sdl.SDL_Quit()
