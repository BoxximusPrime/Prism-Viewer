// Focused deep-opacity atlas: sun/moon and two local lights, one tile each.
#ifdef HAIR_DENSITY_MAPS
uniform sampler2D hairBoundsMap;
uniform sampler2D hairDensityMap;
uniform mat4 hair_depth_matrix[3];
uniform vec4 hair_depth_projection[3];
uniform vec3 hair_depth_valid;
uniform vec4 hair_depth_focus;
uniform vec3 hair_depth_origin[2];
uniform int hair_depth_pass; // 1 ordinary blockers, 2 nearest hair, 3 accumulated opacity
uniform int hair_depth_slot;
uniform int hair_depth_object;
uniform vec4 hair_params;

// Recover axial distance in metres from either an orthographic or perspective map.
float hairDepthDistance(float depth, vec4 projection)
{
    float z = depth * 2.0 - 1.0;
    return (z * projection.w - projection.y) / (z * projection.z - projection.x);
}

const vec4 hairDepthKnots = vec4(0.02, 0.08, 0.32, 2.5);

bool hairDepthCapture(float alpha, out vec4 result)
{
    if (hair_depth_pass == 0) return false;
    if ((hair_depth_pass == 1) == (hair_depth_object != 0)) discard;
    if (alpha <= 0.001) discard;
    float depth = hairDepthDistance(gl_FragCoord.z, hair_depth_projection[hair_depth_slot]);
    result = vec4(depth);
    if (hair_depth_pass == 3)
    {
        vec2 bounds = texelFetch(hairBoundsMap, ivec2(gl_FragCoord.xy), 0).rg;
        if (depth > bounds.g) discard;
        // shortcut: artist meshes proxy fiber density; use authored optical depth when assets provide it.
        float opticalDepth = -log(max(1.0 - 0.85 * clamp(alpha, 0.0, 1.0), 0.001));
        result = opticalDepth * step(vec4(max(depth - bounds.r, 0.0)), hairDepthKnots);
    }
    return true;
}

float hairIntegratedDensity(vec4 layers, float distance)
{
    // Extremely dense overlap may overflow the half-float atlas; it is already opaque.
    layers = min(layers, vec4(64.0));
    vec4 previous = vec4(0.0, layers.xyz);
    vec4 start = vec4(0.0, hairDepthKnots.xyz);
    vec4 fractions = clamp((vec4(distance) - start) / (hairDepthKnots - start), 0.0, 1.0);
    return dot(max(layers - previous, vec4(0)), fractions);
}

float hairDensityShadow(int slot, vec3 pos, float fallback)
{
    float coverage = hair_depth_valid[slot] * (1.0 - smoothstep(hair_depth_focus.w * 0.8,
        hair_depth_focus.w, distance(pos, hair_depth_focus.xyz)));
    if (coverage <= 0.0 || hair_params.z <= 0.0) return fallback;
    vec4 projected = hair_depth_matrix[slot] * vec4(pos, 1.0);
    if (projected.w <= 0.0) return fallback;
    vec3 tc = projected.xyz / projected.w;
    if (any(lessThanEqual(tc, vec3(0))) || any(greaterThanEqual(tc, vec3(1)))) return fallback;
    ivec2 size = textureSize(hairBoundsMap, 0);
    int width = size.x / 3;
    vec2 pixel = tc.xy * vec2(width, size.y) - 0.5;
    ivec2 corner = ivec2(floor(pixel));
    vec2 fraction = fract(pixel);
    float depth = hairDepthDistance(tc.z, hair_depth_projection[slot]);
    // Finite footprint bias, in metres, stays independent of camera distance and skybox altitude.
    float bias = max(0.001, hair_depth_focus.w * 2.0 / float(width));
    float visibility = 0.0;
    for (int y = 0; y < 2; ++y)
    for (int x = 0; x < 2; ++x)
    {
        ivec2 tap = clamp(corner + ivec2(x,y), ivec2(0), ivec2(width-1, size.y-1));
        tap.x += slot * width;
        vec2 bounds = texelFetch(hairBoundsMap, tap, 0).rg;
        vec4 layers = texelFetch(hairDensityMap, tap, 0);
        float distance = max(depth - bias - bounds.r, 0.0);
        float density = hairIntegratedDensity(layers, distance);
        float transmission = exp(-density * clamp(hair_params.w, 0.25, 4.0));
        if (distance > hairDepthKnots.w) transmission = fallback;
        // An ordinary object, including the avatar's head, is always a solid blocker.
        if (depth - bias > bounds.g) transmission = 0.0;
        float weight = (x == 0 ? 1.0-fraction.x : fraction.x) * (y == 0 ? 1.0-fraction.y : fraction.y);
        visibility += transmission * weight;
    }
    return mix(fallback, visibility, coverage);
}

float hairSunShadow(vec3 pos, float fallback)
{
    return hairDensityShadow(0, pos, fallback);
}

float hairLocalShadow(vec3 pos, vec3 origin, float fallback)
{
    for (int i = 0; i < 2; ++i)
        if (hair_depth_valid[i+1] > 0.0 && distance(origin, hair_depth_origin[i]) < 0.001)
            return hairDensityShadow(i+1, pos, fallback);
    return fallback;
}
#else
// Keep the existing lighting on GPUs without room for two more fragment samplers.
bool hairDepthCapture(float alpha, out vec4 result) { return false; }
float hairSunShadow(vec3 pos, float fallback) { return fallback; }
float hairLocalShadow(vec3 pos, vec3 origin, float fallback) { return fallback; }
#endif
