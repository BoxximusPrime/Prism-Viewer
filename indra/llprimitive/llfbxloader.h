/**
 * @file llfbxloader.h
 * @brief Static FBX import shared by mesh uploads and local previews.
 */
#pragma once

#include "llmodelloader.h"

class LLFBXLoader final : public LLModelLoader
{
public:
    using LLModelLoader::LLModelLoader;
    bool OpenFile(const std::string& filename) override;

    // The ordinary mesh upload format carries diffuse materials. Local Mesh
    // can additionally use these exported PBR factors without uploading them.
    struct MaterialFactors
    {
        F32 mRoughness = 0.5f;
        F32 mMetallic = 0.f;
    };
    std::map<std::string, MaterialFactors> mMaterialFactors;
};
