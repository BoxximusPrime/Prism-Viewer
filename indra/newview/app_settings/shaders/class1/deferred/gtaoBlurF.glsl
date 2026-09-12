// Boxxy Viewer GTAO: separable five-tap depth/normal-aware spatial denoiser.
// The RG signal keeps visibility independent of lighting and preserves the
// geometry mask for an exposure-independent diagnostic view.
out vec2 frag_color;
in vec2 vary_fragcoord;
uniform sampler2D diffuseMap;
uniform sampler2D depthMap;
uniform vec2 screen_res;
uniform vec2 delta;
uniform vec4 gtao_params;
vec4 getPositionWithDepth(vec2 tc, float depth);
vec4 getNorm(vec2 tc);

void main()
{
    ivec2 pixel = ivec2(gl_FragCoord.xy);
    vec2 center = texelFetch(diffuseMap, pixel, 0).rg;
    if (center.g < 0.5 || gtao_params.w <= 0.0)
    {
        frag_color = center;
        return;
    }
    vec2 tc = (vec2(pixel) + 0.5) / screen_res;
    vec3 position = getPositionWithDepth(tc, texelFetch(depthMap, pixel, 0).r).xyz;
    vec3 normal = normalize(getNorm(tc).xyz);
    float total = center.r;
    float weights = 1.0;
    float tolerance = max(gtao_params.x * 0.02, abs(position.z) * 0.001);
    for (int side = -1; side <= 1; side += 2)
    {
        float continuity = 1.0;
        for (int step = 1; step <= 2; ++step)
        {
            ivec2 samplePixel = pixel + ivec2(delta) * (side * step);
            if (any(lessThan(samplePixel, ivec2(0))) || any(greaterThanEqual(samplePixel, ivec2(screen_res)))) break;
            vec2 sampleAO = texelFetch(diffuseMap, samplePixel, 0).rg;
            if (sampleAO.g < 0.5) break;
            vec2 sampleTC = (vec2(samplePixel) + 0.5) / screen_res;
            vec3 samplePosition = getPositionWithDepth(sampleTC, texelFetch(depthMap, samplePixel, 0).r).xyz;
            vec3 sampleNormal = normalize(getNorm(sampleTC).xyz);
            vec3 separation = samplePosition - position;
            float planeDistance = max(abs(dot(normal, separation)), abs(dot(sampleNormal, separation)));
            float edge = exp2(-planeDistance * planeDistance / (tolerance * tolerance));
            edge *= pow(max(dot(normal, sampleNormal), 0.0), 8.0);
            // Never blur through an intervening silhouette to a farther tap.
            continuity = min(continuity, edge);
            float weight = continuity * (step == 1 ? 0.65 : 0.25) * gtao_params.w;
            total += sampleAO.r * weight;
            weights += weight;
        }
    }
    frag_color = vec2(total / weights, center.g);
}
