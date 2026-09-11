"""Synthetic two-pass GPU timing using the existing SSS blur harness."""
from pathlib import Path
import sys
import subprocess

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'scripts/tests'))
path = root / 'scripts/tests/test_sss_blur_gpu.py'
source = path.read_text()
start = source.index('    flat=[0.4]*4096; white=[1.0]*4096')
end = source.index("\nif __name__=='__main__':", start)
source = source[:start] + '''
    uniform('sss_params',1,2,0.75,44)
    matrix[5]=0.064
    gl.UniformMatrix4fv(gl.GetUniformLocation(prog,b'inv_proj'),1,0,matrix)
    white=[1.0]*(512*512)
    beam=[1.0 if x<256 else 0.0 for y in range(512) for x in range(512)]
    for smoothing in (0,1):
        uniform('sss_smoothing_pass',smoothing,integer=True)
        for radius in (0.006,0.014,0.028,0.1):
            elapsed=[]
            for sample in range(4):
                filter_image(beam,white,edge=4,radius=radius)
                if sample: elapsed.append(last_ms[0])
            print(f'{"transmission" if smoothing else "diffuse"}: {radius:.3f} m, {statistics.median(elapsed):.3f} ms / 512x512 patch',flush=True)
''' + source[end:]
source = source.replace("uniform('screen_res',64,64)", "uniform('screen_res',512,512)")
source = source.replace('gl.Viewport(0,0,64,64)', 'gl.Viewport(0,0,512,512)')
source = source.replace('0x8814,64,64,0', '0x8814,512,512,0')
source = source.replace('64*64', '512*512')
source = source.replace('gl.ReadPixels(0,0,64,64,RGBA', 'gl.ReadPixels(0,0,512,512,RGBA')
source = source.replace('    def filter_image(', '    query=obj(gl.GenQueries)\n    last_ms=[0.0]\n    def filter_image(')
source = source.replace("        uniform('sss_pass',0,integer=True); gl.DrawArrays", "        gl.BeginQuery(0x88BF,query)\n        uniform('sss_pass',0,integer=True); gl.DrawArrays")
source = source.replace('        pixels=(F*', '        gl.EndQuery(0x88BF)\n        ns=C.c_uint64()\n        gl.GetQueryObjectui64v(query,0x8866,C.byref(ns))\n        last_ms[0]=ns.value/1e6\n        pixels=(F*')
if '--baseline' in sys.argv:
    baseline = subprocess.check_output(['git','show','HEAD:indra/newview/app_settings/shaders/class1/deferred/sssDiffusionF.glsl'],cwd=root,text=True)
    original = Path.read_text
    def read(path, *args, **kwargs):
        if path.name == 'sssDiffusionF.glsl':
            return baseline
        return original(path, *args, **kwargs)
    Path.read_text = read
    print('BASELINE',flush=True)
else:
    print('CURRENT',flush=True)
exec(compile(source,str(path),'exec'),{'__file__':str(path),'__name__':'__main__'})
