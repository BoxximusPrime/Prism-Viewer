#include "llviewerprecompiledheaders.h"
#include "llvolumefog.h"

#include "llframetimer.h"
#include "llviewercontrol.h"
#include "llviewerobjectlist.h"
#include "llviewercamera.h"
#include "llvolume.h"
#include "llvovolume.h"
#include <algorithm>
#include <map>

namespace LLVolumeFog
{
namespace
{
std::map<LLUUID, LLVolumeFogParams> sVolumes;
S32 sScanIndex = 0;
F64 sNextScan = 0.0;
}

bool isCandidate(const LLVOVolume& object)
{
    // Deliberately independent of drawable visibility and face alpha: an
    // invisible box, or a box surrounding the camera, must still be discovered.
    const LLVolume* shape = object.getVolume();
    return !object.isDead() && object.getRegion() && object.flagPhantom() &&
        !object.isAttachment() && !object.isSculpted() && shape &&
        (shape->getParams().getProfileParams().getCurveType() & LL_PCODE_PROFILE_MASK) == LL_PCODE_PROFILE_SQUARE &&
        shape->getParams().getPathParams().getCurveType() == LL_PCODE_PATH_LINE;
}

bool isInRange(const LLVOVolume& object)
{
    const auto& camera = LLViewerCamera::instance();
    return (object.getRenderPosition() - camera.getOrigin()).length() <=
        camera.getFar() + object.getScale().length() * 0.5f;
}

void descriptionChanged(const LLViewerObject& object, const std::string& description)
{
    LLVolumeFogParams params;
    if (object.getPCode() == LL_PCODE_VOLUME && parseVolumeFogDescription(description, params))
        sVolumes[object.getID()] = params;
    else
        sVolumes.erase(object.getID());
}

void discover()
{
    static LLCachedControl<bool> enabled(gSavedSettings, "RenderVolumeFog", true);
    const F64 now = LLFrameTimer::getElapsedSeconds();
    if (!enabled || now < sNextScan) return;
    sNextScan = now + 0.1;
    const S32 count = gObjectList.getNumObjects();
    for (S32 i = 0; i < llmin(count, 256); ++i)
    {
        if (sScanIndex >= count) sScanIndex = 0;
        auto* object = dynamic_cast<LLVOVolume*>(gObjectList.getObject(sScanIndex++));
        if (object && isCandidate(*object) && isInRange(*object))
            object->requestVolumeFogDescription();
    }
}

std::vector<Volume> collect()
{
    std::vector<Volume> result;
    const auto& camera = LLViewerCamera::instance();
    for (auto it = sVolumes.begin(); it != sVolumes.end();)
    {
        auto* object = dynamic_cast<LLVOVolume*>(gObjectList.findObject(it->first));
        if (!object || object->isDead())
        {
            it = sVolumes.erase(it);
            continue;
        }
        const auto& params = it->second;
        if (params.density > 0.f && isCandidate(*object) && isInRange(*object))
        {
            Volume volume{params, object->getRenderPosition(), object->getScale() * 0.5f,
                object->getRenderRotation(), 0.f, object->getID()};
            const auto& half = volume.halfSize;
            if (half.isFinite() && volume.center.isFinite() &&
                half.mV[0] > 0.f && half.mV[1] > 0.f && half.mV[2] > 0.f &&
                camera.sphereInFrustum(volume.center, half.length()))
            {
                // Distance to the actual oriented box, rather than its center,
                // gives surrounding/large volumes fair priority at the cap.
                LLVector3 local = (camera.getOrigin() - volume.center) * ~volume.rotation;
                for (S32 axis = 0; axis < 3; ++axis)
                    local.mV[axis] = llmax(fabsf(local.mV[axis]) - half.mV[axis], 0.f);
                volume.distance = local.length();
                result.push_back(volume);
            }
        }
        ++it;
    }
    std::sort(result.begin(), result.end(), [](const Volume& a, const Volume& b)
    {
        return a.distance != b.distance ? a.distance < b.distance : a.id < b.id;
    });
    if (result.size() > MAX_VOLUMES) result.resize(MAX_VOLUMES);
    return result;
}
}
