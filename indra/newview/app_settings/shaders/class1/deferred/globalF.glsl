/**
 * @file class1/deferred/globalF.glsl
 *
 * $LicenseInfo:firstyear=2024&license=viewerlgpl$
 * Second Life Viewer Source Code
 * Copyright (C) 2024, Linden Research, Inc.
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


 // Global helper functions included in every fragment shader
 // DO NOT declare sampler uniforms here as OS X doesn't compile
 // them out

uniform float sss_object;
uniform float mirror_flag;
uniform vec4 clipPlane;
uniform float clipSign;

void mirrorClip(vec3 pos)
{
    if (mirror_flag > 0)
    {
        if ((dot(pos.xyz, clipPlane.xyz) + clipPlane.w) < 0.0)
        {
                discard;
        }
    }
}

vec4 encodeNormal(vec3 n, float env, float gbuffer_flag)
{
    float f = sqrt(8 * n.z + 8);
    return vec4(n.xy / f + 0.5, env, gbuffer_flag + 0.12 * sss_object);
}

vec4 decodeNormal(vec4 norm)
{
    vec2 fenc = norm.xy*4-2;
    float f = dot(fenc,fenc);
    float g = sqrt(1-f/4);
    vec4 n;
    n.xy = fenc*g;
    n.z = 1-f/2;
    return n;
}

// Filter the GGX lobe over a pixel before lighting, rather than asking TAA to
// recover a highlight narrower than its samples. The squared GGX roughness
// parameter is perceptual roughness^4. Evaluate on normalized material normals
// BEFORE any discard, never on a deferred normal across object edges.
// Tokuyoshi/Kaplanyan normal-variance approximation, also used by Unity HDRP.
float filterPBRRoughness(float perceptual_roughness, vec3 normal)
{
    vec3 dx = dFdx(normal), dy = dFdy(normal);
    float kernel = min(0.5 * (dot(dx, dx) + dot(dy, dy)), 0.04);
    float roughness = clamp(perceptual_roughness, 0.0, 1.0);
    float alpha = roughness * roughness;
    return sqrt(sqrt(min(alpha * alpha + kernel, 1.0)));
}
