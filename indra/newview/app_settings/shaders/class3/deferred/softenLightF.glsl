/**
 * @file class3/deferred/softenLightF.glsl
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

#define FLT_MAX 3.402823466e+38

layout(location = 0) out vec4 frag_color;
layout(location = 1) out vec4 sss_diffuse;

const float M_PI = 3.14159265;

#if defined(HAS_SUN_SHADOW) || defined(HAS_SSAO)
uniform sampler2D lightMap;
#endif

uniform sampler2D     lightFunc;

uniform float blur_size;
uniform float blur_fidelity;

#if defined(HAS_SSAO)
uniform float ssao_irradiance_scale;
uniform float ssao_irradiance_max;
#endif

// Inputs
uniform vec4 clipPlane;
uniform mat3 env_mat;
uniform mat3  ssao_effect_mat;
uniform vec3 sun_dir;
uniform vec3 moon_dir;
uniform int  sun_up_factor;
uniform int classic_mode;

in vec2 vary_fragcoord;

uniform mat4 inv_proj;
uniform vec2 screen_res;

vec4 getNorm(vec2 pos_screen);
vec4 getPositionWithDepth(vec2 pos_screen, float depth);

void calcAtmosphericVarsLinear(vec3 inPositionEye, vec3 norm, vec3 light_dir, out vec3 sunlit, out vec3 amblit, out vec3 atten, out vec3 additive);
vec3  atmosFragLightingLinear(vec3 l, vec3 additive, vec3 atten);
vec3  scaleSoftClipFragLinear(vec3 l);

// reflection probe interface
void sampleReflectionProbes(inout vec3 ambenv, inout vec3 glossenv,
    vec2 tc, vec3 pos, vec3 norm, float glossiness, bool transparent, vec3 amblit_linear);
void sampleReflectionProbesLegacy(inout vec3 ambenv, inout vec3 glossenv, inout vec3 legacyenv,
        vec2 tc, vec3 pos, vec3 norm, float glossiness, float envIntensity, bool transparent, vec3 amblit_linear);
void applyGlossEnv(inout vec3 color, vec3 glossenv, vec4 spec, vec3 pos, vec3 norm);
void applyLegacyEnv(inout vec3 color, vec3 legacyenv, vec4 spec, vec3 pos, vec3 norm, float envIntensity);
float getDepth(vec2 pos_screen);

vec3 linear_to_srgb(vec3 c);
vec3 srgb_to_linear(vec3 c);

uniform vec4 waterPlane;

uniform int cube_snapshot;

uniform float sky_hdr_scale;

void calcHalfVectors(vec3 lv, vec3 n, vec3 v, out vec3 h, out vec3 l, out float nh, out float nl, out float nv, out float vh, out float lightDist);
void calcDiffuseSpecular(vec3 baseColor, float metallic, inout vec3 diffuseColor, inout vec3 specularColor);

vec3 pbrBaseLight(vec3 diffuseColor,
                  vec3 specularColor,
                  float metallic,
                  vec3 pos,
                  vec3 norm,
                  float perceptualRoughness,
                  vec3 light_dir,
                  vec3 sunlit,
                  float scol,
                  vec3 radiance,
                  vec3 irradiance,
                  vec3 colorEmissive,
                  float ao,
                  vec3 additive,
                  vec3 atten);

void pbrIbl(vec3 diffuseColor, vec3 specularColor, vec3 radiance, vec3 irradiance,
            float ao, float nv, float perceptualRoughness, out vec3 diffuseOut, out vec3 specularOut);
void pbrPunctual(vec3 diffuseColor, vec3 specularColor, float perceptualRoughness,
                 float metallic, vec3 n, vec3 v, vec3 l, out float nl, out vec3 diff, out vec3 spec);

float getSSSStrength(float mask, vec3 positionEye);
bool useSSSWrappedDiffuse(float strength);
bool useSSSScreenDiffusion(float strength);
vec3 getSSSDiffuseFactor(float nl, float strength);
vec3 getSSSTransmission(float nl, float nv, float strength);

GBufferInfo getGBuffer(vec2 screenpos);
vec3 clampHDRRange(vec3 color);

vec3 pbrBaseLightSSS(vec3 diffuseColor, vec3 specularColor, float metallic, vec3 v, vec3 norm,
                     float perceptualRoughness, vec3 light_dir, vec3 sunlit, float scol,
                     vec3 radiance, vec3 irradiance, vec3 colorEmissive, float ao,
                     float sssStrength, out vec3 diffuseLighting)
{
    float nv = clamp(abs(dot(norm, v)), 0.001, 1.0);
    vec3 iblDiffuse = vec3(0.0);
    vec3 iblSpecular = vec3(0.0);
    pbrIbl(diffuseColor, specularColor, radiance, irradiance, ao, nv,
           perceptualRoughness, iblDiffuse, iblSpecular);

    float nl = 0.0;
    vec3 directDiffuse = vec3(0.0);
    vec3 directSpecular = vec3(0.0);
    pbrPunctual(diffuseColor, specularColor, perceptualRoughness, metallic, norm, v,
                normalize(light_dir), nl, directDiffuse, directSpecular);

    float diffuseNl = sssStrength > 0.0 ? dot(norm, normalize(light_dir)) : nl;
    vec3 diffuseFactor = getSSSDiffuseFactor(diffuseNl, sssStrength);
    vec3 transmission = getSSSTransmission(diffuseNl, nv, sssStrength);
    vec3 result;
    if (classic_mode > 0)
    {
        irradiance = srgb_to_linear(irradiance * 0.9);
        vec3 sunContrib = min(pow(diffuseFactor, vec3(1.2)), vec3(scol));
        sunContrib = srgb_to_linear(linear_to_srgb(sunContrib) * sunlit * 0.7) * M_PI;
        vec3 specSunContrib = vec3(min(pow(nl, 1.2), scol));
        specSunContrib = srgb_to_linear(linear_to_srgb(specSunContrib) * sunlit * 0.7) * M_PI;

        vec3 ambient = irradiance * diffuseColor;
        vec3 sunDiffuse = clamp(sunContrib * directDiffuse * scol, vec3(0.0), vec3(10.0));
        vec3 combinedSun = clamp((sunContrib * directDiffuse + specSunContrib * directSpecular) * scol,
                                 vec3(0.0), vec3(10.0));
        vec3 transmitted = srgb_to_linear(linear_to_srgb(transmission) * sunlit * 0.7) * diffuseColor * scol;
        sunDiffuse += transmitted;
        combinedSun += transmitted;

        result = srgb_to_linear(linear_to_srgb(ambient) + linear_to_srgb(combinedSun) * 1.1);
        diffuseLighting = ambient + srgb_to_linear(linear_to_srgb(sunDiffuse) * 1.1);
    }
    else
    {
        vec3 transmitted = transmission * diffuseColor / 3.14159265;
        vec3 sunDiffuse = clamp(diffuseFactor * directDiffuse + transmitted, vec3(0.0), vec3(10.0)) * sunlit * 3.0 * scol;
        vec3 combinedSun = clamp(diffuseFactor * directDiffuse + transmitted + nl * directSpecular,
                                 vec3(0.0), vec3(10.0)) * sunlit * 3.0 * scol;
        result = iblDiffuse + combinedSun;
        diffuseLighting = iblDiffuse + sunDiffuse;
    }

    return result + iblSpecular + colorEmissive;
}

void adjustIrradiance(inout vec3 irradiance, float ambocc)
{
    // use sky settings ambient or irradiance map sample, whichever is brighter
    //irradiance = max(amblit_linear, irradiance);

#if defined(HAS_SSAO)
    irradiance = mix(ssao_effect_mat * min(irradiance.rgb*ssao_irradiance_scale, vec3(ssao_irradiance_max)), irradiance.rgb, ambocc);
#endif
}

void main()
{
    vec2  tc           = vary_fragcoord.xy;
    float depth        = getDepth(tc.xy);
    vec4  pos          = getPositionWithDepth(tc, depth);

    GBufferInfo gb = getGBuffer(tc);
    float sssStrength = getSSSStrength(gb.sss, pos.xyz);
    float wrapStrength = useSSSWrappedDiffuse(sssStrength) ? sssStrength : 0.0;
    vec3 sssDiffuseLighting = vec3(0.0);

    vec3 colorEmissive = gb.emissive.rgb;
    float envIntensity = gb.envIntensity;
    vec3  light_dir   = (sun_up_factor == 1) ? sun_dir : moon_dir;

    vec4 baseColor     = gb.albedo;
    vec4 spec        = gb.specular; // NOTE: PBR linear Emissive

#if defined(HAS_SUN_SHADOW) || defined(HAS_SSAO)
    vec2 scol_ambocc = texture(lightMap, vary_fragcoord.xy).rg;
#endif

#if defined(HAS_SUN_SHADOW)
    float scol       = max(scol_ambocc.r, baseColor.a);
#else
    float scol = 1.0;
#endif
#if defined(HAS_SSAO)
    float ambocc     = scol_ambocc.g;
#else
    float ambocc = 1.0;
#endif

    vec3  color = vec3(0);
    float bloom = 0.0;

    vec3 sunlit;
    vec3 amblit;
    vec3 additive;
    vec3 atten;

    calcAtmosphericVarsLinear(pos.xyz, gb.normal, light_dir, sunlit, amblit, additive, atten);

    if (classic_mode > 0)
        sunlit *= 1.35;

    vec3 sunlit_linear = sunlit;
    vec3 amblit_linear = amblit;

    vec3  radiance  = vec3(0);

    if (GET_GBUFFER_FLAG(gb.gbufferFlag, GBUFFER_FLAG_HAS_PBR))
    {
        vec3 orm = spec.rgb;
        float perceptualRoughness = orm.g;
        float metallic = orm.b;
        float ao = orm.r;

        vec3  irradiance = amblit_linear;

        // PBR IBL
        float gloss      = 1.0 - perceptualRoughness;

        sampleReflectionProbes(irradiance, radiance, tc, pos.xyz, gb.normal, gloss, false, amblit_linear);

        adjustIrradiance(irradiance, ambocc);

        vec3 diffuseColor = vec3(0.0);
        vec3 specularColor = vec3(0.0);
        calcDiffuseSpecular(baseColor.rgb, metallic, diffuseColor, specularColor);

        vec3 v = -normalize(pos.xyz);
        if (wrapStrength > 0.0)
        {
            color = pbrBaseLightSSS(diffuseColor, specularColor, metallic, v, gb.normal,
                                    perceptualRoughness, light_dir, sunlit_linear, scol, radiance,
                                    irradiance, colorEmissive, ao, wrapStrength, sssDiffuseLighting);
        }
        else
        {
            // Keep the established PBR composition byte-for-byte when SSS does not alter lighting.
            color = pbrBaseLight(diffuseColor, specularColor, metallic, v, gb.normal,
                                 perceptualRoughness, light_dir, sunlit_linear, scol, radiance,
                                 irradiance, colorEmissive, ao, additive, atten);

            if (useSSSScreenDiffusion(sssStrength))
            {
                pbrBaseLightSSS(diffuseColor, specularColor, metallic, v, gb.normal,
                                perceptualRoughness, light_dir, sunlit_linear, scol, radiance,
                                irradiance, colorEmissive, ao, 0.0, sssDiffuseLighting);
            }
        }
    }
    else if (GET_GBUFFER_FLAG(gb.gbufferFlag, GBUFFER_FLAG_HAS_HDRI))
    {
        // actual HDRI sky, just copy color value
        color = colorEmissive.rgb;
    }
    else if (GET_GBUFFER_FLAG(gb.gbufferFlag, GBUFFER_FLAG_SKIP_ATMOS))
    {
        //should only be true of WL sky, port over base color value and scale for fake HDR
#if defined(HAS_EMISSIVE)
        color = colorEmissive.rgb;
#else
        color = baseColor.rgb;
#endif
        color = srgb_to_linear(color);
        color *= sky_hdr_scale;
    }
    else
    {
        // legacy shaders are still writng sRGB to gbuffer
        baseColor.rgb = srgb_to_linear(baseColor.rgb);

        spec.rgb = srgb_to_linear(spec.rgb);

        float raw_da      = dot(gb.normal, light_dir.xyz);
        float da          = clamp(raw_da, 0.0, 1.0);

        vec3 irradiance = amblit;
        vec3 glossenv = vec3(0);
        vec3 legacyenv = vec3(0);

        sampleReflectionProbesLegacy(irradiance, glossenv, legacyenv, tc, pos.xyz, gb.normal, spec.a, envIntensity, false, amblit_linear);

        adjustIrradiance(irradiance, ambocc);

        // apply lambertian IBL only (see pbrIbl)
        color.rgb = irradiance;

        if (classic_mode > 0)
        {
            vec3 diffuse_factor = getSSSDiffuseFactor(raw_da, wrapStrength);
            diffuse_factor += getSSSTransmission(raw_da, dot(gb.normal, -normalize(pos.xyz)), wrapStrength);
            vec3 sun_contrib = min(pow(diffuse_factor, vec3(1.2)), vec3(scol));

            color.rgb = srgb_to_linear(color.rgb * 0.9 + (linear_to_srgb(sun_contrib) * sunlit_linear * 0.7));
            sunlit_linear = srgb_to_linear(sunlit_linear);
        }
        else
        {
            vec3 diffuse_factor = getSSSDiffuseFactor(raw_da, wrapStrength);
            diffuse_factor += getSSSTransmission(raw_da, dot(gb.normal, -normalize(pos.xyz)), wrapStrength);
            vec3 sun_contrib = min(diffuse_factor, vec3(scol)) * sunlit_linear;
            color.rgb += sun_contrib;
        }

        color.rgb *= baseColor.rgb;
        sssDiffuseLighting = color.rgb;

        vec3 refnormpersp = reflect(pos.xyz, gb.normal);

        if (spec.a > 0.0)
        {
            vec3  lv = light_dir.xyz;
            vec3  h, l, v = -normalize(pos.xyz);
            float nh, nl, nv, vh, lightDist;
            vec3 n = gb.normal;
            calcHalfVectors(lv, n, v, h, l, nh, nl, nv, vh, lightDist);

            if (nl > 0.0 && nh > 0.0)
            {
                float lit = min(nl*6.0, 1.0);

                float sa = nh;
                float fres = pow(1 - vh, 5) * 0.4+0.5;
                float gtdenom = 2 * nh;
                float gt = max(0,(min(gtdenom * nv / vh, gtdenom * nl / vh)));

                scol *= fres*texture(lightFunc, vec2(nh, spec.a)).r*gt/(nh*nl);
                color.rgb += lit*scol*sunlit_linear.rgb*spec.rgb;
            }

            // add radiance map
            applyGlossEnv(color, glossenv, spec, pos.xyz, gb.normal);

        }

        color.rgb = mix(color.rgb, baseColor.rgb, baseColor.a);
        sssDiffuseLighting *= 1.0 - baseColor.a;

        if (envIntensity > 0.0)
        {  // add environment map
            applyLegacyEnv(color, legacyenv, spec, pos.xyz, gb.normal, envIntensity);
        }
   }

    //color.r = classic_mode > 0 ? 1.0 : 0.0;
    float final_scale = 1;
    if (classic_mode > 0)
        final_scale = 1.1;

    frag_color.rgb = clampHDRRange(color.rgb * final_scale); //output linear since local lights will be added to this shader's results
    frag_color.a = 0.0;
    sss_diffuse = vec4(0.0);
    if (useSSSScreenDiffusion(sssStrength))
    {
        sss_diffuse.rgb = clampHDRRange(sssDiffuseLighting * final_scale);
    }
}
