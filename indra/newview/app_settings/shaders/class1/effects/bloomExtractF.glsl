/** HDR automatic bloom bright-pass with a soft threshold knee. */

out vec4 frag_color;

uniform sampler2D diffuseMap;
uniform float bloomThreshold;
uniform float bloomKnee;

in vec2 vary_texcoord0;

void main()
{
    vec3 color = max(texture(diffuseMap, vary_texcoord0).rgb, vec3(0.0));
    float brightness = max(color.r, max(color.g, color.b));
    float knee = max(bloomKnee, 0.0001);
    float soft = clamp((brightness - bloomThreshold + knee) / (2.0 * knee), 0.0, 1.0);
    soft = soft * soft * knee;
    float contribution = max(brightness - bloomThreshold, soft);
    frag_color = vec4(color * (contribution / max(brightness, 0.0001)), 1.0);
}
