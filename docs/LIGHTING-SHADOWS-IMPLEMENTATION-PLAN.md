# Variable projector shadows and lighting implementation plan

Status: **in progress, implementation not started**. Updated 2026-10-16 against source `9e260f21e38a30a482a52c51d390183b3db7aad1`, including the client-side budget and cache design. Initial audit/test evidence retains its earlier source identity in the [current-state analysis](LIGHTING-SHADOWS-CURRENT-STATE.md). The [four-projector proposal](FOUR-PROJECTOR-SHADOWS-PLAN.md) is a smaller fallback candidate, not an implementation already present in the viewer.

The intended result is a user-selectable number of ordinary shadowed projectors, chosen for their contribution to the visible scene, with stable transitions and bounded memory/work. Improve light coverage and consistency across opaque, transparent and volumetric receivers in later independently measurable steps. Preserve existing content's light parameters and material appearance while changing how rendering resources are assigned.

**Client-side constraint:** resolution assignments and cache decisions are automatic, transient viewer state. Expose global graphics preferences only; do not add server-side per-light resolution, object metadata, author-set static flags or protocol dependencies. Existing authored light parameters determine illumination and projection, while the viewer determines the resources used to render them.

## Recommended sequence

1. Establish repeatable integration tests, real program resource counts and a projector-heavy benchmark scene.
2. Improve eligibility, selection ownership and stability while retaining two shadow slots.
3. Prove a projector depth-array path with two slots and existing visual quality.
4. Add a bounded variable count and complete every receiver/lifecycle path.
5. Add a local resolution/memory budget and conservative caching; retain preparation for the first cache experiment, then evaluate skipping it using spatial invalidation.
6. Evaluate clustered receiver lighting and point-light shadows as separate extensions.

The working preference is **depth-array storage**, because the request is for a variable count rather than only four. The first experiment must validate it against the existing two-map path. If it fails capability, quality, complexity or performance gates, the revised four-texture approach can ship a useful smaller increment. Do not implement both complete architectures before comparing the constrained prototypes.

## Delivery contract and budgets

Proposed first expanded target: requested counts **0–8**, default **2**, with **4** as the first live acceptance milestone. Eight is an experiment ceiling, not a measured safe shipping value or a promise that every GPU can sustain it. Keep the algorithm bounded and count-independent so a later measured cap increase does not require another two-way rewrite. Publish only the range supported by completed device and performance tests.

Existing Shadows mode continues to control whether sun/moon and projectors are allowed. Count zero means no ordinary projector maps while retaining the chosen celestial mode. Do not hide point-light, cookie, forward-receiver or transmission limits behind this control.

| Budget | Meaning | Initial policy |
| --- | --- | --- |
| Requested projector count | User's maximum desired shadowed projectors | Persistent integer, default 2; validate/clamp on load and edits |
| Effective active capacity | What the device, compiled variant and successful allocations support | No greater than requested, validated shader capacity and resource budget; show fallback reason and current valid count separately |
| Resident map capacity | Allocated layers/slots, including any transition reserve | Allocate at configuration boundaries; reserve storage counts against memory even while unused and does not increase the active-light cap |
| Map texel budget | Total projector depth storage at chosen resolutions | Explicit safety bound; do not multiply today's output-width maps without checking memory |
| Maps updated this frame | Expensive generation work | Initially every occupied slot; with caching, every dirty/new slot. A strict update limit is optional and requires an explicit missing-shadow policy |
| Receiver-light and cookie limits | Lights a surface/fog sample actually evaluates | Existing values remain explicit until a separate receiver-lighting change |

Use one source of truth for requested/effective/allocated counts and validity. Names such as `RenderMaxProjectorShadows` are proposed implementation names, not existing settings. A global projector quality preset can choose a resolution ceiling and memory cap; it is not a resolution property on a light. Exact presets/defaults remain decision D3. Preserve the current two-slot resolution behavior for parity testing before intentionally changing defaults. Count and allocated bytes can be hard bounds; milliseconds are a measured target because draw cost is variable and already-submitted work cannot be preempted.

## Milestones and acceptance

| ID | Status | Work | Completion evidence |
| --- | --- | --- | --- |
| R0 | Initial audit complete | Trace current paths, review September proposal and October measurements | Current-state document, source map and 2026-10-16 validation record |
| R1 | Source tracing and design recorded; validation pending | Local automatic budget, capture keys, mutation coverage and staged caching | Current-state cache dependency audit and detailed P4 design below |
| P0 | Pending | Repair baseline fixture; inventory real shader resources; establish scenes and diagnostics | Complete program audit and repeatable baseline captures |
| P1 | Pending | Correct and stabilize two-slot selection | Native policy/lifecycle tests and same-camera transition checks |
| P2 | Pending | Two-slot depth-array experiment and resource failure handling | PCF/PCSS parity, full program linking/binding, preview/probe/reload checks |
| P3 | Pending | Variable count and opaque visibility routing | Four distinct shadows, competing fifth light, then the validated count range across all receivers |
| P4 | Design recorded; implementation pending | Local automatic resolution, prepared-view reuse, spatial invalidation and optional update scheduling | P4a–P4f gates below; quality/performance evidence and invalidation tests |
| P5 | Conditional | Cheaper submission and preparation | Measured larger-count CPU bottleneck, serial equivalence, full-frame improvement |
| P6 | Conditional | Clustered receiver lighting and cookie storage | Better alpha/fog light coverage and bounded overflow with existing material parity |
| P7 | Separate extension | Omnidirectional point-light shadows and other lighting quality work | Independent face/texel/work budgets and receiver validation |

P1 can proceed after the relevant P0 correctness baseline. P2/P3 do not require P5/P6. P4 caching is not a prerequisite for a correct initial four-projector implementation, and its first two-slot experiment can run before P3 to isolate reuse from count changes. P0 diagnostics must distinguish map generation, shadow sampling/filtering and unrelated lighting before choosing an optimization branch.

## P0 Establish the baseline

### Repair and preserve useful tests

- Repair `test_projector_cleanup_gpu.py` so its controlled production spotlight variants link the newer hair helpers. Preserve its independent B/A patterns, cleanup/lighting assertions and legacy/PBR checks. Do not replace the failing production path with a stubbed always-lit result.
- Reuse `test_no_shadow.py`, `test_alpha_light_selection.py`, `test_pcss_gpu.py`, `test_alpha_lighting_gpu.py`, fog tests and shadow batching tests. The [validation record](../doc/performance/2026-10-16-lighting-research-validation.md) separates current passes from the stale fixture.
- Add a repeatable sampler/program audit to the existing hidden-GL test infrastructure. The old temporary probe and historical fragment-only counts are insufficient.

### Inspect actual linked programs

Record fragment and combined texture limits, maximum 2D dimensions, array layers, relevant uniform limits, GLSL version, vendor/driver and actual assigned sampler units. Account for the viewer's own `LL_NUM_TEXTURE_LAYERS=32` binding capacity. Link real representative viewer programs with their normal helper objects and indexed material offsets. Include legacy/PBR opaque, indexed alpha, material alpha, PBR alpha, direct glTF, avatar/skinned paths, sorted transparency and Exact OIT, with PCSS on/off, skin/hair helpers, fog/water, probes, SSR and mirrors as supported.

Record optimized-out samplers separately from live ones. Validate sampler types, unique incompatible bindings, uniform-array agreement and render-target completeness. A successful separable fragment link is not proof that a complete draw has a valid channel assignment. Check GLSL 330 and physical lower-capability devices; compiling a 330 shader on the RTX 5090 is not a test of a 16- or 24-unit device.

### Add focused diagnostics

Extend existing capture/debug mechanisms with requested/effective counts, occupied/valid slots, selected light identity, candidate score and rejection reason, fade, map dimensions/bytes, update age/reason, and per-main/probe-view work. Add capture-only counts/timing for projector versus directional cull, preparation, submission, depth raster, opaque resolve and cleanup. Avoid per-draw timing overhead in normal operation and synchronous GPU query readback.

For caching, distinguish maps that are resident, valid, dirty, actually rendered and reused; count validation/preparation time even on a hit. Record invalidation reasons, caster categories, texture/geometry publications, pending rebuilds, resolution migrations and late-frame changes. An age counter alone cannot explain whether a cache is correct or beneficial.

Use the existing PCSS debug view as the starting point for visualizing arbitrary projector slots and light influence. Keep the diagnostic readable: selected/rejected sources and their reasons are more useful than only a texture-grid display. Treat captured scene IDs as local diagnostic data; do not publish private scene/avatar information unnecessarily.

### Required scenes

Create or select controlled scenes only within the user's permitted in-world content/workflow. Capturing an existing scene does not authorize purchasing, uploading or modifying other residents' content.

| Scene | What it resolves |
| --- | --- |
| Neutral room with four distinguishable projectors and a fifth competitor | Correct source identity, all indices, intensity/coverage ranking and handoff |
| Eight projectors with overlapping and disjoint beams | Scaling, receiver coverage, map cost versus screen cost |
| Bright narrow light versus large dim light, including offscreen emitters illuminating visible surfaces | Weakness of the old area heuristic; conservative coverage |
| Camera motion, camera inside a beam, light motion and fast camera cuts | Ranking stability, projection/bounds correctness, transition delay |
| Avatar, cutout foliage, layered glass and hair | Skinning, alpha casting, transparent receiver selection and OIT |
| Fog beams with few/no opaque receivers | Independent volume relevance and the current directional early-return hazard |
| Mirrors/probes, underwater views, material preview and large screenshots | Auxiliary view ownership and resource lifetimes |
| Static room plus animated crowd | Cache opportunity versus invalidation rate; CPU/GPU scaling |

## P1 Improve selection at the existing count

### Selection policy

Build a current main-view candidate snapshot before projector shadow generation, after the necessary scene updates. Stop using `setupSpotLight()` drawing as the producer of desired owners. Preserve projected-texture streaming priority separately. Avoid invoking full `calcNearbyLights()` twice or relying on stale main-view sort results: explicitly place the collection step in the display flow and reuse it for later lighting where practical.

Respect the actual light set admitted by at least one active receiver path and the global local-light enable/count policy. A source omitted from opaque lighting may still matter to alpha or fog, but a source evaluated by no receiver should not reserve a shadow. Share the eligibility snapshot with consumers rather than allowing the shadow selector to invent a different unbounded illumination set. Initially record estimated cost separately from benefit; cost-aware selection can follow reliable per-light measurements.

The initial score should be an inexpensive estimate of **visible lighting benefit**:

```text
benefit = estimated visible receiver coverage
        × linear light strength
        × existing distance attenuation at relevant receivers
```

Coverage starts with conservative projected beam/radius bounds intersected with the view and coarse receiver bounds. Handle the camera inside a light and near-plane intersections explicitly. Reuse the existing projector-plane and receiver-bound math; do not perform a synchronous depth readback or an all-lights × all-triangles search. A visible light emitter is not required: offscreen lights can illuminate visible receivers. Preserve conservative candidates when receiver evidence is unavailable, including transparent/fog-only coverage.

Choose and document a bounded strength metric. Existing code offers luminance for skin/hair and peak RGB for alpha; compare saturated lights as well as white lights before deciding. Use existing SL attenuation instead of inventing a new falloff. Start without CPU cookie readbacks or guessed occlusion savings. Coverage and strength are proxies for benefit, not an exact estimate of how much of a light's illumination would be shadowed.

For stable ownership:

1. Discard invalid/dead/disabled sources, forbidden attachments/avatars and `[no-shadow]` immediately; an empty candidate set is a valid outcome every frame.
2. Rank eligible candidates deterministically by score and persistent object identity.
3. Retain an incumbent when a challenger is only marginally better. Start evaluation with the existing focused-light 1.25 multiplier as a reference, not a fixed final tuning value. Add an absolute floor so near-zero scores cannot sustain useless shadows.
4. Keep a retained light in its physical slot; rank order must not reshuffle depth ownership.
5. Fade ordinary score-driven replacement using elapsed time independent of camera velocity. Invalidity and cap reduction release immediately. Bound unusually large time steps.
6. Keep fading-out owners within the same cap. A replacement acquires a free slot, renders valid depth, and only then contributes shadow visibility. One slot cannot simultaneously hold two different lights' maps.

Do not add fairness round-robin that periodically replaces useful shadows merely to visit every light. Separate optional update fairness/age from which sources deserve residency. Do not add arbitrary author priority tags or a manual pinning UI in this phase.

**Files:** `pipeline.cpp/h`, `llviewerdisplay.cpp`, a minimal testable policy helper only if it prevents duplicating production logic in tests; reuse `llalphalightselection.h` principles and the existing native test pattern. Preserve `llvovolume.cpp`'s texture priority use.

**Acceptance:** two-slot output remains correct; stable ties independent of allocation/draw order; no duplicates; no stale nominations after zero local lights; deterministic 30/60/144 Hz transition behavior; no flash from a newly assigned uncleared map. Test selected/moving-light ordering, disabled/type-changed sources, removal/teleport, caps 0/1/2, and static-camera/camera-motion comparisons. Use a staged diagnostic comparison before changing the default score.

## P2 Prove storage and resource safety with two slots

Implement equal-resolution projector layers in a 2D depth array. Initially render exactly the same two owners with the same projections/resolution/frequency as the reference path. Keep four directional maps separate. Bind the projector array once for comparison sampling and once for raw PCSS/fog sampling as needed; this targets a constant projector sampler cost.

Use a per-slot record containing owner identity, fade, valid flag, layer, captured light transform/projection and resolution metadata. Do not introduce a renderer-wide resource graph. Separate directional and projector matrix contracts where that removes incorrect six-entry assumptions, or retain an explicit shared bounded layout during the parity step. All helper objects in one linked program must agree on declarations.

**Resource work:** extend existing texture-type/binding and target ownership code only as required. Match GL binding caches and sampler cleanup; attach one layer for each depth render; clear new/inactive layers to depth 1; check framebuffer completeness; account for memory; restore framebuffer, viewport/scissor and previous state. A count of zero still needs complete compatible fallback bindings if the linked shader retains live array samplers; use a cleared minimal layer or an established equivalent. Validate dimensions, finite scale values and overflow-safe texel/byte calculations before allocation. Validate the depth-array format and comparison/raw sampling combination on target drivers. Ordinary fragment depth can address a layer without a geometry shader or an indirect draw rewrite.

**Failure behavior:** check the currently ignored `allocateShadowBuffer()` result. Construct a complete usable resource set before exposing it. On failure, release partial allocations, invalidate affected ownership, and fall back to a previously validated capacity/path or disable projector shadows with an explanatory status. Do not continue with incomplete maps or disable unrelated lighting effects silently. Account for temporary peak memory while old and new resources coexist. A Release build must enforce this behavior; assertions alone are insufficient.

**Compatibility:** query capabilities and linked-program resource use rather than assuming 32 units guarantees success. Preserve a validated two-projector path where needed. Array support in the API does not prove `LLTexUnit`, uniforms, previews and driver state are wired correctly. Add the currently missing 2D-array and 2D-array-shadow types to `mapUniformTextureChannel()` and test actual unit assignment, including indexed offsets. Verify global/per-program defines and source hashes select the correct cached shader variants.

**Files:** `pipeline.cpp/h`, `llrender.cpp/h`, `llrendertarget.cpp/h`, `llglslshader.cpp`, `llshadermgr.cpp/h`, `llviewershadermgr.cpp`, `shadowUtil.glsl`, `pcssUtil.glsl`, fog bindings/shader and preview overrides. See the current-state source map for exact entry points.

**Acceptance:** two-slot hardware-PCF and PCSS reference comparisons at subtexel positions, clamped edges, bias, thin blockers/receivers, high altitude and camera movement; no cross-layer contamination; old/new slot identity agrees; context loss/recreation, startup/reload, preview, probe and mode toggles pass. Measure actual program assignments and image parity before adding count variation.

## P3 Make the count variable and complete receivers

### CPU and view lifecycle

Generalize assignment/uniqueness using loops over the effective budget and stable records, replacing pairwise handoff logic. Update construction, release, removal, all lookup/upload loops, temporary view/projection arrays, cull-result storage and validity checks. Add enough distinct camera IDs for the validated capacity, and audit `NUM_CAMERAS` storage and per-view culling before reusing any ID sequentially.

Keep sun cascades, directional debug cameras, six forward lights and independent skin/hair budgets separate. Recheck source validity on each main frame, even with no deferred local-light draws. Isolate projector maintenance from directional empty-receiver early returns. Define local shadow distance explicitly; preserve current distance behavior for parity, then test decoupling it from `shadow_clip` as a separate change.

### Choose opaque visibility routing

Compare a minimal packed-pair reference against a reusable per-light scratch resolve/filter and, if justified, per-light visibility layers. Prefer preserving existing PCSS cleanup for the first complete implementation. Direct in-light sampling is an experiment only if it preserves acceptable quality; removing cleanup is not a like-for-like speedup.

If using packed pairs, resolve only active pairs, omit repeated directional/AO work for extra pairs, and route every spotlight to the correct pair/channel. Bind/rebind on every source transition including unshadowed lights and both spotlight variants. Preserve the original R/G directional/AO contract and prevent scratch read/write feedback. Mirror allocations and lifetimes in main/auxiliary/hero target packs where consumed.

If using reusable scratch, resolve one light, filter it, consume it, then reuse it. Bound work by the projected light influence but expand scissor regions for the filter halo. Clear the sampled domain so a previous light cannot leak into the next. Prepare derivatives/receiver planes before divergent branches where required. Store no later consumer's required data in scratch that has already been overwritten.

### Complete the consumers

- **Opaque legacy/PBR and both spotlight variants:** arbitrary valid shadow mapping, sun/AO preservation, skin/hair branches and SSGI outputs unchanged.
- **Sorted alpha and Exact OIT:** generalized shadow-index lookup in `bindAlphaProjectors()` and shared `projectorUtil`/`shadowUtil`; retain receiver-depth sampling and correct six-light selection. Include direct glTF and skinned variants.
- **Fog:** generalized matrix/layer mapping, validity and fading; complete sampler validation and cleanup. Retain its four projected images and eight local lights as explicit limits. Avoid a circular policy where “already shadowed” fog preference alone determines which sources can obtain a shadow.
- **Skin and hair:** ordinary surface shadow indices follow the new map system; focused entry/exit and density captures retain their own owners and budgets. Validate independent disabling and fallbacks.
- **Probes/mirrors/reflection views:** preserve deliberate reuse of main projector maps, view transforms and existing exclusions. Auxiliary views must not overwrite main nominations or captured metadata.
- **Water, preview, diagnostics and post-processing:** audit all shared shadow helper users; maintain preview neutralization, generalized PCSS debug and scratch lifetimes. Do not assume `deferredLight` remains shadow data after post-processing reuses it.

### Preferences and persistence

Add **Maximum shadow projectors** to the existing Shadows page with requested/effective status and capability explanation. Enable it only for a mode allowing projectors. Use existing saved controls, graphics preset collection, Default/Cancel and change callbacks. Test old saved settings missing the new key, out-of-range values, rapid edits, 2→4→2, zero, unsupported settings restored on another machine, restart, and failed allocation. Compile for a bounded capacity so normal count changes need not create a shader permutation for every number if the selected design permits it.

Update `FEATURES.md` and user-visible descriptions of fog/transparency limits when implementation begins; mark the feature in progress until validated and committed. Update MCP settings allowlists/metadata where the current bridge requires explicit support for a new control.

**Acceptance:** each of four lights produces a distinct correct shadow simultaneously; a fifth competes predictably; then test every supported cap through the experimental ceiling. Check unshadowed fallback, fading owners, all receiver types, light deletion/type changes and settings/resource transitions. Complete the build and validation matrix below before claiming feature completion.

## P4 Bound resolution and update cost

The scheduler answers three separate questions: which lights deserve shadows, which storage/quality each receives, and which depth maps need new work. A cached static light consumes residency and receiver-evaluation cost even when it needs no new depth render. Keep those costs visible rather than treating a cache hit as a free light.

| Slice | Scope | Gate |
| --- | --- | --- |
| P4a | Global projector memory/quality budget and automatic assignment | Fixed-resolution parity, allocation bounds, quality and transition tests |
| P4b | Capture records and diagnostic-only invalidation tracking | Forced-refresh comparisons identify all tested input changes; rendering still runs every frame |
| P4c | Reuse depth after current cull/sort/preparation | Correct output and measured saving after validation overhead, initially at two slots |
| P4d | Skip preparation for proven unchanged maps | Spatial invalidation covers entrants/exits and preserves preparation side effects |
| P4e | Optional measured work scheduling | Stable behavior under sustained overload, no stale shadows, separate CPU/GPU evidence |
| P4f | Optional static/dynamic split | Static depth reuse beats copy/merge, validation and extra-memory costs |

### Local storage and automatic resolution

Start P4a with one equal-resolution bank independent of window width and sun-map resolution. Given requested active count `N`, bank side `R`, and projector byte allowance `B`, use overflow-safe arithmetic to check the requested layers against hardware limits and `floor(remaining_depth_bytes / bytes_per_layer(R))`. Subtract other budgeted depth images before using that formula. Physical allocation may include explicitly budgeted reserve layers; active owners remain bounded by `N` and validated shader capacity. Use conservative format accounting and GL allocation checks; do not assume a portable free-VRAM query or infer a default from the research machine. Count fallback images, transition reserve and optional static-cache depth in the allowance. Track opaque screen-space scratch separately in the renderer's total memory accounting.

If the chosen quality cannot fit the requested count, the automatic policy can choose a lower preset tier before reducing effective capacity. Preserve an explicit quality floor so it cannot meet a number by creating unusably small maps. This is all local policy. Existing `RenderShadowResolutionScale` remains the reference/celestial setting; introduce the independent projector mode as an opt-in experiment before choosing migration/default behavior for existing preferences.

For mixed per-light quality, prefer a **two-bank prototype** before implementing a general atlas: one lower-resolution array and one higher-resolution array, with each slot identifying its bank/layer. Both resolutions are preset values; no authored per-light setting exists. Two banks require up to four projector bindings when both raw and comparison sampling are active. Re-run the full-program audit: the benefit is bounded binding cost as count grows, not necessarily fewer bindings than today's two projectors. Avoid adding more banks without measured need.

Example allocation, **not a proposed shipping default**, assuming four bytes per depth texel:

| Bank | Allocated layers | Side | Planned bytes |
| --- | ---: | ---: | ---: |
| Higher quality | 2 | 2048 | 32 MiB |
| Lower quality | 8 | 1024 | 32 MiB |
| Total | 10 physical layers | Mixed | 64 MiB |

With an active-light cap of eight, two high-quality and six low-quality maps use 56 MiB of that allocation; two low-quality layers remain available as transition reserve. They still consume memory. Spare low-quality layers do not guarantee that a high-quality destination is free. Bank capacities stay fixed between configuration changes; unused high-quality capacity cannot magically become additional low-quality layers. Compare the utilization loss with an atlas before committing to mixed banks. Merely shrinking the viewport inside a 2048 layer does not reduce its storage.

Automatic assignment proceeds as follows:

1. Build the P1 receiver-relevant candidate set and retain stable owners within the active cap. Keep benefit scoring separate from resolution demand.
2. Estimate required detail from conservative beam/receiver projection in the current **output** viewport. A first diagnostic can compare `quality_factor * sqrt(covered_pixels)` with the preset tiers. It is only a heuristic: a visible crop of a large beam, grazing surfaces, near-plane intersections and a camera inside the beam can underestimate required light-space texel density. Keep the previous/conservative tier in ambiguous cases; compare against projected receiver spans in light UV space before enabling this heuristic generally. TAA jitter alone must not change tiers.
3. Assign the high bank to the greatest visible quality benefit among lights needing it; maintain stable UUID ties and an incumbent advantage. Use different promotion/demotion thresholds and a minimum dwell interval. Thresholds are benchmark tuning, not protocol data.
4. Render a replacement into available budgeted storage before switching its published bank/layer. A still-valid lower-quality map remains usable during a quality-only upgrade. Defer an upgrade when no destination or work allowance exists. If a setting change removes storage, migrate within the new bound or release the affected shadow; do not pretend the old resource is still available.
5. Upload the **actual captured** dimensions/texel size per map to opaque, alpha/OIT, fog and debug consumers. Update the common `proj_shadow_res` assumption, PCSS footprints and alpha-stipple target width together. Recompute bias/filter scaling according to the existing shader conventions and verify appearance across tier changes. For two banks use explicit bounded sampler dispatch and a layer coordinate; sampler-uniform arrays have constant-index restrictions in [GLSL 3.30 section 4.1.7](https://registry.khronos.org/OpenGL/specs/gl/GLSLangSpec.3.30.pdf). Raw `texelFetch`/gather and `textureSize` helpers must use the selected array's layer and dimensions correctly.

A resolution change needs fresh rasterization. Increasing size and resampling the old depth cannot recover missing geometry detail. If moving between equal-size storage regions, copying depth is an optional later optimization with unchanged capture keys. Atlas alternatives additionally need stable placement, padding, bounded PCSS footprints and matching tile transforms.

### Cache record and validity rules

Extend the P2 slot record rather than creating a renderer-wide cache framework. The minimum conceptual data is:

| Data | Purpose |
| --- | --- |
| Owner UUID plus validated drawable lifetime and assignment generation | Prevent recycled slots/objects from inheriting a previous source's depth |
| Bank/layer, resource generation, actual dimensions and format | Identify the captured image and its sampling contract |
| Captured light view/projection, projection inputs and agent-origin epoch | Reconstruct receiver matrices from the same light-space image |
| Caster/input revisions, dynamic/unknown reasons and capture serial | Establish whether the image still represents current depth inputs |
| Validity, fade, desired tier, last rendered frame and last use | Separate missing/stale data, selection transitions and quality changes |
| Benefit and delayed generation/validation cost estimates | Diagnose policy and later schedule updates without conflating it with correctness |

The projection key includes actual rendered position/rotation, scale, FOV and radius, which affect the current origin/near/far/aspect calculations. Validate finite, usable projections and compare the actual capture inputs; do not introduce a movement epsilon that silently freezes small shadow motion. Color, intensity, focus/ambiance, falloff and cookie appearance generally change lighting/selection, not geometric depth; keep them out of a narrowly audited depth key. A change of projector type/eligibility still releases the owner. Material changes to the emitting object can independently affect its role as a caster for other lights. Begin with conservative invalidation where a shared setter cannot yet distinguish these cases.

Use a resource/policy epoch for origin changes, world replacement, shadow-caster visibility policy, incompatible shader changes and context/storage recreation. Invalidate all relevant records on those events before consumers can access them. No cache is persisted to a server or reused across a viewer restart.

| Event | Depth validity and action |
| --- | --- |
| New owner or recreated storage | Invalid until a complete capture succeeds; receivers use an unshadowed result |
| Proven unchanged capture inputs | Valid; retain depth and recompute receiver-space matrices |
| Light projection or relevant caster content changes | Invalid immediately; render again or do not sample this shadow |
| Desired resolution changes only | Existing image can remain valid at its captured resolution until replacement is ready |
| Ordinary selection replacement | A valid old owner's fade may finish while it owns storage; never attach its depth to the new owner |
| Deletion, disabled source, `[no-shadow]`, forbidden source or cap reduction | Release/invalidate immediately according to P1; no stale fade from forbidden depth |
| Unknown dependency, invalid bounds or lost mutation history | Fail closed to fresh rendering, or unshadowed output if work is withheld |

A clean exact cache has no arbitrary refresh deadline. A debug forced-refresh comparison can detect mistakes, but periodic refresh does not make missed invalidations correct. Deliberately showing an old moving shadow is a separate approximation and is outside the initial design.

### First cache stage retains preparation

P4b/P4c should initially retain each occupied light's `updateCull()`, `stateSort()` and necessary lazy geometry preparation. Separate preparation from depth clear/submission within the current `renderShadow()` flow without changing the skin/hair paths that reuse prepared lists for compatible captures. Then compare the prepared view with the inputs that generated its previous depth.

Build a conservative caster manifest from **all actual ordinary depth paths**, including volume batches, avatar/terrain/tree pools, masks/blends, rigged paths and direct glTF. Compare stable identities, depth-relevant transforms/material state and geometry/alpha-content revisions. Existing group dirty bits, a buffer pointer, a texture UUID or `mGeneration` alone are inadequate. A hash can accelerate comparison but cannot replace a collision-safe equality/revision contract. Bounds or membership changes that cannot be described reliably force rendering.

Start reuse with supported rigid geometry. If the light volume contains an unproven dynamic caster, continue rendering the whole map. Treat rigging/animesh, flexible geometry, hair deformation and relevant animated-alpha/media paths as dynamic until their specific revision paths are complete. This automatic classification does not require an author to mark objects static. Fresh preparation discovers new entrants and policy changes; the initial optimization saves clear/draw/raster work, not the retained cull/sort cost.

Use the [current-state dependency table](LIGHTING-SHADOWS-CURRENT-STATE.md#existing-dirty-flags-do-not-establish-cache-validity) as the hook inventory. Add depth-input generations at actual geometry/texture publication or mutation points, not only rebuild requests. Same-format texture replacement needs a content generation when it becomes visible to the render thread. Reuse existing face lists for ordinary alpha-texture users; cover direct glTF and in-place media separately or bypass caching for them. Avoid invalidating every shadow for unrelated opaque color/probe texture updates once coverage is proven.

Record the serial after preparation and before the capture's draw inputs are consumed. Mark valid only after successful submission with no intervening incompatible input change. Keep newer events dirty; do not stamp the end-of-frame serial onto an earlier capture. Preserve resource ownership without waiting synchronously for GPU completion; normal same-context command ordering handles later sampling.

### Skipping traversal requires spatial invalidation

P4d can bypass cull/sort only after the prepared-view cache is correct and profiling shows that preparation remains material. For the initial bounded light count, start with direct tests of changed conservative caster bounds against resident light frusta. Complexity is approximately changed bounds times resident lights; a new global spatial index is unnecessary at eight lights unless measurements disagree.

Every relevant mutation supplies the old and new bounds in a consistent agent-space epoch. Test both against the **full light capture volume**, not the main camera's visible set. A wall outside the eye frustum can cast a visible shadow. Insertion tests new bounds, removal tests old bounds, and changing a parent/bridge must cover transformed child extents. Motion inside one group must still notify. A previously empty light volume is a required insertion case.

A coalesced main-thread change list can carry reason bits and a monotonically increasing serial. Keep it bounded: overflow or an unknown old bound invalidates all affected candidate caches conservatively. Retain removals as bounds/identity values, not pointers to destroyed objects. Notifications from upload workers are published through the existing main-thread handoff. Validate finite bounds and use a generation/epoch to prevent comparing old-origin events against new-origin frusta.

Do not depend only on last frame's caster dependencies: they cannot discover a newly arriving object. Do not broadly regard `LLDrawable::isStatic()` as proof against material animation, alpha streaming or view-dependent LOD. Maintain a conservative dynamic-intersection check until those paths have reliable notifications. Only bypass traversal when membership, revisions, pending rebuilds and policy permit it. Audit skipped visibility, streaming, LOD and lifetime side effects before enabling this stage.

### Frame publication and receiver transforms

The current display flow permits image and geometry changes after shadows. Keep a per-frame validity publication immediately before projector visibility/lighting is consumed, after the relevant texture/main-sort work. If a late mutation invalidates a map, the correctness-first prototype masks it to unshadowed output for the remaining consumers and schedules a fresh capture. This is a deliberate possible quality cost; frequent late invalidations fail the visual gate. A later tested reordering or bounded final recapture can remove that gap. Do not add an unbounded repair loop inside rendering.

Mutations triggered by preparing another map must also be visible to this check. Withhold publication of a captured generation if its inputs changed again. Use a consistent validity table for opaque resolve, alpha/OIT and fog; prevent deferred and forward consumers from disagreeing about which generation is valid. Auxiliary views consume published records and recompute transforms, without replacing main-view ownership. Resource/scene changes after publication must invalidate bindings at a safe boundary; no worker directly mutates the table during submission.

For each consuming view compute `clip_to_texture * captured_projection * captured_light_view * inverse(current_eye_view)` and its PCSS inverse, with the existing high-altitude precision safeguards. Initially flush on agent-origin shifts. Cache only light-space depth: screen-space visibility/cleanup and receiver lookups run for the current view every frame. Preserve current camera/caster policies until deliberately changed and tested.

### Work scheduling and overload

P4c initially updates every new/dirty selected map, preserving current update quality. Exact caching opportunistically removes redundant work; it does not guarantee a frame-time ceiling. In P4e an optional target can limit additional generation work:

1. Retain valid cached maps without consuming a depth-update quota. Their preparation and receiver costs still count in performance reporting.
2. Rank required captures by visible benefit, retained ownership and time since a valid result. Use deterministic ties. Optional quality upgrades follow missing/invalid important shadows.
3. Admit updates within both a hard map-count cap and conservative predicted CPU/GPU generation allowances. Keep CPU submission/validation and GPU depth/resolve estimates separate; do not add overlapping durations into an asserted frame cost. New lights start with conservative estimates based on prepared geometry/category and resolution, not a zero-cost assumption.
4. When a new/invalid map is not admitted, keep the light illuminated but omit its shadow. Never sample stale depth to meet the budget. Fade-in can resume after a valid capture. Fade-out using stale depth is not an exact-cache policy.
5. If sustained demand exceeds the target, damp resolution/count changes over a measured window. Prefer a stable smaller set of regularly updated dynamic shadows over round-robin shadow flicker. Report sources whose single update exceeds the allowance; an age bonus cannot make their work fit. Avoid claiming fairness, complete shadow coverage and a hard time limit can all be guaranteed under arbitrary overload.

Use delayed, availability-checked GPU queries and bounded storage, following the pattern in `llviewerautomation.cpp` without turning capture recording into a prerequisite for ordinary rendering. Associate results with the light assignment/resource generation and actual dimensions that produced them; discard obsolete results after replacement. Start with capture-only cost estimates and a fixed policy before introducing an always-on controller. Sample selectively to limit overhead; never block the rendering thread waiting for a timing result.

This permits eight unchanged selected lights to need zero new depth renders, while eight moving lights may need eight. It does not avoid eight lights' receiver shadow evaluation. Lowering resolution mainly helps raster/storage cost; culling and many draw submissions can stay similar. Include those differences when deciding whether to lower resolution or active count.

### Optional static and dynamic depth

P4f is useful only when a map repeatedly contains expensive stable geometry plus a smaller moving population. A practical design keeps static depth per resident light, copies it into that light's ordinary combined depth target, then draws dynamic casters with the same projection and nearest-depth test. This produces one combined image for the existing receiver paths. An equivalent explicit nearest-depth merge is another candidate; taking the minimum of already-filtered visibility values is incorrect for PCSS blocker search and generally for filtering.

Static membership is inferred locally and revocable. When an object starts moving, invalidate the static image to remove its old silhouette before drawing its new dynamic silhouette. Its exit and return to the stable set need the same care. Light motion invalidates both portions. Include static-source texture/LOD/material changes, copy bandwidth, extra target storage and depth-format compatibility in the cost. Measure on rooms and crowds; postpone this slice when whole-map cache hits or cheaper geometry make it unnecessary.

### Cache and budget acceptance

Add narrowly scoped tests using production policy/GLSL, with a cache-bypass reference and frozen inputs where needed. Debug forced refresh compares freshly rendered depth against reused depth; compare final receivers as well, with matching PCSS sample phase and view. Expected quality-tier changes are evaluated separately from exact-cache parity.

| Case | Required result |
| --- | --- |
| Static rigid room, moving/rotating/zooming camera | Reuse where captured inputs remain identical; correct rebased receiver transforms; LOD/tier changes invalidate or migrate correctly |
| Caster enters/exits an empty or occupied light volume; deletion/region unload | No missing new shadow or persistent old silhouette; old and new bounds handled |
| Root/child/linkset interpolation, animated avatar at rest, animesh/flexible/hair | Update whenever rendered depth changes; unknown deformation bypasses reuse |
| Alpha mip arrival, same-ID content update, animated UV, media, alpha/cutoff/sidedness edit | Correct depth refresh even without object motion or a geometry rebuild |
| Terrain edits, vegetation LOD, direct glTF animation/local reload | Complete caster-path coverage or explicit conservative bypass |
| Hidden-selection, mouselook attachments, mute/friends/impostor/slow-avatar changes | Captured set matches the current policy; no forbidden stale contribution |
| Mutation after capture or during another view's preparation | New serial retained, invalid generation not published; no dirty-event loss |
| Reassigned layer, recreated drawable, resource resize, shader reload, origin shift, teleport | No cross-owner depth; valid state cleared or correct capture transforms preserved |
| Quality-only promotion without a spare high layer | Valid old quality retained; upgrade deferred without exceeding memory or active count |
| All lights dynamic, expensive new light, delayed timing results, budget reduction | Stable, visible overload policy; no blocking readback, stale depth or silent capacity overflow |
| Many unchanged maps with small on-screen beams | Validation and receiver costs reported; cache savings survive full-frame measurement |

Record per-reason invalidations, potential versus actual hits, skipped submissions, retained traversal cost, migrations, late invalidation gaps, allocated/peak bytes and CPU/GPU frame p95. Compare fixed quality and fixed total memory independently. A faster result achieved by losing required shadows fails parity; a deliberate lower-quality budget mode must be reported as that tradeoff.

## P5 Reduce submission only where measurements justify it

Re-instrument actual ordinary shadow draws/state transitions and compatible buffer groups at the new counts. Existing static/masked batching, skin palette reuse and inactive-hair setup skips already exist. The October 15 multi-bind experiment failed to improve timings; do not reintroduce it based on API-call count alone.

The larger route is an immutable shadow draw description after required scene/geometry updates, a serial per-view packet/list builder, then selective batching or worker list preparation. Preserve transforms, alpha cutoffs/textures, double-sided state, material differences, skin palettes, deformation and special capture IDs. Distinct vertex buffers and per-draw state constrain multi-draw; shared geometry storage is a separate cost. Keep GL submission on its owning thread.

Only add workers after serial caster/depth equivalence. Test object removal while jobs run, cancelled views, resource lifetime, main/probe views and dirty geometry. Record job overhead, waits, main-thread cost and full-frame p95. Reuse the existing work queue rather than adding another job system. Conservative light-frustum culling can be explored independently; eye-camera occlusion is not a valid substitute.

## P6 Improve many-light receiver coverage

Before replacing receiver selection, quantify cases where six local lights per alpha receiver or four fog cookies visibly omit important lighting. Prototype a common immutable light table and a clustered lookup used first by the affected receiver path. The existing deferred G-buffer can remain; a full Forward+ conversion is not required.

Compare CPU cluster construction against a capability-gated compute path. Include construction/upload time and small-scene overhead, not just fragment time. Use conservative 3D light intersections, a bounded per-cell/total index capacity, a defined overflow policy and diagnostics. Transparent fragments and fog samples must select by their own position; opaque depth-only tile bounds can exclude their lights incorrectly. Preserve classic/PBR falloff, projector focus/ambiance, emission, skin/hair and color-space behavior.

A cookie atlas/array is a separate prerequisite for many simultaneous projectors per receiver. Preserve image aspect, color space, streaming, mip/focus behavior, missing-image fallback and update lifetime. Variable-size images may require resampling or packing; evaluate visual loss and upload cost. Keep shadow residency indices independent of light-list indices and cookie indices.

**Acceptance:** cross-material lighting continuity in scenes beyond six relevant lights, sorted/OIT parity, volume/alpha depth correctness, no overflow-driven corruption, and a demonstrated full-frame benefit or an explicit measured quality tradeoff on representative devices. The original [clustered shading research](https://research.chalmers.se/publication/161725) is architectural guidance, not a viewer speedup forecast.

## P7 Broader lighting extensions

| Candidate | Benefit | Dependency and decision gate |
| --- | --- | --- |
| Point-light shadows | Occlusion for currently unshadowed omnidirectional lights | Budget faces/texels/update work; implement cube coverage, depth conventions, seam filtering and every receiver; do not price one point source as one projector view |
| Directional stability and contact quality | Less swimming/acne/peter-panning and stronger contact at current counts | Protect current warp, receiver-plane and altitude fixes; test cascade changes separately from projector work |
| Probe and indirect-light consistency | Better interior/material agreement | Neutral-scene comparison of ambient/probes/SSGI/AO; avoid double-counting or treating direct shadows as an ambient fix |
| Optional screen-space contact shadows | Small detail below map resolution | Offscreen/disocclusion fallback, transparent depth limitations and temporal stability; supplemental only |
| Better blended/colored shadow transmission | More plausible foliage/glass/cloth | A different visibility representation and compositing model; ordinary OIT is not sufficient |
| Area lights or new physical light units | New authored lighting possibilities | Explicit content/compatibility model; separate from preserving existing SL lighting |
| Virtual maps or ray tracing | Potential long-term scalability/quality | Backend, residency/acceleration, streaming, deformation and broad hardware support; no dependency for P3 |

## Validation matrix

Use production logic in small native tests and production GLSL in controlled hidden-context tests. Keep fixtures narrow and meaningful. Add tests for newly introduced branches and lifecycle behavior, not textual assertions that merely mirror array sizes.

| Layer | Required checks |
| --- | --- |
| Policy | 0/1/2/3/4 and all validated larger counts; ties; no duplicates; no stale owners; cap reduction; invalid/non-finite lights or projection parameters; missing cookie; frame-rate-independent fades; replacement without exposing old depth |
| Resource | Exact limits, below-limit fallback, failed allocation/partial cleanup, resize, rapid setting edits, reload/context recreation, device limits, stable binding cache and sampler types |
| Depth sampling | Every layer with unique depth patterns; PCF/PCSS; raw/comparison coexistence; edges, nonaligned UV, bias, steep slopes, thin occluders, far/near bounds, high altitude, disabled/invalid indices |
| Opaque resolve | Every pair/layer/scratch source; volume/fullscreen spot variants; distinct patterns; no sun/AO contamination; cleanup off/on; no feedback; transitions between shadowed/unshadowed lights |
| Receivers | Legacy/PBR, material masks/blends, direct glTF, terrain, static/rigged/avatar, sorted alpha/OIT, hair/skin independent captures, fog and water |
| Views | Main camera, probe and hero/mirror views, HUD/impostor exclusion, material preview, high-resolution/tiled screenshots and TAA/TAAU jitter |
| Persistence | Old settings, defaults, Cancel, preset save/load, restart, count/mode combinations and fallback status |
| Regression | Existing shadow batching/alpha submission, receiver selection/binding/bounds, PCSS, skin/hair, fog, OIT and relevant temporal tests |

Build with:

```powershell
cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2
```

The canonical output is [secondlife-bin.exe](../build-vc170-64/newview/Release/secondlife-bin.exe). If a compile fails after changing class layout in a header, discard the affected target's compiled objects and precompiled header before rebuilding, following [AGENTS.md](../AGENTS.md). Verify staged shaders/XML and a fresh full shader startup as well as live reload; an incremental link is not enough.

## Measurement protocol and release gates

Use the local Prism MCP for launch, remembered login, camera save/replay, screenshots and captures, following [viewer-mcp.md](../doc/viewer-mcp.md). Never request/read passwords. A direct capture starts without camera or graphics changes. Planned comparisons save the original camera/settings/environment, apply the fixed Midday environment, reapply it after restarts, verify sky metadata, and restore temporary changes afterward. Keep viewport and world-render dimensions identical.

Begin with 1200 warmup frames after a loaded-scene restart and 240 between already-warmed repeats, then at least three 1200-sample runs per variant; increase warmup when streaming or shader compilation has not settled. These are starting protocol choices, not a guarantee that a live scene is stationary. Prefer alternating A/B order where a same-build switch is available. Keep animation, streaming, exposure and background/foreground state recorded. Run separate night/interior visual checks when appropriate without mixing their timings into the Midday comparison.

Compare 0/1/2/4/8 **only where implemented**, keeping sun settings fixed. First vary count at fixed map resolution and filter settings; separately compare fixed total texels and proposed adaptive policies. Repeat with PCSS off/on and cleanup off/on to attribute cost. Include zero-projector controls so directional work and independent skin/hair captures are not assigned to projector cost.

Report per-run frame median/p95/mean, CPU projector cull/preparation/submission, GPU maps/resolve/filter, occupied and updated maps, actual resolutions/bytes, fallback state and identical-camera visual checks. GPU scopes are inclusive and must not be added. CPU/GPU intervals overlap; subtracting them is not a utilization measurement. Short captures are smoke tests only.

Every measurement session gets a dated report under `doc/performance/` with build/source and executable identity, scene/camera, complete relevant settings, sky metadata, viewport, warmup/sample counts, raw artifact links and limitations. Synthetic tests and live performance must be labeled separately.

Release gates:

- **Correctness:** no missing/cross-wired shadows, invalid resources, stale-map flashes or new receiver inconsistencies in the accepted matrix.
- **Compatibility:** two-slot fallback and complete programs work on the tested hardware tiers; untested platforms stay explicitly unverified.
- **Cost:** publish the measured marginal cost of additional slots. For equivalent two-slot output, require no repeatable regression beyond run variability; an initial review trigger of 5% frame p95 regression can flag investigation but is not a universal noise threshold.
- **Quality:** judge selection using captured selected sets and visible receiver coverage; judge transition/caching in motion, not only stills. More FPS obtained by missing a required shadow fails the quality gate.
- **Delivery:** update settings/UI/docs and `FEATURES.md` together; mark work in progress until its evidence is recorded. Do not promise an eight-projector shipping cap before these gates pass.

## Decisions still requiring evidence

| ID | Working preference | Evidence that settles it |
| --- | --- | --- |
| D1 Depth storage | Equal-size array layers; retain four-texture route as fallback | P0 full program audit and P2 real-driver parity/integration |
| D2 Opaque visibility | Preserve filtered visibility; compare packed-pair reference with bounded scratch | Matched quality/cost at 2/4/8, beam overlap and full-screen coverage |
| D3 Resolution and memory | Local global preset; single bank first, automatic two-bank assignment if justified | Fixed-memory quality comparison, cropped/wide beams, allocation/peak bytes, sampler audit and tier-change stability |
| D4 Shipping count | Default 2; prove 4, explore 8 | Complete receiver matrix and repeated full-frame costs |
| D5 Selection metric | Coverage × linear strength × existing attenuation, deterministic retention | Bright-small/dim-large, saturated, fog-only and camera-motion scenes |
| D6 Temporal policy | Full updates first; prepared-view exact reuse before skipping traversal or imposing an update cap | Complete depth-input revisions, late-event handling, validation cost, hit rate and animation/streaming stress tests |
| D7 Many-light receiver path | Keep current selector until its limitations are measured | Alpha/fog coverage failures plus cluster construction/shading benchmarks |
| D8 Hardware scope | Preserve existing compatibility paths | Physical NVIDIA/AMD/Intel and relevant macOS/OpenGL results; no inference from one high-end GPU |
| D9 Mixed resolution storage | Two fixed array banks before a general atlas | Bank utilization, transition headroom, full-program sampler counts versus atlas padding/filter complexity |
| D10 Cache publication boundary | Late dirty maps become unshadowed until refreshed in the first prototype | Frequency/appearance of late updates; whether safe reordering or a bounded final recapture is necessary |
| D11 Static and dynamic split | Postpone until static redraw dominates dynamic-map cost | Classified draw share, additional depth bytes, copy/merge cost and correct membership transitions |

## Next implementation slice

Complete P0's stale cleanup fixture and program-level sampler audit, then extract/test two-slot selection ownership and light-lifecycle invalidation in P1. This produces a trustworthy baseline and improves behavior even before extra maps exist. Keep the first array prototype limited to storage/binding parity so its outcome directly answers D1.

The first caching experiment is P4b at the existing two-light count: identify the complete prepared caster inputs, record mutation/late-change reasons, and compare would-be cache hits with forced depth refresh while still drawing every map. P4c enables depth reuse only after that evidence passes. Do not combine initial cache activation, mixed resolution and a strict update quota in one comparison; each changes a different correctness or quality contract.

Research decisions recorded 2026-10-16: all budget/quality assignment stays client-side; automatic per-light tiers are permitted; count, allocated storage and update work remain separate; prepared-view reuse precedes full traversal skipping; invalid maps never remain sampleable merely to satisfy an update limit. No renderer implementation or live cache-performance claim accompanies these decisions.

After each milestone, update its status with the commit/build and validation report, revise the current-state description to match implemented behavior, and record changed decisions in a dated note here. Keep future ideas conditional rather than expanding every experiment into a mandatory renderer rewrite.
