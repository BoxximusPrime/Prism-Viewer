// GTAO horizon integration adapted from XeGTAO, https://github.com/GameTechDev/XeGTAO
// Copyright (C) 2016-2021, Intel Corporation
// SPDX-License-Identifier: MIT
// See gtao.LICENSE.txt for the full license. GLSL adaptation: Boxxy Viewer.
//
// Full-resolution, spatial-only baseline. The scalar visibility and noise index
// are independent of lighting and ready for a later TAA resolve. Depth access
// is isolated below so a filtered view-depth mip chain can be added separately.

out vec2 frag_color; // R: visibility (may exceed 1 before filtering), G: geometry
in vec2 vary_fragcoord;
uniform sampler2D depthMap;
uniform vec2 screen_res;
uniform vec4 gtao_params; // radius (m), falloff fraction, thin compensation, denoise
uniform int gtao_quality;
uniform int gtao_noise_index; // 0 without TAA; frame index modulo 64 with TAA

vec4 getPositionWithDepth(vec2 tc, float depth);
vec4 getNorm(vec2 tc);

const float GTAO_PI = 3.14159265359;
const float GTAO_HALF_PI = 1.57079632679;

// XeGTAO's Hilbert / R2 sampling. Keep the temporal offset dormant until the
// renderer supplies a working temporal resolve; animating noise alone flickers.
uint gtaoHilbertIndex(uvec2 p)
{
    uint index = 0u;
    for (uint level = 32u; level > 0u; level >>= 1u)
    {
        uvec2 region = uvec2(greaterThan(p & uvec2(level), uvec2(0u)));
        index += level * level * ((3u * region.x) ^ region.y);
        if (region.y == 0u)
        {
            if (region.x == 1u) p = uvec2(63u) - p;
            p = p.yx;
        }
    }
    return index;
}

vec2 gtaoNoise(ivec2 pixel)
{
    uint index = gtaoHilbertIndex(uvec2(pixel) & uvec2(63u));
    index += 288u * uint(gtao_noise_index & 63);
    return fract(vec2(0.5) + float(index) * vec2(0.75487766625, 0.56984029099));
}

bool gtaoPosition(ivec2 pixel, out vec3 position)
{
    if (any(lessThan(pixel, ivec2(0))) || any(greaterThanEqual(pixel, ivec2(screen_res)))) return false;
    float depth = texelFetch(depthMap, pixel, 0).r;
    if (depth >= 1.0 || depth <= 0.0) return false;
    position = getPositionWithDepth((vec2(pixel) + 0.5) / screen_res, depth).xyz;
    return position.z < -0.0001;
}

float gtaoHorizon(ivec2 pixel, vec3 center, vec3 view, vec3 normal, float lowHorizon, float radius)
{
    vec3 position;
    if (!gtaoPosition(pixel, position)) return lowHorizon;
    vec3 delta = position - center;
    // Texel-center snapping can move a tap off the ideal slice. A sample below
    // the surface hemisphere cannot occlude it, regardless of that rounding.
    if (dot(delta, normal) <= 0.0) return lowHorizon;
    float distance = length(delta);
    if (distance < 0.00001) return lowHorizon;
    // XeGTAO near-field falloff and thin-occluder compensation. Off-screen
    // samples are missing information, never a repeated edge texel / wall.
    float falloffDistance = length(delta * vec3(1.0, 1.0, 1.0 + gtao_params.z));
    float weight = clamp((radius - falloffDistance) / (radius * gtao_params.y), 0.0, 1.0);
    return mix(lowHorizon, dot(delta / distance, view), weight);
}

void main()
{
    ivec2 pixel = ivec2(gl_FragCoord.xy);
    vec2 tc = (vec2(pixel) + 0.5) / screen_res;
    vec3 center;
    if (!gtaoPosition(pixel, center))
    {
        frag_color = vec2(1.0, 0.0);
        return;
    }
    vec3 normal = getNorm(tc).xyz;
    float normalLength = length(normal);
    if (normalLength < 0.0001)
    {
        frag_color = vec2(1.0, 1.0);
        return;
    }
    normal /= normalLength;
    float depth = texelFetch(depthMap, pixel, 0).r;
    // Use the actual inverse projection (including any future jitter). Match
    // positions to texel centers. Two D24 quantization steps prevent acne.
    vec3 right = getPositionWithDepth(tc + vec2(1.0 / screen_res.x, 0.0), depth).xyz;
    vec3 up = getPositionWithDepth(tc + vec2(0.0, 1.0 / screen_res.y), depth).xyz;
    vec2 pixelSize = max(vec2(length(right - center), length(up - center)), vec2(0.000001));
    center = getPositionWithDepth(tc, max(0.0, depth - 2.0 / 16777215.0)).xyz;
    vec3 view = normalize(-center);
    // Normal maps can point below the visible hemisphere at silhouettes.
    normal = normalize(normal + max(0.0, 0.001 - dot(normal, view)) * view);

    float radius = gtao_params.x * 1.457; // XeGTAO's radius compensation
    vec2 radiusPixels = radius / pixelSize;
    float screenRadius = min(radiusPixels.x, radiusPixels.y);
    if (screenRadius <= 1.3)
    {
        frag_color = vec2(1.0, 1.0);
        return;
    }
    int slices = gtao_quality == 0 ? 2 : (gtao_quality == 1 ? 3 : 4);
    int steps = slices; // 8 / 18 / 32 depth samples, across both sides
    vec2 noise = gtaoNoise(pixel);
    float visibility = 0.0;
    float unoccluded = 0.0;
    for (int slice = 0; slice < slices; ++slice)
    {
        float phi = (float(slice) + noise.x) * GTAO_PI / float(slices);
        vec2 direction = vec2(cos(phi), sin(phi)); // OpenGL UV and view Y both point up
        vec3 directionView = vec3(direction, 0.0);
        vec3 ortho = directionView - dot(directionView, view) * view;
        vec3 axis = normalize(cross(ortho, view));
        vec3 projectedNormal = normal - axis * dot(normal, axis);
        float projectedLength = length(projectedNormal);
        float cosNormal = clamp(dot(projectedNormal, view) / max(projectedLength, 0.00001), 0.0, 1.0);
        float normalAngle = sign(dot(ortho, projectedNormal)) * acos(cosNormal);
        vec2 lowHorizon = cos(vec2(normalAngle + GTAO_HALF_PI, normalAngle - GTAO_HALF_PI));
        vec2 horizon = lowHorizon;
        for (int step = 0; step < steps; ++step)
        {
            float stepNoise = fract(noise.y + float(slice + step * steps) * 0.61803398875);
            float s = (float(step) + stepNoise) / float(steps);
            s = s * s + 1.3 / screenRadius;
            ivec2 offset = ivec2(round(s * radiusPixels * direction));
            horizon.x = max(horizon.x, gtaoHorizon(pixel + offset, center, view, normal, lowHorizon.x, radius));
            horizon.y = max(horizon.y, gtaoHorizon(pixel - offset, center, view, normal, lowHorizon.y, radius));
        }
        // Analytic cosine-weighted integral of the unoccluded slice (GTAO).
        vec2 h = vec2(-acos(clamp(horizon.y, -1.0, 1.0)), acos(clamp(horizon.x, -1.0, 1.0)));
        h = normalAngle + clamp(h - normalAngle, -GTAO_HALF_PI, GTAO_HALF_PI);
        vec2 integral = (cosNormal + 2.0 * h * sin(normalAngle) - cos(2.0 * h - normalAngle)) * 0.25;
        vec2 openH = normalAngle + vec2(-GTAO_HALF_PI, GTAO_HALF_PI);
        openH = clamp(openH, -GTAO_PI, GTAO_PI);
        vec2 openIntegral = (cosNormal + 2.0 * openH * sin(normalAngle) - cos(2.0 * openH - normalAngle)) * 0.25;
        float weight = mix(projectedLength, 1.0, 0.05);
        visibility += weight * (integral.x + integral.y);
        unoccluded += weight * (openIntegral.x + openIntegral.y);
    }
    // Normalize the finite set of slices against its unoccluded integral.
    // An isolated plane must stay white at every view angle and quality level.
    visibility = pow(max(visibility / max(unoccluded, 0.00001), 0.0), 2.2);
    // Avoid a distant subpixel pop. Retain overshoot until the spatial filter
    // has averaged it, as in XeGTAO; clamping each noisy sample darkens slopes.
    visibility = mix(1.0, max(0.03, visibility), smoothstep(1.3, 4.0, screenRadius));
    frag_color = vec2(visibility, 1.0);
}
