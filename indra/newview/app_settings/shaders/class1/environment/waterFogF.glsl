/**
 * @file class1\environment\waterFogF.glsl
 *
 * $LicenseInfo:firstyear=2007&license=viewerlgpl$
 * Second Life Viewer Source Code
 * Copyright (C) 2007, Linden Research, Inc.
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation;
 * version 2.1 of the License only.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with this library; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA
 *
 * Linden Research, Inc., 945 Battery Street, San Francisco, CA  94111  USA
 * $/LicenseInfo$
 */



uniform vec4 waterPlane;
uniform vec4 waterFogColor;
uniform float waterFogDensity;
uniform float waterFogKS;
uniform vec3 waterFogSunColor;
uniform vec3 waterFogSkyColor;
uniform vec3 waterFogLightDir;
uniform vec3 waterAbsorptionColor;
uniform vec3 waterScatteringColor;
uniform int water_lighting_enabled;
uniform sampler2D exclusionTex;
uniform sampler2D waterWaveSlopes;
uniform vec2 water_wave_direction;
uniform vec2 water_wave_origin;
uniform float water_wave_strength;
uniform float water_wave_scale;
uniform float water_caustics_strength;
uniform vec3 water_caustics_normal_scale;
uniform mat4 water_inverse_view;

// The optical surface and receiver caustics share these exact two slope bands,
// orientation and phase. Caustics filter out unresolved capillary detail instead
// of projecting an unrelated scrolling image onto the ground.
vec2 waterSpectralSlope(vec2 position, float footprint)
{
    vec2 direction = water_wave_direction;
    vec2 across = vec2(-direction.y, direction.x);
    float scale = clamp(water_wave_scale, 0.01, 2.0);
    vec2 local = vec2(dot(position, direction), dot(position, across)) / scale + water_wave_origin;
    vec2 swell, chop;
    if (footprint <= 0.0)
    {
        swell = texture(waterWaveSlopes, local / 256.0).xy;
        chop = texture(waterWaveSlopes, local / 64.0).zw;
    }
    else
    {
        swell = textureLod(waterWaveSlopes, local / 256.0, max(log2(footprint / scale), 0.0)).xy;
        chop = textureLod(waterWaveSlopes, local / 64.0, max(log2(footprint / (scale * 0.25)), 0.0)).zw;
    }
    vec2 slope = swell + 0.55 * chop;
    return water_wave_strength * (direction * slope.x + across * slope.y);
}

vec2 waterCausticLanding(vec2 entry, vec3 light, float depth, float footprint)
{
    vec2 slope = waterSpectralSlope(entry, footprint);
    slope *= water_caustics_normal_scale.xy / max(water_caustics_normal_scale.z, 0.001);
    slope *= mix(0.35, 1.0, smoothstep(0.0, 1.5, depth));
    vec3 ray = refract(-light, normalize(vec3(slope, 1.0)), 1.0 / 1.333);
    return entry + ray.xy * (depth / max(-ray.z, 0.2));
}

float waterCaustics(vec3 pos, vec3 light_dir)
{
    vec3 world = (water_inverse_view * vec4(pos, 1.0)).xyz;
    float pixel_size = max(length(dFdx(world)), length(dFdy(world)));
    float depth = -(dot(pos, waterPlane.xyz) + waterPlane.w);
    if (water_caustics_strength <= 0.0 || depth <= 0.0 || depth >= 16.0)
        return 1.0;
    vec2 uv = gl_FragCoord.xy / vec2(textureSize(exclusionTex, 0));
    if (texture(exclusionTex, uv).r < 1.0)
        return 1.0;
    vec3 light = normalize(mat3(water_inverse_view) * light_dir);
    if (light.z <= 0.02)
        return 1.0;
    // Finite sun size and receiver pixel footprint soften subpixel focusing.
    float footprint = max(max(pixel_size, depth * 0.009), 0.25 * water_wave_scale);
    float epsilon = max(footprint, 0.005);
    vec3 flat_ray = refract(-light, vec3(0, 0, 1), 1.0 / 1.333);
    vec2 entry = world.xy - flat_ray.xy * (depth / -flat_ray.z);
    float area = 1.0;
    float residual = 0.0;
    // Invert the surface-to-receiver map. Its area Jacobian measures sunlight
    // concentration. A flat or uniformly tilted surface has unit concentration.
    // This bounded single-path solve fades at folds rather than inventing energy.
    for (int i = 0; i < 3; ++i)
    {
        vec2 landing = waterCausticLanding(entry, light, depth, footprint);
        vec2 dx = (waterCausticLanding(entry + vec2(epsilon, 0), light, depth, footprint) - landing) / epsilon;
        vec2 dy = (waterCausticLanding(entry + vec2(0, epsilon), light, depth, footprint) - landing) / epsilon;
        area = dx.x * dy.y - dx.y * dy.x;
        vec2 error = landing - world.xy;
        residual = length(error);
        if (abs(area) < 0.08)
            break;
        vec2 step = vec2(dy.y * error.x - dy.x * error.y,
                         dx.x * error.y - dx.y * error.x) / area;
        if (i < 2)
            entry -= step * min(1.0, max(footprint * 4.0, 0.15) / max(length(step), 0.0001));
    }
    float resolved = 1.0 - smoothstep(epsilon, epsilon * 3.0, residual);
    float fade = smoothstep(0.02, 0.25, depth) * (1.0 - smoothstep(8.0, 16.0, depth));
    fade *= smoothstep(0.02, 0.2, light.z) * resolved;
    float focus = clamp(1.0 / max(abs(area), 0.2), 0.25, 4.0);
    return max(0.0, 1.0 + (focus - 1.0) * fade * water_caustics_strength);
}

vec3 srgb_to_linear(vec3 col);
vec3 linear_to_srgb(vec3 col);

vec3 atmosFragLighting(vec3 light, vec3 additive, vec3 atten);

// Analytic single-scattering integral with sunlight attenuated on the way
// down and scattered light attenuated on the way to the eye. Use the smaller
// exponent to stay finite for upward rays and the series at equal exponents.
vec3 waterLitIntegral(vec3 extinction, float distance_in_water,
                     float start_depth, float end_depth, float light_path_scale)
{
    vec3 optical = extinction * distance_in_water;
    vec3 a = extinction * (start_depth * light_path_scale);
    vec3 b = optical + extinction * (end_depth * light_path_scale);
    vec3 delta = abs(b - a);
    vec3 quotient = (vec3(1.0) - exp(-delta)) / max(delta, vec3(0.0001));
    quotient = mix(quotient, vec3(1.0) - 0.5 * delta + delta * delta / 6.0,
                   lessThan(delta, vec3(0.001)));
    return optical * exp(-min(a, b)) * quotient;
}

vec3 waterExtinction()
{
    vec3 tint = clamp(waterAbsorptionColor, vec3(0.0), vec3(1.0));
    float peak = max(max(tint.r, tint.g), tint.b);
    vec3 hue = peak > 0.000001 ? tint / peak : vec3(1.0);
    return max(waterFogDensity, 0.0) * 0.020202707 * (vec3(1.0) + 2.0 * (1.0 - hue));
}

// Sun/sky illumination loses energy on the way down to a receiver. Local
// lights and authored emission are deliberately outside this calculation.
vec3 waterReceiverTransmission(vec3 pos, vec3 light_dir, bool sky)
{
    float depth = -(dot(pos, waterPlane.xyz) + waterPlane.w);
    if (water_lighting_enabled == 0 || depth <= 0.0)
        return vec3(1.0);
    vec2 uv = gl_FragCoord.xy / vec2(textureSize(exclusionTex, 0));
    if (texture(exclusionTex, uv).r < 1.0)
        return vec3(1.0);
    float mu_air = clamp(dot(normalize(light_dir), waterPlane.xyz), 0.0, 1.0);
    float mu_water = sqrt(1.0 - (1.0 / (1.333 * 1.333)) * (1.0 - mu_air * mu_air));
    return exp(-waterExtinction() * depth * (sky ? 1.2 : 1.0 / mu_water));
}

vec3 waterFilterLight(vec3 light, vec3 transmission, int classic)
{
    if (all(equal(transmission, vec3(1.0))))
        return light;
    if (classic == 0)
        return light * transmission;
    // Classic carries sRGB until material composition. Preserve HDR values;
    // the general linear_to_srgb helper clamps them to one.
    vec3 linear = max(srgb_to_linear(light) * transmission, vec3(0.0));
    return mix(1.055 * pow(linear, vec3(1.0 / 2.4)) - 0.055,
               12.92 * linear, lessThanEqual(linear, vec3(0.0031308)));
}

vec3 waterLitSun(vec3 pos, vec3 light_dir, vec3 sunlit, int classic)
{
    vec3 transmission = waterReceiverTransmission(pos, light_dir, false);
    // Applied to incident directional light before material response and shadow
    // visibility, never to emission, ambient light or the final scene colour.
    return waterFilterLight(sunlit, transmission * waterCaustics(pos, light_dir), classic);
}

vec3 waterLitAmbient(vec3 pos, vec3 ambient, int classic)
{
    vec3 transmission = waterReceiverTransmission(pos, waterPlane.xyz, true);
    return waterFilterLight(ambient, transmission, classic);
}

// Integrate the portion of an arbitrary viewing segment inside the water.
// RGB Beer-Lambert transmission lets the preset hue survive farther than its
// complementary wavelengths. Density retains the legacy per-metre scale.
void getWaterFogSegment(vec3 start, vec3 pos, out vec3 transmission, out vec3 scattering)
{
    float eye_height = dot(start, waterPlane.xyz) + waterPlane.w;
    float end_height = dot(pos, waterPlane.xyz) + waterPlane.w;
    float distance_in_water = length(pos - start);
    if (eye_height >= 0.0 && end_height >= 0.0)
        distance_in_water = 0.0;
    else if (eye_height > 0.0)
        distance_in_water *= -end_height / max(eye_height - end_height, 0.000001);
    else if (end_height > 0.0)
        distance_in_water *= -eye_height / max(end_height - eye_height, 0.000001);

    vec3 tint = clamp(waterScatteringColor, vec3(0.0), vec3(1.0));
    vec3 extinction = waterExtinction();
    transmission = exp(-extinction * distance_in_water);
    float start_depth = max(-eye_height, 0.0);
    float end_depth = max(-end_height, 0.0);
    vec3 up = waterPlane.xyz;
    vec3 light_dir = waterFogLightDir / max(length(waterFogLightDir), 0.000001);
    float mu_air = clamp(dot(light_dir, up), 0.0, 1.0);
    // Snell refraction bounds the underwater light path even at sunset.
    const float eta = 1.0 / 1.333;
    float mu_water = sqrt(1.0 - eta * eta * (1.0 - mu_air * mu_air));
    vec3 light_in_water = eta * (light_dir - dot(light_dir, up) * up) + mu_water * up;
    vec3 ray = (pos - start) / max(length(pos - start), 0.000001);
    // A broad forward-scattering lobe gives view-dependent body colour. It is
    // deliberately mild; crest lighting belongs to the displaced wave surface.
    float cosine = clamp(dot(ray, light_in_water), -1.0, 1.0);
    const float anisotropy = 0.2;
    float phase = (1.0 - anisotropy * anisotropy) /
        pow(1.0 + anisotropy * anisotropy - 2.0 * anisotropy * cosine, 1.5);
    float entry = mu_air * (1.0 - (0.02037 + 0.97963 * pow(1.0 - mu_air, 5.0)));
    vec3 sun_transport = waterLitIntegral(extinction, distance_in_water, start_depth, end_depth, 1.0 / mu_water);
    // Average refracted path through the sky hemisphere. Preserve its authored
    // colour instead of desaturating it as solid-surface ambient lighting does.
    vec3 sky_transport = waterLitIntegral(extinction, distance_in_water, start_depth, end_depth, 1.2);
    scattering = tint * (max(waterFogSkyColor, vec3(0.0)) * sky_transport +
        0.5 * max(waterFogSunColor, vec3(0.0)) * entry * phase * sun_transport);
}

void getWaterFogTransport(vec3 pos, out vec3 transmission, out vec3 scattering)
{
    getWaterFogSegment(vec3(0.0), pos, transmission, scattering);
}

// The scene already contains water haze and pre-water transparency. Change its
// optical path instead of fogging it again. At very low transmission the saved
// image cannot recover detail; retain its existing transport rather than amplify
// half-float noise. Transparent layers share the opaque depth approximation.
vec3 waterRefractTransport(vec3 color, vec3 surface, vec3 receiver)
{
    vec3 old_t, old_s, new_t, new_s;
    getWaterFogTransport(receiver, old_t, old_s);
    getWaterFogSegment(surface, receiver, new_t, new_s);
    vec3 ratio = clamp(new_t / max(old_t, vec3(0.0001)), vec3(0.0), vec3(4.0));
    vec3 confidence = smoothstep(vec3(0.01), vec3(0.08), old_t);
    vec3 corrected = max(color - old_s, vec3(0.0)) * ratio + new_s;
    return mix(color, corrected, confidence);
}

vec4 applyWaterFogViewLinearNoClip(vec3 pos, vec4 color)
{
    vec3 transmission, scattering;
    getWaterFogTransport(pos, transmission, scattering);
    color.rgb = color.rgb * transmission + scattering;
    return color;
}

vec4 applyWaterFogViewLinear(vec3 pos, vec4 color)
{
    if (dot(pos, waterPlane.xyz) + waterPlane.w > 0.0)
        return color;
    return applyWaterFogViewLinearNoClip(pos, color);
}

vec4 applyWaterFogView(vec3 pos, vec4 color)
{
    return applyWaterFogViewLinear(pos, color);
}

// for post deferred shaders, apply sky and water fog in a way that is consistent with
// the deferred rendering haze post effects
vec4 applySkyAndWaterFog(vec3 pos, vec3 additive, vec3 atten, vec4 color)
{
    bool eye_above_water = dot(vec3(0), waterPlane.xyz) + waterPlane.w > 0.0;
    bool obj_above_water = dot(pos.xyz, waterPlane.xyz) + waterPlane.w > 0.0;

    if (eye_above_water)
    {
        if (!obj_above_water)
        {
            color.rgb = applyWaterFogViewLinearNoClip(pos, color).rgb;
        }
        else
        {
            color.rgb = atmosFragLighting(color.rgb, additive, atten);
        }
    }
    else
    {
        if (obj_above_water)
        {
            color.rgb = atmosFragLighting(color.rgb, additive, atten);
        }
        else
        {
            color.rgb = applyWaterFogViewLinearNoClip(pos, color).rgb;
        }
    }

    return color;
}
