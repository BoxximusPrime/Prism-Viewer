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

uniform sampler2D   normalMap;

#if defined(SUN_SHADOW)
uniform sampler2DShadow shadowMap0;
uniform sampler2DShadow shadowMap1;
uniform sampler2DShadow shadowMap2;
uniform sampler2DShadow shadowMap3;
#endif

#if defined(SPOT_SHADOW)
uniform sampler2DShadow shadowMap4;
uniform sampler2DShadow shadowMap5;
#endif

uniform vec3 sun_dir;
uniform vec3 moon_dir;
uniform vec2 shadow_res;
uniform vec2 proj_shadow_res;
uniform mat4 shadow_matrix[6];
uniform vec4 shadow_clip;
uniform float shadow_bias;
uniform float shadow_offset;
uniform float spot_shadow_bias;
uniform float spot_shadow_offset;
uniform mat4 inv_proj;
uniform vec2 screen_res;
uniform int sun_up_factor;

float pcfShadow(sampler2DShadow shadowMap, vec3 norm, vec4 stc, float bias_mul, vec2 pos_screen, vec3 light_dir)
{
#if defined(SUN_SHADOW)
    float offset = shadow_bias * bias_mul;
    stc.xyz /= stc.w;
    stc.z += offset * 2.0;
    stc.x = floor(stc.x*shadow_res.x + fract(pos_screen.y*shadow_res.y))/shadow_res.x; // add some chaotic jitter to X sample pos according to Y to disguise the snapping going on here
    float cs = texture(shadowMap, stc.xyz);
    float shadow = cs * 4.0;
    shadow += texture(shadowMap, stc.xyz+vec3( 1.5/shadow_res.x,  0.5/shadow_res.y, 0.0));
    shadow += texture(shadowMap, stc.xyz+vec3( 0.5/shadow_res.x, -1.5/shadow_res.y, 0.0));
    shadow += texture(shadowMap, stc.xyz+vec3(-1.5/shadow_res.x, -0.5/shadow_res.y, 0.0));
    shadow += texture(shadowMap, stc.xyz+vec3(-0.5/shadow_res.x,  1.5/shadow_res.y, 0.0));
    return clamp(shadow * 0.125, 0.0, 1.0);
#else
    return 1.0;
#endif
}

#if defined(SUN_SHADOW) && defined(PCSS_SHADOW)
uniform sampler2D pcssDepthMap0;
uniform sampler2D pcssDepthMap1;
uniform sampler2D pcssDepthMap2;
uniform sampler2D pcssDepthMap3;
#if defined(SPOT_SHADOW)
uniform sampler2D pcssDepthMap4;
uniform sampler2D pcssDepthMap5;
uniform float pcss_projector_radius;
#endif
uniform mat4 pcss_inverse_matrix[6];
uniform vec4 pcss_params;
float pcssShadow(sampler2D depthMap,
                 mat4 lightMatrix, mat4 inverseMatrix, vec4 start,
                 vec3 normal, vec3 lightDir, float sourceRadius);

// Filled before the cascade/projector branches. Projector helpers can be
// called from divergent light-volume branches, where derivatives are invalid.
vec3 pcssReceiverNormal = vec3(0,0,1);
bool pcssDepthPrepared = false;
float pcssDepthError = 0.0;
vec3 pcssSurfaceDx = vec3(0.0);
vec3 pcssSurfaceDy = vec3(0.0);
#endif

float getPCSSDepthError()
{
#if defined(SUN_SHADOW) && defined(PCSS_SHADOW)
    return pcssDepthError;
#else
    return 0.0;
#endif
}

vec2 getPCSSSlopeError(mat4 lightMatrix, vec4 start, float depthError)
{
#if defined(SUN_SHADOW) && defined(PCSS_SHADOW)
    vec2 tc = start.xy / start.w;
    vec4 sx = lightMatrix * vec4(pcssSurfaceDx, 0.0);
    vec4 sy = lightMatrix * vec4(pcssSurfaceDy, 0.0);
    vec2 dx = (sx.xy - tc * sx.w) / start.w;
    vec2 dy = (sy.xy - tc * sy.w) / start.w;
    float det = abs(dx.x * dy.y - dx.y * dy.x);
    // Each finite difference contains two uncertain depth samples. Propagate
    // that interval through the screen-to-shadow Jacobian, per UV axis.
    return 2.0 * depthError * vec2(abs(dy.y) + abs(dx.y), abs(dx.x) + abs(dy.x)) / max(det, 1e-20);
#else
    return vec2(0.0);
#endif
}

vec4 getPosition(vec2 pos_screen);
void preparePCSSDepth(vec3 pos, vec3 normal, vec2 uv)
{
#if defined(SUN_SHADOW) && defined(PCSS_SHADOW)
    if (pcss_params.x <= 0.0) return;
    // Screen-space derivatives span 2x2 quads and can cross hair/body or
    // triangle edges. The nearest depth can also belong to another surface.
    // Select the side whose two samples extrapolate back to this receiver;
    // reciprocal view depth is linear across a perspective-projected plane.
    // The view depth buffer is D24. Differencing its reconstructed positions
    // at long range amplifies quantization into large receiver-plane errors.
    // Allow four depth units for storage and float projection/reconstruction;
    // widen the normal's baseline when that exceeds the contact tolerance.
    pcssDepthError = abs(inv_proj[2].w * pos.z) * (8.0 / 16777216.0);
    float depthError = pcssDepthError * length(pos);
    float baseline = clamp(ceil(4.0 * depthError / max(pcss_params.z, 0.001)), 1.0, 4.0);
    vec2 texel = baseline / screen_res;
    vec3 left = getPosition(uv - vec2(texel.x, 0)).xyz;
    vec3 right = getPosition(uv + vec2(texel.x, 0)).xyz;
    vec3 down = getPosition(uv - vec2(0, texel.y)).xyz;
    vec3 up = getPosition(uv + vec2(0, texel.y)).xyz;
    vec4 farDepth = vec4(getPosition(uv - vec2(2.0 * texel.x, 0)).z,
                         getPosition(uv + vec2(2.0 * texel.x, 0)).z,
                         getPosition(uv - vec2(0, 2.0 * texel.y)).z,
                         getPosition(uv + vec2(0, 2.0 * texel.y)).z);
    vec4 error = abs(2.0 / vec4(left.z, right.z, down.z, up.z) - 1.0 / farDepth - 1.0 / pos.z);
    // Clamped depth fetches outside the viewport do not describe a plane.
    vec2 edge = 0.5 / screen_res;
    if (uv.x - 2.0 * texel.x < edge.x) error.x = 1e20;
    if (uv.x + 2.0 * texel.x > 1.0 - edge.x) error.y = 1e20;
    if (uv.y - 2.0 * texel.y < edge.y) error.z = 1e20;
    if (uv.y + 2.0 * texel.y > 1.0 - edge.y) error.w = 1e20;
    vec3 dx = error.x < error.y ? pos - left : right - pos;
    vec3 dy = error.z < error.w ? pos - down : up - pos;
    pcssSurfaceDx = dx;
    pcssSurfaceDy = dy;
    vec3 geometric = cross(dx, dy);
    pcssReceiverNormal = dot(geometric, geometric) > 1e-16 ? normalize(geometric) : normal;
    pcssDepthPrepared = true;
#endif
}

float sampleSunShadow(sampler2DShadow shadowMap, int cascade, vec3 norm,
                      vec4 stc, vec2 pos_screen, vec3 light_dir)
{
#if defined(SUN_SHADOW) && defined(PCSS_SHADOW)
    if (pcss_params.x > 0.0)
    {
        if (cascade == 0) return pcssShadow(pcssDepthMap0, shadow_matrix[0], pcss_inverse_matrix[0], stc, norm, light_dir, 0.0);
        if (cascade == 1) return pcssShadow(pcssDepthMap1, shadow_matrix[1], pcss_inverse_matrix[1], stc, norm, light_dir, 0.0);
        if (cascade == 2) return pcssShadow(pcssDepthMap2, shadow_matrix[2], pcss_inverse_matrix[2], stc, norm, light_dir, 0.0);
        return pcssShadow(pcssDepthMap3, shadow_matrix[3], pcss_inverse_matrix[3], stc, norm, light_dir, 0.0);
    }
#endif
    return pcfShadow(shadowMap, norm, stc, 1.0, pos_screen, light_dir);
}

float pcfSpotShadow(sampler2DShadow shadowMap, vec4 stc, float bias_scale, vec2 pos_screen)
{
#if defined(SPOT_SHADOW)
    stc.xyz /= stc.w;
    stc.z += spot_shadow_bias * bias_scale;
    stc.x = floor(proj_shadow_res.x * stc.x + fract(pos_screen.y*0.666666666)) / proj_shadow_res.x; // snap

    float cs = texture(shadowMap, stc.xyz);
    float shadow = cs;

    vec2 off = 1.0/proj_shadow_res;
    off.y *= 1.5;

    shadow += texture(shadowMap, stc.xyz+vec3(off.x*2.0, off.y, 0.0));
    shadow += texture(shadowMap, stc.xyz+vec3(off.x, -off.y, 0.0));
    shadow += texture(shadowMap, stc.xyz+vec3(-off.x, off.y, 0.0));
    shadow += texture(shadowMap, stc.xyz+vec3(-off.x*2.0, -off.y, 0.0));
    return shadow*0.2;
#else
    return 1.0;
#endif
}

float sampleDirectionalShadow(vec3 pos, vec3 norm, vec2 pos_screen)
{
#if defined(SUN_SHADOW)
    float shadow = 0.0f;
    vec3 light_dir = normalize((sun_up_factor == 1) ? sun_dir : moon_dir);

    // Evaluate derivatives before the cascade branches. Normal-map detail is
    // not the receiver plane and must not tilt a wide shadow filter.
    vec3 receiverNormal = norm;
#if defined(PCSS_SHADOW)
    vec3 geometricNormal = cross(dFdx(pos), dFdy(pos));
    if (dot(geometricNormal, geometricNormal) > 1e-16)
        receiverNormal = normalize(geometricNormal);
    if (pcssDepthPrepared) receiverNormal = pcssReceiverNormal;
    pcssReceiverNormal = receiverNormal;
#endif

    float dp_directional_light = max(0.0, dot(norm.xyz, light_dir));
          dp_directional_light = clamp(dp_directional_light, 0.0, 1.0);

    vec3 shadow_pos = pos.xyz;

    vec3 offset = light_dir.xyz * (1.0 - dp_directional_light);

#if defined(PCSS_SHADOW)
    if (pcss_params.x <= 0.0)
#endif
        shadow_pos += offset * shadow_offset * 2.0;

    vec4 spos = vec4(shadow_pos.xyz, 1.0);

    if (spos.z > -shadow_clip.w)
    {
        vec4 lpos;
        vec4 near_split = shadow_clip*-0.75;
        vec4 far_split = shadow_clip*-1.25;
        vec4 transition_domain = near_split-far_split;
        float weight = 0.0;

        if (spos.z < near_split.z)
        {
            lpos = shadow_matrix[3]*spos;

            float w = 1.0;
            w -= max(spos.z-far_split.z, 0.0)/transition_domain.z;
            //w = clamp(w, 0.0, 1.0);
            float contrib = sampleSunShadow(shadowMap3, 3, receiverNormal, lpos, pos_screen, light_dir)*w;
            //if (contrib > 0)
            {
                shadow += contrib;
                weight += w;
            }
            shadow += max((pos.z+shadow_clip.z)/(shadow_clip.z-shadow_clip.w)*2.0-1.0, 0.0);
        }

        if (spos.z < near_split.y && spos.z > far_split.z)
        {
            lpos = shadow_matrix[2]*spos;

            float w = 1.0;
            w -= max(spos.z-far_split.y, 0.0)/transition_domain.y;
            w -= max(near_split.z-spos.z, 0.0)/transition_domain.z;
            //w = clamp(w, 0.0, 1.0);
            float contrib = sampleSunShadow(shadowMap2, 2, receiverNormal, lpos, pos_screen, light_dir)*w;
            //if (contrib > 0)
            {
                shadow += contrib;
                weight += w;
            }
        }

        if (spos.z < near_split.x && spos.z > far_split.y)
        {
            lpos = shadow_matrix[1]*spos;

            float w = 1.0;
            w -= max(spos.z-far_split.x, 0.0)/transition_domain.x;
            w -= max(near_split.y-spos.z, 0.0)/transition_domain.y;
            //w = clamp(w, 0.0, 1.0);
            float contrib = sampleSunShadow(shadowMap1, 1, receiverNormal, lpos, pos_screen, light_dir)*w;
            //if (contrib > 0)
            {
                shadow += contrib;
                weight += w;
            }
        }

        if (spos.z > far_split.x)
        {
            lpos = shadow_matrix[0]*spos;

            float w = 1.0;
            w -= max(near_split.x-spos.z, 0.0)/transition_domain.x;
            //w = clamp(w, 0.0, 1.0);
            float contrib = sampleSunShadow(shadowMap0, 0, receiverNormal, lpos, pos_screen, light_dir)*w;
            //if (contrib > 0)
            {
                shadow += contrib;
                weight += w;
            }
        }

        shadow /= weight;
    }
    else
    {
        return 1.0f; // lit beyond the far split...
    }
    //shadow = min(dp_directional_light,shadow);
    return shadow;
#else
    return 1.0;
#endif
}

float sampleSpotShadow(vec3 pos, vec3 norm, int index, vec2 pos_screen)
{
#if defined(SPOT_SHADOW)
    float shadow = 0.0f;
#if defined(PCSS_SHADOW)
    if (pcss_params.x > 0.0)
    {
        if (pos.z <= -shadow_clip.w) return 1.0;
        int slot = index == 0 ? 4 : 5;
        vec4 origin = pcss_inverse_matrix[slot] * vec4(0,0,1,0);
        vec3 lightDir = normalize(origin.xyz / origin.w - pos);
        vec4 start = shadow_matrix[slot] * vec4(pos, 1.0);
        float result = index == 0 ?
            pcssShadow(pcssDepthMap4, shadow_matrix[4], pcss_inverse_matrix[4], start, pcssReceiverNormal, lightDir, pcss_projector_radius) :
            pcssShadow(pcssDepthMap5, shadow_matrix[5], pcss_inverse_matrix[5], start, pcssReceiverNormal, lightDir, pcss_projector_radius);
        float fade = max((pos.z + shadow_clip.z) / (shadow_clip.z - shadow_clip.w) * 2.0 - 1.0, 0.0);
        return clamp(result + fade, 0.0, 1.0);
    }
#endif
    pos += norm * spot_shadow_offset;

    vec4 spos = vec4(pos,1.0);
    if (spos.z > -shadow_clip.w)
    {
        vec4 lpos;

        vec4 near_split = shadow_clip*-0.75;
        vec4 far_split = shadow_clip*-1.25;
        vec4 transition_domain = near_split-far_split;
        float weight = 0.0;

        {
            float w = 1.0;
            w -= max(spos.z-far_split.z, 0.0)/transition_domain.z;

            if (index == 0)
            {
                lpos = shadow_matrix[4]*spos;
                shadow += pcfSpotShadow(shadowMap4, lpos, 0.8, spos.xy)*w;
            }
            else
            {
                lpos = shadow_matrix[5]*spos;
                shadow += pcfSpotShadow(shadowMap5, lpos, 0.8, spos.xy)*w;
            }
            weight += w;
            shadow += max((pos.z+shadow_clip.z)/(shadow_clip.z-shadow_clip.w)*2.0-1.0, 0.0);
        }

        shadow /= weight;
    }
    else
    {
        shadow = 1.0f;
    }
    return shadow;
#else
    return 1.0;
#endif
}

float sampleSSSShadowPath(sampler2DShadow depthMap, mat4 lightMatrix, vec3 pos, vec3 lightDir);

float sampleDirectionalSSSPath(vec3 pos)
{
#if defined(SUN_SHADOW)
    if (pos.z <= -shadow_clip.w) return -1.0;
    vec3 lightDir = normalize(sun_up_factor == 1 ? sun_dir : moon_dir);
    vec4 nearSplit = -shadow_clip * 0.75;
    vec4 farSplit = -shadow_clip * 1.25;
    vec4 domain = nearSplit - farSplit;
    // Match the ordinary shadow cascade overlaps, blending distances to avoid seams.
    vec4 weights = vec4(
        1.0 - max(nearSplit.x - pos.z, 0.0) / domain.x,
        1.0 - max(pos.z - farSplit.x, 0.0) / domain.x - max(nearSplit.y - pos.z, 0.0) / domain.y,
        1.0 - max(pos.z - farSplit.y, 0.0) / domain.y - max(nearSplit.z - pos.z, 0.0) / domain.z,
        1.0 - max(pos.z - farSplit.z, 0.0) / domain.z);
    weights = max(weights, vec4(0.0));
    vec4 paths = vec4(-1.0);
    if (weights.x > 0.0) paths.x = sampleSSSShadowPath(shadowMap0, shadow_matrix[0], pos, lightDir);
    if (weights.y > 0.0) paths.y = sampleSSSShadowPath(shadowMap1, shadow_matrix[1], pos, lightDir);
    if (weights.z > 0.0) paths.z = sampleSSSShadowPath(shadowMap2, shadow_matrix[2], pos, lightDir);
    if (weights.w > 0.0) paths.w = sampleSSSShadowPath(shadowMap3, shadow_matrix[3], pos, lightDir);
    weights *= step(vec4(0.0), paths);
    float total = dot(weights, vec4(1.0));
    return total > 0.0 ? dot(max(paths, vec4(0.0)), weights) / total : -1.0;
#else
    return -1.0;
#endif
}

float sampleSpotSSSPath(vec3 pos, vec3 lightDir, int index)
{
#if defined(SPOT_SHADOW)
    if (pos.z <= -shadow_clip.w) return -1.0;
    if (index == 0) return sampleSSSShadowPath(shadowMap4, shadow_matrix[4], pos, lightDir);
    if (index == 1) return sampleSSSShadowPath(shadowMap5, shadow_matrix[5], pos, lightDir);
#endif
    return -1.0;
}
