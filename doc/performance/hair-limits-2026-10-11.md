# Hair limits and SSS distance fade - 2026-10-11

Status: implemented, uncommitted; Release build, regression tests, remembered login and live range/self-only smoke checks passed. No FPS improvement is claimed.

## Changes

- Hair maximum camera distance defaults to **10 yards (9.144 m)**, with a 1-128 yard control. Attachments use their owning avatar's position; standalone matched objects use their own rendered position.
- **For me only** defaults on. It restricts hair lighting to the user's avatar attachments. Turning it off permits other avatars and matching world objects within range.
- Shared eligibility gates hair surface shading, focused depth subject selection and depth generation. Hair-specific name requests obey it too; independent SSS metadata requests retain their own eligibility. Depth generation rechecks the previous frame's focus so stale selection cannot keep rendering out-of-range/other-avatar maps.
- Removed the Strand direction section, its five setting definitions, defaults/MCP ranges, texture-flow analysis and eight extra texture samples, manual-angle uniforms, confidence/direction previews and automatic-axis lobe branch. Hair uses texture V through the existing mesh frame; generated normal detail and strand variation remain. Non-hair surfaces return before hair surface calculations, and per-draw hair settings bind only for eligible hair. The generic preferences loader retains some old saved direction values in raw metadata; no remaining rendering/UI code consumes them.
- Ordinary SSS lighting already faded over the final 20% of its maximum distance. Focused transmission depth now also fades over the final 20% of its own range and skips capture outside it, instead of relying only on time-based subject switching. Its existing 32 m capture cap remains. No shader sample budget was increased.

## Build and checks

Command: `cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2` (passed).
Executable: `E:\BoxxyViewer\build-vc170-64\newview\Release\secondlife-bin.exe`.
SHA-256: `9eb5009a74de02c7e378115c3b199b19abbba30eb14b47f34eaf0bd1ea1bb05a`.

- Native production-code hair selection checks passed: name matching, self versus other avatars, standalone objects, HUD/dead/null exclusions, shared attachment/avatar distance, yard conversion and live setting changes.
- Native SSS selection checks passed: monotonic range fade, endpoints/midpoint, distance limits, projector selection and frame-rate-independent subject transitions.
- 1,088 hair GPU/config checks, 121 hair-density GPU checks, 70 PBR specular-AA GPU checks and 1,794 SSS GPU checks passed on RTX 5090.
- Hair panel XML/control bounds and overlap checks passed. Settings/UI and all 14 changed shader files stage byte-for-byte.
- 12 MCP regression tests passed outside the sandbox. The sandboxed transport run was interrupted after loopback restrictions prevented completion; the unrestricted rerun passed. Native tests used the workspace temp directory after the sandbox temp directory denied writes.
- Viewer shader startup and remembered login succeeded. Final screenshot shows normal scene rendering without obvious missing geometry. Broader hairstyle appearance and a moving-camera SSS boundary comparison were not performed.

## Live captures

Scene: Mystic Harbor, crowded outdoor area. Viewport 3440 x 1369; render size 3440 x 1316; NVIDIA GEFORCE RTX 5090/PCIE/SSE2, driver 4.6.0 NVIDIA 617.14. Shadows, VSync and SSGI remain off; hair and SSS remain enabled. Other settings are preserved in each raw artifact.

The initial login camera was left untouched and unlocked. Its orientation remained constant; recorded positional settling/drift across these captures was 0.001221 m. This login pose differs from the earlier profiling session. The initial capture changed no camera or settings; the next two captures temporarily changed only the two new hair controls. `viewer_restore` restored all allowlisted settings, including self-only=true and range=10. The final capture confirms the original post-login settings are active again.

| Capture | Self only | Yards | Warmup/measured | Hair depth frames | Hair submit median, ms | Frame interval median, ms | Artifact |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| New defaults | True | 10 | 600/180 | 0 | 0.000 | 38.671 | [raw](../../.logs/viewer-mcp/20261011T222419Z-profile-c182bb27.json) |
| Nearby avatars allowed | False | 10 | 120/60 | 60 | 4.466 | 43.384 | [raw](../../.logs/viewer-mcp/20261011T222448Z-profile-b5d2fd7d.json) |
| Short range | False | 1 | 120/60 | 0 | 0.000 | 37.523 | [raw](../../.logs/viewer-mcp/20261011T222515Z-profile-9cee7271.json) |
| Defaults restored | True | 10 | 120/60 | 0 | 0.000 | 39.716 | [raw](../../.logs/viewer-mcp/20261011T222628Z-profile-9c14727c.json) |

At the default self-only setting there was no eligible self hair depth focus in this captured view, so no hair depth scope ran. Allowing nearby avatars enabled hair depth in all 60 measured frames. Reducing range to one yard removed CPU hair preparation/submission and GPU hair-depth scopes; restoring self-only also left them absent. This verifies the work is skipped, not just visually hidden. Positive self-attachment eligibility is covered by the native production-function test; this scene did not provide a positive self-only depth capture.

These are integration/smoke measurements, not warmed repeated optimization comparisons. Live avatar motion, streaming and scene changes remain active; do not interpret FPS differences as a measured gain from this patch. CPU scopes include driver waits; GPU intervals are inclusive elapsed times. Do not add parent/child intervals or infer utilization from CPU/GPU subtraction.

- [Camera before rebuild](../../.logs/viewer-mcp/20261011T221913Z-hair-range-before-rebuild-ac8d57a6.camera.json)
- [Initial login camera](../../.logs/viewer-mcp/20261011T222332Z-hair-limits-after-login-dbcf6968.camera.json)
- [Final screenshot](../../.logs/viewer-mcp/20261011T222521Z-hair-limits-restored-8b2c90a8.png)
- [Final screenshot metadata](../../.logs/viewer-mcp/20261011T222521Z-hair-limits-restored-8b2c90a8.json)

Viewer remains running and logged in, with temporary settings restored and camera unlocked.
