# Basic hair physics experiment - 2026-10-11

Status: in progress, uncommitted. This is a local cosmetic spring experiment,
not a performance optimization or a strand/collision simulation.

## Implementation and controls

Graphics > Hair > Basic hair physics uses the existing root-name matcher,
For me only option and maximum distance. Both hair lighting and hair physics
must be enabled. Physics is off by default.

| Control | Default | Range |
| --- | ---: | ---: |
| Tip sway, degrees | 1.50 | 0-15 |
| Movement response | 1.0 | 0-10 |
| Spring stiffness | 6.0 | 1-12 |
| Pinned roots, metres | 0.15 | 0.03-0.35 |
| Root gradient, metres | 0.30 | 0.01-1.00 |
| Regional variation | 0.60 | 0-1 |
| Tip lag | 0.50 | 0-1 |

The first prototype followed an idle oscillation. After user feedback, this was
replaced with a three-axis inertial spring driven by changes in head linear and
angular velocity: acceleration, braking, vertical steps and head turns. A small
behind/below-crown lever approximates the hanging mass, and pose velocity is
smoothed before differentiating. Exact damped free evolution allows a small
rebound and settles without clock-driven energy. The total rotation is bounded
by the amount slider. Movement response zero stops new impulses.

State updates once per rendered frame on the linkset root; all linked pieces
share the same regional springs and crown pivot. Long pauses, teleports and abrupt pose
snaps reset the spring. Amount zero or disabling the feature restores the
original geometry transform. Meshes and textures are never modified or uploaded.
The root-pinned revision replaces the rigid draw transform with a shared vertex
bend. Vertices inside the root radius retain their original animated position;
smoothstep increases the effect over the root-gradient distance (default 0.30 m), reaching the full
spring motion at the ends. The radius is measured in world metres after skinning
or object scaling, with the palette/object origin removed before GPU upload.
It covers rigged and ordinary hair, materials, alpha, glow and shadows.
TAA/SSGI receive the previous bend as well as the previous skin/object pose. Shadow batching
keeps different hair objects separate. Reflection probes and impostors retain
their original pose.

This produces a continuous bend, rather than simulating individual strands. It
does not detect authored scalp roots or collide with the avatar. The pinned
sphere may need adjustment for short or unusual hairstyles. Picking and culling still use
the original mesh bounds; very large hairstyles and extreme poses need review.

## Build and automated validation

- Canonical target: `build-vc170-64/newview/Release/secondlife-bin.exe`.
- Build command: `cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2`.
- Movement-response revision: Release build succeeded, viewer 0.9.0.54538,
  executable SHA-256 `1c98d2cf2d2f0ca99d789814b295f9eaf4670374e6a8a9ad79a85aa6e9f199d0`.
- The first compile found const-pointer and matrix-operator API mismatches.
  These were fixed; all 706 target objects/PCH files were discarded before the
  clean retry because the volume class layout changed.
- `test_hair_motion.py`: production spring frame-rate independence, slow-frame
  stability, bounded repeated impulses, no idle motion, opposite start/stop
  response, rebound/settling, clamps and persisted UI defaults; passed.
- `test_hair_motion_driver.py`: extracts the actual avatar driver and supplies
  deterministic poses/time. Passed stationary, acceleration, steady travel,
  braking, yaw turns, vertical steps, linkset sharing, repeated render passes,
  teleport/pause reset and feature/range exclusions. Math wrappers model the
  viewer's quaternion order; this is not an in-world avatar animation test.
- `test_shadow_batching.py`, `test_shadow_mask_batching.py`: existing batching
  checks plus separate moving-hair identities.
- `test_hair_selection.py`: name boundaries, cache invalidation, ownership,
  HUD/dead-object exclusions and camera range.
- `test_hair_gpu.py`: 1,088 checks passed on NVIDIA GeForce RTX 5090, rerun after
  renaming the response control and updating its bounds.
- `test_taa_gpu.py`: 93 checks passed.
- `test_avatar_render_precision.py`: 1,300 existing transform/cache cases passed.
  The extractor now explicitly selects the original model-matrix overload.

The selection, shadow batching, TAA and precision checks passed for the first
prototype; their rendering integration did not change in the movement revision.

Root-pinned revision validation:

- `test_hair_deform_gpu.py`: 172 checks passed, including fixed roots, smooth
  increasing end displacement, nonuniform object transforms, matching rigged
  and unrigged bends, disabled pass-through and all affected vertex paths.
- `test_taa_gpu.py`: 97 checks passed, including enabled hair deformation with
  D24-equal visible/motion geometry and different previous/current bends.
- `test_hair_gpu.py`: 1,124 shader/config checks passed.
- `test_sss_overlay_gpu.py`: 2,180 checks plus all six production vertex variants
  passed; overlay paths share the changed alpha vertex programs.
- Spring, production avatar driver and 1,300 transform/cache checks rerun and
  passed. No dependencies added.
- Release rebuild and live smoke passed (details below).

## Live smoke tests

The sessions used prism-viewer MCP launch and remembered login, in Brianconnais
at 3440 x 1369 viewport / 3440 x 1316 render resolution, NVIDIA RTX 5090.
Every capture used 120 warmup frames and 60 measured frames. GPU scopes are
inclusive and are not summed. These short runs establish integration only.

### First prototype

Executable SHA-256:
`98cb4047a346ed5d3fb2742a38c30b74f3d33d04708c36125b5a060519681f1e`.
Camera saved in [original pose](../../.logs/viewer-mcp/20261011T232252Z-hair-physics-original-25cfca30.camera.json),
then replayed/locked for captures. Hair enabled, initial self-only true, range
10 yards, physics initially disabled, amount 0.5, idle speed 1, stiffness 6.
TAA, GTAO and SSS enabled; SSGI and VSync disabled; BackgroundYieldTime 0.

| Capture | Temporary settings | Frame interval median ms | GPU frame median ms |
| --- | --- | ---: | ---: |
| [Enabled](../../.logs/viewer-mcp/20261011T232315Z-profile-f19a9238.json) | Physics on, shadows off | 6.980 | 5.992 |
| [Maximum](../../.logs/viewer-mcp/20261011T232347Z-profile-d5dd9943.json) | All avatars, amount 3, speed 1.5, stiffness 8 | 6.598 | 5.933 |
| [Shadows](../../.logs/viewer-mcp/20261011T232442Z-profile-ae759f39.json) | Same, shadow detail 2 | 8.468 | 8.129 |

[Before image](../../.logs/viewer-mcp/20261011T232255Z-hair-physics-before-e7bf34e7.png)
and [maximum image](../../.logs/viewer-mcp/20261011T232347Z-hair-physics-sway-max-05881f9d.png)
show no obvious geometry corruption. No Hair.depth_maps scope was active, so
these captures did not establish hair path coverage or visible spring motion.
Automation overrides and the original camera were restored, then unlocked.
Physics was enabled at the end while the user was trying the prototype; their
enable choice was retained. The user reported that it worked but felt like a
pendulum, prompting the movement-response revision.

### Movement-response revision

The rebuilt viewer launched/logged in successfully. A direct capture used the
current unlocked camera and graphics settings without any mutations.
Camera global position was (289292.839379, 278768.994232, 1367.876709), forward
(-0.320729, -0.918315, -0.232016), up (-0.076502, -0.219041, 0.972712), FOV 60.
Start and end camera poses matched. Saved settings were physics enabled,
maximum sway 3 degrees, response 1, stiffness 12, self-only true, range 10 yards;
shadows off, TAA/GTAO/SSS on, SSGI/VSync off, BackgroundYieldTime 0.

- [Raw capture](../../.logs/viewer-mcp/20261011T233544Z-profile-fb51f963.json):
  median frame interval 7.082 ms, GPU frame 6.581 ms, Hair.depth_maps 0.444 ms
  with coverage on all 60 frames.
- [Screenshot](../../.logs/viewer-mcp/20261011T233549Z-hair-physics-movement-response-bf2f499d.png)
  and [metadata](../../.logs/viewer-mcp/20261011T233549Z-hair-physics-movement-response-bf2f499d.json):
  scene and hairstyle render without obvious corruption.
- No settings or camera changes required restoration in this session. The
  viewer remains running for the user to try walking, braking and turning.

The later camera/settings and hair coverage differ from the first session;
timings are not a before/after performance comparison. The screenshot cannot
establish motion quality, and automated live avatar movement was not available.
Starts/stops/turns are covered by deterministic production-driver tests;
in-world feel remains for user review. Collision and per-strand bending remain
outside this experiment.

### Root-pinned revision

Release build succeeded without a compile retry. Executable SHA-256:
`3cc37342d195c53c060d2f3f35ccb9b02df19ff89df74ac316daa60c095a29d7`.
Launch and remembered login succeeded with the staged vertex helper. The current
view was captured directly, with no camera/settings writes. Saved controls were
physics enabled, tip sway 6 degrees, response 3, stiffness 1, root radius 0.15 m,
self-only true, range 10 yards. Shadows off, TAA/GTAO/SSS on, SSGI/VSync off,
BackgroundYieldTime 0. Viewport/render resolution stayed as listed above.

- [Raw capture](../../.logs/viewer-mcp/20261011T234937Z-profile-a7f3b97d.json):
  120 warmup / 60 measured frames; median frame interval 8.814 ms, GPU frame
  7.583 ms, Hair.depth_maps 0.171 ms with coverage in all 60 frames.
- The unlocked camera moved during capture. Its start position was
  (289290.179717, 278764.348877, 1367.153198), forward
  (-0.402825, 0.786313, -0.468449); the end position was
  (289288.650412, 278765.141281, 1366.871460), forward
  (0.885407, 0.149040, -0.440275), FOV 60. Exact poses/up vectors are in the raw
  artifact. This is a render smoke check, not a controlled timing comparison.
- [Screenshot](../../.logs/viewer-mcp/20261011T234937Z-hair-physics-pinned-roots-215a0929.png)
  and [metadata](../../.logs/viewer-mcp/20261011T234937Z-hair-physics-pinned-roots-215a0929.json):
  hair/scene render without obvious corruption. A still image cannot establish
  motion quality or root fit; those remain hairstyle-specific user review.
- No temporary changes needed restoration. Viewer left running with the user's
  controls intact. GPU tests establish root invariance and stronger end motion;
  per-strand topology and avatar collision were not added.

### Expanded response and root-gradient controls

Movement response now reaches 10 in the UI, saved settings, automation range
and spring input clamp. Pinned-root radius now starts at 0.03 m. The new root
gradient controls the distance beyond the pinned radius over which motion fades
from zero to full sway: 0.01-1.00 m, default 0.30 m to preserve existing motion.
Small gradients free the lengths sooner; larger gradients spread the transition.
The previous gradient is retained with the previous bend for temporal motion.

- Spring/config checks passed, including stronger response at 10 than 3,
  saturation, stability and all slider/default/reset bindings.
- 448 pinned-root GPU checks passed across the gradient endpoints and default,
  the smaller root-radius minimum, nonuniform transforms and rigged/unrigged paths.
- 97 TAA and 1,124 hair shader/config checks passed.
- Release build, launch and remembered login passed. Executable SHA-256:
  `64071e2e16e5837709ef7c087a053fdb67c95e5a522da74a6812a1dfbf4aeaef`.
  The running viewer reports the new control and all expanded write ranges.
- [Raw capture](../../.logs/viewer-mcp/20261012T000457Z-profile-bb7d3cf8.json):
  120 warmup / 60 measured frames; median frame interval 6.514 ms, GPU frame
  6.131 ms. No Hair.depth_maps scope was active, so this is general rendering
  smoke evidence; gradient endpoints are verified by GPU tests above.
- Current Brianconnais camera was unchanged, unlocked at global position
  (289290.418284, 278763.033340, 1367.875488), forward
  (0.419503, 0.877602, -0.232017), up (0.100062, 0.209330, 0.972712), FOV 60.
  Viewport 3440 x 1369, render 3440 x 1316, NVIDIA RTX 5090. Physics enabled,
  tip sway 6, response 3, stiffness 3, root radius 0.05 m, gradient 0.30 m,
  self-only true, range 10 yards. Shadows off, TAA/GTAO/SSS on, SSGI/VSync off,
  BackgroundYieldTime 0. No camera or settings writes were made.
- [Screenshot](../../.logs/viewer-mcp/20261012T000457Z-hair-root-gradient-7ae52118.png)
  and [metadata](../../.logs/viewer-mcp/20261012T000457Z-hair-root-gradient-7ae52118.json)
  show the scene rendering normally. Capture occurred October 11 local time
  (October 12 UTC); camera/style differ from earlier sessions, so timings are
  not an optimization comparison. No temporary changes required restoration;
  viewer left running with saved choices intact. In-world tuning remains for
  the user's hairstyle; collision is still outside this experiment.

### Tip sway testing range

Tip sway now reaches 15 degrees in the UI, saved-setting description, runtime
clamp and automation range. Existing saved values and the 1.5-degree default
are retained. Spring/config and production-driver checks passed, including
15-degree output and clamping values above 15. The 448 pinned-root GPU checks
also passed at positive/negative 15 degrees. Release build and remembered login
passed; executable SHA-256:
`c66c90335238b05216634fcef0b64d220c64ccef74b1d1531e2077219393cbad`.
The running viewer reports the 0-15 range. No camera/settings changes or new
timing captures were needed for this bound-only change. In-world appearance at
the larger sway limit remains for user testing; stretching/clipping may be more
noticeable at 15 degrees.

At that stage the hair still used one spring with a radial root mask. Independent dynamics
were discussed as a possible follow-up: overlapping front,
back and side zones with different spring response/recovery would add regional
lag without needing authored strand data. Longer-term options are separate
mid-length/tip springs or grouping disconnected mesh pieces where suitable.

### Four regions and delayed tips

Implemented four overlapping head-local regions (front, back, left, right), each
with independent movement input and spring recovery. The front recovers faster;
the back is softer, and the sides have slightly different responses. Regional
variation blends these with the shared reference spring: 0 gives coherent motion,
1 gives the full regional difference, and the default is 0.60. A second spring
follows each region for delayed tip motion, fading in with distance beyond the
roots; Tip lag ranges from 0 to 1, default 0.50. Both sliders participate in saved
settings, Graphics defaults and MCP. The existing 15-degree sway limit remains.

Vertices inside the root sphere remain exactly pinned. Overlapping regional
weights and normalized quaternion blends keep the transition smooth and preserve
distance from the crown. Previous-frame regional poses, root controls and tip lag
are retained for temporal motion. Linked pieces share the root's motion state;
state and pose history are allocated only for hair that needs them. Teleports,
long pauses and abrupt head pose snaps reset both spring layers.

Validation:

- Release build passed with the canonical command and executable above, version
  0.9.0.54538, SHA-256
  `78e2406f3ef0de304e539ed66013cc062a1f0be67dc2bba2a94bec4cbca9ba0f`.
- Native spring/config and extracted production driver tests passed: regional
  differences, zero-variation agreement, delayed tip peak and settling,
  linked-piece agreement, multi-pass stability, movement directions and resets.
- 544 GPU deformation checks passed, including root pinning, gradual bend,
  regional weights, tip-lag endpoints, nonuniform/rotated models, crown-distance
  preservation, rigged/unrigged agreement and all colour/glow/shadow vertex paths.
- 99 TAA checks passed, including D24 coverage and hair-only motion with stationary
  bones; 1,124 hair GPU/config, 2,180 shared overlay GPU and 1,300 avatar transform
  precision checks passed. `git diff --check` passed.

Live rendering smoke test (October 11 local time, October 12 UTC):

- MCP launch and remembered login succeeded. The saved camera was used directly,
  unlocked; no camera or graphics settings were written, so none needed restoring.
  Scene: Brianconnais, furnished interior with the user's long-haired avatar,
  viewed from behind/above. The camera moved during the capture; exact start/end
  coordinates and orientation are in the raw metadata.
- Viewport 3440 x 1369; render target 3440 x 1316; RTX 5090, NVIDIA 617.14.
  TAA selected, GTAO enabled, SSGI disabled, shadow detail 0, VSync off,
  YieldTime -1 and BackgroundYieldTime 0.
- Hair physics enabled: sway 6 degrees, response 10, stiffness 6, root radius
  0.05 m, gradient 0.19 m, regional variation 0.60, tip lag 0.50; self-only,
  maximum distance 10 m.
- One run, 120 warmup frames and 60 measured frames. GPU frame median/p95:
  6.787/8.964 ms; CPU frame median/p95: 7.308/9.796 ms; frame interval
  median/p95: 7.387/9.856 ms. Inclusive scopes are not added together.
- [Raw capture](../../.logs/viewer-mcp/20261012T005035Z-profile-7a9df240.json),
  [screenshot](../../.logs/viewer-mcp/20261012T005041Z-hair-regions-tip-lag-b32db751.png)
  and [screenshot metadata](../../.logs/viewer-mcp/20261012T005041Z-hair-regions-tip-lag-b32db751.json).
  Screenshot renders the avatar/hair and scene without obvious geometry breakup.
- This is a startup/rendering smoke test, not a cost comparison or proof of natural
  movement on every hairstyle. No paired baseline or repeated timing samples were
  collected, and shadows were disabled in this live scene (covered by GPU path
  tests). The viewer is left running for motion/tuning review. The regional mask
  still approximates the hairstyle; no authored strand roots or avatar collisions
  were added, so aggressive settings can stretch or clip hair.
