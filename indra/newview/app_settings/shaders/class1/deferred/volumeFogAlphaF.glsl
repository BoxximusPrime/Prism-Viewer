// Blended surfaces integrate density only up to their own position. Reuse the
// resolved fog's average illumination instead of marching lights per layer.
uniform int vf_alpha_enabled;
uniform int vf_alpha_scatter;
uniform sampler2D volumeFogMap;
uniform float vf_far;
uniform float vf_intensity;
uniform int vf_count;
uniform vec4 vf_axis_x[8];
uniform vec4 vf_axis_y[8];
uniform vec4 vf_axis_z[8];
uniform vec4 vf_half_density[8];
uniform vec4 vf_color_softness[8];
uniform float vf_ground_density;
uniform vec4 vf_ground_layer;
uniform vec2 vf_ground_fade;
uniform vec3 vf_ground_camera;
uniform mat4 vf_ground_inverse_view;
uniform vec2 vf_ground_noise;
uniform int vf_ground_environment;
uniform float vf_environment_distance_multiplier;
uniform vec3 blue_density;
uniform float haze_density;
uniform float density_multiplier;
uniform float max_y;

float groundProfile(vec3 world_ray, float start, float end);
float groundDensity(vec3 world_ray, float start, float end);
bool fogInterval(vec3 origin, vec3 direction, vec3 half_size, float limit, out float entry, out float leave);

float volumeFogAlphaTransmission(vec3 position)
{
    if (vf_alpha_enabled == 0) return 1.0;
    float distance = length(position);
    if (distance < 0.00001) return 1.0;
    vec3 ray = position / distance;
    float limit = min(distance, vf_far);
    float optical_depth = 0.0;
    if (vf_ground_density > 0.0)
    {
        vec3 world_ray = mat3(vf_ground_inverse_view) * ray;
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
            float smooth_path = vf_ground_density * groundProfile(world_ray, entry, leave) * (leave-entry);
            float path = smooth_path;
            if (vf_ground_noise.x > 0.0)
            {
                // Density samples only: no extra projector/shadow lookups.
                path = 0.0;
                int steps = clamp(int(ceil((leave-entry)/vf_ground_noise.y)), 1, 4);
                float step_length = (leave-entry) / float(steps);
                for (int i = 0; i < steps; ++i)
                {
                    float start = entry + float(i)*step_length;
                    path += groundDensity(world_ray, start, start+step_length) * step_length;
                }
            }
            if (vf_ground_environment != 0)
            {
                // Match the original environment extinction, including its
                // path-height cap, while surface distance haze stays bypassed.
                vec3 env_path = ray * smooth_path;
                if (abs(env_path.y) > max_y) env_path *= max_y / env_path.y;
                float tau = max(blue_density.r + haze_density, 1e-6) * density_multiplier *
                    vf_environment_distance_multiplier * length(env_path);
                path *= tau / max(smooth_path, 0.00001);
            }
            optical_depth += max(path, 0.0);
        }
    }
    for (int i = 0; i < vf_count; ++i)
    {
        vec3 origin = vec3(vf_axis_x[i].w, vf_axis_y[i].w, vf_axis_z[i].w);
        vec3 direction = vec3(dot(vf_axis_x[i].xyz, ray), dot(vf_axis_y[i].xyz, ray), dot(vf_axis_z[i].xyz, ray));
        float entry, leave;
        if (!fogInterval(origin, direction, vf_half_density[i].xyz, limit, entry, leave)) continue;
        float path = leave-entry;
        float softness = vf_color_softness[i].w;
        if (softness > 0.0)
        {
            float step_length = path / 16.0;
            path = 0.0;
            for (int j = 0; j < 16; ++j)
            {
                float t = entry + (float(j)+0.5)*step_length;
                vec3 edge = vf_half_density[i].xyz - abs(origin + direction*t);
                path += smoothstep(0.0, softness, min(edge.x, min(edge.y, edge.z))) * step_length;
            }
        }
        optical_depth += max(vf_half_density[i].w * vf_intensity * path, 0.0);
    }
    return exp(-optical_depth);
}

vec4 applyVolumeFogAlpha(vec3 position, vec4 color)
{
    if (vf_alpha_enabled == 0) return color;
    float transmission = volumeFogAlphaTransmission(position);
    if (transmission >= 1.0) return color;
    ivec2 size = textureSize(volumeFogMap, 0);
    vec4 fog = texelFetch(volumeFogMap, clamp(ivec2(gl_FragCoord.xy), ivec2(0), size-1), 0);
    float background_opacity = max(1.0-fog.a, 0.0);
    // Density quadrature may differ slightly from the opaque pass. A visible
    // layer cannot have more fog in front of it than the background behind it.
    float opacity = min(1.0-transmission, background_opacity);
    color.rgb *= 1.0-opacity;
    if (vf_alpha_scatter != 0)
        color.rgb += fog.rgb*(opacity/max(background_opacity, 0.00001));
    // Keep material coverage intact for sorted alpha and exact OIT blending.
    return color;
}
