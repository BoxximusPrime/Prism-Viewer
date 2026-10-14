# Sideways hair gravity - 2026-10-12

Status: implemented, uncommitted. Updated native driver, GPU tests and Release
build passed. User confirmed the updated behavior works well in the live viewer;
the automated post-build on/off comparison was interrupted before completion.

## Diagnosis and change

The user reported no apparent gravity response while sitting sideways. A fixed
camera on/off comparison in the running viewer showed some displacement, but
the previous implementation combined gravity with normalized movement angles
and multiplied the whole result by Tip sway. Gravity therefore inherited the
15-degree wiggle cap and could not make sideways hair hang down. Disabling
collision for a second gravity-on check still left the limited bend.

Gravity now has separate bounded regional and tip spring states. The existing
shortest-arc quaternion helper supplies the rotation from each representative
hair lever toward world-down. Gravity strength competes with the restoring
spring to choose the target, with up to 90 degrees of sag. Movement remains in
its original 0-15 degree range and is added independently. Zero Tip sway removes
the movement contribution while gravity can remain active. Disabling gravity
settles its contribution back to zero; roots, lag, collision and previous-pose
rendering retain their shared path. No shader interface or header layout change
was needed.

This is still a bounded regional approximation: inverted hair does not receive
an unlimited 180-degree reorientation, large bends can distort some styles, and
proxy collision can restrict the visible sag. Very weak retention takes longer
to settle after a toggle.

## Validation

- Native production driver: sideways gravity exceeds 60 degrees and lowers a
  representative tip by over 0.15 m even with Tip sway zero; resting gravity is
  unchanged when Tip sway becomes 15. Gravity and movement states remain
  separate. Existing strength, shape retention, frame-rate, multi-pass,
  teleport and settling checks remain covered.
- 2,175 GPU root/deformation/contact checks, extending rotation coverage through
  +/-90 and +/-105 degrees and larger regional/tip blends.
- 119 TAA GPU checks, including an 80-degree bend with soft collision and
  matching colour-depth/motion geometry.

## Live captures

Build command: `cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2`.
Executable: [Release viewer](../../build-vc170-64/newview/Release/secondlife-bin.exe).
Old executable SHA-256: `826957f53b9728319487075a1ce31178c1ce56f547abc7a63483eb53b21461e5`.
Updated executable SHA-256: `fb522dea6e1476af2196795d00217f2dcf7413bff5712fbe4a26813404108871`.

Scene: Brianconnais interior, avatar sideways on an orange chair. Viewport
3440 x 1369, render size 3440 x 1316, RTX 5090, driver 617.14. TAA enabled,
GTAO enabled, SSGI disabled, shadows off, VSync off, foreground yield -1,
background yield 0. Physics: Tip sway 15, movement response 2, stiffness 6,
Shape retention 0, gravity strength 3, regional variation 1, tip lag 0.35,
root radius 0.09 m, gradient 0.17 m, collision scale 1.5 and smoothing 0.06 m.
Hair is self-only within 10 m. Collision visualization is off.

The [original camera](../../.logs/viewer-mcp/20261012T101027Z-before-sideways-gravity-debug-3087ff38.camera.json)
was saved before locking it for the old-build comparison. The screenshots show
[gravity on](../../.logs/viewer-mcp/20261012T101027Z-sideways-gravity-on-before-47e671a1.png),
[gravity off](../../.logs/viewer-mcp/20261012T101207Z-sideways-gravity-off-before-76bf6eef.png),
and [gravity on with collision off](../../.logs/viewer-mcp/20261012T101321Z-sideways-gravity-unclipped-before-485c91a4.png).
The last case isolates the gravity cap from the proxy collision response.

| Old-build case | Warmup / measured frames | GPU frame median / p95 (ms) | CPU frame median / p95 (ms) | Frame interval median / p95 (ms) |
| --- | --- | --- | --- | --- |
| Gravity off, collision on | 2000 / 30 | 7.620 / 8.260 | 8.057 / 8.607 | 7.991 / 8.755 |
| Gravity on, collision off | 1500 / 30 | 7.150 / 7.876 | 8.405 / 9.946 | 8.345 / 9.917 |

Raw captures: [gravity off](../../.logs/viewer-mcp/20261012T101148Z-profile-e5b7395a.json),
[gravity on without collision](../../.logs/viewer-mcp/20261012T101321Z-profile-dedadaa1.json).
These single short captures are diagnostic smoke tests with different settings,
not measurements of gravity's isolated cost. CPU and GPU scopes are inclusive
and are not added together.

After rebuilding and remembered login, the sideways pose was visible in the
[updated-build screenshot](../../.logs/viewer-mcp/20261012T102515Z-sideways-gravity-after-pose-check-e197275b.png).
A [fresh camera](../../.logs/viewer-mcp/20261012T102528Z-sideways-gravity-after-original-12c3093a.camera.json)
was saved and locked without changing its pose. A 2000-warmup/30-frame capture
was requested, but no completed result was retained after the interrupted turn;
no new-build timing or automated paired visual result is claimed. The camera
differs from the old-build view, so those screenshots are not a matched pair.
The user's subsequent live feedback was that the update works very well.

`viewer_restore` succeeded after the old-build checks and again after the
interruption, restoring automation settings and releasing the camera. No SDF
implementation or SDF performance measurement is included in this session.
