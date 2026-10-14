# Experimental hair collision - 2026-10-12

Status: in progress, uncommitted. Release build and automated/live smoke checks
passed; movement and fit on the user's hairstyle remain for visual tuning.

## Implementation

Graphics > Hair > Basic hair physics adds **Enable avatar collision
(experimental)** below Tip lag. The saved boolean `BoxxyHairPhysicsCollision`
defaults to false, participates in Graphics defaults, and is exposed through MCP.
It requires the existing hair physics and name/distance/self selection controls.

Five existing skeletal collision volumes (HEAD, NECK, CHEST, L_CLAVICLE,
R_CLAVICLE) supply animated ellipsoids. Their matrices are converted into
head-local coordinates after removing the crown's world position. Missing or
degenerate volumes are skipped. No geometry readback, triangle collision mesh,
new simulation or dependency was added.

The shared vertex helper tests the segment from the original animated vertex to
its proposed swayed position. The earliest ellipsoid entry limits that added
movement. A vertex already inside a proxy can move outward or tangentially, but
cannot move farther inward; it is not pushed out of its authored fit. Pinned
roots and rest poses remain unchanged. The current and previous collider poses
travel with the existing hair deformation history for colour, depth, shadow,
TAA and SSGI paths. Disabling the checkbox bypasses collider construction and
shader contact tests; existing sway remains.

This is approximate collision that limits sway, with no friction or persistent
contact response. It does not repair baseline clipping, exactly match custom
mesh bodies/clothing, collide individual hair cards with each other, or guarantee
that triangle interiors do not intersect. Contact can visibly reduce movement.

## Build and automated checks

- Command: `cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2`.
- Executable: `E:\BoxxyViewer\build-vc170-64\newview\Release\secondlife-bin.exe`.
- Version: Prism Release 0.9.0.54538.
- SHA-256: `7158bc509ef5fe8f73b5d0a57b97e68516bdafa4c1e1dc2d2896270d3b7fba7f`.
- `test_hair_collision.py`: 180 extracted production transform cases covering
  rotated/scaled joints and scene altitudes, plus missing/degenerate joints,
  missing avatars and disabled lookup bypass.
- `test_hair_deform_gpu.py`: 592 checks, including entry contacts, complete
  crossings, tangencies, zero movement, authored overlap, outward movement,
  rotated/nonuniform colliders, all five slots, root pinning and rigged/unrigged
  parity. All production colour/glow/shadow vertex variants link.
- `test_taa_gpu.py`: 107 checks, including collision-enabled D24 equality and
  previous collider pose/checkbox changes in temporal depth.
- Spring/config checks, 1,124 hair GPU/config checks and 2,180 shared overlay GPU
  checks passed. No duplicate saved-setting keys; checkbox within the scroll
  content bounds; staged Release settings/UI/shader resources match source.
- `git diff --check` passed.

## Live rendering smoke session

MCP launch and remembered login succeeded. Saved the original camera before
temporarily enabling collision. No camera writes were made; start/end camera
metadata match. `viewer_restore` acknowledged restoration afterward. A subsequent
settings read showed collision enabled and a different root radius, consistent
with interactive tuning during the session; these current values were left
intact rather than overwritten. Viewer left running.

- Scene: Brianconnais interior, long-haired avatar viewed from behind. Original
  [camera](../../.logs/viewer-mcp/20261012T091511Z-before-hair-collision-4010163d.camera.json)
  at global (289292.88845, 278767.69565, 1367.87524), FOV 60 degrees, unlocked.
- Viewport 3440 x 1369; render target 3440 x 1316; RTX 5090 / NVIDIA 617.14.
- Hair and physics enabled, self-only, range 10 m. Sway 11.1 degrees, response
  5.1, stiffness 1, root radius 0.06 m, gradient 0.17 m, regional variation 1,
  tip lag 0.35. Collision was the only temporary setting change.
- TAA selected; GTAO on; SSGI off; shadow detail 0; VSync off; YieldTime -1;
  BackgroundYieldTime 0.
- One run: 120 warmup frames, 60 measured frames. GPU frame median/p95
  7.355/8.355 ms; CPU frame median/p95 7.894/8.395 ms; frame interval median/p95
  7.910/8.350 ms. CPU/GPU scopes are inclusive and were not summed.
- [Raw capture](../../.logs/viewer-mcp/20261012T091528Z-profile-c0c89a66.json),
  [collision-enabled screenshot](../../.logs/viewer-mcp/20261012T091550Z-hair-collision-enabled-af874a1e.png),
  [screenshot metadata](../../.logs/viewer-mcp/20261012T091550Z-hair-collision-enabled-af874a1e.json).
  Hair and scene render without obvious geometry breakup in the screenshot.

This is an integration smoke test, not a performance comparison. No repeated,
paired on/off measurements were collected, so no collision cost claim is made.
Live shadows were disabled and are covered by GPU shader-path checks instead.
The snapshot does not establish contact quality during quick turns or every pose.


## Collision fitting controls

Added Show collision shapes (default off) and Collision size (0.50x-1.50x,
default 1.00x). The size multiplies each ellipsoid's three radii around its own
animated centre. One shared shape builder supplies both the collision matrices
and the cyan wire overlay, so the displayed boundaries reflect actual collision.
The overlay can be enabled while collision is off, but follows hair physics,
name matching, self-only and distance selection. It draws each selected avatar
once, through the avatar without writing depth; HUD, shadow, impostor and probe
passes exclude it. The visual fitting aid is not a new collision simulation.

Automated fitting checks: 900 production transforms across size bounds/clamping,
rotations, nonuniform joints and scene altitudes; overlay/shader surface parity,
missing/degenerate joints and disabled collision bypass. Spring/config and 1,124
hair GPU/config checks passed. Both controls persist, reset with Hair defaults
and have MCP bounds. XML keys, scroll bounds and staged Release resources passed.
Release build succeeded with executable SHA-256
`2c2d11eeddb902c8afd282e44cb23a3063656339a8de47f03eccb16c2425d6a2`.
The user confirmed the fitting controls work, while noting unattractive local
deformations where vertices hit the proxy volumes; collision is being retained
as an experiment with that limitation.

Fitting smoke session: saved the [original camera](../../.logs/viewer-mcp/20261012T093432Z-before-collision-fit-overlay-d4c6b3a6.camera.json),
then temporarily requested overlay on, collision off and scale 0.75. The
[0.75 screenshot](../../.logs/viewer-mcp/20261012T093432Z-hair-collision-fit-075-51013864.png)
shows cyan outlines. Requested scale 1.25 next; the
[later screenshot](../../.logs/viewer-mcp/20261012T093655Z-hair-collision-fit-125-d0174a6d.png)
has the overlay off. A subsequent settings read showed overlay off and collision
on, so it does not establish a visual size comparison. The camera also changed
interactively; automation made no camera writes. Viewport remained 3440 x 1369,
render target 3440 x 1316, Brianconnais interior, RTX 5090 / NVIDIA 617.14.

One [capture](../../.logs/viewer-mcp/20261012T093655Z-profile-98d1bfe1.json),
120 warmup / 60 measured frames: GPU frame median/p95 7.885/8.640 ms,
CPU frame 8.714/10.289 ms, frame interval 8.697/10.042 ms. Inclusive scopes
were not summed; this is an integration smoke test without an overhead claim.
Other Hair settings matched the prior session except root radius 0.09 m.
The task was interrupted before restoration; the later restore call reported
the bridge unavailable. Automation overrides are unsaved and clear on exit.
