# Shared hair contact motion — 2026-10-12

Status: implemented, uncommitted; Release build, GPU/CPU checks and live activation smoke passed. Hand-gesture visual review remains pending.

## Change

Animated mesh collision now includes a persistent 16 × 16 × 24 head-local
contact grid. It uses the same current/previous skinned triangle shell to measure
surface motion relative to the head. Tangential friction and outward surface
motion drag the grid; six-neighbour coupling spreads that displacement, and the
existing Shape retention and Spring stiffness controls restore its shape.
Contact smoothing also increases neighbour coupling. Root nodes are pinned and
the renderer reapplies the existing root gradient to the interpolated field.
The original exact mesh vertex contact remains the last pushout step.

The grid updates once per frame on the GPU, with no CPU readback. It adds 6,144
bounded nearest-surface queries and eight cached field fetches per hair vertex,
not another full mesh query for every neighbouring render vertex. Each shell
buffer adds 98,320 bytes including metadata. Current and previous fields share
the shell buffers, so colour, depth, shadows and temporal reprojection receive
matching poses. Preview-only mode does not simulate the grid. Disabling mesh
collision leaves basic collision unchanged. Pauses, large pose jumps, missing
history and geometry rebakes clear the grid.

This is spatial coupling, not a strand constraint solver. Separate nearby cards
can move together; no hair self-collision, authored strand lengths, or continuous
fast-hand collision is added. Nodes use an 8 cm contact support and may start
responding slightly before a visible hair vertex touches a finger. The grid spans
±60 cm horizontally and -1.56 to +0.28 m vertically from the crown, fading at its
edges; hair beyond it retains the original local collision. Extra displacement
is bounded to 20 cm. Multiple hair attachments share the cage and the first
selected attachment's regional bend when sampling contacts.

## Automated checks

- `scripts/tests/test_hair_contact_gpu.py`: production compute and deformation
  shaders; moving triangle drag, motion passed to untouched neighbours after
  contact removal, bounded/finite state, pinned roots, settling, recovery strength,
  30/60 Hz aggregate recovery, rigid avatar translation cancellation, history
  resets, smooth interpolation, out-of-grid fallback and separate TAA history.
- `test_hair_mesh_gpu.py`: 124 shell skinning/refit/contact/temporal checks.
- `test_hair_deform_gpu.py`: 2,175 pinned-root and colour/glow/shadow checks.
- `test_taa_gpu.py`: 119 temporal rendering checks.
- `test_hair_motion.py`, `test_hair_motion_driver.py`, `test_hair_collision.py`:
  CPU spring/driver, persisted controls/reset/automation and 900 collider checks.

All listed checks passed on the local RTX 5090. The GPU tests use synthetic
geometry; they do not establish the visual quality of a particular hairstyle.

## Live smoke test

Saved the user's current camera before restart:
[Smart camera](../../.logs/viewer-mcp/20261012T150936Z-before-contact-coupling-cc7bab34.camera.json).
Hair settings at that point: mesh collision on, basic collision on (fallback),
gravity 1.65, tip sway 15, response 2.3, stiffness 3, shape retention 0.05,
root radius 0.09 m, root gradient 0.30 m, contact smoothing 0, regional variation 1,
tip lag 0, both collider previews off. These settings are the user's tuning.
This work does not attempt to solve the earlier mesh collision performance issue.


Initial Release build succeeded ([log](../../.logs/hair-contact-build.log)), SHA-256
`4e49906dd056f721acc3b059b079d85f98a14e506ea60d7100dbdd01ef597d95`.
All shaders loaded; the added program revealed an outdated progress total (265
programs versus 264 planned). The final build corrects that count to 265.

[Initial live smoke capture](../../.logs/viewer-mcp/20261012T151434Z-profile-be2edc6f.json):
180 warmup / 60 measured frames, RTX 5090 / NVIDIA 617.14, viewport 3440×1369,
render target 3440×1316, Smart region, saved camera restored and released.
The camera remained consistent during this short capture. The selected shell
contained 319,093 triangles in 302 meshes; all 6,144 contact points were active.
Median GPU contact coupling: **1.804 ms**; inclusive mesh update: **1.924 ms**;
whole frame: **12.328 ms**. Median CPU mesh update: **0.763 ms**.
These are integration smoke measurements, not a paired optimization claim or a
measurement of the feature's total incremental cost. Scopes are inclusive and
must not be added. Dynamic avatar animation and scene streaming remain factors.

The user resumed camera/settings changes during checking. The later screenshot
looked at the room floor and is not a hair quality comparison. No live
hand-through-hair gesture is claimed as verified. Hand contact propagation is
covered by the production synthetic GPU test above.

Before the final bookkeeping rebuild the latest user camera was saved separately:
[Latest Smart camera](../../.logs/viewer-mcp/20261012T151605Z-contact-coupling-before-final-build-2f52fe48.camera.json).
Latest tuning: contact smoothing 0.135, gravity strength 0.4, shape retention 0.1,
stiffness 6.5; the other hair physics settings match the earlier list. Preserve
these newer choices when restoring the viewer.


Final Release build succeeded ([log](../../.logs/hair-contact-build-final.log)),
SHA-256 `452f96a87b250e5d0d931b032b7903ea06b903e02f84dc0b34ef2b16a3224160`.
Runtime shader sources match the workspace. `test_shader_progress_log.py` passed
against the final startup excerpt: **265/265 programs, loaded=1**
([log](../../.logs/hair-contact-shader-startup.log)). The latest saved camera was
restored and released; the latest supported graphics values were restored,
normalizing the float representation of roughness 0.119999997 to 0.12 at its
allowed endpoint. No other requested value was skipped.


[Final live smoke](../../.logs/viewer-mcp/20261012T151956Z-profile-0ccdaf42.json):
120 warmup / 30 measured frames on the final executable, same RTX 5090/driver
and viewport. The user's camera and tuning continued to change between checks;
this is not comparable to the earlier 60-frame sample. All 6,144 contact points
were active; median grid GPU scope 1.983 ms, whole-frame GPU 17.170 ms. No
performance improvement is claimed. The [final screenshot](../../.logs/viewer-mcp/20261012T151936Z-hair-contact-coupling-final-6c092166.png)
shows the avatar and hair rendering in a side view without an obvious explosive
deformation; it does not demonstrate a hand contact. No active capture or camera
lock was left behind, and subsequent user camera changes were preserved.
