/**
 * @file lltoolposeik.h
 * @brief Live-only bone and IK gizmos for Pose Studio.
 * Copyright (C) 2026 Prism Viewer contributors.
 * SPDX-License-Identifier: LGPL-2.1-only
 */
#ifndef LL_LLTOOLPOSEIK_H
#define LL_LLTOOLPOSEIK_H

#include "lltool.h"
#include "llposestudio.h"
#include "v3dmath.h"
#include "v2math.h"

class LLToolPoseIK final : public LLTool, public LLSingleton<LLToolPoseIK>
{
    LLSINGLETON(LLToolPoseIK);
public:
    bool handleMouseDown(S32 x, S32 y, MASK mask) override;
    bool handleMouseUp(S32 x, S32 y, MASK mask) override;
    bool handleHover(S32 x, S32 y, MASK mask) override;
    bool handleKey(KEY key, MASK mask) override;
    void render() override;
    void clearHover() { mHover = {}; }
    // List selection edits a single bone. World hand/foot handles opt into IK.
    void selectJoint(const std::string& name);

private:
    bool available() const;
    struct Hit
    {
        std::string joint;
        S32 limb = -1;
        S32 part = 0; // center, move XYZ, rotate XYZ
        F32 phase = 0.f;
    };
    Hit pick(S32 x, S32 y);
    bool highlighted(const std::string& joint, S32 part);
    bool selectedPose(LLPoseStudio::BonePose& pose);
    bool drag(S32 x, S32 y);
    LLPoseStudio::IKPose mPose;
    LLPoseStudio::BonePose mBone;
    Hit mHover;
    LLVector3d mPlaneOrigin;
    LLVector3d mGrabOffset;
    LLVector3 mPlaneNormal;
    S32 mLastX = 0, mLastY = 0;
    std::string mSelectedJoint;
    S32 mSelectedLimb = -1;
    U32 mSelectedSession = 0;
    S32 mPart = 0;
    F32 mAxisStart = 0.f;
    F32 mAngle = 0.f;
    bool mRotateInPlane = false;
    bool mLocalAxesAtGrab = false;
    LLVector3 mAxis;
    LLVector3 mRotationVector;
    LLVector2 mRotationTangent;
};
#endif
