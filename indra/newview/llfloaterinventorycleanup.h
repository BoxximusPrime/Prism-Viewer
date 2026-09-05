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
private:
    void scan();
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
    LLUUID mTrash;
    bool mConsumed = true;
};
#endif
