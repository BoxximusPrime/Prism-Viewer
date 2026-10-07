"""Testable local viewer client, shared by MCP and command-line smoke tests."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
EXE = ROOT / "build-vc170-64/newview/Release/secondlife-bin.exe"
ARTIFACTS = ROOT / ".logs/viewer-mcp"
SESSION = ARTIFACTS / "connection.json"
_build_identity = None


def build_identity():
    global _build_identity
    stamp = EXE.stat().st_mtime_ns
    if _build_identity is None or _build_identity["mtime_ns"] != stamp:
        with EXE.open("rb") as binary:
            digest = hashlib.file_digest(binary, "sha256").hexdigest()
        _build_identity = {"executable": str(EXE), "sha256": digest, "mtime_ns": stamp}
    return dict(_build_identity)

# These toggles define the tested variant precisely; feature costs are not additive.
FEATURES = {
    "SSS": {"BoxxySSSEnabled": False},
    "PCSS": {"RenderPCSSEnabled": False},
    "GTAO": {"RenderGTAOEnabled": False},
    "SSGI": {"RenderSSGIEnabled": False},
    "TAA": {"RenderFSAAType": 0},
    "water": {"RenderWaterProceduralWaves": False, "RenderWaterDisplacementEnabled": False,
              "RenderWaterLocalReflections": False, "RenderWaterSubmergedLighting": False,
              "RenderWaterCustomColors": False, "RenderWaterCausticsStrength": 0.0},
    "volumetric_fog": {"RenderVolumeFog": False, "RenderGroundFog": False},
}


def artifact_name(label, suffix):
    clean = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)[:64] or "capture"
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    return ARTIFACTS / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{clean}-{uuid.uuid4().hex[:8]}{suffix}"


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")


class ViewerClient:
    def call(self, op, **params):
        try:
            info = json.loads(SESSION.read_text(encoding="utf-8"))
            port = int(info["port"])
            if not 1 <= port <= 65535:
                raise ValueError("Invalid bridge port")
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/call",
                json.dumps({**params, "op": op}, allow_nan=False).encode(),
                {"Authorization": "Bearer " + info["token"], "Content-Type": "application/json"},
            )
            # A proxy must never receive the local bridge token.
            timeout = 155 if op == "shaders_reload" else 50
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=timeout) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                message = json.load(exc).get("error", f"Viewer bridge rejected request ({exc.code})")
            except (ValueError, AttributeError):
                message = f"Viewer bridge rejected request ({exc.code})"
            raise RuntimeError(message) from exc
        except (OSError, ValueError, KeyError) as exc:
            raise RuntimeError("Viewer bridge is unavailable. In a running viewer, choose Develop > Enable Local MCP (Debug at login); otherwise use viewer_launch.") from exc
        if result.get("error"):
            raise RuntimeError(result["error"])
        result.pop("reqid", None)
        return result

    def launch(self):
        try:
            return {"already_connected": True, **self.call("status")}
        except RuntimeError:
            pass
        if not EXE.is_file():
            raise RuntimeError(f"Release viewer not found: {EXE}")
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        # Use the same viewer-owned bridge as Develop > Enable Local MCP (Debug at login).
        # A command-line override is temporary; the menu controls persistence.
        command = [str(EXE), "--set", "MCPBridgeEnabled", "true"]
        if os.name == "nt":
            # Some MCP hosts put the server in a kill-on-close Windows job.
            # Keep the viewer independent when that job permits breakaway.
            kwargs = dict(cwd=EXE.parent, stdin=subprocess.DEVNULL,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                process = subprocess.Popen(command,
                    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kwargs)
            except PermissionError:
                process = subprocess.Popen(command,
                    creationflags=subprocess.CREATE_NO_WINDOW, **kwargs)
        else:
            process = subprocess.Popen(command, cwd=EXE.parent, start_new_session=True,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Viewer exited before connecting. If a viewer is already running, choose Develop > Enable Local MCP (Debug at login) there.")
            try:
                return {"launched": True, **self.call("status")}
            except RuntimeError:
                time.sleep(.5)
        raise TimeoutError("Viewer launched but its bridge did not connect within 60 seconds")

    def login(self, timeout=120):
        status = self.call("status")
        if status["logged_in"] and not status["disconnected"]:
            return status
        if status["state"] != "STATE_LOGIN_WAIT":
            raise RuntimeError(f"Wait for the login screen; viewer is {status['state']}")
        self.call("login")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.call("status")
            if status["logged_in"] and not status["disconnected"]:
                return status
            if status["state"] == "STATE_LOGIN_WAIT" and deadline-time.monotonic() < timeout-5:
                raise RuntimeError("Login is awaiting input. Complete any credentials, MFA, or login notice in the viewer, then retry; secrets are never read by MCP.")
            time.sleep(1)
        raise TimeoutError(f"Login did not complete: {status['state']}")

    def camera_set(self, pose):
        fields = ("position_global", "forward", "up", "vertical_fov_degrees", "region_id")
        return self.call("camera_set", **{k: v for k, v in pose.items() if k in fields})

    def screenshot(self, label="screenshot", show_ui=False, show_hud=False):
        path = artifact_name(label, ".png")
        result = self.call("snapshot", filename=str(path), show_ui=show_ui, show_hud=show_hud)
        write_json(path.with_suffix(".json"), result)
        return result

    def capture(self, frames, warmup_frames, label, stop=None):
        self.call("profile_start", frames=frames, warmup_frames=warmup_frames)
        deadline = time.monotonic() + 185
        try:
            while time.monotonic() < deadline:
                if stop and stop.is_set():
                    raise RuntimeError("Benchmark cancelled")
                result = self.call("profile_status")
                if result["state"] == "complete":
                    result = self.call("profile_status", include_samples=True)
                    result["build"] = build_identity()
                    path = artifact_name(label, ".json")
                    write_json(path, result)
                    result.pop("samples", None)
                    return {"artifact": str(path), **result}
                if result["state"] in ("failed", "cancelled", "idle"):
                    raise RuntimeError(result.get("error") or f"Capture ended: {result['state']}")
                time.sleep(.25)
            raise TimeoutError("Capture did not finish within 185 seconds")
        except BaseException:
            self.call("profile_cancel")
            raise


class Benchmark:
    def __init__(self, client):
        self.client = client
        self.stop = threading.Event()
        self.thread = None
        self.progress = {"state": "idle"}

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, features, frames=180, warmup_frames=120, repeats=2, uncapped=True):
        if self.running:
            raise RuntimeError("A benchmark is already running")
        if not features or len(features) != len(set(features)) or any(f not in FEATURES for f in features):
            raise ValueError("Select unique features from " + ", ".join(FEATURES))
        if not 10 <= frames <= 2000 or not 1 <= warmup_frames <= 2000 or not 1 <= repeats <= 5:
            raise ValueError("frames 10-2000, warmup_frames 1-2000, repeats 1-5")
        pose = self.client.call("camera_get")
        self.client.camera_set(pose)
        original = self.client.call("settings_get")["values"]
        keys = set().union(*(FEATURES[f] for f in features))
        pacing = {"RenderVSyncEnable": False, "BackgroundYieldTime": 0, "YieldTime": -1} if uncapped else {}
        keys.update(pacing)
        restore = {key: original[key] for key in keys}
        baseline = {**restore, **pacing}
        output = artifact_name("benchmark", ".json")
        self.progress = {"state": "running", "artifact": str(output), "completed_runs": 0,
                         "total_runs": len(features)*repeats*2, "current": "starting", "skipped_features": []}
        self.stop.clear()

        def run():
            report = {"schema_version": 1, "camera": pose, "baseline": baseline, "original_settings": restore,
                      "uncapped": uncapped, "runs": [], "comparisons": [],
                      "note": "Each feature is compared to the captured baseline. Order alternates each repeat. Water variant disables the explicitly listed improvements; underlying water rendering remains. Live scene motion is not frozen."}
            try:
                for feature in features:
                    variant = FEATURES[feature]
                    reason = None
                    if feature == "TAA" and original["RenderFSAAType"] != 3:
                        reason = "TAA is not the active antialiasing mode"
                    elif feature == "PCSS" and original.get("RenderShadowDetail", 0) == 0:
                        reason = "Shadows are disabled"
                    elif all(original[k] == v for k, v in variant.items()):
                        reason = "Already at the disabled variant"
                    if reason:
                        report["comparisons"].append({"feature": feature, "skipped": reason})
                        self.progress["skipped_features"].append(feature)
                        self.progress["total_runs"] -= repeats*2
                        continue
                    for repeat in range(repeats):
                        pair = {}
                        order = ("baseline", "disabled") if repeat%2 == 0 else ("disabled", "baseline")
                        for condition in order:
                            if self.stop.is_set():
                                raise RuntimeError("Benchmark cancelled")
                            self.client.call("settings_set", values={**baseline, **(variant if condition == "disabled" else {})})
                            label = f"{feature}-{repeat+1}-{condition}"
                            self.progress["current"] = label
                            result = self.client.capture(frames, warmup_frames, label, self.stop)
                            image = self.client.screenshot(label)
                            pair[condition] = result
                            report["runs"].append({"feature": feature, "repeat": repeat+1, "condition": condition,
                                                   "settings": {**baseline, **(variant if condition == "disabled" else {})},
                                                   "capture": result["artifact"], "screenshot": image["filename"],
                                                   "gpu_ms": result["gpu_ms"], "frame_interval_ms": result["frame_interval_ms"]})
                            self.progress["completed_runs"] += 1
                            write_json(output, report)
                        report["comparisons"].append({"feature": feature, "repeat": repeat+1,
                            "incremental_gpu_frame_ms": pair["baseline"]["gpu_ms"]["frame"]["median"]-pair["disabled"]["gpu_ms"]["frame"]["median"]})
                report["state"] = "complete"
            except Exception as exc:
                report["state"] = "cancelled" if self.stop.is_set() else "failed"
                report["error"] = str(exc)
            finally:
                try:
                    self.client.call("profile_cancel")
                    self.client.call("settings_set", values=restore)
                    self.client.camera_set(pose)
                    report["settings_restored"] = True
                except Exception as exc:
                    report["settings_restored"] = False
                    report["restore_error"] = str(exc)
                    report["state"] = "failed"
                write_json(output, report)
                self.progress.update(state=report["state"], current="finished", error=report.get("error"),
                                     comparisons=report["comparisons"], settings_restored=report["settings_restored"])

        self.thread = threading.Thread(target=run, name="viewer-benchmark", daemon=True)
        self.thread.start()
        return dict(self.progress)
