"""Variable guide topology, buffer bounds, rendering/history and bend falloff."""
import ctypes as C
import math
import struct
from test_taa_gpu import GPU, SHADERS, W, H
from test_exact_oit_gpu import context, U, SSBO


def run(sdl, gl):
    gpu=GPU(sdl,gl)
    gl.TexBuffer=C.WINFUNCTYPE(None,U,U,U)(sdl.SDL_GL_GetProcAddress(b'glTexBuffer'))
    common=(SHADERS/'class1/deferred/hairDeformV.glsl').read_text()
    solver=gpu.compute((SHADERS/'class1/deferred/hairGuideC.glsl').read_text(),
                       (SHADERS/'class1/deferred/hairCollision.glsl').read_text())
    identity=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
    def buffer(data):
        b,t=gpu.obj(gl.GenBuffers),gpu.obj(gl.GenTextures)
        raw=struct.pack(f'{len(data)*4}f',*(v for p in data for v in p))
        gl.BindBuffer(SSBO,b);gl.BufferData(SSBO,len(raw),C.create_string_buffer(raw),0x88E8)
        gl.BindTexture(0x8C2A,t);gl.TexBuffer(0x8C2A,0x8814,b)
        return b,t
    def texture(unit,pair):
        gl.ActiveTexture(0x84C0+unit);gl.BindTexture(0x8C2A,pair[1])
    def read(pair,count):
        gl.BindBuffer(SSBO,pair[0]);raw=C.create_string_buffer(count*16)
        gl.GetBufferSubData(SSBO,0,len(raw),raw)
        return list(struct.iter_unpack('4f',raw.raw))
    def dispatch(program,groups=1):
        gl.UseProgram(program);gl.DispatchCompute(groups,1,1);gl.MemoryBarrier(0x2000|0x8|0x200)
    def guides(count,deformed=False):
        data=[]
        for chain in range(count):
            angle=chain*math.tau/count
            rest=[(.15*math.cos(angle),.15*math.sin(angle),-.1*i,1) for i in range(9)]
            moved=[(p[0]+(.03*math.cos(angle)*i/8 if deformed else 0),*p[1:]) for i,p in enumerate(rest)]
            data.extend(rest+moved+[(0,0,0,0)]*9)
        data[0]=(*data[0][:3],count)
        return data
    gpu.matrix(solver,'guide_from_previous',identity)
    gpu.uniform(solver,'hair_previous_guides',29,integer=True)
    gpu.uniform(solver,'guide_history',1,integer=True)
    for name,value in {'hair_root_radius':.08,'hair_root_gradient':.1,'guide_dt':1/60,
                       'guide_stiffness':6,'guide_retention':0}.items():gpu.uniform(solver,name,value)
    canary=[(123,456,789,321)]*64
    for count in (4,7,16,31,64):
        data=guides(count)+canary
        old,out=buffer(data),buffer(data)
        gpu.uniform(solver,'guide_gravity',2,0,0)
        for _ in range(30):
            texture(29,old);gl.BindBufferBase(SSBO,5,out[0]);dispatch(solver,(count+15)//16);old,out=out,old
        result=read(old,len(data))
        assert result[count*27:]==canary, 'partial workgroup overwrote binding palette after guide points'
        assert all(math.isfinite(v) for p in result for v in p)
        for chain in range(count):
            base=chain*27
            assert math.dist(result[base][:3],result[base+9][:3])<1.e-6, 'root moved'
            assert result[base+17][0]>data[base+17][0]+.01, 'rope was not simulated'
            assert all(math.dist(result[base+i][:3],data[base+i][:3])<1.e-6 for i in range(9))
        print('PASS: density, all ropes simulated and appended palette untouched:',count)

    render=gpu.compute('''layout(local_size_x=1) in;
layout(std430,binding=5) buffer Output { vec4 result[]; };
uniform vec3 sample_position;
vec3 getHairDeformedPosition(vec3 p);
void main(){result[0]=vec4(getHairDeformedPosition(sample_position),1);}
''',common)
    output=buffer([(0,0,0,0)]*2)
    for name in ('hair_local_from_model','hair_model_from_local'):gpu.matrix(render,name,identity)
    gpu.uniform(render,'hair_guides',29,integer=True);gpu.uniform(render,'hair_guide_active',1,integer=True)
    gpu.uniform(render,'hair_root_radius',.08)
    for count in (4,7,16,31,64):
        data=guides(count,True);pair=buffer(data);texture(29,pair)
        gl.BindBufferBase(SSBO,5,output[0])
        for sector in (.35,count-1.35,count-1.e-5,1.e-5):
            angle=sector*math.tau/count;p=(.15*math.cos(angle),.15*math.sin(angle),-.35)
            i=int(sector);f=sector-i
            shift=.03*((1-f)*math.cos(i*math.tau/count)+f*math.cos(((i+1)%count)*math.tau/count))*.35/.8
            gpu.uniform(render,'sample_position',*p);dispatch(render)
            assert math.dist(read(output,1)[0][:3],(p[0]+shift,p[1],p[2]))<1.e-6
    # The previous pose reads topology from its own buffer, even with a different current count.
    motion='#define main productionMain\n'+(SHADERS/'class1/deferred/taaMotionV.glsl').read_text()+'''
#undef main
void main(){productionMain();vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));gl_Position=vec4(p[gl_VertexID],0,1);}
'''
    temporal=gpu.program('in vec4 previous_clip;out vec4 frag_color;void main(){frag_color=previous_clip;}',motion)
    for name in ('taa_previous_mvp','taa_previous_modelview','modelview_projection_matrix','hair_local_from_model','hair_model_from_local',
                 'hair_previous_local_from_model','hair_previous_model_from_local'):gpu.matrix(temporal,name,identity)
    gpu.uniform(temporal,'hair_guide_active',1,integer=True);gpu.uniform(temporal,'hair_guides',28,integer=True)
    gpu.uniform(temporal,'hair_root_radius',.08);texture(28,buffer(guides(64,True)))
    gpu.uniform(temporal,'hair_previous_guide_active',1,integer=True)
    gpu.uniform(temporal,'hair_previous_guides',29,integer=True);gpu.uniform(temporal,'hair_previous_root_radius',.08)
    target=gpu.texture();pixel=(H//2*W+W//2)*4
    for count in (4,31,64):
        data=guides(count,True);pair=buffer(data);texture(29,pair)
        p=data[(count-1)*27+4];gl.VertexAttrib4f(0,*p);gpu.draw(temporal,target)
        assert math.dist(gpu.read(target)[pixel:pixel+3],data[(count-1)*27+13][:3])<.001
    print('PASS: density-aware rendering, circular seam and previous-frame interpolation')

    # Equal initial zigzags: falloff should preserve upper resistance while loosening lower bends.
    data=guides(4)
    for chain in range(4):
        for i in range(9):data[chain*27+9+i]=(.15+.06*(i%2),0,-.08*i,1)
    for name,value in {'guide_stiffness':12,'guide_bend':4,'guide_elasticity':0}.items():gpu.uniform(solver,name,value)
    gpu.uniform(solver,'guide_gravity',0,0,0)
    curves=[]
    for gradient in (0,.6,1.2):
        old,out=buffer(data),buffer(data);texture(29,old);gl.BindBufferBase(SSBO,5,out[0])
        gpu.uniform(solver,'guide_bend_gradient',gradient);dispatch(solver)
        points=read(out,len(data))[9:18]
        edges=[tuple((b[k]-a[k])/math.dist(a[:3],b[:3]) for k in range(3)) for a,b in zip(points,points[1:])]
        curvature=[math.dist(a,b)**2 for a,b in zip(edges,edges[1:])]
        curves.append((sum(curvature[:2]),sum(curvature[-2:])))
        assert math.dist(points[0][:3],data[0][:3])<1.e-6
        print('Bend gradient / upper curvature / lower curvature:',gradient,*curves[-1])
    assert curves[1][1]>curves[0][1]*1.1, 'falloff did not loosen lower bends'
    assert curves[1][1]/curves[0][1]>curves[1][0]/curves[0][0], 'falloff did not favour upper stiffness'
    assert curves[2][1]<curves[1][1], 'longer gradient did not keep more of the rope firm'
    assert gl.GetError()==0
    print('PASS: spatial bend gradient, longer firm region and unchanged pins')


if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try:run(sdl,gl)
    finally:sdl.SDL_GL_DestroyContext(ctx);sdl.SDL_DestroyWindow(window);sdl.SDL_Quit()
