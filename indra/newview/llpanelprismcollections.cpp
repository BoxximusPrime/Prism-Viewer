#include "llviewerprecompiledheaders.h"
#include "llpanelprismcollections.h"
#include "llprismcollections.h"

#include "llagentwearables.h"
#include "llappearancemgr.h"
#include "llbutton.h"
#include "llcheckboxctrl.h"
#include "llcombobox.h"
#include "llfloaterreg.h"
#include "llinventoryfunctions.h"
#include "llinventoryicon.h"
#include "llinspecttexture.h"
#include "llinventorymodel.h"
#include "llinventorymodelbackgroundfetch.h"
#include "lllineeditor.h"
#include "llnotificationsutil.h"
#include "llscrolllistctrl.h"
#include "llscrolllistitem.h"
#include "llscrolllistcell.h"
#include "llscrollcontainer.h"
#include "llthumbnailctrl.h"
#include "lltextbox.h"
#include "llviewerinventory.h"
#include "llwearableitemslist.h"

namespace PC = LLPrismCollections;
static LLPanelInjector<LLPanelPrismCollections> t_collections("prism_collections");

LLPanelPrismCollections::~LLPanelPrismCollections()
{
    gInventory.removeObserver(this);
}

bool LLPanelPrismCollections::postBuild()
{
    mCategories = getChild<LLComboBox>("categories");
    mSets = getChild<LLScrollListCtrl>("sets");
    mGallery = getChild<LLScrollContainer>("gallery");
    mGalleryContent = getChild<LLPanel>("gallery_content");
    getChild<LLButton>("gallery_mode")->setClickedCallback([this](LLUICtrl*, const LLSD&)
    {
        mGalleryMode = !mGalleryMode;
        mDirty = true;
    });
    getChild<LLButton>("set_photo")->setClickedCallback([this](LLUICtrl*, const LLSD&) { editPhoto(); });
    mCategories->setCommitCallback([this](LLUICtrl*, const LLSD&) { mSets->deselectAllItems(); mGallery->goToTop(); mDirty = true; });
    mSets->setCommitOnSelectionChange(true);
    mSets->setCommitCallback([this](LLUICtrl*, const LLSD&) { updateButtons(); });
    mSets->setDoubleClickCallback([this]()
    {
        if (mSets->getFirstSelected()) PC::wear(mCategories->getValue().asUUID(), mSets->getSelectedValue().asUUID());
    });
    getChild<LLButton>("new_category")->setClickedCallback([this](LLUICtrl*, const LLSD&) { nameCategory(false); });
    getChild<LLButton>("rename_category")->setClickedCallback([this](LLUICtrl*, const LLSD&) { nameCategory(true); });
    getChild<LLButton>("delete_category")->setClickedCallback([this](LLUICtrl*, const LLSD&) { deleteFolder(true); });
    getChild<LLButton>("new_set")->setClickedCallback([this](LLUICtrl*, const LLSD&) { editSet(true); });
    getChild<LLButton>("edit_set")->setClickedCallback([this](LLUICtrl*, const LLSD&) { editSet(false); });
    getChild<LLButton>("delete_set")->setClickedCallback([this](LLUICtrl*, const LLSD&) { deleteFolder(false); });
    getChild<LLButton>("wear_set")->setClickedCallback([this](LLUICtrl*, const LLSD&) { PC::wear(mCategories->getValue().asUUID(), mSets->getSelectedValue().asUUID()); mDirty = true; });
    getChild<LLButton>("remove_set")->setClickedCallback([this](LLUICtrl*, const LLSD&) { PC::wear(mCategories->getValue().asUUID(), LLUUID::null); mDirty = true; });
    gInventory.addObserver(this);
    return true;
}

void LLPanelPrismCollections::onOpen(const LLSD&) { mDirty = true; }

void LLPanelPrismCollections::draw()
{
    if (mDirty || (mRoot.isNull() && mRefresh.getElapsedTimeF32() > 1.f))
    {
        refresh();
        mDirty = false;
        mRefresh.reset();
    }
    const LLUUID active = PC::activeSet(mCategories->getValue().asUUID());
    for (auto* row : mSets->getAllData())
        row->getColumn(1)->setValue(row->getValue().asUUID() == active ? (PC::busy() ? "Working..." : "Active") : "");
    if (mGalleryMode)
    {
        layoutGallery();
        for (const auto& entry : mCards)
        {
            auto* category = gInventory.getCategory(entry.first);
            entry.second->getChild<LLButton>("select")->setToggleState(entry.first == mSets->getSelectedValue().asUUID());
            const std::string status = entry.first == active ? (PC::busy() ? "Working..." : "Active") :
                category && category->getThumbnailUUID().notNull() ? "" : "No photo";
            auto* label = entry.second->getChild<LLTextBox>("status");
            if (label->getText() != status) label->setText(status);
        }
    }
    getChild<LLTextBox>("status")->setValue(mRoot.isNull() ? "Preparing Prism inventory..." :
        PC::busy() ? "Updating collections. Please wait..." : "Stored as links in #Prism / Collections.");
    updateButtons();
    LLPanelAppearanceTab::draw();
}

void LLPanelPrismCollections::refresh()
{
    mRoot = PC::root();
    const LLUUID category = mCategories->getValue().asUUID();
    const LLUUID selected = mSets->getSelectedValue().asUUID();
    const S32 scroll = mSets->getScrollPos();
    mCategories->removeall();
    for (const LLUUID& id : PC::folders(mRoot))
        mCategories->add(gInventory.getCategory(id)->getName(), id);
    if (!mCategories->setCurrentByID(category)) mCategories->selectFirstItem();
    const LLUUID current = mCategories->getValue().asUUID();
    if (current.isNull()) mCategories->setLabel(std::string("No categories yet"));
    if (mRoot.notNull() && !gInventory.isCategoryComplete(mRoot)) LLInventoryModelBackgroundFetch::instance().start(mRoot);
    if (current.notNull() && !gInventory.isCategoryComplete(current)) LLInventoryModelBackgroundFetch::instance().start(current);
    const LLUUID active = PC::activeSet(current);
    mSets->deleteAllItems();
    std::string filter = getFilterSubString();
    LLStringUtil::toLower(filter);
    for (const LLUUID& id : PC::folders(current))
    {
        const std::string name = gInventory.getCategory(id)->getName();
        std::string lower = name;
        LLStringUtil::toLower(lower);
        if (!filter.empty() && lower.find(filter) == std::string::npos) continue;
        LLSD row;
        row["value"] = id;
        row["columns"][0]["column"] = "name";
        row["columns"][0]["value"] = name;
        row["columns"][1]["column"] = "status";
        row["columns"][1]["value"] = id == active ? (PC::busy() ? "Working..." : "Active") : "";
        mSets->addElement(row);
    }
    mSets->selectByID(selected);
    mSets->setScrollPos(scroll);
    mSets->setCommentText(current.isNull() ? "Create a category to get started." : "No sets. Create one from your worn items.");
    mSets->setVisible(!mGalleryMode || mSets->getItemCount() == 0);
    mGallery->setVisible(mGalleryMode && mSets->getItemCount() > 0);
    getChild<LLButton>("gallery_mode")->setToggleState(mGalleryMode);
    refreshGallery();
    getChild<LLTextBox>("status")->setValue(mRoot.isNull() ? "Preparing Prism inventory..." :
        PC::busy() ? "Updating collections. Please wait..." : "Stored as links in #Prism / Collections.");
}

void LLPanelPrismCollections::updateButtons()
{
    const bool ready = !PC::busy() && mRoot.notNull() && gInventory.isCategoryComplete(mRoot);
    const LLUUID category = mCategories->getValue().asUUID();
    const bool has_category = ready && PC::isCategory(category) && gInventory.isCategoryComplete(category);
    const bool has_set = has_category && mSets->getFirstSelected();
    getChild<LLButton>("new_category")->setEnabled(ready);
    for (const char* name : {"rename_category", "delete_category", "new_set"}) getChild<LLButton>(name)->setEnabled(has_category);
    for (const char* name : {"edit_set", "delete_set", "wear_set", "set_photo"}) getChild<LLButton>(name)->setEnabled(has_set);
    getChild<LLButton>("remove_set")->setEnabled(has_category && PC::activeSet(category).notNull());
}

void LLPanelPrismCollections::editPhoto()
{
    const LLUUID id = mSets->getSelectedValue().asUUID();
    auto* set = gInventory.getCategory(id);
    if (!PC::busy() && set && PC::isCategory(set->getParentUUID()))
        LLFloaterReg::showInstance("change_item_thumbnail", LLSD(id));
}

void LLPanelPrismCollections::refreshGallery()
{
    mCards.clear();
    mGalleryContent->deleteAllChildren();
    mGalleryWidth = 0;
    if (!mGalleryMode) return;
    for (auto* row : mSets->getAllData())
    {
        const LLUUID id = row->getValue().asUUID();
        auto* category = gInventory.getCategory(id);
        if (!category) continue;
        LLPanel::Params params;
        auto* card = LLUICtrlFactory::create<LLPanel>(params);
        card->buildFromFile("panel_prism_collection_card.xml");
        card->getChild<LLTextBox>("name")->setText(category->getName());
        card->getChild<LLThumbnailCtrl>("photo")->setValue(category->getThumbnailUUID());
        auto* button = card->getChild<LLButton>("select");
        button->setToolTip(category->getName());
        button->setClickedCallback([this, id](LLUICtrl*, const LLSD&)
        {
            mSets->selectByID(id);
            updateButtons();
        });
        mGalleryContent->addChild(card);
        mCards.emplace_back(id, card);
    }
    layoutGallery();
}

void LLPanelPrismCollections::layoutGallery()
{
    static LLUICachedControl<S32> scrollbar_size("UIScrollbarSize", 16);
    const S32 width = llmax(1, mGallery->getRect().getWidth() - scrollbar_size - 4);
    const S32 viewport_height = llmax(1, mGallery->getRect().getHeight() - 4);
    if (width == mGalleryWidth && viewport_height == mGalleryHeight) return;
    mGalleryWidth = width;
    mGalleryHeight = viewport_height;
    const S32 columns = llmax(1, (width + 8) / 136);
    const S32 rows = (static_cast<S32>(mCards.size()) + columns - 1) / columns;
    const S32 height = llmax(viewport_height, rows * 176);
    mGalleryContent->reshape(width, height);
    const S32 left = llmax(0, (width - (columns * 136 - 8)) / 2);
    for (S32 i = 0; i < static_cast<S32>(mCards.size()); ++i)
    {
        LLRect rect;
        rect.setLeftTopAndSize(left + (i % columns) * 136, height - (i / columns) * 176, 128, 168);
        mCards[i].second->setShape(rect);
    }
}

LLUUID LLPanelPrismCollections::setAt(S32 x, S32 y) const
{
    LLUUID id;
    S32 local_x, local_y;
    if (mGallery->getVisible())
    {
        localPointToOtherView(x, y, &local_x, &local_y, mGallery);
        if (mGallery->getContentWindowRect().pointInRect(local_x, local_y))
        {
            localPointToOtherView(x, y, &local_x, &local_y, mGalleryContent);
            for (const auto& entry : mCards)
                if (entry.second->getRect().pointInRect(local_x, local_y)) { id = entry.first; break; }
        }
    }
    else
    {
        localPointToOtherView(x, y, &local_x, &local_y, mSets);
        if (auto* row = mSets->hitItem(local_x, local_y)) id = row->getValue().asUUID();
    }
    return id;
}

bool LLPanelPrismCollections::handleDoubleClick(S32 x, S32 y, MASK mask)
{
    if (mGallery->getVisible())
    {
        const LLUUID id = setAt(x, y);
        if (id.notNull())
        {
            mSets->selectByID(id);
            PC::wear(mCategories->getValue().asUUID(), id);
            return true;
        }
    }
    return LLPanelAppearanceTab::handleDoubleClick(x, y, mask);
}

bool LLPanelPrismCollections::handleToolTip(S32 x, S32 y, MASK mask)
{
    auto* category = gInventory.getCategory(setAt(x, y));
    if (category && category->getThumbnailUUID().notNull())
    {
        S32 screen_x, screen_y;
        localPointToScreen(x, y, &screen_x, &screen_y);
        LLToolTip::Params p;
        p.message = category->getName();
        p.wrap = false;
        p.max_width = 256;
        p.pos = LLCoordGL(screen_x - 128, screen_y + 300);
        p.create_params = LLSD().with("thumbnail_id", category->getThumbnailUUID());
        p.create_callback = LLInspectTextureUtil::createInventoryToolTip;
        LLToolTipMgr::instance().show(p);
        return true;
    }
    return LLPanelAppearanceTab::handleToolTip(x, y, mask);
}

void LLPanelPrismCollections::nameCategory(bool rename)
{
    const LLUUID category = rename ? mCategories->getValue().asUUID() : LLUUID::null;
    if (rename && !PC::isCategory(category)) return;
    const LLUUID parent = mRoot;
    LLSD args;
    args["ACTION"] = rename ? "Rename category" : "New category";
    args["NAME"] = rename ? gInventory.getCategory(category)->getName() : "";
    LLNotificationsUtil::add("PrismCollectionCategoryName", args, LLSD(),
        [parent, category](const LLSD& notification, const LLSD& response)
        {
            if (LLNotificationsUtil::getSelectedOption(notification, response) != 0) return;
            std::string name = response["name"].asString();
            LLStringUtil::trim(name);
            if (PC::busy() || parent != PC::root() || !gInventory.isCategoryComplete(parent)) return;
            if (!PC::validName(parent, category, name)) { PC::error("Enter a short, unique category name without slashes or line breaks."); return; }
            if (category.notNull())
            {
                if (!PC::isCategory(category)) return;
                LLSD updates;
                updates["name"] = name;
                update_inventory_category(category, updates, nullptr);
            }
            else
            {
                PC::setWriting(true);
                gInventory.createNewCategory(parent, LLFolderType::FT_NONE, name, [](const LLUUID& id)
                {
                    PC::setWriting(false);
                    if (id.isNull()) PC::error("The category could not be created. Please try again.");
                });
            }
        });
}

void LLPanelPrismCollections::deleteFolder(bool category)
{
    const LLUUID id = category ? mCategories->getValue().asUUID() : mSets->getSelectedValue().asUUID();
    auto* folder = gInventory.getCategory(id);
    if (!folder || PC::busy()) return;
    LLSD args;
    args["NAME"] = folder->getName();
    LLNotificationsUtil::add("PrismCollectionDelete", args, LLSD(),
        [id](const LLSD& notification, const LLSD& response)
        {
            auto* folder = gInventory.getCategory(id);
            if (LLNotificationsUtil::getSelectedOption(notification, response) != 0 || PC::busy() || !folder) return;
            if (!PC::isCategory(id) && !PC::isCategory(folder->getParentUUID())) return;
            if (!get_is_category_and_children_removable(&gInventory, id, true))
            {
                PC::error("This folder contains protected or worn original items. Move those out in Inventory before deleting it.");
                return;
            }
            gInventory.removeCategory(id);
            if (folder->getParentUUID() == gInventory.findCategoryUUIDForType(LLFolderType::FT_TRASH)) PC::forget(id);
        });
}

void LLPanelPrismCollections::editSet(bool create)
{
    LLSD key;
    key["category"] = mCategories->getValue();
    key["set"] = create ? LLUUID::null : mSets->getSelectedValue().asUUID();
    // One editor at a time prevents two drafts from overwriting each other.
    auto* existing = LLFloaterReg::findInstance("prism_collection_editor");
    if (existing && existing->getVisible()) { existing->setFocus(true); return; }
    LLFloaterReg::showInstance("prism_collection_editor", key);
}

bool LLFloaterPrismCollection::postBuild()
{
    mItems = getChild<LLScrollListCtrl>("items");
    mItems->setRightMouseDownCallback([this](LLUICtrl*, S32 x, S32 y, MASK) { showItemMenu(x, y); });
    mItems->setCommitOnSelectionChange(true);
    mItems->setCommitCallback([this](LLUICtrl*, const LLSD&) { updateLayerButtons(); });
    mItems->setSortCallback([](S32, const LLScrollListItem* a, const LLScrollListItem* b)
    {
        auto rank = [](const LLScrollListItem* row)
        {
            const auto* item = gInventory.getItem(row->getValue().asUUID());
            if (!item) return 999;
            const auto type = item->getType();
            if (type == LLAssetType::AT_CLOTHING)
                return item->getWearableType() == LLWearableType::WT_TATTOO ? 0 : 100 + static_cast<S32>(item->getWearableType());
            if (type == LLAssetType::AT_OBJECT) return 200;
            if (type == LLAssetType::AT_BODYPART) return 300 + static_cast<S32>(item->getWearableType());
            return 999;
        };
        return rank(a) - rank(b);
    });
    getChild<LLButton>("set_photo")->setClickedCallback([this](LLUICtrl*, const LLSD&)
    {
        if (!mSaving && mSet.notNull()) LLFloaterReg::showInstance("change_item_thumbnail", LLSD(mSet));
    });
    getChild<LLButton>("refresh_worn")->setClickedCallback([this](LLUICtrl*, const LLSD&) { addWorn(); });
    getChild<LLButton>("move_up")->setClickedCallback([this](LLUICtrl*, const LLSD&) { moveItem(-1); });
    getChild<LLButton>("move_down")->setClickedCallback([this](LLUICtrl*, const LLSD&) { moveItem(1); });
    getChild<LLButton>("save")->setClickedCallback([this](LLUICtrl*, const LLSD&) { save(); });
    getChild<LLButton>("cancel")->setClickedCallback([this](LLUICtrl*, const LLSD&) { closeFloater(); });
    return true;
}

void LLFloaterPrismCollection::onOpen(const LLSD& key)
{
    if (mSaving) return;
    mCategory = key["category"].asUUID();
    mSet = key["set"].asUUID();
    getChild<LLButton>("set_photo")->setEnabled(mSet.notNull());
    auto* category = gInventory.getCategory(mCategory);
    if (!category || !PC::isCategory(mCategory)) { closeFloater(); return; }
    setTitle(mSet.isNull() ? "NEW COLLECTION SET" : "EDIT COLLECTION SET");
    getChild<LLTextBox>("category_name")->setText(category->getName());
    mItems->deleteAllItems();
    getChild<LLLineEditor>("set_name")->setText(std::string());
    getChild<LLCheckBoxCtrl>("activate")->setValue(false);
    if (mSet.notNull())
    {
        auto* folder = gInventory.getCategory(mSet);
        if (!folder || folder->getParentUUID() != mCategory) { closeFloater(); return; }
        if (!gInventory.isCategoryComplete(mSet))
        {
            LLInventoryModelBackgroundFetch::instance().start(mSet);
            PC::error("This set is still loading. Please open the editor again in a moment.");
            closeFloater();
            return;
        }
        getChild<LLLineEditor>("set_name")->setText(folder->getName());
        LLInventoryModel::cat_array_t* cats = nullptr;
        LLInventoryModel::item_array_t* items = nullptr;
        gInventory.getDirectDescendentsOf(mSet, cats, items);
        if ((cats && !cats->empty()) || (items && std::any_of(items->begin(), items->end(), [](const auto& item) { return item->getActualType() != LLAssetType::AT_LINK; })))
        {
            PC::error("This folder contains original items or subfolders. Move them out using Inventory; collection sets should contain item links only.");
            closeFloater();
            return;
        }
        if (items)
        {
            auto sorted = *items;
            std::stable_sort(sorted.begin(), sorted.end(), [](const auto& a, const auto& b) { return a->getActualDescription() < b->getActualDescription(); });
            for (const auto& link : sorted) addItem(link->getLinkedUUID(), true);
        }
    }
    addWorn();
    getChild<LLLineEditor>("set_name")->setFocus(true);
}

void LLFloaterPrismCollection::showItemMenu(S32 x, S32 y)
{
    if (mSaving) return;
    auto* row = mItems->hitItem(x, y);
    if (!row) return;
    const LLUUID id = row->getValue().asUUID();
    const bool included = row->getColumn(0)->getValue().asBoolean();
    mItems->selectByID(id);
    mItems->setFocus(true);
    updateLayerButtons();
    const auto handle = getHandle();
    const LLUUID category = mCategory, set = mSet;
    LLWearableItemsList::ContextMenu::instance().showForCollection(mItems, id, x, y, included, PC::validItem(id),
        [handle, category, set, id, included]()
        {
            auto* self = dynamic_cast<LLFloaterPrismCollection*>(handle.get());
            if (!self || !self->getVisible() || self->mSaving || self->mCategory != category || self->mSet != set) return;
            if (!included && !PC::validItem(id)) return;
            for (auto* item : self->mItems->getAllData())
                if (item->getValue().asUUID() == id) { item->getColumn(0)->setValue(!included); break; }
        });
}

void LLFloaterPrismCollection::addItem(const LLUUID& id, bool checked)
{
    auto* item = gInventory.getItem(id);
    const bool body_part = item && item->getType() == LLAssetType::AT_BODYPART;
    for (auto* row : mItems->getAllData())
    {
        if (row->getValue().asUUID() != id) continue;
        if (checked) row->getColumn(0)->setValue(true);
        return;
    }
    LLSD row;
    row["value"] = id;
    row["columns"][0]["column"] = "include";
    row["columns"][0]["type"] = "checkbox";
    row["columns"][0]["value"] = checked;
    if (body_part) row["columns"][0]["tool_tip"] = "Replaces the worn body part of this type. Stays worn when the set is removed.";
    row["columns"][1]["column"] = "icon";
    row["columns"][1]["type"] = "icon";
    row["columns"][1]["value"] = item ? LLInventoryIcon::getIconName(item->getType(), item->getInventoryType(), item->getFlags()) : LLInventoryIcon::getIconName(LLInventoryType::ICONNAME_UNKNOWN);
    row["columns"][2]["column"] = "name";
    row["columns"][2]["value"] = item ? item->getName() : "Missing item (uncheck to remove)";
    row["columns"][3]["column"] = "type";
    row["columns"][3]["value"] = !item ? "Unavailable" : item->getType() == LLAssetType::AT_CLOTHING || body_part ?
        LLWearableType::getInstance()->getTypeLabel(item->getWearableType()) : "Attachment";
    row["columns"][1]["tool_tip"] = row["columns"][3]["value"];
    row["columns"][4]["column"] = "status";
    row["columns"][4]["value"] = !PC::validItem(id) ? "Unavailable" : get_is_item_worn(id) ? "Worn" : "Inventory";
    mItems->addElement(row);
    // Stable grouping preserves the saved/current layer order within each clothing type.
    mItems->sortOnce(3, true);
    updateLayerButtons();
}

void LLFloaterPrismCollection::addWorn()
{
    if (mSaving) return;
    // Seed clothing in its current outermost-to-innermost layer order.
    for (S32 t = 0; t < LLWearableType::WT_COUNT; ++t)
    {
        auto type = static_cast<LLWearableType::EType>(t);
        for (S32 i = static_cast<S32>(gAgentWearables.getWearableCount(type)) - 1; i >= 0; --i)
        {
            const LLUUID id = gAgentWearables.getWearableItemID(type, i);
            if (PC::validItem(id)) addItem(id, false);
        }
    }
    LLInventoryModel::cat_array_t cats;
    LLInventoryModel::item_array_t items;
    gInventory.collectDescendents(LLAppearanceMgr::instance().getCOF(), cats, items, false);
    for (const auto& item : items)
        if (PC::validItem(item->getLinkedUUID()) && get_is_item_worn(item)) addItem(item->getLinkedUUID(), false);
    updateLayerButtons();
}

bool LLFloaterPrismCollection::canMoveLayer(S32 direction) const
{
    const auto rows = mItems->getAllData();
    const S32 index = mItems->getFirstSelectedIndex();
    const S32 next = index + direction;
    if (mSaving || index < 0 || next < 0 || next >= static_cast<S32>(rows.size())) return false;
    const auto* item = gInventory.getItem(rows[index]->getValue().asUUID());
    const auto* other = gInventory.getItem(rows[next]->getValue().asUUID());
    return item && other && item->getType() == LLAssetType::AT_CLOTHING &&
        other->getType() == LLAssetType::AT_CLOTHING && item->getWearableType() == other->getWearableType();
}

void LLFloaterPrismCollection::updateLayerButtons()
{
    getChild<LLButton>("move_up")->setEnabled(canMoveLayer(-1));
    getChild<LLButton>("move_down")->setEnabled(canMoveLayer(1));
}

void LLFloaterPrismCollection::moveItem(S32 direction)
{
    if (!canMoveLayer(direction)) return;
    const S32 index = mItems->getFirstSelectedIndex();
    if (direction < 0) mItems->swapWithPrevious(index);
    else mItems->swapWithNext(index);
    updateLayerButtons();
}

bool LLFloaterPrismCollection::handleDragAndDrop(S32 x, S32 y, MASK mask, bool drop, EDragAndDropType type,
                                               void* data, EAcceptance* accept, std::string& tooltip)
{
    *accept = ACCEPT_NO;
    if (mSaving || (type != DAD_CLOTHING && type != DAD_BODYPART && type != DAD_OBJECT && type != DAD_LINK) || !data) return true;
    auto* item = static_cast<LLInventoryItem*>(data);
    if (!PC::validItem(item->getLinkedUUID()))
    {
        tooltip = "Drop clothing layers, attachments, or body parts from your Inventory.";
        return true;
    }
    *accept = ACCEPT_YES_COPY_MULTI;
    tooltip = "Include this item in the set (creates an inventory link).";
    if (drop) addItem(item->getLinkedUUID(), true);
    return true;
}

void LLFloaterPrismCollection::save()
{
    if (mSaving || !PC::isCategory(mCategory)) return;
    if (PC::busy()) { PC::error("Please wait for the current set to finish applying before saving."); return; }
    if (!gInventory.isCategoryComplete(mCategory)) { PC::error("The category is still loading. Please try again in a moment."); return; }
    std::string name = getChild<LLLineEditor>("set_name")->getText();
    LLStringUtil::trim(name);
    if (!PC::validName(mCategory, mSet, name)) { PC::error("Enter a short, unique set name without slashes or line breaks."); return; }
    uuid_vec_t items;
    for (auto* row : mItems->getAllData())
    {
        if (!row->getColumn(0)->getValue().asBoolean()) continue;
        const LLUUID id = row->getValue().asUUID();
        if (!PC::validItem(id)) { PC::error("A checked item is unavailable. Uncheck it or restore it in Inventory before saving."); return; }
        items.push_back(id);
    }
    if (items.empty()) { PC::error("Check at least one item to include in this set."); return; }
    if (!PC::validBodyParts(items)) { PC::error("Include only one shape, skin, pair of eyes, and system hair in each set."); return; }
    mSaving = true;
    PC::setWriting(true);
    getChild<LLButton>("save")->setEnabled(false);
    getChild<LLLineEditor>("set_name")->setEnabled(false);
    getChild<LLCheckBoxCtrl>("activate")->setEnabled(false);
    mItems->setEnabled(false);
    if (mSet.isNull())
    {
        const auto handle = getHandle();
        gInventory.createNewCategory(mCategory, LLFolderType::FT_NONE, name,
            [handle, name, items](const LLUUID& id)
            {
                auto* self = dynamic_cast<LLFloaterPrismCollection*>(handle.get());
                if (!self) return;
                if (id.isNull())
                {
                    PC::setWriting(false);
                    self->mSaving = false;
                    self->getChild<LLButton>("save")->setEnabled(true);
                    self->getChild<LLLineEditor>("set_name")->setEnabled(true);
                    self->getChild<LLCheckBoxCtrl>("activate")->setEnabled(true);
                    self->mItems->setEnabled(true);
                    PC::error("The set folder could not be created. Please try again.");
                    return;
                }
                self->mSet = id;
                self->saveLinks(id, name, items);
            });
    }
    else saveLinks(mSet, name, items);
}

void LLFloaterPrismCollection::saveLinks(const LLUUID& folder, const std::string& name, const uuid_vec_t& desired)
{
    const auto handle = getHandle();
    auto finish = [handle](bool success)
    {
        PC::setWriting(false);
        auto* self = dynamic_cast<LLFloaterPrismCollection*>(handle.get());
        if (!self) return;
        self->mSaving = false;
        self->mItems->setEnabled(true);
        self->getChild<LLButton>("save")->setEnabled(true);
        self->getChild<LLLineEditor>("set_name")->setEnabled(true);
        self->getChild<LLCheckBoxCtrl>("activate")->setEnabled(true);
        if (success)
        {
            if (self->getChild<LLCheckBoxCtrl>("activate")->getValue().asBoolean()) PC::wear(self->mCategory, self->mSet);
            self->closeFloater();
        }
    };
    auto* category = gInventory.getCategory(folder);
    if (!category || category->getParentUUID() != mCategory || !PC::isCategory(mCategory))
    {
        PC::error("The set folder was moved or deleted. Your original items are untouched.");
        finish(false);
        return;
    }
    LLInventoryModel::cat_array_t* cats = nullptr;
    LLInventoryModel::item_array_t* items = nullptr;
    gInventory.getDirectDescendentsOf(folder, cats, items);
    std::map<LLUUID, LLUUID> existing;
    uuid_vec_t old_links;
    if (items) for (const auto& item : *items)
    {
        if (item->getActualType() == LLAssetType::AT_LINK)
        {
            existing[item->getLinkedUUID()] = item->getUUID();
            old_links.push_back(item->getUUID());
        }
    }
    LLInventoryObject::const_object_list_t missing;
    for (const LLUUID& id : desired)
        if (!existing.count(id)) missing.push_back(gInventory.getItem(id));
    const LLUUID parent = mCategory;
    auto commit = [folder, parent, name, desired, old_links, finish]()
    {
        auto* cat = gInventory.getCategory(folder);
        if (!cat || cat->getParentUUID() != parent || !PC::isCategory(parent)) { finish(false); return; }
        LLInventoryModel::cat_array_t* cats = nullptr;
        LLInventoryModel::item_array_t* items = nullptr;
        gInventory.getDirectDescendentsOf(folder, cats, items);
        std::map<LLUUID, LLUUID> links;
        if (items) for (const auto& item : *items)
            if (item->getActualType() == LLAssetType::AT_LINK) links[item->getLinkedUUID()] = item->getUUID();
        for (const LLUUID& id : desired)
            if (!links.count(id))
            {
                PC::error("Some links could not be saved. Previous links were kept. Please try Save again.");
                finish(false);
                return;
            }
        LLPointer<LLInventoryCallback> saved = new LLBoostFuncInventoryCallback([](const LLUUID&) {},
            [folder, name, desired, finish]()
            {
                uuid_vec_t actual;
                std::string message;
                auto* cat = gInventory.getCategory(folder);
                const bool success = cat && cat->getName() == name && PC::readSet(folder, actual, message) && actual == desired;
                if (!success) PC::error("The server did not confirm all set changes. Please check the set and try Save again.");
                finish(success);
            });
        // Confirm additions before removing old links; wait for metadata/removal replies before wearing.
        for (S32 i = 0; i < desired.size(); ++i)
        {
            LLSD updates;
            updates["desc"] = llformat("prism:%04d", i);
            update_inventory_item(links[desired[i]], updates, saved);
        }
        for (const LLUUID& id : old_links)
        {
            auto* item = gInventory.getItem(id);
            if (item && item->getParentUUID() == folder &&
                (std::find(desired.begin(), desired.end(), item->getLinkedUUID()) == desired.end() || links[item->getLinkedUUID()] != id))
                remove_inventory_item(id, saved);
        }
        LLSD updates;
        updates["name"] = name;
        update_inventory_category(folder, updates, saved);
    };
    if (missing.empty()) commit();
    else link_inventory_array(folder, missing, new LLBoostFuncInventoryCallback([](const LLUUID&) {}, commit));
}
