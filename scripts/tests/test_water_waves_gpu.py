"""Production spectra/IFFT/resolve on a hidden GPU; independent DFT reference.
Run: .venv/Scripts/python.exe scripts/tests/test_water_waves_gpu.py
"""
from array import array
import cmath
import ctypes as C
import math
from pathlib import Path
import statistics
from test_eye_adaptation_gpu import EyeGPU
from test_water_gpu import function
from test_taa_gpu import context, U, I

ROOT=Path(__file__).resolve().parents[2]
SHADERS=ROOT/'indra/newview/app_settings/shaders/class1/environment'

def run(sdl,gl):
    gpu=EyeGPU(sdl,gl)
    count=0
    def check(ok,label):
        nonlocal count
        assert ok,label
        count+=1
    def close(a,b,tolerance=3e-4):
        return all(abs(x-y)<tolerance for x,y in zip(a,b))
    programs=[]
    for file in ('waterWaveFieldF.glsl','waterWaveFFTF.glsl','waterWaveResolveF.glsl'):
        source=(SHADERS/file).read_text()
        programs.append(gpu.program(source))
        # Actual viewer GLSL version as well as the harness's portable GLSL 150.
        shader=gl.CreateShader(0x8B30)
        text=C.c_char_p(('#version 420\n'+source).encode())
        gl.ShaderSource(shader,1,C.byref(text),None);gl.CompileShader(shader)
        ok,log=I(),C.create_string_buffer(16384)
        gl.GetShaderiv(shader,0x8B81,C.byref(ok));gl.GetShaderInfoLog(shader,len(log),None,log)
        check(bool(ok.value),file+': '+log.value.decode());gl.DeleteShader(shader)
    seed,fft,resolve=programs
    check('waterWaveSpectrum' in gpu.reserved,'FFT sampler registered with viewer')

    def transform(targets,size):
        source=0
        for axis in range(2):
            gpu.uniform(fft,'water_fft_axis',axis,integer=True)
            for stage in range(1,size.bit_length()):
                gpu.bind(fft,'waterWaveSpectrum',0,targets[source])
                gpu.uniform(fft,'water_fft_stage',stage,integer=True)
                gpu.render(fft,targets[1-source],size,size)
                source=1-source
        return targets[source]

    # Direct DFT, independent of the butterfly/index algorithm in the shader.
    size=8
    values=[math.sin(i*.731)+math.cos(i*.191)*.3 for i in range(size*size*4)]
    small=[gpu.tex(size,size,values,internal=0x8814),gpu.tex(size,size,internal=0x8814)]
    actual=gpu.pixels(transform(small,size),size,size)
    for y in range(size):
        for x in range(size):
            expected=[]
            for c in (0,2):
                value=sum(complex(*values[(v*size+u)*4+c:(v*size+u)*4+c+2])*
                          cmath.exp(2j*math.pi*(u*x+v*y)/size)
                          for v in range(size) for u in range(size))/(size*size)
                expected.extend((value.real,value.imag))
            check(close(actual[(y*size+x)*4:(y*size+x)*4+4],expected,2e-6),'IFFT matches direct DFT')

    targets=[gpu.tex(256,256,internal=0x8814),gpu.tex(256,256,internal=0x8814)]
    slopes=gpu.tex(256,256);output=gpu.tex(1,1)
    outdir=ROOT/'output/water-wave-review';outdir.mkdir(parents=True,exist_ok=True)
    def seed_at(time,crossing=.25,scale=1):
        gpu.uniform(seed,'water_wave_time',time%1200)
        gpu.uniform(seed,'water_cross_swell',crossing)
        gpu.uniform(seed,'water_wave_scale',scale)
        gpu.render(seed,targets[0],256,256)
    def finish():
        height=transform(targets,256)
        gpu.bind(resolve,'waterWaveSpectrum',0,height)
        gpu.render(resolve,slopes,256,256);gpu.reduce(slopes)
        return height

    # Reproduce the pre-lighting caller: it preserves scene glow by disabling
    # alpha writes. Unwritten FP32 scratch channels may contain any old value.
    # Exercise the actual seed/IFFT/resolve sequence, including poisoned alpha,
    # and take the colour-state boundary from the production update function.
    for name,args in {'ColorMask':[C.c_ubyte]*4, 'GetBooleanv':[U,C.c_void_p]}.items():
        setattr(gl,name,C.WINFUNCTYPE(None,*args)(sdl.SDL_GL_GetProcAddress(('gl'+name).encode())))
    update=function((ROOT/'indra/newview/lldrawpoolwater.cpp').read_text(),
                    'void LLDrawPoolWater::updateWaveField(')
    seed_index=update.index('gPipeline.mWaterWaveScratch[0].bindTarget()')
    resolve_index=update.index('gPipeline.mWaterWaves.flush()')
    owns_color=('glGetBooleanv(GL_COLOR_WRITEMASK, color_mask)' in update[:seed_index] and
                'gGL.setColorMask(true, true)' in update[:seed_index])
    restores_color='gGL.setColorMask(color_mask[0], color_mask[1], color_mask[2], color_mask[3])' in update[resolve_index:]
    poison=[v for _ in range(256*256) for v in (0,0,0,float('nan'))]
    def inherited_update(mask, own_state):
        for target in targets:
            gpu.upload_tex(target,256,256,poison,internal=0x8814)
        gpu.upload_tex(slopes,256,256,poison)
        gl.ColorMask(*mask)
        saved=(C.c_ubyte*4)();gl.GetBooleanv(0x0C23,saved)
        if own_state: gl.ColorMask(1,1,1,1)
        seed_at(2,.95,.11);finish()
        if own_state and restores_color: gl.ColorMask(*saved)
        after=(C.c_ubyte*4)();gl.GetBooleanv(0x0C23,after)
        data=gpu.pixels(slopes,256,256)
        gl.ColorMask(1,1,1,1)
        return data,tuple(after)
    broken,_=inherited_update((1,1,1,0),False)
    check(any(not math.isfinite(v) for v in broken),
          'regression reproduced: inherited RGB-only writes corrupt the FFT and surface slopes')
    reference,_=inherited_update((1,1,1,1),True)
    for mask in ((1,1,1,0),(0,0,0,0),(1,0,1,0),(0,0,0,1)):
        actual,after=inherited_update(mask,owns_color)
        check(all(math.isfinite(v) for v in actual),'wave update overwrites every undefined scratch channel')
        check(actual==reference,'wave field is independent of the preceding draw colour mask')
        check(after==mask,'wave update restores its caller colour mask')

    for time in (0,2,1199.98):
        seed_at(time)
        spectrum=gpu.pixels(targets[0],256,256)
        check(spectrum[:4]==[0]*4,'zero DC energy')
        for x,y in ((7,3),(13,251),(33,17),(255,2)):
            a=spectrum[(y*256+x)*4:(y*256+x)*4+4]
            i=(((-y)%256)*256+(-x)%256)*4;b=spectrum[i:i+4]
            check(close(a,[b[0],-b[1],b[2],-b[3]],.005),'Hermitian symmetry yields real heights')
        if time==0:
            powers=[]
            for y in range(256):
                for x in range(256):
                    i=(y*256+x)*4
                    k2=(x if x<128 else x-256)**2+(y if y<128 else y-256)**2
                    powers.append(k2*(spectrum[i]**2+spectrum[i+1]**2))
            total=sum(powers);effective_modes=total**2/sum(v*v for v in powers)
            check(max(powers)/total<.015,'no single swell mode dominates')
            check(effective_modes>300,'swell energy spread across hundreds of modes')
            print(f'Swell effective mode count: {effective_modes:.0f}; largest mode: {max(powers)/total:.2%}')
        height=finish()
        heights=gpu.pixels(height,256,256);data=gpu.pixels(slopes,256,256)
        check(all(math.isfinite(v) for v in data),'finite full-resolution slopes')
        check(max(abs(v) for c in (1,3) for v in heights[c::4])<1e-5,'negligible imaginary height residual')
        for x,y in ((0,0),(255,255),(11,27),(84,197)):
            def h(px,py,c):return heights[((py%256)*256+(px%256))*4+c]
            expected=[]
            for c,metres in ((0,1),(2,.25)):
                expected.extend((-(h(x+1,y,c)-h(x-1,y,c))/(2*metres),-(h(x,y+1,c)-h(x,y-1,c))/(2*metres)))
            i=(y*256+x)*4
            check(close(data[i:i+4],expected),'slopes match generated heights, including tile edges')
        rms=math.sqrt(sum(v*v for c in (0,1) for v in data[c::4])/(256*256))
        check(.10<rms<.17,'controlled swell energy')
        check(max(abs(v) for v in gpu.pixels(slopes,1,1,8))<1e-5,'mips converge to zero mean slope')
        if time in (0,2):
            with (outdir/f'fft-slopes-{int(time)}.f32').open('wb') as file:array('f',data).tofile(file)
        if time==0:
            baseline=data;variance=sum(v*v for c in (0,1) for v in data[c::4])
            for shift in (24,96):
                correlation=sum(data[(y*256+x)*4+c]*data[(y*256+(x+shift)%256)*4+c]
                                for y in range(256) for x in range(256) for c in (0,1))/variance
                check(abs(correlation)<.25,'no former 24/96-metre periodic lattice')
        if time==2:
            check(sum((a-b)**2 for a,b in zip(data,baseline))/sum(v*v for v in baseline)>.5,'shape evolves over time')

    # Scaling the physical domain preserves resolved spectrum energy even at
    # 0.01; shrinking only the spectral peak used to lose sub-texel waves.
    initial=gpu.program((SHADERS/'waterWaveFieldF.glsl').read_text().replace('void main()', 'void seedMain()')+'''
        uniform int fixture_band, fixture_mode;
        void main(){
            ivec2 index=ivec2(fixture_mode,0);
            frag_color=vec4(waterInitialSpectrum(index,fixture_band),
                            waterInitialSpectrum((-index)&ivec2(255),fixture_band));
        }
    ''')
    initial_target=gpu.tex(1,1,internal=0x8814)
    gpu.uniform(initial,'water_cross_swell',.25)
    coefficients=[]
    for band,mode in ((0,18),(1,33)):
        gpu.uniform(initial,'fixture_band',band,integer=True)
        gpu.uniform(initial,'fixture_mode',mode,integer=True)
        gpu.render(initial,initial_target)
        a=gpu.pixels(initial_target)
        coefficients.append((complex(*a[:2]),complex(*a[2:]).conjugate()))
    reference_spectrum=None
    for scale in (.01,.05,.5,1,2):
        seed_at(0,scale=scale)
        spectrum=gpu.pixels(targets[0],256,256)
        if reference_spectrum is None: reference_spectrum=spectrum
        check(spectrum==reference_spectrum,'size preserves the resolved reference spectrum')
        finish();data=gpu.pixels(slopes,256,256)
        rms=math.sqrt(sum(v*v for c in (0,1) for v in data[c::4])/(256*256))
        check(.08<rms<.19,'wave size preserves controlled slope energy')
        check(all(math.isfinite(v) for v in data),'wave size endpoints stay finite')
        # Evolve both traveling components independently on the CPU. Their
        # phase must follow deep-water dispersion in physical metres.
        time=.13;seed_at(time,scale=scale)
        evolved=gpu.pixels(targets[0],256,256)
        for band,domain,mode in ((0,256,18),(2,64,33)):
            i=mode*4+band
            omega=round(math.sqrt(9.81*2*math.pi*mode/(domain*scale))*1200/(2*math.pi))*2*math.pi/1200
            a,b=coefficients[band//2]
            expected=a*cmath.exp(-1j*omega*time)+b*cmath.exp(1j*omega*time)
            check(abs(complex(*evolved[i:i+2])-expected)<abs(expected)*.002,
                  f'scaled waves follow physical dispersion: {scale}, {band}, {expected}, {complex(*evolved[i:i+2])}')

    seed_at(0);start=gpu.pixels(targets[0],256,256)
    seed_at(1200)
    check(gpu.pixels(targets[0],256,256)==start,'wrapped long-session time preserves phase')
    seed_at(0,0);without_cross=gpu.pixels(targets[0],256,256)
    check(without_cross[2::4]==start[2::4] and without_cross[3::4]==start[3::4],'crossing control preserves chop')
    check(without_cross[0::4]!=start[0::4],'optional crossing control changes swell')
    seed_at(0,3);strong_cross=gpu.pixels(targets[0],256,256)
    check(strong_cross[2::4]==start[2::4] and strong_cross[3::4]==start[3::4],
          'crossing strength 3 preserves the chop band')
    finish();strong_slopes=gpu.pixels(slopes,256,256)
    check(all(math.isfinite(v) for v in strong_slopes),'crossing strength 3 stays finite')
    cross_energy=lambda data:sum(v*v for v in data[1::4])
    check(cross_energy(strong_slopes)>4*cross_energy(baseline),
          'crossing strength 3 substantially increases transverse slope energy')
    seed_at(0)
    finish()
    helper=gpu.program((SHADERS/'waterWavesF.glsl').read_text() + function((SHADERS/'waterFogF.glsl').read_text(), 'vec2 waterSpectralSlope(')+'''
        uniform vec2 fixture_position;
        uniform float fixture_distance;
        out vec4 frag_color;
        void main(){frag_color=vec4(waterSurfaceSlope(fixture_position,vec2(0),vec2(0),vec4(0),fixture_distance),0,1);}
    ''')
    flat=gpu.tex(1,1,[.5,.5,1,1])
    for name,unit,tex in (('waterWaveSlopes',0,slopes),('bumpMap',1,flat),('bumpMap2',2,flat)):
        gpu.bind(helper,name,unit,tex)
    gl.ActiveTexture(0x84C0);gl.BindTexture(0x0DE1,slopes)
    for p in (0x2802,0x2803):gl.TexParameteri(0x0DE1,p,0x2901)
    gpu.uniform(helper,'water_procedural_waves',1,integer=True)
    gpu.uniform(helper,'water_wave_strength',1);gpu.uniform(helper,'water_wave_direction',.8,.6)
    gpu.uniform(helper,'water_wave_scale',1)
    gpu.uniform(helper,'water_wave_origin',0,0);gpu.uniform(helper,'fixture_position',21,37)
    gpu.uniform(helper,'fixture_distance',250)
    def slope():
        gpu.bind(helper,'waterWaveSlopes',0,slopes);gpu.render(helper,output)
        return gpu.pixels(output)[:2]
    original=slope();gpu.uniform(helper,'fixture_distance',10)
    check(close(slope(),original),'flat fine detail is an additive identity')
    gpu.uniform(helper,'water_wave_strength',2)
    check(close(slope(),[2*x for x in original]),'strength scales slopes')
    gpu.uniform(helper,'water_wave_strength',0)
    check(close(slope(),[0,0]),'zero strength with flat detail gives flat water')
    gpu.uniform(helper,'water_wave_strength',1);gpu.uniform(helper,'fixture_distance',250)
    gpu.uniform(helper,'fixture_position',21-256,37+256)
    gpu.uniform(helper,'water_wave_origin',math.fmod(.8*256+.6*-256,256),math.fmod(-.6*256+.8*-256,256))
    check(close(slope(),original),'region-origin shifts preserve the same global sample')
    for scale in (.01,.05,.5,2):
        gpu.uniform(helper,'water_wave_scale',scale)
        gpu.uniform(helper,'water_wave_origin',0,0)
        gpu.uniform(helper,'fixture_position',21*scale,37*scale)
        check(close(slope(),original),'wave size scales crest spacing while preserving slopes')
        gpu.uniform(helper,'fixture_position',21*scale-256,37*scale+256)
        gpu.uniform(helper,'water_wave_origin',math.fmod((.8*256+.6*-256)/scale,256),
                    math.fmod((-.6*256+.8*-256)/scale,256))
        check(close(slope(),original,.002),'scaled waves stay continuous across region origins')

    gpu.uniform(helper,'water_wave_strength',0)
    gpu.uniform(helper,'water_wake_count',1,integer=True)
    gpu.uniform(helper,'water_wakes[0]',0,0,0,1)
    gpu.uniform(helper,'fixture_position',.4,0)
    wake=slope()
    check(wake[0]>.05 and abs(wake[1])<.001,'local wake bends the water normal')
    gpu.uniform(helper,'fixture_position',5,0)
    check(close(slope(),[0,0]),'wake leaves distant water unchanged')
    gpu.uniform(helper,'fixture_position',.4,0)
    gpu.uniform(helper,'water_procedural_waves',0,integer=True)
    check(close(slope(),wake),'wake also works with authored water normals')
    gpu.uniform(helper,'water_wake_count',0,integer=True)
    check(close(slope(),[0,0]),'zero wake count restores the baseline')
    gpu.uniform(helper,'water_wake_count',1,integer=True)
    gpu.uniform(helper,'water_wakes[0]',0,0,2.5,1)
    gpu.uniform(helper,'fixture_position',3.15,0)
    check(close(slope(),[0,0]),'expired wake fades away')

    for name,args in {'GenQueries':[I,C.POINTER(U)],'BeginQuery':[U,U],'EndQuery':[U],
        'GetQueryObjectui64v':[U,U,C.POINTER(C.c_uint64)],'DeleteQueries':[I,C.POINTER(U)]}.items():
        setattr(gl,name,C.WINFUNCTYPE(None,*args)(sdl.SDL_GL_GetProcAddress(('gl'+name).encode())))
    query=U();gl.GenQueries(1,C.byref(query));timings=[]
    for iteration in range(12):
        gl.BeginQuery(0x88BF,query.value);seed_at(iteration/60);finish();gl.EndQuery(0x88BF)
        nanos=C.c_uint64();gl.GetQueryObjectui64v(query.value,0x8866,C.byref(nanos))
        if iteration>=2:timings.append(nanos.value/1e6)
    gl.DeleteQueries(1,C.byref(query));check(gl.GetError()==0,'no GL errors')
    print(f'Passed {count} wave-spectrum GPU checks on {gl.GetString(0x1F01).decode()}')
    print(f'Spectra + IFFT + slopes + mips: median {statistics.median(timings):.3f} ms (isolated GPU pipeline)')

if __name__=='__main__':
    sdl,window,ctx,gl=context()
    try:run(sdl,gl)
    finally:
        sdl.SDL_GL_DestroyContext(ctx);sdl.SDL_DestroyWindow(window);sdl.SDL_Quit()
