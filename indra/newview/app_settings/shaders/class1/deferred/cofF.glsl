/**
 * @file cofF.glsl
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

uniform sampler2D diffuseRect;
uniform sampler2D depthMap;

uniform float depth_cutoff;
uniform float norm_cutoff;
uniform float focal_distance;
uniform float blur_constant;
uniform float tan_pixel_angle;
uniform float magnification;
uniform float max_cof;

uniform mat4 inv_proj;
uniform vec2 screen_res;
uniform vec2 taa_depth_jitter;

in vec2 vary_fragcoord;

float calc_cof(float depth)
{
    float sc = (depth-focal_distance)/-depth*blur_constant;

    sc /= magnification;

    // tan_pixel_angle = pixel_length/-depth;
    float pixel_length =  tan_pixel_angle*-focal_distance;

    sc = sc/pixel_length;
    sc *= 1.414;

    return sc;
}

float sample_cof(ivec2 pixel, ivec2 size)
{
    float z = texelFetch(depthMap,clamp(pixel,ivec2(0),size-1),0).r*2.0-1.0;
    vec4 ndc = vec4(0.0, 0.0, z, 1.0);
    vec4 p = inv_proj*ndc;
    return clamp(calc_cof(p.z/p.w),-max_cof,max_cof);
}
void main()
{
    // Filter blur radii on the same unjittered grid as TAA color, rather than
    // interpolating physical depths across a foreground/background boundary.
    ivec2 size=textureSize(depthMap,0);
    vec2 pos=(vary_fragcoord.xy+taa_depth_jitter)*vec2(size)-.5;
    ivec2 pixel=ivec2(floor(pos));
    vec2 f=fract(pos);
    float sc=mix(mix(sample_cof(pixel,size),sample_cof(pixel+ivec2(1,0),size),f.x),
                 mix(sample_cof(pixel+ivec2(0,1),size),sample_cof(pixel+ivec2(1,1),size),f.x),f.y);

    vec4 diff = texture(diffuseRect, vary_fragcoord.xy);

    frag_color.rgb = diff.rgb;
    frag_color.a = sc/max_cof*0.5+0.5;
}
