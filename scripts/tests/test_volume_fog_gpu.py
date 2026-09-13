"""Run the production fog shaders on a hidden OpenGL context.

Analytic Beer-Lambert references for hard boxes; independent dense numerical
integration for soft/rotated volumes. No viewer login or third-party Python libs.
"""
import ctypes as C
import math
from pathlib import Path
import random
import struct
import sys
import zlib
from test_exact_oit_gpu import context, U, I, F, TEXTURE, FRAMEBUFFER, COLOR_ATTACHMENT, RGBA, FLOAT

ROOT = Path(__file__).resolve().parents[2]


def run(sdl, gl, lighting=False):
    for name, args in {
        'ActiveTexture': [U], 'Uniform4fv': [I,I,C.c_void_p], 'Uniform3f': [I,F,F,F], 'Uniform2f': [I,F,F],
        'UniformMatrix4fv': [I,I,C.c_ubyte,C.c_void_p], 'Disable': [U],
    }.items():
        setattr(gl,name,C.WINFUNCTYPE(None,*args)(sdl.SDL_GL_GetProcAddress(('gl'+name).encode())))

    def obj(generator):
        value=U(); generator(1,C.byref(value)); return value.value

    program=gl.CreateProgram()
    vertex='void main(){vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));gl_Position=vec4(p[gl_VertexID],0,1);}'
    fragment=(ROOT/'indra/newview/app_settings/shaders/class1/deferred/volumeFogF.glsl').read_text()
    stages=[(0x8B31,vertex),(0x8B30,fragment)]
    if lighting:
        stages.append((0x8B30,(ROOT/'indra/newview/app_settings/shaders/class1/deferred/volumeFogLightF.glsl').read_text()))
    for kind,source in stages:
        shader=gl.CreateShader(kind)
        source=C.c_char_p(('#version 330 core\n'+('#define VF_LIGHTING 1\n' if lighting else '')+source).encode())
        gl.ShaderSource(shader,1,C.byref(source),None); gl.CompileShader(shader)
        ok,log=I(),C.create_string_buffer(16384)
        gl.GetShaderiv(shader,0x8B81,C.byref(ok)); gl.GetShaderInfoLog(shader,len(log),None,log)
        assert ok.value,log.value.decode()
        gl.AttachShader(program,shader); gl.DeleteShader(shader)
    gl.LinkProgram(program)
    gl.GetProgramiv(program,0x8B82,C.byref(ok)); gl.GetProgramInfoLog(program,len(log),None,log)
    assert ok.value,log.value.decode()
    gl.UseProgram(program)
    gl.BindVertexArray(obj(gl.GenVertexArrays)); gl.Viewport(0,0,1,1)
    gl.Disable(0x0BE2); gl.Disable(0x0B71)

    def loc(name): return gl.GetUniformLocation(program,name.encode())
    def integer(name,value): gl.Uniform1i(loc(name),value)
    def scalar(name,value): gl.Uniform1f(loc(name),value)
    def vector(name,*values): gl.Uniform3f(loc(name),*values)
    def matrices(name,values): gl.UniformMatrix4fv(loc(name),len(values)//16,False,(F*len(values))(*values))
    def array(name,rows):
        values=[v for row in rows for v in row]
        if rows: gl.Uniform4fv(loc(name),len(rows),(F*len(values))(*values))

    def texture(unit,values):
        gl.ActiveTexture(0x84C0+unit)
        tex=obj(gl.GenTextures); gl.BindTexture(TEXTURE,tex)
        gl.TexImage2D(TEXTURE,0,0x8814,1,1,0,RGBA,FLOAT,(F*4)(*values))
        for param,value in ((0x2801,0x2600),(0x2800,0x2600),(0x2802,0x812F),(0x2803,0x812F)):
            gl.TexParameteri(TEXTURE,param,value)
        return tex

    background=(.1,.2,.3,.4)
    scene=texture(0,background); depth_tex=texture(1,(1,0,0,0)); output=texture(2,(0,0,0,0))
    framebuffer=obj(gl.GenFramebuffers)
    gl.BindFramebuffer(FRAMEBUFFER,framebuffer)
    gl.FramebufferTexture2D(FRAMEBUFFER,COLOR_ATTACHMENT,TEXTURE,output,0)
    assert gl.CheckFramebufferStatus(FRAMEBUFFER)==0x8CD5
    integer('diffuseRect',0); integer('depthMap',1)
    near,far=.1,100.
    A=(far+near)/(near-far); B=2*far*near/(near-far)
    inverse=[1,0,0,0, 0,1,0,0, 0,0,0,1/B, 0,0,-1,A/B]
    gl.UniformMatrix4fv(loc('inv_proj'),1,False,(F*16)(*inverse))
    scalar('vf_far',far)
    scalar('vf_intensity',1)
    gl.Uniform2f(loc('vf_target_size'),1,1)
    if lighting:
        vector('vf_ambient',1,1,1); vector('vf_sun_color',0,0,0); vector('vf_sun_direction',0,0,-1)
        scalar('vf_light_strength',1); scalar('vf_anisotropy',0); integer('vf_steps',32)
        integer('vf_min_steps',8)
        shadow_textures=[]; projector_textures=[]
        for i in range(6):
            integer('pcssDepthMap'+str(i),2+i); shadow_textures.append(texture(2+i,(1,1,1,1)))
        for i in range(4):
            integer('alphaProjectionMap'+str(i),8+i); projector_textures.append(texture(8+i,(1,1,1,1)))
        array('shadow_clip',[(40,60,80,100)])

    def box(start=7,end=13,density=.5,color=(1,0,1),soft=0,center_x=0,angle=0,half_x=5,half_y=5):
        # Rotation about Y; axes are coordinates of local basis vectors in view space.
        c,s=math.cos(angle),math.sin(angle)
        center=(center_x,0,-(start+end)/2)
        axes=((c,0,-s),(0,1,0),(s,0,c))
        return dict(axes=[(*a,-sum(x*y for x,y in zip(a,center))) for a in axes],
                    half=(half_x,half_y,(end-start)/2),density=density,color=color,soft=soft)

    def render(boxes,wall=100):
        integer('vf_count',len(boxes))
        for index,name in enumerate(('vf_axis_x','vf_axis_y','vf_axis_z')):
            array(name,[b['axes'][index] for b in boxes])
        array('vf_half_density',[(*b['half'],b['density']) for b in boxes])
        array('vf_color_softness',[(*b['color'],b['soft']) for b in boxes])
        d=1 if wall==100 else (-A+B/wall)*.5+.5
        gl.ActiveTexture(0x84C1); gl.BindTexture(TEXTURE,depth_tex)
        gl.TexImage2D(TEXTURE,0,0x8814,1,1,0,RGBA,FLOAT,(F*4)(d,0,0,0))
        gl.DrawArrays(4,0,3)
        pixel=(F*4)(); gl.ReadPixels(0,0,1,1,RGBA,FLOAT,pixel)
        assert gl.GetError()==0
        # Test the integrator independently; the production composite/upsample
        # has separate GPU checks below.
        return [min(65000.,background[i]*pixel[3]+pixel[i]) for i in range(3)]+[background[3]*pixel[3]]

    def expected(length,density=.5,color=(1,0,1)):
        t=math.exp(-length*density)
        return [background[i]*t+color[i]*(1-t) for i in range(3)]+[background[3]*t]

    checks=0
    def check(name,actual,wanted,tolerance=2e-5):
        nonlocal checks
        assert all(math.isfinite(x) for x in actual), (name,actual)
        assert max(abs(a-b) for a,b in zip(actual,wanted))<tolerance,(name,actual,wanted)
        checks+=1

    check('empty',render([]),background)
    check('zero density',render([box(density=0)]),background)
    scalar('vf_intensity',0)
    check('zero global intensity',render([box()]),background)
    scalar('vf_intensity',.5)
    check('half global intensity',render([box()]),expected(6,.25))
    scalar('vf_intensity',2)
    check('double global intensity',render([box()]),expected(6,1))
    scalar('vf_intensity',1)
    check('clear sky',render([box()]),expected(6))
    check('wall before box',render([box()],5),background)
    check('wall inside box',render([box()],10),expected(3))
    check('wall behind box',render([box()],20),expected(6))
    check('camera inside',render([box(-2,2)]),expected(2))
    check('box behind camera',render([box(-10,-4)]),background)
    check('parallel miss',render([box(center_x=10)]),background)
    check('parallel boundary',render([box(center_x=5)]),expected(6))
    check('near clip fog',render([box(.01,.09)]),expected(.08))
    check('thin box',render([box(10,10.002)]),expected(.002))
    check('fully opaque fog finite',render([box(density=10)]),expected(6,10))
    check('black fog absorbs',render([box(color=(0,0,0))]),expected(6,color=(0,0,0)))
    # Concentric boxes mix by extinction, not by the CPU/prim iteration order.
    red=box(density=.2,color=(1,0,0)); blue=box(density=.3,color=(0,0,1))
    check('overlap',render([red,blue]),expected(6,.5,(.4,0,.6)))
    check('overlap reversed',render([blue,red]),render([red,blue]))
    # Disjoint layers preserve front-to-back colored transport.
    red=box(2,4,.4,(1,0,0)); blue=box(7,9,.4,(0,0,1))
    t=math.exp(-.8)
    wanted=[background[i]*t*t+(1-t)*red['color'][i]+t*(1-t)*blue['color'][i] for i in range(3)]+[background[3]*t*t]
    check('separate colors',render([blue,red]),wanted)
    boxes=[box(2+i,4+i,.1,(i/8,1-i/8,.4)) for i in range(8)]
    baseline=render(boxes)
    rng=random.Random(2309)
    for i in range(20):
        rng.shuffle(boxes)
        check('eight-box order '+str(i),render(boxes),baseline)

    def numerical(boxes,limit):
        # Independent dense sampling in world/view distance. This does not use
        # the production ray/box intersection, event splitting, or quadrature.
        count=100000; step=limit/count
        trans=1.; scatter=[0.,0.,0.]
        for sample in range(count):
            distance=(sample+.5)*step
            extinction=0.; emission=[0.,0.,0.]
            for b in boxes:
                local=[axis[3]-axis[2]*distance for axis in b['axes']]
                edge=min(h-abs(p) for h,p in zip(b['half'],local))
                if edge<0: continue
                weight=1.
                if b['soft']>0:
                    x=min(1.,edge/b['soft']); weight=x*x*(3-2*x)
                sigma=b['density']*weight
                extinction+=sigma
                emission=[e+c*sigma for e,c in zip(emission,b['color'])]
            if extinction:
                t=math.exp(-extinction*step)
                scatter=[a+trans*(1-t)*e/extinction for a,e in zip(scatter,emission)]
                trans*=t
        return [background[i]*trans+scatter[i] for i in range(3)]+[background[3]*trans]

    soft_cases=[
        [box(soft=3)], [box(soft=.1)], [box(soft=1,angle=.6,half_x=2)],
        [box(soft=2),box(4,10,.2,(0,1,0),1,angle=.4,half_x=2)],
        [box(-3,3,soft=2,angle=.4)], [box(angle=math.pi/2,half_x=2)],
    ]
    for i,boxes in enumerate(soft_cases):
        check('numerical '+str(i),render(boxes,20),numerical(boxes,20),.004)
    if lighting:
        white=box(color=(1,1,1))
        vector('vf_ambient',0,0,0)
        vector('vf_sun_color',.8,.5,.2)
        check('directional color',render([white]),expected(6,color=(.8,.5,.2)))
        vector('vf_sun_color',.01,.02,.04)
        check('moon color',render([white]),expected(6,color=(.01,.02,.04)))
        vector('vf_sun_color',0,0,0)
        check('no illumination absorbs',render([white]),expected(6,color=(0,0,0)))
        vector('vf_sun_color',1e6,1e6,1e6)
        check('HDR target range',render([white]),[65000,65000,65000,expected(6)[3]])
        vector('vf_sun_color',1,1,1); scalar('vf_anisotropy',.5)
        check('forward scattering',render([white]),expected(6,color=(6,6,6)))
        vector('vf_sun_direction',0,0,1)
        check('back scattering',render([white]),expected(6,color=(2/9,2/9,2/9)))
        scalar('vf_anisotropy',0); vector('vf_sun_direction',0,0,-1)

        def upload_texture(unit,tex,color):
            gl.ActiveTexture(0x84C0+unit); gl.BindTexture(TEXTURE,tex)
            gl.TexImage2D(TEXTURE,0,0x8814,1,1,0,RGBA,FLOAT,(F*4)(*color))

        # All samples map inside a synthetic shadow map, so changing its stored
        # depth has an unambiguous expected effect independently of scene depth.
        shadow_matrix=[0,0,0,0, 0,0,0,0, 0,0,0,0, .5,.5,.7,1]
        matrices('shadow_matrix',shadow_matrix*6)
        integer('vf_shadow_mask',1)
        upload_texture(2,shadow_textures[0],(.2,0,0,0))
        check('sun blocked in air',render([white]),expected(6,color=(0,0,0)))
        integer('vf_shadow_mask',0)
        check('sun shadows disabled',render([white]),expected(6,color=(1,1,1)))
        integer('vf_shadow_mask',1)
        upload_texture(2,shadow_textures[0],(1,0,0,0))
        check('sun clear depth',render([white]),expected(6,color=(1,1,1)))
        outside=shadow_matrix[:]; outside[12]=1.1
        matrices('shadow_matrix',outside*6)
        upload_texture(2,shadow_textures[0],(.2,0,0,0))
        check('outside shadow coverage',render([white]),expected(6,color=(1,1,1)))
        matrices('shadow_matrix',shadow_matrix*6)
        array('shadow_clip',[(10,20,40,100)]); integer('vf_shadow_mask',3)
        mixed=render([white])
        assert expected(6,color=(0,0,0))[0]<mixed[0]<expected(6,color=(1,1,1))[0]; checks+=1
        for i in range(4):
            clips=tuple([1+axis for axis in range(i)]+[40+20*axis for axis in range(4-i)])
            array('shadow_clip',[clips]); integer('vf_shadow_mask',1<<i)
            upload_texture(2+i,shadow_textures[i],(.2,0,0,0))
            check('sun shadow slot '+str(i),render([white]),expected(6,color=(0,0,0)))
            upload_texture(2+i,shadow_textures[i],(1,0,0,0))
        integer('vf_shadow_mask',1); array('shadow_clip',[(40,60,80,100)])
        gl.ActiveTexture(0x84C2); gl.BindTexture(TEXTURE,shadow_textures[0])
        depths=[v for d in (.2,1,1,.2) for v in (d,0,0,0)]
        gl.TexImage2D(TEXTURE,0,0x8814,2,2,0,RGBA,FLOAT,(F*16)(*depths))
        check('shadow compares before filtering',render([white]),expected(6,color=(.5,.5,.5)))
        integer('vf_shadow_mask',0); array('shadow_clip',[(40,60,80,100)])
        vector('vf_sun_color',0,0,0)

        def lights(positions,colors=None,metadata=None):
            integer('vf_light_count',len(positions))
            array('vf_light_position',positions)
            array('vf_light_color',colors or [(1,1,1,0)]*len(positions))
            array('vf_light_projector',metadata or [(-1,-1,1,0)]*len(positions))

        def point_reference(start,end,density,center,radius,color=(1,1,1),falloff=0):
            count=30000; step=(end-start)/count; sigma=density
            scatter=[0.,0.,0.]
            for j in range(count):
                t=start+(j+.5)*step
                dist=math.sqrt(center[0]**2+center[1]**2+(center[2]+t)**2)
                a=2*(1-min(1,max(0,(dist/radius+falloff)/(1+falloff))))**2
                w=math.exp(-sigma*(t-start))*sigma*step*a
                scatter=[s+w*c for s,c in zip(scatter,color)]
            trans=math.exp(-sigma*(end-start))
            return [background[i]*trans+scatter[i] for i in range(3)]+[background[3]*trans]

        lights([(0,0,-10,5)],[(1,.2,.1,0)])
        check('point attenuation/color',render([white]),point_reference(7,13,.5,(0,0,-10),5,(1,.2,.1)),.002)
        lights([(0,0,-10,5)],[(1,.2,.1,1)])
        check('point falloff',render([white]),point_reference(7,13,.5,(0,0,-10),5,(1,.2,.1),1),.002)
        lights([(20,0,-10,2)])
        check('out of range',render([white]),expected(6,color=(0,0,0)))
        large=box(1,50,.03,(1,1,1))
        lights([(0,0,-10,.025)],[(10,10,10,0)])
        integer('vf_steps',8)
        check('tiny light in large fog',render([large]),point_reference(1,50,.03,(0,0,-10),.025,(10,10,10)),.0005)
        integer('vf_steps',32)
        lights([(0,0,-10,5)])
        single=render([white])
        lights([(0,0,-10,5)]*8)
        dark=expected(6,color=(0,0,0))
        check('eight light sum',render([white]),[dark[i]+8*(single[i]-dark[i]) for i in range(4)],.0001)

        def projector_matrix(origin=(0,0,0),forward=(0,0,-1),fov=math.pi/2,near=.1,far=40):
            up=(0,1,0)
            right=(-forward[2],0,forward[0]); back=tuple(-x for x in forward)
            q=1/math.tan(fov/2); a=(far+near)/(near-far); b=2*far*near/(near-far)
            rows=[]
            for direction,scale in ((right,.5*q),(up,.5*q)):
                xyz=[scale*direction[j]-.5*back[j] for j in range(3)]
                rows.append(xyz+[-sum(x*y for x,y in zip(xyz,origin))])
            xyz=[(.5*a-.5)*x for x in back]
            rows.append(xyz+[.5*b-sum(x*y for x,y in zip(xyz,origin))])
            xyz=list(forward); rows.append(xyz+[-sum(x*y for x,y in zip(xyz,origin))])
            return [rows[row][col] for col in range(4) for row in range(4)]

        matrices('vf_projector_matrix',projector_matrix()*4)
        array('vf_projector_params',[(10,0,40,0)]*4)
        array('vf_projector_normal',[(0,0,-1,0)]*4)
        array('vf_projector_origin',[(0,0,0,1)]*4)
        for i in range(4):
            lights([(0,0,-1,30)],metadata=[(i,-1,1,0)])
            upload_texture(8+i,projector_textures[i],(.5,.5,.5,1))
            c=((.5+.055)/1.055)**2.4
            check('projector texture/color slot '+str(i),render([white]),point_reference(7,13,.5,(0,0,-1),30,(c,c,c)),.002)
        lights([(0,0,-1,30)],metadata=[(0,0,0,0)])
        upload_texture(8,projector_textures[0],(1,1,1,1))
        integer('vf_shadow_mask',16)
        upload_texture(6,shadow_textures[4],(.2,0,0,0))
        check('projector blocked',render([white]),expected(6,color=(0,0,0)))
        integer('vf_shadow_mask',32)
        lights([(0,0,-1,30)],metadata=[(0,1,0,0)])
        upload_texture(7,shadow_textures[5],(.2,0,0,0))
        check('second projector shadow slot',render([white]),expected(6,color=(0,0,0)))
        integer('vf_shadow_mask',16)
        lights([(0,0,-1,30)],metadata=[(0,0,.5,0)])
        check('projector shadow fade',render([white]),point_reference(7,13,.5,(0,0,-1),30,(.5,.5,.5)),.002)
        lights([(0,0,-1,30)],metadata=[(0,-1,1,0)])
        check('no-shadow projector',render([white]),point_reference(7,13,.5,(0,0,-1),30),.002)
        integer('vf_shadow_mask',0)
        upload_texture(8,projector_textures[0],(1,1,1,0))
        check('projector texture alpha',render([white]),expected(6,color=(0,0,0)))
        upload_texture(8,projector_textures[0],(1,1,1,1))
        matrices('vf_projector_matrix',projector_matrix(origin=(20,0,0))*4)
        check('outside projector cone',render([white]),expected(6,color=(0,0,0)))
        matrices('vf_projector_matrix',projector_matrix(forward=(0,0,1))*4)
        check('behind projector',render([white]),expected(6,color=(0,0,0)))
        matrices('vf_projector_matrix',projector_matrix(far=5)*4)
        check('beyond projector far',render([white]),expected(6,color=(0,0,0)))
        matrices('vf_projector_matrix',projector_matrix(near=15)*4)
        check('before projector near',render([white]),expected(6,color=(0,0,0)))

        # Focus changes select the existing projector mip chain (red/green/blue).
        matrices('vf_projector_matrix',projector_matrix()*4)
        gl.ActiveTexture(0x84C8); gl.BindTexture(TEXTURE,projector_textures[0])
        for level,color in enumerate(((1,0,0,1),(0,1,0,1),(0,0,1,1))):
            side=4>>level; values=color*(side*side)
            gl.TexImage2D(TEXTURE,level,0x8814,side,side,0,RGBA,FLOAT,(F*len(values))(*values))
        gl.TexParameteri(TEXTURE,0x2801,0x2700) # nearest mip, nearest texel
        lights([(0,0,-1,30)],metadata=[(0,-1,1,0)])
        array('vf_projector_params',[(10,2,20,0)]*4)
        focused=render([white]); assert focused[0]>focused[1]+.5; checks+=1
        array('vf_projector_params',[(0,2,18,0)]*4)
        defocused=render([white]); assert defocused[1]>defocused[0]+.5; checks+=1
        gl.TexParameteri(TEXTURE,0x2801,0x2600)
        upload_texture(8,projector_textures[0],(1,1,1,1))
        array('vf_projector_params',[(10,0,40,0)]*4)

        # A 10 cm-wide beam across a 49 m fog path must not vanish at 8 samples.
        matrices('vf_projector_matrix',projector_matrix((1,0,-10),(-1,0,0),.1)*4)
        array('vf_projector_normal',[(-1,0,0,0)]*4)
        array('vf_projector_origin',[(1,0,-10,1)]*4)
        lights([(1,0,-10,3)],[(10,10,10,0)],[(0,-1,1,0)])
        integer('vf_steps',8)
        coarse=render([large])
        integer('vf_steps',64); fine=render([large])
        check('narrow projector sampling',coarse,fine,.0001)
        assert coarse[0]>expected(49,.03,(0,0,0))[0]+.01; checks+=1
        for quality,steps,minimum in (('Performance',16,4),('Balanced',24,6),('High',32,8),('Ultra',64,8)):
            integer('vf_steps',steps); integer('vf_min_steps',minimum)
            check(quality+' narrow projector',render([large]),fine,.0004)
        integer('vf_steps',32); integer('vf_min_steps',8)

    print(f'PASS: {checks} production fog GPU checks (GLSL 330, lighting={lighting}), GPU: {gl.GetString(0x1F01).decode()}')

    if '--preview' in sys.argv or '--benchmark' in sys.argv:
        from test_volume_fog_composite_gpu import Composite
        composite=Composite(sdl,gl)
        gl.UseProgram(program); gl.BindFramebuffer(FRAMEBUFFER,framebuffer)
        # Synthetic checker wall at 20 m and an opaque foreground panel at 4 m.
        # Rendered by the same production shader; not an in-world screenshot.
        width,height=640,360
        boxes=[box(5,11,.35,(1,.05,.7),1,center_x=-1,angle=.45,half_x=3,half_y=2),
               box(8,14,.3,(.03,.7,1),1,center_x=2,angle=-.3,half_x=3,half_y=2)]
        if lighting:
            boxes=[box(3,15,.15,(1,1,1),1,half_x=7,half_y=3)]
            vector('vf_ambient',.035,.035,.035); vector('vf_sun_color',0,0,0)
            integer('vf_shadow_mask',0); scalar('vf_anisotropy',.2); integer('vf_steps',32)
            direction=(-math.sqrt(.5),0,-math.sqrt(.5))
            matrices('vf_projector_matrix',projector_matrix((3,0,-6),direction,.45)*4)
            array('vf_projector_normal',[(*direction,0)]*4)
            array('vf_projector_origin',[(3,0,-6,1)]*4)
            lights([(-3,0,-8,4),(3,0,-6,10)],[(2,.12,.015,0),(.1,.6,3,0)],[(-1,-1,1,0),(0,-1,1,0)])
        render(boxes)
        inverse[0]=width/height
        gl.UniformMatrix4fv(loc('inv_proj'),1,False,(F*16)(*inverse))
        colors=[]; depths=[]
        for y in range(height):
            for x in range(width):
                panel=303<x<333 and 65<y<295
                value=.055 if panel else (.16 if (x//32+y//32)%2 else .32)
                colors.extend((value,value,value,0))
                d=(-A+B/(4 if panel else 20))*.5+.5
                depths.extend((d,0,0,0))
        for unit,tex,data in ((0,scene,colors),(1,depth_tex,depths),(15 if lighting else 2,output,None)):
            gl.ActiveTexture(0x84C0+unit); gl.BindTexture(TEXTURE,tex)
            gl.TexImage2D(TEXTURE,0,0x8814,width,height,0,RGBA,FLOAT,None if data is None else (F*len(data))(*data))
        # Minimal PNG encoder keeps the test harness standard-library-only.
        def chunk(kind,data):
            return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
        previews=[]
        for quality,divisor,steps,minimum in (('high',1,32,8),('balanced',2,24,6)):
            fw,fh=(width+divisor-1)//divisor,(height+divisor-1)//divisor
            gl.ActiveTexture(0x84C0+15); gl.BindTexture(TEXTURE,output)
            gl.TexImage2D(TEXTURE,0,0x881A,fw,fh,0,RGBA,FLOAT,None)
            gl.UseProgram(program); gl.BindFramebuffer(FRAMEBUFFER,framebuffer)
            integer('vf_steps',steps); integer('vf_min_steps',minimum)
            gl.Uniform2f(loc('vf_target_size'),fw,fh)
            gl.Viewport(0,0,fw,fh); gl.DrawArrays(4,0,3)
            composite.draw(scene,depth_tex,output,inverse,width,height)
            pixels=(F*(width*height*4))()
            gl.ReadPixels(0,0,width,height,RGBA,FLOAT,pixels)
            assert gl.GetError()==0
            previews.append(list(pixels))
            raw=bytearray()
            for y in reversed(range(height)):
                raw.append(0)
                for x in range(width):
                    for c in range(3):
                        v=max(0.,min(1.,pixels[(y*width+x)*4+c]))
                        v=12.92*v if v<=.0031308 else 1.055*v**(1/2.4)-.055
                        raw.append(round(v*255))
            png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')
            destination=ROOT/('tmp/volume-fog-'+quality+'-preview.png')
            destination.parent.mkdir(exist_ok=True)
            destination.write_bytes(png)
            print('Synthetic GPU preview:',destination)
        mean_error=sum(abs(x-y) for x,y in zip(*previews))/len(previews[0])
        assert mean_error<.01,mean_error
        print(f'Balanced versus High preview mean absolute linear RGBA difference: {mean_error:.6f}')
        gl.UseProgram(program)
        if '--benchmark' in sys.argv:
            import statistics
            # Measure the integration and integration+reconstruction separately.
            # Excludes the final color copy, TAA and scene/shadow rendering.
            # Increase all input/target sizes; hold the fog across the full view.
            width,height=1920,1080
            for unit,tex in ((0,scene),(1,depth_tex),(2 if not lighting else 15,output)):
                gl.ActiveTexture(0x84C0+unit); gl.BindTexture(TEXTURE,tex)
                color=(.1,.2,.3,0) if unit==0 else (1,0,0,0)
                data=None if tex==output else (F*(width*height*4))(*(color*(width*height)))
                gl.TexImage2D(TEXTURE,0,0x8814,width,height,0,RGBA,FLOAT,data)
            integer('vf_count',1)
            array('vf_axis_x',[(1,0,0,0)]); array('vf_axis_y',[(0,1,0,0)]); array('vf_axis_z',[(0,0,1,9)])
            array('vf_half_density',[(40,40,6,.1)]); array('vf_color_softness',[(1,1,1,1)])
            query=obj(gl.GenQueries)
            for label in ('typical','eight lights','shadowed') if lighting else ('unlit',):
                gl.UseProgram(program)
                if label=='eight lights':
                    lights([(i-4,0,-8,6) for i in range(8)])
                elif label=='shadowed':
                    integer('vf_shadow_mask',1); vector('vf_sun_color',1,1,1)
                for quality,divisor,steps,minimum in (('Performance',2,16,4),('Balanced',2,24,6),('High',1,32,8),('Ultra',1,64,8)):
                    fw,fh=(width+divisor-1)//divisor,(height+divisor-1)//divisor
                    gl.ActiveTexture(0x84C0+15); gl.BindTexture(TEXTURE,output)
                    gl.TexImage2D(TEXTURE,0,0x881A,fw,fh,0,RGBA,FLOAT,None)
                    gl.UseProgram(program)
                    integer('vf_steps',steps); integer('vf_min_steps',minimum)
                    gl.Uniform2f(loc('vf_target_size'),fw,fh)
                    for combined in (False,True):
                        samples=[]
                        for iteration in range(10):
                            gl.UseProgram(program); gl.BindFramebuffer(FRAMEBUFFER,framebuffer); gl.Viewport(0,0,fw,fh)
                            gl.BeginQuery(0x88BF,query); gl.DrawArrays(4,0,3)
                            if combined: composite.draw(scene,depth_tex,output,inverse,width,height)
                            gl.EndQuery(0x88BF)
                            elapsed=C.c_uint64(); gl.GetQueryObjectui64v(query,0x8866,C.byref(elapsed))
                            if iteration>=3: samples.append(elapsed.value/1e6)
                        print(f'1080p {label}, {quality}, {"march+reconstruct" if combined else "march"} GPU median: {statistics.median(samples):.3f} ms')


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try: run(sdl,gl,lighting='--lighting' in sys.argv)
    finally:
        sdl.SDL_GL_DestroyContext(ctx); sdl.SDL_DestroyWindow(window); sdl.SDL_Quit()
