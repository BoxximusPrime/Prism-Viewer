# Body alpha cuts and optional clothing collision — 2026-10-15

Status: in progress, uncommitted. CPU/GPU regressions and Release build pass;
in-world validation pending.

## Confirmed cause and change

`llhairmesh.cpp` used the same legacy face-opacity mask for fitting hair,
fitting head clearance, and building the collision shell. Body faces with
opacity at or below 0.001 were skipped. Changing those alphas also changed the
cached geometry mask, causing a shell rebuild and rope refit. This agrees with
the user's observation that body alpha cuts opened holes in the purple shell.

Body-name matches now include all mesh faces, regardless of visual alpha.
The shared `colliderFaces` policy is used by shell construction, head clearance,
and both invalidation checks. Body alpha changes therefore preserve these masks.
Real attachment, topology and skinning changes still invalidate geometry.
Hair fitting retains its existing visible-face policy.

Graphics > Hair > Physics also has **Clothing collision names (optional)**,
backed by `BoxxyHairPhysicsClothingNames`, initially empty. It matches whole
words/phrases in rigged attachment root names, ignoring case, and includes linked
children. Hair, HUDs, unrigged objects and SSS overlays remain excluded. The
existing body list takes precedence if an attachment matches both lists; an
attachment is included only once.

Clothing excludes faces hidden by legacy opacity or PBR blend/mask opacity
factors. Opaque PBR ignores legacy/material alpha, matching the renderer.
Texture cutouts are not sampled. Clothing visibility changes still rebuild
geometry and refit guides; body alpha cuts do not. These controls persist,
participate in preferences Default/Cancel, and are recorded in capture metadata.

## Cost and quality limits

This combines selected triangles in one BVH; it does not compute the outer union
of body and clothing. Garment linings and overlapping layers can still create
opposing contacts, and dense layers can consume the bounded candidate budget.
Trying one distinctive garment name at a time makes that behavior inspectable.

Skinning/refit work and buffer memory grow with included triangles. Point,
midpoint, cache and ray query budgets are unchanged. Restoring hidden body faces
can itself increase geometry cost. Existing allocation/one-million-triangle
limits still apply; exceeding them disables collision until shader reload.

The [earlier source investigation](hair-tip-trace-2026-10-13.md) observed
543,501 triangles with clothing accidentally included versus 101,768 with the
body list alone. Those were different captures of the earlier solver and are
not a current FPS estimate or a matched cost comparison for this change.

## Validation

- [Selection test](../../scripts/tests/test_hair_mesh_selection.py): compiles
  production collector and face policies; verifies independent lists, linked
  pieces, runtime changes, duplicate prevention/body precedence, hidden body
  masks staying constant, hidden clothing variants, PBR modes, hair/HUD/world
  exclusions, persisted empty default, reset wiring and panel bounds.
- [Head fitting](../../scripts/tests/test_hair_head_fit.py): outer envelope,
  mouth rejection, winding/order, 4/30/64 ropes and 9/17/32 vertices pass.
- [Mesh GPU suite](../../scripts/tests/test_hair_mesh_gpu.py): 311 skinning,
  refit, fitted scaling, moving shell, swept-contact and bounded-query checks pass.
- [Full-rope continuity](../../scripts/tests/test_hair_contact_continuity_gpu.py):
  finite patches, corner continuity, thin/dense shells, pinned-root continuity,
  breathing and root motion pass. [Raw result](../../.logs/hair-alpha-clothing-continuity.log).

A direct MCP baseline was requested on the connected Release 0.10.0.54542 viewer
with 240 warmup / 600 measured frames, without changing the camera or settings.
The bridge disconnected before the result could be saved; no completed artifact,
scene/viewport metadata or valid timing comparison is available from that attempt.
It is not counted as a successful live test. The user will test the rebuilt viewer;
alpha-toggle behavior and selected clothing quality/cost remain unverified in-world.

## Build

Canonical command:

```powershell
cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2
```

[Build log](../../.logs/hair-alpha-clothing-build.log).
The build completed successfully. Canonical
[executable](../../build-vc170-64/newview/Release/secondlife-bin.exe) SHA-256:
`cd447f5f8d38709dfa5bc6fa13153e70be13a9ce151900852b6653afe42c898b`.
All six changed packaged resources (settings, preferences panel and four shaders)
match their source hashes. `git diff --check` passes.
No public class layout changed in this correction.
