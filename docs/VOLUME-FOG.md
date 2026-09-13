# Box volume fog

Status: in progress; uncommitted. The user confirmed the volumes and their
point/sun/moon/projector lighting work in-world. Graphics controls and rendering
optimizations are implemented; their in-world quality/performance check is pending.

## Make a fog box

1. Rez an ordinary **box prim** and size/position/rotate it to enclose the fog.
2. Enable **Phantom**. Attachments are excluded in this prototype.
3. Set **all faces to 100% transparent**, with glow off. Phantom removes
   collision; it does not hide the prim. The viewer does not alter the object.
4. Put this in that prim's **Description**, not its name:

   ```text
   [vfog:0.5,<255,0,255>,6]
   ```

The tag can appear alongside other description text. Tags are case-insensitive.
The parameters are:

| Parameter | Meaning |
| --- | --- |
| `0.5` | Extinction per metre, from 0 to 10. Zero disables this box. Opacity grows with the distance travelled through it: `1 - exp(-density * distance)`. |
| `<255,0,255>` | Fog color, in sRGB with components from 0 to 255. This example is magenta. |
| `6` | Optional inward edge fade, in metres. Omit it or use zero for a hard boundary. The effective fade is limited to the smallest half dimension of the box. |

For a subtle first test in a 10 m box, try `[vfog:0.05,<200,220,255>,2]`.
Density 0.5 is quite thick: a 4 m path through its full-density interior is
approximately 86% opaque. Soft edges reduce the density near each face.

The fog follows the box's full transform, including linkset child transforms,
and works inside or outside the box at any altitude. Use the description on
each individual fog prim; a root tag is not inherited by its children.
Cut/hollow/tapered square-profile prims still use their full scale box bounds.
Mesh, sculpted, flexible and non-box prims are excluded.

`RenderVolumeFog` in Debug Settings is the viewer-wide switch, off by default.
Switching it off removes the effect immediately. Other viewers see only the
ordinary transparent phantom prim.

## Graphics preferences

Open **Preferences > Graphics > Volumetric Fog**. Changes apply immediately;
Cancel restores the values from when Preferences opened, and the five controls
participate in graphics preset saving and hardware-default reset.

- **Enable volumetric fog** turns the entire effect on/off.
- **Global intensity** multiplies every box's authored density, from 0 to 2.
  One preserves authored density. Zero skips fog rendering and releases its
  targets. It does not alter descriptions or independently brighten lights.
- **Quality** controls spatial resolution and light integration sampling.
- **Maximum local lights** limits point lights/projectors to 0–8. Sun/moon and
  ambient illumination remain available even at zero.
- **Receive sun, moon and projector shadows** controls shadow sampling inside
  the fog only. Disabling it saves work but permits light through blockers in
  fog. Surface shadow preferences remain independent.

| Quality | Fog resolution | Lighting sample budget | Minimum per soft/local-light segment |
| --- | --- | --- | --- |
| Performance | Half width and height | 16 | 4 |
| Balanced (default) | Half width and height | 24 | 6 |
| High | Full | 32 | 8 |
| Ultra | Full | 64 | 8 |

Half resolution casts one quarter as many rays. Only the fog is reconstructed;
scene color stays full resolution. The reconstruction rejects neighboring fog
samples across scene-depth discontinuities. Very thin geometry without a
matching low-resolution depth sample stays clear; fine volume boundaries and
beams can soften. High/Ultra avoid this spatial approximation. All four presets
keep the selected light budget, shadows and the same eight-volume limit.

Start with Balanced. Performance, fewer local lights and disabling fog shadows
offer additional savings. High sharpens fine beams/edges; Ultra better samples
lighting along the ray. Existing `RenderVolumeFogSteps` overrides are honored:
set it to **0** to let the quality preset choose samples. The tab reports an
active override.

## Lighting

The tag syntax is unchanged. With `RenderVolumeFogLighting` enabled (the default),
the tag color acts as the fog's scattering tint. Use white or light gray to show
colored lights clearly, for example `[vfog:0.05,<255,255,255>,2]`. Saturated fog
filters the incident light color: magenta fog absorbs much of a green light.

- **Point lights** use the prim's linear light color/intensity, effective range
  and falloff. Light spheres intersecting the fog are considered even if the
  emitter is outside that box. Point lights have no occlusion maps in this
  renderer, so their illumination can pass through walls.
- **Sun/moon** use the currently active celestial light, with its EEP direction
  and atmospherically attenuated color (including moon brightness), plus a small
  EEP ambient contribution. Both below the horizon means no direct celestial
  illumination. Existing cascaded shadows are sampled at each point in air.
- **Projectors** use the same frustum/virtual origin, texture, focus and range as
  surface projectors. Texture RGB/alpha shape and color the beam; explicit mip
  sampling follows focus. The surface-only ambiance term is omitted to keep
  illumination inside the beam. Up to four projector textures can be used.
- **Projector shadows** reuse the two active projector shadow maps and their
  transition fades. The `[no-shadow]` description tag is respected. Additional
  projectors still produce beams but cannot block them at scene occluders.

Sun/moon shadows require Sun/Moon shadows in graphics preferences. Projector
shadows require Sun/Moon + Projector shadows. Lighting still works with shadows
disabled. Fog does not change surface lighting, shadow-map allocation or which
projectors the existing renderer chooses to shadow.

The eight-light budget prioritizes active shadowed projectors, then estimates
contribution from brightness/range and proximity. The existing local-light count,
attachment-light preference and nearby-light exclusions still apply. Excess
projectors are skipped rather than incorrectly rendered as point lights.

Debug Settings update immediately:

| Setting | Default | Meaning |
| --- | --- | --- |
| `RenderVolumeFogIntensity` | 1 | Global authored-density multiplier, 0–2. Zero bypasses rendering. |
| `RenderVolumeFogQuality` | 1 | Performance (0), Balanced (1), High (2), Ultra (3). |
| `RenderVolumeFogShadows` | true | Receive existing celestial/projector shadows in fog. |
| `RenderVolumeFogLighting` | true | Disable to restore the original unlit appearance. |
| `RenderVolumeFogLightCount` | 8 | Local lights, 0–8, including up to four projectors. |
| `RenderVolumeFogSteps` | 0 | Zero follows quality; positive values override the sample budget (8–64). Narrow light/box boundaries add a minimum per segment. |
| `RenderVolumeFogAmbient` | 0.15 | Constant minimum illumination, 0–2, plus a small EEP ambient term. Lower it for dark rooms and clearer beams. |
| `RenderVolumeFogLightStrength` | 1 | Direct-light contribution, 0–8, independent of fog density. |
| `RenderVolumeFogAnisotropy` | 0.2 | Directional scattering, −0.8–0.8. Zero is uniform; positive values brighten views toward the emitter. |

## Discovery and editing

Descriptions are not included in normal simulator object updates. The viewer
scans loaded phantom box prims independently of face visibility/occlusion, and
requests descriptions through the existing shared render-metadata queue.
That queue sends at most ten requests per second; fog discovery adds at most
512 outstanding entries and examines at most 256 loaded objects per 0.1 s.

Local edits in the build tool update the cached description immediately.
Remote/script edits are polled approximately once per minute, with additional
delay possible in busy scenes or while objects/properties are loading. Opening
the object's build properties also retrieves its description. Removing the tag,
making it malformed, deleting the prim, or turning off Phantom stops its fog.
The box must have been streamed to this viewer by the simulator.

## Rendering and limits

- The eight nearest eligible boxes intersecting the camera frustum are used,
  ranked by distance to the box, with deterministic ties. Integration stops at
  the scene depth or the camera draw distance.
- Fog is integrated along the portion of each ray inside each oriented box.
  Unlit hard-edge uniform segments use exact exponential attenuation; unlit soft
  edges use 16 integration samples per segment. Lit fog also splits at light
  spheres and projector frusta, so small lights and narrow beams in large boxes
  are not skipped. Samples are distributed over the occupied fog path, with a
  quality-dependent minimum in locally illuminated/soft segments. Local lights
  outside that ray segment are excluded before sampling. Empty rays return
  before testing lights or sorting boundaries. Sampling stops once transmission
  falls below 0.00001, including within a segment. Hard-medium density/color and
  constant lighting are reused; uniform unshadowed segments need one sample.
  Per-ray array storage is reduced to improve GPU occupancy.
- Overlaps sum extinction and mix color by density at each segment/sample.
  Separate colored volumes retain their front-to-back order.
- Color is converted to linear space, composited before TAA/HDR post-processing,
  and then follows the existing exposure/tone mapping. Fog does not add opacity
  to the glow channel. No fog target is allocated when no eligible volumes exist.
- Integration writes RGB in-scattering and alpha transmittance to an RGBA16F
  target at the selected resolution. Unlit fog reads scene depth only; lit fog
  uses eleven inputs (depth, six raw shadow maps, four projector textures).
  A full-resolution color-only RGBA16F target reconstructs/composites the fog
  using scene color, depth and the fog target, then copies back to scene color.
  Scene depth is never sampled while attached to the active draw framebuffer.
  All sampler units are validated. Targets resize lazily on quality/window
  changes and are released when disabled, at zero intensity or with no volumes.
  GPU profiling labels it `volume fog`. It does not allocate shadow maps or
  alter PCSS surface filtering. It compares raw shadow depths before filtering,
  without surface-normal offsets. Failure to load the lit shader retains unlit
  fog; failure to allocate its target skips the effect.

Current limitations:

- **Shadow coverage:** sun maps are fitted to scene surfaces and can omit air
  outside those bounds. Out-of-map samples are treated as lit; there is no added
  fog-specific cascade coverage. No point-light shadows or additional projector
  shadow slots are introduced.
- **Light transport:** this is a direct-scattering approximation with camera-ray
  extinction. Light travelling through fog toward a sample does not yet receive
  separate medium attenuation, and there is no multiple scattering. Fine light
  texture/shadow patterns can require more samples.
- **Transparency:** fog is applied to the completed scene using its depth buffer.
  Opaque/cutout geometry clips it. Blended glass, hair and particles are not yet
  integrated at their individual depths, including with Exact OIT enabled.
  Water/refraction similarly needs a later integration pass.
- **Reflections:** fog is excluded from reflection probe, mirror/cube snapshot
  and impostor passes. HUD/UI rendering is unaffected.
- **Temporal filtering:** TAA still uses scene surface motion/depth; rapidly
  moving/editing fog boxes can need dedicated temporal handling later.
- This is volume rendering, not fluid simulation or smoke animation. Fog does
  not spill out of a box, and its boundaries need not match any enclosing room.

## Verification

Run:

```powershell
.venv/Scripts/python.exe scripts/tests/test_volume_fog.py
.venv/Scripts/python.exe scripts/tests/test_volume_fog_gpu.py
.venv/Scripts/python.exe scripts/tests/test_volume_fog_gpu.py --lighting
.venv/Scripts/python.exe scripts/tests/test_volume_fog_composite_gpu.py
cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2
```

The parser tests compile the production parser, including invalid numbers,
optional softness, whitespace/case, bounds, and resetting old values after an
invalid edit. The hidden-context GPU suite compiles the production GLSL 330
shader and compares it with analytic attenuation and an independent dense
numerical integrator. It covers wall depth, camera-inside, parallel rays, thin
boxes, near-plane fog, rotated/nonuniform boxes, colors, glow attenuation, soft
edges, and the eight-volume overlap/order limit.

Stage two adds analytic/numerical light comparisons for directional light,
moon-colored light, anisotropy, no illumination, point attenuation/falloff/range,
small lights in large fog, additive light counts, all four texture slots,
projector clipping/alpha/focus, all six shadow slots, shadow fades, disabled
shadows, cascade overlap, out-of-map coordinates and comparison-before-filtering.
The lit suite has 88 checks, including the global intensity and thin-beam checks
at all quality settings; the unlit suite has 46; the parser has 26. The settings
test checks the five UI bindings and four quality choices. Fourteen composite
GPU checks cover depth edges, thin occluders, sky, odd dimensions, a one-pixel
target, full-resolution scene/glow preservation and HDR limits. All pass.
The Release build, source/staged resource hashes and startup validation of the
11 lighting and 3 composite sampler units also pass.

`scripts/tests/test_volume_fog_preferences.py` runs through the viewer's `--leap`
API with separate smoke-test settings. It exercises the live controls, enable
dependencies, quality choices and Cancel restore, and saves a tab screenshot.
The live UI run passed and exited normally. To run it on Windows, use separate
settings and two LEAP arguments (the no-op avoids the command-line parser's
single-LLSD-value conversion):

```powershell
build-vc170-64/newview/Release/secondlife-bin.exe --multiple --settings volume-fog-quality-smoke.xml --set AutoLogin false --quitafter 120 --leap "E:/BoxxyViewer/.venv/Scripts/python.exe E:/BoxxyViewer/scripts/tests/test_volume_fog_preferences.py --noop" --leap "E:/BoxxyViewer/.venv/Scripts/python.exe E:/BoxxyViewer/scripts/tests/test_volume_fog_preferences.py"
```

`--lighting --preview --benchmark` also renders a synthetic point/projector scene
and times the production shaders. On this machine's RTX 5090, synthetic 1080p
full-view fog measured the following medians for **integration + reconstruction**:

| Quality | One point + one projector | Eight point lights | Eight points + directional shadow sampling |
| --- | --- | --- | --- |
| Performance | 0.10 ms | 0.52 ms | 0.77 ms |
| Balanced | 0.12 ms | 0.68 ms | 1.10 ms |
| High | 0.40 ms | 2.67 ms | 4.45 ms |
| Ultra | 0.66 ms | 3.14 ms | 5.78 ms |

Before these changes the eight-point-light integration alone took 3.26 ms;
the optimized High integration takes 2.62 ms, and Balanced plus reconstruction
takes 0.68 ms (about 79% less than the previous integration alone). The synthetic
Balanced/High preview has a mean absolute linear RGBA difference of 0.000383.
These timings exclude the final color copy, shadow-map rendering, TAA and all
other viewer work. They use one box and synthetic lights/shadow maps, not an
in-world workload or FPS measurement. An uncapped viewer can remain at high GPU
utilization while rendering more frames; compare GPU/frame times in the same scene.

The directional phase function and front-to-back integration follow the usual
direct-scattering model discussed in [NVIDIA's volumetric light-scattering
presentation](https://developer.download.nvidia.com/gameworks/events/GDC2016/Fast%20Flexible%20Physically-Based%20Volumetric%20Light%20Scattering%20-%20Notes.pdf).
The renderer uses artistic SL light units, so its strength is adjustable rather
than presented as a radiometric calibration.

In-world checks for the quality changes: compare High/Balanced while moving,
especially narrow beams, box edges and thin foreground objects; overlapping
volumes; quality changes during resizing; light/shadow budget changes; and GPU
frame times in the same scene. Transparency, water and temporal limitations
above still apply.
