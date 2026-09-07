# Dense foliage shadow investigation

Status: shared legacy alpha shader optimization implemented; in-world timing and
visual verification pending. Reported scene appears alpha-blended; face mode is
not confirmed.

## Findings

- `class2/deferred/alphaF.glsl` sampled directional shadows before its existing
  texture/vertex-alpha discard. Transparent holes in overlapping cards could do
  filtered shadow work before being thrown away. Move the lookup after those
  checks in the normal shading branch, shared by ordinary and Exact OIT rendering.
  Keep all cutoffs, blend factors, and shadow filter taps unchanged.
- `class1/deferred/shadowUtil.glsl` performs five comparison-texture lookups per
  selected sun cascade, with overlapping cascade transitions. Alpha blending pays
  this per surviving layer, rather than once per final screen pixel. The actual
  GPU savings from reordering depend on shader compilation and fragment execution.
- `LLPipeline::generateSunShadow` can render four sun cascades and up to two spot
  maps. Each map culls and submits scene geometry separately. Shadow maps scale
  with viewport resolution and `RenderShadowResolutionScale`.
- The legacy and PBR shadow-casting alpha shaders already test texture alpha early.
  They still rasterize overlapping cards in each applicable map. Camera occlusion
  cannot simply be reused: an object hidden from the camera may cast a visible
  shadow. Any further culling or update-rate changes need a separate correctness
  and performance investigation.
- PBR's masked forward path already rejects alpha before shadow sampling. Legacy
  material blending has different output-alpha behavior, including specular glare;
  it cannot safely inherit the simple shader's discard as a blanket optimization.

The shadow toggle disables both casting and receiving costs; it does not alone
identify which dominates. 120 to 20 FPS corresponds to about 8.3 to 50 ms/frame,
but frame caps and CPU/GPU overlap prevent attributing the entire difference to
one pass without GPU timing.

## Verification

1. Run `python scripts/tests/test_alpha_shadow_shader.py` with `glslangValidator`
   on PATH. This checks 14 GLSL variants, including indexed, skinned, avatar,
   impostor, HUD, sun-shadow and Exact OIT combinations. It does not link the
   viewer's complete driver programs or test rendered output.
2. Compare the baseline and updated Release builds in the same grass scene with
   identical camera, sun direction, resolution, shadow settings, and particle
   limit. Let shaders and textures settle. Record several frame-time samples from
   a distance and from inside the grass, with VSync/frame caps disabled for timing.
3. Compare ordinary alpha and Exact OIT. Check card edges, grass shadows on the
   ground, shaded grass, water crossings, avatars, and classic lighting. Appearance
   and cutoffs should match. Shader cache revision changes force recompilation.
4. If the slowdown remains, compare shadow detail 2 (sun/moon plus projectors) with
   1 (sun/moon only). A large change implicates projectors and their maps.
5. At fixed shadow detail, temporarily halve `RenderShadowResolutionScale` from
   its original positive value. This roughly quarters each map's pixel count,
   but does not change the per-layer sun filter tap count. A large improvement
   points toward shadow-map rasterization/bandwidth or cache behavior, not proof
   of a single cause. Restore original settings after the comparison.
6. For direct attribution, collect a GPU trace of `generateSunShadow`/`renderShadow`
   versus the alpha draw/capture pass. The source already has GPU zones, but this
   workspace currently has `USE_TRACY_GPU=OFF`; its CPU Tracy timings are not GPU
   measurements. A GPU-enabled profiling build or external GPU profiler is needed.

No FPS improvement is claimed until the same scene has been retested.

## CPU follow-up

Implemented three removals of repeated work, preserving caster geometry, draw
order, shadow resolution, and per-frame map updates:

- `LLRenderPass::applyModelMatrix` skips skin-scattering setting/uniform lookup
  during shadow rendering; the shadow shaders do not write that G-buffer marker.
- `LLPipeline::postSort` does not construct forward-alpha group lists for shadow
  cameras. Casting uses the render map, which is still populated normally.
- `LLPipeline::renderAlphaObjects` initializes its shader and map-constant uniforms
  on the first draw and shader transitions, instead of every batch. A fresh local
  cache for each invocation preserves sun/spot-map dimensions and entry from masked
  rendering. Rigged skin palettes remain separate for legacy and PBR shaders.

`python scripts/tests/test_shadow_alpha_submission.py` compiles and executes the
production submission function against recording draw/GL stubs. It verifies draw
order, static/rigged and legacy/PBR routing, unavailable skin data, shader reuse,
map-state refresh, and empty passes. It is not an in-world shadow or FPS test.

Unchanged uniform uploads and VBO bindings were already cached. Shadow material
binding already skips normal, metallic/roughness, and emissive maps. Those are not
newly eliminated OpenGL calls. The savings above are CPU traversal/setup work.

The larger remaining candidates require timing: per-map culling, draw-map building,
draw submission, and rigged palette uploads. Separately, Exact OIT performs a
synchronous capture-metadata readback in `validateCapture`; CPU time waiting there
is GPU synchronization, not evidence that shadow culling itself is expensive.

For a stationary in-world scene, bundled Tracy tools can collect CPU zones without
rebuilding. Run from the repository root with the viewer running:

```powershell
New-Item -ItemType Directory -Force build-vc170-64/shadow-profile | Out-Null
& build-vc170-64/packages/bin/tracy-capture.exe -a 127.0.0.1 -s 10 -o build-vc170-64/shadow-profile/shadows-on.tracy
& build-vc170-64/packages/bin/tracy-csvexport.exe -e build-vc170-64/shadow-profile/shadows-on.tracy > build-vc170-64/shadow-profile/shadows-on-self.csv
```

Repeat with shadows disabled using distinct output names. Compare per-frame CPU
time and call counts, including `generateSunShadow`, `updateCull`, `stateSort`,
`postSort`, `renderAlphaObjects`, and `Exact OIT validation readback`. Profiling can
affect frame times, so compare both runs with the same profiler configuration.
CPU zones can include driver waits; GPU attribution still needs GPU profiling.

## Additional opaque-caster and fitting work

- Plain, non-rigged shadow depth now combines consecutive draws only when they
  share a vertex buffer and model matrix and their index ranges are adjacent.
  It preserves index order and vertex bounds, does not modify stored draw infos,
  and respects the existing macOS draw-range limits. Other shaders, rigged draws,
  and the separately submitted PBR/double-sided paths keep their existing behavior.
  Savings depend on how often the scene's buffers contain compatible split batches.
- Disabled sun splits now skip `getVisiblePointCloud`, avoiding a receiver-bound
  traversal that was previously performed before checking `RenderShadowSplits`.
  Their maps are still cleared. This helps only when some splits are disabled.
- Shadow fitting reserves capacity for its bounded corner/intersection candidate
  list and its transformed point list, avoiding repeated vector growth allocations.

Run `python scripts/tests/test_shadow_batching.py` to execute the production batch
loop with recording stubs. The fixture drops from nine draws to six with identical
indices/transforms, and checks gaps, buffer/transform changes, rigged boundaries,
other shaders, empty/null entries, unchanged input metadata, and platform limits.
This is a submission test, not a measured in-world draw reduction or FPS result.

In-world checks should include static multi-material buildings, moving linksets,
rigged attachments, PBR double-sided surfaces, foliage, projector shadows, and
shadow split settings 0 through 3 (restore the initial value afterward). Watch for
missing geometry, changed silhouettes, and stale disabled-split shadows. Compare
GPU-capture draw counts and CPU time with identical scene/camera settings.

## Follow-up from shadows-on/off Tracy captures

The supplied captures averaged 15.14 ms/frame with shadows and 9.90 ms without.
Shadow generation accounted for 3.56 ms/frame on the CPU; Exact OIT validation
readback averaged 6.41 ms with shadows and 4.61 ms without. The readback can wait
for preceding GPU work, so these numbers do not isolate GPU transparency cost.

Additional work in progress:

- Non-rigged legacy masked shadow batches combine consecutive index ranges with
  identical vertex buffer, model matrix, texture, texture matrix, indexed texture
  list (when enabled), and alpha cutoff. Only the existing mask/fullbright-mask/
  tree shadow shaders use this path. Rigged and PBR submission paths are retained.
- Mask loops set the alpha cutoff once per run of identical values, with the first
  draw always setting it. The cache is local to each invocation.
- Fully enclosed nonempty receiver groups already contribute their whole subtree
  bounds. Extent searches stop there; empty internal nodes still descend, and
  partial intersections and occlusion retain the original rules.
- Matrix synchronization calculates inverse modelview only when a shader consumes
  inverse modelview or normals, using an independent inverse-cache hash so later
  lighting shaders receive the current inverse after a depth-only pass.

Automated checks:

```powershell
python scripts/tests/test_shadow_mask_batching.py
python scripts/tests/test_shadow_visible_extents.py
python scripts/tests/test_render_matrix_sync.py
```

The masked fixture preserves per-index texture/transform/cutoff state and reduces
three compatible draws to one, with incompatible boundaries and macOS limits
tested separately. The extent test compares 144 combinations against the original
traversal. The matrix test runs production synchronization with real GLM arithmetic,
verifying inverse/normal values and inverse-call counts across shader changes.
These establish correctness and eliminated work in fixtures, not in-world FPS gains.

Repeat the same-camera Tracy comparison and visual checks above. Textured submission
now appears under `LLRenderPass::pushBatchRange`; compare that zone with the earlier
`LLRenderPass::pushBatch` zone. Check lighting after camera/object movement as well
as grass, masked material boundaries, texture animation, and cascade transitions.
The synchronous Exact OIT validation remains: its current-frame result determines
overflow fallback and sorting passes; removing it needs a separate GPU control-flow
change with overflow regression coverage.
