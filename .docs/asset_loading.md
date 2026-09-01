The viewer has retrying, but mostly only inside one request. Once that retry budget is exhausted, several asset consumers convert the failure into a persistent in-memory “missing/unavailable/failed” state with no expiry. A transient network or capability failure can therefore last for the rest of the object’s lifetime—or the entire viewer session.
I traced the current checkout at commit 62033f2f80e3dce778538c000b95f846b0bb9e33.
How loading works
The simulator generally sends UUID references, not the asset bytes. The viewer checks its local cache, obtains the region’s ViewerAsset capability, then uses one of several separate pipelines:
Asset	Pipeline
Textures	Texture cache → ranged HTTP fetch → JPEG2000 decode → GPU texture
Mesh	Mesh cache → 4 KB header fetch → ranged LOD/skin/physics fetches → parse
Animations, sounds, landmarks, materials, etc.	Generic asset cache → full HTTP GET → subsystem-specific processing


There isn’t one unified retry controller.
Built-in HTTP retrying
The shared HTTP layer defaults to five retries after the original attempt—six total attempts. It uses exponential scheduling of approximately 1, 2, 4, 8, and 16 seconds, plus however long each network attempt takes. See [_httpinternal.h](E:\\BoxxyViewer\\indra\\llcorehttp\\_httpinternal.h) and [_httppolicy.cpp](E:\\BoxxyViewer\\indra\\llcorehttp\\_httppolicy.cpp).
It retries:
- HTTP 499–599, including 500, 502, 503, and 504.
- Connect, DNS, send/receive, timeout, and partial-transfer errors.
It does not retry ordinary 4xx errors such as 404, 408, or 429, nor most parse/decode failures. The classification is in [httpcommon.cpp](E:\\BoxxyViewer\\indra\\llcorehttp\\httpcommon.cpp).
After those attempts finish, the failure is returned to the individual asset subsystem—and that’s where the “forever” behavior appears.
Textures: the clearest bug
Textures do have extra recovery:
- They wait up to roughly 720 seconds for a missing region capability.
- A corrupt cached JPEG2000 file is removed and fetched again once.
- Server-baked avatar textures get an additional ten-retry adaptive policy with long exponential delays.
- Ordinary world textures do not get that outer adaptive retry.
The problematic path is in [llviewertexture.cpp](E:\\BoxxyViewer\\indra\\newview\\llviewertexture.cpp). If a fetch finishes with no raw image, it calls setIsMissingAsset() regardless of whether the final status was a genuine 404 or merely an exhausted timeout/503/network failure.
Immediately afterward, [updateFetch()](E:\\BoxxyViewer\\indra\\newview\\llviewertexture.cpp) does this:
if (mIsMissingAsset)
{
    return false; // skip
}
There is no timer or ordinary-world-texture recovery path. The code even says the flag should only be set when “we know for certain” the database lacks the image, but the fetch-failure path violates that rule.
The flag can disappear if the texture becomes completely unreferenced and is evicted after 30 seconds, but a visible object keeps referencing it, resetting that timer. That makes it effectively session-long. Server bakes and model-preview textures contain special code to clear the flag; normal world textures do not.
Mesh: retries, then a sticky unavailable flag
Mesh has two retry layers:
- The same five HTTP retries.
- Eight additional exponential retries when the viewer cannot even submit/start the request, beginning at 0.5 seconds. These do not cover a completed HTTP response that ultimately failed.
Once the HTTP layer gives up, the mesh handlers explicitly log “Not retrying” and mark the header or LOD unavailable. See the header handler in [llmeshrepository.cpp](E:\\BoxxyViewer\\indra\\newview\\llmeshrepository.cpp) and LOD handler in [llmeshrepository.cpp](E:\\BoxxyViewer\\indra\\newview\\llmeshrepository.cpp).
That eventually sets mIsMeshAssetUnavaliable on the shared system volume in [notifyMeshUnavailable()](E:\\BoxxyViewer\\indra\\newview\\llmeshrepository.cpp). There is no call anywhere that explicitly clears it; only a later successful load would clear it. But the existing object normally will not issue that later load because setting the same volume/LOD is a no-op.
Rigged-mesh skin metadata similarly gets an object-level unavailable flag, but there is an important correction to the original investigation: an ordinary skin HTTP/parse/decode failure does **not** leave the mesh in `mLoadingSkins`. The failure handler queues an unavailable notification, the main thread erases the loading entry, and avatar pending-mesh logic treats `skin info unavailable` as no longer pending. The sticky part is the per-`LLVOVolume` unavailable flag: that existing attachment normally will not request the skin block again. It can break that attachment's rigging, but it does not block unrelated attachments or abort the avatar's other pipelines. See [LLMeshSkinInfoHandler](../indra/newview/llmeshrepository.cpp#L3954), [the main-thread unavailable queue](../indra/newview/llmeshrepository.cpp#L4744), and [hasPendingAttachedMeshes()](../indra/newview/llvoavatar.cpp#L8008).

Failed decomposition and physics requests are worse: some failure paths leave the UUID in a “currently loading” set, preventing another request from being scheduled.
This anti-loop behavior was deliberate: source history includes the 2018 change MAINT-8593 Viewer should not repeat loads indefinitely. The viewer solved retry storms by giving up permanently rather than using a cooldown.

Remote avatars: bakes and attachments fail independently
Remote avatar appearance is at least three independent pipelines:
- `AvatarAppearance` supplies visual parameters, baked texture UUIDs, and an `AttachmentBlock` list describing the attachments the simulator expects.
- The actual attachment objects arrive separately through simulator object updates. Until an object arrives, the viewer does not know its mesh/material UUIDs and cannot request those assets.
- Once a mesh attachment object exists, its mesh LODs, textures/materials, and rigged-mesh skin metadata load separately.

The live rez status is calculated in [getRezzedStatus()](../indra/newview/llvoavatar.cpp#L970):
- `downloading baked` means the texture-entry data is present but the viewer's baked-download test is not complete.
- `loading attachments` means `isFullyTextured()` and `allBakedTexturesCompletelyDownloaded()` are true, but `getAttachmentCount() != mSimAttachments.size()`.
- `full` means those two counts are equal.

This attachment test compares **only counts**, not expected attachment UUIDs against received attachment UUIDs. The source even notes that it does not detect switched attachments. Also, `allBakedTexturesCompletelyDownloaded()` is only a heuristic: [allTexturesCompletelyDownloaded()](../indra/newview/llvoavatar.cpp#L5644) treats an ID that is absent from the texture list as complete, so the label is not proof that every bake decoded successfully.

On first visibility, [updateIsFullyLoaded()](../indra/newview/llvoavatar.cpp#L8677) waits at most about 60 seconds for texture callbacks and about 60 seconds after the attachment count stops changing. When the attachment wait expires, it copies the simulator's expected count into `mLastCloudAttachmentCount` and permits the avatar to decloud even though the live count mismatch remains. More importantly, [idleUpdateLoadingEffect()](../indra/newview/llvoavatar.cpp#L3307) calls the coordinator only while `mFullyLoaded` is false:

```
if (!mFullyLoaded && updateIsFullyLoaded())
```

Once a timeout makes `mFullyLoaded` true, this coordinator is not reevaluated. Existing asynchronous fetches may still finish, but the avatar loading/recovery path is latched off. This short-circuit was introduced by upstream [PR #2187](https://github.com/secondlife/viewer/pull/2187) to reduce repeated avatar loading checks. The separate avatar-appearance rerequest timer is 120 seconds, so the 60-second give-up can stop the loading state before that recovery timer fires.

Observed case: MisssBehavin, 2026-08-31
The live `DebugShowAvatarRenderInfo` overlay showed:

```
MisssBehavin : loading attachments, complexity 1600, area 0.00
```

This is strong evidence for an expected-versus-received attachment object mismatch, not a rigged-mesh skin request stuck in `mLoadingSkins`:
- The `loading attachments` label is generated from the live count mismatch, even after the loading coordinator has stopped.
- `area 0.00` means no attachment surface area was accumulated.
- Base body complexity is charged at 200 per defined visible baked channel in [calculateBodyPartsComplexity()](../indra/newview/llvoavatar.cpp#L11747). `1600` is consistent with eight base-avatar channels and no contribution from usable attachment geometry.
- Visually, the viewer showed only the classic avatar mesh, with custom baked skin but legacy hair/body artifacts and no attachments. Missing attachment objects also prevent Bakes-on-Mesh attachments from hiding the corresponding classic head/body/hair meshes.

The viewer log gives the exact failure timeline:
- `02:53:59Z`: the avatar arrived as `missing parts`.
- `02:55:01Z`: after 62.3779 seconds, the viewer emitted `fully loaded` while the same line still said `downloading baked`.
- Later, the live status became `loading attachments`: the baked-stage heuristic had advanced, but the attachment count still did not match. Because `mFullyLoaded` had already latched true, the coordinator did not revisit or recover the avatar.

This establishes the mechanism behind this instance as: partial bake progress plus missing/unattached attachment objects, followed by timeout and a permanent `mFullyLoaded` latch. It does not yet identify whether the attachment mismatch began because the simulator omitted object updates, the viewer dropped/failed to attach received objects, or the `AvatarAppearance` expected list was stale. The current logging records the expected UUIDs only when the `AVAppearanceAttachments` debug category is enabled.

The next diagnostic change should expose, for every remote avatar:
- `mFullyLoaded`, `mFirstFullyVisible`, and the live rez status simultaneously.
- Simulator-expected attachment count and **asset** UUIDs.
- Actually attached object count plus its separate object and inventory-item UUIDs.
- Pending attachment objects that lack drawables or failed `attachObject()`.
- Per-bake UUID, discard level, callback state, and missing-asset flag.

The UUID lists are diagnostic context, not directly comparable sets: the appearance payload and object stream use different identity domains. Counts and pending-object state can distinguish many missing-object and viewer-attachment failures, but exact expected-to-received identity matching is impossible with the current viewer-visible protocol.
Other assets do the same thing at the consumer level
Generic asset storage itself does not permanently blacklist failed UUIDs. It performs a full HTTP request with the shared five-retry defaults and then calls every waiting consumer with the result; duplicate requests are coalesced into that one network request.
However, consumers commonly turn that callback into a terminal state:
- Animation failure becomes ASSET_FETCH_FAILED; future initialization immediately returns failure in [llkeyframemotion.cpp](E:\\BoxxyViewer\\indra\\llcharacter\\llkeyframemotion.cpp).
- Sound failure sets mHasDecodeFailed, explicitly “to avoid constant rerequests,” in [llaudioengine.cpp](E:\\BoxxyViewer\\indra\\llaudio\\llaudioengine.cpp).
- Landmarks recently gained a limited exception: transient failures permit one later re-request, with 30 seconds between requests, in [lllandmarklist.cpp](E:\\BoxxyViewer\\indra\\newview\\lllandmarklist.cpp).
I also found a plausible teleport-related trigger: generic asset storage caches mViewerAssetUrl and refreshes it only when empty or while explicitly waiting for capabilities. It can therefore retain the previous region’s capability URL. The nearby landmark code specifically mentions obsolete capabilities after teleporting as a known failure cause.

Proposed fix shape
Do not replace every loader with one giant asset manager. Keep the texture, mesh, and generic pipelines, but give them a small shared failure vocabulary and retry-state helper, then repair each pipeline at its existing scheduling boundary.

The invariants should be:
1. Every request reaches exactly one terminal completion path and leaves every `loading` collection, whether it succeeded, failed, was canceled, or failed to post work.
2. `failed temporarily`, `authoritatively missing`, `invalid/corrupt`, `unsupported`, and `local cache/I/O failure` are distinct states. An empty result is not automatically `missing`.
3. A render timeout may permit a placeholder or partial avatar to appear, but it must not mark the underlying data complete or disable recovery.
4. Long-lived retries happen only while the asset still has an interested consumer. They use capped exponential backoff, UUID-derived jitter, request coalescing, and a global budget so failures cannot create a retry storm.
5. A success, new asset UUID, new avatar appearance version, region/capability generation change, or explicit debug refresh resets the relevant cooldown.
6. A negative result is never an immortal boolean. Even an authoritative 404 should have a long negative-cache TTL and be invalidated by endpoint/generation changes; transient failures get much shorter cooldowns.

Shared failure and cooldown state
A small dependency-light value type should carry policy rather than network machinery. Conceptually:

```cpp
enum class LLAssetFailureKind
{
    NONE,
    TRANSIENT,              // timeout, DNS/connect, 408/429, 5xx, missing/stale cap
    AUTHORITATIVE_MISSING,  // negative response from the current authoritative endpoint
    CORRUPT,                // bytes arrived but parsing/decoding failed
    UNSUPPORTED,            // unsafe dimensions/format/version
    LOCAL_IO                // cache read/write/rename failure
};

struct LLAssetRetryState
{
    LLAssetFailureKind kind;
    S32 attempts;
    F64 next_retry_time;
    U32 source_generation;
    S32 http_status;
};
```

The HTTP layer still performs its short in-request attempts. It should additionally retry 408 and 429, honor `Retry-After` for 429/503, and expose the final status. The consumer-level `LLAssetRetryState` handles later attempts over minutes without occupying an HTTP request or worker. Suggested transient cadence is approximately 2 s, 5 s, 15 s, 1 min, then a five-minute cap with jitter while relevant. Corrupt data gets one immediate retry after deleting only that cache entry, then a long cooldown. Unsupported/unsafe content does not automatically retry.

Texture changes
The smallest high-value change is at [LLViewerFetchedTexture::processFetchResults()](../indra/newview/llviewertexture.cpp#L1854):
- Use the already stored `mLastHttpGetStatus` to classify the terminal result.
- Call `setIsMissingAsset()` only for a current-endpoint authoritative negative or deliberately unsupported content, not every fetch that ended without a raw image.
- Store a retry state for transient/network/capability failures. [updateFetch()](../indra/newview/llviewertexture.cpp#L1997) should suppress work until `next_retry_time`, then allow the still-referenced texture back through normal priority scheduling.
- Keep or recreate loaded callbacks across a transient failure. Otherwise a later successful fetch can update the image while the avatar coordinator still believes the callback permanently finished.
- On decode failure, delete the one cached JPEG2000 entry and try the network once. If identical network data fails again, classify it as corrupt with a long cooldown rather than hot-looping.
- A new bake UUID or appearance version resets that bake channel's failure state. For a failed remote bake, continue displaying last-known-good pixels if available, but keep recovery active and request a fresh `AvatarAppearance` on bounded backoff.

Mesh changes
Mesh retry state should be keyed by `(mesh UUID, request kind, LOD/range)` in `LLMeshRepository`, where requests are already coalesced:
- Header, LOD, skin, decomposition, and physics handlers must all publish an explicit success or classified-failure event to the main thread.
- Fix decomposition and physics first: their failure handlers currently publish nothing, so [mLoadingDecompositions and mLoadingPhysicsShapes](../indra/newview/llmeshrepository.cpp#L4069) are erased only on success. Failure must erase or transition those entries to a scheduled cooldown.
- Do not set the shared `LLVolume::mIsMeshAssetUnavaliable` for transient HTTP/capability failures. Keep interested volumes registered in a cooldown entry and requeue it when due. Publish durable unavailable only for a long-lived authoritative/corrupt result.
- Replace `LLVOVolume::mSkinInfoUnavaliable` with the same retryable state, or at minimum add a retry deadline and clear it when due. A skin failure remains local to that mesh attachment.
- New consumers attach to the existing load/cooldown record, preserving request coalescing. Object destruction unregisters the consumer; a record with no consumers does not retry.

Avatar changes
Separate the concepts currently collapsed into `mFullyLoaded`:
- `initial rez released`: a one-way presentation gate saying it is acceptable to show a partial avatar after the deadline.
- `live completeness`: a dirty/event-driven status that can move both directions as bakes and attachments arrive, disappear, fail, or retry.
- `recovery state`: bounded timers for appearance rerequests and attachment repair.

Do not put the expensive old completeness calculation back on every frame. Mark an avatar dirty when it receives `AvatarAppearance`, adds/removes an attachment child, changes pending-attachment state, or receives a bake/mesh success or failure. Recompute on those events, with a low-frequency backstop only for incomplete visible avatars.

Attachment completeness cannot compare identities using the current payloads. Linden's viewer issue [#1117](https://github.com/secondlife/viewer/issues/1117) explicitly describes the new appearance fields as attachment **asset IDs**. `mSimAttachments` therefore contains asset UUIDs and points, while actual child objects expose a scene-object UUID and an inventory-item UUID. Neither equals the asset UUID. The viewer must use attached-object counts (optionally refined by attachment-point counts) and distinguish:
- The attached-object count has reached the simulator-expected count: complete under the current protocol's best available test.
- Object is known but lacks a drawable: keep it pending and request its full object update by local ID with cooldown.
- `attachObject()` failed: keep a bounded pending entry instead of dropping it as [addChild()/lazyAttach()](../indra/newview/llvoavatar.cpp#L7700) currently do.
- The expected count exceeds attached objects and there is no known pending object/local ID: send a bounded `avatartexturesrequest` to refresh `AvatarAppearance`, but record that this is an unresolved simulator object-stream miss.

`RequestMultipleObjects` requires a simulator-local object ID, while `AttachmentBlock` supplies an attachment asset UUID. Therefore a viewer cannot directly request an attachment object it has never heard about. A complete solution to that last case may require a simulator/interest-list resync message or capability such as `RequestAvatarAttachments`. The viewer-only fix can diagnose it, refresh appearance, recover known pending objects, and avoid latching, but it must not pretend that an asset UUID is requestable as an object local ID. A same-count outfit switch at the same attachment points also cannot be detected exactly without additional simulator data.

The current 60-second deadline should only release rendering. It must not copy the expected attachment count into an observed-count field, stop the 120-second appearance rerequest, or prevent later recovery. Classic meshes and last-known-good bakes may remain visible while this runs.

Generic asset and consumer changes
[LLViewerAssetStorage::assetRequestCoro()](../indra/newview/llviewerassetstorage.cpp#L443) currently maps HTTP failures, empty bodies, and invalid bodies into the same legacy error. Introduce a richer result alongside the existing callback API containing failure kind, HTTP status, region ID/capability generation, and cache status; migrate consumers incrementally.

Do not retain one nonempty `mViewerAssetUrl` indefinitely. Snapshot the current region ID and ViewerAsset capability for each attempt. If the agent's region/capability generation changes before completion, or the old endpoint fails, retry against the current capability. This removes the stale-capability teleport hazard without making asset consumers understand regions.

Then replace consumer latches incrementally:
- Animation `ASSET_FETCH_FAILED` becomes a retryable failure state; a still-requested motion can return to `ASSET_NEEDS_FETCH` when due.
- Audio `mHasDecodeFailed` distinguishes network fetch failure from actual decode failure and records a retry deadline.
- Keep the landmark implementation's delayed rerequest behavior, but migrate it to the shared classification/backoff helper.

Observability and manual recovery
Before changing retry behavior, extend the avatar render-info overlay and structured logs with expected/actual/pending attachment counts and IDs, `initial rez released` versus live status, per-bake discard/missing/retry state, and per-mesh request state. Globally record attempts, success-after-retry, final failure kind, time-to-recovery, and suppressed retries.

Add an Advanced-menu `Retry Failed Assets` action for a selected object/avatar. It should make cooldowns immediately due and request fresh appearance data; it should not erase good cache entries or create a separate loading implementation. This is a diagnostic and escape hatch, not the primary recovery mechanism.

Implementation order
1. **Instrumentation and terminal-path cleanup:** expose expected/attached/pending counts, clearly label the UUID domains, and expose retry state; make decomposition/physics failures always leave their loading sets.
2. **Avatar state separation:** keep partial avatars visible after 60 seconds while continuing event-driven completeness and bounded recovery; retain failed `attachObject()` entries.
3. **Texture classification and cooldown:** stop translating transient empty fetches into `mIsMissingAsset`; preserve callbacks and retry relevant textures.
4. **Mesh cooldown records:** migrate header/LOD/skin/decomposition/physics unavailability to classified, coalesced retry state.
5. **Generic assets and stale capabilities:** return richer results, bind requests to capability generations, then migrate animation/audio and other terminal consumers.

Fault-injection tests should cover timeout, DNS/connect failure, 408, 429 with `Retry-After`, 503, authoritative 404, corrupt cached bytes, corrupt network bytes, teleport during a request, appearance-before-attachment ordering, dropped attachment object update, failed `attachObject()`, and successful data arriving after the 60-second render deadline. A same-count switch should be documented as unobservable with current viewer-side identity data (or tested only after a simulator protocol extension). Acceptance requires eventual recovery without an object/relog where a viewer-side recovery request exists, no duplicate concurrent request for the same key, and bounded request rates during a prolonged outage.

Bottom line
The viewer has bounded retries, but almost no post-failure recovery. It conflates:
- “The asset definitely does not exist.”
- “The asset is corrupt.”
- “The CDN/capability/network failed temporarily.”
The proper fix is to replace one-way booleans with classified, expiring failure records containing reason, HTTP status, attempt count, next retry time, and source generation. Timeouts, 5xx responses, missing capabilities, and stale-region failures should enter exponential cooldown with jitter and retry while the asset remains relevant. Even authoritative negative results should expire or be invalidated when their source generation changes.

The safest first product slice is instrumentation plus avatar state separation and texture failure classification. That directly addresses the observed stuck-avatar case and the most common persistent texture failure while establishing the retry primitive that mesh and generic consumers can adopt afterward.

Implementation status — 2026-08-31 UTC

The findings above describe the pre-fix behavior at commit `62033f2f80e3dce778538c000b95f846b0bb9e33`. The first recovery slice is now implemented in the working tree:

- **Shared HTTP policy:** [HttpStatus::isRetryable()](../indra/llcorehttp/httpcommon.cpp) now includes HTTP 408 and 429. The existing policy code therefore also applies its bounded `Retry-After` handling to 429. Coverage for 408, 429, 499, 503, 404, 410, and the existing 501 behavior was added to [test_httpstatus.hpp](../indra/llcorehttp/tests/test_httpstatus.hpp).
- **Textures:** [LLViewerFetchedTexture](../indra/newview/llviewertexture.cpp) now distinguishes endpoint negatives from transient/transport and corrupt/decode outcomes. A transient failure releases its completed fetch worker, retains callbacks and interest, and re-enters the normal scheduler after deterministic UUID-jittered exponential cooldown. Corrupt results use a long cooldown. HTTP 401/403/404/410 still produce the normal missing-image result, but for non-map textures that negative result expires after a jittered 240–300 seconds instead of remaining immortal. Explicit refetch and success reset the retry state. Deliberately unsafe/unsupported images and absent map tiles remain terminal to avoid retry loops.
- **Remote avatars:** [LLVOAvatar](../indra/newview/llvoavatar.cpp) now treats `mFullyLoaded` as a one-way presentation latch while continuing a throttled live-recovery sampler. Attachment completeness uses the simulator-expected asset count versus the attached-object count because their UUID domains cannot be compared. A surplus does not force an incomplete result. Failed `attachObject()` objects remain pending and retry indefinitely at a capped 60-second cadence; known objects can request a fresh object update by local ID no more than every 10 seconds. An incomplete remote avatar can send at most three `avatartexturesrequest` refreshes per appearance generation, beginning after the 60-second presentation deadline; the budget resets after recovery or a new COF/appearance generation. This still cannot directly recover an attachment object the viewer has never received because no simulator-local object ID exists for it.
- **Avatar diagnostics:** `DebugShowAvatarRenderInfo` now adds distance plus expected, attached, pending, and missing attachment counts beneath each avatar. For the MisssBehavin case, this should immediately reveal whether the simulator advertised attachments but delivered none, or whether objects reached the pending/attach path.
- **Mesh decomposition and physics:** [LLMeshRepository](../indra/newview/llmeshrepository.cpp) now emits an explicit failure result for HTTP, parse, request-start exhaustion, cancellation, missing header/range, and allocation failure paths. The main thread consumes those results and always erases `mLoadingDecompositions` or `mLoadingPhysicsShapes`; shutdown also clears both sets. Physics parse failure is no longer published as an empty success. This is terminal-path cleanup and retryability groundwork, not yet the full coalesced mesh cooldown design.
- **Generic ViewerAsset capability selection:** [LLViewerAssetStorage](../indra/newview/llviewerassetstorage.cpp) no longer shares and indefinitely caches one `mViewerAssetUrl`. Each logical request snapshots the current agent region and its capability, and a coroutine waiting for capabilities wakes on a region change so it follows the new region. HTTP 404/410 are mapped to the existing not-in-database result. A request already in flight when a teleport occurs still finishes against its snapshotted endpoint; retrying that failed attempt against the new generation remains follow-up work.

Verification performed for this slice:

- `secondlife-bin` completed a full x64 Release compile and link successfully, producing `build-vc170-64/newview/Release/secondlife-bin.exe`.
- The first Release launch reached login but terminated at `STATE_WORLD_INIT` because the developer-build staging target had omitted `character/avatar_lad.xml` (the log ended in `LLAvatarAppearance::initClass`, before the new recovery paths ran). `stage_viewer_xui` now also stages the complete `character` directory and packaged fonts, and the rebuilt Release tree contains the required avatar XML, skeleton, fonts, app settings, and skin resources.
- `git diff --check` passes for all files in this slice.
- The HTTP classification unit cases are present, but this checkout has `LL_TESTS=OFF`, so the full build did not execute that test binary.

Post-test correction — William Ralior, 2026-08-31 UTC

The first live test of the new diagnostic showed:

```
William Ralior : loading attachments, complexity 5794, area 0.88
attachments expected 9 matched 0 pending 0 missing 9
```

The `matched 0` result was a diagnostic/behavioral regression in this working tree, not evidence that all nine attachment objects were absent. The implementation compared each `AttachmentBlock.ID` against `LLViewerObject::getAttachmentItemID()`. Linden's issue [#1117](https://github.com/secondlife/viewer/issues/1117) identifies the appearance values as **attachment asset IDs**; `getAttachmentItemID()` is the inventory-item ID parsed from the object's `AttachItemID` name-value pair. Those UUIDs are expected to differ, so even healthy avatars were reported as zero matches.

The viewer log confirmed the consequence: dozens of remote avatars were classified as incomplete together and each received attempts 1/3, 2/3, and 3/3 from the new `avatartexturesrequest` recovery path. That traffic was bounded but systematically unnecessary and could make an already busy scene noisier. It does not by itself prove that it caused every visually partial avatar.

The correction now:

- Uses `getAttachmentCount()` as the received count, matching the supported upstream protocol semantics.
- Defines `missing = max(expected - attached, 0)`, so a temporary/stale surplus does not keep an avatar falsely incomplete.
- Labels the overlay `attached`, not `matched`, and adds viewer-to-avatar distance.
- Keeps pending-object retries and the bounded appearance recovery, but they now trigger from a real count deficit (or independent bake/visual-param incompleteness), not a cross-domain UUID comparison.
- Documents same-count switched attachments as unobservable without a simulator payload that correlates expected asset IDs with object or inventory-item IDs.
- Compiles and links successfully in the x64 Release target. The corrected executable is `build-vc170-64/newview/Release/secondlife-bin.exe`, written `2026-08-30 22:49:22 -06:00`, SHA-256 `C89C08EC1D0B122D6E89CBDF8FB4A854D5511BE520E27A577F3A949143401123`.

Distance can independently affect how complete an avatar looks. Baked-avatar texture statistics are driven by the avatar's screen pixel area in `LLVOAvatar::updateTextures()`/`addBakedTextureStats()`, attachment texture virtual size comes from each face's on-screen pixel area, and avatars are ranked/culling-updated by pixel area. Farther or off-screen avatars therefore receive lower texture detail/priority and are more likely to use impostors or low mesh LODs. This is separate from the attachment count:

- `attached < expected` means one or more root attachment objects have not reached the successfully attached state. If `pending > 0`, the viewer knows those objects but has not attached them; if `pending == 0`, the viewer has no requestable local object for the deficit. Distance may correlate through the simulator's object-interest stream, but the viewer cannot directly prove that from an unseen object.
- `attached >= expected` while the avatar still looks partial points instead toward low/deferred mesh LOD, textures/materials, rigged skin data, or intentionally sparse lowest-LOD content. Here viewer-side screen-size prioritization directly makes distance relevant.

Remaining implementation work, in priority order:

1. Replace mesh header/LOD/skin sticky unavailable flags with classified, expiring, coalesced cooldown records; extend the same mechanism beyond decomposition/physics cleanup.
2. Make an in-flight generic asset request detect a region/capability generation change and retry once against the new current endpoint; then expose richer failure status to consumers.
3. Migrate animation and audio consumer latches from permanent fetch failure to retryable fetch state while keeping true decode/unsupported failures rate-limited.
4. Add shared global retry budgeting/telemetry and fault-injection coverage for transport errors, 408/429/503, corrupt bytes, teleports, dropped attachment updates, and late success.
5. Add the manual `Retry Failed Assets` diagnostic action after the automatic paths are stable.

Live follow-up — full roots but missing visible attachments, 2026-08-31 UTC

Two later observations disprove attachment-root count as a sufficient completion test:

```
William Ralior: full, dist 17m, complexity 21568, area 6.28
attachments expected 9 attached 9 pending 0 missing 0

Toran Gustafson: full, dist 21m, complexity 9786, area 1.08
attachments expected 17 attached 17 pending 0 missing 0
```

William was visibly missing some attachments. Toran showed the textured classic avatar body but none of the expected visible mesh body/clothing, despite all 17 attachment roots being attached. This means `getAttachmentCount()` answered the narrower question correctly while the `full` label overclaimed render completeness. An attachment root can arrive and attach while any of the following remains incomplete:

- Linked child object updates have not arrived. Many products use a tiny/invisible root and put the visible mesh in child prims.
- A received prim lacks a drawable or built face geometry.
- Its selected mesh LOD is loading, terminally unavailable, or loaded with no faces.
- Rigged skin metadata is still undecided.
- Referenced textures have no decoded data yet or are terminally missing.
- The avatar is being represented by an impostor snapshot made from an earlier partial state.

The first case is now directly observable. Since December 2023, a full `ObjectData` update for a non-tree root carries a one-byte total-prim count in its generic `Data` field; an empty field explicitly means a one-prim linkset. The upstream viewer parsed this value only into a debug local and discarded it. `LLViewerObject` now retains it as `mExpectedLinksetPrimCount` (`0` means not yet known). Attachment diagnostics compare that count with a guarded recursive traversal of the root and all currently received descendants. This produces known received/expected prim totals, an incomplete-linkset count, and an unknown-count count independently of attachment-root completeness.

The enhanced `DebugShowAvatarRenderInfo` overlay now reports three layers:

1. Rez label plus agent distance, camera-derived avatar pixel area, impostor state, complexity, and physical attachment surface area.
2. Expected/attached/pending/missing roots plus received/expected prims for known linksets.
3. Received objects, missing drawables/geometry, mesh ready/loading/unavailable/empty counts, skin waiting, and unique attachment texture ready/fetching/unresolved/missing counts.

When the root-level rez status says `full` but structural content is incomplete, the debug label says `full/partial`. Texture `fetch` means an active fetch exists. Texture `wait` means the texture has no decoded pixels but no active fetch; that can be low camera priority or cooldown rather than a terminal error. `missing` is the terminal missing/denied state. Static mesh legitimately has no skin block, so `skin-wait` counts only the undecided state, not every unskinned mesh. Placeholder/default/invisible magic textures are excluded.

Distance and impostors

The new `px` value is the avatar's camera-derived screen pixel area. It changes when the camera moves or zooms and drives avatar ranking, impostor selection, texture importance, and mesh LOD. The existing `dist` value is agent-to-avatar distance, while `area` is physical attachment surface area; neither is the texture priority itself. This makes the reported correlation with farther avatars technically plausible even when root counts are complete.

A stale impostor is a real refresh gap but probably not the sole explanation for an hour-long visible failure. `computeNeedsUpdate()` forces a visible remote avatar's impostor dirty after a maximum interval of about four seconds. However, attachment attach/detach and `notifyAttachmentMeshLoaded()` did not directly invalidate it, and linked child mesh completion could miss the owner because `getAvatar()` commonly returns null for children whose own attachment-state bits are zero. Attachment texture completion also has no owner-avatar callback. The working tree now:

- Invalidates a remote avatar impostor immediately after a successful root attach or detach.
- Uses `getAvatarAncestor()` when a linked attachment mesh finishes, then invalidates the owner's impostor.
- Samples a compact attachment-content signature every 15 seconds; any change invalidates an existing impostor, covering late child/mesh/texture progress without a per-frame traversal.

Protocol recovery limit

The message template defines `RequestMultipleObjects` cache-miss type 0 as a request for one full object identified by simulator-local ID. If a linkset says it should contain more prims than the viewer received, the absent children have no known local IDs. Re-requesting the known root can refresh the root but cannot directly name those missing children. The viewer therefore logs structural gaps but does not generate speculative repeated root requests. A robust repair for confirmed missing-child cases requires a simulator-side linkset/avatar attachment resync operation or another payload that supplies the missing child local IDs.

Current-session log evidence around the William/Toran reports showed no mesh-handler failure messages. It did show repeated asset-CDN texture HTTP 403 results (37 failures across 21 UUIDs in the sampled run), each becoming a missing texture and later receiving the newly bounded negative-cache retry. The same UUIDs returned 403 again. Those failures may explain particular invisible/incorrectly alpha-masked surfaces, but the log does not contain enough avatar ownership context to attribute them specifically to William or Toran. The content overlay is needed to distinguish linkset loss, mesh state, texture state, and camera/impostor behavior per avatar.

This diagnostic/impostor-refresh follow-up compiled and linked successfully in the x64 Release target. The test executable is `build-vc170-64/newview/Release/secondlife-bin.exe`, written `2026-08-30 23:22:24 -06:00`, SHA-256 `BE93BDEE1582AFE9911C67D8901328A6503FBFF63D16D1847B70320B910C7C6B`.

Object-cache root-only linkset follow-up — 2026-08-31 UTC

The next William Ralior observation isolated the failure one layer earlier than mesh or texture fetching:

```
roots expected 9 attached 9 pending 0 missing 0
link prims 9/125 incomplete 9
objects 9 no-draw 0 no-geom 0 | mesh ready 5 wait 0 unavailable 0
```

All nine attachment root objects existed and rendered, but those roots advertised 125 total linkset prims and the viewer had exactly nine objects. In other words, none of the 116 linked children had entered the avatar's object graph. A separate login log showed the same person at `8/245`, again exactly one received prim per root. Many other avatars in that session exhibited the same root-only pattern, while some later progressed to their complete prim totals. This rules out distance, impostors, mesh LOD, skin decoding, and texture decoding as the primary cause of this particular state. Those systems cannot load content for child objects that do not exist in the viewer object graph.

The relevant cache is the simulator **object cache**, not the general asset or texture cache. It stores each object/local ID independently rather than storing a linkset atomically. Cached entries loaded from disk begin invalid and do not yet have their packed parent/spatial data decoded. The simulator confirms current objects with cache probes or compressed full object updates; only then may the viewer safely materialize the cached object. A partial root/child set can therefore be persisted and reconstructed across sessions.

A concrete activation bug existed in `LLViewerRegion::cacheFullUpdate()`: when a compressed full update matched the CRC of an invalid disk-cache entry, the code first marked the entry valid, classified the packet as a duplicate, and skipped `decodeBoundingInfo()`. A later `ObjectUpdateCached` probe saw the entry as already valid and skipped decoding again. The entry could remain current-session-confirmed but permanently unmaterialized, with its packed parent ID never connected to the live attachment root. This failure shape strongly matches fresh/uncompressed roots plus root-only cached children.

The working-tree repair now:

- Remembers whether an existing cache entry was valid before a compressed full update. A same-CRC `invalid -> valid` transition refreshes the cached bytes from the simulator's authoritative packet, then calls `decodeBoundingInfo()` and enters the normal visibility/materialization path instead of being dropped as a no-op duplicate. INFO logging samples the first ten and every hundredth such reactivation.
- On a low-frequency incomplete-avatar recovery pass, groups incomplete attachment root local IDs by region and scans that region's cache once. Parent IDs are read from the packed update, so the scan can find entries affected by the old bug even when their in-memory `mParentID` was never decoded. The cache graph is followed transitively through confirmed children so visible grandchildren are not missed.
- Schedules only valid entries confirmed by the simulator in the current session. Invalid disk-only entries are reported as `unconfirmed` but never revived or requested by their stale local IDs.
- Leaves orphan reconnection to the normal object-materialization path instead of manually replaying the broad local-ID orphan list.
- Limits repeated cache materialization attempts to three without forward prim-count progress. Forward progress or a new appearance generation resets the budget.
- Does not run the scheduling pass when object-cache culling is disabled, because that configuration bypasses the queue state machine.
- Validates packed-buffer lengths before reading cached parent IDs, so malformed short disk records are ignored rather than parsed speculatively.

The avatar overlay adds a fourth line for structurally incomplete linksets:

```
cache snap kids N active A wait W queue Q idle I unconfirmed U | queued-now R tries T
```

Interpretation:

- `queue` or `wait`: confirmed cached children are already moving through object creation.
- `idle`: confirmed children exist but could not yet be connected/materialized; the bounded repair will retry.
- `active`: cached child objects materialized; if the recursive avatar count still does not include them, the remaining problem is object parenting/orphan reconnection.
- `unconfirmed`: matching children exist only in the disk cache and were not confirmed by this session's simulator stream. Loading them would be unsafe because simulator local IDs can be reused.
- `cache snap kids 0` with a large prim deficit: neither the live object graph nor the confirmed/reachable region-cache graph contains targetable child local IDs. The viewer cannot manufacture a `RequestMultipleObjects` request for those unseen children; that case still needs a simulator interest-list/linkset resync or a clean session in which the simulator sends the children.

`cache snap` is the most recent low-frequency recovery snapshot, not a per-frame cache query. `queued-now` reports entries advanced out of the inactive state during that pass; it does not claim their viewer objects have already finished materializing.

Disabling `ObjectCacheEnabled` for one relog remains a useful A/B diagnostic: it prevents disk object-cache reuse and tells the simulator that the viewer's cache is empty, so objects selected for the viewer must arrive as full updates rather than cache probes. It does **not** request every object in the region. It costs bandwidth and is not the intended permanent default. With the invalid-to-valid transition fixed, a normal cached relog should no longer lose same-CRC child updates through this specific path.

This object-cache activation/recovery follow-up compiled and linked successfully in the x64 Release target. `git diff --check` passes. The test executable is `build-vc170-64/newview/Release/secondlife-bin.exe`, written `2026-08-31 00:16:39 -06:00`, SHA-256 `C19EBD0D05F719EC5A3635BC8D99AEFAA650A534BBB05062E8A306BDCE668D76`.

Post-fix live validation — root-only arrival stream, 2026-08-31 UTC

The first live run of the cache-activation build produced a stronger discriminator for the persistent avatar failure. One affected avatar remained present at approximately 18 metres with roughly 8.6 million camera-derived pixels and reported:

```
full/partial
cache snap kids 0 active 0 wait 0 queue 0 idle 0 unconfirmed 0
objects 9 no-draw 0 no-geom 0 | mesh ready 5 wait 0 unavailable 0
roots expected 9 attached 9 pending 0 missing 0 | link prims 9/125 incomplete 9
```

The executable and settings path in the log confirm that this was the repaired build. The session emitted zero `Reactivating same-CRC disk cache entry` messages. Therefore the same-CRC invalid-cache activation bug was not exercised for this avatar in this run, and the per-root cache recovery pass had no confirmed, unconfirmed, active, waiting, queued, or idle child entries reachable from the nine current root local IDs. The repair remains valid for the logic hole it addresses, but it is not the primary explanation for this live failure.

This pattern was widespread among avatars already present during login: many linksets remained at exactly one received object per advertised attachment root while every cache-child counter stayed zero. Some avatars arriving or updating later did receive children and could reach complete totals such as `186/186`. Mesh requests also completed for received roots without changing the missing-child totals. Together these observations shift the leading cause from mesh, texture, skin, impostor, and per-root disk-cache materialization to the simulator interest/object-update stream during the crowded login burst.

Repeated `RequestAgentUpdate`/`AvatarAppearance` recovery attempts returned the same appearance generation but caused no attachment-child progress. That request refreshes wearable/appearance state; it is not a linkset-object resync. The session logged 119 circuit packet resends early after login. This supports, but does not prove, a busy or lossy startup interval. The protocol's `ObjectUpdate`, `ObjectUpdateCompressed`, and `ObjectUpdateCached` messages are not themselves marked reliable in the message template. If a child update is never received, the viewer learns neither its simulator-local ID nor its parent relationship and consequently has no identifier with which to request that child later.

Distance can still correlate through simulator interest-list prioritization, but it is not a sufficient explanation here: the affected avatar had very high current camera pixel area and remained root-only. Raising viewer-side camera priority cannot recover an object whose local ID was never announced, and the viewer has no existing completion-driven family-resync request when an advertised root prim count remains short.

Two follow-ups can further separate the remaining cases:

1. Add a lightweight diagnostic count for objects sitting in `LLViewerObjectList`'s orphan tables with parent IDs matching the incomplete attachment roots. This distinguishes “child update received but parenting never completed” from “child update never entered the viewer object list.”
2. Perform one controlled relog with `ObjectCacheEnabled` disabled without clearing unrelated asset caches. This advertises an empty object cache but does not request the full region cache. If the same root-only pattern remains, disk-cache reuse is effectively ruled out; if it disappears, the cache-probe/full-update handshake remains implicated even though no per-root cache entries were reachable in this run.

Protocol inventory: no linkset-family fetch request

The viewer/simulator protocol exposed to the viewer has no request that means “given this known root, send every prim in its linkset.” The available nearby operations are all insufficient:

- Reliable `RequestMultipleObjects` requests a full update for each explicitly supplied simulator-local `U32` ID. Re-requesting a known attachment root returns that root; it does not enumerate or return its unseen children.
- `RequestObjectPropertiesFamily` accepts one known object UUID, but its response contains ownership, permission, sale, and descriptive properties rather than a linkset member-ID manifest or renderable object updates.
- `ObjectSelect` accepts explicit local IDs. The viewer's “select object and family” implementation first walks the children it already has and sends every known member ID; it does not rely on the simulator expanding one root ID into a complete family. It therefore cannot name missing children either.
- Appearance-update requests describe avatar wearable/bake state and appearance generations, not an attachment linkset manifest.
- Object-cost, physics, pathfinding-linkset, and attachment-resource capabilities provide specialized metadata and are not general object-content fetch APIs; attachment resources are also oriented toward the requesting agent's own attachments.
- `RegionHandshakeReply` can advertise cache-empty/all-cacheable behavior for the whole region as object streaming begins. It is coarse session/region initialization, not a safe per-avatar or per-linkset repair endpoint.

Consequently, the simulator must first announce each child through an object update/cache probe before the viewer can address it. The root's advertised total-prim count reveals that content is missing but supplies no member IDs. Persistently seeing the same remote avatars root-only across several relogs is therefore compatible with stable simulator-side interest/cache bookkeeping: as long as those avatars and attachment instances remain in the region, their local IDs and the omission decision can remain stable across viewer sessions. Random packet loss alone becomes a less satisfying explanation when the identity pattern repeats, although a controlled cache-disabled relog is still needed to distinguish simulator interest state from the region object-cache handshake.

Handshake clarification

The region-startup reply has two independent viewer flags in this codebase:

- Bit 0 asks the simulator to send the full region object cache. It is set only when both `RequestFullRegionCache` and `ObjectCacheEnabled` are enabled.
- Bit 1 says the viewer's region object-cache map is empty, so the simulator need not send cache probes.

Therefore `ObjectCacheEnabled=false` produces an empty-cache startup but disables the full-region-cache request; it is not the broadest possible stream. Starting with an empty region cache while leaving both cache settings enabled sets both bits and is the broad region-wide fresh-stream experiment. Neither is a per-avatar request, and neither supplies IDs from viewer knowledge. If either experiment repairs an avatar, the simulator has re-enumerated/pushed the child IDs in response to coarse connection-level state. That would prove a client-triggerable region refresh path exists, but it would not create an in-session `root -> complete linkset` API. Resending `RegionHandshakeReply` after initialization is not specified as a refresh operation, so treating it as one would be an experimental protocol hack rather than a supported recovery mechanism.

Avatar-scoped cache repair boundary

There are two different cache-removal granularities in the current implementation:

- `LLViewerRegion::killCacheEntry(U32 local_id)` targets one in-memory region-cache entry. Despite its “physically delete” comment, it removes the entry from current cache/render scheduling and marks it invalid; it does not erase that object record from the region map by itself. When the local ID is known, the viewer can then send reliable `RequestMultipleObjects` with cache-miss type 0 to obtain a new authoritative full update.
- `LLVOCache::removeEntry(U64 region_handle)` removes the persistent object-cache file for an entire region. The persistent cache does not currently expose an avatar- or individual-object deletion API.

An avatar-scoped automatic repair is nevertheless possible for **addressable** gaps. When `received < expected`, the viewer can collect child local IDs from (a) the live attachment graph, (b) object-list orphan records whose parent is one of the avatar's known roots, and (c) current-session-confirmed region-cache descendants of those roots. After ordinary materialization attempts make no progress, a bounded escalation can invalidate only those cache records and reliably request full updates for those IDs. It should use a cooldown, deduplicate IDs, require current-session confirmation for cache-only records, and stop when the received prim count advances.

This cannot repair an **unaddressable** gap such as `cache snap kids 0`, no matching live children, and no matching orphans. Removing the known root entry and re-requesting the root supplies the root again, not its child-ID manifest. Deleting arbitrary or stale disk entries likewise cannot induce a request for IDs the viewer never learned. Such a case must fall back to a coarse region-stream lifecycle event or a future simulator-supported linkset-family resync operation.

Object discovery is simulator-pushed

The viewer does not initially request a remote avatar by UUID or local ID. After circuit setup, the simulator sends `RegionHandshake`; the viewer loads its region cache and returns reliable `RegionHandshakeReply`. The protocol explicitly says that after this reply the simulator starts sending object data. A full `ObjectUpdate` whose PCode is avatar causes the viewer object list to create the `LLVOAvatar` instance. `CoarseLocationUpdate` is a separate, lower-detail stream used for map/coarse positions and is not sufficient to construct a renderable avatar.

During the session, the viewer sends generic `AgentUpdate` messages containing its camera center and axes. Those inputs help the simulator choose and prioritize the objects in the viewer's interest set, but they are not requests for a named avatar. An avatar entering the area can therefore be announced without any avatar-specific request from the viewer. This push model is the core asymmetry behind the missing-child dead end: the simulator must first announce an object's local ID; only after that can the viewer use `RequestMultipleObjects` to refresh it.

Ranked hypotheses for root-only simulator object delivery

The current evidence proves that the expected children are absent from the avatar's live object graph and from the cache graph reachable by its current roots. It does **not yet prove** that their update packets never reached the viewer. They could have arrived and then been discarded, orphaned, misparented, or culled before the low-frequency snapshot. The current log contains no `createObject failure`, unknown-local-ID, zero-PCode, malformed-object, or invalid-packet evidence, which weakens an obvious decoder rejection but does not instrument every silent lifecycle path.

The hypotheses, ordered by consistency with the observations, are:

1. **Simulator interest/update-queue bookkeeping failure.** Avatar and attachment roots are high-value discovery objects, while linkset children are separately scheduled object updates. A crowded login can fill a per-agent object-update queue. If roots are delivered but child work is deferred, dropped, coalesced, or marked sent before successful delivery, the simulator has no viewer-reported `125 expected / 9 constructed` completion signal that would cause it to repair the family. Stable priorities and attachment instances can make the same avatars fail across reconnects.
2. **Object-cache handshake disagreement.** The simulator may believe it has adequately announced or cache-probed particular child records while the viewer has no corresponding usable entries. Stable simulator local IDs and a nonempty region cache can reproduce the same omission over relogs. The repaired viewer-side same-CRC transition did not activate in this run, so any remaining version would be broader than that concrete bug. Empty-cache and empty-plus-full-region-cache startup tests distinguish this path.
3. **Deterministic attachment bounds/culling error.** Products commonly use tiny or invisible roots and put visible content in children. If attachment-child positions or bounds are evaluated incorrectly by the simulator's interest logic—especially relative versus world coordinates—the same products or avatars can be consistently deprioritized or culled. The earlier distance correlation supports an interest component, although every child across nine separate roots being absent suggests something broader than one malformed attachment.
4. **Viewer receives children but loses their lifecycle.** Children can arrive before roots and enter orphan handling; cache-culling and UUID/local-ID bookkeeping add more transitions before they become attachment descendants. A reconnect failure or later kill could yield the same final `kids 0` snapshot. Existing logs do not trace these stages per root, so this remains open despite the lack of explicit creation errors.
5. **Packet loss or queue pressure alone.** The session accumulated reliable packet resends during the login burst, and object delivery is heavily queued/throttled. Lost update batches could remove many children at once. Purely random loss is a weaker explanation for the same identities failing over several relogs unless packet grouping and priority make the loss deterministic.
6. **Corrupt simulator-side attachment instance.** The root's advertised prim total may remain valid while the simulator's observer-facing child collection or change state is stale. The affected wearer crossing a region boundary, detaching/reattaching, or teleporting away and back would reconstruct/reannounce the attachment instances and is the best discriminator for this case.

The decisive next diagnostic is a per-root receive/lifecycle trace. For every incoming full, compressed, or cached object update, record its local ID and packed parent ID in a bounded region map even if object creation or cache materialization later fails. Once an incomplete avatar root is known, report counts at each stage: packet observed, cache-confirmed, viewer object created, orphaned, parented, and killed. Outcomes then become unambiguous:

- `packet observed = 0`: simulator interest/queue or network delivery.
- `observed > 0, created = 0`: decode/cache/update rejection.
- `created > 0, parented = 0`: orphan/parent resolution.
- `parented > 0` followed by kills: cache culling or object lifecycle removal.

Final implementation disposition — 2026-08-31

The live evidence changed the implementation scope. Earlier sections retain the investigation history and describe experiments that were temporarily present in the working tree; they are not all descriptions of the final code.

Retained fixes:

- **Textures:** terminal failures are classified locally. HTTP 408, 429, 5xx, and transport/core failures receive jittered cooldown retries, bounded to eight failed request generations. Exhaustion stops automatic scheduling until an explicit refetch or request reset. HTTP 401, 403, 404, and 410 remain terminal missing/denied results and are not periodically retried. Successful data clears retry state. The shared `HttpStatus::isRetryable()` policy was not broadened, so unrelated HTTP consumers are unchanged.
- **Generic ViewerAsset requests:** the ViewerAsset capability is resolved from the current agent region for each logical request. Concurrent coroutines no longer share a mutable cached URL, and a teleport while waiting for capabilities wakes the coroutine to follow the new region. HTTP 404/410 are reported as not-in-database rather than a generic request failure.
- **Mesh decomposition and physics-shape requests:** every terminal post, HTTP, parse, allocation, or cancellation failure reaches the main thread and erases the UUID from the corresponding `mLoading*` set. A failed request can therefore be requested again instead of remaining suppressed forever. The physics parse-failure path also deletes its temporary decomposition object.
- **Object cache:** an invalid disk entry confirmed by a same-CRC compressed full update is refreshed from the authoritative incoming packet and decoded/materialized. The broad avatar-driven descendant cache scan was removed.
- **Attachment diagnostics:** roots retain the simulator-reported linkset prim count, and the debug avatar overlay reports root counts, received/expected prims, drawable/geometry state, mesh/skin state, and texture state. This is diagnostic only and performs the expensive recursive content walk only while the debug overlay is enabled.
- **Known pending attachments:** an attachment object that exists but temporarily lacks a drawable or fails `attachObject()` remains in a bounded-backoff pending path. If it has a simulator-local ID, the viewer can request a fresh full object update with cooldown, capped at three network refreshes per pending-object generation.
- **Presentation refresh:** remote-avatar impostors are invalidated directly when an attachment attaches, detaches, or finishes mesh/skin loading. Linked mesh children use the avatar ancestor rather than only their own attachment-state bits.

Removed after live testing:

- Repeated `AvatarAppearance`/`avatartexturesrequest` attempts as recovery for missing linkset children. They returned the same appearance generation and never supplied the absent object IDs.
- Automatic per-avatar scans and materialization attempts over region object-cache descendants. They found no targetable children in the observed root-only cases and added correctness, performance, and merge risks.
- Periodic full attachment-content signature scans and recovery timers.
- The experimental change that made `mFullyLoaded` an explicit one-way presentation state. Upstream loading-state behavior is restored.
- Periodic retries of authoritative texture negatives such as the repeatedly observed HTTP 403 responses.

The practical boundary is now explicit: viewer retries can repair an asset whose UUID/local ID is already known, but cannot repair a simulator-pushed attachment child that was never announced. The `9/125` case occurs before texture, mesh, or skin fetching. The next useful investigation for that case is bounded incoming-object lifecycle instrumentation (`observed -> decoded -> created -> orphaned/parented -> killed`), not additional asset retries.
