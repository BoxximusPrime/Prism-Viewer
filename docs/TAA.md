# Temporal antialiasing

Select **TAA** in Preferences → Graphics → Advanced Settings → Antialiasing,
or use the identical AA selector in the new Graphics → TAA tab. Existing AA
choices and saved preferences are retained. New profiles default to TAA at higher graphics tiers. All changes apply immediately; Cancel
restores the saved preference values. The old Low–Ultra AA quality selector
continues to apply only to FXAA/SMAA.

| Control | Default | Effect |
| --- | --- | --- |
| History weight | 0.97 | Maximum previous-frame contribution; automatic validation can reduce it to zero. |
| Motion protection | 0.85 | Reduces history during motion and color disagreement. Raise for clearer movement, at the cost of more shimmer. |
| Color clipping range | 1.20 | YCoCg neighborhood standard deviations. Lower values reject stale colors more tightly. |
| Transparency protection | 0.00 | Favors the current image where transparency/post-deferred shading changes the opaque image. |
| Sharpening | 1.50 | Range 0–2. Bounded output sharpening, outside history. Adds to general CAS sharpening. |
| Stabilize fine static details | On | Retains thin static geometry and highlights through jitter and gentle camera motion. |
| Debug view | Normal | Motion/reactivity, actual history weight, clipping amount, detail protection, or rejection reasons. Session-only. |

## Rendering

The main world projection uses an eight-sample Halton(2,3) subpixel sequence,
applied after culling, shadow maps, reflection probes, and impostor updates. The
projection is restored before HUDs, world labels, and UI. Selection, snapshots,
GTAO/skin diagnostics, and buffer visualization do not accumulate TAA history.
Native render resolution is retained; this is antialiasing, not upscaling or
frame generation.

The sharpening slider is read every presentation pass and sent directly to
`taa_sharpen`; zero is a color passthrough. The filter allows a bounded extension
of the neighborhood range (one quarter of local contrast at 1, one half at 2)
to restore local peaks and troughs. The former strict range clamp cancelled the
adjustment entirely on thin lines and fine stripes. Sharpening never feeds back
into temporal history and retains the original scene glow alpha.

Camera motion reconstructs position from D24 depth. Visible object batches
overwrite it with previous model transforms; rigged mesh batches additionally
evaluate the previous per-joint skinning palette. The current mesh's vertex and
skin weights are used in both poses. Palettes are captured once per animation
frame, so shadow/probe passes cannot replace previous pose data. Draw batches
that lack consecutive history are marked reactive, covering new objects and
rebuilt/changed LOD batches. Previous view depth accompanies motion for
disocclusion rejection. The motion pass uses the visible depth buffer and the
same transform order as the material shaders; alpha-masked holes retain their
existing coverage.

Classic avatar bodies and impostors do not yet store previous vertex positions.
Their projected bounds are conservatively reactive, restricted to the avatar's
view-depth range so a nearby avatar does not disable AA on the background.
Accurate rigged mesh motion replaces that fallback on visible mesh surfaces.
This intentionally gives less temporal smoothing to untracked geometry.

The HDR resolve runs before exposure, tone mapping, CAS, glow, and depth of field.
It reconstructs the current unjittered image, dilates closest-surface motion and
reactive coverage, rejects offscreen history and mismatching history depths,
clips compressed HDR history against a 3×3 YCoCg variance/min-max box, and lowers
history weight for fast movement and color disagreement. Every contributing
history tap is validated before filtering. Invalid colors are discarded, valid
colors are renormalized, and missing support reduces history weight. A wholly
invalid footprint still rejects history. History stores the
depth of the same nearest surface used for motion dilation, so jitter does not
invalidate stationary silhouettes by mixing foreground and background ownership.
The output is sharpened only for presentation;
scene glow alpha is retained separately from history depth.

Static details receive up to one eight-frame jitter cycle of protection from
color clipping and depth changes between the same foreground/background pair.
The resolve records lifetime, the two surface depths, and a background luminance
anchor in a second history attachment. It refreshes protection only when it
sees contrast again; a removed detail clears within nine frames. Metadata follows
reprojected color, with per-tap surface and background validation. Stored surface
depths are transformed into the current camera's view space when a missing
feature retains its previous depth pair. The old 0.01-pixel motion cutoff is
replaced by graded confidence: coherent motion up to 0.5 pixels/frame retains
full protection, which fades to zero by 4 pixels/frame; differing neighboring
velocities reduce protection too. Changed background shading, new occluders,
and reactive shading cancel protection. Static eligibility is tracked when batching geometry; rigged,
active, flexible, texture-animated, and newly rebuilt batches retain strict
history rejection. The option can be disabled in Graphics > TAA. This adds no
geometry pass. Shader-only changes can be tested using the viewer's shader reload;
changes to resources or geometry classification require restarting a new executable.

Depth of field reconstructs circle-of-confusion values at jitter-adjusted
coordinates matching resolved color. It filters blur radii rather than blending
physical foreground/background depths. Presentation uses a corresponding point
depth sample; material previews and non-TAA copies explicitly clear the offset.
The temporally dilated/signed history depth is never used as physical scene depth.

History diagnostics report actual blend weight (red low, green high), clipping
amount (white high), and detail protection (green protected, blue unprotected).
Rejection reasons distinguish reset (gray), offscreen (blue), no matching depth
(red), partial depth support (yellow), and reactivity (magenta); green is valid.
These views rerun the resolve on demand after presentation consumes its output,
using the same inputs and uniforms. Diagnostic colors never enter history and
no extra persistent buffers are allocated. Sharpening settings and filters are
unchanged by the September stability fixes.

A pre-transparency HDR color snapshot provides conservative reactive detection
for blended hair, clothing, particles, water, and other post-deferred shading,
including Exact OIT composition. This also reduces history on some static
fullbright surfaces. Transparent layers do not have independent motion vectors.

History resets on AA/resource changes, resolution/projection changes, camera mode
changes, large camera cuts, region-origin shifts, skipped/long frames, relevant
TAA/AO setting changes, and entry into snapshot or diagnostic modes. Optional
shader/allocation failure disables jitter and leaves an unjittered current image.

GTAO advances its existing 64-frame sample index while the main image uses TAA;
the shaded result is accumulated by TAA. GTAO retains its spatial denoiser. An
independent AO history is not required by this implementation.

Five targets contain seven RGBA16F attachments: two history color/depth images,
two static-detail histories, motion/previous depth/reactivity, opaque color, and
resolved/scratch color. These use 56 bytes per render pixel, about 111 MiB at
1080p or 443 MiB at 4K. They allocate only when TAA is selected.
There is an additional untextured geometry pass; total cost depends on visible
draw calls and skinned geometry as well as image resolution.

## Validation and remaining limits

September 12 stability fixes are in progress/uncommitted. The 76 general TAA,
23 thin-detail, 25 motion/history, and 20 post-TAA depth GPU checks pass on the
RTX 5090. With repository defaults, the 0.65-pixel bar test at 0.012 pixels/frame
camera motion falls from 0.30155 to 0.01319 mean peak-to-peak variation before
sharpening (about 96% lower), and history rejection falls from 59.2% to zero.
The new suites are `scripts/tests/test_taa_stability_gpu.py` and
`scripts/tests/test_taa_post_depth_gpu.py`. They also verify reprojected metadata,
view-depth rebasing, partial-depth color exclusion, sky diagnostics, CoC edge
coverage and presentation depth. The Release build, staged shader/XML resource
verification, and startup TAA shader/sampler validation passed; in-world retest
is pending. These fixes do not add independent transparency-layer or classic
avatar deformation vectors; their conservative fallback remains in use.

The Release build and startup passed. The Graphics → TAA tab was checked at
runtime, including selecting TAA and confirming that all programs and render
targets initialized. No Second Life login was used.

`scripts/tests/test_taa_gpu.py` runs the production GLSL in a hidden SDL context,
without a viewer login. It tests HDR/history initialization, static convergence,
camera motion, sky translation, near-camera avatar masking, immediate moving
silhouette cleanup, depth rejection, reactive transparency, glow-alpha
preservation, and two-joint motion against a D24 prepass. On the RTX 5090, the
slanted-edge test's squared error fell from 5.46 to 0.65 after accumulation.

The first in-world test exposed a white-frame integration bug: TAA samplers
were missing from the viewer's reserved uniform registry, and texture binding
used GL uniform locations where the API requires reserved uniform indices.
All TAA inputs now use registered sampler indices. Startup validates that each
required sampler has a distinct texture channel and disables TAA on failure.
The GPU checks now follow the viewer registry and actual C++ input bindings;
removing the sampler registrations reproduces a regression-test failure.
The corrected Release build passed startup sampler validation without login;
the user confirmed that the white screen is fixed.

A subsequent stationary-camera test exposed crawling silhouettes. The resolve
used nearest-surface motion but stored center-pixel depth, and rejected history
against bilinear neighbors even when they contributed no color. Matching history
depth to motion ownership and ignoring zero-weight taps fixes these rejection
errors. The expanded 55 GPU checks include geometry/sky silhouettes across the
eight jitter phases, fractional-motion disocclusion, and history-weight response.
At the then-default 0.90 history weight, mean edge peak-to-peak variation falls from
0.3553 to 0.0364 in the synthetic silhouette test, with rejected samples falling
from 69.2% to zero; 0.97 history weight reduces variation further to 0.0193.
Moving-silhouette cleanup still passes. The user confirmed improvement in-world,
but reported remaining crawling on dense thin vertical bars.

`scripts/tests/test_taa_thin_gpu.py` adds 23 GPU checks for that case. With static
detail stabilization, mean peak-to-peak variation drops from 0.2624 to 0.0312 on
0.65-pixel bright bars. It also covers 0.3/1.25-pixel bars, dark bars, specular-like
color-only detail, the disable option, removed-detail expiry, and cancellation
by avatars, movement, reactivity, occluders, or changed lighting. The original
TAA GPU suite now has 76 passing checks, including sharpening at 0, 0.2, 1 and 2,
response, bounded contrast, and unchanged glow alpha. The then-default 0.20 sharpening
keeps thin-bar variation at 0.0339 (versus 0.0312 before sharpening), preserving
the stability improvement. The sharpening algorithm correction was shader-only;
the subsequent range extension to 2 also updates the renderer's C++ clamp and
the preferences slider, requiring the new Release executable. The Release build, startup sampler validation,
two-attachment history allocation, and checked-by-default TAA checkbox passed
at the login screen. Static-detail retention awaits in-world validation.

Real-world dancing avatars, hair, changing LODs, mirrors, camera movement, and
lower-end/AMD/Intel performance still need in-world validation. Synthetic tests
cannot promise zero ghosting in every Second Life scene. Flexible geometry,
animated textures, and layered transparency rely on conservative rejection;
they do not yet have complete per-vertex/layer motion. Tracking classic body
vertices and explicit per-material reactive output are useful future upgrades.

The design follows established motion-vector, clipping, and reactive-mask
principles described by [NVIDIA's temporal antialiasing research](https://research.nvidia.com/sites/default/files/pubs/2018-08_Adaptive-Temporal-Antialiasing/adaptive-temporal-antialiasing-preprint.pdf)
and [AMD's temporal rendering integration documentation](https://gpuopen.com/manuals/fidelityfx_sdk/techniques/super-resolution-temporal/),
including its discussion of short-lived protection for thin features.
This is a native viewer implementation, not an FSR integration.
