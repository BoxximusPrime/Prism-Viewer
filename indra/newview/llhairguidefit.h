#pragma once
#include <glm/glm.hpp>
#include <algorithm>
#include <cmath>
#include <vector>

namespace LLHairMesh
{
// Radial rays start at the head axis and retain the farthest exit, so a mouth
// cavity cannot replace the exterior. Run only when fitting, never per frame.
inline bool headClearanceTriangle(const glm::vec3 triangle[3], const std::vector<glm::vec4>& guides,
    int chains, std::vector<float>& radii, unsigned& tests)
{
    const glm::vec3 a = triangle[0], edge1 = triangle[1] - a, edge2 = triangle[2] - a;
    const float low = std::min({a.z, triangle[1].z, triangle[2].z});
    const float high = std::max({a.z, triangle[1].z, triangle[2].z});
    for (int node = 0; node < 9; ++node)
    {
        for (int chain = 0; chain < chains; ++chain)
        {
            const float z = guides[chain * 27 + node].z;
            if (z < low || z > high) continue;
            if (++tests > 1000000) return false;
            const glm::vec2 radial(guides[chain * 27 + node]);
            const float radius = glm::length(radial);
            if (radius < 1.e-6f) continue;
            const glm::vec3 direction(radial / radius, 0.f);
            const glm::vec3 p = glm::cross(direction, edge2);
            const float determinant = glm::dot(edge1, p);
            if (fabsf(determinant) < 1.e-10f) continue;
            const glm::vec3 s = glm::vec3(0, 0, z) - a, q = glm::cross(s, edge1);
            const float u = glm::dot(s, p) / determinant, v = glm::dot(direction, q) / determinant;
            if (u < -1.e-5f || v < -1.e-5f || u + v > 1.00001f) continue;
            const float distance = glm::dot(edge2, q) / determinant;
            if (distance > 0.f && distance < .35f)
                radii[chain * 9 + node] = std::max(radii[chain * 9 + node], distance + .01f);
        }
    }
    return true;
}
}
