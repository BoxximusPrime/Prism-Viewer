/**
 * @file pbrShadowAlphaMaskF.glsl
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

out vec4 frag_color;
// Ordinary shadows keep their existing output. Focused SSS maps pack the first
// entry (RG) and first exit (BA), selected by the render pass color mask.
uniform int sss_depth_pass;
uniform float sss_depth_id;

uniform sampler2D diffuseMap;

in vec4 post_pos;
in float target_pos_x;
in vec4 vertex_color;
in vec2 vary_texcoord0;
uniform float minimum_alpha;

void main()
{
    // Opaque objects block at entry; their backfaces must not replace a skin exit.
    // Also enforce facing when a double-sided material disables hardware culling.
    if ((sss_depth_pass == 1 && !gl_FrontFacing) ||
        (sss_depth_pass == 2 && (gl_FrontFacing || sss_depth_id == 0.0))) discard;
    float alpha = texture(diffuseMap,vary_texcoord0.xy).a * vertex_color.a;

    if (alpha < minimum_alpha)
    {
        discard;
    }

    frag_color = sss_depth_pass == 0 ? vec4(1.0) :
        vec4(gl_FragCoord.z, sss_depth_id, gl_FragCoord.z, sss_depth_id);
}
