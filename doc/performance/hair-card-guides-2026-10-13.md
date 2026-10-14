# Card-based hair guides — 2026-10-13

Status: implemented and smoke-tested in Release; uncommitted. Broader hairstyle/animation validation remains.

## Change

Optional **Fit ropes to hair cards** detects connected UV ribbons in the private, shape-aware neutral skeleton. Each accepted ribbon gets nine equally spaced guide points, oriented from the endpoint nearest the head toward the tip. A frozen source-vertex table stores the owning rope and distance along it. Colour, depth/shadow and current/previous TAA use this table. A card rotates around its rope centreline, preserving its cross-section width. Root and bending gradients use distance along the card.

The radial mode remains selectable and supplies automatic fallback for unrecognized or over-budget geometry. The new **Card rope limit** defaults to 64, maximum 128, in addition to 4–64 radial ropes. Detection welds matching position/UV seams, without merging nearby crossing cards. Broad/degenerate islands and detached fragments whose nearest endpoint is over 35 cm from the crown fall back. This is topology/UV inference, not texture-alpha segmentation: connected branched meshes, unusual UV layouts and roots not nearest the head remain limitations. Twist is inferred from tangent changes; no independent torsional simulation was added.

**Show detected cards and rope assignments** draws card wireframes and ropes with matching colors. Grey wireframes/ropes indicate radial fallback. Point colors retain yellow pins, red contact and cyan free nodes. Grey thin rest ropes remain visible. The overlay uses the rendering deformation function and bindings, rather than a separate approximation.

## Work limits

- At most 200,000 input vertices and 200,000 triangles across a fit; over-budget objects stay radial.
- At most 192 total guides, dispatched in groups of at most 32 ropes. Existing per-segment ray traversal/triangle limits are unchanged.
- At most 30,000 debug triangles. A limited overlay does not mean remaining geometry is missing from rendering.
- Existing bounded outer-head fitting now uses each guide point's own height, including non-radial cards.
- Diagnostic readbacks accommodate the same hard guide cap; binding/debug data is excluded from per-frame readback.

## Automated checks

Passed: `test_hair_cards.py` (separate/crossing cards, reversed UVs, seam welding, root-to-tip fitting, broad/invalid/detached-tip fallback and input budget); `test_hair_cards_gpu.py` (fixed ownership, 90-degree cross-section rotation, radial/invalid-ID fallback, legacy avatar shader compatibility, production TAA and all 192 guides in bounded batches); `test_hair_head_fit.py` (including different card/radial heights); `test_hair_binding_gpu.py`; `test_hair_deform_gpu.py` (2,176 checks and production shader paths); `test_hair_guides_gpu.py`; `test_hair_segment_rays_gpu.py`; `test_hair_mesh_selection.py`. Settings and Hair panel XML parse.

The segment-ray stress fixture remains bounded at 1,024 rays, 65,536 node visits and 32,768 triangle tests per frame for 64 ropes, including a 0.25-second frame / 30 substeps. Its timings are test-fixture data, not a live performance comparison.

## Build and live session

No optimization claim is made from short smoke captures.

### First live iteration

Build SHA-256 `edc485d44efa5ab3195c654796cb7f0eb13da10bda8fea34be21c26f789d6631`; [build log](../../.logs/hair-cards-release-build.log). Brianconnais, Legacy Perky / LeLutka Avalon and the worn nova. Winter hairstyle; 3440×1369. Started with animated mesh, guides and gravity enabled, root radius 0.07 m, gradient 0.20 m, stiffness 6, retention 1, damping 16, friction 0.35 and elasticity 0. Shader startup initially exposed the legacy avatar's `vec4 weight` declaration; the hair path now matches it, with a dedicated regression. A failed initial startup was closed and the corrected full shader set loaded successfully.

| Capture | Warmup / measured | End-state guides | Observation |
|---|---:|---:|---|
| [Radial](../../.logs/viewer-mcp/20261013T212856Z-profile-8c967f3d.json) | 180 / 300 | 64 radial | Existing mode renders; no diagnostic drops. |
| [Card limit 64](../../.logs/viewer-mcp/20261013T212914Z-profile-6971cc3b.json) | 180 / 300 | 64 radial + 64 card | 213 candidate ribbons; default limit falls back above 64. |
| [Card limit 128](../../.logs/viewer-mcp/20261013T213057Z-profile-fb7e80c7.json) | 180 / 600 | 4 radial + 128 card | User adjusted settings during the session; 1,188 points captured without dropped readbacks. |

These are smoke checks, not controlled performance comparisons: camera/rope density changed, attachments were still settling after login, and diagnostics add CPU/readback overhead. The last capture's guide GPU median was 1.466 ms, p95 2.813 ms; inclusive scopes are not summed.

The colored overlay exposed detached lower fragments creating artificial pinned roots, prompting the 35 cm scalp-anchor check in the final iteration. The 213-candidate count above therefore describes the initial detector, not the final one. Wireframe rendering is capped at 30,000 triangles, and imported vertex totals include hidden material faces; they are not visible-hair coverage percentages.

### Final iteration

Canonical executable: `E:/BoxxyViewer/build-vc170-64/newview/Release/secondlife-bin.exe`. SHA-256 `8055e9b15d35eb2ecaf2f8ab083a44cb1bb6d36a97620f78a5741ef255b1336a`. [Successful Release build log](../../.logs/hair-cards-release-final.log). The final startup loaded all 267 shader programs successfully. The card detector regression includes the detached-fragment case, and the binding/deformation GPU suites were rerun after the shader compatibility fix.

[Final capture](../../.logs/viewer-mcp/20261013T213532Z-profile-bd5f06a9.json): 600 warmup + 600 measured frames, same Brianconnais avatar/outfit and 3440×1369 viewport. [Starting camera](../../.logs/viewer-mcp/20261013T213449Z-hair-cards-final-start-e1d51fd8.camera.json). Animated mesh, gravity and guides remained enabled. User's radial density was now 4; card limit temporarily 128. Existing guide-point overlay was enabled; card wireframes were disabled during the timing capture. Other hair physics values remained as listed above.

- 199 accepted candidate cards, 17 rejected islands; the 128-card cap was reached. Remaining geometry uses radial fallback.
- 132 total guides / 1,188 points, 99,899 body-shell triangles. Head clearance completed within its budget (165,374 ray tests).
- Across the 600 measured frames: zero guide refits, zero invalid histories and zero dropped diagnostics. Largest recorded point step was 18.24 mm; largest tip step 6.94 mm. This does not establish that all contact jitter is eliminated.
- Guide GPU median 1.852 ms, p95 3.716 ms. One smoke capture on an RTX 5090, with diagnostics, is not a performance guarantee or controlled comparison.
- [Card assignment overlay](../../.logs/viewer-mcp/20261013T213641Z-hair-cards-final-overlay-74dda3ab.png), [card-mode surface](../../.logs/viewer-mcp/20261013T213707Z-hair-cards-final-surface-613785c1.png), [radial fallback surface](../../.logs/viewer-mcp/20261013T213709Z-hair-radial-fallback-surface-6e1cfd97.png). Surface screenshots use the same close-up camera but different animation frames. The dense overlay displays matching card/rope colors and original pin/contact markers.

Restored the temporary card toggle/limit/debug controls, the user's enabled guide overlay, and the pre-preview camera; released the camera lock. The updated viewer remains running. Other hairstyles, unusual UV topology, and independent twist remain untested/unsupported as described above.
