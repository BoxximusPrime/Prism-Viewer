# Shadow CPU investigation — 2026-10-11

Status: deeper CPU checkpoints added; Release build, remembered login and two warmed 600-frame captures completed. Rendering behavior has not been changed in this follow-up; changes remain uncommitted. The user is open to substantial engine/threading work when the evidence supports it.

This continues [the draw-preparation investigation](draw-sort-2026-10-11.md). It distinguishes shadow preparation from the rest of CPU shadow rendering, and identifies larger optimization routes instead of accumulating tiny fast paths.

## Fresh baseline

Two captures of 600 measured frames after 120 warmup frames each, in the current Mystic Harbor crowd. No camera/graphics writes or Tracy capture. CPU scopes are inclusive main-thread wall time; they include waits. Nested rows overlap.

| CPU scope | Median 1, ms | Median 2, ms | Mean 1, ms | Mean 2, ms |
| --- | ---: | ---: | ---: | ---: |
| All draw preparation | 4.174 | 4.166 | 4.498 | 4.609 |
| Shadow draw preparation | 2.519 | 2.478 | 2.831 | 2.896 |
| Priority geometry queue | 0.944 | 0.887 | 1.167 | 1.189 |
| Render-map assembly | 0.660 | 0.659 | 0.680 | 0.682 |
| Deferred mesh packing | 0.160 | 0.160 | 0.242 | 0.280 |
| Final buffer upload | 0.002 | 0.002 | 0.046 | 0.060 |
| Dirty volume geometry | 0.336 | 0.316 | 0.549 | 0.588 |
| Dirty particle geometry | 0.485 | 0.475 | 0.492 | 0.480 |
| Dirty mesh geometry | 0.262 | 0.259 | 0.338 | 0.374 |

Frame-interval medians: 53.365 / 52.049 ms. GPU elapsed frame medians: 40.407 / 39.573 ms; shadow-map GPU intervals: 9.585 / 9.647 ms. CPU/GPU wall/elapsed measurements cannot be added or subtracted to infer utilization. The scene has changed since earlier captures, so the older FPS is not a controlled comparison.

Artifacts: [baseline 1](../../.logs/viewer-mcp/20261011T214347Z-profile-d1105b0f.json), [baseline 2](../../.logs/viewer-mcp/20261011T214428Z-profile-2ec57ec0.json), [camera](../../.logs/viewer-mcp/20261011T214258Z-shadow-prep-baseline-090a2b53.camera.json), [screenshot](../../.logs/viewer-mcp/20261011T214459Z-shadow-prep-baseline-36c7dc98.png). Baseline executable SHA-256: `bd12b705a383e6c55063b3abe412edabda6cc42f0889c18bfa9a1b693948ee96`.

## What the code establishes

1. The normal display path updates geometry, culls the world, renders sun/projector shadows plus SSS/hair depth maps, updates textures, then sorts the main view. Shadow preparation therefore encounters queued scene changes before the main view does. [Display order](../../indra/newview/llviewerdisplay.cpp).
2. Every ordinary shadow view calls culling and state sorting; post-sort drains the **global** priority geometry queue and completes deferred mesh work. A particle or volume rebuild inside a shadow timer is not proof that the object is rebuilt for every cascade. Moving the queue drain would relabel cost without necessarily reducing it. [Pipeline](../../indra/newview/pipeline.cpp), [dirty flags](../../indra/newview/llspatialpartition.cpp).
3. Sun shadows use four cascades for the main view and two during a reflection-probe view, with up to two additional projector views when enabled. Each has different frustum/caster requirements, so reusing one cascade's visibility list unchanged would be incorrect. SSS/hair already reuse culling and sorting for compatible entry/exit/thickness views. [Shadow and focused-depth generation](../../indra/newview/pipeline.cpp).
4. Some adjacent static opaque and masked shadow ranges are already merged. The existing skinning cache avoids repeated palette construction, and draw loops skip consecutive uploads for the same avatar/skin. A new batching/palette proposal must go beyond these existing optimizations. [Draw pools](../../indra/newview/lldrawpool.cpp), [avatar palette cache](../../indra/newview/llvoavatar.cpp).
5. Draw submission still performs per-batch model/texture/buffer state handling, skinning-uniform handling and indexed draws. The old Tracy export has 1,929,520 `pushBatchRange` calls and 341,528 `pushUntexturedBatch` calls across all recorded views. These are instrumented function-entry counts, not an exact count of GL draws or unique shadow casters, and they are not a normal-running CPU benchmark. [Trace exports](../../output/draw-sort-20261011/totals.psv).
6. Geometry packing and the final flush mix CPU processing with graphics-driver work. `LLVertexBuffer::flushBuffers` drains a main-thread global mapped-buffer list, while `LLFace::getGeometryVolume` accesses live objects, materials and vertex buffers. Moving these functions directly onto workers would race shared state and move GL operations to the wrong ownership boundary. [Vertex buffers](../../indra/llrender/llvertexbuffer.cpp), [face geometry](../../indra/newview/llface.cpp).

## Added measurements

- `shadow.total`: full sun/projector shadow generation, including reflection-probe shadow views.
- `shadow.cull`: the culling nested in those shadow views.
- `sort.view.shadow`: existing preparation timing between culling and submission.
- `shadow.submit`: work after preparation in `renderShadow`, including rendering calls, state setup/cleanup and driver waits.
- `sss.cull` / `sss.submit`, `hair.cull` / `hair.submit`: analogous focused-depth work, kept separate from sun/projector shadows.

These are capture-only scopes using the existing tested CPU timing mechanism. No per-object timers, rendering-policy change or threading change was added. Post-build captures use 1,200 warmup frames plus 600 measured frames, followed by 120 warmup plus 600 measured frames. The viewer's initial login camera is left untouched as requested.

## Larger routes worth investigating

### 1. Shared shadow draw data, then batching and worker preparation

Build an immutable shadow-specific list after necessary geometry updates, with bounds, model transforms, geometry ranges, material/alpha requirements, and skinning-palette references. Test that same source data against each cascade and create per-view draw lists. Begin serially and compare caster membership and rendered depth against the existing path; only then dispatch the independent list-building jobs through the existing `LL::ThreadPool` / `LL::WorkQueue` infrastructure.

The current functions cannot simply run concurrently: `LLPipeline::sCull`, `LLViewerCamera::sCurCameraID`, render masks, visibility flags, draw-pool queues and geometry rebuild queues are shared mutable state. Spatial-group draw maps also hold ordinary `LLPointer` references whose `LLRefCount` increments are non-atomic. Keep resource ownership and lifetime pins on the main thread; workers read stable job data and return plain results. Merge visibility bookkeeping and commit results on the main thread, with geometry-generation checks to reject stale results after LOD changes, attachment changes, teleports or resource deletion.

Use the same representation to batch compatible submissions. A bigger version stores transforms/palettes in GPU buffers and submits multiple compatible draws together, preserving vertex/index-buffer bindings, shader state and alpha semantics. Merely issuing an indirect draw per object will not remove the per-object overhead. The GL loader already exposes multi-draw entry points, but that does not establish a renderer implementation or portability: feature checks and a working fallback are still required. Khronos specifies multiple commands in a multi-draw and per-draw shader IDs that can select transform data: [multi-draw indirect specification](https://registry.khronos.org/OpenGL/extensions/ARB/ARB_multi_draw_indirect.txt), [shader draw parameters](https://registry.khronos.org/OpenGL/extensions/ARB/ARB_shader_draw_parameters.txt).

This is a substantial change to view preparation, draw packets, shaders and possibly geometry-buffer packing. Its appeal is that it can reduce both repeated preparation and submission overhead. Start with regular opaque sun/projector casters, then rigged casters; retain the existing special paths for alpha cutouts, blended casters, SSS/hair depth, terrain/trees and other draw pools until each is verified. Expected savings must be measured; these scopes do not show how much data is compatible with a batch.

### 2. Worker-built geometry with main-thread commit/upload

Extract the CPU-only portion of dirty volume/mesh rebuilds into jobs with owned inputs and output arrays; give each job private scratch storage. Existing `LLVolumeGeometryManager::s*Faces` arrays are shared static scratch, and `genDrawInfo` currently combines sorting, resource allocation, object mutation and uploads. Separating those responsibilities is required before parallel execution.

This targets rebuild spikes across all views. It does not remove GL upload/driver waits, and job overhead can dominate tiny groups. Start with sufficiently large independent groups, bounded work and explicit same-frame completion/dirty-generation rules. Keep the old path as the fallback until correctness is established. The current roughly 1.2 ms mean priority-queue budget includes work that is not all parallelizable, so do not promise that entire amount as a saving.

### 3. Stable static-shadow caching

Separate static casters from animated/moving/alpha-animated casters and reuse static depth where the exact shadow projection and content are unchanged. This can remove both CPU submissions and GPU work, but only when the static share and cache hit rate are high. The current cascades are fitted to view/scene bounds; a stationary camera does not by itself guarantee unchanged shadow projection. Camera/light movement, new assets, changing geometry, alpha textures and nearby-region changes all require correct invalidation. Crowded avatars remain dynamic and must keep updating.

This has the largest scope and should follow evidence about static versus dynamic draw counts and projection stability. It is not a proposal to lower shadow update frequency and accept stale moving-avatar shadows.

## Post-build results and recommendation

Two completed captures confirm that submission dominates the full CPU shadow pass. Timings below are inclusive main-thread wall times.

| Scope | Median 1, ms | Median 2, ms | Mean 1, ms | Mean 2, ms | p95 1, ms | p95 2, ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `shadow.total` | 11.114 | 11.868 | 11.691 | 12.268 | 15.122 | 15.577 |
| `shadow.submit` | 8.042 | 8.618 | 8.247 | 8.815 | 9.619 | 10.548 |
| `sort.view.shadow` | 2.191 | 2.238 | 2.691 | 2.643 | 5.539 | 5.122 |
| `shadow.cull` | 0.291 | 0.321 | 0.299 | 0.329 | 0.357 | 0.415 |
| `sss.submit` | 2.208 | 2.694 | 2.222 | 2.700 | 2.378 | 2.971 |
| `sss.cull` | 0.063 | 0.068 | 0.065 | 0.071 | 0.079 | 0.091 |
| `hair.submit` | 2.555 | 2.622 | 2.603 | 2.635 | 2.907 | 2.908 |
| `hair.cull` | 0.065 | 0.060 | 0.066 | 0.062 | 0.079 | 0.075 |

Other shadow setup/cleanup, computed from paired samples after excluding the disjoint culling/preparation/submission intervals, averages 0.454 / 0.481 ms. The parent total must not be added to its children. Submission is 70.5% / 71.9% of mean shadow CPU wall time.

Frame-interval medians: 45.462 / 48.640 ms. GPU elapsed frame medians: 34.901 / 36.669 ms; GPU shadow-map medians: 8.285 / 8.611 ms.

**Conditional optimization route: batched shadow submission backed by shared immutable draw data, followed by worker list preparation.** The 8.0–8.6 ms submission median is a larger timed interval than 0.29–0.32 ms of shadow culling alone, but it does not establish a recoverable frame-time budget. Moving only culling onto threads would have a small ceiling in this scene. A useful prototype must remove repeated per-draw state/driver calls, not merely move an unchanged draw loop into another function. It must also measure the compatibility of geometry-buffer/shader bindings and preserve alpha, skinning and special-depth behavior. The user observation below makes a controlled full-frame comparison the priority before committing to this rewrite.

The first implementation experiment should count actual submitted draws, state changes and compatible batch sizes by opaque/masked/blended and static/rigged categories, then replace the largest supported class with a serial packet/batch path and compare depth/coverage. Extend it to workers only after the snapshot and serial equivalence are proven. The existing general worker pool can be reused. An initial success target can be at least 1 ms lower median full shadow CPU time without worse p95 frame time or visual differences; this is a proposed acceptance threshold, not a prediction.

Worker geometry jobs remain a separate option for rebuild spikes. Static shadow caching remains conditional on proving a substantial static draw share and stable projections. Neither should be justified by adding nested timings.

**No engine speedup is claimed.** This build adds timing scopes only. Submission time includes driver waits and possible GPU backpressure; the captures do not isolate pure CPU computation or prove that all 8 ms can be eliminated. Full-frame timing and visual checks remain the acceptance criteria for an optimization.

### Subsequent user observation: shadows disabled

Follow-up: [two warmed captures with shadows off](bottleneck-shadows-off-2026-10-11.md) confirm the ordinary shadow scopes disappear. Rendering still dominates, with SSS/hair depth passes active; the report records the current bottleneck and remaining attribution limits.

The user reports only 1–4 FPS gained by disabling shadows in the same scene. This is a user observation, not an MCP capture; the exact starting FPS, settings snapshots and frame-time samples were not recorded. It weakens the case for prioritizing a substantial shadow-only rewrite from inclusive scope timings alone. A warmed shadows-on/off/on comparison of full-frame times should precede that decision.

Source verification: `generateSunShadow` returns immediately when `RenderShadowDetail <= 0`, before sun/projector culling, sorting or submission. Separate SSS and hair depth passes can still run under their own feature settings. Global geometry work encountered during shadow preparation can instead be performed by another view, and driver waits can move to other calls. Consequently, removing this pass need not reduce frame time by its measured inclusive wall time. FPS is also nonlinear: at a hypothetical 20 FPS baseline, +1–4 FPS corresponds to roughly 2.4–8.3 ms shorter frames; the actual conversion requires the user's starting FPS.

Post-build executable SHA-256: `7d150764d65b807667eb31973a94db729eb3d22c0e9d8dd8ba436b445730e183`. The two post-build captures have identical camera, settings, viewport/render dimensions, sky/water and foreground metadata at start/end; all eight new/reused comparison scopes cover all 600 frames in each run. The summed shadow child intervals fit inside the parent in every sample.

The restart camera moved 1.860 m and rotated 3.447 degrees from the pre-rebuild baseline; it was left at its initial login position. Graphics settings matched across this restart. This is an investigation of the new scopes, not a before/after optimization comparison.

Artifacts: [deeper capture 1](../../.logs/viewer-mcp/20261011T215034Z-profile-8eaee5e3.json), [deeper capture 2](../../.logs/viewer-mcp/20261011T215119Z-profile-8a59d6ca.json), [login camera](../../.logs/viewer-mcp/20261011T214905Z-shadow-cpu-after-login-3d643207.camera.json), [timing/metadata summary](../../output/draw-sort-20261011/shadow-cpu-summary.json).

[Post-build screenshot](../../.logs/viewer-mcp/20261011T215120Z-shadow-cpu-after-rebuild-27c3afa1.png) inspected: ground, building, crowd and shadows are present. Camera, residents and lighting differ from the pre-restart image, so this is a smoke check, not pixel equivalence. Viewer remains logged in with ordinary unlocked camera controls.

## Validation and limits

Release build command: `cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2`; passed. [Canonical executable](../../build-vc170-64/newview/Release/secondlife-bin.exe).

Existing dirty-group and CPU-capture regression checks cover the reused mechanisms. No new control-flow logic was introduced beyond selecting the timing label for the active shadow/SSS/hair view. Live capture coverage, parent/child timing consistency and start/end metadata checks passed for both captures. No large rendering/threading change has been implemented or benchmarked in this follow-up.
