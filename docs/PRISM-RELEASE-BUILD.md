# Windows release builds

The current release is **Prism Viewer 0.3.0**, built as **Prism Release** from
the `v0.3.0` source tag. The Windows installer follows the filename pattern
`Prism_0_3_0_<revision>_x86_64_Setup.exe`. See [0.3.0 release notes](releases/0.3.0.md).
Release packaging verification checks the executable version, staged payload,
and SHA-256 identity of `PrismViewer.exe` and `secondlife-bin.exe`.

## Initial test release history

The first friends-and-family installer is `Prism_26_4_0_54483_x86_64_Setup.exe`, built from the current working tree as **Prism Release**, version **26.4.0.54483**. This is an unsigned test build; installation and uninstall testing are pending.

The installer is in `build-vc170-64/newview/Release/`. It installs `PrismViewer.exe` into the `PrismViewer` directory under Program Files and creates Prism Viewer shortcuts. Preferences remain in the separate `%APPDATA%/Prism` profile. Uninstall preserves that profile. Installing registers Prism to open Second Life location links.

The updated test build defaults to translation off, gesture sounds on, and sending look targets off. All 30 toolbar buttons are included for new account layouts. Name tags use `#2C7B20` within 20 m, `#862B10` from 20–100 m, and gray beyond 100 m. DM floaters default to 540×480. The window title changes from `Prism` to `Prism - <account name>` after login.

Reinstalling does not reset saved preferences, UI colors, toolbar layouts, or floater sizes. Test first-run defaults with a new profile, or back up the existing Prism profile before resetting it. Use the toolbar reset action to restore the shipped button layout in an existing profile.

The latest layout fixes give each DM popout its own size instead of inheriting the Conversations container's dimensions. Minimal radar restores its saved bottom-left position independently of its changing list height, and Now Playing uses a rounded border. The Prism preferences page includes an “Enable colors” checkbox for nameplate chat-range colors, enabled by default.

## Build

From the repository root in PowerShell, with the existing configured build directory and dependencies:

```powershell
$env:CL_MPCount = '2'
cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2
cmake --build build-vc170-64 --config Release --target llpackage -- /m:2
Push-Location build-vc170-64/newview/Release
& ../../tools/nsis-3.11/makensis.exe /V3 secondlife_setup_tmp.nsi
Pop-Location
```

The packaging target stages the payload and generates the NSIS script; the final `makensis` command produces the installer. The portable NSIS 3.11 tool was verified against the SHA-256 in the official NSIS release metadata before use. A different local NSIS installation can supply `makensis.exe`.

The canonical development executable remains `build-vc170-64/newview/Release/secondlife-bin.exe`. The packaged `PrismViewer.exe` must have the same SHA-256 as that executable.

## Initial install check

Install, launch from the new shortcut, sign in, and check graphics, voice/media and AO behavior. Check that a subsequent install updates Prism and that uninstall removes its program files while retaining the Prism profile. Existing viewers should retain their own installations.

For the layout regression check, open a new DM and detach it (540×480 UI units), resize it, then dock and detach it again; the resized dimensions should return. Move minimal radar, restart, and confirm its bottom-left anchor stays in place even if the avatar count changes. Play parcel music and inspect the rounded card border. Toggle nameplate “Enable colors” off and on; the range indicators should disappear and reappear without a restart.
