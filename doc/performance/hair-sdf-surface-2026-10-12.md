# SDF collision surface preview - 2026-10-12

Status: implementation and verification complete; uncommitted. Release build,
251 GPU checks, controls and live preview/on/off/resource-release checks passed.

## Change

Graphics > Hair adds Show SDF collision surface, off by default. It draws the
current collision field's zero surface as a translucent purple overlay through
the avatar, hair and clothing. The existing cyan basic-shape overlay is separate.
Previewing works with SDF collision disabled: it builds the same animated mesh
field without changing which collision mode affects the hair. Hair physics,
supported hardware and the selected mesh body/head remain required.

The preview ray-marches only the field's cube, takes half-cell steps and refines
the first entering zero crossing. It uses the existing GPU texture without CPU
readback or a second field build. It does not write depth or appear in shadows,
reflection captures, HUD rendering or impostors. The existing SDF's resolution,
near-surface band, body selection and transparency limitations remain visible.
Regional variation still controls independent motion; SDF only changes contact.

## Automated validation

- 251 production GPU SDF checks passed, including both preview shaders, surface
  hits/misses, a GPU-animated surface moving into the view ray, parallel rays and
  a camera inside the field bounds, alpha blending and preservation of the
  destination screen alpha/glow channel.
- Native spring/control checks passed, including persisted opt-in defaults,
  checkbox bindings, preferences reset and automation for both SDF controls.
- Whitespace check passed.

## Build and live verification

Build command: `cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2`.
Executable: [Release viewer](../../build-vc170-64/newview/Release/secondlife-bin.exe).

The [original camera](../../.logs/viewer-mcp/20261012T125845Z-sdf-surface-original-65c06b4d.camera.json)
was saved before restarting. Original settings included hair physics and SDF
collision enabled. Live tests temporarily toggled the preview and collision
controls; temporary overrides and the original camera were restored afterward.

The first build, SHA-256
`27f74c4ef0b6ca7c3cb956276b463c690a9844dcbc473a99f3111b6dd7c9c468`,
loaded all 265/265 shader programs. Its
[initial smoke capture](../../.logs/viewer-mcp/20261012T130744Z-profile-542c988f.json)
used 120 warmup/60 measured frames, with 302 meshes and 308,759 triangles in the
field. At 3440 x 1369 (render 3440 x 1316), RTX 5090/NVIDIA 617.14, median GPU
preview time was 0.495 ms and median GPU frame time 10.704 ms. These inclusive
scopes cannot be added and this short capture is not a performance comparison.

The [matching-view on image](../../.logs/viewer-mcp/20261012T130722Z-sdf-surface-on-46c42bd0.png)
and [off image](../../.logs/viewer-mcp/20261012T130744Z-sdf-surface-off-f008a7f8.png)
exposed a transparency ordering issue: hair could cover the preview. The final
draw was moved after Exact OIT composition, and opacity lowered from 0.48 to 0.30.
These initial captures are superseded for final visual acceptance.

The [comparison camera](../../.logs/viewer-mcp/20261012T130722Z-sdf-surface-comparison-23c05206.camera.json)
looks at the avatar's back, standing after restart in the Brianconnais interior.
It is locked at (289292.6, 278770.1, 1366.900024), forward
(-0.275575, 0.944820, -0.177126), up (-0.049596, 0.170041, 0.984188), FOV 50 degrees.

A second [120-warmup/60-frame smoke capture](../../.logs/viewer-mcp/20261012T131552Z-profile-01a7c3f1.json)
on build `071aab516dad18f8dffef894ae70bbd71c2dca8b8c095c227d70619c313628a0`
confirmed the draw order fix but exposed alpha being written to the screen's
glow channel. The final blend uses separate alpha factors (zero, one) to preserve
that channel, with a darker purple tint. That intermediate capture is also
superseded for final visual acceptance.

## Final acceptance

Final Release SHA-256:
`335794cc1e5478d27874f8cb0af60e57ee236ac4491d4b712c223c8489db5d6d`.
Both new shaders, settings and UI match their staged Release files.
`test_shader_progress_log.py` passed with 265/265 programs successfully loaded;
[startup evidence](../../.logs/viewer-mcp/hair-sdf-surface-final-startup-20261012.log).

Same comparison camera, viewport, GPU and scene as above. The avatar was standing
with idle motion. Final settings: hair physics on, tip sway 15, response 2.1,
stiffness 7, root radius 0.03 m, gradient 0.20 m, regional variation 1, tip lag
0.35, shape retention 0.60, gravity 3, basic collision size 1.5, smoothing 0.
Exact OIT and GTAO were on; shadows and SSGI off. Full start/end settings, sky,
camera and raw samples are in each capture; settings were stable within the
final on capture. These are integration smoke tests, not a paired performance
benchmark or a claim about other GPUs/avatars.

| Check | Warmup / measured frames | Result / raw artifact |
| --- | --- | --- |
| SDF collision and preview on | 120 / 60 | [Capture](../../.logs/viewer-mcp/20261012T131951Z-profile-fae887c2.json): 302 meshes, 308,759 triangles; GPU preview median/p95 0.491/0.501 ms; whole GPU frame median 11.011 ms. |
| Preview on, SDF collision off | 60 / 30 | [Capture](../../.logs/viewer-mcp/20261012T132038Z-profile-3a763beb.json): same active field; GPU preview median 0.491 ms. |
| Both SDF controls off | 60 / 30 | [Capture](../../.logs/viewer-mcp/20261012T132116Z-profile-3c770abe.json): field inactive, zero cached meshes/triangles, no preview GPU scope. |

Inclusive GPU scopes must not be added to frame totals. Preview-only mode still
pays for rebuilding the animated collision field, as its tooltip explains.

Visuals: [preview on](../../.logs/viewer-mcp/20261012T131951Z-sdf-surface-accepted-on-45183c60.png),
[preview off with SDF collision retained](../../.logs/viewer-mcp/20261012T132012Z-sdf-surface-accepted-off-5f586fee.png),
and [preview with SDF collision off](../../.logs/viewer-mcp/20261012T132038Z-sdf-surface-preview-only-30946e4a.png).
The surface follows the animated body/head and remains visible through the hair
and clothing. The underlying hair/clothing remain visible through the tint;
turning the overlay off removes it cleanly. No added bloom remains. Idle poses
differ between screenshots; this was not a sideways-chair or all-avatar test.

`viewer_restore` succeeded, the original camera was restored and released, and
the viewer remains open. The user's newer slider edits and enabled preview
were preserved; these differ from the settings read before the first restart.
