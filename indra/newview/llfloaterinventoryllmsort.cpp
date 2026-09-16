#include "llviewerprecompiledheaders.h"
#include "llfloaterinventoryllmsort.h"
#include "llinventoryllmsort.h"
#include "llagent.h"
#include "llapp.h"
#include "llbufferstream.h"
#include "llbutton.h"
#include "llcombobox.h"
#include "llcoros.h"
#include "llfloaterreg.h"
#include "llfolderview.h"
#include "llfolderviewmodelinventory.h"
#include "lliconctrl.h"
#include "llinventorymodel.h"
#include "llinventorymodelbackgroundfetch.h"
#include "llinventorypanel.h"
#include "lllineeditor.h"
#include "llnotificationsutil.h"
#include "llscrollcontainer.h"
#include "llsdutil.h"
#include "lltextbox.h"
#include "lltimer.h"
#include "llviewercontrol.h"
#include "llviewerinventory.h"
#include "llwindow.h"

namespace
{
bool sameName(std::string a, std::string b)
{
    LLStringUtil::trim(a); LLStringUtil::trim(b);
    LLStringUtil::toLower(a); LLStringUtil::toLower(b);
    return a == b;
}
std::string folderPath(LLUUID id)
{
    std::string path;
    std::set<LLUUID> seen;
    while (id.notNull() && seen.insert(id).second)
    {
        const auto* cat = gInventory.getCategory(id);
        if (!cat) break;
        path = cat->getName() + (path.empty() ? "" : " / " + path);
        id = cat->getParentUUID();
    }
    return path;
}
}

LLFloaterInventoryLLMSort::LLFloaterInventoryLLMSort(const LLSD& key) : LLFloater(key) {}
LLFloaterInventoryLLMSort::~LLFloaterInventoryLLMSort() { cancelSort(); }

bool LLFloaterInventoryLLMSort::folderAllowed(const LLUUID& id)
{
    if (!gInventory.isInventoryUsable() || id.isNull()) return false;
    LLUUID current = id;
    std::set<LLUUID> seen;
    while (current.notNull() && seen.insert(current).second)
    {
        const auto* cat = gInventory.getCategory(current);
        if (!cat || cat->getOwnerID() != gAgent.getID()) return false;
        switch (cat->getPreferredType())
        {
        case LLFolderType::FT_TRASH: case LLFolderType::FT_CURRENT_OUTFIT:
        case LLFolderType::FT_MY_OUTFITS: case LLFolderType::FT_OUTFIT:
        case LLFolderType::FT_MARKETPLACE_LISTINGS: case LLFolderType::FT_MARKETPLACE_STOCK:
        case LLFolderType::FT_MARKETPLACE_VERSION: case LLFolderType::FT_INBOX:
        case LLFolderType::FT_FAVORITE: case LLFolderType::FT_CALLINGCARD:
            return false;
        default: break;
        }
        if (current == gInventory.getRootFolderID()) return true;
        current = cat->getParentUUID();
    }
    return false;
}

bool LLFloaterInventoryLLMSort::canSort(const LLUUID& id)
{
    if (const auto* cat = gInventory.getCategory(id))
        return cat->getPreferredType() == LLFolderType::FT_NONE && folderAllowed(id);
    const auto* item = gInventory.getItem(id);
    return item && item->isFinished() && !item->getIsLinkType() &&
        item->getPermissions().getOwner() == gAgent.getID() && folderAllowed(item->getParentUUID());
}

bool LLFloaterInventoryLLMSort::hasModel()
{
    const LLSD config = gSavedSettings.getLLSD("OpenAITranslateConfig");
    std::string endpoint = LLInventoryLLMSort::trim(config["endpoint"].asString());
    while (!endpoint.empty() && endpoint.back() == '/') endpoint.pop_back();
    return (endpoint.compare(0, 7, "http://") == 0 || endpoint.compare(0, 8, "https://") == 0) &&
        !LLInventoryLLMSort::trim(config["model"].asString()).empty();
}

void LLFloaterInventoryLLMSort::show(const std::vector<LLUUID>& ids)
{
    if (ids.empty() || ids.size() > LLInventoryLLMSort::MAX_ITEMS ||
        std::any_of(ids.begin(), ids.end(), [](const LLUUID& id) { return !canSort(id); }))
    {
        LLSD args;
        args["MESSAGE"] = "Select 1-200 items or regular folders in your inventory. Links, library items, "
            "system folders, Trash, outfit folders and Marketplace listings cannot be sorted.";
        LLNotificationsUtil::add("GenericAlert", args);
        return;
    }
    for (const auto& id : ids)
        for (const auto& other : ids)
            if (id != other && gInventory.getCategory(other) && gInventory.isObjectDescendentOf(id, other))
            {
                LLSD args;
                args["MESSAGE"] = "Select a folder or its contents, not both. Folders are sorted with their contents intact.";
                LLNotificationsUtil::add("GenericAlert", args);
                return;
            }
    LLSD key;
    for (const auto& id : ids) key["items"].append(id);
    auto* floater = LLFloaterReg::getTypedInstance<LLFloaterInventoryLLMSort>("inventory_llm_sort");
    floater->openFloater(key);
}

bool LLFloaterInventoryLLMSort::postBuild()
{
    getChild<LLButton>("change_root")->setClickedCallback([this](LLUICtrl*, const LLSD&) { chooseRoot(); });
    getChild<LLButton>("use_root")->setClickedCallback([this](LLUICtrl*, const LLSD&) { useRoot(); });
    getChild<LLButton>("cancel_root")->setClickedCallback([this](LLUICtrl*, const LLSD&) {
        if (mRoot.isNull()) closeFloater();
        else { getChildView("root_picker")->setVisible(false); getChildView("review")->setVisible(true); mDirty = true; }
    });
    getChild<LLButton>("sort")->setClickedCallback([this](LLUICtrl*, const LLSD&) { startSort(); });
    getChild<LLButton>("stop")->setClickedCallback([this](LLUICtrl*, const LLSD&) {
        cancelSort(); mDirty = true; status("Sorting stopped. Review finished suggestions or retry remaining items.");
    });
    getChild<LLButton>("close")->setClickedCallback([this](LLUICtrl*, const LLSD&) { closeFloater(); });
    getChild<LLButton>("model_settings")->setClickedCallback([](LLUICtrl*, const LLSD&) { LLFloaterReg::showInstance("prefs_translation"); });
    getChild<LLButton>("all")->setClickedCallback([this](LLUICtrl*, const LLSD&) { mAttention = false; mDirty = true; });
    getChild<LLButton>("attention")->setClickedCallback([this](LLUICtrl*, const LLSD&) { mAttention = true; mDirty = true; });
    auto* folders = getChild<LLInventoryPanel>("folders");
    folders->setFilterTypes(1ULL << LLInventoryType::IT_CATEGORY);
    folders->setShowFolderState(LLInventoryFilter::SHOW_ALL_FOLDERS);
    folders->setSelectCallback([this](const std::deque<LLFolderViewItem*>& items, bool) {
        const auto* model = items.empty() ? nullptr : dynamic_cast<LLFolderViewModelItemInventory*>(items.back()->getViewModelItem());
        const LLUUID id = model ? model->getUUID() : LLUUID::null;
        getChildView("use_root")->setEnabled(rootAllowed(id));
        getChild<LLTextBox>("selected_root")->setText(rootAllowed(id) ? folderPath(id) : "Choose a folder outside the folders being sorted.");
    });
    getChild<LLLineEditor>("folder_search")->setKeystrokeCallback([folders](LLLineEditor* editor, void*) {
        folders->setFilterSubString(editor->getText());
    }, nullptr);
    return true;
}

void LLFloaterInventoryLLMSort::onOpen(const LLSD& key)
{
    cancelSort();
    // Retire controls while their captured row indices still refer to the old list.
    getChild<LLPanel>("rows")->deleteAllChildren(); mPanels.clear();
    mRows.clear(); mCategories.clear(); mRoot.setNull();
    if (mAgent != gAgent.getID()) mLastRoot.setNull();
    mAgent = gAgent.getID(); mAttention = false; mCreating = false; mLoading = false;
    for (const auto& value : llsd::inArray(key["items"]))
    {
        const LLUUID id = value.asUUID();
        if (!canSort(id)) continue;
        const auto* object = gInventory.getObject(id);
        Row row; row.id = id; row.parent = object->getParentUUID(); row.name = object->getName();
        row.folder = gInventory.getCategory(id) != nullptr;
        mRows.push_back(row);
    }
    if (rootAllowed(mLastRoot)) setRoot(mLastRoot);
    else chooseRoot();
    renderRows();
    getChild<LLScrollContainer>("row_scroll")->goToTop();
}

void LLFloaterInventoryLLMSort::onClose(bool)
{
    cancelSort(); mLoading = false;
}

void LLFloaterInventoryLLMSort::cancelSort()
{
    ++mGeneration; mSorting = false; mAutoSort = false;
    auto request = mRequest; mRequest.reset();
    if (request) request->cancelSuspendedOperation();
}

void LLFloaterInventoryLLMSort::chooseRoot()
{
    if (mCreating) return;
    cancelSort(); mLoading = false; mDirty = true;
    getChildView("review")->setVisible(false);
    getChildView("root_picker")->setVisible(true);
    getChildView("use_root")->setEnabled(false);
    getChild<LLTextBox>("picker_count")->setText(llformat("%d selected items. Choose the folder whose direct subfolders are your categories.", (int)mRows.size()));
    if (mRoot.notNull()) getChild<LLInventoryPanel>("folders")->setSelection(mRoot, false);
}

void LLFloaterInventoryLLMSort::useRoot()
{
    auto selected = getChild<LLInventoryPanel>("folders")->getSelectedItems();
    if (selected.size() != 1) return;
    const auto* model = dynamic_cast<LLFolderViewModelItemInventory*>((*selected.begin())->getViewModelItem());
    if (model) setRoot(model->getUUID());
}

void LLFloaterInventoryLLMSort::setRoot(const LLUUID& id)
{
    if (!rootAllowed(id)) return;
    cancelSort();
    mRoot = id; mLastRoot = id; mRootPath = folderPath(mRoot); mCategories.clear();
    for (auto& row : mRows)
    {
        if (row.state == State::Moved || row.state == State::Skipped) continue;
        row.state = State::Waiting; row.destination.setNull(); row.folderName.clear();
        row.newName.clear(); row.reason.clear(); row.icon.clear();
    }
    getChildView("root_picker")->setVisible(false);
    getChildView("review")->setVisible(true);
    getChild<LLTextBox>("root_path")->setText(folderPath(mRoot));
    getChild<LLTextBox>("root_path")->setToolTip(folderPath(mRoot));
    mLoading = true; mLoadStarted = LLTimer::getTotalSeconds(); mDirty = true;
    mAutoSort = true;
    if (!gInventory.isCategoryComplete(mRoot)) LLInventoryModelBackgroundFetch::instance().scheduleFolderFetch(mRoot, true);
    status("Loading category folders…");
    loadCategories();
}

void LLFloaterInventoryLLMSort::loadCategories()
{
    if (!rootAllowed(mRoot)) { mLoading = false; mAutoSort = false; mDirty = true; status("Choose an available root outside the folders being sorted."); return; }
    if (!gInventory.isCategoryComplete(mRoot)) return;
    mCategories.clear();
    LLInventoryModel::cat_array_t* cats = nullptr;
    LLInventoryModel::item_array_t* items = nullptr;
    gInventory.getDirectDescendentsOf(mRoot, cats, items);
    if (cats) for (const auto& cat : *cats)
        if (folderAllowed(cat->getUUID()) && std::none_of(mRows.begin(), mRows.end(), [&](const Row& row) { return row.id == cat->getUUID(); }))
            mCategories.push_back({cat->getUUID(), cat->getName()});
    std::sort(mCategories.begin(), mCategories.end(), [](const Category& a, const Category& b) { return a.name < b.name; });
    mLoading = false; mDirty = true;
    std::string names;
    for (const auto& cat : mCategories) names += (names.empty() ? "" : " · ") + cat.name;
    getChild<LLTextBox>("categories")->setText(names.empty() ? "No subfolders yet. The model can suggest new categories." : "Existing categories: " + names);
    getChild<LLTextBox>("categories")->setToolTip(names);
    status("Ready. Click Sort items to request suggestions using your translation model.");
}

void LLFloaterInventoryLLMSort::status(const std::string& text)
{
    getChild<LLTextBox>("status")->setText(text);
}

void LLFloaterInventoryLLMSort::startSort()
{
    mAutoSort = false;
    if (mSorting || mCreating || mLoading || mRows.empty()) return;
    if (!rootAllowed(mRoot)) { status("Choose an available root outside the folders being sorted."); return; }
    if (!gInventory.isCategoryComplete(mRoot))
    {
        mLoading = true; mDirty = true; mLoadStarted = LLTimer::getTotalSeconds();
        LLInventoryModelBackgroundFetch::instance().scheduleFolderFetch(mRoot, true);
        status("Loading category folders. Click Sort items when loading finishes."); return;
    }
    // Retain the index-to-UUID mapping for the entire request sequence.
    loadCategories();
    if (mCategories.size() > LLInventoryLLMSort::MAX_CATEGORIES)
    { status("Choose a more specific root with at most 256 category folders."); return; }
    LLSD config = gSavedSettings.getLLSD("OpenAITranslateConfig");
    std::string endpoint = LLInventoryLLMSort::trim(config["endpoint"].asString());
    while (!endpoint.empty() && endpoint.back() == '/') endpoint.pop_back();
    if (!hasModel())
    { status("Set an endpoint and model in Translation settings > OpenAI-compatible, then try again."); return; }
    config["endpoint"] = endpoint;
    mSorting = true; mDirty = true; ++mGeneration;
    getChild<LLTextBox>("model")->setText("Model: " + config["model"].asString());
    getChild<LLTextBox>("model")->setToolTip("Uses the OpenAI-compatible translation connection: " + endpoint);
    LLCoros::instance().launch("InventoryLLMSort", [handle = getHandle(), generation = mGeneration, config] {
        sortCoro(handle, generation, config);
    });
}

void LLFloaterInventoryLLMSort::sortCoro(LLHandle<LLFloater> handle, U32 generation, LLSD config)
{
    auto get = [&]() -> LLFloaterInventoryLLMSort* {
        auto* self = dynamic_cast<LLFloaterInventoryLLMSort*>(handle.get());
        return self && self->mGeneration == generation && self->mAgent == gAgent.getID() && !LLApp::isQuitting() ? self : nullptr;
    };
    auto* self = get(); if (!self) return;
    std::vector<std::string> names;
    for (const auto& cat : self->mCategories) names.push_back(cat.name);
    const size_t count = self->mRows.size();
    for (size_t i = 0; i < count; ++i)
    {
        self = get(); if (!self) return;
        if (self->mRows[i].state != State::Waiting && self->mRows[i].state != State::Error) continue;
        if (!self->unchanged(self->mRows[i]))
        { self->mRows[i].state = State::Error; self->mRows[i].reason = "Item changed. Close and select it again."; continue; }
        self->status(llformat("Sorting item %d of %d…", (int)i + 1, (int)count));
        auto adapter = std::make_shared<LLCoreHttpUtil::HttpCoroutineAdapter>("InventoryLLMSort", LLCore::HttpRequest::DEFAULT_POLICY_ID);
        self->mRequest = adapter;
        auto request = std::make_shared<LLCore::HttpRequest>();
        auto options = std::make_shared<LLCore::HttpOptions>();
        options->setRetries(0); options->setTimeout(120);
        auto headers = std::make_shared<LLCore::HttpHeaders>();
        headers->append(HTTP_OUT_HEADER_CONTENT_TYPE, HTTP_CONTENT_JSON);
        headers->append(HTTP_OUT_HEADER_ACCEPT, HTTP_CONTENT_JSON);
        if (!config["id"].asString().empty()) headers->append(HTTP_OUT_HEADER_AUTHORIZATION, "Bearer " + config["id"].asString());
        LLCore::BufferArray::ptr_t buffer(new LLCore::BufferArray);
        {
            LLCore::BufferArrayStream out(buffer.get());
            out << LLInventoryLLMSort::request(config["model"].asString(), self->mRows[i].name, names);
        }
        // Never retain a floater or inventory pointer across the coroutine suspension.
        self = nullptr;
        const LLSD response = adapter->postRawAndSuspend(request, config["endpoint"].asString() + "/chat/completions", buffer, options, headers);
        self = get(); if (!self) return;
        self->mRequest.reset();
        auto& row = self->mRows[i];
        const auto http = LLCoreHttpUtil::HttpCoroutineAdapter::getStatusFromLLSD(response[LLCoreHttpUtil::HttpCoroutineAdapter::HTTP_RESULTS]);
        const auto& raw = response[LLCoreHttpUtil::HttpCoroutineAdapter::HTTP_RESULTS_RAW].asBinary();
        LLInventoryLLMSort::Suggestion suggestion;
        if (!http)
        {
            row.state = State::Error; row.reason = "Model request failed. Retry or choose a folder manually.";
            self->mSorting = false; self->mDirty = true;
            self->status("Could not reach the model or the request was rejected. Check Translation settings and retry remaining items.");
            return;
        }
        if (!LLInventoryLLMSort::parse(std::string(raw.begin(), raw.end()), names.size(), suggestion))
        { row.state = State::Error; row.reason = "Unusable model response. Retry or choose a folder."; }
        else
        {
            row.reason = suggestion.reason; row.icon = suggestion.icon;
            row.newName = suggestion.name;
            row.state = suggestion.decision == "existing" ? State::Ready : suggestion.decision == "new" ? State::NewFolder : State::Unsure;
            if (row.state == State::Ready)
            {
                row.destination = self->mCategories[suggestion.category].id;
                row.folderName = self->mCategories[suggestion.category].name;
            }
            else if (row.state == State::NewFolder)
                for (const auto& cat : self->mCategories) if (sameName(cat.name, row.newName))
                { row.state = State::Ready; row.destination = cat.id; row.folderName = cat.name; row.newName.clear(); break; }
        }
    }
    self = get(); if (!self) return;
    self->mSorting = false; self->mDirty = true;
    self->status("Review each suggestion. Nothing moves until you approve that item.");
}

bool LLFloaterInventoryLLMSort::rootAllowed(const LLUUID& id) const
{
    return folderAllowed(id) && std::none_of(mRows.begin(), mRows.end(), [&](const Row& row) {
        return row.folder && gInventory.isObjectDescendentOf(id, row.id);
    });
}

bool LLFloaterInventoryLLMSort::unchanged(const Row& row) const
{
    const auto* object = gInventory.getObject(row.id);
    return !LLApp::isQuitting() && mAgent == gAgent.getID() && rootAllowed(mRoot) && folderPath(mRoot) == mRootPath && canSort(row.id) && object &&
        row.folder == (gInventory.getCategory(row.id) != nullptr) &&
        object->getParentUUID() == row.parent && object->getName() == row.name;
}

void LLFloaterInventoryLLMSort::approve(size_t index)
{
    if (mSorting || mCreating || index >= mRows.size()) return;
    auto& row = mRows[index];
    if (row.state != State::Ready && row.state != State::NewFolder) return;
    if (!unchanged(row) || !folderAllowed(mRoot))
    { row.state = State::Error; row.reason = "Item or root changed. Close and select again."; mDirty = true; return; }
    if (row.state == State::Ready) { moveItem(index, row.destination); return; }
    if (index < mPanels.size() && mPanels[index])
        row.newName = LLInventoryLLMSort::trim(mPanels[index]->getChild<LLLineEditor>("new_name")->getText());
    if (!LLInventoryLLMSort::validFolderName(row.newName))
    { row.reason = "Use a single folder name (1-63 bytes), without slashes."; mDirty = true; return; }
    if (!gInventory.isCategoryComplete(mRoot))
    { status("Root folder is still updating. Wait a moment before creating a category."); return; }
    LLInventoryModel::cat_array_t* cats = nullptr;
    LLInventoryModel::item_array_t* items = nullptr;
    gInventory.getDirectDescendentsOf(mRoot, cats, items);
    std::vector<LLUUID> matches;
    if (cats) for (const auto& cat : *cats)
        if (sameName(cat->getName(), row.newName) && folderAllowed(cat->getUUID())) matches.push_back(cat->getUUID());
    if (matches.size() > 1)
    { row.state = State::Unsure; row.reason = "Multiple folders have this name. Choose one from the list."; mDirty = true; return; }
    if (matches.size() == 1) { moveItem(index, matches.front()); return; }
    mCreating = true; row.state = State::Creating; mDirty = true;
    const auto handle = getHandle();
    const U32 generation = mGeneration;
    const LLUUID root = mRoot;
    gInventory.createNewCategory(root, LLFolderType::FT_NONE, row.newName,
        [handle, generation, index, root](const LLUUID& id) {
            auto* self = dynamic_cast<LLFloaterInventoryLLMSort*>(handle.get());
            if (!self) return;
            if (self->mGeneration != generation || self->mRoot != root || self->mAgent != gAgent.getID()) return;
            self->mCreating = false;
            auto& row = self->mRows[index];
            if (id.isNull()) { row.state = State::NewFolder; row.reason = "Folder creation failed. Try again."; self->mDirty = true; return; }
            self->moveItem(index, id);
            const auto* cat = gInventory.getCategory(id);
            if (cat && folderAllowed(id) && cat->getParentUUID() == root)
            {
                self->mCategories.push_back({id, cat->getName()});
                for (auto& other : self->mRows)
                    if (other.state == State::NewFolder && sameName(other.newName, cat->getName()))
                    { other.state = State::Ready; other.destination = id; other.folderName = cat->getName(); other.newName.clear(); }
            }
            self->mDirty = true;
        });
}

void LLFloaterInventoryLLMSort::moveItem(size_t index, const LLUUID& destination)
{
    auto& row = mRows[index];
    const auto* cat = gInventory.getCategory(destination);
    if (!unchanged(row) || !cat || !folderAllowed(destination) || cat->getParentUUID() != mRoot ||
        (row.folder && gInventory.isObjectDescendentOf(destination, row.id)) ||
        (row.state == State::Ready && (cat->getUUID() != row.destination || cat->getName() != row.folderName)) ||
        ((row.state == State::NewFolder || row.state == State::Creating) && !sameName(cat->getName(), row.newName)))
    { row.state = State::Error; row.reason = "Item or destination changed. Review it again before moving."; mDirty = true; return; }
    row.destination = destination; row.folderName = cat->getName();
    const bool already = row.parent == destination;
    if (!already)
    {
        if (row.folder) gInventory.changeCategoryParent(gInventory.getCategory(row.id), destination, false);
        else gInventory.changeItemParent(gInventory.getItem(row.id), destination, false);
    }
    row.state = State::Moved; row.reason = already ? "Already in this folder" : "Moved to " + row.folderName;
    mDirty = true;
}

void LLFloaterInventoryLLMSort::renderRows()
{
    mDirty = false;
    auto* content = getChild<LLPanel>("rows");
    for (auto* panel : mPanels) if (panel) { content->removeChild(panel); delete panel; }
    mPanels.assign(mRows.size(), nullptr);
    size_t attention = 0, reviewed = 0, visible = 0, moved = 0;
    const auto needsAttention = [](State state) { return state == State::NewFolder || state == State::Unsure || state == State::Error; };
    const auto showRow = [&](State state) { return state != State::Moved && (!mAttention || needsAttention(state)); };
    for (const auto& row : mRows)
    {
        attention += needsAttention(row.state);
        reviewed += row.state == State::Moved || row.state == State::Skipped;
        moved += row.state == State::Moved;
        visible += showRow(row.state);
    }
    const S32 width = getChild<LLScrollContainer>("row_scroll")->getRect().getWidth() - 18;
    const S32 height = llmax(1, (S32)visible * 88);
    content->reshape(width, height);
    size_t n = 0;
    for (size_t i = 0; i < mRows.size(); ++i)
    {
        auto& row = mRows[i];
        if (!showRow(row.state)) continue;
        LLPanel::Params panel_params;
        auto* panel = LLUICtrlFactory::create<LLPanel>(panel_params);
        panel->buildFromFile("panel_inventory_llm_sort_row.xml");
        panel->reshape(width, 88);
        panel->setRect(LLRect(0, height - (S32)n * 88, width, height - (S32)(n + 1) * 88));
        ++n; content->addChild(panel); mPanels[i] = panel;
        panel->getChild<LLTextBox>("item_name")->setText(row.name);
        panel->getChild<LLTextBox>("item_name")->setToolTip(row.name + (row.folder ? "\nFolder — contents stay together" : "") + "\nFrom: " + folderPath(row.parent));
        panel->getChild<LLIconCtrl>("category_icon")->setValue(row.icon.empty() ? (row.folder ? "Inv_FolderClosed" : "Inv_Object") : "SortCategory_" + row.icon);
        const bool done = row.state == State::Moved || row.state == State::Skipped;
        const bool enabled = !mSorting && !mCreating && !done && !mLoading;
        auto* combo = panel->getChild<LLComboBox>("destination");
        combo->add("Choose folder…", "");
        for (size_t c = 0; c < mCategories.size(); ++c)
        {
            const auto& cat = mCategories[c];
            const bool duplicate = std::count_if(mCategories.begin(), mCategories.end(), [&](const Category& other) { return sameName(other.name, cat.name); }) > 1;
            combo->add(cat.name + (duplicate ? " [" + cat.id.asString().substr(0, 8) + "]" : ""), cat.id.asString());
        }
        if (done && row.destination.notNull() && !combo->valueExists(row.destination.asString()))
            combo->add(row.folderName, row.destination.asString());
        combo->add("+ New folder…", "new");
        combo->setValue(row.state == State::NewFolder || row.state == State::Creating ? LLSD("new") : LLSD(row.destination.isNull() ? "" : row.destination.asString()));
        combo->setEnabled(enabled);
        combo->setCommitCallback([this, i, combo](LLUICtrl*, const LLSD&) {
            auto& row = mRows[i]; const std::string value = combo->getValue().asString();
            row.destination.setNull(); row.folderName.clear();
            row.state = value == "new" ? State::NewFolder : State::Unsure;
            for (const auto& cat : mCategories) if (cat.id.asString() == value)
            { row.state = State::Ready; row.destination = cat.id; row.folderName = cat.name; break; }
            row.reason.clear(); mDirty = true;
        });
        auto* editor = panel->getChild<LLLineEditor>("new_name");
        editor->setText(row.newName); editor->setVisible(row.state == State::NewFolder || row.state == State::Creating);
        editor->setEnabled(enabled);
        editor->setCommitCallback([this, i, editor](LLUICtrl*, const LLSD&) { mRows[i].newName = editor->getText(); });
        editor->setKeystrokeCallback([this, i](LLLineEditor* field, void*) { mRows[i].newName = field->getText(); }, nullptr);
        std::string reason = row.reason;
        if (row.state == State::Waiting) reason = "Waiting for suggestion";
        if (row.state == State::NewFolder) reason = reason.empty() ? "New category under the selected root" : reason;
        if (row.state == State::Unsure && reason.empty()) reason = "Name is unclear. Choose a folder.";
        panel->getChild<LLTextBox>("reason")->setText(reason);
        panel->getChild<LLTextBox>("reason")->setToolTip(reason);
        panel->getChild<LLTextBox>("reason")->setColor(needsAttention(row.state) ? LLColor4(0.94f, 0.75f, 0.40f, 1) : LLColor4(0.65f, 0.69f, 0.72f, 1));
        auto* approve = panel->getChild<LLButton>("approve");
        approve->setImageColor(row.state == State::NewFolder ? LLColor4(0.85f, 0.66f, 0.33f, 1) : LLColor4(0.40f, 0.75f, 0.56f, 1));
        approve->setLabel(row.state == State::NewFolder ? "Create & Move" : row.state == State::Creating ? "Creating…" : row.state == State::Moved ? "Moved" : row.state == State::Skipped ? "Skipped" : "Approve");
        approve->setEnabled(enabled && (row.state == State::Ready || row.state == State::NewFolder));
        approve->setClickedCallback([this, i](LLUICtrl*, const LLSD&) { this->approve(i); });
        panel->getChild<LLButton>("skip")->setEnabled(enabled);
        panel->getChild<LLButton>("skip")->setClickedCallback([this, i](LLUICtrl*, const LLSD&) { mRows[i].state = State::Skipped; mRows[i].reason = "Skipped. Item left in its original folder."; mDirty = true; });
        panel->getChildView("new_badge")->setVisible(row.state == State::NewFolder || row.state == State::Creating);
    }
    getChild<LLButton>("all")->setLabel(llformat("All (%d)", (int)(mRows.size() - moved)));
    getChild<LLButton>("attention")->setLabel(llformat("Needs attention (%d)", (int)attention));
    getChild<LLButton>("all")->setToggleState(!mAttention);
    getChild<LLButton>("attention")->setToggleState(mAttention);
    getChild<LLTextBox>("count")->setText(llformat("%d of %d reviewed", (int)reviewed, (int)mRows.size()));
    getChildView("empty")->setVisible(visible == 0);
    getChild<LLTextBox>("empty")->setText(std::string(mAttention ? "No items need attention." : "No items left to review."));
    // Recursive control lookups also visit the hidden inventory picker. Do them
    // only when state changes, never on every frame of an idle review.
    const bool pending = std::any_of(mRows.begin(), mRows.end(), [](const Row& row) { return row.state == State::Waiting || row.state == State::Error; });
    getChildView("sort")->setEnabled(!mSorting && !mCreating && !mLoading && pending && mRoot.notNull());
    getChildView("stop")->setVisible(mSorting);
    getChildView("sort")->setVisible(!mSorting);
    getChildView("change_root")->setEnabled(!mCreating);
}

void LLFloaterInventoryLLMSort::draw()
{
    if (mLoading)
    {
        loadCategories();
        if (mLoading && LLTimer::getTotalSeconds() - mLoadStarted > 30)
        { mLoading = false; mAutoSort = false; mDirty = true; status("Folder loading timed out. Click Sort items to retry loading."); }
    }
    if (mAutoSort && !mLoading)
    {
        mAutoSort = false;
        startSort();
    }
    if (mDirty) renderRows();
    LLFloater::draw();
}

void LLFloaterInventoryLLMSort::reshape(S32 width, S32 height, bool called_from_parent)
{
    const bool resized = width != getRect().getWidth() || height != getRect().getHeight();
    LLFloater::reshape(width, height, called_from_parent);
    // Screen fitting can send the same dimensions every frame when the floater
    // is wider than the viewport. Preserve the existing rows in that case.
    if (resized) mDirty = true;
}
