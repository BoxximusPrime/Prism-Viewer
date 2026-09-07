# AO transfer with Firestorm

Prism and Firestorm use the same account's Second Life inventory. Transferring an
AO creates new folders and links to the animations already in that inventory.
It does not download animation files, enable the AO, replace an existing set, or
make animations available to a different account.

## Bring a Firestorm set into Prism

1. Open the Prism Animation Overrider and click **Import from Inventory**.
2. Expand `#Firestorm` → `#AO` in Inventory.
3. Drag **one set folder** from inside `#AO` into the Prism AO window.
4. Wait for the import result. Select the new set in Prism, then click **Activate**
   and enable the AO when ready.

The copy appears under `#Prism/#AO` (or your existing `#Boxxy/#AO`). A name suffix prevents replacing an existing
set. Animation order, timed cycling, random order, cycle intervals and the
supported sit-override setting are retained. The source set is not edited.

Firestorm's smart-sit and disable-stands-in-mouselook options are not implemented
by Prism; an import using those options asks whether to continue without them.
Newer simultaneous animation groups, independent tracks, and the `Always` state
are rejected before creating a set, rather than being flattened or omitted.

## Send a Prism set to Firestorm

Select the set and click **Export to Firestorm**. A new set is created under
`#Firestorm/#AO` with its animation links and supported options. Open Firestorm
and select that set. If Firestorm is already open, use its AO reload control.
The existing Firestorm default set is not changed.

## Notecard interchange

Prism imports the standard ZHAO-II syntax and Firestorm's Oracul state aliases:

```text
[ Standing ]First Stand|Second Stand
[ Walking ]My Walk
[ Sitting On Ground ]My Ground Sit
```

Keep the notecard and its animations (or animation links) together in one
Inventory folder, then drop the notecard into the Prism AO window. The notecard
must be readable/copyable. Names match exactly, including case. Missing or
ambiguous animation names stop the import without creating a partial set.

**Export Notecard** creates a new Inventory folder containing a ZHAO-II notecard
and links to the selected set's animations. That folder can be used for import
in either viewer. The standard notecard transfers state assignments and their
order; set cycling, randomization and sit options in the receiving AO, or use
the direct Firestorm export to retain them.

Names containing commas, pipes, line breaks or unrepresentable line lengths
cannot be exported as ZHAO-II; use direct Firestorm export for those sets.
Animation groups separated by commas are not treated as alternate animations.

## Validation and failures

Transfers wait for required inventory records and stop with a clear error if
they cannot finish. A network failure after writing begins may leave a partial
destination folder, which the error opens for inspection. The source stays in
place. Retry the transfer after resolving the connection issue.

The text-format tests use the production parser and cover all 25 supported
states, Oracul aliases, repeated state lines, Unicode names, ordering, invalid
input, simultaneous groups, and size limits. Compile and run them with:

```text
g++ -std=c++17 -Wall -Wextra -Werror -Iindra/newview indra/newview/llboxxyaonotecard.cpp indra/newview/tests/llboxxyaonotecard_test.cpp -o ao_notecard_test
```

Compatibility is based on Firestorm's public
[AO engine](https://github.com/FirestormViewer/phoenix-firestorm/blob/master/indra/newview/aoengine.cpp)
and [state-name definitions](https://github.com/FirestormViewer/phoenix-firestorm/blob/master/indra/newview/aoset.cpp).
Live inventory transfer still needs verification in both viewers before release.
