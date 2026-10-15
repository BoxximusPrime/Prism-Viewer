# Ordinary shadow submission — 2026-10-15

Status: in progress, uncommitted. This round targets CPU submission overhead without reducing shadow quality.

The retained change reduced mean shadow submission from **1.030 to 0.858 ms (16.7%)** across three warmed captures per build. Overall frame interval improved from **6.314 to 6.044 ms (4.3%)**, equivalent to approximately **158.4 to 165.5 FPS**. Shadow settings and geometry are unchanged. The attempted vertex-buffer multi-bind path did not improve timings and was removed.

## Change and scope

Ordinary draws and draws with hair physics disabled skip guide lookup/binding and redundant deformation uniforms. Every draw still clears the hair radius, and active hair still receives full deformation setup. This shared code covers ordinary shadows and other geometry passes. It changes neither geometry nor draw order, shadow resolution, cascade count, alpha cutoffs, filtering or update frequency. The existing vertex-buffer binding path is unchanged.

This reduces per-draw CPU/driver work; it does **not** combine additional draw calls or move culling to the GPU. An instrumented inventory found that most remaining draws use different vertex buffers. For example, one far cascade contained 195 simple static entries across 192 buffers. A broad multi-draw path would first need shared geometry storage and per-draw transforms/material/skin data. The one-shot diagnostic logging was removed from the measured builds. [Inventory snapshot](../../output/ordinary-shadow-2026-10-15/draw-inventory.txt).

## Build and scene

- All variants are Release builds of Prism 0.10.0.54542, including the existing TAAU work and preceding SSS depth batching change. Only the inactive-hair setup skip differs between the fresh baseline and final build.
- Command: `cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2`.
- Canonical [executable](../../build-vc170-64/newview/Release/secondlife-bin.exe); executable hashes are recorded in each raw capture.
- Baseline SHA-256: `b1d5001f3f909213cbbdaa2543451cb8b35779c396b49e3166cc2815ad34e56d`.
- Final SHA-256: `3bbe2f95682ed6b68b75d57c22f21fa2d4813818c01de1e62bf0b8bd0ebb52be`.
- NVIDIA GeForce RTX 5090, driver 4.6.0 NVIDIA 617.14.
- Kenosaki beach with the nearby avatar, alpha-masked foliage, buildings and water. Camera locked to the [saved pose](../../.logs/viewer-mcp/20261015T185138Z-ordinary-shadow-original-c0042470.camera.json): position `(284821.2644958496, 276669.84033203125, 23.722949981689453)`, forward `(0.9293882250785828, -0.3524192273616791, -0.10971901565790176)`, up `(0.10259093344211578, -0.03890196979045868, 0.9939627051353455)`, vertical FOV 60°.
- Window 3440×1369; TAAU world rendering 2580×987.
- User-selected fixed **Midday**, captured as `Deterministic Midday 2`, sun rotation `(0.17173300683498383, -0.4817489981651306, 0.2885420024394989, 0.8094249963760376)`. This override resets on viewer restart, so it must be reapplied and verified.
- MaxFPS 0, VSync disabled, YieldTime −1 and BackgroundYieldTime 0. Driver global FPS limiter disabled by the user.
- Sun / Moon + Projectors, four sun cascades, resolution scale 2.0, draw distance 128 m. SSS, SSGI, PCSS, hair shading/physics and fog disabled by the user. GTAO, TAA/TAAU and procedural water remain enabled.

## Sampling and exclusions

Three fresh baseline captures each sample 1200 frames. The first warms for 1200 frames after the user reapplies Midday to an already loaded scene; the repeats warm for 240 frames. Raw captures preserve individual frame samples and start/end camera, settings, sky, water and build metadata.

- [Baseline A](../../.logs/viewer-mcp/20261015T191234Z-profile-d21e5cd3.json)
- [Baseline B](../../.logs/viewer-mcp/20261015T191251Z-profile-fb9b77ee.json)
- [Baseline C](../../.logs/viewer-mcp/20261015T191323Z-profile-5e7f54f9.json)
- [Final A](../../.logs/viewer-mcp/20261015T192325Z-profile-7756aa02.json), 1800 warmup / 1200 samples after restart and Midday/viewport verification.
- [Final B](../../.logs/viewer-mcp/20261015T192411Z-profile-b356b78f.json), 240 warmup / 1200 samples.
- [Final C](../../.logs/viewer-mcp/20261015T192449Z-profile-90c52ba7.json), 240 warmup / 1200 samples.

All six comparison captures match camera, graphics settings, sky, water, window/render dimensions and foreground state at both endpoints. A separate 10-frame preflight verified the final configuration; it is not included in performance conclusions. Screenshot capture temporarily renders at full window resolution, so world render dimensions are checked in the timing artifacts, not photo metadata.

Earlier diagnostic captures are excluded from performance comparisons. Changing sunlight took unoptimized shadow submission from about 3.63 ms to 1.14 ms; that was a lighting change, not an optimization gain. A subsequent capture after restarting also used the wrong environment and was discarded. Only matched, verified Midday captures are used below.

## Measurements

Mean milliseconds per frame, averaged across three equally sized runs. Scopes are inclusive; rows overlap and must not be added.

| Scope | Baseline | Final | Change |
| --- | ---: | ---: | ---: |
| Frame interval | 6.314 | 6.044 | −4.3% |
| CPU shadow generation, total | 1.431 | 1.265 | −11.7% |
| CPU shadow submission | 1.030 | 0.858 | −16.7% |
| CPU opaque shadow submission | 0.351 | 0.283 | −19.3% |
| CPU legacy masked shadow submission | 0.236 | 0.174 | −26.2% |
| CPU material-mask shadow submission | 0.122 | 0.112 | −8.1% |
| CPU shadow pool rendering | 0.169 | 0.175 | +3.6% |
| CPU post-present maintenance | 0.841 | 0.789 | −6.2% |
| CPU scene idle/update | 0.507 | 0.573 | +13.0% |
| GPU main frame | 4.168 | 4.368 | +4.8% |
| GPU shadow maps | 0.505 | 0.473 | −6.2% |

| Run | Baseline shadow submission | Final shadow submission | Baseline frame interval | Final frame interval |
| --- | ---: | ---: | ---: | ---: |
| A | 1.026 | 0.856 | 6.288 | 6.012 |
| B | 1.034 | 0.873 | 6.321 | 6.150 |
| C | 1.031 | 0.846 | 6.334 | 5.969 |

Shadow submission p95 was 1.248–1.272 ms before and 1.032–1.081 ms after. Frame-interval p95 was 7.092–7.386 ms before and 6.681–7.097 ms after. These are ranges of per-run p95s, not pooled percentiles.

The reduction is concentrated in the opaque/masked submission paths affected by the guard. Other scopes vary, including scene updates and GPU frame time; this patch does not deliberately transfer work to the GPU, and the measurements do not establish an isolated GPU gain. This is a sequential before/after comparison in one scene, not randomized within-process switching.

## Visual check

The matching [baseline image](../../.logs/viewer-mcp/20261015T191323Z-ordinary-shadow-midday-before-eefa96c8.png) and [final image](../../.logs/viewer-mcp/20261015T192449Z-ordinary-shadow-midday-after-65ddb172.png) retain foliage cutouts and the same terrain/building shadow coverage. No obvious missing geometry or shadow-quality regression was observed. The avatar pose and water vary between images. [Baseline photo metadata](../../.logs/viewer-mcp/20261015T191323Z-ordinary-shadow-midday-before-eefa96c8.json) and [final photo metadata](../../.logs/viewer-mcp/20261015T192449Z-ordinary-shadow-midday-after-65ddb172.json).

## Correctness checks

- [Production hair draw-setup transition checks](../../scripts/tests/test_hair_draw_setup.py): active hair, ordinary geometry immediately after hair, disabling/re-enabling physics, unsupported shaders and no bound shader.
- Existing opaque and static/rigged masked shadow batching tests preserve submitted indices, transforms, skin palettes, alpha state and SSS/hair identity. Alpha shadow routing tests pass.
- 281 hair-deformation GPU checks pass, including disabled-radius passthrough and color/glow/shadow shader paths.
- The final Release build succeeds. Temporary inventory logging and the experimental vertex-buffer changes are absent. The camera lock was released after validation; the user's Midday environment and uncapped graphics settings remain selected.

## Rejected multi-bind experiment

An intermediate build combined the hair change with cached attribute formats and `glBindVertexBuffers` on OpenGL 4.4+. It passed 1,053 real-driver input-state comparisons against the legacy path, including layout transitions, integer attributes, color/emissive aliases and fallback paths. However, its three matched Midday captures measured shadow submission at **1.080, 1.074 and 1.071 ms**, versus **1.026, 1.034 and 1.031 ms** for the baseline. Mean frame times were **6.542, 6.524 and 6.483 ms**, versus **6.288, 6.321 and 6.334 ms**.

This did not establish a performance benefit, so the multi-bind implementation and its dedicated test were removed from the final change. Fewer API calls alone do not establish lower driver cost. There is also live-scene variation and no within-process toggle, so this is evidence for rejecting the experiment, not a precise isolated measurement of the API's cost.

- [Multi-bind A](../../.logs/viewer-mcp/20261015T191746Z-profile-fe22b6e6.json), 1800 warmup / 1200 samples.
- [Multi-bind B](../../.logs/viewer-mcp/20261015T191815Z-profile-e72f01c9.json), 240 warmup / 1200 samples.
- [Multi-bind C](../../.logs/viewer-mcp/20261015T191911Z-profile-1f3ffbfc.json), 240 warmup / 1200 samples.

## Limits

This is a live, animated scene, not a frozen replay; water, avatar animation, reflection updates and streaming can vary. CPU and GPU scopes are inclusive and overlap; they must not be added or subtracted to estimate utilization. Screenshots are visual checks, not pixel-identical proofs. Crowded scenes, active projector lights, other GPUs and physical older-OpenGL/macOS machines still need broader validation.
