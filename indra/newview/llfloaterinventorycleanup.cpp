/** Inventory cleanup: scan metadata, review exact item IDs, then move to Trash. */
#include "llviewerprecompiledheaders.h"
#include "llfloaterinventorycleanup.h"
#include "llagent.h"
#include "llavatarnamecache.h"
#include "llbutton.h"
#include "llcheckboxctrl.h"
#include "llfloaterreg.h"
#include "llinventoryfunctions.h"
#include "llinventorymodel.h"
#include "llinventorymodelbackgroundfetch.h"
#include "llscrolllistctrl.h"
#include "llscrolllistitem.h"
#include "llsdserialize.h"
#include "llsdutil.h"
#include "llspinctrl.h"
#include "lltextbox.h"
#include "lltexteditor.h"
#include "llviewercontrol.h"
#include "llviewerinventory.h"
#include <algorithm>
#include <cctype>
#include <sstream>

namespace
{
constexpr S32 PAGE_SIZE = 500;
const char* PROTECTED = "InventoryCleanupProtectedFolders";
using Entry = LLInventoryCleanupPlan::Entry;

std::string folderPath(LLUUID id)
{
    std::string path;
    std::set<LLUUID> seen;
    while (id.notNull() && seen.insert(id).second)
    {
        const auto* cat = gInventory.getCategory(id);
        if (!cat) return "[Unavailable folder] / " + path;
        path = cat->getName() + (path.empty() ? "" : " / " + path);
        id = cat->getParentUUID();
    }
    return path;
}

bool demoName(std::string name)
{
    // Token matching avoids false positives such as "demolition".
    for (char& c : name)
        c = std::isalnum(static_cast<unsigned char>(c)) ?
            static_cast<char>(std::tolower(static_cast<unsigned char>(c))) : ' ';
    std::istringstream words(name);
    std::string word;
    while (words >> word) if (word == "demo" || word == "demos") return true;
    return false;
}

struct InventoryState
{
    LLInventoryModel::cat_array_t cats;
    LLInventoryModel::item_array_t items;
    std::set<LLUUID> linkedItems;
    std::set<LLUUID> protectedFolders;
    bool complete = false;
    LLInventoryCleanupPlan::LoadState load;
    std::vector<LLUUID> incompleteFolders;
    std::vector<LLUUID> incompleteItems;
    S32 unknownFolders = 0;
    S32 missingChildren = 0;

    explicit InventoryState(bool build_links = true)
    {
        auto& fetch = LLInventoryModelBackgroundFetch::instance();
        load.usable = gInventory.isInventoryUsable();
        load.traversalFinished = fetch.inventoryFetchCompleted();
        load.requestsIdle = fetch.isBulkFetchProcessingComplete();
        if (!load.usable) return;
        // Audit the personal inventory even when the fetcher says it is finished.
        // A known folder version can still have a mismatched child count; a normal
        // start() skips such folders and does not repair them.
        gInventory.collectDescendents(gInventory.getRootFolderID(), cats, items,
            LLInventoryModel::INCLUDE_TRASH);
        const auto inspect_folder = [this](const LLUUID& id) {
            ++load.knownFolders;
            if (gInventory.isCategoryComplete(id)) ++load.completeFolders;
            else
            {
                incompleteFolders.push_back(id);
                if (const auto* cat = gInventory.getCategory(id))
                {
                    if (cat->getVersion() == LLViewerInventoryCategory::VERSION_UNKNOWN) ++unknownFolders;
                    missingChildren += llmax(0, cat->getDescendentCount() - cat->getViewerDescendentCount());
                }
            }
        };
        inspect_folder(gInventory.getRootFolderID());
        for (const auto& cat : cats) inspect_folder(cat->getUUID());
        load.knownItems = items.size();
        // Include links in Trash too: deleting a target must not strand a restorable outfit.
        for (const auto& item : items)
        {
            if (item->isFinished()) ++load.completeItems;
            else incompleteItems.push_back(item->getUUID());
            if (!build_links) continue;
            if (item->getActualType() == LLAssetType::AT_LINK)
                linkedItems.insert(item->getLinkedUUID());
            else if (item->getActualType() == LLAssetType::AT_LINK_FOLDER)
                protectedFolders.insert(item->getLinkedUUID());
        }
        complete = load.ready();
        if (!build_links) return;
        const LLSD saved = gSavedPerAccountSettings.getLLSD(PROTECTED);
        for (const auto& id : llsd::inArray(saved)) protectedFolders.insert(id.asUUID());
    }

    bool eligible(const LLViewerInventoryItem* item) const
    {
        if (!complete || !item || !item->isFinished() || item->getIsLinkType() ||
            linkedItems.count(item->getUUID()) ||
            !get_is_item_removable(&gInventory, item->getUUID(), true)) return false;
        LLUUID parent = item->getParentUUID();
        std::set<LLUUID> seen;
        while (parent.notNull() && seen.insert(parent).second)
        {
            if (protectedFolders.count(parent)) return false;
            const auto* cat = gInventory.getCategory(parent);
            if (!cat) return false;
            const auto type = cat->getPreferredType();
            if (type == LLFolderType::FT_TRASH || type == LLFolderType::FT_CURRENT_OUTFIT ||
                type == LLFolderType::FT_MY_OUTFITS || type == LLFolderType::FT_OUTFIT ||
                type == LLFolderType::FT_MARKETPLACE_LISTINGS || type == LLFolderType::FT_MARKETPLACE_STOCK ||
                type == LLFolderType::FT_MARKETPLACE_VERSION || type == LLFolderType::FT_INBOX)
                return false;
            if (parent == gInventory.getRootFolderID()) return true;
            parent = cat->getParentUUID();
        }
        return false;
    }

    bool folderEligible(const LLUUID& id) const
    {
        const auto* folder = gInventory.getCategory(id);
        if (!complete || !folder || folder->getPreferredType() != LLFolderType::FT_NONE ||
            !get_is_category_removable(&gInventory, id)) return false;
        LLUUID parent = id;
        std::set<LLUUID> seen;
        while (parent.notNull() && seen.insert(parent).second)
        {
            if (protectedFolders.count(parent)) return false;
            const auto* cat = gInventory.getCategory(parent);
            if (!cat) return false;
            const auto type = cat->getPreferredType();
            if (type == LLFolderType::FT_TRASH || type == LLFolderType::FT_CURRENT_OUTFIT ||
                type == LLFolderType::FT_MY_OUTFITS || type == LLFolderType::FT_OUTFIT ||
                type == LLFolderType::FT_MARKETPLACE_LISTINGS || type == LLFolderType::FT_MARKETPLACE_STOCK ||
                type == LLFolderType::FT_MARKETPLACE_VERSION || type == LLFolderType::FT_INBOX) return false;
            if (parent == gInventory.getRootFolderID()) return true;
            parent = cat->getParentUUID();
        }
        return false;
    }

    Entry snapshotFolder(const LLUUID& id) const
    {
        Entry entry{id.asString(), "", folderEligible(id)};
        entry.folder = true;
        const auto* folder = gInventory.getCategory(id);
        if (!folder) return entry;
        LLInventoryModel::cat_array_t children;
        LLInventoryModel::item_array_t child_items;
        gInventory.collectDescendents(id, children, child_items, LLInventoryModel::INCLUDE_TRASH);
        if (children.size() + child_items.size() + 1 > LLInventoryCleanupPlan::MAX_AFFECTED)
        {
            entry.eligible = false;
            return entry;
        }
        LLSD manifest;
        const auto add_folder = [&manifest](const LLViewerInventoryCategory* cat) {
            LLSD data;
            cat->exportLLSD(data);
            data["cleanup_path"] = folderPath(cat->getUUID());
            data["cleanup_child_count"] = cat->getDescendentCount();
            manifest[cat->getUUID().asString()] = data;
        };
        add_folder(folder);
        for (const auto& cat : children)
        {
            add_folder(cat);
            entry.contents.push_back(cat->getUUID().asString());
            if (!folderEligible(cat->getUUID())) entry.eligible = false;
        }
        for (const auto& item : child_items)
        {
            const Entry child = snapshot(item);
            manifest[child.id] = child.fingerprint;
            entry.contents.push_back(child.id);
            if (!child.eligible) entry.eligible = false;
        }
        std::sort(entry.contents.begin(), entry.contents.end());
        if (entry.contents.size() + 1 > LLInventoryCleanupPlan::MAX_AFFECTED) entry.eligible = false;
        std::ostringstream serialized;
        LLSDSerialize::toNotation(manifest, serialized);
        entry.fingerprint = serialized.str();
        return entry;
    }

    Entry snapshot(const LLViewerInventoryItem* item) const
    {
        LLSD data = item->asLLSD();
        data["cleanup_path"] = folderPath(item->getParentUUID());
        std::ostringstream serialized;
        LLSDSerialize::toNotation(data, serialized);
        return {item->getUUID().asString(), serialized.str(), eligible(item)};
    }
};

std::string assetKey(const LLViewerInventoryItem* item)
{
    return item->getAssetUUID().isNull() ? "" :
        std::to_string(item->getActualType()) + ":" + item->getAssetUUID().asString();
}

std::string versionKey(const LLViewerInventoryItem* item)
{
    std::string name = item->getName();
    LLStringUtil::trim(name);
    LLStringUtil::toLower(name);
    return item->getCreatorUUID().asString() + ":" + name;
}

LLSD rowFor(const LLViewerInventoryItem* item, const std::string& reason)
{
    LLSD row;
    row["value"] = item->getUUID();
    LLAvatarName creator;
    const std::string creator_name = LLAvatarNameCache::get(item->getCreatorUUID(), &creator) ?
        creator.getCompleteName() : item->getCreatorUUID().asString();
    const std::vector<std::pair<std::string, std::string>> fields = {
        {"reason", reason}, {"item", item->getName()},
        {"acquired", item->getCreationDate() > 0 ? LLDate(static_cast<F64>(item->getCreationDate())).asString().substr(0, 10) : "Unknown"},
        {"creator", creator_name}, {"folder", folderPath(item->getParentUUID())}};
    for (const auto& field : fields)
    {
        LLSD column;
        column["column"] = field.first;
        column["value"] = field.second;
        row["columns"].append(column);
    }
    return row;
}

LLSD folderRow(const LLUUID& id, const std::string& reason)
{
    LLSD row;
    row["value"] = id;
    const auto* cat = gInventory.getCategory(id);
    const std::vector<std::pair<std::string, std::string>> fields = {
        {"reason", reason}, {"item", cat ? cat->getName() : id.asString()},
        {"acquired", ""}, {"creator", ""}, {"folder", cat ? folderPath(cat->getParentUUID()) : ""}};
    for (const auto& field : fields)
    {
        LLSD column;
        column["column"] = field.first;
        column["value"] = field.second;
        row["columns"].append(column);
    }
    return row;
}

std::string describe(const LLViewerInventoryItem* item, bool show_ids = false)
{
    const auto& perm = item->getPermissions();
    std::string text = item->getName() + "\nFolder: " + folderPath(item->getParentUUID()) +
        "\nPermissions: " + ((perm.getMaskOwner() & PERM_COPY) ? "Copy  " : "No copy  ") +
        ((perm.getMaskOwner() & PERM_MODIFY) ? "Modify  " : "No modify  ") +
        ((perm.getMaskOwner() & PERM_TRANSFER) ? "Transfer" : "No transfer") +
        "    Next owner: " + ((perm.getMaskNextOwner() & PERM_COPY) ? "Copy  " : "No copy  ") +
        ((perm.getMaskNextOwner() & PERM_MODIFY) ? "Modify  " : "No modify  ") +
        ((perm.getMaskNextOwner() & PERM_TRANSFER) ? "Transfer" : "No transfer");
    if (!item->getDescription().empty()) text += "\n" + item->getDescription();
    if (show_ids) text += "\nItem ID: " + item->getUUID().asString() + "    Asset ID: " + item->getAssetUUID().asString();
    return text;
}

void status(LLFloater* floater, const std::string& text)
{
    floater->getChild<LLTextBox>("status")->setValue(text);
}
}

LLFloaterInventoryCleanup::LLFloaterInventoryCleanup(const LLSD& key) : LLFloater(key) {}

bool LLFloaterInventoryCleanup::postBuild()
{
    mItems = getChild<LLScrollListCtrl>("items");
    for (const std::string tool : {"demos", "assets", "versions", "old"})
        getChild<LLButton>("choose_" + tool)->setClickedCallback([this, tool](LLUICtrl*, const LLSD&) { chooseTool(tool); });
    getChild<LLButton>("back")->setClickedCallback([this](LLUICtrl*, const LLSD&) { showHome(); });
    getChild<LLButton>("toggle_protected")->setClickedCallback([this](LLUICtrl*, const LLSD&) {
        const bool show = !getChild<LLPanel>("protected_panel")->getVisible();
        getChild<LLPanel>("protected_panel")->setVisible(show);
        getChild<LLTextEditor>("details")->setVisible(!show);
        getChild<LLButton>("toggle_protected")->setLabel(show ? "Back to item details" : "Protected folders");
        mShowLoadingDetails = false;
    });
    mItems->setCommitCallback([this](LLUICtrl*, const LLSD&) { details(); });
    getChild<LLButton>("retry_loading")->setClickedCallback([this](LLUICtrl*, const LLSD&) { retryLoading(); });
    getChild<LLButton>("loading_details")->setClickedCallback([this](LLUICtrl*, const LLSD&) {
        mShowLoadingDetails = !mShowLoadingDetails;
        getChild<LLPanel>("protected_panel")->setVisible(false);
        getChild<LLTextEditor>("details")->setVisible(true);
        getChild<LLButton>("toggle_protected")->setLabel("Protected folders");
        if (mShowLoadingDetails) refreshLoading();
        else details();
    });
    getChild<LLButton>("scan")->setClickedCallback([this](LLUICtrl*, const LLSD&) { scan(); });
    getChild<LLButton>("review")->setClickedCallback([this](LLUICtrl*, const LLSD&) { review(); });
    getChild<LLButton>("protect")->setClickedCallback([this](LLUICtrl*, const LLSD&) { protectFolders(); });
    getChild<LLButton>("unprotect")->setClickedCallback([this](LLUICtrl*, const LLSD&) { unprotectFolders(); });
    getChild<LLButton>("previous")->setClickedCallback([this](LLUICtrl*, const LLSD&) { --mPage; showPage(); });
    getChild<LLButton>("next")->setClickedCallback([this](LLUICtrl*, const LLSD&) { ++mPage; showPage(); });
    getChild<LLButton>("show")->setClickedCallback([this](LLUICtrl*, const LLSD&) {
        if (auto* row = mItems->getFirstSelected()) show_item_original(row->getUUID());
    });
    return true;
}

void LLFloaterInventoryCleanup::onOpen(const LLSD&)
{
    refreshProtected();
    auto& fetch = LLInventoryModelBackgroundFetch::instance();
    if (gInventory.isInventoryUsable() && !fetch.inventoryFetchStarted())
        fetch.start(gInventory.getRootFolderID());
    mLoadingSignature.clear();
    showHome();
    refreshLoading();
}

void LLFloaterInventoryCleanup::reshape(S32 width, S32 height, bool called_from_parent)
{
    LLFloater::reshape(width, height, called_from_parent);
    if (!mItems) return;
    auto* home = getChild<LLPanel>("home");
    const S32 side = llmin(300, llmin((home->getRect().getHeight() - 200) / 2, (width - 80) / 2));
    const S32 extent = side * 2 + 16;
    auto* grid = getChild<LLPanel>("tool_grid");
    grid->reshape(extent, extent);
    grid->setOrigin((width - extent) / 2, home->getRect().getHeight() - 110 - extent);
    S32 index = 0;
    for (const std::string tool : {"demos", "assets", "versions", "old"})
    {
        const S32 x = (index % 2) * (side + 16);
        const S32 y = (1 - index / 2) * (side + 16);
        getChild<LLPanel>("card_" + tool)->setShape(LLRect(x, y + side, x + side, y));
        ++index;
    }
}

void LLFloaterInventoryCleanup::showHome()
{
    getChild<LLPanel>("home")->setVisible(true);
    getChild<LLPanel>("workspace")->setVisible(false);
    mShowLoadingDetails = false;
    mItems->deselectAllItems();
    reshape(getRect().getWidth(), getRect().getHeight());
    getChild<LLButton>("choose_demos")->setFocus(true);
}

void LLFloaterInventoryCleanup::chooseTool(const std::string& tool)
{
    mTool = tool;
    getChild<LLPanel>("home")->setVisible(false);
    getChild<LLPanel>("workspace")->setVisible(true);
    getChild<LLPanel>("protected_panel")->setVisible(false);
    getChild<LLTextEditor>("details")->setVisible(true);
    getChild<LLButton>("toggle_protected")->setLabel("Protected folders");
    getChild<LLSpinCtrl>("year")->setVisible(tool == "old");
    std::string title, description;
    if (tool == "demos")
    {
        title = "Demo folders";
        description = "Folders with DEMO in their name. Review the complete package before moving it to Trash.";
    }
    else if (tool == "assets")
    {
        title = "Duplicate copies";
        description = "Items sharing the same asset. Compare permissions and keep the copies you need.";
    }
    else if (tool == "versions")
    {
        title = "Object versions";
        description = "Same name and creator, different assets. The newest copy is not always the version you want to keep.";
    }
    else
    {
        title = "Older inventory";
        description = "Items acquired before the selected year. This date does not indicate when an item was last used.";
    }
    getChild<LLTextBox>("tool_title")->setValue(title);
    getChild<LLTextBox>("tool_description")->setValue(description);
    getChild<LLButton>("back")->setFocus(true);
    scan();
}

void LLFloaterInventoryCleanup::draw()
{
    if (LLDate::now().secondsSinceEpoch() >= mNextLoadingUpdate) refreshLoading();
    LLFloater::draw();
}

void LLFloaterInventoryCleanup::refreshLoading()
{
    const F64 now = LLDate::now().secondsSinceEpoch();
    mNextLoadingUpdate = now + 2.0;
    InventoryState state(false);
    auto& fetch = LLInventoryModelBackgroundFetch::instance();
    const std::string counts = llformat(
        "Folders complete: %d / %d known. Item metadata: %d / %d known. Queued folders/items: %d / %d; active requests: %d.",
        static_cast<S32>(state.load.completeFolders), static_cast<S32>(state.load.knownFolders),
        static_cast<S32>(state.load.completeItems), static_cast<S32>(state.load.knownItems),
        static_cast<S32>(fetch.getQueuedFolderCount()), static_cast<S32>(fetch.getQueuedItemCount()),
        fetch.getActiveFetchCount());
    std::string headline;
    if (!state.load.usable) headline = "Waiting for inventory initialization.";
    else if (state.complete) headline = "Ready to scan.";
    else if (!state.load.requestsIdle) headline = "Background fetch is active (request counts include Library).";
    else if (!state.load.traversalFinished) headline = "Personal inventory traversal is not finished. Click Retry loading.";
    else headline = "Fetch is idle, but inventory is incomplete. Click Retry loading or Loading details.";
    const std::string signature = headline + counts;
    if (signature != mLoadingSignature)
    {
        mLoadingSignature = signature;
        mLastLoadingChange = now;
    }
    if (!state.complete && now - mLastLoadingChange >= 30.0)
        headline += llformat(" Counts unchanged for %d seconds.", static_cast<S32>(now - mLastLoadingChange));
    std::string summary;
    if (state.complete) summary = "Inventory ready.";
    else if (!state.load.usable) summary = "Preparing your inventory...";
    else if (!state.load.requestsIdle) summary = llformat("Loading inventory... %d of %d folders ready.",
        static_cast<S32>(state.load.completeFolders), static_cast<S32>(state.load.knownFolders));
    else summary = "Some inventory is missing. Retry loading to finish preparing your scan.";
    getChild<LLTextBox>("loading_status")->setValue(summary);
    getChild<LLTextBox>("home_loading")->setValue(state.complete ? "Inventory ready" : "Inventory is preparing. Choose a tool to view loading status.");
    getChild<LLButton>("retry_loading")->setVisible(!state.complete);
    getChild<LLButton>("loading_details")->setVisible(!state.complete);
    getChild<LLButton>("retry_loading")->setEnabled(state.load.usable && state.load.requestsIdle && !state.complete);
    if (state.complete && mShowLoadingDetails) details();
    if (mShowLoadingDetails)
    {
        std::string text = headline + "\n" + counts + llformat(
            "\nUnknown folder versions: %d; count mismatches: %d; known missing child entries: %d. Totals can grow as folders arrive.\n",
            state.unknownFolders, static_cast<S32>(state.incompleteFolders.size()) - state.unknownFolders, state.missingChildren);
        text += "Completion requires every personal folder (including Trash/outfits) and item; missing links could hide references. Library completion history is not required.\n";
        S32 shown = 0;
        for (const auto& id : state.incompleteFolders)
        {
            if (++shown > 50) break;
            const auto* cat = gInventory.getCategory(id);
            text += folderPath(id) + " [" + id.asString() + "]";
            if (cat) text += llformat(" version=%d, expected children=%d, cached children=%d", cat->getVersion(), cat->getDescendentCount(), cat->getViewerDescendentCount());
            text += "\n";
        }
        for (const auto& id : state.incompleteItems)
        {
            if (++shown > 50) break;
            const auto* item = gInventory.getItem(id);
            text += "Incomplete item: " + (item ? item->getName() : id.asString()) + " [" + id.asString() + "]\n";
        }
        if (state.incompleteFolders.size() + state.incompleteItems.size() > 50)
            text += "Showing the first 50 blockers. Retry requests at most 20 entries per click.\n";
        getChild<LLTextEditor>("details")->setText(text);
    }
}

void LLFloaterInventoryCleanup::retryLoading()
{
    InventoryState state(false);
    auto& fetch = LLInventoryModelBackgroundFetch::instance();
    if (!state.load.usable || !state.load.requestsIdle)
    {
        status(this, "Waiting for current inventory requests. Loading status updates automatically.");
        refreshLoading();
        return;
    }
    if (!state.load.traversalFinished)
    {
        fetch.start(gInventory.getRootFolderID());
        status(this, "Requested a recursive personal-inventory fetch. Nothing in inventory is changed.");
    }
    else
    {
        S32 requested = 0;
        for (const auto& id : state.incompleteFolders)
        {
            if (requested >= 20) break;
            // Force refresh: normal recursive fetch skips known-version folders,
            // even when their cached child count does not match the server count.
            fetch.scheduleFolderFetch(id, true);
            ++requested;
        }
        for (const auto& id : state.incompleteItems)
        {
            if (requested >= 20) break;
            fetch.scheduleItemFetch(id, true);
            ++requested;
        }
        status(this, llformat("Requested refresh of %d incomplete entries (up to 20 per retry). Watch loading status, then Scan. Nothing has moved.", requested));
        LL_INFOS("InventoryCleanup") << "Retry: folders=" << state.incompleteFolders.size()
            << " items=" << state.incompleteItems.size() << " requested=" << requested << LL_ENDL;
    }
    refreshLoading();
}

void LLFloaterInventoryCleanup::scan()
{
    mRows = LLSD::emptyArray();
    mScan.clear();
    mPage = 0;
    mItems->deleteAllItems();
    getChild<LLTextEditor>("details")->setText(std::string());
    InventoryState state;
    if (!state.complete)
    {
        showPage();
        retryLoading();
        return;
    }
    const std::string& mode = mTool;
    if (mode == "demos")
    {
        std::set<LLUUID> candidates;
        for (const auto& cat : state.cats)
            if (demoName(cat->getName()) && state.folderEligible(cat->getUUID())) candidates.insert(cat->getUUID());
        // Only eligible enclosing packages suppress nested candidates. An oversized
        // collection or a protected sibling must not hide a safe individual package.
        std::map<LLUUID, Entry> packages;
        S32 excluded = 0;
        for (const auto& id : candidates)
        {
            Entry entry = state.snapshotFolder(id);
            if (!entry.eligible) { ++excluded; continue; }
            packages.emplace(id, std::move(entry));
        }
        std::vector<LLUUID> roots;
        for (const auto& package : packages)
        {
            const LLUUID& id = package.first;
            const auto* cat = gInventory.getCategory(id);
            LLUUID parent = cat->getParentUUID();
            bool nested = false;
            while (const auto* ancestor = gInventory.getCategory(parent))
            {
                if (packages.count(parent)) { nested = true; break; }
                parent = ancestor->getParentUUID();
            }
            if (!nested) roots.push_back(id);
        }
        std::sort(roots.begin(), roots.end(), [](const LLUUID& a, const LLUUID& b) { return folderPath(a) < folderPath(b); });
        for (const auto& id : roots)
        {
            Entry entry = std::move(packages.at(id));
            mRows.append(folderRow(id, llformat("Demo folder: %d contained entries", static_cast<S32>(entry.contents.size()))));
            mScan.emplace(id.asString(), std::move(entry));
        }
        showPage();
        status(this, llformat("%d demo folders; %d packages excluded by content safety checks or the 2,000-entry limit. Review shows all contents before moving folders.",
            static_cast<S32>(mRows.size()), excluded));
        return;
    }
    const S32 year = getChild<LLSpinCtrl>("year")->getValue().asInteger();
    const F64 cutoff = LLDate(llformat("%04d-01-01T00:00:00Z", year)).secondsSinceEpoch();
    std::map<std::string, S32> assets;
    std::map<std::string, std::set<std::string>> versions;
    for (const auto& item : state.items)
    {
        if (!state.eligible(item)) continue;
        if (!assetKey(item).empty()) ++assets[assetKey(item)];
        if (item->getActualType() == LLAssetType::AT_OBJECT && item->getAssetUUID().notNull())
            versions[versionKey(item)].insert(assetKey(item));
    }
    struct Candidate { LLUUID id; std::string reason; std::string group; time_t date; };
    std::vector<Candidate> candidates;
    for (const auto& item : state.items)
    {
        if (!state.eligible(item)) continue;
        std::string reason;
        std::string group = item->getName();
        if (mode == "assets" && !assetKey(item).empty() && assets[assetKey(item)] > 1)
        {
            reason = llformat("Same asset (%d candidates)", assets[assetKey(item)]);
            group = assetKey(item);
        }
        else if (mode == "versions" && item->getActualType() == LLAssetType::AT_OBJECT &&
                 versions[versionKey(item)].size() > 1)
        {
            reason = "Possible versions: same name + creator";
            group = versionKey(item);
        }
        else if (mode == "old" && item->getCreationDate() > 0 && item->getCreationDate() < cutoff)
            reason = "Acquired before " + std::to_string(year);
        if (!reason.empty()) candidates.push_back({item->getUUID(), reason, group, item->getCreationDate()});
    }
    std::sort(candidates.begin(), candidates.end(), [](const Candidate& a, const Candidate& b) {
        if (a.group != b.group) return a.group < b.group;
        if (a.date != b.date) return a.date > b.date;
        return a.id < b.id;
    });
    for (const auto& candidate : candidates)
    {
        const auto* item = gInventory.getItem(candidate.id);
        mRows.append(rowFor(item, candidate.reason));
        mScan.emplace(candidate.id.asString(), state.snapshot(item));
    }
    showPage();
}

void LLFloaterInventoryCleanup::showPage()
{
    const S32 count = static_cast<S32>(mRows.size());
    mPage = llmax(0, llmin(mPage, (llmax(1, count) - 1) / PAGE_SIZE));
    mItems->deleteAllItems();
    for (S32 i = mPage * PAGE_SIZE; i < llmin(count, (mPage + 1) * PAGE_SIZE); ++i)
        mItems->addElement(mRows[i]);
    getChild<LLButton>("previous")->setEnabled(mPage > 0);
    getChild<LLButton>("next")->setEnabled((mPage + 1) * PAGE_SIZE < count);
    status(this, llformat("%d candidates. Page %d of %d. Select up to 200 entries on this page; changing pages clears selection.",
        count, mPage + 1, llmax(1, (count + PAGE_SIZE - 1) / PAGE_SIZE)));
    details();
}

void LLFloaterInventoryCleanup::details()
{
    mShowLoadingDetails = false;
    std::string text = "Select a result to see its folder and permissions. Worn, linked, and protected inventory is excluded.";
    if (const auto* row = mItems->getFirstSelected())
    {
        if (const auto* item = gInventory.getItem(row->getUUID()))
        {
            text = describe(item);
        }
        else if (gInventory.getCategory(row->getUUID()))
        {
            const auto found = mScan.find(row->getUUID().asString());
            text = "Whole demo folder: " + folderPath(row->getUUID()) +
                "\nAll contents, including landmarks, HUDs, notecards and subfolders, move together. Review shows every affected entry.";
            if (found != mScan.end()) text += llformat("\nContained entries: %d", static_cast<S32>(found->second.contents.size()));
        }
    }
    getChild<LLTextEditor>("details")->setText(text);
    getChild<LLButton>("review")->setEnabled(!mItems->getAllSelected().empty());
}

void LLFloaterInventoryCleanup::review()
{
    const auto selected = mItems->getAllSelected();
    if (selected.empty() || selected.size() > LLInventoryCleanupPlan::MAX_ITEMS)
    {
        status(this, "Select between 1 and 200 entries for one review (at most 2,000 total affected entries). Nothing has moved.");
        return;
    }
    InventoryState state;
    std::vector<Entry> plan;
    std::map<std::string, Entry> current;
    LLSD key;
    for (const auto* row : selected)
    {
        const std::string id = row->getUUID().asString();
        const auto saved = mScan.find(id);
        if (saved == mScan.end()) { status(this, "Selection changed. Scan again. Nothing has moved."); return; }
        const bool folder = saved->second.folder;
        const auto* item = gInventory.getItem(row->getUUID());
        if ((!folder && !item) || (folder && !gInventory.getCategory(row->getUUID())))
        { status(this, "Selection changed. Scan again. Nothing has moved."); return; }
        plan.push_back(saved->second);
        current.emplace(id, folder ? state.snapshotFolder(row->getUUID()) : state.snapshot(item));
        LLSD entry;
        entry["id"] = row->getUUID();
        entry["fingerprint"] = saved->second.fingerprint;
        entry["folder"] = folder;
        for (const auto& child : saved->second.contents) entry["contents"].append(child);
        const auto add_row = [&entry](const LLUUID& object_id, const LLSD& display, const std::string& detail) {
            LLSD child;
            child["id"] = object_id;
            child["row"] = display;
            child["details"] = detail;
            entry["rows"].append(child);
        };
        if (folder)
        {
            add_row(row->getUUID(), folderRow(row->getUUID(), "MOVE WHOLE FOLDER TO TRASH"), "Folder: " + folderPath(row->getUUID()) + "\nID: " + id);
            for (const auto& child : saved->second.contents)
            {
                const LLUUID child_id(child);
                if (const auto* child_item = gInventory.getItem(child_id))
                    add_row(child_id, rowFor(child_item, "Included in folder move"), describe(child_item, true));
                else if (gInventory.getCategory(child_id))
                    add_row(child_id, folderRow(child_id, "Subfolder included in move"), "Folder: " + folderPath(child_id) + "\nID: " + child);
            }
        }
        else add_row(row->getUUID(), rowFor(item, "Move this item to Trash"), describe(item, true));
        key["entries"].append(entry);
    }
    if (!LLInventoryCleanupPlan::validate(plan, current))
    {
        status(this, "Selection changed, overlaps, exceeds 2,000 affected entries, or is no longer eligible. Scan and select again. Nothing has moved.");
        return;
    }
    key["trash"] = gInventory.findCategoryUUIDForType(LLFolderType::FT_TRASH);
    LLFloaterReg::showInstance("inventory_cleanup_review", key);
}

void LLFloaterInventoryCleanup::refreshProtected()
{
    auto* list = getChild<LLScrollListCtrl>("protected");
    list->deleteAllItems();
    const LLSD saved = gSavedPerAccountSettings.getLLSD(PROTECTED);
    for (const auto& id : llsd::inArray(saved))
    {
        LLSD row;
        row["value"] = id;
        row["columns"][0]["column"] = "folder";
        row["columns"][0]["value"] = folderPath(id.asUUID());
        list->addElement(row);
    }
}

void LLFloaterInventoryCleanup::protectFolders()
{
    LLSD saved = gSavedPerAccountSettings.getLLSD(PROTECTED);
    std::set<LLUUID> ids;
    for (const auto& id : llsd::inArray(saved)) ids.insert(id.asUUID());
    for (const auto* row : mItems->getAllSelected())
    {
        if (const auto* item = gInventory.getItem(row->getUUID())) ids.insert(item->getParentUUID());
        else if (gInventory.getCategory(row->getUUID())) ids.insert(row->getUUID());
    }
    saved = LLSD::emptyArray();
    for (const auto& id : ids) saved.append(id);
    gSavedPerAccountSettings.setLLSD(PROTECTED, saved);
    refreshProtected();
    scan();
}

void LLFloaterInventoryCleanup::unprotectFolders()
{
    std::set<LLUUID> remove;
    for (const auto* row : getChild<LLScrollListCtrl>("protected")->getAllSelected()) remove.insert(row->getUUID());
    LLSD saved = LLSD::emptyArray();
    const LLSD previous = gSavedPerAccountSettings.getLLSD(PROTECTED);
    for (const auto& id : llsd::inArray(previous)) if (!remove.count(id.asUUID())) saved.append(id);
    gSavedPerAccountSettings.setLLSD(PROTECTED, saved);
    refreshProtected();
    scan();
}

LLFloaterInventoryCleanupReview::LLFloaterInventoryCleanupReview(const LLSD& key) : LLFloater(key) {}

bool LLFloaterInventoryCleanupReview::postBuild()
{
    getChild<LLScrollListCtrl>("items")->setCommitCallback([this](LLUICtrl*, const LLSD&) {
        if (const auto* row = getChild<LLScrollListCtrl>("items")->getFirstSelected())
        {
            const auto detail = mDetails.find(row->getUUID().asString());
            if (detail != mDetails.end()) getChild<LLTextEditor>("details")->setText(detail->second);
        }
    });
    getChild<LLButton>("execute")->setClickedCallback([this](LLUICtrl*, const LLSD&) { execute(); });
    getChild<LLButton>("cancel")->setClickedCallback([this](LLUICtrl*, const LLSD&) { closeFloater(); });
    getChild<LLCheckBoxCtrl>("acknowledge")->setCommitCallback([this](LLUICtrl*, const LLSD&) {
        getChild<LLButton>("execute")->setEnabled(!mConsumed && getChild<LLCheckBoxCtrl>("acknowledge")->get());
    });
    return true;
}

void LLFloaterInventoryCleanupReview::onOpen(const LLSD& key)
{
    mPlan.clear();
    mDetails.clear();
    getChild<LLTextEditor>("details")->setText(std::string("Select a row to inspect its frozen item ID, asset ID, permissions, and full folder path."));
    auto* list = getChild<LLScrollListCtrl>("items");
    list->deleteAllItems();
    for (const auto& entry : llsd::inArray(key["entries"]))
    {
        Entry planned{entry["id"].asUUID().asString(), entry["fingerprint"].asString(), true};
        planned.folder = entry["folder"].asBoolean();
        for (const auto& id : llsd::inArray(entry["contents"])) planned.contents.push_back(id.asString());
        mPlan.push_back(std::move(planned));
        for (const auto& row : llsd::inArray(entry["rows"]))
        {
            list->addElement(row["row"]);
            mDetails.emplace(row["id"].asUUID().asString(), row["details"].asString());
        }
    }
    mTrash = key["trash"].asUUID();
    mConsumed = mPlan.empty() || mPlan.size() > LLInventoryCleanupPlan::MAX_ITEMS || mTrash.isNull();
    getChild<LLCheckBoxCtrl>("acknowledge")->set(false);
    getChild<LLButton>("execute")->setEnabled(false);
    const S32 folders = static_cast<S32>(std::count_if(mPlan.begin(), mPlan.end(), [](const Entry& entry) { return entry.folder; }));
    getChild<LLButton>("execute")->setLabel(llformat(folders == static_cast<S32>(mPlan.size()) ? "Move %d whole folders to Trash" : "Move %d selected items to Trash", static_cast<S32>(mPlan.size())));
    status(this, llformat("%d whole folders + %d individual items selected; %d total affected entries shown. Destination: My Inventory / Trash. Folder contents stay together.",
        folders, static_cast<S32>(mPlan.size()) - folders, list->getItemCount()));
}

void LLFloaterInventoryCleanupReview::execute()
{
    if (mConsumed || !getChild<LLCheckBoxCtrl>("acknowledge")->get()) return;
    // Consume authorization before any validation or observer callback can re-enter.
    mConsumed = true;
    getChild<LLButton>("execute")->setEnabled(false);
    getChild<LLCheckBoxCtrl>("acknowledge")->set(false);
    InventoryState state;
    std::map<std::string, Entry> current;
    for (const auto& entry : mPlan)
    {
        if (entry.folder) current.emplace(entry.id, state.snapshotFolder(LLUUID(entry.id)));
        else if (const auto* item = gInventory.getItem(LLUUID(entry.id))) current.emplace(entry.id, state.snapshot(item));
    }
    if (!state.complete || mTrash != gInventory.findCategoryUUIDForType(LLFolderType::FT_TRASH) ||
        !gInventory.getCategory(mTrash) || !LLInventoryCleanupPlan::validate(mPlan, current))
    {
        status(this, "Nothing moved. Inventory or protection changed. Close this review, Scan again, and review a new selection.");
        return;
    }
    // Dispatch only reviewed roots. Folder fingerprints include every descendant;
    // recheck membership and metadata immediately before each root move.
    S32 sent = 0;
    for (const auto& entry : mPlan)
    {
        const LLUUID id(entry.id);
        if (entry.folder)
        {
            const Entry fresh = state.snapshotFolder(id);
            if (!LLInventoryCleanupPlan::validate({entry}, {{entry.id, fresh}})) break;
            gInventory.changeCategoryParent(gInventory.getCategory(id), mTrash, true);
        }
        else
        {
            auto* item = gInventory.getItem(id);
            if (!item || state.snapshot(item).fingerprint != entry.fingerprint || !state.eligible(item)) break;
            gInventory.changeItemParent(item, mTrash, true);
        }
        ++sent;
    }
    status(this, llformat("Requested %d of %d reviewed folder/item moves to Trash (folders include their reviewed contents). Server processing is asynchronous; verify in Inventory. Nothing was permanently deleted.",
        sent, static_cast<S32>(mPlan.size())));
}
