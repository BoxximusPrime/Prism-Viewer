/**
 * @file llviewermedia_streamingaudio.h
 * @author Tofu Linden
 * @brief Definition of LLStreamingAudio_MediaPlugins implementation - an implementation of the streaming audio interface which is implemented as a client of the media plugins API.
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

#ifndef LL_VIEWERMEDIA_STREAMINGAUDIO_H
#define LL_VIEWERMEDIA_STREAMINGAUDIO_H


#include "stdtypes.h" // from llcommon

#include "llstreamingaudio.h"
#include "llpluginclassmediaowner.h"
#include "lltimer.h"

class LLPluginClassMedia;

class LLStreamingAudio_MediaPlugins : public LLStreamingAudioInterface, public LLPluginClassMediaOwner
{
 public:
    LLStreamingAudio_MediaPlugins();
    /*virtual*/ ~LLStreamingAudio_MediaPlugins();

    /*virtual*/ void start(const std::string& url);
    /*virtual*/ void stop();
    /*virtual*/ void pause(int pause);
    /*virtual*/ void update();
    /*virtual*/ int isPlaying();
    /*virtual*/ void setGain(F32 vol);
    /*virtual*/ F32 getGain();
    /*virtual*/ std::string getURL();
    void handleMediaEvent(LLPluginClassMedia* self, EMediaEvent event) override;
    std::string getStatusText() const override;
    bool hasPlaybackStarted() const { return mPlaybackStarted && mMediaPlugin && !mFailed; }
    const std::string& getTrackTitle() const { return mLastTitle; }
    F64 getPlaybackSeconds() const;

private:
    LLPluginClassMedia* initializeMedia(const std::string& media_type);
    void reportError(const std::string& reason);

    LLPluginClassMedia *mMediaPlugin;

    std::string mURL;
    F32 mGain;
    LLTimer mConnectTimer;
    bool mConnecting = false;
    bool mFailed = false;
    std::string mError;
    std::string mLastTitle;
    LLTimer mPlaybackTimer;
    F64 mPlaybackSeconds = 0.0;
    bool mPlaybackRunning = false;
    bool mPlaybackStarted = false;
};


#endif //LL_VIEWERMEDIA_STREAMINGAUDIO_H
