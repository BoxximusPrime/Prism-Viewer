# Animated hair collision shell — 2026-10-12

Status: implementation validated; uncommitted. Release build, automated tests, live shell preview and paired captures passed.

## Implementation

Replaces the SDF option and its volume/raymarch preview with direct triangle
collision against the local avatar's selected mesh body/head. Basic collision
and its cyan outlines remain available. Mesh mode takes priority when a shell
is available; the basic checkbox controls fallback.

The shell uses the same LLVolume positions, bind-shape transform, normalized
skin weights and final cached bone palette as attached mesh rendering. This
includes fitted shape, body physics, Bento facial animation and rigged fingers.
Second Life's mesh attachments express these shape/animation changes through
skinning; the shell does not read back rendered pixels or run another animation
controller. Legacy system-avatar morph meshes are outside this selected-mesh path.

CPU preparation caches triangles, their GPU joint indices, a spatially partitioned
binary tree, and bottom-up refit levels. Geometry arrival/replacement, LOD, skin
hash, selection and face opacity changes invalidate the cache. Shape/physics
updates use the latest palette directly. Invalidating at every updateVisualParams
would also rebake during ordinary avatar jiggle, so that hook is deliberately absent.

Each frame has one GPU skinning dispatch plus a refit dispatch for each tree
level, without grid cells, distance-volume generation or CPU readback. Current
and previous shells retain the matching coordinates for TAA. The skinning,
refit and query paths retain full selected-mesh detail, including fingers.
Allocation checks bound memory and respect the hardware's buffer limits.

Hair queries nearby triangles using the BVH. They combine swept hair movement
with nearest-surface pushout within 4 cm, allowing a collider to push stationary hair.
Interpolated mesh normals and a small soft contact margin reduce abrupt contact.
The root gradient scales corrections, and the pinned region is unchanged.
The preview draws the actual skinned shell in purple through the avatar; it
preserves screen alpha/glow and can run with mesh collision disabled.

## Limits

- Contact remains vertex-based shader deformation, not a persistent strand solver
  or hair-to-hair collision. Hair-card intersections and some striping can remain.
- Shell motion is sampled per pose. Hair movement is swept against that pose;
  a very fast finger crossing between poses can still be missed. Deep existing overlap beyond the 4 cm recovery band is not repaired.
- The nearest surface normal approximates inside/outside. Open seams, internal
  or overlapping body layers can produce ambiguous contacts.
- Fully transparent faces are excluded. Texture alpha cutouts do not cut holes
  in the collision geometry. Body/head/hand inclusion follows the SSS selection.
- The first cache build can cause a brief pause. Large pose/shape changes refit
  conservatively but may make the original tree partition less efficient.
- Basic proxy size affects basic shapes only. Roots, regional variation, gravity,
  tip lag and shape retention remain independent motion controls.

## Automated validation

- 124 GPU checks: production skinning and nonuniform shape scaling, normal
  transforms, every leaf bound and parent refit, thin-surface crossings,
  tangential motion, stationary hair pushed by a moving shell, rotated local
  coordinates, degenerate triangles, pinned roots and previous-pose sampling.
- Production tree self-check: triangle coverage/permutation, leaf capacity,
  escape links, bottom-up dependencies and conservative deformed bounds.
- 2,175 existing hair deformation GPU checks, including color/depth/shadow paths.
- 900 collider transform checks and basic fallback/exclusion checks.
- Spring, gravity, shape retention, motion-driver and UI persistence/reset checks.
- 119 TAA GPU checks.

## Build and live captures

Build command: `cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2`.
Executable: [Release viewer](../../build-vc170-64/newview/Release/secondlife-bin.exe).

The sandboxed MSBuild workers stalled before compilation; rerun outside the
sandbox. One numeric-conversion warning in the new file was corrected.
No existing class layout was changed.

Original camera: [saved pose](../../.logs/viewer-mcp/20261012T135118Z-before-mesh-shell-35932ab7.camera.json).
Initial basic-only capture (old executable, context only):
[raw data](../../.logs/viewer-mcp/20261012T135227Z-profile-13611004.json).
Initial screenshot: [basic](../../.logs/viewer-mcp/20261012T140700Z-mesh-shell-before-basic-dee30f3a.png).

Release SHA-256: `294fa496a6b0bb837f65aec9a0735ca796937350fd614c80493dde72ed3d0b77`.
Build log: [final Release build](../../.logs/hair-mesh-build-final.log).
The last shader changes were staged and reloaded through MCP. Runtime source
version: `6d1c44ca-5d67-c53b-ee1f-bdfb021d8efb`. All 264 shader programs loaded.
Staged settings, Hair UI and shaders match the checkout.

### Paired captures

Scene: Brianconnais interior, local avatar wearing mesh body/head and long hair.
[Close camera](../../.logs/viewer-mcp/20261012T142444Z-mesh-shell-close-final-164b7d80.camera.json)
locked for every comparison. RTX 5090, driver 617.14, viewport 3440×1369,
render target 3440×1316. VSync off; TAA, GTAO, SSS and hair transmission enabled;
shadows and SSGI off. Existing hair controls retained (tip sway 15, response 1,
stiffness 10, root radius 0.13 m, gradient 0.05 m, regional variation 1, tip lag 0,
shape retention 0.5, gravity strength 0.9, contact smoothing 0.055 m).
Basic collision enabled at size 1.5. Only mesh collision changed; both previews
were off. Each run used 240 warmup frames and 180 measured frames. Pair ordering
was basic/mesh, mesh/basic, basic/mesh.

| Run | Mode | GPU frame median (ms) | GPU frame p95 (ms) | Shell update median (ms) | Raw data |
| --- | --- | ---: | ---: | ---: | --- |
| 1 | basic | 7.340 | 8.412 | 0.000 | [capture](../../.logs/viewer-mcp/20261012T143007Z-profile-0c3f9537.json) |
| 2 | mesh | 8.726 | 9.305 | 0.116 | [capture](../../.logs/viewer-mcp/20261012T143015Z-profile-9d429f94.json) |
| 3 | mesh | 8.738 | 9.610 | 0.115 | [capture](../../.logs/viewer-mcp/20261012T143022Z-profile-94995d8a.json) |
| 4 | basic | 7.623 | 8.505 | 0.000 | [capture](../../.logs/viewer-mcp/20261012T143029Z-profile-8caa45e1.json) |
| 5 | basic | 7.578 | 8.626 | 0.000 | [capture](../../.logs/viewer-mcp/20261012T143036Z-profile-a5d2d1d2.json) |
| 6 | mesh | 9.709 | 10.690 | 0.116 | [capture](../../.logs/viewer-mcp/20261012T143044Z-profile-9c225f6b.json) |

Paired GPU-frame median differences: **+1.386, +1.115, +2.131 ms** for mesh mode.
Shell update stayed near **0.116 ms**; main-thread shell submission was about
0.724–0.727 ms, including driver waits. Shell geometry was 308,759 triangles in
302 selected meshes, with 224,301 search-tree nodes. Bake counts were unchanged
through each warmed mesh capture; ordinary animation did not rebuild topology.

These are observed costs in one live scene, not utilization percentages or a
universal speedup. Alpha-pass GPU time includes triangle searches and other hair
rendering; the 0.116 ms update is not the feature's total cost. GPU scopes are
inclusive and are not summed. Avatar/AO motion continued, including changes in
arm pose, and contributed to variation. Earlier SDF timings used a different
capture context, so they are not a controlled cross-build percentage comparison.

### Visual and lifecycle checks

- [Mesh collision on](../../.logs/viewer-mcp/20261012T143152Z-mesh-shell-final-on-e3aaa750.png).
- [Basic collision](../../.logs/viewer-mcp/20261012T143446Z-mesh-shell-final-basic-9df25895.png).
- [Preview with mesh collision off](../../.logs/viewer-mcp/20261012T143309Z-mesh-shell-final-preview-only-39e8399e.png)
  shows the selected body/head and individual fingers through the hair/clothing.
  Hidden body sections remain excluded, and internal head parts are visible in
  the through-avatar overlay. The preview is the actual selected triangle shell.
- [Preview-only capture](../../.logs/viewer-mcp/20261012T143309Z-profile-785164f3.json),
  120 warmup / 60 measured frames: shell active; preview median 0.012 ms.
- [Both options off](../../.logs/viewer-mcp/20261012T143446Z-profile-0eeaf84c.json),
  60 warmup / 30 measured frames: inactive shell, zero meshes/nodes/triangles and
  no mesh-update GPU scope.

The hand-through-hair gesture and interactive avatar shape editing were not
performed in-world while the user was away. Bone-driven shape/finger behavior
was checked against the rendering path and synthetic GPU deformation/contact
cases. This does not claim a full strand simulation or continuous hand CCD.

### Session cleanup

Original camera and all automation-changed settings were restored after the
paired/preview checks; the settings comparison found no differences. A subsequent
optional 2,000-frame run was invalidated when the user resumed tuning graphics
and moving the camera. It was cancelled and contributes no performance claim.
The user's latest response/stiffness/tip-lag/smoothing and camera were preserved.
Mesh collision was left enabled for the ongoing interactive trial; preview off.

Outstanding interactive checks: actual hand-through-hair gestures and extreme
shape edits. These are not claimed as live-tested. The implementation stays
experimental, with basic collision retained as an option/fallback.
