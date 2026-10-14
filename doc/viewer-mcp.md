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

Schema version 2 also includes `cpu_ms` in every raw sample and in the summary,
with the same statistics and `active_frames` coverage as `gpu_ms`. CPU scopes
measure **inclusive main-thread wall time**, including waits, not CPU utilization.
Repeated calls (for example, multiple avatars or rendering passes) accumulate
within each frame. Worker-thread execution is excluded. Inactive captures do not
read CPU timers or accumulate samples.

CPU measurement begins after MCP request processing and ends after the main
loop's background work. It is attached to that same frame's GPU sample, including
animation before rendering and presentation/reflection work after GPU timestamps
end. `cpu_ms.frame` measures this interval; `frame_interval_ms` retains its existing
render-start-to-render-start meaning. Do not subtract the CPU and GPU timers to
infer utilization or add a parent scope to its children.

| CPU scope | Work measured |
| --- | --- |
| `scene.idle` | Main idle/update phase, including network, objects, avatars and UI. |
| `scene.network`, `scene.object_update` | Network processing and object/GLTF updates; object updates include avatar updates. |
| `avatar.idle`, `avatar.character`, `avatar.animation` | Avatar update, character update, and normal/forced/hidden motion-update branches, nested in that order. |
| `avatar.rigging_info` | Attachment rigging information updates. |
| `skinning.palette_cache`, `skinning.palette_build` | Cache-miss matrix preparation and joint palette construction; construction is nested inside cache preparation when called there. |
| `skinning.rigged_volume` | CPU rigged-volume deformation, bounds and optional octree rebuilds, including palette construction. This is not GPU vertex skinning time. |
| `render.display` | Display submission, presentation and post-present maintenance. |
| `render.geometry_update`, `render.gl_update`, `render.cull`, `render.state_sort`, `render.texture_update` | Geometry/GL updates, culling, draw sorting and texture updates across invoked views. |
| `render.present`, `render.post_present` | Buffer swap (including VSync waits) and subsequent reflection/snapshot maintenance. |
| `background.total`, `background.yield`, `background.texture_dispatch`, `background.mesh` | Main-thread background phase, its explicit foreground/background sleeps, texture worker dispatch and mesh repository update; dispatch timings do not measure worker execution. |
| `sort.view.world`, `sort.view.shadow`, `sort.view.sss`, `sort.view.hair`, `sort.view.impostor`, `sort.view.reflection`, `sort.view.hud` | Split `render.state_sort` by the active rendering pass; shadow scopes can also belong to reflection views. |
| `sort.post`, `sort.geometry_rebuild`, `sort.priority_rebuild`, `sort.mesh_notifications` | Post-sort preparation, drawable/priority geometry rebuilds and mesh completion processing; these scopes are nested. |
| `sort.render_map`, `sort.mesh_pack`, `sort.alpha_order`, `sort.buffer_upload` | Render-list assembly, deferred mesh packing, alpha-list sorting and the final buffer flush inside post-sort. |
| `geometry.volume_rebuild`, `geometry.mesh_rebuild`, `geometry.particle_rebuild` | Actual dirty geometry/mesh rebuild bodies across all callers; clean early returns are excluded. |
| `shadow.total`, `shadow.cull`, `shadow.submit` | Entire sun/projector shadow generation, its culling, and submission after state sorting (including driver waits); includes reflection-probe shadow views. `sort.view.shadow` measures preparation between culling and submission. Children are nested in the total. |
| `sss.cull`, `sss.submit`, `hair.cull`, `hair.submit` | Culling and draw submission for SSS/hair depth views. Reused exit/thickness views submit draws without another cull/sort. |

| Feature | GPU scopes / comparison |
| --- | --- |
| SSS | Depth maps, diffusion, overlays; enabled/disabled comparison also captures shared shader work. |
| PCSS | Shared sun/projector lighting and alpha passes. Paired `RenderPCSSEnabled` comparison measures incremental cost; those passes are not PCSS-only timers. |
| GTAO | Total, horizon search, denoise. |
| SSGI | Total, geometry, trace, filter, receiver resolve, temporal denoise, compose. |
| TAA | Motion (shared with SSGI) and resolve. Disabled variant selects no AA (`RenderFSAAType=0`), not FXAA/SMAA. |
| Hair mesh collision | `Hair.mesh_update` includes GPU skinning/refit and the nested `Hair.contact_coupling` scope, which builds the nearby body/hand triangle cache and solves shared pull/collision fields. Hair draw passes interpolate those fields. Compare the whole frame against basic collision. `Hair.mesh_surface` measures the optional preview. `hair_mesh` metadata reports availability, active meshes/triangles/nodes, shared contact points and cumulative topology bakes. |
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

Keep a dated Markdown measurement report in `doc/performance/` for each
investigation. Record the executable identity, scene/camera and viewport,
settings changes, warmup/sample counts, timing summaries, validation and
comparison limitations. Link the raw captures, saved cameras and screenshots so
later sessions can revisit the evidence. Update the report after rebuilds and
follow-up captures; distinguish observations from demonstrated improvements.

## Verification

```powershell
./scripts/viewer_mcp/.venv/Scripts/python.exe scripts/tests/test_viewer_mcp.py -v
./scripts/viewer_mcp/.venv/Scripts/python.exe scripts/tests/test_viewer_mcp_cpu.py
```

Tests exercise binary LEAP framing, real pipe/HTTP transport and authentication,
MCP initialization/tool schemas, alternating benchmark order, and restoration
after a simulated failure. The CPU regression requires `g++` on PATH and runs
production capture methods with a deterministic clock and fake GPU, checking
scope accumulation, frame pairing, worker exclusion, cancellation and summaries.
The opt-in live check launches and logs in with the
remembered account, verifies a direct unlocked capture without settings writes,
camera replay and GPU capture, temporarily enables
all seven features for a 14-run smoke suite, and tests cancellation/restoration:

```powershell
./scripts/viewer_mcp/.venv/Scripts/python.exe scripts/tests/viewer_mcp_live.py
```

These short captures verify the workflow; they do not establish optimization
results or guarantee every pass is visible in the current scene. This integration is a development
tool in the checkout; Python dependencies are not bundled into the installer.

### Hair rope simulation

`BoxxyHairPhysicsEnabled` enables local-avatar radial ropes with animated mesh collision. It is independent of `BoxxyHairEnabled` (enhanced shading). Hair attachment name matching is shared; lighting's self-only and camera-distance settings do not disable local physics. The old regional, ellipsoid and hair-card modes and their settings have been removed.

`BoxxyHairPhysicsRopeDensity` selects 4–64 ropes (default 16). Diagnostics report the active `guide_chains` and `guide_points`. Fitting uses a private shaped T-pose, frozen hair skinning bindings and bounded outer-head clearance. Density, attachment topology/visibility and skeleton changes refit the ropes; camera distance no longer changes local-avatar geometry LOD. Shading keeps authored normals and tangents while colour, depth, shadow and TAA passes share rope displacement.

Ropes use stiffness, shape retention, root pinning/gradient, damping, bend resistance/gradient, elasticity and optional world-down gravity. The GPU solver advances with substeps no larger than 1/120 second. Frames over 250 ms, teleports and large turns reset history. Travel limiting is optional (zero disables it); correction velocity is capped at 3 m/s. Polar fitting approximates hanging hair and does not provide hair self-collision.

`BoxxyHairPhysicsColliderNames` selects only matching rigged attachments on the local avatar (default whole words: body, head, hands, feet). Clothing compatibility terms can select unwanted surfaces. `BoxxyHairPhysicsMeshPadding` expands the skinned shell by 0–0.1 metres, including hands. `BoxxyHairPhysicsShowMesh` previews the actual shell in purple. `BoxxyHairPhysicsShowGuides` shows rest/simulated ropes: grey rest lines, yellow pinned nodes, cyan free nodes and red contacts. Both overlays require physics.

Animated contact interpolates previous/current surface positions and normals over substeps, accounting for avatar-relative origin shifts. Contact transfers outward surface velocity and friction relative to tangential surface motion. Rebuilds, pose resets and clearance changes invalidate contact history. Point/midpoint planes stay fixed through constraint iterations. Segment rays are limited to two per segment per frame, 64 nodes and 32 triangles each; incomplete queries retain point/midpoint contact.

The head-local cache has 6 cm spacing, 21×21×32 cells, and bounds (-0.60,-0.60,-1.56) to (0.60,0.60,0.30) metres. Each shell buffer stores tree nodes, skinned triangles, one grid header and one candidate pair per cell. There is no regional displacement field or coupling pass. Cache history keeps body/hand triangle identities within 5 mm nearest-surface ties. Each cell checks at most 128 tree nodes / 64 new triangles plus two history seeds; dispatches contain at most 1,024 cells. Guide dispatches contain at most 32 ropes. Capture readbacks are asynchronous and bounded; a busy GPU drops a diagnostic sample instead of waiting on the main thread.
