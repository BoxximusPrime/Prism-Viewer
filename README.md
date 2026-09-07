# The Prism Viewer

Prism is a customized third-party viewer for [Second Life](https://secondlife.com/),
built from the open-source Linden Lab viewer. It was previously named BoxxyViewer.

See [FEATURES.md](FEATURES.md) for the feature inventory,
[AO transfer](docs/AO-TRANSFER.md) for animation-set import/export, and
[Prism profiles](docs/PRISM-PROFILE.md) for migrating existing preferences.

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
