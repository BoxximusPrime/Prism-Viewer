# Shoulder rope jumps — 2026-10-13

Status: in progress, uncommitted. Eight GPU suites, Release build, shader reload
and live timing smoke checks pass. This fixes a reproduced contact bug; visual
confirmation across animations remains, and not every reported rope jump is yet
confirmed resolved.

## Video and timing evidence

User video: `C:\Users\user\Videos\2026-10-13 06-13-46.mp4`, 3440 × 1440,
60 fps, 289 frames, 4.821 seconds. Inspected extracted frames, including the
[overview](../../.logs/hair-shoulder-video/sheet-01.jpg) and
[shoulder sequence from 0.8–1.9 seconds](../../.logs/hair-shoulder-video/shoulders-080-190.jpg).
Individual shoulder ropes shift abruptly while roots and neighbouring ropes
continue moving smoothly. That pattern suggests local contact correction rather
than a whole-guide reset, but video alone cannot identify the solver operation.

A separate unchanged-viewer [300-frame capture after 30 warmup frames](../../.logs/viewer-mcp/20261013T122131Z-profile-8535dbec.json)
had a maximum frame interval of 20.30 ms (median 13.18 ms), with shell bake count
unchanged at 12. Animated mesh, 32 ropes and the 543,501-triangle shell were
active. This capture contains no 250 ms frame stall and does not support the
slow-frame reset explanation during that interval; it is not synchronized to
the user's recording. No camera or graphics settings were changed for it.

## Reproduced cause

The mesh cache has 6 cm grid spacing. Neighbouring cells can select opposite
sides of a thinner closed surface. The guide solver blended their normals and
signed clearances into one plane, then divided the clearance by the length of
the blended normal. Opposing normals nearly cancel. Once their length crosses
the contact-validity threshold, the resulting plane can produce a large push
despite the rope point already being outside the shell.

A production-GPU test uses a 5 cm thick section and the actual cache generator:

| Point x | Position relative to outer surface x=0.025 m | Old outward correction |
| --- | --- | ---: |
| 0.0359 m | Already clear by 10.9 mm | Approximately zero |
| 0.0361 m | Already clear by 11.1 mm | **91.85 mm** |
| 0.0400 m | Already clear by 15 mm | **40.00 mm** |

Only 0.2 mm separates the first two queries. This is a false-contact
discontinuity, independent of GPU scheduling, frame duration, stiffness tuning
or a history reset. [Original failing output](../../.logs/hair-shoulder-before.log).

## Fix

For each body/hand contact, find the closest valid local candidate normal before
blending. Smoothly reject patches whose normals disagree with that reference;
only candidates with dot product above 0.25 contribute, with full influence
above 0.5. Accepted normals therefore cannot cancel through the previous 0.2
validity threshold. Keep the existing spatial weighting within that surface
patch, fixed solver planes, moving-surface velocity and independent body/hand
contacts.

Both `sampleGuideContact()` and the shared `hairMeshPlanes()` helper apply this
rule, so the rope sweep and regional mode cannot reintroduce the opposite-face
blend. The guide path retains eight candidate samples per kind. The shared
helper re-evaluates its already bounded list of at most 54 unique candidates;
there are no additional BVH searches. All ray/cache search limits, batching and
guide-mode workload reduction from the responsiveness fix remain in place.
No settings or history-reset rules changed.

## Checks

- [Shoulder regression](../../.logs/hair-shoulder-shoulder.log): all tested clear
  points on both sides have negligible correction (floating-point error below
  0.00001 m). Both helper paths recover a point 3 mm inside the surface to the
  existing 5 mm margin. In the full production rope solver, 0.2 mm head motion
  produces maximum node movement **0.1996 mm**, preserving the root pin.
- [Guides](../../.logs/hair-shoulder-guides.log),
  [binding/breathing/elasticity](../../.logs/hair-shoulder-binding.log),
  [regional contact](../../.logs/hair-shoulder-contact.log),
  [contact response](../../.logs/hair-shoulder-contact_response.log),
  [stability](../../.logs/hair-shoulder-stability.log), and
  [mesh skinning/refit/collision](../../.logs/hair-shoulder-mesh.log) pass.
- [Segment-ray stress](../../.logs/hair-shoulder-segment_rays.log) still respects
  the 1,024-ray / 65,536-node / 32,768-triangle per-frame ceilings with 524,288
  overlapping triangles, 64 ropes and 30 substeps. Five warmup / ten measured
  complete-guide dispatches have a synthetic median 6.330 ms, maximum 8.008 ms
  while the live viewer was also running. These timings are not a controlled
  comparison to earlier runs and exclude the rest of the avatar pipeline.

## Build and live verification

The prescribed Release build passed ([build log](../../.logs/hair-shoulder-build.log)).
Only GLSL, the focused GPU regression and documentation changed; no C++ class
layout was changed. Canonical executable:
`E:\BoxxyViewer\build-vc170-64\newview\Release\secondlife-bin.exe`,
Prism 0.9.0.54539. SHA-256:

- Executable: `9ff638d2508aee87138d4f3e351a1f25e6b3e1cffb58318e75d04fdf0624f47c`
- Source/staged `hairGuideC.glsl`: `efc3150a646c9acfb95dce96b95d85a100793d9670717aaf69c636a62443082a`
- Source/staged `hairDeformV.glsl`: `5c87f5e3a407287cab2dbc2710554fbc8b3a2c9720fd50d737d04a61441a1f2d`

The running viewer successfully reloaded all 267 shaders from the Release
directory at 12:31:46 UTC ([reload log](../../.logs/hair-shoulder-reload.log)).
Reload duration was 64.58 seconds; source version was
`94082948-a7d5-7a61-39da-f8517489df59`.

The [after capture](../../.logs/viewer-mcp/20261013T123225Z-profile-e15ed77f.json)
used **120 warmup / 180 measured frames**, RTX 5090 / NVIDIA 617.14, in Brianconnais.
Viewport was 3440 × 1369, render area 3440 × 1316. Camera was unlocked and stable
through this capture: position `(289292.98829, 278767.93898, 1366.72290)`, forward
`(-0.199866, 0.943647, -0.263788)`, up `(-0.054658, 0.258063, 0.964581)`, FOV 60°.
No camera, graphics or animation settings were changed by the test.

[Captured settings](../../.logs/hair-shoulder-graphics.json): physics, animated
mesh, guides, gravity and rope overlay enabled; 32 ropes / 288 points; root
radius 0.1 m, pin gradient 1 m, stiffness 5.5, retention 1, bend 2.4, bend gradient
0, friction 1.15, damping 12.5, elasticity 0.15, gravity 2.3, collision smoothing
0.15, mesh padding 0, travel 2, tip lag 0.3, amount 30, response 0, collision scale
1.5. The active shell had 543,501 triangles, 300,569 BVH nodes, 310 parts and
14,112 cache cells. Bake count stayed at 13 throughout.

| Measurement | Median | Maximum |
| --- | ---: | ---: |
| Frame interval | 13.190 ms | 18.173 ms |
| Guide GPU scope | 1.091 ms | 1.627 ms |
| Mesh update GPU scope | 0.599 ms | 2.969 ms |

Frame interval p95 was 15.452 ms and p99 was 16.943 ms. No frame approached the
250 ms history-reset threshold. GPU scopes are inclusive and must not be added.
This short capture is a smoke check, not a matched performance comparison.

The [post-reload screenshot](../../.logs/viewer-mcp/20261013T123251Z-hair-shoulder-after-193a6c2f.png)
and its [metadata](../../.logs/viewer-mcp/20261013T123251Z-hair-shoulder-after-193a6c2f.json)
show the live rope overlay and hair, but a still image cannot establish that
intermittent jumps have stopped. Subsequent user feedback confirms jumps remain,
possibly reduced but not reliably so. Tips appear to enter the shell before
being pushed out; the apparent rhythm is not shared by every rope and could
follow breathing. See the [follow-up trace](hair-tip-trace-2026-10-13.md).

## Remaining limits

The mesh cache still approximates geometry, and its capped search can miss a
better candidate. Selecting between genuinely separate nearest surfaces can
still change the contact direction. Fully embedded ropes, sharp folds and
competing constraints need additional observation. A 250 ms pause still resets
rope history. The user has already confirmed the preceding GPU workload fix
restored other applications; that does not establish that every remaining rope
jump shares the same cause.
