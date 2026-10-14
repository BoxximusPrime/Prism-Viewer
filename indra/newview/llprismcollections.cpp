#include "llviewerprecompiledheaders.h"
#include "llprismcollections.h"

#include "llagentwearables.h"
#include "llappearancemgr.h"
#include "lleventtimer.h"
#include "llinventoryfunctions.h"
#include "llinventorymodel.h"
#include "llinventorymodelbackgroundfetch.h"
#include "llnotificationsutil.h"
#include "llviewercontrol.h"
#include "llviewerinventory.h"
#include "llvoavatarself.h"

namespace LLPrismCollections
{
namespace
{
bool sCreatingRoot = false;
bool sChanging = false;
bool sWriting = false;

LLUUID childNamed(const LLUUID& parent, const std::string& name)
{
    for (const LLUUID& id : folders(parent))
        if (LLStringUtil::compareInsensitive(gInventory.getCategory(id)->getName(), name) == 0) return id;
    return LLUUID::null;
}

Selections selections()
{
    Selections result;
    const LLSD saved = gSavedPerAccountSettings.getLLSD("PrismCollectionsState")["categories"];
    for (auto it = saved.beginMap(); it != saved.endMap(); ++it)
    {
        Selection& selection = result[LLUUID(it->first)];
        selection.set = it->second["set"].asUUID();
        const LLSD& items = it->second["items"];
        for (auto item = items.beginArray(); item != items.endArray(); ++item) selection.items.push_back(item->asUUID());
    }
    return result;
}

std::set<LLUUID> managedItems()
{
    std::set<LLUUID> result;
    const LLSD saved = gSavedPerAccountSettings.getLLSD("PrismCollectionsState")["managed"];
    for (auto it = saved.beginArray(); it != saved.endArray(); ++it) result.insert(it->asUUID());
    return result;
}

void saveState(const Selections& selected, const std::set<LLUUID>& managed)
{
    LLSD state = LLSD::emptyMap();
    for (const auto& entry : selected)
    {
        LLSD& value = state["categories"][entry.first.asString()];
        value["set"] = entry.second.set;
        for (const LLUUID& id : entry.second.items) value["items"].append(id);
    }
    for (const LLUUID& id : managed) state["managed"].append(id);
    gSavedPerAccountSettings.setLLSD("PrismCollectionsState", state);
}

std::set<LLUUID> wornItems()
{
    std::set<LLUUID> result;
    LLInventoryModel::cat_array_t cats;
    LLInventoryModel::item_array_t items;
    gInventory.collectDescendents(LLAppearanceMgr::instance().getCOF(), cats, items, false);
    for (const auto& item : items)
        if (validItem(item->getLinkedUUID()) && get_is_item_worn(item)) result.insert(item->getLinkedUUID());
    return result;
}

bool capacity(const Change& change)
{
    S32 clothing = gAgentWearables.getClothingLayerCount();
    S32 attachments = gAgentAvatarp->getAttachmentCount();
    auto count = [&](const uuid_vec_t& items, S32 delta)
    {
        for (const LLUUID& id : items)
        {
            auto* item = gInventory.getItem(id);
            if (!item) continue;
            if (item->getType() == LLAssetType::AT_CLOTHING) clothing += delta;
            if (item->getType() == LLAssetType::AT_OBJECT) attachments += delta;
        }
    };
    count(change.remove, -1);
    count(change.add, 1);
    return clothing <= LLAgentWearables::MAX_CLOTHING_LAYERS && attachments <= gAgentAvatarp->getMaxAttachments();
}

// Wait for actual wear/detach completion before allowing another swap or changing layer order.
class Swap final : public LLEventTimer
{
public:
    Swap(const Selections& selected, Change change, uuid_vec_t order)
        : LLEventTimer(0.25f), mChange(std::move(change)), mOrder(std::move(order))
    {
        sChanging = true;
        mTimeout.start();
        // Persist the intended ownership before sending requests, including late server replies.
        auto pending = mChange.managed;
        pending.insert(mChange.remove.begin(), mChange.remove.end());
        saveState(selected, pending);
        if (!mChange.remove.empty()) LLAppearanceMgr::instance().removeItemsFromAvatar(mChange.remove);
    }
    ~Swap() override { sChanging = false; }
    bool tick() override
    {
        if (!isAgentAvatarValid()) return true;
        if (mTimeout.getElapsedTimeF32() > 45.f)
        {
            error("The set did not finish applying. Check your worn items, then use Wear set to retry. Your set links have not changed.");
            return true;
        }
        for (const LLUUID& id : mChange.remove)
            if (get_is_item_worn(id) || LLAppearanceMgr::instance().isLinkedInCOF(id)) return false;
        if (!gAgentWearables.areWearablesLoaded() || LLAppearanceMgr::instance().isOutfitLocked()) return false;
        if (!mAdded)
        {
            // Recheck after detaching: manual outfit changes may have used the available slots.
            Change remaining;
            remaining.add = mChange.add;
            if (!capacity(remaining))
            {
                error("There is not enough room for this set without replacing other worn items. Free some clothing or attachment slots and try again.");
                return true;
            }
            for (const LLUUID& id : mChange.add)
                if (!validItem(id)) { error("A set item is no longer available. Restore it from Trash or edit the set, then retry."); return true; }
            mAdded = true;
            if (!mChange.add.empty()) LLAppearanceMgr::instance().wearItemsOnAvatar(mChange.add, true, false);
            return false;
        }
        for (const LLUUID& id : mOrder)
            if (!get_is_item_worn(id)) return false;

        // Preserve unrelated layers in place; only reorder this set's managed layers within their slots.
        for (S32 t = 0; t < LLWearableType::WT_COUNT; ++t)
        {
            auto type = static_cast<LLWearableType::EType>(t);
            uuid_vec_t ordered;
            for (const LLUUID& id : mOrder)
            {
                auto* item = gInventory.getItem(id);
                if (item && item->getType() == LLAssetType::AT_CLOTHING && item->getWearableType() == type
                    && mChange.managed.count(id)) ordered.push_back(id);
            }
            if (ordered.size() < 2) continue;
            uuid_vec_t group;
            size_t next = 0;
            for (S32 i = static_cast<S32>(gAgentWearables.getWearableCount(type)) - 1; i >= 0; --i)
            {
                LLUUID id = gAgentWearables.getWearableItemID(type, i);
                if (std::find(ordered.begin(), ordered.end(), id) != ordered.end()) id = ordered[next++];
                const auto links = LLAppearanceMgr::instance().findCOFItemLinks(id);
                if (links.empty()) return false;
                group.push_back(links.front()->getUUID());
            }
            LLAppearanceMgr::instance().reorderWearableGroup(type, group);
        }
        saveState(selections(), mChange.managed);
        return true;
    }
private:
    Change mChange;
    uuid_vec_t mOrder;
    LLTimer mTimeout;
    bool mAdded = false;
};
}

Change planChange(const Selections& selected, const std::set<LLUUID>& managed, const std::set<LLUUID>& worn, const uuid_vec_t& applying)
{
    Change change;
    std::set<LLUUID> wanted;
    for (const auto& entry : selected)
        wanted.insert(entry.second.items.begin(), entry.second.items.end());
    for (const LLUUID& id : wanted)
    {
        if (managed.count(id)) change.managed.insert(id);
    }
    change.managed.insert(applying.begin(), applying.end());
    for (const LLUUID& id : applying)
        if (!worn.count(id) && std::find(change.add.begin(), change.add.end(), id) == change.add.end()) change.add.push_back(id);
    for (const LLUUID& id : managed)
    {
        const auto* item = gInventory.getItem(id);
        // Essential body parts stay worn until wearItemsOnAvatar replaces their type.
        if (!wanted.count(id) && worn.count(id) && item && item->getType() != LLAssetType::AT_BODYPART)
            change.remove.push_back(id);
    }
    return change;
}

bool validBodyParts(const uuid_vec_t& items)
{
    std::set<LLWearableType::EType> types;
    for (const LLUUID& id : items)
    {
        const auto* item = gInventory.getItem(id);
        if (item && item->getType() == LLAssetType::AT_BODYPART && !types.insert(item->getWearableType()).second)
            return false;
    }
    return true;
}

void error(const std::string& message)
{
    LLSD args;
    args["MESSAGE"] = message;
    LLNotificationsUtil::add("PrismCollectionsMessage", args);
}

uuid_vec_t folders(const LLUUID& parent)
{
    uuid_vec_t result;
    if (parent.isNull()) return result;
    LLInventoryModel::cat_array_t* cats = nullptr;
    LLInventoryModel::item_array_t* items = nullptr;
    gInventory.getDirectDescendentsOf(parent, cats, items);
    if (cats) for (const auto& cat : *cats) result.push_back(cat->getUUID());
    std::sort(result.begin(), result.end(), [](const LLUUID& a, const LLUUID& b)
    {
        return LLStringUtil::compareDict(gInventory.getCategory(a)->getName(), gInventory.getCategory(b)->getName()) < 0;
    });
    return result;
}

LLUUID root()
{
    const LLUUID inventory = gInventory.getRootFolderID();
    if (inventory.isNull() || !gInventory.isCategoryComplete(inventory)) return LLUUID::null;
    // The AO already maintains #Prism, even when the AO is disabled.
    const LLUUID prism = childNamed(inventory, "#Prism");
    if (prism.isNull()) return LLUUID::null;
    if (!gInventory.isCategoryComplete(prism))
    {
        LLInventoryModelBackgroundFetch::instance().start(prism);
        return LLUUID::null;
    }
    LLUUID collections = childNamed(prism, "Collections");
    if (collections.isNull() && !sCreatingRoot)
    {
        sCreatingRoot = true;
        gInventory.createNewCategory(prism, LLFolderType::FT_NONE, "Collections",
            [](const LLUUID&) { sCreatingRoot = false; });
    }
    return collections;
}

bool isCategory(const LLUUID& id)
{
    auto* category = gInventory.getCategory(id);
    return category && category->getParentUUID() == root() && category->getParentUUID().notNull();
}

bool validItem(const LLUUID& id)
{
    auto* item = gInventory.getItem(gInventory.getLinkedItemID(id));
    return item && item->isFinished() && !item->getIsLinkType()
        && (item->getType() == LLAssetType::AT_CLOTHING || item->getType() == LLAssetType::AT_OBJECT
            || item->getType() == LLAssetType::AT_BODYPART)
        && gInventory.isObjectDescendentOf(item->getUUID(), gInventory.getRootFolderID())
        && !gInventory.isObjectDescendentOf(item->getUUID(), gInventory.findCategoryUUIDForType(LLFolderType::FT_TRASH));
}

bool readSet(const LLUUID& id, uuid_vec_t& result, std::string& message)
{
    result.clear();
    auto* folder = gInventory.getCategory(id);
    if (!folder || !isCategory(folder->getParentUUID())) { message = "That set is no longer in Collections."; return false; }
    if (!gInventory.isCategoryComplete(id))
    {
        LLInventoryModelBackgroundFetch::instance().start(id);
        message = "This set is still loading. Please try again in a moment.";
        return false;
    }
    LLInventoryModel::cat_array_t* cats = nullptr;
    LLInventoryModel::item_array_t* items = nullptr;
    gInventory.getDirectDescendentsOf(id, cats, items);
    if (cats && !cats->empty()) { message = "Sets contain item links directly, without subfolders."; return false; }
    if (items)
    {
        auto sorted = *items;
        std::stable_sort(sorted.begin(), sorted.end(), [](const auto& a, const auto& b)
        {
            return a->getActualDescription() < b->getActualDescription();
        });
        for (const auto& link : sorted)
        {
            if (link->getActualType() != LLAssetType::AT_LINK || !validItem(link->getLinkedUUID()))
            {
                if (link->getActualType() == LLAssetType::AT_LINK)
                    LLInventoryModelBackgroundFetch::instance().start(link->getLinkedUUID(), false);
                message = "A set item is missing, still loading, or unsupported. Sets support clothing layers, attachments, and body parts. Check its links in Inventory.";
                return false;
            }
            if (std::find(result.begin(), result.end(), link->getLinkedUUID()) == result.end()) result.push_back(link->getLinkedUUID());
        }
    }
    if (!validBodyParts(result))
    {
        message = "Include only one shape, skin, pair of eyes, and system hair in each set.";
        return false;
    }
    return true;
}

bool validName(const LLUUID& parent, const LLUUID& id, std::string name)
{
    LLStringUtil::trim(name);
    if (name.empty() || name.size() > 63 || name.find_first_of("/\\\n\r\t") != std::string::npos) return false;
    const LLUUID existing = childNamed(parent, name);
    return existing.isNull() || existing == id;
}

LLUUID activeSet(const LLUUID& category)
{
    return gSavedPerAccountSettings.getLLSD("PrismCollectionsState")["categories"][category.asString()]["set"].asUUID();
}

bool busy() { return sChanging || sWriting; }
void setWriting(bool writing) { sWriting = writing; }

bool wear(const LLUUID& category, const LLUUID& set, bool remove)
{
    if (busy() || !isAgentAvatarValid() || !gAgentWearables.areWearablesLoaded()
        || !gInventory.isCategoryComplete(LLAppearanceMgr::instance().getCOF())
        || LLAppearanceMgr::instance().isOutfitLocked())
    {
        error("Please wait for your current appearance change to finish.");
        return false;
    }
    if (!isCategory(category)) return false;
    uuid_vec_t items;
    std::string message;
    auto* folder = gInventory.getCategory(set);
    if (!folder || folder->getParentUUID() != category) return false;
    if (!readSet(set, items, message)) { error(message); return false; }
    if (items.empty()) { error("Add some items to this set before wearing it."); return false; }
    Selections selected = selections();
    auto managed = managedItems();
    // Include membership saved by older builds, which did not manage pre-worn items.
    auto active = selected.find(category);
    if (active != selected.end() && (!remove || active->second.set == set))
        managed.insert(active->second.items.begin(), active->second.items.end());
    if (remove)
    {
        // Selected members may have been worn outside Collections, without an active selection.
        managed.insert(items.begin(), items.end());
        if (active != selected.end() && active->second.set == set) selected.erase(active);
        items.clear();
    }
    else selected[category] = {set, items};
    auto worn = wornItems();
    // Attachments can be visible before their COF links arrive.
    for (const LLUUID& id : items)
        if (get_is_item_worn(id) || LLAppearanceMgr::instance().isLinkedInCOF(id)) worn.insert(id);
    for (const LLUUID& id : managed)
        if (get_is_item_worn(id) || LLAppearanceMgr::instance().isLinkedInCOF(id)) worn.insert(id);
    const Change change = planChange(selected, managed, worn, items);
    if (!capacity(change))
    {
        error("This set would exceed your clothing or attachment limit. Nothing has changed. Free some slots and try again.");
        return false;
    }
    new Swap(std::move(selected), change, items);
    return true;
}

void forget(const LLUUID& folder)
{
    Selections selected = selections();
    for (auto it = selected.begin(); it != selected.end();)
    {
        if (it->first == folder || it->second.set == folder) it = selected.erase(it);
        else ++it;
    }
    const Change change = planChange(selected, managedItems(), wornItems(), {});
    saveState(selected, change.managed);
}
}
