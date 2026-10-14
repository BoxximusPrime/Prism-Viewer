# Hair shader work reduction — 2026-10-13

Status: implemented, uncommitted. Release build and automated/live validation passed.

## Scope and implementation

The user identified **enhanced hair rendering**, rather than rope physics, as the expensive feature. Initial captures separated both; subsequent lighting comparisons temporarily disabled physics.

- Forward legacy alpha, material alpha, and PBR alpha now select ordinary material lighting or hair lighting before evaluating the seven local-light slots. Previously the ordinary response was computed and then overwritten.
- Hair uses an ambient-only reflection-probe entry point. It preserves probe irradiance (including the disabled-probe fallback) without evaluating glossy probes, hero probes, or screen reflections that hair subsequently discards. This also applies to deferred hair lighting. Ordinary material reflection entry points remain unchanged.
- A local-light slot with zero RGB returns before hair shadow/BRDF work, even when it retains a nonzero radius.
- Transmission capture supplies the current tile's projection as a single vec4. The existing uniform-value cache can suppress repeat uploads; the previous count-three array upload bypassed caching for every draw. Lighting still receives all three projections.
- No resolution, sample count, light count, lighting parameter, transmission model, or simulation update frequency was reduced.

## Setup

- Canonical Release viewer: `build-vc170-64/newview/Release/secondlife-bin.exe`, Prism Release 0.9.0.54539.
- Initial executable SHA-256: `5c7de652c4d317195f37f5756fb84844a218e46baa96f349683c96b1d58233b4`.
- Final executable SHA-256: `8ed5ce32c9fa83e69b50dc134ece9d4508921ac83f306109a4f4739f8e21cc1e`.
- RTX 5090, NVIDIA OpenGL 4.6.0 / driver 617.14; Brianconnais interior, local avatar with long dark hair, Legacy Perky body and Avalon head. Breathing/idle animation and rain continued.
- Viewport 3440×1369; render resolution 3440×1316 throughout. FOV 60 degrees. VSync and foreground/background pacing were left at the user's values.
- Enhanced lighting enabled, self-only, 10-yard range. Roughness .12, shine .35, brightness compensation 4, transmission 1, thickness .7, strand variation 2, generated normals enabled (strength .8, scale .5, rejection 1). Exact OIT enabled, `RenderExactOITNoOpCapture=true`, PCSS enabled/quality 0, reflection probes enabled, screen-space reflections and SSGI disabled. Full settings, sky, camera, and driver metadata are in every raw capture.
- The first direct capture changed no settings/camera. Later comparisons locked a saved pose. All temporary graphics settings were verified restored; the original camera pose was restored and unlocked. The viewer was closed after a final smoke capture, matching its initial state.
- Timestamps below are October 14 UTC / October 13 America/Denver.

Saved cameras: [initial](../../.logs/viewer-mcp/20261014T024522Z-hair-shader-original-171170ae.camera.json), [closer](../../.logs/viewer-mcp/20261014T024655Z-hair-shader-close-c5a06e9b.camera.json), [near](../../.logs/viewer-mcp/20261014T030533Z-hair-shader-near-d1e5e4b4.camera.json).

## Controlled lighting comparison

The final comparison used the **same final executable**, settings, near camera, and viewport. Original lighting shader sources were temporarily restored from the before-change snapshot; the compatible single-projection capture interface was retained in both variants. Thus this comparison isolates the lighting shader changes, **not** the CPU capture-uniform optimization.

Three captures per variant, each with 240 warmup frames and 360 measured frames. Optimized pilots preceded the reference captures, followed by the three final optimized captures. Shader reload completed before warmup. Reference source version: `47616804-f5f1-8c39-36fb-f878f88fb8a9`; optimized: `3c8a4328-25fe-56e2-b7b9-d2e46b2e7da8`.

| Inclusive GPU scope | Reference median of run medians (range), ms | Optimized median of run medians (range), ms |
| --- | ---: | ---: |
| `geometry.alpha` | 2.109 (2.088–2.112) | 1.827 (1.822–1.844) |
| `lighting.atmospherics` | 0.351 (0.351–0.351) | 0.291 (0.290–0.291) |
| `Hair.depth_maps` | 0.249 (0.249–0.256) | 0.254 (0.250–0.254) |
| `frame` | 11.287 (11.287–11.371) | 11.040 (10.966–11.386) |

The shared transparent pass improved by **0.281 ms / 13.3%** in this close-up; the shared atmospheric/deferred-lighting scope also consistently decreased by about .060 ms. These are shared pass timings, not isolated hair-only utilization. Whole-frame median improved about .247 ms / 2.2%, but its run ranges overlap: no dependable universal FPS gain is claimed. Atlas GPU cost did not improve materially, as expected from the unchanged rendering workload. Do not add nested/inclusive scopes.

The shader effects are small at the farther camera. The final near-view toggles gave approximately 9.768 ms with hair lighting off, 10.127 ms with transmission off, and 10.710–10.806 ms with the full optimized shader. Transmission remains a substantial cost: it needs blocker, nearest-hair, and opacity passes for sun/moon plus up to two local lights. Earlier closer-view CPU `hair.submit` medians were roughly 1 ms, so this is also render submission cost, not just fragment arithmetic. The scalar projection's CPU saving was not isolated across identical executable builds and should not be assigned a percentage.

## Raw captures

Medians in milliseconds. Hair depth is nested inside frame; columns must not be summed.

| Capture | Warmup/measured | GPU frame | GPU alpha | GPU hair depth | CPU hair submit | Raw data |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Initial view, both features | 240/240 | 16.874 | 0.688 | 0.275 | 1.103 | [e2ef6c60](../../.logs/viewer-mcp/20261014T024522Z-profile-e2ef6c60.json) |
| Initial view, both features, locked | 240/240 | 16.902 | 0.728 | 0.271 | 1.089 | [0b8e177d](../../.logs/viewer-mcp/20261014T024554Z-profile-0b8e177d.json) |
| Initial view, lighting off | 180/240 | 15.477 | 0.721 | 0.000 | 0.000 | [ec7c0060](../../.logs/viewer-mcp/20261014T024625Z-profile-ec7c0060.json) |
| Initial view, physics off | 180/240 | 11.194 | 0.729 | 0.270 | 1.056 | [37fcc50e](../../.logs/viewer-mcp/20261014T024654Z-profile-37fcc50e.json) |
| Closer, original lighting | 180/240 | 11.121 | 0.769 | 0.260 | 1.052 | [829b9094](../../.logs/viewer-mcp/20261014T024736Z-profile-829b9094.json) |
| Closer, lighting off | 180/240 | 9.971 | 0.716 | 0.000 | 0.000 | [87da4100](../../.logs/viewer-mcp/20261014T024803Z-profile-87da4100.json) |
| Closer, generated normals off | 180/240 | 11.016 | 0.771 | 0.265 | 1.042 | [4c308002](../../.logs/viewer-mcp/20261014T024810Z-profile-4c308002.json) |
| Closer, variation off | 180/240 | 10.950 | 0.776 | 0.265 | 1.041 | [1e105274](../../.logs/viewer-mcp/20261014T024817Z-profile-1e105274.json) |
| Closer, transmission off | 180/240 | 9.853 | 0.761 | 0.000 | 0.000 | [e3bdadeb](../../.logs/viewer-mcp/20261014T024824Z-profile-e3bdadeb.json) |
| Closer, original lighting repeat | 180/240 | 11.046 | 0.770 | 0.267 | 1.036 | [8187a0da](../../.logs/viewer-mcp/20261014T024831Z-profile-8187a0da.json) |
| Closer, ordinary-light skip | 240/360 | 11.065 | 0.757 | 0.266 | 1.050 | [1a607595](../../.logs/viewer-mcp/20261014T025204Z-profile-1a607595.json) |
| Closer, ambient-only and black-slot skip | 240/360 | 11.062 | 0.758 | 0.265 | 1.051 | [b938b2b4](../../.logs/viewer-mcp/20261014T025822Z-profile-b938b2b4.json) |
| Closer, Release with scalar capture projection | 500/360 | 10.901 | 0.934 | 0.264 | 0.999 | [bdfed93e](../../.logs/viewer-mcp/20261014T030532Z-profile-bdfed93e.json) |
| Near, optimized pilot | 240/360 | 10.710 | 1.841 | 0.264 | 0.993 | [a3753fe9](../../.logs/viewer-mcp/20261014T030555Z-profile-a3753fe9.json) |
| Near, lighting off | 240/360 | 9.768 | 1.386 | 0.000 | 0.000 | [bc3d4d8f](../../.logs/viewer-mcp/20261014T030602Z-profile-bc3d4d8f.json) |
| Near, transmission off | 240/360 | 10.127 | 1.577 | 0.000 | 0.000 | [f43abf3b](../../.logs/viewer-mcp/20261014T030610Z-profile-f43abf3b.json) |
| Near, optimized pilot repeat | 240/360 | 10.806 | 1.698 | 0.266 | 0.991 | [0f413a35](../../.logs/viewer-mcp/20261014T030619Z-profile-0f413a35.json) |
| Near, reference 1 | 240/360 | 11.287 | 2.088 | 0.249 | 0.999 | [7f157673](../../.logs/viewer-mcp/20261014T030846Z-profile-7f157673.json) |
| Near, reference 2 | 240/360 | 11.287 | 2.109 | 0.249 | 0.998 | [9d466e78](../../.logs/viewer-mcp/20261014T030854Z-profile-9d466e78.json) |
| Near, reference 3 | 240/360 | 11.371 | 2.112 | 0.256 | 0.996 | [907f7f41](../../.logs/viewer-mcp/20261014T030903Z-profile-907f7f41.json) |
| Near, optimized 1 | 240/360 | 10.966 | 1.827 | 0.254 | 0.996 | [e12e9b8b](../../.logs/viewer-mcp/20261014T030954Z-profile-e12e9b8b.json) |
| Near, optimized 2 | 240/360 | 11.040 | 1.822 | 0.250 | 0.998 | [fc471678](../../.logs/viewer-mcp/20261014T031003Z-profile-fc471678.json) |
| Near, optimized 3 | 240/360 | 11.386 | 1.844 | 0.254 | 1.003 | [4a9a383d](../../.logs/viewer-mcp/20261014T031011Z-profile-4a9a383d.json) |

## Visual and automated checks

Same-camera screenshots show no obvious change in hair highlight shape, pigment, transparency, or the surrounding scene. These are animated, live images, not pixel-identical reference renders; breathing/rain prevents a strict image difference from isolating the shader change. The main scene uses dark hair viewed from behind. Front lighting, other hairstyles, and other GPUs still need broader review.

- [hair-shader-close-before](../../.logs/viewer-mcp/20261014T024655Z-hair-shader-close-before-43b5632e.png)
- [hair-shader-ambient-after](../../.logs/viewer-mcp/20261014T025822Z-hair-shader-ambient-after-e6f0fd24.png)
- [hair-shader-near-reference](../../.logs/viewer-mcp/20261014T030903Z-hair-shader-near-reference-2a9e7ca6.png)
- [hair-shader-near-final](../../.logs/viewer-mcp/20261014T031011Z-hair-shader-near-final-a0e8de17.png)

Validation passed:

- Release build using the required `secondlife-bin` target and `/m:2`.
- 1,200 hair GPU/config checks (legacy/PBR, opaque/cutout, sorted transparency/OIT, normals, local/deferred lighting and coverage).
- 53 targeted production-function checks for unchanged probe irradiance, skipped black-light work, and equivalent blocker/nearest/density capture using the scalar projection.
- Existing alpha lighting/projector, 1,794 SSS GPU, and 15 local mesh material GPU checks.
- Full live shader reloads, staged shader/source equality, and `git diff --check`.
- [Final restored-settings smoke capture](../../.logs/viewer-mcp/20261014T031253Z-profile-fa36b48f.json): 120 warmup / 60 measured frames, both rope updates and hair depth active in all 60 frames, no capture error. This confirms integration after restoration, not performance.

The standalone GPU tests verify semantics, not live frame-time improvements. No rope solver/collision code was changed. Default settings are unchanged.
