"""Validate post-TAA CoC reconstruction and presentation depth on the GPU."""
from test_taa_gpu import GPU, SHADERS, W, H, inverse, context


def run(sdl, gl):
    gpu=GPU(sdl,gl)
    vertex='''out vec2 vary_fragcoord;
    void main(){vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
    gl_Position=vec4(p[gl_VertexID],0,1);vary_fragcoord=p[gl_VertexID]*.5+.5;}'''
    cof=gpu.program((SHADERS/'class1/deferred/cofF.glsl').read_text(),vertex)
    # Read the production presentation depth expression through color alpha.
    # The GLSL compiler otherwise writes it to the default test FBO's absent depth attachment.
    final_source=(SHADERS/'class1/deferred/postDeferredNoDoFF.glsl').read_text()
    final_source=final_source.replace('gl_FragDepth =','frag_color.a =')
    final_source+='\nvec3 clampHDRRange(vec3 color){return clamp(color,vec3(0),vec3(65000));}\n'
    finals=[gpu.program(prefix+final_source,vertex) for prefix in ('','#define HAS_NOISE 1\n')]
    current=gpu.texture([.2,.4,.6,.37]*(W*H)); depth=gpu.texture(depth=True); output=gpu.texture()
    projection=[[1,0,0,0],[0,1,0,0],[0,0,-1.002002,-.2002002],[0,0,-1,0]]
    gpu.matrix(cof,'inv_proj',inverse(projection))
    for name,value in [('focal_distance',-2),('blur_constant',1),('tan_pixel_angle',.01),
                       ('magnification',1),('max_cof',10)]:
        gpu.uniform(cof,name,value)
    depths=[(1.002002-.2002002/(2 if (x+y)%2 else 8))*.5+.5 for y in range(H) for x in range(W)]
    gpu.upload(depth,depths,True)
    for prog in [cof]+finals:
        gpu.bind(prog,'diffuseRect',0,current); gpu.bind(prog,'depthMap',1,depth)
        gpu.uniform(prog,'screen_res',W,H)
    checks=0
    def check(condition,message):
        nonlocal checks
        assert condition,message
        checks+=1
    def alpha(x,y):
        # The chosen optics clamp the far background to -max_cof, while z=2 is in focus.
        x=max(0,min(W-1,x)); y=max(0,min(H-1,y))
        return .5 if (x+y)%2 else 0
    import math
    for jx,jy in [(0,0),(.375,.25),(-.375,-.25),(.125,-.375),(-.4375,4/9)]:
        gpu.uniform(cof,'taa_depth_jitter',jx/W,jy/H)
        gpu.bind(cof,'diffuseRect',0,current); gpu.bind(cof,'depthMap',1,depth)
        gpu.draw(cof,output); pixels=gpu.read(output)
        error=0
        for x,y in [(W//2,H//2),(W//2+1,H//2),(0,0),(W-1,H-1)]:
            px,py=x+jx,y+jy; ix,iy=math.floor(px),math.floor(py); fx,fy=px-ix,py-iy
            expected=(alpha(ix,iy)*(1-fx)+alpha(ix+1,iy)*fx)*(1-fy)+(alpha(ix,iy+1)*(1-fx)+alpha(ix+1,iy+1)*fx)*fy
            error=max(error,abs(pixels[(y*W+x)*4+3]-expected))
        check(error<.002,f'CoC must follow jittered coverage, including borders: {jx,jy,error}')
        check(max(abs(pixels[i]-[.2,.4,.6,.37][i%4]) for i in range(len(pixels)) if i%4!=3)<.001,
              'CoC reconstruction must not change resolved color')
        for prog in finals:
            gpu.uniform(prog,'taa_depth_jitter',jx/W,jy/H)
            gpu.bind(prog,'diffuseRect',0,current); gpu.bind(prog,'depthMap',1,depth)
            gpu.draw(prog,output); pixels=gpu.read(output)
            expected=depths[int(H//2+.5+jy)*W+int(W//2+.5+jx)]
            check(abs(pixels[((H//2)*W+W//2)*4+3]-expected)<.001,f'presentation physical depth: jitter={jx,jy}, actual={pixels[((H//2)*W+W//2)*4+3]}, expected={expected}')
    print(f'PASS: {checks} post-TAA depth GPU checks')


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try: run(sdl,gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx); sdl.SDL_DestroyWindow(window); sdl.SDL_Quit()
