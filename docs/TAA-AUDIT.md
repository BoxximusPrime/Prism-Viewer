# TAA and highlight stability audit — September 17, 2026

Status: paused / uncommitted after the user's final scene comparison. The prior
dim-detail correction produced only slight improvement, and the new detector
produced no visible improvement despite green detection on the slats. The build
passed 346 TAA and 70 material checks, Release staging and uncached startup.
Four additional overlap checks pass (41 detector checks total); frame-time cost
remains unmeasured.

The reported remaining symptom is isolated bright pixels fluctuating even with
a completely stationary camera. A shader-level reproduction confirms that
undersampled PBR highlights can produce that symptom with correct zero motion
vectors, valid depth and functioning history accumulation. This establishes a
specific failure mode; it does not identify every pixel in the reported scene.

## Follow-up: multi-frame flicker detection

**Scene result:** the user reports no on/off difference, while the diagnostic is
green on the slats. Source tracing confirms that the checkbox and metadata reach
the normal resolve, whose result feeds presentation and tone mapping. A focused
production-shader test reproduces green detection (1.0) with exactly zero
difference in normal sharpened output on a high-contrast checker. Existing detail
protection already removes all clipping there; `max(existing_protection, 0.95 *
flicker_protection)` adds nothing. The disagreement penalty is already zero, and
the 0.97 history limit and depth rejection remain unchanged. Green measures
detection, not additional output contribution. This can explain the report,
without identifying every in-world pixel's remaining source of flicker. Earlier
uniform-pattern tests measured a case where old protection was absent, limiting
their relevance to already-protected slats. Investigation stops here as agreed;
no additional shader change or rebuild follows this comparison.

The user chose this final focused attempt after the previous fixes left visible
flicker and required transparency protection at zero for nearby blended textures.
No existing slider defaults or saved preferences are changed. A new enabled-by-default
**Detect repeated flicker** checkbox permits an immediate comparison; it requires
**Stabilize fine static details**. Restart the new Release executable because
this change adds C++ buffer/sampler integration as well as shaders.

A third RGBA16F history attachment stores previous unresolved compressed luminance,
signed recent change amplitude, reversal evidence and quiet age. Repeated changes
of direction build confidence; large new jumps reset it. Quiet intervals within
the eight-frame jitter cycle retain evidence, while eight quiet frames clear it.
One isolated flash or a monotonic fade cannot activate protection. Metadata follows
the strongest accepted reprojected history tap, preserving the sign of changes
instead of bilinearly averaging it.

Confidence relaxes up to 95% of color clipping and removes the corresponding
color-disagreement penalty. It does not bypass depth rejection. Existing static
eligibility, coherent-motion confidence and reactivity remain authoritative.
Both retained surface bounds must still be present before their flicker evidence
can be reused. This last requirement fixed a regression found during validation:
without it, a disappeared foreground could carry confidence into an oscillating
background texture and delay color cleanup.

The production-shader GPU fixture measures three spatially uniform brightness
patterns with no neighborhood contrast for the previous static-detail rule to
protect. At shipped settings, including presentation sharpening 1.5, it records
the last 32 of 160 frames. Values are peak-to-peak `red/(1+red)`:

| Pattern | Detector off | Detector on | Reduction |
| --- | ---: | ---: | ---: |
| Alternating brightness | 0.40576 | 0.01658 | 95.9% |
| One impulse per eight frames | 0.40576 | 0.02889 | 92.9% |
| Eight-phase shading | 0.45798 | 0.02467 | 94.6% |

Mean bounded brightness remains within 0.001 of the sampled temporal mean in
these fixtures. They establish behavior for recurrent shading rejection, not
that the in-world slats have the same cause. The existing textured slat/foliage
cases also exercise disappearing objects, sky wires and dim lighting. The new
suite checks release after settling, a later isolated flash, animated/untracked
surfaces, fast motion, new occluders, reactive overlays, camera cuts and toggle reset.
All 37 new checks, 309 existing TAA checks and 70 material checks pass on an RTX
5090. The Release build, settings/UI XML checks and source/staged-resource hashes
pass. An isolated startup with shader caching disabled compiled TAA and validated
its sampler channels using separate preferences and automatic login disabled.

The two extra history attachments cost 16 bytes per render pixel: about 76 MiB
at 3440×1440 or 127 MiB at 4K. They remain allocated with TAA selected even when
the detector is disabled. There is no extra full-screen pass, but eligible pixels
read up to four extra metadata texels and the resolve writes another attachment.
Frame-time cost is not yet measured. Unmarked lighting or shader animation can
look like aliasing and be smoothed. Depth-rejected pixels and transparent layers
without reliable motion remain limitations. The final scene comparison showed
no benefit, so this investigation is paused as requested by the user.

## Follow-up: dim details still losing history

The user confirmed reloading after the preceding change and still reported
flicker. The supplied 87-frame video shows a changing **detail-protection mask**;
it does not measure variation in the final scene color. The subsequent history
weight image shows red on the slats, and rejection diagnostics show partial or
missing depth support on slats/wires, plus reactive rejection in window interiors.
The earlier fix is therefore **not confirmed to solve the in-world scene**.

A lighting-scaled reproduction exposed a gap in the previous bright fixtures:
detail detection required a fixed 0.05 difference in compressed scene luminance.
At 100 times dimmer lighting, the same slats rejected history on 43.7% of samples,
although compensating display exposure made them just as visible. The detector
now requires 10% local contrast, with a 0.0001 near-black floor. Background
agreement and expired-color checks also scale their tolerance with brightness;
otherwise relaxing dark-detail eligibility could preserve stale dark colors
through actual lighting changes or removal.

The expanded production-shader test covers the original five fixtures, dim slats
and layered leaves at 0.1/0.01 lighting, and 0.3-pixel dark wires against sky.
Display measurements use `red/(light+red)` after TAA sharpening. The coverage
reference averages RGB in the resolve's bounded accumulation space before
applying the display conversion; averaging already-tonemapped phases would
bias that reference. CAS, bloom and the viewer tonemapper remain outside the test.

| Input / light multiplier | Mean variation before | After | Rejected samples before / after |
| --- | ---: | ---: | ---: |
| 0.65 px slats / 0.1 | 0.03080 | 0.00677 | 7.5% / 0% |
| Layered leaves / 0.1 | 0.02523 | 0.00220 | 24.6% / 0% |
| 0.65 px slats / 0.01 | 0.19413 | 0.00681 | 43.7% / 0% |
| Layered leaves / 0.01 | 0.02551 | 0.00218 | 24.6% / 0% |
| 0.3 px wires / 0.1 | 0.08312 | 0.00224 | 44.3% / 0% |

"Before" here is the preceding textured-background/static-accumulation fix,
not the original implementation. Mean coverage differs from the reference by
less than 0.002; spatial contrast is within 4% for all ten cases. The A/B suite
reads actual history weights from the blend diagnostic, including sky where
negative-zero depth cannot record a rejection sign. All ten corrected fixtures
retain approximately 0.97 history at the shipped settings. The A/B suite
passes 115 checks, including lighting changes, expired colors, removed wires
and textured-background cleanup. All 214 existing TAA and 70 material checks
also pass. The Release build passed and the staged shader matches source by
SHA-256. This follow-up changes only the resolve shader and adds no runtime
state, settings or passes. The actual scene comparison is pending; the synthetic
correction alone cannot establish that every observed rejection has this cause.

## Follow-up: textured slats and foliage

The user restarted the client and reported that the first material change did
not fix the distant window slats and leaves. The supplied TAA diagnostic image
shows the affected detail mostly green. This demonstrates that qualifying for
the old clipping/depth protection alone was insufficient; it does not establish
that every affected pixel has valid motion or protection on every frame.

A production-resolve reproduction found three interacting problems:

- Protected pixels still admitted 24% of each jitter phase with the shipped
  history weight of 0.76. Protection relaxed rejection but did not strengthen
  accumulation.
- The brightness endpoint test was unstable on textured backgrounds. Its
  majority-brightness heuristic could also select the foreground slat as the
  background anchor, rejecting history whenever that slat missed a jitter sample.
- Foliage could expose more than two surface depths in the 3×3 footprint. Testing
  only equality with the depth extrema discarded valid intermediate surfaces.

The resolve now raises the base history weight toward 0.97 in proportion to
static-surface confidence. This includes low-contrast edges of a detail: gating
accumulation on the contrast threshold made softer highlight edges flicker.
Clipping/depth exceptions still require the stricter lifetime and surface checks.
Existing eligibility, velocity disagreement, speed, depth and reactive controls
still reduce or cancel history. Saved settings and their
defaults are unchanged; the history slider description now calls it a **base**
weight, and disabling static stabilization restores its original cap.

The background anchor comes from the farthest depth samples when the footprint
spans distinct depths. It must remain inside the current luminance range with the
existing tolerance, rather than match an extremum. Known depth intervals accept
intermediate layers; sky zero remains a special case, never a numeric near bound
that could admit arbitrary nearer surfaces. Ordinary depth validation is unchanged;
these exceptions require the existing static eligibility and bounded lifetime.

Lifetime refresh now also requires the retained surface bounds to remain visible.
Thus texture contrast behind a removed object cannot renew its lock indefinitely.
An expired lock with visibly different retained color is flushed after eight
frames, while unchanged background history survives subpixel camera movement.
No buffer, pass, sampler, C++ layout change or new preference is added.

The new `test_taa_fine_details_gpu.py` compares the previous and current resolve
with identical jittered colors, D24 depths, production camera motion and sampler
bindings. It uses 96×64 RGBA16F images, the shipped history 0.76 and sharpening
1.50, and the last 16 of 144 frames. Values below are per-pixel peak-to-peak
`red/(1+red)` **after TAA presentation sharpening**; CAS, bloom and viewer tone
mapping are not included.

| Input | Mean before | Mean after | Reduction | Worst before | Worst after |
| --- | ---: | ---: | ---: | ---: | ---: |
| Textured slats, 0.65 px | 0.10630 | 0.00625 | 94.1% | 0.57404 | 0.03822 |
| Textured slats, 1 px | 0.05107 | 0.00632 | 87.6% | 0.37361 | 0.05514 |
| Textured slats, 3 px | 0.04276 | 0.00520 | 87.8% | 0.35272 | 0.04920 |
| Textured slats, 5 px | 0.03351 | 0.00407 | 87.8% | 0.34127 | 0.05644 |
| Layered cutout leaves | 0.01866 | 0.00214 | 88.5% | 0.31146 | 0.02327 |

Spatial contrast remains within 1% of the average unaccumulated jitter-cycle
reference in all five cases; mean bounded brightness differs by less than 0.002.
The 64 A/B checks include both average and worst-pixel stability, coverage,
contrast, textured-background removal, base-weight control, disabled stabilization,
animated/untracked eligibility, fast motion and newly covering depth. Full
results are saved to `tmp/taa-tests/fine-detail-results.json`.

The final shader passes all 278 TAA checks (214 existing plus 64 new A/B checks)
and all 70 PBR material checks. The Release build passed, and the staged resolve,
settings descriptions and preferences panel match source byte-for-byte. The
material suite retains its original relative-improvement assertions; both 0.76
and 0.97 now get the stable accumulation on eligible static highlights.
An isolated uncached Release startup loaded TAA and validated all sampler channels,
then shut down cleanly; the user's running viewer and saved settings were preserved.

This is a measured correction to the existing static stabilization, not TSR's
multi-frame luminance detector. Stronger history may respond more slowly to local
shading changes that pass the background/depth tests. Animated or alpha-blended
foliage without reliable motion remains subject to the existing restrictions.
The subsequent reload comparison did not fix the supplied in-world scene; see
the dim-detail follow-up above. The earlier PBR material filter is retained
for its separate, tested highlight failure mode.

## Pipeline review

The review follows `beginTAAFrame`, motion generation, the opaque reference,
`resolveTAA`, presentation, exposure, bloom, tone mapping, CAS and DoF. It also
checks the material inputs to deferred and forward lighting.

| Area | Viewer implementation | Assessment |
| --- | --- | --- |
| Jitter and coordinates | Eight Halton samples; main world projection only; motion removes current jitter; history is unjittered. | The conventions agree. UI, shadows, probes and culling remain separate. A longer sequence alone cannot filter a very narrow specular lobe. |
| Motion and disocclusion | Camera reconstruction, visible-depth object and skinned passes, nearest-surface dilation, previous view depth. | Substantial modern TAA foundation. Classic body deformation, flexible geometry and independent transparent layers remain incomplete. |
| History reconstruction | Four bilinear taps, per-tap depth rejection, accepted-color renormalization. | Avoids mixing rejected foreground colors into valid history. Bilinear reprojection loses detail under repeated subpixel movement; higher-order filters would need equivalent per-tap validation. |
| HDR accumulation | Each sample is bounded before current/history filtering; YCoCg variance/min-max clipping. | Handles bright outliers, but cannot reconstruct a highlight that shading rarely samples. Bounded accumulation also changes mixed-coverage HDR energy. |
| Static details | Reprojected lifetime, surface-depth pair, background anchor, motion and reactive confidence. | Follow-ups fix textured-background validation, intermediate depths and insufficient accumulation. Separate luminance-reversal metadata now addresses recurrent shading rejection. |
| Transparency reference | Captured after opaque/fullbright/masked contributions; matching atmospheric haze and volume fog. | Earlier integration fixes remain covered by GPU tests. Real transparent layers still depend on conservative reactivity. |
| Presentation | TAA unsharp filter, then exposure/bloom/tone mapping and optional CAS; DoF depth uses jitter-adjusted coordinates. | History is protected from sharpening feedback, but presentation can magnify residual variation and CAS can sharpen again. Scene glow alpha is preserved from current input, not accumulated as RGB history. |
| Material sampling | Authored PBR roughness plus a fixed punctual-light floor. | Missing normal-variation filtering was a concrete gap upstream of TAA. This change addresses it. |

## Comparison with other engines

Unity HDRP combines motion/history reconstruction with an adaptive variance box:
high spatial and temporal contrast can relax clipping, with motion limiting that
relaxation. Its material library separately implements normal-variance specular
filtering. The viewer already has the former pipeline's basic ingredients, but
its static-detail rule is different and it lacked the material filter.
[HDRP temporal shader](https://github.com/Unity-Technologies/Graphics/blob/master/Packages/com.unity.render-pipelines.high-definition/Runtime/PostProcessing/Shaders/TemporalAntialiasing.hlsl),
[Unity material filtering](https://github.com/Unity-Technologies/Graphics/blob/master/Packages/com.unity.render-pipelines.core/ShaderLibrary/CommonMaterial.hlsl).

Unreal TSR additionally tracks luminance changes across frames to detect repeated
flicker and selectively relax shading rejection. Its documentation also describes
disabling that heuristic for moving objects, significant parallax and materials
with pixel animation. The new viewer detector adopts the narrower idea of
tracking repeated luminance changes, using its existing static eligibility,
surface validation and reactive safeguards. It is not a port of TSR's analysis.
[Epic's TSR documentation](https://dev.epicgames.com/documentation/en-us/unreal-engine/temporal-super-resolution-in-unreal-engine).

Epic also documents dedicated thin-geometry handling for foliage and repeating
windows/railings. It accumulates partial coverage, checks for scene changes,
stabilizes nearby clusters, and separately detects coherent edges/contrast lines.
Translucent overlays reduce that protection. Dense parallel patterns can still
lose coverage across an entire neighborhood, leaving no spatial evidence that a
feature remains. This corroborates the reported failure category; it does not
prove which rule rejects a particular viewer pixel. Those additional TSR passes
are not implemented here.
[Epic's thin-geometry detection](https://dev.epicgames.com/documentation/unreal-engine/thin-geometry-detection-with-temporal-super-resolution).

AMD FSR2 separates reactive blending from transparency/composition history
protection, and uses luminance instability information. It recommends explicit
material signals where possible rather than relying solely on automatic color
differences. The viewer's opaque-reference mask is a useful approximation, not
equivalent layer motion or material metadata.
[FSR2 implementation guide](https://gpuopen.com/manuals/fidelityfx_sdk/techniques/super-resolution-temporal/).

Filament exposes specular antialiasing independently of temporal antialiasing,
with variance and threshold controls, specifically to stabilize glossy
highlights. This supports addressing the signal before history accumulation.
[Filament material specification](https://google.github.io/filament/main/materials.html).

These systems also serve different resolution and content requirements. A
native-resolution OpenGL viewer does not become equivalent to TSR or FSR by
copying one heuristic.

## Implemented changes

`globalF.glsl` now provides `filterPBRRoughness`. It estimates normal variation
from screen derivatives of the normalized material shading normal and adds a
bounded filter contribution to the squared GGX roughness parameter:

```
kernel = min(0.5 * (dot(dNdx, dNdx) + dot(dNdy, dNdy)), 0.04)
filtered_perceptual_roughness = fourth_root(min(roughness^4 + kernel, 1))
```

This is the normal-variance approximation used by the referenced Unity material
implementation, with a half-pixel standard deviation and a 0.2 kernel threshold.
It is evaluated while shading geometry, before alpha, mirror, water or overlay
discard. Evaluating derivatives on a deferred normal buffer would confuse
unrelated neighboring surfaces with material variation.

The filter is applied once in opaque/masked PBR, forward PBR including Exact OIT,
PBR terrain, and imported glTF lit materials. Deferred lighting, local lights and
reflection-probe selection all receive the resulting roughness. Constant normals
preserve authored roughness, including zero. Normal maps retain their ordinary
sampling; no additional texture fetch, target, pass, setting or geometry draw is
introduced. This material correction applies with other AA modes as well.

The imported glTF alpha path also multiplied material roughness and metallic
factors a second time after preparing ORM. It now uses the prepared values once,
matching its opaque path. GPU checks cover fractional factors with ordinary
alpha and Exact OIT output.

Legacy Blinn-Phong/shininess materials are not changed: their lookup-table
parameterization is different from perceptual GGX roughness. Water keeps its
existing specialized filter. This filter also does not recover variance already
lost inside normal-map mip levels; that requires texture processing or additional
normal statistics, as distinguished in Unity's material implementation.

## Measurements and validation

The material-only measurements in this section predate the fine-detail resolve
follow-up above. Its stronger static accumulation now applies at either base
weight; use the follow-up section for the current slat/foliage results.

The new `scripts/tests/test_specular_aa_gpu.py` runs the production opaque shader,
normal encoding, GGX BRDF, TAA resolve and presentation shader on an RTX 5090.
The reference disables only the new roughness helper. Both paths use 96x64
RGBA16F targets, the eight jitter phases, sharpening 1.5, motion protection 0.85,
clipping 1.20 and transparency protection 0.50. Measurements use frames 80–95
of 96 in the same 16x16 region around the highlight.

The table reports the **largest individual pixel peak-to-peak change** in
`red / (1 + red)`, a bounded display proxy. This deliberately targets the reported
flashing-pixel symptom. It is not the viewer's tonemapper or a full image-quality
score.

| Highlight | History | Before | After | Reduction |
| --- | ---: | ---: | ---: | ---: |
| Geometry normals, roughness 0.04 | 0.76 | 0.23748 | 0.06842 | 71.2% |
| Geometry normals, roughness 0.04 | 0.97 | 0.04914 | 0.01624 | 67.0% |
| Geometry normals, roughness 0.08 | 0.76 | 0.22101 | 0.09139 | 58.6% |
| Geometry normals, roughness 0.08 | 0.97 | 0.04085 | 0.01290 | 68.4% |
| Geometry normals, roughness 0.15 | 0.76 | 0.25364 | 0.04654 | 81.7% |
| Geometry normals, roughness 0.15 | 0.97 | 0.05417 | 0.01506 | 72.2% |
| Texture normals, roughness 0.04 | 0.76 | 0.20728 | 0.07012 | 66.2% |
| Texture normals, roughness 0.04 | 0.97 | 0.03692 | 0.01845 | 50.0% |

The lobe becomes broader and retains more visible highlight contribution.
Consequently, mean variation across the entire region does **not** uniformly
decrease: for the first case it changes from 0.00221 to 0.00271. The improvement
is smaller individual flashes, not uniformly lower error on every pixel. Both
metrics and the background-subtracted highlight contribution are saved in
`tmp/taa-tests/specular-results.json`. The contribution check prevents deleting
the highlight from passing as a stability improvement; it does not prove exact
radiometric energy conservation. Bloom, exposure, CAS and frame-time cost are
not measured by this harness.

The tests also cover flat/matte materials, the roughness cap, unaffected metallic
and occlusion values, alpha-mask helper lanes, forward/OIT and imported glTF
agreement, and compilation of all 16 terrain detail/mapping/paint combinations.
The final run passes 70 specular-AA checks, 214 checks across the six existing
TAA suites, and the transparency/projector lighting suite (72 lighting cases,
180 projector cases, plus overlay rejection checks). The imported glTF tests
also cover opaque/unlit depth-only output so normal filtering does not change
the SSS depth pass.

The shipped history default is **0.76**, not the **0.97** used in previous reports.
Before the fine-detail follow-up it gave each accepted current frame 24% weight instead of 3%, before further
rejection. In the unchanged thin-bar test, stationary variation before sharpening
is 0.05228 at 0.76 versus 0.00830 at 0.97. The old stability suite read defaults
but asserted a high-history bound; it now explicitly tests both the historical
reference and the shipped default. Saved preferences and defaults are unchanged.

## Remaining priorities

The final comparison is complete: the detector did not visibly improve the
supplied scene. Further tuning is paused. Transparent-layer metadata, missing
deformation motion and reconstruction filters remain possible future work,
outside this attempt.
