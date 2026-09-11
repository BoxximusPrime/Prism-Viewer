The largest main-thread costs in **w21_trace.tracy** are lighting/transparency, SSS depth rendering, and avatar updates. Exact OIT and SSS deserve the first optimization experiments; the worst captured hitch also includes a large priority geometry rebuild during SSS shadow traversal.

Analyzed [E:\BoxxyViewer\w21_trace.tracy](E:/BoxxyViewer/w21_trace.tracy), using the project's Tracy 0.11.1 exporter. Analysis date: September 10, 2026. No viewer source or settings were changed.

**Capture and frame timing**

There are 170 complete `FTM_FRAME` scopes, totaling 5.100 seconds, over a 5.128-second interval. Mean frame time is **30.00 ms**, equivalent to approximately **33.3 FPS**. Median is 29.81 ms; the 95th percentile is 34.34 ms; the 99th percentile is 36.95 ms; the worst frame is 43.44 ms. Sixteen of the 170 complete frames exceed 33.33 ms, and all exceed 16.67 ms.

These are elapsed times measured on the CPU thread. They can include driver work, synchronization, and time when the thread is descheduled. They are not measurements of pure CPU execution or GPU execution. The analysis uses instrumented zones, not OS CPU samples or a GPU timeline.

**Where the average frame goes**

The rows below partition the same 170 complete main-thread frames. Nested work is counted once, and the shares sum to 100%. Percentiles are calculated from each category's accumulated time per frame; percentile values should not be added together.

| Main-thread category | Average per frame | Share of frame | 95th percentile |
|---|---:|---:|---:|
| Lighting and transparency | 6.21 ms | 20.71% | 6.94 ms |
| SSS depth rendering | 5.08 ms | 16.94% | 6.95 ms |
| Avatar and object updates | 4.74 ms | 15.80% | 5.47 ms |
| UI and HUD rendering | 3.10 ms | 10.35% | 3.85 ms |
| Texture updates | 2.14 ms | 7.14% | 2.41 ms |
| Main opaque geometry | 2.02 ms | 6.74% | 2.29 ms |
| Other simulation and UI updates | 1.72 ms | 5.74% | 2.48 ms |
| Main scene sorting | 1.70 ms | 5.68% | 2.13 ms |
| Reflection/snapshot update | 1.00 ms | 3.33% | 3.11 ms |
| Other frame work | 2.27 ms | 7.57% | 3.23 ms |
| **Total** | **30.00 ms** | **100.00%** | **34.34 ms for the whole frame** |

At the broader level, `df Display` takes 23.33 ms (77.78% of the frame), `df idle` takes 6.46 ms (21.54%), and work outside those two scopes takes about 0.20 ms. Here, `idle` means simulation and viewer updates; it does not mean the CPU is sleeping. `df Display` includes the reflection update, while its main `Render` child takes 22.33 ms.

**1. SSS depth rendering: 5.08 ms/frame, with the largest spikes**

[LLPipeline::generateSSSDepth](E:/BoxxyViewer/indra/newview/pipeline.cpp:10473) reaches **13.91 ms** in the worst frame. Across the exported capture, its 173 invocations contain 1,024 `renderShadow` calls: approximately six shadow traversals per invocation. The implementation can render three depth maps, with front and back passes for each. All exported `LLPipeline::renderShadow` calls are inside SSS depth generation in this capture.

Those shadow traversals account for approximately 4.68 ms per SSS invocation. Their nested camera-level `stateSort` calls account for about 1.66 ms per SSS invocation. These are portions of the 5.08 ms, not additional costs. The current code already reuses culling and sorting for the back-face pass; repeating that optimization would not address the remaining cost.

The slowest frame starts 3.112 seconds after the first complete frame and takes 43.44 ms. Its nested chain is:

| Nested zone in that frame | Elapsed time |
|---|---:|
| SSS depth generation | 13.91 ms |
| One shadow traversal inside SSS | 9.92 ms |
| Scene sorting inside that traversal | 9.25 ms |
| Post-sort work | 9.10 ms |
| Priority geometry rebuilds | 7.28 ms |

Several individual `LLVolumeGeometryManager::rebuildGeom` calls fall inside that rebuild burst, including calls of 1.30, 1.21, and 2.18 ms. The SSS function's own self time in this frame is only 0.47 ms. This particular spike is substantially descendant work, not just the SSS wrapper or depth-map draw overhead.

Investigate [postSort](E:/BoxxyViewer/indra/newview/pipeline.cpp:3646) calling [rebuildPriorityGroups](E:/BoxxyViewer/indra/newview/pipeline.cpp:2886) during SSS traversal. Check whether necessary rebuilds can be scheduled earlier or spread over frames, while keeping geometry valid for the shadow pass. Separately, test SSS depth update frequency and the number of active depth lights. These are experiment candidates, not measured savings.

A different slow frame, 4.294 seconds into this interval, spends 10.35 ms in SSS, including 7.47 ms of SSS self time. Its cause may differ: finer zones around depth-target operations and GL state calls would help localize it.

**2. Exact OIT: about 4.07 ms/frame in collection and finishing**

These measurements are inside the lighting/transparency category above:

| Exact OIT scope | Average per frame | Largest single frame |
|---|---:|---:|
| Collect completed statistics | 1.79 ms | 4.49 ms |
| GPU scheduled finish — measured CPU-side | 2.28 ms | 2.91 ms |
| Of finish: conditional fallback submission | 1.29 ms | 1.59 ms |
| Of finish: overflow predicate submission | 0.97 ms | 1.50 ms |

Only the first two rows should be added: **4.07 ms/frame, or 13.6% of the frame**. This is not the entire transparency cost or the measured benefit of disabling OIT; capture rendering and other alpha work also exist, and vanilla transparency would replace some work.

[collectStats](E:/BoxxyViewer/indra/newview/fsexactoit.cpp:1239) polls fences with zero timeout, then reads completed buffers using `glGetBufferSubData`. Its 1.79 ms average makes it a strong investigation target despite its asynchronous design. The existing zone cannot identify which GL operation accounts for the delay. Add narrow timing around fence polling, buffer readback, and any capacity growth before choosing a fix.

[finishFrameAsync](E:/BoxxyViewer/indra/newview/fsexactoit.cpp:1537) builds an overflow predicate and submits conditional fallback rendering every eligible frame. Across the full capture, `renderAlpha` alone costs about 1.25 ms per fallback submission. GPU conditional rendering does not remove the CPU's traversal and submission work. This is a concrete reason to examine the fallback path's CPU cost; the capture does not prove overflows were occurring.

The worst 43.44 ms frame also spends 4.02 ms collecting OIT statistics, compared with its usual 1.79 ms. This compounds the geometry-rebuild spike.

**3. Avatar updates: 4.51 ms/frame inside the 4.74 ms object-update budget**

[LLVOAvatar::idleUpdate](E:/BoxxyViewer/indra/newview/llvoavatar.cpp:2939) runs 15,300 times inside the 170 complete frames: an average of 90 avatar-object updates per frame. That is a call count, not a count of distinct human users.

Of its 4.51 ms/frame, `LLCharacter::updateMotions` takes 2.21 ms and `idleUpdateMisc` takes 0.97 ms. Name-tag updates take another 0.16 ms. This makes animation-update frequency, avatar visibility/LOD decisions, and attachment maintenance more promising CPU targets than name tags in this sample. These subcosts are already included in the avatar budget.

**4. Texture updates: mostly face-size and priority bookkeeping**

`LLViewerTextureList::updateImages` costs 2.14 ms/frame. Across all 173 exported image-update scopes, `LLFace::calcPixelArea` accounts for about **1.72 ms per image update**, approximately 80% of that budget. Across every caller, the same function takes 2.03 ms per complete frame.

[The rigged-face branch](E:/BoxxyViewer/indra/newview/llface.cpp:2294) combines joint bounds to calculate face extents. Its aggregate self time is 243.47 ms over the whole capture, with 372,858 calls. There are already throttles in [calcPixelArea](E:/BoxxyViewer/indra/newview/llface.cpp:2276) and [updateImageDecodePriority](E:/BoxxyViewer/indra/newview/llviewertexturelist.cpp:898). Investigate cache invalidation and reuse of rigged bounds before adding another blanket timer.

JPEG2000 decode accounts for only about 46.1 ms of aggregate self time across worker threads in the whole capture. It is not the large texture-related main-thread cost here.

**5. UI, draw submission, and reflection updates**

UI/HUD rendering costs 3.10 ms/frame. [draw_ui_backdrop](E:/BoxxyViewer/indra/newview/llviewerdisplay.cpp:1689), the blurred panel background, accounts for 0.72 ms/frame, about 23% of the UI/HUD rendering budget. Its current code already uses quarter-resolution targets that grow only when needed. An A/B capture with backdrop blur disabled would measure its actual effect.

`LLView::findChildView` looks much larger in inclusive statistics: 1.452 seconds across 1.98 million calls. Because it recursively calls itself, adding inclusive durations counts the same elapsed interval multiple times. Its self time is 108.6 ms across the capture, roughly 0.63 ms per rendered frame. Worth examining excessive repeated lookups, but it is not an 8.4 ms/frame independent hotspot.

The low-level draw helpers also accumulate substantial self time: alpha batch submission totals 257.3 ms, `pushBatchRange` 168.2 ms, and the materials draw loop 106.0 ms across the capture. This supports examining draw traversal and submission volume in the expensive parent passes rather than optimizing a single tiny helper in isolation.

The reflection/snapshot update averages 1.00 ms/frame, but reaches 4.17 ms. Its median is only 0.53 ms, so it contributes uneven work. The `df Snapshot` scope is almost entirely reflection-probe updating in this capture; its name does not imply a user-triggered screenshot.

**Large totals that are mostly waiting**

| Scope | Aggregate self time across captured threads | Interpretation |
|---|---:|---|
| Work-queue `pop` | 19.00 s | Worker threads blocked waiting for work |
| `micro_sleep` | 10.48 s | Explicit sleeps on background threads |
| `LLCondition::wait` | 5.16 s | Condition-variable waiting |
| Windows `GetMessage` | 5.15 s | Native window thread waiting for messages |
| HTTP request queue | 0.35 s | Includes a blocking queue fetch; not clean CPU-work time |

These totals overlap across threads and are not additive main-thread frame costs. The exported thread identities confirm these large scopes are off the main thread. The main thread's `Sleep2` scope totals only 3.71 ms inclusive over 172 calls, about 0.022 ms/frame; buffer swap averages about 0.041 ms. Neither indicates a major frame-limiter or swap wait in the measured zones.

The 1.689-second inclusive `processRequest - retry` total is another misleading hotspot: it contains an intentional sleep before retrying. Its self time after child zones are removed is just 0.071 ms across the capture.

**Largest non-wait self-time zones**

This table covers the whole exported capture, across all instrumented threads. Self time removes instrumented child zones but still includes uninstrumented callees, driver time, and possible descheduling. It uses a different population from the 170-frame allocation above.

| Zone | Aggregate self time | Calls |
|---|---:|---:|
| Exact OIT collect completed stats | 306.34 ms | 172 |
| Alpha: `ra - push batch` | 257.34 ms | 470,376 |
| `calcPixelArea - rigged` | 243.47 ms | 372,858 |
| `LLVOAvatar::idleUpdate` | 173.47 ms | 15,538 |
| `LLRenderPass::pushBatchRange` | 168.23 ms | 1,066,002 |
| Exact OIT overflow predicate submission | 165.13 ms | 172 |
| `LLMotionController::updateMotionsByType` | 151.92 ms | 8,768 |
| `draw_ui_backdrop` | 122.79 ms | 172 |
| `LLPipeline::stateSort` | 118.56 ms | 1,290 |
| `LLKeyframeMotion::onUpdate` | 113.55 ms | 23,728 |
| `LLView::findChildView` | 108.62 ms | 1,979,224 |
| Materials draw loop | 105.97 ms | 538,219 |

The [complete self-time ranking](E:/BoxxyViewer/output/w21-tracy-analysis/self-time-ranked.csv) retains all 958 source locations, including the waits so the export remains auditable. Use that file for precise unrounded totals.

**Measurement details and limits**

- The capture contains 43,989,538 instrumented zone calls. Instrumentation overhead has not been measured separately; absolute frame times should be confirmed with a less heavily instrumented or uninstrumented run before promising FPS improvements.
- This is a short sample of one scene and settings state. It does not establish behavior during teleporting, initial loading, or other locations.
- Native export timestamps are about 2,682 seconds after process start. Tracy 0.11.1 computes its `total_perc` column from the last trace timestamp, rather than subtracting the start of this captured interval. Those raw percentages are unsuitable for this frame breakdown. [Tracy 0.11.1 exporter source](https://github.com/wolfpld/tracy/blob/v0.11.1/csvexport/src/csvexport.cpp).
- There is one 27.70 ms gap between complete `FTM_FRAME` scopes. It is excluded from the per-frame partition, rather than assigned to an invented cause. Peripheral exports contain 172 or 173 scopes, so the main allocation explicitly matches children to the 170 complete frames on exporter thread 1. Exporter thread identifiers are not OS thread IDs.
- CPU-side OpenGL elapsed time alone cannot establish whether this run is CPU-bound or GPU-bound, or whether a particular GL call blocks. No GPU execution-time or OS-scheduler attribution is claimed here.
- Source references point to the current workspace. It contains pre-existing uncommitted work, so a current code excerpt is implementation context rather than proof of the capture's exact build revision.

The recommended investigation order is **SSS traversal/rebuild spikes and Exact OIT collection/fallback**, followed by **avatar animation work**, **rigged texture-priority calculations**, and **UI backdrop cost**. Each proposed change should be checked against a repeated capture of the same camera, scene, and settings; the measured scope cost is not a guaranteed recoverable saving.

Evidence files: [per-frame allocation](E:/BoxxyViewer/output/w21-tracy-analysis/per-frame.csv), [full summary](E:/BoxxyViewer/output/w21-tracy-analysis/summary.json), [analysis script](E:/BoxxyViewer/output/w21-tracy-analysis/analyze.py), [native inclusive export](E:/BoxxyViewer/output/w21-tracy-analysis/zones-inclusive.psv), and [native self-time export](E:/BoxxyViewer/output/w21-tracy-analysis/zones-self.psv).
