/** Cached local comparison of inventory wearables, with delayed outfit updates. */
#ifndef LL_LLFLOATERTATTOOCOMPARE_H
#define LL_LLFLOATERTATTOOCOMPARE_H

#include "llfloater.h"
#include "llframetimer.h"
#include "llviewertexture.h"
#include "llwearabletype.h"
#include <map>
#include <vector>

class LLViewerWearable;
class LLTattooPreviewBuffer;

class LLFloaterTattooCompare : public LLFloater
{
public:
    LLFloaterTattooCompare(const LLSD& key);
    ~LLFloaterTattooCompare() override;
    bool postBuild() override;
    void onOpen(const LLSD& key) override;
    void onClose(bool app_quitting) override;
    bool handleKeyHere(KEY key, MASK mask) override;

    static bool canCompare(const LLUUID& id);
    static bool canCompareSelection(const uuid_vec_t& ids);
    static void show(const uuid_vec_t& ids);
    static LLViewerTexture* getPreviewTexture(U32 baked_index);

private:
    friend class LLTattooPreviewBuffer;
    struct Candidate
    {
        LLUUID id, asset;
        LLViewerWearable* wearable = nullptr;
        std::map<U32, LLPointer<LLViewerTexture>> previews;
    };
    struct Source
    {
        LLPointer<LLViewerFetchedTexture> texture;
        S32 boost;
        bool no_delete;
    };
    using Outfit = std::vector<std::pair<LLUUID, LLUUID>>;
    using COF = std::map<LLUUID, std::pair<LLUUID, std::string>>;
    Outfit outfit(bool compared_only = false) const;
    static COF cof();
    uuid_vec_t desiredItems(S32 index) const;
    bool available() const;
    static void idle(void* data);
    void update();
    bool unchanged() const;
    bool prepare();
    void select(S32 index);
    void step(S32 delta);
    void stop();
    void fail(const std::string& message);
    void status(const std::string& message);
    void commit(S32 index);
    void finishCommit();
    void releaseSources();

    static LLFloaterTattooCompare* sInstance;
    std::vector<Candidate> mCandidates;
    std::vector<LLViewerWearable*> mOriginalWearables;
    uuid_vec_t mOriginalItems, mDesiredItems, mAddedLinks;
    std::vector<Source> mSources;
    std::vector<U32> mRegions;
    Outfit mExpectedOutfit, mCommitOutfit, mOtherWearables;
    COF mExpectedCOF;
    LLWearableType::EType mType = LLWearableType::WT_INVALID;
    LLUUID mRegion;
    LLFrameTimer mTimer, mSelectionTimer;
    U32 mGeneration = 0;
    S32 mSelected = -1, mPreparing = 0, mCommitVersion = -1;
    S32 mPublished = -1, mPending = -1;
    bool mActive = false, mPrepared = false, mCommitting = false, mCancel = false, mClosing = false;
};

#endif
