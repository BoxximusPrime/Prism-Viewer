/**
 * @file llviewermedia_streamingaudio.h
 * @author Tofu Linden, Sam Kolb
 * @brief LLStreamingAudio_MediaPlugins implementation - an implementation of the streaming audio interface which is implemented as a client of the media plugin API.
 *
 * $LicenseInfo:firstyear=2009&license=viewerlgpl$
 * Second Life Viewer Source Code
 * Copyright (C) 2010, Linden Research, Inc.
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation;
 * version 2.1 of the License only.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with this library; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA
 *
 * Linden Research, Inc., 945 Battery Street, San Francisco, CA  94111  USA
 * $/LicenseInfo$
 */
#include "llviewerprecompiledheaders.h"
#include "linden_common.h"
#include "llpluginclassmedia.h"
#include "llpluginclassmediaowner.h"
#include "llviewermedia.h"

#include "llviewermedia_streamingaudio.h"

#include "llmimetypes.h"
#include "lldir.h"
#include "llchat.h"
#include "llnotificationmanager.h"
#include "llnotificationsutil.h"
#include "llviewercontrol.h"
#include "lltrans.h"

LLStreamingAudio_MediaPlugins::LLStreamingAudio_MediaPlugins() :
    mMediaPlugin(NULL),
    mGain(1.0)
{
    // nothing interesting to do?
    // we will lazily create a media plugin at play-time, if none exists.
}

LLStreamingAudio_MediaPlugins::~LLStreamingAudio_MediaPlugins()
{
    delete mMediaPlugin;
    mMediaPlugin = NULL;
}

void LLStreamingAudio_MediaPlugins::start(const std::string& url)
{
    stop();
    mFailed = false;
    mError.clear();
    mLastTitle.clear();
    if (url.empty())
        return;

    mURL = url;
    mConnecting = true;
    mConnectTimer.reset();
    mMediaPlugin = initializeMedia("audio/mpeg"); // VLC also handles AAC and Vorbis streams.

    if(!mMediaPlugin)
    {
        reportError(LLTrans::getString("MusicPluginUnavailable"));
        return;
    }

    LL_INFOS() << "Starting internet stream: " << url << LL_ENDL;
    std::string snt_url = url;
    LLStringUtil::trim(snt_url);
    size_t pos = snt_url.find(' ');
    if (pos != std::string::npos)
    {
        // Preserve support for parcel URLs with a human-readable label after a space.
        snt_url = snt_url.substr(0, pos);
    }
    mMediaPlugin->loadURI(snt_url);
    mMediaPlugin->setVolume(mGain);
    mMediaPlugin->start();
}

void LLStreamingAudio_MediaPlugins::stop()
{
    mPlaybackSeconds = 0.0;
    mPlaybackRunning = false;
    mPlaybackStarted = false;
    mLastTitle.clear();
    mConnecting = false;
    LL_INFOS() << "Stopping internet stream." << LL_ENDL;
    if(mMediaPlugin)
    {
        mMediaPlugin->stop();
        delete mMediaPlugin;
        mMediaPlugin = nullptr;
    }

    mURL.clear();
}

void LLStreamingAudio_MediaPlugins::pause(int pause)
{
    if(!mMediaPlugin)
        return;

    if(pause)
    {
        LL_INFOS() << "Pausing internet stream." << LL_ENDL;
        mMediaPlugin->pause();
    }
    else
    {
        LL_INFOS() << "Unpausing internet stream." << LL_ENDL;
        mMediaPlugin->start();
    }
}

void LLStreamingAudio_MediaPlugins::update()
{
    if (mMediaPlugin)
    {
        mMediaPlugin->idle();
        if (mPlaybackRunning)
            mPlaybackSeconds += mPlaybackTimer.getElapsedTimeF64();
        mPlaybackTimer.reset();
        mPlaybackRunning = !mFailed && mMediaPlugin->getStatus() == MEDIA_PLAYING;
        mPlaybackStarted = mPlaybackStarted || mPlaybackRunning;
        if (!mFailed && !mURL.empty())
        {
            const auto status = mMediaPlugin->getStatus();
            if (status == MEDIA_ERROR)
                reportError(mMediaPlugin->getStatusText().empty() ? LLTrans::getString("MusicPlaybackFailed") : mMediaPlugin->getStatusText());
            else if (status == MEDIA_DONE)
                reportError(LLTrans::getString("MusicStreamEnded"));
            else if (status == MEDIA_PLAYING || status == MEDIA_PAUSED)
                mConnecting = false;
            else if (mConnecting && mConnectTimer.getElapsedTimeF32() > 30.f)
                reportError(LLTrans::getString("MusicConnectionTimeout"));

            if (!mFailed && status == MEDIA_PLAYING)
            {
                std::string title = mMediaPlugin->getMediaName();
                LLStringUtil::trim(title);
                if (title.empty()) mLastTitle.clear();
                if (!title.empty() && title != "LibVLC Plugin" && title != mURL && title != mLastTitle)
                {
                    mLastTitle = title;
                    if (gSavedSettings.getBOOL("ShowStreamMetadata"))
                    {
                        LLSD args;
                        args["TITLE"] = title;
                        LLChat chat(LLTrans::getString("MusicNowPlaying", args));
                        chat.mSourceType = CHAT_SOURCE_SYSTEM;
                        LLNotificationsUI::LLNotificationManager::instance().onChat(chat, LLSD());
                    }
                }
            }
        }
        // Do not delete the plugin from inside one of its event callbacks.
        if (mFailed)
        {
            delete mMediaPlugin;
            mMediaPlugin = nullptr;
        }
    }
}

void LLStreamingAudio_MediaPlugins::reportError(const std::string& reason)
{
    if (mFailed) return;
    mFailed = true;
    mConnecting = false;
    mError = reason;
    LLSD args;
    args["REASON"] = reason;
    LLNotificationsUtil::add("MusicStreamError", args);
    LL_WARNS("AudioEngine") << "Streaming audio failed: " << reason << LL_ENDL;
}

void LLStreamingAudio_MediaPlugins::handleMediaEvent(LLPluginClassMedia*, EMediaEvent event)
{
    if (event == MEDIA_EVENT_PLUGIN_FAILED_LAUNCH)
        reportError(LLTrans::getString("MusicPluginUnavailable"));
    else if (event == MEDIA_EVENT_PLUGIN_FAILED)
        reportError(LLTrans::getString("MusicPluginCrashed"));
}

std::string LLStreamingAudio_MediaPlugins::getStatusText() const
{
    if (mFailed) return mError;
    if (mConnecting) return LLTrans::getString("MusicConnecting");
    if (!mLastTitle.empty()) return mLastTitle;
    return std::string();
}

F64 LLStreamingAudio_MediaPlugins::getPlaybackSeconds() const
{
    return mPlaybackSeconds + (mPlaybackRunning ? static_cast<F64>(mPlaybackTimer.getElapsedTimeF64()) : 0.0);
}

int LLStreamingAudio_MediaPlugins::isPlaying()
{
    if (!mMediaPlugin || mFailed)
        return 0; // stopped

    if (mConnecting) return 1;

    LLPluginClassMediaOwner::EMediaStatus status =
        mMediaPlugin->getStatus();

    switch (status)
    {
    case LLPluginClassMediaOwner::MEDIA_LOADING: // but not MEDIA_LOADED
    case LLPluginClassMediaOwner::MEDIA_PLAYING:
        return 1; // Active and playing
    case LLPluginClassMediaOwner::MEDIA_PAUSED:
        return 2; // paused
    default:
        return 0; // stopped
    }
}

void LLStreamingAudio_MediaPlugins::setGain(F32 vol)
{
    mGain = vol;

    if(!mMediaPlugin)
        return;

    vol = llclamp(vol, 0.f, 1.f);
    mMediaPlugin->setVolume(vol);
}

F32 LLStreamingAudio_MediaPlugins::getGain()
{
    return mGain;
}

std::string LLStreamingAudio_MediaPlugins::getURL()
{
    return mURL;
}

LLPluginClassMedia* LLStreamingAudio_MediaPlugins::initializeMedia(const std::string& media_type)
{
    LLPluginClassMediaOwner* owner = this;
    S32 default_size = 1; // audio-only - be minimal, doesn't matter
    F64 default_zoom = 1.0;
    LLPluginClassMedia* media_source = LLViewerMediaImpl::newSourceFromMediaType(media_type, owner, default_size, default_size, default_zoom);

    if (media_source)
    {
        media_source->setLoop(false); // audio streams are not expected to loop
    }

    return media_source;
}
