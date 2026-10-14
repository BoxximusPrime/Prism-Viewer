# Hair soft contact and shape retention - 2026-10-12

Status: in progress, uncommitted. Automated checks, Release build and live
visual comparison passed; style/pose-specific tuning remains.

## Problem and implementation

The reported hair-card striping is reproduced in a close screenshot with
collision, gravity strength 3 and enlarged 1.5x collision shapes enabled. The
old contact solver can abruptly switch an already-overlapping vertex between
all of its proposed motion and none of it as its motion becomes slightly inward.
Neighboring vertices can therefore disagree even when their directions differ
only slightly.

Contact smoothing (0-0.15 m, default 0.05 m) uses a smooth positive-part function
to ease the inward movement near each ellipsoid's supporting plane. It retains
tangential sliding and outward recovery. The field is evaluated in metres,
including for rotated/nonuniform ellipsoids. Two projection sweeps reduce
conflicts between overlapping proxies; zero retains the original swept hard
stop for comparison. No mesh adjacency or triangle neighborhood data is needed.
The current and previous smoothing values travel with the existing deformation
history for matching colour, shadow and temporal geometry.

Shape retention (0-1, default 1) scales the regional and tip restoring
frequencies from 20% to 100% of their previous values. One preserves the previous
response; zero keeps a weak return to avoid drift. Lower values permit slower
recovery and more gravity bias. Movement excitation, pinned roots, regional
variation, tip lag and the existing 15-degree maximum remain. Both sliders
persist, reset with Hair defaults and have bounded MCP controls.

Limits: this smooths a spatial contact field rather than averaging connected
mesh vertices. Intersections among layered hair cards, exact body/clothing fit
and conflicting contacts among several overlapping proxies are not solved
exactly. Contact normals approximate the ellipsoid surface and vertex shading
uses the existing bend rotation rather than a full deformation Jacobian.

## Automated checks

- 1,347 GPU deformation checks: regression for the grazing-contact discontinuity,
  continuity across 241 neighboring sample positions, the soft approach zone,
  outward recovery, zero rest displacement, movement bounds, nonuniform proxies,
  root pinning, rigged/unrigged agreement and all colour/glow/shadow paths.
- 115 TAA GPU checks, including current/previous soft-contact settings and D24
  coverage agreement between colour depth and motion rendering.
- 900 native collider transforms plus smoothing bounds and missing/degenerate
  joints; existing shared overlay transform checks remain covered.
- Native motion driver: weaker retention permits more gravity droop and slower
  recovery, clamps invalid values and eventually settles at zero retention.
  Existing gravity, multi-pass, linkset and motion cases passed.
- Spring/config and 1,124 Hair GPU/config checks passed.

## Live session

Built with `cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2`.
The [Release executable](../../build-vc170-64/newview/Release/secondlife-bin.exe)
is Prism Release 0.9.0.54538, SHA-256
`826957f53b9728319487075a1ce31178c1ce56f547abc7a63483eb53b21461e5`.
The shared deformation header triggered a broad rebuild; it completed without
compile failures. XML keys, layout spacing/scroll bounds, staged resources and
diff checks passed.

The old-build [camera](../../.logs/viewer-mcp/20261012T095410Z-before-soft-hair-contact-fbd548e5.camera.json)
was saved before a temporary close view, then restored and released before
closing the old viewer for the build. No old-build settings were changed.
The [old-build close view](../../.logs/viewer-mcp/20261012T095440Z-hair-contact-before-close-e49f507d.png)
reproduced the horizontal bands.

MCP launch/login succeeded after building. Saved the new session's
[original camera](../../.logs/viewer-mcp/20261012T100307Z-before-soft-contact-comparison-eb37f920.camera.json),
then locked the same close view for the following three smoke captures.
Afterward, camera_restore and viewer_restore succeeded. A settings read matched
every pre-test exposed value, including smoothing 0.05 and retention 1; the
camera lock was released. Viewer left running.

- Scene: Brianconnais interior, long hair viewed from behind. Locked camera
  global (289294.67616, 278768.04845, 1367.40210), forward
  (-0.356165, -0.762381, -0.540298), up (-0.228687, -0.489514, 0.841474), FOV 35.
  Start/end camera metadata match for each run.
- Viewport 3440 x 1369; render target 3440 x 1316; RTX 5090 / NVIDIA 617.14.
- Hair/physics on, self-only, range 10 m; sway 11.1 degrees, response 5.1,
  stiffness 1, pinned radius 0.09 m, gradient 0.17 m, regional variation 1,
  tip lag 0.35, gravity on/strength 3, collision on/size 1.5, overlay off.
- TAA selected, GTAO on, SSGI off, shadow detail 0, VSync off, YieldTime -1,
  BackgroundYieldTime 0. Only smoothing and retention were temporarily changed.

| Contact / retention | Warmup / samples | GPU frame median / p95 ms | CPU frame median / p95 ms | Frame interval median / p95 ms | Raw capture |
| --- | --- | --- | --- | --- | --- |
| Hard (0 m) / 1 | 120 / 10 | 7.140 / 8.711 | 7.572 / 9.486 | 7.866 / 9.427 | [JSON](../../.logs/viewer-mcp/20261012T100315Z-profile-e1d30dad.json) |
| Soft (0.05 m) / 1 | 120 / 60 | 6.865 / 7.826 | 7.213 / 8.038 | 7.115 / 8.076 | [JSON](../../.logs/viewer-mcp/20261012T100405Z-profile-57041d95.json) |
| Soft (0.05 m) / 0.35 | 120 / 30 | 6.859 / 7.367 | 7.362 / 8.026 | 7.372 / 7.986 | [JSON](../../.logs/viewer-mcp/20261012T100447Z-profile-d5453dd5.json) |

The [hard-contact image](../../.logs/viewer-mcp/20261012T100315Z-hair-hard-contact-close-89e02d44.png)
shows pronounced bands over the lower hair. The matching-camera
[soft-contact image](../../.logs/viewer-mcp/20261012T100405Z-hair-soft-contact-close-516feea4.png)
has substantially fewer visible bands and a continuous lower-hair silhouette.
The [lower-retention image](../../.logs/viewer-mcp/20261012T100447Z-hair-soft-contact-loose-480b487b.png)
also renders without the pronounced banding. Each PNG has a sibling JSON with
screenshot metadata.

These are short integration/visual smoke checks, not repeated paired performance
benchmarks; sample counts differ and live avatar motion is not frozen. Inclusive
scopes were not summed, and no speedup or overhead claim is made. Still images
do not prove motion quality in every style or pose. Strong gravity may already
reach the Tip sway cap, limiting additional resting droop from lower retention.
