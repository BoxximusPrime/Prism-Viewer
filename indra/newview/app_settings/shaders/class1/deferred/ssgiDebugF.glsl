// Final presentation diagnostic, after tone mapping, fog, skin diffusion and transparency.
out vec4 frag_color;
in vec2 vary_fragcoord;
uniform sampler2D ssgiSource;
uniform sampler2D depthMap;
uniform int ssgi_debug;

void main()
{
    float depth = texture(depthMap, vary_fragcoord).r;
    vec3 color = vec3(0.0);
    if (depth > 0.0 && depth < 1.0)
        color = max(texture(ssgiSource, vary_fragcoord).rgb, vec3(0.0));
    // Incoming and applied light were captured by the production composite,
    // including repaired receivers and strength. Do not scale them twice.
    // Incoming and applied bounce share a display curve for comparison. A
    // material response of one should display white, not tone-mapped gray.
    color = ssgi_debug == 4 ? clamp(color, vec3(0.0), vec3(1.0)) : color / (vec3(1.0) + color);
    color = mix(12.92 * color, 1.055 * pow(color, vec3(1.0 / 2.4)) - 0.055,
                vec3(greaterThan(color, vec3(0.0031308))));
    frag_color = vec4(color, 0.0);
}
