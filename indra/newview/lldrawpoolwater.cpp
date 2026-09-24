/**
 * @file lldrawpoolwater.cpp
 * @brief LLDrawPoolWater class implementation
 *
 * $LicenseInfo:firstyear=2002&license=viewerlgpl$
 * Second Life Viewer Source Code
 * Copyright (C) 2010, Linden Research, Inc.
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

#include "llviewerprecompiledheaders.h"
#include <vector>
#include "llfeaturemanager.h"
#include "lldrawpoolwater.h"

#include "llviewercontrol.h"
#include "lldir.h"
#include "llerror.h"
#include "m3math.h"
#include "llrender.h"

#include "llagent.h"        // for gAgent for getRegion for getWaterHeight
#include "llcubemap.h"
#include "lldrawable.h"
#include "llface.h"
#include "llsky.h"
#include "llviewertexturelist.h"
#include "llviewerregion.h"
#include "llvoavatarself.h"
#include "llvowater.h"
#include "llworld.h"
#include "pipeline.h"
#include "llviewershadermgr.h"
#include "llenvironment.h"
#include "llsettingssky.h"
#include "llsettingswater.h"

bool LLDrawPoolWater::sSkipScreenCopy = false;
bool LLDrawPoolWater::sNeedsReflectionUpdate = true;
bool LLDrawPoolWater::sNeedsDistortionUpdate = true;
F32 LLDrawPoolWater::sWaterFogEnd = 0.f;

extern bool gCubeSnapshot;

namespace
{
constexpr S32 MAX_WATER_WAKES = 12;
constexpr F64 WATER_WAKE_LIFETIME = 2.5;
constexpr F64 WATER_WAKE_SPACING = 0.5;

struct WaterWake
{
    LLVector3d position;
    F64 born;
    F32 strength;
};

std::vector<WaterWake> sWaterWakes;
LLVector3d sWakeLastPosition;
F64 sWakeLastTime = -1.0;
F64 sWakeDistance = 0.0;
U32 sWakeFrame = ~0U;

void updateLocalWaterWake(F64 now)
{
    const U32 frame = LLFrameTimer::getFrameCount();
    if (sWakeFrame == frame) return;
    sWakeFrame = frame;
    while (!sWaterWakes.empty() && now - sWaterWakes.front().born >= WATER_WAKE_LIFETIME)
        sWaterWakes.erase(sWaterWakes.begin());

    if (gCubeSnapshot || !isAgentAvatarValid() || !gAgent.getRegion() || gAgentAvatarp->isSitting())
    {
        sWakeLastTime = -1.0;
        return;
    }

    const LLVector3d position = gAgentAvatarp->getPositionGlobal();
    const F32 water_height = gAgent.getRegion()->getWaterHeight();
    const F32 depth = water_height - (F32)position.mdV[VZ];
    const F32 ground_depth = water_height - LLWorld::getInstance()->resolveLandHeightGlobal(position);
    // Wading and surface swimming disturb the water; flying over it and deep
    // dives do not. The simulator's mean water plane is the visual reference.
    if (depth < -0.4f || depth > 1.2f || ground_depth < 0.15f ||
        (gAgent.getFlying() && depth < 0.15f))
    {
        sWakeLastTime = -1.0;
        return;
    }

    const LLVector3d delta = position - sWakeLastPosition;
    const F64 traveled = sqrt(delta.mdV[VX] * delta.mdV[VX] + delta.mdV[VY] * delta.mdV[VY]);
    const F64 dt = now - sWakeLastTime;
    if (sWakeLastTime < 0.0 || dt <= 0.0 || dt > 0.5 || traveled > 4.0 ||
        fabs(delta.mdV[VZ]) > 2.0)
    {
        if (sWakeLastTime >= 0.0 && traveled > 4.0) sWaterWakes.clear();
        sWakeDistance = 0.0;
    }
    else if (traveled / dt >= 0.45)
    {
        const F32 strength = llclamp((F32)(traveled / dt / 2.5), 0.25f, 1.0f);
        for (F64 next = WATER_WAKE_SPACING - sWakeDistance; next <= traveled; next += WATER_WAKE_SPACING)
        {
            sWaterWakes.push_back({sWakeLastPosition + delta * (next / traveled),
                now - dt * (1.0 - next / traveled), strength});
            if (sWaterWakes.size() > MAX_WATER_WAKES) sWaterWakes.erase(sWaterWakes.begin());
        }
        sWakeDistance = fmod(sWakeDistance + traveled, WATER_WAKE_SPACING);
    }
    else
    {
        sWakeDistance = 0.0;
    }
    sWakeLastPosition = position;
    sWakeLastTime = now;
}
}

LLDrawPoolWater::LLDrawPoolWater() : LLFacePool(POOL_WATER)
{
    sWaterWakes.clear();
    sWakeLastTime = -1.0;
    sWakeDistance = 0.0;
    sWakeFrame = ~0U;
}

LLDrawPoolWater::~LLDrawPoolWater()
{
}

void LLDrawPoolWater::setTransparentTextures(const LLUUID& transparentTextureId, const LLUUID& nextTransparentTextureId)
{
    LLSettingsWater::ptr_t pwater = LLEnvironment::instance().getCurrentWater();
    mWaterImagep[0] = LLViewerTextureManager::getFetchedTexture(!transparentTextureId.isNull() ? transparentTextureId : pwater->GetDefaultTransparentTextureAssetId());
    mWaterImagep[1] = LLViewerTextureManager::getFetchedTexture(!nextTransparentTextureId.isNull() ? nextTransparentTextureId : (!transparentTextureId.isNull() ? transparentTextureId : pwater->GetDefaultTransparentTextureAssetId()));
    mWaterImagep[0]->addTextureStats(1024.f*1024.f);
    mWaterImagep[1]->addTextureStats(1024.f*1024.f);
}

void LLDrawPoolWater::setOpaqueTexture(const LLUUID& opaqueTextureId)
{
    LLSettingsWater::ptr_t pwater = LLEnvironment::instance().getCurrentWater();
    mOpaqueWaterImagep = LLViewerTextureManager::getFetchedTexture(opaqueTextureId);
    mOpaqueWaterImagep->addTextureStats(1024.f*1024.f);
}

void LLDrawPoolWater::setNormalMaps(const LLUUID& normalMapId, const LLUUID& nextNormalMapId)
{
    LLSettingsWater::ptr_t pwater = LLEnvironment::instance().getCurrentWater();
    mWaterNormp[0] = LLViewerTextureManager::getFetchedTexture(!normalMapId.isNull() ? normalMapId : pwater->GetDefaultWaterNormalAssetId());
    mWaterNormp[1] = LLViewerTextureManager::getFetchedTexture(!nextNormalMapId.isNull() ? nextNormalMapId : (!normalMapId.isNull() ? normalMapId : pwater->GetDefaultWaterNormalAssetId()));
    mWaterNormp[0]->addTextureStats(1024.f*1024.f);
    mWaterNormp[1]->addTextureStats(1024.f*1024.f);
}

void LLDrawPoolWater::prerender()
{
    mShaderLevel = LLCubeMap::sUseCubeMaps ? LLViewerShaderMgr::instance()->getShaderLevel(LLViewerShaderMgr::SHADER_WATER) : 0;
}

S32 LLDrawPoolWater::getNumPostDeferredPasses()
{
    if (LLViewerCamera::getInstance()->getOrigin().mV[2] < 1024.f)
    {
        return 1;
    }

    return 0;
}

void LLDrawPoolWater::beginPostDeferredPass(S32 pass)
{
    LL_PROFILE_GPU_ZONE("water beginPostDeferredPass")
    gGL.setColorMask(true, true);
    updateWaveField();

    if (LLPipeline::sRenderTransparentWater)
    {
        // copy framebuffer contents so far to a texture to be used for
        // reflections and refractions
        LLGLDepthTest depth(GL_TRUE, GL_TRUE, GL_ALWAYS);

        LLRenderTarget& src = gPipeline.mRT->screen;
        LLRenderTarget& depth_src = gPipeline.mRT->deferredScreen;
        LLRenderTarget& dst = gPipeline.mWaterDis;

        dst.bindTarget();
        gCopyDepthProgram.bind();

        S32 diff_map = gCopyDepthProgram.getTextureChannel(LLShaderMgr::DIFFUSE_MAP);
        S32 depth_map = gCopyDepthProgram.getTextureChannel(LLShaderMgr::DEFERRED_DEPTH);

        gGL.getTexUnit(diff_map)->bind(&src);
        gGL.getTexUnit(depth_map)->bind(&depth_src, true);

        gPipeline.mScreenTriangleVB->setBuffer();
        gPipeline.mScreenTriangleVB->drawArrays(LLRender::TRIANGLES, 0, 3);

        dst.flush();
    }
}

void LLDrawPoolWater::updateWaveField()
{
    LL_PROFILE_GPU_ZONE("water wave field");
    const F64 now = LLFrameTimer::getElapsedSeconds();
    updateLocalWaterWake(now);
    const F64 dt = mWaveLastTime < 0.0 ? 0.0 : llmax(0.0, now - mWaveLastTime);
    mWaveLastTime = now;
    static LLCachedControl<F32> wind_speed(gSavedSettings, "RenderWaterWindSpeed", 1.f);
    const F64 wave_dt = dt * llclamp(wind_speed(), 0.f, 3.f);
    mWaveDetailTime += wave_dt;
    static LLCachedControl<bool> enabled(gSavedSettings, "RenderWaterProceduralWaves", true);
    if (!enabled || !gPipeline.mWaterWaves.isComplete()) return;

    const auto water = LLEnvironment::instance().getCurrentWater();
    F32 speed = water->getWave1Dir().length();
    if (speed < 0.0001f) speed = water->getWave2Dir().length();
    // Integrate speed changes instead of multiplying absolute time: EEP changes
    // do not reset phase, and a stationary preset freezes the wave field.
    mWaveTime += wave_dt * llclamp(speed, 0.f, 3.f);
    const U32 frame = LLFrameTimer::getFrameCount();
    if (gPipeline.mWaterWavesFrame == frame) return;

    static LLCachedControl<F32> crossing(gSavedSettings, "RenderWaterCrossSwellStrength", 0.25f);
    static LLCachedControl<F32> wave_scale(gSavedSettings, "RenderWaterWaveScale", 1.f);
    LLGLDisable blend(GL_BLEND);
    LLGLDisable cull(GL_CULL_FACE);
    LLGLDisable scissor(GL_SCISSOR_TEST);
    LLGLDepthTest depth(GL_FALSE, GL_FALSE);
    // This also runs before deferred lighting, where scene glow/alpha writes
    // are normally disabled. Alpha here is the chop spectrum's imaginary part
    // (and later its Y slope), so every FFT pass must write all four channels.
    gGL.flush();
    GLboolean color_mask[4];
    glGetBooleanv(GL_COLOR_WRITEMASK, color_mask);
    gGL.setColorMask(true, true);
    // Both complex height spectra are generated together, then transformed on
    // the GPU. FP32 scratch buffers avoid rounding errors during the butterflies.
    gPipeline.mWaterWaveScratch[0].bindTarget();
    gWaterWaveProgram.bind();
    gWaterWaveProgram.uniform1f(LLStaticHashedString("water_wave_time"), (F32)fmod(mWaveTime, 1200.0));
    gWaterWaveProgram.uniform1f(LLStaticHashedString("water_cross_swell"), llclamp(crossing(), 0.f, 3.f));
    gWaterWaveProgram.uniform1f(LLStaticHashedString("water_wave_scale"), llclamp(wave_scale(), 0.01f, 2.f));
    gPipeline.mScreenTriangleVB->setBuffer();
    gPipeline.mScreenTriangleVB->drawArrays(LLRender::TRIANGLES, 0, 3);
    gPipeline.mWaterWaveScratch[0].flush();
    gWaterWaveProgram.unbind();

    U32 source = 0;
    gWaterWaveFFTProgram.bind();
    for (S32 axis = 0; axis < 2; ++axis)
    {
        gWaterWaveFFTProgram.uniform1i(LLStaticHashedString("water_fft_axis"), axis);
        for (S32 stage = 1; stage <= 8; ++stage)
        {
            gPipeline.mWaterWaveScratch[1-source].bindTarget();
            gWaterWaveFFTProgram.bindTexture(LLShaderMgr::WATER_WAVE_SPECTRUM,
                &gPipeline.mWaterWaveScratch[source], false, LLTexUnit::TFO_POINT);
            gWaterWaveFFTProgram.uniform1i(LLStaticHashedString("water_fft_stage"), stage);
            gPipeline.mScreenTriangleVB->setBuffer();
            gPipeline.mScreenTriangleVB->drawArrays(LLRender::TRIANGLES, 0, 3);
            gWaterWaveFFTProgram.unbindTexture(LLShaderMgr::WATER_WAVE_SPECTRUM);
            gPipeline.mWaterWaveScratch[1-source].flush();
            source = 1-source;
        }
    }
    gWaterWaveFFTProgram.unbind();

    gPipeline.mWaterWaves.bindTarget();
    gWaterWaveResolveProgram.bind();
    gWaterWaveResolveProgram.uniform1i(LLStaticHashedString("water_wave_resolve_height"), 0);
    gWaterWaveResolveProgram.bindTexture(LLShaderMgr::WATER_WAVE_SPECTRUM,
        &gPipeline.mWaterWaveScratch[source], false, LLTexUnit::TFO_POINT);
    gPipeline.mScreenTriangleVB->setBuffer();
    gPipeline.mScreenTriangleVB->drawArrays(LLRender::TRIANGLES, 0, 3);
    gWaterWaveResolveProgram.unbindTexture(LLShaderMgr::WATER_WAVE_SPECTRUM);
    gPipeline.mWaterWaves.flush();
    // Preserve the real FFT heights separately; slope channels remain unchanged
    // for reflections and caustics. Each texture receives its own mip chain.
    gPipeline.mWaterHeights.bindTarget();
    gWaterWaveResolveProgram.uniform1i(LLStaticHashedString("water_wave_resolve_height"), 1);
    gWaterWaveResolveProgram.bindTexture(LLShaderMgr::WATER_WAVE_SPECTRUM,
        &gPipeline.mWaterWaveScratch[source], false, LLTexUnit::TFO_POINT);
    gPipeline.mScreenTriangleVB->setBuffer();
    gPipeline.mScreenTriangleVB->drawArrays(LLRender::TRIANGLES, 0, 3);
    gWaterWaveResolveProgram.unbindTexture(LLShaderMgr::WATER_WAVE_SPECTRUM);
    gPipeline.mWaterHeights.flush();
    gWaterWaveResolveProgram.unbind();
    gGL.setColorMask(color_mask[0], color_mask[1], color_mask[2], color_mask[3]);
    gPipeline.mWaterWavesFrame = frame;
}

void LLDrawPoolWater::prepareDisplacementDepth()
{
    static LLCachedControl<bool> enabled(gSavedSettings, "RenderWaterDisplacementEnabled", true);
    static LLCachedControl<F32> displacement(gSavedSettings, "RenderWaterDisplacement", 1.f);
    static LLCachedControl<F32> damping(gSavedSettings, "RenderWaterShallowDamping", 1.f);
    static LLCachedControl<bool> waves(gSavedSettings, "RenderWaterProceduralWaves", true);
    if (!enabled || !waves || displacement() <= 0.f || damping() <= 0.f || gCubeSnapshot ||
        !gPipeline.mWaterGeometryDepth.isComplete()) return;
    const U32 frame = LLFrameTimer::getFrameCount();
    if (gPipeline.mWaterGeometryDepthFrame == frame) return;
    // Freeze opaque scene depth before either water pass. Sampling the live
    // framebuffer depth while displacing its geometry would create feedback.
    gGL.flush();
    GLboolean mask[4];
    glGetBooleanv(GL_COLOR_WRITEMASK, mask);
    gGL.setColorMask(true, true);
    LLGLDisable blend(GL_BLEND), cull(GL_CULL_FACE), scissor(GL_SCISSOR_TEST);
    LLGLDepthTest depth(GL_FALSE, GL_FALSE);
    gPipeline.mWaterGeometryDepth.bindTarget();
    gCopyProgram.bind();
    gCopyProgram.bindTexture(LLShaderMgr::DIFFUSE_MAP, &gPipeline.mRT->deferredScreen, true, LLTexUnit::TFO_POINT);
    gPipeline.mScreenTriangleVB->setBuffer();
    gPipeline.mScreenTriangleVB->drawArrays(LLRender::TRIANGLES, 0, 3);
    gCopyProgram.unbindTexture(LLShaderMgr::DIFFUSE_MAP);
    gPipeline.mWaterGeometryDepth.flush();
    gCopyProgram.unbind();
    gGL.setColorMask(mask[0], mask[1], mask[2], mask[3]);
    gPipeline.mWaterGeometryDepthFrame = frame;
}

void LLDrawPoolWater::bindWaveField(LLGLSLShader& shader)
{
    if (shader.getUniformLocation(LLStaticHashedString("water_wake_count")) >= 0)
    {
        F32 wakes[MAX_WATER_WAKES * 4];
        const LLVector3d origin = gAgent.getPosGlobalFromAgent(LLVector3::zero);
        const F64 now = LLFrameTimer::getElapsedSeconds();
        S32 count = 0;
        for (const WaterWake& wake : sWaterWakes)
        {
            const F64 age = now - wake.born;
            if (age < 0.0 || age >= WATER_WAKE_LIFETIME) continue;
            wakes[4 * count] = (F32)(wake.position.mdV[VX] - origin.mdV[VX]);
            wakes[4 * count + 1] = (F32)(wake.position.mdV[VY] - origin.mdV[VY]);
            wakes[4 * count + 2] = (F32)age;
            wakes[4 * count + 3] = wake.strength;
            ++count;
        }
        shader.uniform1i(LLStaticHashedString("water_wake_count"), count);
        if (count) shader.uniform4fv(LLStaticHashedString("water_wakes"), count, wakes);
    }
    static LLCachedControl<bool> procedural(gSavedSettings, "RenderWaterProceduralWaves", true);
    static LLCachedControl<F32> wave_strength(gSavedSettings, "RenderWaterWaveStrength", 1.f);
    static LLCachedControl<F32> wave_scale(gSavedSettings, "RenderWaterWaveScale", 1.f);
    const F32 wave_size = llclamp(wave_scale(), 0.01f, 2.f);
    const bool wave_field_ready = procedural && gPipeline.mWaterWavesFrame != ~0U;
    shader.uniform1i(LLStaticHashedString("water_procedural_waves"), wave_field_ready ? 1 : 0);
    shader.uniform1f(LLStaticHashedString("water_wave_strength"), llclamp(wave_strength(), 0.f, 3.f));
    shader.uniform1f(LLStaticHashedString("water_wave_scale"), wave_size);
    if (wave_field_ready)
    {
        const S32 channel = shader.bindTexture(LLShaderMgr::WATER_WAVE_SLOPES,
            &gPipeline.mWaterWaves, false, LLTexUnit::TFO_ANISOTROPIC);
        if (channel >= 0) gGL.getTexUnit(channel)->setTextureAddressMode(LLTexUnit::TAM_WRAP);
    }
    static LLCachedControl<F32> displacement(gSavedSettings, "RenderWaterDisplacement", 1.f);
    static LLCachedControl<bool> displaced(gSavedSettings, "RenderWaterDisplacementEnabled", true);
    static LLCachedControl<F32> distance(gSavedSettings, "RenderWaterDisplacementDistance", 64.f);
    const F32 height_scale = wave_field_ready && displaced ? llclamp(displacement(), 0.f, 5.f) : 0.f;
    shader.uniform1f(LLStaticHashedString("water_displacement"), height_scale);
    shader.uniform1f(LLStaticHashedString("water_displacement_distance"), llclamp(distance(), 8.f, 128.f));
    static LLCachedControl<F32> damping(gSavedSettings, "RenderWaterShallowDamping", 1.f);
    const bool has_depth = !gCubeSnapshot && gPipeline.mWaterGeometryDepthFrame == LLFrameTimer::getFrameCount();
    shader.uniform1f(LLStaticHashedString("water_shallow_damping"), has_depth ? llclamp(damping(), 0.f, 1.f) : 0.f);
    if (height_scale > 0.f && has_depth)
        shader.bindTexture(LLShaderMgr::WATER_GEOMETRY_DEPTH, &gPipeline.mWaterGeometryDepth, false, LLTexUnit::TFO_POINT);
    if (height_scale > 0.f)
    {
        const S32 channel = shader.bindTexture(LLShaderMgr::WATER_WAVE_HEIGHTS,
            &gPipeline.mWaterHeights, false, LLTexUnit::TFO_TRILINEAR);
        if (channel >= 0) gGL.getTexUnit(channel)->setTextureAddressMode(LLTexUnit::TAM_WRAP);
    }
    const LLVector3d mesh_center = LLVOWater::getMeshCenter();
    const LLVector3 mesh_center_agent = gAgent.getPosAgentFromGlobal(mesh_center);
    shader.uniform2f(LLStaticHashedString("water_mesh_center"), mesh_center_agent.mV[0], mesh_center_agent.mV[1]);
    const auto pwater = LLEnvironment::instance().getCurrentWater();
    shader.uniform3fv(LLShaderMgr::WATER_NORM_SCALE, 1, pwater->getNormalScale().mV);
    LLVector2 direction = pwater->getWave1Dir();
    if (direction.lengthSquared() < 0.000001f) direction = pwater->getWave2Dir();
    if (direction.lengthSquared() < 0.000001f) direction = LLVector2(1.f, 0.f);
    direction.normalize();
    // EEP scrolling advances UVs; the visible pattern moves opposite that vector.
    direction *= -1.f;
    shader.uniform2fv(LLStaticHashedString("water_wave_direction"), 1, direction.mV);
    const LLVector3d origin = gAgent.getPosGlobalFromAgent(LLVector3::zero);
    // Scale and reduce the rotated global origin in double precision, so even
    // tiny waves stay continuous across regions without huge shader coordinates.
    shader.uniform2f(LLStaticHashedString("water_wave_origin"),
        (F32)fmod((origin.mdV[0]*direction.mV[0] + origin.mdV[1]*direction.mV[1]) / wave_size, 256.0),
        (F32)fmod((-origin.mdV[0]*direction.mV[1] + origin.mdV[1]*direction.mV[0]) / wave_size, 256.0));

}

void LLDrawPoolWater::renderPostDeferred(S32 pass)
{
    LL_PROFILE_ZONE_SCOPED_CATEGORY_DRAWPOOL;
    LL_PROFILE_GPU_ZONE("forward water");
    LLGLDisable blend(GL_BLEND);

    gGL.setColorMask(true, true);

    LLColor3 light_diffuse(0, 0, 0);

    LLEnvironment& environment = LLEnvironment::instance();
    LLSettingsWater::ptr_t pwater = environment.getCurrentWater();
    LLSettingsSky::ptr_t   psky   = environment.getCurrentSky();
    LLVector3              light_dir       = environment.getLightDirection();
    bool                   sun_up          = environment.getIsSunUp();
    bool                   moon_up         = environment.getIsMoonUp();
    bool                   has_normal_mips = gSavedSettings.getBOOL("RenderWaterMipNormal");
    bool                   underwater      = LLViewerCamera::getInstance()->cameraUnderWater();
    LLColor4               fog_color       = LLColor4(pwater->getWaterFogColor(), 0.f);
    LLColor3               fog_color_linear = linearColor3(fog_color);

    if (sun_up)
    {
        light_diffuse += psky->getSunlightColor();
    }
    // moonlight is several orders of magnitude less bright than sunlight,
    // so only use this color when the moon alone is showing
    else if (moon_up)
    {
        light_diffuse += psky->getMoonlightColor();
    }

    // Apply magic numbers translating light direction into intensities
    light_dir.normalize();
    F32 ground_proj_sq = light_dir.mV[0] * light_dir.mV[0] + light_dir.mV[1] * light_dir.mV[1];
    if (0.f < light_diffuse.normalize())  // Normalizing a color? Puzzling...
    {
        light_diffuse *= (1.5f + (6.f * ground_proj_sq));
    }

    LLTexUnit::eTextureFilterOptions filter_mode = has_normal_mips ? LLTexUnit::TFO_ANISOTROPIC : LLTexUnit::TFO_POINT;

    LLColor4      specular(sun_up ? psky->getSunlightColor() : psky->getMoonlightColor());
    F32           phase_time = (F32)(mWaveDetailTime * 0.5);
    LLGLSLShader *shader     = nullptr;

    // One pass, one of two shaders.  Void water and region water share state.
    // There isn't a good reason anymore to really have void water run in a separate pass.
    // It also just introduced a bunch of weird state consistency stuff that we really don't need.
    // Not to mention, re-binding the the same shader and state for that shader is kind of wasteful.
    // - Geenz 2025-02-11
    // select shader
    if (underwater)
    {
        shader = &gUnderWaterProgram;
    }
    else
    {
        shader = &gWaterProgram;
    }

    gPipeline.bindDeferredShader(*shader, nullptr, &gPipeline.mWaterDis);

    bindWaveField(*shader);

    LLViewerTexture* tex_a = mWaterNormp[0];
    LLViewerTexture* tex_b = mWaterNormp[1];

    F32 blend_factor = (F32)pwater->getBlendFactor();

    if (tex_a && (!tex_b || (tex_a == tex_b)))
    {
        tex_a->setFilteringOption(filter_mode);
        shader->bindTexture(LLViewerShaderMgr::BUMP_MAP, tex_a);
        blend_factor = 0; // only one tex provided, no blending
    }
    else if (tex_b && !tex_a)
    {
        tex_b->setFilteringOption(filter_mode);
        shader->bindTexture(LLViewerShaderMgr::BUMP_MAP, tex_b);
        blend_factor = 0; // only one tex provided, no blending
    }
    else if (tex_b != tex_a)
    {
        tex_a->setFilteringOption(filter_mode);
        tex_b->setFilteringOption(filter_mode);
        shader->bindTexture(LLViewerShaderMgr::BUMP_MAP, tex_a);
        shader->bindTexture(LLViewerShaderMgr::BUMP_MAP2, tex_b);
    }

    shader->bindTexture(LLShaderMgr::WATER_EXCLUSIONTEX, &gPipeline.mWaterExclusionMask);

    shader->uniform1f(LLShaderMgr::BLEND_FACTOR, blend_factor);

    F32      fog_density = pwater->getModifiedWaterFogDensity(underwater);

    shader->bindTexture(LLShaderMgr::WATER_SCREENTEX, &gPipeline.mWaterDis);

    if (mShaderLevel == 1)
    {
        fog_color.mV[VALPHA] = (F32)(log(fog_density) / log(2));
    }

    F32 water_height = environment.getWaterHeight();
    F32 camera_height = LLViewerCamera::getInstance()->getOrigin().mV[2];
    shader->uniform1f(LLShaderMgr::WATER_WATERHEIGHT, camera_height - water_height);
    shader->uniform1f(LLShaderMgr::WATER_TIME, phase_time);
    shader->uniform3fv(LLShaderMgr::WATER_EYEVEC, 1, LLViewerCamera::getInstance()->getOrigin().mV);

    shader->uniform3fv(LLShaderMgr::WATER_SPECULAR, 1, light_diffuse.mV);

    shader->uniform2fv(LLShaderMgr::WATER_WAVE_DIR1, 1, pwater->getWave1Dir().mV);
    shader->uniform2fv(LLShaderMgr::WATER_WAVE_DIR2, 1, pwater->getWave2Dir().mV);

    shader->uniform3fv(LLShaderMgr::WATER_LIGHT_DIR, 1, light_dir.mV);

    shader->uniform3fv(LLShaderMgr::WATER_NORM_SCALE, 1, pwater->getNormalScale().mV);
    shader->uniform1f(LLShaderMgr::WATER_FRESNEL_SCALE, pwater->getFresnelScale());
    shader->uniform1f(LLShaderMgr::WATER_FRESNEL_OFFSET, pwater->getFresnelOffset());
    static LLCachedControl<F32> roughness_scale(gSavedSettings, "RenderWaterRoughnessScale", 1.f);
    static LLCachedControl<F32> reflection_strength(gSavedSettings, "RenderWaterReflectionStrength", 1.f);
    shader->uniform1f(LLShaderMgr::WATER_BLUR_MULTIPLIER,
        fmaxf(0, pwater->getBlurMultiplier()) * 2);
    static LLCachedControl<F32> refraction_strength(gSavedSettings, "RenderWaterRefractionStrength", 1.f);
    shader->uniform1f(LLStaticHashedString("water_refraction_strength"), llclamp(refraction_strength(), 0.f, 2.f));
    static LLCachedControl<S32> probe_level(gSavedSettings, "RenderReflectionProbeLevel", 0);
    shader->uniform1i(LLStaticHashedString("water_refraction_fog"),
        LLPipeline::RenderDeferredAtmospheric && !(gCubeSnapshot && probe_level == 0) ? 1 : 0);
    shader->uniform1f(LLStaticHashedString("water_roughness_scale"), llclamp(roughness_scale(), 0.f, 3.f));
    shader->uniform1f(LLStaticHashedString("water_reflection_strength"), llclamp(reflection_strength(), 0.f, 1.f));
    static LLCachedControl<bool> local_reflections(gSavedSettings, "RenderWaterLocalReflections", true);
    shader->uniform1i(LLStaticHashedString("water_local_reflections"), local_reflections ? 1 : 0);

    static LLStaticHashedString s_exposure("exposure");
    static LLStaticHashedString tonemap_mix("tonemap_mix");
    static LLStaticHashedString tonemap_type("tonemap_type");

    static LLCachedControl<F32> exposure(gSavedSettings, "RenderExposure", 1.f);

    F32 e = llclamp(exposure(), 0.5f, 4.f);

    static LLCachedControl<bool> should_auto_adjust(gSavedSettings, "RenderSkyAutoAdjustLegacy", false);

    shader->uniform1f(s_exposure, e);
    static LLCachedControl<U32> tonemap_type_setting(gSavedSettings, "RenderTonemapType", 0U);
    shader->uniform1i(tonemap_type, tonemap_type_setting);
    shader->uniform1f(tonemap_mix, psky->getTonemapMix(should_auto_adjust()));

    F32 sunAngle = llmax(0.f, light_dir.mV[1]);
    F32 scaledAngle = 1.f - sunAngle;

    shader->uniform1i(LLShaderMgr::SUN_UP_FACTOR, sun_up ? 1 : 0);

    // SL-15861 This was changed from getRotatedLightNorm() as it was causing
    // lightnorm in shaders\class1\windlight\atmosphericsFuncs.glsl in have inconsistent additive lighting for 180 degrees of the FOV.
    LLVector4 rotated_light_direction = LLEnvironment::instance().getClampedLightNorm();
    shader->uniform3fv(LLViewerShaderMgr::LIGHTNORM, 1, rotated_light_direction.mV);

    shader->uniform3fv(LLShaderMgr::WL_CAMPOSLOCAL, 1, LLViewerCamera::getInstance()->getOrigin().mV);

    if (LLViewerCamera::getInstance()->cameraUnderWater())
    {
        shader->uniform1f(LLShaderMgr::WATER_REFSCALE, pwater->getScaleBelow());
    }
    else
    {
        shader->uniform1f(LLShaderMgr::WATER_REFSCALE, pwater->getScaleAbove());
    }

    LLGLDisable cullface(GL_CULL_FACE);

    // Only push the water planes once.
    // Previously we did this twice: once for void water and one for region water.
    // However, the void water and region water shaders are the same exact shader.
    // They also had the same exact state with the sole exception setting an edge water flag.
    // That flag was not actually used anywhere in the shaders.
    // - Geenz 2025-02-11
    pushWaterPlanes(0);

    // clean up
    shader->unbindTexture(LLShaderMgr::WATER_WAVE_SLOPES);
    gPipeline.unbindDeferredShader(*shader);

    gGL.setColorMask(true, false);
}

void LLDrawPoolWater::pushWaterPlanes(int pass)
{
    LLVOWater* water = nullptr;
    for (LLFace* const& face : mDrawFace)
    {
        water = static_cast<LLVOWater*>(face->getViewerObject());

        water->updateMeshLOD();
        water->renderSurface();

        // Note non-void water being drawn, updates required
        // Previously we had some logic to determine if this pass was also our water edge pass.
        // Now we only have one pass.  Check if we're doing a region water plane or void water plane.
        // - Geenz 2025-02-11
        if (!water->getIsEdgePatch())
        {
            sNeedsReflectionUpdate = true;
            sNeedsDistortionUpdate = true;
        }
    }
}

LLViewerTexture *LLDrawPoolWater::getDebugTexture()
{
    return LLViewerTextureManager::getFetchedTexture(IMG_SMOKE);
}

LLColor3 LLDrawPoolWater::getDebugColor() const
{
    return LLColor3(0.f, 1.f, 1.f);
}
