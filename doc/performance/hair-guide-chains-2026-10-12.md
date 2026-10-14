# Optional guide-chain hair simulation — 2026-10-12

Status: implemented, uncommitted; live appearance review remains experimental.

## Change

The Hair panel adds `Guide chains (experimental, self only)`, default off.
Unchecking restores the existing regional simulation. Basic and animated mesh
collision remain independent choices, including basic fallback when no shell exists.

Sixteen polar guides, nine points each, fit sampled visible hair geometry in the
head frame. Rigged samples use the current final skin palette; changed selection,
geometry, visibility, skin or skeleton shape invalidates the fit. GPU state retains
point velocities across frames, transforms history between head poses, integrates
world gravity, and interleaves length constraints with point/mid-segment contact.
Steps are bounded to 1/120 second; pauses over 250 ms and large jumps reset history.
Surface drag transfers into the chain; transient collision correction is excluded
from that drag. Displayed vertices interpolate two adjacent guides and two nodes.
All shared colour/depth/shadow paths and TAA use the same deformation, with separate
previous guide buffers. No GPU-to-CPU simulation readback is needed.

Controls: stiffness, shape retention, root radius/gradient and gravity affect guides.
Tip sway, movement response, regional variation and tip lag only affect regional mode.
Shape retention zero removes the guide shape spring while retaining length constraints.

## Validation

- Release build with the repository command. Initial linking was blocked by the
  running executable; after closing it, the viewer target's objects/PCH were removed
  and a complete target rebuild succeeded. The final build also corrects the shader
  progress total to include the new compute program.
- `test_hair_guides_gpu.py`: production shader on NVIDIA RTX 5090; pinned roots,
  idle rest, inertial lag/settling, sideways gravity, segment lengths, 30/60 Hz
  agreement, 7 Hz stability, resets, both collider backends, local displacement
  propagating to neighbours, interpolation/seams, mode fallback and TAA history.
- `test_hair_deform_gpu.py`: 2,175 existing deformation/pass checks.
- `test_hair_mesh_gpu.py`: 127 shell checks.
- `test_hair_contact_gpu.py`: existing contact, persistence, interpolation and history.
- `test_taa_gpu.py`: 119 checks.
- `test_hair_motion.py` and `test_hair_motion_driver.py`: old simulation regression
  and new saved control/default/reset/automation registration.

## Live smoke test

Smart region, 3440 x 1369 viewport, existing hair and graphics settings restored.
Camera remained user-controlled; any camera replay was immediately released.
No performance captures, FPS comparisons or optimization claims, at user request.

The initial live smoke test confirmed 16 chains / 144 points active with basic
collision. Switching to the avatar shell retained guide activation and reported
302 mesh pieces / 319,093 triangles / 244,969 BVH nodes / 6,144 contact field points.
The shell was then disabled again to restore the user's collision choice.

Artifacts:
- [Basic mode screenshot](../../.logs/viewer-mcp/20261012T174029Z-guide-chains-basic-live-c1015c46.png)
- [Basic activation metadata](../../.logs/viewer-mcp/20261012T174054Z-guide-chains-restored-camera-e5dd3e6e.json)
- [Avatar shell screenshot](../../.logs/viewer-mcp/20261012T174151Z-guide-chains-avatar-shell-e92cc4df.png)
- [Shell activation metadata](../../.logs/viewer-mcp/20261012T174151Z-guide-chains-avatar-shell-e92cc4df.json)
- [Full target build](../../.logs/hair-guides-build-clean.log)
- [Final build](../../.logs/hair-guides-build-final.log)

## Limits

Automatic polar fitting approximates loose, hanging styles, not authored strands.
Guide length is capped at two metres. Hair offsets from a guide and space between
collision probes can still clip; there is no hair self-collision. Root-gradient
blending and blending between guides do not preserve every hair-card edge length.
Guide mode currently applies only to the local avatar and requires compute shaders;
other avatars/unsupported hardware keep regional motion. Screenshots verify a smoke
test, not brushing animation quality or temporal smoothness across all hairstyles.

## Final build smoke check

Release executable SHA-256: `e0d1a8906316fec12d0b3fcb237651a42dbbfe563fabde11d94100dfb147fe23`.
Final startup loaded 267/267 shaders; `test_shader_progress_log.py` passed against [filtered startup diagnostics](../../.logs/hair-guides-shader-startup.log).
Final runtime activation: `{"active": false, "available": true, "bakes": 0, "contact_points": 0, "guide_chains": 16, "guide_points": 144, "meshes": 0, "nodes": 0, "triangles": 0}`.
Camera replay was released immediately; user settings restored with guides enabled and basic collision retained.
[Final screenshot](../../.logs/viewer-mcp/20261012T174625Z-guide-chains-final-release-25b723e0.png) / [metadata](../../.logs/viewer-mcp/20261012T174625Z-guide-chains-final-release-25b723e0.json).

## Follow-up: excessive motion at low stiffness

The user reported hair flying around; higher stiffness helped but did not fully
resolve it. The previous tests lacked sustained head movement at low stiffness.
A new production-GPU regression with stiffness 1, retention 0.6, repeated head
translation and gravity reproduced 6.267 m/s point velocity and 0.837 m displacement.

The solver now advances pinned anchors and spring targets across the frame's
substeps instead of applying a whole frame of root motion in the first substep.
Velocity damping increases from 2 to 7 per second. A shape-independent travel
constraint allows 4 cm plus 30% of a node's root distance, scaled by the root
transition weight; projected velocity is limited to 3 m/s so contact cannot create
an unlimited impulse. This is a deliberate stability envelope, not full strand physics.

The same regression now reaches 2.800 m/s and 0.280 m displacement. Added alternating
head turns, zero shape retention and mixed 60/7 Hz frames remain bounded with exact
root pinning. Existing gravity, length, both collision backends, neighbour pull,
render interpolation and TAA checks pass. These are synthetic solver measurements,
not viewer performance captures. Large bends/contact may reach the travel limit;
that can trade motion range for remaining clipping.

Shader-only change staged to the running Release shader directory; no executable
rebuild required. User settings and camera are left unchanged.

Live reload succeeded in 3.21 seconds, shader source `1456dffa-8c5f-b515-1a69-5f0daf07d253`. [Filtered shader log](../../.logs/hair-guide-stability-reload.log). Visual motion improvement awaits user comparison.

## Follow-up: mesh contact does not settle on a stationary avatar

The user reports basic proxies are stable but mesh contacts still move near tips
and protrusions, even in a T-pose. Inspection found that guide collision re-swept
from the authored rest position on every constraint solve, and position recovery
became outgoing velocity. A new regression seeds a point inside a stationary
shell: the old solver generated 2.999 m/s outward velocity from depenetration.

Only the guide compute shader changes: mesh sweeps now start from the actual
previous substep position (including midpoint probes), and accumulated contact
corrections supply a normal for inelastic velocity response. Normal velocity is
removed and tangential velocity damped during mesh contact. Basic collision math
and response remain unchanged. Existing shared mesh recovery helpers are unchanged.

Production GPU tests pass for penetration recovery without outgoing bounce,
retained tangential sliding, stationary plane settling, and a two-face stationary
ridge under pressure at alternating 45/60 Hz. Ridge node movement stays below
0.116 mm/frame after settling; this synthetic ridge was already stable before the
change and is a regression check, not evidence that all avatar jitter is fixed.
The new bounce regression fails before the fix and passes after it. Existing pins,
gravity, length bounds, movement stress, both colliders, neighbour transfer,
render interpolation and TAA checks also pass.

No performance captures or camera/settings changes. Mesh corners with competing
constraints and the approximate guide fit can still cause movement; the user's
stationary-avatar comparison remains the visual acceptance test. The added contact
damping can soften mesh brushing/release, while tangential sliding remains tested.

Live reload succeeded in 3.19 seconds; shader source `ac9225a3-4d87-4612-a9af-4b7ad296b626`. [Filtered reload log](../../.logs/hair-guide-mesh-rest-reload.log).

## Follow-up: triangle-boundary contact discontinuity

The previous bounce fix did not resolve the user's T-pose jitter. A direct
production-GPU contact probe across a stationary two-face ridge now reproduces a
separate discontinuity: changing the input by 0.02 mm switches the old nearest
triangle and changes the corrected output by 28.488 mm. This is a spatial contact
selection problem, independent of avatar animation or velocity damping.

Guide mode now interpolates the eight cached grid-corner surface planes with
continuous spatial weights and proximity support. Body and hand candidates are
blended separately, then constrained separately. Degenerate triangles and nearly
cancelling normals are ignored. Settled/slow contacts use this smooth local field;
steps exceeding 2.5 cm retain the existing swept-recovery helper before the smooth
projection. Regional simulation and basic collision paths are unchanged.

The same contact probe changes by 0.0288 mm with the new solver. A test compares the
old and new production paths on the same ridge fixture. The full guide GPU suite
passes, including stationary ridge settling (about 0.125 mm maximum per-frame
movement at alternating 45/60 Hz), penetration recovery without bounce, tangential
sliding, both colliders, movement bounds, pins, interpolation and temporal history.
The latter ridge-motion number alone is not an improvement claim; the demonstrated
improvement is the removal of the nearest-triangle contact discontinuity.

Tradeoff: blending rounds small surface details and can permit some clipping.
The existing cached grid is 8 cm, so this does not reproduce every fine protrusion.
Fast crossings still use the older swept helper. User T-pose comparison remains
necessary; no performance capture, settings changes, camera changes or restart.

Live reload succeeded in 4.21 seconds; shader source `af94a681-dd39-2343-958a-b5c4d56c4549`. [Filtered shader diagnostics](../../.logs/hair-guide-smooth-contact-reload.log).


### Moving mesh contact interpolation (in progress, uncommitted)

Guide mesh contact now interpolates previous/current skinned vertices and normals for each physics substep. Previous avatar-relative positions are translated into the current shell origin before interpolation. Contact velocity is computed from the same barycentric surface points and used for relative normal/tangential damping. The shared drag increment is spread over the substeps. Roots remain pinned. Mesh history is disabled after a rebuild, a guide reset, missing consecutive frames or a clearance change. The existing fast-crossing recovery runs only at the final substep so it cannot project against a future pose early.

Production GPU checks passed: intermediate surface positions, moving-surface velocity, differing mesh origins, invalid history, pushing-surface response, existing static ridge/no-bounce checks, low-stiffness/turning stress, basic collision and temporal rendering. The synthetic oscillating-plane test differed by at most 0.000017646 m between 30 and 60 Hz. This is a numerical regression check, not a live visual or performance measurement. No performance captures were taken. Final-pose cached triangle candidates remain an approximation for very fast remote crossings; rotating/deforming real avatar contact still needs user review.

Build log: [Release build](../../.logs/hair-guide-moving-contact-build.log). Client launch is left to the user.


### Moving-contact regression correction (in progress, uncommitted)

The user reported worse moving-contact jitter with the interpolation change. The surface-relative velocity response imposed the surface normal velocity even when negative, so a receding surface could pull hair inward while soft contact was still active. It also transferred tangential motion on top of the existing shared drag field.

Keep pose interpolation, but transfer only outward surface-normal velocity. Restore damping of the rope's tangential velocity; the shared field remains the sole source of tangential surface drag. Basic collision is unchanged.

Production GPU regression: a one-substep receding-plane fixture reports -1.1999997 m/s normal velocity with the previous response and 0 m/s with the correction. The identical new test was run against the old response in memory and failed as expected. The full suite passes, including no duplicate tangential transfer, pushing-surface response, stationary ridge, pins, low-stiffness stress, interpolation and reset guards. Oscillating-plane 30/60 Hz maximum position difference is 0.00033412 m. No live avatar confirmation or performance capture; this corrects a demonstrated regression without claiming to eliminate all remaining jitter.

Build log: [Release rebuild](../../.logs/hair-guide-contact-regression-build.log). Client launch left to the user.


### Persistent mesh contact selection (in progress, uncommitted)

The mesh cache independently picked a nearest triangle each frame. A fixed ridge fixture changed contact output by 0.068472 m when only the chosen triangle changed. Crossfading old/new candidates removed that endpoint discontinuity, but a repeated-switch rope fixture worsened (0.000935 m to 0.027230 m maximum frame displacement). That approach was discarded before deployment.

Instead, cache selection retains each previous body/hand candidate when its current animated distance is within 5 mm of the new nearest candidate, within the existing search radius. This introduces contact persistence without interpolating conflicting planes. Bind the previous shell/cache and validated contact history to the cache compute pass; invalid history uses a fresh search. No changes to basic collision or spring parameters.

Production GPU tests passed for retained near ties, release after animation moves a surface away, independent body/hand candidates, invalid offsets and resets (`test_hair_contact_cache_gpu.py`). Guide and shared contact suites pass. No live visual confirmation or performance capture yet; triangles can still switch when another becomes meaningfully closer. This addresses a mesh-specific discontinuity, not a claim that every remaining jitter source is eliminated.

Build log: [Release rebuild](../../.logs/hair-contact-persistence-build.log). A restart is required for the new cache-history binding.


### Mesh motion-transfer isolation (temporary, uncommitted)

Live settings read before the test: hair physics enabled, mesh collision enabled, **guide chains disabled**. Do not assume guide mode is active when diagnosing this session. Shared-field drag is therefore disabled as well as guide-mode surface velocity, without changing saved settings. Positional mesh collision remains enabled in both paths. Two shader-local `mesh_motion_transfer` constants are false; restore both to true after diagnosis.

GPU checks passed for zero shared drag with nonzero collision correction, zero guide normal velocity transfer with retained push-out, and the guide regression suite. The contact suite also passes with transfer restored in memory, preserving coverage of the normal mode. Source shaders were copied to the live Release shader directory and reloaded successfully via MCP in 4.98 seconds; source version `1b029a58-438e-1d83-1c95-43ade2fd1489`. No restart, camera changes, settings changes or performance capture. Waiting for user observation of jitter under the same motion.


### Fixed contact planes per solve (in progress, uncommitted)

User still observed jitter with motion transfer disabled. Live settings again showed guide chains off, so the change covers regional collision as well as the guide solver. Regional `hairMeshMovement` selects its planes once and reuses them across two projection passes; a swept hit owns its contact plane to avoid projecting against an endpoint surface behind the obstacle. Guides sample point and midpoint planes once per substep after integration, then reuse them during all constraint iterations. Fast point sweeps run once and their recovery is recorded for contact damping. Basic collision is unchanged. Motion transfer isolation remains disabled in both shaders.

Production GPU checks passed: a sampled plane retains its normal as projection crosses a ridge; 311 shell/sweep/fitted-shape/temporal checks; guide stability/roots/interpolation tests; zero shared drag with retained push-out; and the shared-contact normal-mode suite compiled in memory. The initial regional implementation failed a swept sliding case, which was corrected by retaining the crossing plane before staging. No performance captures or claims of live visual improvement.

Copied `hairGuideC.glsl` and `hairDeformV.glsl` into the running Release shader directory. MCP shader reload succeeded in 64.57 seconds, source version `120fea99-89da-a306-6193-e6d7d60704f8`. No restart, camera or setting changes. User comparison pending. Planes refresh on the next step; corners and newly reached surfaces remain approximate within the current solve.


### Six-centimetre grid experiment (in progress, uncommitted)

User approved trying 6 cm spacing after the 8 cm grid still jittered. Changed CPU buffer allocation and cache/contact/guide/render shader indexing from 16×16×24 (6,144 samples) to 21×21×32 (14,112 samples). Origin remains (-0.60,-0.60,-1.56) m. X/Y extents remain 1.20 m and Z extends from 1.84 to 1.86 m to avoid reducing coverage. Dispatch rounds up to 111 workgroups and guards the final partial group. Swept sample spacing follows the 6 cm grid; contact margins and the physical triangle-coverage radii are unchanged. Drag and guide velocity transfer remain disabled for isolation.

Production GPU suites passed: mesh skinning/refit/sweeps (311 checks), guide constraints/planes/roots/interpolation, shared-field collision with drag disabled, full contact regression with drag enabled in memory, and persistent cache selection. Fixtures were resized/repositioned onto the new lattice; the last-cell check confirms the partial workgroup is dispatched. No performance captures or live visual improvement claims. Sample count is 2.296875× the previous grid; total GPU impact is unmeasured.

Release build log: [6 cm grid build](../../.logs/hair-grid-6cm-build.log). Full restart required for matching buffer sizes; shader-only reload into the older executable is unsafe. User launch and breathing-animation comparison pending.


### Contact-aware regional bend (in progress, uncommitted)

Live settings confirmed regional mode (guides off), gravity on and animated mesh collision on. User reported substantially less jitter without gravity. This experiment constrains the requested regional sway/gravity displacement against weighted body support planes sampled at the original grid point, before looking up collision at a potentially penetrated endpoint. Available outward clearance is preserved; only inward excess is removed, leaving tangential and outward movement. Existing mesh recovery still follows. The output field subtracts the original unconstrained request so the rendered rotation cannot reapply the removed component. This is a GPU displacement constraint, not contact feedback into the CPU spring. Guide motion is unchanged; hands retain separate collision handling; drag remains disabled.

Production GPU checks passed: inward bend removal, preserved tangential/outward/free-space movement, zero-motion behavior, full-field cancellation of the original inward request, existing collision-isolation tests and normal drag suite enabled in memory. No performance capture or confirmed live improvement. Body support uses nearby approximate planes, so sharp contours and clipping between samples remain limitations.

Copied `hairContactC.glsl` to the Release directory and reloaded via MCP successfully in 1.24 seconds; source version `a2e4a92f-3d2e-3799-fbd9-ff1b4de5d372`. No restart, camera changes or settings changes. Breathing-animation comparison pending.


### Motion transfer restored after isolation

User reported less jitter after enabling guide chains, but animated mesh collision roughly halved their framerate relative to basic colliders (user observation; not measured here). Requested restoration of temporarily disabled motion transfer, with performance investigation deferred.

Restored `mesh_motion_transfer=true` in `hairContactC.glsl` and `hairGuideC.glsl`: shared surface drag and outward guide normal-velocity transfer enabled. Retained no-inward-pull correction, contact persistence, fixed planes, regional bend constraint and 6 cm grid. No saved graphics settings, collision selection, guide mode or camera changed. Contact tests now run normal production behavior plus an isolation variant compiled in memory; guide tests check restored outward velocity. Both suites passed.

Both source shaders were copied to the canonical Release shader directory and verified. MCP settings read and shader reload returned viewer bridge unavailable. Live activation is unconfirmed; restart the normal client or reconnect MCP and reload shaders. No rebuild required for this shader-only restoration and no performance captures taken.
