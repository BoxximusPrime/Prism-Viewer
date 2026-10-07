"""Prism rendering MCP. Run using this directory's virtual environment."""
from __future__ import annotations

import json
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Image
from mcp.types import ToolAnnotations

from viewer_client import ViewerClient, Benchmark, FEATURES, artifact_name, write_json, build_identity

client = ViewerClient()
benchmark = Benchmark(client)


@asynccontextmanager
async def lifespan(_server):
    try:
        yield {}
    finally:
        if benchmark.running:
            benchmark.stop.set()
            await asyncio.to_thread(benchmark.thread.join, 55)


mcp = FastMCP("Prism Viewer", lifespan=lifespan, instructions=(
    "Use viewer_launch then viewer_login with the viewer's remembered account. Never request or read passwords. "
    "profile_start captures the current view without changing camera or graphics settings. "
    "Camera locking is optional for standalone captures; paired benchmarks lock a pose and change temporary graphics settings. "
    "GPU scopes are inclusive; do not add overlapping scopes. PCSS requires paired on/off captures of shared lighting. "
    "Poll benchmark_status while a suite runs. Cancel before other mutations. Save artifacts and compare image quality as well as timing."
))
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)


def require_idle():
    if benchmark.running:
        raise RuntimeError("Cancel or finish the running benchmark before changing the viewer")


@mcp.tool(annotations=WRITE)
def viewer_launch() -> dict:
    """Launch the canonical Release viewer with Local MCP enabled, or attach if connected. For an already running viewer, use Develop > Enable Local MCP (Debug at login)."""
    require_idle()
    return client.launch()


@mcp.tool(annotations=READ)
def viewer_status() -> dict:
    """Get connection, startup/login and capture status without exposing credentials."""
    return client.call("status")


@mcp.tool(annotations=WRITE)
def viewer_login() -> dict:
    """Log in using the account/password already selected and remembered by the viewer. Wait up to 120 seconds. MFA or missing credentials require user interaction in the viewer."""
    require_idle()
    return client.login()


@mcp.tool(annotations=READ)
def camera_get() -> dict:
    """Read reproducible global position, forward/up vectors, vertical FOV, and region."""
    return client.call("camera_get")


@mcp.tool(annotations=WRITE)
def camera_set(position_global: list[float], forward: list[float], up: list[float], vertical_fov_degrees: float = 60, region_id: str | None = None) -> dict:
    """Lock the camera every frame at a global XYZ position and orientation. Forward/up are 3-vectors; up permits roll. Position must be near the agent in a loaded region. Region ID optionally guards replay."""
    require_idle()
    pose = dict(position_global=position_global, forward=forward, up=up, vertical_fov_degrees=vertical_fov_degrees)
    if region_id:
        pose["region_id"] = region_id
    return client.camera_set(pose)


@mcp.tool(annotations=WRITE)
def camera_save(label: str = "camera") -> dict:
    """Save the current camera pose and viewport dimensions to a local JSON artifact."""
    pose = client.call("camera_get")
    path = artifact_name(label, ".camera.json")
    write_json(path, pose)
    return {"path": str(path), "pose": pose}


@mcp.tool(annotations=WRITE)
def camera_restore(path: str) -> dict:
    """Restore and lock a previously saved camera JSON pose in its original region."""
    require_idle()
    pose = json.loads(Path(path).read_text(encoding="utf-8"))
    current = client.call("camera_get")
    if pose.get("region_id") != current.get("region_id"):
        raise RuntimeError("Saved camera belongs to a different region")
    if "width" in pose and "height" in pose and (pose["width"], pose["height"]) != (current["width"], current["height"]):
        raise RuntimeError(f"Saved pose requires viewport {pose['width']}x{pose['height']}; current viewport is {current['width']}x{current['height']}. Match the viewer size before replay.")
    return client.camera_set(pose)


@mcp.tool(annotations=WRITE)
def camera_release() -> dict:
    """Release the camera lock and return to ordinary viewer camera controls."""
    require_idle()
    return client.call("camera_release")


@mcp.tool(annotations=READ)
def graphics_settings() -> dict:
    """Read rendering settings, supported write ranges, and feature comparison toggles."""
    result = client.call("settings_get")
    result["values"] = {key: result["values"][key] for key in result["writable"]}
    return {**result, "feature_disabled_variants": FEATURES}


@mcp.tool(annotations=WRITE)
def graphics_set(values: dict) -> dict:
    """Set allowlisted scalar graphics controls temporarily. Changes do not persist on exit. See graphics_settings for names and limits."""
    require_idle()
    return client.call("settings_set", values=values)


@mcp.tool(annotations=WRITE)
def shaders_reload() -> dict:
    """Clear the viewer shader cache and reload GLSL without restarting. Requires login and no active capture/benchmark. Reloads files in viewer_status.shader_directory; copy edited checkout shaders there first if different. Returns completion, duration and source version. Rendering pauses during compilation; allow warmup before profiling."""
    require_idle()
    return client.call("shaders_reload")


@mcp.tool(annotations=WRITE)
def viewer_restore() -> dict:
    """Restore settings changed through automation to their original values and release the camera."""
    require_idle()
    return client.call("restore")


@mcp.tool(annotations=WRITE)
def viewer_screenshot(label: str = "screenshot", show_ui: bool = False, show_hud: bool = False) -> Image:
    """Capture a PNG and metadata, returning the image for visual comparison. Not allowed during a timing capture."""
    require_idle()
    result = client.screenshot(label, show_ui, show_hud)
    return Image(path=result["filename"])


@mcp.tool(annotations=WRITE)
def profile_start(frames: int = 180, warmup_frames: int = 120) -> dict:
    """Capture the current view without changing camera or graphics settings (10-2000 measured frames, 1-2000 warmup). Camera locking is optional. Poll profile_result."""
    require_idle()
    return client.call("profile_start", frames=frames, warmup_frames=warmup_frames)


@mcp.tool(annotations=READ)
def profile_result(save: bool = True) -> dict:
    """Read capture progress or final per-stage GPU/CPU-frame statistics. Save raw samples and full metadata on completion."""
    result = client.call("profile_status", include_samples=save)
    if save and result["state"] == "complete":
        result["build"] = build_identity()
        path = artifact_name("profile", ".json")
        write_json(path, result)
        result["artifact"] = str(path)
        result.pop("samples", None)
    # Full settings/environment are preserved in the artifact; keep tool replies
    # small enough to compare timings without flooding the model's context.
    for key in ("metadata", "end_metadata"):
        if key in result:
            result[key] = {k: v for k, v in result[key].items() if k not in ("settings", "sky", "water")}
    return result


@mcp.tool(annotations=WRITE)
def profile_cancel() -> dict:
    """Cancel a standalone capture. Use benchmark_cancel for a suite."""
    require_idle()
    return client.call("profile_cancel")


@mcp.tool(annotations=WRITE)
def benchmark_start(features: list[str] | None = None, frames: int = 180, warmup_frames: int = 120, repeats: int = 2, uncapped: bool = True) -> dict:
    """Run paired baseline/disabled captures for SSS, PCSS, GTAO, SSGI, TAA, water, volumetric_fog. Alternates order and saves images/raw timings. By default temporarily disables VSync and background sleeps. Restores settings on completion/failure. Returns immediately; poll benchmark_status."""
    return benchmark.start(features or list(FEATURES), frames, warmup_frames, repeats, uncapped)


@mcp.tool(annotations=READ)
def benchmark_status() -> dict:
    """Read suite progress, final comparisons, restoration status, and the report path."""
    return dict(benchmark.progress)


@mcp.tool(annotations=WRITE)
def benchmark_cancel() -> dict:
    """Request cancellation and setting restoration; poll benchmark_status until finished."""
    benchmark.stop.set()
    return {"cancellation_requested": True, **benchmark.progress}


@mcp.tool(annotations=WRITE)
def viewer_quit() -> dict:
    """Gracefully close the connected viewer after restoring temporary settings."""
    require_idle()
    client.call("profile_cancel")
    client.call("restore")
    return client.call("quit")


if __name__ == "__main__":
    mcp.run(transport="stdio")
