/**
 * @file llfloaterwornattachments.cpp
 * @brief Lists the attachment objects worn by another avatar.
 */

#include "llviewerprecompiledheaders.h"

#include "llfloaterwornattachments.h"

#include "llagent.h"
#include "llavataractions.h"
#include "llfiltereditor.h"
#include "llfloaterreg.h"
#include "llfocusmgr.h"
#include "llnamelistctrl.h"
#include "llselectmgr.h"
#include "lltextbox.h"
#include "llui.h"
#include "llviewerjointattachment.h"
#include "llviewerobject.h"
#include "llviewerobjectlist.h"
#include "llviewerregion.h"
#include "llvoavatar.h"
#include "message.h"

LLFloaterWornAttachments::LLFloaterWornAttachments(const LLSD& key)
: LLFloater(key)
{
}

bool LLFloaterWornAttachments::postBuild()
{
    mAttachmentList = getChild<LLNameListCtrl>("attachments");
    mFilterEditor = getChild<LLFilterEditor>("attachment_filter");
    mStatusText = getChild<LLTextBox>("status");
    mFilterEditor->setCommitCallback(
        [this](LLUICtrl*, const LLSD&) { filterAttachments(); });
    mAttachmentList->setMouseEnterCallback(
        [this](LLUICtrl*, const LLSD&) { mMouseOverList = true; });
    mAttachmentList->setMouseLeaveCallback(
        [this](LLUICtrl*, const LLSD&) { mMouseOverList = false; });
    mAttachmentList->setDoubleClickCallback(
        boost::bind(&LLFloaterWornAttachments::showCreatorProfile, this));
    return true;
}

void LLFloaterWornAttachments::onOpen(const LLSD& key)
{
    mAvatarID = key.asUUID();
    refresh();
}

void LLFloaterWornAttachments::onClose(bool app_quitting)
{
    mMouseOverList = false;
    releaseTransientSelections();
}

void LLFloaterWornAttachments::refresh()
{
    releaseTransientSelections();
    mAttachmentList->deleteAllItems();
    mPendingAttachments.clear();
    mReceivedAttachments.clear();

    LLViewerObject* object = gObjectList.findObject(mAvatarID);
    LLVOAvatar* avatar = object ? object->asAvatar() : nullptr;
    if (!avatar)
    {
        mStatusText->setText(getString("avatar_unavailable"));
        return;
    }

    for (const auto& [point_index, attachment_point] : avatar->mAttachmentPoints)
    {
        if (!attachment_point)
        {
            continue;
        }

        for (const auto& attachment_ptr : attachment_point->mAttachedObjects)
        {
            LLViewerObject* attachment = attachment_ptr.get();
            if (!attachment || attachment->isDead() || attachment->isHUDAttachment())
            {
                continue;
            }

            PendingAttachment pending;
            pending.mPointName = attachment_point->getName();
            pending.mTransientSelection = !attachment->isSelected();
            mPendingAttachments.emplace(attachment->getID(), pending);
            requestProperties(attachment);
        }
    }

    updateStatus();
}

void LLFloaterWornAttachments::processObjectProperties(const LLUUID& object_id,
                                                       const LLUUID& creator_id,
                                                       const std::string& name)
{
    LLFloaterWornAttachments* floater =
        LLFloaterReg::findTypedInstance<LLFloaterWornAttachments>("worn_attachments");
    if (!floater || !floater->getVisible())
    {
        return;
    }

    auto found = floater->mPendingAttachments.find(object_id);
    if (found == floater->mPendingAttachments.end()
        || !floater->mReceivedAttachments.insert(object_id).second)
    {
        return;
    }

    floater->releaseTransientSelection(object_id);
    found->second.mName = name;
    found->second.mCreatorID = creator_id;
    floater->addAttachment(object_id, creator_id, name);
    floater->updateStatus();
}

void LLFloaterWornAttachments::filterAttachments()
{
    mFilter = mFilterEditor->getText();
    LLStringUtil::trim(mFilter);
    LLStringUtil::toLower(mFilter);
    mAttachmentList->deleteAllItems();
    for (const LLUUID& object_id : mReceivedAttachments)
    {
        const auto& attachment = mPendingAttachments.at(object_id);
        addAttachment(object_id, attachment.mCreatorID, attachment.mName);
    }
    updateStatus();
}

void LLFloaterWornAttachments::updateStatus()
{
    LLViewerObject* avatar = gObjectList.findObject(mAvatarID);
    if (!avatar || avatar->isDead() || !avatar->asAvatar())
    {
        mStatusText->setText(getString("avatar_unavailable"));
    }
    else if (mPendingAttachments.empty())
    {
        mStatusText->setText(getString("no_attachments"));
    }
    else if (mReceivedAttachments.size() < mPendingAttachments.size())
    {
        mStatusText->setText(getString("loading"));
    }
    else
    {
        mStatusText->setText(mAttachmentList->getItemCount() == 0
            ? getString("no_matches") : LLStringUtil::null);
    }
}

LLViewerObject* LLFloaterWornAttachments::getHoveredAttachment()
{
    auto* floater = LLFloaterReg::findTypedInstance<LLFloaterWornAttachments>("worn_attachments");
    if (!floater || !floater->isShown() || !floater->mMouseOverList
        || !gFocusMgr.getAppHasFocus())
    {
        return nullptr;
    }

    // Hit-test the current rows so sorting, filtering and scrolling cannot leave
    // a highlight attached to an old row. The primary row ID is the creator.
    S32 x, y;
    LLUI::getInstance()->getMousePositionLocal(floater->mAttachmentList, &x, &y);
    LLScrollListItem* row = floater->mAttachmentList->hitItem(x, y);
    LLViewerObject* object = row ? gObjectList.findObject(row->getAltValue().asUUID()) : nullptr;
    LLVOAvatar* avatar = object ? object->getAvatar() : nullptr;
    return object && !object->isDead() && object->isAttachment() && !object->isHUDAttachment()
        && avatar && !avatar->isDead() && avatar->getID() == floater->mAvatarID
        ? object : nullptr;
}

void LLFloaterWornAttachments::addAttachment(const LLUUID& object_id,
                                             const LLUUID& creator_id,
                                             const std::string& name)
{
    const std::string& point_name = mPendingAttachments[object_id].mPointName;
    const std::string display_name = name.empty()
        ? getString("unnamed_attachment")
        : name;
    std::string searchable_name = display_name + "\n" + point_name;
    LLStringUtil::toLower(searchable_name);
    if (searchable_name.find(mFilter) == std::string::npos)
    {
        return;
    }

    LLNameListCtrl::NameItem row;
    row.value = creator_id;
    row.alt_value = object_id;
    row.target = LLNameListCtrl::INDIVIDUAL;
    row.columns.add().column("attachment_point").value(point_name);
    row.columns.add().column("attachment").value(display_name);
    row.columns.add().column("creator").value(LLStringUtil::null);
    mAttachmentList->addNameItemRow(row);
}

void LLFloaterWornAttachments::requestProperties(LLViewerObject* object)
{
    if (!object || !object->getRegion())
    {
        return;
    }

    // ObjectPropertiesFamily omits CreatorID. A transient simulator-side
    // selection requests the complete ObjectProperties record without changing
    // the viewer's visible selection.
    gMessageSystem->newMessageFast(_PREHASH_ObjectSelect);
    gMessageSystem->nextBlockFast(_PREHASH_AgentData);
    gMessageSystem->addUUIDFast(_PREHASH_AgentID, gAgent.getID());
    gMessageSystem->addUUIDFast(_PREHASH_SessionID, gAgent.getSessionID());
    gMessageSystem->nextBlockFast(_PREHASH_ObjectData);
    gMessageSystem->addU32Fast(_PREHASH_ObjectLocalID, object->getLocalID());
    gMessageSystem->sendReliable(object->getRegion()->getHost());
}

void LLFloaterWornAttachments::releaseTransientSelection(const LLUUID& object_id)
{
    auto found = mPendingAttachments.find(object_id);
    LLViewerObject* object = gObjectList.findObject(object_id);
    if (found == mPendingAttachments.end() || !found->second.mTransientSelection
        || !object || !object->getRegion())
    {
        return;
    }

    gMessageSystem->newMessageFast(_PREHASH_ObjectDeselect);
    gMessageSystem->nextBlockFast(_PREHASH_AgentData);
    gMessageSystem->addUUIDFast(_PREHASH_AgentID, gAgent.getID());
    gMessageSystem->addUUIDFast(_PREHASH_SessionID, gAgent.getSessionID());
    gMessageSystem->nextBlockFast(_PREHASH_ObjectData);
    gMessageSystem->addU32Fast(_PREHASH_ObjectLocalID, object->getLocalID());
    gMessageSystem->sendReliable(object->getRegion()->getHost());
}

void LLFloaterWornAttachments::releaseTransientSelections()
{
    for (const auto& [object_id, pending] : mPendingAttachments)
    {
        if (pending.mTransientSelection
            && mReceivedAttachments.find(object_id) == mReceivedAttachments.end())
        {
            releaseTransientSelection(object_id);
        }
    }
}

void LLFloaterWornAttachments::showCreatorProfile()
{
    const LLUUID creator_id = mAttachmentList->getCurrentID();
    if (creator_id.notNull())
    {
        LLAvatarActions::showProfile(creator_id);
    }
}
