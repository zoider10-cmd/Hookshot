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

Left alone: mini-game chests, chests whose item depends on what Link already has, and, unless `--event-chests` is
added to the command, chests that start an event when opened (most of the big items).

### The logic

Without `--event-chests` none of the items that gate the game moves, so the game's own order holds.
With it, thirteen gating items are in the shuffle (Kokiri Sword, Slingshot, Bomb Bag, Boomerang, Lens of Truth, Bow,
Megaton Hammer, Iron Boots, Hover Boots, Longshot, Silver and Golden Gauntlets, Mirror Shield), and the logic places
them so that each can be reached with the ones before it. The spoiler log lists that order.

- The rules (`RULES` in `rando_seed.py`) say what each area's chests ask for, with exceptions for chests known by
  their event. What stays where the game has it (songs, the Hookshot from Dampe's race, tunics, magic, the stones and
  medallions) is folded into them.
- They are written from the original game and ask for too much where the remake is not known: a chest whose place is
  not known asks for what its whole area can ask for, and an area the rules do not know (`DreamWorld`) asks for
  everything, so it only gets items the game can be finished without.
- **They have not been checked against the remake chest by chest**, and they do not look at a dungeon's keys: leave
  Dungeon keys Off. A seed is meant to be finishable, not proven to be. A seed that is not is a rule to fix: note the
  chest and what it needed.
- `--no-logic` puts the big items anywhere.

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
- A chest's event (`Dynamic.GetEventName`) stays with the chest, and the item is the chest's. The Kokiri Sword's chest
  with a purple Rupee in it gave the Rupee, then played its scene and left a sword in Link's hand that was gone after
  a reload. The Kokiri Sword from a chest of Mido's house was a whole sword: the screen faded to black for a moment in
  place of a scene, the sword was in the inventory and kept by a save, and Mido let Link pass.
- Open, from the first logic seed played (Slingshot, Lens of Truth, Hover Boots and Kokiri Sword in Mido's house):
  - **A chest's autosave can lose an item.** Loading the autosave made as one of those chests was opened: the
    Slingshot was gone and its chest open, while the Lens, the boots and the sword were kept. The autosave after the
    Kokiri Sword's own chest (its event) had everything. Until this is understood, save by hand after a big item.
  - The item slots of the HUD did not appear, though the items could be used (the Lens too, which came with a magic
    meter). Probably switched on by an item's own event, which is skipped when the item comes from another chest.
  - Since then, in the same seed: a chest's autosave in the Deku Tree, after the Kokiri Sword's own chest had been
    opened, kept every item, and so did saves made by hand. The loss has only been seen in the autosaves of Mido's
    house before that chest's event. Open the Kokiri Sword's chest early.
  - The item slots appeared with the first item; only the D-pad part waited for the game's own Navi prompt.
- Where the remake differs from the original, found in play:
  - **Bombs cannot be used before the Goron's Bracelet.** The Bomb Bag from a Deku Tree chest was in the inventory
    with bombs, and they could be used once Darunia had given the bracelet. The rules allow for it (see `RULES`).
  - The Lens of Truth comes with a magic meter.
- Chests whose item depends on what Link has (the Hylian Shield's in the graveyard, the Deku Shield ones) are left
  alone: the game decides there between the item and a substitute.
- Gold Skulltulas (`Enemy_Skulltula_Gold`) and Heart Pieces (`HeartPieceAnchor`) do not name an item in the map
  files; shops and gifts are in event flows and actor parameters. They need another way than this one.

Tested in game so far: Kokiri Forest (Mido's house's chests and the Kokiri Sword's). The other areas use the same files and steps.

## The scripts

| Script | What it does |
|---|---|
| `rando_seed.py` | Makes the seed's mod from the settings: the chest shuffle. |
| `rando_inventory.py` | A report of where the game's files name items: how the data is laid out. |
| `rando_locations.py` | A report of every chest, Gold Skulltula, Heart Piece and item actor in the maps, with its parameters. |
| `rando_actors.py` | A report of the parameter files in the item actors' packs, to compare items that behave differently. |
| `rando_sizetable.py` | Finds the size table and shows how much room a map file's entry has. |
| `rando_poc.py` | The first test: one chest's item swapped in place. |
| `rando_poc2.py` | The second test: one chest given any item (its own block, a new name, the size table). Its mod, `rando-zz-test2`, must be deleted before a seed is played: it carries a size table of its own. |

`tests/test_rando_seed.py` checks `rando_seed.py`'s file changes and its shuffle on made-up map files.
