#include "llviewerprecompiledheaders.h"
#include "llhairmesh.h"
#include "llavatarneutralskeleton.h"
#include "llhairmeshtree.h"
#include "llhairguidefit.h"
#include "llframetimer.h"
#include "llglslshader.h"
#include "llimagegl.h"
#include "llmodel.h"
#include "llrender.h"
#include "llskinningutil.h"
#include "llviewerautomation.h"
#include "llviewercontrol.h"
#include "llviewerobjectlist.h"
#include "llviewertexture.h"
#include "llviewerjointattachment.h"
#include "llviewershadermgr.h"
#include "llvoavatarself.h"
#include "llvovolume.h"
#include <map>
#include <deque>

namespace
{
LLGLSLShader sSkinShader, sRefitShader, sCacheShader, sDebugShader;
LLGLSLShader sGuideShader;
U32 sGuides[2] = {}, sGuideTextures[2] = {}, sGuideFrames[2] = {};
S32 sGuideCurrent = 0;
S32 sGuideCount = 0;
F64 sGuideTime = 0.0;
LLVector3 sGuidePivot;
LLQuaternion sGuideRotation;
U32 sInputs[4] = {}, sShells[2] = {}, sTextures[2] = {}, sFrames[2] = {};
U32 sLastUpdate = 0, sTriangles = 0, sNodes = 0, sBakes = 0;
S32 sCurrent = 0;
bool sReady = false, sDirty = true;
LLVector3 sCentres[2];
constexpr U32 CONTACT_POINTS = 21 * 21 * 32;
bool sContacts[2] = {};
LLVector3 sContactPivots[2];
LLQuaternion sContactRotations[2];
F64 sContactTime = 0.0;
std::vector<U32> sLevelOffsets;
std::map<U64, U32> sPaletteOffsets;
struct Mesh
{
    LLUUID id;
    LLPointer<LLVolume> volume;
    U64 skinHash;
    std::vector<U8> faces;
};
std::vector<Mesh> sMeshes;
// Match captured triangle identities to their attachment and material face.
std::vector<U32> sTriangleSources;
constexpr S32 GUIDE_PROBE_PARTS = 7;
std::vector<Mesh> sGuideMeshes;
std::vector<Mesh> sGuideBodies;
std::map<LLUUID, S32> sGuideBindings;
constexpr S32 MAX_GUIDES = 64;
S32 sGuideSkeleton = -1;
std::vector<F32> sTracePalette;
F32 sTracePaletteDelta = 0.f;
LLSD sGuideTrace = LLSD::emptyArray();
LLSD sGuideSnapshot = LLSD::emptyArray();
U32 sGuideTraceDropped = 0, sGuideFits = 0, sGuideResets = 0;
U32 sGuideHeadAdjusted = 0, sGuideHeadTests = 0;
bool sGuideHeadLimited = false;

#if !LL_DARWIN
struct GuideReadback
{
    GLuint buffer = 0;
    GLsync fence = nullptr;
    U32 frame = 0;
    U32 bake = 0;
    S32 count = 0;
    F32 dt = 0.f;
    F32 paletteDelta = 0.f;
    bool history = false, fit = false, meshHistory = false;
    glm::mat4 fromPrevious{1.f};
};
GuideReadback sGuideReadbacks[3];
GLuint sGuideProbe = 0;
std::deque<S32> sGuidePending;
std::vector<glm::vec4> sGuideLastSample;
U32 sGuideLastSampleFrame = 0;
F64 sGuideCapture = 0.0;

void releaseGuideReadbacks(bool releaseProbe = true)
{
    if (releaseProbe)
    {
        if (sGuideProbe) glDeleteBuffers(1, &sGuideProbe);
        sGuideProbe = 0;
    }
    for (auto& sample : sGuideReadbacks)
    {
        if (sample.fence) glDeleteSync(sample.fence);
        if (sample.buffer) glDeleteBuffers(1, &sample.buffer);
        sample = GuideReadback();
    }
    sGuidePending.clear();
    sGuideLastSample.clear();
    sGuideLastSampleFrame = 0;
    sGuideCapture = 0.0;
}

void captureGuides(F32 dt, bool history, bool fit, bool meshHistory, const glm::mat4& fromPrevious)
{
    const F64 capture = LLViewerAutomation::captureStarted();
    if (!capture)
    {
        if (sGuideCapture) releaseGuideReadbacks();
        return;
    }
    if (capture != sGuideCapture)
    {
        releaseGuideReadbacks(false);
        sGuideCapture = capture;
        sGuideTrace = LLSD::emptyArray();
        sGuideSnapshot = LLSD::emptyArray();
        sGuideTraceDropped = 0;
    }
    // Read completed copies in order. A busy GPU costs a sample, never a main-thread wait.
    while (!sGuidePending.empty())
    {
        auto& sample = sGuideReadbacks[sGuidePending.front()];
        const GLenum status = glClientWaitSync(sample.fence, 0, 0);
        if (status == GL_TIMEOUT_EXPIRED) break;
        if (status == GL_ALREADY_SIGNALED || status == GL_CONDITION_SATISFIED)
        {
            std::vector<glm::vec4> data(sample.count * (27 + 9 * GUIDE_PROBE_PARTS));
            glBindBuffer(GL_COPY_READ_BUFFER, sample.buffer);
            glGetBufferSubData(GL_COPY_READ_BUFFER, 0, data.size() * sizeof(glm::vec4), data.data());
            glBindBuffer(GL_COPY_READ_BUFFER, 0);
            LLSD row;
            row["frame"] = LLSD::Integer(sample.frame);
            row["dt_ms"] = sample.dt * 1000.f;
            row["history"] = sample.history;
            row["fit"] = sample.fit;
            row["mesh_history"] = sample.meshHistory;
            row["palette_max_element_change"] = sample.paletteDelta;
            const bool consecutive = sGuideLastSampleFrame + 1 == sample.frame && sGuideLastSample.size() == data.size();
            row["consecutive"] = consecutive;
            F32 peak = 0.f, tipPeak = 0.f, residualPeak = 0.f;
            S32 peakIndex = 0;
            if (consecutive)
            for (S32 chain = 0; chain < sample.count; ++chain)
            for (S32 node = 1; node < 9; ++node)
            {
                const S32 base = chain * 27 + node;
                const glm::vec3 before(sample.fromPrevious * glm::vec4(glm::vec3(sGuideLastSample[base + 9]), 1));
                const glm::vec3 delta = glm::vec3(data[base + 9]) - before;
                const F32 distance = glm::length(delta);
                if (distance > peak) { peak = distance; peakIndex = base; }
                if (node == 8) tipPeak = llmax(tipPeak, distance);
                const glm::vec3 freeVelocity = glm::mat3(sample.fromPrevious) * glm::vec3(sGuideLastSample[base + 18]);
                residualPeak = llmax(residualPeak, glm::length(delta - freeVelocity * sample.dt));
            }
            row["max_step_m"] = peak;
            row["max_tip_step_m"] = tipPeak;
            row["max_velocity_residual_m"] = residualPeak;
            row["chain"] = peakIndex / 27;
            row["node"] = peakIndex % 27;
            row["contact"] = data[peakIndex + 18].w > 0.f;
            row["previous_contact"] = consecutive && sGuideLastSample[peakIndex + 18].w > 0.f;
            for (S32 axis = 0; axis < 3; ++axis) row["position"].append(data[peakIndex + 9][axis]);
            const auto describePoint = [&](LLSD& point, S32 base)
            {
                if (base % 27 == 0) return;
                const S32 probe = sample.count * 27 + ((base / 27) * 9 + base % 27) * GUIDE_PROBE_PARTS;
                for (S32 part = 0; part < GUIDE_PROBE_PARTS; ++part)
                for (S32 axis = 0; axis < 4; ++axis) point["probe"].append(data[probe + part][axis]);
                const S32 offset = S32(data[probe + 3].w) - 1 - S32(sNodes * 2);
                if (sample.bake == sBakes && offset >= 0 && offset % 6 == 0 && U32(offset / 6) < sTriangleSources.size())
                {
                    const U32 source = sTriangleSources[offset / 6], mesh = source >> 8;
                    if (mesh < sMeshes.size())
                    {
                        point["source_object"] = sMeshes[mesh].id;
                        point["source_mesh"] = sMeshes[mesh].volume->getParams().getSculptID();
                        point["source_face"] = LLSD::Integer(source & 255);
                    }
                }
            };
            describePoint(row, peakIndex);
            // Keep one complete snapshot: quiet penetrations are absent from the peak-motion trace.
            if (sGuideSnapshot.size() == 0 || sample.frame % 30 == 0)
            {
                sGuideSnapshot = LLSD::emptyArray();
                for (S32 chain = 0; chain < sample.count; ++chain)
                for (S32 node = 0; node < 9; ++node)
                {
                    const S32 base = chain * 27 + node;
                    LLSD point;
                    point["frame"] = LLSD::Integer(sample.frame);
                    point["chain"] = chain; point["node"] = node;
                    point["contact"] = data[base + 18].w > 0.f;
                    for (S32 axis = 0; axis < 3; ++axis)
                    {
                        point["rest"].append(data[base][axis]);
                        point["position"].append(data[base + 9][axis]);
                    }
                    describePoint(point, base);
                    sGuideSnapshot.append(point);
                }
            }
            // Bounded even for repeated captures or a capture stuck draining its timestamps.
            if (sGuideTrace.size() >= 4096) sGuideTrace.erase(0);
            sGuideTrace.append(row);
            sGuideLastSample = std::move(data);
            sGuideLastSampleFrame = sample.frame;
        }
        else ++sGuideTraceDropped;
        glDeleteSync(sample.fence);
        sample.fence = nullptr;
        sGuidePending.pop_front();
    }
    for (S32 slot = 0; slot < 3; ++slot)
    {
        auto& sample = sGuideReadbacks[slot];
        if (sample.fence) continue;
        if (!sample.buffer)
        {
            glGenBuffers(1, &sample.buffer);
            glBindBuffer(GL_COPY_WRITE_BUFFER, sample.buffer);
            glBufferData(GL_COPY_WRITE_BUFFER, MAX_GUIDES * (27 + 9 * GUIDE_PROBE_PARTS) * sizeof(glm::vec4), nullptr, GL_STREAM_READ);
        }
        glMemoryBarrier(GL_BUFFER_UPDATE_BARRIER_BIT);
        glBindBuffer(GL_COPY_READ_BUFFER, sGuides[sGuideCurrent]);
        glBindBuffer(GL_COPY_WRITE_BUFFER, sample.buffer);
        glCopyBufferSubData(GL_COPY_READ_BUFFER, GL_COPY_WRITE_BUFFER, 0, 0, sGuideCount * 27 * sizeof(glm::vec4));
        if (sGuideProbe)
        {
            glBindBuffer(GL_COPY_READ_BUFFER, sGuideProbe);
            glCopyBufferSubData(GL_COPY_READ_BUFFER, GL_COPY_WRITE_BUFFER, 0, sGuideCount * 27 * sizeof(glm::vec4),
                sGuideCount * 9 * GUIDE_PROBE_PARTS * sizeof(glm::vec4));
        }
        glBindBuffer(GL_COPY_READ_BUFFER, 0);
        glBindBuffer(GL_COPY_WRITE_BUFFER, 0);
        sample.fence = glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE, 0);
        if (!sample.fence) { ++sGuideTraceDropped; return; }
        sample.frame = gFrameCount; sample.count = sGuideCount; sample.dt = dt;
        sample.bake = sBakes;
        sample.history = history; sample.fit = fit; sample.meshHistory = meshHistory;
        sample.paletteDelta = sTracePaletteDelta;
        sample.fromPrevious = fromPrevious;
        sGuidePending.push_back(slot);
        return;
    }
    ++sGuideTraceDropped;
}

struct Vertex { glm::vec4 position, normal, weights; glm::uvec4 joints; };
static_assert(sizeof(Vertex) == 64);

bool matchesHairColliderName(std::string name)
{
    static LLCachedControl<std::string> names(gSavedSettings, "BoxxyHairPhysicsColliderNames");
    static std::string cached;
    static std::vector<std::string> terms;
    if (cached != std::string(names))
    {
        cached = names;
        terms = LLStringUtil::getTokens(cached, ",");
        for (auto& term : terms) { LLStringUtil::trim(term); LLStringUtil::toLower(term); }
    }
    LLStringUtil::toLower(name);
    for (const auto& term : terms)
    {
        if (term.empty()) continue;
        for (size_t pos = name.find(term); pos != std::string::npos; pos = name.find(term, pos + 1))
        {
            const size_t end = pos + term.size();
            if ((pos == 0 || !std::isalnum(static_cast<unsigned char>(name[pos - 1]))) &&
                (end == name.size() || !std::isalnum(static_cast<unsigned char>(name[end])))) return true;
        }
    }
    return false;
}

void collect(LLViewerObject* object, std::vector<LLVOVolume*>& bodies, LLVOVolume*& hair)
{
    if (!object || object->isDead() || object->isHUDAttachment()) return;
    if (auto* volume = dynamic_cast<LLVOVolume*>(object))
    {
        if (volume->isHairEnabled())
        {
            if (!hair) hair = volume;
        }
        else if (volume->isMesh() && volume->getVolume() && volume->getSkinInfo() && !volume->isSSSOverlayEnabled())
        {
            const auto* root = volume->getRootEdit();
            // Skin shading's fit-name matches (e.g. Perky) also include clothing with inward-facing linings.
            if (root && matchesHairColliderName(root->hasCachedObjectName() ?
                root->getCachedObjectName() : root->getAttachmentItemName())) bodies.push_back(volume);
        }
    }
    for (const auto& child : object->getChildren()) collect(child, bodies, hair);
}

std::vector<U8> visibleFaces(LLVOVolume& body)
{
    std::vector<U8> faces(body.getVolume()->getNumVolumeFaces());
    for (S32 i = 0; i < S32(faces.size()); ++i)
    {
        const auto* te = body.getTE(i);
        faces[i] = te && te->getColor().mV[3] > 0.001f;
    }
    return faces;
}

void upload(U32& buffer, size_t bytes, const void* data, GLenum usage)
{
    if (!buffer) glGenBuffers(1, &buffer);
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, buffer);
    glBufferData(GL_SHADER_STORAGE_BUFFER, bytes, data, usage);
}

void dispatchContacts(LLGLSLShader& shader)
{
    // Bound individual GPU jobs; cache cells have no dependencies between cells in a pass.
    for (U32 first = 0; first < CONTACT_POINTS; first += 1024)
    {
        shader.uniform1i(LLStaticHashedString("contact_first"), first);
        glDispatchCompute((llmin(1024U, CONTACT_POINTS - first) + 127) / 128, 1, 1);
    }
}

void collectGuideHair(LLViewerObject* object, std::vector<LLVOVolume*>& result)
{
    if (!object || object->isDead() || object->isHUDAttachment()) return;
    if (auto* v = dynamic_cast<LLVOVolume*>(object))
        if (v->getVolume() && v->isHairEnabled()) result.push_back(v);
    for (const auto& child : object->getChildren()) collectGuideHair(child, result);
}

bool fitHeadClearance(const std::vector<LLVOVolume*>& bodies, LLAvatarNeutralSkeleton& skeleton,
    const glm::mat4& toHead, std::vector<glm::vec4>& guides, S32 chains)
{
    std::vector<float> radii(chains * 9, 0.f);
    U32 vertices = 0, triangles = 0;
    sGuideHeadTests = sGuideHeadAdjusted = 0;
    for (auto* body : bodies)
    {
        const auto* skin = body->getSkinInfo();
        const U32 count = LLSkinningUtil::getMeshJointCount(skin);
        if (!count) continue;
        std::vector<bool> headJoints(count, false);
        bool hasHead = false;
        for (U32 j = 0; j < count; ++j)
            for (auto* joint = gAgentAvatarp->getJoint(skin->mJointNames[j]); joint; joint = joint->getParent())
                if (joint == gAgentAvatarp->mHeadp) { headJoints[j] = hasHead = true; break; }
        if (!hasHead) continue;
        std::vector<LLMatrix4a> palette(count);
        if (!skeleton.palette(skin, palette.data(), count)) continue;
        std::vector<glm::mat4> matrices(count);
        const auto bind = glm::make_mat4(skin->mBindShapeMatrix.mMatrix[0].getF32ptr());
        for (U32 j = 0; j < count; ++j)
            matrices[j] = toHead * glm::make_mat4(palette[j].mMatrix[0].getF32ptr()) * bind;
        const auto faces = visibleFaces(*body);
        for (S32 face = 0; face < body->getVolume()->getNumVolumeFaces(); ++face)
        {
            if (!faces[face]) continue;
            const auto& source = body->getVolume()->getVolumeFace(face);
            if (!source.mWeights || !source.mPositions) continue;
            vertices += source.mNumVertices;
            if (vertices > 200000) return false;
            std::vector<glm::vec3> positions(source.mNumVertices);
            std::vector<bool> eligible(source.mNumVertices, false);
            for (S32 i = 0; i < source.mNumVertices; ++i)
            {
                const auto encoded = glm::make_vec4(source.mWeights[i].getF32ptr());
                if (glm::any(glm::isnan(encoded)) || glm::any(glm::isinf(encoded))) continue;
                auto weights = glm::fract(encoded);
                const F32 total = glm::dot(weights, glm::vec4(1));
                if (total < 1.e-8f) continue;
                weights /= total;
                const glm::uvec4 joints(glm::clamp(glm::floor(encoded), glm::vec4(0), glm::vec4(F32(count - 1))));
                glm::vec4 p(0);
                F32 headWeight = 0.f;
                for (S32 k = 0; k < 4; ++k)
                {
                    p += matrices[joints[k]] * glm::vec4(glm::make_vec3(source.mPositions[i].getF32ptr()), 1) * weights[k];
                    if (headJoints[joints[k]]) headWeight += weights[k];
                }
                positions[i] = glm::vec3(p);
                eligible[i] = headWeight > .5f && glm::length(glm::vec3(p)) < .4f;
            }
            for (S32 i = 0; i + 2 < source.mNumIndices; i += 3)
            {
                if (++triangles > 200000) return false;
                glm::vec3 triangle[3];
                bool valid = true;
                for (S32 k = 0; k < 3; ++k)
                {
                    const U32 index = source.mIndices[i + k];
                    if (index >= positions.size() || !eligible[index]) { valid = false; break; }
                    triangle[k] = positions[index];
                }
                if (valid && !LLHairMesh::headClearanceTriangle(triangle, guides, chains, radii, sGuideHeadTests)) return false;
            }
        }
    }
    for (S32 chain = 0; chain < chains; ++chain)
    for (S32 node = 0; node < 9; ++node)
    {
        auto& rest = guides[chain * 27 + node];
        const F32 radius = glm::length(glm::vec2(rest));
        if (radius < 1.e-6f || radii[chain * 9 + node] <= radius) continue;
        const F32 scale = radii[chain * 9 + node] / radius;
        rest.x *= scale; rest.y *= scale;
        guides[chain * 27 + node + 9] = rest;
        ++sGuideHeadAdjusted;
    }
    return true;
}

bool fitGuides(const std::vector<LLVOVolume*>& hair, const std::vector<LLVOVolume*>& bodies,
    const LLVector3& pivot, const LLQuaternion& rotation, S32 chainCount)
{
    struct Binding { LLUUID id; std::vector<glm::vec4> palette; };
    std::vector<Binding> bindings;
    std::vector<glm::vec3> points;
    sGuideMeshes.clear();
    sGuideBodies.clear();
    for (auto* body : bodies)
        sGuideBodies.push_back({body->getID(), body->getVolume(), body->getSkinInfo()->mHash, visibleFaces(*body)});
    sGuideBindings.clear();
    std::vector<glm::vec4> data(chainCount * 27, glm::vec4(0));
    LLAvatarNeutralSkeleton skeleton(*gAgentAvatarp);
    auto* head = skeleton.joint(gAgentAvatarp->mHeadp);
    const LLQuaternion neutral_rotation = head->getWorldRotation();
    const LLVector3 neutral_pivot = head->getWorldPosition() + LLVector3(0.f, 0.f, .08f) * neutral_rotation;
    const LLMatrix4 inverse_head(~neutral_rotation);
    const glm::mat3 inverse = glm::mat3(glm::make_mat4(&inverse_head.mMatrix[0][0]));
    for (auto* object : hair)
    {
        const auto* skin = object->getSkinInfo();
        const auto* volume = object->getVolume();
        sGuideMeshes.push_back({object->getID(), object->getVolume(), skin ? skin->mHash : 0, visibleFaces(*object)});
        const U32 count = skin ? LLSkinningUtil::getMeshJointCount(skin) : 0;
        std::vector<LLMatrix4a> palette(count);
        if (count && !skeleton.palette(skin, palette.data(), count)) return false;
        const glm::mat4 bind = skin ? glm::make_mat4(skin->mBindShapeMatrix.mMatrix[0].getF32ptr()) : glm::mat4(1);
        const LLMatrix4 unrigged_rotation(object->getRenderRotation());
        const glm::mat3 unrigged = glm::mat3(glm::make_mat4(&unrigged_rotation.mMatrix[0][0]));
        const LLVector3 origin = count ? -neutral_pivot : object->getRenderPosition() - pivot;
        const LLMatrix4 live_inverse_head(~rotation);
        const glm::mat3 object_inverse = count ? inverse : glm::mat3(glm::make_mat4(&live_inverse_head.mMatrix[0][0]));
        bindings.push_back({object->getID(), {}});
        auto& binding = bindings.back();
        binding.palette.emplace_back(F32(count), 0.f, 0.f, 0.f);
        if (count)
        {
            const glm::mat4 to_head = glm::mat4(inverse) * glm::translate(glm::mat4(1), glm::make_vec3(origin.mV));
            for (U32 joint = 0; joint < count; ++joint)
            {
                // Render vertices already include bind shape; freeze only skinning in the guide fit's head frame.
                const glm::mat4 reference = to_head * glm::make_mat4(palette[joint].mMatrix[0].getF32ptr());
                for (S32 column = 0; column < 4; ++column) binding.palette.push_back(reference[column]);
            }
        }
        for (S32 face = 0; face < volume->getNumVolumeFaces(); ++face)
        {
            const auto& source = volume->getVolumeFace(face);
            if (!sGuideMeshes.back().faces[face] || !source.mPositions) continue;
            // Fit from a bounded sample, independent of the hairstyle's triangle count.
            const S32 stride = llmax(1, source.mNumVertices / 2048);
            for (S32 i = 0; i < source.mNumVertices; i += stride)
            {
                glm::vec3 p = glm::make_vec3(source.mPositions[i].getF32ptr());
                if (count && source.mWeights)
                {
                    const glm::vec4 encoded = glm::make_vec4(source.mWeights[i].getF32ptr());
                    if (glm::any(glm::isnan(encoded)) || glm::any(glm::isinf(encoded))) continue;
                    glm::vec4 weights = glm::fract(encoded);
                    const F32 total = glm::dot(weights, glm::vec4(1));
                    if (total < 1.e-8f) continue;
                    weights /= total;
                    const glm::uvec4 joints(glm::clamp(glm::floor(encoded), glm::vec4(0), glm::vec4(F32(count - 1))));
                    glm::mat4 matrix(0);
                    for (S32 k = 0; k < 4; ++k)
                        matrix += glm::make_mat4(palette[joints[k]].mMatrix[0].getF32ptr()) * weights[k];
                    p = glm::vec3(matrix * bind * glm::vec4(p, 1));
                }
                else p = unrigged * (p * glm::make_vec3(object->getScale().mV));
                p = object_inverse * (p + glm::make_vec3(origin.mV));
                if (!glm::any(glm::isnan(p)) && !glm::any(glm::isinf(p)) && glm::length(p) < 3.f)
                    points.push_back(p);
            }
        }
    }
    if (points.empty()) return false;
    F32 depth = 0.1f;
    for (const auto& p : points) depth = llmax(depth, -p.z);
    depth = llclamp(depth, 0.1f, 2.f);
    const F32 angularCutoff = cosf(llmin(F_PI_BY_TWO, acosf(.8f) * 16.f / F32(chainCount)));
    for (S32 chain = 0; chain < chainCount; ++chain)
    {
        const F32 angle = F_TWO_PI * chain / F32(chainCount);
        const glm::vec2 direction(cosf(angle), sinf(angle));
        for (S32 node = 0; node < 9; ++node)
        {
            const F32 z = -depth * node / 8.f;
            F32 sum = 0.f, weight = 0.f;
            for (const auto& p : points)
            {
                const F32 radius = glm::length(glm::vec2(p));
                if (radius < 0.01f) continue;
                const F32 angular = llmax(0.f, glm::dot(glm::vec2(p) / radius, direction) - angularCutoff) / (1.f - angularCutoff);
                const F32 vertical = llmax(0.f, 1.f - fabsf(p.z - z) / llmax(depth / 6.f, 0.06f));
                const F32 w = angular * angular * vertical;
                sum += radius * w; weight += w;
            }
            // shortcut: polar guides approximate loose hair; braids/updos need authored guide topology.
            const F32 radius = weight > 1.e-5f ? sum / weight :
                (node ? glm::length(glm::vec2(data[chain * 27 + node - 1])) : 0.1f);
            const glm::vec4 rest(direction * radius, z, 1.f);
            data[chain * 27 + node] = rest;
            data[chain * 27 + 9 + node] = rest;
        }
    }
    const glm::mat4 to_head = glm::mat4(inverse) * glm::translate(glm::mat4(1), -glm::make_vec3(neutral_pivot.mV));
    sGuideHeadLimited = !fitHeadClearance(bodies, skeleton, to_head, data, chainCount);
    for (auto& binding : bindings)
    {
        sGuideBindings[binding.id] = S32(data.size());
        data.insert(data.end(), binding.palette.begin(), binding.palette.end());
    }
    // Rest root W carries topology with each buffer, including the previous frame used by TAA.
    data[0].w = F32(chainCount);
    for (S32 slot = 0; slot < 2; ++slot)
    {
        upload(sGuides[slot], data.size() * sizeof(glm::vec4), data.data(), GL_DYNAMIC_DRAW);
        if (!sGuideTextures[slot]) glGenTextures(1, &sGuideTextures[slot]);
        gGL.getTexUnit(0)->bindManual(LLTexUnit::TT_BUFFER, sGuideTextures[slot]);
        glTexBuffer(GL_TEXTURE_BUFFER, GL_RGBA32F, sGuides[slot]);
    }
    gGL.getTexUnit(0)->unbind(LLTexUnit::TT_BUFFER);
    sGuideFrames[0] = sGuideFrames[1] = 0;
    sGuideSkeleton = gAgentAvatarp->mLastSkeletonSerialNum;
    sGuideCount = chainCount;
    return true;
}

bool bake(const std::vector<LLVOVolume*>& bodies)
{
    LL_AUTOMATION_CPU_SCOPE("Hair.mesh_bake");
    std::vector<Vertex> vertices;
    std::vector<U32> sources;
    std::vector<std::array<float, 3>> centres;
    sMeshes.clear();
    sTriangleSources.clear();
    sPaletteOffsets.clear();
    U32 jointCount = 0;
    for (auto* body : bodies)
    {
        const auto* skin = body->getSkinInfo();
        auto* volume = body->getVolume();
        sMeshes.push_back({body->getID(), volume, skin->mHash, visibleFaces(*body)});
        const U32 count = LLSkinningUtil::getMeshJointCount(skin);
        if (!count) continue;
        auto entry = sPaletteOffsets.emplace(skin->mHash, jointCount);
        if (entry.second) jointCount += count;
        const U32 base = entry.first->second;
        const auto& palette = gAgentAvatarp->updateSkinInfoMatrixPalette(skin);
        if (palette.mMatrixPalette.size() < count) return false;
        const glm::mat4 bind = glm::make_mat4(skin->mBindShapeMatrix.mMatrix[0].getF32ptr());
        if (fabsf(glm::determinant(bind)) < 1.e-12f) continue;
        const glm::mat3 normal = glm::transpose(glm::inverse(glm::mat3(bind)));
        for (S32 face = 0; face < volume->getNumVolumeFaces(); ++face)
        {
            if (!sMeshes.back().faces[face]) continue;
            const auto& source = volume->getVolumeFace(face);
            if (!source.mWeights || !source.mPositions || !source.mNormals) continue;
            for (S32 i = 0; i + 2 < source.mNumIndices; i += 3)
            {
                Vertex triangle[3];
                glm::vec3 centre(0);
                bool valid = true;
                for (S32 j = 0; j < 3; ++j)
                {
                    const U32 index = source.mIndices[i + j];
                    if (index >= U32(source.mNumVertices)) { valid = false; break; }
                    auto& v = triangle[j];
                    v.position = bind * glm::vec4(glm::make_vec3(source.mPositions[index].getF32ptr()), 1);
                    v.normal = glm::vec4(normal * glm::make_vec3(source.mNormals[index].getF32ptr()), 0);
                    const glm::vec4 weights = glm::make_vec4(source.mWeights[index].getF32ptr());
                    if (glm::any(glm::isnan(weights)) || glm::any(glm::isinf(weights))) { valid = false; break; }
                    v.weights = glm::fract(weights);
                    const F32 total = glm::dot(v.weights, glm::vec4(1));
                    if (total < 1.e-8f) { valid = false; break; }
                    v.weights /= total;
                    const glm::uvec4 joints(glm::clamp(glm::floor(weights), glm::vec4(0), glm::vec4(F32(count - 1))));
                    v.joints = joints + base;
                    for (int k = 0; k < 4; ++k)
                    {
                        const auto& name = skin->mJointNames[joints[k]];
                        if (name.find("mHand") == 0 || name.find("mWrist") == 0 || name.find("mElbow") == 0)
                            v.normal.w += v.weights[k];
                    }
                    glm::mat4 matrix(0);
                    for (int k = 0; k < 4; ++k)
                        matrix += glm::make_mat4(palette.mMatrixPalette[joints[k]].mMatrix[0].getF32ptr()) * v.weights[k];
                    centre += glm::vec3(matrix * v.position) / 3.f;
                    if (glm::any(glm::isnan(v.position)) || glm::any(glm::isinf(v.position)) ||
                        glm::any(glm::isnan(centre)) || glm::any(glm::isinf(centre))) valid = false;
                }
                if (!valid) continue;
                // Bound memory and exact integer packing; oversized shells disable collision.
                if (centres.size() >= 1000000) return false;
                centres.push_back({centre.x, centre.y, centre.z});
                sources.push_back((U32(sMeshes.size() - 1) << 8) | U32(face));
                vertices.insert(vertices.end(), std::begin(triangle), std::end(triangle));
            }
        }
    }
    LLHairMesh::Tree tree(centres);
    sTriangles = U32(centres.size());
    sNodes = U32(tree.nodes.size());
    sFrames[0] = sFrames[1] = 0;
    if (!sTriangles) { sDirty = false; return true; }
    GLint bufferLimit = 0, textureLimit = 0;
    glGetIntegerv(GL_MAX_SHADER_STORAGE_BLOCK_SIZE, &bufferLimit);
    glGetIntegerv(GL_MAX_TEXTURE_BUFFER_SIZE, &textureLimit);
    const U32 texels = sNodes * 2 + sTriangles * 6 + CONTACT_POINTS + 1;
    if (vertices.size() * sizeof(Vertex) > size_t(bufferLimit) || texels > U32(textureLimit) ||
        size_t(texels) * sizeof(glm::vec4) > size_t(bufferLimit)) return false;
    std::vector<Vertex> ordered;
    ordered.reserve(vertices.size());
    sTriangleSources.clear();
    sTriangleSources.reserve(tree.order.size());
    for (U32 index : tree.order)
    {
        ordered.insert(ordered.end(), vertices.begin() + index * 3, vertices.begin() + index * 3 + 3);
        sTriangleSources.push_back(sources[index]);
    }
    upload(sInputs[0], ordered.size() * sizeof(Vertex), ordered.data(), GL_STATIC_DRAW);
    upload(sInputs[1], tree.nodes.size() * sizeof(tree.nodes[0]), tree.nodes.data(), GL_STATIC_DRAW);
    std::vector<U32> levels;
    sLevelOffsets.clear();
    for (const auto& level : tree.levels)
    {
        sLevelOffsets.push_back(U32(levels.size()));
        levels.insert(levels.end(), level.begin(), level.end());
    }
    sLevelOffsets.push_back(U32(levels.size()));
    upload(sInputs[2], levels.size() * sizeof(U32), levels.data(), GL_STATIC_DRAW);
    for (S32 slot = 0; slot < 2; ++slot)
    {
        upload(sShells[slot], size_t(texels) * sizeof(glm::vec4), nullptr, GL_DYNAMIC_DRAW);
        if (!sTextures[slot]) glGenTextures(1, &sTextures[slot]);
        gGL.getTexUnit(0)->bindManual(LLTexUnit::TT_BUFFER, sTextures[slot]);
        glTexBuffer(GL_TEXTURE_BUFFER, GL_RGBA32F, sShells[slot]);
    }
    gGL.getTexUnit(0)->unbind(LLTexUnit::TT_BUFFER);
    sDirty = false;
    ++sBakes;
    return glGetError() == GL_NO_ERROR;
}
#endif
}

void LLHairMesh::invalidate(const LLUUID& object)
{
    for (auto& mesh : sMeshes) if (mesh.id == object) { sDirty = true; break; }
    for (const auto& mesh : sGuideMeshes) if (mesh.id == object) { sGuideMeshes.clear(); break; }
}

void LLHairMesh::release()
{
#if !LL_DARWIN
    if (sInputs[0]) glDeleteBuffers(4, sInputs);
    if (sShells[0]) glDeleteBuffers(2, sShells);
    LLImageGL::deleteTextures(2, sTextures);
#endif
    std::fill(std::begin(sInputs), std::end(sInputs), 0);
    sShells[0] = sShells[1] = sTextures[0] = sTextures[1] = sFrames[0] = sFrames[1] = 0;
    sTriangles = sNodes = 0;
    sContacts[0] = sContacts[1] = false;
    sContactTime = 0.0;
    sMeshes.clear();
    sTriangleSources.clear();
    sPaletteOffsets.clear();
    sLevelOffsets.clear();
    sDirty = true;
}

void LLHairMesh::unloadShaders()
{
    release();
    sGuideShader.unload();
#if !LL_DARWIN
    releaseGuideReadbacks();
    if (sGuides[0]) glDeleteBuffers(2, sGuides);
    LLImageGL::deleteTextures(2, sGuideTextures);
#endif
    sGuides[0] = sGuides[1] = sGuideTextures[0] = sGuideTextures[1] = sGuideFrames[0] = sGuideFrames[1] = 0;
    sGuideMeshes.clear();
    sGuideBindings.clear();
    sGuideTime = 0.0;
    sGuideCount = 0;
    sSkinShader.unload(); sRefitShader.unload(); sCacheShader.unload(); sDebugShader.unload();
    sReady = false;
}

void LLHairMesh::loadShaders()
{
    unloadShaders();
#if !LL_DARWIN
    if (gGLManager.mGLVersion < 4.3f || !glDispatchCompute) return;
    auto* shader_mgr = LLShaderMgr::instance();
    shader_mgr->beginShaderBatch();
    bool success = true;
    for (auto* shader : {&sSkinShader, &sRefitShader})
    {
        shader->mName = shader == &sSkinShader ? "Hair mesh skin" : "Hair mesh refit";
        shader->mFeatures.attachNothing = true;
        shader->mShaderFiles = {{"deferred/hairMeshC.glsl", GL_COMPUTE_SHADER}};
        shader->mShaderLevel = 1;
        shader->clearPermutations();
        shader->addPermutation(shader == &sSkinShader ? "MESH_SKIN" : "MESH_REFIT", "1");
        success = shader->createShader() && success;
    }
    sCacheShader.mName = "Hair contact cache";
    sCacheShader.mFeatures.attachNothing = true;
    sCacheShader.mShaderLevel = 1;
    sCacheShader.mShaderFiles = {{"deferred/hairContactC.glsl", GL_COMPUTE_SHADER},
                               {"deferred/hairCollision.glsl", GL_COMPUTE_SHADER}};
    success = sCacheShader.createShader() && success;
    sGuideShader.mName = "Hair guide chains";
    sGuideShader.mFeatures.attachNothing = true;
    sGuideShader.mShaderLevel = 1;
    sGuideShader.mShaderFiles = {{"deferred/hairGuideC.glsl", GL_COMPUTE_SHADER},
                                {"deferred/hairCollision.glsl", GL_COMPUTE_SHADER}};
    success = sGuideShader.createShader() && success;
    // Finish all submitted jobs before unloading a failed optional hair family.
    if (!shader_mgr->finishShaderBatch() || !success) { unloadShaders(); return; }
    sReady = true;
    sDebugShader.mName = "Hair mesh shell";
    sDebugShader.mFeatures.attachNothing = true;
    sDebugShader.mShaderLevel = 1;
    sDebugShader.mShaderFiles = {{"deferred/hairMeshDebugV.glsl", GL_VERTEX_SHADER},
                                {"deferred/hairMeshDebugF.glsl", GL_FRAGMENT_SHADER}};
    if (!sDebugShader.createShader()) LL_WARNS("HairMesh") << "Collision shell preview unavailable." << LL_ENDL;
#endif
}

void LLHairMesh::update()
{
#if !LL_DARWIN
    if (sLastUpdate == gFrameCount) return;
    sLastUpdate = gFrameCount;
    static LLCachedControl<bool> physics(gSavedSettings, "BoxxyHairPhysicsEnabled", false);
    if (!physics || !sReady || !isAgentAvatarValid() || !gAgentAvatarp->mHeadp)
    {
        if (!sMeshes.empty() || sInputs[0]) release();
        return;
    }
    LL_AUTOMATION_CPU_SCOPE("Hair.mesh_update");
    std::vector<LLVOVolume*> bodies;
    LLVOVolume* hair = nullptr;
    for (const auto& attachment : gAgentAvatarp->mAttachmentPoints)
        for (const auto& object : attachment.second->mAttachedObjects) collect(object, bodies, hair);
    if (!hair || bodies.empty()) { if (!sMeshes.empty()) release(); return; }
    std::sort(bodies.begin(), bodies.end(), [](auto* a, auto* b) { return a->getID() < b->getID(); });
    if (bodies.size() != sMeshes.size()) sDirty = true;
    for (size_t i = 0; !sDirty && i < bodies.size(); ++i)
        if (sMeshes[i].id != bodies[i]->getID() || sMeshes[i].volume != bodies[i]->getVolume() ||
            sMeshes[i].skinHash != bodies[i]->getSkinInfo()->mHash || sMeshes[i].faces != visibleFaces(*bodies[i])) sDirty = true;
    gGL.flush();
    auto* previousShader = LLGLSLShader::sCurBoundShaderPtr;
    if (sDirty && !bake(bodies))
    {
        LL_WARNS("HairMesh") << "Collision shell allocation/geometry limit failed; collision unavailable until shader reload." << LL_ENDL;
        release(); sReady = false;
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0);
        return;
    }
    if (!sTriangles) return;
    LL_AUTOMATION_GPU_SCOPE("Hair.mesh_update");
    sCurrent = 1 - sCurrent;
    sFrames[sCurrent] = 0;
    sContacts[sCurrent] = false;
    sCentres[sCurrent] = gAgentAvatarp->getRootJoint()->getWorldPosition();
    // Fitted shape, body physics and Bento fingers already live in the final render palette.
    std::vector<F32> matrices;
    for (auto* body : bodies)
    {
        const auto* skin = body->getSkinInfo();
        auto found = sPaletteOffsets.find(skin->mHash);
        if (found == sPaletteOffsets.end()) continue;
        const auto& palette = gAgentAvatarp->updateSkinInfoMatrixPalette(skin);
        const size_t offset = size_t(found->second) * 12;
        if (matrices.size() < offset + palette.mGLMp.size()) matrices.resize(offset + palette.mGLMp.size());
        std::copy(palette.mGLMp.begin(), palette.mGLMp.end(), matrices.begin() + offset);
        const LLVector3 delta = palette.mRenderOrigin - sCentres[sCurrent];
        for (size_t i = offset; i < offset + palette.mGLMp.size(); i += 12)
            for (int axis = 0; axis < 3; ++axis) matrices[i + axis * 4 + 3] += delta.mV[axis];
    }
    upload(sInputs[3], matrices.size() * sizeof(F32), matrices.data(), GL_STREAM_DRAW);
    sTracePaletteDelta = 0.f;
    if (LLViewerAutomation::captureStarted())
    {
        if (sTracePalette.size() == matrices.size())
            for (size_t i = 0; i < matrices.size(); ++i)
                sTracePaletteDelta = llmax(sTracePaletteDelta, fabsf(matrices[i] - sTracePalette[i]));
        sTracePalette = matrices;
    }
    else sTracePalette.clear();
    for (U32 i = 0; i < 4; ++i) glBindBufferBase(GL_SHADER_STORAGE_BUFFER, i, sInputs[i]);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 4, sShells[sCurrent]);
    static LLCachedControl<F32> padding(gSavedSettings, "BoxxyHairPhysicsMeshPadding", 0.f);
    static F32 previousPadding = 0.f;
    const F32 shellPadding = llclamp(F32(padding), 0.f, .1f);
    // Resizing the shell is not hand motion: discard its contact drag history.
    if (shellPadding != previousPadding) sContacts[0] = sContacts[1] = false;
    previousPadding = shellPadding;
    sSkinShader.bind();
    sSkinShader.uniform1f(LLStaticHashedString("mesh_padding"), shellPadding);
    sSkinShader.uniform1i(LLStaticHashedString("mesh_vertex_count"), sTriangles * 3);
    sSkinShader.uniform1i(LLStaticHashedString("mesh_node_count"), sNodes);
    glDispatchCompute((sTriangles * 3 + 127) / 128, 1, 1);
    glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT);
    sRefitShader.bind();
    sRefitShader.uniform1i(LLStaticHashedString("mesh_node_count"), sNodes);
    for (S32 level = S32(sLevelOffsets.size()) - 2; level >= 0; --level)
    {
        const U32 count = sLevelOffsets[level + 1] - sLevelOffsets[level];
        sRefitShader.uniform1i(LLStaticHashedString("mesh_level_first"), sLevelOffsets[level]);
        sRefitShader.uniform1i(LLStaticHashedString("mesh_level_count"), count);
        glDispatchCompute((count + 127) / 128, 1, 1);
        glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT);
    }
    glMemoryBarrier(GL_TEXTURE_FETCH_BARRIER_BIT);
    {
        LLVector3 pivot;
        LLQuaternion rotation;
        const F64 now = LLFrameTimer::getTotalSeconds();
        const F32 dt = F32(now - sContactTime);
        if (hair->getHairPhysicsFrame(pivot, rotation))
        {
            LL_AUTOMATION_GPU_SCOPE("Hair.contacts");
            const S32 old = 1 - sCurrent;
            const LLMatrix4 head(rotation);
            const LLVector3 offset = pivot - sCentres[sCurrent];
            const glm::mat4 to_mesh = glm::translate(glm::mat4(1.f), glm::vec3(offset.mV[0], offset.mV[1], offset.mV[2])) *
                glm::make_mat4(&head.mMatrix[0][0]);
            sContactPivots[sCurrent] = pivot;
            sContactRotations[sCurrent] = rotation;
            F32 turn;
            LLVector3 axis;
            (~sContactRotations[old] * rotation).getAngleAxis(&turn, axis);
            const bool history = sContacts[old] && sFrames[old] + 1 == gFrameCount && dt > 0.f && dt < 0.5f &&
                (pivot - sContactPivots[old]).lengthSquared() < 1.f && turn < F_PI_BY_TWO;
            {
                LL_AUTOMATION_GPU_SCOPE("Hair.contact_cache");
                sCacheShader.bind();
                sCacheShader.uniform1i(LLStaticHashedString("contact_history"), history);
                const S32 previous_cache_channel = sCacheShader.enableTexture(LLShaderMgr::HAIR_PREVIOUS_MESH, LLTexUnit::TT_BUFFER);
                if (previous_cache_channel >= 0) gGL.getTexUnit(previous_cache_channel)->bindManual(LLTexUnit::TT_BUFFER, sTextures[old]);
                const S32 cache_channel = sCacheShader.enableTexture(LLShaderMgr::HAIR_MESH, LLTexUnit::TT_BUFFER);
                if (cache_channel >= 0) gGL.getTexUnit(cache_channel)->bindManual(LLTexUnit::TT_BUFFER, sTextures[sCurrent]);
                sCacheShader.uniform1i(LLStaticHashedString("mesh_node_count"), sNodes);
                sCacheShader.uniform1i(LLStaticHashedString("contact_offset"), sNodes * 2 + sTriangles * 6);
                sCacheShader.uniformMatrix4fv(LLStaticHashedString("contact_to_mesh"), 1, false, glm::value_ptr(to_mesh));
                dispatchContacts(sCacheShader);
                glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT | GL_TEXTURE_FETCH_BARRIER_BIT);
                sCacheShader.disableTexture(LLShaderMgr::HAIR_MESH, LLTexUnit::TT_BUFFER);
                sCacheShader.disableTexture(LLShaderMgr::HAIR_PREVIOUS_MESH, LLTexUnit::TT_BUFFER);
            }
            sContacts[sCurrent] = true;
        }
        sContactTime = now;
    }
    for (U32 i = 0; i < 5; ++i) glBindBufferBase(GL_SHADER_STORAGE_BUFFER, i, 0);
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0);
    LLGLSLShader::unbind();
    if (previousShader) previousShader->bind();
    sFrames[sCurrent] = gFrameCount;
#endif
}

void LLHairMesh::updateGuides()
{
#if !LL_DARWIN
    static LLCachedControl<bool> physics(gSavedSettings, "BoxxyHairPhysicsEnabled", false);
    if (!physics || !sReady || !isAgentAvatarValid() || !gAgentAvatarp->mHeadp)
    {
        sGuideFrames[0] = sGuideFrames[1] = 0;
        sGuideTime = 0.0;
        return;
    }
    if (sGuideFrames[sGuideCurrent] == gFrameCount) return;
    LL_AUTOMATION_CPU_SCOPE("Hair.guides_update");
    std::vector<LLVOVolume*> hair;
    std::vector<LLVOVolume*> bodies;
    LLVOVolume* firstHair = nullptr;
    for (const auto& attachment : gAgentAvatarp->mAttachmentPoints)
        for (const auto& object : attachment.second->mAttachedObjects)
        {
            collectGuideHair(object, hair);
            collect(object, bodies, firstHair);
        }
    if (hair.empty()) { sGuideTime = 0.0; return; }
    std::sort(hair.begin(), hair.end(), [](auto* a, auto* b) { return a->getID() < b->getID(); });
    std::sort(bodies.begin(), bodies.end(), [](auto* a, auto* b) { return a->getID() < b->getID(); });
    LLVector3 pivot;
    LLQuaternion rotation;
    if (!hair.front()->getHairPhysicsFrame(pivot, rotation)) return;
    static LLCachedControl<S32> density(gSavedSettings, "BoxxyHairPhysicsRopeDensity", 16);
    const S32 chainCount = llclamp(S32(density), 4, 64);
    bool fit = chainCount != sGuideCount || hair.size() != sGuideMeshes.size() || bodies.size() != sGuideBodies.size() ||
        sGuideSkeleton != gAgentAvatarp->mLastSkeletonSerialNum;
    for (size_t i = 0; !fit && i < hair.size(); ++i)
        fit = hair[i]->getID() != sGuideMeshes[i].id || hair[i]->getVolume() != sGuideMeshes[i].volume ||
            (hair[i]->getSkinInfo() ? hair[i]->getSkinInfo()->mHash : 0) != sGuideMeshes[i].skinHash ||
            visibleFaces(*hair[i]) != sGuideMeshes[i].faces;
    for (size_t i = 0; !fit && i < bodies.size(); ++i)
        fit = bodies[i]->getID() != sGuideBodies[i].id || bodies[i]->getVolume() != sGuideBodies[i].volume ||
            bodies[i]->getSkinInfo()->mHash != sGuideBodies[i].skinHash || visibleFaces(*bodies[i]) != sGuideBodies[i].faces;
    gGL.flush();
    auto* previousShader = LLGLSLShader::sCurBoundShaderPtr;
    if (fit && !fitGuides(hair, bodies, pivot, rotation, chainCount))
    {
        sGuideFrames[0] = sGuideFrames[1] = 0;
        sGuideMeshes.clear();
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0);
        return;
    }
    const F64 now = LLFrameTimer::getTotalSeconds();
    const F32 dt = F32(now - sGuideTime);
    F32 turn; LLVector3 axis;
    (~sGuideRotation * rotation).getAngleAxis(&turn, axis);
    const bool history = !fit && sGuideFrames[sGuideCurrent] + 1 == gFrameCount && sGuideTime > 0.0 &&
        dt > 0.f && dt <= 0.25f && (pivot - sGuidePivot).lengthSquared() < 1.f && turn < F_PI_BY_TWO;
    if (fit) ++sGuideFits;
    if (!history) ++sGuideResets;
    const S32 old = sGuideCurrent;
    sGuideCurrent = 1 - old;
    const LLMatrix4 head(rotation), inverse_head(~rotation), previous_head(sGuideRotation);
    const glm::mat4 inverse = glm::make_mat4(&inverse_head.mMatrix[0][0]);
    const LLVector3 delta = sGuidePivot - pivot;
    const glm::mat4 from_previous = inverse * glm::translate(glm::mat4(1), glm::make_vec3(delta.mV)) *
        glm::make_mat4(&previous_head.mMatrix[0][0]);
    sGuideShader.bind();
    const S32 channel = sGuideShader.enableTexture(LLShaderMgr::HAIR_PREVIOUS_GUIDES, LLTexUnit::TT_BUFFER);
    if (channel >= 0) gGL.getTexUnit(channel)->bindManual(LLTexUnit::TT_BUFFER, sGuideTextures[old]);
    sGuideShader.uniform1i(LLStaticHashedString("guide_history"), history);
    const bool diagnostics = LLViewerAutomation::captureStarted() != 0.0;
    sGuideShader.uniform1i(LLStaticHashedString("guide_diagnostics"), diagnostics);
    if (diagnostics)
    {
        if (!sGuideProbe)
        {
            glGenBuffers(1, &sGuideProbe);
            glBindBuffer(GL_SHADER_STORAGE_BUFFER, sGuideProbe);
            glBufferData(GL_SHADER_STORAGE_BUFFER, MAX_GUIDES * 9 * GUIDE_PROBE_PARTS * sizeof(glm::vec4), nullptr, GL_STREAM_READ);
        }
        glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 6, sGuideProbe);
    }
    sGuideShader.uniform1f(LLStaticHashedString("guide_dt"), history ? dt : 0.f);
    sGuideShader.uniformMatrix4fv(LLStaticHashedString("guide_from_previous"), 1, false, glm::value_ptr(from_previous));
    static LLCachedControl<F32> radius(gSavedSettings, "BoxxyHairPhysicsRootRadius", 0.15f);
    static LLCachedControl<F32> gradient(gSavedSettings, "BoxxyHairPhysicsRootGradient", 0.3f);
    static LLCachedControl<F32> stiffness(gSavedSettings, "BoxxyHairPhysicsStiffness", 6.f);
    static LLCachedControl<F32> retention(gSavedSettings, "BoxxyHairPhysicsShapeRetention", 1.f);
    static LLCachedControl<bool> gravity(gSavedSettings, "BoxxyHairPhysicsGravity", false);
    static LLCachedControl<F32> strength(gSavedSettings, "BoxxyHairPhysicsGravityStrength", 1.f);
    static LLCachedControl<F32> smoothing(gSavedSettings, "BoxxyHairPhysicsCollisionSmoothing", 0.02f);
    static LLCachedControl<F32> friction(gSavedSettings, "BoxxyHairPhysicsFriction", .35f);
    static LLCachedControl<F32> damping(gSavedSettings, "BoxxyHairPhysicsDamping", 7.f);
    static LLCachedControl<F32> bending(gSavedSettings, "BoxxyHairPhysicsBendResistance", 1.f);
    static LLCachedControl<F32> bendGradient(gSavedSettings, "BoxxyHairPhysicsBendGradient", 0.f);
    static LLCachedControl<F32> elasticity(gSavedSettings, "BoxxyHairPhysicsElasticity", .25f);
    static LLCachedControl<F32> travel(gSavedSettings, "BoxxyHairPhysicsTravelLimit", 0.f);
    sGuideShader.uniform1f(LLStaticHashedString("hair_root_radius"), llclamp(F32(radius), .03f, .35f));
    sGuideShader.uniform1f(LLStaticHashedString("hair_root_gradient"), llclamp(F32(gradient), .01f, 1.f));
    sGuideShader.uniform1f(LLStaticHashedString("guide_stiffness"), llclamp(F32(stiffness), 1.f, 12.f));
    sGuideShader.uniform1f(LLStaticHashedString("guide_retention"), llclamp(F32(retention), 0.f, 1.f));
    sGuideShader.uniform1f(LLStaticHashedString("guide_friction"), llclamp(F32(friction), 0.f, 2.f));
    sGuideShader.uniform1f(LLStaticHashedString("guide_damping"), llclamp(F32(damping), 0.f, 30.f));
    sGuideShader.uniform1f(LLStaticHashedString("guide_bend"), llclamp(F32(bending), 0.f, 4.f));
    sGuideShader.uniform1f(LLStaticHashedString("guide_bend_gradient"), llclamp(F32(bendGradient), 0.f, 2.f));
    sGuideShader.uniform1f(LLStaticHashedString("guide_elasticity"), llclamp(F32(elasticity), 0.f, 1.f));
    sGuideShader.uniform1f(LLStaticHashedString("guide_travel"), llclamp(F32(travel), 0.f, 20.f));
    const glm::vec3 fall = glm::mat3(inverse) * glm::vec3(0, 0, gravity ? -9.81f * llclamp(F32(strength), 0.f, 3.f) : 0.f);
    sGuideShader.uniform3fv(LLStaticHashedString("guide_gravity"), 1, glm::value_ptr(fall));
    sGuideShader.uniform1f(LLStaticHashedString("hair_collision_smoothing"), llclamp(F32(smoothing), 0.f, .02f));
    LLVector3 centre;
    const U32 frame = currentFrame(centre);
    bind(sGuideShader, frame, false);
    bind(sGuideShader, history && frame ? frame - 1 : 0, true);
    const bool meshHistory = history && frame && sFrames[1 - sCurrent] + 1 == frame &&
        sContacts[sCurrent] && sContacts[1 - sCurrent];
    sGuideShader.uniform1i(LLStaticHashedString("guide_mesh_history"), meshHistory);
    const LLVector3 previousOffset = meshHistory ? sCentres[1 - sCurrent] - centre : LLVector3::zero;
    sGuideShader.uniform3fv(LLStaticHashedString("guide_previous_mesh_offset"), 1, previousOffset.mV);
    if (frame)
    {
        const LLVector3 offset = pivot - centre;
        const glm::mat4 to_mesh = glm::translate(glm::mat4(1), glm::make_vec3(offset.mV)) * glm::make_mat4(&head.mMatrix[0][0]);
        sGuideShader.uniformMatrix4fv(LLStaticHashedString("hair_mesh_from_local"), 1, false, glm::value_ptr(to_mesh));
    }
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 5, sGuides[sGuideCurrent]);
    {
        LL_AUTOMATION_GPU_SCOPE("Hair.guides_update");
        for (S32 first = 0; first < sGuideCount; first += 32)
        {
            sGuideShader.uniform1i(LLStaticHashedString("guide_first"), first);
            glDispatchCompute(llmin(2, (sGuideCount - first + 15) / 16), 1, 1);
        }
        glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT | GL_TEXTURE_FETCH_BARRIER_BIT);
    }
    captureGuides(dt, history, fit, meshHistory, from_previous);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 6, 0);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 5, 0);
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0);
    sGuideShader.disableTexture(LLShaderMgr::HAIR_MESH, LLTexUnit::TT_BUFFER);
    sGuideShader.disableTexture(LLShaderMgr::HAIR_PREVIOUS_MESH, LLTexUnit::TT_BUFFER);
    sGuideShader.disableTexture(LLShaderMgr::HAIR_PREVIOUS_GUIDES, LLTexUnit::TT_BUFFER);
    sGuideShader.unbind();
    if (previousShader) previousShader->bind();
    sGuideFrames[sGuideCurrent] = gFrameCount;
    sGuideTime = now; sGuidePivot = pivot; sGuideRotation = rotation;
#endif
}

U32 LLHairMesh::guideFrame()
{
    return sGuideFrames[sGuideCurrent] == gFrameCount ? gFrameCount : 0;
}

S32 LLHairMesh::guideBinding(const LLUUID& object)
{
    const auto found = sGuideBindings.find(object);
    return guideFrame() && found != sGuideBindings.end() ? found->second : 0;
}

void LLHairMesh::bindGuides(LLGLSLShader& shader, U32 frame, bool previous)
{
    const S32 slot = frame && frame == sGuideFrames[sGuideCurrent] ? sGuideCurrent :
        (frame && frame == sGuideFrames[1 - sGuideCurrent] ? 1 - sGuideCurrent : -1);
    const S32 channel = shader.enableTexture(previous ? LLShaderMgr::HAIR_PREVIOUS_GUIDES : LLShaderMgr::HAIR_GUIDES, LLTexUnit::TT_BUFFER);
    if (channel >= 0 && slot >= 0) gGL.getTexUnit(channel)->bindManual(LLTexUnit::TT_BUFFER, sGuideTextures[slot]);
    shader.uniform1i(LLStaticHashedString(previous ? "hair_previous_guide_active" : "hair_guide_active"), channel >= 0 && slot >= 0);
}

void LLHairMesh::renderDebug()
{
    static LLCachedControl<bool> show(gSavedSettings, "BoxxyHairPhysicsShowMesh", false);
    static LLCachedControl<bool> guides(gSavedSettings, "BoxxyHairPhysicsShowGuides", false);
    LLVector3 centre;
    const U32 frame = currentFrame(centre);
    const bool shell = show && frame;
    const bool ropes = guides && guideFrame();
    if ((!shell && !ropes) || !sDebugShader.isComplete()) return;
    LL_AUTOMATION_GPU_SCOPE("Hair.mesh_surface");
    gGL.flush();
    auto* previousShader = LLGLSLShader::sCurBoundShaderPtr;
    LLGLDepthTest depth(GL_FALSE, GL_FALSE);
    LLGLEnable blend(GL_BLEND);
    LLGLEnable cull(GL_CULL_FACE);
    gGL.blendFunc(LLRender::BF_SOURCE_ALPHA, LLRender::BF_ONE_MINUS_SOURCE_ALPHA, LLRender::BF_ZERO, LLRender::BF_ONE);
    sDebugShader.bind();
    gGL.pushMatrix();
    LLVertexBuffer::unbind();
    if (shell)
    {
        bind(sDebugShader, frame, false);
        sDebugShader.uniform1i(LLStaticHashedString("guide_debug"), 0);
        const glm::mat4 view(glm::translate(glm::dmat4(glm::make_mat4(gGLModelView)), glm::dvec3(centre.mV[0], centre.mV[1], centre.mV[2])));
        gGL.loadMatrix(glm::value_ptr(view));
        gGL.syncMatrices();
        glDrawArrays(GL_TRIANGLES, 0, sTriangles * 3);
    }
    if (ropes)
    {
        bindGuides(sDebugShader, guideFrame(), false);
        const LLMatrix4 head(sGuideRotation);
        const glm::mat4 view = glm::mat4(glm::translate(glm::dmat4(glm::make_mat4(gGLModelView)),
            glm::dvec3(sGuidePivot.mV[0], sGuidePivot.mV[1], sGuidePivot.mV[2]))) * glm::make_mat4(&head.mMatrix[0][0]);
        gGL.loadMatrix(glm::value_ptr(view));
        gGL.syncMatrices();
        sDebugShader.uniform1f(LLStaticHashedString("hair_root_radius"), llclamp(gSavedSettings.getF32("BoxxyHairPhysicsRootRadius"), .03f, .35f));
        sDebugShader.uniform1i(LLStaticHashedString("guide_debug"), 1);
        glDrawArrays(GL_LINES, 0, sGuideCount * 8 * 2);
        sDebugShader.uniform1i(LLStaticHashedString("guide_debug"), 2);
        glDrawArrays(GL_LINES, 0, sGuideCount * 8 * 2);
        sDebugShader.uniform1i(LLStaticHashedString("guide_debug"), 3);
        LLGLEnable point_size(GL_PROGRAM_POINT_SIZE);
        glDrawArrays(GL_POINTS, 0, sGuideCount * 9);
        sDebugShader.disableTexture(LLShaderMgr::HAIR_GUIDES, LLTexUnit::TT_BUFFER);
    }
    gGL.popMatrix();
    sDebugShader.disableTexture(LLShaderMgr::HAIR_MESH, LLTexUnit::TT_BUFFER);
    sDebugShader.unbind();
    gGL.setSceneBlendType(LLRender::BT_ALPHA);
    if (previousShader) previousShader->bind();
}

U32 LLHairMesh::currentFrame(LLVector3& centre)
{
    centre = sCentres[sCurrent];
    return sFrames[sCurrent] == gFrameCount ? sFrames[sCurrent] : 0;
}

void LLHairMesh::bind(LLGLSLShader& shader, U32 frame, bool previous)
{
    const S32 slot = frame && frame == sFrames[sCurrent] ? sCurrent :
        (frame && frame == sFrames[1 - sCurrent] ? 1 - sCurrent : -1);
    const S32 channel = shader.enableTexture(previous ? LLShaderMgr::HAIR_PREVIOUS_MESH : LLShaderMgr::HAIR_MESH, LLTexUnit::TT_BUFFER);
    if (channel >= 0 && slot >= 0) gGL.getTexUnit(channel)->bindManual(LLTexUnit::TT_BUFFER, sTextures[slot]);
    if (!previous)
    {
        shader.uniform1i(LLStaticHashedString("hair_mesh_nodes"), channel >= 0 && slot >= 0 ? sNodes : 0);
        shader.uniform1i(LLStaticHashedString("hair_mesh_contact"),
            channel >= 0 && slot >= 0 && sContacts[slot] ? sNodes * 2 + sTriangles * 6 : 0);
    }
}

LLSD LLHairMesh::diagnostics()
{
    LLSD result;
    result["available"] = sReady;
    result["guide_chains"] = LLSD::Integer(guideFrame() ? sGuideCount : 0);
    result["guide_points"] = LLSD::Integer(guideFrame() ? sGuideCount * 9 : 0);
    result["active"] = sFrames[sCurrent] != 0 && sFrames[sCurrent] == gFrameCount;
    result["triangles"] = LLSD::Integer(sTriangles);
    result["nodes"] = LLSD::Integer(sNodes);
    result["bakes"] = LLSD::Integer(sBakes);
    result["meshes"] = LLSD::Integer(sMeshes.size());
    result["contact_points"] = LLSD::Integer(sContacts[sCurrent] && sFrames[sCurrent] == gFrameCount ? CONTACT_POINTS : 0);
    result["guide_fits"] = LLSD::Integer(sGuideFits);
    result["guide_resets"] = LLSD::Integer(sGuideResets);
    result["guide_trace_dropped"] = LLSD::Integer(sGuideTraceDropped);
    result["guide_trace"] = sGuideTrace;
    result["guide_snapshot"] = sGuideSnapshot;
    result["guide_fit_pose"] = "shaped_t_pose";
    result["guide_head_adjusted"] = LLSD::Integer(sGuideHeadAdjusted);
    result["guide_head_ray_tests"] = LLSD::Integer(sGuideHeadTests);
    result["guide_head_fit_limited"] = sGuideHeadLimited;
    LLSD sources = LLSD::emptyMap();
    for (const auto* samples : {&sGuideTrace, &sGuideSnapshot})
    for (auto it = samples->beginArray(); it != samples->endArray(); ++it)
    {
        const auto& row = *it;
        if (!row.has("source_object")) continue;
        const LLUUID id = row["source_object"].asUUID();
        const S32 face = row["source_face"].asInteger();
        const std::string key = id.asString() + ":" + std::to_string(face);
        if (sources.has(key)) continue;
        auto* object = gObjectList.findObject(id);
        if (!object || face < 0 || face >= object->getNumTEs()) continue;
        const auto* te = object->getTE(face);
        if (!te) continue;
        auto& info = sources[key];
        info["name"] = object->getCachedObjectName();
        info["attachment"] = object->getRootEdit()->getAttachmentItemName();
        info["texture"] = te->getID();
        info["invisible_texture"] = te->getID() == IMG_INVISIBLE;
        info["face_alpha"] = te->getColor().mV[3];
        const auto* material = te->getMaterialParams().get();
        info["alpha_mode"] = material ? material->getDiffuseAlphaMode() : -1;
        info["alpha_cutoff"] = material ? material->getAlphaMaskCutoff() : 0;
        if (auto* texture = object->getTEImage(U8(face)))
        {
            info["texture_components"] = texture->getComponents();
            info["texture_loaded"] = texture->hasGLTexture();
            S32 opaque = 0;
            for (S32 y = 0; y < 4; ++y)
            for (S32 x = 0; x < 4; ++x)
                opaque += texture->getMask(LLVector2((x + .5f) / 4.f, (y + .5f) / 4.f));
            // A coarse diagnostic sample, not a substitute for full visibility classification.
            info["opaque_mask_samples_of_16"] = opaque;
        }
    }
    result["source_surfaces"] = sources;
    return result;
}
