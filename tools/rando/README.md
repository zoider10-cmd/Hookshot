# Randomizer tools

Scripts that place a randomizer seed's items, run on the player's PC against their own extracted game
(`<game folder>\romfs`). They read the settings of the launcher's **Randomizer** page (`hookshot_options.ini`,
[gpu/vk/oot_rando.h](../../gpu/vk/oot_rando.h)) and write the seed as a RomFS mod, `<game folder>\mods\rando-seed`,
which Mako loads in place of the game's own files ([host/mods.c](../../host/mods.c)). The game's files are never
changed, and no game file belongs in this repository: the scripts' reports name the game's files and items, so
`rando_inventory.txt` and `rando_locations.txt` are in `.gitignore`.

All need Python 3 with `zstandard` (the build's own requirement). Run them with `python -I` from the repository root.

## Playing a seed

1. In the launcher's **Randomizer** page: turn Randomizer on,
   set **Chests**, and **Major items** and **Dungeon keys** as wanted.
2. Press **Play** in the launcher. It runs `<game folder>\rando\rando_seed.py` (a copy the build puts there) with
   `--if-changed`, then starts the game. `mods\rando-seed\spoiler.txt` says what every chest held and holds now;
   `rando\last_run.txt` is what the script said.

The launcher needs Python 3 on the PATH with `zstandard` for this. With the randomizer or Chests off, Play removes the
seed's mod. Starting `hookshot.exe` directly does not place anything.

Since the merge of Mako 3.3 the game's own menu (Insert or F1) has no Randomizer tab: 3.3 wrote that menu anew, and
the tab was not written again for it. The launcher's page has every setting, and **Copy seed ID** and **Paste seed
ID** there do what the tab's Seed row did: an ID holds the seed and every setting, so the same ID is the same seed.
The menu keeps the randomizer's lines of the options file when it saves.

By hand, for trying things: `python -I tools/rando/rando_seed.py "<game folder>\romfs"`.

**A seed being played changes under its save when the seed or a setting is changed.** Finish it, or keep its settings.

**A seed's saves are apart from the normal game's.** With the randomizer on the game keeps its saves in
`<game folder>/user/save_rando`, and in `user/save` with it off (`hos_save_folder`, host/oot_rando.c), so a save made
in a seed is not loaded into a game whose chests are the game's own, nor the other way round. The launcher's **Saves**
button opens the one the next Play uses, and a save dropped in `SAVE FOLDER` is imported into that one. Every seed
shares the one randomizer folder. Saves made with the randomizer on before this (Mako 3.0.1 and the first 3.3 merge)
are in `user/save`: copy that folder to `user/save_rando` once to go on with them. Seen in play: a save made with the randomizer on
is not listed with it off, and is there again with it on.

| Setting | What `rando_seed.py` does with it |
|---|---|
| Chests | Overworld / Dungeons / All: which chests take part. Their items are shuffled among them, across areas. |
| Dungeon keys | Off: a dungeon's small keys, Boss Key, map and compass stay in their chests. Own dungeon: shuffled among that dungeon's chests. Anywhere: as Own dungeon for now. |
| Major items | On: the chests that start an event take part too (most of the big items), placed by the logic. The same as `--event-chests`. |
| The others | Not placed yet. |

Left alone: mini-game chests, chests whose item depends on what Link already has, and, unless Major items is On,
chests that start an event when opened (most of the big items).

### The logic

With Major items Off none of the items that gate the game moves, so the game's own order holds.
With it On, thirteen gating items are in the shuffle (Kokiri Sword, Slingshot, Bomb Bag, Boomerang, Lens of Truth, Bow,
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

## Cosmetics

The launcher's **Cosmetics** page sets a colour for each of adult Link's three tunics, for the hearts and for the
magic meter; **Randomize all** gives each one a colour by chance. They are kept in
`<game folder>\hookshot_cosmetics.ini` (not the options file: the game's menu writes that one whole and would drop
them), and Play runs `<game folder>\rando\rando_cosmetics.py`, which writes their colour textures, changed, to
`mods\cosmetics`. That takes about half a minute after a colour is changed and nothing after that; with everything on
the game's own colour the mod is removed. It has nothing to do with the seed: no item moves.

- The textures are ASTC (the Kokiri Tunic's cloth BC3) and are neither decoded nor compressed again: a block stores
  two colours for each of its parts and how far each pixel lies between them, and only the stored colours are changed.
  The file keeps its size, so there is no size table entry to raise.
- Only the hues that are the tunic's own are changed (the Goron Tunic's reds, not its gold trim or leather).
- Seen in game, through the launcher's page: the Zora Tunic white and the Goron Tunic teal, whole, with their trim,
  belt and leather kept. The Kokiri Tunic pink had only its vest and hat band changed: its cloth was missing from the
  list. With the cloth added it was pink but for its olive stitching and fringe (`Mt_Angin_Acs_Player_Adult_Alb`, BC1),
  added since: seen in game in blue, stitching and fringe with it.
- The Kokiri Tunic is not a model of its own. Its vest is `Mt_Vest_Player_Adult_Alb`, on Link's own model, and its
  cloth is `Angin_Tile_A_Alb`, a picture nine models share: young Link's tunic, Mido's clothes, a Kokiri bed and the
  Fairy Ocarina's strap change colour with it. Young Link's vest, hat and stitching (`Mt_Vest_`, `Mt_Cloth_Parts_` and
  `Mt_PantsParts_Player_Child_Alb`) are changed too, after white and black were seen in play as changed cloth under a
  green vest; Mido's vest is his own and stays green. Giving adult Link a cloth of his own would take a new texture file, so
  a size table entry beside the seed's.
- The hearts and the magic meter are pictures of `UI/Layout2Archive/Common...bntx.zs`, the file of every picture of
  the game's screens (878 of them, a quarter of a gigabyte unpacked): the mod carries that file whole (75 MB) with 17
  heart pictures and 8 of the meter changed. The hearts run from red to orange, and both are taken as their colour;
  their gold frame is left. Seen in game: both show the colour picked (green hearts, on the load screen's saves too; a red meter).
- Not changed: the tunics' pictures in the equipment menu (files of their own), and the Insert menu has no Cosmetics
  tab (the colours are written before the game starts).

By hand: `python -I tools/rando/rando_cosmetics.py "<game folder>\romfs" --goron purple`.

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
  - The Forest Temple's Stalfos room (the Bow's chest) cannot be left without the Bow or a key, and the warp
    songs do not work in it: with another item in the chest the player is shut in. The room's shutter is
    opened by an eye switch (a logic module's doing, `ForestTemple_Room17_ShutterOpen`: not something the map links
    say), and the shutter's `IsDisableSaveAndWarp` is what turns the warp songs off. Every seed's mod sets it to
    false (`FIXES`): the room is left by a warp song, and the game can be saved in it (seen in play). Only the mod has it: with the
    randomizer off the game's own file is used.
  - Leaving that room by a warp song with the Stalfos dead and the eye not shot, then coming back into the temple
    with the Bow: the game showed the room's shutter and opened it, as if the eye had been shot. Seen once (seed
    2068101879); the temple was finished after it. Not known whether it is the Stalfos being dead, the Bow, or both.
  - Looked for more rooms like it in the map files (`rando_shutters.py`), not in play: 45 shutters of the game have
    `IsDisableSaveAndWarp`, most of them opened by the room's enemies being dead. A chest within 30 of one is marked
    when a switch beside the shutter takes an item (eye: Bow, or Slingshot where Link is a child; hammer switch;
    solar switch) that the chest's rule does not ask for. Marked: the Stalfos room's Bow chest (so the check finds
    the known room), and the Deku Tree's map chest, whose eye switch belongs to the Slingshot room next door and
    drops its ladder (`InsideTheDekuTree_Gimmick_FallingLadder`). None in the Fire, Shadow and Spirit Temples, the
    Gerudo Training Ground or Ganon's Castle. What opens a shutter is not in the map files, so this does not prove
    those rooms can be left: it says where a switch is close enough to be the reason.
  - Not known: whether the Deku Tree's Slingshot room can be left without the Slingshot (its ladder is dropped by
    the eye switch, and a child has no warp song). Every seed played so far had the Slingshot before that room.
  - The Fire Temple's Megaton Hammer room cannot be left without the Hammer, but the warp songs work in it (seen in
    play, seed 2068101879, with a Red Rupee in the chest): it is left by a warp song, as the Stalfos room is with its
    fix. Nothing is changed for it. Sheik teaches the Bolero of Fire on the way to the temple, so Link has a warp
    song by then; the rules do not check that.
  - The Fire Temple has 8 small keys and 8 doors that take one (the map files), as the original. The first key
    (Darunia's room) also opens the door off the entrance hall to the Boss Key's room; spent there, none is left for
    the big lava room's door, and the rest of the temple stays shut. With the Hammer and the Hover Boots from other
    chests that is a way to the boss that shuts Link out of the temple's other chests. Not tried in play.
  - **Bombs cannot be used before the Goron's Bracelet.** The Bomb Bag from a Deku Tree chest was in the inventory
    with bombs, and they could be used once Darunia had given the bracelet. The rules allow for it (see `RULES`).
  - Dodongo's Cavern's entrance opens to a bomb flower only (so to the Goron's Bracelet), not to a bomb of Link's own.
    The rules already have its chests ask for leaving the forest, where the bracelet can be got.
  - The Lens of Truth comes with a magic meter.
- Chests whose item depends on what Link has (the Hylian Shield's in the graveyard, the Deku Shield ones) are left
  alone: the game decides there between the item and a substitute.
- Gold Skulltulas (`Enemy_Skulltula_Gold`) and Heart Pieces (`HeartPieceAnchor`) do not name an item in the map
  files; shops and gifts are in event flows and actor parameters. They need another way than this one.

Tested in game so far: Kokiri Forest (Mido's house's chests and the Kokiri Sword's), and seed 2068101879 (Chests: All,
Major items: On, Dungeon keys: Off) played through the Forest Temple, the Water Temple (Iron Boots and Longshot
shuffled) and the Fire Temple (the Megaton Hammer and the Hover Boots from other chests, had before it) without a
chest that could not be reached. That run was ended there with all thirteen gating items collected, each got where
the logic had put it: nothing the rules asked for was out of reach. The Shadow and Spirit Temples and Ganon's Castle
were not played, so the rules of the chests inside them (which held no gating item in this seed) are still unchecked,
and the seed was not finished.

## The scripts

| Script | What it does |
|---|---|
| `rando_seed.py` | Makes the seed's mod from the settings: the chest shuffle. |
| `rando_inventory.py` | A report of where the game's files name items: how the data is laid out. |
| `rando_locations.py` | A report of every chest, Gold Skulltula, Heart Piece and item actor in the maps, with its parameters. |
| `rando_actors.py` | A report of the parameter files in the item actors' packs, to compare items that behave differently. |
| `rando_room.py` | A report of every actor around one chest, with the links between them: how a room is wired. |
| `rando_shutters.py` | Lists every shutter that turns saving and the warp songs off, with the chests and switches near it, and marks the chests to look at in play. |
| `rando_sizetable.py` | Finds the size table and shows how much room a map file's entry has. |
| `rando_poc.py` | The first test: one chest's item swapped in place. |
| `rando_poc2.py` | The second test: one chest given any item (its own block, a new name, the size table). Its mod, `rando-zz-test2`, must be deleted before a seed is played: it carries a size table of its own. |

| `rando_cosmetics.py` | Cosmetics: writes the colours of the tunics, the hearts and the magic meter as a mod of its own, `cosmetics`, from the launcher's Cosmetics page. |

`tests/test_rando_cosmetics.py` checks its block reading and writing on made-up blocks, its colours, and that the
launcher's page and the build match it.
`tests/test_rando_seed.py` checks `rando_seed.py`'s file changes and its shuffle on made-up map files;
`tests/test_rando_shutters.py` checks which chests `rando_shutters.py` marks, on made-up actors.
