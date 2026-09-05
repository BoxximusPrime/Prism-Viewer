/** Inventory cleanup candidates and explicit, immutable review. */
#ifndef LL_LLFLOATERINVENTORYCLEANUP_H
#define LL_LLFLOATERINVENTORYCLEANUP_H
#include "llfloater.h"
#include "llinventorycleanupplan.h"
class LLScrollListCtrl;
class LLFloaterInventoryCleanup : public LLFloater
{
public:
    LLFloaterInventoryCleanup(const LLSD& key);
    bool postBuild() override;
    void onOpen(const LLSD& key) override;
    void draw() override;
    void reshape(S32 width, S32 height, bool called_from_parent = true) override;
private:
    void scan();
    void showHome();
    void chooseTool(const std::string& tool);
    std::string mTool = "demos";
    void refreshLoading();
    void retryLoading();
    F64 mNextLoadingUpdate = 0;
    F64 mLastLoadingChange = 0;
    std::string mLoadingSignature;
    bool mShowLoadingDetails = false;
    void showPage();
    void review();
    void protectFolders();
    void refreshProtected();
    void unprotectFolders();
    void details();
    LLScrollListCtrl* mItems = nullptr;
    LLSD mRows;
    std::map<std::string, LLInventoryCleanupPlan::Entry> mScan;
    S32 mPage = 0;
};
class LLFloaterInventoryCleanupReview : public LLFloater
{
public:
    LLFloaterInventoryCleanupReview(const LLSD& key);
    bool postBuild() override;
    void onOpen(const LLSD& key) override;
private:
    void execute();
    std::vector<LLInventoryCleanupPlan::Entry> mPlan;
    std::map<std::string, std::string> mDetails;
    LLUUID mTrash;
    bool mConsumed = true;
};
#endif
