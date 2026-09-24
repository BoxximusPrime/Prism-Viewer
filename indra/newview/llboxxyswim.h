/**
 * @file llboxxyswim.h
 * @brief Optional swimming controller using existing simulator flight controls.
 */
#ifndef LL_LLBOXXYSWIM_H
#define LL_LLBOXXYSWIM_H

namespace LLBoxxySwim
{
    // Run after input collection and before sending/resetting agent controls.
    void update();
    bool isSwimming();
    void onFlightDisabled();
}

#endif
