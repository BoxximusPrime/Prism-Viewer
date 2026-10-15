# Hair contact fixes and full-rope validation

Date: 2026-10-14 America/Denver. Raw capture filenames use UTC, 2026-10-15.

Status: implemented, uncommitted. GPU regressions, the Release build and packaged
shader verification pass. The user will perform the post-fix live viewer test; no live
stability or performance improvement is claimed yet.

Follow-up: the user reported remaining contact flashing. The
[2026-10-15 investigation](hair-contact-flashing-2026-10-15.md) records new live
captures, a pinned-root contact correction and the rope vertex-count setting.

## Changes

The [initial investigation](hair-contact-jitter-2026-10-14.md) reproduced two
friction-independent contact discontinuities. Both point/midpoint contacts and
the shared movement helper now use finite triangle support. Exterior contact
normals transition toward the closest feature at convex edges. For penetration
recovery, support falls away outside the triangle footprint, and scales the
actual correction so normalizing a plane cannot cancel the fade. Sweeps extend
a finite triangle only by the 5 mm rope contact margin.

A continuous weighted normal replaces the instantaneous nearest-normal winner.
Compatible corner constraints share a correction that clears both surfaces;
opposing normals lose influence continuously instead of dividing by a nearly
cancelled normal. The existing split between positional recovery and velocity
is retained. No physics settings were changed.

Finite patches need a local triangle query: triangles selected at the corners
of the existing 6 cm grid do not cover the interior of that grid cell. A bounded,
near-first BVH query retains four body and four hand triangles, seeded from the
eight cache corners. The full solver refreshes these IDs at most twice per
frame and interpolates their geometry on every substep. The query visits at
most 64 nodes and tests at most 32 new triangles plus 16 seeds. Dense overlapping
shells can still exhaust that budget or hide a better patch; this is not an
exhaustive mesh intersection solver.

## Reproduction results

The new [contact continuity regression](../../scripts/tests/test_hair_contact_continuity_gpu.py)
compiles the production GLSL in a hidden SDL/OpenGL context. GPU: NVIDIA
GeForce RTX 5090. No viewer camera, viewport or graphics settings are involved.

| Fixture | Before | After |
| --- | --- | --- |
| Point beside a small, unrelated triangle | 65 mm sideways push | No correction, for body and hand |
| 2.011 micrometre input across its activation boundary | Approximately 65 mm output change | 2.012 micrometre output change |
| 2.828 micrometre input across a perpendicular corner | 4.241 mm output change, 90-degree normal switch | 2.500 micrometre output change; both clearances at least 5 mm |

The corresponding movement helper passes the same finite-support and corner
checks. Additional fixtures cover 1/5/50 mm thin sections, dense tessellation
between cache corners, and cached moving-surface release. The new regression
was first run against the original shaders and failed on the unsupported
65 mm push. [Failure log](../../.logs/hair-jitter-regression-before.log),
[passing log](../../.logs/hair-contact-fix-contact_continuity.log).

## Complete ropes

Each case runs the real nine-node solver, including length constraints,
midpoints, segment rays and velocity response, for 720 frames. The first 600
frames settle the fixture; the final 120 measure maximum consecutive-frame
node displacement. Root pinning and finite values are checked throughout;
body clearance is checked during the measurement window. All cases use
friction 0, damping 3, stiffness 8, gravity 0.6, retention/bend/elasticity 0,
root radius 0.08 m, root gradient 0.27 m and travel limit 2.25. Geometry is the
already-expanded collision surface, so no additional CPU mesh padding is applied.

| Full-rope fixture | Maximum node step |
| --- | ---: |
| Static corner, 120 Hz | 0.000035 mm |
| Static corner, 60 Hz | 0.000011 mm |
| Static corner, alternating 16.5/16.8 ms | 0.1655 mm |
| Corner breathing, 0.5 mm amplitude, three-second period | 0.0598 mm |
| Root pull, 0.5 mm amplitude, three-second period, varying frame duration | 0.1785 mm |
| Faceted curved shell breathing, 5 mm amplitude, three-second period, varying frame duration | 0.2998 mm |
| Rope beside the unrelated finite patch | No horizontal displacement throughout; zero settled step |

Flat/root fixtures must stay below 0.5 mm per measured frame; the curved fixture
must stay below 1 mm. These are stability regression thresholds, not predictions
of motion in arbitrary scenes. The original static full-rope fixture did not
reproduce the large live jumps; the isolated before/after contact reproductions
establish the two fixes independently.

Other passing production-GPU suites:

- [Guides](../../.logs/hair-contact-fix-guides.log): pins, inertia, frame durations,
  mesh motion, origin compensation and ridge continuity. Settled ridge variation
  is 0.0224 mm.
- [Shoulders](../../.logs/hair-contact-fix-shoulder.log): thin surfaces, penetration
  recovery and complete-rope motion under a 0.2 mm head movement.
- [Binding](../../.logs/hair-contact-fix-binding.log): recovery without launch,
  breathing folds, elastic loading and frozen skeletal bindings.
- [Stability](../../.logs/hair-contact-fix-stability.log): travel/root constraints,
  separation velocity and authored shading normals.
- [Mesh](../../.logs/hair-contact-fix-mesh.log): 311 checks, including finite swept
  coverage. The old expectation of contact 4 cm beside a tiny triangle was
  replaced with literal-triangle and 5 mm thickness cases.
- [Contact cache](../../.logs/hair-contact-fix-contact_cache.log): near ties,
  animated release, independent hands, history reset and bounded traversal.
- [Shader batch](../../.logs/hair-contact-fix-shader_batch.log): loader lifetime,
  failure handling and unsupported GPU fallback. Its temporary compilation
  directory was placed under `.logs` after the sandbox's default temp directory
  denied file creation.

## Bounded workload

The [instrumented segment-ray test](../../scripts/tests/test_hair_segment_rays_gpu.py)
also counts actual finite-contact queries, traversed nodes and triangle fetches.
With 524,288 overlapping triangles, 64 ropes and 30 substeps, point/midpoint
refinement executed 2,048 queries, 59,392 node visits and 65,536 triangle fetches.
The assertions enforce 64 nodes and 32 new plus 16 seed triangles per query.
Segment-ray counts remained 1,024 rays, 29,696 node visits and 32,768 triangle
tests, within their existing limits. [Raw log](../../.logs/hair-contact-fix-segment_rays.log).

Fast endpoint sweeps may add one finite-contact query per free point on the
final substep, up to 512 more queries at 64 ropes; that branch was not triggered
by the stationary stress fixture. Thus the complete refinement ceiling is
2,560 queries per frame, not just the 2,048 point/midpoint queries exercised here.

The instrumented stress fixture measured 3.612 ms median / 5.138 ms maximum
over 10 samples after five warmup dispatches. This is one synthetic test run,
not a matched before/after viewer comparison. It proves executed-work bounds;
it does not establish the live performance cost of the added local queries.
The cache test independently retains its previous 128-node ceiling.

## Build and live test

Build command:

```powershell
cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2
```

The Release build completed successfully. [Executable](../../build-vc170-64/newview/Release/secondlife-bin.exe),
[build log](../../.logs/hair-contact-fix-build.log). The initial sandboxed MSBuild
invocation stalled at startup and was cancelled; the same authorized build
command completed outside the sandbox. No C++ class layouts changed.

Build: Prism 0.10.0.54542, checkout HEAD `74a5f590a20` plus these uncommitted
changes. SHA-256 checks confirm both packaged shaders match source:

- `hairCollision.glsl`: `4a6f97dd9377624b33aee4babe22141bb9e6796f8d4d1a7655b821e1e396c264`
- `hairGuideC.glsl`: `0f4ac5a9f9a0e74d2c0207bf660ae594c4bae2f3462fbf4f41e52abc2de21c08`
- `secondlife-bin.exe`: `2197d6daf6f5d3134a64277a3a900cb3e2825ebc2e7503878b176ca866df9db3`

The executable hash is unchanged because the production changes are runtime
GLSL resources; the verified packaged shader hashes identify the new behavior.

No post-fix live capture was taken: the user requested to run the viewer
personally. The pre-fix scene/camera, viewport, settings, warmup/sample counts
and raw capture links remain in the initial investigation. Confirming that
these corrections eliminate the reported avatar jumps, and measuring their
cost on the actual collider meshes, remains a live-test task.
