# Portable Hookshot Builder on Windows

The Builder has no window: players use the [Hookshot Launcher](https://hookshot.magicbean.dev/download), whose
[portable zip](https://hookshot.magicbean.dev/download/launcher/windows-portable) keeps its data beside it. This page
is for the Builder's command line (`--cli`, as RecompLauncher runs it) kept on an external SSD.

Unpack the whole release zip into a writable folder on your SSD, then run its `HookshotBuilder.exe` setup with
`--portable` before `--cli` and make_game.py's options, for example:

```powershell
.\HookshotBuilder.exe --portable --cli --nup "E:\your-game.nup"
```

The setup creates a marked `HookshotBuilder-data` data folder beside itself. Keep this folder: it contains the
installed Builder, its build tools, SDK downloads you opt into, and the default build files. The zip's own
`HookshotBuilder` folder beside the setup is what the setup installs from; it is never the data folder, and a setup
that finds a portable marker in it stops (unpack the zip into a new folder). The normal setup continues to use
`%LOCALAPPDATA%\HookshotBuilder`; portable mode does not import that installation.

With `--prepare`, the default game folder is `Hookshot` beside the data folder. You can move their containing folder or
change that volume's drive letter: the setup finds its marked data folder beside it again on later `--cli` runs without
the flag, and the installed Builder finds its marked home when it is started directly. No user/system environment
variables or registry configuration are installed. Windows, .NET and third-party tools can still create their own
temporary files and operating-system caches; this is not a zero-write or sandbox mode.

Do not remove `.hookshot-portable` from the data folder. An invalid marker stops the setup rather than silently using
another Builder. The game is played with its own launcher (`hookshot.exe` in the game folder), which needs no Builder.
An interrupted installation keeps staged files separate from the published version. During portable updates, unchanged
parts are copied instead of moved out of the installed Builder, so enough free space for both versions is needed. If
Windows blocks restoration after a failed rename, the preserved old directory remains beside it as
`<version>.rollback-*`; close programs using these folders before recovering it.

For scripted child processes the setup supplies an absolute `HOOKSHOT_SETUP_BASE` and
`HOOKSHOT_BUILDER_PORTABLE=1` to that process tree only. A portable root must have the valid marker, be a dedicated
ordinary drive/UNC directory and fit the native setup's Windows path limits. Do not use the current directory, device
namespace paths or a volume root as a substitute. Portable support described here is Windows-only.

Never share a built game folder, extracted files, saves, caches or downloaded SDK packages. The contribution rules
in [CONTRIBUTING](../CONTRIBUTING.md) apply equally to portable installations.
