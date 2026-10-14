# Animated hair mesh and desktop contention — 2026-10-13

Status: in progress, uncommitted. Seven GPU regression suites, Release build and
live smoke capture pass. The user confirms OBS and other applications are now
responsive with animated mesh enabled. Remaining rope jumps are not confirmed
resolved.

## Evidence and interpretation

The user reports that animated mesh hair physics makes other applications,
particularly OBS controls, intermittently freeze while the viewer and OBS
preview remain smooth. Disabling animated mesh, including retaining simple
colliders, removes the symptom.

Inspection found an uncapped nearest-surface BVH traversal for every one of
14,112 contact-grid cells, every rendered frame. The preceding segment-ray
limits did not constrain this older cache-building pass. A second regional
deformation pass still ran in guide mode, although guide rendering and rope
contacts do not consume that displacement field.

The previous live shell had 543,501 triangles and 300,569 BVH nodes. Its combined
contact/cache stage dominated the mesh-update cost (about 7 ms in that earlier
short smoke capture). That is evidence of significant shared GPU work, not proof
that it caused the reported OBS UI freezes. Windows schedules/preempts GPU work
across contexts; OBS also needs GPU resources. See [Microsoft GPU preemption](https://learn.microsoft.com/en-us/windows-hardware/drivers/display/gpu-preemption)
and [OBS performance troubleshooting](https://obsproject.com/kb/encoding-performance-troubleshooting).

The local OBS log `2026-10-13 05-50-00.txt` identifies the same RTX 5090, D3D11,
hardware GPU scheduling enabled, and an unsuccessful attempt to establish GPU
priority. Its graphics-thread maximum was 55.122 ms; it does not locate the
reported longer UI freezes or establish an encoder failure. No OBS, Windows,
driver, process-priority, or timeout settings were changed.

A separate possible connection to rope jumping exists: `updateGuides()` drops
simulation history after an interval above 250 ms, resetting to the fitted rope
pose. Contact changes can also cause jumps independently. Neither mechanism has
been correlated with the user's observed jumps here; this patch does not change
the existing pause/teleport/history reset rules.

## Changes

- Seed each grid search from up to two previous body/hand candidates, evaluated
  against their current animated vertices. Reject invalid, unaligned and
  wrong-group history. Preserve existing 5 mm tie hysteresis.
- Stop each search after 128 traversal iterations or 64 new triangle tests,
  plus at most two history checks. Guard the traversal stack and child indices.
  Retain the best valid local candidate if the search budget expires.
- Submit grid work in batches of at most 1,024 cells (14 batches per pass).
  Cells within each pass are independent; the existing memory barrier remains
  between cache generation and field evaluation. Smaller dispatches limit
  individual jobs, but do not guarantee driver scheduling fairness.
- In guide mode, clear the unused regional field and skip its neighbour,
  contact-plane, motion-transfer and sweep calculations. The triangle cache,
  point/midpoint collisions and bounded rope rays remain active. Switching back
  to regional mode starts from the cleared field rather than stale motion.
- Split profiling into inclusive `Hair.contacts`, with child scopes
  `Hair.contact_cache` and `Hair.contact_coupling`. The older coupling scope
  included both passes and must not be compared directly to the new child.

## GPU checks

[Cache tests](../../.logs/hair-contention-cache.log) verify persistent ties,
animated release, independent body/hands, invalid and unaligned history, reset,
bit-identical whole-grid versus batched results (including the partial last
batch), and clearing the guide-mode field without changing contact candidates.

An instrumented production cache shader processes 524,288 overlapping triangles
for all 14,112 cells, reaching 64 new triangle tests plus one valid history test
per cell. A separate single-triangle-leaf fixture reaches the 128-step ceiling.
All results remain finite. These checks count actual executed work. The two
possible history candidates account for the maximum of 66 triangle evaluations.

Five warmup and ten measured dispatch sequences on RTX 5090 / driver 617.14 give
0.0996 ms median and 0.1168 ms maximum in the overlapping-triangle fixture.
[Raw timings](../../.logs/hair-contention-cache.log) are synthetic, instrumented,
and collected while the viewer is running: repeated geometry is cache-friendly,
so they are not representative live costs or an optimization comparison.

Other passing suites: [regional contact](../../.logs/hair-contention-contact.log),
[mesh skinning/refit](../../.logs/hair-contention-mesh.log),
[guides](../../.logs/hair-contention-guides.log),
[binding/elasticity](../../.logs/hair-contention-binding.log),
[contact response](../../.logs/hair-contention-contact_response.log), and
[stability](../../.logs/hair-contention-stability.log).

## Live capture and build

The unchanged viewer was using simple colliders when inspected. A direct
[60-frame capture after 30 warmup frames](../../.logs/viewer-mcp/20261013T115541Z-profile-6c94813a.json)
shows 64 ropes, no active mesh, guide GPU median 0.266 ms and frame interval
median 8.35 ms. It is a simple-mode smoke reference, not a paired comparison.
Viewport 3440 × 1369; scene/camera/build are recorded in the raw artifact.
The user subsequently moved regions, so replaying that view would not provide
a valid comparison. Camera and graphics settings have not been changed.

[Release build](../../.logs/hair-contention-build.log) passed with the prescribed
`cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2`.
No class layout was changed. Canonical executable:
`E:\BoxxyViewer\build-vc170-64\newview\Release\secondlife-bin.exe`, SHA-256
`9ff638d2508aee87138d4f3e351a1f25e6b3e1cffb58318e75d04fdf0624f47c`.
Source and staged `hairContactC.glsl` match SHA-256
`71c31e52abff00082576ea9b7be85f96a708b8f0e93e50b4be53ce20bc1c005f`.

The previous viewer had exited during the build. Launched the new Release via
MCP and used remembered login. [All 267 shaders loaded](../../.logs/hair-contention-startup.log).
The saved settings already enabled animated mesh and 64 guides. No graphics
overrides or camera movements were made by the agent; user camera/settings
changes were preserved.

[Changed-code capture](../../.logs/viewer-mcp/20261013T121107Z-profile-21d13911.json):
30 warmup / 60 measured frames, Brianconnais, viewport 3440 × 1369, 543,501
triangles, 300,569 tree nodes, 310 parts, 14,112 cache cells and 64 ropes / 576
rope points. Shell bake count stayed at 9 throughout. The camera moved during
capture; its start/end poses are in the raw artifact. The
[saved camera](../../.logs/viewer-mcp/20261013T121021Z-hair-contention-live-original-6fb99b26.camera.json)
was not restored or locked because the user was actively moving the view.

[Recorded settings](../../.logs/hair-contention-graphics.json): mesh, physics,
guides, gravity and rope overlay on; density 64, bend resistance 2.4, bend
gradient 0, smoothing 0.15, damping 12.5, elasticity 0.15, friction 1.15,
gravity strength 2.3, root radius 0.03 m, root gradient 1 m, mesh padding 0,
retention 1, stiffness 5.5, tip lag 0.3 and travel limit 2.

| GPU scope | Median | Maximum |
| --- | ---: | ---: |
| Contact cache | 0.393 ms | 0.748 ms |
| Regional coupling / guide-mode clear | 0.0077 ms | 3.444 ms |
| Combined contacts | 0.403 ms | 3.758 ms |
| Complete mesh update | 0.582 ms | 3.921 ms |
| Guide update | 1.135 ms | 1.516 ms |

CPU guide-update median was 0.143 ms. Frame interval median was 12.33 ms,
maximum 14.51 ms. GPU scopes are inclusive elapsed intervals; do not add parents
and children. The coupling outlier cannot be identified as shader execution
alone from these timings. This is a smoke check with a moving camera and changed
user settings, not a matched performance comparison with the earlier build.

[Post-update screenshot](../../.logs/viewer-mcp/20261013T121216Z-hair-contention-after-adc48030.png)
and [metadata](../../.logs/viewer-mcp/20261013T121216Z-hair-contention-after-adc48030.json)
show the loaded hairstyle and dense rope overlay. Some ropes extend around the
shoulders; a still image cannot verify settling or eliminate the reported jumps.

Asked the user to retest OBS controls and other applications with the updated
viewer and animated mesh enabled. They answered **“They're responsive now.”**
This supports the workload reduction as an effective mitigation in their test;
there was no per-change isolation or OS scheduling trace to identify which
change removed the freeze.

## Remaining limits

The capped search can miss a better or newly entering surface in dense overlaps;
it retains a valid candidate instead of completing the full nearest search.
Mesh skinning, refitting, drawing and the rest of the viewer still consume GPU
resources. The user's OBS retest passed; longer sessions and remaining rope jumps
still need validation. Smooth viewer FPS alone is insufficient to establish
desktop responsiveness.
