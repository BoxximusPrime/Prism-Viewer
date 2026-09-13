/** Parameters for description-authored fog boxes. No viewer dependencies. */
#pragma once

#include <array>
#include <cmath>
#include <locale>
#include <sstream>
#include <string>

struct LLVolumeFogParams
{
    float density = 0.f; // extinction per metre
    std::array<float, 3> color = {1.f, 1.f, 1.f}; // normalized sRGB
    float softness = 0.f; // inward fade distance in metres
};

// A malformed tag disables fog; never retain parameters from an earlier edit.
inline bool parseVolumeFogDescription(std::string text, LLVolumeFogParams& result)
{
    result = {};
    for (char& c : text)
        if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
    const auto begin = text.find("[vfog:");
    if (begin == std::string::npos) return false;
    const auto end = text.find(']', begin);
    if (end == std::string::npos) return false;
    std::istringstream input(text.substr(begin + 6, end - begin - 6));
    input.imbue(std::locale::classic());
    auto delimiter = [&](char expected)
    {
        char c = 0;
        return bool(input >> c) && c == expected;
    };
    LLVolumeFogParams params;
    if (!(input >> params.density) || !delimiter(',') || !delimiter('<') ||
        !(input >> params.color[0]) || !delimiter(',') ||
        !(input >> params.color[1]) || !delimiter(',') ||
        !(input >> params.color[2]) || !delimiter('>')) return false;
    input >> std::ws;
    if (!input.eof())
    {
        if (!delimiter(',') || !(input >> params.softness)) return false;
        input >> std::ws;
        if (!input.eof()) return false;
    }
    if (!std::isfinite(params.density) || params.density < 0.f || params.density > 10.f ||
        !std::isfinite(params.softness) || params.softness < 0.f || params.softness > 1024.f) return false;
    for (float& component : params.color)
    {
        if (!std::isfinite(component) || component < 0.f || component > 255.f) return false;
        component /= 255.f;
    }
    result = params;
    return true;
}
