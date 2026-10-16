# Lighting research baseline validation

Date: **2026-10-16**, America/Denver. Status: research checks complete; one existing integration fixture needs repair. No renderer implementation, viewer rebuild or live performance comparison was performed.

This supports the [current-state analysis](../../docs/LIGHTING-SHADOWS-CURRENT-STATE.md) and [implementation plan](../../docs/LIGHTING-SHADOWS-IMPLEMENTATION-PLAN.md). It establishes which existing tests can serve as a baseline before changing projector capacity. It does not validate more than the current two ordinary shadowed projectors.

## Source and environment

- Source HEAD: `7cb3296c4d174202d6caf3a0c127e320fb9e7aaa`. Pre-existing working-tree changes include settings/defaults and unrelated viewer work; these were preserved.
- Viewer build: none for this session. The tests compile extracted/native production logic or production shader helpers in their own context; no viewer executable was measured.
- Test interpreter: `E:\BoxxyViewer\.venv\Scripts\python.exe`; native tests used the available MinGW C++ compiler.
- GPU: NVIDIA GeForce RTX 5090/PCIe/SSE2. The existing test harness requested an OpenGL 4.3 context; it reported `4.3.0 NVIDIA 617.14`, GLSL `4.30 NVIDIA via Cg compiler`.
- Scene/camera/environment: synthetic fixtures and a hidden GL context. No login, camera change, live scene, Midday comparison or graphics-setting mutation.
- Warmup/sample counts: no live frame samples. Test case counts below describe correctness fixtures. The receiver-selector test also emits synthetic microbenchmark timings; those are not used to claim viewer performance.
- [Capability queries and audited source SHA-256 hashes](../../output/lighting-research-2026-10-16/capabilities.json).

## Results

| Check | Result | Artifact |
| --- | --- | --- |
| `test_no_shadow.py` | Pass after moving temporary compilation files into the workspace. Covers tag parsing/removal, exact-prim scope, refresh/deduplication, cubemap behavior, shadow binding/slot release and re-eligibility. | [Native shadow-tag log](../../output/lighting-research-2026-10-16/test_no_shadow.py.workspace-temp.log) |
| `test_alpha_light_selection.py` | Pass: 5,000 mixed-light comparisons against brute force and 1,000 bundled-GLM affine round trips. Native hierarchy/selection code is exercised. | [Receiver selection log](../../output/lighting-research-2026-10-16/test_alpha_light_selection.py.workspace-temp.log) |
| `test_pcss_gpu.py` | Pass: 752 GPU cases, including the script's PCF/PCSS, edge/receiver/precision and GLSL 330 checks. | [PCSS log](../../output/lighting-research-2026-10-16/test_pcss_gpu.py.log) |
| `test_projector_cleanup_gpu.py` | Fails while linking its controlled spotlight fixture. Missing `decodeHairTangent`, `hairSafeNormalize`, `hairLocalShadow`, `hairDirectVisibility` and `hairDiffuseVisibility` definitions. | [Cleanup failure log](../../output/lighting-research-2026-10-16/test_projector_cleanup_gpu.py.log) |
| `test_alpha_lighting_gpu.py` | Pass: 36 lighting cases without projectors and 36 with projectors, 180 projector cases, plus skin-overlay rejection/distant fallback checks across six transparency variants. | [Alpha and projector log](../../output/lighting-research-2026-10-16/test_alpha_lighting_gpu.py.log) |

The cleanup fixture assembles `spotLightF.glsl` with older controlled stubs and a helper list lacking the newer hair implementation. The error is a test-program integration gap, not evidence that the full viewer's spotlight shader fails to link. Repairing it is P0 work; do not count this fixture as passing or infer cleanup parity from the other tests.

The first attempts at the two native tests failed because sandbox temporary directories denied compiler/file access. Both passed when `TEMP` and `TMP` were set for the test process to the verified workspace directory `E:\BoxxyViewer\output\lighting-research-2026-10-16\temp`. No test source was changed. The [attempt ledger](../../output/lighting-research-2026-10-16/test-status.txt) retains both failures and successful retries; original logs are [shadow-tag attempt](../../output/lighting-research-2026-10-16/test_no_shadow.py.log) and [receiver-selector attempt](../../output/lighting-research-2026-10-16/test_alpha_light_selection.py.log).

## Queried capabilities

One `glGetIntegerv` query per limit in the existing hidden test context, with positive-result assertions and no GL error:

| Limit | Reported value |
| --- | ---: |
| Fragment texture units | 32 |
| Combined texture units | 192 |
| Maximum 2D texture side | 32768 |
| Maximum array layers | 2048 |
| Fragment uniform components | 4096 |
| Maximum uniform block size | 65536 bytes |
| Maximum color attachments | 8 |

These limits make a small projector-array experiment plausible on this GPU. They do not demonstrate available memory for a particular allocation, layered framebuffer correctness, complete-program sampler assignments, or support on another GPU/driver. The test context's requested version is not a measurement of the viewer's active context version. The historical four-projector probe's 31/35 sampler counts were not reproduced here.

## Reproduction

Run each test from the repository root with the project interpreter:

```powershell
.venv/Scripts/python.exe scripts/tests/test_no_shadow.py
.venv/Scripts/python.exe scripts/tests/test_alpha_light_selection.py
.venv/Scripts/python.exe scripts/tests/test_pcss_gpu.py
.venv/Scripts/python.exe scripts/tests/test_projector_cleanup_gpu.py
.venv/Scripts/python.exe scripts/tests/test_alpha_lighting_gpu.py
```

If sandbox temporary files are unavailable, point the native tests' process-local `TEMP`/`TMP` at a verified writable directory inside the workspace. The capability query used `context()` from `scripts/tests/test_exact_oit_gpu.py`, `glGetString` for identity, and `glGetIntegerv` for the standard limits listed above, then destroyed the context. Raw JSON preserves the values and hashes.

No universal FPS, map-memory saving or increased-projector performance conclusion follows from this session. Full viewer integration, four/eight-source correctness, repeated Midday captures, motion/visual checks and lower-capability hardware remain pending in the plan.
