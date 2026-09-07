/**
 * @file llfloaterboxxyradar.h
 * @brief Lightweight nearby-avatar radar for Boxxy Viewer.
 *
 * $LicenseInfo:firstyear=2026&license=viewerlgpl$
 * Copyright (C) 2026 Boxxy Viewer contributors
 * $/LicenseInfo$
 */

#ifndef LL_LLFLOATERBOXXYRADAR_H
#define LL_LLFLOATERBOXXYRADAR_H

#include "llfloater.h"
#include "llframetimer.h"

#include <map>
#include <string>
#include <vector>

class LLAvatarName;
class LLBoxxyRadarRow;
class LLFilterEditor;
class LLFlatListView;
class LLLineEditor;
class LLLayoutPanel;
class LLScrollListCtrl;
class LLTextBox;

class LLFloaterBoxxyRadar final : public LLFloater
{
    friend class LLFloaterReg;

private:
    explicit LLFloaterBoxxyRadar(const LLSD& key);
    ~LLFloaterBoxxyRadar() override = default;

public:
    bool postBuild() override;
    void onOpen(const LLSD& key) override;
    void onClose(bool app_quitting) override;
    void draw() override;

private:
    enum ECategory
    {
        CATEGORY_VIP,
        CATEGORY_FRIENDS,
        CATEGORY_BLOCKED,
        CATEGORY_NEAR,
        CATEGORY_FAR,
        CATEGORY_COUNT
    };

    struct AvatarEntry
    {
        LLUUID      id;
        std::string formatted_name;
        F64         distance_yards = 0.0;
        ECategory   category       = CATEGORY_FAR;
        bool        typing         = false;
        bool        speaking       = false;
    };

    void refreshRadar();
    void rebuildRadar(const std::vector<AvatarEntry>& entries, const std::vector<std::string>& structure);
    void addSection(ECategory category, S32 count);
    void onSearchChanged(const std::string& query);

    void                     refreshVipList();
    void                     updateVipButtons();
    void                     onAddVip();
    void                     onRemoveVip();
    void                     toggleVipEditor();
    void                     setVipEditorExpanded(bool expanded);
    std::vector<std::string> loadVipTerms() const;
    void                     saveVipTerms(const std::vector<std::string>& terms);

    bool isVip(const LLAvatarName& name, const std::vector<std::string>& terms) const;

    LLFlatListView*                    mRadarList = nullptr;
    LLFilterEditor*                    mSearchInput = nullptr;
    LLTextBox*                         mResultSummary = nullptr;
    LLLineEditor*                      mVipInput  = nullptr;
    LLScrollListCtrl*                  mVipList   = nullptr;
    LLLayoutPanel*                     mVipEditor = nullptr;
    bool                               mVipEditorExpanded = true;
    std::map<LLUUID, LLBoxxyRadarRow*> mRows;
    std::vector<std::string>           mStructure;
    LLFrameTimer                       mRefreshTimer;
    std::string                        mSearchQuery;
    bool                               mForceRebuild = true;
};

class LLFloaterBoxxyRadarSimple final : public LLFloater
{
    friend class LLFloaterReg;

private:
    explicit LLFloaterBoxxyRadarSimple(const LLSD& key);

public:
    bool applyRectControl() override;
    bool postBuild() override;
    void onOpen(const LLSD& key) override;
    bool canClose() override { return false; }
    bool handleMouseDown(S32 x, S32 y, MASK mask) override;
    void handleReshape(const LLRect& new_rect, bool by_user = false) override;
    void draw() override;

private:
    void refreshRadar();

    LLTextBox*   mNearNames = nullptr;
    LLTextBox*   mFarNames  = nullptr;
    LLTextBox*   mNearTotal = nullptr;
    LLTextBox*   mFarTotal  = nullptr;
    LLFrameTimer mRefreshTimer;
};

#endif // LL_LLFLOATERBOXXYRADAR_H
