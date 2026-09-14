/**
 * @file exposureF.glsl
 *
 * $LicenseInfo:firstyear=2023&license=viewerlgpl$
 * Second Life Viewer Source Code
 * Copyright (C) 2023, Linden Research, Inc.
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

/*[EXTRA_CODE_HERE]*/

out vec4 frag_color;

uniform sampler2D emissiveRect;
#ifdef USE_LAST_EXPOSURE
uniform sampler2D exposureMap;
#endif

uniform float dt;
uniform vec2 noiseVec;

uniform vec4 dynamic_exposure_params;
uniform vec4 dynamic_exposure_params2;
uniform int eye_adaptation;
uniform vec4 eye_adaptation_limits; // minimum EV, maximum EV, compensation EV, highlights
uniform vec2 eye_adaptation_times;  // seconds to 90%: entering darkness, entering light

float lum(vec3 col)
{
    vec3 l = vec3(0.2126, 0.7152, 0.0722);
    return dot(l, col);
}

void main()
{
    vec2 tc = vec2(0.5,0.5);

    if (eye_adaptation != 0)
    {
        vec4 meter = textureLod(emissiveRect, tc, 8);
        float weight = max(meter.b, 0.0001);
        float average_log = meter.r / weight;
        float highlights = sqrt(max(meter.g / weight, 0.00000001));
        float min_ev = eye_adaptation_limits.x;
        float max_ev = eye_adaptation_limits.y;
        float target_ev = log2(0.18) + eye_adaptation_limits.z - average_log;
        target_ev = clamp(target_ev, min_ev, max_ev);

        // RMS luminance gives bright regions a voice without using the single
        // hottest pixel as the meter. Leave the tonemapper some HDR headroom.
        float highlight_ev = log2(2.0 / highlights);
        target_ev = mix(target_ev, min(target_ev, highlight_ev), eye_adaptation_limits.w);
        target_ev = clamp(target_ev, min_ev, max_ev);
        if (isnan(target_ev) || isinf(target_ev)) target_ev = 0.0;
#ifdef USE_LAST_EXPOSURE
        float previous = texture(exposureMap, tc).r;
        if (isnan(previous) || isinf(previous) || previous <= 0.0) previous = 1.0;
        float previous_ev = clamp(log2(previous), min_ev, max_ev);
        float seconds = target_ev > previous_ev ? eye_adaptation_times.x : eye_adaptation_times.y;
        float elapsed = (isnan(dt) || isinf(dt)) ? 0.0 : clamp(dt, 0.0, 0.25);
        float blend = 1.0 - exp(-2.302585093 * elapsed / max(seconds, 0.05));
        target_ev = mix(previous_ev, target_ev, blend);
#endif
        frag_color = vec4(exp2(target_ev), 0.0, 0.0, 1.0);
        return;
    }

    float L = textureLod(emissiveRect, tc, 8).r;
    float max_L = dynamic_exposure_params.x;
    L = clamp(L, 0.0, max_L);
    L /= max_L;
    L = pow(L, 2.0);
    float s = mix(dynamic_exposure_params.z, dynamic_exposure_params.y, L);
#ifdef USE_LAST_EXPOSURE
    float prev = texture(exposureMap, vec2(0.5,0.5)).r;

    float speed = -log(dynamic_exposure_params.w) / dynamic_exposure_params2.w;
    s = mix(prev, s, 1 - exp(-speed * dt));
#endif

    frag_color = max(vec4(s, s, s, dt), vec4(0.0));
}
