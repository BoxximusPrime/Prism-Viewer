/**
 * @file llboxxyao.h
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

#ifndef LL_LLBOXXYAO_H
#define LL_LLBOXXYAO_H

#include "lleventtimer.h"
#include "llsingleton.h"
#include "lltimer.h"
#include "lluuid.h"

#include <array>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <vector>

class LLInventoryItem;

class LLBoxxyAO final : public LLEventTimer, public LLSingleton<LLBoxxyAO>
{
    LLSINGLETON(LLBoxxyAO);
    ~LLBoxxyAO() override;

public:
    enum EState
    {
        STATE_STANDING = 0,
        STATE_WALKING,
        STATE_RUNNING,
        STATE_SITTING,
        STATE_SITTING_GROUND,
        STATE_CROUCHING,
        STATE_CROUCH_WALKING,
        STATE_LANDING,
        STATE_SOFT_LANDING,
        STATE_STANDING_UP,
        STATE_FALLING,
        STATE_FLYING_DOWN,
        STATE_FLYING_UP,
        STATE_FLYING,
        STATE_FLYING_SLOW,
        STATE_HOVERING,
        STATE_JUMPING,
        STATE_PRE_JUMPING,
        STATE_TURNING_RIGHT,
        STATE_TURNING_LEFT,
        STATE_TYPING,
        STATE_FLOATING,
        STATE_SWIMMING_FORWARD,
        STATE_SWIMMING_UP,
        STATE_SWIMMING_DOWN,
        STATE_COUNT
    };

    struct Animation
    {
        std::string name;
        LLUUID inventory_id; // Link in #Boxxy/#AO.
        LLUUID original_id;  // User's original inventory item.
        LLUUID asset_id;
        S32 sort_order = -1;
    };

    struct State
    {
        EState type = STATE_STANDING;
        std::string name;
        LLUUID stock_motion;
        LLUUID inventory_id;
        std::vector<Animation> animations;
        U32 current_animation = 0;
        LLUUID current_asset;
        bool cycle = false;
        bool randomize = false;
        F32 cycle_seconds = 30.f;
    };

    struct Set
    {
        std::string name;
        LLUUID inventory_id;
        bool override_sits = false;
        std::array<State, STATE_COUNT> states;
    };

    void onLoginComplete();
    void shutdown();

    bool tick() override;
    LLUUID overrideMotion(const LLUUID& motion, bool start);
    void onMouselookChanged(bool mouselook);
    void onBelowWaterChanged(bool below_water);
    void onRegionChanged();

    bool isEnabled() const { return mEnabled; }
    void setEnabled(bool enabled);

    const std::vector<std::unique_ptr<Set>>& getSets() const { return mSets; }
    Set* getCurrentSet() const { return mCurrentSet; }
    State* getCurrentState() const;
    Set* findSet(const std::string& name) const;

    void selectSet(Set* set);
    void createSet(const std::string& name);
    void removeSet(Set* set);
    void setOverrideSits(Set* set, bool enabled);

    void addAnimation(Set* set, State* state, const LLInventoryItem* item);
    void removeAnimation(State* state, S32 index);
    bool moveAnimation(State* state, S32 index, S32 direction);
    void setCycle(State* state, bool enabled);
    void setRandomize(State* state, bool enabled);
    void setCycleSeconds(State* state, F32 seconds);
    void cycle(S32 direction);
    void playAnimation(S32 index);

    void requestReload();
    const LLUUID& getAOFolder() const { return mAOFolder; }

    using changed_signal_t = boost::signals2::signal<void()>;
    boost::signals2::connection setChangedCallback(const changed_signal_t::slot_type& cb)
    {
        return mChangedSignal.connect(cb);
    }

private:
    void initializeStates(Set& set) const;
    State* stateForMotion(const LLUUID& motion) const;
    State* stateForType(Set* set, EState type) const;
    Set* findSetByInventoryID(const LLUUID& id) const;

    void ensureInventoryFolders();
    bool loadInventory();
    bool loadSet(const LLUUID& category_id, const std::string& folder_name,
                 std::unique_ptr<Set>& result);
    bool loadState(Set& set, const LLUUID& category_id, const std::string& folder_name);
    bool inventoryMatches(const std::vector<std::unique_ptr<Set>>& loaded_sets) const;
    void saveSetOptions(Set* set);
    void saveStateOptions(State* state);
    void normalizeAnimationOrder(State* state);

    void createAnimationLink(const LLUUID& set_id, EState state_type,
                             const LLUUID& item_id);
    void createAnimationLinkInCategory(const LLUUID& category_id,
                                       const LLUUID& set_id, EState state_type,
                                       const LLUUID& item_id);
    LLUUID resolveAnimationAsset(Animation& animation);
    void startCurrentOverride();
    void applyPendingOverrideIfReady();
    void stopCurrentOverride(bool restore_stock);
    void stopStockMotionVariants(const LLUUID& motion);
    void restartCycleTimer(State* state);
    void performCycle(S32 direction);
    void completePendingCycleStop(bool force);
    bool isTransientMotion(const LLUUID& motion) const;

    changed_signal_t mChangedSignal;
    std::vector<std::unique_ptr<Set>> mSets;
    Set* mCurrentSet = nullptr;

    LLUUID mBoxxyFolder;
    LLUUID mAOFolder;
    LLUUID mLastMotion;
    LLUUID mLastOverriddenMotion;
    LLUUID mPendingCycleStart;
    LLUUID mPendingCycleStop;

    using pending_add_key_t = std::pair<LLUUID, EState>;
    std::map<pending_add_key_t, std::vector<LLUUID>> mPendingAnimationAdds;
    std::set<LLUUID> mIgnoredStockStops;

    bool mEnabled = false;
    bool mLoggedIn = false;
    bool mInventoryReady = false;
    bool mCreatePending = false;
    bool mReloadRequested = true;
    bool mInMouselook = false;
    bool mBelowWater = false;
    bool mStandCyclePaused = false;
    bool mInventoryItemsPending = false;
    bool mOverrideApplyPending = false;
    U32 mInventoryRetryPasses = 0;

    LLTimer mInventoryTimer;
    LLTimer mCycleTimer;
    boost::signals2::connection mRegionConnection;
};

#endif // LL_LLBOXXYAO_H
