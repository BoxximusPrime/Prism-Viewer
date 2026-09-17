#ifndef LL_LLFLOATERQUICKPREFS_H
#define LL_LLFLOATERQUICKPREFS_H

#include "llfloater.h"
#include "llinventoryobserver.h"

class LLFloaterQuickPrefs : public LLFloater, public LLInventoryObserver
{
public:
    LLFloaterQuickPrefs(const LLSD& key) : LLFloater(key) {}
    ~LLFloaterQuickPrefs() override;
    bool postBuild() override;
    void onOpen(const LLSD& key) override;
    void draw() override;
    void changed(U32 mask) override { mInventoryDirty = true; }
private:
    void populateEnvironments();
    void applyEnvironment(const std::string& name);
    void cycleEnvironment(const std::string& name, S32 direction);
    bool mInventoryDirty = true;
    U32 mRequest = 0;
    std::map<std::string, U32> mPending;
};
#endif
