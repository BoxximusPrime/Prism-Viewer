// Diagnostic overlay from the actual G-buffer skin marker.
/*[EXTRA_CODE_HERE]*/
out vec4 frag_color;
in vec2 vary_fragcoord;
uniform vec4 sss_params;
GBufferInfo getGBuffer(vec2 tc);
vec4 getPosition(vec2 tc);
uniform int sss_debug_depth, sss_debug_light, sss_debug_captured;
uniform sampler2D diffuseMap;
uniform vec3 sss_debug_sun;
uniform vec3 sss_depth_origin[2];
uniform vec3 sss_depth_valid;
void prepareSSSDepth(vec3 pos);
float sampleFocusedSunSSSPath(vec3 pos, vec3 lightDir);
float sampleLocalSSSPath(vec3 pos, vec3 lightOrigin);
void main()
{
    vec3 pos = getPosition(vary_fragcoord).xyz;
    prepareSSSDepth(pos);
    GBufferInfo gb = getGBuffer(vary_fragcoord);
    if (gb.sss < 0.5) discard;
    if (sss_debug_depth != 0)
    {
        if (sss_debug_light == 3)
        {
            frag_color = vec4(sss_debug_captured != 0 ? texture(diffuseMap, vary_fragcoord).rgb : vec3(0.0), 1.0);
            return;
        }
        float path = sss_debug_light == 0 ? sampleFocusedSunSSSPath(pos, normalize(sss_debug_sun)) :
            sampleLocalSSSPath(pos, sss_depth_origin[clamp(sss_debug_light - 1, 0, 1)]);
        if (sss_depth_valid[clamp(sss_debug_light, 0, 2)] <= 0.0) path = -1.0;
        vec3 color = path < 0.0 ? vec3(1.0, 0.0, 1.0) : vec3(1.0 - clamp(path / 0.3, 0.0, 1.0));
        frag_color = vec4(color, 1.0);
        return;
    }
    float distance = length(pos);
    float fade = 1.0 - smoothstep(sss_params.w * 0.8, sss_params.w, distance);
    frag_color = vec4(1.0, 0.0, 0.6, 0.8 * fade);
}
