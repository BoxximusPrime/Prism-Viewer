"""Count membership comparisons in the original baseline addMotion method.

Synthetic overlapping poses establish algorithmic work, not w21 timings or
actual scene joint counts. No optimized implementation is tested here.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
STUBS = r'''
#include <algorithm>
#include <cassert>
#include <iostream>
#include <list>
#include <map>
#include <vector>
struct LLJoint { enum { USE_MOTION_PRIORITY = -1 }; };
struct LLJointState {
    LLJoint* joint;
    LLJoint* getJoint() { return joint; }
    int getPriority() { return LLJoint::USE_MOTION_PRIORITY; }
};
struct LLPose {
    std::vector<LLJointState*> states;
    size_t index;
    LLJointState* getFirstJointState() { index=0; return states.empty() ? nullptr : states[0]; }
    LLJointState* getNextJointState() { return ++index < states.size() ? states[index] : nullptr; }
};
struct LLMotion {
    enum { ADDITIVE_BLEND = 1 };
    LLPose pose;
    LLPose* getPose() { return &pose; }
    int getPriority() { return 3; }
    int getBlendType() { return 0; }
};
struct LLJointStateBlender { void addJointState(LLJointState*, int, bool) {} };
size_t comparisons = 0;
struct CountedPointer {
    LLJointStateBlender* value;
    CountedPointer(LLJointStateBlender* p): value(p) {}
    bool operator==(LLJointStateBlender* p) const { ++comparisons; return value == p; }
};
struct LLPoseBlender {
    std::map<LLJoint*,LLJointStateBlender*> mJointStateBlenderPool;
    std::list<CountedPointer> mActiveBlenders;
    bool addMotion(LLMotion*);
    ~LLPoseBlender() { for (auto& item : mJointStateBlenderPool) delete item.second; }
};
int run(int joints, int motions) {
    std::vector<LLJoint> skeleton(joints);
    std::vector<LLJointState> states(joints);
    LLMotion motion;
    for (int i=0; i<joints; ++i) {
        states[i].joint = &skeleton[i]; motion.pose.states.push_back(&states[i]);
    }
    LLPoseBlender blender;
    comparisons = 0;
    for (int i=0; i<motions; ++i) assert(blender.addMotion(&motion));
    assert(blender.mActiveBlenders.size() == size_t(joints));
    const size_t expected = size_t(joints)*(joints-1)/2 + size_t(motions-1)*joints*(joints+1)/2;
    assert(comparisons == expected);
    std::cout << joints << " joints x " << motions << " poses: " << joints*motions
              << " joint-state visits, " << comparisons << " membership comparisons\n";
    return 0;
}
'''
# Preserve the historical baseline after current production stops doing this search.
source = subprocess.check_output(["git", "show", "52d375475d080ec8dad2c67b783ef4103ad12f9e:indra/llcharacter/llpose.cpp"], cwd=ROOT, text=True)
start = source.index("bool LLPoseBlender::addMotion(")
end = source.index("//-----------------------------------------------------------------------------", start)
with tempfile.TemporaryDirectory(prefix="boxxy-pose-search-") as folder:
    cpp, exe = Path(folder) / "check.cpp", Path(folder) / "check.exe"
    cpp.write_text(STUBS + source[start:end] + "\nint main() { run(30, 6); run(120, 6); }\n")
    subprocess.run([shutil.which("g++"), "-std=c++17", "-O2", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
