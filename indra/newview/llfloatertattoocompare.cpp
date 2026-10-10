#include "llviewerprecompiledheaders.h"
#include "llfloatertattoocompare.h"

#include "llagent.h"
#include "llagentwearables.h"
#include "llappearancemgr.h"
#include "llcallbacklist.h"
#include "llfloaterreg.h"
#include "llglheaders.h"
#include "llinventoryfunctions.h"
#include "llinventorymodel.h"
#include "lllocaltextureobject.h"
#include "llnotificationsutil.h"
#include "llscrolllistctrl.h"
#include "lltextbox.h"
#include "llviewerregion.h"
#include "llviewertexlayer.h"
#include "llviewerwearable.h"
#include "llvoavatarself.h"
#include "llwearablelist.h"

#include <algorithm>
#include <memory>
#include <set>

using namespace LLAvatarAppearanceDefines;

// Render through the normal bake framebuffer, but never update a live composite.
class LLTattooPreviewBuffer final : public LLViewerTexLayerSetBuffer
{
public:
    LLTattooPreviewBuffer(LLViewerTexLayerSet* layers, LLFloaterTattooCompare* owner,
                         std::vector<LLWearable*> wearables) :
        LLViewerTexLayerSetBuffer(layers, layers->getInfo()->getWidth(), layers->getInfo()->getHeight()),
        mOwner(owner->getHandle()), mGeneration(owner->mGeneration), mType(owner->mType),
        mWearables(std::move(wearables)) {}

    bool needsRender() override
    {
        if (mAttempted) return false;
        auto* owner = dynamic_cast<LLFloaterTattooCompare*>(mOwner.get());
        return owner && owner->mGeneration == mGeneration && owner->mActive &&
            owner->unchanged() && !gAgentAvatarp->getIsAppearanceAnimating();
    }
    bool ready() const { return mReady && hasGLTexture() && isInitialized(); }
    bool failed() const { return mAttempted && !mReady; }

protected:
    bool render() override
    {
        // This swap cannot span a frame or an asynchronous callback.
        auto& wearables = gAgentWearables.mWearableDatas[mType];
        std::vector<std::pair<LLVisualParam*, F32>> params;
        for (auto* param = gAgentAvatarp->getFirstVisualParam(); param; param = gAgentAvatarp->getNextVisualParam())
            params.emplace_back(param, param->getWeight());
        std::vector<std::pair<U8, LLPointer<LLViewerTexture>>> textures;
        for (const auto& entry : LLAvatarAppearance::getDictionary()->getTextures())
            if (entry.second->mIsLocalTexture)
                textures.emplace_back(entry.first, gAgentAvatarp->getTEImage(entry.first));

        wearables.swap(mWearables);
        // Skin and eye tint parameters are used before their texture layers render.
        if (mType != LLWearableType::WT_TATTOO && !wearables.empty())
            wearables.front()->writeToAvatar(gAgentAvatarp);
        const bool success = LLViewerTexLayerSetBuffer::render();
        wearables.swap(mWearables);
        for (const auto& param : params) param.first->setWeight(param.second);
        for (const auto& texture : textures) gAgentAvatarp->setLocalTextureTE(texture.first, texture.second, 0);
        return success;
    }
    void midRenderTexLayerSet(bool success) override {}
    void postRender(bool success) override
    {
        LLViewerTexLayerSetBuffer::postRender(success);
        mAttempted = true;
        mReady = success && hasGLTexture();
        mGLTexturep->setGLTextureCreated(mReady);
    }

private:
    LLHandle<LLFloater> mOwner;
    U32 mGeneration;
    LLWearableType::EType mType;
    std::vector<LLWearable*> mWearables;
    bool mAttempted = false, mReady = false;
};

LLFloaterTattooCompare* LLFloaterTattooCompare::sInstance = nullptr;

LLFloaterTattooCompare::LLFloaterTattooCompare(const LLSD& key) : LLFloater(key)
{
    sInstance = this;
    gIdleCallbacks.addFunction(idle, this);
}

LLFloaterTattooCompare::~LLFloaterTattooCompare()
{
    gIdleCallbacks.deleteFunction(idle, this);
    stop();
    sInstance = nullptr;
}

bool LLFloaterTattooCompare::postBuild()
{
    childSetAction("previous", [this](LLUICtrl*, const LLSD&) { step(-1); });
    childSetAction("next", [this](LLUICtrl*, const LLSD&) { step(1); });
    childSetAction("keep", [this](LLUICtrl*, const LLSD&) { closeFloater(); });
    childSetAction("cancel", [this](LLUICtrl*, const LLSD&) { mCancel = true; closeFloater(); });
    getChild<LLScrollListCtrl>("items")->setCommitCallback([this](LLUICtrl*, const LLSD&)
    {
        select(getChild<LLScrollListCtrl>("items")->getFirstSelectedIndex());
    });
    return true;
}

bool LLFloaterTattooCompare::canCompare(const LLUUID& id)
{
    const auto* item = gInventory.getItem(gInventory.getLinkedItemID(id));
    return item && ((item->getWearableType() == LLWearableType::WT_TATTOO && item->getType() == LLAssetType::AT_CLOTHING) ||
        ((item->getWearableType() == LLWearableType::WT_EYES || item->getWearableType() == LLWearableType::WT_SKIN) &&
            item->getType() == LLAssetType::AT_BODYPART)) && item->isFinished() &&
        gInventory.isObjectDescendentOf(item->getUUID(), gInventory.getRootFolderID()) &&
        !gInventory.isObjectDescendentOf(item->getUUID(), gInventory.findCategoryUUIDForType(LLFolderType::FT_TRASH)) &&
        depth_nesting_in_marketplace(item->getUUID()) < 0;
}

bool LLFloaterTattooCompare::canCompareSelection(const uuid_vec_t& ids)
{
    if (ids.size() < 2 || ids.size() > 16) return false;
    LLWearableType::EType type = LLWearableType::WT_INVALID;
    std::set<LLUUID> seen;
    for (const auto& id : ids)
    {
        if (!canCompare(id)) return false;
        const auto* item = gInventory.getItem(gInventory.getLinkedItemID(id));
        if (type != LLWearableType::WT_INVALID && type != item->getWearableType()) return false;
        type = item->getWearableType();
        seen.insert(item->getUUID());
    }
    return seen.size() >= 2;
}

void LLFloaterTattooCompare::show(const uuid_vec_t& ids)
{
    LLSD key = LLSD::emptyArray();
    for (const auto& id : ids) key.append(id);
    if (auto* floater = LLFloaterReg::getTypedInstance<LLFloaterTattooCompare>("tattoo_compare"))
        floater->openFloater(key);
}

LLFloaterTattooCompare::Outfit LLFloaterTattooCompare::outfit(bool compared_only) const
{
    Outfit result;
    for (S32 type = 0; type < LLWearableType::WT_COUNT; ++type)
    {
        if ((type == mType) != compared_only) continue;
        const auto wearable_type = static_cast<LLWearableType::EType>(type);
        for (U32 i = 0; i < gAgentWearables.getWearableCount(wearable_type); ++i)
        {
            const auto* wearable = gAgentWearables.getViewerWearable(wearable_type, i);
            result.emplace_back(wearable->getItemID(), wearable->getAssetID());
        }
    }
    return result;
}

LLFloaterTattooCompare::COF LLFloaterTattooCompare::cof()
{
    COF result;
    LLInventoryModel::cat_array_t cats;
    LLInventoryModel::item_array_t items;
    gInventory.collectDescendents(LLAppearanceMgr::instance().getCOF(), cats, items, false);
    for (const auto& item : items)
        result[item->getUUID()] = {item->getLinkedUUID(), item->getActualDescription()};
    return result;
}

void LLFloaterTattooCompare::onOpen(const LLSD& key)
{
    if (mClosing)
    {
        status(getString("applying"));
        return;
    }
    if (mActive) return;
    stop();
    mCancel = false;
    getChildView("cancel")->setEnabled(true);
    auto* list = getChild<LLScrollListCtrl>("items");
    list->deleteAllItems();
    if (gDisconnected || !isAgentAvatarValid() || !gAgent.getRegion() || !gAgentWearables.areWearablesLoaded() ||
        gAgentAvatarp->isEditingAppearance() || gAgentWearables.isCOFChangeInProgress() ||
        LLAppearanceMgr::instance().isOutfitLocked())
    {
        fail(getString("busy"));
        return;
    }
    std::set<LLUUID> seen;
    for (auto it = key.beginArray(); it != key.endArray(); ++it)
    {
        const LLUUID id = gInventory.getLinkedItemID(it->asUUID());
        if (!canCompare(id)) { fail(getString("invalid")); return; }
        if (!seen.insert(id).second) continue;
        const auto* item = gInventory.getItem(id);
        if (mType != LLWearableType::WT_INVALID && mType != item->getWearableType())
        { fail(getString("mixed")); return; }
        mType = item->getWearableType();
        Candidate candidate;
        candidate.id = id;
        candidate.asset = item->getAssetUUID();
        mCandidates.push_back(candidate);
        LLSD row;
        row["value"] = id;
        row["columns"][0]["column"] = "name";
        row["columns"][0]["value"] = item->getName();
        list->addElement(row);
    }
    if (mCandidates.size() < 2 || mCandidates.size() > 16)
    {
        fail(getString("count"));
        return;
    }
    for (U32 i = 0; i < gAgentWearables.getWearableCount(mType); ++i)
    {
        auto* wearable = gAgentWearables.getViewerWearable(mType, i);
        mOriginalWearables.push_back(wearable);
        mOriginalItems.push_back(wearable->getItemID());
    }
    U32 replaced = 0;
    for (const auto& id : mOriginalItems) replaced += seen.count(id) != 0;
    if (mType == LLWearableType::WT_TATTOO &&
        gAgentWearables.getClothingLayerCount() - replaced + 1 > LLWearableData::MAX_CLOTHING_LAYERS)
    {
        fail(getString("layer_limit"));
        return;
    }
    mExpectedOutfit = outfit(true);
    mOtherWearables = outfit();
    mExpectedCOF = cof();
    mRegion = gAgent.getRegion()->getRegionID();
    mActive = true;
    mTimer.reset();
    status(getString("loading"));
    const auto handle = getHandle();
    const U32 generation = mGeneration;
    for (size_t i = 0; i < mCandidates.size(); ++i)
    {
        struct Request { LLHandle<LLFloater> handle; U32 generation; size_t index; };
        auto* request = new Request{handle, generation, i};
        const auto* item = gInventory.getItem(mCandidates[i].id);
        LLWearableList::instance().getAsset(item->getAssetUUID(), item->getName(), gAgentAvatarp,
            item->getType(), [](LLViewerWearable* wearable, void* data)
            {
                std::unique_ptr<Request> request(static_cast<Request*>(data));
                auto* self = dynamic_cast<LLFloaterTattooCompare*>(request->handle.get());
                if (!self || self->mGeneration != request->generation || !self->mActive) return;
                if (!wearable || wearable->getType() != self->mType ||
                    wearable->getAssetID() != self->mCandidates[request->index].asset)
                    self->fail(self->getString("asset_failed"));
                else self->mCandidates[request->index].wearable = wearable;
            }, request);
        if (!mActive) break;
    }
}

bool LLFloaterTattooCompare::available() const
{
    return !gDisconnected && !LLApp::isExiting() && isAgentAvatarValid() && gAgent.getRegion() && gAgent.getRegion()->getRegionID() == mRegion &&
        !gAgentAvatarp->isEditingAppearance() && !LLAppearanceMgr::instance().isOutfitLocked() &&
        outfit() == mOtherWearables;
}

bool LLFloaterTattooCompare::unchanged() const
{
    return available() && !gAgentWearables.isCOFChangeInProgress() &&
        outfit(true) == mExpectedOutfit && cof() == mExpectedCOF;
}

uuid_vec_t LLFloaterTattooCompare::desiredItems(S32 index) const
{
    if (index < 0) return mOriginalItems;
    const LLUUID chosen = mCandidates[index].id;
    if (mType != LLWearableType::WT_TATTOO) return {chosen};
    uuid_vec_t desired;
    bool inserted = false;
    for (const auto& id : mOriginalItems)
    {
        const bool selected = std::any_of(mCandidates.begin(), mCandidates.end(),
            [&](const Candidate& candidate) { return candidate.id == id; });
        if (!selected) desired.push_back(id);
        else if (!inserted) { desired.push_back(chosen); inserted = true; }
    }
    if (!inserted) desired.push_back(chosen);
    return desired;
}

bool LLFloaterTattooCompare::prepare()
{
    for (const auto& candidate : mCandidates) if (!candidate.wearable) return false;
    if (mRegions.empty())
    {
        for (U32 region : {BAKED_HEAD, BAKED_UPPER, BAKED_LOWER, BAKED_EYES})
        {
            if ((mType == LLWearableType::WT_EYES) != (region == BAKED_EYES)) continue;
            const auto* baked = LLAvatarAppearance::getDictionary()->getBakedTexture(static_cast<EBakedTextureIndex>(region));
            bool used = mType != LLWearableType::WT_TATTOO;
            for (const auto& candidate : mCandidates)
                for (auto te : baked->mLocalTextures)
                    if (const auto* texture = candidate.wearable->getLocalTextureObject(te))
                        used |= texture->getID().notNull() && texture->getID() != IMG_DEFAULT_AVATAR;
            if (used) mRegions.push_back(region);
        }
        for (U32 region : mRegions)
        {
            auto* layers = gAgentAvatarp->getLayerSet(static_cast<EBakedTextureIndex>(region));
            if (!layers) { fail(getString("render_failed")); return false; }
        }
        if (mRegions.empty()) { fail(getString("empty")); return false; }
        std::set<LLUUID> sources;
        auto collect = [&](LLViewerWearable* wearable)
        {
            for (U32 region : mRegions)
                for (auto te : LLAvatarAppearance::getDictionary()->getBakedTexture(static_cast<EBakedTextureIndex>(region))->mLocalTextures)
                    if (auto* local = wearable->getLocalTextureObject(te))
                    {
                        const LLUUID id = local->getID();
                        if (id.isNull() || id == IMG_DEFAULT_AVATAR || !sources.insert(id).second) continue;
                        auto* image = dynamic_cast<LLViewerFetchedTexture*>(local->getImage());
                        if (image) mSources.push_back({image, image->getBoostLevel(), image->getTextureState() == LLGLTexture::NO_DELETE});
                    }
        };
        for (S32 type = 0; type < LLWearableType::WT_COUNT; ++type)
            for (U32 i = 0; i < gAgentWearables.getWearableCount(static_cast<LLWearableType::EType>(type)); ++i)
                collect(gAgentWearables.getViewerWearable(static_cast<LLWearableType::EType>(type), i));
        for (const auto& candidate : mCandidates) collect(candidate.wearable);
    }
    U64 bytes_per_preview = 0;
    for (U32 region : mRegions)
    {
        const auto* info = gAgentAvatarp->getLayerSet(static_cast<EBakedTextureIndex>(region))->getInfo();
        bytes_per_preview += U64(info->getWidth()) * info->getHeight() * 4;
    }
    U64 required_bytes = 0;
    for (const auto& candidate : mCandidates)
        if (candidate.previews.empty()) required_bytes += bytes_per_preview;

    bool loaded = true;
    for (const auto& source : mSources)
    {
        if (source.texture->isMissingAsset()) { fail(getString("texture_failed")); return false; }
        const bool resident = source.texture->hasGLTexture() && source.texture->getDiscardLevel() >= 0;
        const U64 full_bytes = U64(llmax(0, source.texture->getFullWidth())) * llmax(0, source.texture->getFullHeight()) * 4;
        const U64 resident_bytes = resident ? U64(source.texture->getWidth()) * source.texture->getHeight() * 4 : 0;
        required_bytes += full_bytes > resident_bytes ? full_bytes - resident_bytes : 0;
        loaded &= resident && source.texture->getDiscardLevel() == 0;
    }

    // The viewer's free-VRAM estimate already reserves scene headroom and charges allocations at twice their size.
    constexpr U64 mib = 1024 * 1024;
    F64 available_bytes = llmax(0.0, F64(LLViewerTexture::sFreeVRAMMegabytes)) * mib / 2.0;
    // Check during loading too; leave a quarter of the driver's free memory for other GPU users.
    GLint free_kib[4] = {-1, -1, -1, -1};
    if (gGLManager.mHasNVXGpuMemoryInfo)
        glGetIntegerv(GL_GPU_MEMORY_INFO_CURRENT_AVAILABLE_VIDMEM_NVX, free_kib);
    else if (gGLManager.mHasATIMemInfo)
        glGetIntegerv(GL_TEXTURE_FREE_MEMORY_ATI, free_kib);
    if (free_kib[0] >= 0)
        available_bytes = llmin(available_bytes, F64(free_kib[0]) * 1024.0 * 0.75);
    if (required_bytes > available_bytes || LLViewerTexture::sFreeVRAMMegabytes <= 0.f)
    {
        LLStringUtil::format_map_t args;
        args["[REQUIRED]"] = std::to_string((required_bytes + mib - 1) / mib);
        args["[AVAILABLE]"] = std::to_string(U64(available_bytes / mib));
        fail(getString("cache_limit", args));
        return false;
    }
    for (auto& source : mSources)
    {
        source.texture->setBoostLevel(llmax(source.boost, S32(LLGLTexture::BOOST_PREVIEW)));
        source.texture->addTextureStats(2048.f * 2048.f);
    }
    if (!loaded) return false;

    if (mPreparing < S32(mCandidates.size()))
    {
        auto& candidate = mCandidates[mPreparing];
        if (candidate.previews.empty())
        {
            std::vector<LLWearable*> wearables;
            for (const auto& id : desiredItems(mPreparing))
            {
                if (id == candidate.id) wearables.push_back(candidate.wearable);
                else
                    for (size_t i = 0; i < mOriginalItems.size(); ++i)
                        if (mOriginalItems[i] == id) wearables.push_back(mOriginalWearables[i]);
            }
            for (U32 region : mRegions)
                candidate.previews[region] = new LLTattooPreviewBuffer(
                    gAgentAvatarp->getLayerSet(static_cast<EBakedTextureIndex>(region)), this, wearables);
            status(getString("preparing") + " " + std::to_string(mPreparing + 1) + " / " + std::to_string(mCandidates.size()));
            return false;
        }
        for (const auto& entry : candidate.previews)
        {
            const auto* buffer = static_cast<LLTattooPreviewBuffer*>(entry.second.get());
            if (buffer->failed()) { fail(getString("render_failed")); return false; }
            if (!buffer->ready()) return false;
        }
        ++mPreparing;
    }
    return mPreparing == S32(mCandidates.size());
}

void LLFloaterTattooCompare::idle(void* data)
{
    static_cast<LLFloaterTattooCompare*>(data)->update();
}

void LLFloaterTattooCompare::update()
{
    if (!mActive) return;
    if (LLApp::isExiting() || gDisconnected) { stop(); return; }
    if (!available()) { fail(getString("changed")); return; }
    for (const auto& candidate : mCandidates)
        if (!canCompare(candidate.id) || gInventory.getItem(candidate.id)->getAssetUUID() != candidate.asset)
        { fail(getString("changed")); return; }
    if (mCommitting)
    {
        if (mTimer.getElapsedTimeF32() > 90.f) { fail(getString("apply_interrupted")); return; }
        if (mCommitVersion < 0) return;
        if (cof() != mExpectedCOF) { fail(getString("changed")); return; }
        if (gAgentWearables.isCOFChangeInProgress() || outfit(true) != mCommitOutfit) return;
        mExpectedOutfit = mCommitOutfit;
        mPublished = mPending;
        mCommitting = false;
        if (!mClosing) status(getString("ready"));
    }
    if (!unchanged()) { fail(getString("changed")); return; }
    if (mPrepared)
    {
        for (const auto& candidate : mCandidates)
            for (const auto& entry : candidate.previews)
                if (!static_cast<LLTattooPreviewBuffer*>(entry.second.get())->ready())
                { fail(getString("render_failed")); return; }
        const S32 desired = mClosing && mCancel ? -1 : mSelected;
        if (desired != mPublished && (mClosing || mSelectionTimer.getElapsedTimeF32() >= 2.f))
        {
            commit(desired);
            return;
        }
        if (!mClosing) return;
        // Retain the local preview until the final server bake is usable.
        if (mCommitVersion < 0) { stop(); return; }
        if (mTimer.getElapsedTimeF32() > 90.f) { fail(getString("apply_interrupted")); return; }
        if (gAgentAvatarp->mLastUpdateReceivedCOFVersion < mCommitVersion) return;
        bool ready = true;
        for (U32 region : mRegions)
        {
            const auto te = LLAvatarAppearance::getDictionary()->getBakedTexture(static_cast<EBakedTextureIndex>(region))->mTextureIndex;
            const auto* texture = gAgentAvatarp->getTEImage(te);
            ready &= texture && texture->getID() != IMG_DEFAULT_AVATAR && !texture->isMissingAsset() &&
                texture->hasGLTexture() && texture->getDiscardLevel() >= 0 && texture->getDiscardLevel() <= 1;
        }
        if (ready) { stop(); status(getString("applied")); }
        return;
    }
    if (mTimer.getElapsedTimeF32() > 120.f) { fail(getString("timeout")); return; }
    if (prepare())
    {
        mPrepared = true;
        releaseSources();
        for (const auto* name : {"items", "previous", "next", "keep"}) getChildView(name)->setEnabled(true);
        status(getString("ready"));
        select(0);
    }
}

void LLFloaterTattooCompare::select(S32 index)
{
    if (!mActive || !mPrepared || mClosing || index < 0 || index >= S32(mCandidates.size()) || index == mSelected) return;
    if (!available() || (!mCommitting && !unchanged())) { fail(getString("changed")); return; }
    mSelected = index;
    mSelectionTimer.reset();
    getChild<LLScrollListCtrl>("items")->selectNthItem(index);
    gAgentAvatarp->updateMeshTextures();
    LLStringUtil::format_map_t args;
    args["[CURRENT]"] = std::to_string(index + 1);
    args["[TOTAL]"] = std::to_string(mCandidates.size());
    getChild<LLTextBox>("position")->setText(getString("position_label", args));
}

void LLFloaterTattooCompare::step(S32 delta)
{
    if (mPrepared && !mCandidates.empty())
        select((mSelected + delta + S32(mCandidates.size())) % S32(mCandidates.size()));
}

bool LLFloaterTattooCompare::handleKeyHere(KEY key, MASK mask)
{
    if (mask == MASK_NONE && (key == KEY_LEFT || key == KEY_RIGHT))
    { step(key == KEY_LEFT ? -1 : 1); return true; }
    if (mask == MASK_NONE && key == KEY_ESCAPE)
    { if (!mClosing) mCancel = true; closeFloater(); return true; }
    return LLFloater::handleKeyHere(key, mask);
}

LLViewerTexture* LLFloaterTattooCompare::getPreviewTexture(U32 baked_index)
{
    const auto* self = sInstance;
    if (!self || self->mSelected < 0 || !self->mActive ||
        !isAgentAvatarValid() || gAgentAvatarp->isEditingAppearance()) return nullptr;
    const auto& textures = self->mCandidates[self->mSelected].previews;
    const auto it = textures.find(baked_index);
    return it != textures.end() && static_cast<LLTattooPreviewBuffer*>(it->second.get())->ready() ? it->second.get() : nullptr;
}

void LLFloaterTattooCompare::releaseSources()
{
    for (auto& source : mSources)
        if (source.texture->getBoostLevel() == llmax(source.boost, S32(LLGLTexture::BOOST_PREVIEW)))
        {
            source.texture->setBoostLevel(source.boost);
            if (!source.no_delete && !source.texture->getDontDiscard()) source.texture->forceActive();
        }
    mSources.clear();
}

void LLFloaterTattooCompare::stop()
{
    ++mGeneration;
    mActive = mCommitting = mPrepared = mClosing = false;
    mSelected = -1;
    mPreparing = 0;
    mCommitVersion = -1;
    mPublished = mPending = -1;
    mType = LLWearableType::WT_INVALID;
    releaseSources();
    if (!LLApp::isExiting() && !gDisconnected && isAgentAvatarValid()) gAgentAvatarp->updateMeshTextures();
    mCandidates.clear();
    mOriginalWearables.clear();
    mOriginalItems.clear();
    mDesiredItems.clear();
    // Links added before the replacement was confirmed belong to this attempt only.
    if (!LLApp::isExiting() && !gDisconnected)
        for (const auto& id : mAddedLinks)
        {
            const auto* item = gInventory.getItem(id);
            if (item && item->getIsLinkType() && item->getParentUUID() == LLAppearanceMgr::instance().getCOF())
                remove_inventory_item(id, new LLUpdateAppearanceOnDestroy);
        }
    mAddedLinks.clear();
    mRegions.clear();
    if (findChildView("items", false))
    {
        for (const auto* name : {"items", "previous", "next", "keep"}) getChildView(name)->setEnabled(false);
        getChild<LLTextBox>("position")->setText(LLStringUtil::null);
    }
}

void LLFloaterTattooCompare::status(const std::string& message)
{
    getChild<LLTextBox>("status")->setText(message);
}

void LLFloaterTattooCompare::fail(const std::string& message)
{
    const bool notify = mClosing || mCommitting || !getVisible();
    stop();
    status(message);
    if (notify)
    {
        LLSD args;
        args["MESSAGE"] = message;
        LLNotificationsUtil::add("GenericAlert", args);
    }
}

void LLFloaterTattooCompare::onClose(bool app_quitting)
{
    if (app_quitting) { stop(); return; }
    if (mClosing) return;
    if (!mPrepared || mSelected < 0) { stop(); return; }
    mClosing = true;
    if (!mCommitting) mTimer.reset();
    for (const auto* name : {"items", "previous", "next", "keep", "cancel"}) getChildView(name)->setEnabled(false);
    status(getString("applying"));
    update();
}

void LLFloaterTattooCompare::commit(S32 index)
{
    if (!unchanged()) { fail(getString("changed")); return; }
    mCommitting = true;
    mPending = index;
    mDesiredItems = desiredItems(index);
    mCommitVersion = -1;
    mTimer.reset();
    status(getString(mClosing ? "applying" : "sharing"));
    finishCommit();
}

void LLFloaterTattooCompare::finishCommit()
{
    COF before = cof();
    for (const auto& id : mAddedLinks) before.erase(id);
    if (!available() || before != mExpectedCOF || outfit(true) != mExpectedOutfit)
    { fail(getString("apply_interrupted")); return; }
    const auto handle = getHandle();
    const U32 generation = mGeneration;
    const LLUUID cof_id = LLAppearanceMgr::instance().getCOF();
    mCommitOutfit.clear();
    for (const auto& id : mDesiredItems)
    {
        if (!canCompare(id)) { fail(getString("apply_interrupted")); return; }
        const auto* item = gInventory.getItem(id);
        mCommitOutfit.emplace_back(id, item->getAssetUUID());
        if (!LLAppearanceMgr::instance().findCOFItemLinks(id).empty()) continue;
        LLPointer<LLInventoryCallback> callback = new LLBoostFuncInventoryCallback([handle, generation, id, cof_id](const LLUUID& link_id)
        {
            const auto* link = gInventory.getItem(link_id);
            const bool valid = link && link->getIsLinkType() && link->getParentUUID() == cof_id && link->getLinkedUUID() == id;
            auto* self = dynamic_cast<LLFloaterTattooCompare*>(handle.get());
            if (self && self->mGeneration == generation && self->mCommitting)
            {
                if (!valid) { self->fail(self->getString("apply_interrupted")); return; }
                self->mAddedLinks.push_back(link_id);
                self->finishCommit();
            }
            else if (valid && !LLApp::isExiting() && !gDisconnected)
                remove_inventory_item(link_id, new LLUpdateAppearanceOnDestroy);
        });
        // Confirm all replacements exist before removing any currently worn item.
        link_inventory_object(cof_id, item, callback);
        return;
    }
    COF expected = cof();
    uuid_vec_t removals;
    std::map<LLUUID, std::string> descriptions;
    for (const auto& original : mExpectedCOF)
    {
        const auto* item = gInventory.getItem(original.first);
        if (item && item->getIsLinkType() && item->getWearableType() == mType &&
            std::find(mDesiredItems.begin(), mDesiredItems.end(), original.second.first) == mDesiredItems.end())
        {
            removals.push_back(original.first);
            expected.erase(original.first);
        }
    }
    for (size_t i = 0; mType == LLWearableType::WT_TATTOO && i < mDesiredItems.size(); ++i)
        for (const auto& item : LLAppearanceMgr::instance().findCOFItemLinks(mDesiredItems[i]))
        {
            const auto description = llformat("@%d", mType * 100 + S32(i));
            if (item->getActualDescription() != description)
            {
                descriptions[item->getUUID()] = description;
                expected[item->getUUID()].second = description;
            }
        }

    mExpectedCOF = expected;
    mAddedLinks.clear();
    LLPointer<LLInventoryCallback> callback = new LLBoostFuncInventoryCallback([](const LLUUID&) {}, [handle, generation, expected]
    {
        if (LLApp::isExiting()) return;
        doOnIdleOneTime([handle, generation, expected]
        {
            if (LLApp::isExiting() || gDisconnected) return;
            auto* self = dynamic_cast<LLFloaterTattooCompare*>(handle.get());
            if (self && self->mGeneration == generation && self->mCommitting && cof() == expected)
            {
                self->mCommitVersion = LLAppearanceMgr::instance().getCOFVersion();
                // This transaction already preserves the clothing order and layer limits.
                LLAppearanceMgr::instance().updateAppearanceFromCOF(false, false);
            }
            else
            {
                if (self && self->mGeneration == generation && self->mCommitting)
                    self->fail(self->getString("apply_interrupted"));
                LLAppearanceMgr::instance().updateAppearanceFromCOF();
            }
        });
    });
    for (const auto& id : removals) remove_inventory_item(id, callback);
    for (const auto& entry : descriptions)
    {
        LLSD updates;
        updates["desc"] = entry.second;
        update_inventory_item(entry.first, updates, callback);
    }
}
