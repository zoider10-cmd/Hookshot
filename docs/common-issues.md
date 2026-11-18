# Help

Find what you see below and follow its steps: each fix comes from the [manual](../README.md#if-something-goes-wrong),
with the exact message, file or setting to look for. Nothing fits, or the fix didn't work? [Still stuck?](#still-stuck)
says where the log is and how to ask.

- [Installing and building](#installing-and-building)
- [Starting the game](#starting-the-game)
- [In game: graphics](#in-game-graphics)
- [In game: performance and freezes](#in-game-performance-and-freezes)
- [In game: controls, saves and language](#in-game-controls-saves-and-language)
- [Downloads and antivirus](#downloads-and-antivirus)
- [Still stuck?](#still-stuck)

## Installing and building

### The launcher says "This version isn't supported"

Or: "Hookshot supports build e0f3ccfa". Hookshot builds from one version of the game only.

1. **Check the version.** You need program `0400486024DEC000` with update **v131072** (build `e0f3ccfa`); see
   [what you need](../README.md#what-you-need). The game without its update, or with another one, won't build.
2. **Check the files you chose.** Use a `.nup` file, or the `romfs` and `exefs` folders. The launcher looks for `.nup`
   files in your Downloads, Desktop and Documents folders; if the right one isn't listed, point it at the file.

[Search version reports](https://hookshot.magicbean.dev/progress/#problem-search?q=version)

### "Your antivirus removed part of the build tools"

A false alarm on unsigned programs: Hookshot isn't code-signed yet.

1. **Get the files back.** Restore them from Windows Security's **Protection history**, and add the launcher's folders
   to its exclusions: `%LOCALAPPDATA%\HookshotLauncher` (its data: each version's builder and build tools, in
   `toolchains`, and the build files) and `%LOCALAPPDATA%\Programs\HookshotLauncher` (the launcher itself). The portable
   launcher keeps its data in `HookshotLauncher-data` beside `HookshotLauncher.exe` instead.
2. **Build again.** If a file is still missing, delete that version's folder in
   `%LOCALAPPDATA%\HookshotLauncher\toolchains` (it is named after the version, such as `v3.0.0`): the next build
   downloads it again and checks it.

The [antivirus guide](https://hookshot.magicbean.dev/help/antivirus/) shows each step, and how to check first that the
download is genuine.

[Search antivirus reports](https://hookshot.magicbean.dev/progress/#problem-search?q=antivirus)

### The build is very slow, or runs out of space

1. **Expect about 15 minutes on a 12-core desktop, and longer on a slower PC.** Most of the time is compiling and
   preparing shaders, which use every CPU thread, so a 6-core PC can take twice as long or more (an estimate, not a
   measurement). A hard drive works, but builds are much slower than on an SSD.
2. **Free about 60 GB** before building. The build's own files (about 4 GB) are deleted once the game is ready.

[Search build reports](https://hookshot.magicbean.dev/progress/#problem-search?q=build)

### Linux: the launcher or the build won't start

1. **Let the launcher run as a program.** In your file manager, open its **Properties** and turn on "Allow executing
   file as program", or run `chmod +x HookshotLauncher-*-x86_64.AppImage`.
2. **Check your system.** Linux needs glibc 2.35 or newer (Ubuntu 22.04, Debian 12 or newer). A CPU without AVX2
   builds and plays too: the game and its renderer are built for your processor.

[Search Linux reports](https://hookshot.magicbean.dev/progress/#problem-search?q=linux)

## Starting the game

### The game opens and closes, shows a black screen, or the log says "device lost"

1. **Update your graphics driver.** On Linux, update Mesa or the NVIDIA driver.
2. **Check your graphics card.** Hookshot needs **Vulkan 1.3**; see [what you need](../README.md#what-you-need). A
   driver update can't add it to an older card that doesn't have it.
3. **AMD cards** have known crashes ([#708](https://github.com/NotRexed/Hookshot/issues/708),
   [#614](https://github.com/NotRexed/Hookshot/issues/614)). To try the other drawing path, add the line
   `RX_VK_MESH_SHADERS=compute` to `hookshot_env.txt` in the game folder (usually a little slower; delete the line to
   undo it).
4. **Read the end of the log.** `hookshot_log.txt` in the game folder's `logs` folder has the last run; its last lines usually say what
   failed.

[Search crash reports](https://hookshot.magicbean.dev/progress/#problem-search?q=crash) · [Search black-screen reports](https://hookshot.magicbean.dev/progress/#problem-search?q=black+screen)

### Linux: the game doesn't start, or the picture is broken

1. **Check Vulkan and mesh shaders.** `vulkaninfo | grep mesh` should list `VK_EXT_mesh_shader`. The game needs a
   Vulkan 1.3 driver, ideally with mesh shaders.
2. **Update Mesa or the NVIDIA driver** if it doesn't.

[Search Linux reports](https://hookshot.magicbean.dev/progress/#problem-search?q=linux)

### Linux: Play closed before the game's log appeared

Wait for the game to exit, then open `hookshot_startup.log` in the game folder's `logs` folder: it has up to 64 KiB of the game's
startup errors and its exit status. Started from a terminal, the game prints there instead.

[Search startup reports](https://hookshot.magicbean.dev/progress/#problem-search?q=startup)

## In game: graphics

### Parts of the picture are missing, or a message says your card has no mesh shader support

Without mesh shaders, Hookshot draws through its compute fallback, which leaves some draws out
([#640](https://github.com/NotRexed/Hookshot/issues/640)).

1. **Update your graphics driver:** a card and driver with mesh shaders draw everything. NVIDIA RTX 20 series and
   newer, AMD RX 6000 series and newer, and Intel Arc have them.
2. **Check your card** against [what you need](../README.md#what-you-need).

[Search graphics reports](https://hookshot.magicbean.dev/progress/#problem-search?q=graphics)

### One place has a wrong texture, or a floor or wall is missing

1. **Look for `hookshot_damaged_files.txt`** in the game folder. The build writes it when your dump of the game is
   incomplete (about 23.3 GB instead of 23.8 GB), listing each damaged file and what was put in its place.
2. **Dump the game again** and build from the new dump. The file is removed once the dump is whole.

[Search texture reports](https://hookshot.magicbean.dev/progress/#problem-search?q=texture)

### AMD: blocky textures, solid rectangles in the sky, or dark courtyard surfaces

1. **Turn on ASTC as RGBA8:** open the menu (<kbd>F1</kbd>), go to the **Debug** tab, and under **Developer** turn on
   **ASTC as RGBA8**. Restart the game.
2. **Watch the memory.** It can use much more graphics memory, and stalls when the card runs out. To undo it, turn the
   row off and restart.

If the row can't be changed, `hookshot_env.txt` sets it: remove its `RX_VK_ASTC_RGBA8=1` line. The
[AMD texture workaround](../README.md#amd-texture-workaround) has the details.

[Search AMD reports](https://hookshot.magicbean.dev/progress/#problem-search?q=amd)

## In game: performance and freezes

### It stutters the first time you see something

Normal for now: the game prepares each new shader the first time it needs it, and it is smooth the next time you pass.
You can help remove it for everyone: [send your pipeline list](../README.md#send-your-pipeline-list) (**Debug → Save my
pipeline list** in the menu).

[Search stutter reports](https://hookshot.magicbean.dev/progress/#problem-search?q=stutter)

### Windows, NVIDIA: it stutters on every start, in places you have seen

The driver's shader cache is too small to keep them all (the first start builds about 2 GB). Open the **NVIDIA Control
Panel**, then **Manage 3D settings**, and set **Shader Cache Size** to **Unlimited** (or 10 GB). On Linux the game raises
the driver's limit itself.

[Search stutter reports](https://hookshot.magicbean.dev/progress/#problem-search?q=stutter)

### Low FPS, or it slows down after a while

1. **Match the preset to your card.** In the menu's **Graphics** tab, pick the **Quality preset** for your graphics
   memory: Minimum (4GB), Low (6GB), Balanced (8GB) and so on. If the log says
   `vk: over the driver's video-memory allowance`, choose a lower one: its smaller render resolution needs less video
   memory. How much the textures may use comes from the card and is not a setting.
2. **Walk through the same spot twice** once the shaders are prepared. Note whether the slowdown clears the second time,
   or lasts until you restart.
3. **Compare fairly.** Turn off **Frame generation**, so the FPS counts the game's own frames, and keep the resolution,
   upscaler and frame rate cap the same between runs.
4. **Keep the log from the slow run** (and from the earlier version, after an update), and say where the FPS dropped.
   The [low FPS checklist](../README.md#low-fps-or-stutter) lists the log lines that matter, and a switch that times
   each GPU pass.

[Search performance reports](https://hookshot.magicbean.dev/progress/#problem-search?q=performance)

### Steam Deck: the game freezes and closes in the starting area or first dungeon

`journalctl -k` shows `gfx_0.0.0 timeout`. Add the line `RX_VK_MESH_NOCULL=2c56dc1006942f74` to `hookshot_env.txt` in
the game folder: it turns off the culling pass that runs for seconds there, and every model is still drawn
([#817](https://github.com/NotRexed/Hookshot/issues/817)).

[Search Steam Deck reports](https://hookshot.magicbean.dev/progress/#problem-search?q=steam+deck)

## In game: controls, saves and language

### The menu won't open

Press <kbd>F1</kbd>: it always works. <kbd>Insert</kbd> and <kbd>Esc</kbd> do too, unless **Controls → Menu shortcut**
was changed. On a controller, press Home, or Select and Start together; on a DualShock 4 or DualSense, click the
touchpad.

[Search menu reports](https://hookshot.magicbean.dev/progress/#problem-search?q=menu)

### A and B are swapped, or a button does the wrong thing

1. **Check the layout.** In the menu, open **Controls → Controls** and check **Layout preset**: the default layout has A on the
   right face button, Xbox / PC and Swap Face put it on the bottom one.
2. **Rebind a button** on that page: choose its row and the Gamepad or Keyboard column, press <kbd>Enter</kbd>, then the
   new button. <kbd>Esc</kbd> cancels, <kbd>Delete</kbd> clears it, and **Reset to defaults** puts them all back.
3. **Wrong icons?** **Button prompts** on the same page picks the icons the game shows. It doesn't change what a button
   does.

The [controls reference](../README.md#controls) covers the keyboard, the mouse and rumble.

[Search controller reports](https://hookshot.magicbean.dev/progress/#problem-search?q=controller)

### A save is missing, or a save transfer or update went wrong

1. **Close the game** and stop copying, so nothing else is overwritten.
2. **Copy the save folder somewhere safe:** `user` in the game folder on Windows, `~/.local/share/hookshot` on Linux.
3. **Put the backup back.** Every copy the launcher makes backs up the save it replaces first:
   [undo a copy](saves.md#undo-a-copy) shows where. An update keeps your saves; the
   [updates guide](updates-and-saves.md) says what else it keeps.

Keep save files private: don't post them.

[Search save reports](https://hookshot.magicbean.dev/progress/#problem-search?q=save)

### The game is in the wrong language

Change the code in `language.txt` in the game folder: the file lists them all, and an update keeps the one you set.

[Search language reports](https://hookshot.magicbean.dev/progress/#problem-search?q=language)

## Downloads and antivirus

### Windows Defender or the browser flags the download

Hookshot isn't code-signed yet, so Defender often guesses `Trojan:Win32/Wacatac.H!ml` or `Wacatac.B!ml`: the `!ml`
means a guess, not a known virus.

1. **Check where it came from.** Only the [launcher's releases](https://git.magicbean.dev/MagicBeanDev/HookshotLauncher/releases)
   and [Hookshot's](https://git.magicbean.dev/MagicBeanDev/Hookshot/releases) are official;
   [the download page](https://hookshot.magicbean.dev/download) sends you there.
2. **Let it through safely.** The [antivirus guide](https://hookshot.magicbean.dev/help/antivirus/) shows how to check
   the file, restore it, and exclude only Hookshot's folders.

[Search antivirus reports](https://hookshot.magicbean.dev/progress/#problem-search?q=antivirus)

## Still stuck?

1. **After a crash, click Report.** When Hookshot closes unexpectedly, at the start or while you play, a window says what
   happened and, where it can tell, why (update the graphics driver: Hookshot needs Vulkan 1.3; out of memory; build
   the game again). **Report** copies a report to your clipboard (the error, your PC's hardware and the end of the log,
   with your home folder and user name taken out; no saves or game files) and opens the issue form in your browser:
   paste it into the form's `hookshot_log.txt` box, then say what you were doing. The game sends nothing itself.
   **Open the log folder** shows the logs. The report is also saved in the game folder's `bug-reports/pending` folder.
2. **Make a bug report.** Open the menu (<kbd>F1</kbd>), go to **Gameplay** and choose **Bug report**. It saves a folder
   in `bug-reports` in the game folder with the log, a picture and `report.txt`, which ends with a link that opens the
   report form already filled in. Your home folder and user name are taken out.
3. **Or find the log yourself,** if the game doesn't get that far: `hookshot_log.txt` in the game folder's `logs` folder is the last
   run, and `hookshot_log.1.txt` to `.4.txt` the four before it. On Linux, `hookshot_startup.log` has the startup
   errors.
4. **Search the reports.** [Someone may have had it already](https://hookshot.magicbean.dev/progress/#problem-search),
   with a workaround.
5. **Ask on [Discord](https://discord.gg/magicbean).** The team and other players are there.
6. **Report it** with the [report form](https://git.magicbean.dev/MagicBeanDev/Hookshot/issues/new): your version,
   where you were in the game, your graphics card and driver, the log and a screenshot.
   [What to include](reporting-and-contributing.md) has the details.

Never share game files, keys or saves.
