// One world-anchored EEP cloud layer. RGB is scene-linear in-scattering;
// alpha is transmittance, for the existing volume composite.
out vec4 frag_color;
uniform sampler2D depthMap;
uniform sampler3D diffuseMap; // deterministic, repeating scalar noise
uniform sampler2D cloud_noise_texture;
uniform sampler2D cloud_noise_texture_next;
uniform mat4 inv_proj;
uniform mat4 vc_view_to_world;
uniform vec2 vc_target_size;
uniform vec3 vc_camera; // XY wrapped in world space; Z relative to cloud base
uniform float vc_thickness;
uniform float vc_scale; // base shape scale; EEP weather banks span eight times this
uniform vec3 vc_density;
uniform vec3 vc_detail;
uniform vec2 vc_scroll;
uniform float vc_coverage;
uniform float vc_amount;
uniform float vc_variance;
uniform float vc_blend;
uniform int vc_steps;
uniform vec3 vc_sun_direction;
uniform vec3 vc_sun_color;
uniform vec3 vc_ambient;
uniform vec3 vc_tint;

float cloudNoise(vec3 p)
{
    vec3 f = fract(p);
    // Smooth interpolation between the random texels, independent of GL LOD.
    return textureLod(diffuseMap, (floor(p) + f*f*(3.0-2.0*f) + 0.5) / 64.0, 0.0).r;
}

float cloudWeather(sampler2D weather_map, vec2 uv, float frequency)
{
    // EEP supplies broad coverage. Extruding its finest texels through the
    // layer produces vertical streaks, especially under overhead sunlight.
    // Keep this mask coarser than the 3D billows that define the silhouette.
    // Keep detail in the 3D density instead. A fixed weather resolution also
    // keeps coverage stable as the camera moves or texture mips finish loading.
    ivec2 size = textureSize(weather_map, 0);
    float lod = max(log2(float(max(size.x, size.y))*frequency / 32.0), 0.0);
    return textureLod(weather_map, uv, lod).r;
}

float cloudWeather(vec2 uv, float frequency)
{
    return mix(cloudWeather(cloud_noise_texture, uv, frequency),
               cloudWeather(cloud_noise_texture_next, uv, frequency), vc_blend);
}

float cloudCoverage(vec2 uv)
{
    // Follow cloudsF.glsl's EEP threshold, detail and variance before adding
    // volume. In particular, a negative authored density must stay clear.
    vec2 fine_uv = uv*16.0;
    float variance = vc_variance*(1.0-vc_scale/24000.0); // cloud_scale = vc_scale/6000
    vec2 disturbance = vec2(0.0);
    float density_variance = 0.0;
    if (variance > 0.0)
    {
        disturbance = vec2(cloudWeather(uv/8.0, 0.125), cloudWeather((fine_uv+uv)/16.0, 17.0/16.0))*variance;
        vec2 disturbance2 = vec2(cloudWeather((uv+fine_uv)/4.0, 17.0/4.0), cloudWeather((fine_uv+uv)/8.0, 17.0/8.0))*variance;
        density_variance = min(1.0, (disturbance.x*2.0+disturbance.y*2.0+disturbance2.x+disturbance2.y)*4.0);
    }
    float bias = 2.0*(vc_coverage-0.25)*(1.0-density_variance*density_variance);
    float authored = cloudWeather(uv+vc_scroll+vc_density.xy+disturbance*0.2, 1.0)-0.5;
    // Filter the 16x detail at the same world footprint as the bank mask, so
    // its coverage contribution cannot reintroduce fine extruded columns.
    if (vc_detail.z != 0.0)
        authored += (cloudWeather(fine_uv+vc_detail.xy, 16.0)-0.5)*vc_detail.z;
    float coverage = clamp(max(authored+bias, 0.0)*10.0*vc_density.z, 0.0, 1.0);
    coverage = 1.0-coverage*coverage;
    coverage = 1.0-coverage*coverage;
    return clamp(coverage*vc_amount, 0.0, 1.0);
}

float cloudDensity(vec3 p, bool detail)
{
    float h = p.z / vc_thickness;
    if (h <= 0.0 || h >= 1.0) return 0.0;
    // Broad EEP banks and clear areas surround smaller, independently shaped
    // billows. Repeating the entire weather map at billow scale carpets the sky.
    vec2 uv = vec2(-p.x, p.y) / (vc_scale*8.0);
    float coverage = cloudCoverage(uv);
    if (coverage <= 0.0) return 0.0;
    vec3 q = vec3((uv+vc_scroll+vc_density.xy)*64.0, h*2.0);
    float shape = 0.65*cloudNoise(q) + 0.35*cloudNoise(q*2.0 + 19.0);
    float profile = smoothstep(0.0, 0.16, h)*(1.0-smoothstep(0.55, 1.0, h));
    // Grow rounded 3D bodies inside the weather mask. Taper their boundary
    // with height as well as fading density, so tops do not form a flat sheet.
    shape = pow(shape, 0.7) - (1.0-profile)*0.25;
    // Reach a dense core instead of leaving a broad, translucent fringe.
    float density = smoothstep(0.0, 0.25, shape - (1.0-coverage))*profile;
    if (detail && density > 0.0)
    {
        vec3 offset = vec3(vc_detail.xy*16.0, vc_variance*5.0);
        float erosion = 0.75*cloudNoise(q*4.0 + offset) + 0.25*cloudNoise(q*8.0 + offset);
        density = max(0.0, density - erosion*(0.18*vc_detail.z + 0.2*vc_variance));
    }
    return density * vc_density.z * 0.025;
}

bool cloudInterval(vec3 ray, float limit, out float entry, out float leave)
{
    entry = 0.0;
    leave = limit;
    if (abs(ray.z) < 1e-6)
        return vc_camera.z > 0.0 && vc_camera.z < vc_thickness;
    float a = -vc_camera.z / ray.z;
    float b = (vc_thickness-vc_camera.z) / ray.z;
    entry = max(0.0, min(a,b));
    leave = min(limit, max(a,b));
    return leave > entry;
}

void main()
{
    frag_color = vec4(0.0, 0.0, 0.0, 1.0);
    if (vc_amount <= 0.0 || vc_density.z <= 0.0 || vc_scale < 6.0) return;
    ivec2 size = textureSize(depthMap, 0);
    ivec2 pixel = min(ivec2(gl_FragCoord.xy*vec2(size)/vc_target_size), size-1);
    vec2 uv = (vec2(pixel)+0.5)/vec2(size);
    vec4 point = inv_proj*vec4(uv*2.0-1.0, 0.0, 1.0);
    vec3 ray = normalize((vc_view_to_world*vec4(point.xyz/point.w, 0.0)).xyz);
    float depth = texelFetch(depthMap, pixel, 0).r;
    // Sky extends beyond the viewer's object draw distance.
    float limit = 24000.0;
    if (depth < 1.0)
    {
        vec4 endpoint = inv_proj*vec4(uv*2.0-1.0, depth*2.0-1.0, 1.0);
        if (abs(endpoint.w) > 1e-8) limit = min(limit, length(endpoint.xyz/endpoint.w));
    }
    float entry, leave;
    if (!cloudInterval(ray, limit, entry, leave)) return;
    int steps = clamp(vc_steps, 16, 128);
    // ponytail: fixed jitter without cloud history; add temporal reconstruction
    // if low-sample noise is distracting during movement.
    float jitter = fract(52.9829189*fract(dot(vec2(pixel), vec2(0.06711056,0.00583715))));
    float mu = dot(ray, vc_sun_direction);
    float phase = 0.45 + 0.55*(1.0-0.36)/pow(max(1.36-1.2*mu, 0.05), 1.5);
    vec3 scatter = vec3(0.0);
    float transmittance = 1.0;
    for (int i=0; i<128; ++i)
    {
        if (i >= steps || transmittance < 0.005) break;
        // Spend more samples near the camera/entry, especially when inside a
        // cloud looking horizontally through a long stretch of the layer.
        float a = float(i)/float(steps), b = float(i+1)/float(steps);
        float step_size = (b*b-a*a)*(leave-entry);
        float distance = entry + a*a*(leave-entry) + jitter*step_size;
        vec3 p = vc_camera + ray*distance;
        float density = cloudDensity(p, true);
        if (density <= 0.0) continue;
        // Fade the finite layer into the distant sky, including near-horizontal rays.
        density *= 1.0-smoothstep(16000.0, 24000.0, distance);
        float shadow = 0.0;
        if (dot(vc_sun_color, vc_sun_color) > 0.0)
        {
            // Resolve nearby billows before taking wider steps through the
            // layer. A coarse first sample misses the cloud's own lit edge.
            float light_step = min(vc_thickness*0.125, vc_scale/64.0);
            float light_distance = 0.0;
            for (int j=0; j<4; ++j)
            {
                shadow += cloudDensity(p + vc_sun_direction*(light_distance+0.5*light_step), false)*light_step;
                light_distance += light_step;
                light_step *= 2.0;
            }
        }
        float h = clamp(p.z/vc_thickness, 0.0, 1.0);
        // ponytail: one overhead probe shades folds and undersides; distant
        // skylight occlusion would need a lighting volume.
        float sky_step = min(vc_thickness*0.2, vc_scale/32.0);
        float sky_shadow = cloudDensity(p + vec3(0.0, 0.0, sky_step), false)*sky_step*2.0;
        float sky_visibility = 0.35 + 0.65*exp(-sky_shadow);
        // ponytail: one broad multiple-scattering approximation; higher-order
        // transport needs a separate lighting cache. Keep the sun/moon's color
        // and intensity so sunset stays warm and night cannot gain daylight.
        vec3 bounced_light = vc_sun_color * 0.6 * exp(-shadow*0.1);
        vec3 light = vc_ambient*mix(0.55,1.0,h)*sky_visibility + vc_sun_color*phase*exp(-shadow) + bounced_light;
        // Approximate atmospheric loss over the cloud's own distance.
        light = mix(light, vc_ambient, 1.0-exp(-distance/18000.0));
        float attenuation = exp(-density*step_size);
        scatter += transmittance*(1.0-attenuation)*light*vc_tint;
        transmittance *= attenuation;
    }
    frag_color = vec4(scatter, transmittance);
}
