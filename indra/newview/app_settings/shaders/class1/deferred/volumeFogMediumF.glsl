// Shared density and intersection calculations for opaque and blended fog.
uniform float vf_ground_density;
uniform vec4 vf_ground_layer;
uniform vec2 vf_ground_fade;
uniform vec3 vf_ground_camera;
uniform vec2 vf_ground_noise;

float groundHash(vec3 p)
{
    // Wrap lattice coordinates before hashing, including the neighbouring cell.
    p = mod(p, 128.0);
    p = fract(p * vec3(0.1031, 0.1030, 0.0973));
    p += dot(p, p.yxz + 33.33);
    return fract((p.x + p.y) * p.z);
}

float groundNoise(vec3 p)
{
    vec3 cell = floor(p), f = fract(p);
    f = f*f*(3.0-2.0*f);
    return mix(mix(mix(groundHash(cell), groundHash(cell+vec3(1,0,0)), f.x),
                   mix(groundHash(cell+vec3(0,1,0)), groundHash(cell+vec3(1,1,0)), f.x), f.y),
               mix(mix(groundHash(cell+vec3(0,0,1)), groundHash(cell+vec3(1,0,1)), f.x),
                   mix(groundHash(cell+vec3(0,1,1)), groundHash(cell+vec3(1,1,1)), f.x), f.y), f.z);
}

// Antiderivative of a capped exponential with a continuous zero at six
// falloff heights. Exact segment averages preserve thin layers at any pitch.
float groundIntegral(float height)
{
    if (height <= 0.0) return height;
    float h = vf_ground_layer.y;
    float x = min(height / h, 6.0);
    return h * (1.0-exp(-x)-x*exp(-6.0)) / (1.0-exp(-6.0));
}

float groundHeightProfile(vec3 world_ray, float start, float end)
{
    float a = vf_ground_camera.z - vf_ground_layer.x + world_ray.z * start;
    float b = vf_ground_camera.z - vf_ground_layer.x + world_ray.z * end;
    float mean_density;
    if (abs(b-a) < vf_ground_layer.y * 0.01)
        mean_density = clamp((exp(-max((a+b)*0.5, 0.0)/vf_ground_layer.y)-exp(-6.0)) / (1.0-exp(-6.0)), 0.0, 1.0);
    else
        mean_density = max((groundIntegral(b)-groundIntegral(a))/(b-a), 0.0);
    return mean_density;
}

float groundProfile(vec3 world_ray, float start, float end)
{
    float fade_end = vf_ground_fade.x + vf_ground_fade.y;
    if (vf_ground_fade.y <= 0.0 || start >= fade_end)
        return groundHeightProfile(world_ray, start, end);

    // Average smoothstep over the ramp instead of sampling its midpoint:
    // a long uniform segment must retain the fully dense path after the fade.
    // Height is averaged separately within the ramp and the remaining path.
    float ramp_end = min(end, fade_end);
    float a = clamp((start - vf_ground_fade.x) / vf_ground_fade.y, 0.0, 1.0);
    float b = clamp((ramp_end - vf_ground_fade.x) / vf_ground_fade.y, 0.0, 1.0);
    float ramp_mean = a*a + a*b + b*b - 0.5*(a+b)*(a*a+b*b);
    float path = groundHeightProfile(world_ray, start, ramp_end) * ramp_mean * (ramp_end-start);
    if (end > ramp_end)
        path += groundHeightProfile(world_ray, ramp_end, end) * (end-ramp_end);
    return path / max(end-start, 0.00001);
}

float groundDensity(vec3 world_ray, float start, float end)
{
    float patches = 1.0;
    if (vf_ground_noise.x > 0.0)
    {
        vec3 p = world_ray * ((start+end)*0.5) / vf_ground_noise.y;
        p += vec3(vf_ground_camera.xy, vf_ground_camera.z / vf_ground_noise.y);
        patches = mix(1.0, smoothstep(0.2, 0.8, groundNoise(p)) * 2.0, vf_ground_noise.x);
    }
    return vf_ground_density * groundProfile(world_ray, start, end) * patches;
}

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

