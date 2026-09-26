// Resolve every receiver before denoising, including full-resolution repairs.
out vec4 frag_color;
in vec2 vary_fragcoord;
uniform sampler2D ssgiIndirect;
uniform sampler2D depthMap;
uniform vec2 screen_res;
uniform vec2 ssgi_half_res;
uniform float ssgi_radius;
vec4 getPositionWithDepth(vec2 tc, float depth);
vec4 getNorm(vec2 tc);
vec4 traceSSGI(vec2 tc);
vec2 fullPixel(vec2 tc) { return (floor(clamp(tc, vec2(0.0), vec2(0.999999)) * screen_res) + 0.5) / screen_res; }
void main()
{
    vec2 tc = fullPixel(vary_fragcoord);
    float depth = texture(depthMap, tc).r;
    frag_color = vec4(0.0);
    if (depth <= 0.0 || depth >= 1.0) return;
    vec3 position = getPositionWithDepth(tc, depth).xyz;
    vec3 normal = normalize(getNorm(tc).xyz);
    vec3 gathered = vec3(0.0);
    float weightSum = 0.0;
    float support = 0.0;
    vec2 halfPixel = tc * ssgi_half_res - 0.5;
    ivec2 base = ivec2(floor(halfPixel));
    vec2 fraction = fract(halfPixel);
    float tolerance = max(ssgi_radius * 0.04, abs(position.z) * 0.002);
    for (int y = 0; y < 2; ++y)
    for (int x = 0; x < 2; ++x)
    {
        ivec2 pixel = base + ivec2(x, y);
        if (any(lessThan(pixel, ivec2(0))) || any(greaterThanEqual(pixel, ivec2(ssgi_half_res)))) continue;
        vec4 gi = texelFetch(ssgiIndirect, pixel, 0);
        if (gi.a < 0.5) continue;
        vec2 sampleTC = fullPixel((vec2(pixel) + 0.5) / ssgi_half_res);
        vec3 samplePosition = getPositionWithDepth(sampleTC, texture(depthMap, sampleTC).r).xyz;
        vec3 sampleNormal = normalize(getNorm(sampleTC).xyz);
        vec3 separation = samplePosition - position;
        float plane = max(abs(dot(normal, separation)), abs(dot(sampleNormal, separation)));
        float edge = exp2(-plane * plane / (tolerance * tolerance)) *
            pow(max(dot(normal, sampleNormal), 0.0), 8.0);
        float bilinear = (x == 0 ? 1.0 - fraction.x : fraction.x) *
                         (y == 0 ? 1.0 - fraction.y : fraction.y);
        float weight = edge * bilinear;
        support = max(support, edge);
        gathered += gi.rgb * weight;
        weightSum += weight;
    }
    // Preserve edge rejection. If none of the half-resolution samples
    // represents this receiver, evaluate its own hemisphere instead of losing
    // its light or borrowing a different surface's illumination.
    float confidence = smoothstep(0.5, 0.85, support) * smoothstep(0.01, 0.1, weightSum);
    gathered /= max(weightSum, 0.0001);
    if (confidence < 1.0)
        gathered = mix(traceSSGI(tc).rgb, gathered, confidence);
    frag_color = vec4(gathered, 1.0 - confidence);

}
