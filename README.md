![Prism Viewer login screen](https://i.imgur.com/ciiW5yZ.jpeg)

# The Prism Viewer

Prism is a customized third-party viewer for [Second Life](https://secondlife.com/),
built from the open-source Linden Lab viewer. It was previously named BoxxyViewer.

Prism brings a refreshed interface, built-in avatar tools, and expanded chat,
inventory, and rendering features to everyday Second Life use.

## Highlights

- **A refreshed look:** emerald accents, a crystal-themed login screen, frosted-glass
  panels, and redesigned chat and messaging windows.
- **Built-in animation override:** inventory-backed animation sets with import and
  export support for Firestorm folders and popular AO notecard formats.
- **Radar and avatar tools:** nearby-avatar radar, friend and VIP highlighting,
  attachment inspection, and posing tools.
- **Chat across languages:** automatic nearby-chat and IM translation, multiple
  translation providers, and conversation-specific language choices.
- **Inventory and outfit tools:** expanded search, easier outfit editing, and
  inventory cleanup with a review step before moving items to Trash.
- **Rendering improvements:** order-independent transparency for overlapping
  transparent surfaces, experimental skin scattering, and asset-loading fixes.

Prism is under active development; some features are still being tested in-world.
The feature inventory tracks their current status.

See [FEATURES.md](FEATURES.md) for the feature inventory,
[AO transfer](docs/AO-TRANSFER.md) for animation-set import/export, and
[Prism profiles](docs/PRISM-PROFILE.md) for migrating existing preferences.

## AI disclaimer

Prism is a personal experiment made entirely through AI. This refers to the
Prism-specific changes built on top of Linden Lab's open-source Second Life viewer,
not the upstream codebase. It is an experimental project, and bugs and rough edges
are to be expected.

## Windows development build

```powershell
cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2
```

The development executable is `build-vc170-64/newview/Release/secondlife-bin.exe`.
New CMake configurations default to the `Prism Release` channel; existing build
folders should be configured with `-DVIEWER_CHANNEL="Prism Release"`.

## Upstream and licensing

Prism retains the upstream LGPL license and copyright notices. See [LICENSE](LICENSE)
and the [Second Life Open Source Portal](https://wiki.secondlife.com/wiki/Open_Source_Portal)
for upstream history and build prerequisites. Prism is an independent viewer;
Linden Lab's official viewer downloads and support apply to their own product.
