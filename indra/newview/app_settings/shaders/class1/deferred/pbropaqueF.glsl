/**
 * @file pbropaqueF.glsl
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

/*[EXTRA_CODE_HERE]*/


#ifndef IS_HUD

// deferred opaque implementation

uniform sampler2D diffuseMap;  //always in sRGB space

uniform float metallicFactor;
uniform float roughnessFactor;
uniform vec3 emissiveColor;
uniform sampler2D bumpMap;
uniform sampler2D emissiveMap;
uniform sampler2D specularMap; // Packed: Occlusion, Metal, Roughness

out vec4 frag_data[4];

in vec3 vary_position;
in vec4 vertex_color;
in vec3 vary_normal;
in vec3 vary_tangent;
flat in float vary_sign;

in vec2 base_color_texcoord;
in vec2 normal_texcoord;
in vec2 metallic_roughness_texcoord;
in vec2 emissive_texcoord;

uniform float minimum_alpha; // PBR alphaMode: MASK, See: mAlphaCutoff, setAlphaCutoff()

vec3 linear_to_srgb(vec3 c);
vec3 srgb_to_linear(vec3 c);

uniform vec4 clipPlane;
uniform float clipSign;

void mirrorClip(vec3 pos);
vec4 encodeNormal(vec3 n, float env, float gbuffer_flag);
float filterPBRRoughness(float perceptual_roughness, vec3 normal);
uniform float hair_object;
uniform int hair_debug;
mat3 hairMeshFrame(vec3 pos, vec2 uv, vec2 meshUV, vec3 n, vec4 tangent);
in vec4 vary_hair_tangent;
in vec2 vary_hair_texcoord;
mat3 hairVertexFrame() { return hairMeshFrame(vary_position, base_color_texcoord, vary_hair_texcoord, vary_normal, vary_hair_tangent); }

vec3 hairSurface(vec3 pos, vec2 uv, inout vec3 n, vec4 center, bool generateNormal, out vec3 preview, out float variation);
vec3 hairTangent(vec3 pos, vec2 uv, vec3 n);
vec4 encodeHairNormal(vec3 n, float env, float flag, vec3 tangent);


uniform mat3 normal_matrix;

vec4 hairDiffuseLookup(vec2 uv) { return texture(diffuseMap, uv); }
vec2 hairTextureSize() { return vec2(textureSize(diffuseMap, 0)); }

void main()
{
    vec4 basecolor = texture(diffuseMap, base_color_texcoord.xy).rgba;
    vec4 diffuse_tap = basecolor;
    basecolor.rgb = srgb_to_linear(basecolor.rgb);

    basecolor *= vertex_color;

    vec3 col = basecolor.rgb;

    // from mikktspace.com
    vec3 vNt = texture(bumpMap, normal_texcoord.xy).xyz*2.0-1.0;
    float sign = vary_sign;
    vec3 vN = vary_normal;
    vec3 vT = vary_tangent.xyz;

    vec3 vB = sign * cross(vN, vT);
    vec3 tnorm = normalize( vNt.x * vT + vNt.y * vB + vNt.z * vN );

    // RGB = Occlusion, Roughness, Metal
    // default values, see LLViewerTexture::sDefaultPBRORMImagep
    //   occlusion 1.0
    //   roughness 0.0
    //   metal     0.0
    vec3 spec = texture(specularMap, metallic_roughness_texcoord.xy).rgb;

    spec.g = filterPBRRoughness(spec.g * roughnessFactor, tnorm);
    spec.b *= metallicFactor;

    vec3 hair_preview;
    float hair_variation;
    vec3 strand = hairSurface(vary_position, base_color_texcoord, tnorm, diffuse_tap, false, hair_preview, hair_variation);

    // Keep the derivative quad intact until material filtering is complete.
    mirrorClip(vary_position);
    if (basecolor.a < minimum_alpha) discard;

    vec3 emissive = emissiveColor;
    emissive *= srgb_to_linear(texture(emissiveMap, emissive_texcoord.xy).rgb);

    tnorm *= gl_FrontFacing ? 1.0 : -1.0;

    //spec.rgb = vec3(1,1,0);
    //col = vec3(0,0,0);
    //emissive = vary_tangent.xyz*0.5+0.5;
    //emissive = vec3(sign*0.5+0.5);
    //emissive = vNt * 0.5 + 0.5;
    //emissive = tnorm*0.5+0.5;
    // See: C++: addDeferredAttachments(), GLSL: softenLightF
    frag_data[0] = max(vec4(col, 0.0), vec4(0));                                                   // Diffuse
    frag_data[1] = max(vec4(spec.rgb,0.0), vec4(0));                                    // PBR linear packed Occlusion, Roughness, Metal.
    if (hair_object > 0.5) frag_data[1].a = hair_variation; // Hair replaces unused gloss with strand finish.
    frag_data[2] = encodeHairNormal(tnorm, 0, GBUFFER_FLAG_HAS_PBR, strand); // normal, environment intensity, flags
    if (hair_object > 0.5 && hair_debug != 0) frag_data[0].rgb = hair_preview;

#if defined(HAS_EMISSIVE)
    frag_data[3] = max(vec4(emissive,0), vec4(0));                                                // PBR sRGB Emissive
#endif
}

#else

// forward fullbright implementation for HUDs

uniform sampler2D diffuseMap;  //always in sRGB space

uniform vec3 emissiveColor;
uniform sampler2D emissiveMap;

out vec4 frag_color;

in vec3 vary_position;
in vec4 vertex_color;

in vec2 base_color_texcoord;
in vec2 emissive_texcoord;

uniform float minimum_alpha; // PBR alphaMode: MASK, See: mAlphaCutoff, setAlphaCutoff()

vec3 linear_to_srgb(vec3 c);
vec3 srgb_to_linear(vec3 c);

void main()
{
    vec4 basecolor = texture(diffuseMap, base_color_texcoord.xy).rgba;

    basecolor.a *= vertex_color.a;

    if (basecolor.a < minimum_alpha)
    {
        discard;
    }

    vec3 col = vertex_color.rgb * srgb_to_linear(basecolor.rgb);

    vec3 emissive = emissiveColor;
    emissive *= srgb_to_linear(texture(emissiveMap, emissive_texcoord.xy).rgb);

    col += emissive;

    // HUDs are rendered after gamma correction, output in sRGB space
    frag_color.rgb = linear_to_srgb(col);
    frag_color.a = 0.0;
}

#endif
