// Participating media in up to eight oriented boxes. Output scene-linear
// in-scattering and transmittance, independent of the scene color/resolution.
out vec4 frag_color;
uniform sampler2D depthMap;
uniform mat4 inv_proj;
uniform vec2 vf_target_size;
uniform float vf_intensity;
uniform int vf_count;
uniform float vf_far;
const int VF_MAX = 8;
#ifdef VF_LIGHTING
const int VF_MAX_EVENTS = 32; // two boundaries per box and per local light
uniform int vf_light_count;
uniform int vf_steps;
uniform int vf_min_steps;
uniform int vf_shadow_mask;
vec2 fogLightInterval(int index, vec3 ray, float limit);
vec3 fogDirectional(vec3 ray);
vec3 fogLighting(vec3 position, vec3 ray, int light_mask, vec3 directional);
#else
const int VF_MAX_EVENTS = 16;
#endif
// Unit local axes in view space; w is the camera's coordinate on that axis.
uniform vec4 vf_axis_x[VF_MAX];
uniform vec4 vf_axis_y[VF_MAX];
uniform vec4 vf_axis_z[VF_MAX];
uniform vec4 vf_half_density[VF_MAX];
uniform vec4 vf_color_softness[VF_MAX];

bool fogInterval(vec3 origin, vec3 direction, vec3 half_size, float limit,
                 out float entry, out float leave)
{
    entry = 0.0;
    leave = limit;
    for (int axis = 0; axis < 3; ++axis)
    {
        if (abs(direction[axis]) < 1e-7)
        {
            if (abs(origin[axis]) > half_size[axis]) return false;
        }
        else
        {
            float a = (-half_size[axis] - origin[axis]) / direction[axis];
            float b = ( half_size[axis] - origin[axis]) / direction[axis];
            entry = max(entry, min(a, b));
            leave = min(leave, max(a, b));
        }
    }
    return leave > entry;
}

void main()
{
    ivec2 source_size = textureSize(depthMap, 0);
    ivec2 pixel = min(ivec2(gl_FragCoord.xy * vec2(source_size) / vf_target_size), source_size - 1);
    vec2 uv = (vec2(pixel) + 0.5) / vec2(source_size);
    float depth = texelFetch(depthMap, pixel, 0).r;
    vec4 endpoint = inv_proj * vec4(uv * 2.0 - 1.0, depth * 2.0 - 1.0, 1.0);
    // Use a finite point on the ray even for a far plane at infinity.
    vec4 ray_point = inv_proj * vec4(uv * 2.0 - 1.0, 0.0, 1.0);
    vec3 ray = normalize(ray_point.xyz / ray_point.w);
    float limit = vf_far;
    if (depth < 1.0 && abs(endpoint.w) > 1e-8)
        limit = min(limit, length(endpoint.xyz / endpoint.w));

    vec3 directions[VF_MAX];
    vec2 intervals[VF_MAX];
    float events[VF_MAX_EVENTS];
    int event_count = 0;
    float first_fog = limit, last_fog = 0.0;
    for (int i = 0; i < vf_count; ++i)
    {
        vec3 origin = vec3(vf_axis_x[i].w, vf_axis_y[i].w, vf_axis_z[i].w);
        directions[i] = vec3(dot(vf_axis_x[i].xyz, ray), dot(vf_axis_y[i].xyz, ray), dot(vf_axis_z[i].xyz, ray));
        float entry, leave;
        intervals[i] = vec2(-1.0);
        if (vf_half_density[i].w * vf_intensity > 0.0 &&
            fogInterval(origin, directions[i], vf_half_density[i].xyz, limit, entry, leave))
        {
            intervals[i] = vec2(entry, leave);
            events[event_count++] = entry;
            events[event_count++] = leave;
            first_fog = min(first_fog, entry);
            last_fog = max(last_fog, leave);
        }
    }
    // Most pixels outside a small box need no light intersections or sorting.
    if (event_count == 0)
    {
        frag_color = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }
#ifdef VF_LIGHTING
    vec3 directional = fogDirectional(ray);
    vec2 light_intervals[8];
    // Splitting at light spheres and projector frusta avoids skipping a narrow
    // beam when the enclosing fog box is much larger than the light.
    for (int i = 0; i < vf_light_count; ++i)
    {
        vec2 interval = fogLightInterval(i, ray, last_fog);
        interval.x = max(interval.x, first_fog);
        light_intervals[i] = interval;
        if (interval.y > interval.x)
        {
            events[event_count++] = interval.x;
            events[event_count++] = interval.y;
        }
    }
#endif
    // Split at every boundary so thin boxes and disjoint boxes are never
    // skipped by a fixed-step march across the full camera distance.
    for (int i = 1; i < event_count; ++i)
    {
        float value = events[i];
        int j = i - 1;
        while (j >= 0)
        {
            if (events[j] <= value) break;
            events[j + 1] = events[j];
            --j;
        }
        events[j + 1] = value;
    }

#ifdef VF_LIGHTING
    float occupied_length = 0.0;
    for (int segment = 1; segment < event_count; ++segment)
    {
        float middle = (events[segment - 1] + events[segment]) * 0.5;
        for (int i = 0; i < vf_count; ++i)
        {
            if (middle > intervals[i].x && middle < intervals[i].y)
            {
                occupied_length += events[segment] - events[segment - 1];
                break;
            }
        }
    }
#endif
    float transmittance = 1.0;
    vec3 scattered = vec3(0.0);
    for (int segment = 1; segment < event_count; ++segment)
    {
        float start = events[segment - 1], end = events[segment];
        if (end <= start) continue;
        float middle = (start + end) * 0.5;
        int soft_mask = 0;
        bool occupied = false;
        float uniform_extinction = 0.0;
        vec3 uniform_emission = vec3(0.0);
        for (int i = 0; i < vf_count; ++i)
        {
            bool active = middle > intervals[i].x && middle < intervals[i].y;
            occupied = occupied || active;
            if (active && vf_color_softness[i].w > 0.0) soft_mask |= 1 << i;
            if (active && vf_color_softness[i].w <= 0.0)
            {
                float density = vf_half_density[i].w * vf_intensity;
                uniform_extinction += density;
                uniform_emission += vf_color_softness[i].rgb * density;
            }
        }
        if (!occupied) continue;
        bool soft = soft_mask != 0;
        // Uniform segments are integrated exactly. Soft boundaries use bounded
        // quadrature in that segment only; no temporal noise/history is needed.
        int steps = soft ? 16 : 1;
#ifdef VF_LIGHTING
        int light_mask = 0;
        for (int i = 0; i < vf_light_count; ++i)
            if (middle > light_intervals[i].x && middle < light_intervals[i].y) light_mask |= 1 << i;
        bool varying_light = light_mask != 0 ||
            ((vf_shadow_mask & 15) != 0 && any(greaterThan(directional, vec3(0.0))));
        vec3 constant_light = vec3(1.0);
        if (!varying_light) constant_light = fogLighting(ray * middle, ray, 0, directional);
        steps = max(soft || light_mask != 0 ? vf_min_steps : 2,
            int(ceil(float(vf_steps) * (end - start) / max(occupied_length, 0.00001))));
        if (!varying_light && !soft) steps = 1;
#endif
        float step_length = (end - start) / float(steps);
        for (int step = 0; step < steps; ++step)
        {
            float t = start + (float(step) + 0.5) * step_length;
            float extinction = uniform_extinction;
            vec3 emission = uniform_emission;
            if (soft) for (int i = 0; i < vf_count; ++i)
            {
                if ((soft_mask & (1 << i)) == 0) continue;
                float weight = 1.0;
                float softness = vf_color_softness[i].w;
                if (softness > 0.0)
                {
                    vec3 origin = vec3(vf_axis_x[i].w, vf_axis_y[i].w, vf_axis_z[i].w);
                    vec3 edge = vf_half_density[i].xyz - abs(origin + directions[i] * t);
                    float distance_to_edge = min(edge.x, min(edge.y, edge.z));
                    weight = smoothstep(0.0, softness, distance_to_edge);
                }
                float density = vf_half_density[i].w * vf_intensity * weight;
                extinction += density;
                emission += vf_color_softness[i].rgb * density;
            }
            if (extinction > 0.0)
            {
                float transmission = exp(-extinction * step_length);
                vec3 illumination = vec3(1.0);
#ifdef VF_LIGHTING
                illumination = varying_light ? fogLighting(ray * t, ray, light_mask, directional) : constant_light;
#endif
                scattered += transmittance * (1.0 - transmission) * (emission / extinction) * illumination;
                transmittance *= transmission;
            }
            if (transmittance < 0.00001) break;
        }
        if (transmittance < 0.00001) break;
    }
    frag_color = vec4(clamp(scattered, vec3(0.0), vec3(65000.0)), transmittance);
}
