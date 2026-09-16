"""TAA opaque-reference ordering, haze, fog and actual transparency regressions.

Runs the production haze, fog-composite and TAA shaders in a hidden GL context.
Compares the original pre-lighting reference against the corrected reference.
Run: .venv/Scripts/python.exe scripts/tests/test_taa_composition_gpu.py
"""
import ctypes as C
import json
import statistics

from test_taa_gpu import GPU, ROOT, SHADERS, W, H, inverse, context, U


def run(sdl, gl):
    gpu=GPU(sdl,gl)
    checks=0
    def check(condition,message):
        nonlocal checks
        assert condition,message
        checks+=1

    # These integration contracts are what a resolve-only scene cannot test:
    # the opaque reference must include opaque post-deferred passes and receive
    # the same lighting as the displayed scene, while excluding blended pools.
    pipeline=(ROOT/'indra/newview/pipeline.cpp').read_text()
    def method(name):
        return pipeline.split('LLPipeline::'+name+'(',1)[1].split('\n}\n',1)[0]
    post=method('renderGeomPostDeferred')
    check(post.index('doWaterHaze();')<post.index('captureTAAOpaque();')<post.index('poolp->beginPostDeferredPass(i);'),
          'opaque capture must follow water haze and precede the first blended pool')
    check('cur_type >= LLDrawPool::POOL_ALPHA_PRE_WATER && !done_taa_opaque' in post,
          'capture must wait until fullbright and masked opaque pools have rendered')
    check(pipeline.count('captureTAAOpaque();')==post.count('captureTAAOpaque();'),
          'an earlier capture must not restore the pre-lighting reference')
    haze_code=method('doAtmospherics')
    check(haze_code.index('mTAAOpaque.bindTarget();')<haze_code.rindex('mScreenTriangleVB->drawArrays(')<haze_code.index('mTAAOpaque.flush();'),
          'the opaque reference must receive atmospheric haze')
    fog_code=method('renderVolumeFog')
    check('composite_fog(mTAAOpaque, mTAAResolved);' in fog_code and 'copyTAA(mTAAResolved, mTAAOpaque);' in fog_code,
          'the opaque reference must receive the same integrated volume fog')

    resolve=gpu.program((SHADERS/'class1/deferred/taaResolveF.glsl').read_text())
    camera=gpu.program((SHADERS/'class1/deferred/taaCameraF.glsl').read_text())
    fog=gpu.program((SHADERS/'class1/deferred/volumeFogCompositeF.glsl').read_text())
    # Keep the production haze entry point and blend; provide a deterministic
    # atmosphere so the test does not depend on the user's selected sky preset.
    haze=gpu.program((SHADERS/'class3/deferred/hazeF.glsl').read_text()+'''
    uniform sampler2D depthMap;
    uniform mat4 inv_proj;
    float getDepth(vec2 uv) { return texture(depthMap,uv).r; }
    vec4 getNorm(vec2 uv) { return vec4(0,0,1,0); }
    vec4 getPositionWithDepth(vec2 uv,float d) {
        vec4 p=inv_proj*vec4(uv*2.0-1.0,d*2.0-1.0,1); return p/p.w;
    }
    void calcAtmosphericVarsLinear(vec3 p,vec3 n,vec3 l,out vec3 sunlit,
        out vec3 amblit,out vec3 additive,out vec3 atten) {
        sunlit=amblit=vec3(0); atten=vec3(exp(-abs(p.z)*.025));
        additive=vec3(.15,.2,.25)*(1.0-atten);
    }
    vec3 srgb_to_linear(vec3 c) { return c; }
    ''',gpu.vertex.replace('void main()', 'out vec2 vary_fragcoord; void main()').replace(
        'gl_Position=vec4(p[gl_VertexID],0,1);',
        'gl_Position=vec4(p[gl_VertexID],0,1); vary_fragcoord=p[gl_VertexID]*.5+.5;'))
    gl.BlendFuncSeparate=C.WINFUNCTYPE(None,U,U,U,U)(sdl.SDL_GL_GetProcAddress(b'glBlendFuncSeparate'))
    projection=[[1,0,0,0],[0,1,0,0],[0,0,-1.002002,-.2002002],[0,0,-1,0]]
    identity=[[float(r==c) for c in range(4)] for r in range(4)]
    current,opaque,history,output,vectors,scratch,medium=[gpu.texture() for _ in range(7)]
    depth=gpu.texture(depth=True)
    roi=[y*W+x for y in range(4,H-4) for x in range(4,W-4)]
    def halton(i,b):
        f=1; value=0
        while i: f/=b; value+=f*(i%b); i//=b
        return value
    def d(z): return (1.002002-.2002002/z)*.5+.5
    for prog in (resolve,camera): gpu.uniform(prog,'taa_rcp_res',1/W,1/H)
    gpu.matrix(camera,'taa_previous_projection',projection)
    gpu.matrix(camera,'taa_previous_from_view',identity)
    gpu.matrix(resolve,'taa_previous_inv_projection',inverse(projection))
    gpu.matrix(resolve,'taa_current_from_previous',identity)
    gpu.uniform(resolve,'taa_static_details',1,integer=True)
    for name,value in [('taa_history_weight',.97),('taa_motion_protection',.85),
                       ('taa_clip_gamma',1.2),('taa_transparency',.5)]:
        gpu.uniform(resolve,name,value)
    gpu.uniform(haze,'waterPlane',0,0,1,1)
    gpu.uniform(haze,'sky_hdr_scale',1)
    gpu.upload(medium,[.15,.2,.25,.5]*(W*H))
    def bind_resolve():
        gpu.viewer_bind('resolveTAA',resolve,{'mRT->screen':current,
            'mTAAHistory[1 - mTAAIndex]':history,'mTAAMotion':vectors,
            'mTAAOpaque':opaque,'mRT->deferredScreen':depth})
    def apply_haze(target):
        gpu.bind(haze,'depthMap',0,depth)
        gl.Enable(0x0BE2)
        gl.BlendFuncSeparate(1,0x0302,0,0x0302) # ONE, SRC_ALPHA; ZERO, SRC_ALPHA
        gpu.draw(haze,target)
        gl.Disable(0x0BE2)
    def apply_fog(target):
        gpu.bind(fog,'diffuseRect',0,target)
        gpu.bind(fog,'diffuseMap',1,medium)
        gpu.bind(fog,'depthMap',2,depth)
        gpu.draw(fog,scratch)
        gpu.upload(target,gpu.read(scratch))

    results={}
    for effect in ('atmospheric haze','fullbright mask','volume fog'):
        for aligned in (False,True):
            frames=[]; weights=[]
            for frame in range(96):
                jx,jy=halton(frame%8+1,2)-.5,halton(frame%8+1,3)-.5
                colors=[]; reference=[]; depths=[]
                for y in range(H):
                    for x in range(W):
                        bar=abs((x+.5-jx-(y+.5-jy)*.018)%4.7-2.35)<.325
                        color=(4,2.5,.8,.37) if bar else (.04,.05,.06,.37)
                        colors.extend(color)
                        reference.extend((0,0,0,.37) if effect=='fullbright mask' and bar and not aligned else color)
                        depths.append(d(30 if bar else 90))
                gpu.upload(current,colors); gpu.upload(opaque,reference); gpu.upload(depth,depths,True)
                jp=[row[:] for row in projection]
                for c in range(4):
                    jp[0][c]+=2*jx/W*projection[3][c]
                    jp[1][c]+=2*jy/H*projection[3][c]
                for prog in (resolve,camera):
                    gpu.matrix(prog,'taa_inv_projection',inverse(jp))
                    gpu.uniform(prog,'taa_jitter',jx/W,jy/H)
                gpu.matrix(haze,'inv_proj',inverse(jp)); gpu.matrix(fog,'inv_proj',inverse(jp))
                if effect=='atmospheric haze':
                    apply_haze(current)
                    if aligned: apply_haze(opaque)
                if effect=='volume fog':
                    apply_fog(current)
                    if aligned: apply_fog(opaque)
                gpu.bind(camera,'depthMap',0,depth); gpu.draw(camera,vectors)
                gpu.uniform(resolve,'taa_debug_mode',0,integer=True)
                gpu.uniform(resolve,'taa_history_valid',int(frame>0),integer=True)
                bind_resolve(); gpu.draw(resolve,output)
                if frame>=80:
                    pixels=gpu.read(output)
                    frames.append([pixels[i*4]/(1+pixels[i*4]) for i in roi])
                    gpu.uniform(resolve,'taa_debug_mode',2,integer=True)
                    gpu.draw(resolve,scratch)
                    diagnostics=gpu.read(scratch)
                    weights.extend(diagnostics[i*4+1] for i in roi)
                history,output=output,history
            flicker=statistics.mean(max(v)-min(v) for v in zip(*frames))
            weight=statistics.mean(weights)
            results[f'{effect}, aligned={aligned}']={'flicker':flicker,'history_weight':weight}
            print(effect,aligned,results[f'{effect}, aligned={aligned}'],flush=True)
            if not aligned: before=flicker
            else:
                check(flicker<before*.2, f'correct {effect} reference must remove false reactive flicker')
                check(weight>.95, f'opaque {effect} must retain the configured history weight')

    # Genuine post-capture transparency is still reactive, even after both
    # buffers receive identical atmospheric and volume-fog transforms.
    gpu.uniform(resolve,'taa_history_valid',1,integer=True)
    gpu.uniform(resolve,'taa_jitter',0,0)
    gpu.uniform(resolve,'taa_debug_mode',2,integer=True)
    gpu.uniform(resolve,'taa_motion_protection',0)
    gpu.uniform(resolve,'taa_clip_gamma',2)
    gpu.matrix(resolve,'taa_inv_projection',inverse(projection))
    gpu.matrix(haze,'inv_proj',inverse(projection)); gpu.matrix(fog,'inv_proj',inverse(projection))
    gpu.upload(depth,[d(30)]*(W*H),True)
    gpu.upload(vectors,[0,0,30,-1]*(W*H))
    gpu.upload(history,[.4,.4,.4,30]*(W*H))
    gpu.upload(opaque,[.02,.02,.02,.37]*(W*H))
    gpu.upload(current,[v for y in range(H) for x in range(W)
        for v in ((2,1.5,1,.37) if (x+y)%2 else (.3,.3,.3,.37))])
    for target in (current,opaque): apply_haze(target); apply_fog(target)
    measured=[]
    for protection in (0,.2,.5,1):
        gpu.uniform(resolve,'taa_transparency',protection)
        bind_resolve(); gpu.draw(resolve,output)
        measured.append(statistics.mean(gpu.read(output)[1::4]))
    check(all(a>b for a,b in zip(measured,measured[1:])),
          'transparency protection must still reduce history on actual blended layers')
    print('Actual transparency history weights:',measured)
    print(f'PASS: {checks} TAA composition GPU/integration checks')
    return {'gpu':gl.GetString(0x1F01).decode(),'checks':checks,'results':results}


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try:
        result=run(sdl,gl)
        target=ROOT/'tmp/taa-tests/composition-results.json'
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(result,indent=2)+'\n')
    finally:
        sdl.SDL_GL_DestroyContext(ctx); sdl.SDL_DestroyWindow(window); sdl.SDL_Quit()
