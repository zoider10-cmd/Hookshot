# Updates and saves

The Hookshot Launcher keeps the game up to date: it rebuilds it from the game files the first build kept, so you don't
need your copy of the game again, and your saves and settings stay as they are.

## How updates work

When the launcher starts, it checks for a newer version on your channel. If there is one, press **Update**: it
downloads the new builder (only the parts that changed) and builds the game again, usually faster than the first time.
The launcher updates itself the same way. What changed in each version is on
[Hookshot's releases](https://git.magicbean.dev/MagicBeanDev/Hookshot/releases).

## Before you update

1. **Save and quit** the game from its own menu.
2. **Back up your saves.** Copy the save folder somewhere safe: an update keeps it, but a copy costs nothing. See
   [where Hookshot keeps them](saves.md#where-hookshot-keeps-them).
3. **After updating, load your slot** to check your adventure. If something is wrong, stop and put your backup back
   ([undo a copy](saves.md#undo-a-copy)).

## What an update keeps

| An update keeps | An update replaces |
|---|---|
| Your saves | The game itself (`bin`) and its files |
| Your menu choices and controls (`hookshot_options.ini`) | `image.bin` and the shader list |
| `hookshot_env.txt` | `language.txt`, written again with the game's language |
| Your `mods` folder | |

The first start after an update prepares the game's shaders again, so it's slower than the next ones.

## Channels

The launcher builds from one of three channels:

| Channel | What it is |
|---|---|
| **Stable** | The released version. Choose this to play. |
| **Release candidate** | The next version, before it's released. |
| **Nightly** | Built after every change. Untested: it may break your saves or settings, so back them up first. |

To go back to a released version, build one from the **Stable** channel. When you report a problem, say the exact
version: it's on the launcher's home page, and on the first line of `hookshot_log.txt`. [The versioning
guide](versioning.md) explains the numbers.

## Mods

Mods go in a `mods` folder in the game folder, and an update keeps them. A mod made for an older version may need
updating too. The [mods reference](../README.md#mods) covers installing them and how they're loaded.

## Moving saves

To bring a save from an emulator or Hookshot, export one, or copy saves between Windows builds, see
[moving your saves](saves.md).
