/**
 * @file llfloaterwornattachments.cpp
 * @brief Lists the attachment objects worn by another avatar.
 */

#include "llviewerprecompiledheaders.h"

#include "llfloaterwornattachments.h"

#include "llagent.h"
#include "llavataractions.h"
#include "llfloaterreg.h"
#include "llnamelistctrl.h"
#include "llselectmgr.h"
#include "lltextbox.h"
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
    mStatusText = getChild<LLTextBox>("status");
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

    mStatusText->setText(mPendingAttachments.empty()
        ? getString("no_attachments")
        : getString("loading"));
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
    floater->addAttachment(object_id, creator_id, name);
    if (floater->mReceivedAttachments.size() == floater->mPendingAttachments.size())
    {
        floater->mStatusText->setText(LLStringUtil::null);
    }
}

void LLFloaterWornAttachments::addAttachment(const LLUUID& object_id,
                                             const LLUUID& creator_id,
                                             const std::string& name)
{
    const std::string& point_name = mPendingAttachments[object_id].mPointName;
    const std::string display_name = name.empty()
        ? getString("unnamed_attachment")
        : name;

    LLNameListCtrl::NameItem row;
    row.value = creator_id;
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
