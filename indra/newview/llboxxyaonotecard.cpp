/** @file llboxxyaonotecard.cpp
 * @brief ZHAO-II/Firestorm AO notecard text interchange.
 * Copyright (c) 2026 Boxxy Viewer contributors. LGPL-2.1-or-later.
 */
#include "llboxxyaonotecard.h"

#include <algorithm>
#include <cctype>
#include <sstream>

namespace LLBoxxyAONotecard
{
const std::array<std::string, STATE_COUNT> STATE_NAMES = {
    "Standing", "Walking", "Running", "Sitting", "Sitting On Ground",
    "Crouching", "Crouch Walking", "Landing", "Soft Landing", "Standing Up",
    "Falling", "Flying Down", "Flying Up", "Flying", "Flying Slow", "Hovering",
    "Jumping", "Pre Jumping", "Turning Right", "Turning Left", "Typing",
    "Floating", "Swimming Forward", "Swimming Up", "Swimming Down"
};

namespace
{
std::string trim(const std::string& value)
{
    const auto first = value.find_first_not_of(" \t\r\n");
    return first == std::string::npos ? "" :
        value.substr(first, value.find_last_not_of(" \t\r\n") - first + 1);
}

std::string lower(std::string value)
{
    std::transform(value.begin(), value.end(), value.begin(),
        [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return value;
}
}

int stateIndex(std::string name)
{
    name = lower(trim(name));
    static const std::array<std::string, STATE_COUNT> aliases = {
        "stand.1|stand.2|stand.3", "walk.n", "", "sit.n", "sit.g",
        "crouch", "walk.c", "land.n", "", "stand.u", "", "hover.d",
        "hover.u", "fly.n", "", "hover.n", "jump.n", "jump.p",
        "turn.r", "turn.l", "", "swim.h", "swim.n", "swim.u", "swim.d"
    };
    for (size_t i = 0; i < STATE_COUNT; ++i)
    {
        if (name == lower(STATE_NAMES[i])) return static_cast<int>(i);
        std::istringstream tokens(aliases[i]);
        std::string alias;
        while (std::getline(tokens, alias, '|'))
        {
            if (!alias.empty() && name == alias) return static_cast<int>(i);
        }
    }
    return -1;
}

bool parse(const std::string& text, Animations& result, std::string& error)
{
    result = {};
    error.clear();
    if (text.size() > 65536)
    {
        error = "The notecard exceeds 64 KiB.";
        return false;
    }
    Animations parsed;
    std::istringstream input(text);
    std::string line;
    size_t line_number = 0, count = 0;
    while (std::getline(input, line))
    {
        ++line_number;
        if (line_number == 1 && line.compare(0, 3, "\xef\xbb\xbf") == 0) line.erase(0, 3);
        line = trim(line);
        if (line.empty() || line[0] == '#' || line.compare(0, 2, "//") == 0) continue;
        const auto close = line.find(']');
        if (line[0] != '[' || close == std::string::npos)
        {
            error = "Line " + std::to_string(line_number) + ": expected [State]Animation|Animation.";
            return false;
        }
        const std::string state_name = line.substr(1, close - 1);
        const int state = stateIndex(state_name);
        if (state < 0)
        {
            error = "Unsupported animation state: " + state_name + ".";
            return false;
        }
        std::istringstream names(line.substr(close + 1));
        std::string name;
        while (std::getline(names, name, '|'))
        {
            name = trim(name);
            if (name.empty()) continue;
            if (name.find(',') != std::string::npos)
            {
                error = "Simultaneous animation groups (comma-separated names) are not supported. No set was imported.";
                return false;
            }
            parsed[state].push_back(name);
            ++count;
        }
    }
    if (!count)
    {
        error = "The notecard contains no animation names.";
        return false;
    }
    result = std::move(parsed);
    return true;
}

bool serialize(const Animations& animations, std::string& text, std::string& error)
{
    text.clear();
    error.clear();
    std::string output = "# ZHAO-II AO configuration exported by The Prism Viewer.\n"
        "# Keep this notecard beside its animation links.\n"
        "# Cycling, randomization and sit options must be set in the receiving AO.\n";
    size_t count = 0;
    for (size_t i = 0; i < STATE_COUNT; ++i)
    {
        for (const auto& name : animations[i])
        {
            if (name.empty() || name != trim(name) || name.find_first_of("|,\r\n") != std::string::npos)
            {
                error = "An animation name cannot be represented in a ZHAO-II notecard: " + name;
                return false;
            }
            const std::string line = "[ " + STATE_NAMES[i] + " ]" + name + "\n";
            if (line.size() > 256)
            {
                error = "An animation name exceeds the notecard line limit: " + name;
                return false;
            }
            output += line;
            ++count;
        }
    }
    if (!count || output.size() > 65536)
    {
        error = count ? "The exported notecard exceeds 64 KiB." : "The selected set has no animations.";
        return false;
    }
    text = std::move(output);
    return true;
}
}
