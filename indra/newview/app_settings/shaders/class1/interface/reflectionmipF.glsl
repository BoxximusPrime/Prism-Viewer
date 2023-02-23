/** 
 * @file reflectionmipF.glsl
 *
 * $LicenseInfo:firstyear=2022&license=viewerlgpl$
 * Second Life Viewer Source Code
 * Copyright (C) 2022, Linden Research, Inc.
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
 
out vec4 frag_color;

uniform sampler2D diffuseRect;
uniform sampler2D depthMap;

uniform float resScale;
uniform float znear;
uniform float zfar;

in vec2 vary_texcoord0;

// get linear depth value given a depth buffer sample d and znear and zfar values
float linearDepth(float d, float znear, float zfar);

void main() 
{
    float depth = texture(depthMap, vary_texcoord0.xy).r;
    float dist = linearDepth(depth, znear, zfar);

    // convert linear depth to distance
    vec3 v;
    v.xy = vary_texcoord0.xy / 512.0 * 2.0 - 1.0;
    v.z = 1.0;
    v = normalize(v);
    dist /= v.z;

    vec3 col = texture(diffuseRect, vary_texcoord0.xy).rgb;
    frag_color = vec4(col, dist/256.0);
}
