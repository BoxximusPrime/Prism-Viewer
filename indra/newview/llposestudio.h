/**
 * @file llposestudio.h
 * @brief Local avatar pose ownership for Pose Studio.
 * Copyright (C) 2026 Prism Viewer contributors.
 * SPDX-License-Identifier: LGPL-2.1-only
 */
#ifndef LL_LLPOSESTUDIO_H
#define LL_LLPOSESTUDIO_H

#include "llsingleton.h"
#include "lluuid.h"
#include "v3math.h"
#include "llquaternion.h"

#include <string>
#include <vector>
#include <array>

class LLJoint;
class LLVOAvatar;
class LLSD;

class LLPoseStudio final : public LLSingleton<LLPoseStudio>
{
    LLSINGLETON(LLPoseStudio);
public:
    enum class EndReason { USER, TELEPORT, SKELETON_CHANGED, TARGET_LOST, DISCONNECTED };

    bool begin(LLVOAvatar& avatar);
    void end(EndReason reason = EndReason::USER);
    void endForAvatar(LLVOAvatar& avatar, EndReason reason, bool restore = true);

    // Remove only our presentation before normal evaluation, then apply the
    // held pose after it. Procedural motions never use our edits as their base.
    void beforeUpdate(LLVOAvatar& avatar);
    void afterUpdate(LLVOAvatar& avatar);

    bool isActive() const { return mAvatarID.notNull(); }
    U32 getSession() const { return mSession; }
    bool isActiveFor(const LLVOAvatar& avatar) const;
    EndReason getEndReason() const { return mEndReason; }
    bool setRotationOffset(const std::string& name, const LLVector3& degrees);
    LLVector3 getRotationOffset(const std::string& name) const;
    bool setPositionOffset(const std::string& name, const LLVector3& offset);
    LLVector3 getPositionOffset(const std::string& name) const;
    void resetJoint(const std::string& name);
    void resetPose();
    LLSD serializePose() const;
    bool loadPose(const LLSD& data);

    struct BonePose
    {
        std::string name;
        LLVector3 position;
        LLQuaternion rotation;
        U32 session = 0;
    };
    bool getBonePose(const std::string& name, BonePose& pose);
    bool setBonePosition(const BonePose& pose, const LLVector3& world_position);
    bool setBoneRotation(const BonePose& pose, const LLQuaternion& world_rotation);

    // A pointer-free drag snapshot. Solve on a private chain so IK never feeds
    // presentation transforms back into the avatar's motion controller.
    struct IKPose
    {
        std::array<LLVector3, 3> positions;
        std::array<LLQuaternion, 3> rotations;
        LLVector3 pole;
        U32 session = 0;
        S32 limb = -1; // left/right hand, left/right foot
        bool getReachLimits(F32& minimum, F32& maximum) const;
        bool solve(const LLVector3& target, std::array<LLQuaternion, 3>& result) const;
    };
    bool getIKPose(S32 limb, IKPose& pose);
    static const char* getIKJointName(S32 limb);
    bool setIKTarget(const IKPose& pose, const LLVector3& target);

private:
    struct Transform
    {
        LLVector3 position;
        LLQuaternion rotation;
        LLVector3 scale;

        static Transform capture(LLJoint& joint);
        void apply(LLJoint& joint) const;
        bool isFinite() const;
    };

    struct JointPose
    {
        std::string name;
        LLJoint* joint = nullptr; // checked against the live skeleton before use
        Transform captured;
        Transform animation;
        LLQuaternion rotation;
        LLVector3 degrees;
        LLVector3 position_offset;
    };

    LLVOAvatar* resolveAvatar() const;
    bool matchesSkeleton(LLVOAvatar& avatar) const;
    JointPose* findJoint(const std::string& name);
    void clearTarget(EndReason reason);

    LLUUID mAvatarID;
    const LLVOAvatar* mAvatarIdentity = nullptr; // identity comparison only
    const LLJoint* mRootIdentity = nullptr;
    U32 mSkeletonSerial = 0;
    std::vector<JointPose> mJoints;
    bool mApplied = false;
    EndReason mEndReason = EndReason::USER;
    U32 mSession = 0;
};

#endif
