# Randomizer tools

Scripts that place a randomizer seed's items, run on the player's PC against their own extracted game
(`<game folder>\romfs`). They read the settings of the game's **Randomizer** tab (`hookshot_options.ini`,
[gpu/vk/oot_rando.h](../../gpu/vk/oot_rando.h)) and write the seed as a RomFS mod, `<game folder>\mods\rando-seed`,
which Mako loads in place of the game's own files ([host/mods.c](../../host/mods.c)). The game's files are never
changed, and no game file belongs in this repository: the scripts' reports name the game's files and items, so
`rando_inventory.txt` and `rando_locations.txt` are in `.gitignore`.

All need Python 3 with `zstandard` (the build's own requirement). Run them with `python -I` from the repository root.

## Playing a seed

1. In the game's menu (Insert or F1), **Randomizer** tab: turn Randomizer on, set **Chests** and **Dungeon keys**.
   The launcher's Randomizer page has the same settings. Close the game.
2. `python -I tools/rando/rando_seed.py "<game folder>\romfs"`
3. Start the game. `mods\rando-seed\spoiler.txt` says what every chest held and holds now.

Run step 2 again after changing the seed or a setting. With Randomizer or Chests off it removes what it wrote.

| Setting | What `rando_seed.py` does with it |
|---|---|
| Chests | Overworld / Dungeons / All: which chests take part. Their items are shuffled among them, across areas. |
| Dungeon keys | Off: a dungeon's small keys, Boss Key, map and compass stay in their chests. Own dungeon: shuffled among that dungeon's chests. Anywhere: as Own dungeon for now. |
| The others | Not placed yet. |

Left alone for now: chests that start an event when opened (most of the big items), mini-game chests, and chests
whose item depends on what Link already has. **There is no logic**: nothing checks that a seed can be finished.

## What was found, and how a map file is changed

- An area's actors are in `Banc/<area>/*.bcett.byml.zs` (BYML version 7, zstd, some with the dictionaries of
  `Pack/ZsDic.pack.zs`). A chest (`Obj_TBox_*`) names what it holds in `Dynamic.Drop__DropActor`.
- The files store equal parameter blocks once: chests with equal `Dynamic` blocks share one. A changed chest gets a
  block of its own, added at the end of the file.
- An item name the file does not have yet goes into a copy of its string table at the end of the file, after the names
  it has, so every index already in the file stays right.
- The game does not load a file larger than its entry in `System/Resource/ResourceSizeTable.*.rsizetable.zs`
  (`RESTBL`: a 22-byte header, then a path's CRC32 and a size for each file, sorted). A map file's entry is its unpacked
  size rounded up to 32, plus 264. A file past its entry is skipped whole (Kokiri Forest lost Mido's house and its
  bridges that way), so the mod carries the table with those entries raised.
- A file compressed again without a dictionary is accepted.
- Gold Skulltulas (`Enemy_Skulltula_Gold`) and Heart Pieces (`HeartPieceAnchor`) do not name an item in the map
  files; shops and gifts are in event flows and actor parameters. They need another way than this one.

Tested in game so far: Kokiri Forest (Mido's house's chests). The other areas use the same files and steps.

## The scripts

| Script | What it does |
|---|---|
| `rando_seed.py` | Makes the seed's mod from the settings: the chest shuffle. |
| `rando_inventory.py` | A report of where the game's files name items: how the data is laid out. |
| `rando_locations.py` | A report of every chest, Gold Skulltula, Heart Piece and item actor in the maps, with its parameters. |
| `rando_sizetable.py` | Finds the size table and shows how much room a map file's entry has. |
| `rando_poc.py` | The first test: one chest's item swapped in place. |
| `rando_poc2.py` | The second test: one chest given any item (its own block, a new name, the size table). Its mod, `rando-zz-test2`, must be deleted before a seed is played: it carries a size table of its own. |

`tests/test_rando_seed.py` checks `rando_seed.py`'s file changes and its shuffle on made-up map files.
