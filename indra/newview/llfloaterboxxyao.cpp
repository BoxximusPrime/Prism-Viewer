/**
 * @file llfloaterboxxyao.cpp
 * @brief Boxxy animation overrider manager and launcher floaters.
 *
 * $LicenseInfo:firstyear=2026&license=viewerlgpl$
 * Copyright (C) 2026 Boxxy Viewer contributors
 * $/LicenseInfo$
 */

#include "llviewerprecompiledheaders.h"

#include "llfloaterboxxyao.h"

#include "llbutton.h"
#include "llcheckboxctrl.h"
#include "llcombobox.h"
#include "llfloaterreg.h"
#include "llinventorymodel.h"
#include "llnotificationsutil.h"
#include "llscrolllistctrl.h"
#include "llspinctrl.h"
#include "lltextbox.h"
#include "llviewerinventory.h"

LLFloaterBoxxyAO::LLFloaterBoxxyAO(const LLSD& key)
: LLFloater(key)
{
}

LLFloaterBoxxyAO::~LLFloaterBoxxyAO()
{
    mEngineConnection.disconnect();
}

bool LLFloaterBoxxyAO::postBuild()
{
    mSetCombo = getChild<LLComboBox>("set_combo");
    mStateList = getChild<LLScrollListCtrl>("state_list");
    mAnimationList = getChild<LLScrollListCtrl>("animation_list");
    mEnabled = getChild<LLCheckBoxCtrl>("ao_enabled");
    mOverrideSits = getChild<LLCheckBoxCtrl>("override_sits");
    mCycle = getChild<LLCheckBoxCtrl>("cycle_enabled");
    mRandomize = getChild<LLCheckBoxCtrl>("cycle_randomize");
    mCycleSeconds = getChild<LLSpinCtrl>("cycle_seconds");
    mDropHint = getChild<LLTextBox>("drop_hint");

    mSetCombo->setCommitCallback(boost::bind(&LLFloaterBoxxyAO::onSetSelected, this));
    mStateList->setCommitCallback(boost::bind(&LLFloaterBoxxyAO::onStateSelected, this));
    mAnimationList->setCommitCallback(boost::bind(&LLFloaterBoxxyAO::onAnimationSelected, this));
    mAnimationList->setDoubleClickCallback(boost::bind(&LLFloaterBoxxyAO::onPlayAnimation, this));
    mEnabled->setCommitCallback(boost::bind(&LLFloaterBoxxyAO::onEnabledChanged, this));
    mOverrideSits->setCommitCallback(boost::bind(&LLFloaterBoxxyAO::onOverrideSitsChanged, this));
    mCycle->setCommitCallback(boost::bind(&LLFloaterBoxxyAO::onCycleChanged, this));
    mRandomize->setCommitCallback(boost::bind(&LLFloaterBoxxyAO::onRandomizeChanged, this));
    mCycleSeconds->setCommitCallback(boost::bind(&LLFloaterBoxxyAO::onCycleSecondsChanged, this));

    getChild<LLButton>("activate_set")->setCommitCallback(boost::bind(&LLFloaterBoxxyAO::onActivateSet, this));
    getChild<LLButton>("new_set")->setCommitCallback(boost::bind(&LLFloaterBoxxyAO::onNewSet, this));
    getChild<LLButton>("remove_set")->setCommitCallback(boost::bind(&LLFloaterBoxxyAO::onRemoveSet, this));
    getChild<LLButton>("remove_animation")->setCommitCallback(boost::bind(&LLFloaterBoxxyAO::onRemoveAnimation, this));
    getChild<LLButton>("move_up")->setCommitCallback(boost::bind(&LLFloaterBoxxyAO::onMoveAnimation, this, -1));
    getChild<LLButton>("move_down")->setCommitCallback(boost::bind(&LLFloaterBoxxyAO::onMoveAnimation, this, 1));
    getChild<LLButton>("play_animation")->setCommitCallback(boost::bind(&LLFloaterBoxxyAO::onPlayAnimation, this));
    getChild<LLButton>("previous_animation")->setCommitCallback(boost::bind(&LLFloaterBoxxyAO::onCyclePrevious, this));
    getChild<LLButton>("next_animation")->setCommitCallback(boost::bind(&LLFloaterBoxxyAO::onCycleNext, this));
    getChild<LLButton>("open_inventory")->setCommitCallback(boost::bind(&LLFloaterBoxxyAO::onOpenInventory, this));

    mEngineConnection = LLBoxxyAO::instance().setChangedCallback(
        boost::bind(&LLFloaterBoxxyAO::refresh, this));
    refresh();
    return true;
}

void LLFloaterBoxxyAO::onOpen(const LLSD& key)
{
    LLFloater::onOpen(key);
    refresh();
}

void LLFloaterBoxxyAO::refresh()
{
    if (!mSetCombo || mRefreshing)
    {
        return;
    }
    mRefreshing = true;

    if (mSelectedSetName.empty() && LLBoxxyAO::instance().getCurrentSet())
    {
        mSelectedSetName = LLBoxxyAO::instance().getCurrentSet()->name;
    }
    refreshSets();
    refreshStates();
    refreshAnimations();
    updateControls();

    mRefreshing = false;
}

void LLFloaterBoxxyAO::refreshSets()
{
    mSetCombo->removeall();
    for (const auto& set : LLBoxxyAO::instance().getSets())
    {
        std::string label = set->name;
        if (set.get() == LLBoxxyAO::instance().getCurrentSet())
        {
            label += "  (active)";
        }
        mSetCombo->add(label, LLSD(set->name));
    }

    if (!mSelectedSetName.empty())
    {
        mSetCombo->setSelectedByValue(LLSD(mSelectedSetName), true);
    }
    if (mSetCombo->getCurrentIndex() < 0 && mSetCombo->getItemCount() > 0)
    {
        mSetCombo->setCurrentByIndex(0);
        mSelectedSetName = mSetCombo->getSelectedValue().asString();
    }
}

void LLFloaterBoxxyAO::refreshStates()
{
    mStateList->deleteAllItems();
    LLBoxxyAO::Set* set = selectedSet();
    if (!set)
    {
        return;
    }

    for (S32 i = 0; i < LLBoxxyAO::STATE_COUNT; ++i)
    {
        const LLBoxxyAO::State& state = set->states[i];
        LLSD row;
        row["columns"][0]["column"] = "state";
        row["columns"][0]["value"] = state.name;
        row["columns"][1]["column"] = "count";
        row["columns"][1]["value"] = llformat("%d", static_cast<S32>(state.animations.size()));
        mStateList->addElement(row, ADD_BOTTOM);
    }
    mStateList->selectNthItem(static_cast<S32>(mSelectedState));
}

void LLFloaterBoxxyAO::refreshAnimations()
{
    mAnimationList->deleteAllItems();
    LLBoxxyAO::State* state = selectedState();
    if (!state)
    {
        return;
    }

    for (S32 i = 0; i < static_cast<S32>(state->animations.size()); ++i)
    {
        const LLBoxxyAO::Animation& animation = state->animations[i];
        LLSD row;
        row["columns"][0]["column"] = "playing";
        row["columns"][0]["value"] = animation.asset_id == state->current_asset ? "▶" : "";
        row["columns"][1]["column"] = "animation";
        row["columns"][1]["value"] = animation.name;
        mAnimationList->addElement(row, ADD_BOTTOM);
    }
}

void LLFloaterBoxxyAO::updateControls()
{
    LLBoxxyAO& engine = LLBoxxyAO::instance();
    LLBoxxyAO::Set* set = selectedSet();
    LLBoxxyAO::State* state = selectedState();
    const bool has_set = set != nullptr;
    const bool has_state = state != nullptr;
    const bool has_animation = selectedAnimationIndex() >= 0;

    mEnabled->setValue(engine.isEnabled());
    mOverrideSits->setValue(set ? set->override_sits : false);
    mOverrideSits->setEnabled(has_set);
    mCycle->setValue(state ? state->cycle : false);
    mCycle->setEnabled(has_state);
    mRandomize->setValue(state ? state->randomize : false);
    mRandomize->setEnabled(has_state && state->cycle);
    mCycleSeconds->setValue(state ? state->cycle_seconds : 30.f);
    mCycleSeconds->setEnabled(has_state && state->cycle);

    getChild<LLButton>("activate_set")->setEnabled(has_set && set != engine.getCurrentSet());
    getChild<LLButton>("remove_set")->setEnabled(has_set);
    getChild<LLButton>("remove_animation")->setEnabled(has_animation);
    getChild<LLButton>("move_up")->setEnabled(has_animation && selectedAnimationIndex() > 0);
    getChild<LLButton>("move_down")->setEnabled(has_animation && state &&
        selectedAnimationIndex() + 1 < static_cast<S32>(state->animations.size()));
    const bool editing_current_state = state && state == engine.getCurrentState();
    getChild<LLButton>("play_animation")->setEnabled(has_animation && editing_current_state && engine.isEnabled());
    getChild<LLButton>("previous_animation")->setEnabled(editing_current_state && state->animations.size() > 1);
    getChild<LLButton>("next_animation")->setEnabled(editing_current_state && state->animations.size() > 1);

    if (!has_set)
    {
        mDropHint->setValue("Create an animation set to begin.");
    }
    else if (!has_state)
    {
        mDropHint->setValue("Select an animation state.");
    }
    else
    {
        mDropHint->setValue("Drag animations here from Inventory to add links to " + state->name + ".");
    }
}

LLBoxxyAO::Set* LLFloaterBoxxyAO::selectedSet() const
{
    return LLBoxxyAO::instance().findSet(mSelectedSetName);
}

LLBoxxyAO::State* LLFloaterBoxxyAO::selectedState() const
{
    LLBoxxyAO::Set* set = selectedSet();
    return set ? &set->states[static_cast<S32>(mSelectedState)] : nullptr;
}

S32 LLFloaterBoxxyAO::selectedAnimationIndex() const
{
    return mAnimationList ? mAnimationList->getFirstSelectedIndex() : -1;
}

void LLFloaterBoxxyAO::onSetSelected()
{
    if (mRefreshing) return;
    mSelectedSetName = mSetCombo->getSelectedValue().asString();
    refresh();
}

void LLFloaterBoxxyAO::onStateSelected()
{
    if (mRefreshing || !mStateList->getFirstSelected()) return;
    mSelectedState = static_cast<LLBoxxyAO::EState>(mStateList->getFirstSelectedIndex());
    refreshAnimations();
    updateControls();
}

void LLFloaterBoxxyAO::onAnimationSelected()
{
    if (!mRefreshing) updateControls();
}

void LLFloaterBoxxyAO::onActivateSet()
{
    LLBoxxyAO::instance().selectSet(selectedSet());
}

void LLFloaterBoxxyAO::onNewSet()
{
    LLNotificationsUtil::add("BoxxyAONewSet", LLSD(), LLSD(),
        boost::bind(&LLFloaterBoxxyAO::newSetCallback, this, _1, _2));
}

bool LLFloaterBoxxyAO::newSetCallback(const LLSD& notification, const LLSD& response)
{
    if (LLNotificationsUtil::getSelectedOption(notification, response) == 0)
    {
        const std::string name = response["set_name"].asString();
        mSelectedSetName = name;
        LLBoxxyAO::instance().createSet(name);
    }
    return false;
}

void LLFloaterBoxxyAO::onRemoveSet()
{
    LLBoxxyAO::Set* set = selectedSet();
    if (!set) return;
    LLSD args;
    args["SET_NAME"] = set->name;
    LLNotificationsUtil::add("BoxxyAORemoveSet", args, LLSD(),
        boost::bind(&LLFloaterBoxxyAO::removeSetCallback, this, _1, _2));
}

bool LLFloaterBoxxyAO::removeSetCallback(const LLSD& notification, const LLSD& response)
{
    if (LLNotificationsUtil::getSelectedOption(notification, response) == 0)
    {
        LLBoxxyAO::instance().removeSet(selectedSet());
        mSelectedSetName.clear();
    }
    return false;
}

void LLFloaterBoxxyAO::onRemoveAnimation()
{
    LLBoxxyAO::instance().removeAnimation(selectedState(), selectedAnimationIndex());
    refreshAnimations();
    updateControls();
}

void LLFloaterBoxxyAO::onMoveAnimation(S32 direction)
{
    const S32 index = selectedAnimationIndex();
    if (LLBoxxyAO::instance().moveAnimation(selectedState(), index, direction))
    {
        refreshAnimations();
        mAnimationList->selectNthItem(index + direction);
        updateControls();
    }
}

void LLFloaterBoxxyAO::onPlayAnimation()
{
    if (selectedState() != LLBoxxyAO::instance().getCurrentState()) return;
    LLBoxxyAO::instance().playAnimation(selectedAnimationIndex());
}

void LLFloaterBoxxyAO::onCyclePrevious()
{
    if (selectedState() == LLBoxxyAO::instance().getCurrentState()) LLBoxxyAO::instance().cycle(-1);
}

void LLFloaterBoxxyAO::onCycleNext()
{
    if (selectedState() == LLBoxxyAO::instance().getCurrentState()) LLBoxxyAO::instance().cycle(1);
}

void LLFloaterBoxxyAO::onEnabledChanged()
{
    if (!mRefreshing) LLBoxxyAO::instance().setEnabled(mEnabled->getValue().asBoolean());
}

void LLFloaterBoxxyAO::onOverrideSitsChanged()
{
    if (!mRefreshing) LLBoxxyAO::instance().setOverrideSits(selectedSet(), mOverrideSits->getValue().asBoolean());
}

void LLFloaterBoxxyAO::onCycleChanged()
{
    if (!mRefreshing) LLBoxxyAO::instance().setCycle(selectedState(), mCycle->getValue().asBoolean());
}

void LLFloaterBoxxyAO::onRandomizeChanged()
{
    if (!mRefreshing) LLBoxxyAO::instance().setRandomize(selectedState(), mRandomize->getValue().asBoolean());
}

void LLFloaterBoxxyAO::onCycleSecondsChanged()
{
    if (!mRefreshing) LLBoxxyAO::instance().setCycleSeconds(selectedState(), mCycleSeconds->getValueF32());
}

void LLFloaterBoxxyAO::onOpenInventory()
{
    LLFloaterReg::showInstance("inventory");
}

bool LLFloaterBoxxyAO::handleDragAndDrop(S32 x, S32 y, MASK mask, bool drop,
                                         EDragAndDropType cargo_type, void* cargo_data,
                                         EAcceptance* accept, std::string& tooltip_msg)
{
    if (cargo_type == DAD_ANIMATION && selectedSet() && selectedState())
    {
        *accept = ACCEPT_YES_COPY_SINGLE;
        tooltip_msg = "Add an inventory link to the selected AO state";
        if (drop)
        {
            const LLInventoryItem* item = static_cast<const LLInventoryItem*>(cargo_data);
            LLBoxxyAO::instance().addAnimation(selectedSet(), selectedState(), item);
        }
        return true;
    }

    *accept = ACCEPT_NO;
    tooltip_msg = "Select a set and state, then drag an animation from Inventory";
    return true;
}

LLFloaterBoxxyAOLauncher::LLFloaterBoxxyAOLauncher(const LLSD& key)
: LLFloater(key)
{
}

LLFloaterBoxxyAOLauncher::~LLFloaterBoxxyAOLauncher()
{
    mEngineConnection.disconnect();
}

bool LLFloaterBoxxyAOLauncher::postBuild()
{
    mEnabled = getChild<LLCheckBoxCtrl>("ao_enabled");
    mEnabled->setCommitCallback(boost::bind(&LLFloaterBoxxyAOLauncher::onEnabledChanged, this));
    getChild<LLButton>("open_manager")->setCommitCallback(
        boost::bind(&LLFloaterBoxxyAOLauncher::onOpenManager, this));
    mEngineConnection = LLBoxxyAO::instance().setChangedCallback(
        boost::bind(&LLFloaterBoxxyAOLauncher::refresh, this));
    refresh();
    return true;
}

void LLFloaterBoxxyAOLauncher::onOpen(const LLSD& key)
{
    LLFloater::onOpen(key);
    refresh();
}

void LLFloaterBoxxyAOLauncher::refresh()
{
    if (!mEnabled || mRefreshing) return;
    mRefreshing = true;
    mEnabled->setValue(LLBoxxyAO::instance().isEnabled());
    mRefreshing = false;
}

void LLFloaterBoxxyAOLauncher::onOpenManager()
{
    LLFloaterReg::toggleInstanceOrBringToFront("boxxy_ao");
}

void LLFloaterBoxxyAOLauncher::onEnabledChanged()
{
    if (!mRefreshing) LLBoxxyAO::instance().setEnabled(mEnabled->getValue().asBoolean());
}
