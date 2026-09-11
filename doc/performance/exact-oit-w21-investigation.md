Exact OIT performance investigation — w21
=======================================

Status: first optimization pass implemented and uncommitted; offline checks and Release build passed; in-world validation remains pending. Updated September 10, 2026.

The user reports a crowded area with 50–60 avatars and has authorized implementation after the research. Retain exact transparency and same-frame overflow correctness. No viewer launch or login has been performed; validation uses offline and hidden-context harnesses.

Baseline: workspace commit `52d375475d080ec8dad2c67b783ef4103ad12f9e`, inspected September 10, 2026. Capture: [w21_trace.tracy](E:/BoxxyViewer/w21_trace.tracy). Shared measurements: [frame analysis](E:/BoxxyViewer/output/w21-tracy-analysis/report.md) and [summary](E:/BoxxyViewer/output/w21-tracy-analysis/summary.json).

**Implementation pass**

Each staging slot can now use coherent persistent read mapping on OpenGL 4.4+ when the required entry points exist. Collection copies its 16 bytes directly after the existing fence signals, avoiding buffer binding and `glGetBufferSubData` for mapped slots. The copy, three-slot FIFO, camera tags, historical capacity, busy-slot handling and same-frame GPU overflow decision remain intact. Unsupported versions or failed immutable allocation/mapping recreate the slot with mutable storage and retain the original readback. Buffer deletion unmaps storage; teardown clears the mapping pointer with the slot.

New Tracy scopes distinguish fence polling, completed reads, fence deletion, actual pool growth and the predicate's viewport/polygon queries. Viewer diagnostics include `EXACT_OIT_MAPPED_READBACK_SLOTS`. No new global GL state cache or fallback-renderer rewrite was introduced. Their costs still need localization in a new capture; a signaled staging fence alone did not identify the original 1.785 ms collection cost.

The production ring harness passed mapped and OpenGL 4.3 paths, immutable-allocation/mapping/mutable-allocation failures, unavailable entry point, FIFO/camera/history rules, busy/full slots, failed fences, wraparound and pending-fence teardown. Actual GPU capture/control/composite checks passed all 12 scenarios in both OpenGL 4.3 and 4.4 contexts, including coherent mapped staging and deleting mapped buffers. Driver: NVIDIA 616.56, RTX 5090. [Post-change validation log](E:/BoxxyViewer/output/w21-optimization/remaining-validation.txt). The required Release build succeeded. [Validation summary and build](E:/BoxxyViewer/output/w21-optimization/validation-summary.md).

No readback speedup or FPS gain has yet been measured in the crowded scene. The next capture should compare the new narrow scopes and actual mapped-slot count. The research record below describes the original baseline and remains useful for the deferred predicate/fallback work.

Existing work: [readback investigation](E:/BoxxyViewer/doc/exact-oit-readback-investigation.md) and [algorithm description](E:/BoxxyViewer/doc/ayanestorm-special-exact-oit-how-it-works.md). GPU scheduling, a three-slot staging ring, GPU counter reset, and tiled maximum-depth reduction are already implemented. Their in-world validation was pending in the earlier document.

**Measured budget and interpretation**

The common sample has 170 complete frames, averaging 30.00 ms. These are CPU-thread elapsed times, including possible driver or scheduling delay. Despite the word GPU in a zone name, GPU execution was not timed in this capture. The inspected source commit is not independently verified as the capture's exact executable revision.

| Scope | Mean per complete frame | p95 | Maximum |
|---|---:|---:|---:|
| Collect completed statistics | 1.785 ms | 2.147 ms | 4.493 ms |
| GPU scheduled finish, CPU-side scope | 2.282 ms | 2.662 ms | 2.914 ms |
| Within finish: conditional fallback submission | 1.294 ms | 1.501 ms | 1.589 ms |
| Within finish: overflow predicate submission | 0.971 ms | 1.239 ms | 1.500 ms |
| Within finish: queue statistics | 0.007 ms | 0.011 ms | 0.383 ms |

Only the first two rows add to **4.067 ms/frame, 13.6% of this frame budget**. OIT capture and other alpha work also exist. Disabling OIT would replace some work with vanilla transparency, so this is not a predicted speedup. The two large finish children account for 2.265 ms; just 0.017 ms remains in the parent outside them, including queueing. That makes rewriting CPU sort-loop submission a poor initial target on this evidence, although GPU sort execution still needs its own measurements.

Across all exported frames, `renderAlpha` accounts for about 1.25 ms per conditional fallback submission. The capture does not show how many predicates selected fallback, so it does not establish that the node pool overflowed frequently. In the worst 43.44 ms overall frame, OIT collection costs 4.02 ms alongside the separate SSS rebuild burst.

**Current path and resource lifetime**

1. [Capture setup](E:/BoxxyViewer/indra/newview/fsexactoit.cpp:1003) collects older completed samples before starting a new capture, allowing allocation failure to select vanilla rendering safely. `prepareCaptureBuffers` resets control counters on the GPU and clears per-pixel heads/counts. Capture shaders append fragments to a global node pool, retaining depth and the blend/glow information required for exact composition.
2. [prepareControl](E:/BoxxyViewer/indra/newview/fsexactoit.cpp:1323) uses the existing 16×16 tiled maximum-list reduction when enabled. This avoids one contended global maximum operation per fragment. [The control shader](E:/BoxxyViewer/indra/newview/app_settings/shaders/class1/deferred/exactOITControlC.glsl) derives indirect sort/blend commands from the current capture's maximum depth and overflow flag.
3. [queueStats](E:/BoxxyViewer/indra/newview/fsexactoit.cpp:1301) copies 16 bytes into one of three staging buffers after a buffer-update barrier and fences the immutable copy before sorting. A full ring skips a sample. Pending slots are never overwritten.
4. [collectStats](E:/BoxxyViewer/indra/newview/fsexactoit.cpp:1243) polls the oldest fence with flags zero and timeout zero. It stops at a busy slot; only signaled slots are read with `glGetBufferSubData`. It processes historical capacity and the sample's camera-mode tag, deletes completed/failed fences, advances the FIFO, then grows capacity once if needed. At baseline these staging buffers used `glBufferData(..., GL_STREAM_READ)` without persistent mapping.
5. [finishFrameAsync](E:/BoxxyViewer/indra/newview/fsexactoit.cpp:1563) renders a one-pixel overflow predicate under an occlusion query, then submits vanilla alpha under `GL_QUERY_WAIT`. The GPU selects same-frame fallback. The CPU still walks pools and draw lists, binds shaders/materials/palettes and issues commands.
6. [composite](E:/BoxxyViewer/indra/newview/fsexactoit.cpp:1454) copies the opaque screen background and issues natural merge passes up to the pool-capacity bound. Current-frame GPU commands set unused draws to zero count. At most 26 passes cover the 2 GiB / 32-byte-node limit; command 26 performs the final blend. Barriers separate dependent passes. Overflow disables exact draws so the full fallback result survives.
7. Resource release deletes pending fences and staging buffers and resets ring indexes. Resize may retain the node allocation while recreating size-dependent resources. Any new mapping must fit allocation failure, resize, disable/re-enable and teardown paths, not just steady-state collection.

The optional compute-sort route currently selects synchronous validation; it is not the path demonstrated by w21's scheduled-finish zones. Previous synchronous-readback findings and synthetic reduction speedups must not be presented as newly discovered work or measured gains in this capture.

**Why the remaining cost needs finer attribution**

A zero-timeout fence poll does not request waiting for an unsignaled fence. This distinguishes the current loop from synchronous current-frame validation. It does not make the whole CPU call stack cost-free or identify why collection takes 1.785 ms. [Khronos `glClientWaitSync` reference](https://raw.githubusercontent.com/KhronosGroup/OpenGL-Refpages/main/gl4/glClientWaitSync.xml).

Potential locations include fence polling, completed-buffer retrieval, binding/unbinding, fence deletion, driver work, capacity allocation, and bounded transition logging. The capture has one outer zone, so none is individually established as the cause. [growNodePool](E:/BoxxyViewer/indra/newview/fsexactoit.cpp:1170) returns immediately below capacity; growth is a conditional allocation, not a known 1.785 ms cost every frame. `recordCaptureStats` mostly updates scalar peaks and only logs selected transitions.

The overflow predicate includes two explicit `glGetIntegerv` calls for viewport and polygon mode, temporary state changes, query submission, and a tiny draw. Any of these can own the observed elapsed time, but the one-pixel size does not identify the cause. General `LLGLState` wrappers already cache enable state; they should not all be described as unconditional `glIsEnabled` calls. Additional validation queries depend on `gDebugGL`, which should be recorded in the next capture.

OpenGL conditional rendering suppresses specified GPU rendering commands according to the query result; it cannot skip the C++ fallback traversal around them. `GL_QUERY_NO_WAIT` may execute those commands unconditionally when the result is unavailable. It cannot safely replace WAIT here because that can combine fallback and exact output. WAIT also creates a dependency in GL execution; the CPU trace alone cannot establish where a particular driver implements its cost. [Khronos conditional-render reference](https://raw.githubusercontent.com/KhronosGroup/OpenGL-Refpages/main/gl4/glBeginConditionalRender.xml).

**Ranked next experiments**

| Priority | Experiment | Decision it enables |
|---|---|---|
| 1 | Add coarse counters and narrow zones around fence poll, read, delete, growth and predicate state/query/draw operations. Record pending slots, consumed samples and actual growth. | Localize the 1.785 ms collection and 0.971 ms predicate budgets before choosing a GL change. Measure overall frame time as well as these scopes. |
| 2 | If completed-buffer retrieval dominates, compare a persistently mapped staging ring against the existing path in a hidden-context harness. | Retains delayed FIFO samples and removes per-sample retrieval calls. Keep an OpenGL 4.3-compatible fallback; require actual buffer-storage support and successful allocation/mapping. |
| 3 | If predicate state queries dominate, use already authoritative cached viewport/polygon state or an explicit call-site contract. | Audit every state writer, render-target transition, debug wireframe and restore path first. Replacing a query with a stale cache is a rendering bug. A new global state cache is not justified by two unlocalized calls. |
| 4 | Reduce redundant CPU work in the fallback submission path while preserving its complete behavior. | Reuse safe traversal/state results within the frame only after profiling by batch type. Persistent draw-command infrastructure or a GPU-driven renderer would be much larger work than this investigation justifies. |
| 5 | Explore less frequent statistics sampling only if the readback experiment warrants it. | Current-frame overflow must stay GPU-controlled. Sampling less often delays growth and camera diagnostics and can prolong repeated fallback; this is a tradeoff, not a free optimization. |

For persistent readback, map the staging buffers, not the live control buffer. Retain the copy and its fence, and read only after completion. Coherent persistent mapping still requires synchronization for completed server writes. A noncoherent variant also needs the specified client-mapped barrier before its fence. `CLIENT_STORAGE_BIT` is a placement hint, not a guarantee of faster memory. [Khronos buffer-storage specification](https://registry.khronos.org/OpenGL/extensions/ARB/ARB_buffer_storage.txt). The viewer loads `glBufferStorage`, but the inspected GL manager does not expose an existing `mHasBufferStorage` capability; an entry-point pointer alone should not replace version/extension checking. This was unimplemented at the research baseline; the coherent OpenGL 4.4 path is now implemented and tested as recorded above, with in-world timing pending.

Do not use last frame's maximum list depth to cap sorting, truncate valid lists to a fixed K, skip fallback because recent frames did not overflow, remove dependency barriers without a replacement proof, or poll a current query result synchronously on the CPU to avoid traversal. Each can lose exactness or replace submission overhead with a stall. A different OIT algorithm would change the requested feature rather than merely reduce redundant work.

**Validation performed and requirements for a change**

[Validation log](E:/BoxxyViewer/output/w21-tracy-research/validation.txt): `test_exact_oit_readback.py` passed the extracted production ring methods with busy/full ring, FIFO order, camera identity, historical capacity, wraparound and failed-fence scenarios. `test_exact_oit_gpu.py` passed 12 scenarios using actual capture/control/composite shaders on RTX 5090, OpenGL 4.3, driver 616.56. Coverage includes empty captures and image edges, reduction edges, deep/equal-depth lists, opaque cutoff, exact blend/glow, complete overflow fallback and staged statistics. The harness opens a separate hidden context; the viewer was not launched.

These tests establish a useful correctness baseline, not crowded-scene performance or every material combination. A mapped-ring implementation needs both allocation/mapping failure tests and the old capability path. Predicate changes need adversarial viewport, polygon, cull, depth, stencil, scissor, rasterizer-discard and sample-state tests. Fallback changes must retain rigged depth, depth of field, blend/glow semantics, attachments, double-sided/material routing, and exactly one debug overlay.

Later validation should repeat same-camera crowd captures for baseline and one change at a time, recording node capacity/demand, actual fallback selections, pending samples, debug-GL state, resolution and OIT settings. Exercise resize, rapid mouselook transitions, disabling/re-enabling OIT and deliberately forced overflow. Compare whole-frame mean/tails and nonblocking GPU timings. No in-world timing claim can be made from the hidden-context checks or from a main-menu launch.
