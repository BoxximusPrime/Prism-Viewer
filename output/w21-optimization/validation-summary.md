# First optimization pass — September 10, 2026

The Release viewer build succeeded with exit code 0 using the required command:

```powershell
cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2
```

[Build log](E:/BoxxyViewer/output/w21-optimization/release-build.log). [Executable](E:/BoxxyViewer/build-vc170-64/newview/Release/secondlife-bin.exe): 50,699,264 bytes, built September 10 at 15:20:17 America/Denver. The viewer was not launched or logged in. Changes remain uncommitted; crowded-scene visual and performance validation is pending.

All 11 targeted scripts passed after the relevant production changes. These are standalone CPU harnesses and hidden OpenGL checks, not a full viewer integration test. Run with `.venv/Scripts/python.exe scripts/tests/<script>.py`; CPU compilation uses g++ from `C:/QMK_MSYS/mingw64/bin` on PATH.

| Script | Verified behavior |
|---|---|
| `test_shadow_batching.py` | Per-index transforms and SSS identity, compatible merges, zero-ID exit omission, platform limits |
| `test_shadow_mask_batching.py` | Mask/tree state and identity boundaries, compatible merges, zero-ID exit omission, platform limits |
| `test_shadow_alpha_submission.py` | Alpha routing, shader reuse, entry preservation, opacity restoration and exit omission |
| `test_sss_selection.py` | Projector frustum, linear-light ranking, 30/60/144 Hz transitions |
| `test_sss_depth_precision.py` | 600 altitude/camera cases at 15, 1500 and 4000 m |
| `test_sss_shadow_gpu.py` | 682 reconstruction, coverage, lighting and actual capture-shader checks |
| `test_sss_blur_gpu.py` | Nine blur, boundary and texture-preservation cases |
| `test_exact_oit_readback.py` | Extracted production ring/allocation/cleanup: mapped and 4.3 paths, allocation/mapping failures, FIFO, busy/full slots, camera/history, wraparound, failed fences and pending-fence teardown |
| `test_exact_oit_gpu.py` | 12 actual GPU capture/control/composite cases, deep and equal-depth lists, exact blend/glow, same-frame overflow and staged statistics |
| `test_pose_blender.py` | Production accumulation order, priorities, additive weights, clear/re-add, cached interpolation, repeated apply and independent owners against the old behavior |
| `test_avatar_animation_freeze.py` | Normal, forced, hidden-sync and hidden-nonsync freeze/resume plus menu wiring |

The OIT GPU script also passed with `--mapped-readback`: all 12 cases plus coherent persistent staging reads and mapped-buffer deletion in an OpenGL 4.4 context. Default OpenGL 4.3 also passed. GPU: NVIDIA GeForce RTX 5090, driver 616.56. [Six-script post-change console log](E:/BoxxyViewer/output/w21-optimization/remaining-validation.txt); the other results are summarized above from their individual successful runs.

`test_pose_blender.py --benchmark` measured median synthetic accumulation at **0.0570907 ms before and 0.0124178 ms after (4.59748×)**. It uses 120 joints and six overlapping poses, eight alternating samples of 2,000 iterations, native g++ `-O2`, and the same lightweight transform recorder in both paths with event recording disabled during timing. This isolates bookkeeping; it is not a whole-animation or viewer FPS benchmark. The correctness harness records transform calls and weights rather than reimplementing transform arithmetic.

Next evidence needed: a comparable crowded-scene Tracy capture and visual checks for SSS, transparency and avatar animation. Added scopes distinguish SSS entry/exit and target operations, OIT polling/read/growth/predicate queries, and pose accumulation. Check `EXACT_OIT_MAPPED_READBACK_SLOTS` in viewer diagnostics to confirm the mapped path is active. No SSS/OIT frame-time improvement has yet been measured.
