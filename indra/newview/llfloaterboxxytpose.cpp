/**
 * @file llfloaterboxxytpose.cpp
 * @brief Boxxy pose stand, adapted from Firestorm's FSFloaterPoseStand.
 *
 * "THE BEER-WARE LICENSE" (Revision 42):
 * Cinder Roxley wrote this file. As long as you retain this notice you can do
 * whatever you want with this stuff. If we meet some day, and you think this
 * stuff is worth it, you can buy me a beer in return <cinder.roxley@phoenixviewer.com>
 *
 * Boxxy Viewer adaptations Copyright (C) 2026 Boxxy Viewer contributors.
 */
#include "llviewerprecompiledheaders.h"
#include "llfloaterboxxytpose.h"

#include "llagent.h"
#include "llboxxyao.h"
#include "llcombobox.h"
#include "llfloaterreg.h"
#include "llviewercontrol.h"
#include "llvoavatarself.h"

namespace
{
struct Pose
{
    const char* name;
    const char* id;
};

// Firestorm's public Pose Stand animation set (app_settings/posestand.xml).
constexpr Pose POSES[] =
{
    { "T-Pose", "3481ccd5-cc6c-65ca-c466-dc9df1bf3944" },
    { "Arms Down, Legs Together", "0b4ee516-5dfd-ef4b-4ab6-300bb44cb045" },
    { "Arms Down, Sitting", "b23c52ef-0b15-11f2-852d-8fbd33417847" },
    { "Arms Downward, Legs Apart", "e14fee5f-3735-a236-2e26-94f92f366d81" },
    { "Arms Downward, Legs Together", "2029d88f-4efc-d72d-18d1-274caf9e9bc0" },
    { "Arms Forward, Legs Apart", "cff5559e-c915-0b5e-d587-f789b5cc299a" },
    { "Arms Forward, Legs Together", "23f3163c-183b-dac0-0cdd-7811bcc3b5f1" },
    { "Arms Straight, Legs Apart", "b2f312aa-2c1e-27b8-50fe-a0fa4ff3df4e" },
    { "Arms Straight, Sitting", "c17677b8-9fb2-8d6e-bbbe-219edce64ef4" },
    { "Arms Upward, Legs Apart", "2cfeed25-04f9-caff-f3d2-776cddea5771" },
    { "Arms Upward, Legs Together", "6e83f685-2f53-278f-6758-b529327cce09" },
};
}

LLFloaterBoxxyTPose::LLFloaterBoxxyTPose(const LLSD& key) : LLFloater(key) {}

bool LLFloaterBoxxyTPose::postBuild()
{
    mPoseCombo = getChild<LLComboBox>("pose_combo");
    for (const Pose& pose : POSES)
    {
        mPoseCombo->add(pose.name, LLUUID(pose.id));
    }
    mPoseCombo->selectFirstItem();
    mPoseCombo->setCommitCallback(boost::bind(&LLFloaterBoxxyTPose::onPoseSelected, this));
    return true;
}

void LLFloaterBoxxyTPose::onOpen(const LLSD& key)
{
    if (!gAgentAvatarp)
    {
        return;
    }
    if (mActivePose.notNull())
    {
        return;
    }
    onPoseSelected();
}

void LLFloaterBoxxyTPose::onClose(bool app_quitting)
{
    stopPose();
    gAgent.setCustomAnim(false);
    if (mAOPaused)
    {
        if (app_quitting)
        {
            // Preserve the user's enabled preference without restarting AO
            // while the viewer is tearing down.
            gSavedPerAccountSettings.setBOOL("BoxxyAOEnabled", true);
        }
        else if (!LLBoxxyAO::instance().isEnabled())
        {
            LLBoxxyAO::instance().setEnabled(true);
        }
    }
    mAOPaused = false;
}

void LLFloaterBoxxyTPose::onPoseSelected()
{
    if (!mPoseCombo || !gAgentAvatarp)
    {
        return;
    }
    if (LLBoxxyAO::instance().isEnabled())
    {
        LLBoxxyAO::instance().setEnabled(false);
        mAOPaused = true;
    }
    gAgent.setCustomAnim(true);
    stopPose();
    mActivePose = mPoseCombo->getValue().asUUID();
    if (mActivePose.notNull())
    {
        gAgent.sendAnimationRequest(mActivePose, ANIM_REQUEST_START);
        gAgentAvatarp->startMotion(mActivePose);
    }
}

void LLFloaterBoxxyTPose::stopPose()
{
    if (mActivePose.notNull() && gAgentAvatarp)
    {
        gAgent.sendAnimationRequest(mActivePose, ANIM_REQUEST_STOP);
        gAgentAvatarp->stopMotion(mActivePose, true);
    }
    mActivePose.setNull();
}
