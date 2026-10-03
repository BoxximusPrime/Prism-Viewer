#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <vector>

// CPU receiver selection only. Plane convention: inside is dot(n,p)+w >= 0.
namespace LLAlphaLightSelection
{
using Vec3 = std::array<float, 3>;
struct Bounds
{
    Vec3 min{{std::numeric_limits<float>::infinity(), std::numeric_limits<float>::infinity(), std::numeric_limits<float>::infinity()}};
    Vec3 max{{-std::numeric_limits<float>::infinity(), -std::numeric_limits<float>::infinity(), -std::numeric_limits<float>::infinity()}};
    void include(const Vec3& point)
    {
        for (float component : point) if (!std::isfinite(component)) return;
        for (int i = 0; i < 3; ++i) { min[i] = std::min(min[i], point[i]); max[i] = std::max(max[i], point[i]); }
    }
    void include(const Bounds& other)
    {
        if (other.valid()) { include(other.min); include(other.max); }
    }
    bool valid() const
    {
        for (int i = 0; i < 3; ++i)
            if (!std::isfinite(min[i]) || !std::isfinite(max[i]) || min[i] > max[i]) return false;
        return true;
    }
};
struct Candidate
{
    Vec3 position{};
    float radius = 0.f, falloff = 0.f, strength = 0.f;
    bool projector = false;
    std::array<std::array<float, 4>, 6> planes{};
    uint32_t id = 0;
};
// Affine column-major matrix; reject invalid/projective inputs rather than
// silently producing a receiver box in the wrong coordinate space.
inline Bounds transform(const Bounds& source, const std::array<float, 16>& matrix)
{
    Bounds result;
    if (!source.valid()) return result;
    for (float value : matrix) if (!std::isfinite(value)) return result;
    if (matrix[3] != 0.f || matrix[7] != 0.f || matrix[11] != 0.f || matrix[15] != 1.f) return result;
    for (int corner = 0; corner < 8; ++corner)
    {
        Vec3 point;
        for (int row = 0; row < 3; ++row)
        {
            double value = matrix[12 + row];
            for (int axis = 0; axis < 3; ++axis)
                value += double(matrix[4 * axis + row]) * ((corner & (1 << axis)) ? source.max[axis] : source.min[axis]);
            point[row] = static_cast<float>(value);
            if (!std::isfinite(point[row])) return Bounds{};
        }
        result.include(point);
    }
    return result;
}
struct Selection
{
    std::array<int, 6> ids{{-1, -1, -1, -1, -1, -1}};
    size_t count = 0;
};
struct Statistics { size_t visits = 0, scored = 0; };

class Selector
{
    struct Node
    {
        Bounds bounds, centers;
        size_t begin, end;
        int left = -1, right = -1;
        float maxRadius = 0.f, maxStrength = 0.f, minFalloff = std::numeric_limits<float>::infinity();
        uint32_t minId = std::numeric_limits<uint32_t>::max();
    };
    std::vector<Candidate> mCandidates;
    std::vector<Node> mNodes;
    mutable Statistics mStatistics;
    static Bounds bounds(const Candidate& c)
    {
        Bounds b;
        for (int i = 0; i < 3; ++i) { b.min[i] = c.position[i] - c.radius; b.max[i] = c.position[i] + c.radius; }
        return b;
    }
    static bool overlaps(const Bounds& a, const Bounds& b)
    {
        for (int i = 0; i < 3; ++i) if (a.min[i] > b.max[i] || b.min[i] > a.max[i]) return false;
        return true;
    }
    int buildNode(size_t begin, size_t end)
    {
        Node n; n.begin = begin; n.end = end;
        for (size_t k = begin; k < end; ++k)
        {
            const Candidate& c = mCandidates[k];
            n.bounds.include(bounds(c)); n.centers.include(c.position);
            n.maxRadius = std::max(n.maxRadius, c.radius); n.maxStrength = std::max(n.maxStrength, c.strength);
            n.minFalloff = std::min(n.minFalloff, c.falloff); n.minId = std::min(n.minId, c.id);
        }
        const int index = static_cast<int>(mNodes.size());
        mNodes.push_back(n);
        if (end - begin > 8)
        {
            int axis = 0;
            for (int i = 1; i < 3; ++i) if (n.bounds.max[i] - n.bounds.min[i] > n.bounds.max[axis] - n.bounds.min[axis]) axis = i;
            const size_t mid = begin + (end - begin) / 2;
            std::nth_element(mCandidates.begin() + begin, mCandidates.begin() + mid, mCandidates.begin() + end,
                [axis](const Candidate& a, const Candidate& b) { return a.position[axis] != b.position[axis] ? a.position[axis] < b.position[axis] : a.id < b.id; });
            const int left = buildNode(begin, mid), right = buildNode(mid, end);
            mNodes[index].left = left; mNodes[index].right = right;
        }
        return index;
    }
    static double upperScore(const Node& n, const Bounds& receiver)
    {
        // Below the radius cutoff, attenuation increases with radius and
        // decreases with distance and falloff (> -1). The closest point in
        // the center union and independent extrema therefore overestimate
        // every candidate. Ignoring projector clipping is conservative too.
        double squared = 0.;
        for (int i = 0; i < 3; ++i)
        {
            const double d = std::max({double(receiver.min[i]) - n.centers.max[i], double(n.centers.min[i]) - receiver.max[i], 0.});
            squared += d * d;
        }
        const double attenuation = 1. - std::clamp((std::sqrt(squared) / n.maxRadius + n.minFalloff) / (1. + n.minFalloff), 0., 1.);
        return n.maxStrength * attenuation * attenuation * 2.;
    }
    void query(int index, const Bounds& receiver, size_t limit, Selection& result, std::array<double, 6>& scores) const
    {
        ++mStatistics.visits;
        const Node& n = mNodes[index];
        if (!overlaps(n.bounds, receiver)) return;
        const double upper = upperScore(n, receiver);
        if (!(upper > 0.) || (result.count == limit && (upper < scores[limit - 1] ||
            (upper == scores[limit - 1] && n.minId >= uint32_t(result.ids[limit - 1]))))) return;
        if (n.left >= 0)
        {
            const double left = upperScore(mNodes[n.left], receiver), right = upperScore(mNodes[n.right], receiver);
            const bool leftFirst = left > right || (left == right && mNodes[n.left].minId < mNodes[n.right].minId);
            query(leftFirst ? n.left : n.right, receiver, limit, result, scores);
            query(leftFirst ? n.right : n.left, receiver, limit, result, scores);
            return;
        }
        for (size_t k = n.begin; k < n.end; ++k)
        {
            const Candidate& c = mCandidates[k];
            double distanceSquared = 0.;
            for (int i = 0; i < 3; ++i)
            {
                const double d = std::max({double(receiver.min[i]) - c.position[i], double(c.position[i]) - receiver.max[i], 0.});
                distanceSquared += d * d;
            }
            if (distanceSquared >= double(c.radius) * c.radius) continue;
            if (c.projector)
            {
                bool outside = false;
                for (const auto& plane : c.planes)
                {
                    double maximum = plane[3];
                    for (int i = 0; i < 3; ++i) maximum += double(plane[i]) * (plane[i] >= 0.f ? receiver.max[i] : receiver.min[i]);
                    if (maximum < -1.e-5) { outside = true; break; }
                }
                if (outside) continue;
            }
            ++mStatistics.scored;
            const double attenuation = 1. - std::clamp((std::sqrt(distanceSquared) / c.radius + c.falloff) / (1. + c.falloff), 0., 1.);
            const double score = c.strength * attenuation * attenuation * 2.;
            if (!(score > 0.)) continue;
            size_t at = 0;
            while (at < result.count && (scores[at] > score || (scores[at] == score && result.ids[at] < static_cast<int>(c.id)))) ++at;
            if (at >= limit) continue;
            const size_t count = std::min(limit, result.count + 1);
            for (size_t j = count - 1; j > at; --j) { scores[j] = scores[j - 1]; result.ids[j] = result.ids[j - 1]; }
            scores[at] = score; result.ids[at] = static_cast<int>(c.id); result.count = count;
        }
    }
public:
    void build(std::vector<Candidate> candidates)
    {
        mCandidates.clear(); mNodes.clear();
        for (const Candidate& c : candidates)
        {
            bool valid = c.id <= uint32_t(std::numeric_limits<int>::max()) && std::isfinite(c.radius) && c.radius > 0.f &&
                std::isfinite(c.falloff) && c.falloff > -1.f && std::isfinite(c.strength) && c.strength > 0.f && bounds(c).valid();
            if (c.projector) for (const auto& p : c.planes)
            {
                double norm = 0.;
                for (int i = 0; i < 4; ++i) valid &= std::isfinite(p[i]);
                for (int i = 0; i < 3; ++i) norm += double(p[i]) * p[i];
                valid &= norm > 0.;
            }
            if (valid) mCandidates.push_back(c);
        }
        if (!mCandidates.empty()) { mNodes.reserve(mCandidates.size() * 2); buildNode(0, mCandidates.size()); }
    }
    Selection select(const Bounds& receiver, size_t limit = 6) const
    {
        Selection result; mStatistics = {};
        limit = std::min(limit, size_t(6));
        if (limit && receiver.valid() && !mNodes.empty()) { std::array<double, 6> scores{}; query(0, receiver, limit, result, scores); }
        return result;
    }
    Statistics statistics() const { return mStatistics; }
};
}
