/**
 * @file llfloaterprismwelcome.cpp
 * @brief First-login welcome and optional Prism defaults
 *
 * $LicenseInfo:firstyear=2020&license=viewerlgpl$
 * Second Life Viewer Source Code
 * Copyright (C) 2020, Linden Research, Inc.
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
#include "llfloaterprismwelcome.h"

#include "llbutton.h"
#include "llcheckboxctrl.h"
#include "llfloaterreg.h"
#include "llpresetsmanager.h"
#include "llsdutil.h"
#include "llsdutil_math.h"
#include "llversioninfo.h"
#include "llviewercontrol.h"
#include "llviewershadermgr.h"
#include "pipeline.h"

// These are Prism's added effects. Keep legacy water/graphics controls outside
// the reset, and ignore session-only diagnostics. New effect controls are
// picked up automatically; settings.xml remains the source of defaults.
struct PrismGraphicsDefaults : LLControlGroup::ApplyFunctor
{
    LLSD defaults = LLSD::emptyMap();
    LLSD saved = LLSD::emptyMap();

    static LLSD comparable(LLControlVariable* control, const LLSD& value)
    {
        // XML booleans can be integers, and sliders round reals to F32.
        if (control->isType(TYPE_BOOLEAN)) return LLSD(value.asBoolean());
        if (control->isType(TYPE_F32)) return LLSD(F64(F32(value.asReal())));
        if (control->isType(TYPE_COL4)) return LLColor4(value).getValue();
        return value;
    }

    void apply(const std::string& name, LLControlVariable* control) override
    {
        // Unknown settings survive in old user files, including this removed mode.
        if (!control->isPersisted() || name == "RenderWater" || name == "RenderWaterMaterials" ||
            name == "RenderWaterMipNormal" || name == "RenderWaterRefResolution" ||
            name == "BoxxySSSFullResolution") return;

        bool included = name == "RenderFSAAType" || name == "RenderGlowMinLuminance" ||
            name == "RenderShadowDetail" || name == "RenderHighPrecisionPostProcess" ||
            name == "RenderChromaticAberrationStrength";
        for (const std::string prefix : { "BoxxySSS", "RenderGTAO", "RenderPCSS", "RenderTAA",
            "RenderWater", "RenderVolumeFog", "RenderBloom", "RenderEyeAdaptation",
            "RenderSSGI", "RenderVolumeCloud", "RenderGroundFog", "RenderPost" })
        {
            included |= name.compare(0, prefix.size(), prefix) == 0;
        }
        if (included)
        {
            defaults[name] = comparable(control, control->getDefault());
            saved[name] = comparable(control, control->getSaveValue());
        }
    }
};

static void record_graphics_defaults(const std::string& version, const LLSD& defaults)
{
    gSavedSettings.setString("PrismGraphicsDefaultsVersion", version);
    gSavedSettings.setLLSD("PrismGraphicsDefaultsSnapshot", defaults);
    gSavedSettings.saveToFile(gSavedSettings.getString("ClientSettingsFile"), true);
}

void LLFloaterPrismWelcome::initializeGraphicsDefaults()
{
    // Hardware detection chooses a quality tier first. Fresh profiles then use
    // the shipped Prism effects before the renderer loads its initial shaders.
    PrismGraphicsDefaults graphics;
    gSavedSettings.applyToAll(&graphics);
    for (const auto& entry : llsd::inMap(graphics.defaults))
    {
        gSavedSettings.getControl(entry.first)->resetToDefault(true);
    }
    record_graphics_defaults(LLVersionInfo::instance().getShortVersion(), graphics.defaults);
    LL_INFOS("RenderInit") << "Applied shipped Prism effect defaults to a fresh settings profile." << LL_ENDL;
}

void LLFloaterPrismWelcome::showIfRequired()
{
    PrismGraphicsDefaults graphics;
    gSavedSettings.applyToAll(&graphics);
    const bool changed_defaults = !llsd_equals(graphics.defaults,
        gSavedSettings.getLLSD("PrismGraphicsDefaultsSnapshot"));
    const bool offer_graphics = changed_defaults && !llsd_equals(graphics.defaults, graphics.saved);
    if (gSavedSettings.getBOOL("PrismWelcomeShown") && !offer_graphics)
    {
        record_graphics_defaults(LLVersionInfo::instance().getShortVersion(), graphics.defaults);
        return;
    }

    LLSD key;
    key["offer_graphics"] = offer_graphics;
    key["defaults"] = graphics.defaults;
    LLFloaterReg::showInstance("prism_welcome", key);
}

LLFloaterPrismWelcome::LLFloaterPrismWelcome(const LLSD& key)
    : LLModalDialog(key)
{
}

bool LLFloaterPrismWelcome::postBuild()
{
    getChild<LLButton>("continue_btn")->setCommitCallback([this](LLUICtrl*, const LLSD&) { onContinue(); });
    setDefaultBtn("continue_btn");
    return true;
}

void LLFloaterPrismWelcome::onOpen(const LLSD& key)
{
    mDefaults = key["defaults"];
    mOfferGraphics = key["offer_graphics"].asBoolean();
    getChild<LLCheckBoxCtrl>("update_graphics")->setValue(false);
    getChildView("update_graphics")->setVisible(mOfferGraphics);
    getChildView("graphics_description")->setVisible(mOfferGraphics);
    getChildView("graphics_ready")->setVisible(!mOfferGraphics);
    getChild<LLCheckBoxCtrl>("try_movement")->setValue(false);
    centerOnScreen();
    LLModalDialog::onOpen(key);
    getChild<LLButton>("continue_btn")->setFocus(true);
}

void LLFloaterPrismWelcome::onContinue()
{
    if (mOfferGraphics && getChild<LLCheckBoxCtrl>("update_graphics")->getValue().asBoolean())
    {
        // Apply all effect settings together, then load the matching shaders once.
        const bool skip_reload = LLViewerShaderMgr::sSkipReload;
        LLViewerShaderMgr::sSkipReload = true;
        for (const auto& entry : llsd::inMap(mDefaults))
        {
            if (LLControlVariable* control = gSavedSettings.getControl(entry.first))
            {
                control->resetToDefault(true);
            }
        }
        LLViewerShaderMgr::sSkipReload = skip_reload;
        LLPipeline::refreshCachedSettings();
        if (!skip_reload) LLViewerShaderMgr::instance()->setShaders();
        gSavedSettings.setString("PresetGraphicActive", "");
        LLPresetsManager::getInstance()->triggerChangeSignal();
    }
    if (getChild<LLCheckBoxCtrl>("try_movement")->getValue().asBoolean())
    {
        for (const char* setting : { "BoxxyDragWorldToTurnAvatar", "BoxxyFaceCameraWhenWalkingBackward",
            "BoxxyCameraRelativeMovement", "BoxxyDynamicShoulderCamera", "BoxxyKeepThirdPersonOnZoom" })
        {
            gSavedSettings.setBOOL(setting, true);
        }
    }
    gSavedSettings.setBOOL("PrismWelcomeShown", true);
    record_graphics_defaults(LLVersionInfo::instance().getShortVersion(), mDefaults);
    closeFloater();
}
