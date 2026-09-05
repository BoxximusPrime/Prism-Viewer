# Inventory Cleanup

Status: in progress. The Release build, including final viewer linking, and the authorization regression suite pass. Runtime checks remain pending.

Open Inventory > gear menu > Inventory Cleanup. The landing page presents four large square cards using native button styling, hover/focus states, and theme colors. Each card opens and scans its tool; All cleanup tools returns to the landing page. The year selector appears only for Older inventory. Protected folders can be toggled in the results inspector. Routine item details show readable paths and permissions; exact IDs remain in confirmation review. Tools: whole demo folders identified strictly by their own folder names, same-asset copies, exact normalized-name/creator object version groups with different known assets, and acquired-before-year review. Demo detection matches whole demo/demos tokens in folder names only, case-insensitively. Item names, notecard text, and descriptions never establish a demo candidate. Dates use inventory Acquired timestamps, not last-used history. Unknown dates are excluded from age filtering; unknown asset IDs never establish asset equality.

Results show 500 rows per page, with no automatic selection. Changing pages clears selection. Up to 200 selected roots and 2,000 total affected entries can be reviewed per operation. The separate review freezes each selected item's metadata and full source path, exposes item/asset IDs and permission details, and requires acknowledgement before enabling the count-labeled move button. List selection within review never changes the move set. Demo candidates are whole folders. Their full contents appear in review, including landmarks, HUDs, notecards, and nested folders. The folder moves to Trash intact. Other tools still select individual items. Eligible enclosing packages suppress nested candidate rows to avoid overlapping selections; ineligible or oversized parents do not suppress safe child packages.

The executor validates the entire reviewed set against current inventory before sending any moves. A missing, moved, renamed, changed, newly worn, linked, or protected entry rejects the entire review before any move. Folder fingerprints include the full descendant identity set and metadata; adding, removing, or changing a descendant invalidates review. Any ineligible descendant excludes the whole package. Each operation uses only frozen root UUIDs. Whole-folder actions send one folder move per reviewed root; descendants are not moved individually. Overlapping roots or duplicate affected identities are rejected. There is no name-based substitution, purge, or empty-Trash call. Review authorization is consumed before dispatch to prevent repeated execution. The server processes moves asynchronously, so the result reports requests rather than claiming server-confirmed completion. A mid-dispatch local change can stop remaining requests; already sent requests cannot be rolled back atomically. The viewer rechecks known contents immediately before a folder move, but the server provides no conditional folder-move transaction: changes from another client after dispatch cannot be atomically excluded.

Loading must finish and inventory categories/items must be complete before scanning or authorizing a move. A compact loading message refreshes every two seconds. While loading is incomplete, Loading details reveals complete/known personal folders, item metadata counts, and shared inventory/Library queued and active requests. Retry and diagnostic controls disappear when ready. Counts are not a percentage of a fixed total: new folders can reveal more entries. The personal traversal, request-idle state, and actual completeness audit determine readiness; the historical all-inventory-and-Library completion flag is not used. An idle fetch with incomplete data is labeled explicitly, with unchanged-count elapsed time after 30 seconds. Loading details lists up to 50 blocking folders/items and expected versus cached child counts. Retry loading (also invoked by a blocked Scan) force-refreshes up to 20 incomplete entries per click once requests are idle, because normal recursive fetching skips known-version folders even when counts mismatch. Retry performs reads only and never bypasses the move review or completeness gates. Exclusions include links, targets of item links (including links in Trash), descendants of folder-link targets, worn/active items, outfit folders, Marketplace folders, received items, Trash, and saved protected folder descendants. Creator names use the name cache when available and UUIDs otherwise. Inventory remains the authority; there is no new inventory cache.

## Automated regression checks

The small standalone test target exercises the same authorization validator used by the floater, without a simulator or live inventory:

```powershell
cmake -S indra/newview/tests/inventory_cleanup -B build-vc170-64/cleanup-tests -G "Visual Studio 17 2022" -A x64
cmake --build build-vc170-64/cleanup-tests --config Release --target inventory_cleanup_plan_test -- /m:2
ctest --test-dir build-vc170-64/cleanup-tests -C Release --output-on-failure
```

Eight additional loading cases cover idle-but-incomplete folders/items, active requests, unfinished traversal, missing initialization/root, and a valid empty inventory. Authorization checks cover exact identities, empty/duplicate/oversized selections, a missing or changed last item, changed eligibility, identity substitution, new unselected same-name inventory, and the accepted 200-item boundary.

## Runtime verification after linking

Use disposable test inventory for mutation checks; these have not been performed against the user's inventory.

1. Open both floaters at their minimum size and resize. Verify all controls, frozen metadata, full paths, and count labels are readable. Cancel and window-close must send no moves.
2. Scan during loading: actions must remain unavailable. Verify empty scans and multiple pages, clearing selections on page changes.
3. Create a demo folder containing both demo and non-demo named items, plus a subfolder. Select the package row: the folder and all descendants must appear in review. Confirm moves the folder intact, including the non-demo named packaging. Verify unrelated sibling folders stay in place. Add or remove a nested item after opening review: confirmation must reject the stale package. Verify linked/worn/protected descendants exclude the entire package.
4. Compare two same-name items with different creators, same-asset copies with different permissions, and different-asset objects from one creator. Verify grouping and details; do not infer newest means correct.
5. Open review, then rename, move, delete, edit, wear, link, or protect one selected item before confirming. Verify zero moves and a stale-review message. Repeat with the last row in a multi-item review.
6. Add a new similarly named item after review. Verify it is never included. Highlight only one review row: confirmation must still clearly describe and operate on the entire frozen list.
7. Verify saved outfit links, ordinary links, folder links, worn attachments, active gestures, Marketplace and protected descendants are excluded. Confirm protections survive viewer restart.
8. Confirm once and rapidly click again: only one dispatch is allowed. Verify only reviewed roots and their reviewed contents reach Trash. Restore test folders/items manually to their recorded source folders. Never empty Trash as part of this test.

No bulk keeper shortcuts, permanent deletion, broken-link deletion, last-worn history, archive action, or automatic undo are provided.

## Cache completion flag repair

Status: Release build and linking passed; the 20 existing cleanup checks still pass. Restart verification remains pending.

The LLSD inventory cache reader restored full metadata through the base `LLInventoryItem::fromLLSD()` parser but left the viewer-specific completion flag at its constructor default (false). Legacy cache parsing and network unpacking set that flag. This caused tens of thousands of cached records to look unfinished while folder fetching correctly reported complete.

Successfully parsed cache records with a non-null item ID and a known asset type are now marked complete before being returned to the existing skeleton/version validation. Stale parent versions continue to invalidate cached contents as before. Cleanup still requires complete folders/items and performs the same exact-item review validation; it does not mark arbitrary live items complete or remove its completeness checks.

Runtime regression: restart with an existing populated inventory cache, allow normal folder synchronization, and open Cleanup. Cached item metadata should count as complete without clicking Retry for each item. Confirm an actually incomplete/new item remains blocked until fetched, and stale folder versions still fetch normally.

Whole-folder regression coverage adds 11 cases for changed membership/metadata, protected descendants, identity-kind changes, overlap in either selection order, overlapping subtrees, and the 2,000-affected-entry boundary. Whole-folder runtime verification is pending.

UI runtime checks: click each card including its description, tab between cards and activate with Enter, return to All cleanup tools, resize at minimum/default/large dimensions, and verify protection/details toggling and unchanged mandatory review.
