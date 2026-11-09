<p align="center">
  <img src="launcher/mako_logo.png" alt="Mako" width="420">
</p>

<h1 align="center">MAKO</h1>

<p align="center">
  <b>The Legend of Zelda: Ocarina of Time (Nintendo Switch 2), running natively on PC: tuned for AMD, smooth everywhere.</b><br>
  <a href="#already-playing-update">Update</a> ·
  <a href="#new-player-install">Install</a> ·
  <a href="#the-launcher">Launcher</a> ·
  <a href="#whats-in-mako">What's in Mako</a> ·
  <a href="#known-issues">Known issues</a> ·
  <a href="#credits">Credits</a>
</p>

Mako is a fork of [Hookshot](https://github.com/NotRexed/Hookshot), the static recompilation of Ocarina of Time. It started as
"Hookshot AMD fix (sharkiix version)" and is now its own project: AMD fixes, faster crowded places, its own launcher and builder.

> [!IMPORTANT]
> This repository **does not contain the game, keys or an executable**, and it does not explain how to get them. Mako is built
> **on your PC, from your own copy of the game**. Everything the build makes (`hookshot.exe`, shader caches, saves) stays on
> your PC: never share those files.

---

## Already playing? Update

For players of **Hookshot AMD fix 2.0 / 2.1** who already have the launcher.

1. Open your launcher and press **Update**. It installs a small patch.
2. Start the game. A **Mako** window asks to update: press **Yes**.
3. Your builder downloads Mako and builds your game folder again by itself (around 45 minutes, then a first shader
   preparation). **Your saves and settings are kept.** The old launcher and shortcut are replaced by **Mako**.

Nothing to download by hand. If the builder that made your folder is gone, the window offers this page instead: follow
[New player? Install](#new-player-install) and build into the **same folder** (saves and settings are kept).

## New player? Install

1. Download **`HookshotBuilder.zip`** from the [latest release](https://github.com/Shakoquo/Hookshot/releases/latest) and unzip it
   anywhere (for example in `Documents`).
2. Open the `HookshotBuilder` folder and run **`HookshotBuilder.exe`** (the Mako Builder).
3. Pick your game file (the builder lists the `.nup` files it finds; or **Browse…**), choose where the game goes and its language.
4. Press **Build the game**: around 45 minutes, depending on your CPU. You can use your PC meanwhile.
5. Start the game from the **Mako** shortcut on your desktop.

**What you need**
- Your copy of the game at the supported version: program `0400486024DEC000`, update v131072, build `e0f3ccfa`.
- Windows 10 or 11 (64-bit), a CPU with AVX2, 16 GB of RAM, about 60 GB free while building.
- A graphics card with Vulkan 1.3 and mesh shaders and an up-to-date driver: AMD Radeon RX 6000 or newer, NVIDIA RTX 20 or newer,
  Intel Arc. 8 GB of video memory recommended.
- If the builder says the Windows SDK is missing: install **Visual Studio Build Tools** with "Desktop development with C++".

## The launcher

<p align="center"><img src="launcher/mako_logo.png" alt="" width="120"></p>

The **Mako** shortcut opens the launcher:
- **Play**, and **Update** when a new version is out (graphics fixes install in seconds; bigger updates rebuild the game by themselves).
- **Graphics**: quality preset, output resolution (2048x1152, 2560x1440, 3840x2160), 3D resolution, upscaling, sharpness,
  frame generation, frame pacing, window or full screen, FPS counter.
- **Game**: language and game options. **AMD fixes**: switches for AMD-specific problems.
- **Randomizer**: the settings of a randomizer seed (chests, Gold Skulltulas, quest rewards, songs, Heart Pieces, shops,
  Deku Scrubs, dungeon rewards and keys) and **New seed**. They are also on the **Randomizer** tab of the game's menu
  (<kbd>Insert</kbd>), which shows the seed's ID to share it. **Settings only for now**: nothing places the items yet, so a
  seed still plays as the game shipped.
- **Saves**, **Import saves** (from Eden, Lichii, Ryujinx, a Switch or another Hookshot) and **Game folder**.

## What's in Mako

- **AMD fixes**: shaders that failed to translate on AMD now do; no white grass blades or flowers in Hyrule Field; trees keep
  their leaves up close; NaN guard against flashing/black pixels.
- **Castle Town without the big stutters**: memory imports no longer stall the game in crowded places.
- **Up to date with Hookshot**: the latest upstream work (draw setup cache, render thread on its own core, texture fixes...).
- **Frame generation 2x and frame pacing** on by default (<kbd>Insert</kbd> in game to change them).
- **SAVE FOLDER**: drop a save in the `SAVE FOLDER` beside the game and start it: it is imported, older saves are backed up.
- **The Mako launcher and builder**: one-click updates, resolution settings, a new look.

## Known issues

- Some trees (mostly firs, for example near the Temple of Time) can lose their leaves when you get close.
- The first time a new effect appears, the game can pause for a moment while it is prepared; it does not happen again.
- Report problems with your `hookshot_log.txt` (in the game folder) on the [issues page](https://github.com/Shakoquo/Hookshot/issues).

## Build from source

Mako builds like Hookshot: see the original guide in [docs/hookshot-readme.md](docs/hookshot-readme.md#build-from-source). The
launcher is `launcher/` (`build.ps1`), the builder app `builder/HookshotBuilder`.

## Credits

- **sharkiix**: Mako, the AMD fixes, the launcher and builder.
- **NotRexed** and everyone credited in [Hookshot's readme](docs/hookshot-readme.md#credits): Hookshot itself, which Mako is built on.
- **Eden**, **Eglantine**, **suyu**, **EvilBoyce / EvilOOT**, **Lichii**, **Mesa** and the other projects listed there.

## License

Mako, like Hookshot, is free software under the [GNU General Public License, version 3 or later](LICENSE). Mako is an unofficial
fan project, not affiliated with or endorsed by Nintendo. The Legend of Zelda and Ocarina of Time are trademarks of Nintendo.
