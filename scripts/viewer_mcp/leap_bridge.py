"""Viewer-owned LEAP pipes <-> authenticated loopback JSON. Stdout is LEAP only."""
from __future__ import annotations

import argparse
import hmac
import json
import os
from pathlib import Path
import queue
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import uuid

import llsd

MAX_PACKET = 16 * 1024 * 1024
OPERATIONS = {
    "status", "login", "camera_get", "camera_set", "camera_release",
    "settings_get", "settings_set", "restore", "profile_start", "profile_status",
    "profile_cancel", "snapshot", "shaders_reload", "quit",
}


def read_packet(stream):
    prefix = bytearray()
    while True:
        byte = stream.read(1)
        if not byte:
            raise EOFError("Viewer closed its LEAP pipe")
        if byte == b":":
            break
        if not byte.isdigit() or len(prefix) >= 9:
            raise ValueError("Invalid LEAP length")
        prefix.extend(byte)
    size = int(prefix)
    if not 0 < size <= MAX_PACKET:
        raise ValueError("LEAP packet exceeds limit")
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            raise EOFError("Truncated LEAP packet")
        data.extend(chunk)
    return llsd.parse(bytes(data))


def write_packet(stream, packet, *, binary=False):
    # Viewer -> child is binary, but this viewer deliberately accepts only
    # notation in the reverse direction (LLLeapImpl::rstdout).
    data = llsd.format_binary(packet) if binary else llsd.format_notation(packet)
    stream.write(str(len(data)).encode("ascii") + b":" + data)
    stream.flush()


class LeapConnection:
    def __init__(self, source, sink):
        self.source, self.sink = source, sink
        self.reply_pump = read_packet(source)["pump"]
        self.pending = {}
        self.lock = threading.Lock()
        self.closed = threading.Event()

    def read_forever(self):
        try:
            while True:
                packet = read_packet(self.source)
                data = packet.get("data", {})
                if not isinstance(data, dict):
                    continue
                with self.lock:
                    waiter = self.pending.pop(data.get("reqid"), None)
                if waiter:
                    waiter.put(data)
        except (EOFError, ValueError, OSError):
            self.closed.set()
            with self.lock:
                for waiter in self.pending.values():
                    waiter.put({"error": "Viewer disconnected"})
                self.pending.clear()

    def call(self, params):
        if self.closed.is_set():
            raise RuntimeError("Viewer disconnected")
        if params.get("op") not in OPERATIONS:
            raise ValueError("Unsupported viewer operation")
        request_id = str(uuid.uuid4())
        waiter = queue.Queue(maxsize=1)
        data = {**params, "reply": self.reply_pump, "reqid": request_id}
        with self.lock:
            if len(self.pending) >= 8:
                raise RuntimeError("Too many pending viewer requests")
            self.pending[request_id] = waiter
            write_packet(self.sink, {"pump": "PrismAutomation", "data": data})
        timeout = 150 if params.get("op") == "shaders_reload" else 45
        try:
            return waiter.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError(f"Viewer did not respond within {timeout} seconds; the operation may still be running") from exc
        finally:
            with self.lock:
                self.pending.pop(request_id, None)


def serve(session_file: Path):
    connection = LeapConnection(sys.stdin.buffer, sys.stdout.buffer)
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Never log credentials or request bodies.

        def do_POST(self):
            if self.path != "/call" or self.headers.get("Origin") or not hmac.compare_digest(
                self.headers.get("Authorization", ""), "Bearer " + token
            ):
                self.send_error(403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    raise ValueError("Invalid request length")
                params = json.loads(self.rfile.read(length))
                if not isinstance(params, dict):
                    raise ValueError("Request must be an object")
                result = connection.call(params)
                status = 200
            except (ValueError, RuntimeError, TimeoutError, OSError) as exc:
                result, status = {"error": str(exc)}, 400
            payload = json.dumps(result, default=str, allow_nan=False).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    session_file.parent.mkdir(parents=True, exist_ok=True)
    info = {"port": server.server_port, "token": token, "viewer_pid": os.getppid(), "bridge_pid": os.getpid()}
    temporary = session_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(info), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(session_file)
    threading.Thread(target=connection.read_forever, daemon=True).start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    connection.closed.wait()
    server.shutdown()
    server.server_close()
    try:
        if json.loads(session_file.read_text())["token"] == token:
            session_file.unlink()
    except (OSError, ValueError, KeyError):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-file", type=Path, required=True)
    serve(parser.parse_args().session_file)
