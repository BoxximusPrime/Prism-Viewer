/**
 * Shared projected-light sampling for opaque and alpha/OIT surfaces.
 * Derived from deferredUtil.glsl and spotLightF.glsl.
 * Copyright (C) Linden Research, Inc.
 * SPDX-License-Identifier: LGPL-2.1-only
 */

vec3 srgb_to_linear(vec3 color);
float calcLegacyDistanceAttenuation(float distance, float falloff);
void calcHalfVectors(vec3 lv, vec3 n, vec3 v, out vec3 h, out vec3 l,
    out float nh, out float nl, out float nv, out float vh, out float lightDist);
void pbrPunctual(vec3 diffuseColor, vec3 specularColor, float roughness,
    float metallic, vec3 n, vec3 v, vec3 l, out float nl, out vec3 diff, out vec3 spec);
float sampleSpotShadow(vec3 pos, vec3 norm, int index, vec2 pos_screen);

// Explicit LOD is also valid inside the per-fragment projector branches.
vec4 sampleProjectorDiffuse(sampler2D projection, vec2 tc, float lod, float max_lod)
{
    vec4 ret = textureLod(projection, tc, lod);
    ret.rgb = srgb_to_linear(ret.rgb);
    vec2 dist = vec2(0.5) - abs(tc - vec2(0.5));
    float edge = 0.25 * min(lod / max(max_lod * 0.5, 0.000001), 1.0);
    ret *= clamp(min(dist.x, dist.y) / max(edge, 0.000001), 0.0, 1.0);
    return ret;
}

vec4 sampleProjectorAmbient(sampler2D projection, vec2 tc, float lod)
{
    vec4 ret = textureLod(projection, tc, lod);
    ret.rgb = srgb_to_linear(ret.rgb);
    vec2 dist = tc - vec2(0.5);
    ret *= clamp((0.25 - dot(dist, dist)) / 0.25, 0.0, 1.0);
    return ret;
}

vec4 sampleProjectorSpecular(sampler2D projection, vec2 tc, float lod, float max_lod)
{
    vec4 ret = textureLod(projection, tc, lod);
    ret.rgb = srgb_to_linear(ret.rgb);
    vec2 dist = vec2(0.5) - abs(tc - vec2(0.5));
    float d = min(dist.x, dist.y);
    d *= min(1.0, d * (max_lod - lod));
    float edge = 0.25 * min(lod / max(max_lod * 0.5, 0.000001), 1.0);
    ret *= clamp(d / max(edge, 0.000001), 0.0, 1.0);
    return ret;
}

#ifdef ALPHA_PROJECTORS
uniform sampler2D alphaProjectionMap0;
uniform sampler2D alphaProjectionMap1;
uniform sampler2D alphaProjectionMap2;
uniform sampler2D alphaProjectionMap3;
uniform sampler2D alphaProjectionMap4;
uniform sampler2D alphaProjectionMap5;
uniform sampler2D lightFunc;
uniform int classic_mode;
uniform int alpha_projector_mask;
uniform mat4 alpha_projector_matrix[6];
uniform vec3 alpha_projector_plane[6];
uniform vec3 alpha_projector_normal[6];
uniform vec3 alpha_projector_origin[6];
uniform vec4 alpha_projector_params[6]; // focus, maximum LOD, range, ambiance
uniform vec2 alpha_projector_shadow[6]; // shadow map index, fade

vec4 sampleAlphaProjector(int index, vec2 tc, float lod, int mode)
{
    float max_lod = alpha_projector_params[index].y;
    // Keep sampler indices static for drivers which cannot dynamically index
    // sampler arrays. Geometry and lighting data still follow the HW light slot.
#define SAMPLE_PROJECTOR(i, map) case i: \
    if (mode == 1) return sampleProjectorAmbient(map, tc, lod); \
    if (mode == 2) return sampleProjectorSpecular(map, tc, lod, max_lod); \
    return sampleProjectorDiffuse(map, tc, lod, max_lod);
    switch (index)
    {
        SAMPLE_PROJECTOR(0, alphaProjectionMap0)
        SAMPLE_PROJECTOR(1, alphaProjectionMap1)
        SAMPLE_PROJECTOR(2, alphaProjectionMap2)
        SAMPLE_PROJECTOR(3, alphaProjectionMap3)
        SAMPLE_PROJECTOR(4, alphaProjectionMap4)
        SAMPLE_PROJECTOR(5, alphaProjectionMap5)
    }
#undef SAMPLE_PROJECTOR
    return vec4(0.0);
}

bool alphaProjectorVars(int index, vec3 pos, vec3 norm, vec3 center, float radius,
    float falloff, out vec2 tc, out vec3 lv, out float attenuation,
    out vec3 projected, out float shadow)
{
    float dist = length(center - pos);
    vec4 params = alpha_projector_params[index];
    if (radius <= 0.0 || dist >= radius || params.z <= 0.0)
        return false;
    vec4 coord = alpha_projector_matrix[index] * vec4(pos, 1.0);
    if (coord.w <= 0.0 || coord.z < 0.0)
        return false;
    tc = coord.xy / coord.w;
    if (any(lessThanEqual(tc, vec2(0.0))) || any(greaterThanEqual(tc, vec2(1.0))))
        return false;

    lv = alpha_projector_origin[index] - pos;
    attenuation = calcLegacyDistanceAttenuation(dist / radius, falloff);
    float light_distance = -dot(center - pos, alpha_projector_normal[index]);
    float lod = clamp((light_distance - params.x) / params.z, 0.0, 1.0) * params.y;
    vec4 tap = sampleAlphaProjector(index, tc, lod, 0);
    projected = tap.rgb * tap.a;
    shadow = 1.0;
#ifdef SPOT_SHADOW
    int shadow_index = int(alpha_projector_shadow[index].x);
    if (shadow_index >= 0)
    {
        // Sample the receiver's own depth, never the opaque pixel behind it.
        shadow = clamp(sampleSpotShadow(pos, norm, shadow_index, gl_FragCoord.xy)
            + alpha_projector_shadow[index].y, 0.0, 1.0);
    }
#endif
    return true;
}

vec3 alphaProjectorAmbiance(int index, vec2 tc, float attenuation, float lit, float nl)
{
    float ambiance = alpha_projector_params[index].w;
    float amb_da = (nl > 0.0 ? nl * 0.5 + 0.5 : 0.0) * ambiance;
    amb_da += ambiance;
    amb_da += (nl * nl * 0.5 + 0.5) * ambiance;
    amb_da = min(amb_da * attenuation, 1.0 - lit);
    vec4 tap = sampleAlphaProjector(index, tc, alpha_projector_params[index].y, 1);
    return amb_da * tap.rgb * tap.a;
}
#endif

bool hasAlphaProjector(int light_index)
{
#ifdef ALPHA_PROJECTORS
    return light_index >= 2 && light_index < 8 &&
        (alpha_projector_mask & (1 << (light_index - 2))) != 0;
#else
    return false;
#endif
}

vec3 calcAlphaProjectedLight(int light_index, vec3 pos, vec3 norm, vec3 center,
    float radius, float falloff, vec3 light_color, vec3 diffuse, vec4 spec,
    float env_intensity, inout float glare)
{
    vec3 result = vec3(0.0);
#ifdef ALPHA_PROJECTORS
    int index = light_index - 2;
    vec2 tc;
    vec3 lv, projected;
    float attenuation, shadow;
    if (!alphaProjectorVars(index, pos, norm, center, radius, falloff,
                           tc, lv, attenuation, projected, shadow))
        return result;
    vec3 h, l, v = -normalize(pos);
    float nh, nl, nv, vh, lightDist;
    calcHalfVectors(lv, norm, v, h, l, nh, nl, nv, vh, lightDist);
    vec3 dlit = light_color * projected;
    float lit = nl * attenuation;
    result = dlit * lit * diffuse * shadow;
    result += light_color * diffuse * alphaProjectorAmbiance(index, tc, attenuation, lit, nl)
        * max(dot(-l, norm), 0.0);

    if (spec.a > 0.0)
    {
        float fres = pow(1.0 - vh, 5.0) * 0.4 + 0.5;
        float gt = max(0.0, min(2.0 * nh * nv / vh, 2.0 * nh * nl / vh));
        float scol = fres * texture(lightFunc, vec2(nh, spec.a)).r * gt / (nh * nl);
        vec3 speccol = clamp(dlit * min(nl * 6.0, 1.0) * attenuation * scol * spec.rgb * shadow,
                             vec3(0.0), vec3(1.0));
        result += speccol;
        glare = max(glare, max(max(speccol.r, speccol.g), speccol.b));
    }

    if (env_intensity > 0.0)
    {
        vec3 ref = reflect(normalize(pos), norm);
        float ds = dot(ref, alpha_projector_normal[index]);
        if (ds < 0.0)
        {
            vec3 pfinal = pos + ref * dot(alpha_projector_plane[index] - pos,
                                          alpha_projector_normal[index]) / ds;
            vec4 coord = alpha_projector_matrix[index] * vec4(pfinal, 1.0);
            if (coord.z > 0.0 && coord.w > 0.0)
            {
                vec2 uv = coord.xy / coord.w;
                if (all(greaterThan(uv, vec2(0.0))) && all(lessThan(uv, vec2(1.0))))
                {
                    float lod = (1.0 - spec.a) * alpha_projector_params[index].y * 0.6;
                    result += light_color * sampleAlphaProjector(index, uv, lod, 2).rgb * shadow * env_intensity;
                }
            }
        }
    }
    result *= classic_mode > 0 ? 0.9 : 1.0;
#endif
    return max(result, vec3(0.0));
}

vec3 calcAlphaPBRProjectedLight(int light_index, vec3 pos, vec3 norm, vec3 v, vec3 center,
    float radius, float falloff, vec3 light_color, vec3 diffuse, vec3 specular,
    float roughness, float metallic)
{
    vec3 result = vec3(0.0);
#ifdef ALPHA_PROJECTORS
    int index = light_index - 2;
    vec2 tc;
    vec3 lv, projected;
    float attenuation, shadow;
    if (!alphaProjectorVars(index, pos, norm, center, radius, falloff,
                           tc, lv, attenuation, projected, shadow))
        return result;
    vec3 l = normalize(lv);
    float nl;
    vec3 diff, spec;
    pbrPunctual(diffuse, specular, roughness, metallic, norm, v, l, nl, diff, spec);
    result = attenuation * light_color * projected * 3.25 * shadow
        * clamp(nl * (diff + spec), vec3(0.0), vec3(10.0));
    // Match the projector ambiance term in the opaque PBR pass.
    float ambiance_nl = clamp(dot(norm, l), 0.000001, 1.0);
    result += light_color * alphaProjectorAmbiance(index, tc, attenuation, 0.0, ambiance_nl) * 3.25
        * clamp(nl * (diff + spec), vec3(0.0), vec3(10.0));
    result *= classic_mode > 0 ? 0.9 : 1.0;
#endif
    return max(result, vec3(0.0));
}
