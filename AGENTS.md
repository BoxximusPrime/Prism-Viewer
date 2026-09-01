# Codex build convention

- Build the viewer with the `Release` configuration unless the user explicitly requests another configuration.
- Use: `cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2`
- The canonical executable is `E:\BoxxyViewer\build-vc170-64\newview\Release\secondlife-bin.exe`.
- When reporting a completed build, link to that executable and do not direct the user to another configuration directory.
