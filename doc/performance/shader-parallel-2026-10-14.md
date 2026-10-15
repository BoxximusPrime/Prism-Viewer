# Shader compilation scheduling — 2026-10-14

Status: in progress, uncommitted. Release build, regression checks, four live
shader-loading passes, matched-view screenshot review and rendering smoke test passed.

The viewer already requests the driver's maximum background compiler thread
count through ARB/KHR parallel shader compilation. The existing deferred/OIT
queue stopped after 16 pending programs and drained the entire batch in submission
order. The revised queue retires a completed program and immediately refills its
slot, keeping slow links from blocking submission of later independent programs.
It retains the previous bound of 16 queued programs (the next program is submitted
before making room). The four hair compute programs now submit together, with
completion checked before enabling hair physics or unloading a failed family.
The optional debug preview retains its independent fallback.

The progress plan also counted a removed hair program; it now expects five hair
programs, matching the loader, instead of six.

## Setup and baseline

- Canonical executable: `build-vc170-64/newview/Release/secondlife-bin.exe`.
- Baseline executable SHA-256: `31b6594e132b8d455f40d44358adc7d8598c9c8a6e4307212902a2676e879833`.
- Source base: `e7e005e3b6`, with the existing uncommitted Quick Photo/collections
  changes present in both builds. Shader sources are unchanged by this work.
- GPU: NVIDIA GeForce RTX 5090, driver 617.14; CPU: Intel i9-13900K.
- Scene: Brianconnais, 3440×1369 viewport. Graphics settings were left unchanged.
  [Saved camera](../../.logs/viewer-mcp/20261014T164558Z-shader-parallel-original-924c81b2.camera.json),
  [baseline image and settings](../../.logs/viewer-mcp/20261014T164855Z-shader-parallel-before-80f33ab1.json),
  [baseline screenshot](../../.logs/viewer-mcp/20261014T164855Z-shader-parallel-before-80f33ab1.png).
- Launch and remembered login used the local `prism-viewer` MCP. A cached startup
  preceded three full `shaders_reload` calls per build, treating the first full
  reload as warmup and the next two as measured samples. Each reload clears the
  viewer's binary cache. The driver cache was not cleared. Source version was
  `dee02142-a286-490e-ed07-bb06a0d97f56` for all six reloads.
- Baseline reload durations returned by MCP: **29.5061263, 37.6855515,
  40.6794613 seconds** (including warmup).
- [Baseline viewer log](../../.logs/shader-parallel-before.log). All passes loaded
  successfully; the old progress plan reported 266/267 because of the stale hair
  count. The long reported per-program times include queue residence and must
  not be summed or interpreted as independent compiler CPU timings.

## Results

[Release build log](../../.logs/shader-parallel-build.log), built using
`cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2`.
Final executable SHA-256:
`03dcf067eb0c7359da559708bc5575a0d18b508a689d1e2d06bd1ecaae4801e2`.
No class layout changed. The sandboxed MSBuild stalled before compilation;
the normal-permissions retry completed successfully.

| Full shader reload | Previous scheduler (s) | Rolling scheduler + hair batch (s) |
| --- | ---: | ---: |
| Warmup | 29.5061263 | 27.0010534 |
| Sample 1 | 37.6855515 | 31.8333474 |
| Sample 2 | 40.6794613 | 34.6831985 |
| Median excluding warmup | 39.1825064 | 33.25827295 |

Observed reduction after warmup: **5.92 seconds / 15.1%**. All three new runs
were shorter than their corresponding old run, but both series increased with
successive reloads. This is a small sequential before/after sample, not a
guaranteed speedup on every launch. Exact OIT links still dominate the wait.
[Raw MCP reload measurements](../../.logs/shader-parallel-reloads.json).

[Final viewer log](../../.logs/shader-parallel-after.log) records successful
266/266 totals for cached startup and all three full reloads; no count mismatch.
Simulator transport was serviced during each reload (391, 481 and 539 pumps).

The [post-reload capture](../../.logs/viewer-mcp/20261014T165431Z-profile-d9c353fc.json)
completed 120 warmup frames and 60 measured frames without error. This is a
rendering smoke test, not an FPS benchmark. The
[final screenshot](../../.logs/viewer-mcp/20261014T165437Z-shader-parallel-after-3e631944.png)
and [metadata](../../.logs/viewer-mcp/20261014T165437Z-shader-parallel-after-3e631944.json)
show the same scene at 3440×1369 with hair available, matching graphics settings,
and no obvious rendering regression. Avatar animation, rain and sky time differ;
these are not pixel-identical reference images. The saved camera was replayed
after restart, then released back to normal control. No graphics settings changed.

## Checks

- `test_async_shader_compile.py`: passed, including a slow first job that stays
  pending while a later completed job frees a slot; bounds, fallback, runtime
  feature flags, repeated loads, and simulator heartbeat/ACK behavior retained.
- `test_hair_shader_batch.py`: passed, covering synchronous and parallel success,
  each compute-stage failure, draining before unload, optional preview failure,
  and unsupported compute hardware.
- `test_shader_source_cache.py`: passed.
- `test_shader_bootstrap_gpu.py`: passed on the RTX 5090.
- `test_shader_progress_log.py .logs/shader-parallel-after.log`: passed, four
  complete compilation passes with exact totals.
- `git diff --check`: passed.

## Limits

This measures complete viewer shader reload wall time, not C++ build time or
rendering FPS. Driver compiler scheduling is an implementation-defined hint
([Khronos specification](https://registry.khronos.org/OpenGL/extensions/ARB/ARB_parallel_shader_compile.txt)).
Warm driver caches and CPU/background activity affect the result. Sequential
before/after runs are not a controlled cold-cache benchmark. No other GPU or
driver has been measured.
