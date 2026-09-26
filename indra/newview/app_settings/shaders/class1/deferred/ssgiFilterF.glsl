// Half-resolution edge-aware spatial filter; no animated sampling or history.
out vec4 frag_color;
in vec2 vary_fragcoord;
uniform sampler2D ssgiIndirect;
uniform sampler2D depthMap;
uniform vec2 ssgi_half_res;
uniform vec2 screen_res;
uniform float ssgi_radius;
uniform int ssgi_denoise_mode;
uniform int ssgi_filter_stride;
vec4 getPositionWithDepth(vec2 tc, float depth);
vec4 getNorm(vec2 tc);
vec2 fullPixel(vec2 tc) { return (floor(clamp(tc, vec2(0.0), vec2(0.999999)) * screen_res) + 0.5) / screen_res; }

void main()
{
    vec2 halfTC = (floor(gl_FragCoord.xy) + 0.5) / ssgi_half_res;
    vec2 tc = fullPixel(halfTC);
    vec4 centerGI = texture(ssgiIndirect, halfTC);
    if (centerGI.a < 0.5)
    {
        frag_color = centerGI;
        return;
    }
    vec3 position = getPositionWithDepth(tc, texture(depthMap, tc).r).xyz;
    vec3 normal = normalize(getNorm(tc).xyz);
    vec3 total = vec3(0.0);
    float totalWeight = 0.0;
    float tolerance = max(ssgi_radius * 0.04, abs(position.z) * 0.002);
    int extent = ssgi_denoise_mode == 2 ? 2 : 1;
    for (int y = -2; y <= 2; ++y)
    for (int x = -2; x <= 2; ++x)
    {
        if (abs(x) > extent || abs(y) > extent) continue;
        vec2 neighbor = halfTC + vec2(x, y) * float(ssgi_filter_stride) / ssgi_half_res;
        if (any(lessThan(neighbor, vec2(0.0))) || any(greaterThanEqual(neighbor, vec2(1.0)))) continue;
        vec4 gi = texture(ssgiIndirect, neighbor);
        if (gi.a < 0.5) continue;
        vec2 sampleTC = fullPixel(neighbor);
        vec3 samplePosition = getPositionWithDepth(sampleTC, texture(depthMap, sampleTC).r).xyz;
        vec3 sampleNormal = normalize(getNorm(sampleTC).xyz);
        vec3 separation = samplePosition - position;
        float plane = max(abs(dot(normal, separation)), abs(dot(sampleNormal, separation)));
        float edge = exp2(-plane * plane / (tolerance * tolerance));
        edge *= pow(max(dot(normal, sampleNormal), 0.0), 8.0);
        float wx = extent == 2 ? (x == 0 ? 6.0 : abs(x) == 1 ? 4.0 : 1.0) : (x == 0 ? 2.0 : 1.0);
        float wy = extent == 2 ? (y == 0 ? 6.0 : abs(y) == 1 ? 4.0 : 1.0) : (y == 0 ? 2.0 : 1.0);
        float weight = wx * wy * edge;
        total += gi.rgb * weight;
        totalWeight += weight;
    }
    frag_color = vec4(total / max(totalWeight, 0.0001), centerGI.a);
}
