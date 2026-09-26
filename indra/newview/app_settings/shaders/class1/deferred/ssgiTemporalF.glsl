// Stabilize incoming light, including repaired receivers, before material response.
layout(location = 0) out vec4 frag_color; // RGB incoming light, A linear view depth
layout(location = 1) out vec4 frag_guide; // view normal, signed history age (avatar < 0)
uniform sampler2D ssgiIndirect;
uniform sampler2D ssgiHistory;
uniform sampler2D ssgiHistoryGuide;
uniform sampler2D ssgiGeometry;
uniform sampler2D taa_motion;
uniform sampler2D depthMap;
uniform vec2 screen_res;
uniform vec2 ssgi_jitter_delta;
uniform mat4 ssgi_previous_to_current;
uniform float ssgi_radius;
uniform int ssgi_history_valid;
vec4 getPositionWithDepth(vec2 tc, float depth);
vec4 getNorm(vec2 tc);
vec4 getNormRaw(vec2 tc);
vec4 decodeNormal(vec4 norm);

void main()
{
    ivec2 pixel = ivec2(gl_FragCoord.xy);
    vec2 tc = (vec2(pixel) + 0.5) / screen_res;
    float depth = texelFetch(depthMap, pixel, 0).r;
    frag_color = vec4(0.0);
    frag_guide = vec4(0.0);
    if (depth <= 0.0 || depth >= 1.0) return;
    vec3 position = getPositionWithDepth(tc, depth).xyz;
    vec3 normal = normalize(getNorm(tc).xyz);
    vec3 surfaceNormal = normalize(decodeNormal(texelFetch(ssgiGeometry, pixel, 0)).xyz);
    bool avatar = GBUFFER_AVATAR_FLAG(getNormRaw(tc).w) > 0.5;
    vec4 center = texelFetch(ssgiIndirect, pixel, 0);
    vec3 total = vec3(0.0), square = vec3(0.0);
    vec3 lo = center.rgb, hi = center.rgb;
    float totalWeight = 0.0;
    float tolerance = max(ssgi_radius * 0.04, abs(position.z) * 0.002);
    for (int y = -1; y <= 1; ++y)
    for (int x = -1; x <= 1; ++x)
    {
        ivec2 q = pixel + ivec2(x, y);
        if (any(lessThan(q, ivec2(0))) || any(greaterThanEqual(q, ivec2(screen_res)))) continue;
        float d = texelFetch(depthMap, q, 0).r;
        if (d <= 0.0 || d >= 1.0) continue;
        vec2 uv = (vec2(q) + 0.5) / screen_res;
        vec3 n = normalize(getNorm(uv).xyz);
        vec3 delta = getPositionWithDepth(uv, d).xyz - position;
        float plane = max(abs(dot(delta, normal)), abs(dot(delta, n)));
        float edge = exp2(-plane * plane / (tolerance * tolerance)) * pow(max(dot(n, normal), 0.0), 8.0);
        if (edge < 0.1) continue;
        vec3 light = texelFetch(ssgiIndirect, q, 0).rgb;
        float weight = edge * float((x == 0 ? 2 : 1) * (y == 0 ? 2 : 1));
        total += light * weight;
        square += light * light * weight;
        totalWeight += weight;
        lo = min(lo, light); hi = max(hi, light);
    }
    vec3 mean = total / max(totalWeight, 0.0001);
    vec3 sigma = sqrt(max(square / max(totalWeight, 0.0001) - mean * mean, vec3(0.0)));
    // Ordinary pixels already passed through the half-resolution spatial filter.
    // Only the repair fraction needs this additional full-resolution filtering.
    vec3 current = mix(center.rgb, mean, center.a);
    vec4 motion = texelFetch(taa_motion, pixel, 0);
    vec2 historyTC = tc + motion.rg + ssgi_jitter_delta;
    float age = 1.0;
    if (ssgi_history_valid != 0 && motion.a < 0.5 && motion.b > 0.0 &&
        all(greaterThanEqual(historyTC, vec2(0.0))) && all(lessThan(historyTC, vec2(1.0))))
    {
        vec2 p = historyTC * screen_res - 0.5;
        ivec2 base = ivec2(floor(p));
        vec2 f = fract(p);
        vec3 history = vec3(0.0);
        float support = 0.0, oldAge = 0.0;
        // Validate every tap before interpolation: silhouettes cannot borrow
        // another surface's light through a bilinear history fetch.
        // Compare on the previous surface plane. Neighbouring texels on a
        // grazing wall legitimately have different view depths as jitter moves.
        // The base projection is unchanged while history is valid; removing
        // the jitter delta reconstructs rays in the previous projection.
        vec3 expectedRay = getPositionWithDepth(historyTC - ssgi_jitter_delta, 0.5).xyz;
        vec3 expected = expectedRay * (motion.b / -expectedRay.z);
        float depthTolerance = max(0.01, motion.b * 0.005);
        for (int y = 0; y < 2; ++y)
        for (int x = 0; x < 2; ++x)
        {
            ivec2 q = base + ivec2(x, y);
            if (any(lessThan(q, ivec2(0))) || any(greaterThanEqual(q, ivec2(screen_res)))) continue;
            vec4 old = texelFetch(ssgiHistory, q, 0);
            vec4 guide = texelFetch(ssgiHistoryGuide, q, 0);
            if (abs(guide.a) < 0.5 || (guide.a < 0.0) != avatar || old.a <= 0.0) continue;
            vec3 oldRay = getPositionWithDepth((vec2(q) + 0.5) / screen_res - ssgi_jitter_delta, 0.5).xyz;
            vec3 oldPosition = oldRay * (old.a / -oldRay.z);
            if (abs(dot(oldPosition - expected, guide.xyz)) > depthTolerance) continue;
            vec3 oldNormal = normalize(mat3(ssgi_previous_to_current) * guide.xyz);
            if (dot(oldNormal, surfaceNormal) < 0.85) continue;
            float weight = (x == 0 ? 1.0 - f.x : f.x) * (y == 0 ? 1.0 - f.y : f.y);
            history += old.rgb * weight;
            oldAge += abs(guide.a) * weight;
            support += weight;
        }
        if (support > 0.001)
        {
            history /= support;
            age = min(oldAge / support + 1.0, 16.0);
            // Motion vectors follow surfaces, not changes in their lighting.
            // Restrict history to current local illumination to prevent trails
            // when a donor or blocker moves, or a light switches off.
            // Spatially smoothed neighbours underestimate Monte Carlo variance.
            // Keep a relative noise allowance instead of clipping history back
            // to each frame's nearly uniform but fluctuating light estimate.
            sigma = max(sigma, mean * 0.25);
            vec3 lower = max(vec3(0.0), min(lo, mean - 2.0 * sigma));
            vec3 upper = max(hi, mean + 2.0 * sigma);
            vec3 clipped = clamp(history, lower, upper);
            float weight = min(1.0 - 1.0 / age, 0.92) * support;
            current = mix(current, clipped, weight);
        }
    }
    frag_color = vec4(max(current, vec3(0.0)), min(-position.z, 65000.0));
    frag_guide = vec4(surfaceNormal, avatar ? -age : age);
}
