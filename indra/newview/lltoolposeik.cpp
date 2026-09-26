/**
 * @file lltoolposeik.cpp
 * Copyright (C) 2026 Prism Viewer contributors.
 * SPDX-License-Identifier: LGPL-2.1-only
 */
#include "llviewerprecompiledheaders.h"
#include "lltoolposeik.h"

#include "llagent.h"
#include "llagentcamera.h"
#include "llfloaterposestudio.h"
#include "llfloaterreg.h"
#include "llfocusmgr.h"
#include "llrender2dutils.h"
#include "lltoolmgr.h"
#include "lluicolortable.h"
#include "llviewercamera.h"
#include "llviewercontrol.h"
#include "llviewerdisplay.h"
#include "llviewershadermgr.h"
#include "llviewerwindow.h"
#include "pipeline.h"

extern bool gSnapshot;

namespace
{
constexpr F32 HANDLE_RADIUS = 9.f;
constexpr F32 PICK_RADIUS = 14.f;
constexpr F32 RING_RADIUS = 52.f;
constexpr S32 RING_STEPS = 64;
constexpr S32 MOVE_X = 1, ROTATE_X = 4;
const LLVector3 AXES[] = {LLVector3(1.f, 0.f, 0.f), LLVector3(0.f, 1.f, 0.f), LLVector3(0.f, 0.f, 1.f)};

struct GizmoSegment
{
    LLVector2 start, end;
    S32 part;
    F32 phase = 0.f;
};

bool projectHandle(const LLVector3& position, LLVector2& screen)
{
    // Inverse of mouseDirectionGlobal(), in scaled UI coordinates. This also
    // works during input dispatch, when the current GL matrices may be 2D.
    const auto* camera = LLViewerCamera::getInstance();
    const LLVector3 relative = position - camera->getOrigin();
    const F32 depth = relative * camera->getAtAxis();
    if (depth <= camera->getNear()) return false;
    const LLRect viewport = gViewerWindow->getWorldViewRectScaled();
    const F32 scale = viewport.getHeight() * 0.5f / (tanf(camera->getView() * 0.5f) * depth);
    screen.set(viewport.getCenterX() - (relative * camera->getLeftAxis()) * scale,
               viewport.getCenterY() + (relative * camera->getUpAxis()) * scale);
    return screen.isFinite() && viewport.pointInRect(ll_round(screen.mV[VX]), ll_round(screen.mV[VY]));
}

F32 gizmoScale(const LLVector3& position)
{
    const auto* camera = LLViewerCamera::getInstance();
    const F32 depth = (position - camera->getOrigin()) * camera->getAtAxis();
    return 2.f * depth * tanf(camera->getView() * 0.5f) / gViewerWindow->getWorldViewRectScaled().getHeight();
}

LLVector3 ringVector(S32 axis, F32 phase)
{
    return AXES[(axis + 1) % 3] * cosf(phase) + AXES[(axis + 2) % 3] * sinf(phase);
}

LLQuaternion gizmoRotation(const LLQuaternion& bone_rotation)
{
    return gSavedSettings.getBOOL("PoseStudioLocalAxes") ? bone_rotation : LLQuaternion();
}

std::vector<GizmoSegment> gizmoSegments(const LLVector3& origin, const LLQuaternion& orientation)
{
    // One geometry source for drawing and picking, in UI pixels at any zoom.
    std::vector<GizmoSegment> segments;
    const F32 scale = gizmoScale(origin);
    for (S32 axis = 0; axis < 3; ++axis)
    {
        LLVector2 start, end;
        const LLVector3 direction_world = AXES[axis] * orientation;
        if (projectHandle(origin + direction_world * (26.f * scale), start)
            && projectHandle(origin + direction_world * (92.f * scale), end))
        {
            LLVector2 direction = end - start;
            // A line pointing directly into the camera has no useful drag
            // direction. Orbit slightly to expose that translation arrow.
            if (direction.normalize() > 12.f)
            {
                segments.push_back({start, end, MOVE_X + axis});
                const LLVector2 side(-direction.mV[VY], direction.mV[VX]);
                segments.push_back({end, end - direction * 9.f + side * 4.f, MOVE_X + axis});
                segments.push_back({end, end - direction * 9.f - side * 4.f, MOVE_X + axis});
            }
        }
        for (S32 step = 0; step < RING_STEPS; ++step)
        {
            const F32 phase = F_TWO_PI * step / RING_STEPS;
            if (projectHandle(origin + (ringVector(axis, phase) * orientation) * (RING_RADIUS * scale), start)
                && projectHandle(origin + (ringVector(axis, phase + F_TWO_PI / RING_STEPS) * orientation) * (RING_RADIUS * scale), end))
                segments.push_back({start, end, ROTATE_X + axis, phase});
        }
    }
    return segments;
}

F32 segmentDistanceSquared(const LLVector2& point, const GizmoSegment& segment, F32& fraction)
{
    const LLVector2 delta = segment.end - segment.start;
    const F32 length = delta.lengthSquared();
    fraction = length > 0.001f ? llclamp(((point - segment.start) * delta) / length, 0.f, 1.f) : 0.f;
    return (point - (segment.start + delta * fraction)).lengthSquared();
}

bool axisParameter(const LLVector3& origin, const LLVector3& axis, S32 x, S32 y, F32& parameter)
{
    const LLVector3 ray = gViewerWindow->mouseDirectionGlobal(x, y);
    const LLVector3 offset = LLViewerCamera::getInstance()->getOrigin() - origin;
    const F32 parallel = axis * ray;
    const F32 denominator = 1.f - parallel * parallel;
    if (denominator < 0.0001f) return false;
    parameter = ((axis * offset) - parallel * (ray * offset)) / denominator;
    return llfinite(parameter);
}

LLVector3 axisTarget(const LLPoseStudio::IKPose& pose, const LLVector3& axis, F32 distance)
{
    // Clamp along the selected axis, rather than letting the IK solver pull
    // an unreachable target sideways onto its reach sphere.
    const LLVector3 offset = pose.positions[2] - pose.positions[0];
    const F32 along = offset * axis;
    const F32 perpendicular_sq = llmax(0.f, offset.lengthSquared() - along * along);
    const F32 upper = (pose.positions[1] - pose.positions[0]).length();
    const F32 lower = (pose.positions[2] - pose.positions[1]).length();
    const F32 outer = sqrtf(llmax(0.f, (upper + lower) * (upper + lower) - perpendicular_sq));
    distance = llclamp(distance, -along - outer, -along + outer);
    const F32 inner_sq = (upper - lower) * (upper - lower) - perpendicular_sq;
    if (inner_sq > 0.f)
    {
        const F32 inner = sqrtf(inner_sq);
        const F32 low = -along - inner, high = -along + inner;
        if (distance > low && distance < high)
            distance = along < 0.f ? low : high;
    }
    return pose.positions[2] + axis * distance;
}

bool rotationVector(const LLVector3& origin, const LLVector3& axis, S32 x, S32 y, LLVector3& radial)
{
    const LLVector3 ray = gViewerWindow->mouseDirectionGlobal(x, y);
    const F32 denominator = ray * axis;
    if (fabsf(denominator) < 0.08f) return false;
    const LLVector3 camera = LLViewerCamera::getInstance()->getOrigin();
    const F32 distance = ((origin - camera) * axis) / denominator;
    if (distance <= 0.f) return false;
    radial = camera + ray * distance - origin;
    return radial.isFinite() && radial.normalize() > 0.0001f;
}
}

LLToolPoseIK::LLToolPoseIK() : LLTool("Pose Studio") {}

bool LLToolPoseIK::available() const
{
    return !gDisconnected && !gAgentCamera.cameraMouselook()
        && !LLToolMgr::getInstance()->inBuildMode()
        && gPipeline.hasRenderDebugFeatureMask(LLPipeline::RENDER_DEBUG_FEATURE_UI)
        && gSavedSettings.getBOOL("PoseStudioShowIKHandles")
        && LLPoseStudio::instanceExists() && LLPoseStudio::instance().isActive();
}

void LLToolPoseIK::selectJoint(const std::string& name)
{
    setMouseCapture(false);
    clearHover();
    mSelectedJoint = name;
    mSelectedLimb = -1;
    mSelectedSession = LLPoseStudio::instance().getSession();
}

bool LLToolPoseIK::selectedPose(LLPoseStudio::BonePose& pose)
{
    LLPoseStudio& studio = LLPoseStudio::instance();
    if (!studio.isActive() || studio.getSession() != mSelectedSession)
    {
        mSelectedJoint.clear();
        mSelectedLimb = -1;
        return false;
    }
    return studio.getBonePose(mSelectedJoint, pose);
}

LLToolPoseIK::Hit LLToolPoseIK::pick(S32 x, S32 y)
{
    Hit closest;
    if (!available()) return closest;
    F32 distance = PICK_RADIUS * PICK_RADIUS;
    for (S32 limb = 0; limb < 4; ++limb)
    {
        LLPoseStudio::IKPose pose;
        LLVector2 point;
        if (!LLPoseStudio::instance().getIKPose(limb, pose) || !projectHandle(pose.positions[2], point)) continue;
        const F32 dx = x - point.mV[VX], dy = y - point.mV[VY];
        if (dx * dx + dy * dy < distance)
        {
            distance = dx * dx + dy * dy;
            closest = {LLPoseStudio::getIKJointName(limb), limb, 0, 0.f};
        }
    }
    // Center handles take priority, including switching to another limb.
    if (closest.limb >= 0) return closest;
    LLPoseStudio::BonePose pose;
    if (!selectedPose(pose)) return closest;
    LLVector2 center;
    if (projectHandle(pose.position, center)
        && (LLVector2((F32)x, (F32)y) - center).lengthSquared() < PICK_RADIUS * PICK_RADIUS)
        return {mSelectedJoint, mSelectedLimb, 0, 0.f};
    distance = 6.f * 6.f;
    for (const auto& segment : gizmoSegments(pose.position, gizmoRotation(pose.rotation)))
    {
        F32 fraction;
        const F32 candidate = segmentDistanceSquared(LLVector2((F32)x, (F32)y), segment, fraction);
        if (candidate < distance)
        {
            distance = candidate;
            closest = {mSelectedJoint, mSelectedLimb, segment.part, segment.phase + fraction * F_TWO_PI / RING_STEPS};
        }
    }
    return closest;
}

bool LLToolPoseIK::highlighted(const std::string& joint, S32 part)
{
    return hasMouseCapture() ? joint == mSelectedJoint && part == mPart :
        joint == mHover.joint && part == mHover.part;
}

bool LLToolPoseIK::handleMouseDown(S32 x, S32 y, MASK mask)
{
    // Alt and other modifier drags retain their normal camera/tool behavior.
    if (mask != MASK_NONE) return false;
    const Hit hit = pick(x, y);
    LLPoseStudio& studio = LLPoseStudio::instance();
    if (hit.joint.empty() || !studio.getBonePose(hit.joint, mBone)
        || (hit.limb >= 0 && !studio.getIKPose(hit.limb, mPose))) return false;
    mPlaneOrigin = gAgent.getPosGlobalFromAgent(mBone.position);
    mPlaneNormal = LLViewerCamera::getInstance()->getAtAxis();
    LLVector3d point;
    if (!gViewerWindow->mousePointOnPlaneGlobal(point, x, y, mPlaneOrigin, mPlaneNormal)) return false;
    mGrabOffset = mPlaneOrigin - point;
    mPart = hit.part;
    mAngle = 0.f;
    mLocalAxesAtGrab = gSavedSettings.getBOOL("PoseStudioLocalAxes");
    const LLQuaternion orientation = gizmoRotation(mBone.rotation);
    if (mPart >= ROTATE_X)
    {
        const S32 axis = mPart - ROTATE_X;
        mAxis = AXES[axis] * orientation;
        mRotateInPlane = rotationVector(mBone.position, mAxis, x, y, mRotationVector);
        // An edge-on ring cannot be intersected reliably. Drag along its
        // projected tangent instead, keeping the chosen rotation axis.
        LLVector2 from, to;
        const F32 radius = RING_RADIUS * gizmoScale(mBone.position);
        const LLVector3 radial = ringVector(axis, hit.phase) * orientation;
        const LLVector3 tangent = mAxis % radial;
        if (!projectHandle(mBone.position + radial * radius, from)
            || !projectHandle(mBone.position + (radial + tangent * 0.1f) * radius, to)) return false;
        mRotationTangent = to - from;
        if (mRotationTangent.normalize() < 0.01f)
        {
            projectHandle(mBone.position, from);
            projectHandle(mBone.position + mAxis * radius, to);
            mRotationTangent.set(from.mV[VY] - to.mV[VY], to.mV[VX] - from.mV[VX]);
            mRotationTangent.normalize();
        }
    }
    else if (mPart >= MOVE_X)
    {
        mAxis = AXES[mPart - MOVE_X] * orientation;
        if (!axisParameter(mBone.position, mAxis, x, y, mAxisStart)) return false;
    }
    mSelectedJoint = hit.joint;
    mSelectedLimb = hit.limb;
    mSelectedSession = mBone.session;
    if (auto* floater = LLFloaterReg::findTypedInstance<LLFloaterPoseStudio>("pose_studio")) floater->selectJoint(hit.joint);
    mLastX = x;
    mLastY = y;
    gFocusMgr.setKeyboardFocus(nullptr);
    setMouseCapture(true);
    return true;
}

bool LLToolPoseIK::drag(S32 x, S32 y)
{
    LLVector3d point;
    if (!available() || mLocalAxesAtGrab != gSavedSettings.getBOOL("PoseStudioLocalAxes")) return false;
    if (x == mLastX && y == mLastY) return true;
    LLPoseStudio& studio = LLPoseStudio::instance();
    const LLVector3 origin = gAgent.getPosAgentFromGlobal(mPlaneOrigin);
    if (mPart >= ROTATE_X)
    {
        LLVector3 radial;
        if (mRotateInPlane)
        {
            if (!rotationVector(origin, mAxis, x, y, radial)) return true;
            mAngle += atan2f(mAxis * (mRotationVector % radial), mRotationVector * radial);
            mRotationVector = radial;
        }
        else mAngle += (LLVector2((F32)(x - mLastX), (F32)(y - mLastY)) * mRotationTangent) / RING_RADIUS;
        if (!studio.setBoneRotation(mBone, mBone.rotation * LLQuaternion(mAngle, mAxis))) return false;
    }
    else if (mPart >= MOVE_X)
    {
        F32 parameter;
        if (!axisParameter(origin, mAxis, x, y, parameter)) return true;
        const F32 distance = parameter - mAxisStart;
        if (mSelectedLimb >= 0)
        {
            if (!studio.setIKTarget(mPose, axisTarget(mPose, mAxis, distance))) return false;
        }
        else if (!studio.setBonePosition(mBone, origin + mAxis * distance)) return false;
    }
    else
    {
        if (!gViewerWindow->mousePointOnPlaneGlobal(point, x, y, mPlaneOrigin, mPlaneNormal)) return false;
        const LLVector3 target = gAgent.getPosAgentFromGlobal(point + mGrabOffset);
        if (mSelectedLimb >= 0)
        {
            if (!studio.setIKTarget(mPose, target)) return false;
        }
        else if (!studio.setBonePosition(mBone, target)) return false;
    }
    mLastX = x;
    mLastY = y;
    if (auto* floater = LLFloaterReg::findTypedInstance<LLFloaterPoseStudio>("pose_studio")) floater->onPoseChanged();
    return true;
}

bool LLToolPoseIK::handleHover(S32 x, S32 y, MASK mask)
{
    clearHover();
    if (hasMouseCapture())
    {
        if (!drag(x, y)) setMouseCapture(false);
        gViewerWindow->setCursor(mPart >= ROTATE_X ? UI_CURSOR_TOOLROTATE : UI_CURSOR_TOOLTRANSLATE);
        return true;
    }
    if (mask != MASK_NONE) return false;
    mHover = pick(x, y);
    if (mHover.joint.empty()) return false;
    gViewerWindow->setCursor(mHover.part >= ROTATE_X ? UI_CURSOR_TOOLROTATE : UI_CURSOR_TOOLTRANSLATE);
    return true;
}

bool LLToolPoseIK::handleMouseUp(S32 x, S32 y, MASK)
{
    if (!hasMouseCapture()) return false;
    drag(x, y);
    setMouseCapture(false);
    clearHover();
    return true;
}

bool LLToolPoseIK::handleKey(KEY key, MASK)
{
    if (!hasMouseCapture() || key != KEY_ESCAPE) return false;
    setMouseCapture(false);
    clearHover();
    return true;
}

void LLToolPoseIK::render()
{
    if (!available())
    {
        setMouseCapture(false);
        clearHover();
        return;
    }
    // Never bake editor handles into a photo, even with Include UI enabled.
    if (gSnapshot || !gDisplaySwapBuffers) return;
    gViewerWindow->setup2DRender();
    gUIProgram.bind();
    gGL.getTexUnit(0)->unbind(LLTexUnit::TT_TEXTURE);
    gGL.pushMatrix();
    const LLVector2 scale = gViewerWindow->getDisplayScale();
    gGL.scalef(scale.mV[VX], scale.mV[VY], 1.f);
    const LLColor4 normal = LLUIColorTable::instance().getColor("PoseStudioBoneColor");
    const LLColor4 active = LLUIColorTable::instance().getColor("PoseStudioEditedBoneColor");
    LLPoseStudio::BonePose selected;
    if (selectedPose(selected))
    {
        const LLColor4 colors[] = {LLColor4(0.96f, 0.35f, 0.32f, 1.f), LLColor4(0.40f, 0.86f, 0.48f, 1.f), LLColor4(0.35f, 0.63f, 1.f, 1.f)};
        const auto segments = gizmoSegments(selected.position, gizmoRotation(selected.rotation));
        // A dark outline keeps axes readable against both sky and clothing.
        for (S32 pass = 0; pass < 2; ++pass)
        {
            gGL.setLineWidth(pass == 0 ? 4.f : 2.f);
            gGL.begin(LLRender::LINES);
            for (const auto& segment : segments)
            {
                const S32 axis = (segment.part - 1) % 3;
                const LLColor4 color = pass == 0 ? LLColor4(0.025f, 0.03f, 0.035f, 0.8f) :
                    (highlighted(selected.name, segment.part) ? normal : colors[axis]);
                gGL.color4fv(color.mV);
                gGL.vertex2f(segment.start.mV[VX], segment.start.mV[VY]);
                gGL.vertex2f(segment.end.mV[VX], segment.end.mV[VY]);
            }
            gGL.end();
            gGL.flush();
        }
        gGL.setLineWidth(1.f);
        LLVector2 center;
        if (mSelectedLimb < 0 && projectHandle(selected.position, center))
        {
            gGL.color4f(0.035f, 0.045f, 0.05f, 0.85f);
            gl_circle_2d(center.mV[VX], center.mV[VY], HANDLE_RADIUS + 2.f, 32, true);
            const bool hover = highlighted(selected.name, 0);
            gGL.setLineWidth(hover ? 3.f : 1.f);
            gGL.color4fv((hover ? normal : active).mV);
            gl_circle_2d(center.mV[VX], center.mV[VY], HANDLE_RADIUS, 32, false);
            gGL.setLineWidth(1.f);
        }
    }
    for (S32 limb = 0; limb < 4; ++limb)
    {
        LLPoseStudio::IKPose pose;
        LLVector2 point;
        if (!LLPoseStudio::instance().getIKPose(limb, pose) || !projectHandle(pose.positions[2], point)) continue;
        gGL.color4f(0.035f, 0.045f, 0.05f, 0.85f);
        gl_circle_2d(point.mV[VX], point.mV[VY], HANDLE_RADIUS + 2.f, 32, true);
        const bool hover = highlighted(LLPoseStudio::getIKJointName(limb), 0);
        gGL.setLineWidth(hover ? 3.f : 1.f);
        gGL.color4fv((hover || limb == mSelectedLimb ? active : normal).mV);
        gl_circle_2d(point.mV[VX], point.mV[VY], HANDLE_RADIUS, 32, false);
        // Hands use a cross, feet a small square; both remain easy to pick.
        if (limb < 2)
        {
            gl_line_2d(ll_round(point.mV[VX] - 4), ll_round(point.mV[VY]), ll_round(point.mV[VX] + 4), ll_round(point.mV[VY]));
            gl_line_2d(ll_round(point.mV[VX]), ll_round(point.mV[VY] - 4), ll_round(point.mV[VX]), ll_round(point.mV[VY] + 4));
        }
        else gl_rect_2d(ll_round(point.mV[VX] - 3), ll_round(point.mV[VY] + 3), ll_round(point.mV[VX] + 3), ll_round(point.mV[VY] - 3), false);
        gGL.setLineWidth(1.f);
    }
    gGL.popMatrix();
    gGL.flush();
    gUIProgram.unbind();
}
