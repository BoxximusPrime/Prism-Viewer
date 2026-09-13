"""Production-shader regressions for subpixel motion and TAA history validation.

Measures a static thin-line pattern and a tiny oscillating camera translation.
Uses repository defaults; does not change shaders or viewer preferences.
"""
import json
from pathlib import Path
import statistics
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/tests'))
from test_taa_gpu import GPU, SHADERS, W, H, inverse, context


def run(sdl, gl):
    gpu = GPU(sdl, gl)
    settings = ET.parse(ROOT / 'indra/newview/app_settings/settings.xml').getroot().find('map')
    nodes = list(settings)
    defaults = {}
    for key, value in zip(nodes[::2], nodes[1::2]):
        entries = list(value)
        for k, v in zip(entries[::2], entries[1::2]):
            if k.text == 'Value' and key.text.startswith('RenderTAA'):
                defaults[key.text] = float(v.text)
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
    gpu.matrix(resolve,'taa_previous_inv_projection',inverse(projection))
    for uniform, setting in [('taa_history_weight','RenderTAAHistoryWeight'),
                             ('taa_motion_protection','RenderTAAMotionProtection'),
                             ('taa_clip_gamma','RenderTAAClipGamma'),
                             ('taa_transparency','RenderTAATransparency')]:
        gpu.uniform(resolve,uniform,defaults[setting])
    gpu.uniform(resolve,'taa_static_details',1,integer=True)
    gpu.uniform(copy,'taa_copy_mode',1,integer=True)
    results=[]
    checks=0
    def check(condition, message):
        nonlocal checks
        assert condition, message
        checks+=1
    # Alpha -1: static eligibility; 0: tracked but ineligible surface. Constant
    # depth isolates color clipping from geometric disocclusion. Two depths
    # additionally exercise the silhouette path used by the existing tests.
    for geometry, amplitude, alpha in [(True,0,-1),(True,.004,-1),(True,.006,-1),(True,0,0),(False,0,-1),
                                       (False,.004,-1),(False,.006,-1),
                                       (False,0,0)]:
        frames={s:[] for s in (0,.2,defaults['RenderTAASharpen'])}
        rejected=[]; eligible=[]; previous_shift=0
        for frame in range(96):
            jx,jy=halton(frame%8+1,2)-.5,halton(frame%8+1,3)-.5
            shift=amplitude if frame%2 else -amplitude
            colors=[]; depths=[]
            for y in range(H):
                for x in range(W):
                    bar=abs((x+.5-jx+shift-(y+.5-jy)*.018)%4.7-2.35)<.65*.5
                    colors.extend((4,2.5,.8,.37) if bar else (.04,.05,.06,.37))
                    depths.append(d(2 if bar or not geometry else 8))
            gpu.upload(current,colors); gpu.upload(opaque,colors); gpu.upload(depth,depths,True)
            jp=[row[:] for row in projection]
            for c in range(4):
                jp[0][c]+=2*jx/W*projection[3][c]
                jp[1][c]+=2*jy/H*projection[3][c]
            moved=[row[:] for row in identity]
            moved[0][3]=(shift-previous_shift)*4/W  # z=2 plane
            gpu.matrix(camera,'taa_previous_from_view',moved)
            gpu.matrix(resolve,'taa_current_from_previous',inverse(moved))
            for prog in (resolve,camera):
                gpu.matrix(prog,'taa_inv_projection',inverse(jp))
                gpu.uniform(prog,'taa_jitter',jx/W,jy/H)
            gpu.bind(camera,'depthMap',0,depth); gpu.draw(camera,vectors)
            if alpha==0:
                motion_values=gpu.read(vectors)
                motion_values[3::4]=[0]*(W*H)
                gpu.upload(vectors,motion_values)
            gpu.viewer_bind('resolveTAA',resolve,{'mRT->screen':current,'mTAAHistory[1 - mTAAIndex]':history,
                'mTAAMotion':vectors,'mTAAOpaque':opaque,'mRT->deferredScreen':depth})
            gpu.uniform(resolve,'taa_history_valid',int(frame>0),integer=True)
            gpu.draw(resolve,output)
            if frame>=80:
                pixels=gpu.read(output)
                rejected.extend(pixels[i*4+3]<0 for i in roi)
                metadata=gpu.read(gpu.detail_target(output))
                eligible.extend(metadata[i*4]>=0 for i in roi)
                for strength in frames:
                    gpu.viewer_bind('copyTAA',copy,{'src':output,'mMainRT.screen':current})
                    gpu.uniform(copy,'taa_jitter',jx/W,jy/H)
                    gpu.uniform(copy,'taa_sharpen',strength)
                    gpu.draw(copy,presentation); shown=gpu.read(presentation)
                    frames[strength].append([shown[i*4]/(1+shown[i*4]) for i in roi])
            previous_shift=shift
            history,output=output,history
        result={'geometry':geometry,'camera_oscillation_amplitude_pixels':amplitude,
                'motion_alpha':alpha,'history_rejection_fraction':statistics.mean(rejected),
                'static_eligible_fraction':statistics.mean(eligible),
                'mean_peak_to_peak':{str(s):statistics.mean(max(v)-min(v) for v in zip(*values))
                                     for s,values in frames.items()}}
        results.append(result)
        print(json.dumps(result),flush=True)
        if alpha<0:
            check(result['mean_peak_to_peak']['0']<.035, 'tiny camera movement must preserve thin detail')
            check(result['history_rejection_fraction']<.02, 'camera subpixel motion must not reset thin-edge history')
        else:
            check(result['static_eligible_fraction']==0, 'unqualified geometry must not acquire detail locks')

    # A feature moves one whole pixel, and its metadata must follow its color.
    # Current view depth differs from previous view depth as well.
    middle=(H//2)*W+W//2
    dark=[.05,.05,.05,.37]*(W*H)
    gpu.upload(current,dark); gpu.upload(opaque,dark); gpu.upload(depth,[d(9)]*(W*H),True)
    gpu.upload(vectors,[1/W,0,8,-1]*(W*H))
    old=[.05,.05,.05,8]*(W*H); old[(middle+1)*4:(middle+1)*4+4]=[2,2,2,2]
    metadata=[-1,0,0,0]*(W*H); metadata[(middle+1)*4:(middle+1)*4+4]=[8,2,8,.05/1.05]
    gpu.upload(history,old); gpu.upload(gpu.detail_target(history),metadata)
    gpu.uniform(resolve,'taa_jitter',0,0)
    gpu.matrix(resolve,'taa_inv_projection',inverse(projection))
    current_from_previous=[r[:] for r in identity]; current_from_previous[2][3]=-1
    gpu.matrix(resolve,'taa_current_from_previous',current_from_previous)
    def bind_resolve():
        gpu.viewer_bind('resolveTAA',resolve,{'mRT->screen':current,'mTAAHistory[1 - mTAAIndex]':history,
            'mTAAMotion':vectors,'mTAAOpaque':opaque,'mRT->deferredScreen':depth})
    bind_resolve(); gpu.draw(resolve,output)
    pixel=gpu.read(output)[middle*4:middle*4+4]
    detail=gpu.read(gpu.detail_target(output))[middle*4:middle*4+4]
    print('Reprojected detail:',pixel,detail)
    check(pixel[0]>.1,'one-pixel reprojection must carry protected color instead of the .05 background alone')
    check(abs(detail[0]-7)<.01,'reprojected missing detail lifetime must decrement')
    check(abs(detail[1]-3)<.01 and abs(detail[2]-9)<.01,'retained surface depths must transform into current view space')

    # Reject invalid taps before color filtering. Use two different invalid
    # colors and require the same result, with some valid history surviving.
    gpu.matrix(resolve,'taa_current_from_previous',identity)
    gpu.upload(depth,[d(2)]*(W*H),True); gpu.upload(vectors,[.25/W,0,2,0]*(W*H))
    colors=[.2,.4,.6,.37]*(W*H)
    for y in range(H//2-1,H//2+2):
        for x in range(W//2-1,W//2+2):
            colors[(y*W+x)*4:(y*W+x)*4+3]=[float((x+y)%2)]*3
    gpu.upload(current,colors); gpu.upload(opaque,colors)
    gpu.uniform(resolve,'taa_clip_gamma',2)
    samples=[]
    for invalid in ([1,0,0,1],[0,1,0,1]):
        old=[.2,.4,.6,2]*(W*H); old[(middle+1)*4:(middle+1)*4+4]=invalid
        gpu.upload(history,old); bind_resolve(); gpu.draw(resolve,output)
        samples.append(gpu.read(output)[middle*4:middle*4+4])
    check(samples[0][3]>0,'a partial footprint must reuse valid history')
    check(max(abs(a-b) for a,b in zip(*samples))<.001,'invalid depth colors must not leak into the gather')
    gpu.uniform(resolve,'taa_debug_mode',2,integer=True); gpu.draw(resolve,output)
    weight=gpu.read(output)[middle*4+1]
    check(0<weight<defaults['RenderTAAHistoryWeight']*.8,'partial support must reduce actual history weight')
    for mode in (3,4,5):
        gpu.uniform(resolve,'taa_debug_mode',mode,integer=True); gpu.draw(resolve,output)
        value=gpu.read(output)[middle*4:middle*4+4]
        check(all(0<=v<=1 for v in value),'diagnostics must be finite and bounded')
    # Every tap mismatches: reject completely, including when depth denotes sky.
    gpu.upload(history,[2,0,0,1]*(W*H))
    for z in (2,0):
        gpu.upload(vectors,[0,0,z,0]*(W*H))
        gpu.upload(depth,[d(z) if z else 1]*(W*H),True)
        gpu.uniform(resolve,'taa_debug_mode',2,integer=True); bind_resolve(); gpu.draw(resolve,output)
        check(gpu.read(output)[middle*4:middle*4+3]==[1,0,0],'zero support must show zero weight, even on sky')
    gpu.uniform(resolve,'taa_debug_mode',0,integer=True)
    print(f'PASS: {checks} TAA stability GPU checks')
    return {'gpu':gl.GetString(0x1F01).decode(),'defaults':defaults,'results':results,
            'metric':'Mean per-pixel peak-to-peak red/(1+red), final 16 of 96 frames; 0.65px bars; no CAS or viewer tonemapping.'}


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try:
        result=run(sdl,gl)
        target=ROOT/'tmp/taa-tests/stability-results.json'
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(result,indent=2)+'\n')
    finally:
        sdl.SDL_GL_DestroyContext(ctx); sdl.SDL_DestroyWindow(window); sdl.SDL_Quit()
