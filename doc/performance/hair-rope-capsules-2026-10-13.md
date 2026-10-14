# Full rope collision against the animated shell — 2026-10-13

Status: **withdrawn after live GPU failure; rollback built and checked, uncommitted.**
The initial Release build and six small-fixture GPU suites passed, but the live
viewer stuttered severely and the user reported a subsequent crash while hair
loaded. The experimental capsule shader is no longer in the source or staged
viewer. The sections below describe the rejected experiment, not current
viewer behaviour.

## Failure and rollback

The Windows System log contains an `nvlddmkm` error, event 153, at
**2026-10-13 04:14:57 America/Denver** (10:14:57 UTC), with payload
`Error occurred on GPUID: 100`. This confirms a GPU-driver error was recorded;
it does not by itself establish a TDR timeout or identify the failing shader
instruction. No matching application crash entry was returned by the bounded
event-log search. The available viewer log shows all 267 shaders loaded,
but the experimental guide shader took **89.3114 seconds to compile**.
[Filtered diagnostic evidence](../../.logs/hair-capsule-driver-evidence.txt).

Leading cause from code inspection: each rope could issue 72 direct capsule BVH
traversals plus eight nearest-surface traversals per substep, with additional
nearest searches for trapped segments. Each candidate triangle could invoke up
to 24 motion-advancement steps. There was no per-query node/triangle work budget.
Up to 30 substeps compounded this cost after slow frames, and only a few GPU
threads owned the ropes. The existing avatar shell had previously measured over
543,000 triangles. The small GPU fixtures validated geometry but did not cover
this workload. No full-avatar baseline/capsule performance comparison completed.

Restored the exact pre-experiment `hairGuideC.glsl` to source and staged Release
resources, SHA-256
`d3b0de5e76c82551a26994aa61236f7b03454811ed43a3ccddbae25955d07afc`.
This preserves all prior rope density/gradient, elasticity, binding and debug
features. The new CPU/GPU profiling scopes remain. The viewer hashes shader
source contents for cache versioning, so rollback invalidates the experimental
cached binary on next startup. No graphics settings, driver settings or Windows
timeout values were changed. The bridge is unavailable following the reported
crash; the viewer has not been relaunched during rollback.

The rejected shader and its test are retained only as diagnostic files under
`.logs/hair-capsule-rejected.glsl` and `.logs/hair-capsule-rejected-test.py`.
The test was removed from the active test suite because its capsule functions
no longer exist in the restored production shader. Any future segment-collision
implementation must use a bounded candidate/work budget and validate realistic
mesh counts before a live run.

Rollback verification: the [Release build](../../.logs/hair-capsule-rollback-build.log)
passed and source/staged shader hashes both exactly match the pre-experiment
backup above. [Guide](../../.logs/hair-rollback-guides.log),
[binding/elasticity](../../.logs/hair-rollback-binding.log),
[density/gradient](../../.logs/hair-rollback-density.log), and
[contact/debug](../../.logs/hair-rollback-contact_response.log) GPU regressions
all pass. Breathing-fold motion in the restored solver stays below 0.071 mm/frame
in those fixtures; static recovery creates zero launch speed and animated torso
binding remains fixed. The viewer has deliberately not been relaunched, so
post-rollback live stability is not confirmed. The original mesh clipping
limitations return with the previous collision algorithm.

## Change

Animated mesh + Guide chains now query finite capsules along all eight segments
of each rope, directly against the shell's triangle BVH. The radius remains the
existing 5–10 mm contact margin, derived from collision smoothing. This replaces
the one-midpoint mesh probe; it does not add rope nodes or change simple ellipsoid
collision or regional mode without guides.

The query tests the triangle interior and all three finite edges. Conservative
advancement includes both rope and triangle motion, with swept substep bounds,
interpolated poses/normals and compensated avatar-relative origins. Sweeping
before point recovery preserves the entry side of moving thin surfaces. Nearest
surface recovery searches beyond the old grid cache's 12/20 cm ranges, while
retaining the smooth cached planes for ordinary nearby point contacts.

When a segment crosses opposing faces nearly along their normals, it searches
for a transverse exit: pushing against the two faces alone traps a rope through
a thin solid. Four final alternating capsule passes reduce corrections from a
neighbour undoing clearance. Collision recovery remains separate from kinetic
velocity, and embedded immovable roots retain their exception.

`Hair.guides_update` now measures the CPU update and the GPU compute dispatch in
the existing profiler. GPU scopes are inclusive and must not be added to parent
scopes. No new controls or defaults were added.

## Correctness

- [Capsule GPU regression](../../.logs/hair-capsule-capsule.log): a small patch
  at a quarter of a segment is detected even though neither endpoint nor the
  midpoint is nearby; finite edge contacts work and distant triangle-plane
  extensions do not collide. Degenerate triangles produce no invalid values.
- A stationary rope crossed completely by a face moving 4 cm in one 1/120 s
  step retains the entry side, with the correct 25 mm recovery depth and
  4.8 m/s surface velocity. Receding surfaces do not pull, moving ropes are
  swept too, and origin compensation introduces no fake surface velocity.
- A point 30 cm inside a closed box finds its nearest exit; per-iteration
  recovery remains bounded. A full connected rope recovers an embedded node,
  preserves its pin and generates zero launch velocity on a static surface.
- A thin closed box between two clear endpoints, missed by the old midpoint
  location, has **5.070 mm minimum sampled segment clearance** after settling.
  The test samples 101 locations along every segment, not just rope nodes.
- [Binding/fold/elasticity](../../.logs/hair-capsule-binding.log): static
  recovery creates 0 m/s; frozen hair binding has 0 m torso-animation slip.
  Settled breathing-fold motion stays below 1.523 mm/frame at zero elasticity
  and 0.619 mm/frame at 0.25/1 elasticity, with maximum speed below 0.025 m/s.
  Load/release lengths recover at 30/60 Hz in both collision modes.
- [Guides](../../.logs/hair-capsule-guides.log): pins, gravity, inertia,
  neighbour motion, 30/60/7 Hz, surface interpolation/velocity, reset and render
  interpolation pass. Animated 30/60 Hz position difference is below 0.119 mm.
- [Contact/debug](../../.logs/hair-capsule-contact_response.log),
  [stability/lighting](../../.logs/hair-capsule-stability.log), and
  [density/gradient](../../.logs/hair-capsule-density.log) pass, including
  friction, separating motion, actual overlay positions/colours, 4–64 ropes,
  appended skin-palette canaries and previous-frame interpolation.

Existing test fixtures now provide valid BVH bounds/group flags rather than
dummy headers usable only by the old cache lookup. The empty-contact elasticity
test moves its real geometry away and explicitly rebinds both mesh textures.

## Build and live measurements

[Release build](../../.logs/hair-capsule-build.log) passed using
`cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2`.
Canonical executable: `E:\BoxxyViewer\build-vc170-64\newview\Release\secondlife-bin.exe`.
SHA-256: `5cd6f518a5351dd22d14093b651bb68582530e0c317efbb6d260eb6d87b5ea91`.
Source and staged guide shader SHA-256 match:
`4a3a0e65ec287587b4a2c9a6b3394562c6feeba4a9fea6a641c0cf3652c1b552`.

The bridge was unavailable before the experiment's build. After launch and
remembered login, a direct capture requested 120 warmup and 30 measured frames
without changing camera or graphics settings. It progressed extremely slowly;
the last observed state was still warming with 81 warmup frames remaining and
zero measured frames. The user then reported stuttering, a restart and a crash.
No completed timing artifact or screenshot was saved, so there are no valid
live timing results. An attempted camera save during capture was rejected and
did not change or lock the camera.

At capture start, the user's existing settings were four ropes, mesh/guides/
gravity enabled, debug ropes shown, gravity strength 1.05, stiffness 1,
retention 1, bend resistance 0.8, bend gradient 0, elasticity 1, damping 0,
friction 0.2, smoothing 0, shell padding 0.02 m, root radius 0.03 m, root
gradient 1 m and travel limit 0.6. These were read only. Camera, scene and
viewport metadata were not saved before interruption; no matching-view
performance or visual comparison can be claimed.

## Limits

Interior recovery uses nearest outward normals, not an exact solid-volume
representation. Open seams, overlapping parts or inconsistent mesh normals can
still make inside/outside ambiguous. Root pins embedded in the shell cannot
clear their entire first segment. Sweeps use linear motion between available
poses and at most 24 conservative advances; very fast grazing/deforming contact
can still require additional subdivision. Constraint iterations are finite.

Only the guide ropes gain full-segment collision. Interpolated hair cards can
still overlap between ropes, especially at low density. This is a correctness
experiment; it does not claim all hairstyle/hand-animation jitter is eliminated
or that the performance budget is met.
