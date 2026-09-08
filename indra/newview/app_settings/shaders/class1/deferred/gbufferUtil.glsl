/**
 * @file class1/deferred/gbufferUtil.glsl
 *
 * $LicenseInfo:firstyear=2024&license=viewerlgpl$
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

uniform sampler2D diffuseRect;
uniform sampler2D specularRect;

#if defined(HAS_EMISSIVE)
uniform sampler2D emissiveRect;
#endif

// x: strength/enabled, y: 0 = wrapped / 1 = diffusion / 2 = combined,
// z: warmth, w: maximum view-space distance
uniform vec4 sss_params;
// Combined mode: wrap amount, transmission amount, estimated thickness in mm.
uniform vec3 sss_lighting;
uniform int sss_shadow_thickness;

vec4 getNormRaw(vec2 screenpos);
vec4 decodeNormal(vec4 norm);

GBufferInfo getGBuffer(vec2 screenpos)
{
    GBufferInfo ret;
    vec4 diffInfo = vec4(0);
    vec4 specInfo = vec4(0);
    vec4 emissInfo = vec4(0);

    diffInfo = texture(diffuseRect, screenpos.xy);
    specInfo = texture(specularRect, screenpos.xy);
    vec4 normInfo = getNormRaw(screenpos);

#if defined(HAS_EMISSIVE)
    emissInfo = texture(emissiveRect, screenpos.xy);
#endif

    ret.albedo = diffInfo;
    ret.normal = decodeNormal(normInfo).xyz;
    ret.specular = specInfo;
    ret.envIntensity = normInfo.b;
    ret.gbufferFlag = normInfo.w;
    ret.sss = GBUFFER_SSS_FLAG(normInfo.w);
    ret.emissive = emissInfo;

    return ret;
}

float getSSSStrength(float mask, vec3 positionEye)
{
    float distanceFade = 1.0;
    if (sss_params.w > 0.0)
    {
        distanceFade = 1.0 - smoothstep(sss_params.w * 0.8, sss_params.w, length(positionEye));
    }

    return clamp(sss_params.x, 0.0, 1.0) * clamp(mask, 0.0, 1.0) * distanceFade;
}

bool useSSSWrappedDiffuse(float strength)
{
    return strength > 0.0 && (sss_params.y < 0.5 ||
        (sss_params.y > 1.5 && max(sss_lighting.x, sss_lighting.y) > 0.0));
}

bool useSSSScreenDiffusion(float strength)
{
    return strength > 0.0 && sss_params.y >= 0.5;
}

vec3 getSSSWarmTint()
{
    return mix(vec3(1.0), vec3(1.0, 0.55, 0.35), clamp(sss_params.z, 0.0, 1.0));
}

vec3 getSSSDiffuseFactor(float nl, float strength)
{
    if (sss_params.y > 1.5) strength *= sss_lighting.x;
    float lambert = max(nl, 0.0);
    float wrapped = clamp((nl + 0.5) / 1.5, 0.0, 1.0);
    return vec3(lambert) + (wrapped - lambert) * getSSSWarmTint() * strength;
}

bool useSSSShadowThickness(float nl, float strength)
{
    return sss_shadow_thickness != 0 && sss_params.y > 1.5 &&
           strength > 0.0 && sss_lighting.y > 0.0 && nl < 0.0;
}

// Shared optical response: any light can supply a path length in millimeters.
vec3 getSSSTransmissionForPath(float nl, float strength, float path)
{
    if (sss_params.y < 1.5 || strength <= 0.0 || nl >= 0.0) return vec3(0.0);

    vec3 absorption = mix(vec3(0.3), vec3(0.12, 0.45, 0.8), clamp(sss_params.z, 0.0, 1.0));
    return exp(-absorption * max(path, 0.0)) * clamp(-nl, 0.0, 1.0) * strength * sss_lighting.y;
}

vec3 getSSSTransmission(float nl, float nv, float strength)
{
    if (sss_params.y < 1.5 || strength <= 0.0 || nl >= 0.0) return vec3(0.0);
    // Artist-controlled fallback for bodies without a thickness map. Approximate
    // a rounded cross-section: thinner at silhouettes, thicker facing the camera.
    // This is an optical thickness estimate, not a measurement of mesh geometry.
    float thickness = sss_lighting.z * mix(0.2, 1.0, clamp(abs(nv), 0.0, 1.0));
    float backlight = clamp(-nl, 0.0, 1.0);
    float path = thickness / max(backlight, 0.25);
    return getSSSTransmissionForPath(nl, strength, path);
}

uniform float sss_penetration; // maximum measured path, meters
uniform float sss_minimum_thickness; // meters; zero disables the lower bound
uniform float sss_maximum_thickness; // meters; zero disables the upper bound
uniform float sss_clamp_knee; // transition half-width, meters
float getSSSClampedPath(float path)
{
    // Preserve missing-depth and blocked/untrusted-depth sentinels.
    if (path < 0.0 || path >= 0.08) return path;
    float lower = clamp(sss_minimum_thickness, 0.0, 0.02);
    float upper = clamp(sss_maximum_thickness, 0.0, 0.08);
    float knee = clamp(sss_clamp_knee, 0.0, 0.02);
    if (upper > 0.0 && lower > 0.0)
    {
        upper = max(upper, lower);
        knee = min(knee, (upper - lower) * 0.5);
    }
    if (lower > 0.0)
    {
        float width = min(knee, lower);
        float overlap = max(width - abs(path - lower), 0.0);
        path = max(path, lower) + overlap * overlap / max(4.0 * width, 1e-10);
    }
    if (upper > 0.0)
    {
        float width = min(knee, upper);
        float overlap = max(width - abs(path - upper), 0.0);
        path = min(path, upper) - overlap * overlap / max(4.0 * width, 1e-10);
    }
    return path;
}

vec3 getSSSTransmissionWithDepth(float nl, float nv, float strength, float path, float shadow)
{
    // Negative path means no usable shadow map (including ordinary point lights).
    if (path < 0.0) return getSSSTransmission(nl, nv, strength) * shadow;

    float measuredPath = path;
    path = getSSSClampedPath(path);
    // The existing thickness control scales absorption: 8.5 is neutral for measured paths.
    // Fade across the full measured range: a late, steep cutoff turns small
    // thickness variations into bright islands at low artistic absorption.
    float opticalPath = max(path * 1000.0, 0.5) * (sss_lighting.z / 8.5);
    float penetration = clamp(sss_penetration, 0.005, 0.08);
    // Short grazing chords can amplify small changes in the mesh into bright
    // bands. Ease in across the first ~14 degrees behind the light terminator;
    // stronger backlighting and the estimated-thickness fallback are unchanged.
    float grazing = smoothstep(0.0, 0.25, clamp(-nl, 0.0, 1.0));
    return getSSSTransmissionForPath(nl, strength, opticalPath) *
           (1.0 - smoothstep(0.0, penetration, max(measuredPath, path))) * grazing;
}
