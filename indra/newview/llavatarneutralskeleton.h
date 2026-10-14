#pragma once

#include "lljointdata.h"
#include "llmodel.h"
#include "llpolyskeletaldistortion.h"
#include "llvoavatarself.h"
#include <map>
#include <memory>

// A private skeleton uses the avatar's shape and attachment joint overrides
// in its rest T-pose. Never touch the animated skeleton or rigged cache.
class LLAvatarNeutralSkeleton
{
public:
    explicit LLAvatarNeutralSkeleton(LLVOAvatarSelf& avatar) : mAvatar(avatar)
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

