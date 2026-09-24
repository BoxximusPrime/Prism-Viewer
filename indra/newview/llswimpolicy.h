/**
 * @file llswimpolicy.h
 * @brief Simulator-independent decisions for experimental Linden-water swimming.
 */
#ifndef LL_LLSWIMPOLICY_H
#define LL_LLSWIMPOLICY_H

#include <algorithm>

class LLSwimPolicy
{
public:
    struct Input
    {
        bool enabled = false;
        bool ready = false;
        bool allowed = false;
        bool flying = false;
        bool in_air = false;
        bool stop = false;
        float height = 2.f;
        float depth = 0.f; // Water height minus the physical avatar's center.
        float ground_depth = 0.f; // Water height minus terrain height.
        float forward_velocity = 0.f; // Diagnostics only; never pulse held movement to cap speed.
        float left_velocity = 0.f;
        float up_velocity = 0.f;
        int forward = 0;
        int left = 0;
        int up = 0;
    };

    enum class Flight { KEEP, START, STOP };
    struct Output
    {
        Flight flight = Flight::KEEP;
        int forward = 0;
        int left = 0;
        int up = 0;
    };

    bool swimming() const { return mSwimming; }

    // An explicit Stop Flying/Walk choice must not be undone on the next frame.
    void flightDisabled()
    {
        if (mSwimming)
        {
            mSuppressed = true;
            mSwimming = mOwnsFlight = false;
        }
    }

    Output update(const Input& in)
    {
        Output out{Flight::KEEP, in.forward, in.left, in.up};
        const float height = std::max(0.2f, in.height);
        if (!in.enabled || !in.ready)
        {
            out.flight = leave();
            mSuppressed = false;
            return out;
        }

        const bool shallow = in.ground_depth < 0.8f * height;
        if (in.depth <= 0.f || shallow)
        {
            mSuppressed = false;
        }
        if (mSwimming && !in.flying)
        {
            flightDisabled();
        }
        if (!in.allowed || shallow || in.depth < -0.1f * height)
        {
            out.flight = leave();
            return out;
        }
        if (mSwimming)
        {
            mLeftGround = mLeftGround || in.in_air;
            if (mLeftGround && !in.in_air)
            {
                out.flight = leave();
                mSuppressed = true;
                return out;
            }
        }
        else if (!mSuppressed && in.depth > 0.2f * height)
        {
            mSwimming = true;
            mOwnsFlight = !in.flying;
            mLeftGround = in.in_air;
            mSurface = false;
            out.flight = mOwnsFlight ? Flight::START : Flight::KEEP;
        }

        if (!mSwimming || in.stop)
        {
            return out;
        }

        // Keep held directions continuous; this does not cap simulator speed.
        // Dropping direction flags to cap speed creates accelerate/coast cycles
        // and simulator fly/hover animation changes.

        const float surface_depth = 0.22f * height;
        const float predicted_depth = in.depth - 0.25f * in.up_velocity;
        if (in.up < 0)
        {
            mSurface = false; // Crouch always permits a deliberate dive.
        }
        else if (in.depth < 0.4f * height)
        {
            mSurface = true;
        }
        else if (in.depth > 0.65f * height)
        {
            mSurface = false;
        }
        if (in.up >= 0 && mSurface)
        {
            // Hold the surface with ordinary up/down controls. At depth,
            // neutral input holds the current depth using flight's hover.
            const float error = predicted_depth - surface_depth;
            const float tolerance = std::min(0.12f, 0.06f * height);
            out.up = error > tolerance ? 1 : (error < -tolerance ? -1 : 0);
        }
        return out;
    }

private:
    Flight leave()
    {
        const Flight flight = mSwimming && mOwnsFlight ? Flight::STOP : Flight::KEEP;
        mSwimming = mOwnsFlight = false;
        return flight;
    }

    bool mSwimming = false;
    bool mOwnsFlight = false;
    bool mSuppressed = false;
    bool mLeftGround = false;
    bool mSurface = false;
};

#endif
