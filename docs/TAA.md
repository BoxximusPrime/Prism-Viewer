# Temporal antialiasing

Select **TAA** in Preferences → Graphics → Advanced Settings → Antialiasing,
or use the identical AA selector in the new Graphics → TAA tab. Existing AA
choices and saved preferences are retained. New profiles default to TAA at higher graphics tiers. All changes apply immediately; Cancel
restores the saved preference values. The old Low–Ultra AA quality selector
continues to apply only to FXAA/SMAA.

Graphics → **Post** now offers the same bounded sharpening filter independently
of antialiasing, with a checkbox (off by default) and a 0–2 strength slider
(default 1.50). It runs after spatial AA and scene effects, before photo grading
and HUD/UI composition, and also applies to snapshot renders. When enabled it
replaces TAA's presentation sharpening; the TAA slider is disabled until Post
sharpening is turned off. Existing CAS remains separate. The later color stage
means the result need not match pre-tonemap TAA sharpening exactly. No history
or additional render-target allocation is required. Work is in progress/uncommitted.

| Control | Default | Effect |
| --- | --- | --- |
| History weight | 0.76 | Base previous-frame contribution. Validated static-detail stabilization can raise it to 0.97; rejection can reduce it to zero. Earlier stability measurements below explicitly use a 0.97 base. |
| Motion protection | 0.85 | Reduces history during motion and color disagreement. Raise for clearer movement, at the cost of more shimmer. |
| Color clipping range | 1.20 | YCoCg neighborhood standard deviations. Lower values reject stale colors more tightly. |
| Transparency protection | 0.50 | Favors the current image where blended layers change the opaque image. Higher values reduce trails but can increase shimmer. |
| Sharpening | 1.50 | Range 0–2. Bounded output sharpening, outside history. Adds to general CAS sharpening. |
| Stabilize fine static details | On | Gives validated fine static geometry and highlights stronger accumulation and bounded retention through jitter and gentle camera motion. |
| Detect repeated flicker | On | Learns recurring luminance changes across frames and relaxes color rejection. Requires static-detail stabilization; can smooth untracked lighting animation. |
| Debug view | Normal | Motion/reactivity, actual history weight, clipping amount, detail protection, rejection reasons, or repeated-flicker protection. Session-only. |
| Freeze camera jitter (diagnostic) | Off | Uses zero camera offset while retaining TAA motion tracking and history blending. Session-only; changing it resets TAA and SSGI history. |

To isolate SSGI shimmer, keep **TAA** selected and compare **Freeze camera jitter
(diagnostic)** off and on in Graphics → TAA, allowing a moment for history to
rebuild after each change. Keep lighting, GI and sharpening settings the same.
Compare both a stationary view and a moving avatar. If freezing the offset
stops the shimmer, projection jitter or its interaction with upstream rendering
is implicated. If it persists, the TAA resolve/presentation path remains a
candidate. This is a diagnostic, not a finished stability fix; without the
sample sequence, TAA loses its normal subpixel sampling. Turn the checkbox off
after testing; it also resets to off when the viewer restarts.

The SSGI follow-up keeps jitter enabled and corrects three upstream sources of
instability: ray hits now use depth-derived physical normals, history depth
validation compares the previous surface plane rather than neighboring raw
view depths, and lighting-history clipping allows residual sample variance.
Physical normals occupy an RG16F attachment prepared once per frame; material
normals still orient the receiving hemisphere. The `--jitter` mode in
`scripts/tests/test_ssgi_gpu.py` exercises actual jittered geometry through the
production GI trace, filter, reconstruction, temporal filter and TAA resolve.
Live scene confirmation is pending; leave **Freeze camera jitter** off to test.

## Rendering

The latest follow-up adds reprojected luminance-reversal detection. It learns
recurring changes rather than relying only on the current neighborhood's
contrast. Confidence relaxes color clipping and its disagreement penalty;
depth validation, surface persistence, static eligibility, motion and reactivity
still limit protection. A quiet signal releases it within eight frames, and
isolated flashes or monotonic fades do not build confidence. A third history
attachment stores the previous unresolved luminance, signed change amplitude,
reversal evidence and quiet age. No extra rendering pass is added.

The user's final comparison found no improvement despite green detection on the
slats. The detector can be redundant where existing protection already removes
all clipping; it does not raise the history limit or recover depth-rejected
history. A production-shader check reproduces green detection with identical
normal output on/off. Investigation is paused/uncommitted; the option can be left
off. Installing this version requires a full restart for the buffer changes. See
[the temporal-detector audit](TAA-AUDIT.md#follow-up-multi-frame-flicker-detection).

The preceding dim-detail follow-up uses relative luminance contrast so stationary
slats, foliage and wires do not lose protection solely because their scene
lighting is dark. Background and expiry checks scale with brightness too, keeping
lighting changes and disappeared geometry responsive. The expanded GPU fixtures
reproduce the old history loss under 10–100× dimmer lighting with compensating
display exposure. The user's subsequent comparison showed only slight improvement. See
[the dim-detail audit](TAA-AUDIT.md#follow-up-dim-details-still-losing-history).

The follow-up window-slat/foliage fix changes the temporal resolve itself. Green
detail protection previously relaxed rejection but still admitted 24% of each
jittered frame at the shipped 0.76 history weight. Validated static detail now
uses up to 0.97 history, graded by the existing motion/reactive confidence. The
slider remains the base weight for unprotected surfaces; its value is unchanged.
Background validation uses the observed brightness range and a depth-based
background anchor, and foliage can retain intermediate depths within its known
surface bounds. A disappearing surface still expires even when the remaining
background is textured. See [the follow-up audit](TAA-AUDIT.md#follow-up-textured-slats-and-foliage)
for A/B measurements and limitations. This work is in progress/uncommitted.

September 17 review: PBR materials now filter specular roughness over the pixel
footprint before lighting. This reduces individual flashing highlights that are
too narrow for temporal samples to resolve reliably, including with a stationary
camera. Opaque/masked, blended/OIT, terrain and imported glTF materials share the
filter. It preserves authored roughness on constant normals and broadens the
lobe where normals vary, without additional textures or passes. Work is in
progress/uncommitted; see [the implementation audit](TAA-AUDIT.md) for the engine
comparison, measurements, appearance tradeoffs and remaining limits.

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
It reconstructs the current unjittered image in compressed HDR space, dilates closest-surface motion and
reactive coverage, rejects offscreen history and mismatching history depths,
clips compressed HDR history against a 3×3 YCoCg variance/min-max box, and lowers
history weight for fast movement and color disagreement. Every contributing
history tap is validated and compressed before filtering. Invalid colors are discarded, valid
colors are renormalized, and missing support reduces history weight. A wholly
invalid footprint still rejects history. History stores the
depth of the same nearest surface used for motion dilation, so jitter does not
invalidate stationary silhouettes by mixing foreground and background ownership.
Current reconstruction reuses the existing neighborhood fetches with bilinear
weights. Compressing each tap before interpolation prevents a small HDR highlight
from dominating the whole footprint; compression after raw HDR interpolation
cannot undo that spread. Flat HDR colors are preserved, while mixed bright/dark
pixels have a different, bounded response. The output is sharpened only for presentation;
scene glow alpha is retained separately from history depth.

Static details receive up to one eight-frame jitter cycle of protection from
color clipping and depth changes within known foreground/background bounds.
The resolve records lifetime, the surface depth bounds, and a background luminance
anchor in a second history attachment. Protection refreshes when contrast and
the retained surface bounds are observed again. Background texture contrast alone
cannot renew a missing foreground; its retained color clears within nine frames.
An expired lock is marked separately from never-protected background history,
so unchanged background color can still accumulate through tiny camera movement.
Metadata follows reprojected color, with per-tap surface and background validation. Stored surface
depths are transformed into the current camera's view space when a missing
feature retains its previous depth pair. The old 0.01-pixel motion cutoff is
replaced by graded confidence: coherent motion up to 0.5 pixels/frame retains
full protection, which fades to zero by 4 pixels/frame; differing neighboring
velocities reduce protection too. Changed background shading, new occluders,
and strongly reactive shading cancel protection. Faint composition retains
validated detail protection; reactivity between 0.05 and 0.25 smoothly removes it.
The usual reactive reduction of history weight still applies at every strength.
Static eligibility is tracked when batching geometry; rigged,
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
Repeated-flicker detection uses green for stronger confidence and blue for none.
Green does not measure its additional effect: existing detail protection can
already supply the same or stronger clipping relaxation.
Rejection reasons distinguish reset (gray), offscreen (blue), no matching depth
(red), partial depth support (yellow), and reactivity (magenta); green is valid.
These views rerun the resolve on demand after presentation consumes its output,
using the same inputs and uniforms. Diagnostic colors never enter history and
no extra persistent buffers are allocated. Sharpening settings and filters are
unchanged by the September stability fixes.

A pre-transparency HDR color snapshot provides conservative reactive detection
for blended hair, clothing, particles, water, and Exact OIT composition. It is
captured after post-deferred opaque/fullbright/masked surfaces and water haze,
before blended pools and the water surface. Atmospheric haze and volume fog
also update this reference, so opaque lighting is not mistaken for transparency.
Transparent layers do not have independent motion vectors; even static blended
textures can therefore trade stability for less ghosting at high protection.

History resets on AA/resource changes, resolution/projection changes, camera mode
changes, large camera cuts, region-origin shifts, skipped/long frames, relevant
TAA/AO setting changes, and entry into snapshot or diagnostic modes. Optional
shader/allocation failure disables jitter and leaves an unjittered current image.

GTAO advances its existing 64-frame sample index while the main image uses TAA;
the shaded result is accumulated by TAA. GTAO retains its spatial denoiser. An
independent AO history is not required by this implementation.

Five targets contain nine RGBA16F attachments: two history color/depth images,
two static-detail histories, two flicker histories, motion/previous depth/reactivity,
opaque color, and resolved/scratch color. These use 72 bytes per render pixel,
about 142 MiB at 1080p or 570 MiB at 4K. The flicker detector adds 16 bytes/pixel
(76 MiB at 3440×1440, 127 MiB at 4K) and up to four metadata fetches per eligible
pixel. These buffers allocate only when TAA is selected; disabling the detector
stops its analysis but retains the allocation for immediate on/off comparison.
There is an additional untextured geometry pass; total cost depends on visible
draw calls and skinned geometry as well as image resolution.

## Validation and remaining limits

September 17 multi-frame detector: 346 TAA checks (37 new) and 70 material checks
pass, including the existing disappearing-detail regressions. Release build,
settings/UI XML validation, staged-resource hashes and uncached startup shader
validation pass. The three new controlled patterns show 93–96% less variation
with mean brightness preserved, but the user reports no visible scene improvement.
Four subsequent overlap checks confirm green confidence can coexist with zero
additional effect (41 detector checks now pass). Work is paused/uncommitted;
frame-time cost remains unmeasured. See the detector audit above for details.

September 16 stationary-flicker fixes are in progress/uncommitted. The report
reproduced with a still camera and persisted with GTAO disabled. A follow-up video
shows fluctuations around both distant railings/stairs and foliage while the sky
is nearly constant. The user reports little change from sharpening, partial
improvement from the initial shader fixes, and much better stability on nearby
blended textures with transparency protection at 0.1–0.2.

The follow-up exposed a pipeline ordering error: the opaque reference was taken
before post-deferred fullbright/masked surfaces, atmospheric haze and volume fog.
The resolve compared that incomplete reference with the final lit scene. Ordinary
opaque surfaces could therefore receive strong reactive rejection, particularly
at distances with stronger haze. The capture now follows opaque post-deferred
passes and water haze, and both images receive the same later haze/fog transforms.
Actual alpha composition remains excluded from the reference.

`scripts/tests/test_taa_composition_gpu.py` covers the C++ pass ordering and runs
the production haze, fog-composite and TAA shaders. The atmosphere dependency uses
a deterministic test preset. With identical resolve code, changing only the
reference to include the missing contribution gives:

| Stationary synthetic input | Incomplete reference | Correct reference | Reduction |
| --- | ---: | ---: | ---: |
| Thin geometry through atmospheric haze | 0.11893 | 0.00498 | 95.8% |
| Post-deferred fullbright masked detail | 0.23927 | 0.00830 | 96.5% |
| Thin geometry through volume fog | 0.13809 | 0.00584 | 95.8% |

These are mean per-pixel peak-to-peak bounded brightness over the last 16 of 96
frames, before presentation sharpening, using history 0.97, motion 0.85,
clipping 1.20, transparency 0.50 and fine-detail stabilization. Corrected opaque
cases retain approximately 0.97 history weight instead of 0.27–0.37. A separate
blended-layer case verifies that transparency protection still reduces history.
These controlled scenes reproduce the integration fault; the compressed clip
alone cannot identify the cause of each fluctuating pixel, and an in-world retest
is still needed.

All six TAA suites pass 208 checks, including the 12 new composition checks;
the volume-fog suite also passes 46 GPU checks on the RTX 5090. The Release build
passed and the staged resolve shader matches the source. This renderer change requires
the new executable, not only a shader reload. It adds no persistent buffers or
settings. With TAA active, atmospheric haze draws once more into its reference;
active volume fog adds a composite and copy using existing TAA scratch storage,
without repeating fog integration. In-world performance is not yet measured.

The initial shader investigation reproduced and corrected two independent
resolve problems without GTAO:

- A hard `reactive < 0.01` eligibility test disabled all thin-detail protection
  under faint post-deferred composition, even when it was static. A 4% gray
  overlay on thin bars triggered this failure. Protection now fades with
  reactivity while preserving depth, motion, background and lifetime checks.
- Both current reconstruction and history reprojection filtered raw HDR before
  compression. They now filter individual compressed samples, consistent with
  temporal accumulation and neighborhood clipping. A quarter-pixel contribution
  from a 1024-intensity highlight previously approached white after compression;
  it now contributes a quarter of that highlight's bounded color.

Measured on the RTX 5090 at the reported settings (history 0.97, motion 0.85,
clipping 1.20, transparency 0.50, sharpening 1.50, static details on):

| Stationary synthetic input | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| Thin bars with 4% gray composition | 0.29712 | 0.01459 | 95.1% |
| 0.65-pixel HDR specks, peak 1024 | 0.01486 | 0.00414 | 72.2% |
| Thin bars on a textured background | 0.09207 | 0.07172 | 22.1% |
| Dense 1.4-pixel-period bars | 0.06320 | 0.05457 | 13.7% |
| High-frequency checker texture | 0.05657 | 0.05510 | 2.6% |

The metric is mean per-pixel peak-to-peak `red / (1 + red)` over the final
16 of 96 frames, including TAA presentation sharpening. It is a bounded proxy
for display brightness, not the viewer's actual tonemapper. These tests exclude
CAS, bloom, exposure and GTAO. The measurements establish specific improvements,
not the cause or cure of every pixel in the reported in-world scene.

The initial five TAA suites pass 196 GPU checks, including 52 stationary-flicker
checks in `scripts/tests/test_taa_flicker_gpu.py`. The new tests also check mean
feature coverage (so losing detail cannot masquerade as stability), current and
history HDR interpolation, image borders, gradual reactivity, animated/untracked
rejection, and removed-detail expiry. The analytic edge reference now uses the
same bounded-color filtering convention; the high-history test measures after
80 settling frames, since 48 frames at 0.97 still retain 23% of the reset frame.
The checkbox test compares enabled/disabled stability instead of requiring a
fixed minimum amount of flicker from the old reconstruction filter.

The initial shader-only Release build passed and the staged resolve shader matched
the source. Those changes add no render targets, passes, samplers, settings, or texture
fetches. Existing settings, including sharpening, remain unchanged. Restart the
Release viewer to load the staged shader. In-world confirmation is pending;
small bright mixed-coverage details will be less over-bright than before.

The deeper review identified several remaining limits:

- **Sharpening amplifies residual variation.** `taaCopyF.glsl` applies an unsharp
  adjustment of `2 * strength`, then allows overshoot outside the local range.
  At 1.50 this can substantially amplify fine texture fluctuations, and the
  independent CAS pass can sharpen them again. After this fix the checker test
  measures 0.02319 with sharpening off, 0.02922 at 0.20 and 0.05510 at 1.50.
  This does not establish sharpening as the cause of the reported video; the
  user's sharpening comparison produced little change. Saved preferences and
  shipped defaults were not changed.
- **Actual blended layers still use a conservative reactive mask.** The opaque
  reference correction removes false rejection from fullbright/masked surfaces
  and haze/fog. Strong static alpha composition can still reduce history, because
  these layers lack independent depth and motion. The user's 0.1–0.2 transparency
  setting favors their stability at the cost of possible trails on moving layers.
  A material-provided reactive/composition signal could better distinguish them.
- **PBR specular filtering was added September 17.** The earlier material path
  only normalized sampled normals and imposed a fixed punctual-light roughness
  floor. It now filters roughness using material normal derivatives before
  lighting; see [the audit](TAA-AUDIT.md) for coverage and measurements. Legacy
  shininess materials and variance already lost in texture mips remain outside
  this change. Water retains its specialized filtering.
- **The new luminance detector has limited scope.** It relaxes color rejection
  after repeated brightness reversals on eligible static surfaces. It cannot
  recover history rejected by depth or replace independent transparent-layer
  motion. Unmarked shader/lighting animation can resemble aliasing and be
  smoothed. Controlled tests cover flashes, fading, motion, reactivity, depth
  changes and removal; actual-scene benefit and frame-time cost remain unconfirmed.

These are distinct improvements seen in established implementations: AMD
documents bounded-color filtering, separate lock/reactivity controls, luminance
history and noise-aware RCAS in its [FSR2 implementation guide](https://gpuopen.com/manuals/fidelityfx_sdk/techniques/super-resolution-temporal/).
Filament documents [material specular antialiasing](https://google.github.io/filament/main/materials.html)
for preserving distant glossy highlights. These sources inform the remaining
options; this change implements neither FSR nor Filament.

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
