/**
 * @file llfloaterareasearch.cpp
 * @brief Area search with Boolean and fuzzy name/description matching.
 */
#include "llviewerprecompiledheaders.h"

#include "llfloaterareasearch.h"

#include "llagent.h"
#include "llavatarname.h"
#include "llcheckboxctrl.h"
#include "llfiltereditor.h"
#include "llfloateravatarpicker.h"
#include "llfloaterreg.h"
#include "llfocusmgr.h"
#include "llscrolllistctrl.h"
#include "llscrolllistitem.h"
#include "llspinctrl.h"
#include "lltextbox.h"
#include "lltoolpie.h"
#include "llui.h"
#include "llviewerobject.h"
#include "llviewerobjectlist.h"
#include "llviewerregion.h"
#include "message.h"

#include <algorithm>
#include <set>

namespace
{
std::u32string searchText(const std::string& text)
{
    const LLWString wide = utf8str_to_wstring(utf8str_tolower(text));
    return std::u32string(wide.begin(), wide.end());
}
constexpr F64 REQUEST_TIMEOUT = 30.;
constexpr U32 MAX_ATTEMPTS = 3;
constexpr U32 MAX_OBJECTS_PER_PACKET = 254;
// Firestorm's per-region request window: refill after roughly half the replies arrive.
constexpr U32 MAX_REQUESTS_PER_REGION = 762;
constexpr U32 REFILL_REQUESTS_PER_REGION = 383;

void sendPropertyRequests(LLViewerRegion* region, const std::vector<LLViewerObject*>& objects)
{
    LLMessageSystem* msg = gMessageSystem;
    for (bool select : {true, false})
    {
        U32 count = 0;
        for (LLViewerObject* object : objects)
        {
            // Leave the user's existing simulator selection intact.
            if (!select && object->isSelected()) continue;
            if (!count)
            {
                msg->newMessageFast(select ? _PREHASH_ObjectSelect : _PREHASH_ObjectDeselect);
                msg->nextBlockFast(_PREHASH_AgentData);
                msg->addUUIDFast(_PREHASH_AgentID, gAgent.getID());
                msg->addUUIDFast(_PREHASH_SessionID, gAgent.getSessionID());
            }
            msg->nextBlockFast(_PREHASH_ObjectData);
            msg->addU32Fast(_PREHASH_ObjectLocalID, object->getLocalID());
            if (++count >= MAX_OBJECTS_PER_PACKET || msg->isSendFull(NULL))
            {
                msg->sendReliable(region->getHost());
                count = 0;
            }
        }
        if (count) msg->sendReliable(region->getHost());
    }
}
}

LLFloaterAreaSearch::LLFloaterAreaSearch(const LLSD& key) : LLFloater(key) {}

bool LLFloaterAreaSearch::postBuild()
{
    mObjects = getChild<LLScrollListCtrl>("objects");
    mSearch = getChild<LLFilterEditor>("query");
    mStatus = getChild<LLTextBox>("status");
    mObjects->sortByColumn("distance", true);
    mObjects->setAlternateSort();
    mObjects->setMouseEnterCallback([this](LLUICtrl*, const LLSD&) { mMouseOverList = true; });
    mObjects->setMouseLeaveCallback([this](LLUICtrl*, const LLSD&) { mMouseOverList = false; });
    mSearch->setCommitCallback([this](LLUICtrl*, const LLSD&) { filterChanged(); });
    for (const char* filter : {"fuzzy", "payable", "scripted", "for_sale", "radius"})
    {
        getChild<LLUICtrl>(filter)->setCommitCallback([this](LLUICtrl*, const LLSD&)
        {
            scan();
            rebuildList();
        });
    }
    getChild<LLUICtrl>("mine")->setCommitCallback([this](LLUICtrl*, const LLSD&)
    {
        if (getChild<LLCheckBoxCtrl>("mine")->get()) setOwner(LLUUID::null);
        else rebuildList();
    });
    getChild<LLUICtrl>("choose_owner")->setCommitCallback([this](LLUICtrl*, const LLSD&) { chooseOwner(); });
    getChild<LLUICtrl>("clear_owner")->setCommitCallback([this](LLUICtrl*, const LLSD&) { setOwner(LLUUID::null); });
    getChild<LLUICtrl>("refresh")->setCommitCallback([this](LLUICtrl*, const LLSD&) { refresh(); });
    return true;
}

void LLFloaterAreaSearch::onOpen(const LLSD& key)
{
    refresh();
}

void LLFloaterAreaSearch::onClose(bool app_quitting)
{
    mMouseOverList = false;
    mEntries.clear();
    mObjects->deleteAllItems();
}

void LLFloaterAreaSearch::refresh()
{
    mEntries.clear();
    mRegionID = gAgent.getRegion() ? gAgent.getRegion()->getRegionID() : LLUUID::null;
    scan();
    filterChanged();
    mScanTimer.reset();
    mRequestTimer.reset();
}

bool LLFloaterAreaSearch::inRange(LLViewerObject* object) const
{
    return gAgent.getRegion() && object && !object->isDead() && !object->isOrphaned() && object->getRegion()
        && !object->isAvatar() && !object->isAttachment()
        && object->getRootEdit() == object
        && (object->getPCode() == LL_PCODE_VOLUME || object->getPCode() == LL_PCODE_LEGACY_TREE
            || object->getPCode() == LL_PCODE_LEGACY_GRASS)
        && (object->getPositionGlobal() - gAgent.getPositionGlobal()).length()
            <= mRadius;
}

void LLFloaterAreaSearch::scan()
{
    mRadius = getChild<LLSpinCtrl>("radius")->get();
    std::set<LLUUID> seen;
    if (gAgent.getRegion())
    {
        for (S32 i = 0; i < gObjectList.getNumObjects(); ++i)
        {
            LLViewerObject* object = gObjectList.getObject(i);
            if (!inRange(object)) continue;
            const LLUUID& id = object->getID();
            seen.insert(id);
            Entry& entry = mEntries[id];
            entry.distance = (F32)(object->getPositionGlobal() - gAgent.getPositionGlobal()).length();
        }
    }
    for (auto it = mEntries.begin(); it != mEntries.end();)
    {
        if (!seen.count(it->first)) it = mEntries.erase(it);
        else ++it;
    }
    mRequestPending = true;
}

void LLFloaterAreaSearch::requestProperties()
{
    if (!gAgent.getRegion() || !gMessageSystem) return;
    const F64 now = LLFrameTimer::getTotalSeconds();
    std::map<LLViewerRegion*, U32> in_flight;
    std::map<LLViewerRegion*, std::vector<std::pair<LLViewerObject*, Entry*>>> pending;
    for (auto& [id, entry] : mEntries)
    {
        if (entry.ready) continue;
        LLViewerObject* object = gObjectList.findObject(id);
        if (!inRange(object) || !object->getRegion()->isAlive()) continue;
        LLViewerRegion* region = object->getRegion();
        if (entry.attempts && now - entry.requestedAt < REQUEST_TIMEOUT) ++in_flight[region];
        else if (entry.attempts < MAX_ATTEMPTS) pending[region].emplace_back(object, &entry);
    }
    for (auto& [region, entries] : pending)
    {
        U32& outstanding = in_flight[region];
        if (outstanding > REFILL_REQUESTS_PER_REGION) continue;
        // Nearest objects arrive first, without one slow region blocking its neighbors.
        std::sort(entries.begin(), entries.end(), [](const auto& a, const auto& b)
        {
            return a.second->distance < b.second->distance;
        });
        std::vector<LLViewerObject*> objects;
        for (auto& [object, entry] : entries)
        {
            if (outstanding >= MAX_REQUESTS_PER_REGION) break;
            entry->requestedAt = now;
            ++entry->attempts;
            ++outstanding;
            objects.push_back(object);
        }
        sendPropertyRequests(region, objects);
    }
}

void LLFloaterAreaSearch::filterChanged()
{
    mQuery.parse(searchText(mSearch->getText()));
    rebuildList();
}

void LLFloaterAreaSearch::chooseOwner()
{
    LLFloaterAvatarPicker* picker = LLFloaterAvatarPicker::show(
        [handle = getHandle()](const uuid_vec_t& ids, const std::vector<LLAvatarName>& names)
        {
            auto* floater = static_cast<LLFloaterAreaSearch*>(handle.get());
            if (!floater || ids.empty() || ids.front().isNull()) return;
            floater->getChild<LLCheckBoxCtrl>("mine")->set(false);
            floater->setOwner(ids.front(), names.empty() ? "" : names.front().getCompleteName());
        }, false, true, false, getName(), getChild<LLUICtrl>("choose_owner"));
    if (picker) addDependentFloater(picker);
}

void LLFloaterAreaSearch::setOwner(const LLUUID& id, const std::string& name)
{
    mOwnerID = id;
    getChild<LLTextBox>("owner_name")->setText(id.isNull() ? getString("no_owner_selected")
        : name.empty() ? id.asString() : name);
    getChild<LLUICtrl>("clear_owner")->setEnabled(id.notNull());
    rebuildList();
}

void LLFloaterAreaSearch::rebuildList()
{
    const LLUUID selected = mObjects->getCurrentID();
    const S32 scroll = mObjects->getScrollPos();
    mObjects->deleteAllItems();
    const bool fuzzy = getChild<LLCheckBoxCtrl>("fuzzy")->get();
    const bool payable = getChild<LLCheckBoxCtrl>("payable")->get();
    const bool scripted = getChild<LLCheckBoxCtrl>("scripted")->get();
    const bool for_sale = getChild<LLCheckBoxCtrl>("for_sale")->get();
    const bool mine = getChild<LLCheckBoxCtrl>("mine")->get();
    const bool has_query = mSearch->getText().find_first_not_of(" \t\r\n") != std::string::npos;
    const F64 now = LLFrameTimer::getTotalSeconds();
    S32 loading = 0, unavailable = 0;
    for (const auto& [id, entry] : mEntries)
    {
        const bool failed = !entry.ready && entry.attempts == MAX_ATTEMPTS
            && now - entry.requestedAt >= REQUEST_TIMEOUT;
        if (!entry.ready) { if (failed) ++unavailable; else ++loading; }
        LLViewerObject* object = gObjectList.findObject(id);
        if (!inRange(object) || !mQuery.valid()
            || (payable && !object->flagTakesMoney())
            || (scripted && !object->flagScripted())
            || (mine && !object->permYouOwner())
            || (mOwnerID.notNull() && (!entry.ready || entry.ownerID != mOwnerID))
            || (for_sale && (!entry.ready || !entry.forSale))
            || (has_query && !entry.ready)
            || !mQuery.matches(entry.searchName, entry.searchDescription, fuzzy)) continue;

        LLSD row;
        row["id"] = id;
        row["columns"][0]["column"] = "distance";
        row["columns"][0]["value"] = llformat("%.1f", entry.distance);
        row["columns"][0]["alt_value"] = llformat("%07.1f", entry.distance);
        row["columns"][1]["column"] = "name";
        row["columns"][1]["value"] = entry.ready
            ? (entry.name.empty() ? getString("unnamed") : entry.name)
            : getString(failed ? "unavailable" : "loading");
        row["columns"][2]["column"] = "description";
        row["columns"][2]["value"] = entry.description;
        std::string flags;
        if (object->flagTakesMoney()) flags += getString("flag_payable") + " ";
        if (object->flagScripted()) flags += getString("flag_scripted") + " ";
        if (entry.ready && entry.forSale) flags += getString("flag_sale");
        row["columns"][3]["column"] = "flags";
        row["columns"][3]["value"] = flags;
        mObjects->addElement(row);
    }
    mObjects->updateSort();
    mObjects->selectByID(selected);
    mObjects->setScrollPos(scroll);
    LLStringUtil::format_map_t args;
    args["[SHOWN]"] = llformat("%d", mObjects->getItemCount());
    args["[TOTAL]"] = llformat("%d", (S32)mEntries.size());
    args["[LOADING]"] = llformat("%d", loading);
    args["[UNAVAILABLE]"] = llformat("%d", unavailable);
    mStatus->setText(!mQuery.valid() ? getString("invalid_query")
        : !gAgent.getRegion() ? getString("not_connected") : getString("status_count", args));
}

void LLFloaterAreaSearch::draw()
{
    if (isShown())
    {
        const LLUUID region = gAgent.getRegion() ? gAgent.getRegion()->getRegionID() : LLUUID::null;
        if (region != mRegionID) refresh();
        if (mScanTimer.getElapsedTimeF32() >= 1.f)
        {
            scan();
            rebuildList();
            mScanTimer.reset();
        }
        if (mRequestPending || mRequestTimer.getElapsedTimeF32() >= 1.f)
        {
            mRequestPending = false;
            requestProperties();
            mRequestTimer.reset();
        }
    }
    LLFloater::draw();
}

void LLFloaterAreaSearch::processObjectProperties(const LLUUID& id, const LLUUID& owner_id, const std::string& name,
                                                  const std::string& description, bool for_sale)
{
    auto* floater = LLFloaterReg::findTypedInstance<LLFloaterAreaSearch>("area_search");
    if (!floater || !floater->getVisible()) return;
    auto found = floater->mEntries.find(id);
    if (found == floater->mEntries.end()) return;
    Entry& entry = found->second;
    entry.ownerID = owner_id;
    entry.name = name;
    entry.description = description;
    entry.searchName = searchText(name);
    entry.searchDescription = searchText(description);
    entry.forSale = for_sale;
    entry.ready = true;
    floater->mRequestPending = true;
}

LLViewerObject* LLFloaterAreaSearch::getHoveredObject()
{
    auto* floater = LLFloaterReg::findTypedInstance<LLFloaterAreaSearch>("area_search");
    if (!floater || !floater->isShown() || !floater->mMouseOverList
        || !gFocusMgr.getAppHasFocus()) return nullptr;
    S32 x, y;
    LLUI::getInstance()->getMousePositionLocal(floater->mObjects, &x, &y);
    LLScrollListItem* row = floater->mObjects->hitItem(x, y);
    LLViewerObject* object = row ? gObjectList.findObject(row->getUUID()) : nullptr;
    return floater->inRange(object) ? object : nullptr;
}

bool LLFloaterAreaSearch::handleRightMouseDown(S32 x, S32 y, MASK mask)
{
    S32 list_x, list_y;
    localPointToOtherView(x, y, &list_x, &list_y, mObjects);
    LLScrollListItem* row = mObjects->hitItem(list_x, list_y);
    LLViewerObject* object = row ? gObjectList.findObject(row->getUUID()) : nullptr;
    if (inRange(object))
    {
        mObjects->selectByID(object->getID());
        S32 screen_x, screen_y;
        localPointToScreen(x, y, &screen_x, &screen_y);
        LLToolPie::getInstance()->showObjectContextMenu(object, screen_x, screen_y);
        return true;
    }
    return LLFloater::handleRightMouseDown(x, y, mask);
}
