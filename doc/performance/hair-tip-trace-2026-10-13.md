# Remaining rope jumps: live trace — 2026-10-13

Status: uncommitted; the main remaining cause was identified and corrected.
The user confirms the large kicks are gone. Broad skin-shading name matches
accidentally included Perky-compatible clothing as body collision geometry.
Two corrected live captures have no point steps over 20 mm in 3,000 measured
frames, although smaller contact motion remains. The investigation below also
records the intermediate diagnostic work and a separate cached-patch fix.

## Evidence before diagnostics

The user observes intermittent tip penetration followed by ejection. Different
ropes jump at different times, sometimes with a rhythm that may follow breathing.
The user confirms other applications remain responsive.

The mesh skin/refit/cache and rope solver dispatch every rendered frame. Rope
substeps divide that frame into intervals of at most 1/120 second, interpolating
the current/previous shell poses. Storage and texture-fetch barriers separate
the dependent GPU passes. The CPU main thread prepares the final skeleton
palette and submits work; collision and rope integration run in compute shaders.
The once-per-second surface-eligibility check only invalidates rendering when
eligibility changes. These code observations do not prove every runtime history
transition or cached triangle is correct.

[Pre-diagnostic capture](../../.logs/viewer-mcp/20261013T132628Z-profile-7f0b7913.json):
60 warmup / 1,200 measured frames, unchanged camera/settings, active 32 ropes and
543,501 shell triangles / 300,569 nodes / 310 parts / 14,112 cache cells. Mesh and
guide scopes are active in all 1,200 frames; bake count stays at 15. Frame interval
median 14.900 ms, maximum 27.847 ms; guide GPU median 1.118 ms, maximum 3.178 ms;
mesh update GPU median 0.592 ms, maximum 4.357 ms. No 250 ms slow-frame reset is
possible in this interval, but refits and other reset reasons were not previously
counted. GPU scopes are inclusive; this is a smoke/diagnostic capture, not a
matched optimization comparison. Full scene, camera, settings, viewport and
build metadata are in the raw artifact.

## Bounded diagnostic implementation

During MCP captures only, copy the existing rope positions, velocities and
contact flags into three fixed readback buffers (27 KiB each at 64 ropes).
Consume a copy only after its GPU fence is signaled, polling with zero timeout;
skip a sample if all three buffers are busy. No body-mesh readback or blocking
GPU synchronization is introduced. Release buffers outside captures and on
shader unload. Store at most 4,096 rows in the capture's hair metadata.

Each row records frame duration, guide/mesh history validity, fit status, maximum
point/tip displacement after accounting for head movement, the largest step's
rope/node/contact flags and position, and deviation from the previous velocity's
prediction. That residual includes normal integration and all constraints; it
must not be described as an isolated collision impulse. Comparisons explicitly
mark gaps or changed guide counts as non-consecutive. Cumulative fit/reset
counters distinguish simulation resets from ordinary contact motion.

## Curved contact regression

[Production-GPU test](../../scripts/tests/test_hair_curved_gpu.py) uses the actual
cache and guide shaders on a faceted spherical chest plus overlapping shoulder
lobe. Three rope tips rest at different heights, with a 5 mm sinusoidal radius
change over 3 seconds at 60 Hz, using the user's current stiffness, bend,
elasticity, damping, friction, gravity and root gradient. The first exploratory
run used elasticity 0.15; read-back settings show the user's current value is
zero, so the checked fixture was updated to zero. Simulate 480 frames,
discard the first 240, check finite results, exact root pins and tip steps under
2 mm. Before the patch-distance fix, zero-elasticity maxima were 1.130, 0.178 and
0.296 mm ([output](../../.logs/hair-curved-rigid.log)); afterward they were 0.169,
0.171 and 0.243 mm ([output](../../.logs/hair-patch-curved.log)). This fixture does **not** reproduce
the live avatar's remaining jumps and must not be cited as their resolution.

## Build and live trace

Release compilation passed; the first link collided with the exiting viewer.
No class layout was changed. Relink passed ([log](../../.logs/hair-tip-build.log)).
Executable SHA-256: `6010f6f27fe8baceb6b0e1d17a401047802c0a6d1f5f377bdfaa46bd4c3cc4f3`.
The viewer was restarted and logged in through MCP. Saved camera was restored
and then released; pre/post restart graphics settings match exactly.

Saved pre-restart camera:
[pose](../../.logs/viewer-mcp/20261013T133927Z-hair-tip-before-restart-ddf1ea91.camera.json).

The [first live rope trace](../../.logs/viewer-mcp/20261013T134422Z-profile-b36b245f.json)
used 120 warmup / 1,200 measured frames and returned 1,320 rope samples with zero
dropped readbacks. The first warmup frame had a 417 ms interval and reset; all
subsequent samples retain guide and mesh history. Fits stay at 3 and bakes at 10.
Measured frame interval median is 11.745 ms and maximum 28.457 ms. Capture contains
the same 32 ropes / 543,501-triangle shell. Build, camera, scene, settings and
viewport are in the raw artifact. Post-restart timing is not a controlled
comparison to the earlier session.

After startup recovery, examples include chain 17's tip jumping 66.74 mm at frame
851 and 66.54 mm at frame 1564; chain 15's tip jumps 56.57 mm at frame 970 and
56.48 mm at frame 1691. These samples have history valid and no fit, and usually
change from no final-substep contact to contact. The repeated events on individual
ropes, separated by about one animation cycle, support animation-driven contact
changes rather than a common reset timer. Flags alone do not prove which contact
operation supplies the correction.

## Additional reproduced contact bug

The cached contact blend considered surface orientation but still allowed a
farther parallel patch to contribute its infinite plane at a point outside its
finite triangle. A production-cache test places a raised patch 8 cm in front of
a flat supporting surface and offset sideways. Points already clear of the flat
surface receive false pushes of 7.00, 8.33 and 11.67 mm
([failing output](../../.logs/hair-patch-before.log)).

Both guide and shared mesh helpers now taper candidate influence by excess
distance relative to the nearest patch: full within 5 mm, zero beyond 20 mm.
Existing spatial/directional blending remains within that neighbourhood. The
same queries now have only floating-point error, below 0.00001 m, in both helper
paths ([passing output](../../.logs/hair-patch-after.log)). Opposite-side recovery
and genuine penetration checks remain passing. No additional BVH traversals or
triangle candidates are introduced; workload limits remain unchanged.

Source and staged SHA-256:

- `hairGuideC.glsl`: `d73bc3621c97d81adaff43ee207ac0ea33624f7e7b62c92b7455a79ed40badb7`
- `hairDeformV.glsl`: `8798ac735b0aca221402ac91b6d5cc072efba661f54ffb4b4d5bf59c21b06a87`

All nine GPU suites pass: shoulder, curved, guides, binding, contact,
contact_response, stability, segment_rays and mesh. Logs are
`.logs/hair-patch-<suite>.log` (shoulder is `hair-patch-after.log`). The live reload
completed all 267 programs at 13:50:45 UTC in 65.05 seconds, source version
`ada2b14f-5bc3-f45d-0d07-87d454dff9ed`.

[Post-fix trace](../../.logs/viewer-mcp/20261013T135126Z-profile-e0ea622c.json),
240 warmup / 1,500 measured frames, returned 1,740 samples and zero drops. No
measured history loss or refit occurred. Frame interval median 11.490 ms, maximum
20.023 ms; guides median 0.946 ms, maximum 1.423 ms; mesh update median 0.548 ms,
maximum 1.143 ms. After warmup the largest point/tip step is still **55.63 mm**.
There are 58 frames over 20 mm in 17.52 seconds, compared with 78 in 14.49 seconds
before the fix. This is an uncontrolled live comparison, not an improvement
claim: loop phases, initial rope states and durations differ. The important
result is that substantial recurring jumps remain, with history valid.

## Exact contact probe (in progress)

An extended capture records the point query, both fixed contact planes, nearest
body patch position/identity, its frame motion and distance, at the substep with
the largest constraint correction. It also records the maximum change in final
skinning-palette elements to distinguish body-pose changes from contact changes.
These probes are disabled outside captures and add no collision searches.
Readback buffers are now at most 72 KiB each, plus a 45 KiB GPU probe buffer.

The GPU regression checks that enabling probes leaves the simulation output
identical, returns the expected supporting surface and never writes beyond its
rope slice ([output](../../.logs/hair-probe-shoulder.log)). It also caught a test
fixture binding error: constructing the rope buffers had overwritten the mesh
texture unit in the earlier full-rope shoulder test. The binding is now restored
explicitly; the corrected full-rope test still passes. The standalone contact
reproducer had the correct mesh binding throughout.

Code review of the animation paths: phase offsets are applied at animation
activation/loading completion, rather than periodically resynchronizing self.
Hidden/impostor clock-only updates exclude the local avatar. The collision shell
collects selected rigged body/head attachments and skins them with the same
final palette used by rendering; it does not sample the system Ruth mesh.
These observations are not yet a runtime exclusion of every animation/shape bug.

### Captured contact reversals

The [exact-contact capture](../../.logs/viewer-mcp/20261013T140419Z-profile-902ec0bc.json)
uses 360 warmup / 1,500 measured frames, 1,860 trace rows and zero drops. Release
SHA-256 is `0fc04c43691f98c96b959ed253b52461ffc0a0b4d9b6a9c68b36c008a858c468`;
guide shader SHA-256 is `61f149243bddd7b9785133273ff076e783c9812cb0d2146cd2221f507ed0749f`.
All measured samples have valid history, without a refit. Frame interval median
15.790 ms, maximum 27.918 ms. This diagnostic workload is not a performance
comparison with probes disabled.

At frame 2397, chain 17's tip moves 68.17 mm. Its sampled contact asks for
49.89 mm of correction, while the selected triangle moves only 0.118 mm over
the frame. Chain 18 node 7 subsequently alternates between triangles 2846530
and 2244202 (texture offsets), with nearly opposite normals. Frames 2489–2494
show roughly 16.4 mm alternating point steps and 15–17.6 mm plane penetration,
but only 0.090–0.095 mm of selected-triangle motion. This isolates a contact
direction reversal rather than a simultaneous pose/history reset. It does not
yet identify whether the opposing candidates are different physical surfaces,
hidden layers, or an incorrectly interpreted normal.

Raw maximum palette-element differences are also recorded, but they span all
selected joints and matrix components and must **not** be interpreted as metres
of local surface movement. Selected-triangle displacement is the relevant local
measurement. The probe is taken at the substep with the largest total constraint
correction; it does not isolate every individual solver operation.

The next probe extension adds the nearest authored and geometric normals and
maps its triangle to the source attachment, mesh asset and material face. It
retains all existing collision work limits. The seven-vector probe uses 63 KiB
GPU storage and three 90 KiB readback buffers at the 64-rope maximum. Source
mapping costs four bytes per shell triangle, bounded by the existing one-million
triangle cap.

The [source-normal capture](../../.logs/viewer-mcp/20261013T141744Z-profile-aedb8e03.json)
uses 600 warmup / 1,500 measured frames. Release SHA-256 is
`6380796547b5d8a2db8b51664be2c4e7a8b276b14dcf0762bf8a7ffce70acd81`;
guide source/staged SHA-256 is
`66f839a34c5330f08a44548c21b17fd159da2752b56bf882b9ed99e62f271f32`.
The source probes and general guide GPU regression pass. In the measured trace,
the largest displacement is 66.35 mm. Most large corrections select one mesh
asset, `8246201e-e544-04ac-2f7f-33ee5ac5e95a`, material faces 0–2. Several immediate
opposing contacts select other attachment pieces, typically face 1. For example,
chain 15's tip moves 58.47 mm at frame 1347, then 15.17 mm in the opposing direction
at frame 1348. The latter selects mesh `84778369-688e-0ee2-8815-a8f420a96686`.
Authored and geometric normals agree in direction on both surfaces, so these
samples do not support an isolated shading-normal reversal.

The user identifies the worn body as Legacy Perky and the head as Lelutka Avalon,
with separate hands/feet. They also mention an unusual sitting collider. Shell
collection only recurses through self attachments and requires a selected rigged
SSS mesh; segment rays use only that shell's BVH. World/simulator sitting
colliders are not queried. Whether an eligible attached collision/helper mesh
has been inadvertently collected remains under investigation. Material/name
diagnostics are being added to test that explanation.

## Confirmed wrong collision source

The [material/name capture](../../.logs/viewer-mcp/20261013T142641Z-profile-bd46f405.json)
identifies mesh `8246201e-e544-04ac-2f7f-33ee5ac5e95a` as **Addams // Salem Top with
Necklaces // Perky**. Opposing pieces identify as **[BODY] Legacy (f) Perky (1.7.1)**.
The head identifies as **/ HEAD / lel evox / AVALON 4.0**. The offending source is
clothing geometry, not the simulator sitting collider or the Ruth body. Its
texture has transparent areas, which this geometric shell intentionally does not
model as holes. Its geometric normals are consistent with the contact normals.

The cause is `collect()` using `isSSSEnabled()` to select collision geometry.
SSS's configurable substring whitelist includes **perky**, so clothing labelled
for the Perky body is also eligible. A translucent purple debug view can obscure
overlapping clothing/body surfaces; correct-looking outer geometry did not rule
this out.

That restart placed the avatar in Ungren, rather than Brianconnais, so restoring
the old camera correctly failed its region check. No teleport was requested.
The first material capture has only 508 rope trace rows because the feature was
still becoming active; its initial large recovery samples are not steady-state
evidence. A subsequent [warmed baseline](../../.logs/viewer-mcp/20261013T143206Z-profile-466063c6.json)
uses 240 warmup / 1,500 measured frames and 1,739 trace rows, fixed bake/fit/reset
counts, 543,501 triangles and 310 parts. After discarding 240 trace rows it still
contains a 67.11 mm maximum step and 527 frames over 20 mm. The raw capture stores
the Ungren camera, viewport and settings; no timing comparison to Brianconnais
is valid. Current Release SHA-256:
`2ff10170f85f50f8b0730c3783b0968caccac78a1436d7e270e66ea11d6d22ca`.

### Selection correction

Shell selection now uses `BoxxyHairPhysicsColliderNames`, with default whole
words/phrases **body, head, hands, feet**, independently of SSS. The Hair panel
exposes the list, explains choosing distinctive attachment names and inspecting
the purple shell, and resets it with the category's Default button. Case is
ignored; both word boundaries are required. Linked children inherit the matching
attachment root. An empty list yields no mesh sources. Body names without these
words need a distinctive phrase added to the field. This is configurable name
selection, not a guarantee that every conceivable outfit can be classified
automatically.

[Collector regression](../../scripts/tests/test_hair_mesh_selection.py) compiles
the production collector and reproduces the top's erroneous inclusion before
the change ([failure](../../.logs/hair-selection-before.log)). It passes after
the change ([result](../../.logs/hair-selection-after.log)), retaining actual
body/head/hands/feet and linked pieces, rejecting the top and headphones, testing
runtime list changes/empty lists, and excluding unrelated world objects and HUDs.
Settings and UI XML parse successfully. Solver parameters and all GPU search
budgets are unchanged by this selection correction.

### Release and repeated live validation

The Release build passes ([log](../../.logs/hair-selection-build.log)); canonical
executable SHA-256 is
`8ee821aae7c0a0706b93df54a0e665db3ab670029db3149c1df8438f38f794ae`.
The shader source/staged version remains the seven-vector diagnostic version
listed above. The settings/UI binding/default/reset checks pass with the
collector test. All preceding GPU regressions remain applicable because the
selection correction changes neither solver math nor GPU work budgets.

After this restart, the avatar was back in Brianconnais. The attempted Ungren
camera restore was rejected; that warmup was cancelled. The original Brianconnais
camera was then restored successfully and released before the captures. No
teleport or graphics-setting change was made by this investigation.

Both captures use 32 ropes / 288 points, **101,768 triangles / 296 parts**, versus
543,501 triangles / 310 parts with clothing included. The effective new source
list is its default `body, head, hands, feet`. The source identities producing
the captured maximum corrections now belong to the Legacy body or Avalon head.
Selected triangle count is a direct observation; it is not a proportional GPU
speedup claim.

| Capture | Warmup / measured | Maximum point step | Maximum tip step | Steps >20 mm | Frame median / max | Guide GPU median / max | Mesh GPU median / max |
|---|---:|---:|---:|---:|---:|---:|---:|
| [First](../../.logs/viewer-mcp/20261013T143714Z-profile-467cb4ed.json) | 600 / 1,500 | 10.695 mm | 6.798 mm | 0 | 16.568 / 53.826 ms | 1.227 / 2.815 ms | 0.449 / 2.258 ms |
| [Repeat](../../.logs/viewer-mcp/20261013T143903Z-profile-16d79c56.json) | 240 / 1,500 | 12.993 mm | 10.031 mm | 0 | 18.547 / 24.568 ms | 1.251 / 2.664 ms | 0.450 / 1.848 ms |

Each has zero dropped readbacks, valid guide/mesh history and no fit in all 1,500
measured trace rows. The raw artifacts include settings, scene, camera and
viewport. GPU scopes remain inclusive. Animation phase, scene activity and
restart state are not held identical, so these are repeated functional captures,
not a controlled optimization benchmark.

The [post-fix shell screenshot](../../.logs/viewer-mcp/20261013T143754Z-hair-body-only-shell-38a5dac4.png)
was visually checked with the purple shell and rope overlay active. The user
answered **“Large kicks are gone”** while the corrected Release viewer was
running. This confirms the main visible symptom in the tested outfit/animation;
it does not establish zero jitter, universal automatic name classification,
texture-alpha collision holes, or stability in every hand-through-hair pose.
The new field allows distinctive body attachment phrases when defaults miss a
body or include an unwanted outfit piece. Existing saved stiffness, retention,
gravity, friction, elasticity and other physics controls were preserved.
