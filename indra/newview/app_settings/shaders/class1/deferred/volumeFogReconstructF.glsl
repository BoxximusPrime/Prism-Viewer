// Reuse reduced-resolution fog only where the scene depth supports it.
// Missing samples are integrated at the real pixel by volumeFogF.glsl.
uniform sampler2D diffuseMap;
uniform sampler2D depthMap;
uniform mat4 inv_proj;

float fogViewDepth(float depth)
{
    vec4 point = inv_proj * vec4(0.0, 0.0, depth * 2.0 - 1.0, 1.0);
    return abs(point.z) / max(abs(point.w), 1e-8);
}

bool reconstructVolumeFog(ivec2 pixel, out vec4 fog)
{
    ivec2 source_size = textureSize(depthMap, 0);
    ivec2 fog_size = textureSize(diffuseMap, 0);
    float depth = fogViewDepth(texelFetch(depthMap, pixel, 0).r);
    vec2 position = (vec2(pixel) + 0.5) * vec2(fog_size) / vec2(source_size) - 0.5;
    ivec2 base = ivec2(floor(position));
    vec2 fraction = fract(position);
    float tolerance = max(0.05, depth * 0.02);
    // Preserve continuous terrain slopes without accepting samples across a
    // silhouette. Both sides must form a monotonic slope.
    for (int axis = 0; axis < 2; ++axis)
    {
        ivec2 offset = axis == 0 ? ivec2(1,0) : ivec2(0,1);
        float before = fogViewDepth(texelFetch(depthMap, clamp(pixel-offset, ivec2(0), source_size-1), 0).r)-depth;
        float after = fogViewDepth(texelFetch(depthMap, clamp(pixel+offset, ivec2(0), source_size-1), 0).r)-depth;
        if (before*after < 0.0)
            tolerance = max(tolerance, (1.0 + max(float(source_size.x)/float(fog_size.x),
                float(source_size.y)/float(fog_size.y))) * min(abs(before), abs(after)));
    }
    vec4 sum = vec4(0.0);
    float weights = 0.0;
    for (int y = 0; y < 2; ++y) for (int x = 0; x < 2; ++x)
    {
        ivec2 tap = clamp(base + ivec2(x,y), ivec2(0), fog_size - 1);
        ivec2 guide_pixel = min(ivec2((vec2(tap) + 0.5) * vec2(source_size) / vec2(fog_size)), source_size - 1);
        float difference = abs(fogViewDepth(texelFetch(depthMap, guide_pixel, 0).r) - depth);
        vec2 bilinear = mix(1.0 - fraction, fraction, vec2(x,y));
        float weight = bilinear.x * bilinear.y * max(0.0, 1.0 - difference / tolerance);
        sum += texelFetch(diffuseMap, tap, 0) * weight;
        weights += weight;
    }
    // Do not let a vanishingly small corner tap determine a leaf's fog.
    // The caller uses the same integration/lighting as the main fog pass.
    if (weights < 0.1) return false;
    fog = sum / weights;
    return true;
}
