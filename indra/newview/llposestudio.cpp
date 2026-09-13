/**
 * @file llposestudio.cpp
 * @brief Local avatar pose ownership for Pose Studio.
 * Copyright (C) 2026 Prism Viewer contributors.
 * SPDX-License-Identifier: LGPL-2.1-only
 */
#include "llviewerprecompiledheaders.h"
#include "llposestudio.h"

#include "lljoint.h"
#include "llviewerobjectlist.h"
#include "llvoavatar.h"

#include <algorithm>

LLPoseStudio::LLPoseStudio() = default;

LLPoseStudio::Transform LLPoseStudio::Transform::capture(LLJoint& joint)
{
    return { joint.getPosition(), joint.getRotation(), joint.getScale() };
}

void LLPoseStudio::Transform::apply(LLJoint& joint) const
{
    joint.setPosition(position);
    joint.setRotation(rotation);
    joint.setScale(scale);
}

bool LLPoseStudio::Transform::isFinite() const
{
    return position.isFinite() && rotation.isFinite() && scale.isFinite();
}

bool LLPoseStudio::begin(LLVOAvatar& avatar)
{
    // Target routing is separate from pose data, but v1 only admits self.
    if (isActive() || !avatar.isSelf() || avatar.isDead() || !avatar.isBuilt()
        || avatar.getIsAppearanceAnimating()
        || !avatar.getRootJoint() || avatar.getSkeletonJointCount() == 0)
    {
        return false;
    }

    std::vector<JointPose> captured;
    captured.reserve(avatar.getSkeletonJointCount());
    for (size_t i = 0; i < avatar.getSkeletonJointCount(); ++i)
    {
        LLJoint* joint = avatar.getSkeletonJoint(static_cast<S32>(i));
        if (!joint || joint->getName().empty())
        {
            return false;
        }
        Transform transform = Transform::capture(*joint);
        if (!transform.isFinite())
        {
            return false;
        }
        captured.push_back({ joint->getName(), joint, transform, transform,
                             transform.rotation, LLVector3::zero });
    }

    mJoints = std::move(captured);
    mAvatarID = avatar.getID();
    mAvatarIdentity = &avatar;
    mRootIdentity = avatar.getRootJoint();
    mSkeletonSerial = avatar.getSkeletonSerialNum();
    mApplied = false;
    mEndReason = EndReason::USER;
    LL_INFOS("PoseStudio") << "Started local pose with " << mJoints.size() << " joints" << LL_ENDL;
    return true;
}

bool LLPoseStudio::isActiveFor(const LLVOAvatar& avatar) const
{
    return isActive() && mAvatarIdentity == &avatar && mAvatarID == avatar.getID();
}

LLVOAvatar* LLPoseStudio::resolveAvatar() const
{
    if (!isActive()) return nullptr;
    auto* avatar = dynamic_cast<LLVOAvatar*>(gObjectList.findObject(mAvatarID));
    return avatar && isActiveFor(*avatar) && !avatar->isDead() ? avatar : nullptr;
}

bool LLPoseStudio::matchesSkeleton(LLVOAvatar& avatar) const
{
    if (!isActiveFor(avatar) || !avatar.isBuilt() || avatar.isDead()
        || avatar.getRootJoint() != mRootIdentity
        || avatar.getSkeletonSerialNum() != mSkeletonSerial
        || avatar.getSkeletonJointCount() != mJoints.size())
    {
        return false;
    }
    // Compare pointers before dereferencing any stored joint. Rebuilds can
    // replace a skeleton without changing its joint count or serial.
    for (size_t i = 0; i < mJoints.size(); ++i)
    {
        if (avatar.getSkeletonJoint(static_cast<S32>(i)) != mJoints[i].joint)
        {
            return false;
        }
    }
    return true;
}

void LLPoseStudio::beforeUpdate(LLVOAvatar& avatar)
{
    if (!isActiveFor(avatar)) return;
    if (!matchesSkeleton(avatar))
    {
        clearTarget(EndReason::SKELETON_CHANGED);
        return;
    }
    if (mApplied)
    {
        for (const JointPose& pose : mJoints)
        {
            pose.animation.apply(*pose.joint);
        }
        mApplied = false;
    }
}

void LLPoseStudio::afterUpdate(LLVOAvatar& avatar)
{
    if (!isActiveFor(avatar)) return;
    if (!matchesSkeleton(avatar))
    {
        clearTarget(EndReason::SKELETON_CHANGED);
        return;
    }
    for (JointPose& pose : mJoints)
    {
        // Normal motions, including new network animation events, keep their
        // own state underneath the local preview. No motion/setting is stopped.
        pose.animation = Transform::capture(*pose.joint);
        pose.captured.apply(*pose.joint);
        pose.joint->setRotation(pose.rotation);
    }
    mApplied = true;
}

void LLPoseStudio::clearTarget(EndReason reason)
{
    if (isActive())
    {
        LL_INFOS("PoseStudio") << "Ended local pose, reason " << static_cast<int>(reason) << LL_ENDL;
    }
    mAvatarID.setNull();
    mAvatarIdentity = nullptr;
    mRootIdentity = nullptr;
    mApplied = false;
    mEndReason = reason;
    // Keep the captured/edited values for a future draft workflow, not pointers.
    for (JointPose& pose : mJoints) pose.joint = nullptr;
}

void LLPoseStudio::endForAvatar(LLVOAvatar& avatar, EndReason reason, bool restore)
{
    if (!isActiveFor(avatar)) return;
    if (restore && matchesSkeleton(avatar))
    {
        for (const JointPose& pose : mJoints)
        {
            pose.captured.apply(*pose.joint);
        }
        avatar.getRootJoint()->updateWorldMatrixChildren();
        avatar.dirtyMesh();
        avatar.mNeedsImpostorUpdate = true;
    }
    clearTarget(reason);
}

void LLPoseStudio::end(EndReason reason)
{
    if (LLVOAvatar* avatar = resolveAvatar())
    {
        endForAvatar(*avatar, reason);
    }
    else if (isActive())
    {
        clearTarget(EndReason::TARGET_LOST);
    }
}

LLPoseStudio::JointPose* LLPoseStudio::findJoint(const std::string& name)
{
    auto found = std::find_if(mJoints.begin(), mJoints.end(),
        [&name](const JointPose& pose) { return pose.name == name; });
    return found == mJoints.end() ? nullptr : &*found;
}

bool LLPoseStudio::setRotationOffset(const std::string& name, const LLVector3& degrees)
{
    if (!isActive() || !degrees.isFinite()) return false;
    JointPose* pose = findJoint(name);
    if (!pose) return false;
    // LLQuaternion uses row-vector composition: delta first, then the captured
    // local orientation. The UI stores offsets to avoid Euler wrap on refresh.
    LLQuaternion delta;
    delta.setEulerAngles(degrees.mV[VX] * DEG_TO_RAD, degrees.mV[VY] * DEG_TO_RAD,
                         degrees.mV[VZ] * DEG_TO_RAD);
    pose->degrees = degrees;
    pose->rotation = delta * pose->captured.rotation;
    pose->rotation.normalize();
    LL_INFOS("PoseStudio") << "Rotation offset " << name << " " << degrees << LL_ENDL;
    return true;
}

LLVector3 LLPoseStudio::getRotationOffset(const std::string& name) const
{
    for (const JointPose& pose : mJoints)
    {
        if (pose.name == name) return pose.degrees;
    }
    return LLVector3::zero;
}

void LLPoseStudio::resetJoint(const std::string& name)
{
    if (!isActive()) return;
    if (JointPose* pose = findJoint(name))
    {
        pose->rotation = pose->captured.rotation;
        pose->degrees.clear();
    }
}

void LLPoseStudio::resetPose()
{
    if (!isActive()) return;
    for (JointPose& pose : mJoints)
    {
        pose.rotation = pose.captured.rotation;
        pose.degrees.clear();
    }
}
