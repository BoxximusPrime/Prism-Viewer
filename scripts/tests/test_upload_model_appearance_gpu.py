"""Compile production preview PBR fragment and test coverage on a hidden GPU.

Lighting/probe fixtures isolate coverage; this does not replace live mesh review.
Run with the viewer's Python environment, no login or payment required.
"""
import argparse
import ctypes as C
import re
from pathlib import Path
from test_taa_gpu import GPU, context, W, H
from test_alpha_lighting_gpu import function, STUBS, VERTEX
from test_exact_oit_gpu import F, TEXTURE, FRAMEBUFFER

parser=argparse.ArgumentParser()
parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2])
root=parser.parse_args().root
shaders=root/'indra/newview/app_settings/shaders'
# Reuse the existing utilities from the checkout for the staging-only invocation.
harness=Path(__import__('test_taa_gpu').__file__).resolve().parents[2]/'indra/newview/app_settings/shaders'

def run(sdl,gl):
    gpu=GPU(sdl,gl)
    fragment=(shaders/'class2/deferred/pbralphaF.glsl').read_text(encoding='utf-8')
    util=(harness/'class1/deferred/deferredUtil.glsl').read_text()
    helpers=STUBS+function(util,'void calcHalfVectors(')+function(util,'float calcLegacyDistanceAttenuation(')
    helpers+=util[util.index('bool hasAlphaProjector('):util.index('vec3 pbrCalcPointLightOrSpotLight(')]
    helpers+=function(util,'vec3 pbrCalcPointLightOrSpotLight(')
    helpers+=(harness/'class1/deferred/projectorUtil.glsl').read_text()
    helpers+=function((harness/'class1/deferred/globalF.glsl').read_text(),'float filterPBRRoughness(')
    # A preview must not depend on (or execute) world-only clipping/transport.
    preview_helpers=helpers.replace('void mirrorClip(vec3 p) {}','').replace('void waterClip(vec3 p) {}','')
    preview_helpers=preview_helpers.replace('vec3 waterLitSun(vec3 p, vec3 l, vec3 c, int classic) { return c; }','')
    preview_helpers=preview_helpers.replace('vec3 waterLitAmbient(vec3 p, vec3 c, int classic) { return c; }','')
    preview_helpers=preview_helpers.replace('vec4 applySkyAndWaterFog(vec3 p, vec3 additive, vec3 atten, vec4 c)\n{ return vec4(c.rgb * atten + additive, c.a); }','')
    vertex=VERTEX.replace('uniform float test_normal_length;','uniform float test_normal_length;\nuniform float test_factor;')
    vertex=vertex.replace('vertex_color=vec4(1,1,1,0.6);','vertex_color=vec4(1,1,1,test_factor);')
    preview=gpu.program('#define MODEL_PREVIEW 1\n#define HAS_ALPHA_MASK 1\n'+fragment+preview_helpers,vertex)
    world=gpu.program(fragment+helpers+(harness/'class1/deferred/sssOverlayUtil.glsl').read_text(),vertex)
    output=gpu.texture()
    base=gpu.texture()
    normals=gpu.texture([.5,.5,1,1]*(W*H))
    orm=gpu.texture([1,1,0,1]*(W*H))
    emission=gpu.texture([0,0,0,1]*(W*H))
    checks=0
    def render(program,mode,alpha,factor,cutoff):
        gpu.upload(base,[1,1,1,alpha]*(W*H))
        for name,unit,texture in [('diffuseMap',0,base),('bumpMap',1,normals),
            ('specularMap',2,orm),('emissiveMap',3,emission)]: gpu.bind(program,name,unit,texture)
        gpu.uniform(program,'test_normal_length',1)
        gpu.uniform(program,'test_factor',factor)
        gpu.uniform(program,'test_position',0,0,-5)
        gpu.uniform(program,'test_ambient',.1)
        gpu.uniform(program,'preview_alpha_mode',mode,integer=True)
        gpu.uniform(program,'minimum_alpha',cutoff)
        gpu.uniform(program,'sun_dir',0,0,1)
        gpu.uniform(program,'roughnessFactor',1)
        gpu.uniform(program,'metallicFactor',0)
        gpu.upload(output,[.73,.21,.12,.37]*(W*H))
        gpu.draw(program,output)
        return gpu.read(output)
    for alpha in (0,.2,.6,1):
        for factor in (.25,1):
            opaque=render(preview,0,alpha,factor,-1)
            assert abs(opaque[3]-1)<.001,'Opaque preview did not force full coverage'
            blend=render(preview,2,alpha,factor,-1)
            assert abs(blend[3]-alpha*factor)<.001,'Blended preview lost authored alpha/factor'
            masked=render(preview,1,alpha,factor,.15)
            if alpha*factor<.15:
                assert abs(masked[0]-.73)<.001 and abs(masked[3]-.37)<.001,'Masked fragment was not discarded'
            else: assert abs(masked[3]-1)<.001,'Masked preview did not retain full coverage'
            normal=render(world,2,alpha,factor,-1)
            assert abs(normal[3]-alpha*factor)<.001,'World alpha changed'
            checks+=4
    # Preview must compile when world clipping/fog definitions are absent.
    assert gl.GetUniformLocation(preview,b'preview_alpha_mode')>=0
    assert gl.GetUniformLocation(world,b'preview_alpha_mode')<0
    print(f'PASS: {checks} GPU opaque/mask/blend/factor/world-alpha checks; preview ignores world clipping/fog.')

    # Replay the final preview pass with a patterned color buffer and shared
    # geometry depth. Follow the production shader/bindings, so a fullscreen
    # depth-copy shader cannot silently reintroduce framebuffer feedback.
    renderer=function((root/'indra/newview/llgltfmaterialpreviewmgr.cpp').read_text(),
                      'bool LLGLTFPreviewTexture::renderGeometry(')
    shader_name=re.findall(r'(\w+Program)\.bind\(\);',renderer)[-1]
    shader_setup=(root/'indra/newview/llviewershadermgr.cpp').read_text()
    files=re.findall(re.escape(shader_name)+r'\.mShaderFiles\.push_back\(make_pair\("([^"]+)"',shader_setup)
    assert len(files)==2, 'Expected the production final-pass vertex and fragment shaders'
    for uniform, resource in re.findall(re.escape(shader_name)+r'\.bindTexture\(LLShaderMgr::(\w+),\s*([^;]+)\);',renderer):
        assert resource=='&screen', f'Preview final pass samples its attached depth: {resource}'
        assert uniform in ('DIFFUSE_MAP','DEFERRED_DIFFUSE')
    resolve=gpu.program((shaders/'class1'/files[1]).read_text(),(shaders/'class1'/files[0]).read_text())

    # A foreground depth value exposes clears performed with depth writes off.
    shared_depth=gpu.texture([.1]*(W*H),depth=True)
    gl.FramebufferTexture2D(FRAMEBUFFER,0x8D00,TEXTURE,shared_depth,0)
    clear_scope=renderer[:renderer.index('glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);')]
    clear_state=re.findall(r'LLGLDepthTest \w+\(([^;]+)\);',clear_scope)[-1]
    gl.DepthMask('GL_TRUE, GL_TRUE' in clear_state)
    gl.Clear(0x100)
    depth_pixels=(F*(W*H))()
    gl.ReadPixels(0,0,W,H,0x1902,0x1406,depth_pixels)
    assert min(depth_pixels)>.999, 'Preview depth clear was blocked by the depth write mask'

    positions=(F*9)(-1,-1,0,3,-1,0,-1,3,0)
    buffer=gpu.obj(gl.GenBuffers)
    gl.BindBuffer(0x8892,buffer)
    gl.BufferData(0x8892,C.sizeof(positions),positions,0x88E4)
    gl.EnableVertexAttribArray(0)
    gl.VertexAttribPointer(0,3,0x1406,False,0,None)
    final_scope=renderer[renderer.index(shader_name+'.bind();'):]
    assert 'LLGLDepthTest depth_test(GL_FALSE, GL_FALSE)' in final_scope
    gl.Disable(0x0B71)
    gl.DepthMask(False)
    # Successive color buffers must copy fresh pixels without changing geometry.
    for phase in range(4):
        pattern=[value for y in range(H) for x in range(W)
                 for value in ((.2,.7,.1,1) if ((x//8)^(y//8)^phase)&1 else (.8,.1,.5,.5))]
        gpu.upload(base,pattern)
        gpu.upload(shared_depth,[.3]*(W*H),depth=True)
        gpu.bind(resolve,'diffuseMap',0,base)
        gpu.draw(resolve,output)
        actual=gpu.read(output)
        assert max(abs(a-b) for a,b in zip(actual,pattern))<.001, 'Preview lost texture detail or alpha'
        gl.ReadPixels(0,0,W,H,0x1902,0x1406,depth_pixels)
        assert max(abs(value-.3) for value in depth_pixels)<.0001, 'Final pass changed mesh depth'
    gl.FramebufferTexture2D(FRAMEBUFFER,0x8D00,TEXTURE,0,0)
    print('PASS: preview depth clear, framebuffer feedback guard and four patterned color/alpha/depth copies.')

if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try: run(sdl,gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx)
        sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()
