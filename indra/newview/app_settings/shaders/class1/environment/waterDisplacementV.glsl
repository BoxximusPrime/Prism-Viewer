// Visual height displacement from the same swell/chop that generates normals.
// Shared by the surface and water-exclusion depth pass.
uniform sampler2D waterWaveHeights;
uniform vec2 water_wave_direction;
uniform vec2 water_wave_origin;
uniform vec2 water_mesh_center;
uniform float water_wave_scale;
uniform float water_wave_strength;
uniform float water_displacement;
uniform float water_displacement_distance;
uniform vec3 normScale;
uniform sampler2D waterGeometryDepth;
uniform mat4 modelview_projection_matrix;
uniform mat4 inv_proj;
uniform mat4 inv_modelview;
uniform float water_shallow_damping;

float waterDisplacementDamping(vec3 position)
{
    if (water_shallow_damping <= 0.0)
        return 1.0;
    vec4 clip = modelview_projection_matrix * vec4(position, 1.0);
    if (clip.w <= 0.0) return 1.0;
    vec2 uv = clip.xy / clip.w * 0.5 + 0.5;
    if (any(lessThanEqual(uv, vec2(0.0))) || any(greaterThanEqual(uv, vec2(1.0)))) return 1.0;
    float depth = textureLod(waterGeometryDepth, uv, 0.0).r;
    if (depth >= 0.999999) return 1.0;
    vec4 receiver = inv_modelview * inv_proj * vec4(uv * 2.0 - 1.0, depth * 2.0 - 1.0, 1.0);
    if (abs(receiver.w) < 0.000001) return 1.0;
    float water_depth = position.z - receiver.z / receiver.w;
    // Foreground trees/rocks above water do not describe the submerged bottom.
    if (water_depth < -0.01) return 1.0;
    float edge = min(min(uv.x, uv.y), min(1.0-uv.x, 1.0-uv.y));
    float confidence = smoothstep(0.0, 0.03, edge);
    return mix(1.0, smoothstep(0.0, 1.5, max(water_depth, 0.0)), water_shallow_damping * confidence);
}

vec3 waterDisplacedPosition(vec3 position)
{
    if (water_displacement <= 0.0 || water_wave_strength <= 0.0)
        return position;
    vec2 offset = abs(position.xy - water_mesh_center);
    float radius = max(water_displacement_distance, 1.0);
    float fade = 1.0 - smoothstep(radius * 0.65, radius, length(offset));
    if (fade <= 0.0) return position;
    // Two 25 cm CPU grid cells. Keep resolvable waves throughout the radius;
    // fine ripples stay in the fragment normals instead of aliasing the mesh.
    float footprint = 0.5;
    float scale = clamp(water_wave_scale, 0.01, 2.0);
    vec2 direction = water_wave_direction;
    vec2 across = vec2(-direction.y, direction.x);
    vec2 local = vec2(dot(position.xy, direction), dot(position.xy, across)) / scale + water_wave_origin;
    float swell = textureLod(waterWaveHeights, local / 256.0, max(log2(footprint / scale), 0.0)).r;
    float chop = textureLod(waterWaveHeights, local / 64.0, max(log2(footprint / (scale * 0.25)), 0.0)).g;
    // Scaling heights and wavelengths together preserves the existing slope
    // strength. EEP's normal-scale ratio is an artistic slope multiplier.
    float normal_scale = max(0.5 * (normScale.x + normScale.y), 0.0) / max(normScale.z, 0.001);
    float height = (swell + 0.55 * chop) * scale * water_wave_strength * normal_scale * water_displacement;
    // LLVOWater expands its culling extents by the same eight-metre bound.
    position.z += clamp(height, -8.0, 8.0) * fade * waterDisplacementDamping(position);
    return position;
}
