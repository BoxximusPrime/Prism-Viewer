# LLM inventory sorting

Included in Prism Viewer 0.6.0. In-world move verification remains pending.

Select 1–200 items or regular folders in Inventory (list or gallery), right-click **LLM Sort…**,
and choose a root folder if needed. Sorting starts automatically once its categories
are loaded, using the configured translation model. **Sort / retry remaining**
remains available for retries after configuring an unavailable model. The root's direct child
folders are the available categories, excluding folders being sorted. Only selected
item/folder names and category names are sent
to the endpoint/model configured in **Translation settings > OpenAI-compatible**;
chat translation itself does not need to be enabled.
The LLM Sort menu entry is hidden in both list and gallery views unless an
OpenAI-compatible endpoint and model name are configured. This checks settings,
without making a network request when opening the context menu.

The chosen root is remembered for the current viewer session. Reopening LLM Sort
uses it automatically; **Change…** chooses another root. If the remembered folder
is unavailable or falls inside the new selection, the folder picker opens instead.
The choice is cleared when the account changes and is not saved across restarts.
Invoking LLM Sort with a new selection replaces the open review and scrolls to the
top, then automatically requests suggestions for the new selection. Each item
still requires individual approval.

The prompt gives explicit product words priority over brand, style and color
names: “Dead Jeans - Waldon Pond” is Bottoms because it says jeans. It explains
common clothing synonyms, matches the most specific suitable existing category,
and proposes a new category when a recognizable type has no destination. Names
without a recognizable product type remain uncertain. Product context matters:
“jeans texture pack” is textures and “denim jacket” is outerwear.

Each item receives an existing category, a proposed new category, or a request to
choose manually. Change the dropdown to override any suggestion, or choose
**+ New folder…** and edit its name. **Approve** moves that item. **Create & Move**
creates the named folder under the selected root and then moves that item. Other
items suggesting that same category switch to the created folder, but still need
their own approval. **Skip** leaves an item where it is. There is no bulk approval.
Approved items disappear from the review after the move is issued (or when already
in the chosen folder). Failed moves remain visible. The All count decreases while
the reviewed counter preserves progress against the original selection.
Scrolling over a closed destination dropdown scrolls the review without changing
the destination. An open dropdown still allows scrolling through its choices.
Selected folders move as a unit with all contents intact; their contents are not
classified separately. Select a folder or its contents, not both. The chosen root
must be outside every selected folder, and a folder cannot be moved into itself.

The attention filter includes new categories, uncertain names, and failed replies.
Sorting is sequential and can be stopped; retry processes only waiting/failed rows.
Changing the root discards pending suggestions. Closing or replacing the review
cancels model requests. If folder creation is already in flight, the folder may
still be created, but its delayed callback cannot move the old item or alter the
replacement review.

System folders themselves, links, Library items, Trash, outfits, favorites, calling cards folders, Inbox, and
Marketplace trees are excluded. Every move rechecks the account, item ID/name/source,
root path, and destination ID/name/parent. A stale review fails closed. Moves use
the viewer's existing inventory operation and preserve acquisition dates.

Twelve starter clothing icons (tops, bottoms, shoes, dresses, skirts, outerwear,
underwear, socks, hats, glasses, bags, jewelry) share a transparent atlas and native
texture clipping. They illustrate categories, not item thumbnails. Unknown types
use the existing inventory object icon. Categories always come from the user's
folders; icons do not restrict which categories can be suggested.

Validation commands:

```powershell
.\.venv\Scripts\python.exe scripts/tests/test_inventory_llm_sort.py
.\.venv\Scripts\python.exe scripts/tests/test_inventory_llm_sort_moves.py
.\.venv\Scripts\python.exe scripts/tests/test_inventory_llm_sort_wheel.py
.\.venv\Scripts\python.exe scripts/tests/test_inventory_llm_sort_idle.py
# Optional: 16 classification cases against the configured translation endpoint.
.\.venv\Scripts\python.exe scripts/tests/test_inventory_llm_sort.py --probe
cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2
```

`scripts/tests/preview_inventory_llm_sort.py` stages an inert specimen assembled
from the production XUI files. Open `floater_inventory_llm_sort_specimen.xml` in
Debug > XUI Preview Tool at the login screen. Its controls cannot move inventory.
The script also stages `panel_inventory_llm_sort_specimen.xml`, a standalone row
loaded through `LLPanel::buildFromFile`, matching the live review. Always inspect
this row as well: a nested floater preview inherits its parent's layout and can
hide a missing `layout="topleft"` on the row's root panel.
The generation prompt is in `artwork/prism/inventory-sort-icons-prompt.txt`.

Validated on September 16, 2026: Release build succeeded; 64 parser, prompt and
input checks plus 64 inventory eligibility/move-guard checks passed. Four invented
names classified correctly through the configured local model (existing Tops,
existing Bottoms, new Shoes, and an uncertain boxed item). The native XUI specimen
and icon atlas were inspected in the viewer, including clean startup/shutdown.
Live in-world folder creation and item moves have not been exercised; the native
preview is inert, and move-guard tests use an in-memory inventory.
The missing menu entry on clothing folders was reproduced in the running viewer;
folder selection support is included in the rebuilt Release executable. The new
folder checks cover preserved contents, stale sources, protected folders, and
self/descendant destinations.
The standalone row was verified in the native viewer after fixing its missing
top-left layout. The icon, dropdown, new-category editor, reason and action
buttons now remain within the 88-pixel row; the Release resources were rebuilt.

Idle performance: control lookups now run only when review state changes, and
unchanged reshape notifications no longer rebuild the rows. The frame regression
replays the production draw/reshape and recursive lookup functions with 13 rows
and 65,000 hidden inventory entries. Over 120 idle frames, the previous code made
31,201,440 recursive view visits; same-size screen fitting also rebuilt rows 120
times. Both counts are zero after the fix. Real width/height changes, state
changes, completed loading, and loading timeouts still refresh the review. This
checks scheduling and traversal counts, not live in-world rendering FPS.

Prompt revision: all 16 live classification checks passed with the configured
26B local model, including the reported jeans name, unfamiliar brand/color names,
reordered category indices, Feets/Accessories aliases, missing categories, a more
specific Jeans folder, texture-pack context, and names with no product type.
The probe now asserts decisions, destination names/indices and icons instead of
only checking that the model returned parseable JSON.

Session and interaction refinements: Release build succeeded; 22 checks against
the production lifecycle and folder-creation callbacks passed, covering remembered
roots, invalid/deleted roots, account changes, replacing an active review with a
smaller selection, request cancellation, and delayed callbacks. Eight native
combo/container wheel-handler checks passed, including parent scrolling and the
unchanged default behavior of other dropdowns. The 64 inventory guard checks and
idle-performance regression also passed. These use in-memory inventory and UI
stubs; the new interactions still need confirmation in the logged-in viewer.

Automatic submission and approval cleanup: production draw scheduling and row
counts are covered for immediate/deferred submission, one attempt per selection,
loading timeouts without retry loops, and hiding approved rows in both filters.
Cancellation, replacement, and move-guard regressions also pass. The updated
Release build passed; logged-in interaction confirmation is pending.
