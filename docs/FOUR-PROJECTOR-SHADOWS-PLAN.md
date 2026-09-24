# Up to four projector shadow casters

Status: dry run complete; implementation not started. Source audited on 2026-09-24 at commit `12cf23a35c`. No viewer code was changed or built for this investigation.

## Proposed behavior

Add **Graphics > Shadows > Maximum shadow projectors**, with values 1–4 and a default of 2. Sun / Moon + Projectors enables it. The existing Shadows mode provides the off switch. On devices with fewer than 32 fragment texture units, retain a maximum of two and show that limit in the control.

Keep the existing screen-area priority, camera-dependent fades, local-light eligibility, and `[no-shadow]` behavior. The limit applies to projector shadow sources. Four sun/moon cascades, the six forward local-light slots, fog's four projected-texture slots, and the independent SSS transmission-light budget retain their present meanings.

The proposed implementation uses four ordinary depth textures, a second pair of opaque shadow-result channels, and raw-depth sampling in the four-projector shader variant. Texture arrays and a new lighting architecture are unnecessary for this approach.

## What the dry run established

### 1. The CPU limit is distributed but bounded

`pipeline.h:753` has `mSpotShadow[2]`; lines 859–868 have six combined matrices and two current/target/fade slots. `pipeline.cpp` allocates two maps at 1110, nominates two projectors at 10816, hands slots between lights at 12639, and renders two maps at 12672. Several lifecycle and lookup loops also assume two.

The priority insertion loop already generalizes to N. The handoff does not: it explicitly checks target 0/1 and uses `(i + 1) % 2` to avoid assigning the same projector twice. That block needs a small rewrite.

### 2. Opaque shadow visibility has only two available channels

`class2/deferred/sunLightF.glsl:52` and `sunLightSSAOF.glsl:51` output:

| Channel | Current contents |
| --- | --- |
| R | Sun/moon shadow visibility |
| G | Ambient occlusion |
| B | Projector slot 0 visibility |
| A | Projector slot 1 visibility |

`class3/deferred/spotLightF.glsl:134` chooses B or A. `class1/deferred/blurLightF.glsl:49` cleans up the R/B/A shadow channels. Merely increasing map and matrix counts would make projectors 2 and 3 read the wrong result.

Both ordinary and fullscreen spotlight draws use `spotLightF.glsl`. Despite the `MultiSpotLight` name, `pipeline.cpp:9851` still issues one draw per projector. That lets each draw bind the appropriate result texture using the existing `lightMap` sampler.

### 3. Adding four more active samplers exceeds the real GPU limit

A hidden OpenGL context on the local NVIDIA GeForce RTX 5090 reports **32 fragment texture units**. Scratch copies of the production fragment shaders and their helper objects were linked with PCSS, alpha projectors, reflection probes, SSR, and hero probes enabled. Indexed alpha included all four indexed material textures.

| Fragment path | Existing two projectors | Four with separate comparison + raw samplers | Four using only raw projector depth |
| --- | ---: | ---: | ---: |
| PBR alpha | 31 | 35 | 31 |
| Indexed legacy alpha | 27 | 31 | 27 |
| Legacy material alpha | 30 | 34 | 30 |

These are active sampler counts from linked fragment stages, not estimates from declarations. The separable-stage linker accepted the oversized variants; that does **not** make 35 distinct fragment texture bindings available. Complete viewer programs and their assigned texture channels still need validation.

PCSS already reads raw projector depth. The extra comparison samplers exist for the runtime PCF fallback when PCSS is disabled. In the four-projector variant, ordinary PCF can compare the same raw depth texels and bilinearly interpolate the results. Replacing two comparison plus two raw samplers with four raw samplers keeps the total unchanged.

A scratch implementation of that ordinary projector PCF fallback was compared against the production hardware-PCF function on D24 depth, including clamped texture edges and three bias values. **196,608 rendered comparisons had zero difference on this GPU.** This validates the sampled cases, not every coordinate, driver, or performance profile. PCSS's blocker search and penumbra algorithm were unchanged in the sampler probe.

The temporary sampler probe is `%TEMP%/boxxy-four-shadow-probe.py`; it does not edit production shaders. The parity check was an inline scratch program using the same existing hidden-context test helper.

## Implementation sequence

### 1. Establish capacity and the setting

Files: `pipeline.h`, `pipeline.cpp`, `llshadermgr.h`, `llshadermgr.cpp`, `llviewershadermgr.cpp`, `llviewercontrol.cpp`, `app_settings/settings.xml`.

- Define named capacities for four directional maps, four projector maps, and eight total maps in an existing shared header. Replace only literals that mean these capacities.
- Add persistent integer `RenderMaxProjectorShadows`, default 2, clamped to 1–4. Resolve one effective cap using the device limit and shadow mode; use it consistently in allocation, selection, shader setup, and UI status.
- Compile the existing two-projector sampling path when the effective cap is at most two; compile the four-projector path above two. A shader permutation such as `FOUR_PROJECTOR_SHADOWS` is sufficient.
- Connect changes through the existing shader-setting callback (`llviewercontrol.cpp:180,892`). It refreshes cached settings and `setShaders()` releases/recreates GL buffers. Apply a cap change at that boundary, clear old/pending assignments, and reset fades.
- Register `shadowMap6/7` and `pcssDepthMap6/7` alongside the existing contiguous uniform enums/names. Keep enum order, name order, and assertions synchronized. Unused comparison samplers in the four-projector PCSS variant must remain inactive.
- Use fixed eight-entry matrix arrays and initialize inactive entries. This avoids differing uniform-array declarations between separately compiled shader objects.

Shader source changes are already hashed into the cache key at `llviewershadermgr.cpp:840`; a manual cache-version bump is unnecessary. Put the four-projector define in the basic-shader attributes assigned to `sGlobalDefines` at line 1192: `LLGLSLShader::hash()` already hashes both per-program and global defines at `llglslshader.cpp:2107–2116`, so switching the cap selects the correct binary cache entries.

### 2. Expand storage, allocation, selection, and rendering

Files: `pipeline.h`, `pipeline.cpp`, `llviewercamera.h`.

- Expand current projectors, pending projectors, fades, and map storage from two to four; combined shadow/modelview/projection/inverse arrays from six to eight.
- Allocate a complete bank of two or four depth maps for the compiled variant, even if the requested render count is one or three. Clear unused maps to depth 1 and mask absent slots as fully lit. This keeps active GLSL samplers complete without another fallback resource. Render only selected slots within the requested limit.
- Update allocation/filtering (`pipeline.cpp:1081–1160`), initialization (519), release (1455), drawable removal (2071), target reset (9640), access bounds (11582), and local render matrices/cull results (12104,12761).
- Clear pending nominations every main-view frame, including frames with zero eligible local lights. Nominate the highest N priorities using the current insertion algorithm.
- Replace the two-slot handoff with two short passes: update fades and retain desired current lights; then assign missing targets to available slots while checking all current assignments. Preserve fading-out occupants until their slots are available. Clear slots outside a reduced user cap immediately.
- Apply `[no-shadow]` cleanup to every stored slot, including pending slots. Use all-slot uniqueness checks in place of the pairwise assertions.
- Add `CAMERA_SPOT_SHADOW2/3` before the water camera IDs. The arrays in `llvieweroctree.h` and `llvocache.h` already use `NUM_CAMERAS`, so they expand automatically; their objects still require recompilation.
- Propagate allocation failures and clear partially constructed extra resources before fallback. `allocateScreenBuffer()` currently calls `allocateShadowBuffer()` without testing its return at line 926; the new capacity must not proceed with incomplete maps.

Do not enlarge `mShadowCamera[8]`: it holds two sets of four directional debug cameras. Similarly, `mSSSDepth[3]`, its two local lights, and their camera-ID reuse at line 11980 belong to the independent transmission feature.

### 3. Fit four projector receivers into the sampler budget

Files: `class1/deferred/shadowUtil.glsl`, `pipeline.cpp`, `llviewershadermgr.cpp`; possibly a small sampling helper in the same GLSL file.

- Make `sampleSpotShadow()` accept indices 0–3, validate indices, and use combined matrix slot `4 + index`.
- Add raw-depth dispatch for maps 6 and 7. Use constant sampler branches, consistent with the current GLSL 330-compatible code.
- In the four-projector PCSS-capable variant, use raw depth for both PCSS and ordinary projector PCF. Ordinary PCF keeps the existing five tap positions, bias, weights, and edge clamping; each bilinear depth comparison is reconstructed from neighboring raw texels. Start with the tested four-texel implementation.
- Keep sun/moon PCF and PCSS unchanged. Keep the two-projector variant's hardware-PCF path unchanged. Switching PCSS off while four projectors are enabled selects the raw ordinary-PCF path without exceeding the sampler budget.
- `sampleSpotSSSPath()` at `shadowUtil.glsl:400` has no callers in the shader tree. Remove that dead helper or ensure it does not introduce active comparison samplers in this variant. Do not expand the separate SSS depth-capture system.
- Extend shadow binding/unbinding and matrix uploads at `pipeline.cpp:9018`, `9235`, and `10971`. Avoid arithmetic crossing from the shadow-uniform enum block into the raw-depth block. Bind only complete allocated resources; initialize inactive shader inputs.
- Validate actual linked sampler channels for the four-projector programs, including indexed material offsets. Reject an unsupported four-projector variant and reload at two with an explanatory status rather than disabling unrelated effects.

The runtime cost to check is ordinary projector PCF when PCSS is off: reconstructing a bilinear comparison uses more raw reads than a hardware comparison. A gather optimization can follow if measurements justify it. A projector depth array remains a fallback design if this approach fails driver or performance checks; it is not part of the initial implementation.

### 4. Store and filter opaque results in two pairs

Files: `pipeline.h`, `pipeline.cpp`, `class2/deferred/sunLightF.glsl`, `class2/deferred/sunLightSSAOF.glsl`, `class3/deferred/spotLightF.glsl`.

- Add one additional light-result target to `RenderTargetPack`, allocated at that pack's render resolution when more than two projector slots are supported. Mirror its allocation/release across main, auxiliary, and hero-probe packs.
- Preserve the existing first RGBA result. Add a second pair pass with a base index of 2: write projector slots 2/3 to B/A and set R/G to 1, skipping repeated directional-shadow and AO calculations.
- Explicitly set/reset the pair base for both `gDeferredSunProgram` and `gDeferredSunProbeProgram`. Apply the existing cubemap rule: consume existing projector maps without reallocating, reprioritizing, or rendering those depth maps during a probe update.
- Run the existing cleanup/legacy blur on each populated pair. Reuse `screen_target` as horizontal scratch and each pair's own result target for the vertical result; `bindDeferredShader(shader, light_target)` already supports overriding the input. The existing `blurLightF.glsl` can remain unchanged because both pairs retain B/A placement.
- In `setupSpotLight()`, bind the appropriate pair to the existing `DEFERRED_LIGHT`/`lightMap` unit for every spotlight draw. Read B/A using the slot within that pair. This adds no sampler to the opaque spotlight shader.
- Ensure the override is restored/rebound on transitions between pairs, unshadowed lights, shader variants, and render-target packs. Prevent render-target feedback when running blur.
- Skip the second pair when no extra slot is occupied. Retain a fading-out extra slot until its fade completes.

This adds up to two depth renders, one pair-resolution pass, and two blur passes when cleanup is active. With two selected as the setting, the extra pair passes and extra bank are absent.

### 5. Connect transparency, fog, previews, and preferences

Files: `pipeline.cpp`, `class1/deferred/volumeFogLightF.glsl`, `llviewershadermgr.cpp`, `llgltfmaterialpreviewmgr.cpp`, `llfloaterpreference.cpp`, `skins/default/xui/en/panel_preferences_graphics1.xml`, `FEATURES.md`.

- `bindAlphaProjectors()` at line 10916 searches all selected shadow slots. Keep its six forward-light entries; their stored shadow index now ranges from -1 to 3. Shared `projectorUtil.glsl` already forwards that index, covering normal alpha and Exact OIT without duplicating lighting implementations.
- Fog already supports four projected textures. Extend its eight shadow matrices, raw samplers, shadow mask, light-to-shadow lookup, and cleanup loops (`pipeline.cpp:10318,10658,10711`; `volumeFogLightF.glsl:23,105`). Update the fog shader's explicit sampler validation at `llviewershadermgr.cpp:3544`: six depth inputs become eight, so eleven total samplers become thirteen.
- Update preview shadow overrides at `llgltfmaterialpreviewmgr.cpp:391` for the expanded uniform layout and verify unused raw-depth samplers cannot expose scene shadows in material previews.
- Add the count control to the Shadows tab at XML line 808. Enable it only for projector shadows; show the device cap and that changing it reloads shaders. Fit it with the existing resolution/cascade controls.
- Use the existing bound-control mechanisms for preset save, Default, and Cancel. Verify them rather than adding a second preferences mechanism.
- Update the relevant shadow, transparency, and fog bullets in `FEATURES.md` when implementation begins; mark the feature in progress until the work is committed and confirmed.

## Verification required before completion

1. **Selection and lifecycle:** extend `scripts/tests/test_no_shadow.py` into the four-slot scenarios, reusing production selection code. Exercise 1/2/3/4 caps, five competing lights, tied priorities, replacement while fading, deletion, `[no-shadow]`, zero local lights, cap reduction, and shader reload. Assert unique occupied slots and the requested maximum.
2. **GPU sampling and binding:** extend `test_pcss_gpu.py` to exercise all four independent projector maps and PCSS on/off, including unused indices and GLSL 330. Preserve the raw-PCF comparison against hardware filtering with non-aligned coordinates, edges, and bias. Validate full PBR, legacy, glTF, ordinary-alpha, and OIT programs and assigned sampler channels at the 32-unit limit.
3. **Opaque result routing:** extend `test_projector_cleanup_gpu.py` with four different shadow patterns split across the two results. Verify both spotlight variants, legacy/PBR receivers, all four indices, PCSS cleanup on/off, and no contamination of sun/AO channels. Exercise switching pairs between consecutive draws.
4. **Receivers:** extend `test_alpha_lighting_gpu.py` and `test_volume_fog_gpu.py` with indices 2/3. Existing targeted SSS tests should continue passing with its independent capture budget unchanged.
5. **Build:** run `cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2`. If a compile fails after the header layout changes, discard the affected target's compiled objects and precompiled header before rebuilding, per `AGENTS.md`. Verify staged shaders/XML and a fresh full shader startup.
6. **In-world acceptance:** use four projectors with distinguishable shadows and a fifth competing source; move the camera and lights; include an avatar, cutout foliage, blended/OIT surfaces, and fog. Test Off / Sun / Projectors, 2→4→2, Default/Cancel, resolution changes, mirrors/probe updates, material preview, and restart persistence. Measure frame time and memory at two versus four with PCSS and cleanup independently enabled/disabled.

The dry run resolves the two architectural questions: storage needs a second pair of visibility channels, and the sampler budget can remain unchanged with the tested raw-depth approach. Remaining work is implementation and full-viewer integration, especially fade ownership, pair binding, device fallback, and visual/performance verification.
