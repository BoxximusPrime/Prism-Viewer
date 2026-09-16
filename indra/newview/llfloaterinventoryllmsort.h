/** Local-model inventory suggestions with explicit per-item approval. */
#ifndef LL_LLFLOATERINVENTORYLLMSORT_H
#define LL_LLFLOATERINVENTORYLLMSORT_H
#include "llfloater.h"
#include "llcorehttputil.h"
#include <vector>

class LLFloaterInventoryLLMSort : public LLFloater
{
public:
    LLFloaterInventoryLLMSort(const LLSD& key);
    ~LLFloaterInventoryLLMSort() override;
    bool postBuild() override;
    void onOpen(const LLSD& key) override;
    void onClose(bool app_quitting) override;
    void draw() override;
    void reshape(S32 width, S32 height, bool called_from_parent = true) override;
    static bool canSort(const LLUUID& id);
    static bool hasModel();
    static void show(const std::vector<LLUUID>& ids);
private:
    enum class State { Waiting, Ready, NewFolder, Unsure, Error, Creating, Moved, Skipped };
    struct Row
    {
        LLUUID id, parent, destination;
        std::string name, folderName, newName, icon, reason;
        bool folder = false;
        State state = State::Waiting;
    };
    struct Category { LLUUID id; std::string name; };
    void chooseRoot();
    void useRoot();
    void setRoot(const LLUUID& id);
    void loadCategories();
    void startSort();
    void cancelSort();
    void renderRows();
    void approve(size_t index);
    void moveItem(size_t index, const LLUUID& destination);
    bool unchanged(const Row& row) const;
    bool rootAllowed(const LLUUID& id) const;
    void status(const std::string& text);
    static bool folderAllowed(const LLUUID& id);
    static void sortCoro(LLHandle<LLFloater> handle, U32 generation, LLSD config);
    std::vector<Row> mRows;
    std::vector<Category> mCategories;
    std::vector<LLPanel*> mPanels;
    LLUUID mRoot, mLastRoot, mAgent;
    std::string mRootPath;
    U32 mGeneration = 0;
    bool mSorting = false, mLoading = false, mDirty = false, mAttention = false, mCreating = false;
    bool mAutoSort = false;
    F64 mLoadStarted = 0;
    LLCoreHttpUtil::HttpCoroutineAdapter::ptr_t mRequest;
};
#endif
