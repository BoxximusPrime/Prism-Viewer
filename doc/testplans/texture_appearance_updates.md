# Texture priorities and avatar appearance updates

Status: in progress; automated regression checks pass; in-world verification pending.

## Baseline

In `shadows-on-3.tracy`, approximate aggregate averages were 0.563 ms/frame for
texture updates (including 0.466 ms of decode-priority work), 0.658 ms for avatar
idle updates, and 0.075 ms for writing local wearables to the avatar. These parent
and child timings overlap. These are costs, not promised savings.

## Changes

- Texture-priority loops read settings once per texture update, obtain each
  channel's face list/count once, and reuse the face's viewer-object pointer.
  Texture scale, bias, camera boost, spotlight updates, and fetch scheduling retain
  their existing behavior. The existing face-update throttles are retained.
- `LLFace::calcPixelArea` now caches its radius, angle, and visibility result along
  with its pixel area. Previously a cache hit returned true without initializing
  its output arguments. This could supply undefined inputs to large-texture overlap
  calculations and overwrite a cached media-frustum rejection. The first call now
  computes a result even at frame time zero. The bounding-box radius calculation
  also reuses one square root rather than calculating the same length twice.
- Wearable writes index the immutable dictionary's texture slots by wearable
  type once, replacing a search of all texture slots for every wearable each frame.
  When the avatar already has the requested texture ID, the write avoids the
  texture-manager lookup that preceded `setLocalTextureTE`'s existing early return.
- The private self-avatar parameter helper now uses the parameter its callers
  already looked up, avoiding a second lookup of the same ID. It still invokes
  `setWeight` even for identical weights, preserving driven-parameter effects.

Whole appearance updates are deliberately not skipped: cross-wearable driver
propagation, appearance animation, texture changes, and editor writes can require
updates even when one parameter's weight is unchanged.

## Automated verification

```powershell
python scripts/tests/test_texture_appearance_updates.py
```

The script compiles the production wearable-write, parameter-write, and face-area
methods with recording stubs. It checks:

- Repeated appearance writes still propagate parameters while fetching unchanged
  textures only on the initial assignment.
- Fixed slot indexing runs once; unrelated/baked slots are not assigned by valid
  wearables. Changed IDs and removal back to default textures still update.
- Sex-dependent layer updates and invalid/null avatar guards remain functional.
- Cross-wearable propagation runs on both initial and repeated identical weights,
  including layered wearables and a null entry.
- A new face calculates its initial area; cache hits restore both output arguments.
- Media visibility remains false while cached; expiry recomputes it. Cached angles
  include media/near-camera adjustments. Missing rigged bounds remain rejected.

The Release build validates the real viewer types and callers; fixtures do not
replace visual or in-world performance checks.

## In-world checks

1. Log in and verify body shape, skin, eyes, hair, and layered clothing. Change an
   outfit and add/remove a clothing layer; verify texture and driven-parameter updates.
2. Edit shape sliders, clothing colors, and local textures; exercise preview hints,
   cancel/revert, and sex-dependent appearance changes. Watch appearance transitions.
3. Move near and away from large textured surfaces and media faces; turn them out
   of view and back. Check texture resolution, including rigged attachments and
   missing/loading mesh assets. Verify atlas/repeated textures and projector textures.
4. Capture a comparable stationary scene after loading settles. Compare
   `writeWearablesToAvatar`, `updateImageDecodePriority`, `updateImages`, and
   `calcPixelArea`, along with complete frame times. Keep camera, graphics settings,
   and profiler configuration consistent; record any camera movement needed to
   reproduce the earlier transient rendering workload change.

No post-change FPS gain has been measured yet. OIT synchronization remains separate.
