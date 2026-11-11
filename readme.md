<p align="center">
  <img src="launcher/mako_logo.png" alt="Mako" width="420">
</p>

<h1 align="center">MAKO</h1>

<p align="center">
  <b>The Legend of Zelda: Ocarina of Time (Nintendo Switch 2), running natively on PC: tuned for AMD, smooth everywhere.</b><br>
  <a href="#already-playing-update">Update</a> ·
  <a href="#new-player-install">Install</a> ·
  <a href="#the-launcher">Launcher</a> ·
  <a href="#amd-fsr-4">AMD FSR 4</a> ·
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

For players who already have the **Mako launcher**.

1. Open the launcher and press **Update**.
2. Small graphics fixes install in seconds. Bigger updates (like **3.3**) download the new builder and **build your game folder
   again by itself** (around 25-45 minutes, then a first shader preparation). **Your saves and settings are kept.**

Still on **Hookshot AMD fix 2.x**? Follow [New player? Install](#new-player-install) and build into the **same folder**.

> [!NOTE]
> **Controller not working after updating to 3.3?** The first 3.3 package was missing `SDL2.dll` (DualSense, Switch Pro and
> other non-Xbox controllers). Download **`SDL2.dll`** from the [3.3 release](https://github.com/Shakoquo/Mako/releases/tag/mako-3.3)
> and put it in your game folder, next to `hookshot.exe`. No rebuild needed.

## New player? Install

1. Download **`MakoBuilder.zip`** from the [latest release](https://github.com/Shakoquo/Mako/releases/latest) and unzip it
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
- **Graphics**: quality preset, output resolution (1280x720 up to 3840x2160), 3D resolution, upscaler (AMD FSR 3.1 / FSR 4),
  sharpness, frame generation, frame pacing, VSync, frame rate cap, Anti-Lag 2, window or full screen.
- **Game**: language and game options. **AMD fixes**: switches for AMD-specific problems.
- **Randomizer**: the settings of a randomizer seed (chests, Gold Skulltulas, quest rewards, songs, Heart Pieces, shops,
  Deku Scrubs, dungeon rewards and keys) and **New seed**. They are also on the **Randomizer** tab of the game's menu
  (<kbd>Insert</kbd>), which shows the seed's ID to share it. **Chests work**: **Play** shuffles them as a mod, and
  with **Major items** on the big items too, placed so the game can be finished by rules written from the original game
  and not yet checked against the remake ([tools/rando](tools/rando/README.md)). It needs Python 3 with `zstandard`,
  and a game built from this source. The other settings are not placed yet.
- **Saves**, **Import saves** (from Eden, Lichii, Ryujinx, a Switch or another Hookshot) and **Game folder**.

## AMD FSR 4

- **AMD FSR 3.1** is built into the game: it works on almost every graphics card, **nothing to download**.
  <kbd>Insert</kbd> in game → **Upscaler** → **AMD FSR 3.1**.
- **AMD FSR 4** only runs on **Radeon RX 9000** cards, and needs two files from AMD that Mako cannot ship (AMD's signed files):
  1. Download AMD's [FidelityFX SDK](https://github.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK) (release **v2.4.0**).
  2. In it, open `Kits/FidelityFX/signedbin`.
  3. Copy **`amd_fidelityfx_loader_vk.dll`** and **`amd_fidelityfx_upscaler_vk.dll`** into your game folder, next to `hookshot.exe`.
  4. Start the game: <kbd>Insert</kbd> → **Upscaler** → **AMD FSR 4**.

  The <kbd>Insert</kbd> menu only lists FSR 4 when it can run (an RX 9000 card **and** both files). The launcher always lists it.

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
- Report problems with your `hookshot_log.txt` (in the game folder) on the [issues page](https://github.com/Shakoquo/Mako/issues).

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
