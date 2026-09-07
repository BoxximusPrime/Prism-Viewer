/**
 * @file llfloaterboxxyao.h
 * @brief Boxxy animation overrider manager and launcher floaters.
 *
 * $LicenseInfo:firstyear=2026&license=viewerlgpl$
 * Copyright (C) 2026 Boxxy Viewer contributors
 * $/LicenseInfo$
 */

#ifndef LL_LLFLOATERBOXXYAO_H
#define LL_LLFLOATERBOXXYAO_H

#include "llboxxyao.h"
#include "llfloater.h"

class LLButton;
class LLCheckBoxCtrl;
class LLComboBox;
class LLScrollListCtrl;
class LLSpinCtrl;
class LLTextBox;

class LLFloaterBoxxyAO final : public LLFloater
{
    friend class LLFloaterReg;

private:
    explicit LLFloaterBoxxyAO(const LLSD& key);
    ~LLFloaterBoxxyAO() override;

public:
    bool postBuild() override;
    void onOpen(const LLSD& key) override;
    void draw() override;
    bool handleDragAndDrop(S32 x, S32 y, MASK mask, bool drop,
                           EDragAndDropType cargo_type, void* cargo_data,
                           EAcceptance* accept, std::string& tooltip_msg) override;

private:
    void refresh();
    void refreshSets();
    void refreshStates();
    void refreshAnimations();
    void updateControls();

    void onSetSelected();
    void onStateSelected();
    void onAnimationSelected();
    void onActivateSet();
    void onNewSet();
    void onRemoveSet();
    void onRemoveAnimation();
    void onMoveAnimation(S32 direction);
    void onPlayAnimation();
    void onCyclePrevious();
    void onCycleNext();
    void onEnabledChanged();
    void onOverrideSitsChanged();
    void onCycleChanged();
    void onRandomizeChanged();
    void onCycleSecondsChanged();
    void onOpenInventory();

    bool newSetCallback(const LLSD& notification, const LLSD& response);
    bool removeSetCallback(const LLSD& notification, const LLSD& response);

    LLBoxxyAO::Set* selectedSet() const;
    LLBoxxyAO::State* selectedState() const;
    S32 selectedAnimationIndex() const;

    LLComboBox* mSetCombo = nullptr;
    LLScrollListCtrl* mStateList = nullptr;
    LLScrollListCtrl* mAnimationList = nullptr;
    LLCheckBoxCtrl* mEnabled = nullptr;
    LLCheckBoxCtrl* mOverrideSits = nullptr;
    LLCheckBoxCtrl* mCycle = nullptr;
    LLCheckBoxCtrl* mRandomize = nullptr;
    LLSpinCtrl* mCycleSeconds = nullptr;
    LLTextBox* mDropHint = nullptr;

    std::string mSelectedSetName;
    LLBoxxyAO::EState mSelectedState = LLBoxxyAO::STATE_STANDING;
    bool mRefreshing = false;
    boost::signals2::connection mEngineConnection;
};

class LLFloaterBoxxyAOLauncher final : public LLFloater
{
    friend class LLFloaterReg;

private:
    explicit LLFloaterBoxxyAOLauncher(const LLSD& key);
    ~LLFloaterBoxxyAOLauncher() override;

public:
    bool postBuild() override;
    void onOpen(const LLSD& key) override;

private:
    void refresh();
    void onOpenManager();
    void onEnabledChanged();

    LLCheckBoxCtrl* mEnabled = nullptr;
    bool mRefreshing = false;
    boost::signals2::connection mEngineConnection;
};

#endif // LL_LLFLOATERBOXXYAO_H
