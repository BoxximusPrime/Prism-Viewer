#pragma once

#include <algorithm>
#include <cmath>

namespace LLQuickPhoto
{
// Fractions of standing height; allow space above the head and below the feet.
struct Frame { float bottom, top, yaw; int height; };
inline Frame frame(int preset)
{
    switch (preset)
    {
        case 0: return {0.85f, 1.03f, 0.35f, 256}; // close three-quarter face
        case 2: return {0.43f, 1.05f, 0.f, 256};
        case 3: return {-0.04f, 0.58f, 0.f, 512};
        default: return {-0.05f, 1.07f, 0.f, 512};
    }
}
inline float distance(float height, int preset, float fov, float zoom)
{
    const auto crop = frame(preset);
    const float vertical = height * (crop.top - crop.bottom);
    // Full-length framing also fits shoulders inside the narrow portrait crop.
    const float horizontal = preset == 1 ? height * 0.54f : 0.f;
    return std::max(vertical, horizontal * crop.height / 256.f) / (2.f * std::tan(fov * 0.5f) * zoom);
}
inline void desaturate(unsigned char* rgb, const float* scene_depth, const float* body_depth, int pixels)
{
    for (int i = 0; i < pixels; ++i)
    {
        if (body_depth[i] < 1.f && std::abs(scene_depth[i] - body_depth[i]) < 0.000001f)
        {
            auto* pixel = rgb + i * 3;
            const unsigned char grey = static_cast<unsigned char>((54 * pixel[0] + 183 * pixel[1] + 19 * pixel[2]) / 256);
            pixel[0] = pixel[1] = pixel[2] = grey;
        }
    }
}
}
