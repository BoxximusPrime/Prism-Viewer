# Quick Photo integration checks — 2026-10-14

This is a feature smoke test, not a rendering performance comparison.

## Build and scope

- Release target: `cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2`.
- Executable: [secondlife-bin.exe](../../build-vc170-64/newview/Release/secondlife-bin.exe).
- Version reported by CMake: Prism Release 0.9.0.54540; working tree contains other uncommitted viewer work.
- Build logs: [clean Release build](../../.logs/quick-photo-build-clean.log), [verified preview build](../../.logs/quick-photo-build-verified.log), [transparent clothing fix](../../.logs/quick-photo-build-alpha-fix.log), [viewport alignment fix](../../.logs/quick-photo-build-viewport-fix.log).
- The first compilation exposed callback/API mismatches, which were fixed. Objects and the shared PCH were discarded. A subsequent link reported corrupt shared debug records; Release objects, PCHs and debug artifacts across project targets were then cleared consistently, excluding packages and other configurations.
- Clean Release build, the subsequent preview build, and the transparent clothing correction all passed. The final build completed the canonical `secondlife-bin.exe` target with exit code 0.

## Automated checks

- `scripts/tests/test_quick_photo.py`: passed. Exercises production camera-fit calculations across four presets and five avatar heights, zoom scaling, visible-body depth masking versus foreground clothing and background, preset/menu wiring, thumbnail padding, and stale-preview upload guards. The regression check compiles the actual alpha-group collection condition from `LLPipeline::postSort`: it failed for an avatar preview before the correction and passes afterward, while real shadow maps still skip forward-alpha lists and disabled alpha remains disabled.
- `scripts/tests/test_prism_collections.py`: passed after integrating the new collection buttons.
- `scripts/tests/test_outfit_dates_tpose.py`: passed.
- Viewport regression: the production `doWaterExclusionMask` method is compiled against recording render-target stubs which reproduce the full-size viewport restoration on target rebind. It failed before the guard and passes afterward for both 256×256 and 256×512 previews; ordinary world rendering still runs the mask. This verifies pass control and state preservation without capturing the avatar.

## Capture behavior and limitations

- Face and upper torso: 256×256. Full body and legs: 256×512. Full-resolution photos go to Snapshots. The folder thumbnail API expects square images, so tall photos use a 128×256 image centered in a 256×256 thumbnail with matching background padding.
- Uses the avatar-only appearance-preview target, with temporary camera state restored by the dynamic-texture lifecycle. No world-camera movement, graphics preferences, outfit changes, or detachments are needed to preview. The explicit Wear button does change the worn outfit/set.
- The neutral pose is started and stopped locally. A pre-existing instance of that pose is left alone.
- Mannequin mode is experimental: it desaturates visible classic-avatar pixels and user-marked body/head attachments. Baked skin attachments are suggestions the user can override. Baked clothing/tattoos cannot be separated from skin. The latest correction greys opaque skin before blending clothing, and greys transparent body fragments during OIT capture, so skin seen through clothing stays grey while clothing keeps its colour.
- Attachment filtering affects this photo only. Classic baked clothing remains visible. Large hair, wings, and unusual shapes may need the zoom control.
- An outfit or collection set must be worn before its preview is created. Changes to the current outfit version invalidate an existing preview. The user can refresh again after texture streaming settles.
- No paid upload has been performed as part of automated validation.

## Live evidence

- The Release viewer launched and completed remembered login in Kenosaki. The initial viewport was 3440×1369, vertical FOV approximately 60 degrees, with an unlocked camera. Camera global position was (284815.519058, 276675.765823, 23.697010); forward (-0.519978, -0.823087, -0.228366), up (-0.121968, -0.193067, 0.973575). No camera or graphics-setting changes were issued by the test tools.
- The user exercised Quick Photo and reported that it mostly worked, but the avatar's top was missing. Code tracing found that `generateImpostor` sets both `sShadowRender` and `sImpostorRender`, while the optimized `postSort` skipped transparent geometry whenever the shadow flag was set. The corrected condition includes avatar previews/impostors while preserving the real shadow-map optimization.
- Follow-up: the user reported transparent clothing was now visible off to the side. `renderGeomPostDeferred` still ran the water-exclusion mask during preview rendering. Its nested render target rebound the shared 512×512 preview buffer, replacing the smaller viewport used by the opaque pass. The world-only water mask now skips avatar impostor/preview rendering, matching the existing atmosphere and water-haze guards. The correction Release build passed with exit code 0.
- At the user's request, no screenshots or further visual inspection of the incomplete clothing preview were performed. There are no screenshot artifacts or timing samples for this run. Final clothing appearance, close/pose restoration, and paid inventory/thumbnail upload remain unverified in-world; the regression test establishes the corrected render-list behavior, not final pixel output.
- No warmup/sample counts or performance comparisons apply: this was a feature integration smoke test. The viewer was gracefully closed for the correction build, then relaunched successfully and completed remembered login (`STATE_STARTED`). No images were captured after relaunch.
- The viewport correction build was also relaunched and completed remembered login (`STATE_STARTED`). The user confirmed that this fixed alignment, then reported incorrect overlapping transparency and skin colour visible through transparent clothing in mannequin mode. No screenshots, outfit changes, or paid uploads were used during this follow-up.

## Overlapping transparency and mannequin follow-up

- Quick Photo now uses the existing Exact OIT capture/sort/composite shaders with private 512×512 capture resources, even when world OIT is disabled. Transparent geometry tests opaque depth but never writes it; per-pixel sorting replaces the previous rigged/unrigged alpha order. Water clipping and world GLTF rendering are excluded from the isolated pass. Ordinary alpha keeps the appearance preview's unlit colour path.
- Photo resources start at 32 MiB of nodes and can grow to 128 MiB, subject to the existing VRAM bound. Up to three complete render attempts handle overflow; a failed/unsupported capture leaves upload disabled and displays an error. World resources, pending statistics and GL image/storage bindings are preserved. OpenGL 4.3 is required for this capture path.
- Opaque body depth is collected without transparent layers. Matching pixels in the full opaque colour buffer are desaturated before alpha capture. Each marked body's transparent fragments are also desaturated before storage; clothing fragments preserve their colour and alpha.
- `scripts/tests/test_exact_oit_gpu.py`: passed on NVIDIA GeForce RTX 5090 / driver 617.14, hidden OpenGL 4.3 context. Twelve added cases render three synthetic overlapping layers in all six submission orders with mannequin mode on/off, using the actual capture and composite shaders, and compare against CPU blend results. The existing twelve scheduling/capture/sort/composite GPU scenarios also passed. These are correctness checks, not performance samples or avatar imagery. [Raw output](../../.logs/quick-photo-oit-gpu.log).
- `scripts/tests/test_quick_photo_oit.py`: passed. Compiles the production preview orchestration against recording GL/resource stubs and checks successful capture, overflow retry, memory-limit failure, missing alpha traversal, allocation failure, and restoration of world resources and bindings.
- `scripts/tests/test_quick_photo.py`: passed again, including framing, opaque body masking, alpha collection and viewport preservation.
- The hidden GPU fixtures needed their fog helper stub updated to link the current glow shaders. No runtime shader dependency was removed.
- [Release OIT build log](../../.logs/quick-photo-build-oit.log): passed with exit code 0; canonical executable written 2026-10-14 09:33 MDT. Staged capture/alpha shader hashes match the edited sources. In-world visual confirmation and upload testing remain pending; no screenshots or camera/settings mutations were performed.
- The new Release executable launched through `prism-viewer`. Initial shader startup exceeded the launch tool's 60-second connection wait, then status reached `STATE_LOGIN_WAIT`; remembered login completed successfully at `STATE_STARTED`. No avatar imagery was requested.
- Startup reported shaders loaded successfully (`loaded=1`); the slow Exact OIT material/emissive shader messages all reported `success=1`. The generic 266/267 planned-program count warning also exists in both prior startup records and is not new to this change.
- The user subsequently confirmed the transparency and mannequin results are working well.

## Low A pose follow-up

- Replaced the shared animation asset with a local procedural motion for Quick Photo. Shoulders rotate down 70 degrees from the bind pose, leaving arms 20 degrees from vertical; hips rotate inward 3 degrees and ankles counter-rotate to keep the feet level. Torso, head and limb rotations are held neutral while bone positions, scales and mesh body proportions are preserved.
- The motion uses normal blending at the viewer's highest joint priority so ordinary AOs cannot override it, has a short 0.2-second transition, and is stopped through the existing close/destruction path. No animation request is sent to the simulator and no asset download is required.
- `scripts/tests/test_quick_photo_pose.py`: passed. Applies the production pose table to the repository avatar skeleton and checks downward arm direction, 20-degree arm angle, feet close together without crossing, level feet, preserved position/scale channels, and local start/stop wiring. Exact spacing will vary with avatar proportions.
- `scripts/tests/test_quick_photo.py`: passed again. Existing photo framing, mannequin masking, alpha collection, viewport preservation and UI checks remain green.
- [Release pose build log](../../.logs/quick-photo-build-low-a-pose.log): passed with exit code 0; canonical executable written 2026-10-14 09:43 MDT. The previous viewer was already closed; the new build launched through `prism-viewer`. No screenshots or paid uploads were performed; final in-world pose appearance remains for user confirmation.

## Straight-leg stance adjustment

- The user confirmed the low A pose was close and requested a slightly wider stance with vertical legs. Reversed the hip rolls to 3 degrees outward, compensating for the reference skeleton's inward thigh offset, and reversed the ankle counter-rotation to retain level soles. Arm rotations remain unchanged.
- `scripts/tests/test_quick_photo_pose.py`: passed with the updated geometry checks. The reference skeleton's hip-to-ankle alignment is within 0.5 degrees of vertical in front view, feet are at hip width, soles are level, and arms remain 20 degrees from vertical. Avatar proportions can affect exact spacing.
- [Release stance build log](../../.logs/quick-photo-build-straight-legs.log): passed with exit code 0; canonical executable written 2026-10-14 09:54 MDT. The updated viewer relaunched through `prism-viewer`. No avatar screenshots or paid uploads were performed; final stance appearance remains for user confirmation.

## Closer face framing

- The user confirmed the stance and requested a closer face shot. Tightened the face preset from 0.74–1.07 to 0.85–1.03 of standing height, moving the framing centre upward toward the face. At default zoom this reduces camera distance by approximately 45% and makes the face about 1.8 times larger. The three-quarter angle, square resolution, zoom adjustment and other presets are unchanged.
- `scripts/tests/test_quick_photo.py`: passed, including camera-fit calculations at five avatar heights and zoom scaling.
- [Release close-up build log](../../.logs/quick-photo-build-face-closeup.log): passed with exit code 0; canonical executable written 2026-10-14 10:06 MDT. The updated viewer relaunched through `prism-viewer`. No avatar screenshots or paid uploads were performed; final crop remains for user confirmation.

## Neutral eyes, mannequin controls and collection isolation

- Added neutral rotations for classic and Bento alternate eye joints to the local photo motion. Its priority overrides ordinary eye tracking while preserving joint positions and scales; closing the floater releases the pose through the existing stop path.
- The Body column, its checkboxes and its explanatory text now appear only when mannequin mode is enabled. Hiding them preserves their values, which also identify body/head attachments to retain during isolation.
- Opening a collection set now enables Hide unrelated attachments automatically. Refresh reapplies membership filtering instead of carrying over stale Show selections. Set members and detected body/head attachments remain visible; manual Show overrides are still available until Refresh. Baked clothing/tattoos remain part of the avatar texture and cannot be isolated from skin.
- Existing incomplete outfit/set blocking now names up to three missing worn pieces, counts unique linked items, and summarizes additional missing pieces. The complete status is available in a tooltip. Broken links and inventory/appearance loading retain their separate messages.
- `scripts/tests/test_quick_photo_selection.py`: passed. Compiles production readiness, isolation and mannequin-control methods against small API stubs; covers duplicate links, non-wearables, missing attachment/clothing/body-part items, complete sets, ordinary folders versus outfits, broken links, incomplete descendants, busy outfit changes, body retention, hidden-control state preservation, and all combinations of the production refresh-selection expression.
- `scripts/tests/test_quick_photo_pose.py`: passed against the actual avatar skeleton, including forward directions for both eye rigs and unchanged arm/leg checks. `scripts/tests/test_quick_photo.py` also passed.
- [Release build log](../../.logs/quick-photo-build-eyes-collections.log): passed with exit code 0; canonical executable written 2026-10-14 10:20 MDT. The previous viewer was already closed. The updated viewer launched through `prism-viewer` and completed remembered login (`STATE_STARTED`). No screenshots, outfit changes, paid uploads or camera/graphics changes were performed; final in-world appearance remains for user confirmation.
