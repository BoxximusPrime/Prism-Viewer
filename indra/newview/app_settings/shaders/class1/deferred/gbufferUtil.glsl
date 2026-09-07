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

vec3 getSSSTransmission(float nl, float nv, float strength)
{
    if (sss_params.y < 1.5 || strength <= 0.0 || nl >= 0.0) return vec3(0.0);

    // Artist-controlled fallback for bodies without a thickness map. Approximate
    // a rounded cross-section: thinner at silhouettes, thicker facing the camera.
    // This is an optical thickness estimate, not a measurement of mesh geometry.
    float thickness = sss_lighting.z * mix(0.2, 1.0, clamp(abs(nv), 0.0, 1.0));
    float backlight = clamp(-nl, 0.0, 1.0);
    float path = thickness / max(backlight, 0.25);
    vec3 absorption = mix(vec3(0.3), vec3(0.12, 0.45, 0.8), clamp(sss_params.z, 0.0, 1.0));
    return exp(-absorption * path) * backlight * strength * sss_lighting.y;
}
