# Bounded hair segment rays — 2026-10-13

Status: in progress, uncommitted. Six GPU regression suites, Release build
and live smoke tests pass; broader animation validation remains. This replaces none of the existing point or
midpoint contacts and does not restore the withdrawn capsule experiment.

## Implementation and bounds

Animated mesh + Guide chains casts a finite, two-sided ray between each pair of
rope nodes. Current and previous mesh poses are interpolated at the chosen
substep, including avatar-origin compensation. An intersection uses the
triangle's outward orientation and the deepest part of the segment whose
projection lies inside that finite triangle. This avoids constraining a whole
fold against a triangle's infinite plane.

The additional correction is shared by the neighbouring nodes according to
contact position and mobility. Pins remain fixed; contacts that conflict with
opposing endpoint normals yield. The ray uses only 0.5 mm numerical separation;
the retained point contacts supply thickness and penetration recovery. Each ray
correction is capped at 2 mm per endpoint per projection. Existing separation of
position recovery from velocity prevents the correction from becoming a kick.

Work limits are constants, independent of mesh density or frame duration:

| Added ray work | Hard maximum |
| --- | ---: |
| Searches per segment per frame | 2 |
| BVH nodes visited per search | 64 |
| Triangle tests per search | 32 |
| Searches per frame, 64 ropes × 8 segments | 1,024 |
| BVH visits per frame | 65,536 |
| Triangle tests per frame | 32,768 |

Searches occur at up to two substeps, including the last, outside the repeated
constraint loop. The solver reuses each result for its four existing contact
projection passes. An incomplete search discards even a partial hit and leaves
the existing point/midpoint solver in control. A slow frame can still increase
the pre-existing solver's substeps, but cannot multiply the new ray budget.
The CPU and shader both cap density at 64; the local avatar's guides update once
per frame. There are no new settings or defaults.

## Synthetic GPU verification

Windows, NVIDIA GeForce RTX 5090, driver 617.14, OpenGL 4.3 hidden SDL context.
The tests compile and execute the production shaders; the budget test injects
operation counters only into its own shader programs.

- [Segment rays and stress fixture](../../.logs/hair-rays-segment_rays.log):
  finite and two-sided intersections, nearest hit, missed triangles, degenerate
  triangles, fixed/embedded pins, shared correction, finite footprint, moving
  mesh and compensated origin. A full-solver fixture clears a crossing missed
  by point/midpoint contacts, without moving the pin or introducing velocity.
  Exhausted node/triangle budgets fall back without moving the rope.
- [Guides](../../.logs/hair-rays-guides.log): pins, inertia, gravity, both collision
  modes, 30/60/7 Hz, surface motion, interpolation and invalid history.
- [Binding and elasticity](../../.logs/hair-rays-binding.log): static recovery
  produces zero launch velocity; torso animation produces zero binding slide.
  Breathing-fold maximum settled movement is 0.068/0.064/0.358 mm per frame for
  elasticity 0/0.25/1; maximum speeds remain below 0.045 m/s. Existing thresholds
  pass without relaxation.
- [Contact response](../../.logs/hair-rays-contact_response.log): no resting
  drift, curved-proxy sliding, sideways gravity, friction and debug positions.
- [Density and bend gradient](../../.logs/hair-rays-density.log): 4/7/16/31/64
  ropes, preserved palette storage, interpolation and unchanged pins.
- [Stability](../../.logs/hair-rays-stability.log): ridge motion, travel limits,
  root fade, separation velocity, bending and rendered contact normals.

The stress fixture has **524,288 overlapping candidate triangles**, deliberately
loose BVH bounds, 64 ropes and eight active segments each. At 0 and 1/120 second,
it executes 512 rays, 14,848 node visits and 16,384 triangle tests. At 1/60, 1/30
and 0.25 second (30 substeps), it executes 1,024 rays, 29,696 node visits and
32,768 triangle tests. An independent fixture saturates the 64-node limit.

After five warmup dispatches, ten measured dispatches of the **complete
instrumented guide solver**, at 30 substeps, have a median GPU elapsed time of
**3.207 ms**, maximum **3.466 ms**. This is one synthetic run, not an isolated
ray cost, a live frame time, or a before/after optimization comparison. It
excludes mesh skinning, BVH refitting, contact-cache construction and rendering.

Source shader SHA-256:
`87d824a01d44ea336d1ab7a4b8f471b8720636db0ae7253e4952b97a254db834`.

## Release and live verification

[Release build](../../.logs/hair-rays-build.log) passed using
`cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2`.
Source and staged shader hashes match the value above. Canonical executable:
`E:\BoxxyViewer\build-vc170-64\newview\Release\secondlife-bin.exe`, SHA-256
`5cd6f518a5351dd22d14093b651bb68582530e0c317efbb6d260eb6d87b5ea91`.
No C++ changes were needed for these rays.

Prism Release 0.9.0.54539 launched through the local MCP and logged in with its
remembered account. [All 267 shaders loaded](../../.logs/hair-rays-startup.log);
the guide shader's first viewer compile took 22.0146 seconds. This is startup
compilation time, separate from dispatch timing.

Scene: Brianconnais, the saved third-person room view. Viewport **3440 × 1369**,
render resolution **3440 × 1316**. Camera position
`(289293.100127, 278766.231735, 1367.850220)`, forward
`(-0.870290, -0.436402, -0.228361)`, vertical FOV 60 degrees, unlocked and
unchanged from capture start to end. No camera or graphics settings were changed.
[Recorded graphics settings](../../.logs/hair-rays-graphics.json) match after
capture: mesh/physics/guides/gravity on, 4 ropes, guide overlay on, damping 0,
elasticity 1, stiffness 1, retention 1, bend resistance 0.8, bend gradient 0,
friction 0.2, gravity strength 1.05, root radius 0.03 m, root gradient 1 m,
mesh padding 0.02 m, collision smoothing 0, travel limit 0.6.

The live shell has **543,501 triangles**, 300,569 BVH nodes, 310 mesh parts and
14,112 contact-grid points. All four guide chains (36 points) are active.

| Smoke capture | Warmup / measured | Guide GPU median / max | Observation |
| --- | ---: | ---: | --- |
| [Initial loading](../../.logs/viewer-mcp/20261013T105457Z-profile-57b78843.json) | 5 / 10 frames | 1.007 / 1.073 ms | Two CPU mesh bakes, up to 410 ms; unsuitable for steady timing |
| [After loading](../../.logs/viewer-mcp/20261013T105529Z-profile-6be547cc.json) | 30 / 60 frames | 1.211 / 1.245 ms | No mesh rebakes during capture; frame interval median 16.90 ms, max 19.33 ms |

The second capture's existing mesh-update GPU scope has median 6.982 ms;
its CPU scope has median 0.790 ms. These are inclusive scopes, not additive
components. Guide timing includes the whole guide solver, not just new rays.
Neither capture is a baseline comparison or an optimization claim.

[Screenshot](../../.logs/viewer-mcp/20261013T105506Z-hair-segment-rays-smoke-13323044.png)
and [camera metadata](../../.logs/viewer-mcp/20261013T105506Z-hair-segment-rays-smoke-13323044.json)
show loaded hair and intact rope diagnostics, with no obvious exploded geometry
in that view. The viewer stayed responsive. A still screenshot cannot establish
settling quality; hand-through-hair, seated poses, dense live ropes and longer
sessions remain untested. No driver-stability guarantee follows from this smoke
test.

## Limits

This supplements coverage; it is not a swept capsule or continuous collision
solver. Rays have no thickness and can miss a fully embedded segment or a
surface that passes completely through between sampled poses. Dense overlapping
geometry can exhaust a budget and retain the preceding solver's clipping.
Only the nearest completed ray hit is used, and gentle capped recovery can take
several frames. Existing point contacts remain essential. Work bounds prevent
the previous unbounded search amplification; they do not guarantee driver
stability or a particular frame rate on every device.
