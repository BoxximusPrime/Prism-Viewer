/** Normalized separable blur for the HDR automatic bloom layer. */

out vec4 frag_color;

uniform sampler2D diffuseMap;

in vec4 vary_texcoord0;
in vec4 vary_texcoord1;
in vec4 vary_texcoord2;
in vec4 vary_texcoord3;

void main()
{
    float weights[8];
    weights[0] = 0.25; weights[1] = 0.5; weights[2] = 0.8; weights[3] = 1.0;
    weights[4] = 1.0; weights[5] = 0.8; weights[6] = 0.5; weights[7] = 0.25;
    vec3 color = weights[0] * texture(diffuseMap, vary_texcoord0.xy).rgb;
    color += weights[1] * texture(diffuseMap, vary_texcoord1.xy).rgb;
    color += weights[2] * texture(diffuseMap, vary_texcoord2.xy).rgb;
    color += weights[3] * texture(diffuseMap, vary_texcoord3.xy).rgb;
    color += weights[4] * texture(diffuseMap, vary_texcoord0.zw).rgb;
    color += weights[5] * texture(diffuseMap, vary_texcoord1.zw).rgb;
    color += weights[6] * texture(diffuseMap, vary_texcoord2.zw).rgb;
    color += weights[7] * texture(diffuseMap, vary_texcoord3.zw).rgb;
    frag_color = vec4(color / 5.1, 1.0);
}
