/** Fog inside description-tagged phantom box prims. */
#pragma once

#include "llvolumefogparams.h"
#include "lluuid.h"
#include "v3math.h"
#include "llquaternion.h"
#include <vector>

class LLViewerObject;
class LLVOVolume;

namespace LLVolumeFog
{
constexpr S32 MAX_VOLUMES = 8; // must match volumeFogF.glsl
constexpr S32 MAX_LIGHTS = 8; // must match volumeFogLightF.glsl
constexpr S32 MAX_PROJECTORS = 4;
struct Volume
{
    LLVolumeFogParams params;
    LLVector3 center;
    LLVector3 halfSize;
    LLQuaternion rotation;
    F32 distance;
    LLUUID id;
};

bool isCandidate(const LLVOVolume& object);
bool isInRange(const LLVOVolume& object);
void descriptionChanged(const LLViewerObject& object, const std::string& description);
void discover();
std::vector<Volume> collect();
}
