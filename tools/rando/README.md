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
   set **Chests**, and **Major items**, **Dungeon keys**, **Gold Skulltulas** and **Quest rewards** (with **Frogs**
   and **Light Arrows**) as wanted.
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

**The Tracker tab.** The Insert menu (Insert or F1) has a Tracker tab: a row for the whole game and one for each
area, with the treasure chests and Gold Skulltulas there that take part in the seed. The seed script writes it with
the seed (`mods/rando-seed/tracker.txt`, a line `<name>|<what>` a row: `tracker_lines`) and the menu shows the lines
as they are (`tracker_load`, gpu/vk/vk_menu.cpp; 48 rows at most), so it is the installed seed's, and says "No seed"
with the randomizer off. It is what the seed has in an area, not what is left: the menu does not know what has been
opened. Seen without a window (`RX_VK_MENU_SCRIPT`, `RX_VK_SHOT_MENU=1`); `tests/test_rando_tracker.py`.

**More saves than the game's one.** The game keeps one save of the player's own (`slot_00`) and five it makes itself;
its load menu lists no more. The launcher's **Save copies** button keeps the whole save folder under a name
(`user/save_copies/<save folder>/<name>`) and puts a kept copy back, after keeping the saves that were there as
"Before restore <date and time>". The randomizer's copies and the normal game's are apart, as their saves are. A
restore is refused while the game runs (`SaveCopies`, launcher/Launcher.cs; `tests/test_save_copies.py`).

| Setting | What `rando_seed.py` does with it |
|---|---|
| Chests | Overworld / Dungeons / All: which chests take part. Their items are shuffled among them, across areas. |
| Gold Skulltulas | Dungeons / Overworld / All: which Gold Skulltulas take part. Their tokens change places with the chests' Deku Scrub seeds and bomb, Bombchu, nut and stick bundles (`SKULLTULA_ITEMS`): a chest gives a token, a Skulltula drops the chest's item, made a pick-up. No gating item, key or Heart Piece goes to a Skulltula: the rules do not know their places yet. Needs Chests. |
| Dungeon keys | Off: a dungeon's small keys, Boss Key, map and compass stay in their chests. Own dungeon: shuffled among that dungeon's chests. Anywhere: as Own dungeon for now. |
| Major items | On: the chests that start an event take part too (most of the big items), placed by the logic. The same as `--event-chests`. |
| Open Deku Tree | On: in a new game Mido lets Link by to the Great Deku Tree without a sword and a shield. |
| Open forest exit | On: in a new game Link can leave Kokiri Forest before the Deku Tree is done. |
| Skip opening | On: a new game starts in Link's house, without the narration and Navi's flight. |
| The others | Not placed yet. |

Left alone: mini-game chests, chests whose item depends on what Link already has, and, unless Major items is On,
chests that start an event when opened (most of the big items).

### A new game's open ways, and its opening

- **The two closed ways of the forest are flags.** `KokiriForest_Npc_Kokiri_Mido_Child_Blocker` (Mido, until Link has a
  sword and a shield) and `KokiriForest_Npc_Kokiri_007_Child_Blocker_00` (the Kokiri at the way out, until the Deku
  Tree is done) start set and are put out by the story. Each has an invisible wall of `KokiriForest_Child_Dynamic` that
  is there while it is set, and the character acts on it too: with the walls alone moved away both still stopped Link.
- The seed's mod carries the game's list of flags (`GameData/GameDataList...byml.zs`: a BYML as the map files are, but
  big-endian, each flag named by the MurmurHash3 of its name) with those two starting put out. One byte each; the file
  keeps its size. A flag is kept in a save, so it is a new game's: a save made before keeps the way as it was.
- Seen in play, on a new game with both open: Mido stands in the gate and says his first words about a sword and a
  shield, but lets Link by, and after the Deku Tree is entered says what he says then; the Deku Tree lets Link in and
  plays as usual. The Kokiri at the way out says what he says after the Deku Tree. Saria's scene on the bridge plays
  and gives the Fairy Ocarina, once.
- **The logic does not count on an open way.** Its rules still ask for the sword and the Slingshot before anything
  out of the forest, and for the sword inside the Deku Tree: an open way is the player's to use, never the only way to
  an item.
- **No chest out of the forest is a child's with nothing in hand.** The 36 chests of the child's maps outside the
  dungeons were gone through in play on an open-forest game (seed HVBQ4-TY300-800RD): the only ones young Link opens
  with no item at all are the five the rules already had (the Kokiri Sword's and the four of Mido's house) and the
  graveyard's Hylian Shield chest, which is not shuffled. 23 need something, and 7 were not found (two in Kokiri
  Forest, the four of Hyrule Field, Kakariko's). So an open way out adds no early place for the logic among the
  chests: more early checks have to come from the other kinds (Gold Skulltulas, Heart Pieces, shops, gifts).
- **The opening is the event flow `OpeningEvent`**: two entry points that each play a cutscene and go on (the
  narration, `Dm_Kokiri_0000`, and Navi's flight to Link's house, `Dm_Kokiri_0030`). Neither cutscene sets anything of
  the game; the clock, the first challenge step and the autosave are the flow's own steps. Skip opening changes two
  numbers of that file so both entry points go on to what follows their cutscene. Seen in play: a new game starts in
  Link's house with both cutscenes passed over.

**Starting rupees** (`rando_start_rupees`, `--start-rupees`): a new game starts with 200 rupees, a full child's wallet in
this game. Link's rupees are a whole number of the game's list of starting values (`GameData/GameDataList`,
`PlayerStatus.CurrentRupee`, 0 in a new game), set there as the open ways' flags are (`flag_defaults`, kind `Int`).
Seen in play: a new game's pause menu shows 200, a rupee picked up at the full wallet and spending both behave as
ever. With it the seed's ID has a setting in each of its 16 places: the next one needs a longer ID.

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
  green vest; Mido's vest is his own and stays green. Seen in play since: young Link's tunic is whole in the colour. Giving adult Link a cloth of his own would take a new texture file, so
  a size table entry beside the seed's.
- The hearts and the magic meter are pictures of `UI/Layout2Archive/Common...bntx.zs`, the file of every picture of
  the game's screens (878 of them, a quarter of a gigabyte unpacked): the mod carries that file whole (75 MB) with 17
  heart pictures and 8 of the meter changed. The hearts run from red to orange, and both are taken as their colour;
  their gold frame is left. Seen in game: both show the colour picked (green hearts, on the load screen's saves too; a red meter).
- Not changed: the tunics' pictures in the equipment menu (files of their own), and the Insert menu has no Cosmetics
  tab (the colours are written before the game starts).

By hand: `python -I tools/rando/rando_cosmetics.py "<game folder>\romfs" --goron purple`.

**Navi's colour: looked for, not done.** Her textures (`Tex/Npc_Navi_*`, in two states, `.00` and `.01`) hold almost
no colour, so there is nothing for the textures' way to change. Her model's material animation
(`Model/Npc_Navi.anim.bfres.zs`: `Npc_Navi_Color` swaps those textures, `Status_Default` and `Status_Red` hold
colour constants, a warm white and a red) changes nothing that shows: with every colour constant of
`Status_Default` made green she was as white as before (run without a window). What shows is her glow, a particle
effect. `Effect/Dm_Npc_Navi` and `Effect/Npc_Fairy` are not read while she flies beside Link (a mod with copies of
them is not asked for them); her emitter sets (`Npc_Navi_Wait_00`, `_Trail_00`, `_Talk_00`, `_Attention_*`,
`_LockOn_*`) are in `Effect/static.Nin_Ounce_NVN2.vsetb.byml.zs`, 52 MB, a BYML whose `PtclBin` is one binary of
Nintendo's Vfx3 (`BFFH`, "Nintendo.Vfx3.ResourceModel") holding all 569 of the game's always-loaded emitter sets.
Its `Esets` list has each one's name and guid and no place in the binary, so which numbers are Navi's colours is
not known without reading that format.

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
- **A Gold Skulltula drops what the map tells it to, but only a pick-up can be picked up.** Its token comes from the
  game's drop system (`DropTable_Token_Gold`: `Obj_Token_Gold`), and it has the key a chest names its item by: a
  `Drop__DropActor` in its `Dynamic` block is dropped in the token's place (`add_drop`, and `rando	est_drops.txt`
  to try one). Seen in play in the Deku Tree: with `Obj_Heart_Piece` the Skulltula dropped a Heart Piece and Link
  collected it; with `Item_Boomerang` a tiny boomerang appeared, and with `TBox_Rupee_Purple` a rupee, and neither
  could be collected by touching it or with the Boomerang. The untouched fourth dropped its token as usual.
- Why: an item has two kinds of actor. A pick-up (`Obj_Heart_Piece`, `Obj_Rupee_*`, `Obj_Token_Gold`: `Obj_Item_Base`
  and its attention, physics and pick-up event) is collected in the world. What a chest gives (`Item_*`, `TBox_*`:
  `Item_EventObject_Base`) is only the model its get scene shows: no physics, nothing to touch. The thirteen gating
  items have the second kind alone.
- **An item's actor can be made a pick-up** (`pickup_pack`, and `rando\test_pickups.txt` to try one): in its pack
  (`Pack/Actor/<item>.pack.zs`, a SARC archive of BYML parameter files) the actor takes `Obj_Item_Base` as its parent
  in place of `Item_EventObject_Base`, its own table of game parameters names the base's as its parent, and the pack
  gets the base's files. The size table's entry for a pack is its size rounded up to 32, and 312. The first try
  crashed the game as the actor was made: the item's own table of game parameters took the base's place whole, and
  the pick-up was left without `DropBoundParam` and `GamePhysicsControllerParam` (a rupee's table has the base's as
  its parent). Found by running the game without a window on a copy of the saves, a save loaded by scripted presses
  (`HOS_HEADLESS`, `HOS_INPUT_SCRIPT`, `--user`).
- **The size table has an entry for each parameter file inside a pack too**, by the file's own name. The Bomb Bag's
  table of game parameters, given a parent, no longer fitted its entry and the game stopped as the pack was read
  (the Boomerang's, changed the same way, still fitted). A changed file's entry is raised by 4096 (`PART_GROWTH`):
  with that the Great Deku Tree loads with `Item_BombBag_Small` and `Item_Boomerang` made pick-ups (run without a
  window).
- **Seen in play, made pick-ups from the gold token** (`PICKUP_BASE`): `Item_BombBag_Small`, `Item_Hammer` and
  `Item_Boomerang`, each dropped by a Gold Skulltula of the Great Deku Tree, stay where the Skulltula died, are
  collected by touching them (from a jump and from vines too, without Link falling) with their text, are brought in
  by the Boomerang, and are still there after a save and a load. The Boomerang thrown afterwards behaves as ever.
- **What an item is in the pouch is a file other packs carry a copy of**, under the same name: the item in the menu's
  (`Pouch_*`) and the weapon in the hand's (`Weapon_*`). A child's game loads `Weapon_Boomerang` before a dropped
  item's pack, and its copy was the one used: the Boomerang, alone of the three, had to be picked up with A until
  the copies were changed too (`DefaultAutoGet`). Leaving the weapon's parts (`Boomerang`,
  `gamebalance_AttackParam`) out of the item's table changed nothing, and was taken back.
- **All thirteen gating items load made pick-ups** (run without a window, each in a chest of the Great Deku Tree: a
  chest's item's pack is read as its room loads, a Skulltula's drop's only when it dies). The copies of their pouch
  files are in `Pouch_*`, `Weapon_*`, `Armor_*` and other `Item_*` packs. Seen collected in play: the three above
  only. The gold skull's outline around an item is gone since the token's effects files in its pack name the Deku
  Shield's (`PICKUP_EFFECTS`). Checks: `tests/test_rando_pickups.py`.
- **The Gold Skulltulas setting** (`rando_skulltulas`, `mix_skulltulas`): the map files have 100 Gold Skulltulas
  (`Enemy_Skulltula_Gold`, by hash; 44 in dungeons, told by `DefaultDungeonRoomIndex` as a chest is). Their tokens and
  the chests' rupees and supplies (`SKULLTULA_ITEMS`) are shuffled among those chests and the Skulltulas: a chest gives
  the token as an item (`Item_Token_Gold`), a Skulltula drops the chest's item, made a pick-up. The chest shuffle and
  the logic run first and are not changed by it: no gating item, key or Heart Piece goes to a Skulltula, as the rules
  know no Skulltula's place (many ask for the Boomerang, the Hookshot or the night).
- 74 Skulltulas take a drop in place. The other 26, all in the overworld, have no `Dynamic` block or are in a file
  without the `Drop__DropActor` key: their file is read whole and written again (`add_drop_anew`), which stores equal
  dictionaries each time and so grows the file.
- An item made from another item (a red rupee from a green one, `TBox_Rupee_Red` from `TBox_Rupee_Green`) has that
  one's actor changed, in its own pack's copy, and the other's pack is made a pick-up with it (`pickup_family`). What
  is got by touching it already (a rupee, arrows, a magic jar: `DefaultAutoGet` in its pouch file or that one's
  parent) keeps its pouch file. Checks: `tests/test_rando_skulltulas.py`.
- **A Skulltula is done with by its drop's get event, and the game runs that only the first time an item is got.**
  Seen in play, Gold Skulltulas: All: a chest gave a gold token with its text, and the count went up. The first Deku
  Scrub's seed dropped by a Skulltula stayed in place, turned, and was collected by touch with its text; the next
  ones were put in the pouch without it, stayed where they were, and their Skulltulas were back when the Great Deku
  Tree was entered again, for another seed each time. So were a rupee and a bomb bundle, which the save had had
  before. With the event each time (`PlayGetEventManyTimes`, and `GetType` "Large" where the pouch file names none:
  every item of the game's own that is got each time has both; `pickup_pack`'s `each_time`) four seeds in a row
  were each got with their text, and their Skulltulas stayed dead.
- **What goes to a Skulltula** (`SKULLTULA_ITEMS`): the Deku Scrub's seed, the bomb, Bombchu, Deku Nut and Deku
  Stick bundles, the arrow bundles and the magic jar. Seen in play with the event each time: Deku Nut bundles were each got with their text, and their
  Skulltulas stayed dead. **A bundle Link has nothing to carry in is not got at all**: a bomb bundle without a Bomb
  Bag, and a Deku Nut bundle in a game that had had no nuts yet, stayed where they were with nothing given, and
  their Skulltulas were back when the room was entered again; the nuts were got once some had been bought. It is
  there for later, as a token out of reach is, with no text to say why. The stick and Bombchu bundles have not been
  seen.
- **Gating items on Skulltulas** (`gate_skulltulas`, with Major items and the logic): after the chests are placed, about
  a third of the gating items are each tried on a Skulltula that still drops its token, and stay there if every
  gating item can still be got by the rules; the chest left behind gives the token. What a Skulltula asks for is not
  known one by one yet, so each asks for too much (`SKULLTULA_ASKS`: the three stones' items, the Longshot and the
  Megaton Hammer, with all its area can ask for); `SKULLTULA_RULES` is for the ones known better, by hash, and
  `<game folder>/rando/skulltulas_to_check.txt` lists all 100. A drop is brought in by the Boomerang and by the
  Hookshot, both seen in play (the Hookshot on the House of Twins' Skulltula, an adult's at night, its Deku Scrub's
  seed pulled in and got with its text, the Skulltula dead afterwards), so the adult's Skulltulas are given gating
  items as the child's are.
- **Worth watching: the adult's temples' Skulltulas ask for all their temple can.** All 100 are in `SKULLTULA_RULES`
  now, the Fire, Forest, Water, Shadow and Spirit Temples' 25 and Gerudo Fortress's two with their area's own rule
  (`RULES`) in place of that and `SKULLTULA_ASKS`: no Megaton Hammer or Longshot where the temple takes none. Not
  less than the area's, though the original's logic asks less of most: a temple's keys may lie behind anything
  the temple takes (Dungeon keys: Own dungeon), and the rules know no keys. The one that asks less is the Forest
  Temple's first, in the entrance room, which takes no key. Three of the Spirit Temple's are in the child's half
  and take less; they were not told apart surely enough to say which. Also to watch: the matches marked
  "probably" in `skulltulas_to_check.txt`, and that the original's surroundings still hold (the bean seller on
  Zora's River was past the boulders, not before them).
- **Seen in play, end to end:** the Lens of Truth, put by the logic on the Zora's River Skulltula in the soft soil in
  front of the bean seller (past the boulders: bombs, bugs), was got there. On the way the Goron's Bracelet
  (`Item_Gauntlet_Goron`, not in the pool) was made a pick-up and dropped by the Kokiri Forest night Skulltula
  (`rando	est_drops.txt`, `rando	est_pickups.txt`): got with its text, and bombs could be used after it, so it is
  the item that lets Link use them, not the talk with Darunia. The Lens of Truth and the bracelet are small as they
  hang and a little hard to see.
- **A small item is made larger** (`PICKUP_SCALES`: the Lens of Truth and the Goron's Bracelet, 1.5 times), by its
  ModelInfo's `DebugModelScale`, which the game's own actors use (dogs 0.85, the bosses' light balls 1.5). It is as
  much larger in its chest's scene, the two being one actor: not looked at. **An item hangs about half a metre
  over the place it is taken at**: it is in the pose of the chest's scene (its `ASRef`, `ASInfoRef`), which lifts it
  and turns it to face the camera, and the size carries the lift with it (at 2.5 the Lens of Truth hung a metre
  over; at 1.5, some 40 cm more than at 1). Without the pose it is at the right height and lies edge-on, harder to
  see than small. Both seen without a window, the Lens of Truth put on the vines.
- `rando	est_chests.txt` (lines of `<a chest's hash> <an item>`) makes a chest give an item whatever the seed put
  there: for trying what comes after a gating item without playing up to it.
- **What each Skulltula asks for** (`SKULLTULA_RULES`, all 100 by hash) is written from the original game's
  randomizer logic (track-oot.net's `logic/vanilla.min.json`, without tricks; its `database/world.json` has who can
  get each and when). The two games' lists are the same length area by area, Lake Hylia's five and Lon Lon Ranch's
  four being in the Hyrule Field map here. Each was matched to the map's by its area, the child's or the adult's
  map, `Nocturnal`, `IsMagicBeanSoil`, and where two were alike by height or room; where two could not be told
  apart both ask for the most either does. `<game folder>/rando/skulltulas_to_check.txt` has every line, how sure
  it is, and the original's name for it. The remake's own, from the player and the guides: the Hyrule Field
  southern grotto's crate (the adult's, after the child breaks the rock and kills the Skullwalltula; the grotto by
  the Gerudo Valley entrance has none), the tunnel on Lake Hylia's south-west shore, the vines inside Lon Lon
  Ranch's south-west tower, soft soil in front of the bean seller on Zora's River (past the boulders here: bombs), and the Great Deku Tree's fourth,
  which takes no bombs.
- **Kept from the Skulltulas** (`SKULLTULA_ITEMS_NOT_YET`): rupees (below). Tried on the way with the bundles,
  and no answer: getting a bundle as a token is got (`GetType` "Medium") with the event each time, the token's
  animations (`ASRef`), what a world rupee thinks with (`AIInfoRef` DropItem: it fell), making it from
  `Obj_Item_Base` (not there when its Skulltula died), and dropping a world rupee (`Obj_Rupee_*`) in a chest rupee's
  place (it fell into water, and its Skulltula was back each time). The runs without a window of a bomb bundle on
  vines, passed by whatever was changed, were on a save without a Bomb Bag: they showed nothing of those changes.
- **A parameter file under a new name is used**, once the size table has an entry for it (`size_table_add`: put in its
  place among the sorted CRC32s, the count raised). A Deku Scrub's seed with a pouch file of its own, a copy under
  another name (`pickup_pack`'s `own_pouch`, `OWN_POUCH`), was taken by touch with its text, and a second after it
  (without a window, two put in a line on open ground). A file that only named the item's as its `$parent` was not
  tried apart from a rupee, so a copy with all the item's says is what is written.
- **A rupee is not done with, whatever its pouch file.** A chest's green rupee made a pick-up was walked through and
  stayed, with the game's own pouch file unchanged, with one of its own, and with one of its own that asks for its
  get event each time (all without a window, on a save that had picked up rupees before). The red one taken with its
  text earlier was the first of its colour in its save. So a rupee's get event is not run a second time even when
  its pouch file asks for it, and a pick-up made from the token waits for it. Rupees stay in
  `SKULLTULA_ITEMS_NOT_YET`.
- **A chest's arrows and magic jar go to the Skulltulas**, each with a pouch file of its own (`PICKUP_OWN_POUCH`) and
  its get event each time. On a save with a bow and a magic meter that had had both before, two medium arrow bundles
  in a line were each got with their text, and two large magic jars (without a window). The large arrow bundle is
  given on the strength of the medium one. Without a bow, or without magic, they are not taken, as bombs are not
  without a bag.
- **A character's gift is a name in a scene's flow, and can be made another item** (`gift_item`, and
  `rando\test_gifts.txt`: `<flow> <the item it gives> <another>`). Nearly every item handed to Link goes through one
  flow of the game's, `Dm_SY_GetInEvent` (and `GetPouchContent`): the scene's own flow calls it as a sub-flow with the
  item's name as a parameter, a string. 209 such calls were counted in the 640 flows read (the Goron's Bracelet,
  Zelda's Letter, the stones and medallions, the Great Fairies' gifts, every song, the trading sequence, bottles,
  scales, quivers). The new name is put at the file's end and the parameter made to point at it: the old string is
  the scene's actor's name too. Seen in play with Darunia (`Dm_Goron_0030`) made to give a Piece of Heart: the
  scene ran to its end, Link got the Piece of Heart with its text and no bracelet (he could not lift a Bomb Flower),
  and Darunia was as ever after. Link still went through putting a bracelet on, with nothing in his hand.
  `tests/test_rando_gifts.py`.
- **The Quest rewards setting** (`rando_quests`, `GIFTS`, `gift_items`; `--quests`). Every gift of the game's flows
  was listed (164 lines in 89 scenes, by the sub-flow calls above and by the calls that hand the name on to
  `NpcCommon` and the like: `ReceiveItem`, `ReveiveItem`, `TakenRewardActor`) and gone through with the game's owner,
  who said which take part and what each needs: `<game folder>\rando\gifts_to_check.txt`. Left out by that: songs,
  stones and medallions (their own settings), what is bought (Shops, later), rupee prizes and refills, the Dream
  scrub, and for now the masks and the trading sequence (they may be optional checks later).
  A gift that takes part is a spot among the chests': its item goes into the pool, and its scene's flow is made to
  give what the shuffle put there. A prize of two sizes (a quiver, then a bigger one: the scene gives the one Link
  has not) is one spot, both names made the new item; the two scenes that give a kind put one of each size in the
  pool. 25 take part: Darunia, the Lost Woods target, the Skulltula house (10, 20, 30, 50), the Forest Stage (two),
  Bombchu Bowling (two), the diving game, the fishing pond (two), the two shooting galleries, the cucco lady,
  horseback archery (two), the rolling Goron, the man on the roof, the two Skull Kids, the dog lady; the frogs of
  Zora's River with **Frogs** (`rando_frogs`) and Zelda's Light Arrows with **Light Arrows**
  (`rando_light_arrows`), each off unless set.
  Two of their items gate the game, so with the setting on they are gating items and the rules name them
  (`quest_need`): the Goron's Bracelet wherever bombs are and in Dodongo's Cavern, the Silver Scale wherever an
  adult is (Ruto's Letter). Off, the rules and every seed made before are as they were. The Skulltula house's four
  ask for everything (the logic does not count tokens), so they only hold what the game can be finished without.
  The Silver Scale is not given to a Gold Skulltula (not seen as a pick-up yet).
  **Not in it yet**, each for what its flow asks before it gives (so another item would be given again and again, or
  its own item found elsewhere would shut it): the six Great Fairies (`IsGet.Item_...`), the two tunics, Biggoron's
  Sword and the lake scientist's Piece of Heart (what is in the pouch); and the two ocarinas (the scene puts them in
  the pouch itself), the Gerudo's card (many scenes ask for it), Dampe's Piece of Heart (dropped as an actor).
  **Seen without a player:** a seed with all 25 is written (19 flows) and the game starts and loads a save with it.
  **Seen in play:** the cucco lady (`Minigame_CatchCucco`) made to give a purple rupee: Link got it with its text and
  50 rupees, no bottle, and she gave nothing more when spoken to again.
  The Lost Woods target (`Dm_LostWood_0040`) made to give the Megaton Hammer: the scrub holds out a seed bag, which is
  the hammer when Link holds it up (the scene's prop is its own actor, the gift another), and a second win gives
  the green rupee.
  The Market's shooting gallery (`MiniGame_HitTarget`) made to give a Gold Skulltula token: Link got the token with
  its text, the count went up by one, no seed bag, and a second win gave the gallery's ordinary prize.
  **Not seen in play yet:** the other scenes (but Darunia's) giving another item; whether each gives only once (they
  were chosen for having a flag of their own for that); a gift's item (a scale, a bag, a wallet, the Stone of
  Agony, a bottle, the Light Arrows) coming out of a chest, though each has the chest items' base as the others do.
  `tests/test_rando_quests.py`.
- **Testing a pick-up without the player.** A save made with Link at the foot of the Great Deku Tree's first vines
  (his place is three floats at 0x1b4b0 of `progress.sav`), a map file with an `Enemy_Skulltula` of its Dynamic file
  made the item and put on the vines above him (a heart once taken, and a prop, are not made), and the stick pushed
  by `HOS_INPUT_LIVE` once the room is in: a second save has him on open ground on the Great Deku Tree's 3F, facing down the room, for walking into an
  item put on the floor and for the scene of his holding it up. From the vines: a real token and a first seed were got with their text as he climbed, a
  green rupee and a bomb bundle were passed by (that save has no Bomb Bag: see above).
- **The Kokiri Sword's chest holding another item** played Link putting the sword on his back all the same, and he
  could use a sword until the next load, with none in the inventory (seen in play). The chest starts an event of its
  own, `GetSword` of `Get_StoneOfForest.bfevfl`: the chest's opening (`Dm_SY_Treasurebox`), then the sword's cutscene
  (`Dm_Kokiri_0063`), then Navi if Mido is still in the way. Where the chest holds another item the first now goes on
  to what follows the second (`sword_chest_plain`, one number changed; `tests/test_rando_swordchest.py`). Seen in
  play: the chest gives its item, and Link has no sword after it. The other chests that start an event have not been looked at for the same: most of their events are not
  in a flow of their own name.
- Seen in play with `Item_Boomerang` made a pick-up: its own chest still gives it, with its scene. Dropped by a Gold
  Skulltula it fell to the ground and Link picked it up, with a short animation over his head and no scene. A world
  rupee (`Obj_Rupee_Purple`) flew out, fell, and was collected with its text. A Heart Piece dropped by a Skulltula on
  a wall did not fall and could not be reached (it is collected with A from beside it): a Heart Piece hangs where it
  is put, so it is no drop for a Skulltula out of reach.
- The Deku Scrub before the Deku Tree's Slingshot room is beaten with the Slingshot here, not only by a Deku Shield
  as in the original (seen in play).
- Heart Pieces lying in the world are actors named `Obj_Heart_Piece` in the map files (14 of them), each with a
  `HeartPieceAnchor` for its map icon; shops and gifts are in event flows and actor parameters. Not changed yet.

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
`tests/test_rando_newgame.py` checks the open ways' flags and the opening's change on made-up files.
`tests/test_rando_seed.py` checks `rando_seed.py`'s file changes and its shuffle on made-up map files;
`tests/test_rando_shutters.py` checks which chests `rando_shutters.py` marks, on made-up actors.
