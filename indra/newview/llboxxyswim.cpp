/**
 * @file llboxxyswim.cpp
 * @brief Experimental swimming in Linden water, without simulator extensions.
 */
#include "llviewerprecompiledheaders.h"

#include "llboxxyswim.h"
#include "llswimpolicy.h"

#include "llagent.h"
#include "llagentcamera.h"
#include "llappviewer.h"
#include "llboxxyao.h"
#include "llcharacter.h"
#include "lljointstate.h"
#include "llmotion.h"
#include "llposestudio.h"
#include "llviewercontrol.h"
#include "llviewerregion.h"
#include "llvoavatarself.h"
#include "llworld.h"

#include <array>
#include <cmath>

namespace
{
LLSwimPolicy sPolicy;

bool movementControlsGrabbed()
{
    // A listener using PassToAgent still permits normal movement. In
    // particular, attachment mouse listeners must not disable swimming.
    // Yield only when a script actually consumes locomotion controls.
    static constexpr S32 controls[] = {
        CONTROL_AT_POS_INDEX, CONTROL_AT_NEG_INDEX,
        CONTROL_LEFT_POS_INDEX, CONTROL_LEFT_NEG_INDEX,
        CONTROL_UP_POS_INDEX, CONTROL_UP_NEG_INDEX,
        CONTROL_PITCH_POS_INDEX, CONTROL_PITCH_NEG_INDEX,
        CONTROL_YAW_POS_INDEX, CONTROL_YAW_NEG_INDEX,
        CONTROL_FLY_INDEX, CONTROL_STOP_INDEX,
        CONTROL_NUDGE_AT_POS_INDEX, CONTROL_NUDGE_AT_NEG_INDEX,
        CONTROL_NUDGE_LEFT_POS_INDEX, CONTROL_NUDGE_LEFT_NEG_INDEX,
        CONTROL_NUDGE_UP_POS_INDEX, CONTROL_NUDGE_UP_NEG_INDEX,
        CONTROL_TURN_LEFT_INDEX, CONTROL_TURN_RIGHT_INDEX
    };
    for (S32 control : controls)
    {
        if (gAgent.isControlGrabbed(control)) return true;
    }
    return false;
}

// A procedural, self-only fallback. Never request this UUID from the simulator:
// other viewers have no asset for it. Inventory-backed AO swimming still uses
// the normal shared animation path and takes precedence once it is playing.
const LLUUID SWIM_MOTION_ID("139840b0-c9a6-41fb-a067-bdd69b9200ee");

class LLSwimMotion final : public LLMotion
{
public:
    explicit LLSwimMotion(const LLUUID& id) : LLMotion(id) { mName = "prism_swimming"; }
    static LLMotion* create(const LLUUID& id) { return new LLSwimMotion(id); }

    bool getLoop() override { return true; }
    F32 getDuration() override { return 0.f; }
    F32 getEaseInDuration() override { return 0.35f; }
    F32 getEaseOutDuration() override { return 0.35f; }
    LLJoint::JointPriority getPriority() override { return LLJoint::HIGHEST_PRIORITY; }
    LLMotionBlendType getBlendType() override { return NORMAL_BLEND; }
    F32 getMinPixelArea() override { return 0.f; }

    LLMotionInitStatus onInitialize(LLCharacter* character) override
    {
        static const char* const names[] = {
            "mPelvis", "mTorso", "mChest", "mNeck", "mHead",
            "mCollarLeft", "mCollarRight", "mShoulderLeft", "mShoulderRight",
            "mElbowLeft", "mElbowRight", "mWristLeft", "mWristRight",
            "mHipLeft", "mHipRight", "mKneeLeft", "mKneeRight",
            "mAnkleLeft", "mAnkleRight"
        };
        for (size_t i = 0; i < mJoints.size(); ++i)
        {
            mJoints[i] = new LLJointState;
            if (!mJoints[i]->setJoint(character->getJoint(names[i])))
            {
                return STATUS_FAILURE;
            }
            mJoints[i]->setUsage(LLJointState::ROT);
            addJointState(mJoints[i]);
        }
        return STATUS_SUCCESS;
    }

    bool onActivate() override
    {
        mLastTime = mBlend = mPitch = 0.f;
        return true;
    }

    bool onUpdate(F32 time, U8*) override
    {
        if (!isAgentAvatarValid()) return true; // Lifetime/stop is managed locally by update().
        const LLVector3 velocity = gAgent.getVelocity();
        const F32 horizontal = std::hypot(velocity.mV[VX], velocity.mV[VY]);
        const F32 blend = llclamp(velocity.length() / 1.4f, 0.f, 1.f);
        const F32 dt = llclamp(time - mLastTime, 0.f, 0.2f);
        mLastTime = time;
        const F32 ease = 1.f - std::exp(-dt / 0.25f);
        mBlend += (blend - mBlend) * ease;
        const F32 pitch = mBlend * llclamp(65.f - RAD_TO_DEG *
            std::atan2(velocity.mV[VZ], llmax(horizontal, 0.5f)), 0.f, 115.f);
        mPitch += (pitch - mPitch) * ease;
        const F32 stroke = std::sin(time * F_TWO_PI / 1.8f);
        const F32 kick = std::sin(time * F_TWO_PI / 0.9f);

        // Neutralize the stock flying pose, then blend upright sculling into
        // a prone arm stroke and flutter kick. Pitch follows actual velocity,
        // never the camera, so looking around does not steer the swimmer.
        for (auto& joint : mJoints) joint->setRotation(LLQuaternion::DEFAULT);
        rotate(0, 0.f, mPitch, 0.f);
        rotate(3, 0.f, -0.18f * mPitch, 0.f);
        rotate(4, 0.f, -0.12f * mPitch, 0.f);
        for (size_t side = 0; side < 2; ++side)
        {
            const F32 sign = side == 0 ? 1.f : -1.f;
            const F32 arm = -50.f + mBlend * (120.f + 30.f * stroke);
            rotate(7 + side, sign * arm, 0.f, -sign * (25.f + 20.f * stroke));
            rotate(9 + side, 0.f, 0.f, -sign * (35.f - 20.f * stroke));
            rotate(11 + side, sign * 10.f, 0.f, 0.f);
            rotate(13 + side, sign * (8.f - 5.f * mBlend),
                -12.f + sign * kick * (10.f + 12.f * mBlend), 0.f);
            rotate(15 + side, 0.f, 20.f + 15.f * (1.f - sign * kick), 0.f);
            rotate(17 + side, 0.f, -15.f, 0.f);
        }
        return true;
    }

    void onDeactivate() override {}

private:
    void rotate(size_t joint, F32 x, F32 y, F32 z)
    {
        LLQuaternion rotation;
        rotation.setEulerAngles(x * DEG_TO_RAD, y * DEG_TO_RAD, z * DEG_TO_RAD);
        mJoints[joint]->setRotation(rotation);
    }

    std::array<LLPointer<LLJointState>, 19> mJoints;
    F32 mLastTime = 0.f;
    F32 mBlend = 0.f;
    F32 mPitch = 0.f;
};

bool aoSwimIsPlaying()
{
    LLBoxxyAO& ao = LLBoxxyAO::instance();
    const LLBoxxyAO::State* state = ao.getCurrentState();
    if (!ao.isEnabled() || !state || state->type < LLBoxxyAO::STATE_FLOATING ||
        state->current_asset.isNull()) return false;
    LLMotion* motion = gAgentAvatarp->findMotion(state->current_asset);
    return motion && gAgentAvatarp->getMotionController().isMotionActive(motion) && !motion->isStopped();
}

void updateAnimation()
{
    if (!isAgentAvatarValid()) return;
    LLMotionController& controller = gAgentAvatarp->getMotionController();
    LLMotion* motion = controller.findMotion(SWIM_MOTION_ID);
    if (sPolicy.swimming() && !aoSwimIsPlaying())
    {
        if (!motion)
        {
            gAgentAvatarp->registerMotion(SWIM_MOTION_ID, LLSwimMotion::create);
        }
        if (!motion || !controller.isMotionActive(motion) || motion->isStopped())
        {
            gAgentAvatarp->LLCharacter::startMotion(SWIM_MOTION_ID);
        }
    }
    else if (motion && controller.isMotionActive(motion) && !motion->isStopped())
    {
        controller.stopMotionWithEaseOut(SWIM_MOTION_ID);
    }
}

int direction(U32 controls, U32 positive, U32 negative)
{
    return int((controls & positive) != 0) - int((controls & negative) != 0);
}
}

bool LLBoxxySwim::isSwimming()
{
    return sPolicy.swimming();
}

void LLBoxxySwim::onFlightDisabled()
{
    sPolicy.flightDisabled();
}

void LLBoxxySwim::update()
{
    static LLCachedControl<bool> enabled(gSavedSettings, "BoxxyExperimentalSwimming");
    LLSwimPolicy::Input input;
    input.enabled = enabled;
    LLViewerRegion* region = gAgent.getRegion();
    input.ready = isAgentAvatarValid() && region && !gDisconnected &&
        !LLAppViewer::instance()->logoutRequestSent() &&
        gAgent.getTeleportState() == LLAgent::TELEPORT_NONE;
    input.flying = gAgent.getFlying();
    const U32 controls = gAgent.getControlFlags();
    const char* status = input.enabled ? "not ready" : "disabled";
    if (input.enabled && input.ready)
    {
        status = nullptr;
        if (!gAgent.canFly()) status = "flight not permitted";
        else if (gAgentAvatarp->isSitting() || gAgentAvatarp->getParent()) status = "sitting";
        else if (gAgent.isMovementLocked()) status = "movement locked";
        else if (movementControlsGrabbed()) status = "script consumes movement controls";
        else if (gAgent.getAutoPilot()) status = "autopilot";
        else if (gAgentCamera.cameraCustomizeAvatar()) status = "editing appearance";
        else if (LLPoseStudio::instanceExists() && LLPoseStudio::instance().isActiveFor(*gAgentAvatarp))
            status = "pose studio";
        input.allowed = status == nullptr;
        input.in_air = gAgentAvatarp->mInAir;
        input.height = gAgentAvatarp->mBodySize.mV[VZ] + gAgentAvatarp->mAvatarOffset.mV[VZ];
        const LLVector3d position = gAgent.getPositionGlobal();
        input.depth = region->getWaterHeight() - F32(position.mdV[VZ]);
        input.ground_depth = region->getWaterHeight() - LLWorld::getInstance()->resolveLandHeightGlobal(position);
        const LLVector3 velocity = gAgent.getVelocity() * ~gAgent.getQuat();
        input.forward_velocity = velocity.mV[VX];
        input.left_velocity = velocity.mV[VY];
        input.up_velocity = gAgent.getVelocity().mV[VZ];
        input.forward = direction(controls, AGENT_CONTROL_AT_POS | AGENT_CONTROL_NUDGE_AT_POS,
            AGENT_CONTROL_AT_NEG | AGENT_CONTROL_NUDGE_AT_NEG);
        input.left = direction(controls, AGENT_CONTROL_LEFT_POS | AGENT_CONTROL_NUDGE_LEFT_POS,
            AGENT_CONTROL_LEFT_NEG | AGENT_CONTROL_NUDGE_LEFT_NEG);
        input.up = direction(controls, AGENT_CONTROL_UP_POS | AGENT_CONTROL_NUDGE_UP_POS,
            AGENT_CONTROL_UP_NEG | AGENT_CONTROL_NUDGE_UP_NEG);
        input.stop = (controls & AGENT_CONTROL_STOP) != 0;
    }

    const LLSwimPolicy::Output output = sPolicy.update(input);
    if (output.flight == LLSwimPolicy::Flight::START)
    {
        gAgent.setFlying(true);
        if (!gAgent.getFlying())
        {
            // Stand-up animation can temporarily reject takeoff. Retry once
            // the normal flight path permits it, without latching a user stop.
            sPolicy = LLSwimPolicy();
            status = "takeoff deferred";
        }
    }
    else if (output.flight == LLSwimPolicy::Flight::STOP)
    {
        gAgent.setFlying(false);
    }

    if (sPolicy.swimming())
    {
        gAgent.clearControlFlags(AGENT_CONTROL_FAST_AT | AGENT_CONTROL_FAST_LEFT | AGENT_CONTROL_FAST_UP |
            AGENT_CONTROL_AT_POS | AGENT_CONTROL_AT_NEG | AGENT_CONTROL_NUDGE_AT_POS | AGENT_CONTROL_NUDGE_AT_NEG |
            AGENT_CONTROL_LEFT_POS | AGENT_CONTROL_LEFT_NEG | AGENT_CONTROL_NUDGE_LEFT_POS | AGENT_CONTROL_NUDGE_LEFT_NEG |
            AGENT_CONTROL_UP_POS | AGENT_CONTROL_UP_NEG | AGENT_CONTROL_NUDGE_UP_POS | AGENT_CONTROL_NUDGE_UP_NEG);
        // NUDGE was not a slow-flight mode in SL: horizontal movement still
        // reached flight speed, while ascent/dive barely moved. Keep ordinary
        // controls; clearing FAST is not a swimming-speed cap either.
        if (output.forward) gAgent.setControlFlags(output.forward > 0 ? AGENT_CONTROL_AT_POS : AGENT_CONTROL_AT_NEG);
        if (output.left) gAgent.setControlFlags(output.left > 0 ? AGENT_CONTROL_LEFT_POS : AGENT_CONTROL_LEFT_NEG);
        if (output.up) gAgent.setControlFlags(output.up > 0 ? AGENT_CONTROL_UP_POS : AGENT_CONTROL_UP_NEG);
    }
    updateAnimation();

    if (!status)
    {
        if (sPolicy.swimming()) status = "swimming";
        else if (input.ground_depth < 0.8f * llmax(0.2f, input.height)) status = "water too shallow";
        else if (input.depth <= 0.2f * llmax(0.2f, input.height)) status = "not submerged";
        else status = "waiting for water re-entry or option toggle";
    }
    static std::string last_status;
    if (last_status != status)
    {
        last_status = status;
        LL_INFOS("Swimming") << status << "; depth=" << input.depth
            << "; ground_depth=" << input.ground_depth << "; height=" << input.height
            << "; in_air=" << input.in_air << "; flying=" << gAgent.getFlying()
            << "; forward_speed=" << input.forward_velocity << "; strafe_speed=" << input.left_velocity
            << "; vertical_speed=" << input.up_velocity << LL_ENDL;
    }
}
