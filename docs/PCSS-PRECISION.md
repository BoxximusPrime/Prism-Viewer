# PCSS precision investigation — September 12, 2026

Status: fixes implemented and regression checks passed; uncommitted. After the user closed the viewer and authorized a coordinated rebuild, the Release build passed. The staged PCSS and SSS shader hashes match the sources. The user reports the precision changes helped; further in-world verification is pending.

The reported symptoms are a broad shadow flickering across an open square mesh floor while zooming, some movement with a stationary camera, and occasional shadowed terrain squares. The location is approximately 3,000 metres above the region.

## Findings and changes

### World translations were rounded before cancellation

`generateSunShadow()` composed `bias * projection * lightView * inverseCameraView` entirely in float, including the camera inverse. The intermediate projected world translation becomes large at skybox heights. Rounding it before cancelling the camera translation changes the receiver's shadow depth as the camera moves. PCSS replaced the legacy normalized-depth bias with a small world-space contact bias, making these errors more visible.

The composition and camera inverse now use double precision until the final shader matrix is stored. The PCSS inverse is also computed in double precision from that stored matrix, so it describes the same transform the shader receives. GPU uniforms remain ordinary floats; map formats and resolution are unchanged. The focused SSS shadow path already uses this approach.

Production expressions compiled with bundled GLM were checked over 200 camera positions per altitude and projection type. At 3,000 metres:

| Projection | Previous maximum depth error | Revised maximum depth error |
| --- | ---: | ---: |
| Orthographic sun | 0.5392 mm | 0.0021 mm |
| Warped sun | 0.5068 mm | 0.0073 mm |
| Projector | 37.7370 mm | 0.8068 mm |

These are synthetic measurements of matrix composition, not a capture of the user's scene. Projector precision also depends on near plane and distance. The default PCSS contact bias is 3.5 mm.

### An exact plane does not exactly match rasterized shadow depth

The shader corrects each comparison to the receiver plane at the shadow texel's centre, but previously budgeted no error for subpixel rasterization of the caster. A coarse shadow map on a steep square mesh reproduced self-shadowing in the forward path, where camera depth reconstruction is absent. Quarter-pixel camera changes altered the patches; some affected samples went completely dark.

A small additional depth allowance now scales with receiver slope, shadow texel size and the device's `GL_SUBPIXEL_BITS`. It is one subpixel step, rather than a full shadow texel. On the test GPU that is 1/256 of a texel. The same allowance is used for blocker classification and final filtering. This addresses the rasterized floor regression without raising the user's contact-bias setting.

As with any depth allowance, extremely close blockers within that numerical tolerance can merge with the receiver. Existing close-contact, sloping-receiver and solid-wall tests still pass.

## Verification

- `test_pcss_depth_precision.py`: 2,400 production-expression checks, covering heights 0, 1,500, 3,000 and 4,000 metres; orthographic sun, warped sun and projectors; inverse round trips.
- `test_pcss_gpu.py`: 316 cases, including additional off-axis distant planes with camera-depth quantization and current sun-size/bias defaults. Existing cases include contacts, blocker-distance softness, projectors, GLSL 330 fallback and GTAO integration.
- `test_pcss_mesh_gpu.py`: 144 cases, including 54 new square-floor cases with real D24 camera/shadow rasterization, three distances, three slopes and three subpixel camera phases in deferred and forward paths. Wall and emitter-horizon cases also pass.
- `test_sss_shadow_gpu.py`: 728 shared shadow-path checks passed.

GPU checks ran on an NVIDIA GeForce RTX 5090. They do not constitute cross-vendor or in-world validation.

## Remaining limits and next observation

The four-texel occluder guard was examined because its hard decision can resemble square artifacts. Simply broadening its uncertainty or comparing every texel to the extrapolated plane weakened legitimate wall shadows in regression tests; that guard remains unchanged apart from receiving the raster allowance. There is no confirmed evidence yet that it causes the reported terrain patches.

Reconstructed normals remain uncertain on distant surfaces at a grazing light angle. An exploratory test with a 5-degree emitter and a very steep quantized plane showed a small horizon-visibility variation; the current-default tests pass. The finite-emitter horizon calculation has not been changed.

The viewer still uses float geometry/view matrices, D24 depth and camera-fitted cascades. This change removes specific numerical errors, not all causes of shadow motion. TAA changes the camera's sample positions even while it is stationary, which can expose remaining thresholds. The new floor test exercises subpixel phase changes but does not run the full TAA history resolve.

The decisive next check is the original square floor at 3,000 metres: repeat the same zoom and stationary view with this Release build, then inspect the terrain patches. If the issue persists, compare PCSS on/off and TAA on/off in that scene to separate remaining shadow precision, cascade fitting and temporal sampling behavior.

Background references: [Khronos depth-buffer precision](https://wikis.khronos.org/opengl/Depth_Buffer_Precision) and [NVIDIA's original PCSS description](https://download.nvidia.com/developer/SDK/Individual_Samples/MEDIA/docPix/docs/PCSS.pdf).
