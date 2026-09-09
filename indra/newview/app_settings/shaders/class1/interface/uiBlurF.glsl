// Separable Gaussian blur of the display-referred UI backdrop.
uniform sampler2D diffuseMap;
uniform vec2 blur_step; // one quarter sigma, in texture coordinates
uniform vec2 blur_uv_scale; // used region of the reusable scratch texture
in vec2 vary_fragcoord;
out vec4 frag_color;

void main()
{
    vec3 color = vec3(0.0);
    float total = 0.0;
    vec2 half_texel = 0.5 / vec2(textureSize(diffuseMap, 0));
    for (int i = -12; i <= 12; ++i)
    {
        float weight = exp(-0.5 * float(i * i) / 16.0);
        vec2 uv = clamp(vary_fragcoord * blur_uv_scale + float(i) * blur_step,
                        half_texel, blur_uv_scale - half_texel);
        color += texture(diffuseMap, uv).rgb * weight;
        total += weight;
    }
    frag_color = vec4(color / total, 1.0);
}
