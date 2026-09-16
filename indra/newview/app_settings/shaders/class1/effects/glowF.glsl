/**
 * @file glowF.glsl
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

out vec4 frag_color;

uniform sampler2D diffuseMap;
uniform float glowStrength;
uniform vec2 glowDelta;

in vec4 vary_texcoord0;
in vec4 vary_texcoord1;
in vec4 vary_texcoord2;
in vec4 vary_texcoord3;

void main()
{

    vec4 col = vec4(0.0, 0.0, 0.0, 0.0);

    // Filter the footprint between taps. At the default two-pixel spacing,
    // level-zero samples otherwise skip alternating pixels on every pass.
    vec2 stride = abs(glowDelta) * vec2(textureSize(diffuseMap, 0));
    float lod = log2(max(max(stride.x, stride.y), 1.0));

    // ATI compiler falls down on array initialization.
    float kern[8];
        kern[0] = 0.25; kern[1] = 0.5; kern[2] = 0.8; kern[3] = 1.0;
        kern[4] = 1.0;  kern[5] = 0.8; kern[6] = 0.5; kern[7] = 0.25;

    col += kern[0] * textureLod(diffuseMap, vary_texcoord0.xy, lod);
    col += kern[1] * textureLod(diffuseMap, vary_texcoord1.xy, lod);
    col += kern[2] * textureLod(diffuseMap, vary_texcoord2.xy, lod);
    col += kern[3] * textureLod(diffuseMap, vary_texcoord3.xy, lod);
    col += kern[4] * textureLod(diffuseMap, vary_texcoord0.zw, lod);
    col += kern[5] * textureLod(diffuseMap, vary_texcoord1.zw, lod);
    col += kern[6] * textureLod(diffuseMap, vary_texcoord2.zw, lod);
    col += kern[7] * textureLod(diffuseMap, vary_texcoord3.zw, lod);

    frag_color = max(vec4(col.rgb * glowStrength, col.a), vec4(0));
}
