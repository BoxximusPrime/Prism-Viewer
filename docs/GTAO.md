# GTAO

Initial implementation, uncommitted. Enable it in **Preferences > Graphics > GTAO**.
It is off by default and takes precedence over the legacy SSAO checkbox. Disabling
GTAO restores that checkbox's behavior. Optional shader or render-target failures
fall back to legacy SSAO and appear in the log and preferences status.

## Controls

| Control | Default | Effect |
| --- | --- | --- |
| Radius | 0.50 m | Size of nearby occluders to consider; range 0.05–3 m. |
| Strength | 1 | Exponent applied to filtered visibility; zero removes darkening. |
| Quality | Balanced | Performance / Balanced / High use 8 / 18 / 32 depth taps. |
| Denoising | 1 | Depth/normal-aware spatial smoothing; zero bypasses both filter passes. |
| Distance falloff | 0.60 | Fraction of the radius over which occlusion fades; larger is gentler. |
| Thin-object compensation | 0 | Reduces the contribution of samples separated in view depth, limiting thick silhouettes. |
| White geometry debug | Off | White opaque/masked geometry with only GTAO shading, against gray sky. Session-only. |

The diagnostic runs after exposure, tone mapping, glow and depth of field, before
FXAA/SMAA, and omits presentation noise. It uses the geometry mask captured before
transparency modifies depth. Alpha-blended surfaces are outside this initial AO
pass; HUDs/UI still draw normally. Strength affects the diagnostic and lighting
identically, with the diagnostic converted from linear visibility to display sRGB.

## Rendering

This is a GLSL adaptation of the horizon integration and Hilbert/R2 sampling in
[Intel XeGTAO](https://github.com/GameTechDev/XeGTAO), with the MIT notice included
alongside `gtaoF.glsl`. It is not the complete upstream implementation. The initial
version uses the existing full-resolution D24 depth and packed G-buffer normals,
plus a separable five-tap bilateral denoiser. Finite slice integration is normalized
against its matching unoccluded integral to keep isolated sloped surfaces white;
texel-snapped samples below the surface hemisphere are rejected.

`LLPipeline::renderGTAO()` produces two `RG16F` ping-pong targets: R contains linear
visibility and G contains the geometry mask. They cost 8 bytes per render pixel
combined (about 15.8 MiB at 1920×1080), allocated only while enabled. Render-size
changes rebuild the targets. Cubemap captures, mirrors and impostors do not consume
the main camera's GTAO buffer.

The sun/light-buffer pass writes strength-adjusted visibility into the existing
light-map green channel. Opaque legacy and PBR indirect diffuse lighting use that
visibility; sun/projector shadows retain their own channels. The old shared light
blur preserves GTAO green and runs only when the remaining shadow filtering needs
it. PCSS keeps its existing contact softness. Direct light, emission and specular
lighting retain their existing behavior.

## Later TAA integration

The shader reconstructs positions using the actual inverse projection matrix,
including jitter. `gtao_noise_index` is deliberately held at zero in
`bindDeferredShader()` and already supports a 64-frame sampling cycle. Once a valid
TAA resolve exists, advance this index with that resolve's frame sequence and tune
the spatial filter/sample count with moving-scene tests. Reset temporal history on
camera cuts, projection/render-size changes, and AO setting changes.

TAA still needs the renderer's motion vectors, history validation, disocclusion
handling and suitable clamping. If AO gets its own temporal resolve, insert it
between raw visibility and lighting composition; keep strength outside history so
changes do not accumulate stale darkening. A filtered view-depth mip chain can
replace the isolated depth-fetch helper separately to improve larger-radius cost
and sampling. Neither depth mips nor temporal accumulation is implemented here.

## Validation

The Release build and viewer startup passed with all three GTAO programs loaded.
The suite passed 38 GTAO scenarios and 280 PCSS cases, including preservation of
the filtered GTAO signal through both existing shadow modes. Existing alpha
lighting and skin-diffusion GPU regressions also passed.

`scripts/tests/test_gtao_gpu.py` compiles and runs the production GLSL on a hidden
SDL OpenGL context without logging in. It checks empty sky, isolated flat/sloped
planes at all quality levels, contact shadows, controls and extremes, deterministic
sampling and temporal index wrapping, proportional world scale, different fields
of view/jitter, light-channel preservation/fallback, and the white-geometry output.
It writes `tmp/gtao-tests/white-geometry.png`. Run:

```powershell
.venv/Scripts/python.exe scripts/tests/test_gtao_gpu.py
.venv/Scripts/python.exe scripts/tests/test_gtao_gpu.py --benchmark
```

On the test RTX 5090, a synthetic 1920×1080 scene measured median GPU times of
0.170 / 0.297 / 0.452 ms for Performance / Balanced / High, including both denoise
passes (20 timed frames after five warm-up frames). These are isolated effect
timings, not in-world viewer frame costs or a guarantee on other hardware.

The real preferences tab was checked at the login screen: control layout,
enable/disable, debug selection, radius adjustment, and Cancel restoring values.
No account login was used. In-world appearance, camera motion, dense foliage,
avatars, and performance on lower-end AMD/Intel/NVIDIA hardware remain to be checked.
Like other screen-space AO, missing off-screen/hidden geometry cannot occlude;
large radii and thin silhouettes can still expose those limitations.
