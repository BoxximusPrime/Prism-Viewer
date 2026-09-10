import ctypes as C
import struct as S
from pathlib import Path

dump = max(Path('C:/Users/Trevor/AppData/Local/CrashDumps').glob('secondlife-bin.exe.*.dmp'), key=lambda p:p.stat().st_mtime)
data = dump.read_bytes()
count, directory = S.unpack_from('<II', data, 8)
streams = {S.unpack_from('<III', data, directory+i*12)[0]: S.unpack_from('<III', data, directory+i*12)[1:] for i in range(count)}
_, offset = streams[6]
code = S.unpack_from('<I', data, offset+8)[0]
address = S.unpack_from('<Q', data, offset+24)[0]
ctx_size, ctx = S.unpack_from('<II', data, offset+160)
rsp, rip = S.unpack_from('<Q', data, ctx+152)[0], S.unpack_from('<Q', data, ctx+248)[0]
print(f'Exception {code:#x}; address {address:#x}; RIP {rip:#x}; RSP {rsp:#x}')
_, modules = streams[4]
module_count = S.unpack_from('<I', data, modules)[0]
for i in range(module_count):
    off = modules+4+i*108
    base, size = S.unpack_from('<QI', data, off)
    name_off = S.unpack_from('<I', data, off+20)[0]
    name_len = S.unpack_from('<I', data, name_off)[0]
    name = data[name_off+4:name_off+4+name_len].decode('utf-16-le')
    if base <= rip < base+size:
        print(f'Fault module: {name}; offset {rip-base:#x}')
        image_base = base
        image_name = name
        image_size = size

dbg = C.WinDLL('C:/Program Files (x86)/Microsoft Visual Studio/Shared/Common/VSPerfCollectionTools/vs2022/x64/dbghelp.dll', use_last_error=True)
kernel = C.WinDLL('kernel32')
kernel.GetCurrentProcess.restype = C.c_void_p
process = kernel.GetCurrentProcess()
dbg.SymInitializeW.argtypes = [C.c_void_p, C.c_wchar_p, C.c_int]
dbg.SymLoadModuleExW.argtypes = [C.c_void_p,C.c_void_p,C.c_wchar_p,C.c_wchar_p,C.c_uint64,C.c_uint32,C.c_void_p,C.c_uint32]
dbg.SymLoadModuleExW.restype = C.c_uint64
dbg.SymFromAddr.argtypes = [C.c_void_p,C.c_uint64,C.POINTER(C.c_uint64),C.c_void_p]
print('SymInit:',dbg.SymInitializeW(process, str(Path(image_name).parent), False), C.get_last_error())
loaded = dbg.SymLoadModuleExW(process,None,image_name,None,image_base,0,None,0)
print(f'Symbol module loaded: {loaded:#x}; error {C.get_last_error()}')
def symbol(addr):
    buf = C.create_string_buffer(88+1024)
    S.pack_into('<I',buf,0,88)
    S.pack_into('<I',buf,80,1024)
    displacement = C.c_uint64()
    if dbg.SymFromAddr(process,addr,C.byref(displacement),buf):
        return buf.raw[84:].split(b'\0')[0].decode(errors='replace')+f'+{displacement.value:#x}'
    return '?'
print('Fault:',symbol(rip))
class Line(C.Structure):
    _fields_=[('SizeOfStruct',C.c_uint32),('Key',C.c_void_p),('LineNumber',C.c_uint32),('FileName',C.c_char_p),('Address',C.c_uint64)]
line=Line();line.SizeOfStruct=C.sizeof(Line)
delta=C.c_uint32()
dbg.SymGetLineFromAddr64.argtypes=[C.c_void_p,C.c_uint64,C.POINTER(C.c_uint32),C.POINTER(Line)]
if dbg.SymGetLineFromAddr64(process,rip,C.byref(delta),C.byref(line)):
    print('Source:',line.FileName.decode(),line.LineNumber)
# Stack candidates are diagnostic pointers, not an unwound stack.
_, threads = streams[3]
for i in range(S.unpack_from('<I',data,threads)[0]):
    off=threads+4+i*48
    start, length, rva = S.unpack_from('<QII',data,off+24)
    if start <= rsp < start+length:
        pos=rva+rsp-start
        for j in range(0,min(512,length-(rsp-start)),8):
            value=S.unpack_from('<Q',data,pos+j)[0]
            if image_base <= value < image_base+image_size:
                print(f'Stack +{j:#x}:',symbol(value))
