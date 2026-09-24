// Shared by the above- and below-water surface shaders.
uniform sampler2D bumpMap;
uniform sampler2D bumpMap2;
uniform sampler2D waterWaveSlopes;
uniform float blend_factor;
uniform int water_procedural_waves;
uniform vec2 water_wave_direction;
uniform vec2 water_wave_origin;
uniform float water_wave_strength;
uniform float water_wave_scale;
uniform int water_wake_count;
uniform vec4 water_wakes[12]; // agent-space XY, age in seconds, strength

vec2 waterSpectralSlope(vec2 position, float footprint);

vec2 waterWakeSlope(vec2 position)
{
    vec2 slope = vec2(0.0);
    for (int i = 0; i < water_wake_count; ++i)
    {
        vec4 wake = water_wakes[i];
        vec2 offset = position - wake.xy;
        float radius = 0.25 + wake.z * 1.1;
        float width = 0.18 + wake.z * 0.08;
        float reach = radius + 2.5 * width;
        float distance_squared = dot(offset, offset);
        if (distance_squared > reach * reach) continue;
        float distance_to_wake = sqrt(distance_squared);
        float band = (distance_to_wake - radius) / width;
        if (abs(band) > 2.5) continue;
        float fade = max(1.0 - wake.z / 2.5, 0.0);
        slope += 0.3 * wake.w * fade * fade * band * exp(-band * band) *
            offset / max(distance_to_wake, 0.05);
    }
    return clamp(slope, vec2(-0.35), vec2(0.35));
}

vec3 waterNormal(vec2 uv)
{
    vec3 n = texture(bumpMap, uv).xyz;
    if (blend_factor > 0.0)
        n = mix(n, texture(bumpMap2, uv).xyz, blend_factor);
    return n * 2.0 - 1.0;
}

vec2 waterNormalSlope(vec3 n)
{
    return n.xy / max(n.z, 0.1);
}

float waterDetailWeight(vec2 position, float distance_to_eye)
{
    float patches = 0.5 + 0.25 * (sin(dot(position, vec2(0.035, 0.024))) +
                                 sin(dot(position, vec2(-0.017, 0.041))));
    return mix(0.18, 0.65, smoothstep(0.15, 0.85, patches)) *
           (1.0 - smoothstep(40.0, 200.0, distance_to_eye));
}

vec2 waterSurfaceSlope(vec2 position, vec2 broad_uv, vec2 crossing_uv,
                       vec4 detail_uv, float distance_to_eye)
{
    float detail = waterDetailWeight(position, distance_to_eye);
    if (water_procedural_waves == 0)
    {
        // Retain the previous rendering for a live, like-for-like comparison.
        mat2 rotation = mat2(0.5, -0.8660254, 0.8660254, 0.5);
        vec3 crossing = waterNormal(rotation * crossing_uv);
        crossing.xy = transpose(rotation) * crossing.xy;
        vec3 waves = waterNormal(broad_uv * 0.45) * 0.75 + crossing * 0.60 +
            detail * (waterNormal(detail_uv.xy) * 0.12 + waterNormal(detail_uv.zw) * 0.22);
        return 0.275 * waves.xy / max(waves.z, 0.001) + waterWakeSlope(position);
    }

    vec2 slope = waterSpectralSlope(position, 0.0);
    // The authored normal map supplies only small surface detail.
    slope += detail * (0.04 * waterNormalSlope(waterNormal(detail_uv.xy)) +
                       0.025 * waterNormalSlope(waterNormal(detail_uv.zw)));
    return slope + waterWakeSlope(position);
}
