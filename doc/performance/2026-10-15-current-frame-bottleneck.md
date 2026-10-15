# Current frame bottleneck — 2026-10-15

Status: two direct captures complete. No rendering options or camera controls were changed, and no new build or optimization was made for this measurement.

## Finding

The profile points to main-thread rendering/submission overhead as the current limit. The viewer averaged **133.4–133.7 FPS (7.48–7.50 ms/frame)**. The largest individually identified CPU rendering cost is ordinary shadow generation, **2.33–2.34 ms/frame**, including **1.83 ms** of draw submission. Turning off PCSS disables the filtering feature but leaves the underlying sun/projector shadow maps active.

GPU frame timestamps averaged **4.56 ms**, while presentation took only **0.20 ms CPU** and no yielding scope was active. MaxFPS is 0 and VSync is disabled. Together these support a CPU/submission limit rather than frame pacing or the disabled SSS/SSGI passes. They are not hardware-utilization counters, and CPU/GPU intervals overlap; subtracting them does not measure unused GPU capacity.

## Build and scene

- Existing [Release executable](../../build-vc170-64/newview/Release/secondlife-bin.exe), Prism Release 0.10.0.54542.
- SHA-256: `89085efca97c8d6291ff7ec4380950ec65c15d2d63f3cdbd322261a81d60b55f` (includes the preceding SSS batching optimization and existing TAAU work).
- NVIDIA GeForce RTX 5090, OpenGL driver 4.6.0 NVIDIA 617.14.
- Kenosaki beach, one nearby avatar, foliage/buildings and water. Region ID `be6871f8-7332-4040-bf21-1c2f75c0b57b`.
- Camera global position `(284821.1134338379, 276669.8975982666, 23.74078369140625)`, forward `(0.9293931722640991, -0.3524058759212494, -0.10971982032060623)`, up `(0.10259225219488144, -0.03890077397227287, 0.9939625263214111)`, vertical FOV 60°. Unlocked, but identical start/end camera metadata across both captures.
- Window 3440×1369; world rendering 2580×987 with TAAU enabled. Foreground throughout both captures.
- [View immediately after captures](../../.logs/viewer-mcp/20261015T184826Z-current-bottleneck-features-disabled-ba095fbc.png) and [photo metadata](../../.logs/viewer-mcp/20261015T184826Z-current-bottleneck-features-disabled-ba095fbc.json). Live animation/day cycle continue; this is a scene reference, not a pixel comparison.

## Settings and sampling

The user disabled SSS, SSGI, PCSS, hair shading/physics, ground fog, volume fog and water displacement before this measurement. GTAO, TAA/TAAU, procedural water, local water reflections and submerged water lighting remain enabled. Ordinary shadows are **Sun / Moon + Projectors**, **four sun cascades**, at **2.0 resolution scale**, with draw distance 128 m. MaxFPS 0, VSync false, YieldTime −1, BackgroundYieldTime 0. Settings metadata matches across the two captures and their endpoints.

The first capture warmed for 360 frames and sampled 1200; the repeat warmed for 240 and sampled 1200. Both completed successfully. Raw artifacts contain per-frame samples, all graphics settings, start/end camera, sky/water and build metadata:

- [Capture 1](../../.logs/viewer-mcp/20261015T184741Z-profile-c3cb3f27.json)
- [Capture 2](../../.logs/viewer-mcp/20261015T184813Z-profile-c532d305.json)

## Measurements

All entries below are mean milliseconds per frame, except the stated p95 rows. CPU scopes are inclusive main-thread wall times including driver waits. Child scopes overlap their parents; **do not sum this table**. Shadow scopes include reflection views, so they can also overlap post-present work.

| Measurement | Capture 1 | Capture 2 |
| --- | ---: | ---: |
| Frame interval | 7.498 | 7.480 |
| Frame interval p95 | 8.442 | 8.383 |
| CPU frame | 7.495 | 7.477 |
| CPU render/display including presentation and subsequent maintenance | 6.827 | 6.805 |
| CPU main-view submission | 5.732 | 5.722 |
| CPU ordinary shadows, total | 2.342 | 2.334 |
| CPU shadow draw submission, within shadow total | 1.835 | 1.827 |
| CPU opaque shadow submission, within shadow submission | 0.656 | 0.654 |
| CPU legacy masked shadow submission, within shadow submission | 0.593 | 0.591 |
| CPU material-mask shadow submission, within shadow submission | 0.179 | 0.177 |
| CPU shadow sort, within shadow total | 0.215 | 0.215 |
| CPU shadow cull, within shadow total | 0.101 | 0.101 |
| CPU post-present reflection/snapshot maintenance | 0.859 | 0.849 |
| CPU scene idle/update | 0.551 | 0.551 |
| CPU avatar idle, within scene update | 0.175 | 0.175 |
| CPU avatar animation, within avatar update | 0.065 | 0.066 |
| CPU skinning palette cache | 0.084 | 0.084 |
| CPU presentation | 0.202 | 0.201 |
| CPU background work | 0.017 | 0.017 |
| GPU main frame, before presentation | 4.559 | 4.559 |
| GPU lighting total, inclusive | 2.360 | 2.359 |
| GPU alpha geometry | 0.818 | 0.818 |
| GPU ordinary shadow maps | 0.774 | 0.775 |
| GPU opaque geometry | 0.442 | 0.447 |
| GPU TAA motion | 0.215 | 0.216 |
| GPU TAA resolve | 0.339 | 0.339 |
| GPU GTAO total | 0.206 | 0.205 |
| GPU water surface | 0.417 | 0.416 |
| GPU water wave field | 0.189 | 0.187 |

There are no SSS, SSGI, hair or fog GPU scopes in either capture. `lighting.sun_pcss` is still present as a shared sun-lighting scope (about 0.059 ms), but metadata confirms PCSS is disabled; that scope name alone does not establish PCSS work.

## Next investigation and limits

Ordinary shadow submissions are the clearest next CPU target: approximately 31% of total main-thread frame time, chiefly opaque and alpha-masked geometry. Reflection-probe updates are another candidate, but the current post-present timer also wraps snapshot maintenance and is not an isolated reflection cost. Four cascades can require repeated scene submission even when the only nearby avatar is inexpensive to animate. The avatar's measured animation and palette preparation are small here.

Remaining render/display time is not fully subdivided into CPU timers for opaque, alpha, lighting and UI, so this capture cannot attribute every millisecond or prove a particular GL call is responsible. GPU frame timestamps exclude post-present reflection maintenance and include elapsed gaps; this is a main-thread bottleneck diagnosis, not a utilization measurement. Confirming marginal settings costs would require controlled on/off comparisons. No feature toggles, cascade reductions, or code changes were performed in this session.
