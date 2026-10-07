// Inspect the actual direct-shadow lightmap after PCSS cleanup, before its
// storage is reused by post processing. G is AO and must not enter this view.
// Depth is sampled here, before transparent receivers modify the depth buffer.
out vec4 frag_color;
in vec2 vary_fragcoord;
uniform sampler2D diffuseMap;
uniform sampler2D depthMap;
uniform vec2 projector_fade;

void main()
{
    vec4 shadows = texture(diffuseMap, vary_fragcoord);
    vec2 projectors = clamp(shadows.ba + projector_fade, 0.0, 1.0);
    float visibility = clamp(min(shadows.r, min(projectors.x, projectors.y)), 0.0, 1.0);
    // Match a white diffuse surface's sRGB display without exposure/tonemapping.
    float shade = visibility <= 0.0031308 ? visibility * 12.92 :
        1.055 * pow(visibility, 1.0 / 2.4) - 0.055;
    bool geometry = texture(depthMap, vary_fragcoord).r < 1.0;
    frag_color = vec4(vec3(geometry ? shade : 0.18), 0.0);
}
