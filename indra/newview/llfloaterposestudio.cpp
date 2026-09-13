/**
 * @file llfloaterposestudio.cpp
 * @brief Grouped bone browser and rotation controls for Pose Studio.
 * Copyright (C) 2026 Prism Viewer contributors.
 * SPDX-License-Identifier: LGPL-2.1-only
 */
#include "llviewerprecompiledheaders.h"
#include "llfloaterposestudio.h"

#include "llagent.h"
#include "llbutton.h"
#include "llfiltereditor.h"
#include "lljoint.h"
#include "llposestudio.h"
#include "llscrolllistctrl.h"
#include "llsliderctrl.h"
#include "lltextbox.h"
#include "llviewercontrol.h"
#include "llvoavatarself.h"

#include <array>
#include <cctype>

namespace
{
// Keep skeleton order and indent ancestry within each body area. Canonical
// names remain the row IDs and tooltips, never joint pointers.
const char* const GROUPS[] = { "body", "left_arm", "right_arm", "left_leg", "right_leg",
                             "left_hand", "right_hand", "face", "wings", "tail", "hind_legs", "other" };

size_t jointGroup(const std::string& name)
{
    const auto starts = [&name](const char* prefix) { return name.find(prefix) == 0; };
    const bool left = name.find("Left") != std::string::npos;
    if (starts("mHand")) return left ? 5 : 6;
    if (starts("mFace") || starts("mEye")) return 7;
    if (starts("mWing")) return 8;
    if (starts("mTail")) return 9;
    if (starts("mHind")) return 10;
    if (starts("mCollar") || starts("mShoulder") || starts("mElbow") || starts("mWrist")) return left ? 1 : 2;
    if (starts("mHip") || starts("mKnee") || starts("mAnkle") || starts("mFoot") || starts("mToe")) return left ? 3 : 4;
    if (starts("mPelvis") || starts("mSpine") || starts("mTorso") || starts("mChest")
        || starts("mNeck") || starts("mHead") || starts("mSkull")) return 0;
    return 11;
}

std::string jointLabel(const std::string& name)
{
    // The group already identifies face/finger bones. Split the remaining
    // canonical name into words, retaining the side and numbered segments.
    const size_t start = name.find("mFace") == 0 || name.find("mHand") == 0 ? 5 : 1;
    std::string label;
    for (size_t i = start; i < name.size(); ++i)
    {
        const unsigned char ch = name[i];
        if (i > start && (std::isupper(ch) || (std::isdigit(ch) && !std::isdigit(static_cast<unsigned char>(name[i - 1])))))
            label += ' ';
        label += ch;
    }
    return label;
}
}

LLFloaterPoseStudio::LLFloaterPoseStudio(const LLSD& key) : LLFloater(key) {}

LLFloaterPoseStudio::~LLFloaterPoseStudio()
{
    if (LLPoseStudio::instanceExists()) LLPoseStudio::instance().end();
}

bool LLFloaterPoseStudio::postBuild()
{
    mJointList = getChild<LLScrollListCtrl>("joints");
    mJointList->setCommitCallback([this](LLUICtrl*, const LLSD&) {
        if (mJointList->hasSelectedItem()) mSelectedJoint = mJointList->getValue().asString();
        refreshRotation();
    });
    mJointList->setCommentText(getString("no_matches"));
    getChild<LLFilterEditor>("bone_search")->setCommitCallback([this](LLUICtrl*, const LLSD& value) {
        mFilter = value.asString();
        LLStringUtil::trim(mFilter);
        LLStringUtil::toLower(mFilter);
        buildJointRows();
        mJointList->setScrollPos(0);
        refreshRotation();
    });
    const char* fields[] = { "rotation_x", "rotation_y", "rotation_z" };
    for (S32 i = 0; i < 3; ++i)
    {
        mRotation[i] = getChild<LLSliderCtrl>(fields[i]);
        mRotation[i]->setCommitCallback([this](LLUICtrl*, const LLSD&) { onRotation(); });
    }
    getChild<LLButton>("start")->setClickedCallback([this](LLUICtrl*, const LLSD&) { onStart(); });
    getChild<LLButton>("end")->setClickedCallback([this](LLUICtrl*, const LLSD&) {
        LLPoseStudio::instance().end();
        refresh();
    });
    getChild<LLButton>("reset_joint")->setClickedCallback([this](LLUICtrl*, const LLSD&) {
        LLPoseStudio::instance().resetJoint(mJointList->getValue().asString());
        refreshRows();
        refreshRotation();
    });
    getChild<LLButton>("reset_pose")->setClickedCallback([this](LLUICtrl*, const LLSD&) {
        LLPoseStudio::instance().resetPose();
        refreshRows();
        refreshRotation();
    });
    refresh();
    return true;
}

void LLFloaterPoseStudio::onOpen(const LLSD& key)
{
    mStartFailed = false;
    buildJointRows();
    refreshRotation();
    refresh();
}

void LLFloaterPoseStudio::onClose(bool app_quitting)
{
    LLPoseStudio::instance().end();
}

void LLFloaterPoseStudio::draw()
{
    refresh();
    LLFloater::draw();
}

void LLFloaterPoseStudio::onStart()
{
    mStartFailed = !isAgentAvatarValid() || gDisconnected
        || gAgent.getTeleportState() != LLAgent::TELEPORT_NONE
        || !LLPoseStudio::instance().begin(*gAgentAvatarp);
    buildJointRows();
    refreshRotation();
    refresh();
}

void LLFloaterPoseStudio::onRotation()
{
    LLPoseStudio::instance().setRotationOffset(mJointList->getValue().asString(),
        LLVector3(mRotation[0]->getValueF32(), mRotation[1]->getValueF32(), mRotation[2]->getValueF32()));
    refreshRows();
}

void LLFloaterPoseStudio::buildJointRows()
{
    const S32 scroll = mJointList->getScrollPos();
    mJointRows.clear();
    mJointList->deleteAllItems();
    mRowsBuilt = isAgentAvatarValid() && gAgentAvatarp->isBuilt();
    if (!mRowsBuilt) return;

    std::array<std::vector<std::pair<std::string, size_t>>, std::size(GROUPS)> groups;
    for (size_t i = 0; i < gAgentAvatarp->getSkeletonJointCount(); ++i)
    {
        if (LLJoint* joint = gAgentAvatarp->getSkeletonJoint(static_cast<S32>(i)))
        {
            const std::string& name = joint->getName();
            std::string searchable = name + " " + jointLabel(name);
            LLStringUtil::toLower(searchable);
            if (!mFilter.empty() && searchable.find(mFilter) == std::string::npos) continue;
            const size_t group = jointGroup(name);
            size_t depth = 1;
            for (LLJoint* parent = joint->getParent(); parent && jointGroup(parent->getName()) == group;
                 parent = parent->getParent()) ++depth;
            groups[group].emplace_back(name, depth);
        }
    }
    const LLColor4 group_color = LLUIColorTable::instance().getColor("PoseStudioGroupColor");
    for (size_t group = 0; group < groups.size(); ++group)
    {
        if (groups[group].empty()) continue;
        LLScrollListItem::Params heading;
        heading.enabled(false);
        heading.columns.add().column("bone").value(getString(GROUPS[group]))
            .font(LLFontGL::getFontSansSerifSmallBold()).color(group_color);
        mJointList->addRow(heading);
        for (const auto& [name, depth] : groups[group])
        {
            LLScrollListItem::Params row;
            row.value(name);
            row.columns.add().column("bone").value(std::string(depth * 2, ' ') + jointLabel(name)).tool_tip(name);
            for (const char* axis : { "x", "y", "z" })
                row.columns.add().column(axis).value("0.0").font_halign(LLFontGL::RIGHT);
            mJointRows.push_back(mJointList->addRow(row));
        }
    }
    if (!mJointList->setSelectedByValue(mSelectedJoint, true) && !mJointRows.empty())
        mJointList->setSelectedByValue(mJointRows.front()->getValue(), true);
    mJointList->setScrollPos(scroll);
    refreshRows();
}

void LLFloaterPoseStudio::refreshRows()
{
    const LLColor4 bone_color = LLUIColorTable::instance().getColor("PoseStudioBoneColor");
    const LLColor4 edited_color = LLUIColorTable::instance().getColor("PoseStudioEditedBoneColor");
    for (LLScrollListItem* row : mJointRows)
    {
        const LLVector3 degrees = LLPoseStudio::instance().getRotationOffset(row->getValue().asString());
        const bool edited = degrees != LLVector3::zero;
        for (S32 column = 0; column < 4; ++column)
        {
            row->getColumn(column)->setColor(edited ? edited_color : bone_color);
            if (column > 0) row->getColumn(column)->setValue(llformat("%.1f", degrees.mV[column - 1]));
        }
    }
}

void LLFloaterPoseStudio::refreshRotation()
{
    const std::string name = mJointList->getValue().asString();
    getChild<LLTextBox>("selected_bone")->setText(name.empty() ? getString("select_bone") : jointLabel(name));
    const LLVector3 degrees = LLPoseStudio::instance().getRotationOffset(name);
    for (S32 i = 0; i < 3; ++i) mRotation[i]->setValue(degrees.mV[i]);
}

void LLFloaterPoseStudio::refresh()
{
    LLPoseStudio& studio = LLPoseStudio::instance();
    const bool available = isAgentAvatarValid() && gAgentAvatarp->isBuilt()
        && !gAgentAvatarp->getIsAppearanceAnimating()
        && !gDisconnected && gAgent.getTeleportState() == LLAgent::TELEPORT_NONE;
    if (studio.isActive() && !available)
    {
        studio.end(gDisconnected ? LLPoseStudio::EndReason::DISCONNECTED : LLPoseStudio::EndReason::TARGET_LOST);
    }
    const bool active = studio.isActive();
    if (!available) mRowsBuilt = false;
    if (available && !mRowsBuilt)
    {
        buildJointRows();
        refreshRotation();
    }
    const bool can_edit = active && mJointList->hasSelectedItem();
    getChild<LLButton>("start")->setEnabled(available && !active);
    getChild<LLButton>("end")->setEnabled(active);
    getChild<LLButton>("reset_joint")->setEnabled(can_edit);
    getChild<LLButton>("reset_pose")->setEnabled(active);
    for (LLSliderCtrl* rotation : mRotation) rotation->setEnabled(can_edit);

    const char* status = "ready";
    if (!available) status = "unavailable";
    else if (mStartFailed) status = "capture_failed";
    else if (active) status = gSavedSettings.getBOOL("BoxxyFreezeAvatarAnimations") ? "posing_frozen" : "posing";
    else if (studio.getEndReason() == LLPoseStudio::EndReason::SKELETON_CHANGED) status = "skeleton_changed";
    else if (studio.getEndReason() == LLPoseStudio::EndReason::TELEPORT) status = "teleported";
    getChild<LLTextBox>("status")->setText(getString(status));
}
