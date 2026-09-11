/**
 * Tagged mesh skin diffusion. Filters diffuse irradiance only; surface color and
 * specular detail remain sharp. The vertical pass adds the diffuse difference.
 */
/*[EXTRA_CODE_HERE]*/

layout(location = 0) out vec4 frag_color;
layout(location = 1) out vec4 frag_guide;
in vec2 vary_fragcoord;
// Use registered sampler slots so each input gets its own texture unit.
uniform sampler2D diffuseMap;    // current horizontal/vertical filter input
uniform sampler2D altDiffuseMap; // original diffuse lighting for the final delta
// normalMap belongs to getGBuffer(), including its packed skin flag. Keep the
// quarter-resolution normal/depth guide in a separate registered sampler slot.
uniform sampler2D bumpMap;
uniform sampler2D specularMap;   // completed wide irradiance filter
uniform vec4 sss_params; // strength, mode, warmth, maximum distance
uniform float sss_depth; // scattering radius in meters, not mesh thickness
uniform int sss_pass; // 0/1: full-resolution narrow filter/composite, 2: prepare, 3/4: wide filter
uniform int sss_smoothing_pass; // filter isolated transmission with gentler normal rejection
uniform int sss_full_resolution; // screenshot quality: original contiguous per-pixel gather
uniform vec2 screen_res;
uniform mat4 inv_proj;

GBufferInfo getGBuffer(vec2 tc);
vec4 getPosition(vec2 tc);
vec3 srgb_to_linear(vec3 c);

vec3 skinAlbedo(GBufferInfo gb)
{
    vec3 albedo = gb.albedo.rgb;
    if (!GET_GBUFFER_FLAG(gb.gbufferFlag, GBUFFER_FLAG_HAS_PBR))
        albedo = srgb_to_linear(albedo);
    return max(albedo, vec3(0.02));
}

float projectedRadius(float z)
{
    return max(sss_depth * 0.5 * screen_res.y / max(abs(inv_proj[1][1]) * -z, 0.001), 0.0);
}

float surfaceWeight(vec3 normal, float z, vec4 guide)
{
    float separation = abs(guide.w - z);
    if (separation > max(sss_depth, 0.002)) return 0.0;
    float alignment = max(dot(normal, guide.xyz), 0.0);
    if (sss_smoothing_pass == 0) alignment *= alignment * alignment * alignment;
    return exp(-separation / max(sss_depth * 2.0, 0.001)) * alignment;
}

vec3 kernelSigma()
{
    return sss_smoothing_pass != 0 ? vec3(0.8) :
        mix(vec3(0.65), vec3(1.0, 0.55, 0.35), sss_params.z);
}

void prepareWideFilter()
{
    // Average every source texel, including one-pixel lights, after removing
    // albedo. Coverage normalizes silhouettes without darkening their edges.
    ivec2 base = ivec2(gl_FragCoord.xy) * 4;
    vec4 colors[16];
    vec4 guides[16];
    float nearest = -1e20;
    for (int i = 0; i < 16; ++i)
    {
        ivec2 pixel = base + ivec2(i % 4, i / 4);
        vec2 uv = (vec2(pixel) + 0.5) / screen_res;
        GBufferInfo gb = getGBuffer(uv);
        bool skin = gb.sss >= 0.5 && all(lessThan(vec2(pixel), screen_res));
        colors[i] = vec4(texture(altDiffuseMap, uv).rgb / skinAlbedo(gb), skin ? 1.0 : 0.0);
        guides[i] = vec4(gb.normal, getPosition(uv).z);
        if (skin) nearest = max(nearest, guides[i].w);
    }
    vec3 irradiance = vec3(0.0);
    vec4 guide = vec4(0.0);
    float count = 0.0;
    for (int i = 0; i < 16; ++i)
    {
        // A tile straddling separate depth layers represents the front layer.
        // The full-resolution composite rejects it on the other layer.
        float weight = colors[i].a * (nearest - guides[i].w <= max(sss_depth, 0.002) ? 1.0 : 0.0);
        irradiance += colors[i].rgb * weight;
        guide += guides[i] * weight;
        count += weight;
    }
    frag_color = vec4(irradiance / max(count, 1.0), count / 16.0);
    frag_guide = count > 0.0 ? vec4(normalize(guide.xyz), guide.w / count) : vec4(0.0);
}

void filterWide()
{
    ivec2 pixel = ivec2(gl_FragCoord.xy);
    ivec2 size = textureSize(diffuseMap, 0);
    vec4 center = texelFetch(diffuseMap, pixel, 0);
    if (center.a <= 0.0) { frag_color = vec4(0.0); return; }
    vec4 guide = texelFetch(bumpMap, pixel, 0);
    float radius = projectedRadius(guide.w) * 0.25;
    if (radius <= 0.5) { frag_color = center; return; }
    int axis = sss_pass == 3 ? 0 : 1;
    ivec2 direction = sss_pass == 3 ? ivec2(1, 0) : ivec2(0, 1);
    int taps = int(ceil(min(radius, float(size[axis]))));
    int first = max(-taps, -pixel[axis]);
    int last = min(taps, size[axis] - 1 - pixel[axis]);
    vec3 sigma = kernelSigma();
    vec3 sum = vec3(0.0), weights = vec3(0.0);
    for (int i = first; i <= last; ++i)
    {
        ivec2 sample_pixel = pixel + direction * i;
        vec4 value = texelFetch(diffuseMap, sample_pixel, 0);
        if (value.a <= 0.0) continue;
        vec4 sample_guide = texelFetch(bumpMap, sample_pixel, 0);
        float edge = surfaceWeight(guide.xyz, guide.w, sample_guide) * value.a;
        float offset = float(i) / radius;
        vec3 weight = exp(vec3(-4.5 * offset * offset) / (sigma * sigma)) * edge *
            clamp(radius - abs(float(i)) + 0.5, 0.0, 1.0);
        sum += value.rgb * weight;
        weights += weight;
    }
    frag_color = vec4(sum / max(weights, vec3(0.00001)), center.a);
}

vec4 cubicWeights(float t)
{
    float t2 = t * t, t3 = t2 * t;
    return vec4(1.0 - 3.0*t + 3.0*t2 - t3, 4.0 - 6.0*t2 + 3.0*t3,
                1.0 + 3.0*t + 3.0*t2 - 3.0*t3, t3) / 6.0;
}

vec3 wideIrradiance(vec2 tc, vec3 normal, float z, vec3 fallback)
{
    // A positive cubic reconstruction avoids four-pixel slope changes around
    // narrow lights. Geometry/coverage weights keep it on the same skin layer.
    vec2 pixel = tc * screen_res * 0.25 - 0.5;
    ivec2 base = ivec2(floor(pixel));
    vec2 fraction = fract(pixel);
    vec4 wx = cubicWeights(fraction.x), wy = cubicWeights(fraction.y);
    ivec2 size = textureSize(specularMap, 0);
    vec3 sum = vec3(0.0);
    float weights = 0.0;
    for (int y = 0; y < 4; ++y)
    for (int x = 0; x < 4; ++x)
    {
        ivec2 p = clamp(base + ivec2(x - 1, y - 1), ivec2(0), size - 1);
        vec4 value = texelFetch(specularMap, p, 0);
        vec4 guide = texelFetch(bumpMap, p, 0);
        float weight = wx[x] * wy[y] * value.a * surfaceWeight(normal, z, guide);
        sum += value.rgb * weight;
        weights += weight;
    }
    return weights > 0.00001 ? sum / weights : fallback;
}

void main()
{
    if (sss_pass == 2) { prepareWideFilter(); return; }
    if (sss_pass >= 3) { filterWide(); return; }
    vec2 tc = vary_fragcoord;
    GBufferInfo center = getGBuffer(tc);
    vec3 pos = getPosition(tc).xyz;
    float fade = 1.0 - smoothstep(sss_params.w * 0.8, sss_params.w, length(pos));
    if (center.sss < 0.5 || fade <= 0.0)
    {
        frag_color = vec4(0.0);
        return;
    }

    vec3 albedo = skinAlbedo(center);
    float radius = projectedRadius(pos.z);
    float visible = smoothstep(0.5, 1.5, radius);
    if (visible <= 0.0)
    {
        // Subpixel diffusion is invisible: keep the horizontal irradiance valid
        // for adjacent pixels, and skip the neighborhood filter entirely.
        frag_color = sss_pass == 0 ? vec4(texture(diffuseMap, tc).rgb / albedo, 0.0) : vec4(0.0);
        return;
    }
    // Keep the original per-pixel filter for small radii, blending to the wide
    // buffer over 8--16 pixels so zooming cannot expose a resolution switch.
    float wide = sss_full_resolution != 0 ? 0.0 : smoothstep(8.0, 16.0, radius);
    if (sss_full_resolution == 0 && sss_pass == 0 && radius > 20.0)
    {
        frag_color = vec4(texture(diffuseMap, tc).rgb / albedo, 0.0);
        return;
    }
    vec2 direction = sss_pass == 0 ? vec2(1.0 / screen_res.x, 0.0) : vec2(0.0, 1.0 / screen_res.y);
    vec3 sigma = kernelSigma();
    vec3 sum = vec3(0.0);
    vec3 weights = vec3(0.0);
    // Screenshot quality evaluates the full requested radius here; the default
    // path evaluates wide radii on the quarter-resolution grid above.
    int axis = sss_pass == 0 ? 0 : 1;
    int taps = int(ceil(min(radius, screen_res[axis])));
    int pixel = int(tc[axis] * screen_res[axis]);
    int first = max(-taps, -pixel);
    int last = min(taps, int(screen_res[axis]) - 1 - pixel);
    if (sss_pass == 0 || wide < 1.0)
    for (int i = first; i <= last; ++i)
    {
        float offset = float(i) / radius;
        vec2 uv = tc + direction * float(i);
        if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)))) continue;
        GBufferInfo sample_gb = getGBuffer(uv);
        if (sample_gb.sss < 0.5) continue;
        vec3 sample_pos = getPosition(uv).xyz;
        float separation = abs(sample_pos.z - pos.z);
        // Do not mix distant layers just because both surfaces are tagged skin.
        if (separation > max(sss_depth, 0.002)) continue;
        float edge = exp(-separation / max(sss_depth * 2.0, 0.001));
        edge *= pow(max(dot(center.normal, sample_gb.normal), 0.0), sss_smoothing_pass != 0 ? 1.0 : 4.0);
        // Introduce an edge texel gradually as the radius crosses its footprint.
        float footprint = clamp(radius - abs(float(i)) + 0.5, 0.0, 1.0);
        vec3 weight = exp(vec3(-4.5 * offset * offset) / (sigma * sigma)) * edge * footprint;
        vec3 irradiance = texture(diffuseMap, uv).rgb;
        if (sss_pass == 0) irradiance /= skinAlbedo(sample_gb);
        sum += irradiance * weight;
        weights += weight;
    }
    vec3 filtered = sum / max(weights, vec3(0.00001));
    if (sss_pass == 0)
    {
        frag_color = vec4(filtered, 0.0);
    }
    else
    {
        vec3 original = texture(altDiffuseMap, tc).rgb;
        if (wide > 0.0)
            filtered = mix(filtered, wideIrradiance(tc, center.normal, pos.z, original / albedo), wide);
        // Transmission already contains SSS strength and distance fade. Replace
        // it fully instead of retaining a fraction of the original mottling.
        float amount = sss_smoothing_pass != 0 ? visible : sss_params.x * fade * visible;
        frag_color = vec4((filtered * albedo - original) * amount, 0.0);
    }
}
