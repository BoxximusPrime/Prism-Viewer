# Codex build convention

- Build the viewer with the `Release` configuration unless the user explicitly requests another configuration.
- Use: `cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2`
- The canonical executable is `E:\BoxxyViewer\build-vc170-64\newview\Release\secondlife-bin.exe`.
- When reporting a completed build, link to that executable and do not direct the user to another configuration directory.

## Feature inventory

- Keep `FEATURES.md` up to date. When adding or substantially changing a major user-facing viewer feature, update the relevant section with a concise bullet as part of the same change.
- Mark work as in progress when it is not yet committed or confirmed complete.
