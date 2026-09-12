// Initialize camera motion for terrain, sky and geometry without an object pass.
out vec4 frag_color;
uniform sampler2D depthMap;
uniform mat4 taa_inv_projection;
uniform mat4 taa_previous_from_view;
uniform mat4 taa_previous_projection;
uniform vec2 taa_rcp_res;
uniform vec2 taa_jitter;
uniform vec2 taa_reactive_depth_range;
void main()
{
    vec2 uv = gl_FragCoord.xy * taa_rcp_res;
    float d = texelFetch(depthMap, ivec2(gl_FragCoord.xy), 0).r;
    vec4 p = taa_inv_projection * vec4(uv * 2.0 - 1.0, d * 2.0 - 1.0, 1);
    p /= p.w;
    if (taa_reactive_depth_range.y > 0.0)
    {
        if (d >= 1.0 || -p.z < taa_reactive_depth_range.x || -p.z > taa_reactive_depth_range.y) discard;
        frag_color = vec4(0,0,0,1);
        return;
    }
    // A sky direction has no translation. Clouds remain subject to color rejection.
    bool sky = d >= 1.0;
    vec4 old_view = taa_previous_from_view * vec4(p.xyz, sky ? 0.0 : 1.0);
    vec4 old_clip = taa_previous_projection * old_view;
    vec2 old_uv = old_clip.xy / max(old_clip.w, 0.00001) * 0.5 + 0.5;
    frag_color = vec4(old_uv - (uv - taa_jitter), sky ? 0.0 : min(max(-old_view.z, 0.0), 65000.0),
                      old_clip.w <= 0.0 ? 1.0 : -1.0);
}
