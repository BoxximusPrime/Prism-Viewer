# Hair collision recovery and large gravity bends — 2026-10-12

Status: implemented, uncommitted. Production shader tests and live reload passed;
the final close-up shows smoother cards, with broader motion review still needed.
This is a shader-only update to the existing Release executable; no restart or
C++ rebuild was needed. No new controls or geometry subdivision were added.

## Changes

- The shared cache keeps the nearest non-hand body triangle and the nearest hand
  triangle independently. Previously the nearest overall triangle and the hand
  triangle could be identical, losing the torso/scalp contact under a hand.
- Body recovery searches cached candidates up to 20 cm away instead of 10 cm,
  retaining bounded two-pass corrections. Nearby hand contact takes priority over
  a distant recovery plane, avoiding sideways pushes from remote body surfaces.
- The shared persistent field removes additional inward pull against nearby
  surfaces, while preserving pre-existing overlap and leaving an idle field at
  zero. The existing pinned roots, gradient and 20 cm displacement cap remain.
- Surface clearance increases from 2 mm to 5 mm.
- Collision correction now runs at shared grid nodes, followed by trilinear
  interpolation in the rendering passes. The user confirmed less penetration
  with the earlier per-vertex version but reported severe bunching and stretched
  triangles. Adjacent vertices no longer independently pick different collision
  directions. Transient collision correction stays separate from persistent
  hand pull: its XY components reuse unused cache ZW, and its Z reuses contact W.
  Reset frames still solve collision but never read missing pull history. Hand
  recovery support is 12 cm to cover the 8 cm node spacing. No extra allocation
  or dispatch was added. Existing Contact smoothing controls support softness
  through the already uploaded contact-spread value.
- Large-bend sweeps extend a cached triangle's contact patch by one 8 cm grid cell.
  A gravity bend can otherwise cross between the literal small cached triangles
  and land beyond the recovery radius. Exact crossings still use their triangle;
  the extension only accepts nearby plane crossings moving into the surface.
- Tree bounds encode both body and hand presence. This lets the independent
  searches skip subtrees that cannot contain the needed surface. The existing
  escape index uses its sign for hands and an exactly representable fractional
  half for body presence; traversal takes the integer absolute value. No buffer
  layout, memory allocation or CPU format change is needed.

The common deformation shader serves colour, depth, shadows and current/previous
temporal poses. Basic collision retains its existing implementation.

## Regression evidence

Before the changes, a production GPU probe left a stationary vertex 14 cm inside
the body untouched. Another fixture returned the hand twice instead of independent
body/hand candidates. Both assertions failed before editing the shaders and pass
afterward. A later large-bend fixture crossed a tiny cached surface patch by 70 cm
and ended on the wrong side; its literal ray misses the triangle by 4 cm. That
failed before patch coverage and now stops outside the surface. A parallel ray
farther from the patch remains unaffected.

Passing checks:

- `test_hair_mesh_gpu.py`: 127 skinning/refit, subtree flags, deep recovery,
  surface-patch sweep, tangent/outward motion, rotated coordinates, pins and
  current/previous pose checks.
- `test_hair_contact_gpu.py`: collision continuity along a dense sample strip
  crossing small triangle edges, independent body/hand cache entries, stored inward
  pull recovery, zero stationary drift, brushing, neighbour propagation, recovery
  controls, low frame rates, history and temporal interpolation.
- `test_hair_deform_gpu.py`: 2,175 shared colour/glow/shadow and pinned-root checks.
- `test_taa_gpu.py`: 119 checks, rerun with shared collision correction.
- [Final live shader reload](../../.logs/hair-recovery-final-shader-reload.log):
  266/266 programs. Final shader source version
  `bdbb931c-9ad8-8688-b894-4bd38be3387f`. All three staged shader files match source.

## Live session

The user is now viewing a different long hairstyle while dancing, with another
avatar present in Smart. This is not the earlier close-up brushing benchmark.
RTX 5090 / NVIDIA 617.14, Prism Release 0.9.0.54539, 3440 × 1369 window and
3440 × 1316 performance render resolution. Shader changes were hot-reloaded into
[the Release viewer](../../build-vc170-64/newview/Release/secondlife-bin.exe).

An initial direct capture changed neither graphics settings nor camera. A later
[comparison pose](../../.logs/viewer-mcp/20261012T162406Z-hair-recovery-comparison-dbcb1fca.camera.json)
was saved and briefly locked for the first before/after measurements. The user
requested free camera inspection; the lock was released immediately and remains
released. The mesh preview was briefly enabled for a screenshot, then restored
to off. Other settings were unchanged by the tools; the user is adjusting gravity
and other hair controls directly. Performance captures stopped at the user's
request before the final shared-correction change.

| Capture | Warmup / measured | GPU frame median ms | Frame interval median ms | Shared cache/contact median ms |
| --- | ---: | ---: | ---: | ---: |
| [Original, direct](../../.logs/viewer-mcp/20261012T162334Z-profile-afbe3ce7.json) | 180 / 180 | 22.76 | 30.04 | — |
| [Original, locked](../../.logs/viewer-mcp/20261012T162607Z-profile-8b1a1c8a.json) | 240 / 240 | 22.48 | 29.56 | 3.76 |
| [Initial recovery, locked](../../.logs/viewer-mcp/20261012T162838Z-profile-fb823f59.json) | 240 / 240 | 22.57 | 29.55 | 11.51 |
| [Patch coverage and pruning, free camera, gravity on](../../.logs/viewer-mcp/20261012T163728Z-profile-0ee24284.json) | 120 / 120 | 15.44 | 20.85 | 2.05 |

The intermediate version's independent search increased cache work, motivating
the final body-presence pruning. The final version also adds gravity patch
coverage. Later free-camera captures are smoke tests rather than controlled
performance comparisons. GPU scopes are inclusive and are not summed. Animation
phase, cache bake pose, camera and manually changed settings limit comparisons.
Raw capture files contain settings, scene metadata and executable identity.

The user reported a small improvement from the initial recovery, then identified
gravity driving hair into the back. That led to the additional large-bend test
and patch coverage. The user then confirmed that hair stayed outside the body,
but supplied a close-up of bunched cards and stretched triangles. That led to
shared, interpolated collision correction rather than vertex-local pushout.
Initial matching-camera screenshots:
[before](../../.logs/viewer-mcp/20261012T162407Z-hair-recovery-before-0767bb1f.png),
[initial recovery](../../.logs/viewer-mcp/20261012T162752Z-hair-recovery-after-214148ff.png).
These show different dance phases and do not establish elimination of clipping.

The [final shared-correction close-up](../../.logs/viewer-mcp/20261012T164600Z-hair-shared-collision-final-d099bd29.png)
shows smooth front locks rather than the jagged bunching in the user's supplied
image. Camera, pose and user tuning differ (the final settings read had gravity
enabled at strength 0.2), so this is a visual smoke check, not a strict image
comparison. No performance captures were taken after the user requested
they stop. The viewer remains running, the camera is unlocked, and the temporary
mesh preview is off.

## Remaining limits

Long hair triangles can still cross the body between their vertices. The shared
grid smooths corrections but does not enforce edge or strand lengths. Cached
surface patches approximate nearby geometry and may over-repel at sharp folds
or gaps. Deep recovery is bounded, roots remain pinned, and opposing contacts
can still conflict. There is no per-strand length constraint, hair self-collision
or continuous moving-body sweep. Other hairstyles, bodies and GPUs have not been
validated in this change.

## Follow-up: surface jitter and early hand response

The user reported remaining jitter and hair moving before the hand reached it.
The drag kernel previously retained full strength through 5.5 cm and faded only
at 12 cm. A GPU regression reproduced a 14 mm pull from a hand still 6.5 cm away.
The kernel now fades between 1.5 and 4 cm; near-contact brushing and neighbour
propagation remain covered. Hand swept patches extend only 2 cm instead of 8 cm;
body patches retain their larger coverage for gravity bends.

Transient collision correction now uses its own previous grid value with
exponential damping (40 ms time constant). The difference from the current
solution is capped at 3 mm, limiting penetration lag during abrupt contacts.
History resets solve directly without reading the previous correction. Root
pinning and separate current/previous temporal rendering remain unchanged.

Production GPU checks pass: 127 mesh checks, 2,175 deformation checks, contact
and temporal-field regressions, including no distant-hand impulse, small-surface
noise damping, direct reset and a 3 mm bound on delayed recovery. The neighbour
transfer test now expects a smaller transferred signal after narrowing the
contact zone; interpolation tolerance accounts for RGBA16F readback quantization.
No performance captures, camera locks, setting changes or new controls were used
for this follow-up. The coarse 8 cm field still limits exact contact timing;
these changes reduce early response rather than guaranteeing pixel-exact touch.

Live reload passed 266/266 programs on the existing Release executable, source
version `f4c55c67-f75d-ee5e-e15a-f300f143c444`:
[reload verification](../../.logs/hair-contact-stability-reload.log).
Both staged shader files match source. The camera remains free; live evaluation
of jitter and exact hand timing is still pending. All 119 TAA GPU checks passed.
