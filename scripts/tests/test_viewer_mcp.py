"""MCP protocol, real LEAP bridge transport, and benchmark recovery tests."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch, PropertyMock

MCP_DIR = Path(__file__).resolve().parents[1] / "viewer_mcp"
sys.path.insert(0, str(MCP_DIR))
from leap_bridge import read_packet, write_packet
import viewer_client as vc


class FramingTests(unittest.TestCase):
    def test_binary_types_and_unicode(self):
        packet = {"pump": "reply", "data": {"text": "fog 🌫", "vector": [1.2, -2.3, 7], "flag": True}}
        stream = io.BytesIO()
        write_packet(stream, packet, binary=True)
        self.assertEqual(read_packet(io.BytesIO(stream.getvalue())), packet)

    def test_bad_lengths_and_truncation(self):
        for payload in (b"-1:x", b"9999999999:x", b"20000000:x", b"0:"):
            with self.assertRaises(ValueError):
                read_packet(io.BytesIO(payload))
        with self.assertRaises(EOFError):
            read_packet(io.BytesIO(b"12:short"))

    def test_partial_reads(self):
        class Partial(io.BytesIO):
            def read(self, n=-1):
                return super().read(min(n, 3))
        stream = io.BytesIO()
        packet = {"data": list(range(100))}
        write_packet(stream, packet)
        self.assertEqual(read_packet(Partial(stream.getvalue())), packet)


class BridgeTests(unittest.TestCase):
    def test_real_pipe_http_auth_roundtrip_and_eof_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            session = Path(folder) / "connection.json"
            process = subprocess.Popen([sys.executable, str(MCP_DIR / "leap_bridge.py"), "--session-file", str(session)],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                write_packet(process.stdin, {"pump": "private-reply", "data": {"command": "private-command"}}, binary=True)
                deadline = time.monotonic() + 10
                while not session.exists() and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertTrue(session.exists())
                info = json.loads(session.read_text())
                url = f"http://127.0.0.1:{info['port']}/call"
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                def request(token, body, origin=None):
                    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
                    if origin: headers["Origin"] = origin
                    with opener.open(urllib.request.Request(url, json.dumps(body).encode(), headers), timeout=5) as result:
                        return json.load(result)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    request("wrong", {"op": "status"})
                self.assertEqual(error.exception.code, 403)
                with self.assertRaises(urllib.error.HTTPError):
                    request(info["token"], {"op": "status"}, "http://evil.example")
                with self.assertRaises(urllib.error.HTTPError):
                    request(info["token"], {"op": "arbitrary_event"})
                with ThreadPoolExecutor() as executor:
                    for op, response in [("status", {"logged_in": True}), ("shaders_reload", {"reloaded": True})]:
                        result = executor.submit(request, info["token"], {"op": op})
                        # A real viewer requires notation, not binary, from child stdout.
                        packet = read_packet(process.stdout)
                        self.assertEqual(packet["pump"], "PrismAutomation")
                        self.assertEqual(packet["data"]["op"], op)
                        self.assertEqual(packet["data"]["reply"], "private-reply")
                        write_packet(process.stdin, {"pump": "private-reply", "data": {"reqid": packet["data"]["reqid"], **response}}, binary=True)
                        self.assertTrue(all(result.result(timeout=5)[key] == value for key, value in response.items()))
                process.stdin.close()
                self.assertEqual(process.wait(timeout=5), 0)
                self.assertFalse(session.exists())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                for stream in (process.stdout, process.stderr): stream.close()


class FakeViewer:
    def __init__(self, fail=False):
        self.values = {"RenderPCSSEnabled": True, "RenderSSGIEnabled": True, "RenderShadowDetail": 2, "RenderFSAAType": 2,
                       "RenderVSyncEnable": True, "BackgroundYieldTime": 40, "YieldTime": -1}
        self.history = []
        self.fail = fail
    def call(self, op, **params):
        if op == "camera_get": return {"position_global": [0, 0, 1], "forward": [1, 0, 0], "up": [0, 0, 1], "vertical_fov_degrees": 60}
        if op == "settings_get": return {"values": dict(self.values)}
        if op == "settings_set": self.values.update(params["values"])
        return {}
    def camera_set(self, pose): return pose
    def capture(self, frames, warmup, label, stop):
        self.history.append((label, dict(self.values)))
        if self.fail: raise RuntimeError("GPU failure")
        return {"artifact": label+'.json', "gpu_ms": {"frame": {"median": 10 if self.values["RenderPCSSEnabled"] else 8}}, "frame_interval_ms": {"median": 11}}
    def screenshot(self, label): return {"filename": label+'.png'}


class BenchmarkTests(unittest.TestCase):
    def test_balanced_order_and_restore(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(vc, "ARTIFACTS", Path(folder)):
            fake = FakeViewer()
            suite = vc.Benchmark(fake)
            suite.start(["PCSS"], frames=10, warmup_frames=1, repeats=2)
            suite.thread.join(5)
            self.assertEqual(suite.progress["state"], "complete")
            self.assertEqual([v["RenderPCSSEnabled"] for _,v in fake.history], [True,False,False,True])
            self.assertTrue(fake.values["RenderPCSSEnabled"])
            self.assertTrue(suite.progress["settings_restored"])
            self.assertTrue(fake.values["RenderVSyncEnable"])
            self.assertEqual(fake.values["BackgroundYieldTime"], 40)
            self.assertTrue(all(not v["RenderVSyncEnable"] and v["BackgroundYieldTime"] == 0 for _,v in fake.history))
            self.assertEqual(suite.progress["comparisons"][0]["incremental_gpu_frame_ms"], 2)

    def test_failure_restores(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(vc, "ARTIFACTS", Path(folder)):
            fake = FakeViewer(fail=True)
            suite = vc.Benchmark(fake)
            suite.start(["PCSS"], frames=10, warmup_frames=1, repeats=1)
            suite.thread.join(5)
            self.assertEqual(suite.progress["state"], "failed")
            self.assertTrue(fake.values["RenderPCSSEnabled"])
            self.assertTrue(suite.progress["settings_restored"])

    def test_invalid_selection(self):
        suite = vc.Benchmark(FakeViewer())
        for features in ([], ["PCSS", "PCSS"], ["unknown"]):
            with self.assertRaises(ValueError): suite.start(features)

    def test_taa_skips_smaa_instead_of_mislabeling_its_cost(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(vc, "ARTIFACTS", Path(folder)):
            fake = FakeViewer()
            suite = vc.Benchmark(fake)
            suite.start(["TAA"], frames=10, warmup_frames=1, repeats=1)
            suite.thread.join(5)
            self.assertEqual(fake.history, [])
            self.assertEqual(suite.progress["skipped_features"], ["TAA"])
            self.assertEqual(suite.progress["total_runs"], 0)


class MCPTests(unittest.TestCase):
    def test_shader_reload_preserves_camera_and_settings_and_blocks_benchmark(self):
        import server
        with patch.object(server.client, "call", return_value={"reloaded": True}) as call:
            self.assertEqual(server.shaders_reload(), {"reloaded": True})
            call.assert_called_once_with("shaders_reload")
            call.reset_mock()
            with patch.object(vc.Benchmark, "running", new_callable=PropertyMock, return_value=True):
                with self.assertRaisesRegex(RuntimeError, "benchmark"):
                    server.shaders_reload()
            call.assert_not_called()

    def test_direct_capture_does_not_touch_camera_or_settings(self):
        import server
        with patch.object(server.client, "call", return_value={"state": "warming"}) as call:
            self.assertEqual(server.profile_start(frames=600, warmup_frames=300), {"state": "warming"})
            call.assert_called_once_with("profile_start", frames=600, warmup_frames=300)

    def test_initialize_and_tool_schemas(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        async def check():
            parameters = StdioServerParameters(command=sys.executable, args=[str(MCP_DIR / "server.py")])
            async with stdio_client(parameters) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    names = {tool.name for tool in result.tools}
                    self.assertTrue({"viewer_launch", "viewer_login", "camera_set", "benchmark_start", "profile_result", "shaders_reload"} <= names)
                    self.assertTrue(all(tool.inputSchema.get("type") == "object" for tool in result.tools))
                    result = await session.call_tool("benchmark_status", {})
                    self.assertFalse(result.isError)
        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
