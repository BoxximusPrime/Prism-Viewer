# PCSS penumbra investigation — September 12, 2026

Status: implemented and uncommitted. The user reports improvements from the receiving-floor and shadow-stability corrections, but no visible improvement in the wall's angle-dependent softness from the subsequent search/warp patch. The September 17 depth-generation correction below passes GPU regressions and the Release build; an in-world wall retest is pending.

The user reports hard silhouette fragments within a soft avatar shadow, several visible visibility tiers, and softness that changes with the camera angle. Controlled regressions reproduced the defects below. They do not reproduce the full scene or establish that every reported artifact has the same cause.

## Sparse blocker search

The blocker search spread its disk samples over the entire cascade-derived search radius. That radius can be much larger than the actual penumbra. The centre sample finds a narrow caster inside its hard silhouette, but nearby receivers outside that silhouette can miss the caster entirely. Those receivers fall back to minimum softness, leaving hard fragments beside a soft shadow.

The search now divides the existing sample budget between two uniform disks: half at one eighth of the full search radius, and half at the full radius. The local group retains a centre sample. This improves nearby narrow-caster detection while preserving the broader search. Search budgets remain 8/16/32 samples and filter budgets remain 16/32/64; there is no additional temporal noise or filter pass.

A strip-caster regression compares the filtered visibility against an analytic disk-emitter convolution. Its maximum visibility error fell from 0.3286 to 0.0468. Across 27 additional combinations of blocker distance, emitter angle and projection warp, the worst error is 0.0903. Finite sampling still approximates the blocker distribution, and dividing the budget reduces the sample density of the outer disk. These results are not a guarantee for every thin caster or multi-layer occluder.

## Camera-oriented sampling

The sun/moon sampling disk selected its tangent from fixed camera-space axes. Although a continuous circular emitter is rotation invariant, a finite disk sample pattern is not. Turning the camera therefore moved the sample pattern over the same surface.

The shader now uses world up and north transformed into camera space to construct that tangent. CPU uniform uploads supply those axes from the current view. The sampling pattern stays aligned to the scene as the camera turns. Projector sampling retains its existing emitter-plane orientation.

Controlled camera pitch and roll comparisons pass at all three quality levels, with a maximum visibility difference of 0.000005. These tests hold the shadow map constant; camera-fitted cascade resolution and coverage can still change in the viewer.

September 17: Graphics > PCSS now exposes **Stabilize shadow pattern** (`RenderPCSSStablePattern`), enabled and saved by default. Turning it off restores the old camera-space up/north axes so the sampling disk follows camera rotation. It updates the existing axis uniforms immediately, without a shader reload or additional rendering work. Projector emitter axes, receiver bias, geometric normals and cascade fitting are independent of this switch. The new comparison tests retain 0.000005 maximum orbit variation with stabilization on and reproduce 0.372776 variation with it off on a controlled narrow-caster case. Projector output matches exactly in both modes. All 750 PCSS GPU checks and the Release build pass. The live preference checkbox, scoped Default, Cancel restoration, OK/reopen retention and PCSS enable dependency pass using isolated login-screen settings. In-world comparison is pending; the change is uncommitted.

### Camera-fitted cascades changed softness (September 17 follow-up)

The user reports that the pattern toggle makes no visible difference to a much larger softness change on a vertical wall. The earlier camera-rotation tests held the shadow map fixed. New cases also refit its depth range, rotate its axes and change its perspective warp while preserving the receiver, caster and light.

Two independent faults were reproduced in `pcssUtil.glsl`:

- The sun blocker-search radius depended on the cascade's near plane, which follows the camera. On a sloping caster, changing the search area changed the average blocker distance and therefore softness. Sun/moon searches now cover the configured maximum world-space penumbra radius. The existing local search samples still cover nearby contacts. Projectors retain their light-based near-plane calculation.
- The search and filter projected a finite disk using only the local UV derivative. Under a perspective warp this distorts the world-space disk as the camera refits the cascade. Each tap now includes its homogeneous denominator, projecting the intended offset exactly. Samples beyond the projection horizon are excluded.

The shared fix covers deferred and forward PCSS receivers. Search/filter budgets remain 8/16, 16/32 and 32/64, with no new texture fetches, render targets or passes. The pattern stabilization toggle remains available: it changes existing axis uniforms without adding GPU samples, and its separate finite-pattern regression still demonstrates a benefit. Cleanup code is unchanged.

Controlled comparisons on an RTX 5090:

| Measurement | Previous | Revised |
| --- | ---: | ---: |
| Maximum visibility difference from cascade depth refitting | 0.236870 | 0.000002 |
| Maximum/minimum edge width across cascade rotations/warps, all qualities | 1.8554 | 1.0702 |
| Wall edge width across left/front/right perspective views, D24 reconstruction and cascade refitting | 78.160 / 113.721 / 109.250 mm | 112.283 / 113.721 / 116.197 mm |

The perspective case measures the 10–90% transition on the wall rather than counting screen pixels. Cleanup alone measures 5.458 / 5.536 / 5.684 mm spread at 0 / 45 / 63 degree wall angles, retaining the expected small world-space footprint. Finite texels, samples and screen-space filtering still introduce small differences; these cases do not include the user's scene or TAA history.

All 792 PCSS, 306 rasterized mesh/horizon, 1,786 SSS GPU and 14 alpha shader syntax checks pass. The Release build passes and the staged shader matches its source. The isolated viewer loads its shaders and shuts down cleanly. A six-case GPU microbenchmark at 256×256 measured roughly 4% more time in five cases (about 0.0004 ms per draw), with the sixth faster; this is shader timing, not a full-viewer frame-time measurement. **The user's subsequent in-world retest showed essentially no improvement in the wall's angle-dependent softness.** These shader corrections did not resolve that report. Changes are uncommitted.

### Preserve caster depths before PCSS (September 17 follow-up; in progress)

Comparison with [Unity HDRP's directional PCSS integration](https://raw.githubusercontent.com/Unity-Technologies/Graphics/master/Packages/com.unity.render-pipelines.high-definition/Runtime/Lighting/Shadow/HDShadowSampling.hlsl) identified an upstream failure that the previous tests missed: a directional cascade's near plane moves with its receiver fit, and depth-clamped casters no longer contain their true distance. [NVIDIA's PCSS integration guide](https://developer.download.nvidia.com/assets/gamedev/docs/PCSS_Integration.pdf) relies on that blocker distance to estimate the penumbra. Correcting the sampling disk cannot recover depth already flattened during shadow rendering.

The viewer fits each sun map to visible receivers, retains off-screen casters using a separate light-side culling plane, and renders with `GL_DEPTH_CLAMP`. A caster between those two near planes therefore writes zero depth. Orbiting can move the fitted plane through the same caster, changing its reconstructed gap and shadow softness. Our previous analytic maps and rasterized meshes did not exercise that combination.

`extendSunShadowDepth()` now remaps only the projection's Z row to include the existing caster culling limit when PCSS is active. It handles orthographic maps and the viewer's perspective-along-Y warp. XY/W, the far plane, resolution, culling volume and submitted geometry stay unchanged. The existing inverse matrix then recovers real blocker distances. This adds a small CPU projection calculation per cascade, with no additional shader instructions, samples, maps or render passes. Projector and PCSS-off projections retain their existing behavior.

The regression compiles the production C++ helper, rasterizes a caster outside the receiver fit plus a receiver into D24 with depth clamping enabled, and runs the production deferred and forward shadow functions. It varies the fitted near plane, including the viewer's actual perspective projection with 64:1 and 640:1 denominator ranges. The old projections are retained as a baseline to verify that the fixture reproduces the defect.

| Shadow projection | Previous 10–90% edge width across near-plane fits | Corrected |
| --- | ---: | ---: |
| Orthographic | 1.808–9.596 pixels | 9.596–9.596 pixels |
| Viewer perspective warp, 64:1 | 1.958–9.526 pixels | 9.525–9.526 pixels |
| Viewer perspective warp, 640:1 | 1.958–9.525 pixels | 9.524–9.525 pixels |

All 406 rasterized mesh/horizon/cascade checks, 792 PCSS checks, 1,786 SSS checks and 4,000 altitude/projection precision checks pass on an RTX 5090, as do 88 lit volumetric-fog checks. The Release build passes. Isolated startup completes shader loading and shuts down cleanly; cached shader binaries fell back to successful recompilation, and the timed exit fired during browser initialization before the login screen. The depth-fit checks also verify unchanged XY/W and far-plane mapping. A wider depth range reduces D24 precision, especially at the far end of an extreme perspective warp; quantization is checked explicitly, and the extended skybox cases remain below the existing 1 mm transform-error limit. Camera-dependent texel density, cascade blending and the previously deferred wall flicker are separate remaining limitations. Full-scene frame time and the user's wall have not been verified with this build. Changes are uncommitted.

## Receiving floor falsely entered the shadow

Earlier soft-edge tests used clear depth behind the caster. Adding a receiving floor exposed a separate bug: when all four centre texels contain an occluder, PCSS bounds the receiver-plane correction using that occluder's slopes to prevent light leaks through walls. That bounded plane then misclassified actual floor texels elsewhere in the search/filter as blockers. Both the estimated penumbra and the filtered visibility could change abruptly across shadow-map cells. Camera-fitted projections can change the cells and slopes involved.

The shader now retains the original receiver plane alongside the bounded comparison plane. It excludes samples consistent with that receiver from blocker-distance estimation. For filtering, it accumulates guarded visibility and visibility with matching receiver texels restored. Restoring an isolated matching texel is insufficient: a grazing tangent can cross a wall at that depth. A complete in-bounds 2x2 patch must match the receiver before the restored result is used. The blocker search also looks for that evidence because a narrow contact filter may contain only mixed caster/floor footprints. Certification stops after a patch is found, and is skipped when the guard leaves the receiver plane intact.

This adds conditional depth gathers during certification, plus comparison arithmetic; the blocker/filter sample locations and counts are unchanged. In the worst case certification can attempt a gather for each search sample. GPU performance in a full scene has not been measured. The shared numerical tolerance and wall guard remain in force. A matching plane is a depth-based inference, not a material or object-identity test.

Before/after comparisons hold the caster fixed and add/remove only the receiving plane from the shadow map:

| Cases | Previous maximum visibility difference | Revised difference |
| --- | ---: | ---: |
| Sloping floor, orthographic/warped sun (original positive-slope sweep) | 0.4464 | 0.000000 |
| Contact softness and sun/projector quality sweep | 0.4927 | 0.000000 |
| Perspective pitch, D24 camera reconstruction, all qualities | 0.5000 | 0.000000 |

The regression now includes negative receiver slope as well. There are 44 floor-versus-empty pairs (88 draws), with a 0.001 visibility-difference limit. Perspective cases intersect actual camera rays with the plane, quantize camera depth to D24, and run production normal reconstruction. They are not merely coordinate rotations, but still use a controlled map rather than the viewer's complete cascade fitting and temporal resolve.

## Verification

### Optional secondary cleanup

Following further user reports of camera-dependent softness and angular chest shadows, an adjustable cleanup pass is implemented for an in-world comparison. `RenderPCSSCleanup` appears in Graphics > PCSS as Cleanup smoothing, ranging from 0 to 3, default 1.5. It applies immediately and participates in the existing preference reset/save/cancel handling. Zero disables cleanup.

The existing horizontal/vertical light-buffer passes now run for active PCSS cleanup even when GTAO is enabled or legacy SSAO is disabled. A separate small Gaussian filters only sun/moon and projector visibility (R/B/A). It uses integer texel taps and rejects/attenuates neighbours using surface normals and point-to-plane separation, with a depth-precision allowance. Each unit supplies a 4 mm surface Gaussian sigma, with a one-render-pixel minimum. Per-axis position derivatives convert the surface footprint into render pixels. Sigma is capped at 12 pixels and support is truncated to twice sigma (maximum 24 pixels in either direction). It does not sample material colors. The green AO channel retains either the existing legacy blur or the untouched GTAO result.

No extra render targets or temporal history are allocated. Cleanup adds two fullscreen passes when no legacy blur was needed, with six neighbours per axis at the default pixel minimum and up to 48 per axis in closeups. Dense integer taps avoid the gaps of a sparse wide filter. Full-scene GPU cost remains unmeasured. This pass covers opaque and alpha-cutout receivers; alpha-blended surfaces use separate forward lighting. Normal-map detail can reduce smoothing through the normal/depth tests. Small contacts can soften at higher settings. This is screen-space cleanup, so it does not establish camera-invariant world-space penumbra width or correct large polygon-shaped shadow errors.

470 PCSS GPU cases pass, including 17 new cleanup checks for zero/off, sampling-step attenuation, constant preservation, horizontal/vertical filtering, sloping-plane consistency, depth and normal boundaries, and legacy AO preservation. Settings and panel XML parse, and control registration is checked. 793 SSS GPU checks also pass. The Release executable rebuilt and linked successfully; staged shader, settings and PCSS panel hashes match their sources. In-world A/B comparison is pending.

The user reports some improvement from cleanup, but no visible response to the Cleanup smoothing control on a solid-box receiver under a spotlight. The running process is the current Release build. Static tracing found both deferred spotlight variants reading the cleaned B/A channels, without a later overwrite before spotlight lighting. This does not establish the live scene's state or receiver path.

`test_projector_cleanup_gpu.py` adds 16 integration cases: both production spotlight variants (camera inside/outside the light volume), both projector shadow slots, legacy/PBR material paths, and hard/broad visibility edges. Production cleanup runs horizontally and vertically through RGBA16F intermediates before the production spotlight fragment shader consumes it; unrelated material and lighting inputs are controlled. At three pixels, the maximum linear-lighting change is 0.4287–0.4321 for the hard edge and 0.0039 for the broad edge. The test demonstrates that cleanup can reach projector lighting and that a broad penumbra can change imperceptibly; it does not reproduce or resolve the user's no-effect observation. No production change was made on this follow-up. The subsequent zoom observation below identifies a scale limitation in that version.


### Closeup cleanup scale correction (in progress)

The user subsequently confirmed that projector cleanup becomes visible when zooming far out. The original fixed-pixel footprint covered progressively less of the surface when approaching it. Cleanup now uses the surface-scaled footprint described above, retaining the pixel minimum for distant sampling artifacts. The setting key, 0–3 range and default 1.5 remain unchanged; the UI drops the pixel unit. At the default, surface sigma targets 6 mm until the 12-pixel cap is reached. This is still a separable screen-space approximation: the minimum, cap, oblique surface mapping and edge rejection can affect apparent width. It does not replace PCSS blocker estimation. Higher closeup sampling can increase GPU time; full-viewer cost is unmeasured.

The GPU suite passes 482 PCSS cases plus 16 projector integration cases. A four-scale impulse regression measures surface spread of 5.633, 5.470, 5.458 and 5.329 mm across 1×/2×/4×/8× zoom; depth and normal boundary rejection is checked at each scale. The old shader fails this same zoom regression. Only shader and resource files change for this correction, so the existing Release executable can load it on restart. In-world confirmation is pending.

- 453 PCSS GPU cases passed, including receiving-floor, perspective-view, narrow-caster, projection-warp and camera-rotation regressions; GLSL 330 fallback is covered by the existing suite.
- 144 rasterized mesh/horizon GPU cases passed.
- 793 shared SSS shadow-path GPU checks passed.
- 2,400 altitude/matrix precision checks passed.

GPU checks ran on an NVIDIA GeForce RTX 5090 using production shaders. They do not exercise the complete viewer's temporal resolve or reproduce the screenshots. The next check is the same avatar shadow on white while orbiting between overhead and oblique views, followed by the original square floor at approximately 3,000 metres. The visible banding may have additional causes; the core PCSS correction does not increase filter density; optional cleanup is described above. The earlier precision correction is documented in `PCSS-PRECISION.md`.
