# Hair contact flashing, pinned-root correction and rope resolution

Date: 2026-10-15 America/Denver. Status: implemented, uncommitted. Release build
and automated regressions pass; some live mid-rope jumping remains.

## What the flashing means

The guide overlay reads the velocity buffer's W component. The solver writes
one when `contact_weight > 1e-7` in its final substep. Red/orange therefore means
a positional correction occurred, not that a persistent collision manifold
classified the point as touching. Earlier substep contacts can disappear from
the displayed flag. Even tiny corrections can flicker, but the live capture
also confirms substantial real jumps.

The first two [contact fixes](hair-contact-fix-2026-10-14.md) remain in place.
This investigation found another discontinuity: the midpoint plane was disabled
entirely while a pinned root lay inside it. Crossing to the outside enabled its
full correction. With only one free endpoint, a midpoint correction moves that
endpoint twice as far.

A temporary GPU diagnostic counted point, midpoint and ray corrections without
changing the physics. Its largest event moved chain 0, node 1 by 24.54 mm. The
midpoint correction contributed 26.87 mm across iterations; point corrections
contributed 0.027 mm and rays zero. The root was only 0.054 mm outside the winning
plane. A second 23.10 mm event farther down the rope also came from midpoint
correction. This attributes those events to midpoint constraints, but does not
prove they share the same root gate.

## Reproduction and correction

The actual nine-node GPU solver, a stationary finite triangle, zero gravity,
zero friction and zero starting velocity reproduce the pinned-root gate:

| Input | Original gate | Continuous pinned allowance |
| --- | ---: | ---: |
| 2 micrometre root movement across the midpoint plane | 24.258 mm difference in solved rope | 0.001997 mm difference |

The fix subtracts the pinned endpoint's weighted penetration from the segment
constraint instead of dropping that constraint. The free portion stays
constrained on both sides of the threshold; the root remains fixed. The same
continuous allowance replaces the corresponding ray-projection early return.
It does not add restitution, friction, damping or a persistent contact latch.

The regression also checks free-endpoint clearance and that static penetration
recovery adds no velocity. [Original reproduction](../../.logs/hair-midpoint-gate-probe.log),
[passing regression](../../.logs/hair-root-contact-contact_continuity.log),
[production test](../../scripts/tests/test_hair_contact_continuity_gpu.py).
The original local diagnostic asserts the old defect and is expected to fail
after the fix; use the production test to validate current code.

## Live captures and limits

All three captures used 240 warmup and 1,500 measured frames, 3440×1369, the
current unlocked but stationary camera in Brianconnais, and an animated avatar.
Camera and graphics settings were not changed. The scene included a raised hand,
14 nine-node ropes, 296 collider meshes and 65,535 BVH nodes. Build at capture
time was Prism Release 0.10.0.54542, executable SHA-256
`2197d6daf6f5d3134a64277a3a900cb3e2825ebc2e7503878b176ca866df9db3`.
The root fix and diagnostic variants were loaded through MCP shader reloads.

Physics settings: friction 0, damping 16.5, stiffness 1, gravity 0.6,
retention/bend/elasticity 0, travel limit 0, root radius 0.08 m, root gradient
0.27 m, expansion 0.015 m and smoothing 0. Exact settings:
[settings snapshot](../../.logs/hair-contact-flashing-settings.json).
Each raw capture includes camera position/orientation, driver/GPU and build metadata.

The trace includes warmup rows; the statistics below exclude its first 240 rows
and use the maximum node displacement in each of the 1,500 measured frames.

| Capture | Median step | p95 | p99 | Maximum |
| --- | ---: | ---: | ---: | ---: |
| [Initial current view](../../.logs/viewer-mcp/20261015T102200Z-profile-32606715.json) | 2.209 mm | 5.881 mm | 22.889 mm | 56.888 mm |
| [Diagnostic attribution](../../.logs/viewer-mcp/20261015T102625Z-profile-b62509b6.json) | 1.422 mm | 2.529 mm | 3.200 mm | 24.540 mm |
| [Pinned-root correction](../../.logs/viewer-mcp/20261015T103642Z-profile-94f73644.json) | 1.345 mm | 3.370 mm | 5.597 mm | 29.696 mm |

No fits, resets or dropped readbacks occurred within any capture. The animation
was not replayed at matching phases, captures were not repeated, and diagnostic
instrumentation changes GPU workload. These numbers do **not** establish a
percentage improvement or a performance comparison. They show that the root
fix is live and that occasional large mid-rope events persist. The isolated
GPU reproduction establishes the corrected threshold independently.

[Summary with camera/build metadata](../../.logs/hair-contact-flashing-summary.json),
[visually inspected scene/rope overlay](../../.logs/viewer-mcp/20261015T102211Z-hair-contact-flashing-baseline-0df7be6a.png).
The diagnostic shader was restored and the production root correction loaded
before the last capture. No temporary graphics settings or camera locks remain.

## Vertex-count setting

Graphics > Hair > Physics now has **Vertices per rope**, range 9–32, default 9.
Rope density continues to control the number of ropes around the head.
Changing vertex count refits the neutral shape and clears simulation history.
Each buffer carries its own chain and vertex counts, including previous buffers
used by motion vectors. Fitting, debug lines/points and asynchronous capture
offsets use the selected topology. The setting persists and participates in
the existing preferences Default/Cancel handling and MCP scalar allowlist.

The [resolution GPU test](../../scripts/tests/test_hair_resolution_gpu.py) checks
64 ropes at 9, 17 and 32 vertices, including 30-substep frames, plane clearance,
pins, finite values, capped velocity, guarded simulation/diagnostic buffers,
independent previous/current rendering layouts and debug vertex indexing.
[Raw results](../../.logs/hair-resolution-gpu.log).
The [head-fitting test](../../.logs/hair-resolution-head_fit.log) covers the same
vertex counts with 4/30/64 ropes and retains its traversal ceiling.

[Executed-work checks](../../.logs/hair-resolution-segment_rays.log) exercise
524,288 overlapping triangles, 64 ropes and up to 30 substeps at each vertex
count. Per-query node/triangle limits remain fixed; total queries scale with
the number of segments. At 32 vertices the point/midpoint ceiling is 7,936
queries and the segment-ray ceiling is 3,968 rays per frame. Fast endpoint
sweeps can add at most 1,984 queries. Timing printed by this synthetic test
is not a live performance prediction.

The default nine-node continuity, guide and ray suites pass after generalizing
the layout. Root-fix shoulder, binding and stability suites also passed before
that generalization. Logs are under `.logs/hair-resolution-*.log` and
`.logs/hair-root-contact-*.log`.

The viewer disconnected before the executable rebuild. The new control has not
been exercised in the live viewer; higher resolution's effect on the remaining
jumps and real-scene GPU cost is unverified. It provides a controlled geometry
resolution experiment, not proof that midpoint contact handling is now reliable
in every pose.

## Build

The canonical Release command completed successfully:

```powershell
cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2
```

[Executable](../../build-vc170-64/newview/Release/secondlife-bin.exe),
[build log](../../.logs/hair-resolution-build.log).
Executable SHA-256:
`340eba166ec67515421c32c390a641ae31244e3fb8124bb014bf39e013cec0e7`.
All six changed packaged resources (four shaders, settings and the preferences
panel) match their source SHA-256 hashes. `git diff --check` passes.
No public class layout changed; the fitting header changes an inline function's
parameters, and the readback struct is private to `llhairmesh.cpp`.
