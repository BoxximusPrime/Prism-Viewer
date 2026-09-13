/**
 * @file pcssUtil.glsl
 * @brief Contact-hardening sun/moon and projector shadows using existing maps.
 *
 * Copyright (C) 2026 Prism Viewer contributors.
 * SPDX-License-Identifier: LGPL-2.1-only
 */

#if defined(SUN_SHADOW) && defined(PCSS_SHADOW)
// x: tan(angular radius), zero disables PCSS; y: maximum penumbra radius (m);
// z: receiver bias toward the light (m); w: minimum penumbra radius (m).
uniform vec4 pcss_params;
uniform int pcss_quality;
uniform float pcss_raster_error;
// World axes transformed into the receiver's camera space. A fixed camera
// axis rotates the finite sample pattern over the scene when the view turns.
uniform vec3 pcss_world_up;
uniform vec3 pcss_world_north;
float getPCSSDepthError();
vec2 getPCSSSlopeError(mat4 lightMatrix, vec4 start, float depthError);

// A fixed disk avoids frame-dependent noise in a renderer without temporal AA.
vec2 pcssDisk(int i, int count)
{
    float angle = float(i) * 2.39996323;
    float radius = sqrt((float(i) + 0.5) / float(count));
    return vec2(cos(angle), sin(angle)) * radius;
}

// Return guarded visibility, visibility with receiver texels restored, and
// evidence that a complete bilinear footprint belongs to the receiver plane.
vec3 pcssCompare(sampler2D depthMap, vec2 uv, vec3 receiver, vec2 slope, float bias, vec2 slopeError,
                 vec2 receiverSlope)
{
    vec2 size = vec2(textureSize(depthMap, 0));
    vec2 grid = uv * size - 0.5;
    vec2 base = floor(grid);
    vec2 f = fract(grid);
    // Gather order: upper left, upper right, lower right, lower left.
#if __VERSION__ >= 400
    // Gather at the footprint center so fixed-point texture coordinate
    // rounding cannot select a different quad than the plane comparisons.
    vec4 depths = textureGather(depthMap, (base + 1.0) / size);
#else
    ivec2 hi = ivec2(size) - 1;
    ivec2 p = ivec2(base);
    vec4 depths = vec4(texelFetch(depthMap, clamp(p + ivec2(0,1), ivec2(0), hi), 0).r,
                       texelFetch(depthMap, clamp(p + ivec2(1,1), ivec2(0), hi), 0).r,
                       texelFetch(depthMap, clamp(p + ivec2(1,0), ivec2(0), hi), 0).r,
                       texelFetch(depthMap, clamp(p, ivec2(0), hi), 0).r);
#endif
    vec4 x = (clamp(base.x + vec4(0,1,1,0), 0.0, size.x - 1.0) + 0.5) / size.x;
    vec4 y = (clamp(base.y + vec4(1,1,0,0), 0.0, size.y - 1.0) + 0.5) / size.y;
    vec4 reference = receiver.z + bias + slope.x * (x - receiver.x) + slope.y * (y - receiver.y);
    reference -= slopeError.x * abs(x - receiver.x) + slopeError.y * abs(y - receiver.y);
    // One hardware comparison depth for all four texels required a large
    // slope bias. That erased close occluders in polygon-shaped patches.
    // A receiver plane may extrapolate beyond the shadow frustum at grazing
    // angles. Clear texels still mean no blocker, even when reference > 1.
    vec4 lit = max(step(reference, depths), step(vec4(1.0), depths));
    vec4 receiverPlane = receiver.z + receiverSlope.x * (x - receiver.x) + receiverSlope.y * (y - receiver.y);
    vec4 receiverTolerance = -bias + slopeError.x * abs(x-receiver.x) + slopeError.y * abs(y-receiver.y);
    vec4 onReceiver = step(abs(depths-receiverPlane), receiverTolerance);
    vec4 restored = max(lit, onReceiver);
    return vec3(mix(mix(lit.w, lit.z, f.x), mix(lit.x, lit.y, f.x), f.y),
                mix(mix(restored.w, restored.z, f.x), mix(restored.x, restored.y, f.x), f.y),
                all(greaterThanEqual(base, vec2(0.0))) && all(lessThan(base+1.0, size)) &&
                all(greaterThan(onReceiver, vec4(0.5))) ? 1.0 : 0.0);
}

float pcssShadow(sampler2D depthMap,
                 mat4 lightMatrix, mat4 inverseMatrix, vec4 start,
                 vec3 normal, vec3 lightDir, float sourceRadius)
{
    if (start.w <= 0.0) return 1.0;
    vec3 tc = start.xyz / start.w;
    if (any(lessThanEqual(tc, vec3(0.0))) || any(greaterThanEqual(tc, vec3(1.0)))) return 1.0;

    vec4 receiver = inverseMatrix * vec4(tc, 1.0);
    vec3 pos = receiver.xyz / receiver.w;

    // The visible geometric face, rather than its shading/normal-map normal,
    // determines which part of the emitter is above the surface horizon.
    // Grazing exit faces may occupy less than a shadow texel: sampling clear
    // depth there otherwise invents bright triangles that bias cannot remove.
    if (dot(normal, -pos) < 0.0) normal = -normal;
    float nl = dot(normal, lightDir);
    float horizonWidth = pcss_params.x * sqrt(max(1.0 - nl * nl, 0.0));
    if (sourceRadius > 0.0)
    {
        vec4 source = inverseMatrix * vec4(0, 0, 1, 0);
        float distance = length(source.xyz / source.w - pos);
        vec2 emitterNormal = vec2(dot(normal, normalize(inverseMatrix[0].xyz)),
                                  dot(normal, normalize(inverseMatrix[1].xyz)));
        horizonWidth = sourceRadius * length(emitterNormal) / max(distance, 0.001);
    }
    float visibility = 1.0;
    if (nl <= -horizonWidth) return 0.0;
    if (nl < horizonWidth)
    {
        // Area of the circular emitter above the receiver plane. This keeps
        // finite lights soft as they cross the horizon instead of a hard cut.
        float h = clamp(nl / max(horizonWidth, 1e-7), -1.0, 1.0);
        visibility = 0.5 + (asin(h) + h * sqrt(max(1.0 - h * h, 0.0))) / 3.14159265;
    }

    // The legacy normalized-depth bias grows with cascade depth range. Use
    // metres here to retain close contacts consistently across cascades.
    vec4 biased = start + lightMatrix * vec4(lightDir * pcss_params.z, 0.0);
    float bias = min(biased.z / biased.w - tc.z, -2.0 / 16777216.0);

    // Transform the geometric receiver plane, including the cascade's warp.
    // Correct every tap for slope so a broad kernel does not shadow itself.
    vec4 plane = transpose(inverseMatrix) * vec4(normal, -dot(normal, pos));
    // A back-facing receiver is an exit surface. The shadow map contains a
    // different, light-facing entry surface, so extrapolating the exit plane
    // can move comparisons in front of real blockers in triangle-shaped gaps.
    // It needs ordinary depth comparisons, not self-shadow slope correction.
    bool lightFacing = nl > 0.0;
    vec2 slope = lightFacing && abs(plane.z) > 1e-7 ? -plane.xy / plane.z : vec2(0.0);
    vec2 receiverSlope = slope;

    // A receiver plane is only reliable for self-shadow correction where the
    // map actually contains that receiver. A wall covering the entire center
    // footprint must not disappear when a grazing face extrapolates through
    // it. Keep any correction within the occluder's measured depth gradients.
    ivec2 size = textureSize(depthMap, 0);
    ivec2 hi = size - 1;
    // Rasterized shadow vertices have finite subpixel precision. Even an
    // exact receiver plane can differ from their stored depth by a small
    // fraction of a texel's slope, especially on coarse, grazing cascades.
    bias -= dot(abs(slope), 1.0 / vec2(size)) * pcss_raster_error;
    ivec2 center = ivec2(floor(tc.xy * vec2(size) - 0.5));
    vec4 centerDepths = vec4(texelFetch(depthMap, clamp(center, ivec2(0), hi), 0).r,
                            texelFetch(depthMap, clamp(center + ivec2(1,0), ivec2(0), hi), 0).r,
                            texelFetch(depthMap, clamp(center + ivec2(0,1), ivec2(0), hi), 0).r,
                            texelFetch(depthMap, clamp(center + ivec2(1,1), ivec2(0), hi), 0).r);

    // Only deferred receivers have camera-depth uncertainty. Project that
    // interval through the receiver plane instead of asking the user to add
    // a large world-space contact bias (which detaches nearby avatar shadows).
    vec4 uncertainty = lightMatrix * vec4(pos * getPCSSDepthError(), 0.0);
    vec3 delta = (uncertainty.xyz - tc * uncertainty.w) / start.w;
    bool covered = all(lessThan(centerDepths, vec4(tc.z + bias - abs(delta.z))));
    if (covered)
    {
        vec2 casterSlope = vec2(max(abs(centerDepths.y - centerDepths.x), abs(centerDepths.w - centerDepths.z)),
                                max(abs(centerDepths.z - centerDepths.x), abs(centerDepths.w - centerDepths.y))) * vec2(size);
        slope = clamp(slope, -casterSlope, casterSlope);
    }
    float depthError = abs(delta.z - dot(slope, delta.xy));
    bias -= depthError;
    // The bound above comes from shadow texels, not the reconstructed camera
    // normal. Its potentially unbounded slope uncertainty no longer applies.
    vec2 slopeError = lightFacing && !covered ? getPCSSSlopeError(lightMatrix, start, depthError) : vec2(0.0);

    // Sun rays share a perpendicular disk. A projector's emitter instead
    // stays in its own XY plane; rotating it toward each receiver stretches
    // the penumbra off axis and changes the sampling pattern across the cone.
    vec3 axis = abs(dot(lightDir, pcss_world_up)) < 0.9 ? pcss_world_up : pcss_world_north;
    vec3 tangent = sourceRadius > 0.0 ? normalize(inverseMatrix[0].xyz) : normalize(cross(lightDir, axis));
    vec3 bitangent = sourceRadius > 0.0 ? normalize(inverseMatrix[1].xyz) : cross(lightDir, tangent);
    vec4 du = lightMatrix * vec4(tangent, 0.0);
    vec4 dv = lightMatrix * vec4(bitangent, 0.0);
    mat2 footprint = mat2((du.xy - tc.xy * du.w) / start.w,
                          (dv.xy - tc.xy * dv.w) / start.w);

    vec4 nearPoint = inverseMatrix * vec4(tc.xy, 0.0, 1.0);
    float nearDistance = max(dot(nearPoint.xyz / nearPoint.w - pos, lightDir), 0.0);
    // For a projector, start.w is distance along its perspective axis. An
    // emitter radius produces gap / blocker-distance penumbra growth.
    float lightDistance = sourceRadius > 0.0 ? start.w : 0.0;
    float nearAxisDistance = sourceRadius > 0.0 ? 1.0 / nearPoint.w : 0.0;
    float searchRadius = sourceRadius > 0.0 ?
        sourceRadius * max(lightDistance - nearAxisDistance, 0.0) / max(nearAxisDistance, 0.001) :
        nearDistance * pcss_params.x;
    searchRadius = clamp(searchRadius, pcss_params.w, pcss_params.y);
    int searchCount = pcss_quality == 0 ? 8 : (pcss_quality == 1 ? 16 : 32);
    int filterCount = searchCount * 2;
    float blockerDistance = 0.0;
    float blockers = 0.0;
    // No certification is needed if the occluder guard left the plane intact.
    float receiverFound = all(equal(slope, receiverSlope)) ? 1.0 : 0.0;
    for (int i = 0; i < searchCount; ++i)
    {
        // Always test the center to preserve narrow, fully shadowed contacts.
        int halfCount = searchCount / 2;
        bool local = i < halfCount;
        vec2 disk = local ? pcssDisk(max(i - 1, 0), halfCount - 1) : pcssDisk(i - halfCount, halfCount);
        // Search at two scales. The full cascade search alone leaves large
        // holes near the receiver, missing narrow casters in their penumbra.
        float searchScale = local ? 0.125 : 1.0;
        vec2 offset = i == 0 ? vec2(0.0) : footprint * disk * searchRadius * searchScale;
        vec2 uv = tc.xy + offset;
        if (any(lessThan(uv, vec2(0.0))) || any(greaterThanEqual(uv, vec2(1.0)))) continue;
        ivec2 texel = ivec2(uv * vec2(size));
        uv = (vec2(texel) + 0.5) / vec2(size);
        float depth = texelFetch(depthMap, texel, 0).r;
        float receiverDepth = tc.z + dot(slope, uv - tc.xy);
        float tapBias = bias - dot(slopeError, abs(uv - tc.xy));
        float surfaceDepth = tc.z + dot(receiverSlope, uv - tc.xy);
        float surfaceTolerance = -tapBias;
        if (receiverFound == 0.0 && depth < 1.0 && abs(depth-surfaceDepth) <= surfaceTolerance)
        {
            // A small contact filter may contain only mixed edge quads.
            // Certify the receiver in the wider search too, stopping once
            // a complete patch is found. Reuse the same comparison helper.
            receiverFound = pcssCompare(depthMap, uv, tc, slope, bias, slopeError, receiverSlope).z;
        }
        // The receiver remains the receiver even when a caster covers the
        // centre and forces bounded comparisons elsewhere in the kernel.
        if (depth < receiverDepth + tapBias && depth < 1.0 && abs(depth-surfaceDepth) > surfaceTolerance)
        {
            vec4 blocker = inverseMatrix * vec4(uv, depth, 1.0);
            if (sourceRadius > 0.0)
            {
                // Average actual axial blocker depths. The receiver plane
                // is only for comparisons: its depth at a distant search tap
                // can approach infinity and is not this receiver's distance.
                blockerDistance += 1.0 / blocker.w;
            }
            else
            {
                // Reconstruct metres, not a normalized-depth ratio: the latter
                // changes softness as the camera refits the shadow cascades.
                // Measure from this receiver, not the extrapolated plane at
                // each tap, which made softness depend on triangle slope.
                blockerDistance += dot(blocker.xyz / blocker.w - pos, lightDir);
            }
            blockers += 1.0;
        }
    }
    float averageDistance = blockerDistance / max(blockers, 1.0);
    float radius = max(averageDistance, 0.0) * pcss_params.x;
    if (sourceRadius > 0.0)
        radius = blockers > 0.0 ? sourceRadius * max(lightDistance - averageDistance, 0.0) / max(averageDistance, 0.001) : 0.0;
    radius = clamp(radius, pcss_params.w, pcss_params.y);
    // Even an empty sparse search needs the contact filter: returning fully
    // lit here popped small blockers and cut off the minimum-softness edge.
    if (radius <= 0.0)
    {
        vec3 contact = pcssCompare(depthMap, tc.xy, tc, slope, bias, slopeError, receiverSlope);
        return min(visibility, receiverFound + contact.z > 0.0 ? contact.y : contact.x);
    }
    vec3 shadow = vec3(0.0, 0.0, receiverFound);
    for (int i = 0; i < filterCount; ++i)
    {
        vec2 offset = footprint * pcssDisk(i, filterCount) * radius;
        vec2 uv = tc.xy + offset;
        if (any(lessThan(uv, vec2(0.0))) || any(greaterThanEqual(uv, vec2(1.0)))) shadow.xy += 1.0;
        else shadow += pcssCompare(depthMap, uv, tc, slope, bias, slopeError, receiverSlope);
    }
    // The map can already include the same horizon occlusion; cap its
    // visibility rather than multiplying and counting that shadow twice.
    // A grazing tangent can merely cross a wall at one texel. Require a
    // matching 2x2 patch in the search/filter before exempting receiver
    // texels; otherwise retain the wall guard. This also handles mixed
    // caster/floor bilinear taps without adding a dark border to the floor.
    return min(visibility, (shadow.z > 0.0 ? shadow.y : shadow.x) / float(filterCount));
}
#endif
