/**
 * @file llboxxyvip.cpp
 * @brief Shared VIP-name matching for Boxxy Viewer.
 *
 * $LicenseInfo:firstyear=2026&license=viewerlgpl$
 * Copyright (C) 2026 Boxxy Viewer contributors
 * $/LicenseInfo$
 */

#include "llviewerprecompiledheaders.h"

#include "llboxxyvip.h"

#include "llavatarname.h"
#include "llviewercontrol.h"

#include <algorithm>
#include <cctype>
#include <cmath>

namespace
{
std::string           sCachedSetting;
LLBoxxyVIP::terms_t   sTerms;
U32                   sRevision  = 0;
bool                  sInitialized = false;

void refreshTerms()
{
    static LLCachedControl<std::string> vip_names(gSavedPerAccountSettings, "BoxxyRadarVIPNames");
    const std::string& setting = vip_names;
    if (sInitialized && setting == sCachedSetting)
    {
        return;
    }

    sInitialized  = true;
    sCachedSetting = setting;
    sTerms         = LLStringUtil::getTokens(setting, "\n");
    for (std::string& term : sTerms)
    {
        LLStringUtil::trim(term);
    }
    sTerms.erase(std::remove(sTerms.begin(), sTerms.end(), LLStringUtil::null), sTerms.end());
    ++sRevision;
}

std::vector<std::string> nameParts(const LLAvatarName& name)
{
    std::vector<std::string> parts;
    const std::string        display_name = name.getDisplayName(true);
    const std::string        account_name = name.getAccountName();
    parts.push_back(LLBoxxyVIP::normalizeName(display_name));
    parts.push_back(LLBoxxyVIP::normalizeName(account_name));
    parts.push_back(LLBoxxyVIP::normalizeName(name.getUserName(true)));
    parts.push_back(LLBoxxyVIP::normalizeName(display_name + " " + account_name));

    const std::vector<std::string> display_tokens = LLStringUtil::getTokens(display_name, " \t._-()[]{}");
    for (const std::string& token : display_tokens)
    {
        parts.push_back(LLBoxxyVIP::normalizeName(token));
    }
    return parts;
}

// Restricted Damerau-Levenshtein distance. The caller only uses this for
// short avatar names and small error thresholds.
S32 fuzzyDistance(const std::string& left, const std::string& right)
{
    const size_t     left_size  = left.size();
    const size_t     right_size = right.size();
    std::vector<S32> previous(right_size + 1);
    std::vector<S32> current(right_size + 1);
    std::vector<S32> before_previous(right_size + 1);

    for (size_t column = 0; column <= right_size; ++column)
    {
        previous[column] = static_cast<S32>(column);
    }

    for (size_t row = 1; row <= left_size; ++row)
    {
        current[0] = static_cast<S32>(row);
        for (size_t column = 1; column <= right_size; ++column)
        {
            const S32 substitution_cost = left[row - 1] == right[column - 1] ? 0 : 1;
            current[column] = llmin(llmin(current[column - 1] + 1, previous[column] + 1),
                                    previous[column - 1] + substitution_cost);

            if (row > 1 && column > 1 && left[row - 1] == right[column - 2] && left[row - 2] == right[column - 1])
            {
                current[column] = llmin(current[column], before_previous[column - 2] + 1);
            }
        }
        before_previous.swap(previous);
        previous.swap(current);
    }
    return previous[right_size];
}

bool fuzzyMatches(const std::string& normalized_term,
                  const std::vector<std::string>& candidates,
                  bool allow_short_substrings = false)
{
    if (normalized_term.empty())
    {
        return false;
    }

    for (const std::string& candidate : candidates)
    {
        if (candidate.empty())
        {
            continue;
        }

        if (candidate == normalized_term)
        {
            return true;
        }

        // Ordinary radar search supports substrings; VIP terms compare only
        // against complete name candidates and tokens.
        if (allow_short_substrings && candidate.find(normalized_term) != std::string::npos)
        {
            return true;
        }

        if (normalized_term.size() < 4)
        {
            continue;
        }

        const S32 allowed_distance = normalized_term.size() >= 10 ? 3 : normalized_term.size() >= 6 ? 2 : 1;
        if (std::abs(static_cast<S32>(candidate.size()) - static_cast<S32>(normalized_term.size())) <= allowed_distance &&
            fuzzyDistance(candidate, normalized_term) <= allowed_distance)
        {
            return true;
        }
    }
    return false;
}
} // namespace

const LLBoxxyVIP::terms_t& LLBoxxyVIP::getTerms()
{
    refreshTerms();
    return sTerms;
}

U32 LLBoxxyVIP::getRevision()
{
    refreshTerms();
    return sRevision;
}

std::string LLBoxxyVIP::normalizeName(std::string value)
{
    value = utf8str_tolower(value);
    std::string normalized;
    normalized.reserve(value.size());
    for (unsigned char character : value)
    {
        // Preserve UTF-8 bytes so non-ASCII display names still support exact
        // substring matching. Fuzzy edit distance remains intentionally simple.
        if (character >= 0x80 || std::isalnum(character))
        {
            normalized.push_back(static_cast<char>(character));
        }
    }
    return normalized;
}

bool LLBoxxyVIP::matches(const LLAvatarName& name)
{
    return matches(name, getTerms());
}

bool LLBoxxyVIP::matches(const LLAvatarName& name, const terms_t& terms)
{
    const std::vector<std::string> candidates = nameParts(name);
    for (const std::string& term : terms)
    {
        if (fuzzyMatches(normalizeName(term), candidates))
        {
            return true;
        }
    }
    return false;
}

bool LLBoxxyVIP::matchesSearch(const LLAvatarName& name, const std::string& query)
{
    return fuzzyMatches(normalizeName(query), nameParts(name), true);
}
