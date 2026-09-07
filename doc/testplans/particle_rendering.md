# Particle glow and Exact OIT regression check

Status: build and standalone shader syntax validation performed; in-world checks pending.

## In-world comparison

1. Use the same particle-heavy scene, camera positions, window resolution, graphics
   settings, and particle limit in the baseline and updated Release viewers. Disable
   frame caps/VSync for timing, allow textures to load, and record several samples
   of frame time both from a distance and with particles filling the screen.
2. Compare each build with `RenderExactOIT` enabled and disabled; keep
   `RenderExactOITDebugMode` at 0 for timings. Restore original settings afterward.
   This distinguishes ordinary particle overdraw from the added capture/sort cost.
3. Test zero-glow particles, glowing particles, mixed glowing/non-glowing particles
   sharing a texture, additive particles, and ribbons with glow at only one end.
   Check particles both in front of and behind transparent objects and water.
   Verify that actual glow, ribbon gradients, and transparency ordering are unchanged.
4. Let glowing particles expire and replace them with zero-glow particles to exercise
   vertex-buffer reuse. Check HUD particles as well. No stale glow should appear.
5. In a GPU frame capture, zero-glow particle batches should have no emissive draw.
   Glowing batches should retain their emissive draw, but exactly zero-glow texels
   should allocate no Exact OIT nodes. The particle color pass remains present.
   Existing profiler zones are `Exact OIT capture`, `Exact OIT natural sort`, and
   `Exact OIT composite`. Watch viewer diagnostics/logs for node-pool overflow:
   overflow discards the capture and renders transparency again using fallback.

For a particle-only pixel with nonzero color alpha and zero glow, the former path
stored one color node plus one useless glow node per particle layer. The updated
path stores only the color node. This is a work-count reduction, not a measured FPS
claim. Dense genuinely glowing particles still require capture and sorting.

## Standalone shader syntax check

Run in PowerShell from the repository root with `glslangValidator` on PATH. The
prototype supplies the viewer's separately linked texture lookup declaration;
this checks fragment syntax, not driver linking or rendered output.

```powershell
$shaderDir = Join-Path $PWD 'indra/newview/app_settings/shaders/class1/deferred'
foreach ($shaderName in @('exactOITEmissiveF.glsl', 'exactOITPbrGlowF.glsl')) {
    $shaderCheck = Join-Path $env:TEMP ('boxxy-check-' + $shaderName)
    $source = "#version 430 core`nvec4 diffuseLookup(vec2 uv);`n" +
        [IO.File]::ReadAllText((Join-Path $shaderDir $shaderName))
    [IO.File]::WriteAllText($shaderCheck, $source)
    & glslangValidator -S frag $shaderCheck
    if ($LASTEXITCODE -ne 0) { throw "Shader validation failed: $shaderName" }
}
```
