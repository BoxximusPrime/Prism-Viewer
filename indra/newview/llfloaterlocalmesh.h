/**
 * @file llfloaterlocalmesh.h
 * @brief Session-only mesh previews anchored to an editable world prim.
 */
#pragma once

#include "llfloater.h"
#include <memory>

class LLViewerObject;
namespace LL::GLTF { class Asset; }

// Watch mesh exports and keep PBR materials current while the floater is closed.
void updateLocalMeshPreview(LLViewerObject& object);
void updateLocalMeshMaterials(LL::GLTF::Asset& asset);

class LLFloaterLocalMesh final : public LLFloater
{
public:
    explicit LLFloaterLocalMesh(const LLSD& key);
    bool postBuild() override;
    void draw() override;

private:
    LLViewerObject* getTarget() const;
    void browse();
    void reload();
    void remove();
    void load(const LLUUID& target_id, const std::string& filename, bool preserve_placement);
    void updateMaterialControls();
    void selectMaterial();
    void toggleFactorOverrides();
    void changeFactor(bool roughness);
    void resetMaterial();

    LLUUID mStatusTarget;
    std::weak_ptr<LL::GLTF::Asset> mControlsAsset;
    std::string mStatus;
    bool mPickerPending = false;
};
