/** @file llboxxyaotransfer.cpp
 * @brief Inventory-based AO transfer between Boxxy, Firestorm and ZHAO-II.
 * Copyright (c) 2026 Boxxy Viewer contributors. LGPL-2.1-or-later.
 */
#include "llviewerprecompiledheaders.h"
#include "llboxxyaotransfer.h"

#include "llagent.h"
#include "llassetstorage.h"
#include "llboxxyao.h"
#include "llboxxyaonotecard.h"
#include "llfilesystem.h"
#include "llframetimer.h"
#include "llinventorymodel.h"
#include "llinventorymodelbackgroundfetch.h"
#include "llinventorypanel.h"
#include "llnotecard.h"
#include "llnotificationsutil.h"
#include "llviewerassetupload.h"
#include "llviewerregion.h"
#include "llviewerinventory.h"
#include "roles_constants.h"

#include <cmath>
#include <functional>
#include <map>
#include <memory>
#include <set>
#include <sstream>

namespace LLBoxxyAOTransfer
{
namespace
{
using Set = LLBoxxyAO::Set;
using State = LLBoxxyAO::State;
using Animation = LLBoxxyAO::Animation;
static_assert(LLBoxxyAONotecard::STATE_COUNT == LLBoxxyAO::STATE_COUNT);

enum class Mode { ImportFolder, ImportNotecard, ExportFirestorm, ExportNotecard };
struct Operation;
std::shared_ptr<Operation> sOperation;

void message(const std::string& text)
{
    LLSD args;
    args["MESSAGE"] = text;
    LLNotificationsUtil::add("BoxxyAOTransferMessage", args);
}

bool folderReady(const LLUUID& id)
{
    if (gInventory.isCategoryComplete(id)) return true;
    gInventory.fetchDescendentsOf(id);
    return false;
}

LLUUID childFolder(const LLUUID& parent, const std::string& name)
{
    LLInventoryModel::cat_array_t* cats = nullptr;
    LLInventoryModel::item_array_t* items = nullptr;
    gInventory.getDirectDescendentsOf(parent, cats, items);
    if (cats)
    {
        for (const auto& cat : *cats)
        {
            if (cat->getName() == name) return cat->getUUID();
        }
    }
    return LLUUID::null;
}

std::string uniqueName(const LLUUID& parent, std::string base)
{
    LLStringUtil::replaceChar(base, ':', '-');
    LLInventoryObject::correctInventoryName(base);
    base = utf8str_truncate(base, 48);
    if (base.empty()) base = "Imported AO";
    std::set<std::string> names;
    LLInventoryModel::cat_array_t* cats = nullptr;
    LLInventoryModel::item_array_t* items = nullptr;
    gInventory.getDirectDescendentsOf(parent, cats, items);
    if (cats)
    {
        for (const auto& cat : *cats)
        {
            names.insert(cat->getName().substr(0, cat->getName().find(':')));
        }
    }
    std::string candidate = base;
    for (U32 suffix = 2; names.count(candidate); ++suffix)
    {
        candidate = base + llformat(" (%u)", suffix);
    }
    return candidate;
}

struct Operation : std::enable_shared_from_this<Operation>
{
    Mode mode;
    LLUUID source;
    LLUUID session = gAgent.getSessionID();
    LLUUID destination;
    Set data;
    bool writing = false;
    bool downloading = false;
    bool text_ready = false;
    bool confirming = false;
    bool options_accepted = false;
    std::string text;
    std::string warnings;
    std::string error;
    S32 pending = 0;
    F64 deadline = LLFrameTimer::getElapsedSeconds() + 120.0;
    F64 next_poll = 0.0;

    Operation(Mode transfer_mode, const LLUUID& id) : mode(transfer_mode), source(id)
    {
        for (size_t i = 0; i < data.states.size(); ++i)
        {
            data.states[i].type = static_cast<LLBoxxyAO::EState>(i);
            data.states[i].name = LLBoxxyAONotecard::STATE_NAMES[i];
        }
    }

    bool active() const
    {
        return sOperation.get() == this && session == gAgent.getSessionID();
    }

    void fail(const std::string& reason)
    {
        if (!active()) return;
        message(reason + (destination.notNull() ?
            "\nA partial transfer folder may remain in Inventory. The original set and animations were not changed." :
            "\nThe original set and animations were not changed."));
        if (destination.notNull()) LLInventoryPanel::openInventoryPanelAndSetSelection(true, destination);
        sOperation.reset();
    }

    void finishedOne()
    {
        if (!active() || --pending != 0) return;
        LLBoxxyAO::instance().requestReload();
        LLInventoryPanel::openInventoryPanelAndSetSelection(true, destination);
        const bool importing = mode == Mode::ImportFolder || mode == Mode::ImportNotecard;
        message(importing ? "AO imported as \"" + data.name + "\". Select it in Prism AO when you want to use it." :
            mode == Mode::ExportFirestorm ? "AO exported to #Firestorm/#AO as \"" + data.name +
                "\". Open Firestorm and select the new set; reload its AO if Firestorm is already running." :
            "AO notecard and animation links exported to \"" + data.name +
                "\". Drop the notecard into the receiving AO. Set cycling, randomization and sit options there; the standard notecard stores animation assignments only.");
        sOperation.reset();
    }

    bool readAnimation(const LLViewerInventoryItem* item, Animation& animation)
    {
        if (!item || !item->isFinished())
        {
            if (item) LLInventoryModelBackgroundFetch::instance().scheduleItemFetch(item->getUUID(), true);
            return false;
        }
        const LLUUID original_id = item->getLinkedUUID();
        const LLViewerInventoryItem* original = gInventory.getItem(original_id);
        if (!original || !original->isFinished())
        {
            LLInventoryModelBackgroundFetch::instance().scheduleItemFetch(original_id, true);
            return false;
        }
        if (original->getInventoryType() != LLInventoryType::IT_ANIMATION || original->getAssetUUID().isNull())
        {
            error = "An animation link is unavailable: " + item->getName();
            return false;
        }
        animation.name = original->getName();
        animation.original_id = original_id;
        animation.asset_id = original->getAssetUUID();
        // The virtual getter follows the link and returns the animation's
        // description. AO sequence numbers belong to the link itself.
        if (!LLStringUtil::convertToS32(item->LLInventoryItem::getDescription(), animation.sort_order)) animation.sort_order = -1;
        return true;
    }

    bool readFolder()
    {
        const auto* category = gInventory.getCategory(source);
        if (!category) { error = "The AO set folder is no longer available."; return false; }
        if (!folderReady(source)) return false;
        const auto options = LLStringUtil::getTokens(category->getName(), ":");
        if (options.empty()) { error = "The AO set needs a name."; return false; }
        data.name = options.front();
        data.override_sits = false;
        warnings.clear();
        for (size_t i = 1; i < options.size(); ++i)
        {
            if (options[i] == "SO") data.override_sits = true;
            else if (options[i] == "SM") warnings += "Smart sit detection\n";
            else if (options[i] == "DM") warnings += "Disable stands in mouselook\n";
            else if (options[i] != "**")
            {
                error = "Unsupported Firestorm set option: " + options[i];
                return false;
            }
        }
        LLInventoryModel::cat_array_t* cats = nullptr;
        LLInventoryModel::item_array_t* items = nullptr;
        gInventory.getDirectDescendentsOf(source, cats, items);
        std::set<int> seen;
        size_t count = 0;
        for (auto& state : data.states) state.animations.clear();
        if (cats) for (const auto& cat : *cats)
        {
            if (!folderReady(cat->getUUID())) return false;
            const auto state_options = LLStringUtil::getTokens(cat->getName(), ":");
            const int index = state_options.empty() ? -1 : LLBoxxyAONotecard::stateIndex(state_options.front());
            if (index < 0 || !seen.insert(index).second)
            {
                error = "Unsupported or repeated AO state folder: " + cat->getName() +
                    ". Drop one set folder from #Firestorm/#AO, not the #AO folder itself.";
                return false;
            }
            State& state = data.states[index];
            state.cycle = false;
            state.randomize = false;
            state.cycle_seconds = 30.f;
            for (size_t i = 1; i < state_options.size(); ++i)
            {
                const auto& option = state_options[i];
                if (option == "CY") state.cycle = true;
                else if (option == "RN") state.randomize = true;
                else if (option.compare(0, 2, "CT") == 0 &&
                    LLStringUtil::convertToF32(option.substr(2), state.cycle_seconds) &&
                    std::isfinite(state.cycle_seconds) && state.cycle_seconds >= 0.f && state.cycle_seconds <= 3600.f) {}
                else { error = "Unsupported AO state option: " + option; return false; }
            }
            LLInventoryModel::cat_array_t* children = nullptr;
            LLInventoryModel::item_array_t* animations = nullptr;
            gInventory.getDirectDescendentsOf(cat->getUUID(), children, animations);
            if (children && !children->empty())
            {
                error = "This set contains animation groups or tracks. Prism currently supports one animation at a time per state; no set was imported.";
                return false;
            }
            if (animations) for (const auto& item : *animations)
            {
                if (!item->isFinished())
                {
                    LLInventoryModelBackgroundFetch::instance().scheduleItemFetch(item->getUUID(), true);
                    return false;
                }
                if (item->getInventoryType() != LLInventoryType::IT_ANIMATION) continue;
                Animation animation;
                if (!readAnimation(item, animation)) return false;
                state.animations.push_back(animation);
                ++count;
            }
            std::stable_sort(state.animations.begin(), state.animations.end(),
                [](const Animation& a, const Animation& b)
                {
                    if (a.sort_order < 0 && b.sort_order < 0) return a.name < b.name;
                    if (a.sort_order < 0) return false;
                    if (b.sort_order < 0) return true;
                    return a.sort_order < b.sort_order;
                });
        }
        if (!count) { error = "The folder contains no supported AO animations."; return false; }
        return true;
    }

    static void notecardDownloaded(const LLUUID& asset_id, LLAssetType::EType type,
        void* userdata, S32 status, LLExtStat)
    {
        std::unique_ptr<std::weak_ptr<Operation>> holder(static_cast<std::weak_ptr<Operation>*>(userdata));
        auto self = holder->lock();
        if (!self || !self->active()) return;
        if (status) { self->fail("The AO notecard could not be downloaded."); return; }
        LLFileSystem file(asset_id, type, LLFileSystem::READ);
        const S32 size = file.getSize();
        if (size <= 0 || size > 1024 * 1024) { self->fail("The AO notecard asset has an invalid size."); return; }
        std::string buffer(size, '\0');
        if (!file.read(reinterpret_cast<U8*>(&buffer[0]), size)) { self->fail("The AO notecard could not be read."); return; }
        LLNotecard notecard;
        std::istringstream input(buffer);
        if (!notecard.importStream(input)) { self->fail("The AO notecard is not valid."); return; }
        self->text = notecard.getText();
        self->text_ready = true;
    }

    bool readNotecard()
    {
        const auto* item = gInventory.getItem(source);
        if (!item) { error = "The AO notecard is no longer available."; return false; }
        if (!item->isFinished())
        {
            LLInventoryModelBackgroundFetch::instance().scheduleItemFetch(source, true);
            return false;
        }
        if (!gAgent.allowOperation(PERM_COPY, item->getPermissions(), GP_OBJECT_MANIPULATE))
        {
            error = "The AO notecard must allow copying to be imported.";
            return false;
        }
        if (!text_ready)
        {
            if (!downloading)
            {
                if (!gAssetStorage || item->getAssetUUID().isNull()) { error = "Save the notecard before importing it."; return false; }
                downloading = true;
                gAssetStorage->getInvItemAsset(LLHost(), gAgent.getID(), session,
                    item->getPermissions().getOwner(), LLUUID::null, source,
                    item->getAssetUUID(), LLAssetType::AT_NOTECARD, &notecardDownloaded,
                    new std::weak_ptr<Operation>(shared_from_this()), true);
            }
            return false;
        }
        if (!folderReady(item->getParentUUID())) return false;
        LLBoxxyAONotecard::Animations parsed;
        if (!LLBoxxyAONotecard::parse(text, parsed, error)) return false;
        std::map<std::string, Animation> available;
        LLInventoryModel::cat_array_t* cats = nullptr;
        LLInventoryModel::item_array_t* items = nullptr;
        gInventory.getDirectDescendentsOf(item->getParentUUID(), cats, items);
        if (items) for (const auto& candidate : *items)
        {
            if (!candidate->isFinished())
            {
                LLInventoryModelBackgroundFetch::instance().scheduleItemFetch(candidate->getUUID(), true);
                return false;
            }
            if (candidate->getInventoryType() != LLInventoryType::IT_ANIMATION) continue;
            Animation animation;
            if (!readAnimation(candidate, animation)) return false;
            const auto previous = available.find(animation.name);
            if (previous != available.end() && previous->second.asset_id != animation.asset_id)
            {
                error = "Two different animations have the same name: " + animation.name +
                    ". Give them distinct names before importing.";
                return false;
            }
            available[animation.name] = animation;
        }
        data.name = item->getName();
        for (size_t i = 0; i < parsed.size(); ++i)
        {
            data.states[i].animations.clear();
            for (const auto& name : parsed[i])
            {
                const auto found = available.find(name);
                if (found == available.end())
                {
                    error = "Animation not found beside the notecard: " + name +
                        ". Keep the notecard and all its animations or animation links in the same Inventory folder.";
                    return false;
                }
                data.states[i].animations.push_back(found->second);
            }
        }
        return true;
    }

    bool readExport()
    {
        const Set* set = nullptr;
        for (const auto& candidate : LLBoxxyAO::instance().getSets())
        {
            if (candidate->inventory_id == source) set = candidate.get();
        }
        if (!set) { error = "Select an AO set before exporting."; return false; }
        data = *set;
        size_t count = 0;
        LLBoxxyAONotecard::Animations names;
        std::map<std::string, LLUUID> assets;
        for (size_t i = 0; i < data.states.size(); ++i)
        {
            for (auto& animation : data.states[i].animations)
            {
                const auto* original = gInventory.getItem(animation.original_id);
                if (!original || !original->isFinished())
                {
                    LLInventoryModelBackgroundFetch::instance().scheduleItemFetch(animation.original_id, true);
                    return false;
                }
                if (animation.inventory_id.isNull()) return false; // Wait for pending additions to finish.
                if (!readAnimation(original, animation)) return false;
                ++count;
                names[i].push_back(animation.name);
                const auto found = assets.find(animation.name);
                if (mode == Mode::ExportNotecard && found != assets.end() && found->second != animation.asset_id)
                {
                    error = "Different animations share the name \"" + animation.name +
                        "\". Use Export to Firestorm to preserve their identities, or rename them before notecard export.";
                    return false;
                }
                assets[animation.name] = animation.asset_id;
            }
        }
        if (!count) { error = "The selected set has no animations."; return false; }
        if (mode == Mode::ExportNotecard)
        {
            if (!gAgent.getRegion() || gAgent.getRegion()->getCapability("UpdateNotecardAgentInventory").empty())
            {
                error = "This region does not support notecard uploads.";
                return false;
            }
            if (!LLBoxxyAONotecard::serialize(names, text, error)) return false;
        }
        return true;
    }

    void createFolder(const LLUUID& parent, const std::string& name,
        const std::function<void(const LLUUID&)>& done)
    {
        if (!active()) return;
        auto self = shared_from_this();
        gInventory.createNewCategory(parent, LLFolderType::FT_NONE, name,
            [self, done](const LLUUID& id)
            {
                if (!self->active()) return;
                if (id.isNull()) self->fail("The destination inventory folder could not be created.");
                else done(id);
            });
    }

    void ensureFolder(const LLUUID& parent, const std::string& name,
        const std::function<void(const LLUUID&)>& done)
    {
        const LLUUID existing = childFolder(parent, name);
        if (existing.notNull()) done(existing);
        else createFolder(parent, name, done);
    }

    void addLink(const LLUUID& folder, const Animation& animation, S32 order)
    {
        if (!active()) return;
        const auto* original = gInventory.getItem(animation.original_id);
        if (!original) { fail("An animation disappeared from Inventory during transfer."); return; }
        // Supply the order in the creation request itself. Editing the new
        // link afterward would race reloads and require another server write.
        LLPointer<LLViewerInventoryItem> link_source = new LLViewerInventoryItem(original);
        if (order >= 0) link_source->setDescription(llformat("%d", order));
        LLInventoryObject::const_object_list_t objects;
        objects.emplace_back(LLConstPointer<LLInventoryObject>(link_source.get()));
        ++pending;
        auto self = shared_from_this();
        link_inventory_array(folder, objects,
            new LLBoostFuncInventoryCallback([self](const LLUUID& id)
            {
                if (!self->active()) return;
                const auto* item = gInventory.getItem(id);
                if (id.isNull() || !item) { self->fail("An animation link could not be created."); return; }
                self->finishedOne();
            }));
    }

    void addNotecard()
    {
        if (!active()) return;
        ++pending;
        auto self = shared_from_this();
        create_inventory_item(gAgent.getID(), session, destination, LLTransactionID::tnull,
            data.name, "ZHAO-II AO configuration", LLAssetType::AT_NOTECARD,
            LLInventoryType::IT_NOTECARD, 0, PERM_ALL,
            new LLBoostFuncInventoryCallback([self](const LLUUID& id)
            {
                if (!self->active()) return;
                if (id.isNull() || !gAgent.getRegion()) { self->fail("The AO notecard could not be created."); return; }
                const std::string url = gAgent.getRegion()->getCapability("UpdateNotecardAgentInventory");
                if (url.empty()) { self->fail("The region no longer supports notecard uploads."); return; }
                LLNotecard card;
                card.setText(self->text);
                std::ostringstream buffer;
                if (!card.exportStream(buffer)) { self->fail("The AO notecard could not be encoded."); return; }
                auto upload = std::make_shared<LLBufferedAssetUploadInfo>(id, LLAssetType::AT_NOTECARD, buffer.str(),
                    [self](LLUUID, LLUUID, LLUUID, LLSD) { self->finishedOne(); },
                    [self](LLUUID, LLUUID, LLSD, std::string reason)
                    {
                        self->fail("The AO notecard upload failed: " + reason);
                        return true;
                    });
                LLViewerAssetUpload::EnqueueInventoryUpload(url, upload);
            }));
    }

    void populate(const LLUUID& folder)
    {
        destination = folder;
        pending = 1; // Keep synchronous callbacks from finishing before all requests are queued.
        auto self = shared_from_this();
        if (mode == Mode::ExportNotecard)
        {
            std::set<LLUUID> linked;
            for (const auto& state : data.states) for (const auto& animation : state.animations)
            {
                if (linked.insert(animation.original_id).second) addLink(folder, animation, -1);
            }
            addNotecard();
        }
        else
        {
            for (const auto& state : data.states)
            {
                if (state.animations.empty()) continue;
                ++pending;
                std::string name = state.name;
                if (state.cycle) name += ":CY";
                if (state.randomize) name += ":RN";
                name += llformat(":CT%.2f", state.cycle_seconds);
                createFolder(folder, name, [self, state](const LLUUID& state_id)
                {
                    S32 order = 0;
                    for (const auto& animation : state.animations) self->addLink(state_id, animation, order++);
                    self->finishedOne();
                });
            }
        }
        finishedOne();
    }

    void createSetFolder(const LLUUID& parent)
    {
        data.name = uniqueName(parent, data.name + (mode == Mode::ExportNotecard ? " (AO transfer)" : ""));
        std::string folder_name = data.name;
        if (mode != Mode::ExportNotecard && data.override_sits) folder_name += ":SO";
        auto self = shared_from_this();
        createFolder(parent, folder_name, [self](const LLUUID& id) { self->populate(id); });
    }

    void prepare()
    {
        if (!active() || writing || confirming) return;
        const LLUUID root = gInventory.getRootFolderID();
        if (root.isNull() || !folderReady(root)) return;
        const LLUUID boxxy_ao = LLBoxxyAO::instance().getAOFolder();
        if (boxxy_ao.isNull() || !folderReady(boxxy_ao)) return;
        bool ready = false;
        if (mode == Mode::ImportFolder) ready = readFolder();
        else if (mode == Mode::ImportNotecard) ready = readNotecard();
        else ready = readExport();
        if (!error.empty()) { fail(error); return; }
        if (!ready) return;
        if (!warnings.empty() && !options_accepted)
        {
            confirming = true;
            LLSD args;
            args["OPTIONS"] = warnings;
            auto self = shared_from_this();
            LLNotificationsUtil::add("BoxxyAOTransferOptions", args, LLSD(),
                [self](const LLSD& notification, const LLSD& response)
                {
                    if (!self->active()) return false;
                    if (LLNotificationsUtil::getSelectedOption(notification, response) != 0) sOperation.reset();
                    else
                    {
                        self->confirming = false;
                        self->options_accepted = true;
                        self->deadline = LLFrameTimer::getElapsedSeconds() + 120.0;
                    }
                    return false;
                });
            return;
        }
        if (mode == Mode::ExportFirestorm)
        {
            const LLUUID fs = childFolder(root, "#Firestorm");
            if (fs.notNull())
            {
                if (!folderReady(fs)) return;
                const LLUUID ao = childFolder(fs, "#AO");
                if (ao.notNull() && !folderReady(ao)) return;
            }
        }
        writing = true;
        deadline = LLFrameTimer::getElapsedSeconds() + 180.0;
        auto self = shared_from_this();
        if (mode == Mode::ExportFirestorm)
        {
            ensureFolder(root, "#Firestorm", [self](const LLUUID& fs)
            {
                self->ensureFolder(fs, "#AO", [self](const LLUUID& ao) { self->createSetFolder(ao); });
            });
        }
        else createSetFolder(mode == Mode::ExportNotecard ? root : boxxy_ao);
    }
};

void start(Mode mode, const LLUUID& source)
{
    if (sOperation) { message("An AO transfer is already in progress. Please wait for it to finish."); return; }
    if (source.isNull() || !gInventory.isObjectDescendentOf(source, gInventory.getRootFolderID()))
    {
        message("Choose an AO set folder or notecard from your own Inventory.");
        return;
    }
    sOperation = std::make_shared<Operation>(mode, source);
    auto operation = sOperation;
    operation->prepare();
}
}

void importFolder(const LLUUID& id) { start(Mode::ImportFolder, id); }
void importNotecard(const LLUUID& id) { start(Mode::ImportNotecard, id); }
void exportToFirestorm(const LLUUID& id) { start(Mode::ExportFirestorm, id); }
void exportNotecard(const LLUUID& id) { start(Mode::ExportNotecard, id); }

void openImportInventory()
{
    const LLUUID fs = childFolder(gInventory.getRootFolderID(), "#Firestorm");
    LLInventoryPanel::openInventoryPanelAndSetSelection(true, fs.notNull() ? fs : gInventory.getRootFolderID());
}

void update()
{
    auto operation = sOperation;
    if (!operation) return;
    if (!operation->active()) { sOperation.reset(); return; }
    const F64 now = LLFrameTimer::getElapsedSeconds();
    if (!operation->confirming && now >= operation->deadline)
    {
        operation->fail("AO transfer timed out while waiting for Inventory. Check your connection and retry.");
    }
    else if (now >= operation->next_poll)
    {
        operation->next_poll = now + 1.0;
        operation->prepare();
    }
}

void cancel() { sOperation.reset(); }
bool isBusy() { return sOperation != nullptr; }
bool isWriting() { return sOperation && sOperation->writing; }
}
