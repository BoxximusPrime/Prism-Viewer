/**
 * @file llpanelboxxynowplaying.cpp
 * @brief Passive parcel music status card.
 * Copyright (C) 2026 Boxxy Viewer contributors.
 * $LicenseInfo:firstyear=2026&license=viewerlgpl$
 * $/LicenseInfo$
 */
#include "llviewerprecompiledheaders.h"
#include "llpanelboxxynowplaying.h"

#include "llaudioengine.h"
#include "llclipboard.h"
#include "llrender.h"
#include "llslider.h"
#include "llstartup.h"
#include "lltextbox.h"
#include "lluicolortable.h"
#include "llviewercontrol.h"
#include "llviewermedia_streamingaudio.h"

#include <cmath>

LLPanelBoxxyNowPlaying::LLPanelBoxxyNowPlaying()
{
    buildFromFile("panel_boxxy_now_playing.xml");
}

bool LLPanelBoxxyNowPlaying::postBuild()
{
    mTitle = getChild<LLTextBox>("track_title");
    mURL = getChild<LLTextBox>("stream_url");
    mTime = getChild<LLTextBox>("elapsed");
    mState = getChild<LLTextBox>("playback_state");
    mVolume = getChild<LLSlider>("music_volume");
    mTitle->setClickedCallback([this](void*)
    {
        const LLWString text = utf8str_to_wstring(mTitle->getText());
        LLClipboard::instance().copyToClipboard(text, 0, static_cast<S32>(text.size()));
    });
    mURL->setClickedCallback([this](void*)
    {
        const LLWString text = utf8str_to_wstring(mURL->getText());
        LLClipboard::instance().copyToClipboard(text, 0, static_cast<S32>(text.size()));
    });
    mVolume->setCommitCallback([](LLUICtrl*, const LLSD&)
    {
        gSavedSettings.setBOOL("MuteMusic", false);
    });
    return true;
}

void LLPanelBoxxyNowPlaying::draw()
{
    // Keep the view registered so playback can make it appear again.
    auto* stream = gAudiop ? dynamic_cast<LLStreamingAudio_MediaPlugins*>(gAudiop->getStreamingAudioImpl()) : nullptr;
    const bool active = gSavedSettings.getBOOL("BoxxyShowNowPlaying") &&
                        LLStartUp::getStartupState() == STATE_STARTED && stream && stream->hasPlaybackStarted();
    mTitle->setVisible(active);
    mURL->setVisible(active);
    mVolume->setVisible(active);
    if (!active) return;

    // Keep the rightmost 400 UI pixels clear for notification toasts. Clamp on
    // smaller windows so the card remains entirely on screen.
    const LLRect parent_rect = getParent()->getLocalRect();
    const S32 width = llmin(300, llmax(1, parent_rect.getWidth() - 24));
    const S32 left = llmax(12, parent_rect.getWidth() - 400 - width);
    const S32 top = llmax(138, parent_rect.getHeight() - 62);
    const LLRect old_rect = getRect();
    setShape(LLRect(left, top, left + width, top - 126));

    const bool paused = stream->isPlaying() == LLAudioEngine::AUDIO_PAUSED;
    const std::string title = stream->getTrackTitle().empty() ? getString("no_title") : stream->getTrackTitle();
    std::string url = stream->getURL();
    LLStringUtil::trim(url);
    url = url.substr(0, url.find(' '));
    const U64 seconds = static_cast<U64>(stream->getPlaybackSeconds());
    const std::string time = seconds >= 3600
        ? llformat("%llu:%02llu:%02llu", seconds / 3600, (seconds / 60) % 60, seconds % 60)
        : llformat("%02llu:%02llu", seconds / 60, seconds % 60);
    if (mTitle->getText() != title) mTitle->setText(title);
    if (mURL->getText() != url) mURL->setText(url);
    if (mTime->getText() != time) mTime->setText(time);
    mTitle->setToolTip(getString("copy_title") + title);
    mURL->setToolTip(getString("copy_url") + url);
    const std::string state = getString(paused ? "paused" : "playing");
    if (mState->getText() != state) mState->setText(state);
    // Parent drawing has already translated to the previous position.
    LLUI::pushMatrix();
    LLUI::translate(static_cast<F32>(getRect().mLeft - old_rect.mLeft),
                    static_cast<F32>(getRect().mBottom - old_rect.mBottom));
    LLPanel::draw();

    const LLColor4 accent = LLUIColorTable::instance().getColor("BoxxyRadarNearColor").get();
    const LLColor4 border = LLUIColorTable::instance().getColor("LtGray").get();
    gl_rect_2d(getLocalRect(), border % 0.65f, false);
    // Decorative playback bars, deliberately independent of audio amplitude.
    const F64 phase = stream->getPlaybackSeconds();
    gGL.getTexUnit(0)->unbind(LLTexUnit::TT_TEXTURE);
    gGL.color4fv(accent.mV);
    gGL.begin(LLRender::TRIANGLES);
    for (S32 i = 0; i < 7; ++i)
    {
        const F32 height = paused ? 3.f : 4.f + 11.f * static_cast<F32>(
            0.5 + 0.5 * std::sin(phase * (3.5 + i * 0.37) + i * 1.8));
        const F32 x = 16.f + i * 6.f;
        gGL.vertex2f(x, 13.f); gGL.vertex2f(x + 3.f, 13.f);
        gGL.vertex2f(x + 3.f, 13.f + height);
        gGL.vertex2f(x, 13.f); gGL.vertex2f(x + 3.f, 13.f + height); gGL.vertex2f(x, 13.f + height);
    }
    gGL.end();
    LLUI::popMatrix();
}
