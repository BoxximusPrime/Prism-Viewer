# Edit window: controls and design study

Status: implemented in the working tree, 2026-09-09; uncommitted. The five Edit tabs now use grouped native controls, horizontal XYZ transforms, direct clipboard actions, and scrollable form bodies. The shared toolbar has additional separation above the tabs. Modifier stepping and the original selection rules are retained.

Visual refinement, 2026-09-10: the five tabs use rounded charcoal section backgrounds, subtle outlines, and larger headings, following the approved concept more closely. Texture channels use native segmented buttons. The Identity section has additional bottom padding, and the Content inventory uses the same rounded treatment. The viewer's existing rounded image mask supplies the corners; no new rendering code or dependencies were added.

Scope: the shared tools and selection summary, plus General, Object, Features, Texture, and Content. The original concept study covered General, Object, and Texture; Features and Content were implemented in the same style.

Tab refinement, 2026-09-10: all five property tabs use the approved Prism charcoal/amber artwork with raised selection and hover/pressed/disabled states. Their 80px fading rail belongs to the tab container, so it follows docking/resizing and disappears with the property tabs in Land mode. Existing property panels and localized labels are retained. (in progress; Release build and XML preservation/staging checks passed; integrated appearance awaits runtime verification)

Docking, 2026-09-10: the title bar's Dock/Undock button switches between a right-hand dock and the saved floating rectangle. The dock has a flush charcoal background without the floating window's outer rounded frame; the inner rounded sections remain. It reduces the actual world viewport and moves the edge toolbars clear of it. Drag its left edge to resize; `BuildEditDocked` and `BuildEditDockWidth` remember the preference. Docking needs at least 880 × 460 scaled UI pixels, including a 320-pixel world area; smaller windows temporarily use the floating layout. Closing Edit releases its viewport space. Debug → UI Tests → Edit Dock opens an inert preview of the real docking controller on the login screen.

Concept boards: [General: compact / spacious](concepts/edit-window-2026-09-09/general-concepts.png), [Object: columns / transform rows](concepts/edit-window-2026-09-09/object-concepts.png), [Texture: legacy / PBR / media](concepts/edit-window-2026-09-09/texture-modes.png).

Revised board: [Complete General / Object / Texture windows with shared tools](concepts/edit-window-2026-09-09/full-window-concept.png). Generated with the built-in ImageGen tool using this [full prompt](concepts/edit-window-2026-09-09/full-window-prompt.txt). This board develops the B layouts and shows Legacy textures; the original Texture board still documents the other material modes.

The images are generated design studies. Numeric examples and permission states are illustrative. Inapplicable controls are sometimes shown disabled for discoverability; final implementation must follow the actual selection rules described below. The original three boards omit the shared toolbar and are tab-content studies. A complete window must reserve space for the shared controls described next; final dimensions require an implementation and screen-size check.

## Shared tools above the tabs

These controls belong to the build/edit window, independently of the selected properties tab. Keep the common header stable when switching General, Object, Features, Texture, and Content. Its contextual tools change with the primary tool mode.

| Group | Existing controls and information | Current behavior to preserve |
| --- | --- | --- |
| Primary tool mode | Focus, Move, Edit, Create, Land | The top-level Move tool is the grab tool; it is distinct from Move within Edit mode. The current icon buttons can gain short visible labels. |
| Edit manipulation | Move; Rotate (Ctrl); Stretch (Ctrl+Shift); Select Face | Four mutually exclusive modes; a segmented row can replace the radio-button stack. |
| Linked parts | Edit linked checkbox; previous arrow, selected prim's link number, next arrow; Link; Unlink | Shows the scripting link number for one selected prim while Edit linked is on: 0 for an unlinked prim, 1 for a linked root, and 2 onward for children. Arrows cycle through parts, wrap through the root, and skip seated avatars, including in Select Face mode. Hidden for no or multiple selections; arrows disable without another prim. Existing Link/Unlink gating remains. |
| Stretch behavior | Stretch Both Sides; Stretch Textures | Two independent checkboxes. Currently visible throughout Edit mode, not only while Stretch is selected. |
| Grid | Snap checkbox; grid/ruler dropdown; grid Options button | Keep Snap independent of the ruler choice. Options opens the existing grid-options floater. |
| Grid choices | World / Local / Reference for world objects | Attachments use Attachment / Local / Reference; HUDs use Screen / Local. These choices depend on selection type, not the properties tab. |
| Help/status | Contextual tool instruction | For example, "Drag to move, shift-drag to copy." Preserve mode-specific help and keyboard-modifier hints. |
| Selection summary | Selected object count; land impact; More info link | Preserve the link to object weights and the existing conditional states. |
| Selection summary | Faces selected; Nothing selected | Face information is conditional on face mode and a single selected object; the empty-selection message replaces the normal summary. |

Other primary tool modes replace the Edit controls rather than adding another permanent block:

| Mode | Existing contextual controls |
| --- | --- |
| Focus | Zoom; Orbit (Ctrl); Pan (Ctrl+Shift); zoom slider. |
| Move (grab) | Move; Lift (Ctrl); Spin (Ctrl+Shift). |
| Create | Cube, Prism, Pyramid, Tetrahedron, Cylinder, Hemicylinder, Cone, Hemicone, Sphere, Hemisphere, Torus, Tube, Ring, Tree, Grass; Keep Tool selected; Copy selection; Center Copy; Rotate Copy. |
| Land | Select Land, Flatten, Raise, Lower, Smooth, Roughen, Revert; brush Size and Strength sliders; Apply. The existing land-information panel replaces the object properties tabs in this mode. |

Implemented window: title and primary tool strip, followed by rows for manipulation, grid, linking, and stretch behavior; then contextual help and selection summary; then the five properties tabs. The header stays fixed while form bodies scroll. The default window is 560 × 924, with a 560 × 620 minimum; Content's inventory area expands with the window.

## General

| Proposed group | Existing controls and information | Current behavior to preserve |
| --- | --- | --- |
| Identity | Name; Description | Editable text fields, with current length and permission limits. |
| Ownership | Creator name/profile icon; Owner name/avatar or group icon | Linked identity information, not editable name fields. |
| Ownership | Current group; choose-group button | Keep the existing group chooser. A labeled **Set group** button can replace the wrench presentation. |
| Ownership | Share with group checkbox; Deed button | Keep these as distinct actions, with their existing restrictions and confirmations. |
| Permissions | “You can modify this object” status | Read-only permission status, including other existing selection states. |
| Permissions | Anyone: Move, Copy | Two independent checkboxes. There is no everyone Transfer checkbox here. |
| Permissions | Next owner: Modify, Copy, Transfer | Three independent checkboxes, retaining the existing permission dependencies. |
| Interaction | Click to dropdown | Touch (default), Sit on object, Buy object, Pay object, Open, Zoom, Ignore object, None. |
| Sales | For Sale checkbox; L$ price; sale type dropdown | Sale types: Copy, Contents, Original. |
| Sales | Show in search checkbox | Keep existing selection and permission gating. |
| Details | Pathfinding attributes | Read-only value. |
| Technical details | B:, O:, G:, E:, N:, F: permission readout widgets | Diagnostic widgets defined in the XUI; shown as applicable by the existing debug-permission logic. They should not become everyday editable settings. |

Design opportunity: give the name and description full-width fields; keep ownership actions together; separate permission grants from sales. A permission table must not invent combinations that do not exist—use the two existing checkbox rows.

## Object

| Proposed group | Existing controls | Current behavior to preserve |
| --- | --- | --- |
| Object flags | Locked, Physical, Temporary, Phantom | Four separate checkboxes. |
| Position | X, Y, Z in meters; Copy; Paste; clipboard menu | Menu contains Copy position, Paste position, Copy all, Paste all. “All” refers to position, size, and rotation. |
| Size | X, Y, Z in meters; Copy; Paste; clipboard menu | Menu contains Copy size, Paste size, Copy all, Paste all. |
| Rotation | X, Y, Z in degrees; Copy; Paste; clipboard menu | Menu contains Copy rotation, Paste rotation, Copy all, Paste all. |
| Shape | Prim type dropdown; geometry Copy/Paste menu | Box, Cylinder, Prism, Sphere, Torus, Tube, Ring, Sculpted. Geometry clipboard is distinct from transform clipboards. |
| Shape | Path Cut: begin/end | Numeric pair. |
| Shape | Hollow percentage; Hollow Shape dropdown | Hollow Shape: Default, Circle, Square, Triangle. Shape selection is disabled when hollow is zero. |
| Shape | Twist: begin/end | Numeric pair; limits and increments depend on the prim. |
| Shape | Taper X/Y or Hole Size X/Y | One pair is relabeled and interpreted according to the shape. |
| Shape | Top Shear X/Y | Numeric pair where supported. |
| Shape | Slice, Dimple, or Profile Cut: begin/end | The same advanced-cut pair uses a shape-specific label. |
| Circular shapes | Skew; additional Taper X/Y; Radius; Revolutions | Conditional controls for torus/tube/ring shapes. |
| Sculpt | Sculpt Texture picker; Mirror; Inside-out; Stitching type dropdown | Stitching types: Sphere, Torus, Plane, Cylinder. Mesh selection disables the unsupported sculpt/prim editing actions. |

Shape-state coverage:

| Selected type | Geometry organization |
| --- | --- |
| Box / Cylinder / Prism | Path Cut, Hollow + Hollow Shape, Twist, Taper, Top Shear, Slice. |
| Sphere | Path Cut, Hollow + Hollow Shape, Twist, Dimple; unsupported taper/shear controls are hidden. |
| Torus / Tube / Ring | Path Cut, Hollow + Hollow Shape, Twist, Hole Size, Top Shear, Profile Cut, Skew, additional Taper, Radius, Revolutions. |
| Sculpted | Texture and stitching controls replace the parametric geometry fields. |
| Mesh / restricted selection | Preserve the existing enabled, disabled, hidden, and mixed-selection states. Do not imply mesh topology can be edited here. |

Numeric inputs already accept the viewer's expression entry and stepping behavior. Alt uses 10× the configured step, Ctrl 0.1×, and Shift 0.01×, limited to displayed precision. Keep normal wheel/arrow operation and all existing object limits.

Design opportunity: compare the familiar two-column arrangement with three horizontal XYZ rows. In the latter, put Copy/Paste beside each group heading, then place shape controls in a separate section beneath the transforms. Keep units on the group and color only the axis labels.

## Texture

Texture is a conditional inspector, not one fixed form. Its mode dropdown selects **Textures**, **PBR Metallic Roughness**, or **Media**.

### Surface appearance and clipboard actions

| Existing control | Notes |
| --- | --- |
| Color swatch | Opens the color picker; disabled for a selected PBR material. |
| Transparency % | Numeric field; enabled state depends on the material/selection. |
| Glow | Numeric field. |
| Full Bright | Checkbox; disabled for PBR. |
| Hide water | Checkbox with existing special handling and restrictions. |
| Color Copy/Paste menu | Copies/pastes the existing surface-appearance parameters. |
| Texture Copy/Paste menu | Separate material/texture-parameter clipboard, retaining asset permissions, selection compatibility, loading states, and error handling. |

The concept exposes existing clipboard actions as labeled buttons; it does not add new clipboard semantics.

### Legacy Textures mode

Channel choices: **Texture (diffuse)**, **Bumpiness (normal)**, **Shininess (specular)**. Short labels Diffuse / Normal / Specular are possible without changing the three modes.

| Channel | Existing channel-specific controls |
| --- | --- |
| Diffuse | Texture picker; Alpha mode dropdown: None, Alpha blending, Alpha masking, Emissive mask; Mask cutoff (0–255), shown for Alpha masking. |
| Normal | Normal texture picker; Bumpiness dropdown. Options: None, Brightness, Darkness, woodgrain, bark, bricks, checker, concrete, crustytile, cutstone, discs, gravel, petridish, siding, stonetile, stucco, suction, weave. “Use texture” is added dynamically when a map is selected. |
| Specular | Specular texture picker; Shininess dropdown: None, Low, Medium, High, plus dynamic “Use texture”; with a specular map, Glossiness (0–255), Environment (0–255), and specular Color swatch. |

Legacy mapping controls:

- Mapping dropdown: Default / Planar.
- Lock repeat checkbox.
- Horizontal scale and Vertical scale.
- Horizontal offset and Vertical offset.
- Rotation in degrees.
- Repeats per meter.
- Align planar faces checkbox, shown/enabled according to the existing planar-selection rules (currently hidden when inapplicable).
- Align button for texture alignment.

Diffuse, normal, and specular each have their own underlying scale/offset/rotation fields. A single consistent visible grid can present the currently selected channel; it must not merge the stored values for those channels.

### PBR Metallic Roughness mode

| Group | Existing controls |
| --- | --- |
| Target/channel | Complete material, Base color, Metallic/roughness, Emissive, Normal. |
| Complete material | Material picker; Choose from inventory; Edit Selected; Save to inventory. |
| Loading state | “Loading contents...” replaces unavailable material actions while inventory permissions load. |
| Mapping | Mapping dropdown in Complete material view; Scale U/V, Offset U/V, Rotation, Repeats per meter. |

The material picker and the three inventory/editor buttons appear in Complete material view. Individual channel views show that channel's transform controls. Legacy Lock repeat and texture Align are not shown in PBR mode. Preserve the current visibility and enablement rules, including those of Align planar faces.

Metallic, roughness, normal-strength, and similar material-authoring sliders are **not inline controls on this tab**. The existing Edit Selected action opens the separate material editor. They should not be invented in these concepts.

### Media mode

- Current media information/URL and embedded media preview.
- Choose..., Remove, and media Align buttons.
- Mapping: Default / Planar, Lock repeat, scale U/V, offset U/V, rotation, repeats per meter, Align planar faces, and texture Align.

There are two existing Align actions in Media mode. Put one beside the media preview and the other inside the mapping section so their context is clear.

## Features

- Physics: physics shape type, material, gravity, friction, density, and restitution.
- Flexible: Flexible Path, Animated Mesh, softness, gravity, drag, wind, tension, and force X/Y/Z.
- Light: toggle, color and projector texture, intensity, radius, falloff, FOV, focus, and ambiance.
- Reflection probe: toggle, volume type, the existing dynamic/update selector alternatives, ambiance, and near clip.
- Direct feature and light Copy/Paste buttons retain the existing clipboard menus and enablement rules.

## Content

- New Script flyout (LSL/Lua), New Notecard, Permissions, and Explore in IDE/Stop Exploring.
- Content filter and the existing object inventory tree, with its normal object selection and permission behavior.

## Verification

Link-number display and part cycling, 2026-09-11: `scripts/tests/test_edit_link_number.py` compiles the production lookup, arrow enablement, and selection callback. It checks unlinked/root/child numbers, selection gating, attachments, seated avatars, missing children, relinking, both cycling directions, wraparound, pending-field commits, and compatibility with the existing face-selection shortcuts. The label and arrows default to hidden and fit between Edit linked and Link. This check, the existing Edit regressions, and the Release build passed. Live selection behavior has not been tested in-world.

The Release build and the focused build-control regression check passed. A control-preservation audit found no removed functional controls or changed numeric limits, steps, bindings, or original callbacks across the five tabs. Existing translations were moved into the new group hierarchy.

All five tabs were inspected through the login screen's XUI Preview Tool, including scrolling to the lower Features controls. This generic preview does not instantiate the real selection controllers; live object editing, material application, and selection-dependent permission states still require an in-world check. No character was logged in.

The dock passed the Release build and `scripts/tests/test_edit_dock.py`, which compiles the production geometry helper and checks width limits, offsets, minimum world area, and recovery across window sizes. The real offline dock preview verified Dock/Undock, restoration of the floating frame, native edge double-click resizing to the maximum allowed width, the saved width setting, fallback at 800 × 650, automatic docking after returning to 1184 × 1081, and close/reopen. The default 560-pixel dock width was restored. Automated drag gestures did not produce a visible resize, so continuous drag behavior and HUD placement still need an in-world check.

Field interaction fix, 2026-09-10: the old `LLPanel::clearCtrls()` disabled the new scroll containers in Object, Features, and Texture. Selection refresh enabled their individual fields but left a disabled ancestor blocking input. The shared reset routine now traverses section panels and scroll content, clears only the contained controls, and preserves scrollbars and composite control internals. `scripts/tests/test_panel_clear_controls.py` reproduced the failure before the fix and passes repeated clear/re-enable cycles afterward, including fields that must remain disabled for permissions. General and Content use their own field-specific reset logic. The Release rebuild and existing build-control/docking regression checks also passed; live editing has not been retested.

## Concept directions

**A — Compact inspector.** Retain familiar density and the Object tab's two columns; use consistent section spacing, longer inputs, restrained separators, and labeled clipboard actions.

**B — Spacious inspector.** Use more width for readable values, horizontal XYZ transform groups, clear ownership/permissions/sales sections, and one consistent UV grid. Shape-specific and channel-specific controls appear in their relevant section.

Texture is illustrated in three separate mode states so a polished picture does not accidentally suggest that mutually exclusive controls all appear together. The concepts use illustrative object names, identity names, prices, textures, and numeric values. Grouping, disclosure controls, and visual styling are proposals; the functional inventory above is the authority for implementation.

## Source references

- [Shared tools, General, and Object XUI](../indra/newview/skins/default/xui/en/floater_tools.xml)
- [Shared tool visibility, ruler choices, and selection summary](../indra/newview/llfloatertools.cpp)
- [General behavior and permissions](../indra/newview/llpanelpermissions.cpp)
- [Object behavior, geometry visibility, and clipboard actions](../indra/newview/llpanelobject.cpp)
- [Texture XUI](../indra/newview/skins/default/xui/en/panel_tools_texture.xml)
- [Texture mode/channel visibility and permissions](../indra/newview/llpanelface.cpp)
- [Position clipboard menu](../indra/newview/skins/default/xui/en/menu_copy_paste_pos.xml), [Size](../indra/newview/skins/default/xui/en/menu_copy_paste_size.xml), [Rotation](../indra/newview/skins/default/xui/en/menu_copy_paste_rot.xml), [Geometry](../indra/newview/skins/default/xui/en/menu_copy_paste_object.xml)
- [Color clipboard menu](../indra/newview/skins/default/xui/en/menu_copy_paste_color.xml), [Texture clipboard menu](../indra/newview/skins/default/xui/en/menu_copy_paste_texture.xml)
