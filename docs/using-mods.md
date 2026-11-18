# Mods

Hookshot loads mods that replace or add the game's files: textures, models, texts, sounds and other data. It
doesn't load mods that change the game's code. This page covers installing them, turning them off and checking that
they loaded.

## Before you start

- **Back up your saves.** A mod can change what gets saved, and removing it later doesn't undo progress made with it.
  See [where Hookshot keeps them](saves.md#where-hookshot-keeps-them).
- **Stop the game.** Mods are found once, when the game starts: add, remove, rename or edit them with the game
  closed, then start it again.

## Install a mod

1. **Open the game folder.** In the launcher, select the version and choose **Open folder**. Each version has its
   own game folder, so each has its own mods.
2. **Make a `mods` folder** there, beside `bin`, if there isn't one yet.
3. **Put each mod in a folder of its own** inside `mods`, with the mod's `romfs` folder in it:

   ```text
   mods/
     01-hd-textures/
       romfs/
         ...
     02-new-music/
       romfs/
         ...
   ```

   Most mods made for emulators already come in this layout: unpack them into `mods` as they are. Their deeper
   layouts work too, such as `mods/contents/<title id>/<name>/romfs`.
4. **Start the game.**

An update of the game keeps your `mods` folder. A mod made for an older version of the game files may need an update
of its own.

## Turn a mod off

Rename its folder so that it starts with `_` or `-`, for example `_02-new-music`. Everything inside it is then left
out. Remove the `_` to turn it back on. Delete the folder to remove the mod for good.

## When two mods change the same file

The one that sorts last wins, by its whole path inside `mods`, ignoring case. Number the folders at the same level
(`01-...`, `02-...`) to choose the order: here `02-new-music` wins over `01-hd-textures` for any file they both have.
Files that only one mod has are used either way.

## Mods that make files bigger

The game sets aside a fixed amount of memory for each of its files, in a resource size table
(`System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs`). A mod with larger files, such as HD
textures, ships that table with its entries grown. Without it the game leaves the mod's file out, or a loading screen
waits forever.

Only one mod's table is used: the one in the mod that sorts last. If two mods each make files bigger, you need one
table with both mods' entries, in the mod that wins. Hookshot adds the button prompts' sizes to that table itself, so
your controller's icons keep working.

## Check that a mod loaded

Open `hookshot_log.txt` in the game folder's `logs` folder after a start:

| The log says | It means |
|---|---|
| `mods: 2 mods from ...` | The mods found, and the folder they came from |
| `mods: 01-hd-textures: 154 RomFS files` | That mod was found, with this many files |
| `mods: ... <- ...` | The game read that file from a mod |
| `mods: none in ...` | A `mods` folder with no mod in it: check that each mod has its `romfs` folder |
| `mods: ... is off (its name starts with _)` | A folder you turned off |
| `mods: ...: exefs patches are left out` | The mod's code patches aren't used (below) |

No `mods:` lines at all means there is no `mods` folder in this version's game folder.

## What doesn't work

- **Code patches.** A mod's `exefs` folder (`.pchtxt` and `.ips` patches, such as frame rate patches) is left out:
  Hookshot builds the game's code ahead of time, so patching its instructions would need a new build. Its `romfs`
  files still load.
- **Mod managers and installers.** There is no Mods tab and nothing to download or unpack: the `mods` folder is all
  there is.

Hookshot rewords one of the game's texts for a PC (a hint that names the console's built-in microphone). A mod that
has its own copy of that text file wins over the rewording.

## For mod authors

The [README's Mods section](../README.md#mods) has the details of the size table, and the
[file mod contract](mods.md) covers discovery, conflicting files, disabling and what the loader does not provide, with
an example checked without the game. To keep mods somewhere else, set `HOS_MODS=<folder>` in `hookshot_env.txt`: it
names the folder that holds the mods, not one mod's `romfs`.
