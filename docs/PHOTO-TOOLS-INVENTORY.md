# Photography tools inventory

Research date: 2026-09-09. Scope: Firestorm, Aperture, and the current Prism/BoxxyViewer working tree.

Status: inventory complete; implementation recommendations are proposed work, not implemented features. Existing features described below are confirmed in source, not newly verified in a running viewer. Existing work marked in progress in `FEATURES.md` retains that status.

The strongest first step is a Photo Studio floater that makes our existing renderer easy to use. The largest additional capabilities are live color grading, precise camera bookmarks and focus controls, a full joint poser, and reliable presets for complete photographic looks.

## Evidence and comparison boundaries

- Local baseline: commit `6f76800f2c709c5e40ffb8493d4fc2ded7899dbd`, including the working-tree changes present during this inventory. The product is branded Prism; the repository directory remains BoxxyViewer.
- Firestorm: inspected public `master` at [commit db512f2](https://github.com/FirestormViewer/phoenix-firestorm/commit/db512f2904b531d6ae47e8aeb532e480c727e914), dated 2026-09-09. This is a source baseline, not a claim that every feature is in a particular installed release. Its wiki was unavailable to this research session, so the comparison uses official source files.
- Aperture: inspected public default branch `dev` at [commit 933ecb0](https://github.com/ApertureViewer/Aperture-Viewer/commit/933ecb09cc09398ffe99151ede11043d1a75df76), dated 2025-06-21, alongside its [official wiki](https://github.com/ApertureViewer/Aperture-Viewer/wiki), which describes version 1.0.0. Documentation and development source can differ; numeric limits should be checked in the target release before being used as requirements.
- Aperture is based on Firestorm. Many shared controls expose inherited Second Life renderer settings. A longer slider range or higher default does not establish better rendering quality. That requires comparable scenes, settings, and GPU measurements.

## Feature comparison

“Expose” means the underlying capability is present and primarily needs a photography interface. “Extend” means existing code provides a foundation but lacks part of the workflow. “Add” means no equivalent complete feature was found in the inspected local paths.

| Capability | Firestorm / Aperture evidence | Our current viewer | What we would need |
|---|---|---|---|
| Unified photo workspace | Firestorm groups environment, shadows, effects, general quality, aids, and camera settings in [Phototools][fs-tools]. Aperture integrates eight areas in [APS][ap-tools]. | Controls are distributed among environment floaters, Graphics, Camera, Snapshot, and avatar tools. | **Add, high priority:** one toolbar-accessible Photo Studio floater, with clear sections, numeric entry, useful ranges, and per-control reset. Reuse existing settings and panels. |
| Sun, moon, sky, clouds, water | Both provide environment controls; Aperture embeds detailed atmosphere, cloud, celestial-body, and water editors in [APS][ap-tools]. | Personal Lighting and fixed sky/water editors already exist, including sun/moon positioning, haze, cloud cover, ambient/sun colors, water, and local environment overrides. [Local environment code][local-env] | **Expose:** environment selection, sun/moon direction, essential atmosphere controls, cloud pause, and a clear return to shared environment. Add a small set of deliberately authored photography presets. |
| Shadow direction and quality | Both expose sun/moon and projector shadows, resolution scaling, bias/offset, blur, and cascade-related tuning. [Firestorm controls][fs-tools], [Aperture shadow guide][ap-shadows] | Shadow modes are in Graphics. Resolution scale, bias, Gaussian/blur controls, and split tuning exist in settings and are consumed by the pipeline. [Local pipeline][local-pipeline] | **Expose, high priority:** quality, softness, and artifact correction, with advanced controls tucked away. Direction comes from sun/moon or projector placement. This does not initially require a new shadow renderer. |
| Ambient occlusion | Both expose SSAO strength and radius; Aperture also adds a runtime sample-count control. [Aperture SSAO source][ap-ao] | SSAO exists, with radius/strength/irradiance controls. The inspected shader uses a fixed eight-sample loop. [Local SSAO shader][local-ao] | **Expose** existing tuning first. **Extend** sample quality only if controlled image comparisons justify it; this requires shader work, not just a slider. |
| Reflections and mirrors | Firestorm exposes probe, mirror, and SSR controls. Aperture groups more reflection tuning into its own tab. [Firestorm controls][fs-tools], [Aperture controls][ap-tools] | Reflection probes, SSR, mirrors, update-rate/resolution options, and related debug settings already exist. [Advanced Graphics][local-graphics] | **Expose:** practical quality presets and relevant controls. Avoid copying higher maxima without checking allocation limits, frame time, and memory use. |
| Lens and depth of field | Both expose aperture/f-number, focal length, blur limits, resolution, and focus transition controls. Pointer-following focus and focus visualization are also present. [Firestorm controls][fs-tools], [Aperture lens guide][ap-lens] | DoF rendering and lens parameters exist. Focus follows the alt-camera target, mouselook hit, or cursor in flycam; ordinary UI mostly exposes the DoF toggle. [Local DoF implementation][local-dof] | **Expose, high priority:** aperture, focal length, and blur quality. **Extend:** independent focus picking, focus lock/manual distance, and a visible focus indicator. Preserve composition while adjusting focus. |
| Exposure and tone mapping | Both expose exposure and ACES/Khronos Neutral tone mapping. [Firestorm controls][fs-tools], [Aperture post guide][ap-post] | Exposure, both tone mappers, tone-map mix, HDR controls, and sharpening are already present. [Advanced Graphics][local-graphics] | **Expose:** put these beside photographic controls. An exposure-lock workflow is a separate proposed improvement; do not assume the exposure multiplier alone freezes adaptation. |
| Live color and tonal grading | Aperture adds contrast, highlights, shadows, whites, blacks, black lift, saturation, vibrance, RGB luminance weights, and three-way color balance with luminance preservation. [Post guide][ap-post], [final shader][ap-final] | The live renderer has exposure/tone mapping and sharpening. Snapshot filters exist, but an equivalent live grading suite was not found. | **Add, high priority:** a neutral-by-default grading stage and controls. Start with contrast, tonal ranges, saturation/vibrance, then three-way balance and monochrome channel weights. |
| Bloom and artistic lens effects | Both expose glow/bloom tuning. Aperture additionally exposes chromatic aberration and film grain. [Aperture lens guide][ap-lens], [final shader][ap-final] | Glow strength, width, iterations, extraction thresholds, and quality settings already exist. Artistic grain and chromatic aberration equivalents were not found. | **Expose** glow. **Add later:** optional grain and chromatic aberration. Vignette could be a further enhancement, but is not counted here as verified APS parity. |
| Camera placement and roll | Firestorm has photographic camera controls, roll, and store/load view actions. Aperture adds 12 standard-camera and 12 flycam slots. [Firestorm camera UI][fs-camera], [Aperture camera implementation][ap-camera] | Orbit/pan/zoom, FOV settings, camera smoothing, and joystick/flycam infrastructure exist. Standard Camera UI lacks the same roll and exact-shot workflow. | **Extend, high priority:** roll with reset, precise placement, lock, and named shot bookmarks containing position, focus, orientation, and FOV. Reuse existing camera APIs. |
| Camera presets versus shot bookmarks | Aperture stores global camera position, focus, focus-object identity, and roll for its standard slots. [Implementation][ap-camera] | Our current camera presets save FOV and avatar-relative camera/focus offsets. They do not save an exact world-space photographic shot. [Local preset manager][local-presets] | **Add:** actual shot bookmarks alongside existing camera presets. Define recall behavior after teleport or when the target object disappears; preserve global-coordinate precision. |
| Avatar animation timing | Firestorm provides slow-motion controls. Aperture exposes a global animation-time factor. [Firestorm controls][fs-tools], [Aperture avatar controls][ap-tools] | Local avatar freeze/resume is implemented; the standard slow-motion toggle sets our own avatar to 0.2x speed. The feature inventory still marks freeze as in progress pending in-world verification. [Avatar update][local-avatar], [feature inventory][local-features] | **Expose** freeze/resume and existing slow motion. **Extend:** continuous speed control across supported avatars using motion-controller facilities, with predictable resume behavior and compatibility with our animation synchronization. This controls local presentation, not simulator time. |
| Full avatar posing | Both contain a joint poser with body/face/hand controls, rotation/position/scale, mirroring, pose save/load, and BVH-related export options. [Firestorm poser UI][fs-poser], [Aperture poser source][ap-poser] | We have a pose-stand floater with 11 supplied animations and temporary AO suspension. It is not a joint editor. [Local pose stand][local-pose] | **Add, larger project:** joint selection/manipulation, pose persistence, undo/reset, and AO/freeze interaction. Start with self posing and explicitly supported targets. |
| Scene cleanup and lighting suppression | Photo panels collect avatar/HUD visibility, attached-light/particle controls, and diagnostic aids. Aperture exposes a fullbright toggle. [Firestorm controls][fs-tools], [Aperture controls][ap-tools] | HUD/UI capture switches, avatar complexity controls, attached-light and particle suppression, and 360 avatar hiding exist in different places. [Graphics panel][local-graphics-main], [snapshot UI][local-snapshot] | **Expose:** names, HUDs, particles, attached lights, and avatar visibility. **Extend:** cohesive temporary scene overrides and an optional fullbright suppression path, after checking every affected render path. |
| Framing and capture guides | Both snapshot floaters offer a capture frame and framing guides. [Firestorm snapshot UI][fs-snapshot], [Aperture snapshot UI][ap-snapshot] | Snapshot size, aspect constraint, preview, and UI/HUD exclusion exist. Equivalent framing-guide controls were not found. [Local snapshot UI][local-snapshot] | **Add, high priority:** rule-of-thirds and output-aspect guides that never appear in saved photos. Add convenient portrait, square, and landscape aspect presets. |
| Resolution, format, and output | Both offer local PNG/JPEG/BMP export, custom resolution, persistent save-location options, and timestamped naming. [Firestorm export UI][fs-export], [Aperture export UI][ap-export] | PNG/JPEG/BMP, JPEG quality, custom dimensions, 4K/5K/7680×4320 choices, filters, and a maximum dimension of 7680 already exist. Including UI/HUD clamps ordinary snapshots to window size. [Local export UI][local-export], [limit][local-limit] | **Expose and verify:** retain the capture implementation. Add convenient naming/location options where needed. Audit preview/export agreement, memory behavior, and effects at large sizes before promising improved output quality. |
| Depth and compositing output | Both offer depth and a separate “Depth (24 bit)” option, plus capture without post-processing. [Firestorm snapshot UI][fs-snapshot], [Aperture snapshot UI][ap-snapshot] | Color and depth output exist. The inspected depth readback converts the result to an 8-bit value; no separate 24-bit depth or no-post layer appears in the snapshot UI. [Local readback][local-readback] | **Extend, later:** higher-precision depth and an explicit post-processing bypass. HDR rendering does not itself mean HDR/RAW/EXR export. Those formats would be separate work. |
| 360 photography | Both snapshot interfaces provide access to 360 capture. [Firestorm snapshot UI][fs-snapshot], [Aperture snapshot UI][ap-snapshot] | A registered 360 capture floater, equirectangular output implementation, quality choices, and avatar-hiding option already exist. [Local 360 implementation][local-360] | **Expose and verify:** link it from Photo Studio. Test consistent exposure, skies, and supported effects across cube faces. |
| Saved photographic looks | Aperture has an explicit list of graphics-preset controls that includes its grading, lens, and shadow settings. [Preset list][ap-presets] | Graphics presets exist, but discover settings by walking the Preferences UI. Studio-only controls would not automatically join that list. Camera and environment state are separate. [Local preset collection][local-preset-collection] | **Extend, high priority:** explicitly include photographic controls. Keep reusable visual looks separate from location-specific camera bookmarks. A broader shot recipe linking environment, look, and camera would be our additional workflow. |
| Night-sky presentation | Aperture documents an expanded procedural starfield with color and twinkling. [Official feature overview][ap-home] | Environment star brightness and the existing sky renderer are present. | **Optional:** evaluate only after the core photo workflow. It is an environment-rendering project, not a prerequisite for good photo tools. |

## Recommended implementation order

### 1. Photo Studio using the existing renderer

Relative size: medium UI/integration work; highest immediate return.

Provide one floater with Environment, Light & Shadows, Lens & Camera, Color, Subject, and Capture sections. Populate it first with already-functional controls. Include our skin-scattering controls as a portrait option: this is an existing investment worth making accessible, with its current verification status preserved. [Current feature inventory][local-features]

Add per-control reset, saved looks, and an explicit restore-previous-settings action. For a temporary photo session, remember values before changing them and provide a clear way to keep the result. Reuse LLSD/settings, floater registration, environment cloning, and existing graphics/camera infrastructure. Do not make another independent renderer-settings store.

The first useful deliverable should let someone choose lighting, soften shadows, set portrait DoF, freeze a pose, select output dimensions, capture a photo, and return to their normal settings without hunting through Preferences.

### 2. Precise composition and capture

Relative size: medium camera and snapshot work.

Add ordinary-camera roll/reset, exact shot bookmarks, independent focus picking/lock, aspect masks, and framing guides. Keep camera FOV and DoF focal-length behavior coordinated so lens changes are understandable. Use world-space bookmarks without replacing existing avatar-relative camera presets.

Capture quality should include subject detail/complexity, texture readiness, anti-aliasing, shadow quality, DoF resolution, and reflections. Reuse our existing controls; a “Photo quality” preset should explain which expensive effects it enables. A higher resolution alone cannot repair low-detail geometry or unloaded textures.

### 3. Live photographic grading

Relative size: medium-to-large renderer/UI work; the clearest Aperture-style capability gap.

Start with contrast, highlights/shadows, white/black points, saturation, and vibrance; follow with three-way color balance and monochrome channel weights. Add grain and chromatic aberration after the basic grading behaves consistently. Temperature/tint would be a useful addition, but this inventory does not treat shader parameters alone as proof of a complete competitor UI.

Choose the intended position of each adjustment relative to exposure, tone mapping, gamma conversion, DoF, and sharpening. Aperture applies its artistic adjustments in the final screen pass; that is useful implementation evidence, not proof of recoverable HDR highlight detail. [Aperture pipeline][ap-pipeline], [final shader][ap-final]

Integrate narrowly with our current pipeline. Keep neutral settings visually neutral, preserve transparency and skin-lighting behavior, and explicitly define whether 360/depth/no-post captures include each effect. Existing snapshot filters should remain a distinct post-capture choice.

### 4. A complete poser

Relative size: large; valuable for portraits and fashion photography.

Treat this as its own feature, launched from Photo Studio. A first complete version needs joint selection, transforms, mirror/copy, undo/reset, pose save/load, and reliable exit/restoration. Integrate our AO suspension and freeze behavior. BVH export and broader target support can follow the core posing workflow. Copying a poser floater alone would not provide its animator, joint-manipulation, and persistence dependencies.

### 5. Targeted renderer and specialist improvements

Relative size: variable; prioritize using actual images and performance measurements.

Evaluate adjustable SSAO sampling, further shadow filtering, and reflection quality only when the existing settings show a specific limitation. Higher-precision depth export, fullbright suppression, night-sky work, and advanced shot recipes are separate candidates. A temporary local studio-light rig is also a possible future feature; it was not established as a distinct capability in the inspected photo suites.

## Where implementation would connect

| Area | Existing local entry points | Key observation |
|---|---|---|
| Floater and environment UI | [Registration][local-floaters], [environment adjust][local-env], fixed-environment editors and environment settings panels | Reuse local-environment editing and restoration behavior. |
| Lighting and quality | [Graphics controls][local-graphics], [settings definitions][local-settings], [pipeline][local-pipeline] | Most first-phase photo controls already have settings and live consumers. |
| Lens and camera | [DoF focus calculations][local-dof], [camera floater][local-camera], camera/joystick APIs | Extend focus and ordinary-camera roll without confusing them with flycam behavior. |
| Presets | [Preset manager][local-presets], [Preferences control discovery][local-preset-collection] | Explicitly capture new photo controls; current UI traversal is insufficient for a new floater. |
| Capture | [Snapshot floater][local-snapshot-cpp], [snapshot preview][local-preview], [window readback][local-readback], [360 capture][local-360] | Preserve existing export; add guides and new output modes at the appropriate layer. |
| Subject controls | [Pose stand][local-pose], [avatar freeze][local-avatar], motion controller | Pose stand, animation timing, and joint posing are related but distinct systems. |

## Validation for future implementation

These checks are proposed acceptance criteria, not tests performed by this inventory:

- A portrait with mesh skin, hair, transparent clothing, and a projector light: check shadows, skin scattering, transparency, and DoF edges together.
- Interior, daylight exterior, and night scenes: confirm environment overrides, reflection behavior, exposure, and neutral grading.
- The same composition at window resolution, 4K, and 7680-pixel output: compare framing, focus, grain/effect scale, output formats, and peak memory. Also test portrait and square crops.
- Save/reload a look with Preferences closed; recall a shot with a missing focus target; restore settings after closing the photo workflow or teleporting.
- Freeze, slow, resume, and pose with AO enabled; ensure leaving photo tools restores intended animation behavior.
- Compare 360 faces and final panorama for exposure or effect seams. Validate depth and no-post modes separately from ordinary color output.

No runtime code was changed and no build was required for this inventory. `FEATURES.md` remains the record of implemented/in-progress viewer features; proposed work above should enter it when implementation begins.

[fs-tools]: https://github.com/FirestormViewer/phoenix-firestorm/blob/db512f2904b531d6ae47e8aeb532e480c727e914/indra/newview/skins/default/xui/en/floater_phototools.xml
[fs-camera]: https://github.com/FirestormViewer/phoenix-firestorm/blob/db512f2904b531d6ae47e8aeb532e480c727e914/indra/newview/skins/default/xui/en/floater_phototools_camera.xml
[fs-poser]: https://github.com/FirestormViewer/phoenix-firestorm/blob/db512f2904b531d6ae47e8aeb532e480c727e914/indra/newview/skins/default/xui/en/floater_fs_poser.xml
[fs-snapshot]: https://github.com/FirestormViewer/phoenix-firestorm/blob/db512f2904b531d6ae47e8aeb532e480c727e914/indra/newview/skins/default/xui/en/floater_snapshot.xml
[fs-export]: https://github.com/FirestormViewer/phoenix-firestorm/blob/db512f2904b531d6ae47e8aeb532e480c727e914/indra/newview/skins/default/xui/en/panel_snapshot_local.xml
[ap-tools]: https://github.com/ApertureViewer/Aperture-Viewer/blob/933ecb09cc09398ffe99151ede11043d1a75df76/indra/newview/skins/default/xui/en/floater_ap_phototools.xml
[ap-home]: https://github.com/ApertureViewer/Aperture-Viewer/wiki
[ap-shadows]: https://github.com/ApertureViewer/Aperture-Viewer/wiki/Shd-Tab-%E2%80%90-Shadows-Settings
[ap-lens]: https://github.com/ApertureViewer/Aperture-Viewer/wiki/Lens-Tab-%E2%80%90-Lens-Settings
[ap-post]: https://github.com/ApertureViewer/Aperture-Viewer/wiki/Post-Tab-%E2%80%90-Post%E2%80%90Processing-Effects
[ap-camera]: https://github.com/ApertureViewer/Aperture-Viewer/blob/933ecb09cc09398ffe99151ede11043d1a75df76/indra/newview/apfloaterphototools.cpp
[ap-poser]: https://github.com/ApertureViewer/Aperture-Viewer/blob/933ecb09cc09398ffe99151ede11043d1a75df76/indra/newview/fsfloaterposer.cpp
[ap-snapshot]: https://github.com/ApertureViewer/Aperture-Viewer/blob/933ecb09cc09398ffe99151ede11043d1a75df76/indra/newview/skins/default/xui/en/floater_snapshot.xml
[ap-export]: https://github.com/ApertureViewer/Aperture-Viewer/blob/933ecb09cc09398ffe99151ede11043d1a75df76/indra/newview/skins/default/xui/en/panel_snapshot_local.xml
[ap-presets]: https://github.com/ApertureViewer/Aperture-Viewer/blob/933ecb09cc09398ffe99151ede11043d1a75df76/indra/newview/app_settings/graphic_preset_controls.xml
[ap-pipeline]: https://github.com/ApertureViewer/Aperture-Viewer/blob/933ecb09cc09398ffe99151ede11043d1a75df76/indra/newview/pipeline.cpp#L8673
[ap-final]: https://github.com/ApertureViewer/Aperture-Viewer/blob/933ecb09cc09398ffe99151ede11043d1a75df76/indra/newview/app_settings/shaders/class1/deferred/postDeferredNoDoFF.glsl
[ap-ao]: https://github.com/ApertureViewer/Aperture-Viewer/blob/933ecb09cc09398ffe99151ede11043d1a75df76/indra/newview/app_settings/shaders/class1/deferred/aoUtil.glsl
[local-env]: E:/BoxxyViewer/indra/newview/llfloaterenvironmentadjust.cpp:219
[local-pipeline]: E:/BoxxyViewer/indra/newview/pipeline.cpp
[local-ao]: E:/BoxxyViewer/indra/newview/app_settings/shaders/class1/deferred/aoUtil.glsl:59
[local-graphics]: E:/BoxxyViewer/indra/newview/skins/default/xui/en/floater_preferences_graphics_advanced.xml
[local-graphics-main]: E:/BoxxyViewer/indra/newview/skins/default/xui/en/panel_preferences_graphics1.xml
[local-dof]: E:/BoxxyViewer/indra/newview/pipeline.cpp:7926
[local-presets]: E:/BoxxyViewer/indra/newview/llpresetsmanager.cpp:249
[local-avatar]: E:/BoxxyViewer/indra/newview/llvoavatar.cpp:5131
[local-features]: E:/BoxxyViewer/FEATURES.md
[local-pose]: E:/BoxxyViewer/indra/newview/llfloaterboxxytpose.cpp
[local-snapshot]: E:/BoxxyViewer/indra/newview/skins/default/xui/en/floater_snapshot.xml
[local-export]: E:/BoxxyViewer/indra/newview/skins/default/xui/en/panel_snapshot_local.xml
[local-limit]: E:/BoxxyViewer/indra/newview/llviewerwindow.h:153
[local-readback]: E:/BoxxyViewer/indra/newview/llviewerwindow.cpp:5407
[local-360]: E:/BoxxyViewer/indra/newview/llfloater360capture.cpp
[local-preset-collection]: E:/BoxxyViewer/indra/newview/llfloaterpreference.cpp:929
[local-floaters]: E:/BoxxyViewer/indra/newview/llviewerfloaterreg.cpp
[local-settings]: E:/BoxxyViewer/indra/newview/app_settings/settings.xml
[local-camera]: E:/BoxxyViewer/indra/newview/llfloatercamera.cpp
[local-snapshot-cpp]: E:/BoxxyViewer/indra/newview/llfloatersnapshot.cpp
[local-preview]: E:/BoxxyViewer/indra/newview/llsnapshotlivepreview.cpp
