"""Static textured slats and layered cutout foliage through production TAA.

Run: .venv/Scripts/python.exe scripts/tests/test_taa_fine_details_gpu.py
Optional --reference PATH compares an older resolve with identical inputs.
Measures TAA sharpening at shipped settings, including exposure-normalized dark
details. This is a display-brightness proxy, not the viewer's full tonemapper.
"""
import argparse
import json
import math
from pathlib import Path
import statistics
import xml.etree.ElementTree as ET

from test_taa_gpu import GPU, ROOT, SHADERS, W, H, inverse, context


def halton(i, base):
    factor = 1; value = 0
    while i:
        factor /= base; value += factor*(i % base); i //= base
    return value


def run(sdl, gl, reference=None):
    gpu = GPU(sdl, gl)
    source = (SHADERS/'class1/deferred/taaResolveF.glsl').read_text()
    programs = {'current':gpu.program(source)}
    if reference: programs['reference'] = gpu.program(reference.read_text())
    copy = gpu.program((SHADERS/'class1/deferred/taaCopyF.glsl').read_text())
    camera = gpu.program((SHADERS/'class1/deferred/taaCameraF.glsl').read_text())
    nodes = list(ET.parse(ROOT/'indra/newview/app_settings/settings.xml').getroot().find('map'))
    defaults = {}
    for key, value in zip(nodes[::2], nodes[1::2]):
        if key.text.startswith('RenderTAA'):
            fields = dict(zip(list(value)[::2],list(value)[1::2]))
            defaults[key.text] = float(next(v.text for k,v in fields.items() if k.text=='Value'))
    projection = [[1,0,0,0],[0,1,0,0],[0,0,-1.002002,-.2002002],[0,0,-1,0]]
    identity = [[float(r==c) for c in range(4)] for r in range(4)]
    current, opaque, vectors, presentation, scratch = [gpu.texture() for _ in range(5)]
    depth = gpu.texture(depth=True)
    roi = [y*W+x for y in range(4,H-4) for x in range(4,W-4)]
    checks = 0
    def check(condition, message):
        nonlocal checks
        assert condition, message
        checks += 1
    def depth_value(z): return (1.002002-.2002002/z)*.5+.5
    def bind_resolve(prog, history):
        gpu.viewer_bind('resolveTAA',prog,{'mRT->screen':current,'mTAAHistory[1 - mTAAIndex]':history,
            'mTAAMotion':vectors,'mTAAOpaque':opaque,'mRT->deferredScreen':depth})
    def bounded(pixels): return [pixels[i*4]/(light+pixels[i*4]) for i in roi]
    def compressed(pixels):
        return [pixels[i*4+c]/(1+max(pixels[i*4:i*4+3])) for i in roi for c in range(3)]
    def flicker(frames):
        values = [max(v)-min(v) for v in zip(*frames)]
        return {'mean':statistics.mean(values),'p95':sorted(values)[int(len(values)*.95)],'max':max(values)}
    for prog in (*programs.values(),camera,copy): gpu.uniform(prog,'taa_rcp_res',1/W,1/H)
    gpu.matrix(camera,'taa_previous_projection',projection)
    gpu.matrix(camera,'taa_previous_from_view',identity)
    gpu.uniform(copy,'taa_copy_mode',1,integer=True)
    gpu.uniform(copy,'taa_sharpen',defaults['RenderTAASharpen'])
    for prog in programs.values():
        gpu.matrix(prog,'taa_previous_inv_projection',inverse(projection))
        gpu.matrix(prog,'taa_current_from_previous',identity)
        gpu.uniform(prog,'taa_static_details',1,integer=True)
        for uniform,setting in [('taa_history_weight','RenderTAAHistoryWeight'),
                                ('taa_motion_protection','RenderTAAMotionProtection'),
                                ('taa_clip_gamma','RenderTAAClipGamma'),
                                ('taa_transparency','RenderTAATransparency')]:
            gpu.uniform(prog,uniform,defaults[setting])

    results = []
    cases=[(shape,width,1) for shape,width in
           [('slats',.65),('slats',1),('slats',3),('slats',5),('leaves',1)]]
    cases += [(shape,width,light) for light in (.1,.01) for shape,width in [('slats',.65),('leaves',1)]]
    cases += [('wires',.3,.1)]
    for shape,width,light in cases:
        inputs = []
        for phase in range(8):
            jx,jy = halton(phase+1,2)-.5,halton(phase+1,3)-.5
            colors=[]; backgrounds=[]; depths=[]
            for y in range(H):
                for x in range(W):
                    px,py = x+.5-jx,y+.5-jy
                    base = .05+.25*(.5+.5*math.sin(px*1.7+py*.4))
                    background = (base,base*.8,base*.65,.37)
                    bar = abs((px-py*.018)%(width+4.05)-(width+4.05)*.5)<width*.5
                    foreground = (1,.625,.2,.37)
                    front_depth = 30
                    if shape=='leaves':
                        gx,gy = int(px/5.3),int(py/4.7)
                        variation = (gx*13+gy*7)%11/11
                        cx,cy = px%5.3-2.65,py%4.7-2.35
                        bar = ((cx+.6*cy)/(1.1+variation))**2+(cy/(.45+variation*.6))**2<1
                        foreground = (.1+variation*.4,.22+variation*.55,.04+variation*.09,.37)
                        front_depth = 30+variation*5
                    if shape=='wires':
                        background=(.3,.45,.7,.37)
                        foreground=(.02,.02,.02,.37)
                        bar=abs((py-px*.12)%5.3-2.65)<width*.5
                    foreground=tuple(c*light for c in foreground[:3])+(.37,)
                    background=tuple(c*light for c in background[:3])+(.37,)
                    colors.extend(foreground if bar else background)
                    backgrounds.extend(background)
                    depths.append(1 if shape=='wires' and not bar else depth_value(front_depth if bar else 50))
            jp = [row[:] for row in projection]
            for c in range(4):
                jp[0][c] += 2*jx/W*projection[3][c]
                jp[1][c] += 2*jy/H*projection[3][c]
            inputs.append((jx,jy,colors,backgrounds,depths,inverse(jp)))
        case_results = {}
        for label,prog in programs.items():
            history,output = gpu.texture(),gpu.texture()
            samples=[]; shown_samples=[]; reference_samples=[]; weights=[]
            for frame in range(144):
                jx,jy,colors,backgrounds,depths,inv = inputs[frame%8]
                gpu.upload(current,colors); gpu.upload(opaque,colors); gpu.upload(depth,depths,True)
                for p in (prog,camera):
                    gpu.uniform(p,'taa_jitter',jx/W,jy/H)
                    gpu.matrix(p,'taa_inv_projection',inv)
                gpu.bind(camera,'depthMap',0,depth); gpu.draw(camera,vectors)
                bind_resolve(prog,history)
                gpu.uniform(prog,'taa_history_valid',int(frame>0),integer=True)
                gpu.draw(prog,output)
                if frame<8:
                    # Average all unaccumulated jitter phases as a coverage and
                    # spatial-contrast reference: deleting/blurring lines fails.
                    gpu.uniform(prog,'taa_history_valid',0,integer=True)
                    gpu.draw(prog,scratch); reference_samples.append(compressed(gpu.read(scratch)))
                if frame>=128:
                    pixels=gpu.read(output)
                    samples.append(bounded(pixels))
                    # Read the actual blend diagnostic, including sky where
                    # negative zero depth cannot encode a rejection sign.
                    gpu.uniform(prog,'taa_debug_mode',2,integer=True)
                    gpu.draw(prog,scratch); debug=gpu.read(scratch)
                    weights.extend(debug[i*4+1] for i in roi)
                    gpu.uniform(prog,'taa_debug_mode',0,integer=True)
                    gpu.viewer_bind('copyTAA',copy,{'src':output,'mMainRT.screen':current})
                    gpu.uniform(copy,'taa_jitter',jx/W,jy/H)
                    gpu.draw(copy,presentation); shown_samples.append(bounded(gpu.read(presentation)))
                history,output = output,history
            averages = list(map(statistics.mean,zip(*samples)))
            # Average in the resolve's accumulation space, then expose/convert
            # once. Averaging already-tonemapped phases would give a biased
            # reference as lighting changes (the conversion is nonlinear).
            reference_color=list(map(statistics.mean,zip(*reference_samples)))
            truth=[]
            for i in range(0,len(reference_color),3):
                rgb=reference_color[i:i+3]
                red=rgb[0]/(1-max(rgb))
                truth.append(red/(light+red))
            result = {'shape':shape,'width':width,'light':light,'variant':label,'flicker':flicker(samples),
                      'sharpened':flicker(shown_samples),'mean':statistics.mean(averages),
                      'contrast':statistics.pstdev(averages),'reference_mean':statistics.mean(truth),
                      'reference_contrast':statistics.pstdev(truth),'history_weight':statistics.mean(weights),
                      'rejected':statistics.mean(w<.05 for w in weights)}
            results.append(result); case_results[label] = result
            print(json.dumps(result),flush=True)
            if label=='current':
                check(result['sharpened']['mean']<.012,'fine detail must settle at shipped settings, including sharpening')
                check(result['sharpened']['max']<.08,'isolated flashing pixels must settle too')
                check(result['rejected']<.01 and result['history_weight']>.95,
                      'static coverage must retain history, including sky silhouettes')
                check(abs(result['mean']-result['reference_mean'])<.006,'stability must preserve mean coverage')
                check(.94<result['contrast']/result['reference_contrast']<1.06,'stability must preserve spatial contrast')

                # Remove the foreground but keep high-contrast wall texture.
                # Texture contrast must not refresh a disappeared surface's lock.
                for frame in range(9):
                    jx,jy,colors,backgrounds,depths,inv = inputs[frame%8]
                    gpu.upload(current,backgrounds); gpu.upload(opaque,backgrounds)
                    gpu.upload(depth,[1 if shape=='wires' else depth_value(50)]*(W*H),True)
                    for p in (prog,camera):
                        gpu.uniform(p,'taa_jitter',jx/W,jy/H); gpu.matrix(p,'taa_inv_projection',inv)
                    gpu.bind(camera,'depthMap',0,depth); gpu.draw(camera,vectors)
                    bind_resolve(prog,history); gpu.draw(prog,output)
                    history,output = output,history
                pixels=gpu.read(history); metadata=gpu.read(gpu.detail_target(history))
                if shape=='wires':
                    check(max(abs(pixels[i*4+c]-(.3,.45,.7)[c]*light) for i in roi for c in range(3))<.002*light,
                          'removed dark wires must clear from the sky')
                else:
                    check(max(pixels[i*4+c] for i in roi for c in range(3))<.302*light,
                          'removed foreground color must clear even on a textured background')
                check(all(abs(metadata[i*4+1]-(0 if shape=='wires' else 50))<1 for i in roi),
                      'expired foreground depths must not keep renewing from background texture')
        if reference:
            before,after = case_results['reference'],case_results['current']
            check(after['sharpened']['mean']<before['sharpened']['mean']*1.05+.0003,
                  'average variation must not regress against the supplied reference')
            check(after['sharpened']['max']<before['sharpened']['max']*1.05+.001,
                  'the worst individual flashing pixel must not regress')

    # The base-weight slider still controls unprotected/animated surfaces. Static
    # confidence, reactive shading, new occluders and a disabled checkbox retain
    # their rejection authority over the stronger stationary accumulation.
    prog=programs['current']; history=gpu.texture(); output=gpu.texture()
    checker=[v for y in range(H) for x in range(W) for v in ((.8,.8,.8,.37) if (x+y)%2 else (.04,.04,.04,.37))]
    gpu.upload(current,checker); gpu.upload(opaque,checker)
    gpu.upload(depth,[depth_value(2)]*(W*H),True)
    gpu.upload(history,[.3,.3,.3,2]*(W*H))
    gpu.upload(gpu.detail_target(history),[8,2,2,.04/1.04]*(W*H))
    gpu.matrix(prog,'taa_inv_projection',inverse(projection))
    gpu.uniform(prog,'taa_jitter',0,0); gpu.uniform(prog,'taa_history_valid',1,integer=True)
    gpu.uniform(prog,'taa_debug_mode',2,integer=True)
    center=(H//2*W+W//2)*4
    for weight in (.5,.76,.9,.97):
        gpu.uniform(prog,'taa_history_weight',weight)
        for enabled,alpha in ((1,-1),(0,-1),(1,0),(1,1)):
            gpu.uniform(prog,'taa_static_details',enabled,integer=True)
            gpu.upload(vectors,[0,0,2,alpha]*(W*H)); bind_resolve(prog,history); gpu.draw(prog,output)
            actual=gpu.read(output)[center+1]
            expected=0 if alpha==1 else .97 if enabled and alpha<0 else weight
            check(abs(actual-expected)<.001,'base slider, static boost, animation and reactivity must remain independent')
    gpu.uniform(prog,'taa_history_weight',.76)
    for label,speed,alpha,z in [('fast motion',4.1,-1,2),('untracked',0,1,2),('new occluder',0,-1,1)]:
        gpu.upload(depth,[depth_value(z)]*(W*H),True)
        gpu.upload(vectors,[speed/W,0,z,alpha]*(W*H)); bind_resolve(prog,history); gpu.draw(prog,output)
        check(gpu.read(output)[center+1]<=.761,f'{label} must never acquire boosted accumulation')

    # Contrast-relative eligibility must not preserve stale dim colors through
    # a real lighting change, or let a vanished surface's expired lock linger.
    gpu.uniform(prog,'taa_debug_mode',0,integer=True)
    for light in (1,.1,.01):
        gpu.upload(depth,[depth_value(8)]*(W*H),True)
        gpu.upload(vectors,[0,0,8,-1]*(W*H))
        for expired in (False,True):
            colors=[v for y in range(H) for x in range(W) for v in
                    ((.2*light,)*3+(.37,) if not expired or (x+y)%2 else (.04*light,)*3+(.37,))]
            gpu.upload(current,colors);gpu.upload(opaque,colors)
            gpu.upload(history,[.15*light,.15*light,.15*light,8 if expired else 2]*(W*H))
            gpu.upload(gpu.detail_target(history),[-2 if expired else 8,2,8,.04*light/(1+.04*light)]*(W*H))
            bind_resolve(prog,history);gpu.draw(prog,output)
            actual=gpu.read(output)
            check(max(abs(actual[i*4+c]-colors[i*4+c])/light for i in roi for c in range(3))<.002,
                  'expired details and lighting changes must clear at every tested brightness')
    print(f'PASS: {checks} fine-detail TAA GPU checks')
    return {'gpu':gl.GetString(0x1F01).decode(),'checks':checks,'defaults':defaults,'results':results}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--reference',type=Path)
    args=parser.parse_args()
    sdl,window,ctx,gl = context()
    try:
        result=run(sdl,gl,args.reference)
        target=ROOT/'tmp/taa-tests/fine-detail-results.json'
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(result,indent=2)+'\n')
    finally:
        sdl.SDL_GL_DestroyContext(ctx); sdl.SDL_DestroyWindow(window); sdl.SDL_Quit()
