/**
 * @file bumpF.glsl
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

out vec4 frag_data[4];

uniform float minimum_alpha;
uniform sampler2D diffuseMap;
uniform sampler2D bumpMap;

in vec3 vary_mat0;
in vec3 vary_mat1;
in vec3 vary_mat2;

in vec4 vertex_color;
in vec2 vary_texcoord0;
in vec3 vary_position;

void mirrorClip(vec3 pos);
vec4 encodeNormal(vec3 n, float env, float gbuffer_flag);

uniform float hair_object;
uniform int hair_debug;
mat3 hairMeshFrame(vec3 pos, vec2 uv, vec2 meshUV, vec3 n, vec4 tangent);
in vec4 vary_hair_tangent;
in vec2 vary_hair_texcoord;
mat3 hairVertexFrame() { return hairMeshFrame(vary_position, vary_texcoord0, vary_hair_texcoord, vec3(vary_mat0.z, vary_mat1.z, vary_mat2.z), vary_hair_tangent); }

vec3 hairSurface(vec3 pos, vec2 uv, inout vec3 n, vec4 center, bool generateNormal, out vec3 preview, out float variation);
vec3 hairTangent(vec3 pos, vec2 uv, vec3 n);
vec4 encodeHairNormal(vec3 n, float env, float flag, vec3 tangent);

vec4 hairDiffuseLookup(vec2 uv) { return texture(diffuseMap, uv); }
vec2 hairTextureSize() { return vec2(textureSize(diffuseMap, 0)); }

void main()
{
    vec4 diffuse_tap = texture(diffuseMap, vary_texcoord0.xy);
    vec3 norm = texture(bumpMap, vary_texcoord0.xy).rgb * 2.0 - 1.0;
    vec3 nvn = normalize(vec3(dot(norm,vary_mat0), dot(norm,vary_mat1), dot(norm,vary_mat2)));
    vec3 hair_preview;
    float hair_variation;
    vec3 strand = hairSurface(vary_position, vary_texcoord0, nvn, diffuse_tap, false, hair_preview, hair_variation);
    mirrorClip(vary_position);
    if (diffuse_tap.a < minimum_alpha) discard;
    vec4 col = diffuse_tap * vertex_color;

    frag_data[0] = vec4(col.rgb, 0.0);
    frag_data[1] = vertex_color.aaaa; // spec
    if (hair_object > 0.5) frag_data[1].a = hair_variation; // Hair replaces unused gloss with strand finish.
    //frag_data[1] = vec4(vec3(vertex_color.a), vertex_color.a+(1.0-vertex_color.a)*vertex_color.a); // spec - from former class3 - maybe better, but not so well tested
    frag_data[2] = encodeHairNormal(nvn, vertex_color.a, GBUFFER_FLAG_HAS_ATMOS, strand);
    if (hair_object > 0.5 && hair_debug != 0) frag_data[0].rgb = hair_preview;

#if defined(HAS_EMISSIVE)
    frag_data[3] = vec4(0, 0, 0, 0);
#endif
}
