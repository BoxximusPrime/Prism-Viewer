"""Compile and exercise the actual description-tag and projector refresh methods.
Run with Python and a C++17 compiler on PATH (or CXX).
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
VIEWER = ROOT / "indra/newview"


def function(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


def main():
    obj = (VIEWER / "llviewerobject.cpp").read_text(encoding="utf-8")
    vol = (VIEWER / "llvovolume.cpp").read_text(encoding="utf-8")
    setter = function(obj, "void LLViewerObject::setCachedObjectDescription(")
    refresh = function(vol, "bool LLVOVolume::projectorShadowsDisabled() const")
    harness = r'''
#include <algorithm>
#include <cassert>
#include <cctype>
#include <deque>
#include <string>
#include <unordered_set>
using F64 = double;
struct LLStringUtil {
    static void toLower(std::string& s) {
        std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return std::tolower(c); });
    }
};
struct LLFrameTimer {
    inline static double now = 1.0;
    static double getElapsedSeconds() { return now; }
};
bool gCubeSnapshot = false;
struct Request { int id, relevance; double not_before; int attempts; bool projector; };
std::deque<Request> sRenderPropertyRequests;
std::unordered_set<int> sRenderQueuedObjectIDs;
struct LLViewerObject {
    std::string mObjectDescription;
    bool mObjectDescriptionValid = false;
    bool mNoShadowDescriptionTag = false;
    int dirty = 0;
    void markDescriptionRenderStateChanged() { ++dirty; }
    void setCachedObjectDescription(const std::string&);
    bool hasNoShadowDescriptionTag() const { return mNoShadowDescriptionTag; }
};
struct LLVOVolume : LLViewerObject {
    int id;
    mutable double mNextProjectorDescriptionRequest = 0;
    explicit LLVOVolume(int value) : id(value) {}
    float priority = 1.f;
    float getSpotLightPriority() const { return priority; }
    int getID() const { return id; }
    bool projectorShadowsDisabled() const;
};
'''
    harness += setter + "\n" + refresh
    pipeline = (VIEWER / "pipeline.cpp").read_text(encoding="utf-8")
    setup = function(pipeline, "void LLPipeline::setupSpotLight(")
    index_code = setup[setup.index("    S32 s_idx = -1;"):setup.index("    shader.uniform1i(LLShaderMgr::PROJECTOR_SHADOW_INDEX")]
    selection = setup[setup.index("    // make sure we're not already targeting"):setup.index("    LLViewerTexture* img")]
    cleanup = function(pipeline, "        for (U32 i = 0; i < 2; ++i)\n        {\n            auto shadow_disabled")
    harness += r'''
using U32 = unsigned;
using S32 = int;
using F32 = float;
#define llassert assert
struct LLDrawable {
    LLVOVolume* volume;
    LLVOVolume* getVOVolume() { return volume; }
};
struct DrawablePtr {
    LLDrawable* p = nullptr;
    operator LLDrawable*() const { return p; }
    LLDrawable* operator->() const { return p; }
    bool notNull() const { return p != nullptr; }
    bool isNull() const { return p == nullptr; }
    DrawablePtr& operator=(LLDrawable* value) { p = value; return *this; }
};
DrawablePtr mShadowSpotLight[2], mTargetShadowSpotLight[2];
float mSpotLightFade[2] = {1, 1};
'''
    harness += "int shadowIndex(LLDrawable* drawablep) {\nbool no_shadow = drawablep->volume->projectorShadowsDisabled();\n" + index_code + "return s_idx;\n}\n"
    harness += "void nominate(LLDrawable* drawablep) {\nauto* volume = drawablep->volume;\nbool no_shadow = volume->projectorShadowsDisabled();\n" + selection + "}\n"
    harness += "void releaseTaggedSlots() {\n" + cleanup + "\n}\n"
    harness += r'''
int main() {
    LLVOVolume light(1);
    for (const auto& description : {"[no-shadow]", "Lamp [NO-SHADOW] warm", "[sss][No-Shadow]"}) {
        light.setCachedObjectDescription(description);
        assert(light.projectorShadowsDisabled());
        assert(light.mObjectDescription == description);
    }
    for (const auto& description : {"", "(no description)", "no-shadow", "[no-shadows]", "[no shadow]", "[sss]"}) {
        light.setCachedObjectDescription(description);
        assert(!light.projectorShadowsDisabled());
    }
    light.setCachedObjectDescription("[no-shadow]");
    int dirtied = light.dirty;
    light.setCachedObjectDescription("[no-shadow]");
    assert(light.dirty == dirtied);
    light.setCachedObjectDescription("ordinary lamp");
    assert(light.dirty == dirtied + 1 && !light.projectorShadowsDisabled());
    // Repeated renderer calls cannot flood the metadata queue.
    assert(sRenderPropertyRequests.size() == 1);
    assert(sRenderPropertyRequests.front().projector);
    sRenderPropertyRequests.clear(); sRenderQueuedObjectIDs.clear();
    LLFrameTimer::now = 60;
    light.projectorShadowsDisabled();
    assert(sRenderPropertyRequests.empty());
    LLFrameTimer::now = 61;
    light.projectorShadowsDisabled();
    assert(sRenderPropertyRequests.size() == 1);
    LLFrameTimer::now = 122;
    light.projectorShadowsDisabled();
    assert(sRenderPropertyRequests.size() == 1); // still queued: deduplicate
    // A child uses its own description; an unrelated tagged root cannot affect it.
    LLVOVolume root(2), child(3);
    root.setCachedObjectDescription("[no-shadow]");
    child.setCachedObjectDescription("child light");
    assert(root.projectorShadowsDisabled() && !child.projectorShadowsDisabled());
    // Cubemap rendering consumes cached flags without creating network work.
    auto size = sRenderPropertyRequests.size();
    gCubeSnapshot = true;
    LLVOVolume probe_view_light(4);
    probe_view_light.setCachedObjectDescription("[no-shadow]");
    assert(probe_view_light.projectorShadowsDisabled());
    assert(sRenderPropertyRequests.size() == size);
    // Run the actual opaque shadow binding, nomination, and slot-release code.
    gCubeSnapshot = false;
    LLDrawable first{&root}, second{&child};
    mShadowSpotLight[0] = &first;
    mTargetShadowSpotLight[0] = &first;
    assert(shadowIndex(&first) == -1);
    releaseTaggedSlots();
    assert(!mShadowSpotLight[0].notNull() && !mTargetShadowSpotLight[0].notNull());
    assert(mSpotLightFade[0] == 0.f);
    nominate(&first);
    assert(!mTargetShadowSpotLight[0].notNull());
    nominate(&second);
    assert(mTargetShadowSpotLight[0] == &second);
    mShadowSpotLight[0] = &second;
    assert(shadowIndex(&second) == 0);
    root.setCachedObjectDescription("ordinary lamp");
    root.priority = 2.f;
    nominate(&first);
    assert(mTargetShadowSpotLight[0] == &first);
    assert(mTargetShadowSpotLight[1] == &second);
}
'''
    compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        raise RuntimeError("A C++17 compiler is required")
    with tempfile.TemporaryDirectory(prefix="no-shadow-test-") as tmp:
        source = Path(tmp) / "test.cpp"
        binary = Path(tmp) / ("test.exe" if os.name == "nt" else "test")
        source.write_text(harness, encoding="utf-8")
        subprocess.run([compiler, "-std=c++17", str(source), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
    print("PASS: tag parsing/removal, description preservation, exact-prim scope, refresh throttling/deduplication, cubemap behavior, shadow binding/slot release and re-eligibility")


if __name__ == "__main__":
    main()
