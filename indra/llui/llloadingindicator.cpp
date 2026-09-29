/**
 * @file llloadingindicator.cpp
 * @brief Perpetual loading indicator
 *
 * $LicenseInfo:firstyear=2010&license=viewerlgpl$
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

#include "linden_common.h"

#include "llloadingindicator.h"

// Linden library includes
#include "llsingleton.h"

// Project includes
#include "lluictrlfactory.h"
#include "lluiimage.h"
#include "llrender2dutils.h"

void LLLoadingIndicator::drawSmall(const LLRect& rect, F32 alpha)
{
    const F32 size = static_cast<F32>(llmin(rect.getWidth(), rect.getHeight()));
    if (size <= 0.f) return;
    const F32 x = 0.5f * static_cast<F32>(rect.mLeft + rect.mRight);
    const F32 y = 0.5f * static_cast<F32>(rect.mBottom + rect.mTop);
    const F64 seconds = LLFrameTimer::getElapsedSeconds();
    const S32 step = static_cast<S32>(fmod(seconds, 0.8) * 10.0);

    // The backing keeps the moving white head readable over every icon color.
    gGL.color4f(0.025f, 0.03f, 0.04f, 0.92f * alpha);
    gl_circle_2d(x, y, size * 0.48f, 24, true);
    for (S32 dot = 0; dot < 8; ++dot)
    {
        const S32 age = (step - dot + 8) % 8;
        const F32 brightness = 1.f - static_cast<F32>(age) * 0.1f;
        const F32 angle = F_PI_BY_TWO - static_cast<F32>(dot) * F_TWO_PI / 8.f;
        gGL.color4f(brightness, brightness, brightness, alpha);
        gl_circle_2d(x + cosf(angle) * size * 0.32f,
                    y + sinf(angle) * size * 0.32f, size * 0.08f, 12, true);
    }
}

// registered in llui.cpp to avoid being left out by MS linker
//static LLDefaultChildRegistry::Register<LLLoadingIndicator> r("loading_indicator");

///////////////////////////////////////////////////////////////////////////////
// LLLoadingIndicator class
///////////////////////////////////////////////////////////////////////////////

LLLoadingIndicator::LLLoadingIndicator(const Params& p)
:   LLUICtrl(p),
    mImagesPerSec(p.images_per_sec > 0 ? p.images_per_sec : 1.0f),
    mCurImageIdx(0)
{
}

void LLLoadingIndicator::initFromParams(const Params& p)
{
    for (LLUIImage* image : p.images().image)
    {
        mImages.push_back(image);
    }

    // Start timer for switching images.
    start();
}

void LLLoadingIndicator::draw()
{
    // Time to switch to the next image?
    if (mImageSwitchTimer.getStarted() && mImageSwitchTimer.hasExpired())
    {
        // Switch to the next image.
        if (!mImages.empty())
        {
            mCurImageIdx = (mCurImageIdx + 1) % mImages.size();
        }

        // Restart timer.
        start();
    }

    LLUIImagePtr cur_image = mImages.empty() ? LLUIImagePtr(NULL) : mImages[mCurImageIdx];

    // Draw current image.
    if( cur_image.notNull() )
    {
        cur_image->draw(getLocalRect(), LLColor4::white % getDrawContext().mAlpha);
    }

    LLUICtrl::draw();
}

void LLLoadingIndicator::stop()
{
    mImageSwitchTimer.stop();
}

void LLLoadingIndicator::start()
{
    mImageSwitchTimer.start();
    F32 period = 1.0f / (mImages.size() * mImagesPerSec);
    mImageSwitchTimer.setTimerExpirySec(period);
}
