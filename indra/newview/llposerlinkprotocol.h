/**
 * @file llposerlinkprotocol.h
 * Copyright (C) 2026 Prism Viewer contributors.
 * SPDX-License-Identifier: LGPL-2.1-only
 */
#ifndef LL_LLPOSERLINKPROTOCOL_H
#define LL_LLPOSERLINKPROTOCOL_H

#include <array>
#include <cmath>
#include <locale>
#include <map>
#include <sstream>
#include <string>

namespace LLPoserLinkProtocol
{
constexpr unsigned short PORT = 17635;
constexpr size_t MAX_LINE = 32768;
using Rotations = std::map<std::string, std::array<float, 4>>;

inline bool hello(const std::string& line, std::string& code)
{
    if (line.size() != 19 || line.compare(0, 13, "POSER-LINK 1 ") != 0) return false;
    for (size_t i = 13; i < 19; ++i)
        if (line[i] < '0' || line[i] > '9') return false;
    code = line.substr(13);
    return true;
}

inline bool decodePose(const std::string& line, Rotations& rotations)
{
    if (line.size() > MAX_LINE) return false;
    std::istringstream stream(line);
    stream.imbue(std::locale::classic());
    std::string command;
    size_t count = 0;
    if (!(stream >> command >> count) || command != "POSE" || count == 0 || count > 160) return false;
    Rotations parsed;
    for (size_t i = 0; i < count; ++i)
    {
        std::string name;
        std::array<float, 4> q;
        if (!(stream >> name >> q[0] >> q[1] >> q[2] >> q[3]) || name.size() > 48) return false;
        float norm = 0.f;
        for (float value : q)
        {
            if (!std::isfinite(value)) return false;
            norm += value * value;
        }
        if (!std::isfinite(norm) || std::abs(norm - 1.f) > .001f || !parsed.emplace(name, q).second) return false;
    }
    stream >> std::ws;
    if (!stream.eof()) return false;
    rotations.swap(parsed);
    return true;
}
}

#endif
