# Hair rope contact jitter investigation

Date: 2026-10-14 America/Denver. Raw artifact filenames use UTC, 2026-10-15.

Status: investigation complete; report uncommitted. Production code and viewer
settings were not modified during this initial investigation, and no new build was made. Two contact discontinuities
were reproduced on the GPU using the current production shaders. They provide
concrete mechanisms for friction-independent jumps. Live captures support a
contact problem, but do not attribute every observed jump to one operation.

The subsequent implementation and regression results are recorded in
[Hair contact fixes](hair-contact-fix-2026-10-14.md). The findings below describe
the original shaders and baseline captures.

## Findings

### Finite triangles become unsupported collision planes

`sampleGuideContact()` finds a closest point on each finite triangle, but uses
`dot(gap, normal)` to construct a plane. It can then push a rope lying beside the
triangle, outside its footprint. The range is 20 cm for body candidates and 12 cm
for hands. The distance fade weights the plane average; it does not fade the
resulting correction. With one plane, dividing weighted clearance by weighted
normal magnitude cancels the influence. A nearly zero influence still produces
the full correction until the total-weight cutoff disables it.

The earlier relative-distance rejection only helps when a closer candidate of
the same kind exists. It cannot reject a lone, inappropriate patch. Independent
hand contacts are particularly exposed to this case. The shared sweep helper
has the same finite-patch extension in `hairMeshPlanes()`.

Production-GPU reproduction, with a stationary small triangle at x=0.08 m and
y=0.05–0.09 m, querying x=0.02 m, y=0, z=-0.4 m:

- The nearest finite triangle point is **82.704 mm away**. The point receives a
  **65.000 mm sideways correction** anyway, for both body and hand classification.
- Moving a query **0.002012 mm** across the hand-contact activation boundary
  changes its correction from approximately zero to **65.000 mm**. The triangle
  is stationary and there is no friction, animation, rope refit or frame hitch.

Relevant code: [guide sampling and projection](../../indra/newview/app_settings/shaders/class1/deferred/hairGuideC.glsl),
lines 203–251; [shared collision helper](../../indra/newview/app_settings/shaders/class1/deferred/hairCollision.glsl),
lines 41–103 and 175–192.

### Selecting one nearest normal creates a discontinuous contact direction

`sampleGuideContact()` chooses the nearest contributing candidate's normal, then
rejects other candidates according to their agreement with that winner. The
agreement filter is smooth, but the winner selection is a hard comparison.
Switching the nearest candidate can therefore replace the entire accepted group
of normals. There is no persistent per-rope-point contact identity here; the
cache's persistence belongs to its 6 cm grid cells.

Production-GPU reproduction with two perpendicular surface patches:

| Query | Projected position in metres |
| --- | --- |
| (0.002001, 0.001999, -0.4) | (0.002001, 0.005000, -0.4) |
| (0.001999, 0.002001, -0.4) | (0.005000, 0.002001, -0.4) |

A **0.002828 mm** input change rotates the contact normal by 90 degrees and
changes the output position by **4.241 mm**. Both queries need clearance from
both surfaces, but the solver selects one. The shared helper reproduces the
same switch. This is a concrete mechanism for alternating positions when rope
constraints pull a point back across a contact-selection boundary.

Relevant code: [guide nearest-normal selection](../../indra/newview/app_settings/shaders/class1/deferred/hairGuideC.glsl),
lines 206–225; [shared nearest-normal selection](../../indra/newview/app_settings/shaders/class1/deferred/hairCollision.glsl),
lines 73–94. Simply averaging opposing normals again would reintroduce the
previous thin-shoulder cancellation bug.

### Friction tuning cannot remove these position corrections

Contact projection is interleaved with length constraints and applied again
after the iteration loop. Friction acts later on tangential velocity, at
`hairGuideC.glsl:496`. Setting friction to zero does not affect either reproduced
contact operation. The fixed planes are also reused after length and midpoint
constraints move their query points. This can amplify disagreement between
contacts and rope constraints; its separate contribution was not measured.

The cache intentionally retains a triangle until a replacement is more than
5 mm closer (`hairContactC.glsl:80`). That can resemble sticking, but the tested
parallel-patch history sequence did not produce a large discontinuity. It is
not established as the primary cause.

## Live evidence

Two direct MCP captures each used **240 warmup and 1,500 measured frames**.
All 1,500 analyzed post-warmup rope rows in each capture were consecutive, retained
guide and mesh history, and had no refit. Neither capture dropped a readback.
Fit/reset/bake counters stayed constant within each capture. The guide GPU scope
was active in every measured frame.

| Capture | Median / maximum largest node step per frame | Frames above 5 / 20 mm | Frame interval median / max | Guide GPU median / max |
| --- | --- | --- | --- | --- |
| [First](../../.logs/viewer-mcp/20261015T023724Z-profile-ba8acfd2.json) | 4.504 / 113.301 mm | 654 / 186 | 15.300 / 25.282 ms | 1.495 / 2.527 ms |
| [Second](../../.logs/viewer-mcp/20261015T024019Z-profile-6ef54ee3.json) | 0.617 / 20.768 mm | 17 / 1 | 15.383 / 19.615 ms | 1.303 / 1.933 ms |

These are different live scenes/poses, **not a before/after comparison**. The
first was in Neo Star with a hand near the hair and an unlocked moving camera;
the second was in Brianconnais with a stable unlocked camera. The region and
camera changed through ordinary viewer interaction between captures. No camera,
teleport or settings mutation was performed by this investigation. The guide
overlay was switched on through ordinary viewer interaction; all sampled physics
parameters were unchanged. Exact start/end camera poses are retained in the raw
captures and [summary](../../.logs/hair-jitter-summary.json).

Both captures used a 3440 × 1369 viewport, 3440 × 1316 render area, 14 ropes,
126 points, 89,607 collision triangles and 65,535 BVH nodes. GPU: RTX 5090,
NVIDIA 617.14. GPU scopes are inclusive and must not be added together. These
are diagnostic captures, not optimization measurements.

Specific observations:

- First capture: 82 adjacent peak-trace pairs for the same rope/node combine
  a body-contact normal change exceeding 60 degrees with a node step above 5 mm.
  For example, chain 12 node 6 switches between body triangle offsets 254155 and
  451591. At frame 195973 the node steps **22.466 mm**, while its newly selected
  triangle moves approximately **0.162 mm**. The following frame switches back.
  These offsets are local diagnostic identifiers, not asset IDs.
- Second capture: chain 0 node 4 steps **14.006 mm** at frame 206897 while its
  selected body patch moves only **0.0679 mm**. Its sampled hand plane is absent.
  A similar **13.995 mm** event occurs at frame 207387. This demonstrates that
  the residual issue also occurs without an active sampled hand plane.
- Peak probes record the substep with the largest combined constraint correction,
  not an isolated collision impulse. Only the greatest-moving point is traced
  each frame. The trace therefore cannot reconstruct every neighbour's contribution
  or conclusively assign each event to the two synthetic reproductions.

[First-scene screenshot](../../.logs/viewer-mcp/20261015T023745Z-hair-jitter-investigation-baseline-70401174.png)
and [second-scene rope overlay](../../.logs/viewer-mcp/20261015T024414Z-hair-jitter-investigation-second-scene-150745ea.png)
were visually inspected. Still images establish the visible setup, not temporal stability.

## Build and settings

Running viewer: Prism Release 0.10.0.54542,
`E:\BoxxyViewer\build-vc170-64\newview\Release\secondlife-bin.exe`.
Executable SHA-256:
`2197d6daf6f5d3134a64277a3a900cb3e2825ebc2e7503878b176ca866df9db3`.
Checkout HEAD: `74a5f590a20`. Source and staged guide/cache shader hashes matched:

- Guide: `e245ac5110450fe612468e856e488e7a0ca42fa2dd5177e6b17e10cb96c1957b`
- Cache: `3a95b692e94bc435d75ccb4e5df70058d47129dd04172b6c6f9aadb52d851d9b`

Observed physics settings: friction 0, damping 3, elasticity 0, bend resistance 0,
shape retention 0, stiffness 8, gravity enabled at 0.6, root radius 0.08 m,
root gradient 0.27 m, mesh padding 0.015 m, collision smoothing 0, travel limit
2.25 and density 14. The padding is additional to the solver's 5 mm contact
margin. Exact float values and before/after setting reads are in the local summary.

## Reproduction and limits

The initial run used this [local diagnostic script](../../.logs/hair-jitter-probe.py):

```powershell
scripts/viewer_mcp/.venv/Scripts/python.exe -u .logs/hair-jitter-probe.py
```

[Raw output](../../.logs/hair-jitter-probe.log). That run compiled the original cache,
guide and collision GLSL in the existing hidden SDL/OpenGL harness. Its diagnostic
assertions confirm the original incorrect contact responses; they are not
passing-fix regression assertions. With the subsequent fixes installed, use the
[contact continuity regression](../../scripts/tests/test_hair_contact_continuity_gpu.py)
instead. All synthetic tests use the real GPU.

A complete nine-node rope against the static perpendicular corner, using the
current physics tuning, was also simulated for 720 frames per case, analyzing
the final 120. Maximum steps were 0.1265 mm at 120 Hz, approximately zero at
60 Hz, and 0.1781 mm with alternating 16.5/16.8 ms frames. Roots remained pinned
and results finite. Thus this full-rope fixture does **not** reproduce the large
live jumps. Variable substep count alone was insufficient in this fixture;
the isolated contact discontinuities remain demonstrated independently.

## Recommended correction order

1. Give point and midpoint contacts finite geometric support. Use appropriate
   closest-feature or swept contact for ordinary exterior motion, while preserving
   deliberate deep-penetration recovery with a reliable side/inside criterion.
   Merely shrinking the range or capping each push could hide the symptom and
   allow tunnelling or trapped points.
2. Keep a bounded set of geometrically valid contact constraints across compatible
   creases, with continuity as their influence changes. Avoid selecting a whole
   normal group from an instantaneous nearest-candidate winner, and retain the
   protection against mixing opposite sides of a thin shell.
3. Turn these diagnostic cases into regression assertions for continuity and
   clearance, then exercise slow breathing, moving hands, pin gradients, concave
   folds and frame-duration transitions in complete ropes and live captures.
   Preserve current BVH/query budgets and verify all affected helper callers.

Changing damping, friction or bend resistance is not a correction for these
invalid contacts. No production fix or post-fix validation is claimed here.
