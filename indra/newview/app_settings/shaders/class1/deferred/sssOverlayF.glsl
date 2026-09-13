// Capture skin colour only. Existing alpha/PBR vertex shaders supply animation,
// texture transforms and vertex tint; the neck supplies geometry and lighting.
in vec3 vary_position;
in vec4 vertex_color;
#ifdef SSS_OVERLAY_PBR
in vec2 base_color_texcoord;
#else
in vec2 vary_texcoord0;
#endif
#ifndef USE_INDEXED_TEX
uniform sampler2D diffuseMap;
#endif
out vec4 frag_color;
bool isSSSOverlay(vec3 positionEye);
vec3 srgb_to_linear(vec3 color);

void main()
{
    if (!isSSSOverlay(vary_position)) discard;
#ifdef SSS_OVERLAY_PBR
    vec4 color = texture(diffuseMap, base_color_texcoord);
    color.rgb = srgb_to_linear(color.rgb) * vertex_color.rgb;
#else
#ifdef USE_INDEXED_TEX
    vec4 color = diffuseLookup(vary_texcoord0);
#else
    vec4 color = texture(diffuseMap, vary_texcoord0);
#endif
    color.rgb = srgb_to_linear(color.rgb * vertex_color.rgb);
#endif
    color.a *= vertex_color.a;
    if (color.a < 0.004) discard;
    frag_color = color;
}
