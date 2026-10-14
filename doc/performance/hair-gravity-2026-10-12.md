# Experimental hair gravity - 2026-10-12

Status: in progress, uncommitted. Automated checks, Release build and in-world
smoke check passed. Hairstyle-specific visual tuning remains.

## Implementation

Graphics > Hair > Basic hair physics adds Enable gravity (experimental), off
by default, and Gravity strength (0-3, default 1). Both persist, reset with Hair
defaults and are available through MCP with matching bounds.

Gravity applies world-down torque using each region's existing representative
lever. Its equilibrium offset is inversely proportional to the squared spring
frequency, using the same stiffness clamp as the spring integrator. The target
and resulting bend retain the existing bounds. Movement impulses still combine
with this bias; the existing tip follower delays the ends. Switching gravity
off allows the hair to settle back. Movement response zero does not disable
gravity, while Tip sway zero disables all bending.

No shader or deformation-history layout changes: current/previous rotations
continue through the shared colour, depth, shadow and temporal paths, including
root pinning and the existing optional collision limiter. One set of five
springs per hair linkset advances once per frame. Regions approximate the style;
this is not a strand simulation and cannot make arbitrary hair hang freely.
Tip sway still limits the total bend to at most 15 degrees.

## Automated validation

- Production native driver: world-down movement in upright, pitched, rolled and
  inverted poses; strength zero, negative/high clamps, stiffness resistance,
  delayed tips, frame-rate agreement and settling after disabling gravity.
  Existing movement, linked-piece, multi-pass and teleport/pause cases passed.
- Spring/config checks: opt-in defaults, persistence, slider bounds, reset and
  automation registration passed.
- 1,124 hair GPU/config checks and 592 root-pinning/deformation GPU checks passed
  on RTX 5090, including shared colour/glow/shadow paths.

## Release and live validation

Built successfully with:

`cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2`

Executable: [Release viewer](../../build-vc170-64/newview/Release/secondlife-bin.exe),
Prism Release 0.9.0.54538, SHA-256
`dbd8500be4b2441c4a32796047a1c0a80a7718ebe16bed90f61823a9a9e0f5ad`.
XML settings uniqueness, Hair scroll bounds, staged resources and diff checks
passed. No class layout changed.

MCP launch and remembered login succeeded. Saved the
[original camera](../../.logs/viewer-mcp/20261012T094551Z-before-hair-gravity-4ae21bd7.camera.json)
before temporarily enabling gravity; no other settings or camera writes were
made. Start/end camera metadata match. `viewer_restore` succeeded, and a settings
read confirmed every exposed graphics value matches the pre-test values,
including gravity off. Viewer left running.

- Scene: Brianconnais interior, standing long-haired avatar viewed from behind.
  Camera global (289289.85546, 278769.48560, 1367.87524), FOV 60, unlocked.
- Viewport 3440 x 1369; render target 3440 x 1316; RTX 5090 / NVIDIA 617.14.
- Hair/physics enabled, self-only, range 10 m; gravity on, strength 1; sway 11.1
  degrees, response 5.1, stiffness 1, root radius 0.09 m, gradient 0.17 m,
  regional variation 1, tip lag 0.35; collision on at size 1.29, overlay off.
- TAA selected, GTAO on, SSGI off, shadow detail 0, VSync off, YieldTime -1,
  BackgroundYieldTime 0.
- One run: 120 warmup / 60 measured frames. GPU frame median/p95 6.452/7.174 ms;
  CPU frame 6.963/7.755 ms; frame interval 6.956/7.733 ms. Inclusive scopes
  were not summed.
- [Raw capture](../../.logs/viewer-mcp/20261012T094604Z-profile-fb647fab.json),
  [gravity-enabled screenshot](../../.logs/viewer-mcp/20261012T094604Z-hair-gravity-enabled-32e3b743.png),
  [screenshot metadata](../../.logs/viewer-mcp/20261012T094604Z-hair-gravity-enabled-32e3b743.json).
  Hair and scene render without obvious geometry breakup in the snapshot.

This is an integration smoke test, not a repeated on/off performance comparison.
No gravity cost claim is made. The live screenshot does not establish movement
quality in every pose or style; tilted/inverted direction and settling were
checked in the native driver. Existing collision can limit the visible droop.
