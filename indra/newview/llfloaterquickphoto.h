/** Avatar-only outfit and collection photography. */
#ifndef LL_LLFLOATERQUICKPHOTO_H
#define LL_LLFLOATERQUICKPHOTO_H

#include "llfloater.h"
#include "lltimer.h"

class LLQuickPhotoPreview;
class LLScrollListCtrl;

class LLFloaterQuickPhoto final : public LLFloater
{
public:
    explicit LLFloaterQuickPhoto(const LLSD& key);
    ~LLFloaterQuickPhoto() override;
    bool postBuild() override;
    void onOpen(const LLSD& key) override;
    void onClose(bool app_quitting) override;
    bool canClose() override { return !mUploading; }
    void draw() override;
private:
    void updateMannequinControls();
    void refreshAttachments();
    void refreshPreview();
    void isolateAttachments();
    void wearFolder();
    void upload();
    void uploadThumbnail();
    void stopPose();
    bool folderReady(std::string& reason);
    void status(const std::string& message);

    LLUUID mFolder;
    LLUUID mUploadedAsset;
    uuid_set_t mMembers;
    LLPointer<LLQuickPhotoPreview> mPreview;
    LLScrollListCtrl* mAttachments = nullptr;
    LLTimer mRefreshTimer;
    std::string mReadiness;
    bool mCanCapture = false;
    bool mUploading = false;
    bool mOwnPose = false;
};
#endif
