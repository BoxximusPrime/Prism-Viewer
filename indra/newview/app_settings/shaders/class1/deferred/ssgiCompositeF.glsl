// Add local diffuse bounce before SSS diffusion. Probe diffuse stays as a baseline.
layout(location = 0) out vec4 frag_color;
layout(location = 1) out vec4 sss_diffuse;
in vec2 vary_fragcoord;
uniform sampler2D ssgiIndirect;
uniform sampler2D depthMap;
uniform sampler2D diffuseRect;
uniform sampler2D specularRect;
uniform sampler2D normalMap;
uniform vec2 screen_res;
uniform float ssgi_strength;
uniform float ssgi_avatar_strength;
uniform int ssgi_debug;
uniform int ssgi_sss_active;
uniform vec4 sss_params;
vec4 getPositionWithDepth(vec2 tc, float depth);
vec4 getNorm(vec2 tc);
vec4 getNormRaw(vec2 tc);
vec3 srgb_to_linear(vec3 c);
vec2 fullPixel(vec2 tc) { return (floor(clamp(tc, vec2(0.0), vec2(0.999999)) * screen_res) + 0.5) / screen_res; }

void main()
{
    vec2 tc = fullPixel(vary_fragcoord);
    float depth = texture(depthMap, tc).r;
    frag_color = vec4(0.0);
    sss_diffuse = vec4(0.0);
    if (depth <= 0.0 || depth >= 1.0) return;
    vec3 position = getPositionWithDepth(tc, depth).xyz;
    vec3 normal = normalize(getNorm(tc).xyz);
    float flags = getNormRaw(tc).w;
    if (GET_GBUFFER_FLAG(flags, GBUFFER_FLAG_HAS_HDRI) ||
        GET_GBUFFER_FLAG(flags, GBUFFER_FLAG_SKIP_ATMOS)) return;

    vec3 gathered = texelFetch(ssgiIndirect, ivec2(gl_FragCoord.xy), 0).rgb;

    vec4 albedo = texture(diffuseRect, tc);
    vec4 material = texture(specularRect, tc);
    bool pbr = GET_GBUFFER_FLAG(flags, GBUFFER_FLAG_HAS_PBR);
    vec3 diffuse = pbr ? albedo.rgb * (1.0 - material.b) * 0.96 :
        srgb_to_linear(albedo.rgb) * (1.0 - albedo.a);
    // Screen-space ray visibility already occludes this local contribution.
    // Screen AO still attenuates the separate probe baseline; material AO
    // retains unresolved micro-occlusion from the asset.
    float materialAO = pbr ? clamp(material.r, 0.0, 1.0) : 1.0;
    vec3 response = diffuse * materialAO;
    response *= mix(1.0, ssgi_avatar_strength, GBUFFER_AVATAR_FLAG(flags));
    vec3 bounce = max(gathered * response * ssgi_strength, vec3(0.0));
    frag_color.rgb = ssgi_debug == 4 ? max(response, vec3(0.0)) :
        ssgi_debug == 1 ? max(gathered * ssgi_strength, vec3(0.0)) : bounce;

    float mask = GBUFFER_SSS_FLAG(flags);
    float distanceFade = 1.0 - smoothstep(sss_params.w * 0.8, sss_params.w, length(position));
    if (ssgi_sss_active != 0 && sss_params.x * mask * distanceFade > 0.0)
        sss_diffuse.rgb = bounce;
}
