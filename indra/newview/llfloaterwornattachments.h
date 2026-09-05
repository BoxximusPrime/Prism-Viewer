/**
 * @file llfloaterwornattachments.h
 * @brief Lists the attachment objects worn by another avatar.
 */

#ifndef LL_LLFLOATERWORNATTACHMENTS_H
#define LL_LLFLOATERWORNATTACHMENTS_H

#include "llfloater.h"
#include "lluuid.h"

#include <map>
#include <set>

class LLNameListCtrl;
class LLTextBox;
class LLViewerObject;

class LLFloaterWornAttachments final : public LLFloater
{
public:
    LLFloaterWornAttachments(const LLSD& key);

    bool postBuild() override;
    void onOpen(const LLSD& key) override;
    void onClose(bool app_quitting) override;

    static void processObjectProperties(const LLUUID& object_id,
                                        const LLUUID& creator_id,
                                        const std::string& name);

private:
    struct PendingAttachment
    {
        std::string mPointName;
        bool mTransientSelection = false;
    };

    void refresh();
    void addAttachment(const LLUUID& object_id,
                       const LLUUID& creator_id,
                       const std::string& name);
    void showCreatorProfile();

    LLUUID mAvatarID;
    LLNameListCtrl* mAttachmentList = nullptr;
    LLTextBox* mStatusText = nullptr;
    void requestProperties(LLViewerObject* object);
    void releaseTransientSelection(const LLUUID& object_id);
    void releaseTransientSelections();

    std::map<LLUUID, PendingAttachment> mPendingAttachments;
    std::set<LLUUID> mReceivedAttachments;
};

#endif
