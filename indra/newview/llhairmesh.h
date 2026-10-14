// Experimental, animated-mesh collision for the local avatar's hair.
#pragma once

#include "v3math.h"

class LLGLSLShader;
class LLSD;
class LLUUID;

namespace LLHairMesh
{
    void loadShaders();
    void unloadShaders();
    void release();
    void invalidate(const LLUUID& object);
    void update();
    void updateGuides();
    U32 guideFrame();
    S32 guideBinding(const LLUUID& object);
    void bindGuides(LLGLSLShader& shader, U32 frame, bool previous);
    void renderDebug();
    U32 currentFrame(LLVector3& centre);
    void bind(LLGLSLShader& shader, U32 frame, bool previous);
    LLSD diagnostics();
}
