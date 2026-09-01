/**
 * @file llfloaterboxxyradar.cpp
 * @brief Lightweight nearby-avatar radar for Boxxy Viewer.
 *
 * $LicenseInfo:firstyear=2026&license=viewerlgpl$
 * Copyright (C) 2026 Boxxy Viewer contributors
 * $/LicenseInfo$
 */

#include "llviewerprecompiledheaders.h"

#include "llfloaterboxxyradar.h"

#include "llagent.h"
#include "llavataractions.h"
#include "llavatarname.h"
#include "llavatarnamecache.h"
#include "llboxxyvip.h"
#include "llbutton.h"
#include "llcallingcard.h"
#include "llfiltereditor.h"
#include "llflatlistview.h"
#include "lliconctrl.h"
#include "lllineeditor.h"
#include "lllayoutstack.h"
#include "llmutelist.h"
#include "lloutputmonitorctrl.h"
#include "llpanelpeoplemenus.h"
#include "llscrolllistctrl.h"
#include "llspeakers.h"
#include "lltextbox.h"
#include "lluicolortable.h"
#include "llviewercontrol.h"
#include "llviewerobjectlist.h"
#include "llvoiceclient.h"
#include "llvoavatar.h"
#include "llwindow.h"
#include "llworld.h"

#include <algorithm>
#include <cmath>
#include <limits>

namespace
{
constexpr F64 METERS_TO_YARDS       = 1.0936132983377078;
constexpr F64 NEAR_DISTANCE_YARDS   = 20.0;
constexpr F32 RADAR_REFRESH_SECONDS = 0.5f;

std::string formatDistance(F64 distance_yards)
{
    if (distance_yards < 100.0)
    {
        return llformat("%.1f yd", distance_yards);
    }
    return llformat("%.0f yd", distance_yards);
}

} // namespace

class LLBoxxyRadarRow final : public LLPanel
{
public:
    explicit LLBoxxyRadarRow(const LLUUID& avatar_id) : LLPanel(), mAvatarId(avatar_id) { buildFromFile("panel_boxxy_radar_row.xml"); }

    bool postBuild() override
    {
        mName     = getChild<LLTextBox>("avatar_name");
        mTyping   = getChild<LLIconCtrl>("typing_icon");
        mVoice    = getChild<LLOutputMonitorCtrl>("voice_indicator");
        mDistance = getChild<LLTextBox>("distance");
        mVoice->setChannelState(LLOutputMonitorCtrl::UNDEFINED_CHANNEL);
        mVoice->setSpeakerId(mAvatarId);
        return true;
    }

    void update(const std::string& name, F64 distance_yards, bool typing, bool speaking)
    {
        mName->setValue(name);
        const std::string tooltip = name + "\nDouble-click to IM; right-click for more actions.";
        mName->setToolTip(tooltip);
        setToolTip(tooltip);
        mDistance->setValue(formatDistance(distance_yards));
        mTyping->setVisible(typing);
        mVoice->setVisible(speaking);
    }

    bool handleDoubleClick(S32 x, S32 y, MASK mask) override
    {
        LLAvatarActions::startIM(mAvatarId);
        return true;
    }

    bool handleRightMouseDown(S32 x, S32 y, MASK mask) override
    {
        const uuid_vec_t avatar_ids(1, mAvatarId);
        LLPanelPeopleMenus::gNearbyPeopleContextMenu.show(this, avatar_ids, x, y);
        return true;
    }

    bool handleHover(S32 x, S32 y, MASK mask) override
    {
        getWindow()->setCursor(UI_CURSOR_HAND);
        return true;
    }

    void onMouseEnter(S32 x, S32 y, MASK mask) override
    {
        getChildView("hovered_icon")->setVisible(true);
        LLPanel::onMouseEnter(x, y, mask);
    }

    void onMouseLeave(S32 x, S32 y, MASK mask) override
    {
        getChildView("hovered_icon")->setVisible(false);
        LLPanel::onMouseLeave(x, y, mask);
    }

private:
    LLUUID               mAvatarId;
    LLTextBox*           mName     = nullptr;
    LLIconCtrl*          mTyping   = nullptr;
    LLOutputMonitorCtrl* mVoice    = nullptr;
    LLTextBox*           mDistance = nullptr;
};

class LLBoxxyRadarHeader final : public LLPanel
{
public:
    LLBoxxyRadarHeader(const std::string& category_name, const std::string& color_name, S32 count) : LLPanel()
    {
        buildFromFile("panel_boxxy_radar_header.xml");
        const LLUIColor category_color = LLUIColorTable::instance().getColor(color_name);
        getChild<LLIconCtrl>("category_accent")->setColor(category_color);
        getChild<LLTextBox>("category_name")->setColor(category_color);
        getChild<LLTextBox>("category_name")->setValue(category_name);
        getChild<LLTextBox>("category_count")->setColor(category_color);
        getChild<LLTextBox>("category_count")->setValue(llformat("%d", count));
    }
};

LLFloaterBoxxyRadar::LLFloaterBoxxyRadar(const LLSD& key) : LLFloater(key)
{
}

bool LLFloaterBoxxyRadar::postBuild()
{
    mRadarList = getChild<LLFlatListView>("radar_list");
    mRadarList->setAllowSelection(false);
    mSearchInput   = getChild<LLFilterEditor>("radar_search");
    mResultSummary = getChild<LLTextBox>("result_summary");
    mVipInput = getChild<LLLineEditor>("vip_input");
    mVipList  = getChild<LLScrollListCtrl>("vip_list");
    mVipEditor = getChild<LLLayoutPanel>("vip_editor");

    mSearchInput->setCommitCallback(boost::bind(&LLFloaterBoxxyRadar::onSearchChanged, this, _2));
    mVipInput->setCommitOnFocusLost(false);
    mVipInput->setCommitCallback(boost::bind(&LLFloaterBoxxyRadar::onAddVip, this));
    getChild<LLButton>("add_vip")->setCommitCallback(boost::bind(&LLFloaterBoxxyRadar::onAddVip, this));
    getChild<LLButton>("remove_vip")->setCommitCallback(boost::bind(&LLFloaterBoxxyRadar::onRemoveVip, this));
    getChild<LLButton>("toggle_vip_editor")->setCommitCallback(boost::bind(&LLFloaterBoxxyRadar::toggleVipEditor, this));
    mVipList->setCommitCallback(boost::bind(&LLFloaterBoxxyRadar::updateVipButtons, this));
    mVipList->setDoubleClickCallback(boost::bind(&LLFloaterBoxxyRadar::onRemoveVip, this));

    refreshVipList();
    updateVipButtons();
    setVipEditorExpanded(true);
    return true;
}

void LLFloaterBoxxyRadar::onOpen(const LLSD& key)
{
    LLFloater::onOpen(key);
    mForceRebuild = true;
    refreshVipList();
    refreshRadar();
    mRefreshTimer.reset();
}

void LLFloaterBoxxyRadar::draw()
{
    if (mForceRebuild || mRefreshTimer.getElapsedTimeF32() >= RADAR_REFRESH_SECONDS)
    {
        refreshRadar();
        mRefreshTimer.reset();
    }
    LLFloater::draw();
}

void LLFloaterBoxxyRadar::refreshRadar()
{
    if (!mRadarList || gAgentID.isNull())
    {
        return;
    }

    uuid_vec_t              avatar_ids;
    std::vector<LLVector3d> positions;
    const F32               all_known_avatars_radius = std::sqrt(std::numeric_limits<F32>::max());
    LLWorld::getInstance()->getAvatars(&avatar_ids, &positions, gAgent.getPositionGlobal(), all_known_avatars_radius);

    const std::vector<std::string> vip_terms = loadVipTerms();
    std::vector<AvatarEntry>       entries;
    entries.reserve(avatar_ids.size());
    S32 total_avatar_count = 0;

    LLVoiceClient* voice_client  = LLVoiceClient::getInstance();
    const bool     voice_enabled = voice_client && voice_client->voiceEnabled();

    for (size_t index = 0; index < avatar_ids.size() && index < positions.size(); ++index)
    {
        const LLUUID& avatar_id = avatar_ids[index];
        if (avatar_id.isNull() || avatar_id == gAgentID)
        {
            continue;
        }
        ++total_avatar_count;

        AvatarEntry entry;
        entry.id             = avatar_id;
        entry.distance_yards = dist_vec(positions[index], gAgent.getPositionGlobal()) * METERS_TO_YARDS;
        const bool is_friend  = LLAvatarTracker::instance().isBuddy(avatar_id);
        const bool is_blocked = LLMuteList::getInstance()->isMuted(avatar_id);
        bool       is_vip     = false;

        LLAvatarName avatar_name;
        if (LLAvatarNameCache::get(avatar_id, &avatar_name))
        {
            std::string username = avatar_name.getAccountName();
            if (username.empty())
            {
                username = avatar_name.getUserName(true);
            }
            std::string display_name = avatar_name.getDisplayName(true);
            if (display_name.empty())
            {
                display_name = username;
            }
            entry.formatted_name = display_name + " (" + username + ")";
            is_vip               = isVip(avatar_name, vip_terms);

            if (!mSearchQuery.empty() && !LLBoxxyVIP::matchesSearch(avatar_name, mSearchQuery))
            {
                continue;
            }
        }
        else
        {
            if (!mSearchQuery.empty())
            {
                continue;
            }
            entry.formatted_name = "(loading...)";
        }

        entry.category = is_blocked                                   ? CATEGORY_BLOCKED
                         : is_vip                                      ? CATEGORY_VIP
                         : is_friend                                   ? CATEGORY_FRIENDS
                         : entry.distance_yards <= NEAR_DISTANCE_YARDS ? CATEGORY_NEAR
                                                                       : CATEGORY_FAR;

        LLPointer<LLSpeaker> speaker  = LLLocalSpeakerMgr::instance().findSpeaker(avatar_id);
        entry.typing                  = speaker.notNull() && speaker->mTyping;
        LLViewerObject* avatar_object = gObjectList.findObject(avatar_id);
        if (avatar_object && avatar_object->isAvatar())
        {
            entry.typing = entry.typing || static_cast<LLVOAvatar*>(avatar_object)->isTyping();
        }
        entry.speaking = voice_enabled && voice_client->getVoiceEnabled(avatar_id) && voice_client->getIsSpeaking(avatar_id);
        entries.push_back(entry);
    }

    if (mResultSummary)
    {
        if (mSearchQuery.empty())
        {
            mResultSummary->setValue(llformat("%d avatar%s nearby", total_avatar_count,
                                              total_avatar_count == 1 ? "" : "s"));
        }
        else
        {
            const S32 match_count = static_cast<S32>(entries.size());
            mResultSummary->setValue(llformat("%d %s / %d nearby", match_count,
                                              match_count == 1 ? "match" : "matches", total_avatar_count));
        }
    }

    std::sort(entries.begin(), entries.end(),
              [](const AvatarEntry& left, const AvatarEntry& right)
              {
                  if (left.category != right.category)
                  {
                      return left.category < right.category;
                  }
                  if (left.distance_yards != right.distance_yards)
                  {
                      return left.distance_yards < right.distance_yards;
                  }
                  return left.formatted_name < right.formatted_name;
              });

    std::vector<std::string> structure;
    for (S32 category = 0; category < CATEGORY_COUNT; ++category)
    {
        structure.push_back(llformat("header:%d", category));
        for (const AvatarEntry& entry : entries)
        {
            if (entry.category == category)
            {
                structure.push_back(llformat("%d:%s", category, entry.id.asString().c_str()));
            }
        }
    }

    if (mForceRebuild || structure != mStructure)
    {
        rebuildRadar(entries, structure);
    }

    for (const AvatarEntry& entry : entries)
    {
        const auto found = mRows.find(entry.id);
        if (found != mRows.end())
        {
            found->second->update(entry.formatted_name, entry.distance_yards, entry.typing, entry.speaking);
        }
    }

    mForceRebuild = false;
}

void LLFloaterBoxxyRadar::rebuildRadar(const std::vector<AvatarEntry>& entries, const std::vector<std::string>& structure)
{
    mRadarList->clear();
    mRows.clear();

    for (S32 category = 0; category < CATEGORY_COUNT; ++category)
    {
        const S32 count = static_cast<S32>(
            std::count_if(entries.begin(), entries.end(), [category](const AvatarEntry& entry) { return entry.category == category; }));
        addSection(static_cast<ECategory>(category), count);

        for (const AvatarEntry& entry : entries)
        {
            if (entry.category != category)
            {
                continue;
            }
            LLBoxxyRadarRow* row = new LLBoxxyRadarRow(entry.id);
            mRows[entry.id]      = row;
            mRadarList->addItem(row, entry.id);
        }
    }
    mStructure = structure;
}

void LLFloaterBoxxyRadar::addSection(ECategory category, S32 count)
{
    const char* name = "";
    const char* color_name = "BoxxyRadarFarColor";
    const char* tooltip = "";
    switch (category)
    {
        case CATEGORY_VIP:
            name = "VIP";
            color_name = "BoxxyRadarVIPColor";
            tooltip = "Matches your VIP watch list";
            break;
        case CATEGORY_FRIENDS:
            name = "Friends";
            color_name = "NameTagFriend";
            tooltip = "Avatars on your friends list";
            break;
        case CATEGORY_BLOCKED:
            name = "Blocked";
            color_name = "LtRed";
            tooltip = "Avatars on your block list";
            break;
        case CATEGORY_NEAR:
            name = "Near";
            color_name = "BoxxyRadarNearColor";
            tooltip = "Avatars within 20 yards";
            break;
        case CATEGORY_FAR:
            name = "Far";
            tooltip = "Avatars more than 20 yards away";
            break;
        default:
            break;
    }

    LLPanel* header = new LLBoxxyRadarHeader(name, color_name, count);
    header->setToolTip(std::string(tooltip));
    mRadarList->addItem(header, llformat("header:%d", static_cast<S32>(category)));
}

void LLFloaterBoxxyRadar::onSearchChanged(const std::string& query)
{
    std::string trimmed_query = query;
    LLStringUtil::trim(trimmed_query);
    if (trimmed_query == mSearchQuery)
    {
        return;
    }

    mSearchQuery = trimmed_query;
    mForceRebuild = true;
    refreshRadar();
    mRefreshTimer.reset();
}

void LLFloaterBoxxyRadar::refreshVipList()
{
    if (!mVipList)
    {
        return;
    }

    mVipList->deleteAllItems();
    for (const std::string& term : loadVipTerms())
    {
        LLSD row;
        row["value"]                = term;
        row["columns"][0]["column"] = "name";
        row["columns"][0]["value"]  = term;
        mVipList->addElement(row, ADD_BOTTOM);
    }
    updateVipButtons();
}

void LLFloaterBoxxyRadar::updateVipButtons()
{
    if (mVipList)
    {
        getChild<LLButton>("remove_vip")->setEnabled(mVipList->getFirstSelected() != nullptr);
    }
}

void LLFloaterBoxxyRadar::onAddVip()
{
    std::string term = mVipInput->getText();
    LLStringUtil::trim(term);
    if (term.empty())
    {
        return;
    }

    std::vector<std::string> terms      = loadVipTerms();
    const std::string        normalized = LLBoxxyVIP::normalizeName(term);
    const bool               duplicate  = std::find_if(terms.begin(), terms.end(), [&normalized](const std::string& existing)
                                                       { return LLBoxxyVIP::normalizeName(existing) == normalized; }) != terms.end();

    if (!duplicate)
    {
        terms.push_back(term);
        saveVipTerms(terms);
    }

    mVipInput->setText(LLStringUtil::null);
    refreshVipList();
    mForceRebuild = true;
}

void LLFloaterBoxxyRadar::onRemoveVip()
{
    if (!mVipList || !mVipList->getFirstSelected())
    {
        return;
    }

    const std::string        selected = mVipList->getFirstSelected()->getValue().asString();
    std::vector<std::string> terms    = loadVipTerms();
    terms.erase(std::remove(terms.begin(), terms.end(), selected), terms.end());
    saveVipTerms(terms);
    refreshVipList();
    mForceRebuild = true;
}

void LLFloaterBoxxyRadar::toggleVipEditor()
{
    setVipEditorExpanded(!mVipEditorExpanded);
}

void LLFloaterBoxxyRadar::setVipEditorExpanded(bool expanded)
{
    mVipEditorExpanded = expanded;
    const S32 editor_height = expanded ? 164 : 32;
    mVipEditor->setTargetDim(editor_height);

    for (const char* name : {"vip_editor_accent", "vip_editor_description", "vip_input", "add_vip", "vip_list", "remove_vip", "vip_editor_footer"})
    {
        getChildView(name)->setVisible(expanded);
    }
    getChild<LLButton>("toggle_vip_editor")->setLabel(expanded ? "Collapse" : "Expand");
    getChild<LLButton>("toggle_vip_editor")->setToolTip(
        LLStringExplicit(expanded ? "Collapse VIP controls" : "Expand VIP controls"));
}

std::vector<std::string> LLFloaterBoxxyRadar::loadVipTerms() const
{
    return LLBoxxyVIP::getTerms();
}

void LLFloaterBoxxyRadar::saveVipTerms(const std::vector<std::string>& terms)
{
    std::string value;
    for (const std::string& term : terms)
    {
        if (!value.empty())
        {
            value += '\n';
        }
        value += term;
    }
    gSavedPerAccountSettings.setString("BoxxyRadarVIPNames", value);
}

bool LLFloaterBoxxyRadar::isVip(const LLAvatarName& name, const std::vector<std::string>& terms) const
{
    return LLBoxxyVIP::matches(name, terms);
}
