// Immutable triangle ordering; only the bounds need refitting as the avatar moves.
#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <numeric>
#include <vector>

namespace LLHairMesh
{
struct Tree
{
    // first triangle/left child, leaf count (zero for branches), escape, right child
    std::vector<std::array<uint32_t, 4>> nodes;
    std::vector<uint32_t> order;
    std::vector<std::vector<uint32_t>> levels;

    void split(const std::vector<std::array<float, 3>>& centres, uint32_t first, uint32_t count, uint32_t depth)
    {
        const uint32_t index = uint32_t(nodes.size());
        nodes.push_back({first, count, 0, 0});
        if (levels.size() <= depth) levels.resize(depth + 1);
        levels[depth].push_back(index);
        if (count > 4)
        {
            auto lo = centres[order[first]], hi = lo;
            for (uint32_t i = first + 1; i < first + count; ++i)
                for (int axis = 0; axis < 3; ++axis)
                {
                    lo[axis] = std::min(lo[axis], centres[order[i]][axis]);
                    hi[axis] = std::max(hi[axis], centres[order[i]][axis]);
                }
            int axis = 0;
            for (int i = 1; i < 3; ++i) if (hi[i] - lo[i] > hi[axis] - lo[axis]) axis = i;
            const uint32_t middle = first + count / 2;
            std::nth_element(order.begin() + first, order.begin() + middle, order.begin() + first + count,
                [&](uint32_t a, uint32_t b) { return centres[a][axis] < centres[b][axis]; });
            nodes[index][0] = index + 1;
            nodes[index][1] = 0;
            split(centres, first, count / 2, depth + 1);
            nodes[index][3] = uint32_t(nodes.size());
            split(centres, middle, count - count / 2, depth + 1);
        }
        nodes[index][2] = uint32_t(nodes.size());
    }

    explicit Tree(const std::vector<std::array<float, 3>>& centres)
    {
        order.resize(centres.size());
        std::iota(order.begin(), order.end(), 0u);
        nodes.reserve(centres.size());
        if (!order.empty()) split(centres, 0, uint32_t(order.size()), 0);
    }
};
}
