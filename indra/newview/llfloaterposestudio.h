/**
 * @file llfloaterposestudio.h
 * Copyright (C) 2026 Prism Viewer contributors.
 * SPDX-License-Identifier: LGPL-2.1-only
 */
#ifndef LL_LLFLOATERPOSESTUDIO_H
#define LL_LLFLOATERPOSESTUDIO_H

#include "llfloater.h"
#include <vector>

class LLScrollListCtrl;
class LLScrollListItem;
class LLSliderCtrl;

class LLFloaterPoseStudio final : public LLFloater
{
public:
    explicit LLFloaterPoseStudio(const LLSD& key);
    ~LLFloaterPoseStudio() override;
    bool postBuild() override;
    void draw() override;

private:
    void onOpen(const LLSD& key) override;
    void onClose(bool app_quitting) override;
    void refresh();
    void buildJointRows();
    void refreshRows();
    void refreshRotation();
    void onStart();
    void onRotation();

    LLScrollListCtrl* mJointList = nullptr;
    std::vector<LLScrollListItem*> mJointRows;
    LLSliderCtrl* mRotation[3] = {};
    bool mStartFailed = false;
    bool mRowsBuilt = false;
    std::string mFilter;
    std::string mSelectedJoint = "mPelvis";
};

#endif
