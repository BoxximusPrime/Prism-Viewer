# Hair collision, guide motion and shading fixes — 2026-10-12

Status: implemented and uncommitted. Production GPU regressions, Release build and live integration smoke checks pass. Broader hairstyle and animation validation remains.

## Scope

- Regional contact blends distinct nearby cached body/hand surface patches instead of selecting a single nearest patch. Existing swept-crossing recovery remains.
- Regional root mobility scales requested drag before collision. Rendering no longer scales the entire collision correction. Guide mobility is handled by the solver, with no second root fade in rendering.
- Guide travel bounds precede contact, and a final contact pass prevents neighbouring segment corrections from leaving a point inside its plane. An embedded pinned root retains its attachment; its first free endpoint is constrained without forcing the entire root segment outside an impossible surface.
- Contact preserves genuine separating velocity and removes correction-generated normal kicks. Receding surfaces still cannot pull hair inward.
- Compliant second-neighbour distance constraints resist guide kinks independently of shape retention. They use the existing stiffness setting and timestep-scaled compliance, preserve segment lengths, and do not add controls.
- Analytic derivatives of the shared contact field transform lighting normals and tangents, including its boundary fade. Seven skinned lighting entry points use inverse-transpose normals for this nonrigid deformation. Degenerate/folded transforms retain a finite lighting fallback.

## Regression results

Run `scripts/tests/test_hair_stability_gpu.py` with the repository Python environment. It runs production shaders in a hidden SDL/OpenGL context on the local RTX 5090; it does not measure viewer FPS.

| Reproduction | Before | After |
| --- | --- | --- |
| Regional ridge: 12 mm sinusoidal animation, maximum shell step 0.628 mm; 120 warmup and 120 sampled frames | 29.087 mm maximum rendered step | 0.751 mm |
| Same animated ridge, mesh drag disabled for isolation | 29.867 mm | 0.266 mm |
| Partial-root regional vertex | 7.655 mm penetration after rendering | 10.000 mm outside |
| Guide travel limit, stiffness 6 / retention 1 | 19.465 mm penetration | 10.224 mm outside |
| Partial-root guide vertex | 5.464 mm penetration after rendering | 14.400 mm outside |
| Separating guide in soft band | outward speed reduced to zero | 0.472 m/s; contact-free reference 0.466 m/s |

With retention zero, the one-frame kink probe has summed squared tangent differences of 10.063 at stiffness 1 and 8.271 at stiffness 12. The test checks segment lengths too. This isolates immediate bend resistance; it does not claim curvature is monotonic at every point in a subsequent oscillation.

Contact normals/tangents agree with finite differences of actual deformed geometry, both within the grid and at its fade boundary. Actual diffuse, bump, alpha, material, PBR opaque, PBR alpha and fullbright-shiny skinned vertex programs return the expected contact normal.

Other checks passed: guide inertia/gravity/pins, 30/60/7 Hz and low-stiffness stress; shell skinning/refit/crossing (311 checks); shared contact/drag/history/reset; 2,176 deformation/pass checks; 119 TAA checks.

Raw regression results: [log](../../.logs/hair-six-fixes-regression.log). Pre-fix reproductions: [review log](../../tmp/hair-review-probes.log).

## Live session

Scene: Brianconnais, animated local avatar with long dark hair. Viewport 3440×1369; render target 3440×1316. Camera remained user-controlled and was not moved by this work. [Saved camera](../../.logs/viewer-mcp/20261012T213450Z-before-hair-six-fixes-09466882.camera.json).

Initial settings: guides on, mesh collision off, gravity on at 1.2, stiffness 1, retention 0, root radius 0.12 m, root gradient 0.10 m, smoothing 0.15 m, mesh padding 0.015 m. These are the user's settings, not recommended defaults. Regional mesh checks temporarily enable mesh collision and disable guides.

Pre-reload Release executable SHA-256: `e3090de3485907a55734495705f471368356ca35afdb982a3fe883de75340070`.

Before: [screenshot](../../.logs/viewer-mcp/20261012T213600Z-hair-six-fixes-before-regional-f8d5c690.png), [60-frame smoke capture after 120 warmup frames](../../.logs/viewer-mcp/20261012T213656Z-profile-62e5e17c.json). Median GPU contact coupling 7.327 ms; inclusive mesh update 7.465 ms; whole frame 15.662 ms. Shell: 302 meshes, 308,617 triangles, 14,112 contact points. No guide chains in this capture.

Build: [Release log](../../.logs/hair-six-fixes-build.log). The first sandboxed build stalled at the MSBuild banner and was interrupted; the retry outside that sandbox completed successfully with `cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2`. No C++ class layout changed. The executable hash is unchanged because these fixes change shader and UI resources. The ten changed shader files and tooltip XML match the canonical Release resources by hash. Live shader reload succeeded with source version `8eb89e8d-a87d-c44b-0e2d-9da3a11a6433`.

After reload, each timing capture used 120 warmup frames and 60 measured frames:

| Mode | Contact coupling median | Inclusive mesh update median | Whole-frame GPU median | Raw capture |
| --- | --- | --- | --- | --- |
| Regional, gravity on | 7.773 ms | 7.919 ms | 16.228 ms | [JSON](../../.logs/viewer-mcp/20261012T214109Z-profile-7c5df464.json) |
| Guides, gravity off | 2.079 ms | 2.217 ms | 9.817 ms | [JSON](../../.logs/viewer-mcp/20261012T214130Z-profile-3785d864.json) |
| Guides, gravity on | 2.082 ms | 2.199 ms | 9.630 ms | [JSON](../../.logs/viewer-mcp/20261012T214144Z-profile-3e55a9f7.json) |

Guide captures report 16 chains / 144 guide points. Shell counts remain 302 meshes / 308,617 triangles. Captures completed without reported errors. The live camera changed during testing; automation did not move it. These timings therefore do not establish performance gains or regressions between modes or builds.

Visual smoke checks: [regional with gravity](../../.logs/viewer-mcp/20261012T213924Z-hair-six-fixes-after-regional-66bd5fc9.png), [regional without gravity](../../.logs/viewer-mcp/20261012T214115Z-hair-six-fixes-after-regional-no-gravity-3fa445dc.png), [guides without gravity](../../.logs/viewer-mcp/20261012T214134Z-hair-six-fixes-after-guides-no-gravity-8ca1e271.png), [guides with gravity](../../.logs/viewer-mcp/20261012T214150Z-hair-six-fixes-after-guides-43e684f5.png). Hair remains visibly coherent without an obvious deformation explosion in these views. Animation poses and views differ, so this is not a pixel comparison or proof that all jitter is eliminated.

Restoration verified: mesh collision off, guides on, gravity on, matching the initial values. No stiffness, retention, camera or other graphics controls were changed by this work.

## Limits

The numerical regressions use synthetic surfaces. Live screenshots cannot prove absence of animation jitter. Captures here are short integration smoke tests, not repeated optimization benchmarks; scopes are inclusive and must not be added. Existing limitations remain: automatically fitted guides, finite grid coverage, approximate surface patches, pinned authored overlap, and no hair self-collision.
