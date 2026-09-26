// Reconstruct physical surface orientation once for GI hit/history validation.
// Normal maps describe shading, not the planes intersected by screen-space rays.
out vec2 frag_color;
uniform sampler2D depthMap;
uniform vec2 screen_res;
vec4 getPositionWithDepth(vec2 tc, float depth);
vec4 getNorm(vec2 tc);
vec4 encodeNormal(vec3 n, float env, float gbuffer_flag);

vec3 ssgiSurfaceNormal(vec2 tc, vec3 center)
{
    vec2 dx = vec2(1.0 / screen_res.x, 0.0), dy = vec2(0.0, 1.0 / screen_res.y);
    vec2 lo = 0.5 / screen_res, hi = 1.0 - lo;
    vec2 l = clamp(tc - dx, lo, hi), r = clamp(tc + dx, lo, hi);
    vec2 d = clamp(tc - dy, lo, hi), u = clamp(tc + dy, lo, hi);
    vec3 left = getPositionWithDepth(l, texture(depthMap, l).r).xyz;
    vec3 right = getPositionWithDepth(r, texture(depthMap, r).r).xyz;
    vec3 down = getPositionWithDepth(d, texture(depthMap, d).r).xyz;
    vec3 up = getPositionWithDepth(u, texture(depthMap, u).r).xyz;
    vec3 x = tc.x <= lo.x || (tc.x < hi.x && abs(right.z - center.z) < abs(center.z - left.z)) ? right - center : center - left;
    vec3 y = tc.y <= lo.y || (tc.y < hi.y && abs(up.z - center.z) < abs(center.z - down.z)) ? up - center : center - down;
    vec3 normal = cross(x, y);
    return dot(normal, normal) > 1e-16 ? normalize(normal) : normalize(getNorm(tc).xyz);
}

void main()
{
    vec2 tc = gl_FragCoord.xy / screen_res;
    float depth = texture(depthMap, tc).r;
    frag_color = vec2(0.5);
    if (depth <= 0.0 || depth >= 1.0) return;
    vec3 center = getPositionWithDepth(tc, depth).xyz;
    frag_color = encodeNormal(ssgiSurfaceNormal(tc, center), 0.0, 0.0).xy;
}
