/**
 * @file llboxxyao.cpp
 * @brief Viewer-side animation overrider for Boxxy Viewer.
 *
 * $LicenseInfo:firstyear=2026&license=viewerlgpl$
 * Copyright (C) 2026 Boxxy Viewer contributors
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation;
 * version 2.1 of the License only.
 * $/LicenseInfo$
 */

#include "llviewerprecompiledheaders.h"

#include "llboxxyao.h"
#include "llboxxyaotransfer.h"

#include "llagent.h"
#include "llanimationstates.h"
#include "llfoldertype.h"
#include "llfloaterreg.h"
#include "llinventoryfunctions.h"
#include "llinventorymodel.h"
#include "llinventorymodelbackgroundfetch.h"
#include "llmotion.h"
#include "llmotioncontroller.h"
#include "llnotificationsutil.h"
#include "llstring.h"
#include "lltoolbarview.h"
#include "llviewercontrol.h"
#include "llviewerinventory.h"
#include "llvoavatarself.h"

namespace
{
constexpr F32 INVENTORY_RETRY_SECONDS = 1.5f;
constexpr char BOXXY_FOLDER_NAME[] = "#Prism";
constexpr char LEGACY_FOLDER_NAME[] = "#Boxxy";
constexpr char AO_FOLDER_NAME[] = "#AO";

std::vector<std::string> splitOptions(const std::string& value)
{
    std::vector<std::string> result;
    LLStringUtil::getTokens(value, result, ":");
    return result;
}

std::string stateFolderName(const LLBoxxyAO::State& state)
{
    std::string folder_name = state.name;
    if (state.cycle) folder_name += ":CY";
    if (state.randomize) folder_name += ":RN";
    if (state.cycle_seconds > 0.f) folder_name += llformat(":CT%.2f", state.cycle_seconds);
    return folder_name;
}
}

LLBoxxyAO::LLBoxxyAO()
: LLEventTimer(0.25f),
  mLastMotion(ANIM_AGENT_STAND),
  mLastOverriddenMotion(ANIM_AGENT_STAND)
{
    mInventoryTimer.setTimerExpirySec(0.f);
    mCycleTimer.stop();
    mRegionConnection = gAgent.addRegionChangedCallback(
        boost::bind(&LLBoxxyAO::onRegionChanged, this));
}

LLBoxxyAO::~LLBoxxyAO()
{
    mRegionConnection.disconnect();
}

void LLBoxxyAO::initializeStates(Set& set) const
{
    static const char* const names[STATE_COUNT] =
    {
        "Standing", "Walking", "Running", "Sitting", "Sitting On Ground",
        "Crouching", "Crouch Walking", "Landing", "Soft Landing", "Standing Up",
        "Falling", "Flying Down", "Flying Up", "Flying", "Flying Slow", "Hovering",
        "Jumping", "Pre Jumping", "Turning Right", "Turning Left", "Typing",
        "Floating", "Swimming Forward", "Swimming Up", "Swimming Down"
    };

    static const LLUUID motions[STATE_COUNT] =
    {
        ANIM_AGENT_STAND,
        ANIM_AGENT_WALK,
        ANIM_AGENT_RUN,
        ANIM_AGENT_SIT,
        ANIM_AGENT_SIT_GROUND_CONSTRAINED,
        ANIM_AGENT_CROUCH,
        ANIM_AGENT_CROUCHWALK,
        ANIM_AGENT_LAND,
        ANIM_AGENT_MEDIUM_LAND,
        ANIM_AGENT_STANDUP,
        ANIM_AGENT_FALLDOWN,
        ANIM_AGENT_HOVER_DOWN,
        ANIM_AGENT_HOVER_UP,
        ANIM_AGENT_FLY,
        ANIM_AGENT_FLYSLOW,
        ANIM_AGENT_HOVER,
        ANIM_AGENT_JUMP,
        ANIM_AGENT_PRE_JUMP,
        ANIM_AGENT_TURNRIGHT,
        ANIM_AGENT_TURNLEFT,
        ANIM_AGENT_TYPE,
        ANIM_AGENT_HOVER,
        ANIM_AGENT_FLY,
        ANIM_AGENT_HOVER_UP,
        ANIM_AGENT_HOVER_DOWN
    };

    for (S32 i = 0; i < STATE_COUNT; ++i)
    {
        State& state = set.states[i];
        state.type = static_cast<EState>(i);
        state.name = names[i];
        state.stock_motion = motions[i];
    }
}

void LLBoxxyAO::onLoginComplete()
{
    if (mLoggedIn)
    {
        return;
    }

    mLoggedIn = true;
    mEnabled = gSavedPerAccountSettings.getBOOL("BoxxyAOEnabled");
    mOverrideApplyPending = mEnabled;
    requestReload();

    // Existing accounts have a saved toolbar layout that predates the AO
    // command. Install it once on the right toolbar; after that it remains a
    // normal user-customizable toolbar button.
    if (gToolBarView && !gSavedPerAccountSettings.getBOOL("BoxxyAOToolbarInstalled"))
    {
        const LLCommandId command_id("boxxy_ao");
        if (gToolBarView->hasCommand(command_id) == LLToolBarEnums::TOOLBAR_NONE)
        {
            gToolBarView->addCommand(command_id, LLToolBarEnums::TOOLBAR_RIGHT);
        }
        gSavedPerAccountSettings.setBOOL("BoxxyAOToolbarInstalled", true);
    }

    // Install Radar once as well. It remains a normal, removable toolbar
    // command after this first-run migration of an account's saved layout.
    if (gToolBarView && !gSavedPerAccountSettings.getBOOL("BoxxyRadarToolbarInstalled"))
    {
        const LLCommandId command_id("boxxy_radar");
        if (gToolBarView->hasCommand(command_id) == LLToolBarEnums::TOOLBAR_NONE)
        {
            gToolBarView->addCommand(command_id, LLToolBarEnums::TOOLBAR_RIGHT);
        }
        gSavedPerAccountSettings.setBOOL("BoxxyRadarToolbarInstalled", true);
    }

    if (gToolBarView && !gSavedPerAccountSettings.getBOOL("BoxxyTPoseToolbarInstalled"))
    {
        const LLCommandId command_id("boxxy_tpose");
        if (gToolBarView->hasCommand(command_id) == LLToolBarEnums::TOOLBAR_NONE)
        {
            gToolBarView->addCommand(command_id, LLToolBarEnums::TOOLBAR_RIGHT);
        }
        gSavedPerAccountSettings.setBOOL("BoxxyTPoseToolbarInstalled", true);
    }

    if (gSavedSettings.getBOOL("BoxxySimpleRadarEnabled") && !LLFloaterReg::instanceVisible("boxxy_radar"))
    {
        LLFloaterReg::showInstance("boxxy_radar_simple", LLSD(), false);
    }
}

void LLBoxxyAO::shutdown()
{
    LLBoxxyAOTransfer::cancel();
    mLoggedIn = false;
    mOverrideApplyPending = false;
    mIgnoredStockStops.clear();
    mCycleTimer.stop();
}

bool LLBoxxyAO::tick()
{
    if (!mLoggedIn || !isAgentAvatarValid())
    {
        return false;
    }

    LLBoxxyAOTransfer::update();

    // Do not normalize a half-built import: link replies can arrive out of
    // order, and compacting their indices early would lose the imported order.
    if ((!mInventoryReady || mReloadRequested) && mInventoryTimer.hasExpired() &&
        !LLBoxxyAOTransfer::isWriting())
    {
        ensureInventoryFolders();
        if (mAOFolder.notNull() && loadInventory())
        {
            mInventoryReady = true;
            mReloadRequested = false;
        }
        mInventoryTimer.setTimerExpirySec(INVENTORY_RETRY_SECONDS);
    }

    completePendingCycleStop(false);
    applyPendingOverrideIfReady();

    State* state = getCurrentState();
    const bool airborne = gAgent.getFlying() || gAgentAvatarp->mInAir;
    if (state && state->type == STATE_STANDING && airborne)
    {
        if (mCycleTimer.getStarted())
        {
            mCycleTimer.stop();
        }
        mStandCyclePaused = true;
    }
    else if (mStandCyclePaused && state && state->type == STATE_STANDING && !airborne)
    {
        // Landing starts a fresh full interval rather than immediately
        // consuming whatever time remained before takeoff.
        mStandCyclePaused = false;
        restartCycleTimer(state);
    }

    // Some uploaded stands are not marked as looping. Once such a motion
    // reaches its own endpoint, the simulator removes it even though the AO
    // is still in the Standing state. Advance immediately when cycling, or
    // restart the sole/current stand, rather than leaving the avatar neutral
    // until the configured cycle timer expires.
    if (!airborne && mEnabled && state && state->type == STATE_STANDING &&
        state->current_asset.notNull() && mPendingCycleStart.isNull())
    {
        LLMotionController& controller = gAgentAvatarp->getMotionController();
        LLMotion* motion = controller.findMotion(state->current_asset);
        if (motion && !controller.isMotionLoading(motion) &&
            (!controller.isMotionActive(motion) || motion->isStopped()))
        {
            if (state->cycle && state->animations.size() > 1)
            {
                performCycle(1);
            }
            else
            {
                gAgent.sendAnimationRequest(state->current_asset, ANIM_REQUEST_START);
                gAgentAvatarp->LLCharacter::startMotion(state->current_asset);
                restartCycleTimer(state);
            }
        }
    }

    if (!airborne && mEnabled && state && state->cycle && state->cycle_seconds > 0.f &&
        state->animations.size() > 1 && mCycleTimer.getStarted() && mCycleTimer.hasExpired())
    {
        LL_INFOS("BoxxyAO") << "Cycle timer expired for " << state->name
                             << " after " << state->cycle_seconds << " seconds." << LL_ENDL;
        performCycle(1);
    }

    return false;
}

void LLBoxxyAO::requestReload()
{
    mReloadRequested = true;
    mInventoryTimer.setTimerExpirySec(0.35f);
}

void LLBoxxyAO::ensureInventoryFolders()
{
    if (mCreatePending)
    {
        return;
    }

    if (mBoxxyFolder.isNull())
    {
        if (!gInventory.isCategoryComplete(gInventory.getRootFolderID()))
        {
            gInventory.fetchDescendentsOf(gInventory.getRootFolderID());
            return;
        }

        LLInventoryModel::cat_array_t* root_categories = nullptr;
        LLInventoryModel::item_array_t* root_items = nullptr;
        gInventory.getDirectDescendentsOf(gInventory.getRootFolderID(), root_categories, root_items);
        if (root_categories)
        {
            for (const auto& category : *root_categories)
            {
                if (category->getName() == LEGACY_FOLDER_NAME)
                {
                    // Reuse existing sets without moving or duplicating inventory.
                    mBoxxyFolder = category->getUUID();
                }
                if (category->getName() == BOXXY_FOLDER_NAME)
                {
                    mBoxxyFolder = category->getUUID();
                    break;
                }
            }
        }
    }

    if (mBoxxyFolder.isNull())
    {
        mCreatePending = true;
        gInventory.createNewCategory(gInventory.getRootFolderID(), LLFolderType::FT_NONE,
            BOXXY_FOLDER_NAME, [this](const LLUUID& id)
            {
                mBoxxyFolder = id;
                mCreatePending = false;
                requestReload();
            });
        return;
    }

    if (!gInventory.isCategoryComplete(mBoxxyFolder))
    {
        gInventory.fetchDescendentsOf(mBoxxyFolder);
        return;
    }

    LLInventoryModel::cat_array_t* categories = nullptr;
    LLInventoryModel::item_array_t* items = nullptr;
    gInventory.getDirectDescendentsOf(mBoxxyFolder, categories, items);
    if (categories)
    {
        for (const auto& category : *categories)
        {
            if (category->getName() == AO_FOLDER_NAME)
            {
                mAOFolder = category->getUUID();
                return;
            }
        }
    }

    mCreatePending = true;
    gInventory.createNewCategory(mBoxxyFolder, LLFolderType::FT_NONE, AO_FOLDER_NAME,
        [this](const LLUUID& id)
        {
            mAOFolder = id;
            mCreatePending = false;
            requestReload();
        });
}

bool LLBoxxyAO::loadInventory()
{
    if (!gInventory.isCategoryComplete(mAOFolder))
    {
        gInventory.fetchDescendentsOf(mAOFolder);
        return false;
    }

    LLInventoryModel::cat_array_t* categories = nullptr;
    LLInventoryModel::item_array_t* items = nullptr;
    gInventory.getDirectDescendentsOf(mAOFolder, categories, items);
    if (!categories)
    {
        return false;
    }

    mInventoryItemsPending = false;
    std::vector<std::unique_ptr<Set>> loaded_sets;
    bool all_sets_ready = true;
    for (const auto& category : *categories)
    {
        std::unique_ptr<Set> set;
        if (!loadSet(category->getUUID(), category->getName(), set))
        {
            all_sets_ready = false;
            continue;
        }
        if (set)
        {
            loaded_sets.emplace_back(std::move(set));
        }
    }
    if (!all_sets_ready)
    {
        return false;
    }

    // Inventory-link creation is asynchronous.  The link callback can run
    // before the containing folder's cached descendants include the new
    // item, so do not replace a richer live model with that stale snapshot.
    // User-initiated removals are erased from the live model first and are
    // therefore unaffected by this guard.
    bool loaded_loses_animation = false;
    for (const auto& current_set : mSets)
    {
        const Set* loaded_set = nullptr;
        for (const auto& candidate : loaded_sets)
        {
            if (candidate->inventory_id == current_set->inventory_id)
            {
                loaded_set = candidate.get();
                break;
            }
        }
        if (!loaded_set)
        {
            continue;
        }

        for (S32 i = 0; i < STATE_COUNT && !loaded_loses_animation; ++i)
        {
            for (const Animation& current_animation : current_set->states[i].animations)
            {
                bool found = false;
                for (const Animation& loaded_animation : loaded_set->states[i].animations)
                {
                    if (loaded_animation.original_id == current_animation.original_id)
                    {
                        found = true;
                        break;
                    }
                }
                if (!found)
                {
                    loaded_loses_animation = true;
                    break;
                }
            }
        }
        if (loaded_loses_animation)
        {
            break;
        }
    }
    if (loaded_loses_animation && mInventoryRetryPasses < 12)
    {
        ++mInventoryRetryPasses;
        return false;
    }

    if (inventoryMatches(loaded_sets))
    {
        // Item fetch retries commonly return the same usable subset several
        // times. Do not tear down and restart an identical live AO each pass.
        if (mInventoryItemsPending && mInventoryRetryPasses < 12)
        {
            ++mInventoryRetryPasses;
            return false;
        }
        mInventoryRetryPasses = 0;
        return true;
    }

    const std::string selected_name = gSavedPerAccountSettings.getString("BoxxyAOCurrentSet");
    const bool was_enabled = mEnabled;

    // Preserve a currently playing override across an inventory-only model
    // refresh.  Stopping and starting it here produces a visible twitch even
    // when the active animation itself did not change.
    LLUUID active_set_id;
    LLUUID active_asset_id;
    EState active_state_type = STATE_STANDING;
    if (mCurrentSet)
    {
        active_set_id = mCurrentSet->inventory_id;
        if (State* active_state = getCurrentState())
        {
            active_state_type = active_state->type;
            active_asset_id = active_state->current_asset;
        }
    }

    bool preserve_active_override = false;
    U32 preserved_animation_index = 0;
    if (was_enabled && active_asset_id.notNull())
    {
        for (const auto& loaded_set : loaded_sets)
        {
            if (loaded_set->inventory_id != active_set_id)
            {
                continue;
            }
            const State& loaded_state = loaded_set->states[static_cast<S32>(active_state_type)];
            for (U32 i = 0; i < loaded_state.animations.size(); ++i)
            {
                if (loaded_state.animations[i].asset_id == active_asset_id)
                {
                    preserve_active_override = true;
                    preserved_animation_index = i;
                    break;
                }
            }
            break;
        }
    }

    if (mCurrentSet && !preserve_active_override)
    {
        stopCurrentOverride(true);
    }

    mSets = std::move(loaded_sets);
    mCurrentSet = findSet(selected_name);
    if (!mCurrentSet && !mSets.empty())
    {
        mCurrentSet = mSets.front().get();
        gSavedPerAccountSettings.setString("BoxxyAOCurrentSet", mCurrentSet->name);
    }

    mChangedSignal();
    if (preserve_active_override && mCurrentSet &&
        mCurrentSet->inventory_id == active_set_id)
    {
        State* active_state = stateForType(mCurrentSet, active_state_type);
        active_state->current_animation = preserved_animation_index;
        active_state->current_asset = active_asset_id;
        restartCycleTimer(active_state);
    }
    else if (was_enabled && mCurrentSet)
    {
        if (mOverrideApplyPending)
        {
            applyPendingOverrideIfReady();
        }
        else
        {
            startCurrentOverride();
        }
    }

    if (mInventoryItemsPending && mInventoryRetryPasses < 12)
    {
        ++mInventoryRetryPasses;
        return false;
    }
    mInventoryRetryPasses = 0;
    return true;
}

bool LLBoxxyAO::inventoryMatches(
    const std::vector<std::unique_ptr<Set>>& loaded_sets) const
{
    if (loaded_sets.size() != mSets.size())
    {
        return false;
    }

    for (const auto& loaded : loaded_sets)
    {
        const Set* current = nullptr;
        for (const auto& candidate : mSets)
        {
            if (candidate->inventory_id == loaded->inventory_id)
            {
                current = candidate.get();
                break;
            }
        }
        if (!current || current->name != loaded->name ||
            current->override_sits != loaded->override_sits)
        {
            return false;
        }

        for (S32 i = 0; i < STATE_COUNT; ++i)
        {
            const State& lhs = current->states[i];
            const State& rhs = loaded->states[i];
            if (lhs.inventory_id != rhs.inventory_id || lhs.cycle != rhs.cycle ||
                lhs.randomize != rhs.randomize ||
                !is_approx_equal(lhs.cycle_seconds, rhs.cycle_seconds) ||
                lhs.animations.size() != rhs.animations.size())
            {
                return false;
            }
            for (size_t j = 0; j < lhs.animations.size(); ++j)
            {
                const Animation& lhs_animation = lhs.animations[j];
                const Animation& rhs_animation = rhs.animations[j];
                if (lhs_animation.inventory_id != rhs_animation.inventory_id ||
                    lhs_animation.original_id != rhs_animation.original_id ||
                    lhs_animation.asset_id != rhs_animation.asset_id ||
                    lhs_animation.name != rhs_animation.name ||
                    lhs_animation.sort_order != rhs_animation.sort_order)
                {
                    return false;
                }
            }
        }
    }
    return true;
}

bool LLBoxxyAO::loadSet(const LLUUID& category_id, const std::string& folder_name,
                        std::unique_ptr<Set>& result)
{
    if (!gInventory.isCategoryComplete(category_id))
    {
        gInventory.fetchDescendentsOf(category_id);
        return false;
    }

    std::vector<std::string> options = splitOptions(folder_name);
    if (options.empty() || options.front().empty())
    {
        return true;
    }

    auto set = std::make_unique<Set>();
    initializeStates(*set);
    set->name = options.front();
    set->inventory_id = category_id;
    for (auto it = options.begin() + 1; it != options.end(); ++it)
    {
        if (*it == "SO")
        {
            set->override_sits = true;
        }
    }

    LLInventoryModel::cat_array_t* categories = nullptr;
    LLInventoryModel::item_array_t* items = nullptr;
    gInventory.getDirectDescendentsOf(category_id, categories, items);
    bool all_states_ready = true;
    if (categories)
    {
        for (const auto& category : *categories)
        {
            if (!loadState(*set, category->getUUID(), category->getName()))
            {
                all_states_ready = false;
            }
        }
    }
    if (!all_states_ready)
    {
        return false;
    }

    result = std::move(set);
    return true;
}

bool LLBoxxyAO::loadState(Set& set, const LLUUID& category_id, const std::string& folder_name)
{
    if (!gInventory.isCategoryComplete(category_id))
    {
        gInventory.fetchDescendentsOf(category_id);
        return false;
    }

    std::vector<std::string> options = splitOptions(folder_name);
    if (options.empty())
    {
        return true;
    }

    State* state = nullptr;
    for (State& candidate : set.states)
    {
        if (candidate.name == options.front())
        {
            state = &candidate;
            break;
        }
    }
    if (!state)
    {
        LL_WARNS("BoxxyAO") << "Ignoring unknown AO state folder " << folder_name << LL_ENDL;
        return true;
    }

    state->inventory_id = category_id;
    for (auto it = options.begin() + 1; it != options.end(); ++it)
    {
        if (*it == "CY")
        {
            state->cycle = true;
        }
        else if (*it == "RN")
        {
            state->randomize = true;
        }
        else if (it->size() > 2 && it->substr(0, 2) == "CT")
        {
            LLStringUtil::convertToF32(it->substr(2), state->cycle_seconds);
        }
    }

    LLInventoryModel::cat_array_t* categories = nullptr;
    LLInventoryModel::item_array_t* items = nullptr;
    gInventory.getDirectDescendentsOf(category_id, categories, items);
    bool items_pending = false;
    if (items)
    {
        for (const auto& item : *items)
        {
            if (!item->getIsLinkType() || item->getInventoryType() != LLInventoryType::IT_ANIMATION)
            {
                continue;
            }

            const LLUUID original_id = item->getLinkedUUID();
            if (original_id.isNull())
            {
                if (!item->isFinished())
                {
                    LLInventoryModelBackgroundFetch::instance().scheduleItemFetch(item->getUUID(), true);
                    items_pending = true;
                }
                else
                {
                    LL_WARNS("BoxxyAO") << "Ignoring AO link " << item->getUUID()
                                         << " with no target inventory item." << LL_ENDL;
                }
                continue;
            }

            if (!item->isFinished())
            {
                // A complete category can still contain an item whose full
                // record has not arrived.  The link identity and target are
                // already usable, so retain the row while fetching the rest.
                LLInventoryModelBackgroundFetch::instance().scheduleItemFetch(item->getUUID(), true);
                items_pending = true;
            }

            LLViewerInventoryItem* original = gInventory.getItem(original_id);
            if (!original || !original->isFinished())
            {
                LLInventoryModelBackgroundFetch::instance().scheduleItemFetch(original_id, true);
                items_pending = true;
            }

            Animation animation;
            animation.name = item->getName();
            animation.inventory_id = item->getUUID();
            animation.original_id = original_id;
            // Keep the link even when its target has not been fetched yet.
            // A link's own asset UUID is the target *inventory* UUID, not the
            // animation asset UUID sent to the simulator.  Resolve the latter
            // now when possible and lazily at playback time otherwise.
            if (original && original->isFinished())
            {
                animation.asset_id = original->getAssetUUID();
            }
            if (!LLStringUtil::convertToS32(item->LLInventoryItem::getDescription(), animation.sort_order))
            {
                animation.sort_order = -1;
            }
            state->animations.emplace_back(std::move(animation));
        }
    }

    std::stable_sort(state->animations.begin(), state->animations.end(),
        [](const Animation& lhs, const Animation& rhs)
        {
            if (lhs.sort_order < 0 && rhs.sort_order < 0) return lhs.name < rhs.name;
            if (lhs.sort_order < 0) return false;
            if (rhs.sort_order < 0) return true;
            return lhs.sort_order < rhs.sort_order;
        });
    if (items_pending)
    {
        // Publish every known link immediately. A later retry fills in the
        // animation asset UUIDs without changing which rows the user sees.
        mInventoryItemsPending = true;
    }
    else
    {
        normalizeAnimationOrder(state);
    }
    return true;
}

LLBoxxyAO::Set* LLBoxxyAO::findSet(const std::string& name) const
{
    for (const auto& set : mSets)
    {
        if (set->name == name)
        {
            return set.get();
        }
    }
    return nullptr;
}

LLBoxxyAO::Set* LLBoxxyAO::findSetByInventoryID(const LLUUID& id) const
{
    for (const auto& set : mSets)
    {
        if (set->inventory_id == id)
        {
            return set.get();
        }
    }
    return nullptr;
}

LLBoxxyAO::State* LLBoxxyAO::stateForType(Set* set, EState type) const
{
    return set ? &set->states[static_cast<S32>(type)] : nullptr;
}

LLBoxxyAO::State* LLBoxxyAO::stateForMotion(const LLUUID& motion) const
{
    if (!mCurrentSet)
    {
        return nullptr;
    }

    if (motion == ANIM_AGENT_SIT_GROUND)
    {
        return stateForType(mCurrentSet, STATE_SITTING_GROUND);
    }

    if (motion == ANIM_AGENT_STAND_1 || motion == ANIM_AGENT_STAND_2 ||
        motion == ANIM_AGENT_STAND_3 || motion == ANIM_AGENT_STAND_4)
    {
        return stateForType(mCurrentSet, STATE_STANDING);
    }
    if (motion == ANIM_AGENT_WALK_NEW || motion == ANIM_AGENT_FEMALE_WALK ||
        motion == ANIM_AGENT_FEMALE_WALK_NEW)
    {
        return stateForType(mCurrentSet, STATE_WALKING);
    }
    if (motion == ANIM_AGENT_RUN_NEW || motion == ANIM_AGENT_FEMALE_RUN_NEW)
    {
        return stateForType(mCurrentSet, STATE_RUNNING);
    }

    if (mBelowWater)
    {
        if (motion == ANIM_AGENT_HOVER) return stateForType(mCurrentSet, STATE_FLOATING);
        if (motion == ANIM_AGENT_FLY) return stateForType(mCurrentSet, STATE_SWIMMING_FORWARD);
        if (motion == ANIM_AGENT_HOVER_UP) return stateForType(mCurrentSet, STATE_SWIMMING_UP);
        if (motion == ANIM_AGENT_HOVER_DOWN) return stateForType(mCurrentSet, STATE_SWIMMING_DOWN);
    }

    for (State& state : mCurrentSet->states)
    {
        if (state.type >= STATE_FLOATING)
        {
            continue;
        }
        if (state.stock_motion == motion)
        {
            return &state;
        }
    }
    return nullptr;
}

LLBoxxyAO::State* LLBoxxyAO::getCurrentState() const
{
    return stateForMotion(mLastMotion);
}

bool LLBoxxyAO::isTransientMotion(const LLUUID& motion) const
{
    return motion == ANIM_AGENT_SIT_GROUND || motion == ANIM_AGENT_SIT_GROUND_CONSTRAINED ||
           motion == ANIM_AGENT_PRE_JUMP || motion == ANIM_AGENT_STANDUP ||
           motion == ANIM_AGENT_LAND || motion == ANIM_AGENT_MEDIUM_LAND;
}

LLUUID LLBoxxyAO::resolveAnimationAsset(Animation& animation)
{
    if (animation.asset_id.notNull() || animation.original_id.isNull())
    {
        return animation.asset_id;
    }

    LLViewerInventoryItem* original = gInventory.getItem(animation.original_id);
    if (!original || !original->isFinished())
    {
        LLInventoryModelBackgroundFetch::instance().scheduleItemFetch(
            animation.original_id, true);
        return LLUUID::null;
    }

    animation.asset_id = original->getAssetUUID();
    if (animation.asset_id.notNull())
    {
        LL_DEBUGS("BoxxyAO") << "Resolved animation asset " << animation.asset_id
                              << " for inventory link " << animation.inventory_id
                              << LL_ENDL;
    }
    return animation.asset_id;
}

LLUUID LLBoxxyAO::overrideMotion(const LLUUID& motion, bool start)
{
    if (start)
    {
        // If the simulator starts a stock motion again, a previously sent
        // stop for that UUID is no longer the stop we intended to ignore.
        mIgnoredStockStops.erase(motion);
    }
    else if (mIgnoredStockStops.erase(motion) != 0)
    {
        return LLUUID::null;
    }

    State* state = stateForMotion(motion);
    if (!state)
    {
        return LLUUID::null;
    }

    if (!mEnabled || !mCurrentSet)
    {
        if (start && motion != ANIM_AGENT_TYPE)
        {
            mLastMotion = motion;
            if (!state->animations.empty())
            {
                mLastOverriddenMotion = motion;
            }
        }
        return LLUUID::null;
    }

    if (!start && state->current_asset.notNull())
    {
        // The simulator rotates between several stock stand UUIDs. Their
        // start/stop notifications can straddle our timed custom-animation
        // handoff; treating an old stock variant's stop as "not standing"
        // clears the newly selected override and creates the multi-second
        // neutral gap visible in the manager as a missing play arrow.
        bool same_state_still_signaled = false;
        bool different_primary_state_signaled = false;
        for (const auto& signaled_animation : gAgentAvatarp->mSignaledAnimations)
        {
            State* signaled_state = stateForMotion(signaled_animation.first);
            if (!signaled_state || signaled_state->type == STATE_TYPING)
            {
                continue;
            }
            if (signaled_state == state)
            {
                same_state_still_signaled = true;
            }
            else
            {
                different_primary_state_signaled = true;
            }
        }

        const bool grounded_stand = state->type == STATE_STANDING &&
            isAgentAvatarValid() && !gAgent.getFlying() && !gAgentAvatarp->mInAir;
        if (same_state_still_signaled ||
            (grounded_stand && !different_primary_state_signaled))
        {
            LL_DEBUGS("BoxxyAO") << "Ignoring stale stock stop for " << motion
                                  << " while " << state->name
                                  << " remains the active avatar state." << LL_ENDL;
            return LLUUID::null;
        }
    }

    if (state->type != STATE_TYPING && mPendingCycleStop.notNull() &&
        (!start || motion != mLastMotion))
    {
        // A locomotion/state change must not leave the older stand running
        // while a pending replacement finishes loading.
        completePendingCycleStop(true);
    }

    if (start)
    {
        const bool continuing_same_state = motion != ANIM_AGENT_TYPE &&
            !isTransientMotion(motion) && state == getCurrentState() &&
            state->current_asset.notNull();

        // Typing is a layered animation, not the avatar's locomotion state.
        // Remembering it as the primary motion interrupts stand timing and
        // differs from Firestorm's AO state tracking.
        if (motion != ANIM_AGENT_TYPE)
        {
            mLastMotion = motion;
        }
        if (motion == ANIM_AGENT_SIT && !mCurrentSet->override_sits)
        {
            return LLUUID::null;
        }
        if (state->animations.empty())
        {
            return LLUUID::null;
        }

        if (continuing_same_state)
        {
            // The simulator periodically replaces one stock stand variant
            // with another. This is a reassertion of Standing, not a new
            // state entry: keep the selected override and, crucially, do not
            // reset its cycle countdown.
            mLastOverriddenMotion = motion;
            return state->current_asset;
        }

        if (state->current_animation >= state->animations.size())
        {
            state->current_animation = 0;
        }
        if (state->cycle && state->randomize && state->animations.size() > 1)
        {
            state->current_animation = static_cast<U32>(ll_frand() * state->animations.size());
            state->current_animation = llmin<U32>(state->current_animation,
                                                   static_cast<U32>(state->animations.size() - 1));
        }

        const LLUUID old_asset = state->current_asset;
        state->current_asset = resolveAnimationAsset(
            state->animations[state->current_animation]);
        mLastOverriddenMotion = motion;
        if (old_asset.notNull() && old_asset != state->current_asset)
        {
            gAgent.sendAnimationRequest(old_asset, ANIM_REQUEST_STOP);
            gAgentAvatarp->LLCharacter::stopMotion(old_asset);
        }
        if (state->type != STATE_TYPING)
        {
            restartCycleTimer(state);
        }
        mChangedSignal();

        if (state->current_asset.isNull())
        {
            // Keep the stock motion running until the link target arrives.
            if (state->type != STATE_TYPING)
            {
                mOverrideApplyPending = true;
            }
            return LLUUID::null;
        }
        if (state->type != STATE_TYPING)
        {
            mOverrideApplyPending = false;
        }
        if (isTransientMotion(motion))
        {
            gAgent.sendAnimationRequest(state->current_asset, ANIM_REQUEST_START);
            return LLUUID::null;
        }
        return state->current_asset;
    }

    const LLUUID result = state->current_asset;
    LL_INFOS("BoxxyAO") << "Clearing " << state->name
                         << " override " << result
                         << " for stock motion stop " << motion << LL_ENDL;
    state->current_asset.setNull();
    if (state->type != STATE_TYPING)
    {
        mCycleTimer.stop();
    }
    mChangedSignal();
    if (isTransientMotion(motion) && result.notNull())
    {
        gAgent.sendAnimationRequest(result, ANIM_REQUEST_STOP);
        gAgentAvatarp->LLCharacter::stopMotion(result);
        return LLUUID::null;
    }
    return result;
}

void LLBoxxyAO::setEnabled(bool enabled)
{
    if (mEnabled == enabled)
    {
        return;
    }

    mEnabled = enabled;
    gSavedPerAccountSettings.setBOOL("BoxxyAOEnabled", enabled);
    if (enabled)
    {
        startCurrentOverride();
    }
    else
    {
        mOverrideApplyPending = false;
        stopCurrentOverride(true);
    }
    mChangedSignal();
}

void LLBoxxyAO::stopStockMotionVariants(const LLUUID& motion)
{
    std::vector<LLUUID> stock_motions;
    State* state = stateForMotion(motion);
    if (state && state->type == STATE_STANDING)
    {
        // The simulator can already be running any one of these by the time
        // the AO inventory becomes ready after login.  Stopping only the
        // default stand UUID leaves that variant competing with the AO.
        stock_motions =
        {
            ANIM_AGENT_STAND,
            ANIM_AGENT_STAND_1,
            ANIM_AGENT_STAND_2,
            ANIM_AGENT_STAND_3,
            ANIM_AGENT_STAND_4
        };
    }
    else if (state && state->type == STATE_WALKING)
    {
        stock_motions =
        {
            ANIM_AGENT_WALK,
            ANIM_AGENT_WALK_NEW,
            ANIM_AGENT_FEMALE_WALK,
            ANIM_AGENT_FEMALE_WALK_NEW
        };
    }
    else if (state && state->type == STATE_RUNNING)
    {
        stock_motions =
        {
            ANIM_AGENT_RUN,
            ANIM_AGENT_RUN_NEW,
            ANIM_AGENT_FEMALE_RUN_NEW
        };
    }
    else
    {
        stock_motions.emplace_back(motion);
    }

    std::set<LLUUID> unique_motions(stock_motions.begin(), stock_motions.end());
    for (const LLUUID& stock_motion : unique_motions)
    {
        if (stock_motion.isNull())
        {
            continue;
        }
        mIgnoredStockStops.insert(stock_motion);
        gAgent.sendAnimationRequest(stock_motion, ANIM_REQUEST_STOP);
        gAgentAvatarp->LLCharacter::stopMotion(stock_motion);
    }
}

void LLBoxxyAO::startCurrentOverride()
{
    if (!mCurrentSet || !isAgentAvatarValid())
    {
        return;
    }

    LLUUID animation = overrideMotion(mLastMotion, true);
    if (animation.notNull())
    {
        gAgent.sendAnimationRequest(animation, ANIM_REQUEST_START);
        stopStockMotionVariants(mLastMotion);
    }
}

void LLBoxxyAO::applyPendingOverrideIfReady()
{
    if (!mOverrideApplyPending || !mEnabled || !mCurrentSet ||
        !isAgentAvatarValid())
    {
        return;
    }

    State* state = getCurrentState();
    if (!state)
    {
        return;
    }
    if (state->animations.empty())
    {
        mOverrideApplyPending = false;
        return;
    }
    if (mLastMotion == ANIM_AGENT_SIT && !mCurrentSet->override_sits)
    {
        mOverrideApplyPending = false;
        return;
    }

    startCurrentOverride();
    if (state->current_asset.notNull())
    {
        LL_INFOS("BoxxyAO") << "Applied pending override for " << state->name
                             << " using asset " << state->current_asset << LL_ENDL;
        mOverrideApplyPending = false;
    }
}

void LLBoxxyAO::stopCurrentOverride(bool restore_stock)
{
    if (!mCurrentSet || !isAgentAvatarValid())
    {
        return;
    }

    completePendingCycleStop(true);
    for (State& state : mCurrentSet->states)
    {
        if (state.current_asset.notNull())
        {
            gAgent.sendAnimationRequest(state.current_asset, ANIM_REQUEST_STOP);
            gAgentAvatarp->LLCharacter::stopMotion(state.current_asset);
            state.current_asset.setNull();
        }
    }
    mCycleTimer.stop();
    if (restore_stock && mLastMotion.notNull())
    {
        gAgent.sendAnimationRequest(mLastMotion, ANIM_REQUEST_START);
    }
}

void LLBoxxyAO::selectSet(Set* set)
{
    if (!set || set == mCurrentSet)
    {
        return;
    }

    if (mEnabled)
    {
        stopCurrentOverride(true);
    }
    mCurrentSet = set;
    gSavedPerAccountSettings.setString("BoxxyAOCurrentSet", set->name);
    if (mEnabled)
    {
        startCurrentOverride();
    }
    mChangedSignal();
}

void LLBoxxyAO::createSet(const std::string& requested_name)
{
    std::string name = requested_name;
    LLStringUtil::trim(name);
    if (name.empty() || name.find(':') != std::string::npos || findSet(name))
    {
        LLNotificationsUtil::add("BoxxyAOInvalidSetName");
        return;
    }
    if (mAOFolder.isNull())
    {
        LLNotificationsUtil::add("BoxxyAONotReady");
        return;
    }

    gInventory.createNewCategory(mAOFolder, LLFolderType::FT_NONE, name,
        [this, name](const LLUUID&)
        {
            gSavedPerAccountSettings.setString("BoxxyAOCurrentSet", name);
            requestReload();
        });
}

void LLBoxxyAO::removeSet(Set* set)
{
    if (!set)
    {
        return;
    }
    if (set == mCurrentSet && mEnabled)
    {
        stopCurrentOverride(true);
    }
    gInventory.removeCategory(set->inventory_id);
    if (set == mCurrentSet)
    {
        gSavedPerAccountSettings.setString("BoxxyAOCurrentSet", "");
    }
    requestReload();
}

void LLBoxxyAO::setOverrideSits(Set* set, bool enabled)
{
    if (!set || set->override_sits == enabled)
    {
        return;
    }
    const bool is_active_sit = set == mCurrentSet && mEnabled &&
        (mLastMotion == ANIM_AGENT_SIT || mLastMotion == ANIM_AGENT_SIT_GROUND ||
         mLastMotion == ANIM_AGENT_SIT_GROUND_CONSTRAINED);
    if (is_active_sit)
    {
        stopCurrentOverride(true);
    }

    set->override_sits = enabled;
    saveSetOptions(set);

    if (is_active_sit && enabled)
    {
        startCurrentOverride();
    }
    mChangedSignal();
}

void LLBoxxyAO::saveSetOptions(Set* set)
{
    if (!set || set->inventory_id.isNull())
    {
        return;
    }
    std::string folder_name = set->name;
    if (set->override_sits) folder_name += ":SO";
    rename_category(&gInventory, set->inventory_id, folder_name);
}

void LLBoxxyAO::saveStateOptions(State* state)
{
    if (!state || state->inventory_id.isNull())
    {
        return;
    }
    rename_category(&gInventory, state->inventory_id, stateFolderName(*state));
}

void LLBoxxyAO::addAnimation(Set* set, State* state, const LLInventoryItem* item)
{
    if (!set || !state || !item || item->getInventoryType() != LLInventoryType::IT_ANIMATION)
    {
        return;
    }
    const LLUUID original_id = item->getLinkedUUID();
    const LLInventoryItem* original = gInventory.getItem(original_id);
    if (!original || original->getAssetUUID().isNull())
    {
        LLNotificationsUtil::add("BoxxyAOAnimationUnavailable");
        return;
    }

    for (const Animation& animation : state->animations)
    {
        if (animation.original_id == original_id)
        {
            LLNotificationsUtil::add("BoxxyAOAnimationAlreadyAdded");
            return;
        }
    }

    createAnimationLink(set->inventory_id, state->type, original_id);
}

void LLBoxxyAO::createAnimationLink(const LLUUID& set_id, EState state_type,
                                    const LLUUID& item_id)
{
    Set* set = findSetByInventoryID(set_id);
    State* state = stateForType(set, state_type);
    const LLInventoryItem* item = gInventory.getItem(item_id);
    if (!set || !state || !item)
    {
        return;
    }

    const LLUUID original_id = item->getLinkedUUID();
    Animation animation;
    animation.name = item->getName();
    animation.original_id = original_id;
    animation.asset_id = item->getAssetUUID();
    animation.sort_order = static_cast<S32>(state->animations.size());
    state->animations.emplace_back(std::move(animation));
    mChangedSignal();

    if (state->inventory_id.isNull())
    {
        // Folder creation is asynchronous. Queue every add for this state and
        // let only the first one create the folder; otherwise a quick series
        // of drops creates several same-named state folders and scatters the
        // saved links between them.
        const pending_add_key_t key(set_id, state_type);
        auto [pending_it, inserted] = mPendingAnimationAdds.try_emplace(key);
        pending_it->second.emplace_back(item_id);
        if (!inserted)
        {
            return;
        }

        const std::string folder_name = stateFolderName(*state);
        gInventory.createNewCategory(set_id, LLFolderType::FT_NONE, folder_name,
            [this, key](const LLUUID& category_id)
            {
                auto pending_it = mPendingAnimationAdds.find(key);
                if (pending_it == mPendingAnimationAdds.end())
                {
                    return;
                }
                std::vector<LLUUID> pending_items = std::move(pending_it->second);
                mPendingAnimationAdds.erase(pending_it);

                Set* callback_set = findSetByInventoryID(key.first);
                State* callback_state = stateForType(callback_set, key.second);
                if (category_id.isNull())
                {
                    LL_WARNS("BoxxyAO") << "Failed to create AO state folder for set "
                                         << key.first << LL_ENDL;
                    if (callback_state)
                    {
                        const std::set<LLUUID> failed_items(
                            pending_items.begin(), pending_items.end());
                        auto& animations = callback_state->animations;
                        animations.erase(std::remove_if(animations.begin(), animations.end(),
                            [&failed_items](const Animation& queued_animation)
                            {
                                return queued_animation.inventory_id.isNull() &&
                                    failed_items.find(queued_animation.original_id) !=
                                        failed_items.end();
                            }), animations.end());
                    }
                    LLNotificationsUtil::add("BoxxyAOAnimationUnavailable");
                    mChangedSignal();
                    requestReload();
                    return;
                }

                if (callback_state)
                {
                    callback_state->inventory_id = category_id;
                    // Options may have changed while folder creation was in
                    // flight; persist the latest state name, not the snapshot
                    // used to begin the request.
                    saveStateOptions(callback_state);
                }
                for (const LLUUID& pending_item : pending_items)
                {
                    createAnimationLinkInCategory(category_id, key.first,
                                                  key.second, pending_item);
                }
            });
        return;
    }

    createAnimationLinkInCategory(state->inventory_id, set_id, state_type, item_id);
}

void LLBoxxyAO::createAnimationLinkInCategory(const LLUUID& category_id,
                                              const LLUUID& set_id,
                                              EState state_type,
                                              const LLUUID& item_id)
{
    const LLInventoryItem* item = gInventory.getItem(item_id);
    if (category_id.isNull() || !item)
    {
        LL_WARNS("BoxxyAO") << "Cannot create AO animation link for " << item_id
                             << " in category " << category_id << LL_ENDL;
        Set* callback_set = findSetByInventoryID(set_id);
        State* callback_state = stateForType(callback_set, state_type);
        if (callback_state)
        {
            auto& animations = callback_state->animations;
            animations.erase(std::remove_if(animations.begin(), animations.end(),
                [&item_id](const Animation& queued_animation)
                {
                    return queued_animation.inventory_id.isNull() &&
                        queued_animation.original_id == item_id;
                }), animations.end());
            normalizeAnimationOrder(callback_state);
        }
        LLNotificationsUtil::add("BoxxyAOAnimationUnavailable");
        mChangedSignal();
        requestReload();
        return;
    }

    LLInventoryObject::const_object_list_t objects;
    objects.emplace_back(LLConstPointer<LLInventoryObject>(item));
    const LLUUID original_id = item->getLinkedUUID();
    LLPointer<LLInventoryCallback> callback = new LLBoostFuncInventoryCallback(
        [this, set_id, state_type, original_id](const LLUUID& link_id)
        {
            Set* callback_set = findSetByInventoryID(set_id);
            State* callback_state = stateForType(callback_set, state_type);
            if (link_id.isNull())
            {
                LL_WARNS("BoxxyAO") << "Failed to create inventory link for AO animation "
                                     << original_id << LL_ENDL;
                if (callback_state)
                {
                    auto& animations = callback_state->animations;
                    animations.erase(std::remove_if(animations.begin(), animations.end(),
                        [&original_id](const Animation& queued_animation)
                        {
                            return queued_animation.inventory_id.isNull() &&
                                queued_animation.original_id == original_id;
                        }), animations.end());
                    normalizeAnimationOrder(callback_state);
                }
                LLNotificationsUtil::add("BoxxyAOAnimationUnavailable");
                mChangedSignal();
                requestReload();
                return;
            }

            // Give the optimistic row the identity of its completed link and
            // write its order immediately. The subsequent reload can then
            // converge without dropping or alphabetically reordering it.
            bool animation_still_present = false;
            if (callback_state)
            {
                for (Animation& queued_animation : callback_state->animations)
                {
                    if (queued_animation.original_id == original_id)
                    {
                        animation_still_present = true;
                        if (queued_animation.inventory_id.isNull())
                        {
                            queued_animation.inventory_id = link_id;
                        }
                        break;
                    }
                }
                if (animation_still_present)
                {
                    normalizeAnimationOrder(callback_state);
                }
                else
                {
                    // The user removed the optimistic row before its request
                    // completed. Remove the late server link as well so it
                    // cannot reappear on the next reload.
                    remove_inventory_object(link_id, nullptr);
                }
            }
            requestReload();
        });
    link_inventory_array(category_id, objects, callback);
}

void LLBoxxyAO::removeAnimation(State* state, S32 index)
{
    if (!state || index < 0 || index >= static_cast<S32>(state->animations.size()))
    {
        return;
    }
    const LLUUID link_id = state->animations[index].inventory_id;
    if (link_id.notNull())
    {
        remove_inventory_object(link_id, nullptr);
    }
    state->animations.erase(state->animations.begin() + index);
    normalizeAnimationOrder(state);
    mChangedSignal();
}

bool LLBoxxyAO::moveAnimation(State* state, S32 index, S32 direction)
{
    if (!state || index < 0 || index >= static_cast<S32>(state->animations.size()))
    {
        return false;
    }
    const S32 destination = index + direction;
    if (destination < 0 || destination >= static_cast<S32>(state->animations.size()))
    {
        return false;
    }
    std::swap(state->animations[index], state->animations[destination]);
    normalizeAnimationOrder(state);
    mChangedSignal();
    return true;
}

void LLBoxxyAO::normalizeAnimationOrder(State* state)
{
    if (!state)
    {
        return;
    }
    for (S32 i = 0; i < static_cast<S32>(state->animations.size()); ++i)
    {
        Animation& animation = state->animations[i];
        animation.sort_order = i;
        LLViewerInventoryItem* item = gInventory.getItem(animation.inventory_id);
        if (item && item->LLInventoryItem::getDescription() != llformat("%d", i))
        {
            LLPointer<LLViewerInventoryItem> updated = new LLViewerInventoryItem(item);
            updated->setDescription(llformat("%d", i));
            updated->setComplete(true);
            updated->updateServer(false);
            gInventory.updateItem(updated);
        }
    }
}

void LLBoxxyAO::setCycle(State* state, bool enabled)
{
    if (!state) return;
    state->cycle = enabled;
    saveStateOptions(state);
    restartCycleTimer(state);
    mChangedSignal();
}

void LLBoxxyAO::setRandomize(State* state, bool enabled)
{
    if (!state) return;
    state->randomize = enabled;
    saveStateOptions(state);
    mChangedSignal();
}

void LLBoxxyAO::setCycleSeconds(State* state, F32 seconds)
{
    if (!state) return;
    state->cycle_seconds = llclamp(seconds, 0.f, 3600.f);
    saveStateOptions(state);
    restartCycleTimer(state);
    mChangedSignal();
}

void LLBoxxyAO::restartCycleTimer(State* state)
{
    mCycleTimer.stop();
    if (state && state->type == STATE_STANDING && isAgentAvatarValid() &&
        (gAgent.getFlying() || gAgentAvatarp->mInAir))
    {
        mStandCyclePaused = true;
        return;
    }
    if (state && state->type == STATE_STANDING)
    {
        mStandCyclePaused = false;
    }
    if (mEnabled && state && state->cycle && state->cycle_seconds > 0.f &&
        state->animations.size() > 1 && state->current_asset.notNull())
    {
        mCycleTimer.start();
        mCycleTimer.setTimerExpirySec(state->cycle_seconds);
        LL_INFOS("BoxxyAO") << "Started cycle timer for " << state->name
                             << " at " << state->cycle_seconds << " seconds." << LL_ENDL;
    }
}

void LLBoxxyAO::cycle(S32 direction)
{
    performCycle(direction < 0 ? -1 : 1);
}

void LLBoxxyAO::playAnimation(S32 index)
{
    State* state = getCurrentState();
    if (!state || index < 0 || index >= static_cast<S32>(state->animations.size()))
    {
        return;
    }
    state->current_animation = static_cast<U32>(index);
    performCycle(0);
}

void LLBoxxyAO::performCycle(S32 direction)
{
    State* state = getCurrentState();
    if (!mEnabled || !state || state->animations.empty() || state->current_asset.isNull())
    {
        return;
    }
    if (state->type == STATE_STANDING && isAgentAvatarValid() &&
        (gAgent.getFlying() || gAgentAvatarp->mInAir))
    {
        mCycleTimer.stop();
        mStandCyclePaused = true;
        return;
    }

    // A second cycle request must not overwrite the bookkeeping for an
    // in-flight handoff. Once the simulator has acknowledged the replacement,
    // complete that handoff; otherwise keep the current selection unchanged.
    completePendingCycleStop(false);
    if (mPendingCycleStop.notNull())
    {
        restartCycleTimer(state);
        return;
    }

    const LLUUID old_asset = state->current_asset;
    if (direction == 0)
    {
        // The caller selected current_animation explicitly.
    }
    else if (state->randomize && state->animations.size() > 1)
    {
        U32 next = state->current_animation;
        while (next == state->current_animation)
        {
            next = static_cast<U32>(ll_frand() * state->animations.size());
            next = llmin<U32>(next, static_cast<U32>(state->animations.size() - 1));
        }
        state->current_animation = next;
    }
    else if (direction < 0)
    {
        state->current_animation = state->current_animation == 0
            ? static_cast<U32>(state->animations.size() - 1)
            : state->current_animation - 1;
    }
    else
    {
        state->current_animation = (state->current_animation + 1) % state->animations.size();
    }

    const LLUUID next_asset = resolveAnimationAsset(
        state->animations[state->current_animation]);
    if (next_asset.isNull())
    {
        // Keep the old pose alive while the selected link target is fetched.
        // A later cycle/play request can retry without creating a neutral gap.
        state->current_asset = old_asset;
        restartCycleTimer(state);
        mChangedSignal();
        return;
    }

    state->current_asset = next_asset;
    if (state->current_asset != old_asset)
    {
        // Start the replacement locally before stopping the previous motion.
        // Waiting for the simulator's animation-state echo left the avatar in
        // the neutral pose for a visible fraction of a second between stands.
        gAgent.sendAnimationRequest(state->current_asset, ANIM_REQUEST_START);
        gAgentAvatarp->LLCharacter::startMotion(state->current_asset);
        if (old_asset.notNull())
        {
            // Motion startup can return success while its asset is still
            // loading. Keep the prior stand alive until the replacement is
            // genuinely active, then retire it from both viewer and simulator.
            mPendingCycleStart = state->current_asset;
            mPendingCycleStop = old_asset;
        }
    }
    restartCycleTimer(state);
    mChangedSignal();
}

void LLBoxxyAO::completePendingCycleStop(bool force)
{
    if (mPendingCycleStop.isNull())
    {
        return;
    }
    if (!force)
    {
        if (!isAgentAvatarValid() || mPendingCycleStart.isNull())
        {
            return;
        }

        LLMotionController& controller = gAgentAvatarp->getMotionController();
        LLMotion* replacement = controller.findMotion(mPendingCycleStart);
        const bool locally_ready = replacement &&
            !controller.isMotionLoading(replacement) &&
            controller.isMotionActive(replacement) && !replacement->isStopped();
        const bool simulator_ready =
            gAgentAvatarp->mSignaledAnimations.find(mPendingCycleStart) !=
            gAgentAvatarp->mSignaledAnimations.end();
        if (!locally_ready || !simulator_ready)
        {
            return;
        }
    }

    gAgent.sendAnimationRequest(mPendingCycleStop, ANIM_REQUEST_STOP);
    if (isAgentAvatarValid())
    {
        gAgentAvatarp->LLCharacter::stopMotion(mPendingCycleStop);
    }
    mPendingCycleStart.setNull();
    mPendingCycleStop.setNull();
}

void LLBoxxyAO::onMouselookChanged(bool mouselook)
{
    mInMouselook = mouselook;
}

void LLBoxxyAO::onBelowWaterChanged(bool below_water)
{
    if (mBelowWater == below_water)
    {
        return;
    }
    if (mEnabled) stopCurrentOverride(true);
    mBelowWater = below_water;
    if (mEnabled) startCurrentOverride();
}

void LLBoxxyAO::onRegionChanged()
{
    if (mEnabled && mLastMotion.notNull())
    {
        gAgent.sendAnimationRequest(mLastMotion, ANIM_REQUEST_START);
    }
}
