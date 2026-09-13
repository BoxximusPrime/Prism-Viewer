uniform sampler2D diffuseRect;
uniform sampler2D diffuseMap;
uniform sampler2D altDiffuseMap;
uniform int sss_overlay_pass;
uniform float sss_overlay_distance;
in vec2 vary_fragcoord;
out vec4 frag_data[2];
vec4 getNormRaw(vec2 tc);
vec4 getPosition(vec2 tc);
vec3 srgb_to_linear(vec3 color);
vec3 linear_to_srgb(vec3 color);

void main()
{
    vec2 tc = vary_fragcoord;
    float flag = getNormRaw(tc).w;
    if (sss_overlay_pass == 0)
    {
        frag_data[0] = texture(diffuseRect, tc);
        vec3 positionEye = getPosition(tc).xyz;
        float z = GBUFFER_SSS_FLAG(flag) > 0.5 && length(positionEye) < sss_overlay_distance ? positionEye.z : 0.0;
        frag_data[1] = vec4(z, 0, 0, 0);
        return;
    }
    vec4 base = texture(altDiffuseMap, tc);
    vec4 overlay = texture(diffuseMap, tc); // linear, premultiplied by capture blending
    bool pbr = GET_GBUFFER_FLAG(flag, GBUFFER_FLAG_HAS_PBR);
    vec3 color = pbr ? base.rgb : srgb_to_linear(base.rgb);
    color = color * (1.0 - overlay.a) + overlay.rgb;
    // Preserve emission/fullbright metadata and all non-colour G-buffer targets.
    frag_data[0] = vec4(pbr ? color : linear_to_srgb(color), base.a);
    frag_data[1] = vec4(0);
}
