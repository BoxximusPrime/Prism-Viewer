# Prism profile and naming

The Prism Viewer uses the **Prism Release** channel and its own **Prism** profile.
On Windows, preferences live in `%APPDATA%\Prism`; cache data uses
`%LOCALAPPDATA%\Prism`. The Windows package and shortcut are **Prism Viewer**.
The development target remains `secondlife-bin`.

The installer registers Prism separately and uninstalling it preserves user data.
Second Life remains the platform name, including its URLs and protocol handlers.
Linden Lab copyright notices and upstream attribution remain in place.

## Importing preferences from the previous Boxxy build

Close the viewer, then run `python scripts/import_prism_preferences.py` on Windows.
The importer copies selected global preferences, colors, keyboard bindings,
account preferences and toolbar layouts from the old `SecondLife` profile.
It never overwrites existing Prism files or modifies the source profile.
Use `--source` and `--destination` to select other profile directories.

Stored profile/cache paths are reset so Prism creates its own directories.
Sign in again after importing: passwords, browser sessions, caches and chat
transcripts are not copied. Old chat history remains in the original profile.

New AO inventories use `#Prism/#AO`. An existing `#Boxxy/#AO` is reused when
there is no `#Prism` folder; when both exist, `#Prism` takes priority. Saved
`Boxxy…` setting names and internal UI identifiers remain stable for compatibility.
