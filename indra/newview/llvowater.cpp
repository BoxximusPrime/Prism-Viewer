/**
 * @file llvowater.cpp
 * @brief LLVOWater class implementation
 *
 * $LicenseInfo:firstyear=2005&license=viewerlgpl$
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

#include "llvowater.h"
#include "llagent.h"
#include <algorithm>
#include <cmath>
#include <vector>

#include "llviewercontrol.h"

#include "lldrawable.h"
#include "lldrawpoolwater.h"
#include "llface.h"
#include "llsky.h"
#include "llsurface.h"
#include "llviewercamera.h"
#include "llviewertexturelist.h"
#include "llviewerregion.h"
#include "llworld.h"
#include "pipeline.h"
#include "llspatialpartition.h"

///////////////////////////////////

template<class T> inline T LERP(T a, T b, F32 factor)
{
    return a + (b - a) * factor;
}

LLVOWater::LLVOWater(const LLUUID &id,
                     const LLPCode pcode,
                     LLViewerRegion *regionp) :
    LLStaticViewerObject(id, pcode, regionp),
    mRenderType(LLPipeline::RENDER_TYPE_WATER)
{
    // Terrain must draw during selection passes so it can block objects behind it.
    mbCanSelect = false;
    setScale(LLVector3(256.f, 256.f, 0.f)); // Hack for setting scale for bounding boxes/visibility.

    mIsEdgePatch = false;
}


void LLVOWater::markDead()
{
    LLViewerObject::markDead();
}


bool LLVOWater::isActive() const
{
    return false;
}


void LLVOWater::setPixelAreaAndAngle(LLAgent &agent)
{
    mAppAngle = 50;
    mPixelArea = 500*500;
}


// virtual
void LLVOWater::updateTextures()
{
}

// Never gets called
void  LLVOWater::idleUpdate(LLAgent &agent, const F64 &time)
{
}

LLDrawable *LLVOWater::createDrawable(LLPipeline *pipeline)
{
    pipeline->allocDrawable(this);
    mDrawable->setLit(false);
    mDrawable->setRenderType(mRenderType);

    LLDrawPoolWater *pool = (LLDrawPoolWater*) gPipeline.getPool(LLDrawPool::POOL_WATER);

    mDrawable->setNumFaces(1, pool, LLWorld::getInstance()->getDefaultWaterTexture());

    return mDrawable;
}

// Fixed 25 cm world-space samples throughout the displacement radius. The
// window moves in 16 m steps, with a guard band so changed cells are already
// flat. Region and void patches clip the same lattice, including shared edges.
// Large grids are split into U16-sized buffers below, not coarsened near the eye.
std::vector<F64> waterMeshAxis(F64 low, F64 high, F64 center, F64 radius)
{
    std::vector<F64> axis{low, high};
    auto insert = [&](F64 x) { if (x > low && x < high) axis.push_back(x); };
    const F64 extent = std::ceil(radius / 16.0) * 16.0 + 16.0;
    const F64 first = std::ceil(std::max(low, center - extent) * 4.0) * 0.25;
    const F64 last = std::min(high, center + extent);
    for (F64 x = first; x <= last; x += 0.25) insert(x);
    std::sort(axis.begin(), axis.end());
    axis.erase(std::unique(axis.begin(), axis.end()), axis.end());
    return axis;
}

LLVector3d LLVOWater::getMeshCenter()
{
    extern bool gCubeSnapshot;
    static LLVector3d center;
    if (!gCubeSnapshot)
    {
        center = gAgent.getPosGlobalFromAgent(LLViewerCamera::getInstance()->getOrigin());
        // The shader fades around the continuous camera position. Only the CPU
        // mesh window is snapped; moving it must not change sampled wave phase.
        center.mdV[2] = 0.0;
    }
    return center;
}

void LLVOWater::updateMeshLOD()
{
    static LLCachedControl<bool> waves(gSavedSettings, "RenderWaterProceduralWaves", true);
    static LLCachedControl<F32> displacement(gSavedSettings, "RenderWaterDisplacement", 1.f);
    static LLCachedControl<bool> enabled(gSavedSettings, "RenderWaterDisplacementEnabled", true);
    static LLCachedControl<F32> distance(gSavedSettings, "RenderWaterDisplacementDistance", 64.f);
    const bool displaced = waves && enabled && displacement() > 0.f;
    LLVector3d center = getMeshCenter();
    for (S32 axis = 0; axis < 2; ++axis) center.mdV[axis] = std::floor(center.mdV[axis] / 16.0) * 16.0;
    if (mDrawable && (displaced != mMeshDisplaced || (displaced &&
        (mMeshCenter != center || mMeshDistance != llclamp(distance(), 8.f, 128.f)))))
        updateGeometry(mDrawable);
}

void LLVOWater::renderSurface()
{
    for (auto& buffer : mMeshBuffers)
    {
        buffer->setBuffer();
        buffer->drawRange(LLRender::TRIANGLES, 0, buffer->getNumVerts() - 1, buffer->getNumIndices(), 0);
    }
}

bool LLVOWater::updateGeometry(LLDrawable *drawable)
{
    LL_PROFILE_ZONE_SCOPED;
    if (drawable->getNumFaces() < 1)
    {
        LLDrawPoolWater *poolp = (LLDrawPoolWater*) gPipeline.getPool(LLDrawPool::POOL_WATER);
        drawable->addFace(poolp, NULL);
    }
    LLFace* face = drawable->getFace(0);
    if (!face) return true;

    static LLCachedControl<bool> waves(gSavedSettings, "RenderWaterProceduralWaves", true);
    static LLCachedControl<F32> displacement(gSavedSettings, "RenderWaterDisplacement", 1.f);
    static LLCachedControl<bool> enabled(gSavedSettings, "RenderWaterDisplacementEnabled", true);
    static LLCachedControl<F32> distance(gSavedSettings, "RenderWaterDisplacementDistance", 64.f);
    mMeshDisplaced = waves && enabled && displacement() > 0.f;
    mMeshDistance = llclamp(distance(), 8.f, 128.f);
    mMeshCenter = getMeshCenter();
    for (S32 axis = 0; axis < 2; ++axis) mMeshCenter.mdV[axis] = std::floor(mMeshCenter.mdV[axis] / 16.0) * 16.0;
    const LLVector3& scale = getScale();
    const LLVector3d center = getPositionGlobal();
    const LLVector3d origin = gAgent.getPosGlobalFromAgent(LLVector3::zero);
    std::vector<F64> axes[2];
    for (S32 axis = 0; axis < 2; ++axis)
    {
        const F64 low = center.mdV[axis] - scale.mV[axis] * 0.5;
        const F64 high = center.mdV[axis] + scale.mV[axis] * 0.5;
        if (mMeshDisplaced)
            axes[axis] = waterMeshAxis(low, high, mMeshCenter.mdV[axis], mMeshDistance);
        else
        {
            const S32 cells = (LLPipeline::sRenderTransparentWater ? 8 : 1) *
                llclamp((S32)llround(scale.mV[axis] / 256.f), 1, 8);
            for (S32 i = 0; i <= cells; ++i) axes[axis].push_back(low + (high-low) * i / cells);
        }
    }
    const S32 size_x = (S32)axes[0].size();
    const S32 size_y = (S32)axes[1].size();
    const LLVector3 position = getPositionAgent();
    const F32 height = position.mV[VZ] - scale.mV[VZ] * 0.5f;
    std::vector<LLPointer<LLVertexBuffer>> buffers;
    // A face remains the culling proxy for the whole water object. Its geometry
    // is drawn in chunks so increasing detail never overflows 16-bit indices or
    // changes the pool's face list while iterating it. Reuse existing buffers.
    constexpr S32 chunk_cells = 128;
    for (S32 start_y = 0; start_y < size_y - 1; start_y += chunk_cells)
        for (S32 start_x = 0; start_x < size_x - 1; start_x += chunk_cells)
        {
            const S32 nx = llmin(chunk_cells + 1, size_x - start_x);
            const S32 ny = llmin(chunk_cells + 1, size_y - start_y);
            const S32 vertex_count = nx * ny;
            const S32 index_count = (nx - 1) * (ny - 1) * 6;
            LLPointer<LLVertexBuffer> buffer;
            if (buffers.size() < mMeshBuffers.size()) buffer = mMeshBuffers[buffers.size()];
            if (!buffer || buffer->getNumVerts() != vertex_count || buffer->getNumIndices() != index_count)
            {
                buffer = new LLVertexBuffer(LLDrawPoolWater::VERTEX_DATA_MASK);
                if (!buffer->allocateBuffer(vertex_count, index_count))
                {
                    LL_WARNS() << "Failed to allocate water mesh" << LL_ENDL;
                    return false;
                }
            }
            LLStrider<LLVector3> vertices, normals;
            LLStrider<LLVector2> texcoords;
            LLStrider<U16> indices;
            buffer->getVertexStrider(vertices);
            buffer->getNormalStrider(normals);
            buffer->getTexCoord0Strider(texcoords);
            buffer->getIndexStrider(indices);
            for (S32 y = 0; y < ny; ++y)
                for (S32 x = 0; x < nx; ++x)
                {
                    const F64 gx = axes[0][start_x + x];
                    const F64 gy = axes[1][start_y + y];
                    *vertices++ = LLVector3((F32)(gx - origin.mdV[0]), (F32)(gy - origin.mdV[1]), height);
                    *normals++ = LLVector3(0.f, 0.f, 1.f);
                    *texcoords++ = LLVector2((F32)((gx - axes[0].front()) / scale.mV[0]),
                                            (F32)((gy - axes[1].front()) / scale.mV[1]));
                    if (x + 1 < nx && y + 1 < ny)
                    {
                        const U16 v = (U16)(y * nx + x);
                        *indices++ = v;     *indices++ = v+1;    *indices++ = v+nx;
                        *indices++ = v+1;   *indices++ = v+nx+1; *indices++ = v+nx;
                    }
                }
            buffer->unmapBuffer();
            buffers.push_back(buffer);
        }
    mMeshBuffers = std::move(buffers);
    face->setSize(mMeshBuffers.front()->getNumVerts(), mMeshBuffers.front()->getNumIndices());
    face->setIndicesIndex(0);
    face->setGeomIndex(0);
    face->setVertexBuffer(mMeshBuffers.front());
    face->mCenterAgent = position;
    face->mCenterLocal = position;
    mDrawable->movePartition();
    LLPipeline::sCompiles++;
    return true;
}

void LLVOWater::initClass()
{
}

void LLVOWater::cleanupClass()
{
}

void setVecZ(LLVector3& v)
{
    v.mV[VX] = 0;
    v.mV[VY] = 0;
    v.mV[VZ] = 1;
}

void LLVOWater::setIsEdgePatch(const bool edge_patch)
{
    mIsEdgePatch = edge_patch;
}

void LLVOWater::updateSpatialExtents(LLVector4a &newMin, LLVector4a& newMax)
{
    LLVector4a pos;
    pos.load3(getPositionAgent().mV);
    LLVector4a scale;
    scale.load3(getScale().mV);
    scale.mul(0.5f);

    newMin.setSub(pos, scale);
    newMax.setAdd(pos, scale);
    // The vertex shader clamps displacement to +/-8 m, including troughs below
    // the mean water plane (the old bounds only extended above that plane).
    LLVector4a margin;
    margin.set(0.f, 0.f, 8.f, 0.f);
    newMin.sub(margin);
    newMax.add(margin);

    pos.setAdd(newMin,newMax);
    pos.mul(0.5f);

    mDrawable->setPositionGroup(pos);
}

U32 LLVOWater::getPartitionType() const
{
    if (mIsEdgePatch)
    {
        return LLViewerRegion::PARTITION_VOIDWATER;
    }

    return LLViewerRegion::PARTITION_WATER;
}

U32 LLVOVoidWater::getPartitionType() const
{
    return LLViewerRegion::PARTITION_VOIDWATER;
}

LLWaterPartition::LLWaterPartition(LLViewerRegion* regionp)
: LLSpatialPartition(0, false, regionp)
{
    mInfiniteFarClip = true;
    mDrawableType = LLPipeline::RENDER_TYPE_WATER;
    mPartitionType = LLViewerRegion::PARTITION_WATER;
}

LLVoidWaterPartition::LLVoidWaterPartition(LLViewerRegion* regionp) : LLWaterPartition(regionp)
{
    mOcclusionEnabled = false;
    mDrawableType = LLPipeline::RENDER_TYPE_VOIDWATER;
    mPartitionType = LLViewerRegion::PARTITION_VOIDWATER;
}
