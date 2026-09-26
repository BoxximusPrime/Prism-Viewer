/**
 * @file llposestudio.cpp
 * @brief Local avatar pose ownership for Pose Studio.
 * Copyright (C) 2026 Prism Viewer contributors.
 * SPDX-License-Identifier: LGPL-2.1-only
 */
#include "llviewerprecompiledheaders.h"
#include "llposestudio.h"

#include "lljoint.h"
#include "lljointsolverrp3.h"
#include "llviewerobjectlist.h"
#include "llvoavatar.h"

#include <algorithm>

namespace
{
const char* const IK_JOINTS[4][3] = {
    {"mShoulderLeft", "mElbowLeft", "mWristLeft"},
    {"mShoulderRight", "mElbowRight", "mWristRight"},
    {"mHipLeft", "mKneeLeft", "mAnkleLeft"},
    {"mHipRight", "mKneeRight", "mAnkleRight"}
};

LLVector3 perpendicular(LLVector3 pole, const LLVector3& direction)
{
    pole -= direction * (pole * direction);
    if (pole.normalize() < 0.001f)
    {
        pole = (fabsf(direction.mV[VZ]) < 0.9f ? LLVector3::z_axis : LLVector3::y_axis) % direction;
        pole.normalize();
    }
    return pole;
}
}

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
                             transform.rotation, LLVector3::zero, LLVector3::zero });
    }

    mJoints = std::move(captured);
    mAvatarID = avatar.getID();
    mAvatarIdentity = &avatar;
    mRootIdentity = avatar.getRootJoint();
    mSkeletonSerial = avatar.getSkeletonSerialNum();
    mApplied = false;
    mEndReason = EndReason::USER;
    ++mSession;
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
        pose.joint->setPosition(pose.captured.position + pose.position_offset);
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

bool LLPoseStudio::setPositionOffset(const std::string& name, const LLVector3& offset)
{
    if (!isActive() || !offset.isFinite()) return false;
    JointPose* pose = findJoint(name);
    if (!pose) return false;
    pose->position_offset = offset;
    LL_INFOS("PoseStudio") << "Position offset " << name << " " << offset << LL_ENDL;
    return true;
}

LLVector3 LLPoseStudio::getPositionOffset(const std::string& name) const
{
    for (const JointPose& pose : mJoints)
    {
        if (pose.name == name) return pose.position_offset;
    }
    return LLVector3::zero;
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
        pose->position_offset.clear();
    }
}

void LLPoseStudio::resetPose()
{
    if (!isActive()) return;
    for (JointPose& pose : mJoints)
    {
        pose.rotation = pose.captured.rotation;
        pose.degrees.clear();
        pose.position_offset.clear();
    }
}

const char* LLPoseStudio::getIKJointName(S32 limb)
{
    return limb >= 0 && limb < 4 ? IK_JOINTS[limb][2] : "";
}

bool LLPoseStudio::getIKPose(S32 limb, IKPose& pose)
{
    LLVOAvatar* avatar = resolveAvatar();
    if (limb < 0 || limb >= 4 || !avatar || !matchesSkeleton(*avatar) || !mApplied) return false;
    LLJoint* parent = nullptr;
    for (S32 i = 0; i < 3; ++i)
    {
        JointPose* joint = findJoint(IK_JOINTS[limb][i]);
        if (!joint || (i > 0 && joint->joint->getParent() != parent)) return false;
        parent = joint->joint;
        pose.positions[i] = parent->getWorldPosition();
        pose.rotations[i] = parent->getWorldRotation();
        if (!pose.positions[i].isFinite() || !pose.rotations[i].isFinite()) return false;
    }
    LLVector3 direction = pose.positions[2] - pose.positions[0];
    if (direction.normalize() < 0.001f) direction = pose.positions[1] - pose.positions[0];
    direction.normalize();
    LLVector3 bend = pose.positions[1] - pose.positions[0];
    bend -= direction * (bend * direction);
    // Keep the existing elbow/knee bend. A straight limb needs a preferred
    // direction: elbows back, knees forward, in the avatar's frame.
    if (bend.lengthSquared() < 0.000001f)
        bend = LLVector3(limb < 2 ? -1.f : 1.f, 0.f, 0.f) * avatar->getRootJoint()->getWorldRotation();
    pose.pole = perpendicular(bend, direction);
    pose.session = mSession;
    pose.limb = limb;
    return true;
}

bool LLPoseStudio::IKPose::solve(const LLVector3& target, std::array<LLQuaternion, 3>& result) const
{
    if (!target.isFinite() || !pole.isFinite()) return false;
    for (S32 i = 0; i < 3; ++i)
        if (!positions[i].isFinite() || !rotations[i].isFinite()) return false;
    const F32 upper_length = (positions[1] - positions[0]).length();
    const F32 lower_length = (positions[2] - positions[1]).length();
    if (upper_length < 0.001f || lower_length < 0.001f) return false;

    LLVector3 direction = target - positions[0];
    const F32 distance = direction.normalize();
    if (distance < 0.0001f)
    {
        direction = positions[2] - positions[0];
        if (direction.normalize() < 0.0001f)
        {
            direction = positions[1] - positions[0];
            direction.normalize();
        }
    }
    // Avoid both singular ends of the reachable interval; never stretch bones.
    const F32 margin = llmin(upper_length, lower_length) * 0.001f;
    const F32 reach = llclamp(distance, fabsf(upper_length - lower_length) + margin,
                             upper_length + lower_length - margin);
    LLJoint upper("pose_ik_upper"), lower("pose_ik_lower", &upper), end("pose_ik_end", &lower), goal("pose_ik_goal");
    upper.setPosition(positions[0]);
    upper.setRotation(rotations[0]);
    lower.setPosition((positions[1] - positions[0]) * ~rotations[0]);
    lower.setRotation(rotations[1] * ~rotations[0]);
    end.setPosition((positions[2] - positions[1]) * ~rotations[1]);
    goal.setPosition(positions[0] + direction * reach);
    LLJointSolverRP3 solver;
    solver.setupJoints(&upper, &lower, &end, &goal);
    solver.setPoleVector(perpendicular(pole, direction));
    solver.solve();
    result = {upper.getWorldRotation(), lower.getWorldRotation(), rotations[2]};
    return result[0].isFinite() && result[1].isFinite();
}

bool LLPoseStudio::setIKTarget(const IKPose& pose, const LLVector3& target)
{
    IKPose current;
    if (pose.session != mSession || !getIKPose(pose.limb, current)) return false;
    std::array<LLQuaternion, 3> world_rotations;
    if (!pose.solve(target, world_rotations)) return false;
    std::array<LLQuaternion, 3> local_rotations;
    std::array<LLVector3, 3> degrees;
    std::array<JointPose*, 3> joints;
    for (S32 i = 0; i < 3; ++i)
    {
        joints[i] = findJoint(IK_JOINTS[pose.limb][i]);
        LLJoint* parent = joints[i]->joint->getParent();
        const LLQuaternion parent_rotation = i > 0 ? world_rotations[i - 1] :
            (parent ? parent->getWorldRotation() : LLQuaternion());
        local_rotations[i] = world_rotations[i] * ~parent_rotation;
        local_rotations[i].normalize();
        const LLQuaternion offset = local_rotations[i] * ~joints[i]->captured.rotation;
        offset.getEulerAngles(&degrees[i].mV[VX], &degrees[i].mV[VY], &degrees[i].mV[VZ]);
        degrees[i] *= RAD_TO_DEG;
        if (!local_rotations[i].isFinite() || !degrees[i].isFinite()) return false;
    }
    for (S32 i = 0; i < 3; ++i)
    {
        joints[i]->rotation = local_rotations[i];
        joints[i]->degrees = degrees[i];
        joints[i]->joint->setRotation(local_rotations[i]);
    }
    if (LLVOAvatar* avatar = resolveAvatar())
    {
        avatar->getRootJoint()->updateWorldMatrixChildren();
        avatar->dirtyMesh();
    }
    return true;
}

bool LLPoseStudio::getBonePose(const std::string& name, BonePose& pose)
{
    LLVOAvatar* avatar = resolveAvatar();
    if (!avatar || !matchesSkeleton(*avatar) || !mApplied) return false;
    JointPose* joint = findJoint(name);
    if (!joint) return false;
    pose = {name, joint->joint->getWorldPosition(), joint->joint->getWorldRotation(), mSession};
    return pose.position.isFinite() && pose.rotation.isFinite();
}

bool LLPoseStudio::setBonePosition(const BonePose& pose, const LLVector3& world_position)
{
    BonePose current;
    if (!world_position.isFinite() || pose.session != mSession || !getBonePose(pose.name, current)) return false;
    JointPose* joint = findJoint(pose.name);
    LLVector3 local = world_position;
    if (LLJoint* parent = joint->joint->getParent())
    {
        local = (world_position - parent->getWorldPosition()) * ~parent->getWorldRotation();
        // Invert LLXformMatrix::update(): child offsets use the parent's local
        // scale, only when that parent enables scale-child-offset behavior.
        if (parent->getXform()->getScaleChildOffset())
        {
            const LLVector3 scale = parent->getScale();
            for (S32 axis = 0; axis < 3; ++axis)
            {
                if (fabsf(scale.mV[axis]) < 0.000001f) return false;
                local.mV[axis] /= scale.mV[axis];
            }
        }
    }
    const LLVector3 offset = local - joint->captured.position;
    if (!local.isFinite() || !offset.isFinite()) return false;
    joint->position_offset = offset;
    joint->joint->setPosition(local);
    if (LLVOAvatar* avatar = resolveAvatar())
    {
        avatar->getRootJoint()->updateWorldMatrixChildren();
        avatar->dirtyMesh();
    }
    return true;
}

bool LLPoseStudio::setBoneRotation(const BonePose& pose, const LLQuaternion& world_rotation)
{
    BonePose current;
    if (!world_rotation.isFinite() || pose.session != mSession || !getBonePose(pose.name, current)) return false;
    JointPose* joint = findJoint(pose.name);
    LLJoint* parent = joint->joint->getParent();
    LLQuaternion local = parent ? world_rotation * ~parent->getWorldRotation() : world_rotation;
    local.normalize();
    const LLQuaternion offset = local * ~joint->captured.rotation;
    LLVector3 degrees;
    offset.getEulerAngles(&degrees.mV[VX], &degrees.mV[VY], &degrees.mV[VZ]);
    degrees *= RAD_TO_DEG;
    if (!local.isFinite() || !degrees.isFinite()) return false;
    joint->rotation = local;
    joint->degrees = degrees;
    joint->joint->setRotation(local);
    if (LLVOAvatar* avatar = resolveAvatar())
    {
        avatar->getRootJoint()->updateWorldMatrixChildren();
        avatar->dirtyMesh();
    }
    return true;
}
