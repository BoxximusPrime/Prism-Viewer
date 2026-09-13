// Lighting at points in air, with no surface-normal offsets or screen-space
// surface shadow factor. Coordinates and light transforms are all view-space.
const int VF_LIGHTS = 8;
uniform int vf_light_count;
uniform vec4 vf_light_position[VF_LIGHTS]; // xyz center, w effective radius
uniform vec4 vf_light_color[VF_LIGHTS]; // linear RGB, w legacy falloff
uniform vec4 vf_light_projector[VF_LIGHTS]; // texture slot (-1 point), shadow slot, visibility fade, unused
uniform mat4 vf_projector_matrix[4];
uniform vec4 vf_projector_params[4]; // focus, maximum LOD, range, unused
uniform vec4 vf_projector_normal[4];
uniform vec4 vf_projector_origin[4];
uniform sampler2D alphaProjectionMap0;
uniform sampler2D alphaProjectionMap1;
uniform sampler2D alphaProjectionMap2;
uniform sampler2D alphaProjectionMap3;

uniform vec3 vf_ambient;
uniform vec3 vf_sun_color; // active sun OR moon; zero when both are below horizon
uniform vec3 vf_sun_direction; // sample toward light
uniform float vf_light_strength;
uniform float vf_anisotropy;
uniform int vf_shadow_mask;
uniform mat4 shadow_matrix[6];
uniform vec4 shadow_clip;
// Reuse raw-depth units/sampler objects, with four depth comparisons per tap.
uniform sampler2D pcssDepthMap0;
uniform sampler2D pcssDepthMap1;
uniform sampler2D pcssDepthMap2;
uniform sampler2D pcssDepthMap3;
uniform sampler2D pcssDepthMap4;
uniform sampler2D pcssDepthMap5;

bool fogClipPlane(float origin, float direction, inout vec2 interval)
{
    if (abs(direction) < 1e-8) return origin >= 0.0;
    float t = -origin / direction;
    if (direction > 0.0) interval.x = max(interval.x, t);
    else interval.y = min(interval.y, t);
    return interval.y > interval.x;
}

vec2 fogLightInterval(int index, vec3 ray, float limit)
{
    vec3 center = vf_light_position[index].xyz;
    float radius = vf_light_position[index].w;
    float along = dot(center, ray);
    // Perpendicular distance avoids subtracting two large squared distances.
    vec3 perpendicular = center - ray * along;
    float discriminant = radius * radius - dot(perpendicular, perpendicular);
    if (radius <= 0.0 || discriminant <= 0.0) return vec2(0.0);
    float root = sqrt(discriminant);
    vec2 interval = vec2(max(0.0, along - root), min(limit, along + root));
    int projector = int(vf_light_projector[index].x);
    if (projector >= 0 && interval.y > interval.x)
    {
        mat4 transform = vf_projector_matrix[projector];
        vec4 origin = transform[3];
        vec4 direction = transform * vec4(ray, 0.0);
        // The existing projector matrix includes the NDC-to-[0,1] transform.
        if (!fogClipPlane(origin.w - 1e-6, direction.w, interval) ||
            !fogClipPlane(origin.x, direction.x, interval) ||
            !fogClipPlane(origin.w - origin.x, direction.w - direction.x, interval) ||
            !fogClipPlane(origin.y, direction.y, interval) ||
            !fogClipPlane(origin.w - origin.y, direction.w - direction.y, interval) ||
            !fogClipPlane(origin.z, direction.z, interval) ||
            !fogClipPlane(origin.w - origin.z, direction.w - direction.z, interval)) return vec2(0.0);
    }
    return interval.y > interval.x ? interval : vec2(0.0);
}

// Henyey-Greenstein relative to isotropic scattering (mean one). Viewer light
// units are artistic rather than radiometric; strength supplies the exposure.
float fogPhase(float cosine)
{
    float g = vf_anisotropy;
    float denominator = max(1.0 + g*g - 2.0*g*clamp(cosine, -1.0, 1.0), 0.01);
    return (1.0 - g*g) / (denominator * sqrt(denominator));
}

float fogCompareShadow(sampler2D map, vec3 coordinate)
{
    ivec2 size = textureSize(map, 0);
    vec2 p = coordinate.xy * vec2(size) - 0.5;
    ivec2 base = ivec2(floor(p));
    vec2 fraction = fract(p);
    float reference = coordinate.z - 0.000002;
    float sum = 0.0;
    for (int y = 0; y < 2; ++y) for (int x = 0; x < 2; ++x)
    {
        ivec2 texel = clamp(base + ivec2(x,y), ivec2(0), size - 1);
        vec2 weight = mix(1.0 - fraction, fraction, vec2(x,y));
        sum += weight.x * weight.y * step(reference, texelFetch(map, texel, 0).r);
    }
    return sum;
}

bool fogShadowCoordinate(int index, vec3 position, out vec3 coordinate)
{
    vec4 projected = shadow_matrix[index] * vec4(position, 1.0);
    if (projected.w <= 0.0) return false;
    coordinate = projected.xyz / projected.w;
    return all(greaterThanEqual(coordinate, vec3(0.0))) && all(lessThanEqual(coordinate, vec3(1.0)));
}

float fogShadow(int index, vec3 coordinate)
{
    // Constant sampler indices remain compatible with GLSL 330 drivers.
    if (index == 0) return fogCompareShadow(pcssDepthMap0, coordinate);
    if (index == 1) return fogCompareShadow(pcssDepthMap1, coordinate);
    if (index == 2) return fogCompareShadow(pcssDepthMap2, coordinate);
    if (index == 3) return fogCompareShadow(pcssDepthMap3, coordinate);
    if (index == 4) return fogCompareShadow(pcssDepthMap4, coordinate);
    return fogCompareShadow(pcssDepthMap5, coordinate);
}

float fogSunShadow(vec3 position)
{
    float depth = -position.z;
    if ((vf_shadow_mask & 15) == 0 || depth >= shadow_clip.w) return 1.0;
    float shadow = 0.0, weights = 0.0;
    for (int i = 0; i < 4; ++i)
    {
        if ((vf_shadow_mask & (1 << i)) == 0) continue;
        float weight = 1.0;
        if (i > 0) weight -= max(1.25 * shadow_clip[i-1] - depth, 0.0) / max(0.5 * shadow_clip[i-1], 0.0001);
        if (i < 3) weight -= max(depth - 0.75 * shadow_clip[i], 0.0) / max(0.5 * shadow_clip[i], 0.0001);
        if (weight <= 0.0) continue;
        vec3 coordinate;
        if (!fogShadowCoordinate(i, position, coordinate)) continue;
        shadow += weight * fogShadow(i, coordinate);
        weights += weight;
    }
    // Surface-fitted shadow maps can omit air outside their bounds. Do not
    // clamp those samples to an unrelated edge texel or reuse a stale cascade.
    if (weights <= 0.0) return 1.0;
    float fade = smoothstep(shadow_clip.w * 0.9, shadow_clip.w, depth);
    return mix(shadow / weights, 1.0, fade);
}

vec4 fogProjection(int index, vec2 uv, float lod)
{
    if (index == 0) return textureLod(alphaProjectionMap0, uv, lod);
    if (index == 1) return textureLod(alphaProjectionMap1, uv, lod);
    if (index == 2) return textureLod(alphaProjectionMap2, uv, lod);
    return textureLod(alphaProjectionMap3, uv, lod);
}

vec3 fogSRGBToLinear(vec3 color)
{
    return mix(color / 12.92, pow((color + 0.055) / 1.055, vec3(2.4)), step(vec3(0.04045), color));
}

vec3 fogDirectional(vec3 ray)
{
    return vf_sun_color * fogPhase(dot(vf_sun_direction, ray));
}

vec3 fogLighting(vec3 position, vec3 ray, int light_mask, vec3 directional)
{
    if (vf_light_strength <= 0.0) return vf_ambient;
    vec3 light = vec3(0.0);
    if (any(greaterThan(directional, vec3(0.0))))
        light = directional * fogSunShadow(position);
    for (int i = 0; i < vf_light_count; ++i)
    {
        if ((light_mask & (1 << i)) == 0) continue;
        vec3 delta = vf_light_position[i].xyz - position;
        float distance = length(delta);
        float radius = vf_light_position[i].w;
        if (radius <= 0.0 || distance >= radius) continue;
        float falloff = vf_light_color[i].w;
        // Match calcLegacyDistanceAttenuation, shared by SL point/projector lights.
        float attenuation = 1.0 - clamp((distance / radius + falloff) / (1.0 + falloff), 0.0, 1.0);
        attenuation *= attenuation * 2.0;
        vec3 projected_color = vec3(1.0);
        float visibility = 1.0;
        int projector = int(vf_light_projector[i].x);
        if (projector >= 0)
        {
            vec4 projected = vf_projector_matrix[projector] * vec4(position, 1.0);
            if (projected.w <= 0.0) continue;
            vec3 coordinate = projected.xyz / projected.w;
            if (any(lessThan(coordinate, vec3(0.0))) || any(greaterThan(coordinate, vec3(1.0)))) continue;
            vec4 params = vf_projector_params[projector];
            if (params.z <= 0.0) continue;
            float light_distance = -dot(delta, vf_projector_normal[projector].xyz);
            float lod = clamp((light_distance - params.x) / params.z, 0.0, 1.0) * params.y;
            vec4 tap = fogProjection(projector, coordinate.xy, lod);
            vec2 edge_distance = min(coordinate.xy, 1.0 - coordinate.xy);
            float edge = 0.25 * min(lod / max(params.y * 0.5, 0.000001), 1.0);
            float edge_weight = clamp(min(edge_distance.x, edge_distance.y) / max(edge, 0.000001), 0.0, 1.0);
            projected_color = fogSRGBToLinear(max(tap.rgb, vec3(0.0))) * tap.a * edge_weight;
            int shadow = int(vf_light_projector[i].y);
            vec3 shadow_coordinate;
            if (shadow >= 0 && (vf_shadow_mask & (1 << (shadow + 4))) != 0 &&
                fogShadowCoordinate(shadow + 4, position, shadow_coordinate))
                visibility = clamp(fogShadow(shadow + 4, shadow_coordinate) + vf_light_projector[i].z, 0.0, 1.0);
            // The projector's virtual origin differs from its prim center.
            delta = vf_projector_origin[projector].xyz - position;
        }
        vec3 to_light = delta / max(length(delta), 0.0001);
        light += vf_light_color[i].rgb * projected_color * attenuation * visibility * fogPhase(dot(to_light, ray));
    }
    return vf_ambient + light * vf_light_strength;
}
