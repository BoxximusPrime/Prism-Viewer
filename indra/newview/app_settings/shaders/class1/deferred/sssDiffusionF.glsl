/**
 * Tagged mesh skin diffusion. Filters diffuse irradiance only; surface color and
 * specular detail remain sharp. The vertical pass adds the diffuse difference.
 */
/*[EXTRA_CODE_HERE]*/

out vec4 frag_color;
in vec2 vary_fragcoord;
// Use registered sampler slots so each input gets its own texture unit.
uniform sampler2D diffuseMap;    // current horizontal/vertical filter input
uniform sampler2D altDiffuseMap; // original diffuse lighting for the final delta
uniform vec4 sss_params; // strength, mode, warmth, maximum distance
uniform float sss_depth; // scattering radius in meters, not mesh thickness
uniform int sss_pass;
uniform vec2 screen_res;
uniform mat4 inv_proj;

GBufferInfo getGBuffer(vec2 tc);
vec4 getPosition(vec2 tc);
vec3 srgb_to_linear(vec3 c);

vec3 skinAlbedo(GBufferInfo gb)
{
    vec3 albedo = gb.albedo.rgb;
    if (!GET_GBUFFER_FLAG(gb.gbufferFlag, GBUFFER_FLAG_HAS_PBR))
        albedo = srgb_to_linear(albedo);
    return max(albedo, vec3(0.02));
}

void main()
{
    vec2 tc = vary_fragcoord;
    GBufferInfo center = getGBuffer(tc);
    vec3 pos = getPosition(tc).xyz;
    float fade = 1.0 - smoothstep(sss_params.w * 0.8, sss_params.w, length(pos));
    if (center.sss < 0.5 || fade <= 0.0)
    {
        frag_color = vec4(0.0);
        return;
    }

    vec3 albedo = skinAlbedo(center);
    float radius = clamp(sss_depth * 0.5 * screen_res.y /
                         max(abs(inv_proj[1][1]) * -pos.z, 0.001), 0.0, 24.0);
    float visible = smoothstep(0.5, 1.5, radius);
    if (visible <= 0.0)
    {
        // Subpixel diffusion is invisible: keep the horizontal irradiance valid
        // for adjacent pixels, and skip the neighborhood filter entirely.
        frag_color = sss_pass == 0 ? vec4(texture(diffuseMap, tc).rgb / albedo, 0.0) : vec4(0.0);
        return;
    }
    vec2 direction = sss_pass == 0 ? vec2(1.0 / screen_res.x, 0.0) : vec2(0.0, 1.0 / screen_res.y);
    vec3 sigma = mix(vec3(0.65), vec3(1.0, 0.55, 0.35), sss_params.z);
    vec3 sum = vec3(0.0);
    vec3 weights = vec3(0.0);
    for (int i = -6; i <= 6; ++i)
    {
        float offset = float(i) / 6.0;
        vec2 uv = tc + direction * radius * offset;
        if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)))) continue;
        GBufferInfo sample_gb = getGBuffer(uv);
        if (sample_gb.sss < 0.5) continue;
        vec3 sample_pos = getPosition(uv).xyz;
        float edge = exp(-abs(sample_pos.z - pos.z) / max(sss_depth * 2.0, 0.001));
        edge *= pow(max(dot(center.normal, sample_gb.normal), 0.0), 4.0);
        vec3 weight = exp(vec3(-4.5 * offset * offset) / (sigma * sigma)) * edge;
        vec3 irradiance = texture(diffuseMap, uv).rgb;
        if (sss_pass == 0) irradiance /= skinAlbedo(sample_gb);
        sum += irradiance * weight;
        weights += weight;
    }
    vec3 filtered = sum / max(weights, vec3(0.00001));
    if (sss_pass == 0)
    {
        frag_color = vec4(filtered, 0.0);
    }
    else
    {
        vec3 original = texture(altDiffuseMap, tc).rgb;
        frag_color = vec4((filtered * albedo - original) * sss_params.x * fade * visible, 0.0);
    }
}
