# Shadow stability investigation — September 17, 2026

Status: implemented, uncommitted, Release build and viewer shader startup passed; staged shader hash verified. The user reports substantial visual improvement, with vertical-wall flicker still present. That flicker remains deferred. The sampling-pattern toggle did not affect a subsequently reported large change in wall-shadow softness with camera angle; the separate cascade search/projection correction is documented in `PCSS-PENUMBRA.md`. The regressions reproduce specific faults, not the user's complete scene.

## Scope

Traced sun/moon cascades and projector maps from fitting, culling, caster submission and shader binding through PCSS/PCF, opaque lighting, forward transparency and cleanup. Reviewed alpha-mask/blend caster shaders, the geometric horizon, receiver-plane bias, blocker search, the wall safeguard and SSS interaction. Production changes are confined to the shared `shadowUtil.glsl`.

## Reproduced defects and changes

### Thin receivers inherited another surface's normal

The deferred PCSS normal reconstruction picks the side whose two depth samples best extrapolate to the receiver. Its baseline grows to four pixels at distance. A thin vertical surface can have unrelated depth on **both** sides. Picking the smaller error still creates a false, nearly grazing receiver plane. That plane changes both the geometric light horizon and shadow comparisons, producing dark patches on lit geometry or bright patches under blockers.

The shader now tests whether either side on each axis is consistent with the receiver. The tolerance includes camera-depth precision and a quarter of the first depth difference to allow modest curvature. When both sides of an axis fail, it uses the supplied surface normal and excludes the invalid differences from the slope-uncertainty calculation. Otherwise it retains geometric reconstruction, choosing a valid side when available. This reuses the existing eight depth fetches.

With the old reconstruction restored in the updated test, a one-pixel-wide rasterized vertical ribbon at 4 m returned **0.497688 visibility** despite having no occluder. The revised shader keeps it above 0.99. Raster tests cover 1/3/7-pixel ribbons, 4/40/160 m distances, three subpixel camera phases and light angles of 5/55/85 degrees, in deferred and forward paths. Synthetic thin-receiver tests additionally check foreground/background layers and real blockers; their maximum visibility error after correction is zero.

The fallback is deliberately limited to unresolved surfaces. A normal map or smoothed vertex normal is not an exact geometric plane; that limitation remains when camera depth cannot establish a plane. Existing curved-mesh, wall-occlusion and close-contact regressions still pass.

### Ordinary shadow sampling moved with unrelated screen coordinates

Both legacy PCF helpers snapped shadow X to a texel using a phase derived from screen/camera Y. Changing that phase moved the sample kernel even when the receiver's shadow coordinates were fixed. The new phase-invariance regression fails on the old shader.

Removed the snapping and retained the existing hardware bilinear comparisons and five weighted taps. Sun/moon and projector PCF now preserve continuous subtexel movement. This affects PCSS-disabled and hardware-fallback rendering; the PCSS disk pattern is unchanged.

### Projector fading divided by zero

The legacy projector helper used a sun-cascade weight even though it samples one projector map. Multiplication and division by that weight normally cancelled, but at `pos.z = -0.75 * shadow_clip.z` it became zero and produced NaN. Nearer receivers could also have negative weights, while the far fade was incorrectly divided by the weight.

Removed the redundant weighting. The helper now samples its one map and adds the bounded far fade, matching the PCSS projector path. Regression cases cover both slots, the exact former singularity and nearby depths, and the final fade with PCSS on/off.

### Sun fading could overbrighten forward surfaces

The shared directional helper added a fade to shadow visibility without bounding the result. A fully lit receiver returned **1.5** halfway through the last fade. Deferred light-buffer output clamps this, but forward receivers call the helper directly.

The shared helper now returns visibility in [0, 1]. Tests exercise lit and occluded receivers throughout the fade, with PCSS enabled and disabled.

## Rendering cost

No additional shadow/depth fetches, filter samples, passes, buffers, history, map resolution or draw submissions. The normal validity check adds a small amount of arithmetic to deferred PCSS; the ordinary PCF path loses snapping arithmetic and redundant projector weighting. Cleanup settings and cost are unchanged.

A GPU timer probe compared the old (`ac9eb130ba`) and revised production helpers on 256×256 deferred PCSS draws, with nine batches of 100 draws after warmup:

| Controlled map | Before, median ms/draw | After, median ms/draw |
| --- | ---: | ---: |
| Receiver plane | 0.00984 | 0.00965 |
| Soft shadow edge | 0.01007 | 0.00979 |
| Covered receiver | 0.01003 | 0.01030 |

These small measurements vary within roughly ±3%; they are a cost sanity check, not a full-viewer FPS claim. The GPU was an RTX 5090 with the user's viewer also running. Real scenes, other GPUs and driver scheduling can differ.

## Verification

- `test_pcss_gpu.py`: 725 cases, including 243 new thin-receiver, phase-invariance and distance-fade draws. Existing receiver-floor, narrow-caster, projector, cascade-warp, GLSL 330 fallback, GTAO and cleanup checks pass.
- `test_pcss_mesh_gpu.py`: 306 cases, including 162 new ribbon draws with actual D24 camera/shadow rasterization. Curved meshes, solid walls and finite-emitter horizons pass.
- `test_sss_shadow_gpu.py`: 1,786 shared SSS capture/path/lighting checks.
- `test_alpha_lighting_gpu.py`: 72 lighting and 180 projector cases, plus overlay rejection/fallback for all six transparency variants.
- `test_projector_cleanup_gpu.py`: 16 integration cases.
- `test_pcss_depth_precision.py`: 2,400 altitude/projection checks.
- Shadow extent traversal: 144 scenarios. Alpha submission, opaque/masked batching and 14 alpha-shader syntax checks pass.
- Release build: `cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2`. Source and staged `shadowUtil.glsl` SHA-256 hashes match.
- Full Release viewer startup with isolated settings, PCSS and projector shadows enabled reached `STATE_LOGIN_WAIT` without shader compile/link/sampler errors. The first short startup attempt expired before shader loading; the longer retry completed the check.

GPU tests use production shaders on an NVIDIA GeForce RTX 5090. They do not simulate the complete viewer's TAA resolve or reproduce a logged-in scene.

## Remaining observations

Camera-fitted cascades can still change coverage, texel scale and projection warp as the view moves. Stabilizing those transforms would change effective shadow resolution and deserves a separate measured experiment. Alpha-blended casters still use the existing coarse coverage pattern. Finite PCSS sampling and the geometric horizon on low-polygon meshes can still expose faceting; increasing global bias or weakening the wall safeguard would risk contact loss or light leaks. This pass leaves those behaviors intact because the controlled wall, floor and horizon tests did not establish another safe correction.

Restart the Release viewer to load the shader update. The useful in-world comparison is the same vertical surface and clothing/avatar edge under a moving camera and shallow light, first with PCSS on and then off, followed by TAA on/off if flicker persists. No graphics-default changes are required.

Background: [NVIDIA PCSS integration](https://developer.download.nvidia.com/assets/gamedev/docs/PCSS_Integration.pdf) discusses receiver-plane comparison bias; [Accurate Normal Reconstruction from Depth Buffer](https://atyuwen.github.io/posts/normal-reconstruction/) describes the extrapolation-based depth-neighbor selection used by this family of reconstruction methods. The validity fallback and regression findings above come from this viewer's implementation and tests.
