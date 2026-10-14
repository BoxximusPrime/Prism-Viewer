# Hair guide binding, mesh recovery and elasticity — 2026-10-13

Status: implemented and checked, uncommitted. Synthetic GPU checks, Release build
and live integration smoke pass; broader hairstyle/animation validation remains.

## Changes and evidence

The user's guide overlay separated two symptoms: animated mesh contact made ropes
kick around chest folds, while breathing moved visible back hair despite stable
ropes. Both reproduced independently in production shaders with synthetic data.

- Mesh contact/length recovery generated **3.0000004 m/s** from a stationary fold
  with zero incoming velocity or force. Constraint position correction now
  redirects but cannot increase predicted particle speed; connected velocity
  constraints transfer motion from anchors. Surface motion and friction still
  act at contact. Midpoint contact planes yield to opposing endpoint normals at
  folds. The same static case now creates **0 m/s**.
- A 12 mm torso palette translation moved visible hair **17.191 mm** despite
  unchanged guides. Each rigged hair skin now stores a head-local reference
  palette in both guide buffers when guides are fitted. Rendering uses that
  reference so guide interpolation does not move with torso skinning. Current
  and previous TAA positions use the matching binding. The same test now moves
  **0 mm**; head translation still follows, and disabling guides restores normal
  skeletal animation. Bind shape is already present in render vertices.
- Guide elasticity adds compliant length constraints with accumulated multipliers
  and timestep scaling, sharing the existing bending solver pattern. It does not
  change rest lengths. Graphics > Hair has a 0–1 control, default **0.25**; zero
  restores rigid lengths. This is softness, not a maximum stretch percentage.
  Settings persistence, reset, automation and slider bounds are wired together.

Baseline [GPU reproduction](../../.logs/hair-binding-before.log) and
final [binding/recovery/elasticity results](../../.logs/hair-binding-after.log).

## Regression results

Tests run on the local GPU using real GLSL programs and synthetic geometry. They
are correctness checks, not representative viewer performance measurements.

| Check | Result |
| --- | --- |
| 0.5 mm sinusoidally moving fold, elasticity 0 / 0.25 / 1 | Maximum settled frame displacement 0.0708 / 0.0643 / 0.0350 mm; speeds 0.00425 / 0.00387 / 0.00167 m/s |
| 0.8 m rope loaded by gravity, elasticity 0 / 0.25 / 1 | Length 0.80121 / 0.80840 / 0.83332 m; unloaded length returns within 0.001 mm of 0.8 m |
| Elasticity 0.25 at 30 / 60 Hz | Matching settled loaded/released lengths, both mesh and non-mesh paths |
| Animated plane at 30 / 60 Hz | Maximum guide position difference 0.105 mm |
| Static ridge | Settled frame movement 0.00412 mm |
| Repeated contact projection | Zero drift |
| Friction 0 / 1 | Tangential velocity 0.5 / 0.41826 m/s |
| Frozen guide binding and TAA | No torso-induced displacement or false temporal motion; head following and guide-off fallback pass |

- [Guide solver](../../.logs/hair-binding-guides-final.log): pins, inertia, gravity,
  constraints, 30/60/7 Hz, reset, proxies/mesh, neighbour pull, interpolation/seams.
- [Contact response and debug](../../.logs/hair-binding-response-final.log):
  idempotence, curved proxy sliding, full sideways fall, friction, single surface
  motion transfer, actual overlay positions and colours.
- [Stability and normals](../../.logs/hair-binding-stability-final.log): regional
  animated contact, root clearance, separating velocity, bending and seven
  skinned lighting paths. The bend-isolation case explicitly sets elasticity
  to zero to keep its rigid-length assertion; elastic loading has separate coverage.
- [Persisted settings](../../.logs/hair-binding-settings.log): slider defaults,
  bounds, reset and automation registration, plus spring regression checks.
- [Deformation](../../.logs/hair-binding-deform.log): 2,176 pinned-root checks,
  including colour, glow and shadows.
- [TAA](../../.logs/hair-binding-taa.log): 119 checks, plus the explicit frozen
  binding temporal test above.
- [Skeletal precision](../../.logs/hair-binding-precision.log): 480 cases,
  maximum local skinning error 0.000000101 m.

The settings test initially hit a sandbox temporary-directory permission error;
rerunning with its temporary directory inside the build workspace passed.

## Live integration

The user's camera was saved before restart:
[camera](../../.logs/viewer-mcp/20261013T072232Z-hair-binding-before-restart-b6db872b.camera.json).
Scene: Brianconnais, viewport 3440×1369. User's existing hair tuning included
mesh collision and guides on, gravity 3, damping 22, friction 0, bending 0,
stiffness 1, retention 0, smoothing 0.07, root radius 0.1 m, root gradient 0.27 m,
travel limit 0. These are deliberate user experiments, not defaults to overwrite.

Initial Release build passed after the binding/header changes:
[build log](../../.logs/hair-binding-build.log). The [final Release build](../../.logs/hair-binding-build-final.log)
also passed after adding elasticity. Executable:
`E:\BoxxyViewer\build-vc170-64\newview\Release\secondlife-bin.exe`, SHA-256
`05228a53203e5c67e1b153d3229e87d91f0c5605d8b2fc22764b917ea422c40e`.
Runtime GLSL, settings and preferences XML match workspace hashes. All
**267/267 shaders loaded successfully**; [startup log](../../.logs/hair-binding-shader-startup.log)
passes `test_shader_progress_log.py`. Initial launch exceeded the bridge's
60-second wait while compiling; the subsequent status check connected, and
remembered login succeeded without further launch.

The [screenshot](../../.logs/viewer-mcp/20261013T074337Z-hair-binding-elasticity-release-a5d01d8f.png)
shows the hair and rope overlay rendering from behind. It is a broad integration
view, not a close-up proof that every contact is stable. The saved camera was
restored and released; no graphics settings were changed for this test. Existing
tuning was preserved, with the new elasticity control at its default 0.25.

[Live smoke capture](../../.logs/viewer-mcp/20261013T074436Z-profile-e1bae9e9.json):
120 warmup / 60 measured frames, Brianconnais, RTX 5090 / NVIDIA 617.14,
viewport 3440×1369, render 3440×1316. Camera start/end match the saved pose, with
no camera lock. The animated shell contains 543,501 triangles across 310 meshes;
all 14,112 contact samples and 16 guides / 144 nodes are active. Median GPU mesh
update **3.339 ms**, nested contact coupling **3.141 ms**, whole GPU frame
**13.351 ms**; median CPU mesh update **0.802 ms**. These scopes are inclusive and
must not be added. There is no paired performance comparison or optimization
claim; scene content, animation, the visible debug overlay, and user settings
limit comparisons with other sessions. GPU regression programs were finished
before the capture. No active capture or camera lock was left behind.

## Limits

The synthetic fold is a controlled contact stress case, not the user's exact
breast/hand geometry. Guides still approximate a hairstyle using 16 ropes of
nine points; no hair self-collision is added. Reference binding captures the pose
at fitting time and refreshes on existing geometry/skeleton invalidation.
Elasticity yields under load; it is not a hard strain cap. High loads or difficult
contacts can stretch more. The mesh velocity correction favours stable recovery
over perfectly energy-conserving strand dynamics. In-world hand-through-hair,
seated poses, and broader hairstyle quality need visual follow-up.
