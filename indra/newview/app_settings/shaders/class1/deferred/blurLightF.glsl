/**
 * @file blurLightF.glsl
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

/*[EXTRA_CODE_HERE]*/

out vec4 frag_color;

uniform sampler2D lightMap;

uniform float dist_factor;
uniform float blur_size;
uniform vec2 delta;
uniform vec2 screen_res;
uniform vec3 kern[4];
uniform float kern_scale;
uniform int pcss_enabled;
uniform int gtao_enabled;
uniform float pcss_cleanup;
uniform int pcss_cleanup_only;
uniform mat4 inv_proj;

in vec2 vary_fragcoord;

vec4 getPosition(vec2 pos_screen);
vec4 getNorm(vec2 pos_screen);

vec3 cleanupShadow(vec2 tc, vec3 pos, vec3 normal, vec3 center)
{
    // Keep pixel cleanup at distance, but cover a small surface footprint
    // up close. A fixed pixel radius becomes invisible as the camera zooms
    // in. Integer taps keep depth, normal and visibility on the same surface.
    vec3 dx = dFdx(pos), dy = dFdy(pos);
    vec3 plane = cross(dx, dy);
    plane = dot(plane, plane) > 1e-20 ? normalize(plane) : normal;
    float depthError = abs(inv_proj[2].w * pos.z) * length(pos) * (8.0 / 16777216.0);
    float tolerance = max(0.002, 0.25 * min(length(dx), length(dy))) + depthError;
    float amount = clamp(pcss_cleanup, 0.0, 3.0);
    float metresPerPixel = length(dx * delta.x + dy * delta.y);
    // One unit supplies a 4 mm surface sigma as well as a one-pixel minimum.
    // Bound work for extreme closeups; dense sampling avoids sparse blur bands.
    float sigma = min(max(amount, amount * 0.004 / max(metresPerPixel, 1e-6)), 12.0);
    int radius = int(ceil(2.0 * sigma));
    vec3 sum = center;
    float total = 1.0;
    ivec2 size = textureSize(lightMap, 0);
    ivec2 origin = ivec2(tc * vec2(size));
    for (int i = -radius; i <= radius; ++i)
    {
        if (i == 0) continue;
        ivec2 tap = origin + ivec2(delta) * i;
        if (any(lessThan(tap, ivec2(0))) || any(greaterThanEqual(tap, size))) continue;
        vec2 uv = (vec2(tap) + 0.5) / vec2(size);
        vec3 otherNormal = getNorm(uv).xyz;
        float agreement = max(dot(normal, otherNormal), 0.0);
        vec3 difference = getPosition(uv).xyz - pos;
        float separation = max(abs(dot(plane, difference)), abs(dot(otherNormal, difference)));
        float weight = exp(-0.5 * float(i*i) / max(sigma*sigma, 1e-6)) * pow(agreement, 8.0);
        weight *= 1.0 - smoothstep(tolerance, 2.0*tolerance, separation);
        sum += texelFetch(lightMap, tap, 0).rba * weight;
        total += weight;
    }
    return sum / total;
}

void main()
{
    vec2 tc = vary_fragcoord.xy;
    vec4 norm = getNorm(tc);
    vec3 pos = getPosition(tc).xyz;
    vec4 ccol = texture(lightMap, tc).rgba;
    vec3 shadows = ccol.rba;
    if (pcss_enabled != 0)
    {
        if (pcss_cleanup > 0.0) shadows = cleanupShadow(tc, pos, norm.xyz, shadows);
        if (pcss_cleanup_only != 0)
        {
            frag_color = vec4(shadows.x, ccol.g, shadows.yz);
            return;
        }
    }

    vec2 dlt = kern_scale * delta / (1.0+norm.xy*norm.xy);
    dlt /= max(-pos.z*dist_factor, 1.0);

    vec2 defined_weight = kern[0].xy; // special case the first (centre) sample's weight in the blur; we have to sample it anyway so we get it for 'free'
    vec4 col = defined_weight.xyxx * ccol;

    // relax tolerance according to distance to avoid speckling artifacts, as angles and distances are a lot more abrupt within a small screen area at larger distances
    float pointplanedist_tolerance_pow2 = pos.z*pos.z*0.00005;

    // perturb sampling origin slightly in screen-space to hide edge-ghosting artifacts where smoothing radius is quite large
    tc *= screen_res;
    float tc_mod = 0.5*(tc.x + tc.y);
    tc_mod -= floor(tc_mod);
    tc_mod *= 2.0;
    tc += ( (tc_mod - 0.5) * kern[1].z * dlt * 0.5 );

    // TODO: move this to kern instead of building kernel per pixel
    vec3 k[7];
    k[0] = kern[0];
    k[2] = kern[1];
    k[4] = kern[2];
    k[6] = kern[3];

    k[1] = (k[0]+k[2])*0.5f;
    k[3] = (k[2]+k[4])*0.5f;
    k[5] = (k[4]+k[6])*0.5f;

    for (int i = 1; i < 7; i++)
    {
        vec2 samptc = tc + k[i].z*dlt*2.0;
        samptc /= screen_res;
        vec3 samppos = getPosition(samptc).xyz;

        float d = dot(norm.xyz, samppos.xyz-pos.xyz);// dist from plane

        if (d*d <= pointplanedist_tolerance_pow2)
        {
            col += texture(lightMap, samptc)*k[i].xyxx;
            defined_weight += k[i].xy;
        }
    }

    for (int i = 1; i < 7; i++)
    {
        vec2 samptc = tc - k[i].z*dlt*2.0;
        samptc /= screen_res;
        vec3 samppos = getPosition(samptc).xyz;

        float d = dot(norm.xyz, samppos.xyz-pos.xyz);// dist from plane

        if (d*d <= pointplanedist_tolerance_pow2)
        {
            col += texture(lightMap, samptc)*k[i].xyxx;
            defined_weight += k[i].xy;
        }
    }

    col /= defined_weight.xyxx;
    // Keep PCSS cleanup separate from the broader legacy AO filter.
    if (pcss_enabled != 0) col.rba = shadows;
    // GTAO already has its own edge-aware spatial denoiser.
    if (gtao_enabled != 0) col.g = ccol.g;
    //col.y *= col.y;

    frag_color = max(col, vec4(0));

#ifdef IS_AMD_CARD
    // If it's AMD make sure the GLSL compiler sees the arrays referenced once by static index. Otherwise it seems to optimise the storage awawy which leads to unfun crashes and artifacts.
    vec3 dummy1 = kern[0];
    vec3 dummy2 = kern[3];
#endif
}
