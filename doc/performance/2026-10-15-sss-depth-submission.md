# SSS depth transmission submission — 2026-10-15

Status: implemented, Release build and single-avatar comparison complete; uncommitted. Crowded and multi-light validation remains pending.

Repeated uncapped captures reduced mean SSS CPU submission from **0.993 to 0.468 ms (53%)**, with the rigged-mask component falling from **0.711 to 0.183 ms (74%)**. This change batches adjacent compatible mesh sections and selects their individual transmission identities in the GPU fragment shader. Map resolution and update frequency are unchanged.

## Setup

- Canonical Release build: `cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2`.
- Executable: [secondlife-bin.exe](../../build-vc170-64/newview/Release/secondlife-bin.exe).
- Initial build: Prism Release 0.10.0.54542, SHA-256 `68e118f5929377cdba85978660967d48b2aceb627b580548f07f5004058ba84f`.
- Existing uncommitted TAAU changes are included and preserved.
- GPU: NVIDIA GeForce RTX 5090, driver OpenGL 4.6.0 NVIDIA 617.14.
- Scene: Kenosaki, one nearby mesh avatar in a beach exterior with foliage and buildings.
- Window 3440×1369; world output 3440×1316; TAAU rendering 2580×987. MCP photos use the native, unaccumulated photo path.
- [Original camera](../../.logs/viewer-mcp/20261015T181136Z-sss-transmission-original-5f41fc7c.camera.json): global position `(284821.75440979004, 276669.8270111084, 23.737478256225586)`, forward `(0.90031314, -0.41101453, -0.14319003)`, up `(0.13025814, -0.05946595, 0.98969519)`, vertical FOV 60°.
- SSS Combined, strength 1, transmission 0.8, depth-based thickness on, point-light depth on, local depth resolution 1024, transmission smoothing 56. PCSS, GTAO, SSGI and TAAU enabled; hair shading/physics disabled. Full settings/environment are stored in raw captures.
- Initial direct capture preserved the camera/settings. Controlled captures lock the saved camera and temporarily disable VSync; YieldTime −1 and BackgroundYieldTime 0 match their original values. The early captures retained a saved MaxFPS limit of 120. The user confirmed the driver limiter was disabled before the final comparison, and MaxFPS was temporarily changed from 120 to 0 while the viewer was stopped. Comparisons across that transition are not used to claim an improvement. MaxFPS is now included in profiling settings/metadata and uncapped benchmark overrides.
- After measurements, restored saved MaxFPS 120, VSync enabled, original camera pose and ordinary unlocked camera controls; verified the restored settings after relaunching the final Release build. The driver's limiter remains as configured by the user.

## Final uncapped comparison

Both builds used the same CPU timer scopes, saved camera, viewport, graphics options and whitelist. The only settings metadata difference is the shader-cache version. Each build warmed for 1200 frames after login, then captured 600 frames; the second capture warmed for 240 frames and captured another 600. SSS scope coverage is 600/600 in all four captures.

- Baseline SHA-256: `6479f62494f03e78f249e202374373505f1c5c56b2e5b2ec460b2aa51c14f86c`.
- Optimized SHA-256: `89085efca97c8d6291ff7ec4380950ec65c15d2d63f3cdbd322261a81d60b55f`.

| Capture | SSS submit CPU mean / p95 | Rigged masks CPU mean | Ordinary shadow submit CPU mean | SSS depth GPU mean | Frame interval mean | Raw samples |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Baseline 1 | 0.996 / 1.070 ms | 0.713 ms | 2.170 ms | 1.015 ms | 9.795 ms | [JSON](../../.logs/viewer-mcp/20261015T183302Z-profile-50eb7ba3.json) |
| Baseline 2 | 0.991 / 1.046 ms | 0.709 ms | 2.178 ms | 1.005 ms | 9.833 ms | [JSON](../../.logs/viewer-mcp/20261015T183424Z-profile-dee29d0f.json) |
| Optimized 1 | 0.471 / 0.523 ms | 0.184 ms | 1.752 ms | 0.676 ms | 9.017 ms | [JSON](../../.logs/viewer-mcp/20261015T183940Z-profile-b5007e9d.json) |
| Optimized 2 | 0.465 / 0.499 ms | 0.182 ms | 1.727 ms | 0.662 ms | 8.792 ms | [JSON](../../.logs/viewer-mcp/20261015T183953Z-profile-bd8d4385.json) |

The stable reduction is in rigged draw submission. SSS culling stayed near 0.014 ms and sorting near 0.033 ms. Ordinary shadow submission also benefits from the shared batching path. The observed whole-frame improvement is about 9%, but this is not an isolated measurement of SSS: animation, the region day cycle and background scene activity continued. GPU timestamp reductions can reflect reduced submission starvation and do not measure utilization.

Visual smoke comparison: [before](../../.logs/viewer-mcp/20261015T183424Z-sss-uncapped-before-e1ed9fa4.png), [before metadata](../../.logs/viewer-mcp/20261015T183424Z-sss-uncapped-before-e1ed9fa4.json), [after](../../.logs/viewer-mcp/20261015T184004Z-sss-batched-after-f405b600.png), [after metadata](../../.logs/viewer-mcp/20261015T184004Z-sss-batched-after-f405b600.json). No obvious seams, missing skin geometry, or broken clothing cutouts were visible. Avatar pose and sunlight changed, so these images cannot establish pixel equivalence or identical transmission brightness; exact depth/identity output is covered by the GPU fixture below.

## Initial measurements

CPU measurements are inclusive main-thread elapsed time including driver waits. GPU measurements are elapsed timestamp intervals and can include starvation; they are not GPU utilization. Do not add parent and child scopes. Live animation, environment, network and streaming are not frozen.

| Capture | Warmup / samples | SSS submission CPU mean | SSS cull CPU mean | SSS sort CPU mean | Frame interval mean | Raw artifact |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Direct, original settings | 180 / 360 | 1.008 ms | 0.015 ms | 0.036 ms | 10.401 ms | [JSON](../../.logs/viewer-mcp/20261015T181114Z-profile-410603eb.json) |
| Baseline 1, fixed camera / VSync off, MaxFPS 120 | 240 / 600 | 1.020 ms | — | — | 9.947 ms | [JSON](../../.logs/viewer-mcp/20261015T181211Z-profile-7d8661a7.json) |
| Baseline 2, fixed camera / VSync off, MaxFPS 120 | 240 / 600 | 1.021 ms | — | — | 9.783 ms | [JSON](../../.logs/viewer-mcp/20261015T181233Z-profile-5544128a.json) |

Depth rasterization, vertex skinning and thickness reconstruction already execute on the GPU. The measured CPU cost is primarily submission, not cull/sort work. Added child submission timers separate opaque, non-batched pools, legacy masks, alpha blend, fullbright masks, material masks and PBR masks before selecting an optimization.

Instrumented baseline build SHA-256: `a9a467f9017917e199f39e66da5e93693c98888b42ea9a40dd73bc04c2eb4852`. Its two captures used the same camera and settings, with 1200/600 and 240/600 warmup/sample frames after login.

| CPU scope | Baseline 1 mean | Baseline 2 mean |
| --- | ---: | ---: |
| `sss.submit` | 1.008 ms | 1.013 ms |
| `sss.submit.material_mask` | 0.733 ms | 0.736 ms |
| `sss.submit.opaque` | 0.170 ms | 0.174 ms |
| `sss.submit.pools` | 0.058 ms | 0.056 ms |
| `sss.submit.mask` | 0.022 ms | 0.023 ms |

Raw captures: [instrumented baseline 1](../../.logs/viewer-mcp/20261015T181826Z-profile-d8ac0c7d.json), [instrumented baseline 2](../../.logs/viewer-mcp/20261015T181851Z-profile-808c700d.json). The material-mask stage accounts for about 73% of SSS submission in this view.

## Change

Rigged alpha-masked depth draws merge consecutive index ranges when vertex buffer, avatar, existing palette-cache skin hash, model transform, diffuse alpha texture/bindings, texture matrix, cutoff and hair object/classification match. Distinct skin-info instances can share the same cached palette. This extends the existing static masked batching approach to three rigged legacy shadow shaders; other shaders retain their existing path.

For the rigged material-mask SSS path, up to 32 sections can share one draw even with different object identities. A small uniform table stores exclusive triangle endpoints and exact object IDs; the fragment shader binary-searches `gl_PrimitiveID` to select the original identity. Other shaders still split at identity boundaries. Single-section and ordinary-shadow draws disable the table. Missing skin palettes, zero-count draws, zero-identity SSS exits, triangle alignment, float exactness and platform range limits remain guarded. Draw-info objects are not mutated.

A temporary diagnostic observed 248 skin material-mask draws and 377,448 indices in one depth view, including 234 adjacent ranges sharing a vertex buffer. Every adjacent pair had different skin-info pointers and object identities; diffuse texture, texture matrix, cutoff and avatar matched. This explains why pointer/identity-preserving merges alone were ineffective. [Diagnostic draw snapshot](../../output/sss-depth-2026-10-15/baseline-draws.txt). The one-shot diagnostic logging was removed from the final build.

The name filter currently uses case-insensitive substrings from attachment root names, including `body`, `head`, `ear`, `Noelle` and other terms. Clothing labels containing a body name or even `wear` (containing `ear`) can qualify. The user's reported clothing matches were retained throughout this comparison; narrowing the whitelist was not the source of the performance gain. Exact per-attachment matches were not enumerated.

## Validation and limitations

- Native static/rigged masked batching tests pass with per-index state/palette recording, all three shadow shader variants, indexed/nonindexed textures, SSS phases, hair phases, missing palettes, transform/texture/identity boundaries, empty inputs and both platform-limit modes.
- Existing opaque batching and alpha-shadow submission tests pass.
- All 1,794 SSS GPU checks pass, including entry/exit capture fragments and sun/spot/point transmission.
- An additional 144 comparisons run the production masked depth shader on the GPU in GLSL 330 and 430. Batched output exactly matches separate draws for 1–32 sections, 24-bit IDs, nonzero draw offsets, clipping, alpha cutouts, front/back faces, zero-ID exits and ordinary shadows; a subsequent unbatched draw ignores the old table.
- All 12 MCP tests pass using `scripts/viewer_mcp/.venv/Scripts/python.exe`, including cap restoration after success and failure. An initial run in the general-purpose `.venv` lacked the MCP dependency; rerunning in the configured MCP environment resolved it.
- Instrumented and optimized Release builds pass. MSBuild stalled in the restricted sandbox; the prescribed build completed outside it. Native test temporary files were redirected into the workspace after the sandbox temporary directory rejected writes.
- [Before photo](../../.logs/viewer-mcp/20261015T181145Z-sss-transmission-before-dc673368.png) and [metadata](../../.logs/viewer-mcp/20261015T181145Z-sss-transmission-before-dc673368.json).

The first contiguous rigged-batching attempt did **not** improve the measured bottleneck: submission means were 1.017 and 1.023 ms, and material-mask means 0.737 and 0.742 ms. Raw captures: [attempt 1](../../.logs/viewer-mcp/20261015T182235Z-profile-e16e1e88.json), [attempt 2](../../.logs/viewer-mcp/20261015T182351Z-profile-8d8046e8.json). Build SHA-256: `4bc9addc149b4a814f80cb45be6950a51dc39b2aa0182ea2075a78c4ac0edda2`. Both captures used 600 samples, with 1200 then 240 warmup frames. The final change removes the pointer/identity barriers described above.

This scene does not establish crowded-region or multi-light performance, other vendors' GPU behavior, or unchanged appearance at every animation pose. Live timing is measured on the RTX 5090; the Darwin limits were tested in the native submission fixture, not on macOS hardware. Raw artifacts are local ignored outputs and must be preserved separately when sharing this report.
