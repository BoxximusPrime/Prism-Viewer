/**
* @file llfloaterhoverheight.cpp
* @brief Controller for self avatar hover height
* @author vir@lindenlab.com
*
* $LicenseInfo:firstyear=2014&license=viewerlgpl$
* Second Life Viewer Source Code
* Copyright (C) 2014, Linden Research, Inc.
*
* This library is free software; you can redistribute it and/or
* modify it under the terms of the GNU Lesser General Public
* License as published by the Free Software Foundation;
* version 2.1 of the License only.
*
* This library is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
* Lesser General Public License for more details.
*
* You should have received a copy of the GNU Lesser General Public
* License along with this library; if not, write to the Free Software
* Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA
*
* Linden Research, Inc., 945 Battery Street, San Francisco, CA  94111  USA
* $/LicenseInfo$
*/

#include "llviewerprecompiledheaders.h"

#include "llfloaterhoverheight.h"
#include "llsliderctrl.h"
#include "llviewercontrol.h"
#include "llsdserialize.h"
#include "llagent.h"
#include "llviewerregion.h"
#include "llvoavatarself.h"
#include "llfloaterreg.h"
#include "llscrolllistctrl.h"
#include "lltextbox.h"
#include "llviewerjointattachment.h"
#include "llviewerobjectlist.h"
#include "llvovolume.h"
#include "lljointdata.h"
#include "llpolyskeletaldistortion.h"
#include "llskinningutil.h"
#include "llmeshrepository.h"
#include "llworld.h"
#include "pipeline.h"

#include <cmath>
#include <limits>
#include <memory>

namespace
{
    // A private skeleton uses the avatar's shape and attachment joint overrides
    // in its rest T-pose. Never touch the animated skeleton or rigged cache.
    class ShoeHeightSkeleton
    {
    public:
        explicit ShoeHeightSkeleton(LLVOAvatarSelf& avatar) : mAvatar(avatar)
        {
            std::vector<LLJointData> bones;
            avatar.getJointMatricesAndHierarhy(bones);
            for (const auto& bone : bones) addRotations(bone);
            for (LLVisualParam* param = avatar.getFirstVisualParam(); param; param = avatar.getNextVisualParam())
            {
                if (auto* distortion = dynamic_cast<LLPolySkeletalDistortion*>(param)) mShape.push_back(distortion);
            }
        }

        LLJoint* joint(LLJoint* source)
        {
            if (!source) return nullptr;
            auto found = mJoints.find(source);
            if (found != mJoints.end()) return found->second.get();
            LLJoint* parent = joint(source->getParent());
            auto copy = std::make_unique<LLJoint>();
            copy->setup(source->getName(), parent);
            copy->setScale(source->getScale());
            auto rotation = mRestRotations.find(source->getName());
            if (rotation != mRestRotations.end())
            {
                // buildCharacter() zeros the runtime pelvis: mRoot already
                // supplies its world height. The XML bind pelvis is 1.067 m
                // above the origin; adding it again lowers the avatar by ~1 m.
                LLVector3 position = source == mAvatar.mPelvisp ? LLVector3::zero : source->getDefaultPosition();
                for (const auto* shape : mShape) position += shape->getJointPositionOffset(source);
                LLUUID mesh;
                LLVector3 override_position;
                if (source->hasAttachmentPosOverride(override_position, mesh)) position = override_position;
                copy->setPosition(position);
                copy->setRotation(rotation->second);
            }
            else
            {
                // Root and attachment points retain their configured transform.
                copy->setPosition(source->getPosition());
                copy->setRotation(source->getRotation());
            }
            LLJoint* result = copy.get();
            mJoints.emplace(source, std::move(copy));
            return result;
        }

        bool palette(const LLMeshSkinInfo* skin, LLMatrix4a* matrices, U32 count)
        {
            if (!count || skin->mInvBindMatrix.size() < count || skin->mJointNames.size() < count) return false;
            for (U32 index = 0; index < count; ++index)
            {
                LLJoint* neutral = joint(mAvatar.getJoint(skin->mJointNames[index]));
                if (!neutral) return false;
                matMul(skin->mInvBindMatrix[index], neutral->getWorldMatrix4a(), matrices[index]);
            }
            return true;
        }

    private:
        void addRotations(const LLJointData& bone)
        {
            mRestRotations[bone.mName] = mayaQ(bone.mRotation[VX], bone.mRotation[VY], bone.mRotation[VZ], LLQuaternion::XYZ);
            for (const auto& child : bone.mChildren) addRotations(child);
        }
        LLVOAvatarSelf& mAvatar;
        std::map<std::string, LLQuaternion> mRestRotations;
        std::vector<const LLPolySkeletalDistortion*> mShape;
        std::map<LLJoint*, std::unique_ptr<LLJoint>> mJoints;
    };

    bool lowestAttachmentVertex(LLViewerObject* object, ShoeHeightSkeleton& skeleton,
                                const LLMatrix4& attachment_to_neutral, F32& lowest)
    {
        if (!object || object->isDead()) return false;
        if (auto* volume_object = dynamic_cast<LLVOVolume*>(object))
        {
            LLVolume* volume = volume_object->getVolume();
            if (!volume || (volume_object->isMesh() && !volume->isMeshAssetLoaded())) return false;
            const bool rigged = volume_object->isRiggedMesh();
            LLMatrix4a matrices[LL_MAX_JOINTS_PER_MESH_OBJECT];
            const LLMeshSkinInfo* skin = nullptr;
            U32 joint_count = 0;
            if (rigged)
            {
                skin = volume_object->getSkinInfo();
                if (!skin) return false;
                joint_count = LLSkinningUtil::getMeshJointCount(skin);
                if (joint_count > LL_MAX_JOINTS_PER_MESH_OBJECT || !skeleton.palette(skin, matrices, joint_count)) return false;
            }
            if (!volume->getNumVolumeFaces()) return false;
            for (S32 face_index = 0; face_index < volume->getNumVolumeFaces(); ++face_index)
            {
                const LLVolumeFace& face = volume->getVolumeFace(face_index);
                if (!face.mPositions || !face.mNumVertices) return false;
                if (rigged && !face.mWeights) return false;
                for (S32 vertex = 0; vertex < face.mNumVertices; ++vertex)
                {
                    LLVector3 position(face.mPositions[vertex].getF32ptr());
                    if (rigged)
                    {
                        LLMatrix4a weighted;
                        LLSkinningUtil::getPerVertexSkinMatrix(face.mWeights[vertex].getF32ptr(), matrices, false, weighted, joint_count);
                        LLVector4a bound, posed;
                        skin->mBindShapeMatrix.affineTransform(face.mPositions[vertex], bound);
                        weighted.affineTransform(bound, posed);
                        position.set(posed.getF32ptr());
                    }
                    else
                    {
                        position = volume_object->volumePositionToAgent(position) * attachment_to_neutral;
                    }
                    if (!position.isFinite()) return false;
                    lowest = llmin(lowest, position.mV[VZ]);
                }
            }
        }
        for (LLViewerObject* child : object->getChildren())
        {
            if (!lowestAttachmentVertex(child, skeleton, attachment_to_neutral, lowest)) return false;
        }
        return true;
    }

    bool findShoeGround(LLVOAvatarSelf& avatar, LLVector3& ground)
    {
        const LLVector3d center = gAgent.getPosGlobalFromAgent(avatar.getRenderPosition());
        const LLVector3d start = center + LLVector3d(0.0, 0.0, 0.5);
        // resolveHeightAgent() only searches +/-0.5 m about the pelvis and
        // clamps object-floor intersections to that segment. Reach below the
        // physical avatar's feet, independent of its visual hover offset.
        const LLVector3d end = center - LLVector3d(0.0, 0.0, llmax(2.f, avatar.mBodySize[VZ] + 0.5f));
        LLVector3d intersection;
        LLVector3 normal;
        const F32 distance = LLWorld::getInstance()->resolveStepHeightGlobal(&avatar, start, end, intersection, normal, nullptr);
        ground = gAgent.getPosAgentFromGlobal(intersection);
        if (!std::isfinite(distance) || distance < 0.f || distance > 1.f || !ground.isFinite()) return false;

        // The step solver deliberately lowers the Havok foot plane by 5 cm.
        // Use it only to locate the support surface: shoes should meet rendered
        // geometry, which can also differ from an object's collision shape.
        // Keep the ray near the support plane to avoid overhead furniture.
        LLVector4a ray_start, ray_end, surface;
        ray_start.load3((ground + LLVector3(0.f, 0.f, 0.25f)).mV);
        ray_end.load3((ground - LLVector3(0.f, 0.f, 0.25f)).mV);
        const auto filter = [](LLViewerObject* object)
        {
            return !object->isAvatar() && !object->isAttachment();
        };
        if (!gPipeline.lineSegmentIntersectInWorld(ray_start, ray_end, false, false, true, false,
                nullptr, nullptr, nullptr, &surface, nullptr, nullptr, nullptr, nullptr, filter)) return false;
        LL_INFOS("ShoeHeight") << "Step floor " << llformat("%.6f", ground.mV[VZ])
            << " rendered floor " << llformat("%.6f", surface.getF32ptr()[VZ]) << LL_ENDL;
        ground.set(surface.getF32ptr());
        return ground.isFinite();
    }
}

bool LLFloaterShoeHeight::postBuild()
{
    getChild<LLUICtrl>("apply")->setCommitCallback([this](LLUICtrl*, const LLSD&) { applyHeight(); });
    getChild<LLUICtrl>("cancel")->setCommitCallback([this](LLUICtrl*, const LLSD&) { closeFloater(); });
    getChild<LLScrollListCtrl>("attachments")->setCommitCallback([this](LLUICtrl*, const LLSD&)
    {
        getChild<LLUICtrl>("apply")->setEnabled(true);
    });
    getChild<LLScrollListCtrl>("attachments")->setDoubleClickCallback([this]() { applyHeight(); });
    return LLModalDialog::postBuild();
}

void LLFloaterShoeHeight::onOpen(const LLSD& key)
{
    LLModalDialog::onOpen(key);
    auto* list = getChild<LLScrollListCtrl>("attachments");
    list->deleteAllItems();
    getChild<LLUICtrl>("apply")->setEnabled(false);
    getChild<LLTextBox>("status")->setText(getString("instructions"));
    if (!isAgentAvatarValid()) return;
    for (const auto& entry : gAgentAvatarp->mAttachmentPoints)
    {
        LLViewerJointAttachment* point = entry.second;
        if (!point || point->getIsHUDAttachment()) continue;
        for (const auto& object : point->mAttachedObjects)
        {
            if (!object || object->isDead()) continue;
            LLSD row;
            row["id"] = object->getID();
            row["columns"][0]["column"] = "name";
            row["columns"][0]["value"] = object->getAttachmentItemName();
            row["columns"][1]["column"] = "point";
            row["columns"][1]["value"] = point->getName();
            list->addElement(row);
        }
    }
    list->sortByColumnIndex(0, true);
    if (!list->getItemCount()) getChild<LLTextBox>("status")->setText(getString("no_attachments"));
}

void LLFloaterShoeHeight::applyHeight()
{
    auto fail = [this](const char* message) { getChild<LLTextBox>("status")->setText(getString(message)); };
    if (!isAgentAvatarValid() || !gAgent.getRegion() || !gAgent.getRegion()->avatarHoverHeightEnabled())
    {
        fail("unavailable");
        return;
    }
    if (gAgentAvatarp->isSitting() || gAgent.getFlying() || gAgentAvatarp->mInAir || gAgent.getVelocity().lengthSquared() > 0.01f)
    {
        fail("stand_still");
        return;
    }
    LLViewerObject* object = gObjectList.findObject(getChild<LLScrollListCtrl>("attachments")->getSelectedValue().asUUID());
    if (!object || object->isDead() || !object->isAttachment() || object->isHUDAttachment() || object->getAvatar() != gAgentAvatarp)
    {
        fail("detached");
        return;
    }
    F32 lowest = std::numeric_limits<F32>::infinity();
    LLViewerJointAttachment* attachment = nullptr;
    for (const auto& entry : gAgentAvatarp->mAttachmentPoints)
    {
        if (entry.second && entry.second->isObjectAttached(object)) { attachment = entry.second; break; }
    }
    if (!attachment) { fail("detached"); return; }
    ShoeHeightSkeleton skeleton(*gAgentAvatarp);
    LLMatrix4 attachment_to_neutral = attachment->getWorldMatrix();
    attachment_to_neutral.invert();
    attachment_to_neutral *= skeleton.joint(attachment)->getWorldMatrix();
    if (!lowestAttachmentVertex(object, skeleton, attachment_to_neutral, lowest) || !std::isfinite(lowest))
    {
        fail("not_loaded");
        return;
    }
    // Hover is a direct meter offset on mRoot. Compare the sampled sole with
    // the rendered floor, using the simulator support plane only as a guide.
    LLVector3 ground;
    if (!findShoeGround(*gAgentAvatarp, ground)) { fail("ground_unavailable"); return; }
    const F32 height = gAgentAvatarp->getHoverOffset().mV[VZ] + ground.mV[VZ] - lowest;
    LL_INFOS("ShoeHeight") << "Attachment " << object->getID()
        << " current hover " << gAgentAvatarp->getHoverOffset().mV[VZ]
        << " ground " << ground.mV[VZ] << " neutral sole " << lowest
        << " physical center " << gAgentAvatarp->getRenderPosition().mV[VZ]
        << " body height " << gAgentAvatarp->mBodySize.mV[VZ]
        << " calculated hover " << height << LL_ENDL;
    if (!std::isfinite(height) || height < MIN_HOVER_Z || height > MAX_HOVER_Z)
    {
        fail("out_of_range");
        return;
    }
    gSavedPerAccountSettings.setF32("AvatarHoverOffsetZ", height);
    // Also commit a previewed slider value when the saved setting was unchanged.
    gAgentAvatarp->setHoverOffset(LLVector3(0.f, 0.f, height));
    closeFloater();
}

LLFloaterHoverHeight::LLFloaterHoverHeight(const LLSD& key) : LLFloater(key)
{
}

void LLFloaterHoverHeight::syncFromPreferenceSetting(void *user_data, bool update_offset)
{
    F32 value = gSavedPerAccountSettings.getF32("AvatarHoverOffsetZ");

    LLFloaterHoverHeight *self = static_cast<LLFloaterHoverHeight*>(user_data);
    LLSliderCtrl* sldrCtrl = self->getChild<LLSliderCtrl>("HoverHeightSlider");
    sldrCtrl->setValue(value,false);

    if (isAgentAvatarValid() && update_offset)
    {
        LLVector3 offset(0.0, 0.0, llclamp(value,MIN_HOVER_Z,MAX_HOVER_Z));
        LL_INFOS("Avatar") << "setting hover from preference setting " << offset[2] << LL_ENDL;
        gAgentAvatarp->setHoverOffset(offset);
        //gAgentAvatarp->sendHoverHeight();
    }
}

bool LLFloaterHoverHeight::postBuild()
{
    getChild<LLUICtrl>("AutoShoeHeight")->setCommitCallback([](LLUICtrl*, const LLSD&)
    {
        LLFloaterReg::showInstance("shoe_height");
    });
    LLSliderCtrl* sldrCtrl = getChild<LLSliderCtrl>("HoverHeightSlider");
    sldrCtrl->setMinValue(MIN_HOVER_Z);
    sldrCtrl->setMaxValue(MAX_HOVER_Z);
    sldrCtrl->setSliderMouseUpCallback(boost::bind(&LLFloaterHoverHeight::onFinalCommit,this));
    sldrCtrl->setSliderEditorCommitCallback(boost::bind(&LLFloaterHoverHeight::onFinalCommit,this));
    childSetCommitCallback("HoverHeightSlider", &LLFloaterHoverHeight::onSliderMoved, NULL);

    // Initialize slider from pref setting.
    syncFromPreferenceSetting(this);
    // Update slider on future pref changes.
    if (gSavedPerAccountSettings.getControl("AvatarHoverOffsetZ"))
    {
        gSavedPerAccountSettings.getControl("AvatarHoverOffsetZ")->getCommitSignal()->connect(boost::bind(&syncFromPreferenceSetting, this, false));
    }
    else
    {
        LL_WARNS() << "Control not found for AvatarHoverOffsetZ" << LL_ENDL;
    }

    updateEditEnabled();

    if (!mRegionChangedSlot.connected())
    {
        mRegionChangedSlot = gAgent.addRegionChangedCallback(boost::bind(&LLFloaterHoverHeight::onRegionChanged,this));
    }
    // Set up based on initial region.
    onRegionChanged();

    return true;
}

void LLFloaterHoverHeight::onClose(bool app_quitting)
{
    if (mRegionChangedSlot.connected())
    {
        mRegionChangedSlot.disconnect();
    }
}

// static
void LLFloaterHoverHeight::onSliderMoved(LLUICtrl* ctrl, void* userData)
{
    if (isAgentAvatarValid())
    {
        LLSliderCtrl* sldrCtrl = static_cast<LLSliderCtrl*>(ctrl);
        F32 value = sldrCtrl->getValueF32();
        LLVector3 offset(0.0, 0.0, llclamp(value, MIN_HOVER_Z, MAX_HOVER_Z));
        LL_INFOS("Avatar") << "setting hover from slider moved" << offset[2] << LL_ENDL;
        gAgentAvatarp->setHoverOffset(offset, false);
    }
}

// Do send-to-the-server work when slider drag completes, or new
// value entered as text.
void LLFloaterHoverHeight::onFinalCommit()
{
    LLSliderCtrl* sldrCtrl = getChild<LLSliderCtrl>("HoverHeightSlider");
    F32 value = sldrCtrl->getValueF32();
    gSavedPerAccountSettings.setF32("AvatarHoverOffsetZ",value);
}

void LLFloaterHoverHeight::onRegionChanged()
{
    LLViewerRegion *region = gAgent.getRegion();
    if (region && region->simulatorFeaturesReceived())
    {
        updateEditEnabled();
    }
    else if (region)
    {
        region->setSimulatorFeaturesReceivedCallback(boost::bind(&LLFloaterHoverHeight::onSimulatorFeaturesReceived,this,_1));
    }
}

void LLFloaterHoverHeight::onSimulatorFeaturesReceived(const LLUUID &region_id)
{
    LLViewerRegion *region = gAgent.getRegion();
    if (region && (region->getRegionID()==region_id))
    {
        updateEditEnabled();
    }
}

void LLFloaterHoverHeight::updateEditEnabled()
{
    bool enabled = gAgent.getRegion() && gAgent.getRegion()->avatarHoverHeightEnabled();
    LLSliderCtrl* sldrCtrl = getChild<LLSliderCtrl>("HoverHeightSlider");
    sldrCtrl->setEnabled(enabled);
    getChild<LLUICtrl>("AutoShoeHeight")->setEnabled(enabled && isAgentAvatarValid());
    if (enabled)
    {
        syncFromPreferenceSetting(this);
    }
}
