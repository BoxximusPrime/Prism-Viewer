# Current bottleneck with shadows off - 2026-10-11

Status: two warmed live captures complete; no rendering code, settings or camera changes. This follows the user's observation of only 1-4 FPS gained by disabling shadows and the [shadow investigation](shadow-cpu-2026-10-11.md). This session diagnoses the current workload; it is not a shadows-on/off benchmark or an optimization result.

## Setup and validation

- Two captures, each 120 warmup frames and 600 measured frames. Already-running Release viewer; no restart, camera lock, settings overrides or Tracy capture.
- Build: `E:\BoxxyViewer\build-vc170-64\newview\Release\secondlife-bin.exe`; SHA-256 `7d150764d65b807667eb31973a94db729eb3d22c0e9d8dd8ba436b445730e183`. Existing uncommitted timing instrumentation is included.
- Scene: Mystic Harbor, crowded outdoor area with many visible avatars. Screenshot shows normal rendered geometry; this is a visual smoke check, not a before/after quality comparison.
- Viewport 3440 x 1369; render size 3440 x 1316; foreground throughout. GPU NVIDIA GEFORCE RTX 5090/PCIE/SSE2, driver 4.6.0 NVIDIA 617.14.
- Camera position: `[179017.05239868164, 331966.8279724121, 2004.76806640625]`; forward `[-0.8203083276748657, 0.5094801187515259, -0.25985434651374817]`; vertical FOV approximately 60 degrees. Camera remained unlocked and unchanged.
- Shadows off (`RenderShadowDetail=0`), VSync off, `YieldTime=-1`, `BackgroundYieldTime=0`; SSS mode 2 with thickness and local point-depth enabled at 2048 resolution; hair shading/transmission enabled; TAA and GTAO enabled; SSGI, volumetric clouds, volume fog and ground fog disabled. Full settings are in the raw artifacts.
- Camera, graphics settings, sky/water, viewport, render dimensions and foreground metadata match at the start/end of both captures and across both runs. Both contain 600 samples. No sun/projector shadow CPU or GPU scope is present. Hair depth ran in all 600 frames of run 1 and 599 of run 2; SSS ran in all 600 frames of both.
- Live scene contents, avatar motion, streaming, driver scheduling and other system activity are not frozen. Run 2 was slower despite matching recorded setup; report the range rather than implying a stable exact cost.

## Frame and main-thread results

| Measure | Run 1 | Run 2 |
| --- | ---: | ---: |
| Mean frame interval, ms | 44.271 | 48.280 |
| Median frame interval, ms | 43.083 | 47.285 |
| p95 frame interval, ms | 53.463 | 57.100 |
| FPS from mean interval | 22.59 | 20.71 |
| Median main-view CPU submission interval, ms | 35.502 | 39.416 |
| Display share of mean measured main-thread frame time | 87.7% | 88.2% |

CPU timings are inclusive main-thread wall times, including driver waits. Parent/child scopes overlap; do not sum this table. `render.display` includes presentation and post-present maintenance. Avatar animation is nested in avatar updates and scene idle; palette construction is nested in palette preparation and invoked from rendering. These are not CPU utilization measurements.

| Scope | Median 1, ms | Median 2, ms | p95 1, ms | p95 2, ms |
| --- | ---: | ---: | ---: | ---: |
| `frame` | 43.532 | 47.475 | 52.776 | 56.933 |
| `render.display` | 37.921 | 41.653 | 46.879 | 50.706 |
| `scene.idle` | 5.009 | 5.246 | 6.432 | 6.623 |
| `scene.object_update` | 3.275 | 3.409 | 4.016 | 4.131 |
| `avatar.idle` | 3.031 | 3.140 | 3.776 | 3.847 |
| `avatar.animation` | 1.615 | 1.661 | 2.137 | 2.153 |
| `skinning.palette_cache` | 1.067 | 1.165 | 1.362 | 1.450 |
| `skinning.palette_build` | 0.701 | 0.773 | 0.895 | 0.959 |
| `sss.submit` | 4.798 | 5.321 | 5.253 | 6.201 |
| `hair.submit` | 3.610 | 3.826 | 4.196 | 4.597 |
| `render.state_sort` | 2.926 | 3.299 | 4.937 | 5.977 |
| `sort.view.sss` | 1.239 | 1.539 | 3.323 | 4.135 |
| `sort.view.hair` | 0.426 | 0.447 | 0.553 | 0.634 |
| `sort.view.world` | 0.973 | 1.070 | 1.216 | 1.347 |
| `render.texture_update` | 2.035 | 3.287 | 2.768 | 4.463 |
| `render.post_present` | 0.952 | 0.940 | 8.976 | 9.095 |
| `render.present` | 0.223 | 0.249 | 0.495 | 0.552 |
| `render.cull` | 0.658 | 0.688 | 0.823 | 0.850 |
| `render.geometry_update` | 0.327 | 0.358 | 0.432 | 0.462 |
| `background.total` | 0.019 | 0.022 | 0.028 | 0.050 |

Rendering dominates (about 88% of measured main-thread time); animation and CPU skinning-palette construction are smaller costs. Among specifically timed rendering work, SSS depth submission is 4.8-5.3 ms and hair depth submission 3.6-3.8 ms. These remain active with ordinary shadows off. Their preparation also includes globally necessary geometry updates that can move to another view when a feature is disabled; do not treat every nested preparation millisecond as removable feature cost.

Post-present reflection/snapshot maintenance has a roughly 0.94-0.95 ms median but a 9.0-9.1 ms p95, making it relevant to frame spikes. It runs outside the main GPU-frame timestamp interval. In run 2 the largest measured CPU frame was 97.9 ms, with 92.8 ms in display; the current finer scopes do not isolate the cause of that outlier. Background work and presentation are small in these captures.

## GPU elapsed intervals

| Scope | Median 1, ms | Median 2, ms | p95 1, ms | p95 2, ms |
| --- | ---: | ---: | ---: | ---: |
| `frame` | 32.437 | 35.961 | 37.871 | 41.758 |
| `lighting.total` | 11.551 | 12.570 | 14.431 | 15.214 |
| `Hair.depth_maps` | 7.747 | 5.825 | 9.660 | 9.014 |
| `SSS.depth_maps` | 4.165 | 5.618 | 6.902 | 7.506 |
| `geometry.opaque` | 5.221 | 5.025 | 11.822 | 10.929 |
| `geometry.alpha` | 2.243 | 2.098 | 8.024 | 6.206 |
| `TAA.motion` | 2.744 | 3.628 | 4.767 | 4.811 |
| `GTAO.total` | 0.703 | 0.703 | 0.713 | 0.710 |
| `SSS.diffusion` | 0.613 | 0.614 | 0.825 | 0.862 |
| `TAA.resolve` | 0.264 | 0.264 | 0.274 | 0.300 |
| `water.wave_field` | 0.178 | 0.179 | 1.772 | 1.874 |

The largest broad interval is `lighting.total` at 11.6-12.6 ms. Source inspection confirms that `renderDeferredLighting` includes GTAO, SSS diffusion, water preparation, post-deferred geometry (alpha/fullbright/glow), OIT completion and TAA motion. Consequently `geometry.alpha`, `TAA.motion`, `SSS.diffusion`, `GTAO.total`, and water preparation must not be added to that parent total or called separate extra costs. The `lighting.*_pcss` names label shared lighting passes even when ordinary shadows are off; they do not establish active PCSS cost.

Hair depth is the largest separately named feature interval (5.8-7.7 ms median), followed by SSS depth (4.2-5.6 ms); ordinary opaque geometry is around 5.0-5.2 ms. The varying distribution across consecutive intervals can include driver scheduling and GPU queue starvation, not just changes in GPU arithmetic. CPU and GPU intervals overlap and cannot be summed or subtracted to establish utilization or recoverable savings.

## Conclusion and next target

The strongest supported bottleneck is rendering/submission as a whole, with repeated SSS/hair depth rendering prominent among the measured individual paths. Animation is not the leading measured cost in this scene. There is no evidence here to prioritize a shadow-only engine rewrite while shadows are disabled.

The next targeted investigation should split main-thread opaque drawing, deferred lighting, post-deferred/OIT work and TAA motion submission, and separate reflection work from snapshot maintenance. The present broad display interval leaves too much rendering unpartitioned to name one dominant CPU draw loop or distinguish compute from driver waits confidently. A warmed paired toggle of SSS and hair transmission would measure their actual full-frame impact; it was not performed in this direct capture. Threading recommendations should follow that attribution rather than assume the full elapsed interval can be parallelized away.

## Artifacts

- [Capture 1](../../.logs/viewer-mcp/20261011T220040Z-profile-3d8410cd.json)
- [Capture 2](../../.logs/viewer-mcp/20261011T220124Z-profile-b75d71a4.json)
- [Saved camera](../../.logs/viewer-mcp/20261011T220129Z-bottleneck-shadows-off-157b4b56.camera.json)
- [Screenshot](../../.logs/viewer-mcp/20261011T220129Z-bottleneck-shadows-off-e5f6310e.png)
- [Screenshot metadata](../../.logs/viewer-mcp/20261011T220129Z-bottleneck-shadows-off-e5f6310e.json)

No feature-disabled comparison, hardware utilization capture, source change, rebuild or speedup claim was made in this session. Viewer remains running with its original current camera and settings.
