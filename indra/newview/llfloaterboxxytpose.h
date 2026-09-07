/**
 * @file llfloaterboxxytpose.h
 * @brief Small Firestorm-compatible pose stand for Boxxy Viewer.
 */
#ifndef LL_FLOATERBOXXY_TPOSE_H
#define LL_FLOATERBOXXY_TPOSE_H

#include "llfloater.h"
#include "lluuid.h"

class LLComboBox;

class LLFloaterBoxxyTPose final : public LLFloater
{
    LOG_CLASS(LLFloaterBoxxyTPose);
public:
    explicit LLFloaterBoxxyTPose(const LLSD& key);
    bool postBuild() override;

private:
    void onOpen(const LLSD& key) override;
    void onClose(bool app_quitting) override;
    void onPoseSelected();
    void stopPose();

    LLComboBox* mPoseCombo = nullptr;
    LLUUID mActivePose;
    bool mAOPaused = false;
};

#endif
