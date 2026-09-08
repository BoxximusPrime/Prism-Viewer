# Exact OIT readback investigation

Status: GPU scheduling and tiled depth reduction implemented; direct OpenGL
correctness checks pass. In-world visual and performance verification is pending.

Implementation controls (both enabled by default): `RenderExactOITAsync` selects
GPU scheduling; `RenderExactOITReduceMaximum` selects tiled reduction. Disable
both for the synchronous/per-fragment-atomic comparison. The optional compute
sorter retains synchronous validation. GPU scheduling shader/allocation failures
also retain synchronous validation.

Run `.venv/Scripts/python.exe scripts/tests/test_exact_oit_gpu.py` on Windows
with the bundled SDL3 runtime and an OpenGL 4.3 GPU. The test creates a hidden
context and runs the actual capture, control, overflow, and composite shaders.
It checks small-pool allocation overflow, deep lists and equal-depth ordering,
glow/blending, opaque cutoff, reduction tile edges, all indirect-pass boundaries
through the maximum pool capacity, and copied statistics surviving counter reset.
`scripts/tests/test_exact_oit_readback.py` exercises the production C++ ring
methods with controlled fences, including busy/full rings, FIFO camera identity,
historical capacity, wraparound, and failed fences.

An optional `--benchmark` runs an isolated 256x256x64-fragment capture with the
same actual capture shader and alternates the maximum-depth implementations.
On the RTX 5090 / NVIDIA 616.56, an initial run measured 2.36 ms versus 0.237 ms
median GPU time (eight samples each after warmup) for global per-fragment maximum
versus tiled reduction. This is a synthetic capture-plus-maximum measurement,
not a viewer frame-rate prediction or a benchmark of conditional fallback.

## Evidence

Capture: `lots_of_avatars.tracy`, September 7, 2026. Approximately 4.3 seconds
of recorded frame activity, 148 display passes. CPU zone elapsed time includes
driver/GPU waits; it is not a measurement of CPU execution alone.

`Exact OIT validation readback`:

- Total: 828.807 ms.
- Mean: 5.600 ms per display pass.
- Median: 5.506 ms; p95: 6.512 ms; maximum: 13.616 ms.
- Reads four uints (16 bytes) with `glGetBufferSubData`.

The read happens after post-deferred geometry, before OIT sorting and blending.
It can absorb outstanding opaque, shadow, and transparency GPU work; the trace
does not establish that OIT capture itself costs 5.6 ms. Current CMake settings
have `USE_TRACY_GPU=OFF`, so a new CPU/GPU capture is needed to attribute GPU work.

As a rough scale comparison, all recorded `LLDrawPoolAlpha::renderPostDeferred`
calls total 176.919 ms, or 1.195 ms per displayed frame. This includes multiple
views and is NOT a measurement of the proposed additional fallback submission.

## Why simply making the read asynchronous is incorrect

The four control words are allocation count, capacity, overflow, and maximum
per-pixel list length. Their consumers have different requirements:

| Consumer | Needs current frame data? | Can move off the CPU? |
| --- | --- | --- |
| Reject incomplete capture and render vanilla fallback | Yes | GPU predicate can select the current frame's draws |
| Determine sufficient sort passes | Yes, or a proven upper bound | GPU-generated indirect commands |
| Peak diagnostics and camera-transition logging | No | Delayed readback, tagged with its originating frame/camera |
| Grow node storage for future captures | No | Delayed demand processing, without invalidating a newer capture |

Using last frame's overflow or list depth is unsafe: a sudden camera move can
overflow this frame or expose a deeper list immediately. A larger pool reduces
overflow frequency but does not prove that the capture is complete.

Persistent mapping or staging plus an immediate fence wait preserves the same
CPU/GPU dependency. Reducing the transfer to one word also retains it.

## Recommended prototype: GPU decisions, delayed statistics

Preserve the existing natural merge sorter and original fallback draw sequence.
The optimization should change scheduling, not the transparency algorithm.

1. After capture, a small GPU preparation pass reads the current control words.
   It writes indirect draw commands for the natural-sort passes and final blend.
   An overflowed capture gets zero-count sort/composite commands.
2. Submit a bounded sequence of indirect sort draws, with the existing storage
   and image barriers between passes. A command is active only if its pass is
   needed for the current maximum list depth. Extra submitted commands draw zero
   vertices; they must not rasterize unnecessary full-screen passes.
3. Produce an exact overflow predicate using a tiny occlusion-query draw: its
   fragment survives only on overflow. Disable depth/stencil rejection and ensure
   viewport/scissor/sample state cannot suppress it. Do not use early fragment
   tests, which could count samples before the shader discards them.
4. Submit the existing vanilla fallback under `glBeginConditionalRender` with
   `GL_QUERY_WAIT`. GPU-side conditional execution avoids requiring a query
   result in application memory. Measure driver behavior; this is not a promise
   that the API can never stall. `GL_QUERY_NO_WAIT` is incorrect here because it
   is allowed to execute the fallback even when the predicate is unavailable.
5. Copy the control words to a small staging ring and fence each copied sample.
   Poll older slots without waiting. A busy ring must not force a wait merely
   to update diagnostics. Keep each sample's capacity and camera/frame identity.
6. Process completed statistics and growth requests separately from current-frame
   validation. Do not call today's `captureOverflowed()` on an old sample: it
   calls `discardCapture()` and would invalidate the current frame.

This uses normal conditional rendering, not inverted conditional rendering:
the query means overflow; indirect commands already suppress the exact path on
overflow. No OpenGL 4.5 inverted-query dependency is necessary.

### Sort bound

The node pool is limited to 2 GiB with 32-byte nodes: at most 67,108,864 nodes.
A valid pixel list therefore needs at most 26 pairwise merge passes. More
generally use `ceil(log2(capacity))`, with integer arithmetic. Natural merge
sort reduces the number of runs by at least half per pass; reversing natural
runs and pruning provably hidden nodes can only reduce the work.

The GPU activates only `ceil(log2(current maximum list length))` passes.
Zero/one-node lists need no sort pass; the valid frame still needs final blend.
Do not substitute a guessed layer cap or last-frame depth.

The optional compute sorter is not a prerequisite. It already uses indirect
dispatch, but its CPU merge-loop bound would also have to stop depending on
readback. Until separately validated, retain the synchronous path when that
optional sorter is selected rather than silently changing its algorithm.

### Main tradeoff and acceptance criterion

Conditional rendering suppresses GPU drawing, not C++ traversal, uniform setup,
or driver command submission. The CPU must submit the fallback draw sequence
even on successful captures. That could be worthwhile versus the observed wait,
but must be measured in this avatar scene. Raw frame rate may remain GPU-limited
even if the CPU can run ahead; also inspect frame latency and pacing.

## Integration issues that cannot be skipped

- Add the consumer-appropriate `GL_BUFFER_UPDATE_BARRIER_BIT` before reading or
  copying shader-written control data. The current validation uses storage,
  image, and atomic-counter barriers but not the buffer-update barrier. These
  control variables are SSBO uint atomics, not atomic-counter-buffer objects.
  This is a correctness correction, not a demonstrated speed improvement.
- Generate indirect commands with `GL_COMMAND_BARRIER_BIT` before consuming them.
- Replace or explicitly measure the next frame's `glBufferSubData` counter
  reset: without readback draining GPU work first, overwriting the same storage
  can become a new implicit synchronization point. Prefer a GPU-ordered reset.
- Audit barriers for reuse of node storage, framebuffer-cleared head/count
  images, and CPU-API-cleared compute queue headers. The old synchronous wait
  must not be relied on to hide missing resource dependencies.
- Fallback must start from the untouched opaque scene, with the ordinary rigged
  depth writes, GLTF draws, emissive handling, and depth-of-field pass preserved.
  GPU conditional execution does not suppress ordinary CPU state changes.
- Debug-alpha overlays must run once on either outcome. Clear capture-completed
  state for fallback's CPU traversal so its existing DOF test works, then restore
  the state needed by the exact branch. Audit the existing fallback scope and
  shader routing rather than only wrapping its draw calls.
- A staging sample describes the capacity at capture time, not the latest pool
  capacity. Delayed growth must remain VRAM-bounded and respect resize, resource
  release, shader reload, and mode changes.

## Separate, smaller GPU experiment

Every stored fragment performs `atomicMax` on the same global maximum-list word,
in addition to global allocation and per-pixel head/count atomics. This is a
possible contention hotspot, not something the CPU trace proves.

An alternative is to remove that global max update from capture and reduce the
already-recorded count image afterward, using workgroup-local reductions and
one global maximum update per workgroup. It retains exact depth and overflow
behavior. Its cost is an extra image scan and dispatch; test it independently
so any benefit is distinguishable from CPU/GPU scheduling changes.

## Validation required before calling it an improvement

- Record GPU durations for opaque/shadows, OIT capture, preparation, sort,
  composite, and fallback, alongside CPU submission and whole-frame timings.
  Compare a steady camera and abrupt camera movement in the same avatar scene.
- Force a tiny node pool: overflow must select complete same-frame vanilla
  rendering, with no partial exact result, doubled blending, or missing glow.
- Compare old/new outputs on empty lists, single nodes, monotonic/reversed/random
  depths, equal-depth nodes, and depths crossing powers of two. Include lists
  substantially deeper than the previous frame and opaque-cutoff on/off.
- Exercise rigged and unrigged alpha, GLTF, emissives, DOF, debug overlays,
  mouselook changes, resizing, toggling OIT, shader reload, and allocation failure.
- Artificially delay statistics consumption: rendering must remain correct and
  polling must stay nonblocking. Verify historical samples cannot discard a
  newer capture or cause unbounded growth.
- Reject a result that merely moves the 5.6 ms wait into counter reset, query
  submission, buffer reuse, or presentation without improving the intended
  frame-time/latency metrics.

## References

- Implementation: `indra/newview/fsexactoit.cpp`, `fsexactoit.h`,
  `app_settings/shaders/class1/deferred/exactOITCaptureF.glsl`,
  `exactOITCompositeF.glsl`, and `exactOITSortC.glsl`.
- Integration: `indra/newview/pipeline.cpp` and `lldrawpoolalpha.cpp`.
- [Khronos memory-barrier semantics](https://wikis.khronos.org/opengl/GLAPI/glMemoryBarrier).
- [OpenGL 4.3 specification, conditional rendering](https://registry.khronos.org/OpenGL/specs/gl/glspec43.core.pdf).
- [Conditional-render design and WAIT/NO_WAIT semantics](https://registry.khronos.org/OpenGL/extensions/NV/NV_conditional_render.txt).
- [Indirect draw command semantics](https://registry.khronos.org/OpenGL/extensions/ARB/ARB_draw_indirect.txt).
