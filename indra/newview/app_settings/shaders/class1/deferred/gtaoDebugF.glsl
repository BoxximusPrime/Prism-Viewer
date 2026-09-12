// Display white geometry multiplied by GTAO visibility, after tone mapping.
// No material colors, direct shadows, exposure, bloom, or skin diffusion.
out vec4 frag_color;
in vec2 vary_fragcoord;
uniform sampler2D diffuseMap;
uniform float gtao_strength;
void main()
{
    vec2 ao = texture(diffuseMap, vary_fragcoord).rg;
    float visibility = gtao_strength <= 0.0 ? 1.0 : pow(clamp(ao.r, 0.0, 1.0), gtao_strength);
    // sRGB encode a white diffuse surface with this linear visibility.
    float shade = visibility <= 0.0031308 ? visibility * 12.92 : 1.055 * pow(visibility, 1.0 / 2.4) - 0.055;
    frag_color = vec4(vec3(ao.g < 0.5 ? 0.18 : shade), 0.0);
}
