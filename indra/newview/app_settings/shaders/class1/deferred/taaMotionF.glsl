out vec4 frag_color;
in vec4 previous_clip;
in float previous_depth;
uniform vec2 taa_rcp_res;
uniform vec2 taa_jitter;
uniform float taa_reactive;
void main()
{
    vec2 uv = gl_FragCoord.xy * taa_rcp_res - taa_jitter;
    vec2 old_uv = previous_clip.xy / max(previous_clip.w, 0.00001) * 0.5 + 0.5;
    frag_color = vec4(old_uv - uv, min(max(previous_depth, 0.0), 65000.0),
                      previous_clip.w <= 0.0 ? 1.0 : taa_reactive);
}
