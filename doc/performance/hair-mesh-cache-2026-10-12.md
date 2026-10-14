# Hair mesh collision: dense-style performance and brushing — 2026-10-12

Status: implemented and uncommitted. Release build and GPU/CPU regressions passed.
The user confirmed that the formerly slow hairstyle is worn and, after restart,
that the replayed brushing animation pulls the hair more visibly.

## Diagnosis and change

The original mesh path searched a 319,093-triangle avatar shell for every hair
vertex, repeatedly in colour, depth, shadow and temporal passes. The same scene
returned to about 69 FPS with mesh collision disabled. GPU skinning/refit was
only about 0.12 ms; repeated contact searches were the expensive part.

The existing 6,144-point head-local grid now caches nearby animated triangle
indices once per frame. Each node keeps the nearest surface plus an independent
hand/forearm candidate, classified from the mesh's skin weights. A near-first
tree search and subtree hand flags build the cache. Render passes examine a
bounded set of cached triangles instead of walking the full body tree. These
are still the actual skinned mesh triangles; this is not a distance volume.

Brushing had three additional problems: a nearer stationary scalp hid a moving
hand, the narrow contact kernel missed fingers between grid points, and frames
longer than 100 ms cleared the persistent pull. Independent hand contacts, a
12 cm support radius, and history retention up to 500 ms address those cases.
The existing large-pose-jump/missing-frame reset remains. Root falloff is now
applied once to contact motion instead of weakening it twice. Displacement stays
bounded to 20 cm, spreads through neighbouring points, and recovers through the
existing Shape retention and Spring stiffness controls. Basic collision is unchanged.

Each shell now adds 196,624 bytes for the contact field, triangle cache and
metadata (98,304 bytes more than the previous field). Both temporal poses keep
their own cache and displacement field. No GPU readback or new user controls.

## Build and validation

- Canonical executable: [Release viewer](../../build-vc170-64/newview/Release/secondlife-bin.exe).
- Build command: `cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2`.
- Executable SHA-256: `1d66db99333188773de46314d48974f2cd61e5af232dbf6b79966caf5ad5272a`.
- [Build output](../../.logs/hair-cache-build.log); [266/266 shader startup and settings reload](../../.logs/hair-cache-final-shader-startup.log).
- Runtime copies of `hairMeshC`, `hairContactC` and `hairDeformV` match their source files.
- `test_hair_contact_gpu.py`: production cache/coupling/render/TAA shaders; the
  closer stationary scalp regression, 7 FPS brushing, neighbour pull, bounded
  recovery, controls, rigid head-relative translation, pins and independent history.
- `test_hair_mesh_gpu.py`: 124 skinning, hand-weight/subtree flags, fitted scaling,
  refit, swept contact, head rotation, root and temporal checks. Fixture buffers
  explicitly initialize the persistent fields.
- `test_hair_deform_gpu.py`: 2,175 pinned-root and shared colour/glow/shadow checks.
- `test_taa_gpu.py`: 119 checks.
- `test_hair_motion_driver.py`, `test_hair_collision.py` (900 checks), and
  `test_hair_mesh_tree.py`: production spring/gravity/retention driver, basic
  collider transforms and topology/refit regressions.

All listed checks passed. The scalp/hand fixture reproduced zero contact motion
before the fix and passes with the revised shaders. Synthetic geometry verifies
the mechanism; the user's live brushing confirmation verifies this hairstyle.

## Live measurement setup

RTX 5090, NVIDIA 617.14, Prism Release 0.9.0.54539. Smart region, the user's
long black hairstyle and animated mesh body/head: 302 mesh objects, 319,093
triangles, 244,969 tree nodes and 6,144 contact points. Saved
[comparison camera](../../.logs/viewer-mcp/20261012T154014Z-hair-lag-comparison-628947b2.camera.json)
was restored after restart and locked for paired runs: position
`[209640.183746, 268220.491074, 1948.404053]`, 60 degree vertical FOV,
3440 × 1369 window, 3440 × 1316 capture render resolution.

Physics enabled; tip sway 15, response 2.2, stiffness 5.5, root radius 0.09 m,
root gradient 0.14 m, retention 0, smoothing 0, regional variation 1, tip lag 0,
gravity off, both previews off. Basic collision enabled, size 1.5. Mesh collision
is the only setting toggled for paired final captures. TAA, SSS, PCSS and GTAO
enabled, shadow detail 2, draw distance 128 m, VSync enabled. Full settings and
environment metadata are in the raw JSON artifacts. The pre-restart settings
were restored, including small float-range endpoint rounding when needed.

Initial direct capture left the camera/settings untouched; one capture invalidated
by manual settings changes was excluded. The valid original direct capture used
120 warmup/120 measured frames. A second original mesh capture locked the same
camera and used 90/90; original basic collision used 180/120.

The final brushing comparisons use 360 warmup and 360 measured frames each.
Two earlier new-build runs used 240/180 while the animation was being restarted.
A separate run overlapping a standalone GPU test was excluded from conclusions.

## Results

Final paired results are recorded below. GPU scopes are inclusive elapsed times,
not utilization percentages; parent and child scopes must not be summed. FPS is
the reciprocal of the median frame interval, not of GPU frame time.

| Capture | Warmup / measured | Median GPU frame ms | Median frame interval ms | Approx. FPS |
| --- | ---: | ---: | ---: | ---: |
| [Original mesh, direct](../../.logs/viewer-mcp/20261012T153721Z-profile-0de68e1c.json) | 120 / 120 | 181.40 | 181.23 | 5.5 |
| [Original mesh, locked](../../.logs/viewer-mcp/20261012T154235Z-profile-31ce3024.json) | 90 / 90 | 156.62 | 157.32 | 6.4 |
| [Original basic](../../.logs/viewer-mcp/20261012T154014Z-profile-af6ca552.json) | 180 / 120 | 13.50 | 14.42 | 69.4 |
| [Cached mesh, brushing 1](../../.logs/viewer-mcp/20261012T160255Z-profile-25399997.json) | 360 / 360 | 15.49 | 18.83 | 53.1 |
| [Basic, brushing 1](../../.logs/viewer-mcp/20261012T160332Z-profile-0a139eed.json) | 360 / 360 | 13.77 | 18.49 | 54.1 |
| [Cached mesh, brushing 2](../../.logs/viewer-mcp/20261012T160408Z-profile-833cf971.json) | 360 / 360 | 14.12 | 18.82 | 53.1 |
| [Basic, brushing 2](../../.logs/viewer-mcp/20261012T160547Z-profile-ba17dc99.json) | 360 / 360 | 13.42 | 18.27 | 54.7 |

The original direct capture spent 43.03 ms in `Hair.depth_maps`, 38.05 ms in
`SSS.depth_maps`, 15.66 ms in `TAA.motion` and 7.91 ms in `geometry.alpha`.
Its contact-grid median was only 0.0036 ms because slow frames reset the field.
The two final mesh brushing runs spend 5.79 and 1.85 ms in the shared
`Hair.contact_coupling` cache/simulation scope. This varies with pose and the
spatial tree built when mesh collision is enabled. CPU mesh-update submission
remains around 0.8 ms. Whole-frame performance is the comparison that matters.

## Visual checks and limits

The user confirmed "Animation running; hair reacts more." Matching-camera
screenshots show the same hairstyle intact with the gesture active:
[mesh enabled](../../.logs/viewer-mcp/20261012T160157Z-hair-cache-brush-active-15a0bda0.png).
The debug mesh shell still displays the actual animated geometry; the nearby
candidate cache is an approximation of which triangles need testing.

Animation phase and the live scene are not deterministic across runs or restart;
other avatars/streaming and CPU/presentation time may differ. The original basic
run reached 69 FPS, while the later basic runs were about 54–55 FPS. Thus the measured
result is removal of this hairstyle's catastrophic mesh-search slowdown, not a
promise of a particular FPS in all scenes. Screenshots temporarily hide UI and
render at 3440 × 1369; performance captures all use 3440 × 1316.

The 8 cm spatial cache can lose detail at sharp folds, overlapping surfaces or
very fast movement. It selects a nearby hand surface rather than simulating
individual fingers as separate constraints. The 12 cm support can pull hair
slightly before visible contact. Hair outside the finite grid has reduced contact
coverage. This remains spatial coupling without authored strands, strand-length
constraints or hair self-collision. Other hairstyles, bodies and GPUs were not
tested in this change.

After measurement, mesh collision was re-enabled and the camera lock released.
The viewer remains running on the new Release build with the user's restored
settings and brushing animation. No capture remains active.
