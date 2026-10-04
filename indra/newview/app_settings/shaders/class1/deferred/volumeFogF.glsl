// Participating media in up to eight oriented boxes. Output scene-linear
// in-scattering and transmittance, independent of the scene color/resolution.
out vec4 frag_color;
uniform sampler2D depthMap;
uniform mat4 inv_proj;
uniform vec2 vf_target_size;
uniform int vf_reconstruct;
bool reconstructVolumeFog(ivec2 pixel, out vec4 fog);
uniform float vf_intensity;
uniform int vf_count;
uniform float vf_far;
// Local height fog, integrated together with boxes so overlaps scatter once.
uniform float vf_ground_density;
uniform vec4 vf_ground_layer; // base altitude, falloff height, water, distance
uniform vec2 vf_ground_fade; // clear distance from camera, fade-in length
uniform vec3 vf_ground_camera; // wrapped global noise xy, global altitude
uniform mat4 vf_ground_inverse_view;
uniform vec2 vf_ground_noise; // amount, size in metres
uniform vec3 vf_ground_color;
uniform int vf_ground_environment;
uniform vec3 vf_environment_light_direction;
uniform float sky_hdr_scale;
void calcAtmosphericVarsWithAmbient(vec3 position, vec3 light_dir, float ambFactor,
    out vec3 sunlit, out vec3 amblit, out vec3 additive, out vec3 atten, out vec3 ambient_additive);
vec3 srgb_to_linear(vec3 color);
const int VF_MAX = 8;
#ifdef VF_LIGHTING
const int VF_MAX_EVENTS = 34; // two per box/light plus the ground layer
uniform int vf_light_count;
uniform int vf_steps;
uniform int vf_min_steps;
uniform int vf_shadow_mask;
vec2 fogLightInterval(int index, vec3 ray, float limit);
vec3 fogDirectional(vec3 ray);
uniform float vf_light_strength;
vec3 fogLighting(vec3 position, vec3 ray, int light_mask, vec3 directional,
    out float sun_visibility, out vec3 local_light);
#else
const int VF_MAX_EVENTS = 18;
#endif
// Unit local axes in view space; w is the camera's coordinate on that axis.
uniform vec4 vf_axis_x[VF_MAX];
uniform vec4 vf_axis_y[VF_MAX];
uniform vec4 vf_axis_z[VF_MAX];
uniform vec4 vf_half_density[VF_MAX];
uniform vec4 vf_color_softness[VF_MAX];

float groundProfile(vec3 world_ray, float start, float end);
float groundDensity(vec3 world_ray, float start, float end);
bool fogInterval(vec3 origin, vec3 direction, vec3 half_size, float limit, out float entry, out float leave);

void main()
{
    ivec2 source_size = textureSize(depthMap, 0);
    ivec2 pixel = min(ivec2(gl_FragCoord.xy * vec2(source_size) / vf_target_size), source_size - 1);
    if (vf_reconstruct != 0)
    {
        vec4 fog;
        if (reconstructVolumeFog(pixel, fog))
        {
            frag_color = fog;
            return;
        }
        // Reintegrate only unsupported pixels at their own depth. Returning
        // clear fog here made thin leaves and sky gaps sparkle as they moved.
    }
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
    vec2 ground_interval = vec2(-1.0);
    vec3 world_ray = mat3(vf_ground_inverse_view) * ray;
    float ground_density_scale = 1.0;
    vec3 ground_ambient = vec3(0.0), ground_direct = vec3(0.0);
    if (vf_ground_density > 0.0)
    {
        float bottom = vf_ground_layer.z;
        float top = vf_ground_layer.x + 6.0 * vf_ground_layer.y;
        float entry = vf_ground_fade.x, leave = min(limit, vf_ground_layer.w);
        if (abs(world_ray.z) < 1e-7)
        {
            if (vf_ground_camera.z < bottom || vf_ground_camera.z > top) leave = -1.0;
        }
        else
        {
            float a = (bottom-vf_ground_camera.z)/world_ray.z;
            float b = (top-vf_ground_camera.z)/world_ray.z;
            entry = max(entry, min(a,b));
            leave = min(leave, max(a,b));
        }
        if (top > bottom && leave > entry)
        {
            if (vf_ground_environment != 0)
            {
                // Match the original haze at this ray's smooth height-weighted
                // path. Compute its nonlinear color conversion once per ray,
                // then distribute that scattering through the lit volume.
                float path = vf_ground_density * groundProfile(world_ray, entry, leave) * (leave-entry);
                vec3 sunlit, amblit, additive, atten, ambient_additive;
                calcAtmosphericVarsWithAmbient(ray * max(path, 0.0001), vf_environment_light_direction, 1.0,
                    sunlit, amblit, additive, atten, ambient_additive);
                float opacity = 1.0-atten.r;
                ground_density_scale = path > 0.0 ? -log(max(atten.r, 1e-30))/path : 0.0;
                if (opacity > 1e-7)
                {
                    ground_ambient = srgb_to_linear(max(ambient_additive*2.0, vec3(0.0))) * sky_hdr_scale / opacity;
                    ground_direct = max(srgb_to_linear(max(additive*2.0, vec3(0.0))) * sky_hdr_scale / opacity - ground_ambient, vec3(0.0));
                }
            }
            if (ground_density_scale > 0.0)
            {
                ground_interval = vec2(entry, leave);
                events[event_count++] = entry;
                events[event_count++] = leave;
                first_fog = entry;
                last_fog = leave;
            }
        }
    }
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
        if (middle > ground_interval.x && middle < ground_interval.y)
        {
            occupied_length += events[segment] - events[segment - 1];
            continue;
        }
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
        bool ground = middle > ground_interval.x && middle < ground_interval.y;
        bool occupied = ground;
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
            ((vf_shadow_mask & 15) != 0 && (any(greaterThan(directional, vec3(0.0))) ||
                (ground && any(greaterThan(ground_direct, vec3(0.0))))));
        vec3 constant_light = vec3(1.0);
        float constant_sun_visibility = 1.0;
        vec3 constant_local = vec3(0.0);
        if (!varying_light) constant_light = fogLighting(ray * middle, ray, 0, directional, constant_sun_visibility, constant_local);
        steps = max(soft || light_mask != 0 ? vf_min_steps : 2,
            int(ceil(float(vf_steps) * (end - start) / max(occupied_length, 0.00001))));
        if (!varying_light && !soft) steps = 1;
#endif
        // Height extinction is analytic; samples resolve noise and lighting.
        if (ground)
        {
            if (vf_ground_noise.x > 0.0)
                steps = max(steps, min(64, max(8, int(ceil((end-start)*2.0/vf_ground_noise.y)))));
        }
        float step_length = (end - start) / float(steps);
        for (int step = 0; step < steps; ++step)
        {
            float t = start + (float(step) + 0.5) * step_length;
            float extinction = uniform_extinction;
            vec3 emission = uniform_emission;
            float ground_extinction = 0.0;
            if (ground)
            {
                float density = groundDensity(world_ray, t-step_length*0.5, t+step_length*0.5) * ground_density_scale;
                extinction += density;
                ground_extinction = density;
            }
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
                vec3 ground_illumination = ground_ambient + ground_direct;
#ifdef VF_LIGHTING
                float sun_visibility = constant_sun_visibility;
                vec3 local_light = constant_local;
                illumination = varying_light ? fogLighting(ray * t, ray, light_mask, directional, sun_visibility, local_light) : constant_light;
                ground_illumination = ground_ambient + ground_direct * sun_visibility * vf_light_strength + local_light;
#endif
                vec3 source = emission * illumination;
                source += ground_extinction * vf_ground_color * (vf_ground_environment != 0 ? ground_illumination : illumination);
                scattered += transmittance * (1.0 - transmission) * (source / extinction);
                transmittance *= transmission;
            }
            if (transmittance < 0.00001) break;
        }
        if (transmittance < 0.00001) break;
    }
    frag_color = vec4(clamp(scattered, vec3(0.0), vec3(65000.0)), transmittance);
}
