# SSS / PCSS boundary investigation

September 12, 2026. The user identified the square patch as a boundary between mesh body pieces and an attachment without SSS enabled. It was a material-configuration boundary, not a PCSS/SSS renderer bug. The separate geometric-horizon regression fix below is implemented and uncommitted; the coordinated Release build and staged shader checks passed. It did not change the reported patch.

## Report and reproduced fault

The screenshot shows a sharp polygon-like boundary on an avatar's neck. The user reports that disabling SSS removes the boundary and reveals more of the skin's shadow. The exact scene has not been reproduced locally.

PCSS computes surface visibility using the geometric receiver plane. Measured SSS transmission intentionally bypasses ordinary surface shadow visibility: valid light entering thin skin must be able to reach its back surface. Its separate entry/exit maps must certify that path.

The SSS path previously combined two different normal decisions:

- Its geometric entry-surface rejection was a hard switch at zero geometric N·L.
- Its grazing transmission fade used only the smooth shading/normal-map normal.

A smooth shading normal can remain strongly backlit while adjacent geometric faces straddle the light horizon. The transmission then remains bright until the geometric rejection switches it off. That creates a sharp face boundary, even with a smooth shadow visibility input. Since measured transmission is added outside the PCSS surface-shadow term, the bright side can obscure that shadow.

A new GPU case holds the shading response and certified 4 mm tissue path constant while geometric N·L approaches zero. Before correction its red transmission was:

| Geometric N·L | −0.30 | −0.125 | −0.01 | −0.0001 | +0.0001 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Previous transmission | 0.1847 | 0.1847 | 0.1847 | 0.1847 | 0 |

The test fails before the shader change. This establishes a real discontinuity, not proof that it is the sole cause of the supplied screenshot.

## Change

`sssDepthUtil.glsl` now fades focused-map transmission coverage using the geometric receiver's backlighting over the same 0–0.25 N·L interval used by the optical model's shading-normal grazing fade. That is approximately the first 14.5 degrees behind the surface horizon. Stronger geometric backlighting retains its existing response; the fade is an artistic stability treatment, not a new physical transport model.

The hard front-face rejection remains, and missing or invalid entry/exit pairs remain opaque. Thin-skin transmission is not multiplied by PCSS surface visibility, which would incorrectly black out valid transmitted light. Diffusion radii, wrap settings, PCSS filtering and thickness measurements are unchanged. Near-grazing transmission becomes darker by design.

The legacy sun-lighting path's use of a capped diffuse/shadow combination was also examined. It can flatten portions of a soft-shadow response, but changing that renderer-wide convention was not needed to fix the reproduced transmission discontinuity and is outside this patch.

## Verification

- 793 SSS GPU checks passed, including 65 new geometric-horizon cases. The production legacy/PBR sun shaders are exercised in modern and classic lighting modes, with shadow visibility inputs 0, 0.5 and 1. The scene output, surface-diffusion buffer and isolated-transmission buffer remain consistent before smoothing.
- Existing focused-map validity, thick blockers, thin skin, local lighting and 100 mm curved-arm tests pass. The arm's minimum coverage remains 0.959.
- Both optimized and maximum-quality diffusion/transmission blur suites pass, including odd-viewport conservation.
- 316 PCSS synthetic GPU cases and 144 PCSS mesh/horizon cases pass.

Checks ran on an NVIDIA GeForce RTX 5090 using production shaders in a hidden GL context. The new lighting cases supply controlled PCSS visibility values rather than reproducing a full avatar scene and temporal resolve.

Wrap, transmission brightness and screen-diffusion-only tests did not remove the reported boundary; disabling SSS did. The user's subsequent attachment inspection resolved that report. The geometric-horizon change remains a separate correction supported by the controlled regression above.
