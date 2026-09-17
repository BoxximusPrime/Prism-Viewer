#include "llviewerprecompiledheaders.h"
#include "llfloaterquickprefs.h"

#include "llagent.h"
#include "llcombobox.h"
#include "llenvironment.h"
#include "llinventorymodel.h"
#include "llinventorymodelbackgroundfetch.h"
#include "llsliderctrl.h"
#include "llsettingsvo.h"
#include "llnotificationsutil.h"
#include "llviewercontrol.h"
#include "llviewerinventory.h"
#include "llviewerregion.h"
#include "llvoavatarself.h"

namespace
{
    const char* const GRAPHICS_SETTINGS[] = {
        "RenderShadowResolutionScale", "RenderPCSSQuality", "RenderGTAOQuality"
    };
    const char* const ENV_ROWS[] = {"sky", "water", "day"};
}

LLFloaterQuickPrefs::~LLFloaterQuickPrefs()
{
    gInventory.removeObserver(this);
}

bool LLFloaterQuickPrefs::postBuild()
{
    getChild<LLComboBox>("graphics")->setCommitCallback([this](LLUICtrl*, const LLSD&)
    {
        const bool ultra = getChild<LLComboBox>("graphics")->getValue().asString() == "ultra";
        for (const char* name : GRAPHICS_SETTINGS)
        {
            auto control = gSavedSettings.getControl(name);
            control->setValue(ultra ? LLSD(2) : control->getDefault());
        }
    });
    getChild<LLUICtrl>("name_tags")->setCommitCallback([](LLUICtrl* ctrl, const LLSD&)
    {
        gSavedSettings.setS32("AvatarNameTagMode", ctrl->getValue().asBoolean() ? 1 : 0);
    });
    auto* hover = getChild<LLSliderCtrl>("hover");
    hover->setMinValue(MIN_HOVER_Z);
    hover->setMaxValue(MAX_HOVER_Z);
    hover->setCommitCallback([](LLUICtrl* ctrl, const LLSD&)
    {
        if (isAgentAvatarValid())
            gAgentAvatarp->setHoverOffset(LLVector3(0.f, 0.f, llclamp((F32)ctrl->getValue().asReal(), MIN_HOVER_Z, MAX_HOVER_Z)), false);
    });
    auto save_hover = [this](LLUICtrl*, const LLSD&)
    {
        gSavedPerAccountSettings.setF32("AvatarHoverOffsetZ", getChild<LLSliderCtrl>("hover")->getValueF32());
    };
    hover->setSliderMouseUpCallback(save_hover);
    hover->setSliderEditorCommitCallback(save_hover);
    for (const std::string name : ENV_ROWS)
    {
        getChild<LLComboBox>(name)->setCommitCallback([this, name](LLUICtrl*, const LLSD&) { applyEnvironment(name); });
        getChild<LLUICtrl>(name + "_prev")->setCommitCallback([this, name](LLUICtrl*, const LLSD&) { cycleEnvironment(name, -1); });
        getChild<LLUICtrl>(name + "_next")->setCommitCallback([this, name](LLUICtrl*, const LLSD&) { cycleEnvironment(name, 1); });
    }
    getChild<LLUICtrl>("shared")->setCommitCallback([this](LLUICtrl*, const LLSD&)
    {
        mPending.clear();
        auto& env = LLEnvironment::instance();
        env.clearEnvironment(LLEnvironment::ENV_LOCAL);
        env.setSelectedEnvironment(LLEnvironment::ENV_LOCAL, LLEnvironment::TRANSITION_INSTANT);
    });
    gInventory.addObserver(this);
    return true;
}

void LLFloaterQuickPrefs::onOpen(const LLSD& key)
{
    LLFloater::onOpen(key);
    mInventoryDirty = true;
    if (gInventory.getRootFolderID().notNull())
        LLInventoryModelBackgroundFetch::instance().start();
    getChild<LLSliderCtrl>("hover")->setValue(gSavedPerAccountSettings.getF32("AvatarHoverOffsetZ"));
}

void LLFloaterQuickPrefs::populateEnvironments()
{
    std::map<std::string, LLSD> selected;
    for (const char* name : ENV_ROWS)
    {
        selected[name] = getChild<LLComboBox>(name)->getValue();
        getChild<LLComboBox>(name)->removeall();
    }
    LLInventoryModel::cat_array_t categories;
    LLInventoryModel::item_array_t items;
    gInventory.collectDescendents(gInventory.getRootFolderID(), categories, items, LLInventoryModel::EXCLUDE_TRASH);
    gInventory.collectDescendents(gInventory.getLibraryRootFolderID(), categories, items, LLInventoryModel::EXCLUDE_TRASH);
    for (const auto& item : items)
    {
        if (item->getType() != LLAssetType::AT_SETTINGS || item->getAssetUUID().isNull())
            continue;
        const char* row = nullptr;
        switch (item->getSettingsType())
        {
        case LLSettingsType::ST_SKY: row = "sky"; break;
        case LLSettingsType::ST_WATER: row = "water"; break;
        case LLSettingsType::ST_DAYCYCLE: row = "day"; break;
        default: break;
        }
        if (row)
            getChild<LLComboBox>(row)->add(item->getName(), item->getAssetUUID());
    }
    for (const std::string name : ENV_ROWS)
    {
        auto* combo = getChild<LLComboBox>(name);
        combo->sortByName();
        combo->setValue(selected[name]);
        getChild<LLUICtrl>(name + "_prev")->setEnabled(combo->getItemCount() > 0);
        getChild<LLUICtrl>(name + "_next")->setEnabled(combo->getItemCount() > 0);
    }
    mInventoryDirty = false;
}

void LLFloaterQuickPrefs::applyEnvironment(const std::string& name)
{
    LLUUID asset = getChild<LLComboBox>(name)->getValue().asUUID();
    if (asset.isNull()) return;
    // A newer click wins even when asset fetches complete out of order.
    if (name == "day") mPending.clear();
    else mPending.erase("day");
    const U32 request = ++mRequest;
    mPending[name] = request;
    LLHandle<LLFloater> handle = getHandle();
    LLSettingsVOBase::getSettingsAsset(asset,
        [handle, name, request](LLUUID asset_id, LLSettingsBase::ptr_t settings, S32 status, LLExtStat)
        {
            auto* self = static_cast<LLFloaterQuickPrefs*>(handle.get());
            if (!self) return;
            auto pending = self->mPending.find(name);
            if (pending == self->mPending.end() || pending->second != request) return;
            self->mPending.erase(pending);
            if (!settings || status)
            {
                LLSD args;
                args["NAME"] = asset_id.asString();
                LLNotificationsUtil::add("FailedToFindSettings", args);
                return;
            }
            auto& env = LLEnvironment::instance();
            env.setEnvironment(LLEnvironment::ENV_LOCAL, settings);
            env.setSelectedEnvironment(LLEnvironment::ENV_LOCAL, LLEnvironment::TRANSITION_INSTANT);
        });
}

void LLFloaterQuickPrefs::cycleEnvironment(const std::string& name, S32 direction)
{
    auto* combo = getChild<LLComboBox>(name);
    const S32 count = combo->getItemCount();
    if (!count) return;
    const S32 current = combo->getCurrentIndex();
    combo->setCurrentByIndex(current < 0 ? (direction > 0 ? 0 : count - 1) : (current + direction + count) % count);
    applyEnvironment(name);
}

void LLFloaterQuickPrefs::draw()
{
    if (mInventoryDirty) populateEnvironments();
    bool ultra = true, defaults = true;
    for (const char* name : GRAPHICS_SETTINGS)
    {
        const auto control = gSavedSettings.getControl(name);
        ultra &= control->getValue().asReal() == 2.0;
        defaults &= control->getValue().asReal() == control->getDefault().asReal();
    }
    auto* graphics = getChild<LLComboBox>("graphics");
    if (!graphics->hasFocus())
    {
        graphics->setValue(ultra ? "ultra" : defaults ? "default" : "");
        if (!ultra && !defaults) graphics->setLabel(getString("custom"));
    }
    getChild<LLUICtrl>("name_tags")->setValue(gSavedSettings.getS32("AvatarNameTagMode") != 0);
    getChild<LLSliderCtrl>("hover")->setEnabled(isAgentAvatarValid() && gAgent.getRegion() && gAgent.getRegion()->avatarHoverHeightEnabled());
    if (!getChild<LLSliderCtrl>("hover")->hasFocus())
        getChild<LLSliderCtrl>("hover")->setValue(gSavedPerAccountSettings.getF32("AvatarHoverOffsetZ"));
    auto& env = LLEnvironment::instance();
    const bool local = env.getSelectedEnvironment() == LLEnvironment::ENV_LOCAL &&
        (env.getEnvironmentDay(LLEnvironment::ENV_LOCAL) || env.getEnvironmentFixedSky(LLEnvironment::ENV_LOCAL) || env.getEnvironmentFixedWater(LLEnvironment::ENV_LOCAL));
    for (const char* name : ENV_ROWS)
    {
        if (mPending.count(name) || getChild<LLComboBox>(name)->hasFocus()) continue;
        LLSettingsBase::ptr_t settings;
        if (std::string(name) == "sky") settings = env.getEnvironmentFixedSky(LLEnvironment::ENV_LOCAL);
        else if (std::string(name) == "water") settings = env.getEnvironmentFixedWater(LLEnvironment::ENV_LOCAL);
        else settings = env.getEnvironmentDay(LLEnvironment::ENV_LOCAL);
        auto* combo = getChild<LLComboBox>(name);
        if (!local || !settings || !combo->setSelectedByValue(settings->getAssetId(), true))
        {
            combo->setValue(LLUUID::null);
            combo->setLabel(getString(!local ? "shared_label" : settings ? "custom" : "day_driven"));
        }
    }
    LLFloater::draw();
}

