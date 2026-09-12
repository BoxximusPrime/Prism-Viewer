/**
 * @file class1/deferred/shadowUtil.glsl
 *
 * $LicenseInfo:firstyear=2007&license=viewerlgpl$
 * Second Life Viewer Source Code
 * Copyright (C) 2007, Linden Research, Inc.
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation;
 * version 2.1 of the License only.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with this library; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA
 *
 * Linden Research, Inc., 945 Battery Street, San Francisco, CA  94111  USA
 * $/LicenseInfo$
 */

// Capture derivatives before per-pixel backlight tests and light-volume discards.
// They describe the receiver's geometry, independently of its normal map.
vec3 sssSurfaceDx = vec3(0.0);
vec3 sssSurfaceDy = vec3(0.0);
float sssDepthCoverage = 1.0;
float getSSSDepthCoverage() { return sssDepthCoverage; }
void prepareSSSDepth(vec3 pos)
{
    sssDepthCoverage = 1.0;
    sssSurfaceDx = dFdx(pos);
    sssSurfaceDy = dFdy(pos);
}

// Reconstruct one texel's entry distance. Sample at its center so the depth
// comparison is binary, independent of the texture's nearest/linear filter.
float sampleSSSTexelPath(sampler2DShadow depthMap, vec2 uv, vec4 start, vec4 step)
{
    const float maxPath = 0.08;
    // A lit back-facing pixel has no trustworthy entry (open mesh, normal-map
    // detail, or unresolved silhouette). Keep it opaque instead of glowing.
    // Resolve at least the optical model's 0.5 mm minimum. Smaller differences
    // are indistinguishable from self-depth/receiver-slope rounding noise.
    vec4 surface = start + step * 0.0005;
    if (textureLod(depthMap, vec3(uv, surface.z / surface.w - 1.0 / 16777216.0), 0.0) >= 0.5) return maxPath;
    vec4 end = start + step * maxPath;
    if (textureLod(depthMap, vec3(uv, end.z / end.w), 0.0) < 0.5) return maxPath;

    float lo = 0.0;
    float hi = maxPath;
    for (int i = 0; i < 10; ++i)
    {
        float mid = (lo + hi) * 0.5;
        vec4 probe = start + step * mid;
        float visible = textureLod(depthMap, vec3(uv, probe.z / probe.w), 0.0);
        if (visible >= 0.5) hi = mid;
        else lo = mid;
    }
    // Ease in over the next half millimeter instead of moving a hard on/off
    // boundary to the minimum resolvable thickness.
    return mix(maxPath, hi, smoothstep(0.0005, 0.001, hi));
}

vec2 sssReceiverSlope(mat4 lightMatrix, vec4 start)
{
    vec3 tc = start.xyz / start.w;
    vec4 sx = lightMatrix * vec4(sssSurfaceDx, 0.0);
    vec4 sy = lightMatrix * vec4(sssSurfaceDy, 0.0);
    vec3 dx = (sx.xyz - tc * sx.w) / start.w;
    vec3 dy = (sy.xyz - tc * sy.w) / start.w;
    float det = dx.x * dy.y - dx.y * dy.x;
    if (abs(det) > 1e-5 * max(length(dx.xy) * length(dy.xy), 1e-20))
        return vec2(dy.y * dx.z - dx.y * dy.z, dx.x * dy.z - dy.x * dx.z) / det;
    return vec2(0.0);
}

// A shading/normal-map normal can point behind a light even when the visible
// geometric surface faces it. Such a surface is an entry, not a tissue exit:
// neighboring triangles above its extrapolated plane are not valid thickness.
bool sssIsEntrySurface(vec3 pos, vec3 lightDir)
{
    vec3 normal = cross(sssSurfaceDx, sssSurfaceDy);
    if (dot(normal, normal) <= 1e-20) return false;
    if (dot(normal, -pos) < 0.0) normal = -normal;
    return dot(normal, lightDir) >= 0.0;
}

// -1 means unavailable; 0.08 means opaque or no reliable light-facing entry.
float sampleSSSShadowPath(sampler2DShadow depthMap, mat4 lightMatrix, vec3 pos, vec3 lightDir)
{
    const float maxPath = 0.08;
    vec4 start = lightMatrix * vec4(pos, 1.0);
    if (start.w <= 0.0) return -1.0;
    vec3 tc = start.xyz / start.w;
    if (any(lessThanEqual(tc, vec3(0.0))) || any(greaterThanEqual(tc, vec3(1.0)))) return -1.0;
    if (sssIsEntrySurface(pos, lightDir)) return 0.08;
    vec4 step = lightMatrix * vec4(lightDir, 0.0);
    vec4 end = start + step * maxPath;
    if (end.w <= 0.0 || end.z / end.w <= 0.0 || end.z / end.w >= tc.z) return maxPath;

    // Compare each entry against the receiver plane at that texel, not against
    // the center pixel's depth. Otherwise a sloping surface shadows itself and
    // those small depth differences become bright, false thickness bands.
    vec2 receiverSlope = sssReceiverSlope(lightMatrix, start);

    // Filtering comparison results and then requiring 99.9% visibility chooses
    // the deepest contributing texel abruptly, even for a microscopic UV shift.
    // Interpolate reconstructed distances instead, including opaque neighbors.
    vec2 size = vec2(textureSize(depthMap, 0));
    vec2 grid = tc.xy * size - 0.5;
    vec2 base = floor(grid);
    vec2 f = fract(grid);
    vec4 weights = vec4((1.0-f.x)*(1.0-f.y), f.x*(1.0-f.y), (1.0-f.x)*f.y, f.x*f.y);
    vec2 corners[4] = vec2[4](vec2(0,0), vec2(1,0), vec2(0,1), vec2(1,1));
    float path = 0.0;
    for (int i = 0; i < 4; ++i)
    {
        if (weights[i] <= 0.0) continue;
        vec2 uv = (clamp(base + corners[i], vec2(0.0), size - 1.0) + 0.5) / size;
        vec4 receiver = start;
        receiver.z += dot(receiverSlope, uv - tc.xy) * start.w;
        path += weights[i] * sampleSSSTexelPath(depthMap, uv, receiver, step);
    }
    return path;
}

// Positive cubic B-spline weights smooth thickness before the exponential
// lighting response, without ringing or averaging depth across a silhouette.
vec4 sssCubicWeights(float f)
{
    float g = 1.0 - f;
    return vec4(g*g*g, 3.0*f*f*f - 6.0*f*f + 4.0,
                -3.0*f*f*f + 3.0*f*f + 3.0*f + 1.0, f*f*f) / 6.0;
}

// World-space width of a light-map texel at the receiver. Project away the
// light direction so a grazing tangent does not create an unbounded tolerance.
float sssReceiverTexelSize(mat4 lightMatrix, vec4 start, vec3 lightDir, vec2 size)
{
    vec3 tc = start.xyz / start.w;
    vec4 sx = lightMatrix * vec4(sssSurfaceDx, 0.0);
    vec4 sy = lightMatrix * vec4(sssSurfaceDy, 0.0);
    vec2 dx = (sx.xy - tc.xy * sx.w) / start.w;
    vec2 dy = (sy.xy - tc.xy * sy.w) / start.w;
    float det = dx.x * dy.y - dx.y * dy.x;
    if (abs(det) <= 1e-5 * max(length(dx) * length(dy), 1e-20)) return 0.0;
    vec3 tx = (sssSurfaceDx * dy.y - sssSurfaceDy * dx.y) / (det * size.x);
    vec3 ty = (sssSurfaceDy * dx.x - sssSurfaceDx * dy.x) / (det * size.y);
    return max(length(cross(lightDir, tx)), length(cross(lightDir, ty)));
}

float sampleFilteredSSSPath(sampler2D depthMap, mat4 lightMatrix, vec3 pos, vec3 lightDir)
{
    vec4 start = lightMatrix * vec4(pos, 1.0);
    if (start.w <= 0.0) return -1.0;
    vec3 tc = start.xyz / start.w;
    if (any(lessThanEqual(tc, vec3(0.0))) || any(greaterThanEqual(tc, vec3(1.0)))) return -1.0;
    if (sssIsEntrySurface(pos, lightDir)) return 0.3;
    vec4 step = lightMatrix * vec4(lightDir, 0.0);
    vec2 slope = sssReceiverSlope(lightMatrix, start);
    ivec2 size = textureSize(depthMap, 0);
    float footprintTolerance = 0.5 * sssReceiverTexelSize(lightMatrix, start, lightDir, vec2(size));
    // Fade the last four texels as well as the subject boundary. A projection
    // becoming unavailable must meet zero transmission continuously.
    vec2 border = min(tc.xy, vec2(1.0) - tc.xy) * vec2(size);
    sssDepthCoverage *= smoothstep(0.0, min(4.0, float(min(size.x, size.y)) * 0.25), min(border.x, border.y));
    vec2 grid = tc.xy * vec2(size) - 0.5;
    ivec2 base = ivec2(floor(grid)) - 1;
    vec4 wx = sssCubicWeights(fract(grid.x)), wy = sssCubicWeights(fract(grid.y));
    float result = 0.0;
    float trustedWeight = 0.0;
    for (int y = 0; y < 4; ++y)
    for (int x = 0; x < 4; ++x)
    {
        ivec2 texel = clamp(base + ivec2(x,y), ivec2(0), size - 1);
        vec2 uv = (vec2(texel) + 0.5) / vec2(size);
        vec4 receiver = start;
        receiver.z += dot(slope, uv - tc.xy) * start.w;
        // RG: first entry depth/object ID. BA: first tagged skin exit depth/object ID.
        // Identity zero includes clothing, alpha blend, terrain and the default avatar.
        vec4 layer = texelFetch(depthMap, texel, 0);
        float depth = layer.r;
        float denominator = step.z - depth * step.w;
        float exitDenominator = step.z - layer.b * step.w;
        if (layer.g > 0.0 && layer.g == layer.a && layer.b > layer.r &&
            denominator < -1e-10 && exitDenominator < -1e-10)
        {
            // Solve projected depth directly instead of binary-searching a
            // comparison sampler. Each of the 16 taps needs one depth fetch.
            float measured = clamp((depth * receiver.w - receiver.z) / denominator, 0.0, 0.3);
            // Reject self-depth uncertainty in distance units. An extra rounded
            // projected-depth comparison can erase real thin layers far away.
            float uncertainty = max(0.0005, receiver.w / (-denominator * 16777216.0));
            float exitDistance = (layer.b * receiver.w - receiver.z) / exitDenominator;
            float exitUncertainty = max(max(0.001, footprintTolerance), receiver.w / (-exitDenominator * 8388608.0));
            // The receiver must be the first exit of this same closed layer.
            // A later finger/mesh behind a resolvable air gap is not part of its
            // thickness. Account for the finite map footprint on curved meshes.
            float exitTrust = 1.0 - smoothstep(exitUncertainty, exitUncertainty * 2.0, abs(exitDistance));
            float weight = wx[x] * wy[y] * exitTrust * smoothstep(uncertainty, uncertainty * 2.0, measured);
            result += measured * weight;
            trustedWeight += weight;
        }
    }
    // Uncertain/occluded samples reduce coverage; they are not 300 mm of skin.
    // Mixing that sentinel into thickness creates false thick stripes and makes
    // the penetration slider control matching errors instead of tissue depth.
    sssDepthCoverage *= trustedWeight;
    return trustedWeight > 0.0 ? min(result / trustedWeight, 0.3) : 0.3;
}

// Focused maps are independent of ordinary visible shadows. Local maps cover
// one nearby skin cluster, not all six directions of a point light.
uniform sampler2D sssDepthMap0;
uniform sampler2D sssDepthMap1;
uniform sampler2D sssDepthMap2;
uniform mat4 sss_depth_matrix[3];
uniform vec3 sss_depth_valid;
uniform vec4 sss_depth_focus;
uniform vec3 sss_depth_origin[2];
uniform int sss_point_depth;

float sssFocusCoverage(vec3 pos)
{
    return 1.0 - smoothstep(sss_depth_focus.w * 0.8, sss_depth_focus.w,
                            distance(pos, sss_depth_focus.xyz));
}

float sampleFocusedSunSSSPath(vec3 pos, vec3 lightDir)
{
    sssDepthCoverage = sssFocusCoverage(pos) * sss_depth_valid.x;
    if (sssDepthCoverage <= 0.0) return -1.0;
    return sampleFilteredSSSPath(sssDepthMap0, sss_depth_matrix[0], pos, lightDir);
}

float sampleLocalSSSPath(vec3 pos, vec3 lightOrigin)
{
    sssDepthCoverage = sssFocusCoverage(pos);
    if (sssDepthCoverage <= 0.0) return -1.0;
    vec3 lightDir = normalize(lightOrigin - pos);
    if (sss_depth_valid.y > 0.0 && distance(lightOrigin, sss_depth_origin[0]) < 0.001)
    {
        sssDepthCoverage *= sss_depth_valid.y;
        return sampleFilteredSSSPath(sssDepthMap1, sss_depth_matrix[1], pos, lightDir);
    }
    if (sss_depth_valid.z > 0.0 && distance(lightOrigin, sss_depth_origin[1]) < 0.001)
    {
        sssDepthCoverage *= sss_depth_valid.z;
        return sampleFilteredSSSPath(sssDepthMap2, sss_depth_matrix[2], pos, lightDir);
    }
    sssDepthCoverage = 0.0;
    return -1.0;
}
