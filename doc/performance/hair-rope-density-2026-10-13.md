# Hair rope density and bend gradient — 2026-10-13

Status: implemented and checked, uncommitted. GPU regressions, Release build and
live control/topology smoke checks pass; collision quality still needs tuning.

## Controls

Graphics > Hair, with Guide chains enabled:

- **Rope density:** integer count 4–64, default 16. Changes refit and reset the
  ropes. Increasing density narrows angular fitting regions as well as adding
  simulated ropes. Each rope still has nine points. Rendering, previous-frame
  interpolation, debug drawing and diagnostics use the fitted count.
- **Bend gradient (m):** 0–2 m, default 0 for uniform resistance. With a positive
  value, existing Guide bend resistance tapers smoothly from its upper value to
  5% over this distance beyond the pinned radius. Larger distances retain a
  firmer upper region. Bend resistance must be above zero. The gradient uses
  fitted rest positions, independent of root mobility and Shape retention.

Both controls persist, reset through the existing graphics reset action, and
are available through the local MCP graphics allowlist. Defaults preserve the
previous count and uniform bending behaviour.

The first rest root's unused W component stores the rope count in each guide
buffer. This lets current/previous shader reads share the correct buffer's
topology without extra render-pass uniforms. Compute dispatch rounds up to
16-thread groups and rejects invocations beyond the actual count. Frozen skin
palettes remain appended after the variable-sized rope data. Refitting clears
the previous guide frames so old offsets are not used with new topology.

## Correctness checks

- [Density and gradient GPU checks](../../.logs/hair-density-gpu.log): production
  solver at 4, 7, 16, 31 and 64 ropes; every rope moves under load, roots stay
  fixed, and canary data after the ropes stays intact. Real render interpolation
  matches the expected guide blend, including the circular seam and the last
  rope. TAA reads previous buffers with counts different from the current buffer.
- Equal initial zigzags with uniform bend resistance produced upper/lower
  curvature scores 1.749 / 0.735. A 0.6 m gradient gave 1.294 / 3.945: lower
  bends remained looser while upper constraints stayed firm. Extending the
  gradient to 1.2 m reduced lower curvature to 1.370. Pins stayed fixed. Scores
  are sums of squared differences between adjacent unit edge directions.
- [Guide regressions](../../.logs/hair-density-guides.log): pins, inertia,
  gravity, length constraints, 30/60/7 Hz, both collider types, moving contact,
  interpolation, seams and fallback pass at the default count. Existing test
  fixtures now carry their topology metadata.
- [Binding/recovery/elasticity](../../.logs/hair-density-binding.log): no
  static recovery launch or torso-induced slip; moving fold and load/release
  checks retain the preceding build's results.
- [Settings](../../.logs/hair-density-settings.log): defaults, persistence,
  slider bounds, integer density, guide-only enablement, reset and automation
  registration pass, along with the existing spring tests.
- [Contact/debug regression](../../.logs/hair-density-response.log) and
  [stability/lighting regression](../../.logs/hair-density-stability.log) results
  both pass, including debug positions/colours and the seven skinned lighting paths.

## Build and live checks

Release build passed: [build](../../.logs/hair-density-build.log).
Executable `E:\BoxxyViewer\build-vc170-64\newview\Release\secondlife-bin.exe`,
SHA-256 `caf23a0c638907e3daf631a2bb60c1762588beaa2fe9973bbce115844e1a86db`.
Runtime shader/settings/preferences hashes match the source. All **267/267**
programs loaded; the [startup log](../../.logs/hair-density-shader-startup.log)
passes `test_shader_progress_log.py`. Shader compilation exceeded launch's
60-second bridge wait; a subsequent status check connected and remembered login
succeeded, without starting another viewer.

No bridge was available before the build, so a pre-build live camera/settings
snapshot could not be obtained. The post-launch [camera](../../.logs/viewer-mcp/20261013T085909Z-hair-density-before-live-73f5451a.camera.json)
and graphics values were saved before temporary controls. No camera was changed
or locked by automation. The user moved it during testing; those changes were
preserved.

Scene: Brianconnais, viewport 3440×1369, render 3440×1316, RTX 5090 / NVIDIA 617.14.
Existing user hair settings: mesh collision/guides/gravity on; gravity 1.25,
bend resistance 2.7, stiffness 2.5, retention 0.6, elasticity 0.6, damping 16,
friction 0.05, smoothing 0.08, root radius 0.06 m, root gradient 0.28 m,
travel limit 2. Temporarily enabled the overlay and set the bend gradient to
0.6 m, then selected densities 4, 31 and 64. The shell contained 543,501 triangles
in 310 meshes with all 14,112 contact samples active.

| Density | Warmup / measured frames | Live diagnostic ropes / points | Median GPU frame | Raw capture |
| --- | --- | --- | --- | --- |
| 4 | 120 / 30 | 4 / 36 | 12.701 ms | [JSON](../../.logs/viewer-mcp/20261013T085950Z-profile-ddd60eb5.json) |
| 31 | 60 / 30 | 31 / 279 | 13.768 ms | [JSON](../../.logs/viewer-mcp/20261013T090026Z-profile-fab40645.json) |
| 64 | 60 / 30 | 64 / 576 | 17.556 ms | [JSON](../../.logs/viewer-mcp/20261013T090102Z-profile-1a3e252f.json) |

These are short integration samples, not comparable performance runs: camera
positions differ, the 31-rope sample contains camera movement, and scene/animation
work varies. Scopes are inclusive and must not be added. GPU test programs were
finished before captures.

[Four-rope screenshot](../../.logs/viewer-mcp/20261013T090004Z-hair-density-4-4d5ecb02.png)
and [64-rope screenshot](../../.logs/viewer-mcp/20261013T090118Z-hair-density-64-aec4c76f.png)
confirm the overlay density changes while hair remains rendered. The 64-rope view
also shows some outward/contact-deflected chains; it does not establish improved
collision stability at maximum density. No hand/seated quality comparison is claimed.

Restored density 16, gradient 0 and the overlay off. A final settings read matched
every saved graphics value. Viewer remains logged in with no active capture or
camera lock.

## Limits

More ropes increase simulation work and improve angular sampling; they do not
increase the nine-point resolution along each rope or add hair self-collision.
Guides remain an approximation fitted to visible hair geometry. Density changes
intentionally refit in the current pose and reset motion, so adjusting the slider
can visibly reposition hair. The bend gradient scales existing resistance;
with resistance zero there is no bending force to taper. Broader hairstyle and
animation validation remains necessary; short live samples are integration
smoke checks, not performance comparisons.
