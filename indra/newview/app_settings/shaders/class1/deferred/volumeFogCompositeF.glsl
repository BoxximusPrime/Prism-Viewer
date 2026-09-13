// Reconstruct only fog, preserving the full-resolution scene and glow channel.
out vec4 frag_color;
uniform sampler2D diffuseRect;
uniform sampler2D diffuseMap; // RGB in-scattering, A transmittance
uniform sampler2D depthMap;
uniform mat4 inv_proj;

float viewDepth(float depth)
{
    vec4 point = inv_proj * vec4(0.0, 0.0, depth * 2.0 - 1.0, 1.0);
    return abs(point.z) / max(abs(point.w), 1e-8);
}

void main()
{
    ivec2 pixel = ivec2(gl_FragCoord.xy);
    ivec2 source_size = textureSize(depthMap, 0);
    ivec2 fog_size = textureSize(diffuseMap, 0);
    vec4 scene = texelFetch(diffuseRect, pixel, 0);
    vec4 fog;
    if (all(equal(source_size, fog_size)))
        fog = texelFetch(diffuseMap, pixel, 0);
    else
    {
        float depth = viewDepth(texelFetch(depthMap, pixel, 0).r);
        vec2 position = gl_FragCoord.xy * vec2(fog_size) / vec2(source_size) - 0.5;
        ivec2 base = ivec2(floor(position));
        vec2 fraction = fract(position);
        vec4 sum = vec4(0.0);
        float weights = 0.0;
        // Reject samples across depth discontinuities. A thin foreground object
        // with no matching low-resolution sample stays clear rather than taking
        // the much longer fog path behind it. High/Ultra avoid this spatial loss.
        float tolerance = max(0.05, depth * 0.02);
        for (int y = 0; y < 2; ++y) for (int x = 0; x < 2; ++x)
        {
            ivec2 tap = clamp(base + ivec2(x,y), ivec2(0), fog_size - 1);
            ivec2 guide_pixel = min(ivec2((vec2(tap) + 0.5) * vec2(source_size) / vec2(fog_size)), source_size - 1);
            float difference = abs(viewDepth(texelFetch(depthMap, guide_pixel, 0).r) - depth);
            vec2 bilinear = mix(1.0 - fraction, fraction, vec2(x,y));
            float weight = bilinear.x * bilinear.y * max(0.0, 1.0 - difference / tolerance);
            sum += texelFetch(diffuseMap, tap, 0) * weight;
            weights += weight;
        }
        fog = weights > 0.00001 ? sum / weights : vec4(0.0, 0.0, 0.0, 1.0);
    }
    frag_color = vec4(clamp(scene.rgb * fog.a + fog.rgb, vec3(0.0), vec3(65000.0)), scene.a * fog.a);
}
