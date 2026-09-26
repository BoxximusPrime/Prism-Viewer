// Cosine-weighted one-bounce diffuse transport, evaluated for every receiver.
// Static stratified samples also work without TAA. A miss adds no local light;
// the renderer's existing probe illumination remains the ambient baseline.
uniform sampler2D depthMap;
uniform sampler2D ssgiSource;
uniform sampler2D ssgiGeometry;
vec4 decodeNormal(vec4 norm);
uniform vec2 screen_res;
uniform mat4 projection_matrix;
uniform float ssgi_radius;
uniform int ssgi_quality;
vec4 getPositionWithDepth(vec2 tc, float depth);
vec4 getNorm(vec2 tc);

bool projectSSGI(vec3 position, out vec2 tc)
{
    vec4 clip = projection_matrix * vec4(position, 1.0);
    if (clip.w <= 0.0 || clip.z <= -clip.w || clip.z >= clip.w) return false;
    tc = clip.xy / clip.w * 0.5 + 0.5;
    return all(greaterThanEqual(tc, vec2(0.0))) && all(lessThan(tc, vec2(1.0)));
}

vec2 ssgiFullPixel(vec2 tc)
{
    return (floor(tc * screen_res) + 0.5) / screen_res;
}

vec3 ssgiSurfaceNormal(vec2 tc)
{
    return normalize(decodeNormal(texture(ssgiGeometry, tc)).xyz);
}

vec3 traceSSGIRay(vec3 origin, vec3 direction, float bias, int steps)
{
    float previous = bias;
    for (int step = 1; step <= steps; ++step)
    {
        float fraction = float(step) / float(steps);
        float distance = mix(bias, ssgi_radius, fraction * fraction);
        vec2 tc;
        if (!projectSSGI(origin + direction * distance, tc)) break;
        tc = ssgiFullPixel(tc);
        float depth = texture(depthMap, tc).r;
        if (depth > 0.0 && depth < 1.0)
        {
            vec3 surface = getPositionWithDepth(tc, depth).xyz;
            vec3 normal = ssgiSurfaceNormal(tc);
            float facing = dot(normal, direction);
            // Intersect the sampled surface plane within this ray interval.
            // A foreground surface metres ahead of the ray is not an infinite
            // blocker. Geometry, including a black donor, determines the hit.
            if (abs(facing) > 0.001)
            {
                float hitDistance = dot(surface - origin, normal) / facing;
                if (hitDistance >= previous && hitDistance <= distance)
                {
                    vec3 hit = origin + direction * hitDistance;
                    vec2 hitTC;
                    if (projectSSGI(hit, hitTC))
                    {
                        hitTC = ssgiFullPixel(hitTC);
                        float hitDepth = texture(depthMap, hitTC).r;
                        vec3 actual = getPositionWithDepth(hitTC, hitDepth).xyz;
                        vec3 hitNormal = ssgiSurfaceNormal(hitTC);
                        vec3 adjacent = getPositionWithDepth(hitTC + vec2(1.0 / screen_res.x, 0.0), hitDepth).xyz;
                        // Validate both local planes, rather than raw Z: a
                        // pixel on a grazing wall spans a large depth interval.
                        // The finite normal-space thickness still rejects an
                        // unrelated foreground surface at the projected hit.
                        float thickness = clamp(length(adjacent - actual) * 2.0, 0.01, 0.1);
                        vec3 separation = actual - hit;
                        float planeError = max(abs(dot(separation, normal)), abs(dot(separation, hitNormal)));
                        if (hitDepth > 0.0 && hitDepth < 1.0 &&
                            planeError <= thickness)
                        {
                            // Opaque backfaces block the ray but do not emit
                            // the camera-facing side's diffuse radiance.
                            if (dot(hitNormal, direction) >= -0.001) return vec3(0.0);
                            vec3 radiance = max(texture(ssgiSource, hitTC).rgb, vec3(0.0));
                            // Limit extreme emissive fireflies without changing hue.
                            float peak = max(radiance.r, max(radiance.g, radiance.b));
                            radiance *= min(1.0, 16.0 / max(peak, 0.0001));
                            return radiance * (1.0 - smoothstep(ssgi_radius * 0.8, ssgi_radius, hitDistance));
                        }
                    }
                }
            }
        }
        previous = distance;
    }
    return vec3(0.0);
}

vec4 traceSSGI(vec2 tc)
{
    float depth = texture(depthMap, tc).r;
    vec3 normal = getNorm(tc).xyz;
    if (depth <= 0.0 || depth >= 1.0 || length(normal) < 0.5)
    {
        return vec4(0.0);
    }
    normal = normalize(normal);
    vec3 center = getPositionWithDepth(tc, depth).xyz;
    vec3 adjacent = getPositionWithDepth(tc + vec2(1.0 / screen_res.x, 0.0), depth).xyz;
    float bias = clamp(length(adjacent - center) * 0.05, 0.0005, 0.005);
    vec3 origin = center + normal * bias;
    vec3 tangent = normalize(cross(abs(normal.z) < 0.999 ? vec3(0, 0, 1) : vec3(0, 1, 0), normal));
    vec3 bitangent = cross(normal, tangent);
    vec2 pixel = floor(tc * screen_res);
    vec2 noise = fract(52.9829189 * fract(vec2(dot(pixel, vec2(0.06711056, 0.00583715)),
                                               dot(pixel, vec2(0.156735, 0.387449)))));
    int rays = ssgi_quality == 0 ? 4 : ssgi_quality == 1 ? 8 : 16;
    int steps = ssgi_quality == 0 ? 16 : ssgi_quality == 1 ? 24 : 32;
    vec3 gathered = vec3(0.0);
    for (int ray = 0; ray < rays; ++ray)
    {
        float u = (float(ray) + noise.x) / float(rays);
        float phi = 6.28318530718 * fract(float(ray) * 0.61803398875 + noise.y);
        vec3 direction = tangent * (sqrt(u) * cos(phi)) + bitangent * (sqrt(u) * sin(phi)) + normal * sqrt(1.0 - u);
        gathered += traceSSGIRay(origin, direction, bias, steps);
    }
    // For p(omega) = cos(theta)/pi the Lambertian cos(theta)/pi cancels
    // exactly. Do not multiply by donor-facing or receiver-facing again.
    return vec4(gathered / float(rays), 1.0);
}
