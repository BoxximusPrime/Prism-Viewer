// Diagnostic overlay from the actual G-buffer skin marker.
/*[EXTRA_CODE_HERE]*/
out vec4 frag_color;
in vec2 vary_fragcoord;
uniform vec4 sss_params;
GBufferInfo getGBuffer(vec2 tc);
vec4 getPosition(vec2 tc);
void main()
{
    GBufferInfo gb = getGBuffer(vary_fragcoord);
    if (gb.sss < 0.5) discard;
    float distance = length(getPosition(vary_fragcoord).xyz);
    float fade = 1.0 - smoothstep(sss_params.w * 0.8, sss_params.w, distance);
    frag_color = vec4(1.0, 0.0, 0.6, 0.8 * fade);
}
