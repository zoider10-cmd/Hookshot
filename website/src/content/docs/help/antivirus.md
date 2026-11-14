---
title: Antivirus warnings
description: Why Windows Defender and browsers flag Hookshot, how to check your download is genuine, and how to fix it on Windows.
---

Hookshot's Windows programs (the launcher, the builder, and the game it builds) are new and **not code-signed yet**:
the signing certificate is still being applied for. Windows Defender and browsers judge unsigned programs nobody has
seen before by guesswork, so they often flag Hookshot, most often as **`Trojan:Win32/Wacatac.H!ml`** or
**`Wacatac.B!ml`**. The `!ml` at the end means Defender's machine learning guessed: it is not a known virus.

That doesn't mean you should trust any file with Hookshot's name. First check that yours is genuine, then let it through.

## 1. Check that your download is genuine

Only download Hookshot from its two release pages on git.magicbean.dev:

- [The Hookshot Launcher's releases](https://git.magicbean.dev/MagicBeanDev/HookshotLauncher/releases)
- [Hookshot's releases](https://git.magicbean.dev/MagicBeanDev/Hookshot/releases)

The [download page](/download) and its links send you to the first of these.

A copy from anywhere else may not be ours. To check a file you downloaded, compare its SHA-256 with the one the release
lists in its `SHA256SUMS` file. In PowerShell, in the folder you downloaded it to:

```powershell
Get-FileHash .\HookshotLauncher-*-windows-x64-setup.exe
```

The `Hash` it prints must be the same as the file's line in `SHA256SUMS`. You only need to do this for the launcher:
it checks the signature of every release's `SHA256SUMS`, and every file it downloads against it, by itself.

## 2. Let it through on Windows

Where the warning appears decides what to do.

### The browser blocks the download

- **Chrome:** open your downloads (<kbd>Ctrl</kbd>+<kbd>J</kbd>), find the file, and choose **Keep** (Chrome may call it
  **Download suspicious file**).
- **Edge:** open your downloads (<kbd>Ctrl</kbd>+<kbd>J</kbd>), point at the file, choose **…** then **Keep**, then
  **Show more** and **Keep anyway**.
- **Firefox:** open your downloads (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Y</kbd>), right-click the file and choose
  **Allow download**.

### "Windows protected your PC" when you start it

This is SmartScreen. Choose **More info**, then **Run anyway**.

### Defender removed a file

This shows as a Defender notification, as the launcher saying **"Your antivirus removed part of the build tools"**, or
as a file that is suddenly missing (`hookshot.exe`, or the launcher itself). Put it back, then stop it happening again:

1. Open **Windows Security** (search for it in the Start menu), then **Virus & threat protection**.
2. Choose **Protection history**. Open the most recent entry that names Hookshot or one of its folders (usually a
   `Wacatac` detection), choose **Actions**, then **Restore**. Do this for each Hookshot entry.
3. Back on **Virus & threat protection**, under **Virus & threat protection settings**, choose **Manage settings**.
4. Scroll to **Exclusions**, choose **Add or remove exclusions**, then **Add an exclusion** → **Folder**, and add these
   folders, one at a time:
   - `%LOCALAPPDATA%\HookshotLauncher`: the launcher's data, with each version's builder and build tools (in
     `toolchains`) and the build files. The portable launcher keeps it in `HookshotLauncher-data` beside
     `HookshotLauncher.exe` instead: add that folder.
   - `%LOCALAPPDATA%\Programs\HookshotLauncher`: the installed launcher itself.
   - Your game folder: `%USERPROFILE%\Games\Hookshot` unless you chose another.

   You can type the `%...%` paths straight into the folder picker's address bar.
5. In the launcher, build again. If a file is still missing, delete that version's folder in
   `%LOCALAPPDATA%\HookshotLauncher\toolchains` (named after the version, such as `v3.0.0`): the next build downloads
   it again and checks it.

Or do steps 3 and 4 in one go, in PowerShell started with **Run as administrator**:

```powershell
Add-MpPreference -ExclusionPath "$env:LOCALAPPDATA\HookshotLauncher"
Add-MpPreference -ExclusionPath "$env:LOCALAPPDATA\Programs\HookshotLauncher"
Add-MpPreference -ExclusionPath "$env:USERPROFILE\Games\Hookshot"
```

:::caution
Exclude only these folders. Don't exclude a whole drive or your Downloads folder, and don't turn off real-time
protection: they protect you from everything else.
:::

### Another antivirus (Avast, AVG, Norton, Bitdefender, Kaspersky, ...)

The steps are the same, with that program's names for them: restore the files from its quarantine (sometimes called the
"vault" or "chest"), then add `%LOCALAPPDATA%\HookshotLauncher`, `%LOCALAPPDATA%\Programs\HookshotLauncher` and your
game folder as **exceptions** (or "exclusions"). Then build again in the launcher.

## 3. Help get it fixed

Every report of a false positive teaches Microsoft that Hookshot is safe, for everyone. Send the flagged file to
[Microsoft's file submission](https://www.microsoft.com/wdsi/filesubmission): choose **Home customer**, then
**Incorrectly detected as malware/malicious**, and give the detection name (such as `Wacatac.H!ml`).

## Still stuck?

[Search the reports](/progress/#problem-search?q=antivirus) or [ask on Discord](https://discord.gg/magicbean). To
report a new problem, include the file's name and version, where you downloaded it from, and the exact detection name.
Never send game files or keys.
