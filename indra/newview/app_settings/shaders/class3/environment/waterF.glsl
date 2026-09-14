/**
 * @file waterF.glsl
 *
 * $LicenseInfo:firstyear=2022&license=viewerlgpl$
 * Second Life Viewer Source Code
 * Copyright (C) 2022, Linden Research, Inc.
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

// Water is a dielectric interface over the already-fogged scene colour.
out vec4 frag_color;

uniform sampler2D bumpMap;
uniform sampler2D bumpMap2;
uniform sampler2D exclusionTex;
uniform float blend_factor;
uniform float blurMultiplier;
uniform float water_reflection_strength;
uniform float water_roughness_scale;
uniform float refScale;
uniform vec3 normScale;
uniform float fresnelScale;
uniform float fresnelOffset;
uniform vec4 waterPlane;
#ifdef TRANSPARENT_WATER
uniform sampler2D screenTex;
uniform sampler2D depthMap;
uniform mat4 projection_matrix;
uniform int water_local_reflections;
uniform int cube_snapshot;
uniform float water_refraction_strength;
uniform int water_refraction_fog;
#endif

in vec4 refCoord;
in vec4 littleWave;
in vec3 vary_position;
in vec3 vary_normal;
in vec3 vary_tangent;
in vec3 vary_light_dir;
in vec4 view;
in vec2 water_position;
in vec2 crossingWave;

void mirrorClip(vec3 pos);
vec3 getPositionWithNDC(vec3 ndc);
vec4 applyWaterFogViewLinear(vec3 pos, vec4 color);
vec3 waterRefractTransport(vec3 color, vec3 surface, vec3 receiver);
void calcAtmosphericVarsLinear(vec3 pos, vec3 norm, vec3 light_dir,
    out vec3 sunlit, out vec3 amblit, out vec3 additive, out vec3 atten);
void sampleReflectionProbesWater(inout vec3 ambenv, inout vec3 glossenv,
    vec2 tc, vec3 pos, vec3 norm, float glossiness, vec3 amblit);
vec2 BRDF(float NoV, float roughness);
#ifdef HAS_SUN_SHADOW
float sampleDirectionalShadow(vec3 pos, vec3 norm, vec2 pos_screen);
#endif

vec2 waterSurfaceSlope(vec2 position, vec2 broad_uv, vec2 crossing_uv,
                       vec4 detail_uv, float distance_to_eye);

float waterFresnel(float cosine, float f0)
{
    return f0 + (1.0 - f0) * pow(1.0 - clamp(cosine, 0.0, 1.0), 5.0);
}

#ifdef TRANSPARENT_WATER
bool waterProject(vec3 pos, out vec2 uv)
{
    vec4 clip = projection_matrix * vec4(pos, 1.0);
    uv = clip.xy / max(clip.w, 0.000001) * 0.5 + 0.5;
    return clip.w > 0.0 && all(greaterThan(uv, vec2(0.001))) &&
                           all(lessThan(uv, vec2(0.999)));
}

vec3 waterScenePosition(vec2 uv)
{
    return getPositionWithNDC(vec3(uv * 2.0 - 1.0, texture(depthMap, uv).r * 2.0 - 1.0));
}

// Screen-space wave refraction, relative to the flat interface. Applying the
// entire flat-interface Snell shift to a single colour/depth layer exposes holes
// and lifts a second silhouette out of the unwarped scene. Keep that baseline
// registered, and use the difference in refracted directions for wave distortion.
vec4 waterRefractedScene(vec3 pos, vec3 n, vec2 screen_uv, float mask, float water_depth)
{
    vec4 original = texture(screenTex, screen_uv);
    float strength = clamp(water_refraction_strength * refScale / 0.03, 0.0, 2.0);
    float confidence = mask * smoothstep(0.02, 0.5, water_depth);
    if (strength <= 0.0 || confidence <= 0.0 || cube_snapshot != 0)
        return original;
    vec3 incident = normalize(pos);
    vec3 bend = refract(incident, n, 1.0 / 1.333) -
                refract(incident, normalize(waterPlane.xyz), 1.0 / 1.333);
    vec3 direction = normalize(incident + bend * strength * confidence);
    if (direction.z >= -0.01 || dot(direction, waterPlane.xyz) >= -0.01)
        return original;

    vec3 receiver = waterScenePosition(screen_uv);
    vec2 uv = screen_uv;
    // Limit distortion in screen space, independently of resolution. Deep water
    // cannot supply newly exposed geometry from this single scene layer.
    vec2 size = vec2(textureSize(screenTex, 0));
    float max_pixels = 20.0 * size.y / 1080.0;
    for (int i = 0; i < 3; ++i)
    {
        float distance_to_receiver = max((receiver.z - pos.z) / direction.z, 0.0);
        vec2 candidate;
        waterProject(pos + direction * distance_to_receiver, candidate);
        vec2 offset = candidate - screen_uv;
        offset *= min(1.0, max_pixels / max(length(offset * size), 0.00001));
        vec2 edge = min(screen_uv, 1.0 - screen_uv);
        offset *= smoothstep(0.0, 0.035, min(edge.x, edge.y));
        candidate = clamp(screen_uv + offset, 0.5 / size, 1.0 - 0.5 / size);
        // Retreat the sampling coordinate at occlusion/exclusion edges. Never
        // cross-fade two scene colours: that creates a transparent duplicate.
        for (int j = 0; j < 6; ++j)
        {
            vec3 target = waterScenePosition(candidate);
            if (target.z < pos.z - 0.001 && texture(depthMap, candidate).r < 0.99999 &&
                texture(exclusionTex, candidate).r >= mask &&
                dot(target, waterPlane.xyz) + waterPlane.w < -0.001)
                break;
            candidate = mix(screen_uv, candidate, 0.5);
        }
        uv = candidate;
        receiver = waterScenePosition(uv);
    }
    if (receiver.z >= pos.z || texture(depthMap, uv).r >= 0.99999 ||
        texture(exclusionTex, uv).r < mask || dot(receiver, waterPlane.xyz) + waterPlane.w >= 0.0)
        return original;
    vec4 refracted = texture(screenTex, uv);
    if (water_refraction_fog != 0)
        refracted.rgb = waterRefractTransport(refracted.rgb, pos, receiver);
    return refracted;
}

// Same-frame, short-range reflection of visible land and objects. No additional
// scene render or history buffer. Misses fade to the existing environment probes.
vec4 waterLocalReflection(vec3 pos, vec3 n, float roughness)
{
    float confidence = (1.0 - smoothstep(96.0, 192.0, length(pos))) *
                       (1.0 - smoothstep(0.18, 0.45, roughness));
    vec3 direction = reflect(normalize(pos), n);
    if (water_local_reflections == 0 || cube_snapshot != 0 || confidence <= 0.0 ||
        dot(direction, waterPlane.xyz) <= 0.01)
        return vec4(0.0);

    vec3 origin = pos + waterPlane.xyz * 0.03;
    float previous_t = 0.0;
    float step_size = 0.2;
    float t = 0.1;
    bool was_in_front = false;
    for (int i = 0; i < 24; ++i)
    {
        vec3 ray_pos = origin + direction * t;
        vec2 uv;
        if (!waterProject(ray_pos, uv))
            break;
        vec3 scene_pos = waterScenePosition(uv);
        float gap = scene_pos.z - ray_pos.z;
        if (gap >= 0.0 && was_in_front)
        {
            float lo = previous_t, hi = t;
            for (int j = 0; j < 5; ++j)
            {
                float mid = (lo + hi) * 0.5;
                vec3 candidate = origin + direction * mid;
                waterProject(candidate, uv);
                if (waterScenePosition(uv).z - candidate.z >= 0.0)
                    hi = mid;
                else
                    lo = mid;
            }
            ray_pos = origin + direction * hi;
            waterProject(ray_pos, uv);
            scene_pos = waterScenePosition(uv);
            gap = scene_pos.z - ray_pos.z;
            float tolerance = 0.12 + 0.002 * length(scene_pos);
            // Reject depth discontinuities, the sky, and submerged geometry.
            // This prevents the seabed being mistaken for a land reflection.
            if (gap >= 0.0 && gap < tolerance && texture(depthMap, uv).r < 0.99999 &&
                dot(scene_pos, waterPlane.xyz) + waterPlane.w > 0.02)
            {
                vec2 edge = min(uv, 1.0 - uv);
                confidence *= smoothstep(0.0, 0.06, min(edge.x, edge.y));
                confidence *= 1.0 - smoothstep(48.0, 96.0, hi);
                confidence *= 1.0 - smoothstep(tolerance * 0.5, tolerance, gap);
                return vec4(texture(screenTex, uv).rgb, confidence);
            }
            return vec4(0.0);
        }
        was_in_front = gap < 0.0;
        previous_t = t;
        step_size *= 1.24;
        t = min(t + step_size, 96.0);
        if (previous_t >= 96.0)
            break;
    }
    return vec4(0.0);
}
#endif

// GGX with height-correlated Smith visibility. Unlike the generic material
// BRDF, a low-F0 water dielectric still reaches full grazing reflectance.
float waterSunSpecular(vec3 n, vec3 v, vec3 l, float roughness, float f0)
{
    float nl = max(dot(n, l), 0.0);
    float nv = max(dot(n, v), 0.001);
    vec3 half_vector = l + v;
    if (nl <= 0.0 || dot(half_vector, half_vector) < 0.000001)
        return 0.0;
    vec3 h = normalize(half_vector);
    float nh = max(dot(n, h), 0.0);
    // A finite sun highlight remains stable at the mirror endpoint. Environment
    // reflections can still use zero roughness; this is only the direct lobe.
    float a = pow(max(roughness, 0.02), 2.0);
    float a2 = a * a;
    float d = (1.0 - nh * nh) + nh * nh * a2;
    float distribution = a2 / (3.14159265 * d * d);
    float visibility = 0.5 / max(
        nl * sqrt(nv * nv * (1.0 - a2) + a2) +
        nv * sqrt(nl * nl * (1.0 - a2) + a2), 0.000001);
    return nl * distribution * visibility * waterFresnel(dot(v, h), f0);
}

float waterSurfaceRoughness(vec3 n)
{
    float preset = clamp(blurMultiplier, 0.06, 1.0);
    float scale = clamp(water_roughness_scale, 0.0, 3.0);
    // Below 1 sharpens the preset; above 1 reaches the full roughness range.
    // Multiplying a near-zero preset alone made most of the slider ineffective.
    float base = scale <= 1.0 ? preset * scale : mix(preset, 1.0, (scale - 1.0) * 0.5);
    // Keep the subpixel specular filter after the material adjustment. Smooth
    // settings can sharpen resolved highlights without reintroducing glitter.
    vec3 dx = dFdx(n);
    vec3 dy = dFdy(n);
    float variance = min(0.5 * (dot(dx, dx) + dot(dy, dy)), 0.02);
    return clamp(pow(pow(base, 4.0) + variance, 0.25), 0.0, 1.0);
}

void main()
{
    mirrorClip(vary_position);
    vec3 pos = vary_position;
    vec3 v = normalize(-pos);
    vec3 up = normalize(vary_normal);
    vec3 tangent = normalize(vary_tangent);
    vec3 bitangent = normalize(cross(up, tangent));
    vec2 screen_uv = refCoord.xy / refCoord.z * 0.5 + 0.5;
    float mask = clamp(texture(exclusionTex, screen_uv).r, 0.0, 1.0);

    float water_depth = 1000.0;
#ifdef TRANSPARENT_WATER
    vec3 behind = waterScenePosition(screen_uv);
    water_depth = max(-(dot(behind, waterPlane.xyz) + waterPlane.w), 0.0);
#endif
    vec2 slope = waterSurfaceSlope(water_position, vec2(refCoord.w, view.w),
                                   crossingWave, littleWave, length(pos));
    vec3 waves = vec3(slope * mix(0.35, 1.0, smoothstep(0.0, 1.5, water_depth)), 1.0);
    // Use the same normal for reflections, Fresnel and direct light. Keep the
    // authored scale, with a positive Z even for a zero-strength preset.
    waves *= max(normScale, vec3(0.0));
    waves.z = max(waves.z, 0.001);
    vec3 n = normalize(tangent * waves.x + bitangent * waves.y + up * waves.z);
    // Very steep normal-map slopes must not point behind the viewing hemisphere.
    float facing = dot(n, v);
    if (facing < 0.001)
        n = normalize(mix(n, up, clamp((0.001 - facing) / max(dot(up, v) - facing, 0.001), 0.0, 1.0)));

    float roughness = waterSurfaceRoughness(n);

    vec3 sunlit, amblit, additive, atten;
    vec3 light_dir = normalize(vary_light_dir);
    calcAtmosphericVarsLinear(pos, n, light_dir, sunlit, amblit, additive, atten);
    float shadow = 1.0;
#ifdef HAS_SUN_SHADOW
    shadow = sampleDirectionalShadow(pos, n, screen_uv);
#endif

#ifdef TRANSPARENT_WATER
    vec4 transmitted = waterRefractedScene(pos, n, screen_uv, mask, water_depth);
#else
    if (mask < 1.0)
        discard;
    vec4 transmitted = applyWaterFogViewLinear(-v * 2048.0, vec4(0.0));
#endif

    // Air/water IOR 1.333 gives F0 ~= 0.02037. Existing EEP Fresnel controls
    // remain modest artistic adjustments around their default values.
    float f0 = clamp(0.02037 * exp2(clamp((fresnelOffset - 0.5) * 2.0 +
                     fresnelScale - 0.3999, -2.0, 2.0)), 0.005, 0.08);
    float nv = max(dot(n, v), 0.001);
    // The viewer's BRDF LUT uses glossiness on its second axis.
    vec2 brdf = BRDF(nv, 1.0 - roughness);
    float reflection_strength = clamp(water_reflection_strength, 0.0, 1.0);
    float reflected_energy = clamp(f0 * brdf.x + brdf.y, 0.0, 1.0) * reflection_strength;
    vec3 irradiance = vec3(0.0), radiance = vec3(0.0);
    // Reflection rays originate at the surface pixel, not the refracted UV.
    sampleReflectionProbesWater(irradiance, radiance, screen_uv, pos, n, 1.0 - roughness, amblit);
#ifdef TRANSPARENT_WATER
    if (mask > 0.0 && reflection_strength > 0.0)
    {
        vec4 local_reflection = waterLocalReflection(pos, n, roughness);
        radiance = mix(radiance, local_reflection.rgb, local_reflection.a);
    }
#endif
    vec3 direct = waterSunSpecular(n, v, light_dir, roughness, f0) * sunlit * shadow * atten * reflection_strength;
    vec3 color = transmitted.rgb * (1.0 - reflected_energy) + radiance * reflected_energy + direct;
    color = mix(transmitted.rgb, color, mask);
    // Alpha is the viewer's authored glow channel, not surface opacity. Water
    // is not emissive; its specular highlights remain HDR in RGB for tone mapping.
    frag_color = vec4(clamp(color, vec3(0.0), vec3(65504.0)), 0.0);
}
