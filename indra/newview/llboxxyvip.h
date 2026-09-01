/**
 * @file llboxxyvip.h
 * @brief Shared VIP-name matching for Boxxy Viewer.
 *
 * $LicenseInfo:firstyear=2026&license=viewerlgpl$
 * Copyright (C) 2026 Boxxy Viewer contributors
 * $/LicenseInfo$
 */

#ifndef LL_LLBOXXYVIP_H
#define LL_LLBOXXYVIP_H

#include "stdtypes.h"

#include <string>
#include <vector>

class LLAvatarName;

namespace LLBoxxyVIP
{
using terms_t = std::vector<std::string>;

// These values are refreshed automatically when the per-account setting
// changes, so every VIP-aware UI uses the same matching rules and list.
const terms_t& getTerms();
U32            getRevision();

std::string normalizeName(std::string value);
bool        matches(const LLAvatarName& name);
bool        matches(const LLAvatarName& name, const terms_t& terms);
bool        matchesSearch(const LLAvatarName& name, const std::string& query);
}

#endif // LL_LLBOXXYVIP_H
