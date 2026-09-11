Avatar animation performance investigation — w21
===============================================

Status: first optimization pass implemented and uncommitted; offline checks and Release build passed; in-world validation remains pending. Updated September 10, 2026.

The user reports a crowded area with 50–60 avatars and has authorized implementation after the research. Significant animation CPU work is expected. Preserve update rate, motion fidelity and visibility policy. No viewer launch or login has been performed; validation uses offline harnesses.

Baseline: workspace commit `52d375475d080ec8dad2c67b783ef4103ad12f9e`, inspected September 10, 2026. Capture: [w21_trace.tracy](E:/BoxxyViewer/w21_trace.tracy). Shared measurements: [frame analysis](E:/BoxxyViewer/output/w21-tracy-analysis/report.md) and [summary](E:/BoxxyViewer/output/w21-tracy-analysis/summary.json).

**Implementation pass**

`LLPoseBlender::addMotion` now performs one map lookup per joint state and uses a pool-owned blender membership flag instead of scanning the active list. List insertion and blend arithmetic order are preserved. `blendAndApply` and `clearBlenders` reset membership; cached blending and interpolation retain it. A new outer avatar-category Tracy zone measures accumulation separately in the next capture. No animation clocks, update periods, curve sampling, constraints, joint setters or attachment movement policies changed.

[test_pose_blender.py](E:/BoxxyViewer/scripts/tests/test_pose_blender.py) uses the real class declarations, pose iteration, joint-state insertion and pose-blender methods. It compares ordered calls/weights/priorities against the old list-search behavior across clear/re-add, rejected low-priority states, additive motions, cached interpolation, repeated apply and independent owners. Transform arithmetic is recorded, not reimplemented. This check and the existing freeze/resume controller test passed.

The optional native C++ benchmark measured synthetic 120-joint, six-pose accumulation at median **0.05709 ms before versus 0.01242 ms after**, about **4.60× faster**, across eight alternating samples of 2,000 iterations. Both versions use the same lightweight transform recorder, with recording disabled for timing. This measures accumulation bookkeeping, not complete pose evaluation or viewer FPS; the fixture is not the measured crowd's joint/motion distribution. Command: `.venv/Scripts/python.exe scripts/tests/test_pose_blender.py --benchmark`, with g++ on PATH.

The broader unchanged-transform and keyframe-cursor proposals remain deferred: they need separate invalidation/caller evidence and crowded-scene timing. [Post-change validation log](E:/BoxxyViewer/output/w21-optimization/remaining-validation.txt). The required Release build succeeded. [Validation summary and build](E:/BoxxyViewer/output/w21-optimization/validation-summary.md). The research record below describes the original baseline.

**Measured budget and crowd interpretation**

The shared sample has 170 complete frames averaging 30.00 ms. Avatar `idleUpdate` takes **4.508 ms/frame**, including **2.207 ms motion updates** and **0.969 ms miscellaneous avatar/attachment maintenance**. Those are nested scopes, not additive to the avatar total. Name tags account for 0.158 ms/frame. The capture's exact executable revision has not been independently established; source references describe the inspected workspace baseline.

There are 15,300 avatar-object update calls, or 90/frame. This does not contradict the reported 50–60 residents: [updateCharacter's documented cases](E:/BoxxyViewer/indra/newview/llvoavatar.cpp:5112) include the local avatar, other residents, control avatars for animated objects, and UI avatars. The capture does not identify each avatar's role or distinct human owner. Do not infer 90 residents, 90 fully animated skeletons, or an unnecessary-update bug from this call count.

The [motion export and summarizer](E:/BoxxyViewer/output/w21-tracy-research/summarize_motions.py) attribute events to the same 170 complete frames and main exporter thread as the shared report. [Full results](E:/BoxxyViewer/output/w21-tracy-research/motion-summary.json):

| Motion scope | Calls in complete frames | Mean time per frame | Relationship |
|---|---:|---:|---|
| `LLCharacter::updateMotions` | 15,300 | 2.207 ms | Outer dispatch |
| Controller full update | 4,319 | 1.936 ms | Child of dispatch |
| Controller minimal update | 10,981 | 0.268 ms | Alternative child of dispatch |
| Controller by blend type | 8,638 | 1.719 ms | Inside full updates; two calls per full update |
| Keyframe `onUpdate` | 23,381 | 0.658 ms | Nested motion callbacks |
| Physics motion controller | 2,798 | 0.163 ms | Nested motion callbacks |
| Idle active-motion maintenance | 10,981 | 0.237 ms | Within minimal updates in this capture |
| Loading-motion maintenance | 15,300 | 0.0025 ms | Runs in both controller paths |

Full and minimal calls sum exactly to dispatch: **28.2% full, 71.8% minimal**, averaging 25.4 and 64.6 calls/frame respectively. These describe the path taken, not the number of visible humans or the exact pose work each full call performs. Minimal updates keep necessary motion lifecycle/time work; their 0.268 ms cost is much smaller than full updates.

Across the entire export, rather than the 170-frame subset, `updateMotionsByType` has 151.92 ms self time over 8,768 calls, about 0.883 ms per 172 exported display scopes. This includes uninstrumented pose accumulation and other controller bookkeeping. There is no separate timing zone for `LLPoseBlender::addMotion`, so 0.883 ms is an enclosing budget, not its measured cost. Self time can also include descheduling; this is not a CPU-sampling profile.

**Current scheduling and motion flow**

1. [idleUpdate](E:/BoxxyViewer/indra/newview/llvoavatar.cpp:2939) calls character update and then visibility/attachment/other maintenance. [updateCharacter](E:/BoxxyViewer/indra/newview/llvoavatar.cpp:5131) sets the animation-freeze state, handles build/appearance/root state and decides whether to update the pose.
2. [computeUpdatePeriod](E:/BoxxyViewer/indra/newview/llvoavatar.cpp:4671) already selects full-rate updates or impostor periods of 32, 48 or 64 frames according to visibility, muting, complexity and distance. [computeNeedsUpdate](E:/BoxxyViewer/indra/newview/llvoavatar.cpp:5083) spreads updates using a UUID byte and has a four-second maximum impostor interval. Self-avatar animation has explicit protection from the ordinary early-out.
3. Invisible or skipped avatars take `HIDDEN_UPDATE`. With Boxxy animation syncing enabled, the controller clock advances while pose evaluation is skipped; returning to visibility requests an impostor refresh. This preserves shared animation phase. Removing these minimal calls would risk synchronized dancing, finite-motion cleanup and visibility transitions.
4. [Full controller update](E:/BoxxyViewer/indra/llcharacter/llmotioncontroller.cpp:835) consumes elapsed wall time, respects freeze/pause, services loading, resets joint signatures and traverses additive and regular motions. [updateMotionsByType](E:/BoxxyViewer/indra/llcharacter/llmotioncontroller.cpp:568) preserves motion ordering, signature coverage, LOD fade, ease in/out, stop events and callbacks. It adds a motion to the blender even on its last callback.
5. [Minimal update](E:/BoxxyViewer/indra/llcharacter/llmotioncontroller.cpp:934) consumes the timer delta, optionally advances animation time and maintains loading/stopping motions without writing a pose. Frozen updates consume wall time before returning, preventing a large jump on resume. Pause ownership remains independent of the global freeze option.
6. [Keyframe update](E:/BoxxyViewer/indra/llcharacter/llkeyframemotion.cpp:684) handles loop/stop time, samples curves, applies constraints and updates hand-pose data. The motion's joint list comes from shared keyframe data, while character-specific state belongs to the motion instance.
7. [Pose blending](E:/BoxxyViewer/indra/llcharacter/llpose.cpp:471) groups joint states by target joint and applies priority/additive blending. Joint setters invalidate world transforms, and the avatar updates its joint hierarchy. [idleUpdateMisc](E:/BoxxyViewer/indra/newview/llvoavatar.cpp:3266) then maintains attachment positions, bounds and spatial bridges when detailed updates are required.

Animation evaluation is distinct from render-pass skinning and palette uploads in SSS/OIT. A change to one may affect another, but their timings must be measured in their respective parent scopes rather than counted twice.

**Candidate 1: constant-time active-blender membership**

For every joint state, [addMotion](E:/BoxxyViewer/indra/llcharacter/llpose.cpp:471) looks up its blender in `mJointStateBlenderPool` using `find`, then uses `operator[]` for a second tree lookup. It also uses `std::find` over `mActiveBlenders`, a linked list, to avoid duplicate active entries. `std::find` has linear worst-case comparisons in the range length. [C++ working draft, find algorithms](https://eel.is/c++draft/alg.find).

Overlapping motions revisit many of the same active joints. The [operation-count diagnostic](E:/BoxxyViewer/output/w21-tracy-research/count_pose_blender_searches.py) extracts the original commit's production `addMotion` body unchanged and wraps list pointer equality with a counter. Blending itself is stubbed because this measures membership work, not pose correctness or speed. [Recorded counts](E:/BoxxyViewer/output/w21-tracy-research/pose-search-counts.txt):

| Synthetic workload | Joint-state visits | Active-list comparisons |
|---|---:|---:|
| 30 joints, six overlapping pose additions | 180 | 2,760 |
| 120 joints, six overlapping pose additions | 720 | 43,440 |

For J distinct joints visited in the same order by M pose additions, this fixture performs `J*(J-1)/2 + (M-1)*J*(J+1)/2` comparisons. These joint/motion counts are examples, not measured w21 workloads. The diagnostic does not test an optimized implementation or claim a millisecond saving.

The smallest candidate is to retain the existing map and ordered list, reuse the map iterator, and give each pool-owned joint blender an active-membership flag (or owner generation if that better fits its lifecycle). Set it when first added; append in exactly the current `push_front` order. No additional hash container is needed. The pool owns distinct blenders for each pose blender, so membership must not be placed globally on a joint or shared motion.

Lifecycle rules matter: clear membership when `blendAndApply` empties the list and when `clearBlenders` clears it. Keep it active through `blendAndCache` and `interpolate`, which intentionally retain the list for cached-pose interpolation. Preserve priority ordering and the six joint-state slots, even when `addJointState` rejects a lower-priority state. A membership shortcut must not change arithmetic order, weights or callback behavior.

Before implementation, add an outer accumulation timing zone or aggregate comparison/visit counts at the controller level. Avoid instrumenting every joint with another heavy zone. Validate original versus changed pose output across multiple frames, clear/re-add, overlapping priorities, additive motions, rejected low-priority states and cached interpolation. This is the first recommended optimization because it targets demonstrably repeated bookkeeping with a small local change.

**Candidate 2: exact unchanged-transform guards**

[LLJoint::setPosition](E:/BoxxyViewer/indra/llcharacter/lljoint.cpp:333) already compares the effective value after attachment overrides. [setRotation](E:/BoxxyViewer/indra/llcharacter/lljoint.cpp:797) checks finiteness, but its equality guard is commented out and it always touches the joint. [setScale](E:/BoxxyViewer/indra/llcharacter/lljoint.cpp:865) resolves attachment scale overrides and always touches. [blendJointStates](E:/BoxxyViewer/indra/llcharacter/llpose.cpp:241) calls position, scale and rotation setters even when some channels retain their current values.

Consider exact equality after computing the effective scale first, then the effective finite rotation. Do not compare the requested scale before overrides, introduce an epsilon, normalize quaternions or treat q and -q as interchangeable without examining arithmetic and caller expectations. Audit setters used intentionally to force invalidation, attachment override changes, hierarchy changes and shape/skeleton rebuilds before adopting a guard.

[touch](E:/BoxxyViewer/indra/llcharacter/lljoint.cpp:198) already propagates only newly dirty flags. It is incorrect to claim every setter recursively dirties the whole skeleton on every call. [updateWorldMatrixChildren](E:/BoxxyViewer/indra/llcharacter/lljoint.cpp:963) also checks matrix dirtiness while traversing. Parent changes must continue to invalidate dependent children even if their local value is unchanged. Record actual setter equality, dirty touches and matrix recomputations; the existing `sNumTouches`/`sNumUpdates` counters are reset in avatar miscellaneous update and need careful ownership attribution.

This candidate may save work outside the controller as well as within it, but the trace does not quantify its recoverable share. Require transform/hierarchy equivalence tests for parent movement, attachment overrides, skeleton rebuilds and repeated no-op assignments before an in-world experiment.

**Candidates to defer or constrain**

| Candidate | Evidence and reason to defer |
|---|---|
| Curve-search cursor or contiguous key storage | Position/rotation/scale curves call `std::map::lower_bound` at [lines 162, 242 and 323](E:/BoxxyViewer/indra/llcharacter/llkeyframemotion.cpp:162). The 0.658 ms keyframe budget also includes interpolation/constraints/hand-pose work. First separate those costs. A cursor must be per instance and reset on loops, seeks, reverse time and curve edits; shared animation data can be sampled by avatars at different phases. Replacing all maps also affects serialization and loop-boundary resampling. |
| Attachment bounds/movement reuse | The 0.969 ms miscellaneous scope is meaningful but already checks detailed-update and visibility conditions. Attachments can receive server-driven movement independently of a joint, and updating bounds can invalidate the old spatial-bridge pointer. Measure repeated unchanged bounds and movement first; do not skip all maintenance for a frozen pose. |
| Further animation throttling | About 72% of updates are already minimal. More rate reduction changes motion quality and requires an explicit policy for self, nearby avatars, control avatars and UI previews. Preserve hidden animation time and finite-motion retirement. |
| Re-enable quantized time steps | Both the caller and controller document the existing SL-763 distant-animation speed defect. The `updateTimeStep` call is deliberately disabled. This is not a ready-made free optimization. |
| Whole-motion skipping from joint masks | Keyframe callbacks also affect constraints and hand-pose state. Skipping a callback based only on visible joint coverage could lose side effects or stop events. |
| Physics, hand/eye or loading rewrites | Their measured budgets are approximately 0.163, 0.009/0.005 and 0.0025 ms/frame respectively. Preserve behavior; prioritize the larger repeated bookkeeping first. |

**Original research validation and implementation handoff**

[Validation log](E:/BoxxyViewer/output/w21-tracy-research/validation.txt): `test_avatar_animation_freeze.py` passed extracted production full/minimal controller methods with deterministic time, covering normal, forced, hidden-sync and hidden-nonsync freeze/resume plus menu wiring. The pose search-count diagnostic also passed. At the research stage these tests covered the baseline, with no production changes or viewer launch. The implementation and its additional checks are recorded above.

The first implementation followed the active-blender recommendation, preserving list and arithmetic order and adding lifecycle comparisons alongside freeze/resume checks. Evaluate unchanged-transform guards separately if subsequent measurements justify them. Offline fixtures should include self/forced updates, additive/regular priority overlap, empty poses, equal transforms, rejected joint states, paused/frozen transitions, finite-motion stop/ease behavior, cached interpolation, different phases of shared animation data, and attachment/hierarchy changes relevant to the actual change.

When in-world validation is authorized, repeat the crowded scene with the same camera/settings, then exercise synchronized dance, hidden-to-visible/impostor transitions, walking/sitting, control avatars/animesh, appearance editing and attaching/removing rigged items. Record full/minimal update counts and avatar categories so a population change is not mistaken for an optimization. Compare whole-frame mean/tails and motion scopes, using an equivalent profiling configuration and a less instrumented check before claiming FPS gains. Keep this document updated with actual measurements and regressions as experiments proceed.
