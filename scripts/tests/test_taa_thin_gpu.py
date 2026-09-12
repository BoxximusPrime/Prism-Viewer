"""Thin geometry and specular-detail TAA regressions; no viewer login."""
import statistics

from test_taa_gpu import GPU, SHADERS, W, H, inverse, context


def run(sdl, gl):
    gpu = GPU(sdl, gl)
    source = (SHADERS/'class1/deferred/taaResolveF.glsl').read_text()
    resolve = gpu.program(source)
    copy = gpu.program((SHADERS/'class1/deferred/taaCopyF.glsl').read_text())
    camera = gpu.program((SHADERS/'class1/deferred/taaCameraF.glsl').read_text())
    projection = [[1,0,0,0],[0,1,0,0],[0,0,-1.002002,-.2002002],[0,0,-1,0]]
    identity = [[float(r==c) for c in range(4)] for r in range(4)]
    current, opaque, history, output, vectors = [gpu.texture() for _ in range(5)]
    depth = gpu.texture(depth=True)
    presentation = gpu.texture()
    def halton(i,b):
        f=1; v=0
        while i: f/=b; v+=f*(i%b); i//=b
        return v
    def d(z): return (1.002002-.2002002/z)*.5+.5
    for prog in (resolve,camera):
        gpu.uniform(prog,'taa_rcp_res',1/W,1/H)
    gpu.matrix(camera,'taa_previous_projection',projection)
    gpu.matrix(camera,'taa_previous_from_view',identity)
    for name,value in [('taa_history_weight',.9),('taa_motion_protection',.85),('taa_clip_gamma',1),('taa_transparency',1)]:
        gpu.uniform(resolve,name,value)
    gpu.uniform(resolve,'taa_static_details',1,integer=True)
    roi=[y*W+x for y in range(4,H-4) for x in range(4,W-4)]
    checks=0
    def check(condition,message):
        nonlocal checks
        assert condition,message
        checks+=1
    for width,geometry,dark,enabled in ((.65,True,False,True),(1.25,True,False,True),
                                       (.3,True,False,True),(.65,False,False,True),
                                       (.65,True,True,True),(.65,True,False,False)):
        gpu.uniform(resolve,'taa_static_details',int(enabled),integer=True)
        gold=(4,2.5,.8,.37); black=(.04,.05,.06,.37)
        foreground,background=(black,gold) if dark else (gold,black)
        frames=[]; rejected=[]; presented_frames=[]
        for frame in range(80):
            jx,jy=halton(frame%8+1,2)-.5,halton(frame%8+1,3)-.5
            colors=[]; depths=[]
            for y in range(H):
                for x in range(W):
                    # Slight lean and noninteger spacing exercise all pixel phases.
                    bar=abs((x+.5-jx-(y+.5-jy)*.018)%4.7-2.35)<width*.5
                    colors.extend(foreground if bar else background)
                    depths.append(d(2 if bar or not geometry else 8))
            gpu.upload(current,colors); gpu.upload(opaque,colors); gpu.upload(depth,depths,True)
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
            if frame>=64:
                pixels=gpu.read(output)
                frames.append([pixels[i*4]/(1+pixels[i*4]) for i in roi])
                rejected.extend(pixels[i*4+3]<0 for i in roi)
                if width==.65 and geometry and not dark and enabled:
                    gpu.viewer_bind('copyTAA',copy,{'src':output,'mMainRT.screen':current})
                    gpu.uniform(copy,'taa_copy_mode',1,integer=True)
                    gpu.uniform(copy,'taa_rcp_res',1/W,1/H); gpu.uniform(copy,'taa_jitter',jx/W,jy/H)
                    gpu.uniform(copy,'taa_sharpen',.2)
                    gpu.draw(copy,presentation); shown=gpu.read(presentation)
                    presented_frames.append([shown[i*4]/(1+shown[i*4]) for i in roi])
            history,output=output,history
        # Compare in bounded display-like luminance so HDR peaks do not dominate.
        crawl=statistics.mean(max(v)-min(v) for v in zip(*frames))
        print(f'Thin bars width={width}, geometry={geometry}, dark={dark}, enabled={enabled}: crawl={crawl:.4f}, rejection={statistics.mean(rejected):.1%}')
        if enabled:
            check(crawl<.06, f'Thin detail should settle: {crawl:.4f}')
            check(statistics.mean(rejected)<.02,'static thin detail should retain history')
        else:
            check(crawl>.2,'the checkbox must disable static-detail retention')
        if presented_frames:
            presented_crawl=statistics.mean(max(v)-min(v) for v in zip(*presented_frames))
            print(f'Thin bars after default presentation sharpening: crawl={presented_crawl:.4f}')
            check(presented_crawl<crawl*1.5,'default sharpening must preserve the thin-detail stability improvement')

        # A removed static detail gets at most one jitter cycle of grace, then
        # returns to strict clipping. This must also clear HDR and dark details.
        for frame in range(9):
            gpu.upload(current,list(background)*(W*H)); gpu.upload(opaque,list(background)*(W*H))
            gpu.upload(depth,[d(8 if geometry else 2)]*(W*H),True)
            gpu.bind(camera,'depthMap',0,depth); gpu.draw(camera,vectors)
            gpu.viewer_bind('resolveTAA',resolve,{'mRT->screen':current,'mTAAHistory[1 - mTAAIndex]':history,
                'mTAAMotion':vectors,'mTAAOpaque':opaque,'mRT->deferredScreen':depth})
            gpu.draw(resolve,output); history,output=output,history
        result=gpu.read(history)
        check(max(abs(result[i*4+c]-background[c]) for i in roi for c in range(3))<.006,
              'removed static detail must clear after its eight-frame grace period')

    # Even an existing static lock cannot protect a newly covering avatar,
    # moving geometry, reactive transparency, a new depth, or changed lighting.
    gpu.uniform(resolve,'taa_static_details',1,integer=True)
    gpu.uniform(resolve,'taa_jitter',0,0)
    gpu.matrix(resolve,'taa_inv_projection',inverse(projection))
    for label,speed,alpha,z,color in (
        ('tracked avatar',0,0,8,black),('moving world',.1,-1,8,black),
        ('reactive surface',0,1,8,black),('new occluder',0,-1,1,black),
        ('changed lighting',0,-1,8,(.8,.8,.8,.37))):
        gpu.upload(current,list(color)*(W*H)); gpu.upload(opaque,list(color)*(W*H))
        gpu.upload(depth,[d(z)]*(W*H),True)
        gpu.upload(vectors,[speed/W,0,z,alpha]*(W*H))
        gpu.upload(history,[4,2.5,.8,2]*(W*H))
        gpu.upload(gpu.detail_target(history),[8,2,8,.047]*(W*H))
        gpu.viewer_bind('resolveTAA',resolve,{'mRT->screen':current,'mTAAHistory[1 - mTAAIndex]':history,
            'mTAAMotion':vectors,'mTAAOpaque':opaque,'mRT->deferredScreen':depth})
        gpu.draw(resolve,output); result=gpu.read(output)
        check(max(abs(result[i*4+c]-color[c]) for i in roi for c in range(3))<.002,
              f'{label} must cancel static retention immediately')
    print(f'PASS: {checks} thin-detail GPU checks')


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try: run(sdl,gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx); sdl.SDL_DestroyWindow(window); sdl.SDL_Quit()
