/**
 * @file llfloaterlocalmesh.cpp
 * @brief Session-only mesh previews. No object parameters or assets are sent.
 */
#include "llviewerprecompiledheaders.h"
#include "llfloaterlocalmesh.h"

#include "fsyspath.h"
#include "gltf/asset.h"
#include "gltfscenemanager.h"
#include "llappviewer.h"
#include "llbutton.h"
#include "llcheckboxctrl.h"
#include "llcombobox.h"
#include "lldaeloader.h"
#include "llfbxloader.h"
#include "lldir.h"
#include "llfilepicker.h"
#include "llframetimer.h"
#include "llgltfmateriallist.h"
#include "llgltfmaterialpreviewmgr.h"
#include "llspinctrl.h"
#include "lltexturectrl.h"
#include "llviewermenufile.h"
#include "llselectmgr.h"
#include "llskinningutil.h"
#include "lltextbox.h"
#include "llviewercontrol.h"
#include "llviewerobjectlist.h"
#include "llviewershadermgr.h"
#include "llvovolume.h"
#include "llxmlparser.h"

#include <limits>
#include <optional>

namespace
{
using namespace LL::GLTF;

using MeshFileStamp = std::pair<std::filesystem::file_time_type, std::uintmax_t>;

std::optional<MeshFileStamp> meshFileStamp(const std::string& filename)
{
    const fsyspath path(filename);
    std::error_code error;
    const auto modified = std::filesystem::last_write_time(path, error);
    if (error) return std::nullopt;
    const auto size = std::filesystem::file_size(path, error);
    if (error || size == 0) return std::nullopt;
    return MeshFileStamp(modified, size);
}

struct PreviewMaterial
{
    LLUUID mID;
    LLPointer<LLFetchedGLTFMaterial> mFetched;
    LLGLTFMaterial mSnapshot;
    std::optional<F32> mRoughness;
    std::optional<F32> mMetallic;
    bool mApplied = false;
};

// Previews own this extra state; ordinary/uploaded Assets keep their existing
// copy semantics. The shared_ptr deleter below deletes the concrete type.
struct LocalMeshAsset : Asset
{
    std::vector<Material> mImportedMaterials;
    std::vector<PreviewMaterial> mPreviewMaterials;
    S32 mPreviewTextureStart = 0;
    bool mMaterialsDirty = false;
    bool mAutoReload = true;
    std::optional<MeshFileStamp> mFileStamp;
    F64 mNextFileCheck = 0.;
    F64 mFileChangedAt = 0.;
    S32 mReloadAttempts = 0;
    bool mReloadPending = false;
    bool mAutoReloadFailed = false;
};

void rebuildMaterialBatches(Asset& asset)
{
    for (auto& data : asset.mRenderData)
        for (auto& batches : data.mBatches)
        {
            batches.clear();
            batches.resize(asset.mMaterials.size() + 1);
        }
    for (S32 n = 0; n < S32(asset.mNodes.size()); ++n)
    {
        const auto& node = asset.mNodes[n];
        if (node.mMesh == INVALID_INDEX) continue;
        auto& mesh = asset.mMeshes[node.mMesh];
        for (S32 p = 0; p < S32(mesh.mPrimitives.size()); ++p)
        {
            auto& primitive = mesh.mPrimitives[p];
            const auto& material = asset.mMaterials[primitive.mMaterial];
            primitive.mShaderVariant = 0;
            if (material.mUnlit.mPresent) primitive.mShaderVariant |= LLGLSLShader::GLTFVariant::UNLIT;
            if (material.isMultiUV()) primitive.mShaderVariant |= LLGLSLShader::GLTFVariant::MULTI_UV;
            if (material.mAlphaMode == Material::AlphaMode::BLEND) primitive.mShaderVariant |= LLGLSLShader::GLTFVariant::ALPHA_BLEND;
            asset.mRenderData[material.mDoubleSided].mBatches[primitive.mShaderVariant][primitive.mMaterial + 1].mPrimitives.push_back({p, n});
        }
    }
}

Material previewPBRMaterial(LocalMeshAsset& asset, S32 slot, LLFetchedGLTFMaterial& source)
{
    Material result;
    result.mName = asset.mImportedMaterials[slot].mName;
    result.mPbrMetallicRoughness.mBaseColorFactor = glm::make_vec4(source.mBaseColor.mV);
    result.mPbrMetallicRoughness.mRoughnessFactor = source.mRoughnessFactor;
    result.mPbrMetallicRoughness.mMetallicFactor = source.mMetallicFactor;
    result.mEmissiveFactor = glm::make_vec3(source.mEmissiveColor.mV);
    result.mAlphaCutoff = source.mAlphaCutoff;
    result.mDoubleSided = source.mDoubleSided;
    result.mAlphaMode = source.mAlphaMode == LLGLTFMaterial::ALPHA_MODE_BLEND ? Material::AlphaMode::BLEND :
        source.mAlphaMode == LLGLTFMaterial::ALPHA_MODE_MASK ? Material::AlphaMode::MASK : Material::AlphaMode::OPAQUE;

    TextureInfo* infos[] = {&result.mPbrMetallicRoughness.mBaseColorTexture, &result.mNormalTexture,
        &result.mPbrMetallicRoughness.mMetallicRoughnessTexture, &result.mEmissiveTexture};
    LLViewerFetchedTexture* textures[] = {source.mBaseColorTexture, source.mNormalTexture,
        source.mMetallicRoughnessTexture, source.mEmissiveTexture};
    for (S32 i = 0; i < 4; ++i)
    {
        const S32 index = asset.mPreviewTextureStart + slot * 4 + i;
        asset.mImages[asset.mTextures[index].mSource].mTexture = textures[i];
        if (textures[i]) infos[i]->mIndex = index;
        const auto& transform = source.mTextureTransform[i];
        infos[i]->mTextureTransform.mPresent = true;
        infos[i]->mTextureTransform.mOffset = glm::make_vec2(transform.mOffset.mV);
        infos[i]->mTextureTransform.mScale = glm::make_vec2(transform.mScale.mV);
        infos[i]->mTextureTransform.mRotation = transform.mRotation;
    }
    // SL stores occlusion in the red channel of the metallic/roughness image.
    static_cast<TextureInfo&>(result.mOcclusionTexture) = result.mPbrMetallicRoughness.mMetallicRoughnessTexture;
    return result;
}

bool initializeMaterials(LocalMeshAsset& asset, const LocalMeshAsset* previous)
{
    S32 default_material = INVALID_INDEX;
    for (auto& mesh : asset.mMeshes)
        for (auto& primitive : mesh.mPrimitives)
            if (primitive.mMaterial == INVALID_INDEX)
            {
                if (default_material == INVALID_INDEX)
                {
                    if (asset.mMaterials.size() >= size_t(gGLManager.mMaxUniformBlockSize / (12 * sizeof(vec4)))) return false;
                    default_material = S32(asset.mMaterials.size());
                    asset.mMaterials.emplace_back().mName = "Default material";
                }
                primitive.mMaterial = default_material;
            }
    asset.mImportedMaterials = asset.mMaterials;
    asset.mPreviewMaterials.resize(asset.mMaterials.size());
    asset.mPreviewTextureStart = S32(asset.mTextures.size());
    for (size_t slot = 0; slot < asset.mMaterials.size(); ++slot)
    {
        // Match named slots across reordering. Duplicate names use occurrence
        // order; unnamed slots match by index only while they stay unnamed.
        const auto& name = asset.mMaterials[slot].mName;
        if (previous)
        {
            size_t occurrence = 0;
            for (size_t i = 0; i < slot; ++i) if (asset.mMaterials[i].mName == name) ++occurrence;
            for (size_t i = 0; i < previous->mImportedMaterials.size(); ++i)
                if (previous->mImportedMaterials[i].mName == name &&
                    (name.empty() ? i == slot : occurrence-- == 0))
                {
                    asset.mPreviewMaterials[slot] = previous->mPreviewMaterials[i];
                    asset.mPreviewMaterials[slot].mApplied = false;
                    break;
                }
        }
        for (S32 channel = 0; channel < 4; ++channel)
        {
            asset.mTextures.emplace_back().mSource = S32(asset.mImages.size());
            asset.mImages.emplace_back().mLoadIntoTexturePipe = true;
        }
    }
    asset.mMaterialsDirty = true;
    updateLocalMeshMaterials(asset);
    return true;
}

bool eligible(LLViewerObject* object)
{
    // A single standalone prim keeps linkset/attachment transforms unambiguous.
    return object && !object->isDead() && object->getPCode() == LL_PCODE_VOLUME &&
        !object->getParent() && !object->isAttachment() && object->getChildren().empty() &&
        object->permYouOwner() && object->permModify() && !object->isSculpted() &&
        (!object->mGLTFAsset || object->mGLTFAsset->mLocalMeshPreview);
}

S32 addPreviewAccessor(Asset& asset, const void* data, S32 count, S32 stride,
    Accessor::Type type, Accessor::ComponentType component)
{
    if (!data || count <= 0 || stride <= 0 || U64(count) * stride > S32_MAX)
        throw std::runtime_error("Invalid Collada vertex buffer");
    auto& buffer = asset.mBuffers.emplace_back();
    buffer.mByteLength = count * stride;
    const auto* bytes = static_cast<const U8*>(data);
    buffer.mData.assign(bytes, bytes + buffer.mByteLength);
    auto& view = asset.mBufferViews.emplace_back();
    view.mBuffer = S32(asset.mBuffers.size()) - 1;
    view.mByteLength = buffer.mByteLength;
    view.mByteStride = stride;
    auto& accessor = asset.mAccessors.emplace_back();
    accessor.mBufferView = S32(asset.mBufferViews.size()) - 1;
    accessor.mCount = count;
    accessor.mType = type;
    accessor.mComponentType = component;
    return S32(asset.mAccessors.size()) - 1;
}

bool convertDAEScene(Asset& asset, const LLModelLoader::scene& scene)
{
    asset.mScenes.emplace_back();
    asset.mScene = 0;
    // The Collada importer already converts units/up-axis to SL space. Undo
    // only the axis conversion here, so both formats share the same fit/reload.
    const mat4 to_gltf = glm::rotate(mat4(1.f), -F_PI_BY_TWO, vec3(1.f, 0.f, 0.f));
    for (const auto& entry : scene)
    {
        for (const auto& instance : entry.second)
        {
            const LLModel* model = instance.mModel;
            if (!model || !model->mSkinWeights.empty() || !model->mSkinInfo.mJointNames.empty() ||
                model->getNumVolumeFaces() == 0) return false;
            auto& node = asset.mNodes.emplace_back();
            node.mMatrix = to_gltf * glm::make_mat4(&instance.mTransform.mMatrix[0][0]);
            node.mMatrixValid = true;
            node.mName = instance.mLabel;
            node.mMesh = S32(asset.mMeshes.size());
            asset.mScenes[0].mNodes.push_back(S32(asset.mNodes.size()) - 1);
            auto& mesh = asset.mMeshes.emplace_back();
            mesh.mName = instance.mLabel;
            for (S32 face_index = 0; face_index < model->getNumVolumeFaces(); ++face_index)
            {
                const LLVolumeFace& face = model->getVolumeFace(face_index);
                if (face.mNumIndices <= 0 || face.mNumIndices % 3 || !face.mIndices) return false;
                for (S32 i = 0; i < face.mNumIndices; ++i)
                    if (face.mIndices[i] >= face.mNumVertices) return false;
                auto& primitive = mesh.mPrimitives.emplace_back();
                primitive.mAttributes["POSITION"] = addPreviewAccessor(asset, face.mPositions,
                    face.mNumVertices, sizeof(LLVector4a), Accessor::Type::VEC3, Accessor::ComponentType::FLOAT);
                if (face.mNormals)
                    primitive.mAttributes["NORMAL"] = addPreviewAccessor(asset, face.mNormals,
                        face.mNumVertices, sizeof(LLVector4a), Accessor::Type::VEC3, Accessor::ComponentType::FLOAT);
                if (face.mTexCoords)
                {
                    std::vector<LLVector2> uv(face.mTexCoords, face.mTexCoords + face.mNumVertices);
                    // Primitive::upload flips glTF V for the viewer's texture pipe.
                    for (auto& tc : uv) tc[1] = 1.f - tc[1];
                    primitive.mAttributes["TEXCOORD_0"] = addPreviewAccessor(asset, uv.data(),
                        face.mNumVertices, sizeof(LLVector2), Accessor::Type::VEC2, Accessor::ComponentType::FLOAT);
                }
                primitive.mIndices = addPreviewAccessor(asset, face.mIndices, face.mNumIndices,
                    sizeof(U16), Accessor::Type::SCALAR, Accessor::ComponentType::UNSIGNED_SHORT);

                LLImportMaterial imported;
                if (size_t(face_index) < model->mMaterialList.size())
                {
                    auto found = instance.mMaterial.find(model->mMaterialList[face_index]);
                    if (found != instance.mMaterial.end()) imported = found->second;
                }
                primitive.mMaterial = S32(asset.mMaterials.size());
                auto& material = asset.mMaterials.emplace_back();
                material.mName = instance.mLabel + "/" + (size_t(face_index) < model->mMaterialList.size() ?
                    model->mMaterialList[face_index] : std::to_string(face_index + 1));
                material.mPbrMetallicRoughness.mBaseColorFactor = glm::make_vec4(imported.mDiffuseColor.mV);
                material.mPbrMetallicRoughness.mMetallicFactor = 0.f;
                // COLLADA's legacy importer supplies diffuse only, not PBR
                // roughness. Start with a moderately rough dielectric preview.
                material.mPbrMetallicRoughness.mRoughnessFactor = 0.5f;
                material.mUnlit.mPresent = imported.mFullbright;
                if (imported.mDiffuseColor.mV[3] < 1.f) material.mAlphaMode = Material::AlphaMode::BLEND;
                if (!imported.mDiffuseMapFilename.empty())
                {
                    material.mPbrMetallicRoughness.mBaseColorTexture.mIndex = S32(asset.mTextures.size());
                    auto& texture = asset.mTextures.emplace_back();
                    texture.mSource = S32(asset.mImages.size());
                    auto& image = asset.mImages.emplace_back();
                    image.mUri = imported.mDiffuseMapFilename;
                    image.mName = imported.mDiffuseMapLabel;
                }
            }
        }
    }
    return !asset.mNodes.empty();
}

bool loadModelFile(Asset& asset, const std::string& filename, bool fbx)
{
    // Collada DOM can loop while recovering a truncated document. Reject an
    // export still being written before entering that parser on the UI thread.
    if (!fbx)
    {
        LLXmlParser xml;
        if (!xml.parseFile(filename)) return false;
    }
    JointTransformMap joints;
    JointNameSet names;
    JointMap aliases;
    U32 state = LLModelLoader::STARTING;
    auto joint_lookup = [](const std::string&, void*) -> LLJoint* { return nullptr; };
    auto state_callback = [&state](U32 value, void*) { state = value; };
    std::unique_ptr<LLModelLoader> loader;
    if (fbx)
        loader.reset(new LLFBXLoader(filename, LLModel::LOD_HIGH, {}, joint_lookup, {}, state_callback,
            nullptr, joints, names, aliases, LLSkinningUtil::getMaxJointCount(),
            gSavedSettings.getU32("ImporterModelLimit"), 0));
    else
        loader.reset(new LLDAELoader(filename, LLModel::LOD_HIGH, {}, joint_lookup, {}, state_callback,
            nullptr, joints, names, aliases, LLSkinningUtil::getMaxJointCount(),
            gSavedSettings.getU32("ImporterModelLimit"), 0, gSavedSettings.getBOOL("ImporterPreprocessDAE")));
    // Parse the source itself on each reload; no upload or SLM cache is involved.
    if (!loader->OpenFile(filename) || state != LLModelLoader::DONE) return false;
    for (const auto& model : loader->mModelList)
        if (!model->mSkinWeights.empty() || !model->mSkinInfo.mJointNames.empty()) return false;
    asset.mFilename = filename;
    asset.mLoadIntoVRAM = true;
    asset.mVersion = "2.0";
    if (!convertDAEScene(asset, loader->mScene)) return false;
    if (fbx)
    {
        const auto& factors = static_cast<LLFBXLoader*>(loader.get())->mMaterialFactors;
        size_t material_index = 0;
        for (const auto& entry : loader->mScene)
            for (const auto& instance : entry.second)
                for (const auto& binding : instance.mModel->mMaterialList)
                {
                    auto& material = asset.mMaterials[material_index++].mPbrMetallicRoughness;
                    const auto& exported = factors.at(binding);
                    material.mRoughnessFactor = exported.mRoughness;
                    material.mMetallicFactor = exported.mMetallic;
                }
    }
    if (!asset.prep()) return false;
    // Imported diffuse textures do not declare glTF alpha modes. Preserve their
    // alpha channel, including partial transparency, when one is present.
    for (auto& mesh : asset.mMeshes)
        for (auto& primitive : mesh.mPrimitives)
        {
            auto& material = asset.mMaterials[primitive.mMaterial];
            const S32 texture = material.mPbrMetallicRoughness.mBaseColorTexture.mIndex;
            if (texture != INVALID_INDEX)
            {
                auto image = asset.mImages[asset.mTextures[texture].mSource].mTexture;
                if (image && image->getComponents() == 4)
                {
                    material.mAlphaMode = Material::AlphaMode::BLEND;
                    primitive.mShaderVariant |= LLGLSLShader::GLTFVariant::ALPHA_BLEND;
                }
            }
        }
    return true;
}

bool preparePreview(Asset& asset, const Asset* previous)
{
    // Only the active scene is previewed. Reject cycles/shared children before
    // the recursive transform updater sees them, and exclude unused mesh nodes
    // from both rendering and picking.
    S32 scene_index = asset.mScene == INVALID_INDEX ? 0 : asset.mScene;
    if (scene_index < 0 || size_t(scene_index) >= asset.mScenes.size() ||
        asset.mNodes.size() > size_t(LLSkinningUtil::getMaxGLTFJointCount()) ||
        asset.mMaterials.size() > size_t(gGLManager.mMaxUniformBlockSize / (12 * sizeof(vec4))))
        return false;

    Scene scene = asset.mScenes[scene_index];
    std::vector<bool> active(asset.mNodes.size(), false);
    std::vector<S32> pending = scene.mNodes;
    while (!pending.empty())
    {
        S32 index = pending.back();
        pending.pop_back();
        if (index < 0 || size_t(index) >= active.size() || active[index]) return false;
        active[index] = true;
        auto& node = asset.mNodes[index];
        if (node.mMesh < INVALID_INDEX ||
            (node.mMesh != INVALID_INDEX && size_t(node.mMesh) >= asset.mMeshes.size())) return false;
        pending.insert(pending.end(), node.mChildren.begin(), node.mChildren.end());
    }
    asset.mScenes = {scene};
    asset.mScene = 0;
    for (size_t i = 0; i < active.size(); ++i)
        if (!active[i]) asset.mNodes[i].mMesh = INVALID_INDEX;

    asset.updateTransforms();
    // glTF is Y-up; SL is Z-up. Keep handedness by mapping (x,y,z) to (x,-z,y).
    const mat4 upright = glm::rotate(mat4(1.f), F_PI_BY_TWO, vec3(1.f, 0.f, 0.f));
    vec3 minimum(std::numeric_limits<float>::max());
    vec3 maximum(std::numeric_limits<float>::lowest());
    bool has_geometry = false;
    for (const auto& node : asset.mNodes)
    {
        if (node.mMesh == INVALID_INDEX) continue;
        const mat4 transform = upright * node.mAssetMatrix;
        for (const auto& primitive : asset.mMeshes[node.mMesh].mPrimitives)
        {
            if (primitive.mMode != Primitive::Mode::TRIANGLES || primitive.mIndexArray.empty()) return false;
            for (const auto& position : primitive.mPositions)
            {
                const F32* p = position.getF32ptr();
                vec3 point(transform * vec4(p[0], p[1], p[2], 1.f));
                if (!std::isfinite(point.x) || !std::isfinite(point.y) || !std::isfinite(point.z)) return false;
                minimum = glm::min(minimum, point);
                maximum = glm::max(maximum, point);
                has_geometry = true;
            }
        }
    }
    const vec3 extent = maximum - minimum;
    const F32 longest = llmax(extent.x, extent.y, extent.z);
    if (!has_geometry || !std::isfinite(longest) || longest < 0.000001f) return false;

    // Fit once. Reload preserves the original pivot and scale even when the
    // exported bounds change, so editing a vertex doesn't move the whole mesh.
    asset.mLocalMeshTransform = previous ? previous->mLocalMeshTransform :
        glm::scale(mat4(1.f), vec3(1.f / longest)) *
        glm::translate(mat4(1.f), -(minimum + maximum) * 0.5f) * upright;
    for (S32 root : scene.mNodes)
    {
        auto& node = asset.mNodes[root];
        node.mMatrix = asset.mLocalMeshTransform * node.mMatrix;
        node.mMatrixValid = true;
        node.mTRSValid = false;
    }
    asset.updateTransforms();
    asset.uploadMaterials();

    // The development glTF loader does not build render buffers. Use one VBO
    // per primitive: primitives sharing a material need not share attributes.
    for (auto& mesh : asset.mMeshes)
    {
        for (auto& primitive : mesh.mPrimitives)
        {
            if (primitive.mPositions.empty() || primitive.mIndexArray.empty()) return false;
            if (primitive.getIndexCount() > U32(S32_MAX / 2)) return false;
            LLPointer<LLVertexBuffer> buffer = new LLVertexBuffer(primitive.mAttributeMask);
            // LLVertexBuffer's U32 upload switches a buffer allocated in U16 units.
            if (!buffer->allocateBuffer(primitive.getVertexCount(), primitive.getIndexCount() * 2)) return false;
            primitive.mVertexOffset = primitive.mIndexOffset = 0;
            buffer->setBuffer();
            primitive.upload(buffer);
            buffer->unmapBuffer();
        }
    }
    LLVertexBuffer::unbind();
    for (S32 node_index = 0; node_index < S32(asset.mNodes.size()); ++node_index)
    {
        const auto& node = asset.mNodes[node_index];
        if (node.mMesh == INVALID_INDEX) continue;
        auto& mesh = asset.mMeshes[node.mMesh];
        for (S32 index = 0; index < S32(mesh.mPrimitives.size()); ++index)
        {
            const auto& primitive = mesh.mPrimitives[index];
            const S32 material = primitive.mMaterial;
            const S32 sided = material == INVALID_INDEX ? 0 : asset.mMaterials[material].mDoubleSided;
            auto& batch = asset.mRenderData[sided].mBatches[primitive.mShaderVariant][material + 1];
            batch.mPrimitives.push_back({index, node_index});
        }
    }
    return true;
}

// Asset currently has no owning UBO destructor (its upload code copies Assets).
// Give previews their own deletion policy without changing those copy semantics.
std::shared_ptr<Asset> makePreview()
{
    return std::shared_ptr<Asset>(new LocalMeshAsset, [](Asset* asset)
    {
        if (asset->mNodesUBO) glDeleteBuffers(1, &asset->mNodesUBO);
        if (asset->mMaterialsUBO) glDeleteBuffers(1, &asset->mMaterialsUBO);
        delete static_cast<LocalMeshAsset*>(asset);
    });
}

bool replacePreview(LLViewerObject& object, const std::string& filename,
    bool preserve_placement, bool require_stable_file = false)
{
    auto asset = makePreview();
    asset->mLocalMeshPreview = true;
    auto& preview = static_cast<LocalMeshAsset&>(*asset);
    const auto* previous = preserve_placement && object.mGLTFAsset ?
        static_cast<LocalMeshAsset*>(object.mGLTFAsset.get()) : nullptr;
    preview.mAutoReload = previous ? previous->mAutoReload : true;
    preview.mFileStamp = meshFileStamp(filename);
    preview.mNextFileCheck = LLFrameTimer::getTotalSeconds() + 0.5;
    LLGLSLShader* previous_shader = LLGLSLShader::sCurBoundShaderPtr;
    gDebugProgram.bind();
    bool success = false;
    try
    {
        std::string extension = gDirUtilp->getExtension(filename);
        LLStringUtil::toLower(extension);
        success = ((extension == "dae" || extension == "fbx") ? loadModelFile(*asset, filename, extension == "fbx") :
            asset->load(filename, true)) && preparePreview(*asset, previous);
        if (success) success = initializeMaterials(preview, previous);
        // An export can resume writing after the debounce. Never install a
        // preview parsed from a source that changed during an automatic load.
        if (success && require_stable_file)
            success = preview.mFileStamp && preview.mFileStamp == meshFileStamp(filename);
    }
    catch (const std::exception& error)
    {
        LL_WARNS("LocalMesh") << "Cannot load local mesh: " << error.what() << LL_ENDL;
    }
    LLVertexBuffer::unbind();
    if (previous_shader) previous_shader->bind();
    else gDebugProgram.unbind();
    if (!success) return false; // Keep the last good asset on every failure path.

    object.mGLTFAsset = asset;
    object.markForUpdate();
    auto& objects = LL::GLTFSceneManager::instance().mObjects;
    if (std::find(objects.begin(), objects.end(), &object) == objects.end()) objects.push_back(&object);
    // Existing node selections must not divert the build tools into node editing.
    if (auto* node = LLSelectMgr::getInstance()->getSelection()->findNode(&object))
    {
        node->mSelectedGLTFNode = -1;
        node->mSelectedGLTFPrimitive = -1;
    }
    return true;
}

void autoReloadPreview(LLViewerObject& object)
{
    auto& preview = static_cast<LocalMeshAsset&>(*object.mGLTFAsset);
    const F64 now = LLFrameTimer::getTotalSeconds();
    if (!preview.mAutoReload || now < preview.mNextFileCheck) return;
    preview.mNextFileCheck = now + 0.5;
    if (!eligible(&object) || !gSavedSettings.getBOOL("RenderCanUseGLTFPBROpaqueShaders") ||
        gGLTFPBRMetallicRoughnessProgram.mGLTFVariants.empty()) return;

    const auto stamp = meshFileStamp(preview.mFilename);
    if (stamp != preview.mFileStamp)
    {
        preview.mFileStamp = stamp;
        preview.mFileChangedAt = now;
        preview.mReloadPending = stamp.has_value();
        preview.mReloadAttempts = 0;
        preview.mAutoReloadFailed = false;
    }
    // Deleted, locked and empty files are checked again without losing the
    // preview. Require one quiet second after the last observed write.
    if (!stamp || !preview.mReloadPending || now - preview.mFileChangedAt < 1.) return;
    // Copy the path: a successful replacement destroys the old asset.
    const std::string filename = preview.mFilename;
    if (replacePreview(object, filename, true, true)) return;

    preview.mAutoReloadFailed = true;
    preview.mReloadPending = ++preview.mReloadAttempts < 3;
    preview.mNextFileCheck = now + 2.;
    // Stop reparsing an unchanged invalid export after three tries. A new
    // file change always starts a fresh attempt, even with the window closed.
}
}

void updateLocalMeshPreview(LLViewerObject& object)
{
    if (!object.mGLTFAsset || !object.mGLTFAsset->mLocalMeshPreview) return;
    autoReloadPreview(object);
    updateLocalMeshMaterials(*object.mGLTFAsset);
}

void updateLocalMeshMaterials(Asset& base)
{
    if (!base.mLocalMeshPreview) return;
    auto& asset = static_cast<LocalMeshAsset&>(base);
    bool changed = asset.mMaterialsDirty;
    for (size_t i = 0; i < asset.mPreviewMaterials.size(); ++i)
    {
        auto& preview = asset.mPreviewMaterials[i];
        auto* fetched = preview.mFetched.get();
        if (fetched && fetched->isLoaded())
        {
            LLGLTFPreviewTexture::prepareMaterial(fetched);
            // Local material reloads update this shared fetched material.
            if (!preview.mApplied || preview.mSnapshot != static_cast<const LLGLTFMaterial&>(*fetched))
            {
                preview.mSnapshot = *fetched;
                preview.mApplied = true;
                changed = true;
            }
            // Refresh texture pointers too: local images may be replaced while
            // the material's scalar values remain unchanged.
            asset.mMaterials[i] = previewPBRMaterial(asset, S32(i), *fetched);
        }
        else if (!fetched)
        {
            asset.mMaterials[i] = asset.mImportedMaterials[i];
            if (asset.mMaterialsDirty)
                for (S32 channel = 0; channel < 4; ++channel)
                {
                    const S32 texture = asset.mPreviewTextureStart + S32(i) * 4 + channel;
                    asset.mImages[asset.mTextures[texture].mSource].mTexture = nullptr;
                }
        }
        // Pending/failed fetches retain the last successfully displayed material.
        if (preview.mRoughness) asset.mMaterials[i].mPbrMetallicRoughness.mRoughnessFactor = *preview.mRoughness;
        if (preview.mMetallic) asset.mMaterials[i].mPbrMetallicRoughness.mMetallicFactor = *preview.mMetallic;
        if (preview.mRoughness || preview.mMetallic) asset.mMaterials[i].mUnlit.mPresent = false;
    }
    if (changed)
    {
        rebuildMaterialBatches(asset);
        asset.uploadMaterials();
        asset.mMaterialsDirty = false;
    }
}

LLFloaterLocalMesh::LLFloaterLocalMesh(const LLSD& key) : LLFloater(key) {}

bool LLFloaterLocalMesh::postBuild()
{
    getChild<LLButton>("load")->setClickedCallback([this](LLUICtrl*, const LLSD&) { browse(); });
    getChild<LLButton>("reload")->setClickedCallback([this](LLUICtrl*, const LLSD&) { reload(); });
    getChild<LLButton>("remove")->setClickedCallback([this](LLUICtrl*, const LLSD&) { remove(); });
    getChild<LLCheckBoxCtrl>("auto_reload")->setCommitCallback([this](LLUICtrl*, const LLSD&) {
        auto* object = getTarget();
        if (!eligible(object) || !object->mGLTFAsset || !object->mGLTFAsset->mLocalMeshPreview) return;
        auto& preview = static_cast<LocalMeshAsset&>(*object->mGLTFAsset);
        preview.mAutoReload = getChild<LLCheckBoxCtrl>("auto_reload")->get();
        preview.mNextFileCheck = 0.;
        if (preview.mAutoReload && preview.mAutoReloadFailed)
        {
            preview.mReloadPending = true;
            preview.mReloadAttempts = 0;
            preview.mAutoReloadFailed = false;
            preview.mFileChangedAt = LLFrameTimer::getTotalSeconds();
        }
        mStatus.clear();
    });
    getChild<LLComboBox>("material_slot")->setCommitCallback([this](LLUICtrl*, const LLSD&) {
        getChild<LLTextureCtrl>("material")->closeDependentFloater();
        updateMaterialControls();
    });
    getChild<LLSpinCtrl>("roughness")->setCommitCallback([this](LLUICtrl*, const LLSD&) { changeFactor(true); });
    getChild<LLSpinCtrl>("metallic")->setCommitCallback([this](LLUICtrl*, const LLSD&) { changeFactor(false); });
    getChild<LLCheckBoxCtrl>("override_factors")->setCommitCallback([this](LLUICtrl*, const LLSD&) { toggleFactorOverrides(); });
    getChild<LLButton>("reset_material")->setClickedCallback([this](LLUICtrl*, const LLSD&) { resetMaterial(); });
    auto* material = getChild<LLTextureCtrl>("material");
    material->setInventoryPickType(PICK_MATERIAL);
    material->setCanApplyImmediately(false);
    material->setOnSelectCallback([this](LLUICtrl*, const LLSD&) { selectMaterial(); });
    material->setCommitCallback([this](LLUICtrl*, const LLSD&) { selectMaterial(); });
    material->setOnCancelCallback([this](LLUICtrl*, const LLSD&) { updateMaterialControls(); });
    return true;
}

LLViewerObject* LLFloaterLocalMesh::getTarget() const
{
    auto selection = LLSelectMgr::getInstance()->getSelection();
    return selection->getObjectCount() == 1 ? selection->getFirstRootObject() : nullptr;
}

void LLFloaterLocalMesh::draw()
{
    LLViewerObject* object = getTarget();
    const bool valid = eligible(object);
    const bool loaded = object && object->mGLTFAsset && object->mGLTFAsset->mLocalMeshPreview;
    const LLUUID target = object ? object->getID() : LLUUID::null;
    const auto asset = loaded ? object->mGLTFAsset : nullptr;
    if (mControlsAsset.lock() != asset || (!asset && getChild<LLComboBox>("material_slot")->getItemCount() > 0))
    {
        getChild<LLTextureCtrl>("material")->closeDependentFloater();
        mControlsAsset = asset;
        if (asset) mStatus.clear();
        auto* slots = getChild<LLComboBox>("material_slot");
        slots->removeall();
        if (asset)
        {
            slots->add("All materials", LLSD(-1));
            for (S32 i = 0; i < S32(asset->mMaterials.size()); ++i)
                slots->add(asset->mMaterials[i].mName.empty() ? llformat("Material %d", i + 1) : asset->mMaterials[i].mName, LLSD(i));
        }
        slots->selectFirstItem();
        if (!asset)
        {
            getChild<LLTextureCtrl>("material")->setImageAssetID(LLUUID::null);
            getChild<LLCheckBoxCtrl>("override_factors")->setValue(false);
            getChild<LLCheckBoxCtrl>("override_factors")->setTentative(false);
            getChild<LLTextBox>("material_status")->setText(std::string());
        }
        updateMaterialControls();
    }
    const bool controls_enabled = valid && loaded && !mPickerPending && !asset->mMaterials.empty();
    for (const char* name : {"material_slot", "material", "override_factors", "reset_material"})
        getChild<LLUICtrl>(name)->setEnabled(controls_enabled);
    if (asset && !getChild<LLTextureCtrl>("material")->isPickerShown() &&
        !getChild<LLSpinCtrl>("roughness")->hasFocus() && !getChild<LLSpinCtrl>("metallic")->hasFocus())
        updateMaterialControls();
    const auto* overrides = getChild<LLCheckBoxCtrl>("override_factors");
    for (const char* name : {"roughness", "metallic"})
        getChild<LLSpinCtrl>(name)->setEnabled(controls_enabled && overrides->get() && !overrides->getTentative());
    if (target != mStatusTarget)
    {
        mStatus.clear();
        mStatusTarget = target;
    }
    getChild<LLButton>("load")->setEnabled(valid && !mPickerPending);
    getChild<LLButton>("reload")->setEnabled(valid && loaded && !mPickerPending);
    getChild<LLButton>("remove")->setEnabled(loaded && !mPickerPending);
    auto* auto_reload = getChild<LLCheckBoxCtrl>("auto_reload");
    auto_reload->setEnabled(valid && loaded && !mPickerPending);
    auto_reload->setValue(loaded ? static_cast<LocalMeshAsset&>(*asset).mAutoReload : true);
    auto node = object ? LLSelectMgr::getInstance()->getSelection()->findNode(object) : nullptr;
    getChild<LLTextBox>("target")->setText(node ? node->mName : getString("no_target"));
    getChild<LLTextBox>("filename")->setText(loaded ? gDirUtilp->getBaseFileName(object->mGLTFAsset->mFilename) : getString("no_file"));
    getChild<LLTextBox>("filename")->setToolTip(loaded ? object->mGLTFAsset->mFilename : "");
    std::string status = !mStatus.empty() ? mStatus : getString(valid ? (loaded ? "ready" : "choose_file") : "select_prim");
    if (valid && loaded && (mStatus.empty() || mStatus == getString("ready")))
    {
        const auto& preview = static_cast<LocalMeshAsset&>(*asset);
        if (preview.mAutoReload)
            status = getString(!preview.mFileStamp ? "auto_missing" : preview.mReloadPending ? "auto_waiting" :
                preview.mAutoReloadFailed ? "auto_failed" : "auto_ready");
    }
    getChild<LLTextBox>("status")->setText(status);
    LLFloater::draw();
}

void LLFloaterLocalMesh::browse()
{
    LLViewerObject* object = getTarget();
    if (!eligible(object) || mPickerPending) return;
    const LLUUID id = object->getID();
    const auto handle = getHandle();
    mPickerPending = true;
    LLFilePickerReplyThread::startPicker(
        [handle, id](const std::vector<std::string>& files, LLFilePicker::ELoadFilter, LLFilePicker::ESaveFilter)
        {
            auto* self = static_cast<LLFloaterLocalMesh*>(handle.get());
            if (!self || LLAppViewer::instance()->quitRequested()) return;
            self->mPickerPending = false;
            if (!files.empty()) self->load(id, files.front(), false);
        }, LLFilePicker::FFLOAD_MODEL, false,
        [handle](const std::vector<std::string>&, LLFilePicker::ELoadFilter, LLFilePicker::ESaveFilter)
        {
            if (auto* self = static_cast<LLFloaterLocalMesh*>(handle.get())) self->mPickerPending = false;
        });
}

void LLFloaterLocalMesh::reload()
{
    LLViewerObject* object = getTarget();
    if (eligible(object) && object->mGLTFAsset && object->mGLTFAsset->mLocalMeshPreview)
        load(object->getID(), object->mGLTFAsset->mFilename, true);
}

void LLFloaterLocalMesh::load(const LLUUID& id, const std::string& filename, bool preserve_placement)
{
    mStatusTarget = id;
    mStatus = getString("load_failed");
    LLViewerObject* object = gObjectList.findObject(id);
    if (!eligible(object))
    {
        mStatus = getString("select_prim");
        return;
    }
    // The simulator's GLTFEnabled flag also enables upload features. Keep local
    // shader availability independent of that capability and its upload paths.
    if (!gSavedSettings.getBOOL("LocalMeshRendering"))
    {
        gSavedSettings.setBOOL("LocalMeshRendering", true);
        LLViewerShaderMgr::instance()->setShaders();
    }
    if (!gSavedSettings.getBOOL("RenderCanUseGLTFPBROpaqueShaders") ||
        gGLTFPBRMetallicRoughnessProgram.mGLTFVariants.empty())
    {
        mStatus = getString("shader_unavailable");
        return;
    }
    if (replacePreview(*object, filename, preserve_placement)) mStatus = getString("ready");
}

void LLFloaterLocalMesh::remove()
{
    LLViewerObject* object = getTarget();
    if (!object || !object->mGLTFAsset || !object->mGLTFAsset->mLocalMeshPreview) return;
    object->mGLTFAsset.reset();
    object->markForUpdate();
    mStatusTarget = object->getID();
    mStatus = getString("removed");
}

void LLFloaterLocalMesh::updateMaterialControls()
{
    auto asset = mControlsAsset.lock();
    if (!asset || asset->mMaterials.empty()) return;
    const auto& preview = static_cast<LocalMeshAsset&>(*asset);
    const S32 selected = getChild<LLComboBox>("material_slot")->getValue().asInteger();
    const S32 slot = llmax(0, selected);
    if (size_t(slot) >= preview.mPreviewMaterials.size()) return;
    const auto& material = asset->mMaterials[slot].mPbrMetallicRoughness;
    getChild<LLSpinCtrl>("roughness")->setValue(material.mRoughnessFactor);
    getChild<LLSpinCtrl>("metallic")->setValue(material.mMetallicFactor);
    getChild<LLTextureCtrl>("material")->setImageAssetID(preview.mPreviewMaterials[slot].mID);
    const bool override_factors = preview.mPreviewMaterials[slot].mRoughness.has_value() ||
        preview.mPreviewMaterials[slot].mMetallic.has_value();
    bool mixed_roughness = false, mixed_metallic = false, mixed_material = false, mixed_overrides = false;
    if (selected < 0)
        for (size_t i = 1; i < asset->mMaterials.size(); ++i)
        {
            mixed_roughness |= asset->mMaterials[i].mPbrMetallicRoughness.mRoughnessFactor != material.mRoughnessFactor;
            mixed_metallic |= asset->mMaterials[i].mPbrMetallicRoughness.mMetallicFactor != material.mMetallicFactor;
            mixed_material |= preview.mPreviewMaterials[i].mID != preview.mPreviewMaterials[slot].mID;
            mixed_overrides |= (preview.mPreviewMaterials[i].mRoughness.has_value() ||
                preview.mPreviewMaterials[i].mMetallic.has_value()) != override_factors;
        }
    getChild<LLSpinCtrl>("roughness")->setTentative(mixed_roughness);
    getChild<LLSpinCtrl>("metallic")->setTentative(mixed_metallic);
    getChild<LLTextureCtrl>("material")->setTentative(mixed_material);
    // Clicking a mixed selection enables overrides on every selected surface.
    getChild<LLCheckBoxCtrl>("override_factors")->setValue(override_factors && !mixed_overrides);
    getChild<LLCheckBoxCtrl>("override_factors")->setTentative(mixed_overrides);
    bool fetching = false, failed = false;
    for (size_t i = 0; i < preview.mPreviewMaterials.size(); ++i)
        if (selected < 0 || i == size_t(selected))
        {
            auto* fetched = preview.mPreviewMaterials[i].mFetched.get();
            fetching |= fetched && fetched->isFetching();
            failed |= fetched && !fetched->isFetching() && !fetched->isLoaded();
        }
    getChild<LLTextBox>("material_status")->setText(getString(fetching ? "material_loading" :
        failed ? "material_failed" : "material_help"));
}

void LLFloaterLocalMesh::selectMaterial()
{
    auto asset = mControlsAsset.lock();
    auto* object = getTarget();
    if (!eligible(object) || !asset || object->mGLTFAsset != asset) return;
    auto& preview = static_cast<LocalMeshAsset&>(*asset);
    const S32 selected = getChild<LLComboBox>("material_slot")->getValue().asInteger();
    const LLUUID id = getChild<LLTextureCtrl>("material")->getImageAssetID();
    for (size_t i = 0; i < preview.mPreviewMaterials.size(); ++i)
        if (selected < 0 || i == size_t(selected))
        {
            auto& slot = preview.mPreviewMaterials[i];
            if (slot.mID == id) continue;
            slot = PreviewMaterial{};
            slot.mID = id;
            if (id.notNull()) slot.mFetched = gGLTFMaterialList.getMaterial(id);
        }
    preview.mMaterialsDirty = true;
    updateLocalMeshMaterials(*asset);
    updateMaterialControls();
}

void LLFloaterLocalMesh::toggleFactorOverrides()
{
    auto asset = mControlsAsset.lock();
    auto* object = getTarget();
    if (!eligible(object) || !asset || object->mGLTFAsset != asset) return;
    auto& preview = static_cast<LocalMeshAsset&>(*asset);
    const S32 selected = getChild<LLComboBox>("material_slot")->getValue().asInteger();
    const bool enabled = getChild<LLCheckBoxCtrl>("override_factors")->get();
    for (size_t i = 0; i < preview.mPreviewMaterials.size(); ++i)
        if (selected < 0 || i == size_t(selected))
        {
            auto& slot = preview.mPreviewMaterials[i];
            if (enabled)
            {
                // Start from each surface's own values without flattening a
                // mixed selection to the first surface's factors.
                const auto& material = asset->mMaterials[i].mPbrMetallicRoughness;
                if (!slot.mRoughness) slot.mRoughness = material.mRoughnessFactor;
                if (!slot.mMetallic) slot.mMetallic = material.mMetallicFactor;
            }
            else
            {
                slot.mRoughness.reset();
                slot.mMetallic.reset();
            }
        }
    preview.mMaterialsDirty = true;
    updateLocalMeshMaterials(*asset);
    updateMaterialControls();
}

void LLFloaterLocalMesh::changeFactor(bool roughness)
{
    const auto* overrides = getChild<LLCheckBoxCtrl>("override_factors");
    if (!overrides->get() || overrides->getTentative()) return;
    auto asset = mControlsAsset.lock();
    auto* object = getTarget();
    if (!eligible(object) || !asset || object->mGLTFAsset != asset) return;
    auto& preview = static_cast<LocalMeshAsset&>(*asset);
    const S32 selected = getChild<LLComboBox>("material_slot")->getValue().asInteger();
    const F32 value = llclamp(F32(getChild<LLSpinCtrl>(roughness ? "roughness" : "metallic")->getValue().asReal()), 0.f, 1.f);
    for (size_t i = 0; i < preview.mPreviewMaterials.size(); ++i)
        if (selected < 0 || i == size_t(selected))
        {
            auto& slot = preview.mPreviewMaterials[i];
            (roughness ? slot.mRoughness : slot.mMetallic) = value;
        }
    preview.mMaterialsDirty = true;
    updateLocalMeshMaterials(*asset);
    updateMaterialControls();
}

void LLFloaterLocalMesh::resetMaterial()
{
    auto asset = mControlsAsset.lock();
    auto* object = getTarget();
    if (!eligible(object) || !asset || object->mGLTFAsset != asset) return;
    auto& preview = static_cast<LocalMeshAsset&>(*asset);
    const S32 selected = getChild<LLComboBox>("material_slot")->getValue().asInteger();
    for (size_t i = 0; i < preview.mPreviewMaterials.size(); ++i)
        if (selected < 0 || i == size_t(selected)) preview.mPreviewMaterials[i] = PreviewMaterial{};
    preview.mMaterialsDirty = true;
    updateLocalMeshMaterials(*asset);
    updateMaterialControls();
}
