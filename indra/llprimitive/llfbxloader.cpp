/**
 * @file llfbxloader.cpp
 * @brief Convert static FBX scenes into the existing mesh upload representation.
 */
#include "linden_common.h"
#include "llfbxloader.h"

#include "lldir.h"
#include "llfile.h"
#include "llmd5.h"
#include "../lib/ufbx/ufbx.h"

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <memory>
#include <set>
#include <stdexcept>

namespace
{
const std::string lod_suffix[LLModel::NUM_LODS] = {"_LOD0", "_LOD1", "_LOD2", "", "_PHYS"};

std::string fbxString(ufbx_string value)
{
    return std::string(value.data, value.length);
}

std::filesystem::path fbxPath(const std::string& value)
{
    std::string path = value;
    std::replace(path.begin(), path.end(), '\\', '/');
    return std::filesystem::path(std::u8string(path.begin(), path.end()));
}

std::string fbxTextureFile(const ufbx_material_map& map, const std::string& filename)
{
    const ufbx_texture* texture = map.texture;
    if (!map.texture_enabled || !texture) return {};
    // Layered/procedural shaders cannot be represented by a diffuse texture.
    if (texture->type != UFBX_TEXTURE_FILE) return {};
    std::string texture_name = fbxString(texture->filename);
    if (texture->content.size)
    {
        std::string extension = gDirUtilp->getExtension(texture_name);
        LLStringUtil::toLower(extension);
        if (extension != "png" && extension != "jpg" && extension != "jpeg" &&
            extension != "tga" && extension != "bmp") return {};
        // LLImportMaterial uses filenames. Cache embedded images by content,
        // rather than writing beside the user's FBX or trusting its paths.
        LLMD5 digest;
        digest.update(static_cast<const U8*>(texture->content.data), texture->content.size);
        digest.finalize();
        char hash[MD5HEX_STR_SIZE];
        digest.hex_digest(hash);
        const std::string path = gDirUtilp->getExpandedFilename(LL_PATH_CACHE,
            std::string("fbx-texture-") + hash + "." + extension);
        if (!gDirUtilp->fileExists(path))
        {
            llofstream output(path, std::ios::binary);
            output.write(static_cast<const char*>(texture->content.data), std::streamsize(texture->content.size));
            output.close();
            if (!output)
            {
                LLFile::remove(path);
                throw std::runtime_error("Could not cache an embedded FBX texture.");
            }
        }
        return path;
    }
    const auto directory = fbxPath(filename).parent_path();
    // Prefer paths relative to the export, including Blender's copied texture
    // directory. Fall back to the original absolute path or a relocated image.
    for (const auto& path : {directory / fbxPath(fbxString(texture->relative_filename)),
             fbxPath(texture_name), fbxPath(fbxString(texture->absolute_filename)),
             directory / fbxPath(texture_name).filename()})
    {
        std::error_code error;
        if (std::filesystem::is_regular_file(path, error))
        {
            const auto utf8 = path.u8string();
            return std::string(utf8.begin(), utf8.end());
        }
    }
    LL_WARNS("FBX") << "Missing diffuse texture: " << texture_name << LL_ENDL;
    return {};
}

F32 fbxFactor(const ufbx_material_map& map, F32 fallback)
{
    const F32 value = map.has_value ? F32(map.value_real) : fallback;
    if (!std::isfinite(value)) throw std::runtime_error("FBX contains a non-finite material factor.");
    return llclamp(value, 0.f, 1.f);
}

// Chunk triangle corners before deduplication to keep every face safely within
// the upload format's 16-bit vertex limit, even when every corner has a UV seam.
struct FBXVertex
{
    F32 position[3];
    F32 normal[3];
    F32 uv[2];
};

void appendFBXFace(LLModel& model, std::vector<FBXVertex>& vertices, const std::string& binding)
{
    if (vertices.empty()) return;
    std::vector<U32> indices(vertices.size());
    ufbx_vertex_stream stream{vertices.data(), vertices.size(), sizeof(FBXVertex)};
    const size_t count = ufbx_generate_indices(&stream, 1, indices.data(), indices.size(), nullptr, nullptr);
    if (!count || count >= 65535) throw std::runtime_error("Could not index FBX geometry.");
    auto& face = model.getVolumeFaces().emplace_back();
    face.resizeVertices(S32(count));
    face.resizeIndices(S32(indices.size()));
    for (size_t i = 0; i < count; ++i)
    {
        const auto& vertex = vertices[i];
        face.mPositions[i].load3(vertex.position);
        face.mNormals[i].load3(vertex.normal);
        face.mTexCoords[i].set(vertex.uv);
        if (i == 0)
        {
            face.mExtents[0] = face.mExtents[1] = face.mPositions[i];
            face.mTexCoordExtents[0] = face.mTexCoordExtents[1] = face.mTexCoords[i];
        }
        else
        {
            update_min_max(face.mExtents[0], face.mExtents[1], face.mPositions[i]);
            update_min_max(face.mTexCoordExtents[0], face.mTexCoordExtents[1], face.mTexCoords[i]);
        }
    }
    face.mCenter->setAdd(face.mExtents[0], face.mExtents[1]);
    face.mCenter->mul(0.5f);
    for (size_t i = 0; i < indices.size(); ++i) face.mIndices[i] = U16(indices[i]);
    model.mMaterialList.push_back(binding);
    vertices.clear();
}
}

bool LLFBXLoader::OpenFile(const std::string& filename)
{
    setLoadState(READING_FILE);
    mModelList.clear();
    mScene.clear();
    mMaterialFactors.clear();
    auto fail = [this](const std::string& reason)
    {
        LL_WARNS("FBX") << reason << LL_ENDL;
        LLSD warning;
        warning["Message"] = "FBXImportError";
        warning["REASON"] = reason;
        mWarningsArray.append(warning);
        setLoadState(ERROR_PARSING);
        return false;
    };

    ufbx_load_opts options{};
    options.file_format = UFBX_FILE_FORMAT_FBX;
    options.target_axes = ufbx_axes_right_handed_z_up;
    options.target_unit_meters = 1.0;
    options.generate_missing_normals = true;
    options.use_blender_pbr_material = true;
    options.ignore_animation = true; // Import static transforms, not animation playback.
    options.strict = true;
    options.index_error_handling = UFBX_INDEX_ERROR_HANDLING_ABORT_LOADING;
    options.node_depth_limit = 512;
    options.temp_allocator.memory_limit = 512 * 1024 * 1024;
    options.result_allocator.memory_limit = 512 * 1024 * 1024;
    ufbx_error error{};
    std::unique_ptr<ufbx_scene, decltype(&ufbx_free_scene)> source(
        ufbx_load_file(filename.c_str(), &options, &error), &ufbx_free_scene);
    if (!source)
    {
        char message[1024];
        ufbx_format_error(message, sizeof(message), &error);
        return fail(message);
    }

    try
    {
        material_map materials;
        std::map<const ufbx_material*, std::string> bindings;
        std::set<std::string> material_names;
        auto materialBinding = [&](const ufbx_material* source_material) -> std::string
        {
            auto found = bindings.find(source_material);
            if (found != bindings.end()) return found->second;
            std::string name = source_material ? fbxString(source_material->name) : "Default material";
            if (name.empty()) name = "Material";
            const std::string base = name;
            for (size_t suffix = 2; !material_names.insert(name).second; ++suffix)
                name = base + " " + std::to_string(suffix);
            bindings[source_material] = name;
            auto& material = materials[name];
            material.mBinding = name;
            auto& factors = mMaterialFactors[name];
            if (source_material)
            {
                const auto& pbr = source_material->pbr;
                const auto color = pbr.base_color.value_vec3;
                const F32 factor = fbxFactor(pbr.base_factor, 1.f);
                if (pbr.base_color.has_value)
                    material.mDiffuseColor.set(F32(color.x) * factor, F32(color.y) * factor,
                        F32(color.z) * factor, fbxFactor(pbr.opacity, 1.f));
                else
                    material.mDiffuseColor.set(factor, factor, factor, fbxFactor(pbr.opacity, 1.f));
                for (F32 channel : material.mDiffuseColor.mV)
                    if (!std::isfinite(channel)) throw std::runtime_error("FBX contains an invalid material color.");
                material.mFullbright = source_material->features.unlit.enabled;
                material.mDiffuseMapFilename = fbxTextureFile(pbr.base_color, filename);
                material.mDiffuseMapLabel = gDirUtilp->getBaseFileName(material.mDiffuseMapFilename);
                factors.mRoughness = fbxFactor(pbr.roughness, 0.5f);
                if (source_material->features.roughness_as_glossiness.enabled)
                    factors.mRoughness = 1.f - factors.mRoughness;
                factors.mMetallic = fbxFactor(pbr.metalness, 0.f);
            }
            return name;
        };

        model_list models;
        scene instances;
        std::set<std::string> model_names;
        size_t triangle_count = 0;
        LLVolumeParams params;
        params.setType(LL_PCODE_PROFILE_SQUARE, LL_PCODE_PATH_LINE);
        setLoadState(CREATING_FACES);
        for (const ufbx_node* node : source->nodes)
        {
            const ufbx_mesh* mesh = node->mesh;
            if (!mesh || !mesh->num_triangles) continue;
            if (mesh->all_deformers.count)
                return fail("Rigged meshes, blend shapes and geometry caches are not supported by the static FBX importer.");
            triangle_count += mesh->num_triangles;
            if (triangle_count > 2000000) return fail("FBX exceeds the two-million-triangle import limit.");
            std::string name = fbxString(node->name);
            if (name.empty()) name = "Mesh";
            for (const auto& suffix : lod_suffix)
                if (!suffix.empty() && name.size() > suffix.size() &&
                    name.compare(name.size() - suffix.size(), suffix.size(), suffix) == 0)
                {
                    name.resize(name.size() - suffix.size());
                    break;
                }
            const std::string base = name;
            for (size_t suffix = 2; !model_names.insert(name).second; ++suffix)
                name = base + "_" + std::to_string(suffix);
            LLPointer<LLModel> model = new LLModel(params, F32(mLod));
            model->ClearFacesAndMaterials();
            // Baking includes hierarchy, pivots, geometric transforms and units.
            // It also removes shear/negative scales that cannot be uploaded as prim transforms.
            const auto& transform = node->geometry_to_world;
            const auto normal_transform = ufbx_matrix_for_normals(&transform);
            const double determinant = ufbx_matrix_determinant(&transform);
            if (!std::isfinite(determinant) || determinant == 0.0)
                return fail("FBX contains a singular or non-finite mesh transform.");
            const bool mirrored = determinant < 0.0;
            std::vector<U32> triangle_indices(mesh->max_face_triangles * 3);
            for (const auto& part : mesh->material_parts)
            {
                if (!part.num_triangles) continue;
                const std::string binding = materialBinding(part.index < node->materials.count ? node->materials[part.index] : nullptr);
                std::vector<FBXVertex> vertices;
                constexpr size_t max_corners = 65532;
                vertices.reserve(std::min(part.num_triangles * 3, max_corners));
                for (U32 face_index : part.face_indices)
                {
                    const auto face = mesh->faces[face_index];
                    if (face.num_indices < 3) continue;
                    const size_t triangles = ufbx_triangulate_face(triangle_indices.data(), triangle_indices.size(), mesh, face);
                    if (!triangles) return fail("Could not triangulate an FBX polygon.");
                    for (size_t corner = 0; corner < triangles * 3; ++corner)
                    {
                        const size_t offset = mirrored ? (corner / 3) * 3 + (corner % 3 == 0 ? 0 : 3 - corner % 3) : corner;
                        const U32 index = triangle_indices[offset];
                        const auto position = ufbx_transform_position(&transform, mesh->vertex_position[index]);
                        auto normal = ufbx_transform_direction(&normal_transform, mesh->vertex_normal[index]);
                        normal = ufbx_vec3_normalize(normal);
                        const auto uv = mesh->vertex_uv.exists ? mesh->vertex_uv[index] : ufbx_vec2{};
                        FBXVertex vertex{{F32(position.x), F32(position.y), F32(position.z)},
                            {F32(normal.x), F32(normal.y), F32(normal.z)}, {F32(uv.x), F32(uv.y)}};
                        for (F32 value : vertex.position) if (!std::isfinite(value)) return fail("FBX contains invalid vertex positions.");
                        for (F32 value : vertex.normal) if (!std::isfinite(value)) return fail("FBX contains invalid normals.");
                        for (F32 value : vertex.uv) if (!std::isfinite(value)) return fail("FBX contains invalid texture coordinates.");
                        vertices.push_back(vertex);
                        if (vertices.size() == max_corners) appendFBXFace(*model, vertices, binding);
                    }
                }
                appendFBXFace(*model, vertices, binding);
            }
            if (!model->getNumVolumeFaces()) continue;
            model->sortVolumeFacesByMaterialName();
            if (!mNoNormalize) model->normalizeVolumeFaces();
            // Split into the simulator's eight-face meshes, retaining one
            // normalization for the entire source object and stable LOD labels.
            for (S32 part = 0; model; ++part)
            {
                if (models.size() >= mGeneratedModelLimit) return fail("FBX exceeds ImporterModelLimit after splitting mesh faces.");
                LLPointer<LLModel> next;
                if (model->getNumVolumeFaces() > LL_SCULPT_MESH_MAX_FACES)
                {
                    next = new LLModel(params, F32(mLod));
                    next->getVolumeFaces().assign(model->getVolumeFaces().begin() + LL_SCULPT_MESH_MAX_FACES, model->getVolumeFaces().end());
                    next->mMaterialList.assign(model->mMaterialList.begin() + LL_SCULPT_MESH_MAX_FACES, model->mMaterialList.end());
                    next->mNormalizedScale = model->mNormalizedScale;
                    next->mNormalizedTranslation = model->mNormalizedTranslation;
                    model->trimVolumeFacesToSize();
                    model->mMaterialList.resize(LL_SCULPT_MESH_MAX_FACES);
                }
                if (!mNoOptimize) model->remapVolumeFaces();
                if (!validate_model(model)) return fail("FBX generated an invalid mesh face.");
                const std::string label = name + (part ? "_part" + std::to_string(part) : "");
                model->mLabel = label + lod_suffix[mLod];
                model->mSubmodelID = part;
                LLMatrix4 placement;
                placement.initScale(model->mNormalizedScale);
                placement.setTranslation(model->mNormalizedTranslation);
                material_map instance_materials;
                for (const auto& binding : model->mMaterialList) instance_materials[binding] = materials[binding];
                instances[placement].push_back(LLModelInstance(model, label, placement, instance_materials));
                models.push_back(model);
                model = next;
            }
        }
        if (models.empty()) return fail("FBX contains no polygon meshes.");
        std::sort(models.begin(), models.end(), [](const auto& a, const auto& b)
        {
            if (a->mSubmodelID != b->mSubmodelID) return a->mSubmodelID < b->mSubmodelID;
            return LLStringUtil::compareInsensitive(a->mLabel, b->mLabel) < 0;
        });
        mModelList = std::move(models);
        mScene = std::move(instances);
        mFirstTransform = true;
        for (const auto& entry : mScene)
            for (const auto& instance : entry.second) stretch_extents(instance.mModel, instance.mTransform);
        setLoadState(DONE);
        return true;
    }
    catch (const std::exception& exception)
    {
        return fail(exception.what());
    }
}
