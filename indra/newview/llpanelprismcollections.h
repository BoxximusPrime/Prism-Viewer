#ifndef LL_LLPANELPRISMCOLLECTIONS_H
#define LL_LLPANELPRISMCOLLECTIONS_H

#include "llpanelappearancetab.h"
#include "llfloater.h"
#include "llinventoryobserver.h"
#include "lltimer.h"

class LLComboBox;
class LLScrollListCtrl;
class LLScrollContainer;

class LLPanelPrismCollections final : public LLPanelAppearanceTab, public LLInventoryObserver
{
public:
    LLPanelPrismCollections() = default;
    ~LLPanelPrismCollections() override;
    bool postBuild() override;
    void onOpen(const LLSD&) override;
    void draw() override;
    bool handleToolTip(S32 x, S32 y, MASK mask) override;
    bool handleDoubleClick(S32 x, S32 y, MASK mask) override;
    void changed(U32) override { mDirty = true; }
    void onFilterSubStringChanged(const std::string&, const std::string&) override { mDirty = true; }
    bool isActionEnabled(const LLSD&) override { return false; }
    void updateMenuItemsVisibility() override {}
    LLToggleableMenu* getGearMenu() override { return nullptr; }
    LLToggleableMenu* getSortMenu() override { return nullptr; }
    bool getTrashMenuVisible() override { return false; }
private:
    void refresh();
    void updateButtons();
    void nameCategory(bool rename);
    void deleteFolder(bool category);
    void editSet(bool create);
    void refreshGallery();
    void layoutGallery();
    void editPhoto();
    LLUUID setAt(S32 x, S32 y) const;
    LLComboBox* mCategories = nullptr;
    LLScrollListCtrl* mSets = nullptr;
    LLScrollContainer* mGallery = nullptr;
    LLPanel* mGalleryContent = nullptr;
    std::vector<std::pair<LLUUID, LLPanel*>> mCards;
    S32 mGalleryWidth = 0;
    S32 mGalleryHeight = 0;
    bool mGalleryMode = false;
    LLUUID mRoot;
    LLTimer mRefresh;
    bool mDirty = true;
};

class LLFloaterPrismCollection final : public LLFloater
{
    friend class LLFloaterReg;
    explicit LLFloaterPrismCollection(const LLSD& key) : LLFloater(key) {}
public:
    bool postBuild() override;
    void onOpen(const LLSD& key) override;
    bool canClose() override { return !mSaving; }
    bool handleDragAndDrop(S32 x, S32 y, MASK mask, bool drop, EDragAndDropType type,
                           void* data, EAcceptance* accept, std::string& tooltip) override;
private:
    void showItemMenu(S32 x, S32 y);
    void addItem(const LLUUID& id, bool checked);
    void addWorn();
    bool canMoveLayer(S32 direction) const;
    void updateLayerButtons();
    void moveItem(S32 direction);
    void save();
    void saveLinks(const LLUUID& folder, const std::string& name, const uuid_vec_t& items);
    LLScrollListCtrl* mItems = nullptr;
    LLUUID mCategory, mSet;
    bool mSaving = false;
};
#endif
