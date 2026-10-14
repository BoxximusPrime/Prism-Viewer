# Hair fitting and head contacts — 2026-10-13

Status: implemented and user-confirmed, uncommitted. The user confirms the trapped head ropes are resolved. The preceding clothing-selection fix also remains effective.

## Findings and implementation

- `fitGuides()` sampled the live animation palette. Crouching, leaning, and torso poses could become permanent rest geometry and frozen hair bindings. It now uses the existing shape-aware neutral skeleton from shoe-height fitting, extracted as a shared helper. The same neutral palette drives both the fitted points and their frozen rendering bindings. The live skeleton and animation state are untouched.
- Mouth geometry is a hypothesis, not yet confirmed. Peak-motion traces miss stable penetrations; captures now keep one full rope snapshot, replaced at most every 30 frames, from the existing asynchronous readback. This adds no GPU searches or synchronous GPU waits.

## Full-point diagnosis

The neutral-only Release build (`1c8a7173130957ffd6c1ce573afe6d3184085421c41367f34146d740e781af2f`) captured a concrete fit/pinning defect:

- [Loaded capture](../../.logs/viewer-mcp/20261013T145636Z-profile-687424c4.json), 120 warmup + 600 measured frames, same saved Brianconnais view and 3440×1369 viewport. Thirty ropes / 270 points, 101,768 shell triangles, no readback drops.
- Chains 0, 1, 2, and 29, node 1, had authored rest distances 61.65–66.27 mm from the pivot, inside the user's 70 mm fully pinned region. Their simulated positions equaled those rest positions exactly.
- Their nearest head triangles reported signed separations of -21.34, -22.33, -23.45, and -15.62 mm. These points cannot escape because pinned nodes deliberately skip collision. Neighboring free links then fold around anchors inside the skull.
- The closest faces were `HeadHD` face 0. This establishes embedded anchors, but does not prove that the face is internal mouth geometry. The separately attached gums/teeth object does not match the body/head/hands/feet collector.
- [Loaded screenshot](../../.logs/viewer-mcp/20261013T145709Z-hair-head-neutral-loaded-a303ba64.png).
- The earlier [post-login capture](../../.logs/viewer-mcp/20261013T145524Z-profile-11a3941f.json) had no hair or collision shell yet; attachment requests were delayed. It is not a physics measurement.

## Outer-head fit correction

After sampling the neutral hair, fitting skins eligible head triangles from the already-authorized own-avatar collision attachments into the same neutral head frame. A majority of every triangle vertex's weights must descend from `mHead`, and geometry must be near the head. Radial intersections at each rope height retain the outermost surface, independent of triangle winding, and provide 10 mm clearance. A nearer internal mouth surface cannot replace an outer hit. Rest positions and initial simulated positions are corrected together before pinning.

Work occurs only on fitting/refitting, with caps of 200,000 sampled vertices, 200,000 visited triangles, and 1,000,000 ray/triangle tests. An incomplete fit discards all partial clearance changes and reports the limit in diagnostics. Existing point/ray collision budgets are unchanged. Collision attachment/geometry/visibility changes invalidate the fit so a head arriving after the hair receives the same correction.

Limits: this remains polar guide fitting for loose hair. The head silhouette also includes eligible visible head details; there is no general texture-alpha or mouth-face classifier. Extremely complex heads that exceed the fitting cap retain the previous approximate fit and expose `guide_head_fit_limited` in captures.

## Baseline

- Release executable SHA256: `8ee821aae7c0a0706b93df54a0e665db3ab670029db3149c1df8438f38f794ae`.
- Scene: Brianconnais, user-controlled avatar and camera, Legacy Perky 1.7.1 and LeLutka Avalon 4.0. Animated mesh and guide overlay enabled; purple mesh overlay disabled. No camera or graphics changes for capture.
- Two initial captures aborted after user slider changes. A subsequent unchanged-settings capture completed: 120 warmup + 600 measured frames. This is a diagnostic smoke capture, not a performance comparison.
- [Raw baseline](../../.logs/viewer-mcp/20261013T144937Z-profile-5d45a080.json). Largest recorded point step: 12.160 mm. 55 peak-motion rows selected the head mesh, all its face 0; this does not identify interior mouth geometry by itself.
- [Camera saved before restart](../../.logs/viewer-mcp/20261013T145102Z-hair-head-before-neutral-98492891.camera.json), viewport 3440×1369.

## Checks

- Shared neutral sampler / shoe-height regression passes, including 30 animated poses, body-shape offsets, joint overrides, and no mutation of the live skeleton.
- Hair binding GPU regression passes: fixed guide deformation is unchanged by animated torso palettes; existing elastic recovery checks pass.
- Production outer-head fitting regression passes for 4/30/64 ropes, nested mouth geometry, both winding orders, surface enumeration order, untouched lower heights, degenerate triangles, and the hard work budget.
- Existing attachment-selection regression passes.
- Final Release build passes: executable SHA256 `1e8984f0b7526d973a1d3589e76ceaa7fdb83c384255edcf7bd516e05012c583`, [build log](../../.logs/hair-head-clearance-build.log).

## Live result

- Same Brianconnais scene, 3440×1369 viewport. Original saved camera restored after restart, then released to the user; the user moved the avatar/view during validation, so these are diagnostic smoke captures, not matched performance benchmarks.
- [Capture 1](../../.logs/viewer-mcp/20261013T150614Z-profile-79c39ec1.json): 600 warmup + 600 measured frames. Maximum measured point step 9.867 mm; all measured trace rows have valid mesh/rope history and no refit.
- [Capture 2](../../.logs/viewer-mcp/20261013T150727Z-profile-d85e8aa2.json): 120 warmup + 600 measured frames. Maximum measured point step 9.333 mm; again no measured history reset/refit. Neither capture dropped a readback.
- Frame interval median/max: 18.995/23.743 ms and 18.982/25.364 ms. Guide GPU scope median/max: 1.092/1.631 ms and 1.147/1.948 ms. Guide CPU scope median/max: 4.720/6.578 ms and 4.562/6.184 ms. Scopes are inclusive and not summed; capture diagnostics are active and these figures are not an optimization comparison.
- Thirty-one of 270 initial guide points needed head clearance; the fit used 35,160 ray/triangle tests and did not reach any work limit. Shell remains 101,768 triangles / 296 parts. No per-frame shader collision changes were made.
- Chains 0/1/2/29 node 1 now sample positive nearest-head clearances 8.88/16.98/12.11/19.13 mm, compared with -21.34/-22.33/-23.45/-15.62 mm before the correction. Their neighboring points also remain outside in the snapshot.
- [Visual check](../../.logs/viewer-mcp/20261013T150635Z-hair-head-clearance-9c7d5ab3.png). The user explicitly confirms the ropes that were trapped inside the head look resolved.
- Settings preserved: physics, guides, animated mesh and gravity on; 30 ropes; root radius .07 m, gradient .2 m; stiffness 6, retention 1, bend 1.9, bend gradient 0, elasticity 0, travel limit 0; damping 16, friction .35, gravity 1.25; collision scale 1.5, smoothing .15, mesh padding 0; amount 30, response 0, regional variation 1, tip lag .3. Guide overlay on; mesh/simple-collider overlays off. No sliders were changed by this work.

The data confirms a bad initial fit combined with collision-exempt pinned points. It does not prove internal mouth geometry was the original trigger. Broader head/outfit and unusual hairstyle coverage remains untested; the explicit fitting caps and polar topology limits above still apply.
