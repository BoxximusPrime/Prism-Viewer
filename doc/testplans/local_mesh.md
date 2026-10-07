# Local Mesh preview

Local Mesh previews static models from `.fbx`, `.dae`, `.glb` or `.gltf` files.
For separate glTF exports, keep the `.bin` and texture files alongside the model.
DAE uses the viewer's Collada importer, preserving scene placement, units and
up-axis, diffuse colors/textures and fullbright materials. Collada polygons are
triangulated by that importer. Its usual limitations (such as negative scales)
apply; advanced Collada material effects are not reproduced. Keep referenced
textures available at their exported paths. DAE animation is not played.
Rigging and simulator physics preview are not part of this version.

FBX uses the same static importer as the mesh uploader (see [FBX import](fbx_import.md)).
Binary and ASCII FBX support polygon triangulation, scene transforms, units/up-axis,
normals, the first UV set, material slots and diffuse textures, including embedded
images. Local Mesh also uses the exported roughness/metallic factors. Separate
roughness/metallic, normal and emissive maps from FBX are not converted; use an
inventory/local PBR material or glTF/GLB for those. FBX animation is ignored and
rigging, blend shapes and geometry caches are rejected.

## Normal workflow

1. Rez a standalone cube you own and leave it selected in Edit mode.
2. Open **Build > Local Mesh** and choose **Load Mesh...**.
3. Select an FBX, DAE, GLB or glTF. The first load may pause while local preview shaders compile.
4. The mesh should replace the cube, with glTF Y-up converted to SL Z-up. Its
   longest side fits the cube; its center is at the prim origin. An unequal prim
   scale stretches the preview along those axes.
5. Move, rotate and scale through the normal build tools. Click the mesh itself
   to select the prim. The prim's editing bounds remain the control envelope.
6. Export changes over the source file. **Auto Reload** is on by default for each
   preview; turn it off to use **Reload** manually instead. The initial fit
   and pivot remain fixed: changing source bounds must not recenter the preview.
7. **Remove Preview** restores the prim's original geometry and appearance,
   retaining any moves/rotations/scales made through the build tools.

The assignment lasts for the current object instance/session. Closing the Local
Mesh window keeps the preview. Other viewers see the prim; its server geometry,
materials, physics and land impact are unchanged by loading/removing a preview.
Normal build-tool edits to the prim are ordinary server edits.

## Automatic reload

Status: in progress, uncommitted; Release build passed; viewer testing by user.

**Auto Reload** watches the selected preview's source model file for FBX, DAE,
GLB and glTF. Each preview keeps its own checkbox setting for the session.
Watching continues when the floater is closed or another object is selected.
It checks file modification time and size twice per second, then waits for one
second without changes before importing. A source that changes during automatic
import is discarded. Placement and material overrides follow the manual reload
path. Large models can briefly pause the viewer while importing, just as with
manual Reload.

Missing, empty or unavailable source files leave the last good preview in place
and are checked until they return. Failed imports retry up to three times, then
wait for a new file change or manual Reload. Turning Auto Reload off and back on
also retries a failed export. Removing a preview stops watching it.

Only the source model file is watched. Changes to separate textures or glTF
`.bin` files require re-exporting the model file too, or clicking **Reload**.
Inventory/local PBR materials retain their existing independent update behavior.

- Re-export each supported format and check that it updates within a few seconds.
- Move/rotate/scale the prim, assign a PBR material and numeric overrides, then
  re-export with changed bounds; the original placement and overrides must remain.
- Close the floater, change selection and re-export; the original preview updates.
- Load two previews, disable Auto Reload on one, and re-export both files. Only
  the enabled preview updates; manual Reload still works for the disabled one.
- Change the file while Auto Reload is off, then enable it; the new export loads.
- Export through a temporary file/rename, or delete/empty the source before
  restoring it; the last good preview remains until a valid export is ready.
- Save a broken export: retain the previous preview and report failure after
  bounded retries. Save a valid export to the same path; watching recovers.
- Remove the preview or delete the prim, then change the file; nothing reloads.

## World materials

Select a **Surface** or **All materials** in Local Mesh. The **PBR Material**
swatch accepts inventory materials and the picker's Local materials. These use
the world's lights, shadows and reflection probes with base color, normal,
metallic/roughness/occlusion and emissive textures. Local material file updates
continue while the floater is closed.

**Override roughness / metallic** is off by default, so the assigned or exported
material supplies its own factors. Enable it to edit **Roughness** and **Metallic**,
which replace those factors while still multiplying the material maps. Enabling
starts from each selected surface's current values. Unchecking clears these
numeric overrides without removing the assigned PBR material. Picking a different
material also turns overrides off. The fields show the material's factors while
disabled; a mixed checkbox means only some selected surfaces have overrides.
Try roughness 0.2 and metallic 1 for an obvious reflective test, then adjust for
the intended material. Changing either factor makes a fullbright surface lit.
glTF/GLB retains authored PBR values; the legacy DAE importer supplies diffuse
appearance only, so DAE starts at roughness 0.5, metallic 0. Legacy Collada
shininess/specular effects are not translated into PBR.

**Reload** rereads exported geometry, textures and materials while preserving
preview overrides by material name (duplicate names use occurrence order;
unnamed materials use their index). Keep names stable when re-exporting.
**Reset to Export** removes overrides for the selected surface(s), allowing new
exported material values to show. **Load Mesh...** starts fresh overrides.

Material changes in this floater are session-only. The ordinary Build Texture
tab still edits the real prim; use Local Mesh's swatch for preview assignments.

- Compare matte and polished surfaces inside a reflection probe; move around
  them to check view-dependent highlights. Repeat with a point light and sun.
- Apply textured opaque, masked and blended PBR materials, including double-sided
  materials. Test a source with a black tint and a source with vertex colors;
  replacing the material must replace its tint while preserving vertex colors.
- Assign an inventory material: the override checkbox should be off and the
  disabled fields should show its factors. Enable, edit both, then uncheck:
  restore the material's factors and keep its textures/assignment. Repeat with
  exported materials, All materials with differing values, Reload, and Reset.
- Set unequal prim scales; highlights and normal-map details must stay attached
  to the surface. Check a normal-map strength of zero in a glTF export.
- Override one slot, reorder named slots in an export, then Reload. The override
  must stay with its name. Reset must restore the newly exported appearance.
- Change the selected prim/slot while the material picker is open; it must close
  without assigning its pending choice to the new target. Cancel a choice too.
- Check slow/failed material fetches: preserve the last displayed appearance and
  show loading/error status. Removing a preview during fetch must remain safe.
- Close the floater, re-export a material selected from the Local tab, and confirm
  its textures/factors update. Reopen and verify the controls reflect it.

## Regression checks

Generate original fixtures with `python scripts/tests/local_mesh_fixtures.py`.
They are saved under the ignored `.logs/local-mesh-fixtures` directory.

- Load `reload.glb`: cyan/orange pyramid, two material slots, generated normals.
- Load `pyramid.dae`: textured/orange pyramid. Load `z-up-centimeters.dae`:
  orientation, size and texture direction should match despite different units/up-axis.
- Replace `reload.dae` with `taller.dae`, then `broken.dae`; check stable placement
  and retention of the last good preview on failure, just as with GLB.
- Textured GLB/glTF and DAE loads must return without freezing the main thread.
- Check DAE exports containing several objects, instanced meshes with different
  material bindings, and rigged files (rejected).
- Cancel the file picker; Load/Reload/Remove must become available again.
- Replace `reload.glb` with the contents of `taller.glb`; Reload should extend
  the tip without moving the base or changing the prim's transform.
- Replace that file with `truncated.glb`; Reload must report failure and leave
  the last valid mesh visible and selectable. Restore the good file and retry.
- Load `pyramid.gltf`, then `cycle.gltf`. The latter must fail without a crash
  or loss of the previous preview. Temporarily missing `.bin` files also fail.
- Pick empty space inside the hidden cube but outside the mesh: it must not
  select the hidden cube. Pick geometry extending outside the original cube:
  it must select the prim, with normal build tools rather than glTF node tools.
- Change selection while the picker is open: the file belongs to the captured
  prim. Removed/ineligible captured objects must not receive a preview.
- Closing/reopening the floater preserves controls for a selected preview.
- Remove the preview: original faces, selection and LOD updates must return.
- Check opaque materials, textures, alpha, lighting and shadows in-world.

`python scripts/tests/test_local_mesh.py` executes the production validation and
placement functions with native fixture types and fake GPU storage. It covers
invalid ranges/references, supported mesh restrictions, Y-up conversion, reload
pivot/scale retention, scene graph errors, and material/primitive grouping.
It also covers the DAE scene conversion, indexed geometry, UV direction,
instance materials, texture references, default materials and invalid buffers.
It also checks named override remapping, unmatched/new surfaces, fallback slots
and moving material batches between opaque/blended/double-sided variants.

`python scripts/tests/test_local_mesh_materials_gpu.py` runs the production glTF
shaders and GGX/IBL lighting with controlled probe samples on a hidden OpenGL
context. It checks material UBOs, vertex tint, nonuniform/mirrored transforms,
alpha masking/blending, normal strength, ORM and specular/probe response.
`test_specular_aa_gpu.py` covers the shared roughness and transparency paths.
These are shader regressions, not substitutes for an in-world probe review.
