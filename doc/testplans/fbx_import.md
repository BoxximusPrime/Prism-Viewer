# FBX mesh import

Status: in progress, uncommitted; Release build passed; viewer testing by user.

FBX is available in both **Build > Local Mesh > Load Mesh...** and the ordinary
**Upload > Model** picker. The same parser and conversion feed both workflows.
Upload still uses the viewer's normal preview, generated or file-based LODs,
physics selection, validation, fee calculation, and final Upload button.
Compiling or importing a file does not upload it.

Supported: binary/ASCII FBX, static polygon meshes (including quads/ngons),
multiple objects, parent/pivot/geometric transforms, unit/up-axis conversion,
mirrored/nonuniform transforms, normals, the first UV set, material slots,
diffuse colors/opacity and external or embedded PNG/JPEG/TGA/BMP diffuse textures.
Embedded images are cached in the viewer's cache directory; missing external
images leave the diffuse color available and are reported in the viewer log.
Blender's roughness/metallic factors are retained in Local Mesh.

The mesh uploader retains its existing diffuse material upload representation.
Full PBR node graphs, separate roughness/metallic maps, normal/emissive maps,
layered/procedural textures, texture transforms, extra UV sets and vertex colors
are not imported through this FBX path. Apply viewer PBR materials separately;
glTF/GLB remains available for richer Local Mesh material exports.

Animation is ignored; the stored static transforms are imported. Skinning,
blend shapes and geometry caches are rejected explicitly. Apply those modifiers
to a static copy before export if only the resulting shape is needed.

The importer splits large faces to stay within 16-bit vertex indices and splits
models at eight faces. It rejects files exceeding `ImporterModelLimit` after
splitting or two million triangles across mesh instances. Parser temporary and
result allocations each have a 512 MiB limit.

For Blender exports, select the intended mesh objects, enable Selected Objects
if appropriate, and export FBX. Keep copied image files with the export, or use
embedded supported images. Keep object/material names stable for reload and
custom LOD matching. The uploader recognizes `_LOD2`, `_LOD1`, `_LOD0`, and `_PHYS`
companion FBX files using its existing filename convention.

Manual checks:

- Load the same FBX in Local Mesh and the upload preview; compare orientation,
  dimensions, surface bindings, normals and UVs.
- Try several objects under a rotated/scaled parent, a mirrored object,
  a concave ngon, and a file exported with different axes/units.
- Try external images, embedded images, Unicode paths and a moved asset folder.
- In Local Mesh, assign PBR materials and numeric overrides, re-export, Reload,
  and confirm placement and material overrides survive. Turn overrides off to
  use exported roughness/metallic factors again.
- In upload, inspect generated LODs, load named custom LOD/physics FBX files,
  check models with more than eight material faces and large vertex counts,
  and use the existing fee calculation. Final paid upload remains a user action.
- Try truncated/non-FBX files and a skinned/blend-shape asset; import must report
  an error without producing a partial upload or replacing a good local preview.

The parser is vendored [ufbx 0.23.0](https://github.com/ufbx/ufbx/tree/v0.23.0),
with its MIT license and pinned source hashes in `indra/lib/ufbx`.
