/**
 * @file llfloaterareasearch.h
 * @brief Search loaded world objects without selecting them.
 */
#ifndef LL_LLFLOATERAREASEARCH_H
#define LL_LLFLOATERAREASEARCH_H

#include "llareasearchquery.h"
#include "llfloater.h"
#include "llframetimer.h"

#include <map>

class LLFilterEditor;
class LLScrollListCtrl;
class LLTextBox;
class LLViewerObject;

class LLFloaterAreaSearch final : public LLFloater
{
public:
    LLFloaterAreaSearch(const LLSD& key);
    bool postBuild() override;
    void onOpen(const LLSD& key) override;
    void onClose(bool app_quitting) override;
    void draw() override;
    bool handleRightMouseDown(S32 x, S32 y, MASK mask) override;

    static void processObjectProperties(const LLUUID& id, const LLUUID& owner_id, const std::string& name,
                                        const std::string& description, bool for_sale);
    static LLViewerObject* getHoveredObject();

private:
    struct Entry
    {
        LLUUID ownerID;
        std::string name;
        std::string description;
        std::u32string searchName;
        std::u32string searchDescription;
        F32 distance = 0.f;
        F64 requestedAt = 0.;
        U32 attempts = 0;
        bool ready = false;
        bool forSale = false;
    };

    void refresh();
    void scan();
    void requestProperties();
    void filterChanged();
    void chooseOwner();
    void setOwner(const LLUUID& id, const std::string& name = "");
    void rebuildList();
    bool inRange(LLViewerObject* object) const;

    LLScrollListCtrl* mObjects = nullptr;
    LLFilterEditor* mSearch = nullptr;
    LLTextBox* mStatus = nullptr;
    std::map<LLUUID, Entry> mEntries;
    LLAreaSearchQuery mQuery;
    LLUUID mRegionID;
    LLUUID mOwnerID;
    LLFrameTimer mScanTimer;
    LLFrameTimer mRequestTimer;
    F32 mRadius = 96.f;
    bool mRequestPending = false;
    bool mMouseOverList = false;
};

#endif
