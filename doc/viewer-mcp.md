# Local viewer MCP and rendering captures

This developer integration connects Codex to the **Release** viewer in this
checkout. It is opt-in and off by default. **Develop > Enable Local MCP**, at
the bottom of the developer menu, starts the bridge in an already running viewer.
At login it is at the bottom of the hidden **Debug** menu (Ctrl+Alt+D).
The checkbox remembers your choice, so later ordinary `secondlife-bin.exe`
launches start it automatically. Uncheck it to stop the bridge, cancel an active
capture, restore automation settings, and release any automation camera lock.
The viewer launches `scripts/viewer_mcp/leap_bridge.py` through existing LEAP
pipes. The helper accepts authenticated
requests on a random loopback port and forwards a fixed set of operations to
`PrismAutomation` on the viewer main thread. The MCP server uses the official
[Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk).

## Setup

From the repository root, run:

```powershell
./scripts/viewer_mcp/setup.ps1
cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2
```

Setup creates a private Python 3.12 virtual environment and a project-scoped
`.codex/config.toml` entry named `prism-viewer`. The entry has a 180-second tool
timeout to accommodate login and shader compilation. Reconnect MCP servers or start a new Codex session
after setup. No OpenAI API key is needed. The viewer is always launched from
`build-vc170-64/newview/Release/secondlife-bin.exe`.

For a viewer that is already running, choose **Develop > Enable Local MCP** (or **Debug** at login);
no restart or special shortcut is needed. `viewer_launch` starts the Release
viewer with a temporary MCP-enabled override when the viewer is closed.
A connected instance is reused. Reconnects attach to its existing bridge while the viewer remains
running. Some Windows MCP hosts terminate child applications when the MCP server
stops; use `viewer_launch` and `viewer_login` again in that case. The bridge exits
with the viewer.
The session token lives in ignored `.logs/viewer-mcp/connection.json`; do not
publish that file. Requests from browser origins are rejected. The helper does
not expose arbitrary LEAP dispatch, shell commands, or login secrets.

## Normal workflow

1. `viewer_launch`, then poll `viewer_status` until `STATE_LOGIN_WAIT`.
2. `viewer_login` uses the selected remembered account. Missing credentials,
   MFA, terms, or login errors require interaction in the viewer; the bridge
   never reads or stores the password.
3. For a direct capture, go straight to `profile_start`, then poll
   `profile_result`. Neither call changes the camera, graphics settings, VSync,
   or background throttling. A camera lock is optional; start/end camera and
   graphics metadata record the captured setup. Moving the camera can change
   the measured workload, so use a fixed pose for controlled comparisons.
4. For repeatable camera comparisons, `camera_get` records global XYZ position, forward and up vectors,
   vertical field of view, region, and viewport dimensions. `camera_save` saves
   this as JSON. `camera_set` locks a pose every frame after camera smoothing.
   `camera_restore` verifies the region and viewport dimensions before locking
   the saved pose. Match the saved viewport size in the viewer before replay;
   runtime native resizing is intentionally not exposed by this bridge.
5. Use `graphics_settings` to inspect available settings and write ranges;
   `graphics_set` changes only allowlisted numeric/boolean rendering controls.
6. `profile_start` starts a bounded asynchronous capture; `profile_result`
   reports progress and saves raw samples plus metadata on completion.
7. `benchmark_start` locks the current pose and runs the feature suite in a background worker. Poll
   `benchmark_status` for progress. `benchmark_cancel` cancels and restores the
   suite's initial settings. A graceful MCP shutdown also cancels the suite.
8. `viewer_screenshot` returns an image and saves a matching metadata file.
   `viewer_restore` restores all automation settings and releases the camera.
   `viewer_quit` restores and requests a normal viewer shutdown.

Camera orientation uses normalized forward/up vectors, allowing roll without
Euler-angle conventions. Global coordinates are in metres. The camera must be
within 4096 metres of the agent and in loaded scenery. Camera control does not
teleport the avatar. Leaving the region releases the lock and fails an active
capture. Unlock with `camera_release` for ordinary camera interaction.

Graphics overrides use unsaved control values, so a crash or forced process
exit does not persist experimental settings. A suite restores its initial
values after success, cancellation, or failure while the bridge remains
reachable. Abruptly killing only the MCP process can leave temporary overrides
and the camera lock active until `viewer_restore` or viewer exit.

## Shader editing without restarting

`viewer_status` reports the actual `shader_directory` used by the running viewer.
Edit the GLSL in `indra/newview/app_settings/shaders`; if the reported directory
differs, copy the changed files into the same relative paths there (and remove
runtime copies of any deleted shader files). Release builds normally use a copy
under `build-vc170-64/newview/Release/app_settings/shaders`. No C++ rebuild is
needed for shader-only edits.

Call `shaders_reload` after saving/copying. It uses the viewer's existing full
reload path, clears its binary shader cache, rereads the GLSL, and recreates
render buffers. The reply reports `reloaded`, `elapsed_seconds`, `shader_directory`
and `source_version` (the shader cache hash). It preserves the camera and graphics
options. Rendering pauses during compilation. Warm up again before capturing and
check a screenshot before comparing performance.

Reload requires a connected, logged-in viewer and is rejected during a capture
or benchmark. It allows 150 seconds for compilation; a timeout does not cancel
compilation, so check status/logs before retrying. Compiler errors use the existing
viewer log and failure behavior; this command does not provide rollback to the
previous shaders, and failures in required shaders can terminate the viewer.
Reconnect the MCP server after updating the Python tools to discover the command.

## Capture semantics

Captures warm up for a configurable number of rendered frames, then record
10–2000 frames. Results contain raw per-frame samples, mean, median, p95, p99,
minimum, maximum, stage coverage, viewport/render resolution, camera, graphics
settings, GPU/driver identity, viewer version, executable SHA-256, and environment sky/water data.
The default warmup is 120 frames and capture is 180 frames.

GPU timestamp pairs are allocated before warmup, read only when available, and
bounded to 4096 query objects. They use `GL_TIMESTAMP`, so nested scopes do not
collide with the viewer's existing `GL_TIME_ELAPSED` profiler. Disabled capture
scopes issue no GL commands. Overflow, timeout, changed settings, window resize,
disconnect, or minimization fails the capture rather than returning a partial
success. Captures accept either a free camera or an explicitly locked pose.

`gpu_ms.frame` ends **before buffer presentation** and excludes VSync wait and
post-present reflection maintenance. GPU intervals are elapsed execution
intervals, not hardware utilization counters. `render_submit_ms` measures CPU
wall time submitting the main view. `frame_interval_ms` measures time between
frame starts (the interval ending at each sample's start), including idle,
presentation, and other viewer work. These are
different measurements and must not be substituted for each other.

Scopes are **inclusive**. Do not sum a feature total and its child stages, or
add all feature costs together. A stage absent from every frame is omitted;
`active_frames` reports coverage and absent frames contribute zero to a stage's
aggregate. No coverage means the scene did not exercise that path.

| Feature | GPU scopes / comparison |
| --- | --- |
| SSS | Depth maps, diffusion, overlays; enabled/disabled comparison also captures shared shader work. |
| PCSS | Shared sun/projector lighting and alpha passes. Paired `RenderPCSSEnabled` comparison measures incremental cost; those passes are not PCSS-only timers. |
| GTAO | Total, horizon search, denoise. |
| SSGI | Total, geometry, trace, filter, receiver resolve, temporal denoise, compose. |
| TAA | Motion (shared with SSGI) and resolve. Disabled variant selects no AA (`RenderFSAAType=0`), not FXAA/SMAA. |
| Water | Wave-field generation and surface rendering. The comparison disables the listed wave, displacement, local-reflection, submerged-lighting, custom-color and caustic controls; it is not a stock-viewer water comparison. |
| Volumetric fog | Main fog pass. The disabled variant turns off both tagged-volume fog and Ground Fog. Alpha-integrated fog also affects shared alpha passes; use the on/off comparison for total incremental cost. |

The suite captures a baseline and a disabled variant for each selected feature,
alternating order on successive repeats. It records the exact changed controls,
screenshots, capture paths, and paired GPU-frame median differences. An already
disabled feature is skipped; TAA is skipped when another AA mode is selected.
Suites temporarily disable VSync and foreground/background yielding by default
(`uncapped=false` preserves pacing), then restore those settings too.
A negative difference is preserved as measured,
not presented as a guaranteed improvement.

For useful optimization comparisons, choose representative scenes: skin closeups
for SSS, varied lights and casters for PCSS, geometry and bounce lighting for AO/GI,
water in view for water tests, and fog volumes for fog tests. Keep resolution,
lighting, camera, and unrelated graphics settings fixed; allow streaming to settle.
Live avatars, day cycles, particles, animated water, texture loading, and network
events are not frozen by this bridge. Inspect the saved images/environment and
repeat captures before attributing a small difference to code. Instrumentation
itself has overhead; compare runs using the same instrumentation.

## Verification

```powershell
./scripts/viewer_mcp/.venv/Scripts/python.exe scripts/tests/test_viewer_mcp.py -v
```

Tests exercise binary LEAP framing, real pipe/HTTP transport and authentication,
MCP initialization/tool schemas, alternating benchmark order, and restoration
after a simulated failure. The opt-in live check launches and logs in with the
remembered account, verifies a direct unlocked capture without settings writes,
camera replay and GPU capture, temporarily enables
all seven features for a 14-run smoke suite, and tests cancellation/restoration:

```powershell
./scripts/viewer_mcp/.venv/Scripts/python.exe scripts/tests/viewer_mcp_live.py
```

These short captures verify the workflow; they do not establish optimization
results or guarantee every pass is visible in the current scene. This integration is a development
tool in the checkout; Python dependencies are not bundled into the installer.
