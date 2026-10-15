"""Measure actual CEF shared-memory paints using the shipped SLPlugin protocol.

Windows-only diagnostic, with an isolated cache and local scroll fixture. Does
not log in or touch the viewer's browser session. Not a viewer presentation test.
"""
import argparse
import hashlib
import json
import mmap
from pathlib import Path
import socket
import statistics
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / 'build-vc170-64/newview/Release'


def encode(value):
    if isinstance(value, dict):
        node = ET.Element('map')
        for key, item in value.items():
            ET.SubElement(node, 'key').text = key
            node.append(encode(item))
        return node
    kind = {bool: 'boolean', int: 'integer', float: 'real', str: 'string'}[type(value)]
    node = ET.Element(kind)
    node.text = str(int(value)) if isinstance(value, bool) else str(value)
    return node


def decode(node):
    if node.tag == 'map':
        items = list(node)
        return {items[i].text: decode(items[i+1]) for i in range(0, len(items), 2)}
    if node.tag == 'integer': return int(node.text or 0)
    if node.tag == 'real': return float(node.text or 0)
    if node.tag == 'boolean': return node.text in ('true', '1')
    return node.text or ''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', default='baseline')
    parser.add_argument('--seconds', type=float, default=8)
    parser.add_argument('--sleeps', type=float, nargs='+', default=[.02, .01, .001])
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    assert 1 <= args.seconds <= 60 and 1 <= args.repeats <= 10
    assert all(.001 <= s <= 1 for s in args.sleeps)
    output = ROOT / '.logs/browser-cadence' / (args.label + '-' + uuid.uuid4().hex[:8])
    output.mkdir(parents=True)
    width, height = 960, 640
    name = 'Local\\PrismCadence-' + uuid.uuid4().hex
    memory = mmap.mmap(-1, width * height * 4, tagname=name)
    server = socket.socket()
    server.bind(('127.0.0.1', 0)); server.listen(1); server.settimeout(30)
    process = subprocess.Popen([str(RELEASE / 'slplugin.exe'), str(server.getsockname()[1])],
                               cwd=RELEASE / 'llplugin', creationflags=subprocess.CREATE_NO_WINDOW)
    conn = None
    try:
        conn, _ = server.accept(); conn.settimeout(.1)
        buffer = b''
        def send(cls, event, **params):
            node = ET.Element('llsd'); node.append(encode({'class': cls, 'name': event, 'params': params}))
            conn.sendall(ET.tostring(node) + b'\0')
        def messages():
            nonlocal buffer
            try:
                part = conn.recv(262144)
                if not part: raise RuntimeError('Plugin disconnected')
                buffer += part
            except socket.timeout:
                return []
            result = []
            while b'\0' in buffer:
                message, buffer = buffer.split(b'\0', 1)
                result.append(decode(ET.fromstring(message)[0]))
            return result
        def wait(event):
            deadline = time.perf_counter() + 40
            while time.perf_counter() < deadline:
                for msg in messages():
                    if msg['name'] == event: return msg
            raise RuntimeError('Timeout waiting for ' + event)
        wait('hello')
        send('internal', 'load_plugin', file='media_plugin_cef.dll', dir=str(RELEASE / 'llplugin'))
        wait('load_plugin_response')
        send('internal', 'sleep_time', time=.01)
        send('media', 'set_user_data_path', cache_path=str(output) + '/', username='',
             cef_log_file=str(output / 'cef.log'), cef_verbose_log=False, cef_remote_debugging_port='0x0')
        send('media', 'init', target='', factor=1.0)
        wait('texture_params')
        send('internal', 'shm_add', name=name, size=width * height * 4)
        wait('shm_add_response')
        send('media', 'size_change', name=name, width=width, height=height, texture_width=width, texture_height=height)
        wait('size_change_response')
        send('media', 'load_uri', uri=(ROOT / 'scripts/tests/browser_scroll.html').as_uri() + '?auto')
        wait('navigate_complete')
        results = []
        for repeat in range(args.repeats):
            for delay in (args.sleeps if repeat % 2 == 0 else args.sleeps[::-1]):
                send('internal', 'sleep_time', time=delay)
                warmup = time.perf_counter() + 3
                while time.perf_counter() < warmup: messages()
                started = time.perf_counter(); paints = []; page = []; cpu = []
                while time.perf_counter() - started < args.seconds:
                    for msg in messages():
                        now = time.perf_counter() - started
                        params = msg['params']
                        if msg['name'] == 'updated':
                            offset = ((height - 8) * width + 8) * 4
                            b, g, r, _ = memory[offset:offset+4]
                            paints.append({'time': now, 'frame': r + (g << 8) + (b << 16)})
                        elif msg['name'] == 'debug_message' and 'CADENCE ' in params.get('message_text', ''):
                            payload = params['message_text'].split('CADENCE ', 1)[1]
                            page.append(json.JSONDecoder().raw_decode(payload)[0])
                        elif msg['name'] == 'heartbeat': cpu.append(params['cpu_usage'])
                elapsed = time.perf_counter() - started
                unique = [p for i, p in enumerate(paints) if i == 0 or p['frame'] != paints[i-1]['frame']]
                intervals = [(b['time'] - a['time']) * 1000 for a, b in zip(unique, unique[1:])]
                row = dict(repeat=repeat, sleep=delay, elapsed=elapsed, paints=paints, page=page,
                           heartbeat_cpu=cpu, unique_pixel_fps=len(unique)/elapsed, paint_fps=len(paints)/elapsed,
                           page_fps=statistics.mean(p['fps'] for p in page) if page else None,
                           median_ms=statistics.median(intervals) if intervals else None,
                           p95_ms=sorted(intervals)[int((len(intervals)-1)*.95)] if intervals else None)
                results.append(row)
                print(json.dumps({k:v for k,v in row.items() if k not in ('paints','page','heartbeat_cpu')}), flush=True)
        binaries = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                    [RELEASE/'slplugin.exe', RELEASE/'llplugin/media_plugin_cef.dll', RELEASE/'llplugin/libcef.dll']}
        (output/'results.json').write_text(json.dumps(dict(width=width, height=height, binaries=binaries, results=results), indent=2))
        print(output/'results.json', flush=True)
    finally:
        if conn:
            try:
                send('internal', 'shutdown_plugin')
                deadline = time.perf_counter() + 8
                while process.poll() is None and time.perf_counter() < deadline: messages()
            except (OSError, RuntimeError): pass
            conn.close()
        if process.poll() is None: process.terminate()
        process.wait(timeout=10)
        server.close(); memory.close()


if __name__ == '__main__':
    main()
