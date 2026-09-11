"""Check production pose accumulation/order/lifecycle against the original list search.

Uses the real class declarations, pose iteration, joint-state insertion and pose
blender methods. Transform arithmetic is recorded, not simulated. Optional
--benchmark measures synthetic accumulation only; it is not an FPS estimate.
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
STUBS = r'''
#include <algorithm>
#include <cassert>
#include <chrono>
#include <climits>
#include <iostream>
#include <list>
#include <string>
#include <tuple>
#include <vector>
using F32 = float; using S32 = int;
constexpr S32 S32_MIN = INT_MIN;
#define LL_ALIGN_NEW
#define llassert assert
#define LL_PROFILE_ZONE_SCOPED_CATEGORY_AVATAR
template<class T> struct LLPointer {
    T* p = nullptr;
    LLPointer(T* value = nullptr): p(value) {}
    T* operator->() const { return p; }
    operator T*() const { return p; }
    bool isNull() const { return !p; }
    bool notNull() const { return p; }
};
struct LLJoint {
    enum { USE_MOTION_PRIORITY = -1 };
    int id = -1;
    std::string getName() const { return std::to_string(id); }
};
struct LLJointState {
    LLJoint* joint; int id, priority; float weight;
    LLJoint* getJoint() const { return joint; }
    int getPriority() const { return priority; }
    void setWeight(float value) { weight = value; }
};
struct DeletePairedPointer {
    template<class T> void operator()(T& item) const { delete item.second; }
};
using Event = std::tuple<int,int,int,bool,float>;
std::vector<Event> events;
bool recording = true;
'''
SUPPORT = r'''
struct LLMotion {
    enum LLMotionBlendType { NORMAL_BLEND, ADDITIVE_BLEND };
    LLPose pose;
    int priority = 0;
    LLMotionBlendType type = NORMAL_BLEND;
    LLPose* getPose() { return &pose; }
    int getPriority() { return priority; }
    LLMotionBlendType getBlendType() { return type; }
};
void LLJointStateBlender::blendJointStates(bool apply_now) {
    if (recording) {
        events.emplace_back(apply_now ? 1 : 2, -1, 0, false, 0);
        for (int i=0; i<JSB_NUM_JOINT_STATES && mJointStates[i]; ++i)
            events.emplace_back(0, mJointStates[i]->id, mPriorities[i], mAdditiveBlends[i], mJointStates[i]->weight);
    }
    if (apply_now) clear();
}
void LLJointStateBlender::resetCachedJoint() {
    if (recording) events.emplace_back(3, -1, 0, false, 0);
}
void LLJointStateBlender::interpolate(float u) {
    if (recording) events.emplace_back(4, mJointStates[0] ? mJointStates[0]->id : -1, 0, false, u);
}
// Original bookkeeping retained as an independent reference for list lifecycle.
struct ReferenceBlender : LLPoseBlender {
    bool addMotion(LLMotion* motion) {
        for (auto* state=motion->pose.getFirstJointState(); state; state=motion->pose.getNextJointState()) {
            auto* joint = state->getJoint();
            LLJointStateBlender* blender;
            if (mJointStateBlenderPool.find(joint) == mJointStateBlenderPool.end()) {
                blender = new LLJointStateBlender;
                mJointStateBlenderPool[joint] = blender;
            } else blender = mJointStateBlenderPool[joint];
            blender->addJointState(state,
                state->getPriority() == LLJoint::USE_MOTION_PRIORITY ? motion->getPriority() : state->getPriority(),
                motion->getBlendType() == LLMotion::ADDITIVE_BLEND);
            if (std::find(mActiveBlenders.begin(), mActiveBlenders.end(), blender) == mActiveBlenders.end())
                mActiveBlenders.push_front(blender);
        }
        return true;
    }
    void blendAndApply() {
        for (auto* blender : mActiveBlenders) blender->blendJointStates();
        mActiveBlenders.clear();
    }
    void clearBlenders() {
        for (auto* blender : mActiveBlenders) blender->clear();
        mActiveBlenders.clear();
    }
};
struct Fixture {
    std::vector<LLJoint> joints;
    std::vector<LLMotion> motions;
    std::vector<LLJointState> states;
    Fixture(int joint_count, int motion_count): joints(joint_count), motions(motion_count) {
        states.reserve(joint_count*motion_count);
        for (int j=0; j<joint_count; ++j) joints[j].id=j;
        for (int m=0; m<motion_count; ++m) {
            motions[m].priority=m%5;
            motions[m].type=m%3 ? LLMotion::NORMAL_BLEND : LLMotion::ADDITIVE_BLEND;
            for (int j=0; j<joint_count; ++j) {
                states.push_back({&joints[j], m*joint_count+j, j%4 ? -1 : (m+2)%7, float(m+1)/motion_count});
                motions[m].pose.addJointState(&states.back());
            }
        }
    }
};
template<class Blender> void scenario(Blender& blender, Fixture& fixture) {
    LLMotion empty;
    for (int frame=0; frame<30; ++frame) {
        blender.addMotion(&empty);
        for (size_t i=frame%3; i<fixture.motions.size(); ++i) blender.addMotion(&fixture.motions[i]);
        if (frame%2) {
            blender.blendAndCache(true);
            blender.interpolate(.25f);
            blender.blendAndCache(false);
            blender.interpolate(.75f);
            blender.addMotion(&fixture.motions[0]); // retained list must not duplicate joints
        }
        if (frame%3 == 0) {
            blender.clearBlenders();
            blender.addMotion(&fixture.motions[1]); // membership must reset on clear
        }
        blender.blendAndApply(); // and on apply
        blender.blendAndApply(); // empty list has no work
        blender.clearBlenders();
    }
}
template<class Blender> double benchmark(Fixture& fixture) {
    Blender blender;
    auto start=std::chrono::steady_clock::now();
    for (int frame=0; frame<2000; ++frame) {
        for (auto& motion : fixture.motions) blender.addMotion(&motion);
        blender.blendAndApply();
    }
    return std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count()/2000;
}
int main(int argc, char**) {
    Fixture fixture(12, 10); // More than six states exercises rejected/lower-priority entries.
    ReferenceBlender reference;
    LLPoseBlender actual;
    scenario(reference, fixture);
    const auto expected=events;
    events.clear(); scenario(actual, fixture);
    assert(events == expected);
    // A second owner has independent active membership even for the same joint pointers.
    LLPoseBlender second;
    events.clear(); scenario(second, fixture);
    assert(events == expected);
    std::cout << "Passed production pose accumulation: order/priorities/additive weights, clear/re-add, cache/interpolate/apply, independent owners\n";
    if (argc>1) {
        recording=false;
        Fixture crowd(120, 6);
        std::vector<double> old_times, new_times;
        for (int i=0; i<8; ++i) {
            if (i%2) { new_times.push_back(benchmark<LLPoseBlender>(crowd)); old_times.push_back(benchmark<ReferenceBlender>(crowd)); }
            else { old_times.push_back(benchmark<ReferenceBlender>(crowd)); new_times.push_back(benchmark<LLPoseBlender>(crowd)); }
        }
        std::sort(old_times.begin(),old_times.end()); std::sort(new_times.begin(),new_times.end());
        const double before=(old_times[3]+old_times[4])/2, after=(new_times[3]+new_times[4])/2;
        std::cout << "Synthetic 120-joint/6-pose accumulation, median ms/iteration: original=" << before
                  << " current=" << after << " ratio=" << before/after << "\n";
    }
}
'''


def method(source, signature):
    start = source.index(signature)
    end = source.index("\n}", start) + 2
    return source[start:end] + "\n"


def main():
    source = (ROOT / "indra/llcharacter/llpose.cpp").read_text()
    header = (ROOT / "indra/llcharacter/llpose.h").read_text()
    header = re.sub(r'^#include ".*"\n', '', header, flags=re.M)
    pose = source[source.index("LLPose::~LLPose()"):source.index("LLJointStateBlender::LLJointStateBlender()")]
    joint = source[source.index("LLJointStateBlender::LLJointStateBlender()"):source.index("void LLJointStateBlender::blendJointStates(")]
    joint += method(source, "void LLJointStateBlender::clear()")
    blender = source[source.index("LLPoseBlender::LLPoseBlender()"):]
    with tempfile.TemporaryDirectory(prefix="boxxy-pose-blender-") as folder:
        cpp, exe = Path(folder) / "check.cpp", Path(folder) / "check.exe"
        cpp.write_text(STUBS + header + SUPPORT + pose + joint + blender)
        subprocess.run([shutil.which("g++"), "-std=c++17", "-O2", str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)] + sys.argv[1:], check=True)


if __name__ == "__main__":
    main()
