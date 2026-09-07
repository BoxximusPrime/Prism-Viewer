/** @file llboxxyaonotecard.h
 * @brief ZHAO-II/Firestorm AO notecard text interchange.
 * Copyright (c) 2026 Boxxy Viewer contributors. LGPL-2.1-or-later.
 */
#ifndef LL_LLBOXXYAONOTECARD_H
#define LL_LLBOXXYAONOTECARD_H

#include <array>
#include <string>
#include <vector>

namespace LLBoxxyAONotecard
{
constexpr size_t STATE_COUNT = 25;
extern const std::array<std::string, STATE_COUNT> STATE_NAMES;
using Animations = std::array<std::vector<std::string>, STATE_COUNT>;

// Accepts standard ZHAO-II names and the Oracul aliases supported by Firestorm.
int stateIndex(std::string name);
bool parse(const std::string& text, Animations& result, std::string& error);
bool serialize(const Animations& animations, std::string& text, std::string& error);
}

#endif
