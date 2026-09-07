/**
 * @file llpanelboxxynowplaying.h
 * @brief Passive parcel music status card.
 * Copyright (C) 2026 Boxxy Viewer contributors.
 * $LicenseInfo:firstyear=2026&license=viewerlgpl$
 * $/LicenseInfo$
 */
#ifndef LL_LLPANELBOXXYNOWPLAYING_H
#define LL_LLPANELBOXXYNOWPLAYING_H

#include "llpanel.h"

class LLTextBox;
class LLSlider;

class LLPanelBoxxyNowPlaying final : public LLPanel
{
public:
    LLPanelBoxxyNowPlaying();
    bool postBuild() override;
    void draw() override;

private:
    LLTextBox* mTitle = nullptr;
    LLTextBox* mURL = nullptr;
    LLTextBox* mTime = nullptr;
    LLTextBox* mState = nullptr;
    LLSlider* mVolume = nullptr;
};

#endif
