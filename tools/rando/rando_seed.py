"""Randomizer, stage 2: shuffles what the chests hold across the whole game, as a mod.

Reads the Randomizer settings the launcher keeps in <game folder>\\hookshot_options.ini (rando_on, rando_seed,
rando_chests, rando_keys, rando_major, rando_open_deku, rando_open_forest, rando_skip_intro) and writes changed map
files, an updated size table and, for the last three, the game's list of flags and its opening event to
<game folder>\\mods\\rando-seed\\romfs\\..., which Mako loads in place of the game's own. The game's files are not
touched. The same seed and settings give the same shuffle.

    python -I tools/rando/rando_seed.py "F:\\Games\\OOT Remake Rando\\romfs"
    python -I tools/rando/rando_seed.py <romfs> [--game <folder>] [--seed N] [--chests 0..3] [--keys 0..2] [--event-chests] [--no-logic] [--dry-run]

The launcher runs it at Play (the copy the build puts in <game folder>\\rando, with --if-changed), so it only needs
running by hand to try something. With the randomizer off (or Chests Off) it removes the files it wrote before, so
the game is as shipped again.

Settings:
  Chests        1 the overworld's chests take part, 2 the dungeons', 3 all. Their items are shuffled among them, across
                areas: a Kokiri Forest chest can hold what a Fire Temple chest held.
  Dungeon keys  Off: a dungeon's small keys, Boss Key, map and compass stay in their own chests. Own dungeon: they are
                shuffled among that dungeon's chests. Anywhere is treated as Own dungeon for now: the game counts a
                small key for the dungeon it is picked up in, so one from another dungeon would be miscounted.
  Major items   On: the same as --event-chests, below.
  Open Deku Tree, Open forest exit   On: a new game starts with that way of Kokiri Forest open (OPEN, below). The logic
                does not count on either: its rules still ask for the sword and the Slingshot before anything out of
                the forest, so an open way is the player's to use and never the only way to an item.
  Skip opening   On: a new game starts in Link's house (OPENING, below).
What it leaves alone: a mini-game's chests, a chest whose item depends on what Link already has, and, unless
Major items is On or --event-chests is given, a chest that starts an event when opened (most of the big items: the Kokiri Sword, the Fairy
Bow, the Megaton Hammer...).
  --event-chests  Those take part too. The event stays with its chest and the item is the chest's: the Kokiri Sword's
                  chest with a purple Rupee in it gave the Rupee, then played its sword scene and left a sword in
                  Link's hand that was gone after a reload; the sword from another chest was a whole sword (in the
                  inventory, kept by a save, and Mido let Link pass).
The logic (with --event-chests, unless --no-logic): the thirteen items that gate the game and come from chests are
placed so that each can be reached with the ones before it, by rules of what every area's chests ask for (RULES,
below). The rules are written from the original game and ask for too much where the remake is not known; they have not
been checked against the remake chest by chest, and they do not look at a dungeon's keys (leave Dungeon keys Off).
So a seed is meant to be finishable, not proven to be. Without --event-chests no gating item moves, and the game's own
order holds. mods\\rando-seed\\spoiler.txt says where everything went and the order the rules found.

How a map file is changed (each step shown to work in game, one chest at a time, before this was written):
  - a changed chest gets a parameter block of its own at the end of the file (the files store equal blocks once, so
    changing the shared one would change its twins);
  - item names the file does not have yet go into a copy of its string table at the end, after the names it has;
  - the file grows, so its entry in the game's size table (System/Resource/ResourceSizeTable...rsizetable) is raised:
    the game does not load a file larger than its entry.
Needs the zstandard package.
"""
import argparse
import collections
import math
import os
import random
import struct
import sys
import zlib

ZSTD = b"\x28\xb5\x2f\xfd"
MOD = "rando-seed"
# (raised whenever the same settings would place something else than before: the launcher's run at Play, --if-changed,
# then makes the seed again. A seed being played changes under its save when that happens, so not lightly)
PLACEMENT = 3   # 2: the chests of LOCKED_ROOMS kept their items; 3: they take part again, their rooms opened by FIXES
# (a chest with one of these parameters is left as it is: see the top of this file)
KEEP_IF = ("GetEventName", "CheckEventName", "CheckEventNameIndoor", "Drop__CheckActor", "Drop__DropActor_Substitute",
           "DropViewActor", "IsEnableRepeatOpen", "SpawnType")
# (a chest's GetEventName that is known not to care what the chest holds: Mido's house's chests, whose event only
# quiets Navi. They gave other items in the tests and played as usual)
# Chests whose room cannot be left without the item they hold (by their event), found in play: with anything else in
# them the player is shut in. The Forest Temple's Stalfos room: no way out without the Bow or a key, and the warp
# songs do not work in it. Placement 2 kept their items; since then FIXES gives their rooms a way out.
LOCKED_ROOMS = ("ForestTemple_GetBow",)
# Changes to the map that a shuffled game needs, written with every seed (and so only with the randomizer on):
# {an actor's hash: {a key of its Dynamic block: the truth value it gets}}.
# The Stalfos room's shutter (opened by an eye switch, so by the Bow) no longer turns saving and the warp songs off
# while it is shut: without the Bow the room is left by a warp song, as any other. Nothing new to learn for a player.
FIXES = {0x74fb0489585fe0e2: {"IsDisableSaveAndWarp": False}}
FIXES_VERSION = 5   # (1: the eye switch took the Hookshot. 2: before the Kokiri Sword's chest's own cutscene was left out. 4: before Hyrule Field's clock ran from a new game's start, FIELD_CLOCK)
# The forest's two closed ways. Each is a flag of the game that starts set and is put out by the story: Mido stands in
# the way to the Deku Tree until Link has a sword and a shield (KokiriForest_Npc_Kokiri_Mido_Child_Blocker), and a
# Kokiri in the forest's way out until the Deku Tree is done (KokiriForest_Npc_Kokiri_007_Child_Blocker_00). An
# invisible wall of KokiriForest_Child_Dynamic is there while its flag is set (its Presence), and the character acts on
# the flag too: with the walls alone moved away both still stopped Link (seen in play). --open-deku and --open-forest
# make the flag start put out, in the game's list of flags (FLAG_LIST): {the setting: {a flag: the value it starts
# with}}. A flag is kept in a save, so this is a new game's; a save made before keeps the way as it was.
OPEN = {
    "deku": {"KokiriForest_Npc_Kokiri_Mido_Child_Blocker": False},
    "forest": {"KokiriForest_Npc_Kokiri_007_Child_Blocker_00": False},
}
FLAG_LIST = "GameData"   # (the folder of the romfs: GameDataList.Product.<n>.byml.zs in it)
# The clock of Hyrule Field. Until the owl's first cutscene there, the field's sky stays the day's whatever the time is
# set to: no day turns to night, and the Sun's Song's night is day again at once (seen in play). What ends it is the
# flag HyruleField_ArriveEntrance, the first thing the owl's event sets (the flow Goto_HyruleCastle, its entry
# Goto_HyruleCastle_Kaepora_00). Found with a save made before the owl and runs without a window: a night asked for
# stayed day at the forest's way out and far in the field; with the flag set first, it was night and stayed so; and
# with the flag set the owl's event began all the same when Link walked on (it is not what starts it).
# A seed can give the Sun's Song before the owl is met, and a way out of the forest that does not pass the owl leaves
# the sky so for good: so every seed's new game starts with the flag set (FIELD_CLOCK, in the list of flags), and the
# game's side sets it for a save that has it put out (host/hos_main.c).
# Tried first, and left: the flag HyruleField_ChangeENV, which leaving the forest sets and the owl's event puts out. It
# chooses the field's time table of palettes (WorldParam HyruleField_Child: ConditionEnvTimePalette) and is not what
# holds the day: with its step passed over the song failed as before.
FIELD_CLOCK = {"HyruleField_ArriveEntrance": True}
# Starting rupees: the list's whole number PlayerStatus.CurrentRupee is what Link has, 0 in a new game. With the
# setting on a new game starts with START_RUPEES of them (flag_defaults, kind "Int"). A game already begun keeps
# what its save says.
# 200 is what the child's wallet holds in this game (its owner's word; the original's held 99): a full wallet, and not
# more than it can hold.
RUPEES = "PlayerStatus.CurrentRupee"
START_RUPEES = 200
# A new game's opening is the event flow OpeningEvent: two entry points that each play a cutscene and go on. Neither
# cutscene sets anything of the game: Dm_Kokiri_0000 is the narration, Dm_Kokiri_0030 Navi's flight to Link's house.
#   Opening_LoadingKokiriForest: event 7 (plays Dm_Kokiri_0000) -> 14 (is the forest loaded?) -> the fades
#   Opening_Introduction: 5 -> the clock, the first challenge step, the camera -> 23 (a wait) -> 0 (plays
#     Dm_Kokiri_0030) -> 17 (was it skipped?) -> 19 (the fade, Navi beside Link, the camera) -> the music, the autosave
# --skip-intro starts the first at 14 and sends 23 on to 19: what the flow does after each cutscene, without it.
OPENING = "Event/EventFlow/OpeningEvent.bfevfl.zs"
PLAIN_EVENTS = ("KokiriForest_TreasureBox_NaviChatOff",)
# The Kokiri Sword's chest starts an event of its own (GetSword, of the flow below): the chest is opened
# (Dm_SY_Treasurebox, as every chest's), then Link puts the sword on his back (Dm_Kokiri_0063), then Navi speaks if
# Mido is still in the way. With another item in the chest the second still played: Link put a sword on his back
# that he did not have, and could use it until the next load, with none in the inventory (seen in play). So where
# the chest holds another item the event goes from the first cutscene to what follows the second (sword_chest_plain).
SWORD_EVENT = "Get_StoneOfForest_GetSword"
SWORD_FLOW = "Event/EventFlow/Get_StoneOfForest.bfevfl.zs"
DUNGEON_ITEMS = ("Item_Dungeon_SmallKey", "Item_Dungeon_BossKey", "Item_Dungeon_Map", "Item_Dungeon_Compass")
Chest = collections.namedtuple("Chest", "hash gyaml dyn_where dyn_at item params pos event")

# ---- the logic: what Link needs before a chest can be opened ----
# Thirteen items gate the game and come from chests. Everything else that gates it (songs, the Ocarina, the Hookshot
# from Dampe's race, tunics, magic, bottles, the stones and medallions) stays where the game has it, so it is folded
# into the rules below: "ADULT" stands for all it takes to pull the Master Sword, and so on.
# The rules are by area, with exceptions for chests known by their event. They are written from the original game's
# layout and are meant to ask for too much, never too little: a chest whose place in the remake is not known asks for
# what its whole area can ask for, and an area that is not known asks for everything, so it only ever gets items the
# game can be finished without. They have NOT been checked against the remake chest by chest.
S, SL, BB, BM = "Item_Sword_Kokiri", "Item_Range_SlingShot", "Item_BombBag_Small", "Item_Boomerang"
LENS, BOW, HAM, IRON = "Item_GlassTruth", "Item_Range_Bow", "Item_Hammer", "Item_HeavyBoot"
HOVER, LONG, SG, MS, GG = "Item_HoverBoot", "Item_Longshot", "Item_Gauntlet_Silver", "Item_Shield_Mirror", "Item_Gauntlet_Gold"
PROGRESSION = frozenset((S, SL, BB, BM, LENS, BOW, HAM, IRON, HOVER, LONG, SG, MS, GG))
NONE = frozenset()
# Found in play: bombs cannot be used before Darunia gives the Goron's Bracelet (the original game has no such tie).
# No rule asks for bombs alone: each that names BB also names the sword and the Slingshot, with which Link is out of
# the forest and can get the bracelet (Zelda's Lullaby, Saria's Song, Darunia). A rule that asks for BB below that
# would have to ask for those too.
CHILD = frozenset((S, SL))                 # out of the forest: the Deku Tree done
ADULT = frozenset((S, SL, BB, BM))         # the three stones: Dodongo's Cavern (bombs) and Jabu-Jabu (Boomerang) done
MEDALS3 = ADULT | {BOW, HAM, IRON, LONG}   # the Forest, Fire and Water Temples done: the way to the Shadow Temple
DESERT = ADULT | {LONG, HOVER, LENS}       # across the Haunted Wasteland
# area (the Banc folder): (what its chests ask for, {a chest's event: what that chest asks for})
RULES = {
    "KokiriForest": (ADULT, {"KokiriForest_TreasureBox_NaviChatOff": NONE, "Get_StoneOfForest_GetSword": NONE}),
    "InsideTheDekuTree": (frozenset((S,)), {}),
    "DodongoCavern": (CHILD | {BB}, {"DodongoCavern_GetMap": CHILD, "DodongoCavern_GetCompass": CHILD, "Get_StoneOfFire_GetBombBag": CHILD}),
    "InsideJabuJabuBelly": (ADULT, {"InsideJabuJabuBelly_TreasureBoxWithRuto09": CHILD | {BB}}),
    "BottomOfTheWell": (ADULT | {LENS}, {"BottomOfTheWell_GetGlassTruth": ADULT, "BottomOfTheWell_GetCompass": ADULT}),
    "ForestTemple": (ADULT | {BOW}, {"ForestTemple_GetBow": ADULT, "ForesetTemple_GetMap": ADULT}),
    "FireTemple": (ADULT | {HAM, BOW}, {"FireTemple_GetHammer": ADULT}),
    "IceCavern": (ADULT, {}),
    "WaterTemple": (ADULT | {IRON, LONG, BOW}, {"WaterTemple_Room07_LongHook_FocusOnGimmick": ADULT | {IRON}}),
    "ShadowTemple": (MEDALS3 | {LENS, HOVER}, {"SageOfShdawo_GetHoverBoots": MEDALS3 | {LENS}}),
    "SpiritTemple": (DESERT | {SG, BOW, MS}, {}),
    "DesertColossus": (DESERT | {SG, BOW, MS}, {"SageOfSpirit_NaboorIsTakenAway": DESERT, "SageOfSpirit_GetShield": DESERT | {SG}}),
    "GerudoTrainingGround": (MEDALS3 | {LENS, HOVER, SG}, {}),
    "InsideGanonCastle": (PROGRESSION, {"InsideGanonCastle_Get_Gauntlet_Gold": PROGRESSION - {GG}}),
    # the overworld: where a chest is in the remake is not known, so each asks for what its area's hardest chest did
    "HyruleField": (ADULT | {HAM}, {}), "KakarikoVillage": (ADULT, {}), "Graveyard": (ADULT, {}), "LostWood": (ADULT, {}),
    "SacredForestMeadow": (ADULT, {}), "DeathMountainTrail": (ADULT, {}), "DeathMountainCrater": (ADULT | {HAM}, {}),
    "GoronCity": (ADULT | {HAM, SG}, {}), "ZoraRiver": (ADULT, {}), "ZoraDomain": (ADULT, {}), "ZoraFountain": (ADULT | {IRON}, {}),
    "GerudoValley": (ADULT | {HAM, LONG}, {}), "GerudoFortress": (ADULT | {HOVER, LONG, BOW}, {}),
    "HountedWasteland": (DESERT | {BOW}, {}),
}


# ---- Quest rewards: the gifts that take part, and what they add to the rules ----
# With Quest rewards on, what some characters give takes part with the chests: a gift is a spot like a chest, its
# item goes into the pool and the scene gives what the shuffle put there (gift_items). Which scenes, who gives and what
# each asks for were gone through with the game's owner (the list of every gift of the game's flows, 164 lines, and
# the answers: <game folder>\rando\gifts_to_check.txt).
# Two of the gifts' items gate the game, so with the setting on they are gating items too (QUEST_GATES) and the rules
# name them (quest_need): the Goron's Bracelet, without which bombs cannot be used (found in play) nor Dodongo's
# Cavern entered, and the Silver Scale, for Ruto's Letter at the bottom of Lake Hylia, so for Jabu-Jabu and all that
# an adult does. Off, they are where the game has them and the rules are as they were: the seeds made before keep
# their shuffle.
# NOT in the shuffle yet, each for a reason found in its flow (they stay as the game has them):
#   the six Great Fairies            ask "has Link got my item" (IsGet.Item_...): another item would be given at
#                                    every visit, and theirs found elsewhere would shut the fountain
#   the Goron and Zora Tunics        the same, by what is in the pouch (Armor_Adult_Goron, Armor_Adult_Zora)
#   Biggoron's Sword, the lake       the same (Weapon_Sword_Giant; Item_Scale_Gold)
#   scientist's Piece of Heart
#   the two ocarinas                 put in the pouch by the scene itself, not through the gift's flow
#   the Gerudo's card                many scenes ask for it: to be looked at
#   Dampe's Piece of Heart           is dropped from the hole as an actor of its own, then picked up
BR, SSC = "Item_Gauntlet_Goron", "Item_Scale_Silver"
QUEST_GATES = frozenset((BR, SSC))
CHILD_BOMBS = CHILD | {BB, BR}
GROWN = ADULT | QUEST_GATES
Gift = collections.namedtuple("Gift", "key flow olds item area name need when entry", defaults=(None,))
# key: its name in the seed (never changed: a gift's place in the shuffle). flow: the scene's flow. olds: the items
# the flow names for this gift (a prize of sizes names two: the one Link has not got yet is given); each is made the
# gift's new item. item: what goes into the pool for it. area: the Banc folder its rules and the tracker count it in.
# need: what Link needs (meant to ask for too much, never too little; where the way to it is not known in the terms of
# the rules it asks for everything: such a gift only ever holds what the game can be finished without).
# when: None, or the setting of its own it waits for ("frogs", "light"; "scrubs": Deku Scrubs, which does not wait
# for Quest rewards). entry: None, or the one entry point of the flow whose calls are the gift's (two sales of one
# flow that name the same item: the Business Scrubs' two Pieces of Heart).
EVERYTHING = PROGRESSION | QUEST_GATES
GIFTS = (
    Gift("darunia", "Dm_Goron_0030", ("Item_Gauntlet_Goron",), BR, "GoronCity", "Darunia's gift", CHILD, None),
    Gift("lostwood_target", "Dm_LostWood_0040", ("Item_BulletBag_Medium", "Item_BulletBag_Large"), "Item_BulletBag_Medium", "LostWood",
         "the Lost Woods target", CHILD, None),
    Gift("skulltula_house_10", "GatheringTokenGold", ("Item_Wallet_Medium",), "Item_Wallet_Medium", "KakarikoVillage",
         "the Skulltula house: 10 tokens", EVERYTHING, None),   # (tokens: the logic does not count them yet)
    Gift("skulltula_house_20", "GatheringTokenGold", ("Item_AgonyStone",), "Item_AgonyStone", "KakarikoVillage",
         "the Skulltula house: 20 tokens", EVERYTHING, None),
    Gift("skulltula_house_30", "GatheringTokenGold", ("Item_Wallet_Large",), "Item_Wallet_Large", "KakarikoVillage",
         "the Skulltula house: 30 tokens", EVERYTHING, None),
    Gift("skulltula_house_50", "GatheringTokenGold", ("Obj_Heart_Piece",), "Obj_Heart_Piece", "KakarikoVillage",
         "the Skulltula house: 50 tokens", EVERYTHING, None),
    Gift("forest_stage_skull", "LostWood_ScrubForestStageElder_SkullMaskFirst", ("Item_StickBag_Medium", "Item_StickBag_Large"),
         "Item_StickBag_Medium", "LostWood", "the Forest Stage: the Skull Mask", CHILD, None),
    Gift("forest_stage_truth", "LostWood_ScrubForestStageElder_TrueMaskFirst", ("Item_NutBag_Medium", "Item_NutBag_Large"),
         "Item_NutBag_Medium", "LostWood", "the Forest Stage: the Mask of Truth", GROWN, None),
    Gift("bowling_bag", "MiniGame_BombchuBowling", ("Item_BombBag_Medium", "Item_BombBag_Large"), "Item_BombBag_Large", "Market",
         "Bombchu Bowling: the bag", CHILD_BOMBS, None),
    Gift("bowling_heart", "MiniGame_BombchuBowling", ("Obj_Heart_Piece",), "Obj_Heart_Piece", "Market",
         "Bombchu Bowling: the Piece of Heart", CHILD_BOMBS, None),
    Gift("diving", "MiniGame_Diving", ("Item_Scale_Silver",), SSC, "ZoraDomain", "the Zoras' diving game", CHILD_BOMBS, None),
    Gift("fishing_child", "MiniGame_Fishing", ("Obj_Heart_Piece",), "Obj_Heart_Piece", "HyruleField", "the fishing pond, as a child", CHILD, None),
    Gift("fishing_adult", "MiniGame_Fishing", ("Item_Scale_Gold",), "Item_Scale_Gold", "HyruleField", "the fishing pond, as an adult", GROWN, None),
    Gift("frogs", "MiniGame_FrogTenors", ("Obj_Heart_Piece",), "Obj_Heart_Piece", "ZoraRiver", "the frogs of Zora's River", GROWN, "frogs"),
    Gift("gallery_market", "MiniGame_HitTarget", ("Item_BulletBag_Medium", "Item_BulletBag_Large"), "Item_BulletBag_Large", "Market",
         "the Market's shooting gallery", CHILD, None),
    Gift("gallery_kakariko", "MiniGame_HitTarget", ("Item_Quiver_Medium", "Item_Quiver_Large"), "Item_Quiver_Medium", "KakarikoVillage",
         "Kakariko's shooting gallery", GROWN | {BOW}, None),
    Gift("cucco_lady", "Minigame_CatchCucco", ("Item_Bottle",), "Item_Bottle", "KakarikoVillage", "the cucco lady", CHILD, None),
    Gift("archery_heart", "Minigame_HorsebackArchery", ("Obj_Heart_Piece",), "Obj_Heart_Piece", "GerudoFortress",
         "horseback archery: 1000 points", GROWN | {BOW}, None),
    Gift("archery_quiver", "Minigame_HorsebackArchery", ("Item_Quiver_Medium", "Item_Quiver_Large"), "Item_Quiver_Large", "GerudoFortress",
         "horseback archery: 1500 points", GROWN | {BOW}, None),
    Gift("rolling_goron", "Npc_Goron_006_Child", ("Item_BombBag_Medium", "Item_BombBag_Large"), "Item_BombBag_Medium", "GoronCity",
         "the rolling Goron", CHILD_BOMBS, None),
    Gift("roof_man", "Npc_Hylia_001_Adult", ("Obj_Heart_Piece",), "Obj_Heart_Piece", "KakarikoVillage",
         "the man on the roof", GROWN, None),   # (the Hookshot, said its owner, not sure: it is Dampe's, an adult's)
    Gift("skull_kid_song", "Npc_SkullKid_Child", ("Obj_Heart_Piece",), "Obj_Heart_Piece", "LostWood", "the Skull Kid: Saria's Song", CHILD, None),
    Gift("skull_kid_game", "Npc_SkullKid_Child_02", ("Obj_Heart_Piece",), "Obj_Heart_Piece", "LostWood", "the Skull Kids' memory game", CHILD, None),
    Gift("dog_lady", "SubEvent_FindRichard", ("Obj_Heart_Piece",), "Obj_Heart_Piece", "Market", "the dog lady", CHILD, None),
    Gift("light_arrows", "Dm_TimeTemple_0130", ("Item_Arrow_Light",), "Item_Arrow_Light", "Market", "Zelda: the Light Arrows",
         MEDALS3 | DESERT | {LENS, HOVER, SG, BOW, MS} | QUEST_GATES, "light"),
)
# ---- Deku Scrubs: the Business Scrubs' one-time sales ----
# A Business Scrub's wares are named in its map file (ScrubBusiness_ShopItemActorName0..2), and its flow
# (Enemy_Scrub_Business_Common) finds the sale by that name: the name is put in the game's data and compared
# (EventQueryIsGameDataString64), and the sale that matches is a sub-flow call with the item, its price and its
# text. So the map's name is the sale's key and is left as it is; what is sold is the call's ActorName.
# 21 scrubs outside the Dream World (the Dream's are left alone: the game's owner's word). Most sell what can be
# bought again and again (seeds, nuts, bombs, arrows, potions): those stay. Four sales are made once, and are the
# setting's: a Piece of Heart (Hyrule Field), another from the scrub with a secret (Death Mountain Crater), the Deku
# Stick upgrade (Kokiri Forest and the Lost Woods: the same sale) and the Deku Nut upgrade (the Lost Woods). An
# upgrade's sale names two sizes, the one Link has not; both are made the new item, and the bigger size goes into
# the pool (the Forest Stage's gifts, with Quest rewards, put in the middle ones).
# What each asks for is in the rules' words before Quest rewards; with it on, quest_need adds its two.
SCRUB_FLOW = "Enemy_Scrub_Business_Common"
SCRUBS = (
    Gift("scrub_heart_field", SCRUB_FLOW, ("Obj_Heart_Piece",), "Obj_Heart_Piece", "HyruleField",
         "a Business Scrub: a Piece of Heart", ADULT | {HAM}, "scrubs", "SimpleShopRoot_Enemy_Scrub_Business_Pouch"),
    Gift("scrub_heart_secret", SCRUB_FLOW, ("Obj_Heart_Piece",), "Obj_Heart_Piece", "DeathMountainCrater",
         "the Business Scrub with a secret: a Piece of Heart", ADULT | {HAM}, "scrubs", "Secret"),
    Gift("scrub_sticks", SCRUB_FLOW, ("Item_StickBag_Medium", "Item_StickBag_Large"), "Item_StickBag_Large", "LostWood",
         "a Business Scrub: the Deku Stick upgrade", CHILD, "scrubs", "SimpleShopRoot_Enemy_Scrub_Business_Pouch"),
    Gift("scrub_nuts", SCRUB_FLOW, ("Item_NutBag_Medium", "Item_NutBag_Large"), "Item_NutBag_Large", "LostWood",
         "a Business Scrub: the Deku Nut upgrade", CHILD, "scrubs", "SimpleShopRoot_Enemy_Scrub_Business_Pouch"),
)


# ---- Shops: four shelves of each shop sell a shuffled item, once ----
# What a shop sells is three things that say the same (found with a Boomerang put on the Kokiri shop's shelf):
#   - the shelf's actor in the map file (Shop_DekuStick, with its place in the row, ShopItemIndex: none is 0): what
#     is seen on the shelf and what is given;
#   - the keeper's goods list (Component/ShopParam/<keeper>...ShopParam.bgyml in the keeper's pack, a copy in each of
#     the keeper's packs: GoodsList, by the same place): the actor whose price is asked, and how many there are
#     (StockNum; all of them without end but the masks, and the Kokiri shop's first nuts and stick);
#   - the three lists of the game's actors (RSDB: ActorInfo, GameActorInfo, PouchActorInfo). A shelf actor that is not
#     in them is not made, and its keeper, asked for his wares, stopped the game (seen in play).
# A shelf actor is Shop_Item_Base with an item's own name, model, animation and place in the pouch, and a price
# (Shop_Armor_Goron is that of the Goron Tunic). So an item of the chests is given one, Shop_Rando_<item>
# (shop_pack), with its rows in the three lists (shop_rows), and put on the shelf (shelf_actors) and in the goods
# list with one in stock (shop_goods). Seen in play: the Boomerang on the Kokiri shop's shelf, named, bought and
# got; its price was the Deku Stick's, 10, the goods list still naming that, and it had no words under its name:
# those are the line <the item's name>_ShopCaption of ActorMsg/PouchContent.msbt, which only what the game sells
# has. An item without one is given its own description under that label, in every language (shop_caption).
# Four shelves of each of six shops take part (SHOPS): not the Happy Mask Shop (its owner's word: the masks stay),
# and not what a game needs to buy again and again or by its own scenes (the shields, the tunics, bombs, arrows,
# the first nuts and stick, the potions and the fairy). What a shelf sold goes into the pool as the chests' own
# kind of it (SHELF_ITEMS), a red rupee for what no chest holds. Child and adult have one shop each of a kind, with
# the same goods: both sell the shuffled items, and what was bought as a child may be there again for the adult.
# A shop's need is what its place asks for in the rules' words, meant to ask for too much. Its place, for the
# tracker, is before its counter: three metres from its keeper, away from the shelves (the keeper's own place put
# Link behind the Bombchu Shop's counter, where a wall he could not see kept him: seen in play), or the game's own
# place for Link there (the Kokiri shop's ShopPosition_Link, the anchor before the Goron's and the Zora's keeper).
# The Bombchu Shop is young Link's alone (the adult's Market has its ruin), and its door is shut ("Closed due to bomb
# shortage") until two things hold, by the Market's logic for it (Logic/Market_Child_Prefab_0c76: the door's EnableOpen
# is Get_StoneOfFire_IsCompleted_Exp AND the time's division Night): it is night, and the Goron's Ruby's quest is at
# its last step, Complete (the list of flags: an enum of 21 steps from NotReady, through Darunia, Saria's Song,
# DungeonStart, BossBattle and EscapeDungeon). So its shelves ask for what Dodongo's Cavern asks for, DODONGO_DONE:
# the quest's step, not an item, is the gate, and bombs found early do not open it. Seen in play: shut at night
# before King Dodongo. Its name says so for the tracker.
DODONGO_DONE = CHILD | {BB}
# Which shelves (rando_shop_shelves, --shop-shelves). Off: the four of each shop above (slots). On: its other four
# too (rest), every shelf of a keeper's goods list, each sold once: the shields, the tunics, the potions and the bombs,
# arrows, nuts and sticks a game buys again and again are then not for sale, and come from grass, pots and enemies
# (the tunics from the Goron and King Zora, who give them still). What such a shelf sold goes into the pool as the
# chests' kind of it where there is one (SHELF_ITEMS: the shields are TBox_Shield_Deku and TBox_Shield_Hylian), a red
# rupee for the rest (a potion, a tunic, a fairy, a heart).
# One shelf is its own setting's: the Kokiri shop's Deku Shield (SHIELD_SHELF), with the Kokiri Sword's chest
# (rando_sword_shield, --sword-shield). Off: the sword is in its chest and the shield on its shelf whatever the
# other settings say. On: the chest takes part as an event's chest does (with Major items) and the shelf as a
# shop's does (with Shops, whichever its shelves). Mido lets Link by with a sword and a shield (OPEN), so with the shelf
# shuffled the shield is a gating item (DS, SHIELD_GATES): every rule that asks for the sword asks for it too, unless
# Open Deku Tree is on (shield_need). A Deku Shield burns: one found and lost after Mido is passed is not needed again.
DS = "TBox_Shield_Deku"
SHIELD_GATES = frozenset((DS,))
SHIELD_SHELF = ("kokiri", 6, "Shop_Weapon_Shield_Deku")
Shop = collections.namedtuple("Shop", "key params areas name need place ages slots rest")
SHOPS = (
    Shop("kokiri", ("Npc_Kokiri_001_Shop_Child", "Npc_Kokiri_001_Shop_Child_ShortStock"), ("KokiriForest",), "the Kokiri shop", NONE,
         (-1.9, 110.7, -22.6), "CA", ((0, "Shop_Heart"), (1, "Shop_DekuSeedBundle_02"), (3, "Shop_DekuNutBundle_02"), (5, "Shop_DekuStickBundle_Medium")),
         ((2, "Shop_DekuNutBundle_01"), (4, "Shop_DekuSeedBundle_01"), (7, "Shop_DekuStick"))),   # (and SHIELD_SHELF, 6)
    Shop("general", ("Npc_Hylia_018_Shop", "Npc_Hylia_018_Shop_Adult"), ("Market", "KakarikoVillage"), "the Bazaar", CHILD,
         (19.5, 100.4, 16.1), "C", ((0, "Shop_Heart"), (1, "Shop_MagicJar_Small"), (2, "Shop_DekuSeedBundle_02"), (7, "Shop_DekuStick")),
         ((3, "Shop_ArrowBundle_01"), (4, "Shop_BombBundle_01"), (5, "Shop_DekuNutBundle_01"), (6, "Shop_Weapon_Shield_Hylian"))),
    Shop("medicine", ("Npc_Hylia_020_Shop",), ("Market", "KakarikoVillage"), "the Potion Shop", CHILD,
         (20.6, 100.1, 6.0), "C", ((2, "Shop_Bottle_HalfMilk"), (5, "Shop_Bottle_Poe"), (6, "Shop_Bottle_Bug"), (7, "Shop_Bottle_Fish")),
         ((0, "Shop_Bottle_RedPotion"), (1, "Shop_Bottle_GreenPotion"), (3, "Shop_Bottle_Fairy"), (4, "Shop_Bottle_BlueFire"))),
    Shop("bombchu", ("Npc_Hylia_021_Shop",), ("Market",), "the Bombchu Shop (at night, after Dodongo's Cavern)", DODONGO_DONE,
         (-24.1, 100.4, 32.4), "C", ((4, "Shop_BombchuBundle_01"), (5, "Shop_BombchuBundle_07"), (6, "Shop_BombchuBundle_02"), (7, "Shop_BombchuBundle_08")),
         ((0, "Shop_BombchuBundle_03"), (1, "Shop_BombchuBundle_04"), (2, "Shop_BombchuBundle_05"), (3, "Shop_BombchuBundle_06"))),
    Shop("goron", ("Npc_Goron_011_Shop_Child",), ("GoronCity",), "the Goron shop", CHILD | {BB},
         (-16.6, 98.0, -20.2), "CA", ((0, "Shop_Heart"), (2, "Shop_Bottle_Bug"), (6, "Shop_BombBundle_03"), (7, "Shop_BombBundle_04")),
         ((1, "Shop_Bottle_RedPotion"), (3, "Shop_Armor_Goron"), (4, "Shop_BombBundle_01"), (5, "Shop_BombBundle_02"))),
    Shop("zora", ("Npc_Zora_011_Shop",), ("ZoraDomain",), "the Zora shop", ADULT,
         (-27.1, 104.9, 18.2), "CA", ((2, "Shop_Bottle_Bug"), (5, "Shop_ArrowBundle_02"), (6, "Shop_Bottle_Fish"), (7, "Shop_ArrowBundle_03")),
         ((0, "Shop_Bottle_RedPotion"), (1, "Shop_Bottle_GreenPotion"), (3, "Shop_Armor_Zora"), (4, "Shop_ArrowBundle_01"))),
)


def shop_slots(shop, every=False, shield=False):
    """the shelves of a shop that sell a shuffled item, [(its place in the goods list, the game's own actor there)]:
    its four; every: its other shelves too; shield: the Deku Shield's (the Kokiri shop's), whichever the others are.
    The four come first, in their order: a shelf's number in its name is its place here."""
    slots = list(shop.slots) + (list(shop.rest) if every else [])
    if shield and shop.key == SHIELD_SHELF[0]:
        slots.append(SHIELD_SHELF[1:])
    return slots


def shield_need(need):
    """what a rule asks for with the Deku Shield's shelf shuffled and Mido in the way: the shield wherever the sword"""
    return frozenset(need | SHIELD_GATES) if S in need else need

SHELF_ITEMS = (("Shop_DekuSeedBundle", "Item_ScrubBusinessSeed"), ("Shop_DekuNutBundle", "TBox_DekuNutBundle"), ("Shop_DekuStick", "Item_DekuStickBundle_Small"),
               ("Shop_MagicJar", "Tbox_MagicJar_Large"), ("Shop_BombBundle", "Item_BombBundle_Small"), ("Shop_BombchuBundle", "Item_BombchuBundle_Small"),
               ("Shop_ArrowBundle", "TBox_ArrowBundle_Medium"), ("Shop_Weapon_Shield_Deku", DS), ("Shop_Weapon_Shield_Hylian", "TBox_Shield_Hylian"))
SHELF_OTHER = "TBox_Rupee_Red"
SHOP_BASE, SHOP_SAMPLE = "Shop_Item_Base", "Shop_ArrowBundle_01"
SHOP_TABLES = ("ActorInfo", "GameActorInfo", "PouchActorInfo")
SHOP_ROW, SHOP_ROW_HEAPS = "Shop_DekuStick", "Shop_Armor_Goron"   # (a shelf's rows to go by; the heaps of a shelf that is another item)
SHOP_PARAM = "Component/ShopParam/%s.game__component__ShopParam.bgyml"
SHOP_TEXT = "ActorMsg/PouchContent.msbt"
ACTOR_FILE = "Actor/%s.engine__actor__ActorParam.bgyml"
ACTOR_REF = "Work/Actor/%s.engine__actor__ActorParam.gyml"
# A shelf's price is rolled by the seed, 1 to SHOP_PRICE_MAX rupees, whatever is put on it (its owner's word: always
# rolled, in one of two ways: 1, most of them low; 2, any price as likely as another). What Link can pay is what his
# wallet holds: 200 as a child (the wallet he starts with, in this game), 500 with the Adult's Wallet, 1000 with the
# Giant's (WALLETS: its owner's numbers). So with Shops the two wallets are gating items (SHOP_GATES): they are
# shuffled, by the two Gold Skulltula family's gifts that give them taking part (SHOP_WALLET_GIFTS, whether Quest
# rewards is on or not), and a shelf asks for the wallet its price needs (wallet_need) with what its shop asks for.
# A price up to 500 asks for the Adult's Wallet though the Giant's would do: too much, never too little. Seen in
# play: a green rupee bought for 150 gave one rupee and was sold out after, in its shop and when it was come back to.
# The most a shelf costs was 1000 and is 750 (its owner's word, 2026-11-13), and a price within the child's wallet
# comes up a little more often than its share of the range, in both ways (SHOP_CHILD_MORE: that often the price is
# rolled within the child's 200 alone). A seed made before keeps its prices.
WM, WL = "Item_Wallet_Medium", "Item_Wallet_Large"
SHOP_GATES = frozenset((WM, WL))
SHOP_WALLET_GIFTS = ("skulltula_house_10", "skulltula_house_30")
SHOP_PRICE_MAX = 750
SHOP_CHILD, SHOP_CHILD_MORE = 200, 0.15
# How low the Low prices are: the power an even roll is raised to. It was 3, the cube: one shelf in eight cost 1 rupee
# (seen in play: seven of a seed's 48 shelves, four of them Gold Skulltula tokens, and asked about). 2, the square,
# is gentler (its owner's word, 2026-11-13): 1 rupee on one shelf in 25, six in ten within the child's wallet.
SHOP_LOW_POWER = 2
WALLETS = ((200, NONE), (500, frozenset((WM,))), (SHOP_PRICE_MAX, frozenset((WL,))))


# How an item stands on its shelf (SHELF_POSE, for the name: there is no such table). A shelf's actor had the item's
# own pose and animation (ASInfoRef, ASRef, AnimationRef), which are those of the scene where Link gets it: they
# lift it, turn it and, for some, draw it twice. Seen in play with them: the Iron Boots twice, one pair under the
# other; the compass tilted and half behind its price board; the Light Arrows and the Deku Stick bundle well over
# their shelf. So a shelf's actor has none of the three (shop_pack), and the item is as its model is made: seen
# without them, the boots once, the compass flat on its board, the hammer, bow, key and Longshot lying on theirs.
# Then the model's box tells where it is (the list of actors has it, ModelAabbMin and ModelAabbMax):
# - one that reaches under its own origin is put that much higher (shelf_lift): a Gold Skulltula's token reaches
#   0.19 under and was half in its board; the Megaton Hammer's 0.28;
# - one made where it is worn is put that much lower (SHELF_WORN): the gauntlets' box is 1.17 m up, and without the
#   pose they were at the top of the picture; lowered by it, on their shelf (seen in play);
# - and an item's own number where its box is not how it shows (SHELF_LIFT): the three magic arrows' boxes take in
#   their glow, and they hung a hand over the shelf; the Deku Stick bundle stands where its origin is.
# The Lens of Truth took the longest. Its model is made where it is worn, before young Link's eyes: its box is 0.92
# to 1.04 m up, 22 cm wide, and faces forward. It is 11 cm tall: put down by its box at its own size it stood behind
# its shelf's price board, which is as tall, and was not seen (the tries before this took that for a model that does
# not show, and turned it, which swung it off its shelf). So its shelf's actor is 0.67 m lower (SHELF_LIFT), its
# lenses a hand over the board, facing the shop, at its own size. It was 1.5 times its size for a while, and the
# shop's arrows round the shelf looked at were then far under it (reported from play): they go by the model's box as
# the list of actors has it, which is the model's own size, so a model far from its origin is not made larger here.
# At its own size the arrows are round it. Seen so in the Kokiri shop, the Bazaar and the Goron shop.
SHELF_LIFT = {"Item_Arrow_Fire": 0.1, "Item_Arrow_Ice": 0.1, "Item_Arrow_Light": 0.1, "Item_DekuStickBundle_Small": 0.0, "Item_GlassTruth": -0.67, "Item_Range_Bow": 0.15, "Item_Sword_Kokiri": 0.15, "Item_Shield_Mirror": 0.35, "TBox_Shield_Hylian": 0.35,
              "TBox_Shield_Deku": 0.3}


def shelf_lift(item, floor):
    """how much higher an item's shelf actor is put: its own number, or what its model reaches under its origin
    (floor: the lowest of its box, or None), when that is a hand's breadth and not a model made elsewhere"""
    if item in SHELF_LIFT:
        return SHELF_LIFT[item]
    return round(-floor, 2) if floor is not None and -0.5 < floor < -0.02 else 0.0


def model_floor(data, item):
    """the lowest of an item's model's box in the game's list of actors (ActorInfo: ModelAabbMin.Y), or None"""
    tree, _ = byml_parse(data)
    for row in tree[1]:
        if row[1].get("__RowId", ("", ""))[1] == item:
            low = row[1].get("ModelAabbMin", ("dict", {}))[1].get("Y")
            return struct.unpack("<f", low[1])[0] if low and low[0] == 0xD2 else None
    return None


def model_box(data, item):
    """an item's model's box in the game's list of actors (ActorInfo: ModelAabbMin, ModelAabbMax): ((x, y, z) the
    lowest, (x, y, z) the highest), or None"""
    tree, _ = byml_parse(data)
    for row in tree[1]:
        if row[1].get("__RowId", ("", ""))[1] == item:
            ends = []
            for key in ("ModelAabbMin", "ModelAabbMax"):
                at = row[1].get(key, ("dict", {}))[1]
                if not all(axis in at and at[axis][0] == 0xD2 for axis in "XYZ"):
                    return None
                ends.append(tuple(struct.unpack("<f", at[axis][1])[0] for axis in "XYZ"))
            return tuple(ends)
    return None


# How large an item is on its shelf. A shelf's own goods are up to 1.1 m long (the Deku Stick); the Megaton Hammer
# (1.78 m) and the Fairy Bow (1.36 m) filled the shop's wall (seen in play). An item longer than SHELF_LONG is made
# SHELF_LONG long, and one smaller than SHELF_SMALL (the compass, 16 cm and flat: half hidden by its shelf's price
# board; the Stone of Agony, 8 cm) is made SHELF_SMALL, at most three times its size. The size is the shelf actor's
# Scale in the map file. An item's own number, where its box does not say it: the Small Key, tall and thin, stood
# over its shelf's whole height.
SHELF_LONG = 0.9
SHELF_SCALE = {"Item_Dungeon_SmallKey": 0.6, "Item_Dungeon_Compass": 1.5, "Item_GlassTruth": 1.0,
               "Item_Gauntlet_Gold": 1.0, "Item_Gauntlet_Silver": 1.0, "Item_Gauntlet_Goron": 1.0}
# (the Fairy Bow's model is long front to back, 1.36 m along its own Z: on the Kokiri shop's shelf it lay pointing at
# the viewer, its end alone to be seen behind the price board (its owner's picture, 2026-11-13). A quarter turn about
# the upright laid it across, flat: a thin line. With a quarter turn about Z too it lies across with its curve and
# string to the viewer: seen so on a shelf of the Bazaar and one of the Goron shop, whose own angles differ (of four
# turns tried on each, the one that showed it the same in both). The hammer, the sword and the stick bundle are long
# the same way and lie as they did: seen, and left.)
# (the Kokiri Sword is long the same way, 0.65 m: on the Kokiri shop's shelf a small dark shape behind the price board
# (its owner's picture, 2026-11-13). With the bow's turn it stands on that shop's shelves, blade up, plain to see:
# seen on two of them. Not seen with it in the Bazaar or the Goron shop, where the bow lies across with that turn.
# The Megaton Hammer with it stood on end, taller than its shelf's space, and is left lying; the Deku Stick bundle
# leans as the game's own stick does, with the turn or without, and is left.)
# (the three shields lay flat on their faces (reported from play: the Mirror Shield). A quarter turn about X stands the
# Mirror Shield and the Deku Shield up, their faces to the shop; the same turn showed the Hylian Shield's face upside
# down and the other way its back, so it has the other quarter turn and a half turn about the upright. Each seen so
# on shelves of the Kokiri shop, the Bazaar and the Goron shop, whose own angles differ, raised to stand over the
# price board.)
SHELF_TURN = {"Item_Range_Bow": (0.0, 1.57, 1.57), "Item_Sword_Kokiri": (0.0, 1.57, 1.57), "Item_Shield_Mirror": (1.57, 0.0, 0.0),
              "TBox_Shield_Deku": (1.57, 0.0, 0.0), "TBox_Shield_Hylian": (-1.57, 3.14, 0.0)}
# An item whose model is made where it is worn, not at its own origin (the gauntlets: 1.17 m up): its shelf's actor is
# put that much lower (shelf_fit). The gauntlets keep their size: their box is the pair's, 1.6 m from one to the other.
SHELF_WORN = 0.5


def shelf_fit(item, box):
    """(how much higher an item's shelf actor is put, how large it is made: 1.0 its own size), by its model's box
    (model_box, or None) and its own numbers"""
    scale = SHELF_SCALE.get(item, 1.0)
    floor = None
    if box:
        size = max(high - low for low, high in zip(*box))
        if item not in SHELF_SCALE and size > 0:
            if size > SHELF_LONG * 1.3:
                scale = round(SHELF_LONG / size, 2)
        floor = box[0][1]
    if item in SHELF_LIFT:
        return SHELF_LIFT[item], scale
    if floor is not None and floor > SHELF_WORN:
        return round(-floor * scale, 2), scale
    return round(shelf_lift(item, floor) * scale, 2), scale


# A shelf of bundles has a board beside it with how many are in one ("x 10": Shop_Board_Bundle_05, _10, _20, ...),
# an actor of its own in the map file. With another item on the shelf it stayed, and said x 10 under a Kokiri Sword
# (seen in play). The board next to a shelf that sells a shuffled item (within SHELF_BOARD_NEAR of it) is put far
# under the map: not taken out of the file, so nothing that names it is left without it.
SHELF_BOARD, SHELF_BOARD_NEAR, SHELF_BOARD_AWAY = "Shop_Board_Bundle_", 0.5, 2000.0


# ---- Progressive items: what the rules ask for when an upgrade found gives the next one Link has not ----
# The game's side (host/hos_main.c hos_oot_pouch_add) puts the next of an upgrade's family in the pouch whatever was
# found. So Link has the family's second when he has found two of it: a rule that asks for the Silver Gauntlets
# asks for them and for the Goron's Bracelet, the Giant's Wallet for the Adult's too (progressive_need). Only the
# ones the seed shuffles are added: the others are where the game has them, and the rules count on that already.
# Too much, never too little: with both found he has the second, whichever came first.
PROGRESSIVE_TIERS = (("Item_Gauntlet_Goron", "Item_Gauntlet_Silver", "Item_Gauntlet_Gold"), ("Item_Wallet_Medium", "Item_Wallet_Large"),
                     ("Item_Scale_Silver", "Item_Scale_Gold"))


def progressive_need(need, shuffled):
    """what a rule asks for with Progressive items: each upgrade it names, and the ones under it of its family that
    the seed shuffles"""
    more = set(need)
    for tiers in PROGRESSIVE_TIERS:
        for k, item in enumerate(tiers):
            if item in need:
                more.update(i for i in tiers[:k] if i in shuffled)
    return frozenset(more)


def shelf_item(actor):
    """what goes into the pool for a shelf's own actor: the chests' kind of it, or a red rupee"""
    return next((item for start, item in SHELF_ITEMS if actor.startswith(start)), SHELF_OTHER)


def shop_actor(name):
    """the shelf actor made for an item, or for a shelf (its shop's key and its place: one shelf, one price)"""
    return "Shop_Rando_" + name


def shop_price(rng, mode):
    """A shelf's price, 1 to SHOP_PRICE_MAX. mode 1: most of them low (an even roll to the power SHOP_LOW_POWER: about
    six in ten within the child's wallet, one in seven past the Adult's), in fives from 10 up; 2: any price as likely as
    another, but for the child's wallet's, which come up a little more often (about four in ten). In both, SHOP_CHILD_MORE
    of the prices are rolled within the child's wallet alone."""
    most = SHOP_CHILD if rng.random() < SHOP_CHILD_MORE else SHOP_PRICE_MAX
    if mode == 2:
        return rng.randint(1, most)
    price = 1 + int((most - 1) * rng.random() ** SHOP_LOW_POWER)
    return price if price < 10 else min(SHOP_PRICE_MAX, 5 * round(price / 5))


def wallet_need(price):
    """the wallet a price asks for: nothing while the child's holds it"""
    return next((need for most, need in WALLETS if price <= most), WALLETS[-1][1])


def shop_pack(item, item_pack, base_pack, sample_pack, price, pouch=None, name=None):
    """An item's shelf actor (name: its actor's, shop_actor(item) when not given): (its pack, the names of the three files it has that no other pack has, the name its
    texts go by). The pack is the shelf base's files and the item's; its actor has the base's as its parent and the
    item's own name, model, animation and place in the pouch; its table of game parameters is the item's entries,
    the base's table as its parent, and a price of its own. pouch: pouch files to take in place of the item's ({name:
    bytes}: the ones a pick-up's pack changed, of which the game uses the first copy it loads)."""
    base, own, sample = sarc_read(base_pack), sarc_read(item_pack), sarc_read(sample_pack)
    name = name or shop_actor(item)
    chain = actor_chain(item, own)
    if not chain:
        raise ValueError("%s: its pack has no actor of that name" % item)
    files = collections.OrderedDict(base)
    for k, v in own.items():
        files.setdefault(k, v)
    for k, v in (pouch or {}).items():
        if k in files:
            files[k] = v

    def part(key):
        for _, tree, _ in chain:
            ref = tree[1].get("Components", ("dict", {}))[1].get(key)
            if ref and ref[0] == "string" and ref[1]:
                return ref
        return None

    if not part("ModelInfoRef") or not part("PouchContentRef"):
        raise ValueError("%s has no model or no place in the pouch: it cannot be put on a shelf" % item)
    actor_name = ACTOR_FILE % name
    table_name = "GameParameter/GameParameterTable/%s.engine__actor__GameParameterTable.bgyml" % name
    price_name = "GameParameter/PriceParam/%s.game__pouchcontent__PriceParam.bgyml" % name
    sample_actor, sample_table = ACTOR_FILE % SHOP_SAMPLE, "GameParameter/GameParameterTable/%s.engine__actor__GameParameterTable.bgyml" % SHOP_SAMPLE
    sample_price = "GameParameter/PriceParam/%s.game__pouchcontent__PriceParam.bgyml" % SHOP_SAMPLE
    if ACTOR_FILE % SHOP_BASE not in base or not {sample_actor, sample_table, sample_price} <= set(sample):
        raise ValueError("the shelf base's pack or the sample shelf's is not what it was")
    _, version = byml_parse(sample[sample_actor])
    # (not the item's pose and animation, ASInfoRef, ASRef and AnimationRef: they are its "item got" scene's: SHELF_POSE, above SHELF_LIFT)
    comps = collections.OrderedDict((key, part(key)) for key in ("ActorNameRef", "ModelInfoRef", "PouchContentRef") if part(key))
    comps["GameParameterTableRef"] = ("string", "?" + table_name)
    files[actor_name] = byml_build(("dict", collections.OrderedDict((("$parent", ("string", ACTOR_REF % SHOP_BASE)),
                                                                     ("Components", ("dict", collections.OrderedDict(sorted(comps.items()))))))), version)
    entries = collections.OrderedDict()
    table_ref = part("GameParameterTableRef")
    if table_ref and ref_file(table_ref[1]) in own:
        entries.update(byml_parse(own[ref_file(table_ref[1])])[0][1].get("Components", ("dict", {}))[1])
    entries["PriceParam"] = ("string", "?" + price_name)
    table, table_version = byml_parse(sample[sample_table])   # (the sample's: the shelf base's table as its parent)
    table[1]["Components"] = ("dict", collections.OrderedDict(sorted(entries.items())))
    files[table_name] = byml_build(table, table_version)
    cost, cost_version = byml_parse(sample[sample_price])
    cost[1]["BuyingPrice"] = (cost[1]["BuyingPrice"][0], struct.pack("<I", price))
    files[price_name] = byml_build(cost, cost_version)
    named = part("ActorNameRef")
    return sarc_write(files), [actor_name, table_name, price_name], ref_file(named[1]).split("/")[-1].split(".")[0] if named else item


def shop_rows(data, kind, item, price, name=None):
    """One of the game's three lists of actors (kind: SHOP_TABLES) with the row of an item's shelf actor (name: its
    actor's, shop_actor(item) when not given), in its place
    by name: the item's own row in the list of actors (its model, with a shelf's heaps where they are larger) and
    in the pouch's (with what it costs), a shelf's in the game's."""
    tree, version = byml_parse(data)
    name = name or shop_actor(item)
    by = {r[1]["__RowId"][1]: r for r in tree[1]}
    need = (SHOP_ROW,) if kind == "GameActorInfo" else (item, SHOP_ROW_HEAPS if kind == "ActorInfo" else SHOP_ROW)
    if any(n not in by for n in need):
        raise ValueError("the game's %s has no row of %s" % (kind, " or of ".join(n for n in need if n not in by)))
    number = lambda node, value: (node[0], struct.pack("<I", value))
    if kind == "ActorInfo":
        row = ("dict", collections.OrderedDict(by[item][1]))
        for k in ("InstanceHeapSize", "PreActorRenderInfoHeapSize"):
            if k in row[1] and k in by[SHOP_ROW_HEAPS][1]:
                row[1][k] = number(row[1][k], max(struct.unpack("<I", row[1][k][1])[0], struct.unpack("<I", by[SHOP_ROW_HEAPS][1][k][1])[0]) + 32768)
    elif kind == "GameActorInfo":
        row = ("dict", collections.OrderedDict(by[SHOP_ROW][1]))
    else:
        row = collections.OrderedDict(by[item][1])
        row["BuyingPrice"] = number(by[SHOP_ROW][1]["BuyingPrice"], price)
        row["SellingPrice"] = number(by[SHOP_ROW][1]["SellingPrice"], 1)
        row = ("dict", collections.OrderedDict(sorted(row.items())))
    row[1]["__RowId"] = ("string", name)
    rows = [r for r in tree[1] if r[1]["__RowId"][1] != name] + [row]
    rows.sort(key=lambda r: r[1]["__RowId"][1])
    return byml_build((tree[0], rows), version)


# ---- Bombchus: a limit of their own ----
# The game counts Bombchus against the Bomb Bag: their row of the list of pouch actors (RSDB/PouchActorInfo) names
# the bombs' limit (MaxNumGameData "Bomb", the flag PouchContentMaxNum.Bomb, 0 until a bag is got) and the small bag
# as what they are carried in. So Bombchus found before a Bomb Bag were lost: a chest of five gave none, the Items
# screen "0/0" (reported from play, the save without a bag). The game has another kind of limit, one of the item's
# own (FixedMaxNum: the Magic Beans' 10, the Gold Skulltula tokens' 100). Every seed gives the Bombchus that
# (BOMBCHU_LIMIT) and takes the bag's two fields away: seen without a window on a save with its Bomb Bag taken out,
# three Bombchus given one by one were 1, 2, 3, a bundle of five made 8, and bombs given the same way stayed 0 (the
# bag is still what bombs ask for: the rules' gating item is as it was). The same change to the file of the
# Bombchu's own pack did nothing: the list is what the game reads. Not seen: a Bombchu used without a bag.
BOMBCHU, BOMBCHU_LIMIT = "Item_Bombchu", 50
POUCH_TABLE = "PouchActorInfo"


def chu_limit(data, limit=BOMBCHU_LIMIT):
    """the list of pouch actors with the Bombchus' limit their own: the new bytes (the same bytes back when it is so
    already). A list without their row, or whose row is not as the game's, is an error."""
    tree, version = byml_parse(data)
    rows = [r for r in tree[1] if r[1].get("__RowId", ("", ""))[1] == BOMBCHU]
    if len(rows) != 1:
        raise ValueError("the list of pouch actors has %d rows of %s" % (len(rows), BOMBCHU))
    row = rows[0][1]
    if "FixedMaxNum" in row and "MaxNumGameData" not in row and "SmallBagActor" not in row:
        return data
    if row.get("MaxNumGameData") != ("string", "Bomb") or "SmallBagActor" not in row or "FixedMaxNum" in row:
        raise ValueError("the Bombchus' row is not counted against the Bomb Bag as this was written for")
    kept = [(k, v) for k, v in row.items() if k not in ("MaxNumGameData", "SmallBagActor")] + [("FixedMaxNum", (0xD1, struct.pack("<i", limit)))]
    row.clear()
    row.update(sorted(kept))
    return byml_build(tree, version)


def shop_goods(data, sells):
    """A keeper's goods list with the places of `sells` ({place: (the game's own shelf actor there, the new one)})
    selling the new actor, one in stock, from the start (what the game waits for before it shows a shelf, and what
    it takes off its price, are left out). ValueError: a place whose actor is not the one named."""
    tree, version = byml_parse(data)
    goods = tree[1].get("GoodsList")
    if not goods or goods[0] != "array":
        raise ValueError("no goods list")
    stock = next((g[1]["StockNum"][0] for g in goods[1] if "StockNum" in g[1]), 0xD3)
    for index, (old, new) in sells.items():
        if index >= len(goods[1]) or goods[1][index][1].get("Actor", ("", ""))[1] != ACTOR_REF % old:
            raise ValueError("the goods list's place %d is not %s" % (index, old))
        entry = collections.OrderedDict((k, v) for k, v in goods[1][index][1].items() if k not in ("Release", "PriceOffset", "ConditionalPriceOffsetList"))
        entry["Actor"] = ("string", ACTOR_REF % new)
        entry["StockNum"] = (stock, struct.pack("<I", 1))
        goods[1][index] = ("dict", collections.OrderedDict(sorted(entry.items())))
    return byml_build(tree, version)


def shelf_actors(data, sells, lifts=None, scales=None, turns=None):
    """A map file with its shelves of `sells` ({(the game's own shelf actor, its place in the row): the new one})
    made the new actor: (the file written anew, or None when it has none of them; how many). lifts: {a new actor:
    how much higher its shelf's actor is put}; scales: {a new actor: how large it is made}, where not its own size.
    The board of how many a bundle holds beside such a shelf is put out of sight (SHELF_BOARD)."""
    tree, version = byml_parse(data)
    actors = tree[1].get("Actors")
    n = 0
    number = lambda node: struct.unpack("<f", node[1])[0] if isinstance(node[1], bytes) and len(node[1]) == 4 else None
    place = lambda actor: ([number(x) for x in actor[1]["Translate"][1]]
                           if actor[1].get("Translate", ("", ()))[0] == "array" and len(actor[1]["Translate"][1]) == 3 else None)
    changed = []   # (where the shelves that sell a shuffled item were, before any lift)
    for actor in actors[1] if actors and actors[0] == "array" else ():
        gyaml = actor[1].get("Gyaml", ("", ""))[1]
        index = actor[1].get("Dynamic", ("dict", {}))[1].get("ShopItemIndex")
        if sells.get((gyaml, struct.unpack("<I", index[1])[0] if index and isinstance(index[1], bytes) and len(index[1]) == 4 else 0)):
            at = place(actor)
            if at and None not in at:
                changed.append(at)
    for actor in actors[1] if actors and actors[0] == "array" else ():
        gyaml = actor[1].get("Gyaml", ("", ""))
        at = place(actor)
        if (gyaml[0] == "string" and gyaml[1].startswith(SHELF_BOARD) and at and None not in at and
                any(abs(at[0] - x) <= SHELF_BOARD_NEAR and abs(at[2] - z) <= SHELF_BOARD_NEAR and abs(at[1] - y) <= SHELF_BOARD_NEAR for x, y, z in changed)):
            node = actor[1]["Translate"][1]
            node[1] = (node[1][0], struct.pack("<f", at[1] - SHELF_BOARD_AWAY))
    for actor in actors[1] if actors and actors[0] == "array" else ():
        gyaml = actor[1].get("Gyaml", ("", ""))[1]
        index = actor[1].get("Dynamic", ("dict", {}))[1].get("ShopItemIndex")
        new = sells.get((gyaml, struct.unpack("<I", index[1])[0] if index and isinstance(index[1], bytes) and len(index[1]) == 4 else 0))
        if new and actor[1].get("Gyaml", ("", ""))[0] == "string":
            actor[1]["Gyaml"] = ("string", new)
            at = actor[1].get("Translate")
            if (lifts or {}).get(new) and at and at[0] == "array" and len(at[1]) == 3 and isinstance(at[1][1][1], bytes) and len(at[1][1][1]) == 4:
                at[1][1] = (at[1][1][0], struct.pack("<f", struct.unpack("<f", at[1][1][1])[0] + lifts[new]))
            size = (scales or {}).get(new)
            if size and size != 1.0:
                actor[1]["Scale"] = ("array", [(0xD2, struct.pack("<f", size))] * 3)
            turn = (turns or {}).get(new)
            if turn:   # (turned on its shelf: added to the shelf's own angles, x, y, z in radians)
                was = actor[1].get("Rotate")
                angles = [number(x) or 0.0 for x in was[1]] if was and was[0] == "array" and len(was[1]) == 3 else [0.0, 0.0, 0.0]
                actor[1]["Rotate"] = ("array", [(0xD2, struct.pack("<f", a + b)) for a, b in zip(angles, turn)])
            n += 1
    return (byml_build(tree, version) if n else None), n


def msbt_hash(label, groups):
    """the group of a text file's labels that a label is in"""
    h = 0
    for ch in label.encode():
        h = (h * 0x492 + ch) & 0xffffffff
    return h % groups


def msbt_add(data, label, text):
    """The text file with another line, `label`, of the bytes `text` (its closing zero byte is added), the last of
    its texts. A label it has is given the text (msbt_set). ValueError: a file with more than labels and texts (a
    line's attributes are not known how to write)."""
    try:
        msbt_text(data, label)
        return msbt_set(data, label, text)
    except ValueError as e:
        if "has no line" not in str(e):
            raise
    out = bytearray(data[:0x20])
    at = 0x20
    for _ in range(struct.unpack_from("<H", data, 0x0e)[0]):
        kind, size = data[at:at + 4], struct.unpack_from("<I", data, at + 4)[0]
        body = at + 0x10
        sec = bytearray(data[body:body + size])
        if kind == b"LBL1":
            groups = struct.unpack_from("<I", sec, 0)[0]
            labels, n = [[] for _ in range(groups)], 0
            for g in range(groups):
                count, off = struct.unpack_from("<II", sec, 4 + 8 * g)
                for _k in range(count):
                    ln = sec[off]
                    labels[g].append(bytes(sec[off:off + 1 + ln + 4]))
                    off += 1 + ln + 4
                    n += 1
            labels[msbt_hash(label, groups)].append(bytes([len(label.encode())]) + label.encode() + struct.pack("<I", n))
            sec = bytearray(struct.pack("<I", groups) + bytes(8 * groups))
            for g in range(groups):
                struct.pack_into("<II", sec, 4 + 8 * g, len(labels[g]), len(sec))
                sec += b"".join(labels[g])
        elif kind == b"TXT2":
            n = struct.unpack_from("<I", sec, 0)[0]
            offs = [struct.unpack_from("<I", sec, 4 + 4 * i)[0] for i in range(n)] + [size]
            texts = [bytes(sec[offs[i]:offs[i + 1]]) for i in range(n)] + [bytes(text) + b"\0"]
            sec = bytearray(struct.pack("<I", n + 1) + bytes(4 * (n + 1)))
            for i, t in enumerate(texts):
                struct.pack_into("<I", sec, 4 + 4 * i, len(sec))
                sec += t
        else:
            raise ValueError("a text file with a section %r: a line cannot be added" % bytes(kind))
        fill = data[body + size:body + (size + 15 & ~15)][:1] or b"\xab"
        out += kind + struct.pack("<I", len(sec)) + data[at + 8:at + 0x10] + sec + fill * (-len(sec) % 16)
        at = body + (size + 15 & ~15)
    struct.pack_into("<I", out, 0x12, len(out))
    return bytes(out)


def shop_caption(data, name):
    """The pouch's text file with the words a shop shows under an item's name, <name>_ShopCaption, for an item that
    has none: its own description (<name>_Caption), or what is said when it is got (<name>_GetCaption). None: it
    has the line, or neither of the other two."""
    try:
        msbt_text(data, name + "_ShopCaption")
        return None
    except ValueError:
        pass
    for other in ("_Caption", "_GetCaption"):
        try:
            a, b = msbt_text(data, name + other)
        except ValueError:
            continue
        return msbt_add(data, name + "_ShopCaption", bytes(data[a:b]).rstrip(b"\0"))
    return None


# ---- a scrub's words ----
# A sale's text is the scrub's own, named in the sale's call (SellerMessageId): "This bag will allow you to carry more
# Deku sticks. It's 40 rupees. Wanna buy it?" for a sale that is now a Bomb Bag (seen in play). The texts are in the
# language archives (Mals/<language>.Product.<n>.sarc.zs), a file a subject (EventFlowMsg/Enemy_Event.msbt: UTF-8, a
# line's tags the byte 0x0E, then its group, type and size as 16-bit numbers, then its bytes). No line of the scrubs'
# is without its item, so the words before "It's <price> rupees. Wanna buy it?" of a sale that sells another item are
# made SCRUB_WORDS. The line is shorter then, and the file is written anew with it (msbt_set): it and its archive are
# smaller, never bigger, so the size table's entry still holds them. The price and the question, with their tags, are
# as they were. English only (the two English archives): the other languages keep the scrub's own words. The two
# Pieces of Heart are one line. The stick scrub has two: ..._02 is what he says the first time, two pages ("Do you
# know about Deku sticks? ..." and "And this bag can carry a lot of Deku sticks! It's ..."; seen in play, the first
# of them left as it was), made the one page.
SCRUB_TEXT = "EventFlowMsg/Enemy_Event.msbt"
SCRUB_LANGS = ("USen", "EUen")
SCRUB_WORDS = "I've got something special for you."
SCRUB_LINES = {"scrub_heart_field": ("Enemy_Scrub_Business_Heart_01",), "scrub_heart_secret": ("Enemy_Scrub_Business_Heart_01",),
               "scrub_sticks": ("Enemy_Scrub_Business_DekuStickPouch_01", "Enemy_Scrub_Business_DekuStickPouch_02"),
               "scrub_nuts": ("Enemy_Scrub_Business_DekuNutsPouch_01",)}


def msbt_text(data, label):
    """where a line of a text file (MSBT) is: (its first byte, the byte after its last), by its label. ValueError: not
    such a file, or no such label."""
    if data[:8] != b"MsgStdBn" or data[8:10] != b"\xff\xfe" or data[0x0c] != 0:
        raise ValueError("not a little-endian UTF-8 text file")
    at, index, texts = 0x20, None, None
    for _ in range(struct.unpack_from("<H", data, 0x0e)[0]):
        kind, size = data[at:at + 4], struct.unpack_from("<I", data, at + 4)[0]
        body = at + 0x10
        if kind == b"LBL1":
            for g in range(struct.unpack_from("<I", data, body)[0]):
                n, off = struct.unpack_from("<II", data, body + 4 + 8 * g)
                p = body + off
                for _k in range(n):
                    ln = data[p]
                    if data[p + 1:p + 1 + ln] == label.encode():
                        index = struct.unpack_from("<I", data, p + 1 + ln)[0]
                    p += 1 + ln + 4
        elif kind == b"TXT2":
            texts = (body, size)
        at = body + (size + 15 & ~15)
    if index is None or texts is None:
        raise ValueError("the text file has no line %s" % label)
    body, size = texts
    n = struct.unpack_from("<I", data, body)[0]
    if index >= n:
        raise ValueError("the line %s is past the file's texts" % label)
    start = struct.unpack_from("<I", data, body + 4 + 4 * index)[0]
    end = struct.unpack_from("<I", data, body + 4 + 4 * (index + 1))[0] if index + 1 < n else size
    return body + start, body + end


def msbt_set(data, label, text):
    """The text file with the line `label` made the bytes `text` (its closing zero byte is added): the file written
    anew, the texts after it moved, the sections' and the file's sizes set. The other lines and sections are as they
    were."""
    start, end = msbt_text(data, label)
    out = bytearray(data[:0x20])
    at = 0x20
    for _ in range(struct.unpack_from("<H", data, 0x0e)[0]):
        kind, size = data[at:at + 4], struct.unpack_from("<I", data, at + 4)[0]
        body = at + 0x10
        sec = bytearray(data[body:body + size])
        if kind == b"TXT2":
            n = struct.unpack_from("<I", sec, 0)[0]
            offs = [struct.unpack_from("<I", sec, 4 + 4 * i)[0] for i in range(n)] + [size]
            index = next(i for i in range(n) if body + offs[i] == start)
            texts = [bytes(sec[offs[i]:offs[i + 1]]) for i in range(n)]
            texts[index] = bytes(text) + b"\0"
            sec = bytearray(struct.pack("<I", n) + bytes(4 * n))
            for i, t in enumerate(texts):
                struct.pack_into("<I", sec, 4 + 4 * i, len(sec))
                sec += t
        fill = data[body + size:body + (size + 15 & ~15)][:1] or b"\xab"   # (what the file fills a section's end with)
        out += kind + struct.pack("<I", len(sec)) + data[at + 8:at + 0x10] + sec + fill * (-len(sec) % 16)
        at = body + (size + 15 & ~15)
    struct.pack_into("<I", out, 0x12, len(out))
    return bytes(out)


def scrub_words(data, label, words=SCRUB_WORDS):
    """The text file with the sale line `label` saying `words` before its price ("It's ..."): the new bytes (the
    file is shorter by what the scrub's own words were longer: msbt_set), or None when it says so already. The tags
    at the line's start and everything from "It's" on are as they were; a line of two pages is one."""
    start, end = msbt_text(data, label)
    a = start
    while a + 8 <= end and data[a] == 0x0E:   # (the tags the line starts with)
        a += 7 + struct.unpack_from("<H", data, a + 5)[0]
    b = data.find(b"It's", a, end)
    if b < 0:
        raise ValueError("the line %s names no price" % label)
    last = end
    while last > b and data[last - 1] == 0:   # (its closing zero byte, and what fills the section after the last line)
        last -= 1
    sep = b"\n" if data[b - 1:b] == b"\n" else b" "
    new = bytes(data[start:a]) + words.encode("utf-8") + sep + bytes(data[b:last])
    if len(new) > last - start:
        raise ValueError("the line %s would grow: the words are longer than the scrub's own" % label)
    if new == bytes(data[start:last]):
        return None
    return msbt_set(data, label, new)


def gift_hash(key):
    """a gift's place among the chests' hashes: its own, the same in every seed (no chest's is this high)"""
    return 0xF1F7000000000000 | zlib.crc32(key.encode())


def quest_need(need, area):
    """what a chest or a Gold Skulltula asks for (by the rules made before Quest rewards) with the gifts' two gating
    items named: the bracelet wherever bombs are, and in Dodongo's Cavern; the Silver Scale wherever an adult is"""
    need = set(need)
    if BB in need or area == "DodongoCavern":
        need.add(BR)
    if need >= ADULT:
        need.add(SSC)
    return frozenset(need)


def rule(area, event):
    """what a chest of this area with this event asks for; an area the rules do not know: everything"""
    default, by_event = RULES.get(area, (PROGRESSION, {}))
    return by_event.get(event, default)


def collect(placed):
    """What Link can get from nothing: placed is [(what the chest asks for, its item)]. Returns the spheres: the
    items each round of opening every chest he can reach adds."""
    have, spheres = set(), []
    while True:
        new = sorted({item for need, item in placed if item in PROGRESSION and item not in have and need <= have})
        if not new:
            return spheres
        have.update(new)
        spheres.append(new)


def reach(have, placed):
    """have, and every item that can then be got from the chests of placed"""
    have = set(have)
    grew = True
    while grew:
        grew = False
        for need, item in placed:
            if item not in have and need <= have:
                have.add(item)
                grew = True
    return have


def stays_why(c, events, placement=PLACEMENT):
    """Why a chest keeps its own item whatever the settings, or None. events: chests that start an event take part too.
    placement: the version of the rules (a seed made by an earlier one is made again as it was)."""
    if placement == 2 and c.event in LOCKED_ROOMS:
        return "its room cannot be left without the item it holds"
    kept = [k for k in KEEP_IF if k in c.params]
    if "GetEventName" in kept and (c.event in PLAIN_EVENTS or events and not c.event.startswith("MiniGame")):
        kept.remove("GetEventName")
    if kept == ["GetEventName"]:
        return "starts an event (--event-chests lets them take part)"
    if kept:
        return "a mini-game's, or depends on what Link has"
    if "MiniGame" in c.item:
        return "a mini-game's item"
    return None


def table(d, at):
    n = int.from_bytes(d[at + 1:at + 4], "little")
    out = []
    for k in range(n):
        s = at + struct.unpack_from("<I", d, at + 4 + 4 * k)[0]
        out.append(d[s:d.index(b"\0", s)].decode("utf-8", "replace"))
    return out


def entries(d, at, keys):
    """a dictionary node's (key, type, value, where its value is)"""
    if d[at] != 0xC1:
        return
    for k in range(int.from_bytes(d[at + 1:at + 4], "little")):
        e = at + 4 + 8 * k
        key = int.from_bytes(d[e:e + 3], "little")
        yield keys[key] if key < len(keys) else "", d[e + 3], struct.unpack_from("<I", d, e + 4)[0], e + 4


def chests(d):
    """Every actor with a Dynamic.Drop__DropActor (chests, and pots and the like). And the key and string tables."""
    if d[:2] != b"YB":
        raise ValueError("not a little-endian BYML")
    key_at, str_at, root = struct.unpack_from("<III", d, 4)
    keys, strings = table(d, key_at), table(d, str_at)
    found = []
    for name, kind, value, _ in entries(d, root, keys):
        if name != "Actors" or kind != 0xC0:
            continue
        n = int.from_bytes(d[value + 1:value + 4], "little")
        vals = value + 4 + (n + 3 & ~3)
        for i in range(n):
            if d[value + 4 + i] != 0xC1:
                continue
            actor = struct.unpack_from("<I", d, vals + 4 * i)[0]
            ident, gyaml, dyn, pos = None, "", None, ()
            for k, t, v, where in entries(d, actor, keys):
                if k == "Hash" and t == 0xD5:
                    ident = struct.unpack_from("<Q", d, v)[0]
                elif k == "Hash" and t == 0xD3:
                    ident = v
                elif k == "Gyaml" and t == 0xA0:
                    gyaml = strings[v]
                elif k == "Translate" and t == 0xC0 and int.from_bytes(d[v + 1:v + 4], "little") == 3:
                    pos = tuple(round(x, 1) for x in struct.unpack_from("<3f", d, v + 8))
                elif k == "Dynamic" and t == 0xC1:
                    dyn = (where, v)
            if not dyn:
                continue
            item, event, params = None, "", []
            for dk, dt, dv, _ in entries(d, dyn[1], keys):
                params.append(dk)
                if dk == "Drop__DropActor" and dt == 0xA0:
                    item = strings[dv] if dv < len(strings) else "<%d>" % dv
                elif dk == "GetEventName" and dt == 0xA0:
                    event = strings[dv] if dv < len(strings) else ""
            if item is not None:
                found.append(Chest(ident, gyaml, dyn[0], dyn[1], item, tuple(params), pos, event))
    return found, keys, strings


def string_table(strings):
    """a BYML string table: 0xC2, the count, an offset for each string and one for the end, the strings"""
    head = 4 + 4 * (len(strings) + 1)
    offsets, at, blob = [], head, bytearray()
    for s in strings:
        offsets.append(at)
        raw = s.encode("utf-8") + b"\0"
        blob += raw
        at += len(raw)
    offsets.append(at)
    out = bytes([0xC2]) + len(strings).to_bytes(3, "little") + b"".join(struct.pack("<I", o) for o in offsets) + bytes(blob)
    return out + b"\0" * (-len(out) % 4)


def rewrite(data, gives):
    """data (a BYML map file) with each chest of `gives` ({hash: item}) holding its item: the new bytes, or None when
    nothing in it changes. Read back before it is returned: those chests hold their items, every other actor what it held."""
    found, keys, strings = chests(data)
    todo = [c for c in found if c.hash is not None and gives.get(c.hash, c.item) != c.item]
    if not todo:
        return None
    out = bytearray(data)
    out += b"\0" * (-len(out) % 4)
    names = list(strings)
    for c in todo:
        if gives[c.hash] not in names:
            names.append(gives[c.hash])
    if len(names) > len(strings):   # (after the names it has: every index the file uses stays right)
        at = len(out)
        out += string_table(names)
        struct.pack_into("<I", out, 8, at)
    for c in todo:
        n = int.from_bytes(data[c.dyn_at + 1:c.dyn_at + 4], "little")
        block = bytearray(data[c.dyn_at:c.dyn_at + 4 + 8 * n])
        for k, (dk, dt, dv, _) in enumerate(entries(data, c.dyn_at, keys)):
            if dk == "Drop__DropActor":
                struct.pack_into("<I", block, 4 + 8 * k + 4, names.index(gives[c.hash]))
        at = len(out)
        out += block
        struct.pack_into("<I", out, c.dyn_where, at)
    again, _, _ = chests(bytes(out))
    if len(again) != len(found):
        raise ValueError("did not read back with the same actors")
    for was, now in zip(found, again):
        expect = gives.get(was.hash, was.item) if was.hash is not None else was.item
        if now.item != expect or now.hash != was.hash or now.params != was.params or now.event != was.event:
            raise ValueError("did not read back as written (%r: %s, expected %s)" % (now.hash, now.item, expect))
    return bytes(out)


def fix(data, fixes=None):
    """data (a BYML map file) with the truth values of `fixes` ({hash: {Dynamic key: value}}) set: the new bytes, or
    None when the file has none of those actors or they already say so. Each actor gets a Dynamic block of its own
    (an equal block is stored once for several actors). Read back before it is returned."""
    fixes = FIXES if fixes is None else fixes
    if data[:2] != b"YB":
        raise ValueError("not a little-endian BYML")
    key_at, _, root = struct.unpack_from("<III", data, 4)
    keys = table(data, key_at)

    def actors(d):
        """(hash, where the Dynamic block's offset is, the block) of the actors of `fixes`"""
        for name, kind, value, _ in entries(d, root, keys):
            if name != "Actors" or kind != 0xC0:
                continue
            n = int.from_bytes(d[value + 1:value + 4], "little")
            vals = value + 4 + (n + 3 & ~3)
            for i in range(n):
                if d[value + 4 + i] != 0xC1:
                    continue
                ident, dyn = None, None
                for k, t, v, where in entries(d, struct.unpack_from("<I", d, vals + 4 * i)[0], keys):
                    if k == "Hash" and t == 0xD5:
                        ident = struct.unpack_from("<Q", d, v)[0]
                    elif k == "Dynamic" and t == 0xC1:
                        dyn = (where, v)
                if ident in fixes and dyn:
                    yield ident, dyn[0], dyn[1]

    def values(d, block):
        return {k: v != 0 for k, t, v, _ in entries(d, block, keys) if t == 0xD0}

    todo = [(h, where, block) for h, where, block in actors(data)
            if any(values(data, block).get(k) != v for k, v in fixes[h].items())]
    if not todo:
        return None
    before, _, _ = chests(data)
    out = bytearray(data)
    out += b"\0" * (-len(out) % 4)
    for h, where, block in todo:
        n = int.from_bytes(data[block + 1:block + 4], "little")
        new = bytearray(data[block:block + 4 + 8 * n])
        for k, (dk, dt, _, _) in enumerate(entries(data, block, keys)):
            if dk in fixes[h]:
                if dt != 0xD0:
                    raise ValueError("%s of %#x is not a truth value" % (dk, h))
                struct.pack_into("<I", new, 4 + 8 * k + 4, int(fixes[h][dk]))
        at = len(out)
        out += new
        struct.pack_into("<I", out, where, at)
    out = bytes(out)
    for h, _, block in actors(out):
        if any(values(out, block).get(k) != v for k, v in fixes[h].items()):
            raise ValueError("the fix of %#x did not read back as written (has it that key?)" % h)
    after, _, _ = chests(out)
    if [(c.hash, c.item, c.params, c.event) for c in after] != [(c.hash, c.item, c.params, c.event) for c in before]:
        raise ValueError("a fix changed a chest")
    return out


class NotInPlace(ValueError):
    """a drop that add_drop_in_place does not write: the file is written anew for it (add_drop_anew)"""


def add_drop(data, drops, anew=False):
    """data (a BYML map file) with each actor of `drops` ({hash: item}) given that item as what it drops: its Dynamic
    block gets a Drop__DropActor (the key a chest names its item by; an enemy has the same one), or has the one it had
    changed. The new bytes, or None when the file has none of those actors. Written into the file as it is where
    that can be done (add_drop_in_place), and the whole file anew where an actor has no Dynamic block or the file no
    such key (add_drop_anew; anew: that way whatever the file has, for a test)."""
    if not drops or not any(struct.pack("<Q", h) in data for h in drops):
        return None
    if not anew:
        try:
            return add_drop_in_place(data, drops)
        except NotInPlace:
            pass
    return add_drop_anew(data, drops)


def add_drop_anew(data, drops):
    """add_drop by reading the whole file and writing it again (byml_parse, byml_build): an actor without a Dynamic
    block gets one, and the key table gets Drop__DropActor in its place. The file grows: the game's stores equal
    dictionaries once, and this does not. Everything else reads back as it was, or it is an error."""
    tree, version = byml_parse(data)
    actors = tree[1].get("Actors") if tree and tree[0] == "dict" else None
    done = set()
    for actor in actors[1] if actors and actors[0] == "array" else []:
        ident = actor[1].get("Hash") if actor[0] == "dict" else None
        if not ident or ident[0] not in (0xD3, 0xD5):
            continue
        h = int.from_bytes(ident[1], "little")
        if h in drops:
            dyn = actor[1].get("Dynamic")
            if dyn is None or dyn[0] != "dict":
                dyn = actor[1]["Dynamic"] = ("dict", collections.OrderedDict())
            dyn[1]["Drop__DropActor"] = ("string", drops[h])
            done.add(h)
    if not done:
        return None
    out = byml_build(tree, version)

    def plain(node):   # (a dictionary's keys in any order: the file has them in its key table's)
        if node[0] == "dict":
            return {k: plain(v) for k, v in node[1].items()}
        return [plain(v) for v in node[1]] if node[0] == "array" else node
    if plain(byml_parse(out)[0]) != plain(tree):
        raise ValueError("the file written anew does not read back as it was made")
    before, _, _ = chests(data)
    after, _, _ = chests(out)
    got = {c.hash: c.item for c in after}
    if any(got.get(h) != drops[h] for h in done):
        raise ValueError("a drop did not read back as written")
    was = {c.hash: (c.item, c.event, c.gyaml, c.params, c.pos) for c in before}
    now = {c.hash: (c.item, c.event, c.gyaml, c.params, c.pos) for c in after}
    if any(now.get(h) != v for h, v in was.items() if h not in done) or set(now) - set(was) - done:
        raise ValueError("giving a drop changed another actor's")
    return out


def add_drop_in_place(data, drops):
    """add_drop without writing the file anew: the actor gets a Dynamic block of its own at the end of the file, and
    an item name the file does not have goes into a copy of its string table there. An actor without a Dynamic
    block, or a file that has no Drop__DropActor key, is NotInPlace."""
    if not drops:
        return None
    found, keys, strings = chests(data)
    key_at, _, root = struct.unpack_from("<III", data, 4)
    todo = []
    for name, kind, value, _ in entries(data, root, keys):
        if name != "Actors" or kind != 0xC0:
            continue
        n = int.from_bytes(data[value + 1:value + 4], "little")
        vals = value + 4 + (n + 3 & ~3)
        for i in range(n):
            if data[value + 4 + i] != 0xC1:
                continue
            ident, dyn = None, None
            for k, t, v, where in entries(data, struct.unpack_from("<I", data, vals + 4 * i)[0], keys):
                if k == "Hash" and t == 0xD5:
                    ident = struct.unpack_from("<Q", data, v)[0]
                elif k == "Dynamic" and t == 0xC1:
                    dyn = (where, v)
            if ident in drops:
                if not dyn:
                    raise NotInPlace("%#x has no Dynamic block to put a drop in" % ident)
                todo.append((ident, dyn[0], dyn[1]))
    if not todo:
        return None
    if "Drop__DropActor" not in keys:
        raise NotInPlace("the file has no Drop__DropActor key")
    drop_key = keys.index("Drop__DropActor")
    out = bytearray(data)
    out += b"\0" * (-len(out) % 4)
    names = list(strings)
    for h, _, _ in todo:
        if drops[h] not in names:
            names.append(drops[h])
    if len(names) > len(strings):
        at = len(out)
        out += string_table(names)
        struct.pack_into("<I", out, 8, at)
    for h, where, node in todo:
        n = int.from_bytes(data[node + 1:node + 4], "little")
        rows = [bytes(data[node + 4 + 8 * k:node + 12 + 8 * k]) for k in range(n)]
        rows = [r for r in rows if int.from_bytes(r[:3], "little") != drop_key]
        rows.append(drop_key.to_bytes(3, "little") + bytes([0xA0]) + struct.pack("<I", names.index(drops[h])))
        rows.sort(key=lambda r: int.from_bytes(r[:3], "little"))   # (a dictionary's keys are in the key table's order)
        at = len(out)
        out += bytes([0xC1]) + len(rows).to_bytes(3, "little") + b"".join(rows)
        struct.pack_into("<I", out, where, at)
    out = bytes(out)
    again, _, _ = chests(out)
    got = {c.hash: c.item for c in again}
    if any(got.get(h) != drops[h] for h, _, _ in todo):
        raise ValueError("a drop did not read back as written")
    before = {c.hash: (c.item, c.event) for c in found}
    if any(before[c.hash] != (c.item, c.event) for c in again if c.hash in before and c.hash not in drops):
        raise ValueError("giving a drop changed another actor's")
    return out


# ---- an actor's pack (Pack/Actor/<name>.pack.zs): a SARC archive of its parameter files ----
# The Gold Skulltulas setting. A Gold Skulltula drops what its map file names (Drop__DropActor, the key a chest names
# its item by; without one, its token), so its token and a chest's item can change places: the chest gives the token
# as an item (TOKEN), the Skulltula drops the chest's, made a pick-up (pickup_pack).
SKULLTULA = "Enemy_Skulltula_Gold"
TOKEN = "Item_Token_Gold"
# What a Skulltula may be given: what the game can be finished without, and is no loss where a Skulltula cannot be
# reached yet. No gating item and no dungeon's key (the rules know no Skulltula's place: many ask for the Boomerang,
# the Hookshot or the night), and no Heart Piece (it hangs where it is put and is taken with A from beside it: one
# dropped on a wall could not be reached, seen in play).
# A Skulltula is done with when its drop is got as a token is: the drop's get event runs, and the drop is gone. The
# game runs an item's get event the first time it is got and not again, so the second seed of a game was put in the
# pouch and stayed where it was, and its Skulltula was back when the room was entered again, for another seed. With
# the event each time (pickup_pack's each_time) four seeds in a row were each got with their text and their
# Skulltulas stayed dead; so were Deku Nut bundles (seen in play).
# A bundle Link has nothing to carry in is not got at all: a bomb bundle without a Bomb Bag, and a Deku Nut bundle in
# a game that had had no nuts yet, stayed where they were with nothing given, and their Skulltulas were back when
# the room was entered again (seen in play; the nuts were got once some had been bought). It is there for later, as
# a token out of reach is. The stick and Bombchu bundles are given on the strength of the nuts: not seen yet.
# A chest's arrows and magic jar have the pouch file of the world's own (a world arrow bundle's, a jar's), so each is
# given one of its own (PICKUP_OWN_POUCH) with the event each time: two arrow bundles in a line, and two jars, were
# each got with their text (without a window, on a save that had had both before). The large arrow bundle is given on
# the strength of the medium one.
SKULLTULA_ITEMS = ("Item_ScrubBusinessSeed", "Item_BombBundle_Small", "Item_BombchuBundle_Small", "TBox_DekuNutBundle",
                   "Item_DekuStickBundle_Small", "TBox_ArrowBundle_Medium", "TBox_ArrowBundle_Large", "Tbox_MagicJar_Large")
# Kept from the Skulltulas: the rupees. A chest's green rupee made a pick-up was walked through and stayed, with the
# game's own pouch file, with one of its own, and with one of its own that asks for its get event each time (without
# a window, on a save that had picked up rupees before): a rupee's get event is not run a second time whatever its
# pouch file says, and a pick-up made from the token waits for it. What else was tried with them on the way: what a
# world rupee thinks with (AIInfoRef DropItem: it fell); a world rupee (Obj_Rupee_*) dropped in a chest rupee's place
# (it fell into water, and its Skulltula was back each time).
SKULLTULA_ITEMS_NOT_YET = ("TBox_Rupee_Green", "TBox_Rupee_Blue", "TBox_Rupee_Red", "TBox_Rupee_Purple", "TBox_Rupee_Gold")


def skulltulas(data):
    """A map file's Gold Skulltulas: [(hash, position, can be given a drop in place, is a dungeon's)]. In place: it has
    a Dynamic block and the file has the Drop__DropActor key (add_drop_in_place; the file is written anew for the
    others). A dungeon's has its room's number there, as a dungeon's chest has."""
    if data[:2] != b"YB":
        raise ValueError("not a little-endian BYML")
    key_at, str_at, root = struct.unpack_from("<III", data, 4)
    keys, strings = table(data, key_at), table(data, str_at)
    out = []
    for name, kind, value, _ in entries(data, root, keys):
        if name != "Actors" or kind != 0xC0:
            continue
        n = int.from_bytes(data[value + 1:value + 4], "little")
        vals = value + 4 + (n + 3 & ~3)
        for i in range(n):
            if data[value + 4 + i] != 0xC1:
                continue
            ident, gyaml, dyn, pos, dungeon = None, "", False, (), False
            for k, t, v, _ in entries(data, struct.unpack_from("<I", data, vals + 4 * i)[0], keys):
                if k == "Hash" and t == 0xD5:
                    ident = struct.unpack_from("<Q", data, v)[0]
                elif k == "Gyaml" and t == 0xA0:
                    gyaml = strings[v] if v < len(strings) else ""
                elif k == "Translate" and t == 0xC0 and int.from_bytes(data[v + 1:v + 4], "little") == 3:
                    pos = tuple(round(x, 1) for x in struct.unpack_from("<3f", data, v + 8))
                elif k == "Dynamic" and t == 0xC1:
                    dyn = True
                    dungeon = any(dk == "DefaultDungeonRoomIndex" for dk, _, _, _ in entries(data, v, keys))
            if gyaml == SKULLTULA and ident is not None:
                out.append((ident, pos, dyn and "Drop__DropActor" in keys, dungeon))
    return out


# ---- the logic for a Gold Skulltula: what Link needs before its drop can be got ----
# Not known Skulltula by Skulltula yet, so each asks for too much: what its area's chests can ask for (RULES), and
# what a Skulltula's place can ask for anywhere: the three stones, the Longshot (the Hookshot's reach and more) and
# the Megaton Hammer. A Skulltula known better than that is in SKULLTULA_RULES, by its hash: what it asks for in
# place of all that. A drop is brought in by the Boomerang and by the Hookshot (both seen in play), so a gating item
# goes to the child's Skulltulas and the adult's alike.
SKULLTULA_ASKS = ADULT | {LONG, HAM}
# (where a child goes: the overworld's maps say it in their name, <area>_Child_..., and a dungeon has one map for both)
SKULLTULA_CHILD_DUNGEONS = ("InsideTheDekuTree", "DodongoCavern", "InsideJabuJabuBelly", "BottomOfTheWell")
# Written from the original game's randomizer logic (track-oot.net's, without tricks), each matched to the map's
# Skulltula by its area, who can get it, night and soft soil, and where two were alike by height or room; the
# remake's new places from the player (<game folder>/rando/skulltulas_to_check.txt has every line and how sure
# it is). In the rules' own words: CHILD is out of the forest (night, a bottle of bugs, a Deku Stick), ADULT is the
# three stones done (the Hookshot, the songs an adult learns). Where the original gives a choice (the Boomerang or
# the Hookshot) the child's is asked for; where two could not be told apart both ask for the most either does.
SKULLTULA_RULES = {
    # Bottom of the Well
    0x6789388e9fb9c92c: ADULT | {LENS},        # boomerang, lens, adult first (Song of Storms)
    0xa8d6182a5c956e16: ADULT | {LENS},        # boomerang, lens, adult first (Song of Storms)
    0x35fb354fac262d36: ADULT | {LENS},        # boomerang, lens, adult first (Song of Storms)
    # DeathMountainCrater
    0xfcd7f04dcf755e8e: CHILD | {BB},          # child, sword, slingshot, bombs (to get up the mountain)
    0x58c75badf059ca54: ADULT | {HAM},         # child, bugs, and adult first with the hammer (the child gets here by B
    # DeathMountainTrail
    0xf5359b24fc86ac22: ADULT | {HAM},         # adult, hammer, night
    0x0b8e43abfa0b5f86: ADULT | {HAM},         # adult, hammer, night
    0x04e03ac27985e328: CHILD | {BB},          # bombs (or the hammer)
    0xf1d32c06612da232: CHILD | {BB},          # child, bugs, bombs
    # DesertColossus
    0xd0f7e5ffa76ba288: DESERT,                # adult, hookshot, night; all it takes to cross the desert (probably)
    0x9ae3d0ac392e6cda: DESERT,                # adult, hookshot or longshot, night; all it takes to cross the desert (probably)
    0x0341f2c03598c861: DESERT,                # child, bugs; adult first with all it takes to cross the desert (the ch
    # Dodongo's Cavern
    0xbdfe13c37f356829: CHILD | {BB},          # bombs (or the hammer) (probably)
    0x758ce7b4868447fb: CHILD | {BB, BM},      # boomerang or hookshot, bombs (probably)
    0x3f5b150f16d84603: CHILD | {BB},          # bombs (probably)
    0x0d53e429a1ef383d: ADULT | {LONG},        # adult, scarecrow or longshot (probably)
    0x10434342a3917ebd: CHILD | {BB},          # sword or slingshot, bombs (probably)
    # Ganon's Castle (outside)
    0x4e13cc311cd04df4: ADULT,                 # adult
    # GerudoValley
    0xbc85efca2b222cd9: ADULT | {LONG},        # adult, hookshot, night, longshot (to cross the valley)
    0xa017ce09904c2dce: ADULT | {LONG},        # adult, hookshot, night, longshot (to cross the valley)
    0x738f5746cc517702: CHILD,                 # child, bugs
    0xd3d86d3d6988ed8c: CHILD | {BM},          # child, boomerang, night
    # GoronCity
    0xfbbc2d490276c68e: ADULT,                 # adult
    0x07e6e21142cc54db: CHILD | {BB},          # child, bombs
    # Graveyard
    0x032f42f523be6425: CHILD | {BM},          # child, boomerang, night
    0xe91f6be796358ffc: CHILD,                 # child, bugs
    # Haunted Wasteland
    0xceed596f17934971: DESERT,                # hookshot or boomerang; all it takes to cross the desert
    # Hyrule Castle
    0x22c0f7dff5ebb86d: CHILD,                 # child, sword or slingshot
    0x7f28485fa5d3688f: ADULT,                 # boomerang or hookshot, bombs, Song of Storms (adult first) (probably)
    # HyruleField
    0x0af4d6f063d3ae9f: ADULT | {LONG},        # adult, longshot, night
    0x6689bdebc95368eb: ADULT | {IRON},        # adult, iron boots, hookshot
    0x7d8ec14bdd1f6341: ADULT,                 # adult, bombs as a child (the rock over the grotto), sword or slingshot
    0x781e0de8eed42373: CHILD,                 # sword or slingshot
    0xa6a4e87da18fa678: CHILD | {BB, BM},      # boomerang or hookshot, bombs (to open the grotto) (probably)
    0x25e6072d4df023b3: CHILD | {BM},          # boomerang or hookshot, night (probably)
    0x04be4a8ff29f2099: CHILD | {BM},          # child, boomerang, night (probably)
    0x1e38e8d23596eecf: CHILD | {BM},          # child, boomerang, night (probably)
    0xc1858a4fcd84a28e: CHILD | {BM},          # child, boomerang, night
    0x61576befd16c499a: CHILD,                 # child, bugs
    0xdc8113831c56b194: CHILD | {BM},          # child, boomerang, night (probably)
    # IceCavern
    0xcdb49f5d0a67fcf6: ADULT,                 # adult, hookshot or boomerang
    0x63701a2cf70b201c: ADULT,                 # adult, hookshot or boomerang
    0x165fc0bc0aca1f6c: ADULT,                 # adult, hookshot or boomerang
    # Inside Jabu-Jabu's Belly
    0x9c95fd41b89c058a: ADULT,                 # child, boomerang, bombs (to get to Jabu-Jabu)
    0xc03f282ff60942b6: ADULT,                 # child, boomerang, bombs (to get to Jabu-Jabu)
    0x9fc92497f014dbd5: ADULT,                 # child, boomerang, bombs (to get to Jabu-Jabu)
    0xddd260afb6f2989a: ADULT,                 # child, boomerang, bombs (to get to Jabu-Jabu)
    # Inside the Deku Tree
    0xf2e27d6a27026acf: CHILD,                 # slingshot or boomerang
    0xbce05898ce61f1c0: frozenset((S,)),       # sword or slingshot
    0xfad8931a0011e1d4: CHILD,                 # slingshot or boomerang (probably)
    0xdf73f3739cef466b: CHILD,                 # slingshot or boomerang (probably)
    # KakarikoVillage
    0x2df265292516bdf0: ADULT,                 # adult, hookshot, night
    0xa1632e322c612b97: CHILD,                 # child, night
    0x6a8d9b2373d08fcb: CHILD,                 # child, night, sword or slingshot
    0xc3c68d0ac4b85831: CHILD,                 # child, night
    0xd1cef51cf294fb86: CHILD,                 # child, night, slingshot (probably)
    0xd4883a16973b1d06: CHILD,                 # child, night
    # KokiriForest
    0x62c340f0b876c195: ADULT,                 # adult, hookshot, night
    0xecdc46b409ed7d38: CHILD,                 # child, sword or slingshot, night (out of the forest, or the Sun's Song
    0x858f5000ad57b2cc: CHILD,                 # child, bugs, sword or slingshot
    # Lost Woods
    0x3c2b585ac5c0443e: ADULT,                 # adult, night, a bean planted as a child (probably)
    0x8186bcb07d6c2cf9: CHILD,                 # child, bugs
    0xf6fa6ef0ca152948: CHILD,                 # child, bugs
    # Market
    0x7c1a05315f83c34d: CHILD,                 # child
    # SacredForestMeadow
    0xc8db3346f78ea31b: ADULT,                 # adult, hookshot, night
    # ZoraDomain
    0x853b892663c0215d: ADULT,                 # adult, night, hookshot or bow
    # ZoraFountain
    0x845ba51dc18c855e: ADULT | {SG},          # adult, hookshot, night, silver gauntlets, bombs (probably)
    0x63446d12663daa83: ADULT,                 # child, boomerang, night, bombs (to get up the river)
    0xf0dac245e2fc448e: CHILD | {BB},          # child, bombs (to get up the river)
    # ZoraRiver
    0x97824c2ffeaa877c: ADULT,                 # adult, hookshot, night
    0x8325fea55edfbe97: ADULT,                 # adult, hookshot, night
    0xabad0e9f0d471156: CHILD | {BB},          # child, bugs, bombs: past the boulders (seen in play)
    0x78ae4fd90b3cfaaa: CHILD | {BB},          # child, night, sword or slingshot, bombs (past the boulders)
    # The adult's temples. A temple's keys may lie behind anything the temple takes (Dungeon keys: Own dungeon), so each
    # asks for what its temple's chests can (RULES) and no less, but for the Forest Temple's first, by the door; and no
    # more: not the Megaton Hammer or the Longshot of SKULLTULA_ASKS where its temple does not take them.
    # FireTemple
    0xcc175a90e0014905: ADULT | {HAM, BOW},            # adult; hammer, bow
    0x7f498ada1c2e9c7a: ADULT | {HAM, BOW},            # adult; hammer, bow
    0x4d1b7e35ca0c6484: ADULT | {HAM, BOW},            # adult; hammer, bow
    0xb0f77b17cfb37458: ADULT | {HAM, BOW},            # adult; hammer, bow
    0x5e3ae6a7cf3ac292: ADULT | {HAM, BOW},            # adult; hammer, bow
    # ForestTemple
    0x984021bc20419ebe: ADULT | {BOW, LONG},           # adult, longshot; bow (probably)
    0x2aa39f00aaa2d331: ADULT | {BOW},                 # adult, hookshot or boomerang; bow
    0xf46b1710ed0620d1: ADULT | {BOW},                 # adult, hookshot or boomerang; bow (probably)
    0x99ca89963485df11: ADULT,                         # adult, hookshot or bow or bombs
    0x1bf5f0176ef03bda: ADULT | {BOW},                 # adult, hookshot; bow (probably)
    # GerudoFortress
    0x81ed4ed76699e3d8: ADULT | {HOVER, LONG, BOW},    # adult, night; hover boots, longshot, bow (what the fortress 
    0xb4ece769e6f3a206: ADULT | {HOVER, LONG, BOW},    # adult, night; hover boots, longshot, bow (what the fortress 
    # ShadowTemple
    0x8e87908cb035e950: MEDALS3 | {LENS, HOVER},       # adult; lens, hover boots, and the three temples before it
    0xd23a7a2c9eced9ce: MEDALS3 | {LENS, HOVER},       # adult; lens, hover boots, and the three temples before it
    0xd7ffbe169189e50d: MEDALS3 | {LENS, HOVER},       # adult; lens, hover boots, and the three temples before it
    0x7a74bc651f9fe024: MEDALS3 | {LENS, HOVER},       # adult; lens, hover boots, and the three temples before it
    0xeafe60e592e9a3fb: MEDALS3 | {LENS, HOVER},       # adult; lens, hover boots, and the three temples before it
    # SpiritTemple
    0x8c8bb95471d20d02: DESERT | {SG, BOW, MS},        # the desert crossed; silver gauntlets, bow, mirror shield
    0x4696b2730de0516c: DESERT | {SG, BOW, MS},        # the desert crossed; silver gauntlets, bow, mirror shield
    0x9222e742b73d3d2c: DESERT | {SG, BOW, MS},        # the desert crossed; silver gauntlets, bow, mirror shield
    0xb3d9f353599eea53: DESERT | {SG, BOW, MS},        # the desert crossed; silver gauntlets, bow, mirror shield
    0x70b0fca66ca4808a: DESERT | {SG, BOW, MS},        # the desert crossed; silver gauntlets, bow, mirror shield
    # WaterTemple
    0xd731ea6a04d0fd01: ADULT | {IRON, LONG, BOW},     # adult, iron boots, longshot, bow
    0xa0973706f6415ecd: ADULT | {IRON, LONG, BOW},     # adult, iron boots, longshot, bow (probably)
    0xe03a2965df9f7b30: ADULT | {IRON, LONG, BOW},     # adult, iron boots, longshot, bow
    0x02974596f92cf377: ADULT | {IRON, LONG, BOW},     # adult, iron boots, longshot, bow
    0x3d0de5adaeb73cc9: ADULT | {IRON, LONG, BOW},     # adult, iron boots, longshot, bow
}
SKULLTULA_GATING_SHARE = 0.35   # (of the gating items, how many are tried on a Skulltula)


def skulltula_rule(h, area):
    """what the Skulltula of this hash, in this area, asks for"""
    return SKULLTULA_RULES.get(h, rule(area, "") | SKULLTULA_ASKS)


def gate_skulltulas(rng, gives, drops, skulls, needs, skull_needs, fixed, share=SKULLTULA_GATING_SHARE, never=(), token=TOKEN):
    """Some of the gating items the logic put in chests (gives) moved to Gold Skulltulas that still drop their token
    (skulls: hashes, in a fixed order; drops: the ones that do not), each only if every gating item can still be
    got by the rules. The chest it leaves gives the token. needs and skull_needs: what a chest and a Skulltula ask
    for; fixed: [(what it asks for, the item)] of the gating items in chests that stay.
    never: gating items that are not tried (one not seen dropped by a Skulltula yet).
    token: what a Skulltula's own drop is, which the chest left gives (the Pieces of Heart lying in the world are
    placed by this too: theirs is the piece).
    Returns (what the chests give, what the Skulltulas drop, the spheres, how many were moved)."""
    gives, drops = dict(gives), dict(drops)
    where = {i: (False, h) for h, i in gives.items() if i in PROGRESSION}   # item -> (on a Skulltula, the hash)

    def placed():
        return fixed + [((skull_needs if on_skull else needs)[h], i) for i, (on_skull, h) in sorted(where.items())]

    want = {i for _, i in fixed} | set(where)
    free = [h for h in skulls if h not in drops]
    rng.shuffle(free)
    order = sorted(where)
    rng.shuffle(order)
    order = [i for i in order if i not in never]   # (after the shuffle: the seeds made before `never` keep theirs)
    moved = 0
    for item in order:
        if not free or rng.random() >= share:
            continue
        chest = where[item][1]
        where[item] = (True, free[-1])
        if {i for sphere in collect(placed()) for i in sphere} >= want:
            drops[free.pop()] = item
            gives[chest] = token
            moved += 1
        else:
            where[item] = (False, chest)
    return gives, drops, collect(placed()), moved


def mix_skulltulas(rng, gives, skulls, token=TOKEN):
    """The tokens of `skulls` (Skulltulas' hashes, in a fixed order) and the chests' items a Skulltula may be given
    (SKULLTULA_ITEMS) shuffled among those chests and those Skulltulas. Returns (what the chests give now, {a
    Skulltula's hash: the item it drops} for the ones that do not drop their token)."""
    if not skulls:
        return dict(gives), {}
    chests_in = [h for h in gives if gives[h] in SKULLTULA_ITEMS]
    items = [gives[h] for h in chests_in] + [token] * len(skulls)
    rng.shuffle(items)
    new, drops = dict(gives), {}
    for h, item in zip(chests_in + list(skulls), items):
        if h in gives:
            new[h] = item
        elif item != token:
            drops[h] = item
    return new, drops


def sarc_hash(name, mult=101):
    h = 0
    for c in name.encode():
        h = (h * mult + (c if c < 128 else c - 256)) & 0xFFFFFFFF
    return h


def sarc_read(data):
    """a SARC archive's files, {name: bytes} (little-endian, as the game's are)"""
    if data[:4] != b"SARC" or struct.unpack_from("<H", data, 6)[0] != 0xFEFF:
        raise ValueError("not a little-endian SARC archive")
    head, _, _, data_at = struct.unpack_from("<HHII", data, 4)
    if data[head:head + 4] != b"SFAT":
        raise ValueError("a SARC archive without its file table")
    n = struct.unpack_from("<H", data, head + 6)[0]
    nodes = head + 12
    names = nodes + 16 * n + 8
    out = collections.OrderedDict()
    for i in range(n):
        _, attr, a, b = struct.unpack_from("<IIII", data, nodes + 16 * i)
        at = names + (attr & 0xFFFFFF) * 4
        out[data[at:data.index(b"\0", at)].decode()] = bytes(data[data_at + a:data_at + b])
    return out


def sarc_write(files, mult=101, align=8):
    """a SARC archive of {name: bytes}, as the game's own packs are laid out (the same bytes for the same files)"""
    names, nodes, blob = bytearray(), [], bytearray()
    for name, data in sorted(files.items(), key=lambda kv: sarc_hash(kv[0], mult)):
        blob += b"\0" * (-len(blob) % align)
        nodes.append((sarc_hash(name, mult), 0x01000000 | len(names) // 4, len(blob), len(blob) + len(data)))
        blob += data
        names += name.encode() + b"\0"
        names += b"\0" * (-len(names) % 4)
    head = 0x14 + 12 + 16 * len(nodes) + 8 + len(names)
    data_at = head + (-head % align)
    out = bytearray(b"SARC" + struct.pack("<HHIIHH", 0x14, 0xFEFF, data_at + len(blob), data_at, 0x0100, 0))
    out += b"SFAT" + struct.pack("<HHI", 12, len(nodes), mult)
    for node in nodes:
        out += struct.pack("<IIII", *node)
    out += b"SFNT" + struct.pack("<HH", 8, 0) + names
    out += b"\0" * (data_at - len(out)) + blob
    return bytes(out)


def set_root_string(data, key, value):
    """a BYML file with the string its root dictionary has under `key` changed: the new bytes. The new string goes
    into a copy of the string table at the end of the file, as an item's name does in a map file."""
    if data[:2] != b"YB":
        raise ValueError("not a little-endian BYML")
    key_at, str_at, root = struct.unpack_from("<III", data, 4)
    keys, strings = table(data, key_at), table(data, str_at)
    where = next((w for k, t, _, w in entries(data, root, keys) if k == key and t == 0xA0), None)
    if where is None:
        raise ValueError("the file's root has no string %s" % key)
    out = bytearray(data)
    out += b"\0" * (-len(out) % 4)
    names = strings if value in strings else strings + [value]
    if len(names) > len(strings):
        at = len(out)
        out += string_table(names)
        struct.pack_into("<I", out, 8, at)
    struct.pack_into("<I", out, where, names.index(value))
    return bytes(out)


def byml_parse(data):
    """A little-endian BYML file as a tree that keeps every value's type, for writing it again changed: a dictionary
    is ("dict", {key: node}), an array ("array", [node]), a string ("string", text), anything else (its type byte,
    its bytes: 4, or the 8 a 64-bit value points at). Returns (the tree, the file's version)."""
    if data[:2] != b"YB":
        raise ValueError("not a little-endian BYML")
    version = struct.unpack_from("<H", data, 2)[0]
    key_at, str_at, root = struct.unpack_from("<III", data, 4)
    keys = table(data, key_at) if key_at else []
    strings = table(data, str_at) if str_at else []

    def value(kind, at):
        raw = struct.unpack_from("<I", data, at)[0]
        if kind == 0xA0:
            return ("string", strings[raw])
        if kind in (0xC0, 0xC1):
            return node(raw)
        if kind in (0xD4, 0xD5, 0xD6):
            return (kind, bytes(data[raw:raw + 8]))
        if kind in (0xD0, 0xD1, 0xD2, 0xD3, 0xFF):
            return (kind, bytes(data[at:at + 4]))
        raise ValueError("a BYML value of a type not written again here (%#x)" % kind)

    def node(at):
        kind, n = data[at], int.from_bytes(data[at + 1:at + 4], "little")
        if kind == 0xC1:
            out = collections.OrderedDict()
            for k in range(n):
                e = at + 4 + 8 * k
                out[keys[int.from_bytes(data[e:e + 3], "little")]] = value(data[e + 3], e + 4)
            return ("dict", out)
        if kind == 0xC0:
            vals = at + 4 + (n + 3 & ~3)
            return ("array", [value(data[at + 4 + k], vals + 4 * k) for k in range(n)])
        raise ValueError("a BYML node of a type not written again here (%#x)" % kind)

    return (node(root) if root else None), version


def byml_build(tree, version):
    """the bytes of a tree of byml_parse: the key and string tables sorted, every container written once"""
    keys, strings = set(), set()

    def gather(nd):
        if nd[0] == "dict":
            keys.update(nd[1])
            for v in nd[1].values():
                gather(v)
        elif nd[0] == "array":
            for v in nd[1]:
                gather(v)
        elif nd[0] == "string":
            strings.add(nd[1])
    gather(tree)
    keys, strings = sorted(keys, key=lambda k: k.encode()), sorted(strings, key=lambda k: k.encode())
    key_index, string_index = {k: i for i, k in enumerate(keys)}, {k: i for i, k in enumerate(strings)}
    out = bytearray(16)
    key_at = len(out)
    out += string_table(keys)
    str_at = len(out)
    out += string_table(strings)

    def emit(nd):
        """(type byte, the 4 bytes that stand for the value where it is held)"""
        if nd[0] == "string":
            return 0xA0, struct.pack("<I", string_index[nd[1]])
        if nd[0] == "dict":
            rows = [(key_index[k], emit(v)) for k, v in nd[1].items()]
            rows.sort(key=lambda r: r[0])
            at = len(out)
            out.extend(bytes([0xC1]) + len(rows).to_bytes(3, "little"))
            for k, (kind, held) in rows:
                out.extend(k.to_bytes(3, "little") + bytes([kind]) + held)
            return 0xC1, struct.pack("<I", at)
        if nd[0] == "array":
            rows = [emit(v) for v in nd[1]]
            at = len(out)
            out.extend(bytes([0xC0]) + len(rows).to_bytes(3, "little") + bytes(k for k, _ in rows))
            out.extend(b"\0" * (-len(out) % 4))
            for _, held in rows:
                out.extend(held)
            return 0xC0, struct.pack("<I", at)
        kind, raw = nd
        if kind in (0xD4, 0xD5, 0xD6):
            out.extend(b"\0" * (-len(out) % 8))
            at = len(out)
            out.extend(raw)
            return kind, struct.pack("<I", at)
        return kind, raw

    _, held = emit(tree)
    out[0:16] = b"YB" + struct.pack("<HII", version, key_at, str_at) + held
    return bytes(out)


# What an item's actor is made a pick-up from. Obj_Item_Base is what a Heart Piece and a rupee are made from: it falls
# to the ground. A gold token is made from it too, with parts of its own: it stays where the Skulltula died, is
# collected by touching it, and the Boomerang and the Hookshot bring it in, which is how every Skulltula's place was
# made to be reached. So an item is made a pick-up from the token.
PICKUP_BASE = "Obj_Token_Gold"
# The token's effects and sounds come with it: a gold skull's outline around the item as it is got, in the item's own
# chest too (seen in play). The item's actor cannot name others: an ELinkRef or SLinkRef of its own, empty or another
# pick-up's or the token's very own, stopped the game as the actor was made, and an item given the token's parts one
# by one without them was not there at all when its Skulltula died (all tried). What the token's two files say is
# changed in the item's pack instead: each holds a name, and they get a plain pick-up's, the Deku Shield as it lies in
# the world.
PICKUP_EFFECTS = "Obj_Shield_Deku"


# (what a chest's item is made from: the model a chest's get scene shows, with nothing to touch)
CHEST_BASE = "Item_EventObject_Base"


def ref_file(ref):
    """the pack's file a parameter file names: "?X.bgyml" is X.bgyml, "Work/X.gyml" is X.bgyml"""
    name = ref.lstrip("?")
    if name.startswith("Work/"):
        name = name[len("Work/"):]
    return name[:-len(".gyml")] + ".bgyml" if name.endswith(".gyml") else name


def actor_chain(item, files):
    """An item's actor and the actors it is made from, as far as its pack has them: [[file, tree, version]], the
    item's own first (a red rupee's: TBox_Rupee_Red, TBox_Rupee_Green, Item_EventObject_Base)."""
    chain, name = [], "Actor/%s.engine__actor__ActorParam.bgyml" % item
    while name in files and name not in [c[0] for c in chain]:
        tree, version = byml_parse(files[name])
        chain.append([name, tree, version])
        parent = tree[1].get("$parent")
        if not parent or parent[0] != "string":
            break
        name = ref_file(parent[1])
    return chain


def pickup_family(item, item_pack):
    """the actors an item is made from that are chests' items themselves, by name, the item's own first: each has a
    pack of its own with a copy of the same file, and is made a pick-up with the item"""
    chest = "Actor/%s.engine__actor__ActorParam.bgyml" % CHEST_BASE
    return [name.split("/")[1].split(".")[0] for name, _, _ in actor_chain(item, sarc_read(item_pack)) if name != chest]


# An item's model is made to be held up over Link's head, seen from close: hanging where a Skulltula died the
# smallest are hard to see (the Lens of Truth and the Goron's Bracelet, seen in play). These are made larger, by
# their ModelInfo's DebugModelScale (the game's own dogs, light balls and a rolling rock have one that is not 1). The
# model is as much larger in its chest's scene: the two are one actor. Not more than this: an item hangs in the
# pose of that scene, about half a metre over the place it is taken at, and its size carries that with it (at 2.5
# the Lens of Truth hung a metre over it; without the pose, its ASRef and ASInfoRef left out, it lay edge-on at
# the right height: both seen without a window).
PICKUP_SCALES = {"Item_GlassTruth": 1.5, "Item_Gauntlet_Goron": 1.5}


# How an item is got, in its pouch file: "Large" is Link holding it up (the hash of the word, as the game's files have it)
GET_LARGE = 1746592023


# An item whose pouch file is another thing's too: a chest's rupee has the world rupee's, a chest's arrows the world's
# arrow bundle's, a chest's magic jar the world's jar's. Changed in place it would change every world rupee (its get
# event each time one is picked up), and of the copies of one name the game uses the first it loaded. These are given
# a pouch file of their own, under a name of its own (OWN_POUCH), with the item's as its parent.
PICKUP_OWN_POUCH = frozenset(("TBox_Rupee_Green", "TBox_Rupee_Blue", "TBox_Rupee_Red", "TBox_Rupee_Purple", "TBox_Rupee_Gold",
                              "TBox_ArrowBundle_Medium", "TBox_ArrowBundle_Large", "Tbox_MagicJar_Large"))
OWN_POUCH = "Component/PouchContentParam/Rando_%s.game__component__PouchContentParam.bgyml"


def pickup_pack(item, item_pack, base_pack, base_name=PICKUP_BASE, effects_name=PICKUP_EFFECTS, each_time=False,
                own_pouch=PICKUP_OWN_POUCH):
    """An item's pack (a SARC archive) made into a pick-up's. Its actor takes the base's as its parent in place of
    Item_EventObject_Base (the model a chest's get scene shows, with nothing to touch), and the pack gets the files
    of the base's that it lacks. An item made from another item (a red rupee from a green one) has that one's
    parent changed: the one whose parent Item_EventObject_Base is. What the item has of its own (its model, its
    animation, what it is in the pouch) stays over the base's, with two changes:
      - its table of game parameters names the base's as its parent. An item's own table took the base's place
        whole and left the pick-up without DropBoundParam and GamePhysicsControllerParam: the game stopped at the
        missing one as the actor was made (a rupee's table has the base's as its parent);
      - what it is in the pouch is got by touching it (DefaultAutoGet, as a token's and a rupee's are), not by
        standing beside it and pressing A. One that says so already, itself or by its parent, is left as it is.
    each_time: its get event runs each time it is got, not only the first (PlayGetEventManyTimes, and how it is got
    where its pouch file does not say: every item of the game's own that is got each time says both). A pick-up made
    from the token is done with by its get event: the second Deku Scrub's seed of a game was put in the pouch and
    stayed where it was, and its Skulltula was back when the room was entered again (seen in play).
    Seen in play with the Boomerang, the Megaton Hammer and the small Bomb Bag: the chest still gives the item with
    its scene, and dropped by a Gold Skulltula it stays there and is collected by touching it, with its text."""
    files, base = sarc_read(item_pack), sarc_read(base_pack)
    own = "Actor/%s.engine__actor__ActorParam.bgyml" % item
    chest_actor = "Actor/%s.engine__actor__ActorParam.bgyml" % CHEST_BASE
    if own not in files:
        raise ValueError("%s: its pack has no actor of that name" % item)
    chain = actor_chain(item, files)

    def pouch_says(key, name=None):
        """what the item's pouch file (or the pouch file `name`) says of `key`, itself or the nearest parent that
        does: True, False or None"""
        seen = []
        for _, tree, _ in chain if name is None else ():
            ref = tree[1].get("Components", ("dict", {}))[1].get("PouchContentRef")
            if ref and ref[0] == "string" and ref[1]:
                name = ref_file(ref[1])
                break
        while name in files and name not in seen:
            seen.append(name)
            sub, _ = byml_parse(files[name])
            if key in sub[1]:
                return any(sub[1][key][1])
            parent = sub[1].get("$parent")
            name = ref_file(parent[1]) if parent and parent[0] == "string" else ""
        return None

    base_actor = "Actor/%s.engine__actor__ActorParam.bgyml" % base_name
    base_table = "GameParameter/GameParameterTable/%s.engine__actor__GameParameterTable.bgyml" % base_name
    if base_actor not in base or base_table not in base:
        raise ValueError("%s: the base's pack has no actor or no table of game parameters of %s" % (item, base_name))
    top = next((k for k, (_, tree, _) in enumerate(chain)
                if tree[1].get("$parent", ("", ""))[0] == "string" and ref_file(tree[1]["$parent"][1]) == chest_actor), None)
    if top is None:
        raise ValueError("%s is not made from %s: not a chest's item" % (item, CHEST_BASE))
    chain = chain[:top + 1]
    name, tree, version = chain[top]
    tree[1]["$parent"] = ("string", "Work/" + base_actor.replace(".bgyml", ".gyml"))
    files[name] = byml_build(tree, version)

    def part(key):
        """the pack's file an entry of the actor's Components names (the item's own, or the nearest it is made
        from), or "" """
        for _, tree, _ in chain:
            ref = tree[1].get("Components", ("dict", {}))[1].get(key)
            if ref and ref[0] == "string" and ref[1]:
                return ref_file(ref[1]) if ref_file(ref[1]) in files else ""
        return ""

    name = part("GameParameterTableRef")
    if name and name != base_table:
        sub, sub_version = byml_parse(files[name])
        if "$parent" not in sub[1]:
            sub[1]["$parent"] = ("string", "Work/" + base_table.replace(".bgyml", ".gyml"))
            files[name] = byml_build(sub, sub_version)
    # (a pouch file of its own for each actor of the item's that names one and is in own_pouch: the item's, and the item
    # it is made from, whose actor this pack has a copy of and whose own pack is changed the same way)
    for name, tree, version in chain:
        actor = name.split("/")[1].split(".")[0]
        ref = tree[1].get("Components", ("dict", {}))[1].get("PouchContentRef")
        if actor not in own_pouch or not ref or ref[0] != "string" or ref_file(ref[1]) not in files:
            continue
        was = ref_file(ref[1])
        was_tree, was_version = byml_parse(files[was])
        new = OWN_POUCH % actor
        # (a copy of the item's, with all it says and its parent: a file that only named the item's as its parent was
        # not taken by touching it, seen without a window. And what the item's own would be given below, given here to
        # each: the same file in every pack that has it)
        own = collections.OrderedDict(was_tree[1])
        own["DefaultAutoGet"] = (0xD0, struct.pack("<I", 1))
        if each_time and not pouch_says("PlayGetEventManyTimes", was):
            own["PlayGetEventManyTimes"] = (0xD0, struct.pack("<I", 1))
            if pouch_says("GetType", was) is None:
                own["GetType"] = (0xD3, struct.pack("<I", GET_LARGE))
        files[new] = byml_build(("dict", own), was_version)
        tree[1]["Components"][1]["PouchContentRef"] = ("string", "?" + new)
        files[name] = byml_build(tree, version)
    first = part("PouchContentRef")
    if first and not pouch_says("DefaultAutoGet"):
        sub, sub_version = byml_parse(files[first])
        sub[1]["DefaultAutoGet"] = (0xD0, struct.pack("<I", 1))
        files[first] = byml_build(sub, sub_version)
    name = part("ModelInfoRef")
    if name and item in PICKUP_SCALES:
        sub, sub_version = byml_parse(files[name])
        sub[1]["DebugModelScale"] = ("dict", collections.OrderedDict((axis, (0xD2, struct.pack("<f", PICKUP_SCALES[item]))) for axis in "XYZ"))
        files[name] = byml_build(sub, sub_version)
    if first and each_time and not pouch_says("PlayGetEventManyTimes"):
        sub, sub_version = byml_parse(files[first])
        sub[1]["PlayGetEventManyTimes"] = (0xD0, struct.pack("<I", 1))
        if pouch_says("GetType") is None:
            sub[1]["GetType"] = (0xD3, struct.pack("<I", GET_LARGE))
        files[first] = byml_build(sub, sub_version)
    for name, data in base.items():
        files.setdefault(name, data)
    for kind in ("ELink", "SLink"):   # (the base's effects and sounds: another's, PICKUP_EFFECTS above)
        name = "Component/%s/%s.engine__component__%sParam.bgyml" % (kind, base_name, kind)
        if effects_name and name in files:
            sub, sub_version = byml_parse(files[name])
            if sub[1].get("UserName", ("", ""))[0] == "string":
                sub[1]["UserName"] = ("string", effects_name)
                files[name] = byml_build(sub, sub_version)
    return sarc_write(files)


def murmur3(data, seed=0):
    """MurmurHash3, 32 bits: the game's list of flags names each by this hash of its name"""
    c1, c2, h = 0xcc9e2d51, 0x1b873593, seed
    whole = len(data) & ~3
    for i in range(0, whole, 4):
        k = int.from_bytes(data[i:i + 4], "little") * c1 & 0xffffffff
        k = (k << 15 | k >> 17) * c2 & 0xffffffff
        h ^= k
        h = ((h << 13 | h >> 19) & 0xffffffff) * 5 + 0xe6546b64 & 0xffffffff
    if len(data) > whole:
        k = int.from_bytes(data[whole:], "little") * c1 & 0xffffffff
        h ^= (k << 15 | k >> 17) * c2 & 0xffffffff
    h ^= len(data)
    h = (h ^ h >> 16) * 0x85ebca6b & 0xffffffff
    h = (h ^ h >> 13) * 0xc2b2ae35 & 0xffffffff
    return h ^ h >> 16


def flag_defaults(data, flags, kind="Bool"):
    """The game's list of flags (GameDataList: a BYML as the map files are, but big-endian, "BY") with the value each
    flag of `flags` ({name: truth value}) starts a new game with: the new bytes, or None when they already start so.
    A flag is a dictionary of Data.Bool, {DefaultValue, Hash (of its name), ...}; the value is in the dictionary
    itself, so the file keeps its size. A name the list does not have as a truth value is an error.
    kind "Int": the list's whole numbers (Data.Int: PlayerStatus.CurrentRupee, the rupees Link has), `flags` then
    {name: a number from 0 to 2147483647}."""
    whole = kind == "Int"
    if whole and any(not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 0x7fffffff for v in flags.values()):
        raise ValueError("a number to start with is not a whole number the list can hold")
    if data[:2] != b"BY":
        raise ValueError("not a big-endian BYML (%r)" % data[:4])
    key_at, _, root = struct.unpack_from(">III", data, 4)
    count = lambda at: int.from_bytes(data[at + 1:at + 4], "big")
    keys = []
    for k in range(count(key_at)):
        at = key_at + struct.unpack_from(">I", data, key_at + 4 + 4 * k)[0]
        keys.append(data[at:data.index(b"\0", at)].decode("utf-8", "replace"))

    def fields(at):
        """a dictionary node's {key: (type, value, where its value is)}"""
        if data[at] != 0xC1:
            raise ValueError("no dictionary at %#x" % at)
        out = {}
        for k in range(count(at)):
            e = at + 4 + 8 * k
            key = int.from_bytes(data[e:e + 3], "big")
            out[keys[key] if key < len(keys) else ""] = (data[e + 3], struct.unpack_from(">I", data, e + 4)[0], e + 4)
        return out

    node, at, _ = fields(root).get("Data", (0, 0, 0))
    node, bools, _ = fields(at).get(kind, (0, 0, 0)) if node == 0xC1 else (0, 0, 0)
    if node != 0xC0 or data[bools] != 0xC0:
        raise ValueError("the list has no Data.%s" % kind)
    want = {murmur3(name.encode()): name for name in flags}
    if len(want) != len(flags):
        raise ValueError("two of the flags have one hash")
    n = count(bools)
    values = bools + 4 + (n + 3 & ~3)
    found = {}
    for i in range(n):
        if data[bools + 4 + i] != 0xC1:
            continue
        f = fields(struct.unpack_from(">I", data, values + 4 * i)[0])
        h = f.get("Hash")
        if not h or h[0] not in (0xD1, 0xD3) or h[1] not in want:
            continue
        v = f.get("DefaultValue")
        if not v or v[0] != (0xD1 if whole else 0xD0):
            raise ValueError("%s has no %s to start with" % (want[h[1]], "whole number" if whole else "truth value"))
        found[want[h[1]]] = (v[1] if whole else v[1] != 0, v[2])
    missing = sorted(set(flags) - set(found))
    if missing:
        raise ValueError("the game's list has no flag " + ", ".join(missing))
    if all(found[name][0] == (v if whole else bool(v)) for name, v in flags.items()):
        return None
    out = bytearray(data)
    for name, v in flags.items():
        struct.pack_into(">I", out, found[name][1], v if whole else int(bool(v)))
    return bytes(out)


def opening_skip(data):
    """OpeningEvent (a BFEVFL file) with its two cutscenes passed over: the new bytes, of the same size. Every step
    it relies on is checked first (see OPENING, above): a flow that is not the one this was written for is an error."""
    u16 = lambda at: struct.unpack_from("<H", data, at)[0]
    u64 = lambda at: struct.unpack_from("<Q", data, at)[0]
    if data[:6] != b"BFEVFL" or u16(0x20) != 1:
        raise ValueError("not an event flow file of one flowchart")
    chart = u64(u64(0x28))
    if data[chart:chart + 4] != b"EVFL" or u16(chart + 0x16) != 29 or u16(chart + 0x18) != 2:
        raise ValueError("the opening's flowchart is not the one of 29 events and 2 entry points")
    events, entries = u64(chart + 0x30), u64(chart + 0x40)
    event = lambda i: events + 0x30 * i

    def text(ptr):
        return bytes(data[ptr + 2:ptr + 2 + u16(ptr)]).decode("utf-8", "replace") if ptr else ""

    def plays(i):
        """the cutscene an EventTransition step plays: the first string of its parameters that names a Dm_ flow"""
        at = u64(event(i) + 0x10)
        for k in range(u16(at + 2) if at else 0):
            item = u64(at + 0x10 + 8 * k)
            if data[item] in (0, 5) and u16(item + 2) == 1 and text(u64(item + 0x10)).startswith("Dm_"):
                return text(u64(item + 0x10))
        return ""

    step = lambda i: (data[event(i) + 8], u16(event(i) + 0x0a))   # (its kind: 0 an action, 1 a switch; its next step)
    if (u16(entries + 0x1c) != 7 or step(7) != (0, 14) or plays(7) != "Dm_Kokiri_0000" or data[event(14) + 8] != 1 or
            step(23) != (0, 0) or step(0) != (0, 17) or plays(0) != "Dm_Kokiri_0030" or data[event(17) + 8] != 1 or step(19) != (0, 10)):
        raise ValueError("the opening's steps are not the ones this was written for")
    out = bytearray(data)
    struct.pack_into("<H", out, entries + 0x1c, 14)        # (the first entry point starts after the narration)
    struct.pack_into("<H", out, event(23) + 0x0a, 19)      # (the wait goes on to what follows Navi's cutscene)
    return bytes(out)


def sword_chest_plain(data):
    """Get_StoneOfForest (a BFEVFL file) with the Kokiri Sword's chest's own cutscene passed over: the new bytes, of the
    same size. Every step it relies on is checked first (see SWORD_EVENT, above): a flow that is not the one this
    was written for is an error."""
    u16 = lambda at: struct.unpack_from("<H", data, at)[0]
    u64 = lambda at: struct.unpack_from("<Q", data, at)[0]
    if data[:6] != b"BFEVFL" or u16(0x20) != 1:
        raise ValueError("not an event flow file of one flowchart")
    chart = u64(u64(0x28))
    if data[chart:chart + 4] != b"EVFL" or u16(chart + 0x16) != 227 or u16(chart + 0x18) != 27:
        raise ValueError("the flowchart is not the one of 227 events and 27 entry points")
    events, entries = u64(chart + 0x30), u64(chart + 0x40)
    event = lambda i: events + 0x30 * i

    def text(ptr):
        return bytes(data[ptr + 2:ptr + 2 + u16(ptr)]).decode("utf-8", "replace") if ptr else ""

    def plays(i):
        """the cutscene an EventTransition step plays: the string of its parameters that names a Dm_ flow"""
        at = u64(event(i) + 0x10)
        for k in range(u16(at + 2) if at else 0):
            item = u64(at + 0x10 + 8 * k)
            if data[item] in (0, 5) and u16(item + 2) == 1 and text(u64(item + 0x10)).startswith("Dm_"):
                return text(u64(item + 0x10))
        return ""

    step = lambda i: (data[event(i) + 8], u16(event(i) + 0x0a))   # (its kind: 0 an action, 1 a switch; its next step)
    if (u16(entries + 0x20 * 7 + 0x1c) != 48 or step(48) != (0, 47) or step(47) != (0, 88) or plays(47) != "Dm_SY_Treasurebox" or
            step(88) != (0, 211) or plays(88) != "Dm_Kokiri_0063" or data[event(211) + 8] != 1):
        raise ValueError("the sword chest's steps are not the ones this was written for")
    out = bytearray(data)
    struct.pack_into("<H", out, event(47) + 0x0a, 211)     # (the chest's opening goes on to what follows the sword's cutscene)
    return bytes(out)


# ---- a gift: what a character hands Link ----
# Nearly every item given by a character, a fairy or a scene goes through one flow of the game's, Dm_SY_GetInEvent (and
# GetPouchContent): the scene's own flow calls it as a sub-flow and names the item in the call's parameters, a string
# (Darunia's, Dm_Goron_0030: GetInEvent_Goron with ActorName "Item_Gauntlet_Goron"). 209 such calls were counted.
# So a gift is changed by changing that string. The item's name is the scene's actor's name too (the bracelet Darunia
# holds out), from the same file's strings, so the string itself is left: the new name is put at the file's end and
# the parameter made to point at it. The scene is as it was: Darunia still holds out a bracelet.
GIFT_FLOWS = "Event/EventFlow"
FLOW_EXTRA = 288   # (a flow's entry in the size table: its size rounded up to 32 and 272 or 280 in the three looked at)


def gift_item(data, old, new):
    """An event flow (a BFEVFL file) with every sub-flow call's parameter that is the string `old` made the string
    `new`: the new bytes (longer by the new string, the file's size in its header raised), or None when no call has
    it. The other strings and every other pointer are as they were."""
    return gift_items(data, {old: new})[0]


def flow_reach(data, entry):
    """The events of a flow's flowchart that its entry point `entry` can come to (their indices), by every branch:
    an action's and a sub-flow call's next, a switch's cases, a fork's branches and its join. ValueError: no such
    entry point."""
    u16 = lambda at: struct.unpack_from("<H", data, at)[0]
    u64 = lambda at: struct.unpack_from("<Q", data, at)[0]
    chart = u64(u64(0x28))
    count, entries_n = u16(chart + 0x16), u16(chart + 0x18)
    events, names, entries = u64(chart + 0x30), u64(chart + 0x38), u64(chart + 0x40)

    def text(ptr):
        return bytes(data[ptr + 2:ptr + 2 + u16(ptr)]).decode("utf-8", "replace") if 0 < ptr < len(data) - 2 else ""

    first = [u16(entries + 0x20 * k + 0x1c) for k in range(entries_n) if names and text(u64(names + 8 + 16 * (k + 1) + 8)) == entry]
    if not first:
        raise ValueError("the flow has no entry point %s" % entry)
    seen, stack = set(), list(first)
    while stack:
        i = stack.pop()
        if i == 0xFFFF or i >= count or i in seen:
            continue
        seen.add(i)
        e = events + 0x30 * i
        kind = data[e + 8]
        if kind in (0, 3, 4):
            stack.append(u16(e + 0x0a))
        elif kind == 1:
            cases = u64(e + 0x18)
            stack += [u16(cases + 8 * c + 4) for c in range(u16(e + 0x0a))]
        elif kind == 2:
            forks = u64(e + 0x10)
            stack += [u16(forks + 2 * c) for c in range(u16(e + 0x0a))] + [u16(e + 0x0c)]
    return seen


def gift_items(data, swaps, kinds=(4,)):
    """gift_item for several items of one flow at once: swaps is {old: new}. kinds: the steps looked at (4 a call of a
    sub-flow, the gifts'; 0 an action and 1 a question too, for a name the flow sets or asks about: the songs'). All are found before any is changed, so
    that one gift's new item is not taken for another's old one (a flow with two gifts whose items changed places).
    A key (entry, old) in place of old is only that entry point's calls (flow_reach): two sales of one flow that
    name the same item. Such a key comes before a plain one for the same name.
    Returns (the new bytes, or None when no call has any of them; the keys that were found)."""
    scoped = {}   # an entry point -> the events it comes to
    for key in swaps:
        if isinstance(key, tuple) and key[0] not in scoped:
            scoped[key[0]] = flow_reach(data, key[0])
    u16 = lambda at: struct.unpack_from("<H", data, at)[0]
    u64 = lambda at: struct.unpack_from("<Q", data, at)[0]
    if data[:6] != b"BFEVFL" or u16(0x20) != 1 or struct.unpack_from("<I", data, 0x1c)[0] != len(data):
        raise ValueError("not an event flow file of one flowchart")
    chart = u64(u64(0x28))
    if data[chart:chart + 4] != b"EVFL":
        raise ValueError("the flowchart is not where the file says")
    events, count = u64(chart + 0x30), u16(chart + 0x16)

    def text(ptr):
        return bytes(data[ptr + 2:ptr + 2 + u16(ptr)]).decode("utf-8", "replace") if 0 < ptr < len(data) - 2 else ""

    where = []
    for i in range(count):
        e = events + 0x30 * i
        if data[e + 8] not in kinds:   # (4: a call of a sub-flow)
            continue
        params = u64(e + 0x10)
        if not params or data[params] != 1:   # (1: a container of named parameters)
            continue
        for k in range(u16(params + 2)):
            item = u64(params + 0x10 + 8 * k)
            if data[item] != 5 or u16(item + 2) != 1:   # (5: a string of its own, not a name passed on)
                continue
            name = text(u64(item + 0x10))
            key = next(((entry, name) for entry, reach in scoped.items() if i in reach and (entry, name) in swaps), name)
            if key in swaps:
                where.append((item + 0x10, swaps[key], key))
    if not where:
        return None, set()
    out = bytearray(data)
    at = {}
    for pointer, new, _ in where:
        if new not in at:   # (each new name once, at the file's end)
            out += b"\0" * (-len(out) % 8)
            at[new] = len(out)
            name = new.encode("utf-8")
            out += struct.pack("<H", len(name)) + name + b"\0"
        struct.pack_into("<Q", out, pointer, at[new])
    out += b"\0" * (-len(out) % 8)
    struct.pack_into("<I", out, 0x1c, len(out))
    return bytes(out), {old for _, _, old in where}


def size_entry(size, extra=264):
    """what the game's size table holds for a file of `size` bytes unpacked: the size rounded up to 32, and 264 for a
    map file (every one looked at had exactly that), 312 for an actor's pack (PACK_EXTRA: six looked at)"""
    return (size + 31 & ~31) + extra


PACK_EXTRA = 312
SHOP_EXTRA = 65536   # (for a list of the game's actors and a language's archive, whose entries follow no rule looked for: far more than either grows)


def size_table_update(tbl, sizes, extra=264):
    """The size table ("RESTBL": a header of 22 bytes, then a path's CRC32 and a size for each file, sorted by the
    CRC32) with the entries of `sizes` ({path without .zs: bytes unpacked}) raised to fit."""
    if tbl[:6] != b"RESTBL":
        raise ValueError("not a size table (%r)" % tbl[:6])
    count = struct.unpack_from("<I", tbl, 14)[0]
    if 22 + count * 8 > len(tbl):
        raise ValueError("the size table's entry count does not fit the file")
    out = bytearray(tbl)
    for path, size in sizes.items():
        crc = zlib.crc32(path.encode()) & 0xffffffff
        lo, hi = 0, count
        while lo < hi:
            mid = (lo + hi) // 2
            if struct.unpack_from("<I", tbl, 22 + mid * 8)[0] < crc:
                lo = mid + 1
            else:
                hi = mid
        at = 22 + lo * 8
        if lo >= count or struct.unpack_from("<I", tbl, at)[0] != crc:
            raise ValueError("%s is not in the size table" % path)
        struct.pack_into("<I", out, at + 4, max(struct.unpack_from("<I", tbl, at + 4)[0], size_entry(size, extra)))
    return bytes(out)


# The size table has an entry for each parameter file inside a pack too, by the file's own name, and the game takes
# the memory for the file as it is read from it: the Bomb Bag's table of game parameters, given a parent, no longer
# fitted its entry and the game stopped there as the pack was read (the Boomerang's, changed the same way, still
# fitted its own). The game's entries follow no rule found (252 bytes: 5432; 568 bytes: 5896; 152 bytes: 5288), so a
# changed file's entry is raised by this much, far more than any of them grows.
PART_GROWTH = 4096


def size_table_raise(tbl, paths, by=PART_GROWTH):
    """the size table with the entries of `paths` raised by `by`; a path with no entry is left out"""
    count = struct.unpack_from("<I", tbl, 14)[0]
    index = {struct.unpack_from("<I", tbl, 22 + k * 8)[0]: 22 + k * 8 for k in range(count)}
    out = bytearray(tbl)
    for path in set(paths):
        at = index.get(zlib.crc32(path.encode()) & 0xffffffff)
        if at is not None:
            struct.pack_into("<I", out, at + 4, struct.unpack_from("<I", tbl, at + 4)[0] + by)
    return bytes(out)


# What a new parameter file's entry is given: more than any of the game's own of its kind has (5288 to 5984 for a pouch
# file, of 152 to 740 bytes).
PART_NEW = 8192


def size_table_add(tbl, paths, size=PART_NEW):
    """the size table with an entry of `size` for each of `paths` that it does not have: put in its place among the
    CRC32s, which are sorted, and the count raised. A path whose CRC32 the table has is left as it is."""
    count = struct.unpack_from("<I", tbl, 14)[0]
    end = 22 + count * 8
    have = {struct.unpack_from("<I", tbl, 22 + k * 8)[0] for k in range(count)}
    new = sorted({zlib.crc32(path.encode()) & 0xffffffff for path in paths} - have)
    if not new:
        return tbl
    rows = [bytes(tbl[22 + k * 8:30 + k * 8]) for k in range(count)] + [struct.pack("<II", crc, size) for crc in new]
    rows.sort(key=lambda r: struct.unpack_from("<I", r)[0])
    return bytes(tbl[:14]) + struct.pack("<I", len(rows)) + bytes(tbl[18:22]) + b"".join(rows) + bytes(tbl[end:])


def unpack(data, zs, dicts):
    if data[:4] != ZSTD:
        return data
    try:
        return zs.ZstdDecompressor().decompress(data, max_output_size=1 << 28)
    except Exception:
        pass
    for d in dicts:
        try:
            return zs.ZstdDecompressor(dict_data=d).decompress(data, max_output_size=1 << 28)
        except Exception:
            pass
    raise ValueError("could not be decompressed")


def dictionaries(romfs, zs):
    try:
        raw = zs.ZstdDecompressor().decompress(open(os.path.join(romfs, "Pack", "ZsDic.pack.zs"), "rb").read(), max_output_size=1 << 28)
        start = struct.unpack_from("<I", raw, 0x0c)[0]
        return [zs.ZstdCompressionDict(raw[start + st:start + end], dict_type=zs.DICT_TYPE_FULLDICT)
                for _, _, st, end in (struct.unpack_from("<IIII", raw, 0x20 + k * 16) for k in range(struct.unpack_from("<H", raw, 0x1a)[0]))]
    except Exception:
        return []


def settings(game):
    """the randomizer's lines of the options file (0 where it does not say)"""
    got = {"rando_on": 0, "rando_seed": 0, "rando_chests": 0, "rando_keys": 0, "rando_major": 0, "rando_open_deku": 0, "rando_open_forest": 0,
           "rando_skip_intro": 0, "rando_skulltulas": 0, "rando_quests": 0, "rando_frogs": 0, "rando_light_arrows": 0,
           "rando_start_rupees": 0, "rando_scrubs": 0, "rando_shops": 0, "rando_progressive": 0, "rando_songs": 0, "rando_heart_pieces": 0,
           "rando_shop_shelves": 0, "rando_sword_shield": 0, "rando_dungeon_rewards": 0}
    try:
        with open(os.path.join(game, "hookshot_options.ini"), encoding="utf-8", errors="replace") as f:
            for line in f:
                key, eq, value = line.partition("=")
                if eq and key.strip() in got:
                    try:
                        got[key.strip()] = int(value.strip())
                    except ValueError:
                        pass
    except OSError:
        pass
    return got


def set_option(game, key, value):
    """one line of the options file set (the others kept as they are)"""
    path = os.path.join(game, "hookshot_options.ini")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    lines = [x for x in lines if x.partition("=")[0].strip() != key] + ["%s=%d" % (key, value)]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


# ---- the tracker: the checks the seed has in each area, for the game's menu ----
# The Insert menu's Tracker tab (gpu/vk/vk_menu.cpp: tracker_load) shows <game folder>\mods\rando-seed\tracker.txt as
# it is: a row for each line "<name>|<what>", TRACKER_ROWS of them at most, a name of up to 47 characters and a
# value of up to 71. Lines that start with # are not rows.
TRACKER = "tracker.txt"
TRACKER_ROWS = 48
AREA_NAMES = {
    "KokiriForest": "Kokiri Forest", "LostWood": "Lost Woods", "SacredForestMeadow": "Sacred Forest Meadow", "HyruleField": "Hyrule Field",
    "Market": "Market", "HyruleCastle": "Hyrule Castle", "GanonCastle": "Ganon's Castle (outside)", "KakarikoVillage": "Kakariko Village",
    "Graveyard": "Graveyard", "DeathMountainTrail": "Death Mountain Trail", "DeathMountainCrater": "Death Mountain Crater",
    "GoronCity": "Goron City", "ZoraRiver": "Zora's River", "ZoraDomain": "Zora's Domain", "ZoraFountain": "Zora's Fountain",
    "GerudoValley": "Gerudo Valley", "GerudoFortress": "Gerudo's Fortress", "HountedWasteland": "Haunted Wasteland",
    "DesertColossus": "Desert Colossus", "InsideTheDekuTree": "Inside the Deku Tree", "DodongoCavern": "Dodongo's Cavern",
    "InsideJabuJabuBelly": "Inside Jabu-Jabu's Belly", "BottomOfTheWell": "Bottom of the Well", "ForestTemple": "Forest Temple",
    "FireTemple": "Fire Temple", "IceCavern": "Ice Cavern", "WaterTemple": "Water Temple", "ShadowTemple": "Shadow Temple",
    "SpiritTemple": "Spirit Temple", "GerudoTrainingGround": "Gerudo Training Ground", "InsideGanonCastle": "Inside Ganon's Castle",
    "DreamWorld": "Dream World",
}


def tracker_lines(chests, skulls, gifts=None):
    """The tracker file's lines. chests, skulls and gifts: {area (the Banc folder): how many of them take part}. A
    line for the whole game, then one for each area that has any, by its name; no more than the menu has rows for."""
    gifts = gifts or {}

    def what(c, k, g):
        parts = (["%d chest%s" % (c, "" if c == 1 else "s")] if c else []) + (["%d Gold Skulltula%s" % (k, "" if k == 1 else "s")] if k else [])
        parts += ["%d gift%s" % (g, "" if g == 1 else "s")] if g else []
        return ", ".join(parts) or "nothing"

    areas = sorted(set(chests) | set(skulls) | set(gifts), key=lambda a: AREA_NAMES.get(a, a).lower())
    areas = [a for a in areas if chests.get(a, 0) or skulls.get(a, 0) or gifts.get(a, 0)]
    rows = [("The whole game", what(sum(chests.values()), sum(skulls.values()), sum(gifts.values())))]
    rows += [(AREA_NAMES.get(a, a), what(chests.get(a, 0), skulls.get(a, 0), gifts.get(a, 0))) for a in areas]
    if len(rows) > TRACKER_ROWS:   # (more areas than rows: the last row says so)
        rows = rows[:TRACKER_ROWS - 1] + [("And %d more areas" % (len(rows) - TRACKER_ROWS + 1), "see the spoiler")]
    return ["# The checks of this seed in each area, for the menu's Tracker tab: <name>|<what>"] + [
        "%s|%s" % (name.replace("|", "/")[:47], value[:71]) for name, value in rows]


# ---- the checks, one by one: for the Tracker tab's "Go there" ----
# <game folder>\mods\rando-seed\checks.txt, a line for each chest and Gold Skulltula that takes part:
# "<the area's name, as its tracker row>|<Chest or Gold Skulltula>|<the Banc folder>|<C, A or CA: the ages whose map has
# it>|<x> <y> <z>|<what the rules ask for>". The menu steps through an area's lines and has the game take Link to one
# (the debug tools: the teleport to the folder's map, then the place). What a check holds is not in the file. A gift
# or a Business Scrub's sale has a line too, its kind the gift's name and its place from GIFT_PLACES. CHECK_ROWS: as
# many as the menu keeps (kTrackerChecks).
# What the rules ask for: the gating items of the check's rule, each by its two letters (CHECK_CODES, the menu's
# kLogicItems), with commas; "-" when it asks for nothing. The menu says a check is in logic when Link carries them
# all. The rules ask for too much, never too little (see RULES): a check not in logic may be within reach.
CHECKS = "checks.txt"
CHECK_ROWS = 320
CHECK_NAME = 79   # (a check's name: as many characters as the menu keeps of it)
CHECK_CODES = collections.OrderedDict((
    ("Item_Sword_Kokiri", "KS"), ("Item_Range_SlingShot", "SL"), ("Item_BombBag_Small", "BB"), ("Item_Boomerang", "BM"),
    ("Item_GlassTruth", "LT"), ("Item_Range_Bow", "BW"), ("Item_Hammer", "HM"), ("Item_HeavyBoot", "IB"), ("Item_HoverBoot", "HB"),
    ("Item_Longshot", "LS"), ("Item_Gauntlet_Silver", "SG"), ("Item_Shield_Mirror", "MS"), ("Item_Gauntlet_Gold", "GG"),
    ("Item_Gauntlet_Goron", "GB"), ("Item_Scale_Silver", "SS"), ("Item_Wallet_Medium", "AW"), ("Item_Wallet_Large", "GW"),
    ("Item_Melody_ZeldaLullaby", "ZL"), ("Item_Melody_EponaSong", "EP"), ("Item_Melody_SariaSong", "SR"), ("Item_Melody_TimeSong", "ST"),
    ("Item_Melody_StormSong", "SO"), ("Item_Melody_SpiritRequiem", "RQ"), ("Item_Melody_ShadowNocturne", "NC")))


def check_ages(names):
    """C, A or CA: the ages whose map files (names) have a check. A map without an age in its name is both's."""
    child = any("_Child" in n or "_Adult" not in n for n in names)
    adult = any("_Adult" in n or "_Child" not in n for n in names)
    return ("C" if child else "") + ("A" if adult else "")


# A gift or a Business Scrub's sale is a scene, not an actor with a hash: where Link stands for it is written here, by
# the gift's key, from the map files of its area (GIFTS' and SCRUBS' area): the giver, or the game's own place for
# Link there (a mini-game's StartPos, a scene's anchor). (the ages whose map has it, the place). Its line's kind is the
# gift's name. Read from the map files, not walked to: the four tried unattended are named in the README.
GIFT_PLACES = {
    "darunia": ("C", (-0.2, 98.6, -38.5)),                 # (Npc_Goron_Darunia_Child at z -41.8, the door at -29.2)
    "lostwood_target": ("C", (41.1, 102.6, -4.9)),         # (HitTargetOfDekuScrub)
    "skulltula_house_10": ("CA", (-26.5, 109.9, 74.5)),    # (Npc_SkullDad at z 72.5)
    "skulltula_house_20": ("CA", (-26.5, 109.9, 74.5)),
    "skulltula_house_30": ("CA", (-26.5, 109.9, 74.5)),
    "skulltula_house_50": ("CA", (-26.5, 109.9, 74.5)),
    "forest_stage_skull": ("C", (-10.0, 83.2, -52.0)),     # (ScrubForestStageElder at z -54.5)
    "forest_stage_truth": ("C", (-10.0, 83.2, -52.0)),
    "bowling_bag": ("C", (-25.1, 100.0, 9.5)),             # (BombchuBowlingStartPos)
    "bowling_heart": ("C", (-25.1, 100.0, 9.5)),
    "diving": ("C", (25.4, 113.2, -5.3)),                  # (MiniGame_Diving_PlayerStart)
    "fishing_child": ("C", (-97.6, 134.1, 489.7)),         # (MiniGame_Fishing_PlayerStart)
    "fishing_adult": ("A", (-97.6, 134.1, 489.7)),
    "frogs": ("C", (9.2, 101.9, -54.8)),                   # (OcarinaPoint_MiniGame_FrogTenors)
    "gallery_market": ("C", (-14.2, 100.1, -12.4)),        # (HitTargetStartPos)
    "gallery_kakariko": ("A", (-58.5, 91.4, 62.6)),        # (HitTargetStartPos)
    "cucco_lady": ("C", (-73.9, 99.5, 82.9)),              # (CatchCucco_GoalPoint)
    "archery_heart": ("A", (69.5, 115.0, 36.3)),           # (HorsebackArcheryPlayerPos)
    "archery_quiver": ("A", (69.5, 115.0, 36.3)),
    "rolling_goron": ("C", (-10.3, 109.6, -16.5)),         # (Npc_Goron_006_Child)
    "roof_man": ("CA", (-36.1, 107.5, 29.0)),              # (his HeartPieceAnchor)
    "skull_kid_song": ("C", (-28.6, 101.0, 1.6)),          # (On_Center_Npc_SkullKid_Child)
    "skull_kid_game": ("C", (48.4, 97.8, 15.8)),           # (OcarinaPoint_SkullKidSession)
    "dog_lady": ("C", (-0.3, 100.1, 26.9)),                # (SubEvent_FindRichard_Link_Stay)
    "light_arrows": ("A", (108.0, 103.9, -34.0)),          # (the Temple of Time, before the Spirit Stones' base at x 110.4)
    "scrub_heart_field": ("CA", (25.0, 129.9, 22.1)),      # (the scrubs: where the map has them)
    "scrub_heart_secret": ("C", (-23.0, 119.1, 33.0)),
    "scrub_sticks": ("CA", (-45.2, 95.2, 72.6)),
    "scrub_nuts": ("CA", (7.3, 82.9, -85.6)),
    "song_zelda": ("C", (5.1, 126.8, -236.4)),             # (DoorOfTime_MeetImpa_StartPos: before Impa, in the castle's courtyard)
    "song_epona": ("C", (-91.9, 150.6, 247.0)),            # (Npc_Hylia_Malon_Child at z 245.4, Lon Lon Ranch)
    "song_saria": ("C", (-6.9, 114.4, -85.2)),             # (Dm_MelodyGet_Saria_Start)
    "song_sun": ("CA", (149.5, 98.7, 2.7)),                # (Dm_MelodyGet_Sun_Child: in the royal tomb)
    "song_time": ("C", (0.2, 150.2, 56.8)),                # (GetOcarinaOfTime_AreaOut_Destination: before the Market's bridge)
    "song_storms": ("A", (1.2, 105.1, 49.5)),              # (Npc_Hylia_009_Adult at z 51.3, in the windmill)
    "song_minuet": ("A", (-7.0, 114.4, -84.3)),            # (Dm_MelodyGet_Forest_Position)
    "song_bolero": ("A", (-17.5, 114.0, -10.2)),           # (Dm_MelodyGet_Fire_LinkPosition)
    "song_serenade": ("A", (-45.1, 109.7, 41.8)),          # (before the chest whose opening starts the lesson, SageOfWater_MelodyGet_Water)
    "song_requiem": ("A", (-156.0, 95.4, 10.3)),           # (Dm_MelodyGet_Spilit_Player_pos)
    "song_nocturne": ("A", (-119.8, 96.6, 58.7)),          # (KakarikoVillage_Entrance: the lesson starts as Link comes in)
    "song_prelude": ("A", (134.0, 106.4, -34.0)),          # (before Npc_Hylia_Sheik_Adult at x 139.0, past the Door of Time)
}


# ---- a chest's and a Gold Skulltula's name, made from the map files ----
# The game names neither. What its map files do say is put together (check_name): what the chest held before the
# shuffle (known to who knows the game, and nothing about what it holds now), whether it is the big kind, a Gold
# Skulltula's night and its bean soil, and where: a dungeon's room by its number, a part of the map that has a name
# of its own (Lake Hylia, Lon Lon Ranch, the Temple of Time: a LocationArea not the map's own), or the way out it
# is near (a MapIconEntranceAnchor within EXIT_NEAR metres). "Chest (red rupee), room 10", "Big chest (Kokiri Sword)",
# "Gold Skulltula, night, by the Lost Woods exit". Two of an area that come out the same are numbered, by place.
# Nobody has gone through them: they tell one check from the next, and are not the names a player would give.
ITEM_WORDS = {
    "TBox_Rupee_Green": "green rupee", "TBox_Rupee_Blue": "blue rupee", "TBox_Rupee_Red": "red rupee", "TBox_Rupee_Purple": "purple rupee",
    "TBox_Shield_Deku": "Deku Shield", "TBox_Shield_Hylian": "Hylian Shield",
    "TBox_Rupee_Silver": "silver rupee", "TBox_Rupee_Gold": "gold rupee", "Item_ScrubBusinessSeed": "Deku Seeds", "Obj_Heart_Piece": "Piece of Heart",
    "Item_Token_Gold": "Skulltula token", "TBox_DekuNutBundle": "Deku Nuts", "TBox_ArrowBundle_Small": "arrows", "TBox_ArrowBundle_Medium": "arrows",
    "TBox_ArrowBundle_Large": "arrows", "Item_BombchuBundle_Small": "Bombchus", "Item_BombBundle_Small": "bombs", "Tbox_MagicJar_Large": "magic jar",
    "Item_StickBag_Large": "Deku Stick bag", "Item_NutBag_Large": "Deku Nut bag", "Item_DekuStickBundle_Small": "Deku Sticks",
    "Item_Sword_Kokiri": "Kokiri Sword", "Item_Range_SlingShot": "Slingshot", "Item_BombBag_Small": "Bomb Bag", "Item_Boomerang": "Boomerang",
    "Item_GlassTruth": "Lens of Truth", "Item_Range_Bow": "Bow", "Item_Hammer": "Megaton Hammer", "Item_HeavyBoot": "Iron Boots",
    "Item_HoverBoot": "Hover Boots", "Item_Longshot": "Longshot", "Item_Gauntlet_Silver": "Silver Gauntlets", "Item_Shield_Mirror": "Mirror Shield",
    "Item_Gauntlet_Gold": "Golden Gauntlets", "Item_Gauntlet_Goron": "Goron's Bracelet", "Item_Dungeon_SmallKey": "small key", "Item_Dungeon_BossKey": "boss key", "Item_Dungeon_Map": "map",
    "Item_Dungeon_Compass": "compass",
}
EXIT_NEAR = 40.0
MARKS = ("LocationArea", "MapIconEntranceAnchor")


def spaced(name):
    """an actor's or a place's name in words: "LonLonRanch" -> "Lon Lon Ranch", "Item_Arrow_Fire" -> "Arrow Fire" """
    name = name.split("_", 1)[1] if name.split("_", 1)[0] in ("Item", "TBox", "Tbox", "Obj", "Weapon", "Armor") and "_" in name else name
    out = ""
    for k, ch in enumerate(name.replace("_", " ")):
        out += (" " if k and ch.isupper() and out[-1:].islower() else "") + ch
    return out


def marks(data):
    """What a map file has to name its checks by: [(hash, Gyaml, place, scale, {a Dynamic's name: its text, or its
    number as it is written})] for its chests, Gold Skulltulas, LocationAreas and MapIconEntranceAnchors."""
    if data[:2] != b"YB":
        raise ValueError("not a little-endian BYML")
    key_at, str_at, root = struct.unpack_from("<III", data, 4)
    keys, strings = table(data, key_at), table(data, str_at)
    out = []
    for name, kind, value, _ in entries(data, root, keys):
        if name != "Actors" or kind != 0xC0:
            continue
        n = int.from_bytes(data[value + 1:value + 4], "little")
        vals = value + 4 + (n + 3 & ~3)
        for i in range(n):
            if data[value + 4 + i] != 0xC1:
                continue
            ident, gyaml, pos, scale, dyn, turned = None, "", (), (), None, (0.0, 0.0, 0.0)
            for k, t, v, _ in entries(data, struct.unpack_from("<I", data, vals + 4 * i)[0], keys):
                if k == "Hash" and t == 0xD5:
                    ident = struct.unpack_from("<Q", data, v)[0]
                elif k == "Hash" and t == 0xD3:
                    ident = v
                elif k == "Gyaml" and t == 0xA0:
                    gyaml = strings[v] if v < len(strings) else ""
                elif k in ("Translate", "Scale") and t == 0xC0 and int.from_bytes(data[v + 1:v + 4], "little") == 3:
                    three = tuple(round(x, 1) for x in struct.unpack_from("<3f", data, v + 8))
                    pos, scale = (three, scale) if k == "Translate" else (pos, three)
                elif k == "Rotate" and t == 0xC0 and int.from_bytes(data[v + 1:v + 4], "little") == 3:
                    turned = struct.unpack_from("<3f", data, v + 8)
                elif k == "Dynamic" and t == 0xC1:
                    dyn = v
            if gyaml in MARKS or gyaml == SKULLTULA or gyaml.startswith("Obj_TBox") or gyaml in HEART_ACTORS:
                words = {}
                for dk, dt, dv, _ in entries(data, dyn, keys) if dyn is not None else ():
                    words[dk] = (strings[dv] if dv < len(strings) else "") if dt == 0xA0 else dv
                words["Rotate"] = turned   # (not a Dynamic's name: how the actor is turned, in radians about X, Y and Z)
                out.append((ident, gyaml, pos, scale, words))
    return out


# Where Link is put to go to a chest: not on it. Above a chest he came down on it or behind it, and behind one of Mido's
# house's he was between the chest and the wall, where a wall he could not see kept him (seen in play). A chest's
# front is its own +Z turned as the chest is (about X, then Y, then Z: the four of Mido's house, turned 0.83 to -0.78
# about Y, face the room's middle so); he is put CHEST_FRONT metres before it, at its height.
CHEST_FRONT = 1.3


def chest_front(pos, turned, far=CHEST_FRONT):
    """the place `far` metres before a chest: its place and how it is turned (radians about X, Y, Z)"""
    x, y, z = 0.0, 0.0, 1.0
    rx, ry, rz = turned
    y, z = y * math.cos(rx) - z * math.sin(rx), y * math.sin(rx) + z * math.cos(rx)
    x, z = x * math.cos(ry) + z * math.sin(ry), -x * math.sin(ry) + z * math.cos(ry)
    x, y = x * math.cos(rz) - y * math.sin(rz), x * math.sin(rz) + y * math.cos(rz)
    flat = math.hypot(x, z) or 1.0
    return (round(pos[0] + far * x / flat, 1), pos[1], round(pos[2] + far * z / flat, 1))


# ---- Songs: the twelve songs, shuffled among the twelve places that teach one ----
# Each lesson gives its song as a character gives a gift: its flow (Dm_MelodyGet_...) calls the game's
# GetPouchContent with the song's name. So a lesson is a gift whose item is a song (SONGS), and the song it gives is
# changed as a gift's is. The lesson's scene is as it was: its teacher plays the notes of the song the game has there,
# and the scene of the song got names the one the shuffle put there.
# A song is not only named where it is given. The game asks "has Link this song" to know whether a lesson is done
# (the windmill man, Sheik, the Kokiri: IsGet.Item_Melody_..., EventQueryCheckIsGet), the Bolero's lesson sets its
# flag itself before the gift, and the royal tomb's two stones talk as after the lesson once Link has the Sun's Song
# (their AIScheduleParam's ConditionFlag). With the songs shuffled each of these means the lesson, not the song, so
# each is made to name the song its lesson gives now (SONG_FLOWS, SONG_STONES): a song found elsewhere does not shut
# the place that taught it. The flows that play a song (Dm_SY_Ocarina...) are left: there the song is the song.
# Left as the game has them, not looked into: Kakariko's adult logic (Logic/KakarikoVillage_Adult_Common_*, which
# names the Song of Storms' flag and cannot be changed in place), Navi's hints, the Scarecrow's Song.
# The rules: a song that gates the game is a gating item (SONG_GATES), placed by the logic with the others, and only
# in a lesson (place's `bound`). What the rules had folded in is named (song_need): an adult has Zelda's Lullaby (the
# Zoras' and Darunia's doors), Saria's Song (Darunia), the Song of Time (the Door of Time) and, asked for too much
# rather than too little, the Song of Storms (the well, the grottos); the Zoras' places ask for the Lullaby; the
# Shadow Temple for the Nocturne (the only way in), the Spirit Temple and the Colossus for the Requiem (a child's only
# way there); Ganon's Castle for all of them. Epona's Song gates the horseback archery only. The other five gate
# nothing. A lesson asks for what its line says, the songs named: none asks for the song the game teaches there.
ZL, EPONA, SARIA, SUN, TIME, STORMS, MINUET, BOLERO, SERENADE, REQUIEM, NOCTURNE, PRELUDE = SONG_ITEMS = tuple(
    "Item_Melody_" + n for n in ("ZeldaLullaby", "EponaSong", "SariaSong", "SunSong", "TimeSong", "StormSong", "ForestMinuet", "FireBolero",
                                 "WaterSerenade", "SpiritRequiem", "ShadowNocturne", "LightPrelude"))
SONG_GATES = frozenset((ZL, EPONA, SARIA, TIME, STORMS, REQUIEM, NOCTURNE))
SONG_GROWN = frozenset((ZL, SARIA, TIME, STORMS))   # (what an adult's check asks for)
SONG_ADULT = ADULT | {ZL, SARIA, TIME}              # (what an adult's lesson asks for: an adult, without the Song of Storms)
SONG_AREAS = {"ZoraDomain": {ZL}, "ZoraFountain": {ZL}, "InsideJabuJabuBelly": {ZL}, "BottomOfTheWell": {STORMS}, "ShadowTemple": {NOCTURNE},
              "SpiritTemple": {REQUIEM}, "DesertColossus": {REQUIEM}, "InsideGanonCastle": set(SONG_GATES)}
SONG_GIFTS = {"darunia": {ZL, SARIA}, "skull_kid_song": {SARIA}, "archery_heart": {EPONA}, "archery_quiver": {EPONA}}
SONGS_HARD = ("frogs",)   # (the frogs ask for six songs: with the songs shuffled, for everything, so no gating item is theirs)
SONGS = (
    Gift("song_zelda", "Dm_MelodyGet_Zelda", (ZL,), ZL, "HyruleCastle", "Impa's lesson: Zelda's Lullaby", CHILD, "songs"),
    Gift("song_epona", "Dm_MelodyGet_Epona", (EPONA,), EPONA, "HyruleField", "Malon's lesson: Epona's Song", CHILD, "songs"),
    Gift("song_saria", "Dm_MelodyGet_Saria", (SARIA,), SARIA, "SacredForestMeadow", "Saria's lesson: Saria's Song", CHILD, "songs"),
    Gift("song_sun", "Dm_MelodyGet_Sun_03", (SUN,), SUN, "Graveyard", "the royal tomb: the Sun's Song", CHILD | {ZL}, "songs"),
    Gift("song_time", "Dm_MelodyGet_Time", (TIME,), TIME, "HyruleField", "the Ocarina of Time: the Song of Time", ADULT | {ZL, SARIA}, "songs"),
    Gift("song_storms", "Dm_MelodyGet_Storm", (STORMS,), STORMS, "KakarikoVillage", "the windmill man: the Song of Storms", SONG_ADULT, "songs"),
    Gift("song_minuet", "Dm_MelodyGet_Forest", (MINUET,), MINUET, "SacredForestMeadow", "Sheik, the meadow: the Minuet of Forest", SONG_ADULT, "songs"),
    Gift("song_bolero", "Dm_MelodyGet_Fire", (BOLERO,), BOLERO, "DeathMountainCrater", "Sheik, the crater: the Bolero of Fire", SONG_ADULT | {HAM}, "songs"),
    Gift("song_serenade", "Dm_MelodyGet_Water", (SERENADE,), SERENADE, "IceCavern", "Sheik, the Ice Cavern: the Serenade of Water", SONG_ADULT, "songs"),
    Gift("song_requiem", "Dm_MelodyGet_Spilit", (REQUIEM,), REQUIEM, "DesertColossus", "Sheik, the Colossus: the Requiem of Spirit", SONG_ADULT | DESERT, "songs"),
    Gift("song_nocturne", "Dm_MelodyGet_Shadow", (NOCTURNE,), NOCTURNE, "KakarikoVillage", "Sheik, Kakariko: the Nocturne of Shadow", SONG_ADULT | MEDALS3, "songs"),
    Gift("song_prelude", "Dm_MelodyGet_Shine", (PRELUDE,), PRELUDE, "Market", "Sheik, the Temple of Time: the Prelude of Light", SONG_ADULT | {BOW}, "songs"),
)
# ---- Dungeon rewards: the Spiritual Stones and the Medallions (rando_dungeon_rewards, --dungeon-rewards) ----
# Each of eight dungeons ends in a scene that gives its stone or medallion, by the flow the other gifts go through
# (GetPouchContentByActorName, the item's name a string of the scene's flow): the Deku Tree's last words, Darunia on
# the trail, Ruto at the fountain, and the five sages' awakenings (Dm_Awake_*_Get). The Light Medallion is Rauru's, at
# the Temple of Time, and stays: no dungeon ends in it.
# What the game does with them, looked for in every flow, every logic module, every actor's pack and the list of
# flags: nothing asks whether Link holds one. The story's doors go by each dungeon's own quest, an enum of steps that
# ends in Complete (Get_StoneOfForest, _Fire and _Water; SageOfForest, _Fire, _Water, _Shadow and _Spirit: each has an
# expression <its name>_IsCompleted_Exp, and the Bombchu Shop's door is one that asks it). The flag IsGet.<item> of
# each is in the list and no expression reads it. Their names are otherwise in the scenes that show them (the Door
# of Time's three stones, the bridge to Ganon's Castle) and in their own packs and the menu's. So which stone or
# medallion a dungeon gives changes what the Quest screen shows and nothing the rules ask for: none is a gating item.
# 1, Dungeons: the eight are shuffled among the eight endings (bound to them, as the songs are to the lessons).
# 2, Anywhere, is not made yet: as 1.
# An ending asks for what its dungeon asks for (meant to ask for too much). Not in the tracker yet: no place is
# written for them (GIFT_PLACES). Not seen in play yet.
# REWARDS_READY: the setting is held off until its endings are seen in play (its owner's word, 2026-11-13: off in what
# is pushed, on in the work at hand). Off, the script takes the setting as 0 whatever the options file says, and the
# launcher's row says "Not available yet" (RandoNotYet: 1; on: 2, Dungeons offered and Anywhere not). The two are
# kept in step by tests/test_rando_rewards.py.
REWARDS_READY = True
REWARD_ITEMS = ("Item_Stone_Forest", "Item_Stone_Fire", "Item_Stone_Water",
                "Item_Medal_Forest", "Item_Medal_Fire", "Item_Medal_Water", "Item_Medal_Shadow", "Item_Medal_Spirit")
REWARDS = (
    Gift("reward_deku", "Dm_Kokiri_0130", (REWARD_ITEMS[0],), REWARD_ITEMS[0], "KokiriForest", "the Great Deku Tree's ending", CHILD, "rewards"),
    Gift("reward_dodongo", "Dm_DeathMtTrail_0025", (REWARD_ITEMS[1],), REWARD_ITEMS[1], "DeathMountainTrail", "Dodongo's Cavern's ending: Darunia", CHILD | {BB}, "rewards"),
    Gift("reward_jabu", "Dm_ZoraFountain_0030", (REWARD_ITEMS[2],), REWARD_ITEMS[2], "ZoraFountain", "Jabu-Jabu's ending: Ruto", ADULT, "rewards"),
    Gift("reward_forest", "Dm_Awake_Forest_Get", (REWARD_ITEMS[3],), REWARD_ITEMS[3], "ForestTemple", "the Forest Temple's ending: Saria", ADULT | {BOW}, "rewards"),
    Gift("reward_fire", "Dm_Awake_Fire_Get", (REWARD_ITEMS[4],), REWARD_ITEMS[4], "FireTemple", "the Fire Temple's ending: Darunia", ADULT | {HAM, BOW}, "rewards"),
    Gift("reward_water", "Dm_Awake_Water_Get", (REWARD_ITEMS[5],), REWARD_ITEMS[5], "WaterTemple", "the Water Temple's ending: Ruto", ADULT | {IRON, LONG, BOW}, "rewards"),
    Gift("reward_shadow", "Dm_Awake_Shadow_Get", (REWARD_ITEMS[6],), REWARD_ITEMS[6], "ShadowTemple", "the Shadow Temple's ending: Impa", MEDALS3 | {LENS, HOVER}, "rewards"),
    Gift("reward_spirit", "Dm_Awake_Spirit_Get", (REWARD_ITEMS[7],), REWARD_ITEMS[7], "SpiritTemple", "the Spirit Temple's ending: Nabooru", DESERT | {SG, BOW, MS}, "rewards"),
)
# A flow of the game can have a second file, <name>.110.bfevfl.zs, the one a later version of the game added (the five
# awakenings have one each): both are written with the same change (FLOW_TWIN).
FLOW_TWIN = ".110"
# (the flows that name a song where the lesson is meant: the lessons, and who asks whether one is done)
SONG_FLOWS = tuple(g.flow for g in SONGS) + (
    "AllSage", "BottomOfTheWell", "SageOfWater", "Npc_Hylia_007_Adult", "Npc_Hylia_009_Adult", "Npc_Hylia_009_Child", "Npc_Hylia_051_Adult",
    "Npc_Hylia_Sheik_Adult", "Npc_Kokiri_009_Child", "Npc_Kokiri_011_Child", "Npc_Kokiri_012_Child", "Npc_Kokiri_013_Child",
    "Npc_Kokiri_Fado_Child", "Npc_Kokiri_Mido_Child")
# The ocarina's own flow gives a lesson's song too, before the lesson's scene of the song got: when the notes have
# been played back, its two learning entry points add the song of the lesson's kind to the pouch
# (EventTriggerAddOrRemovePouchContent, one step for each song). Found in play: Malon's lesson, shuffled to the Song of
# Storms, gave that and Epona's Song. So those steps are made to add the song the lesson gives now, and only those:
# the rest of that flow is where a song is played, and names the song that is meant.
SONG_PLAY_FLOW = "Dm_SY_Ocarina"
SONG_PLAY_ENTRIES = ("LearningOcarinaPlayAuto", "LearningOcarinaPlayAutoForSeek")
SONG_WORDS = ("", "IsGet.", "HavePlayedGetEvent.")   # (a song's name, its flag, and the flag of its scene)
SONG_STONES = tuple("Component/AIScheduleParam/Obj_Graveyard_Tombstone_A_0%d.game__component__AIScheduleParam.bgyml" % k for k in (1, 2))


def song_need(need, area, key=None):
    """what a check asks for with the songs named (see above). key: a gift's, for the ones that ask for a song of
    their own. A lesson's own line is not put through this: it names its songs itself."""
    need = set(need)
    if need >= ADULT:
        need |= SONG_GROWN
    return frozenset(need | SONG_AREAS.get(area, set()) | SONG_GIFTS.get(key, set()))


def song_words(now):
    """{what a flow names: what it names now} for the songs that changed places: now is {a lesson's own song: the
    song it gives}. Each song's name, its flag and its scene's flag."""
    return {word + old: word + new for old, new in now.items() if old != new for word in SONG_WORDS}


def song_stone(data, now):
    """A royal tomb's stone (an AIScheduleParam file) asking for the song its lesson gives now, or None when it does
    not ask for the Sun's Song's flag. now: as song_words'."""
    words = song_words(now)
    tree, version = byml_parse(data)
    found = []

    def walk(node):
        kind, value = node if isinstance(node, tuple) and len(node) == 2 else (None, None)
        if kind == "dict":
            for k, v in list(value.items()):
                if k == "ConditionFlag" and v[0] == "string" and v[1] in words:
                    value[k] = ("string", words[v[1]])
                    found.append(k)
                else:
                    walk(v)
        elif kind == "array":
            for v in value:
                walk(v)

    walk(tree)
    return byml_build(tree, version) if found else None


# ---- Heart Pieces: the Pieces of Heart lying in the world ----
# A Piece of Heart that lies in the world is an actor of its map file, Obj_Heart_Piece (one, in Gerudo Valley, is
# Obj_GerudoValley_Heart_Piece: the same without being lifted). With the setting on some gating items are moved to
# the pieces, where the rules still let the game be finished (gate_skulltulas, as for the Skulltulas), and the chest
# such an item leaves gives a Piece of Heart, as some of the game's do. A piece holds its own piece or a gating
# item, nothing else, and nothing moves without the logic.
# The map is left as it is: the piece lies there, is taken as a piece and stays taken as every piece does. What it
# gives is said in its check's line, and the game's side puts that item in the pouch in the piece's place
# (host/hos_main.c oot_piece_gives). The scene is the piece's: it shows a Piece of Heart and says so.
# Tried first, and left: the item itself lying there, made a pick-up. From the token (as a Skulltula's drop is) it
# was there again each time its map was entered; from the piece too, seen in play (the Megaton Hammer of Zora's
# River); and with the saved truth value of the piece's hash set by the game's own setter, there again all the same.
# The pieces a character gives or a chest holds are not these: they are gifts and chests.
# What a piece asks for: its area's rule, which asks for an adult and more everywhere a piece lies. The one of Lon Lon
# Ranch (HEART_RULES) asks for what a child out of the forest has. None has been walked to.
# RANDO_TEST_HEARTS="<a piece's hash>=<an item> ..." makes that piece that item, for a test.
HEART = "Obj_Heart_Piece"
HEART_ACTORS = (HEART, "Obj_GerudoValley_Heart_Piece")
HEART_RULES = {0x88358af5b5300aa9: CHILD}   # (Lon Lon Ranch, behind the crates)


def heart_rule(h, area):
    """what the Piece of Heart of this hash, lying in this area, asks for"""
    return HEART_RULES.get(h, rule(area, ""))


def hearts(data):
    """The Pieces of Heart lying in a map file: [(hash, place)]."""
    return [(h, pos) for h, gyaml, pos, _, _ in marks(data) if gyaml in HEART_ACTORS and h is not None]


def check_name(kind, item, about, pos, exits=(), parts=()):
    """A check's name. kind: "Chest" or "Gold Skulltula". item: what a chest held. about: what its actor says
    ({"big", "room", "night", "soil"}). exits: [(place, where it leads)] and parts: [(place, how far it reaches, its
    name)] of its area's maps."""
    if kind == "Chest":
        name = ("Big chest" if about.get("big") else "Chest") + (" (%s)" % (ITEM_WORDS.get(item) or spaced(item)) if item else "")
    else:
        name = kind + (", night" if about.get("night") else "") + (", bean soil" if about.get("soil") else "")
    if isinstance(about.get("room"), int):
        return name + ", room %d" % about["room"]
    if len(pos) != 3:
        return name
    inside = sorted((math.hypot(pos[0] - p[0], pos[2] - p[2]), words) for p, reach, words in parts if math.hypot(pos[0] - p[0], pos[2] - p[2]) < reach)
    if inside:
        return name + ", " + AREA_NAMES.get(inside[0][1], spaced(inside[0][1]))
    near = sorted((math.dist(pos, p), words) for p, words in exits if math.dist(pos, p) < EXIT_NEAR)
    return name + (", by the %s exit" % AREA_NAMES.get(near[0][1], spaced(near[0][1])) if near else "")


def check_lines(chests, skulls, gifts=()):
    """The checks file's lines. chests, skulls and gifts: [(area (the Banc folder), position, ages, what its rule asks
    for, its name, its actor's hash)]; a chest or a Gold Skulltula without a name is "Chest" or "Gold Skulltula". The
    name is the line's kind; those of an area that are the same are numbered, by place. By the area's name, the
    chests first, then the Gold Skulltulas, then the gifts, each by name; no more than the menu keeps. After what the
    rules ask for a line may have two more fields: its actor's hash, 16 hexadecimal digits ("-" without one), and
    the item it gives (a seventh of a tuple): the game's side marks a check collected when its item is given near it.
    A line with neither ends after what the rules ask for. An eighth of a tuple is where Link is put to go to the
    check, when that is not the check's own place (a chest's front): a field more, "x y z"."""
    rows = []
    for order, plain, those in ((0, "Chest", chests), (1, "Gold Skulltula", skulls), (2, "", gifts)):
        for area, pos, ages, need, *more in those:
            if len(pos) != 3 or not ages:
                continue
            name = more[0] if more else plain
            rows.append([AREA_NAMES.get(area, area).replace("|", "/")[:47], (name[:1].upper() + name[1:]).replace("|", "/"), area, ages, pos,
                         ",".join(code for item, code in CHECK_CODES.items() if item in need) or "-", order, more[1] if len(more) > 1 else None,
                         more[2] if len(more) > 2 else "", more[3] if len(more) > 3 else None])
    rows.sort(key=lambda r: (r[0].lower(), r[6], r[1], r[4]))
    same = collections.Counter((r[0], r[1]) for r in rows if r[1] not in ("Chest", "Gold Skulltula"))
    count = collections.Counter()
    for r in rows:
        if same[(r[0], r[1])] > 1 and r[6] < 2:   # (gifts of one place are told apart by their names already)
            count[(r[0], r[1])] += 1
            r[1] = r[1][:CHECK_NAME - 4] + " #%d" % count[(r[0], r[1])]
        r[1] = r[1][:CHECK_NAME]
    return ["# The checks of this seed, one by one, for the Tracker tab: <area>|<kind>|<folder>|<ages>|<x> <y> <z>|<the rules ask for>[|<the actor's hash>[|<the item it gives>[|<where Link is put>]]]"] + [
        "%s|%s|%s|%s|%.1f %.1f %.1f|%s%s%s%s" % (name, kind, area, ages, pos[0], pos[1], pos[2], need,
                                                 "" if key is None and not given and not stand else "|-" if key is None else "|%016x" % key,
                                                 "|" + given if given else "|-" if stand else "", "|%.1f %.1f %.1f" % tuple(stand) if stand else "")
        for name, kind, area, ages, pos, need, _, key, given, stand in rows[:CHECK_ROWS]]


def remove_old(mod):
    """the files a run before this one wrote (its list: rando_manifest.txt), and the folders they leave empty"""
    listing = os.path.join(mod, "rando_manifest.txt")
    if not os.path.isfile(listing):
        return 0
    n = 0
    with open(listing, encoding="utf-8") as f:
        rels = [line.strip() for line in f if line.strip()]
    for rel in rels + ["spoiler.txt", TRACKER, CHECKS, "rando_stamp.txt", "rando_manifest.txt"]:
        path = os.path.normpath(os.path.join(mod, rel))
        if not path.startswith(os.path.normpath(mod) + os.sep) or not os.path.isfile(path):   # (only inside the mod's folder)
            continue
        os.remove(path)
        n += 1
        folder = os.path.dirname(path)
        while folder != os.path.normpath(mod) and not os.listdir(folder):
            os.rmdir(folder)
            folder = os.path.dirname(folder)
    if os.path.isdir(mod) and not os.listdir(mod):
        os.rmdir(mod)
    return n


def place(rng, spots, which, keys_mode, needs=None, bound=None):
    """What each chest holds. spots: {hash: (area, item, is a dungeon's chest, why it stays or None)}, in a fixed order.
    needs: {hash: what the chest asks for} for the logic, or None: no logic.
    Returns ({hash: item} for the chests that take part, how many chests stay for each reason, the spheres or None).
    With the logic, the thirteen gating items are placed so that each can be reached with the others (an assumed
    fill), counting the ones that stay in their own chests; then the rest goes where there is room.
    bound: None, or (items, hashes): those items go to those spots only, and those spots hold nothing else (the songs
    and the lessons); or a list of such pairs, each a group of its own (the songs, and the dungeons' rewards)."""
    groups = [g for g in ([bound] if isinstance(bound, tuple) else bound or []) if g]
    bound = groups or None
    bound_items = frozenset(i for items, _ in groups for i in items)
    bound_spots = frozenset(h for _, hashes in groups for h in hashes)
    group_of_item = lambda item: next((k for k, (items, _) in enumerate(groups) if item in items), None)
    group_of_spot = lambda h: next((k for k, (_, hashes) in enumerate(groups) if h in hashes), None)
    fits = lambda item, h: group_of_item(item) == group_of_spot(h)
    stays = collections.Counter()
    pool = []
    for h, (area, item, dungeon, why) in spots.items():
        if not why and dungeon is not None and (which == 1 and dungeon or which == 2 and not dungeon):   # (None: a gift, of neither kind)
            why = "not this Chests setting's"
        if not why and keys_mode == 0 and item in DUNGEON_ITEMS:
            why = "a dungeon's key, map or compass (Dungeon keys: Off)"
        if why:
            stays[why] += 1
        else:
            pool.append(h)
    gives = {}
    # a dungeon's keys, map and compass first, among that dungeon's own chests
    by_area = collections.OrderedDict()
    for h in pool:
        by_area.setdefault(spots[h][0], []).append(h)
    for area, here in by_area.items():
        own = [spots[h][1] for h in here if spots[h][1] in DUNGEON_ITEMS]
        if bound:   # (a lesson in a dungeon's area is not one of its chests)
            here = [h for h in here if h not in bound_spots]
        for h, item in zip(rng.sample(here, len(own)), own):
            gives[h] = item
    rest = [h for h in pool if h not in gives]
    items = [spots[h][1] for h in pool if spots[h][1] not in DUNGEON_ITEMS]
    spheres = None
    if needs is not None:
        gating = sorted(i for i in items if i in PROGRESSION)
        # (a gating item in a chest that stays is got there, as the game has it)
        fixed = [(needs[h], spots[h][1]) for h in spots if h not in pool and spots[h][1] in PROGRESSION]
        for attempt in range(400):
            order = list(gating)
            rng.shuffle(order)
            placed, ok = {}, True
            for k, item in enumerate(order):
                # Link with every gating item still to be placed, and what the chests filled so far then give him
                have = reach(order[k + 1:], fixed + [(needs[h], i) for h, i in placed.items()])
                free = [h for h in rest if h not in placed and needs[h] <= have and (not bound or fits(item, h))]
                if not free:
                    ok = False
                    break
                placed[rng.choice(free)] = item
            if ok:
                spheres = collect(fixed + [(needs[h], i) for h, i in placed.items()])
                if {i for sphere in spheres for i in sphere} >= {i for _, i in fixed} | set(gating):
                    break
            spheres = None
        if spheres is None:
            raise ValueError("no arrangement the logic accepts was found: fewer chests take part than it needs")
        gives.update(placed)
        rest = [h for h in rest if h not in placed]
        items = [i for i in items if i not in PROGRESSION]
    for group_items, group_spots in groups:   # (the songs that are left, among the lessons that are left; and so each group)
        mine, theirs = [h for h in rest if h in group_spots], [i for i in items if i in group_items]
        rng.shuffle(theirs)
        gives.update(zip(mine, theirs))
        rest, items = [h for h in rest if h not in group_spots], [i for i in items if i not in group_items]
    # everything else among the chests that are left, wherever they are
    rng.shuffle(items)
    for h, item in zip(rest, items):
        gives[h] = item
    return gives, stays, spheres


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("romfs")
    p.add_argument("--game", help="the game folder (default: the folder the romfs is in)")
    p.add_argument("--seed", type=int, help="in place of the options file's rando_seed (and the randomizer counts as on)")
    p.add_argument("--chests", type=int, choices=(0, 1, 2, 3), help="in place of rando_chests: 1 overworld, 2 dungeons, 3 all")
    p.add_argument("--keys", type=int, choices=(0, 1, 2), help="in place of rando_keys: 0 off, 1 own dungeon, 2 anywhere (as 1)")
    p.add_argument("--event-chests", action="store_true", help="chests that start an event take part too: most of the big items, placed by the logic")
    p.add_argument("--no-logic", action="store_true", help="with --event-chests: the big items anywhere, whether the seed can be finished or not")
    p.add_argument("--open-deku", action="store_true", help="as rando_open_deku=1: in a new game the way to the Deku Tree is open without a sword and a shield")
    p.add_argument("--open-forest", action="store_true", help="as rando_open_forest=1: in a new game the forest can be left before the Deku Tree is done")
    p.add_argument("--skip-intro", action="store_true", help="as rando_skip_intro=1: a new game starts in Link's house, without the two opening cutscenes")
    p.add_argument("--skulltulas", type=int, choices=(0, 1, 2, 3), help="in place of rando_skulltulas: the Gold Skulltulas whose tokens change places "
                                                                        "with the chests' rupees and supplies. 1 dungeons, 2 overworld, 3 all")
    p.add_argument("--quests", action="store_true", help="as rando_quests=1: what characters give takes part with the chests (GIFTS)")
    p.add_argument("--frogs", action="store_true", help="not used any more: with Quest rewards the frogs of Zora's River always take part")
    p.add_argument("--light-arrows", action="store_true", help="as rando_light_arrows=1: with Quest rewards, Zelda's Light Arrows take part too")
    p.add_argument("--scrubs", action="store_true", help="as rando_scrubs=1: the Business Scrubs' four one-time sales take part with the chests (SCRUBS)")
    p.add_argument("--shops", type=int, choices=(0, 1, 2), help="in place of rando_shops: four shelves of each shop sell a shuffled item, once (SHOPS). "
                                                               "2: with rolled prices")
    p.add_argument("--shop-shelves", type=int, choices=(0, 1), help="in place of rando_shop_shelves: with Shops, 0 four shelves of each shop, 1 every shelf (shop_slots)")
    p.add_argument("--sword-shield", type=int, choices=(0, 1), help="in place of rando_sword_shield: 0 the Kokiri Sword stays in its chest and the Deku Shield on "
                                                                     "its shelf, 1 both take part (the chest with Major items, the shelf with Shops)")
    p.add_argument("--heart-pieces", action="store_true", help="as rando_heart_pieces=1: the Pieces of Heart lying in the world change places with "
                                                                "the chests' items a pick-up can be, and may hold a gating item")
    p.add_argument("--songs", type=int, choices=(0, 1, 2), help="in place of rando_songs: the twelve songs are shuffled among the twelve lessons (SONGS). "
                                                               "2, a song in any item's place, is not made yet: as 1")
    p.add_argument("--dungeon-rewards", type=int, choices=(0, 1, 2), help="in place of rando_dungeon_rewards: the eight dungeons' stones and medallions are "
                                                                         "shuffled among their eight endings (REWARDS). 2, one in any item's place, is not made yet: as 1")
    p.add_argument("--progressive", action="store_true", help="as rando_progressive=1: the rules count an upgrade found as the next of its family")
    p.add_argument("--start-rupees", action="store_true", help="as rando_start_rupees=1: a new game starts with %d rupees" % START_RUPEES)
    p.add_argument("--if-changed", action="store_true", help="do nothing when the mod is already this seed's (the launcher, at Play)")
    p.add_argument("--dry-run", action="store_true", help="say what would change, write nothing")
    a = p.parse_args()
    romfs = os.path.abspath(a.romfs)
    game = os.path.abspath(a.game) if a.game else os.path.dirname(romfs)
    mod = os.path.join(game, "mods", MOD)
    ini = settings(game)
    on = ini["rando_on"] != 0 or a.seed is not None
    seed = a.seed if a.seed is not None else ini["rando_seed"]
    which = a.chests if a.chests is not None else ini["rando_chests"]
    keys_mode = a.keys if a.keys is not None else ini["rando_keys"]
    which = which if 0 <= which <= 3 else 0
    keys_mode = keys_mode if 0 <= keys_mode <= 2 else 0
    stamp_path = os.path.join(mod, "rando_stamp.txt")
    # A seed made before the Major items setting, with --event-chests (its spoiler lists the gating items; it has no
    # stamp): the setting is turned on for it, so that the same seed is made again and not another under its save.
    try:
        old = "" if os.path.isfile(stamp_path) else open(os.path.join(mod, "spoiler.txt"), encoding="utf-8").read()
    except OSError:
        old = ""
    if on and "the gating items" in old and not ini["rando_major"] and not a.event_chests and not a.dry_run:
        set_option(game, "rando_major", 1)
        ini["rando_major"] = 1
        print("this seed was made with the big items shuffled: Major items is now On in the options, to keep it as it is")
    a.event_chests = a.event_chests or ini["rando_major"] != 0
    a.songs = a.songs if a.songs is not None else ini["rando_songs"]
    a.songs = 1 if a.songs in (1, 2) else 0
    a.dungeon_rewards = a.dungeon_rewards if a.dungeon_rewards is not None else ini["rando_dungeon_rewards"]
    a.dungeon_rewards = 1 if a.dungeon_rewards in (1, 2) and REWARDS_READY else 0
    a.heart_pieces = a.heart_pieces or ini["rando_heart_pieces"] != 0
    # (the songs gate the game: with them shuffled the logic places them, whatever Major items says)
    logic_now = (a.event_chests or bool(a.songs)) and not a.no_logic
    # (the options file's rando_open_deku and rando_open_forest too, so that the launcher's run at Play keeps them)
    a.open_deku = a.open_deku or ini["rando_open_deku"] != 0
    a.open_forest = a.open_forest or ini["rando_open_forest"] != 0
    a.skip_intro = a.skip_intro or ini["rando_skip_intro"] != 0
    a.start_rupees = a.start_rupees or ini["rando_start_rupees"] != 0
    a.scrubs = a.scrubs or ini["rando_scrubs"] != 0
    a.progressive = a.progressive or ini["rando_progressive"] != 0
    a.shops = a.shops if a.shops is not None else ini["rando_shops"]
    a.shops = a.shops if 0 <= a.shops <= 2 else 0
    a.shop_shelves = (a.shop_shelves if a.shop_shelves is not None else ini["rando_shop_shelves"]) == 1 and a.shops != 0
    a.sword_shield = (a.sword_shield if a.sword_shield is not None else ini["rando_sword_shield"]) == 1
    shield_shelf = a.sword_shield and a.shops != 0   # (the Deku Shield's shelf takes part: with Shops)
    a.skulltulas = a.skulltulas if a.skulltulas is not None else ini["rando_skulltulas"]
    a.skulltulas = a.skulltulas if 0 <= a.skulltulas <= 3 else 0
    a.quests = a.quests or ini["rando_quests"] != 0
    a.frogs = a.quests   # (no longer a choice of its own: the frogs take part whenever Quest rewards is on; rando_frogs and --frogs are read and not used)
    a.light_arrows = a.quests and (a.light_arrows or ini["rando_light_arrows"] != 0)
    # A test: <game folder>\rando\test_drops.txt, lines of "<an actor's hash> <an item>": that actor (a Gold Skulltula,
    # say) drops the item. For finding how the other kinds of check hold what they give; not a setting.
    drops = {}
    try:
        with open(os.path.join(game, "rando", "test_drops.txt"), encoding="utf-8") as f:
            for line in f:
                parts = line.split("#")[0].split()
                if len(parts) == 2:
                    drops[int(parts[0], 16)] = parts[1]
    except (OSError, ValueError):
        pass
    # Another: <game folder>\rando\test_chests.txt, lines of "<a chest's hash> <an item>": that chest gives the item,
    # whatever the seed put there (a gating item within reach, to try what comes after it). The seed's own count of
    # each item is not kept by it, and the spoiler's order of the gating items does not know of it.
    test_chests = {}
    try:
        with open(os.path.join(game, "rando", "test_chests.txt"), encoding="utf-8") as f:
            for line in f:
                parts = line.split("#")[0].split()
                if len(parts) == 2:
                    test_chests[int(parts[0], 16)] = parts[1]
    except (OSError, ValueError):
        pass
    # Another: <game folder>\rando\test_gifts.txt, lines of "<a flow's name> <the item it gives> <another item>": that
    # scene gives the other item (gift_item). For finding how a character's gift can be changed; not a setting.
    test_gifts = []
    try:
        with open(os.path.join(game, "rando", "test_gifts.txt"), encoding="utf-8") as f:
            test_gifts = [tuple(line.split("#")[0].split()) for line in f if len(line.split("#")[0].split()) == 3]
    except OSError:
        pass
    # Another: <game folder>\rando\test_pickups.txt, an item's actor on each line (Item_Boomerang): its pack is made a
    # pick-up's (pickup_pack), so that it can be collected where a Skulltula drops it.
    pickups = []
    try:
        with open(os.path.join(game, "rando", "test_pickups.txt"), encoding="utf-8") as f:
            pickups = sorted({line.split("#")[0].strip() for line in f} - {""})
    except OSError:
        pass
    flags = {}
    # (the loop's variable was named `on` once and wrote over the randomizer's switch: with the forest's way open the
    #  script took the randomizer for on whatever the options said, and never took a seed away. Seen in play: a normal
    #  game with a seed's chests)
    for name, opened in (("deku", a.open_deku), ("forest", a.open_forest)):
        if opened:
            flags.update(OPEN[name])
    # (the open ways are only named when one is open: the seeds made before them keep their stamp)
    rest = " seed %d chests %d keys %d major %d logic %d%s\n" % (seed, which, min(keys_mode, 1), a.event_chests, logic_now,
                                                               (" open %d%d flags" % (a.open_deku, a.open_forest) if flags else "") + (" intro skipped" if a.skip_intro else "") + (" rupees %d" % START_RUPEES if a.start_rupees else "") + ((" skulltulas %d" + " gated all" * logic_now) % a.skulltulas if a.skulltulas else "") +
                                                               (" quests 1%s%s" % (" frogs" * a.frogs, " light" * a.light_arrows) if a.quests else "") + (" scrubs 1 words 2" if a.scrubs else "") + (" shops %d prices 5" % a.shops if a.shops else "") + (" shelves all" if a.shop_shelves else "") + (" sword and shield 1" if a.sword_shield else "") + (" progressive 1" if a.progressive else "") + (" songs 2" if a.songs else "") + (" rewards 1" if a.dungeon_rewards else "") + (" hearts 2" if a.heart_pieces else "") + " checks 9" +
                                                               (" test drops %08x" % (zlib.crc32(repr(sorted(drops.items())).encode()) & 0xffffffff) if drops else "") +
                                                               (" test pickups " + ",".join(pickups) if pickups else "") +
                                                               (" test chests %08x" % (zlib.crc32(repr(sorted(test_chests.items())).encode()) & 0xffffffff) if test_chests else "") +
                                                               (" test gifts %08x" % (zlib.crc32(repr(sorted(test_gifts)).encode()) & 0xffffffff) if test_gifts else ""))
    # (the seed in the game folder, made by an earlier version of the rules: made again as it was, not another one
    # under its save. A new seed, or other settings, take the rules of today)
    placement = PLACEMENT
    try:
        was = open(stamp_path, encoding="utf-8").read()
        was = was.split("\n")[0] + "\n"   # (the first line: the settings. The second, later: the fixes)
        if was.startswith("placement ") and was.split(" ", 2)[2:] == [rest[1:]] and 1 <= int(was.split()[1]) < PLACEMENT:
            placement = int(was.split()[1])
    except (OSError, ValueError):
        pass
    stamp = "placement %d%sfixes %d\n" % (placement, rest, FIXES_VERSION)   # (the fixes: the same items, written again)
    print("randomizer %s, seed %d, chests %s, dungeon keys %s, major items %s" % (
        "on" if on else "off", seed, ("off", "overworld", "dungeons", "all")[which],
        ("off", "own dungeon", "anywhere (as own dungeon for now)")[keys_mode], "on" if a.event_chests else "off"))
    if a.if_changed and on and which:
        try:
            if open(stamp_path, encoding="utf-8").read() == stamp:
                print("the mod is already this seed's: nothing to do")
                return
        except OSError:
            pass
    # (the test mods change the same files, and one carries a size table of its own that would win over this one's)
    tests = [os.path.join(game, "mods", n) for n in ("rando-poc", "rando-zz-test2") if os.path.isdir(os.path.join(game, "mods", n))]
    if tests and not a.dry_run:
        sys.exit("Delete the test mods first, then run this again:\n  " + "\n  ".join(tests))
    if not on or which == 0:
        n = 0 if a.dry_run else remove_old(mod)
        print("nothing to shuffle (turn Randomizer on and set Chests in the menu's Randomizer tab)%s" % (
            ": %d files of the last seed removed" % n if n else ""))
        return
    try:
        import zstandard as zs
    except ImportError:
        sys.exit("the zstandard package is missing: python -m pip install zstandard")
    dicts = dictionaries(romfs, zs)

    # ---- every map file with chests ----
    files = collections.OrderedDict()   # rel -> (bytes, [Chest])
    maps = collections.defaultdict(set)  # a chest's or Gold Skulltula's hash -> the names of the map files that have it
    about = {}                                 # the same -> what its actor says of it (check_name)
    exits = collections.defaultdict(set)       # an area -> its ways out: (place, where it leads)
    sub_areas = collections.defaultdict(set)   # an area -> its parts with a name of their own: (place, reach, name)
    skulls = collections.OrderedDict()  # hash -> [area, position, can be given a drop (in every file it is in), a dungeon's, a child's map has it]
    pieces = collections.OrderedDict()  # a Piece of Heart lying in the world: hash -> [area, position]
    paths = []
    for top, dirs, names in os.walk(os.path.join(romfs, "Banc")):
        dirs.sort()
        paths += [os.path.join(top, n) for n in sorted(names) if ".bcett.byml" in n.lower()]
    for path in sorted(paths, key=lambda q: os.path.relpath(q, romfs).replace("\\", "/")):
        rel = os.path.relpath(path, romfs).replace("\\", "/")
        try:
            data = unpack(open(path, "rb").read(), zs, dicts)
            found, _, _ = chests(data)
        except Exception as e:
            print("skipped %s: %s" % (rel, e))
            continue
        try:   # (what the file has to name its checks by: check_name)
            folder = rel.split("/")[1] if rel.count("/") > 1 else "(Banc)"
            for h, gyaml, pos, scale, words in marks(data):
                leads = words.get("Location")
                if gyaml in MARKS:
                    if isinstance(leads, str) and leads and leads != folder and len(pos) == 3:
                        if gyaml == "LocationArea":
                            sub_areas[folder].add((pos, max(scale[0], scale[2], 60.0) if len(scale) == 3 else 60.0, leads))
                        else:
                            exits[folder].add((pos, leads))
                elif h is not None:
                    was = about.setdefault(h, {})
                    was["big"] = was.get("big") or gyaml.startswith("Obj_TBox_A_02")
                    was.setdefault("turned", words.get("Rotate", (0.0, 0.0, 0.0)))
                    was["night"] = was.get("night") or bool(words.get("Enemy_Skulltula_Gold_Nocturnal"))
                    was["soil"] = was.get("soil") or bool(words.get("Enemy_Skulltula_Gold_IsMagicBeanSoil"))
                    if "DefaultDungeonRoomIndex" in words:
                        was["room"] = words["DefaultDungeonRoomIndex"]
        except (ValueError, struct.error, IndexError):
            pass
        lying = []
        if a.heart_pieces:
            try:
                lying = hearts(data)
            except (ValueError, struct.error, IndexError):
                pass
            for h, pos in lying:
                maps[h].add(rel.split("/")[-1])
                pieces.setdefault(h, [folder, pos])
        here = skulltulas(data) if a.skulltulas else []
        if any(not can for _, _, can, _ in here):
            try:   # (a file that has to be written anew for its Skulltulas: can it be read whole?)
                byml_parse(data)
                here = [(h, pos, True, dungeon) for h, pos, _, dungeon in here]
            except (ValueError, struct.error, IndexError):
                pass
        for h, pos, can, dungeon in here:
            parts = rel.split("/")
            maps[h].add(parts[-1])
            entry = skulls.setdefault(h, [parts[1] if len(parts) > 2 else "(Banc)", pos, True, False, False])
            entry[2], entry[3] = entry[2] and can, entry[3] or dungeon
            entry[4] = entry[4] or "_Child_" in parts[-1] or entry[0] in SKULLTULA_CHILD_DUNGEONS
        if found or here or any(struct.pack("<Q", h) in data for h in drops):
            files[rel] = (data, found)

    # ---- the chests: one per hash (the same chest is in several files: child and adult, static and dynamic) ----
    spots = collections.OrderedDict()   # hash -> [area, item, dungeon, why it stays, type, position]
    for rel, (data, found) in files.items():
        parts = rel.split("/")
        area = parts[1] if len(parts) > 2 else "(Banc)"
        for c in found:
            if c.hash is None or not c.gyaml.startswith("Obj_TBox"):
                continue
            maps[c.hash].add(parts[-1])
            why = stays_why(c, a.event_chests, placement)
            if c.event == SWORD_EVENT and not a.sword_shield:   # (Shuffle sword and shield: Off)
                why = why or "the Kokiri Sword stays in its chest (Shuffle sword and shield: Off)"
            dungeon = "DefaultDungeonRoomIndex" in c.params
            if c.hash not in spots:
                spots[c.hash] = [area, c.item, dungeon, why, c.gyaml, c.pos, c.event]
            else:
                s = spots[c.hash]
                if s[1] != c.item:
                    s[3] = "holds different items in different files"
                elif s[0] != area:
                    s[3] = s[3] or "is in two areas' files"
                s[3] = s[3] or why
                s[2] = s[2] or dungeon
    # ---- Quest rewards: the gifts that take part, as spots among the chests' ----
    gifts = collections.OrderedDict()   # its hash -> the Gift
    global PROGRESSION
    if a.quests:
        PROGRESSION = PROGRESSION | QUEST_GATES
        for g in GIFTS:
            if g.when is None or g.when == "frogs" and a.frogs or g.when == "light" and a.light_arrows:
                gifts[gift_hash(g.key)] = g
                spots[gift_hash(g.key)] = [g.area, g.item, None, None, "gift", g.name, ""]
    if a.scrubs:   # (Deku Scrubs: with or without Quest rewards)
        for g in SCRUBS:
            gifts[gift_hash(g.key)] = g
            spots[gift_hash(g.key)] = [g.area, g.item, None, None, "scrub", g.name, ""]
    lessons = collections.OrderedDict()   # a lesson's hash -> its Gift
    if a.songs:   # (Songs: with or without the others)
        PROGRESSION = PROGRESSION | SONG_GATES
        for g in SONGS:
            gifts[gift_hash(g.key)] = lessons[gift_hash(g.key)] = g
            spots[gift_hash(g.key)] = [g.area, g.item, None, None, "song", g.name, ""]
    endings = collections.OrderedDict()   # a dungeon's ending's hash -> its Gift
    if a.dungeon_rewards:   # (Dungeon rewards: with or without the others; none is a gating item)
        for g in REWARDS:
            gifts[gift_hash(g.key)] = endings[gift_hash(g.key)] = g
            spots[gift_hash(g.key)] = [g.area, g.item, None, None, "reward", g.name, ""]
    shelves = collections.OrderedDict()   # a shop shelf's hash -> (its Shop, its place in the goods list, the game's own actor there)
    shelf_prices = {}                     # the same -> what it costs
    if a.shops:   # (Shops: with or without the others)
        PROGRESSION = PROGRESSION | SHOP_GATES   # (the wallets: shuffled, and asked for by the shelves' prices)
        for g in GIFTS:
            if g.key in SHOP_WALLET_GIFTS and gift_hash(g.key) not in gifts:
                gifts[gift_hash(g.key)] = g
                spots[gift_hash(g.key)] = [g.area, g.item, None, None, "gift", g.name, ""]
        roll = random.Random("shop prices:%d:%d" % (seed, a.shops))
        for shop in SHOPS:
            for k, (index, actor) in enumerate(shop_slots(shop, a.shop_shelves, shield_shelf)):
                price = shop_price(roll, a.shops)
                g = Gift("shop_%s_%d" % (shop.key, index), "", (), shelf_item(actor), shop.areas[0],
                         "%s: shelf %d, %d rupee%s" % (shop.name, k + 1, price, "" if price == 1 else "s"), shop.need | wallet_need(price), "shops", None)
                gifts[gift_hash(g.key)], shelves[gift_hash(g.key)], shelf_prices[gift_hash(g.key)] = g, (shop, index, actor), price
                spots[gift_hash(g.key)] = [g.area, g.item, None, None, "shop", g.name, ""]
    # (a string seed: the same on every Python 3. The seeds made before --event-chests keep their shuffle without it)
    logic = logic_now   # (without the event chests or the songs no gating item moves: nothing to ask)
    rng = random.Random("stage2:%d:%d:%d%s%s%s" % (seed, which, min(keys_mode, 1), ":events" if a.event_chests else "", ":logic" if logic else "",
                                                   ":songs" if a.songs else ""))
    needs = {h: rule(s[0], s[6]) for h, s in spots.items()}
    if a.quests:   # (the rules with the gifts' two gating items named; a gift asks for what its line of GIFTS says)
        needs = {h: quest_need(gifts[h].need, gifts[h].area) if h in gifts else quest_need(n, spots[h][0]) for h, n in needs.items()}
    elif gifts:    # (the scrubs alone)
        needs = {h: gifts[h].need if h in gifts else n for h, n in needs.items()}
    if a.songs:    # (the songs named: a lesson's line names its own; the frogs ask for everything)
        needs = {h: n if h in lessons else frozenset(PROGRESSION) if h in gifts and gifts[h].key in SONGS_HARD else
                 song_need(n, spots[h][0], gifts[h].key if h in gifts else None) for h, n in needs.items()}
    gear = shield_need if shield_shelf and not a.open_deku else (lambda need: need)   # (the shield with the sword: Mido)
    if shield_shelf:
        PROGRESSION = PROGRESSION | SHIELD_GATES
    step = (lambda need: progressive_need(gear(need), PROGRESSION)) if a.progressive else gear
    needs = {h: step(n) for h, n in needs.items()}
    # (what a Gold Skulltula asks for, by the same settings)
    skull_asks = lambda h: step((lambda n: song_need(n, skulls[h][0]) if a.songs else n)(
        quest_need(skulltula_rule(h, skulls[h][0]), skulls[h][0]) if a.quests else skulltula_rule(h, skulls[h][0])))
    try:
        gives, stays, spheres = place(rng, collections.OrderedDict((h, tuple(s[:4])) for h, s in spots.items()), which, keys_mode,
                                      needs if logic else None,
                                      [group for group in ((frozenset(SONG_ITEMS), frozenset(lessons)) if a.songs else None,
                                                           (frozenset(REWARD_ITEMS), frozenset(endings)) if a.dungeon_rewards else None) if group] or None)
    except ValueError as e:
        sys.exit("%s. Nothing written. Try Chests: All, or --no-logic." % e)
    unknown = sorted({s[0] for h, s in spots.items() if s[0] not in RULES and h not in gifts})

    # (the game's own count of each item is kept: every item given was some chest's)
    before = collections.Counter(spots[h][1] for h in gives)
    if before != collections.Counter(gives.values()):
        sys.exit("the shuffle lost or made an item: nothing written")

    # ---- the Gold Skulltulas: their tokens and the chests' rupees and supplies change places ----
    skull_drops, able = {}, []
    if a.skulltulas:
        mine = [h for h, s in skulls.items() if a.skulltulas == 3 or s[3] == (a.skulltulas == 1)]   # (this setting's)
        able = [h for h in mine if skulls[h][2]]
        gives, skull_drops = mix_skulltulas(random.Random("skulltulas:%d:%d:%d" % (seed, a.skulltulas, len(able))), gives, able)
        if logic:   # (some of the gating items to the Skulltulas, where the rules still let the game be finished)
            fixed = [(needs[h], spots[h][1]) for h in spots if h not in gives and spots[h][1] in PROGRESSION]
            gives, skull_drops, spheres, gated = gate_skulltulas(
                random.Random("skulltulas gated:%d:%d:%d" % (seed, a.skulltulas, len(able))), gives, skull_drops,
                able, needs, {h: skull_asks(h) for h in able}, fixed,
                never=((SSC,) if a.quests else ()) + (tuple(SHOP_GATES) if a.shops else ()) + (tuple(SONG_GATES) if a.songs else ()))
            print("Gold Skulltulas: %d gating item%s now dropped by one" % (gated, "" if gated == 1 else "s"))
        for h, item in skull_drops.items():
            drops.setdefault(h, item)   # (a test's drop for the same Skulltula stays)
        pickups = sorted(set(pickups) | set(skull_drops.values()))
        print("Gold Skulltulas %s: %d take part (%d more cannot be given a drop: their map file is not read whole; the map files have %d), %d now drop a "
              "chest's item, %d chests hold a token" % (("", "dungeons", "overworld", "all")[a.skulltulas], len(able),
                                                        len(mine) - len(able), len(skulls), len(skull_drops),
                                          sum(1 for i in gives.values() if i == TOKEN)))

    # ---- Heart Pieces: the pieces lying in the world and the chests' items a pick-up can be change places ----
    heart_drops = {}   # a piece's hash -> the item it gives now
    heart_asks = lambda h: step((lambda n: song_need(n, pieces[h][0]) if a.songs else n)(
        (lambda n: quest_need(n, pieces[h][0]) if a.quests else n)(heart_rule(h, pieces[h][0]))))
    if a.heart_pieces and pieces:
        if logic:   # (some of the gating items to the pieces, where the rules still let the game be finished)
            fixed = [(needs[h], spots[h][1]) for h in spots if h not in gives and spots[h][1] in PROGRESSION] + [
                (skull_asks(h), item) for h, item in skull_drops.items() if item in PROGRESSION]
            gives, heart_drops, spheres, gated = gate_skulltulas(
                random.Random("hearts gated:%d:%d" % (seed, len(pieces))), gives, heart_drops, list(pieces), needs,
                {h: heart_asks(h) for h in pieces}, fixed, token=HEART,
                never=((SSC,) if a.quests else ()) + (tuple(SHOP_GATES) if a.shops else ()) + (tuple(SONG_GATES) if a.songs else ()))
        else:
            print("Heart Pieces: nothing moves without the logic (Major items, or Songs)")
        for word in os.environ.get("RANDO_TEST_HEARTS", "").split():   # (a test: "<a piece's hash>=<an item>")
            heart_drops[int(word.split("=")[0], 16)] = word.split("=")[1]
        print("Heart Pieces: %d lying in the world take part, %d now give a gating item, and the chest each left holds a Piece of Heart" % (
            len(pieces), len(heart_drops)))

    if test_chests:   # (a test: these chests give what the file says)
        strangers = sorted(h for h in test_chests if h not in gives)
        if strangers:
            sys.exit("rando\\test_chests.txt: no chest that takes part has the hash %s. Nothing written." % ", ".join("%#x" % h for h in strangers))
        gives.update(test_chests)
        print("TEST: %d chest%s given an item (rando\\test_chests.txt): %s" % (
            len(test_chests), "" if len(test_chests) == 1 else "s", ", ".join("%s in %s" % (i, spots[h][0]) for h, i in sorted(test_chests.items()))))

    # ---- the map files ----
    changed, sizes, fixes_done, drops_done = collections.OrderedDict(), {}, 0, 0
    for rel, (data, found) in files.items():
        try:
            new = rewrite(data, gives)
            fixed = fix(new if new is not None else data)
            dropped = add_drop(fixed if fixed is not None else new if new is not None else data, drops,
                               anew=bool(os.environ.get("RANDO_DROPS_ANEW")))   # (a test: every file with a drop written anew)
        except Exception as e:
            sys.exit("%s: %s. Nothing was written to the mod." % (rel, e))
        if fixed is not None:
            new, fixes_done = fixed, fixes_done + 1
        if dropped is not None:
            new, drops_done = dropped, drops_done + 1
        if new is not None:
            changed[rel] = new
            sizes[rel[:-3] if rel.lower().endswith(".zs") else rel] = len(new)
    moved = sum(1 for h, item in gives.items() if item != spots[h][1] and h not in gifts)
    print("%d chests take part, %d now hold another chest's item; %d map files change" % (len(gives) - len(gifts), moved, len(changed)))
    if a.quests:
        mine = [h for h, g in gifts.items() if g.when not in ("scrubs", "shops", "songs")]
        print("Quest rewards: %d gifts take part%s%s, %d now give another item" % (
            len(mine), "" if a.frogs else " (not the frogs: their setting is off)", "" if a.light_arrows else " (not the Light Arrows: their setting is off)",
            sum(1 for h in mine if gives[h] != gifts[h].item)))
    if a.scrubs:
        mine = [h for h, g in gifts.items() if g.when == "scrubs"]
        print("Deku Scrubs: %d one-time sales take part, %d now sell another item" % (len(mine), sum(1 for h in mine if gives[h] != gifts[h].item)))
    for why, n in stays.most_common():
        print("  left alone: %d (%s)" % (n, why))
    if len(drops) > len(skull_drops):
        print("TEST: %d actor%s given an item to drop (rando\\test_drops.txt)" % (
            len(drops) - len(skull_drops), "" if len(drops) - len(skull_drops) == 1 else "s"))
    # ---- the open ways: the game's list of flags, with theirs starting put out ----
    flag_files = {}
    if True:   # (every seed: Hyrule Field's clock, FIELD_CLOCK, with the open ways' flags and the rupees)
        folder = os.path.join(romfs, FLAG_LIST)
        lists = sorted(n for n in (os.listdir(folder) if os.path.isdir(folder) else []) if n.startswith("GameDataList.") and ".byml" in n.lower())
        if not lists:
            sys.exit("no list of flags in %s: the ways cannot be opened, nor the rupees given. Nothing written." % folder)
        for n in lists:
            try:
                was = unpack(open(os.path.join(folder, n), "rb").read(), zs, dicts)
                new = flag_defaults(was, dict(flags, **FIELD_CLOCK))
                if a.start_rupees:   # (the same file: the rupees after the flags)
                    more = flag_defaults(new if new is not None else was, {RUPEES: START_RUPEES}, kind="Int")
                    new = more if more is not None else new
            except Exception as e:
                sys.exit("%s: %s. Nothing written." % (n, e))
            if new is not None:
                flag_files[FLAG_LIST + "/" + n] = new
        if a.start_rupees:
            print("a new game starts with %d rupees" % START_RUPEES)
        print("Hyrule Field's day and night run from a new game's start (the Sun's Song works before the owl is met)")
    if flags:
        print("open ways in a new game: %s (%d flag%s start put out)" % (
            " and ".join(n for n, on in (("the Deku Tree's", a.open_deku), ("the forest's way out", a.open_forest)) if on), len(flags), "" if len(flags) == 1 else "s"))
    print("map fixes for a shuffled game: %d file%s (the warp songs work in the Forest Temple's Stalfos room)%s" % (
        fixes_done, "" if fixes_done == 1 else "s", "" if fixes_done else ": NOT FOUND, that room can shut Link in without the Bow"))
    if logic:
        print("logic: on. The %d gating items can be got in this order by the rules (%d rounds):" % (sum(map(len, spheres)), len(spheres)))
        for k, sphere in enumerate(spheres):
            print("  %d. %s" % (k + 1, ", ".join(sphere)))
        if unknown:
            print("  areas the rules do not know (their chests only get items the game can be finished without): " + ", ".join(unknown))
        if keys_mode:
            print("  NOTE: the logic does not look at a dungeon's keys: with Dungeon keys on Own dungeon a key can still be behind its door")
    elif a.event_chests:
        print("logic: OFF (--no-logic): the gating items are anywhere, and most seeds cannot be finished")

    # ---- TEST: items' packs made pick-ups' ----
    pack_files, pack_sizes, pack_parts, pack_new = {}, {}, set(), set()
    pouch_changed = {}   # (the pouch files the pick-ups changed: a shelf actor's pack takes them too)
    if pickups:
        def pack(name):
            return unpack(open(os.path.join(romfs, "Pack", "Actor", name + ".pack.zs"), "rb").read(), zs, dicts)
        try:
            base = pack(PICKUP_BASE)
            base_parts = sarc_read(base)
            pouch = pouch_changed
            for item in list(pickups):   # (an item made from another: that one's pack has a copy of the same actor)
                pickups += [n for n in pickup_family(item, pack(item))
                            if n not in pickups and os.path.isfile(os.path.join(romfs, "Pack", "Actor", n + ".pack.zs"))]
            for item in pickups:
                old = pack(item)
                # (each time: what can be got more than once. A gating item is got once, and is as it was seen in play)
                new = pickup_pack(item, old, base, each_time=item not in PROGRESSION)
                old_parts = sarc_read(old)
                pack_parts.update(name for name, data in sarc_read(new).items()   # (the files changed in it)
                                  if data != old_parts.get(name, base_parts.get(name)))
                pack_new.update(name for name in sarc_read(new) if name not in old_parts and name not in base_parts)
                pack_files["Pack/Actor/%s.pack.zs" % item] = new
                pack_sizes["Pack/Actor/%s.pack" % item] = len(new)
                pouch.update((name, data) for name, data in sarc_read(new).items()
                             if "/PouchContentParam/" in name and data != old_parts.get(name, base_parts.get(name)))
            # What an item is in the pouch is a file other packs carry a copy of, under the same name: the item in
            # the menu's (Pouch_*), the weapon in the hand's (Weapon_*), boots and gauntlets worn (Armor_*). The
            # Boomerang, made a pick-up just as the Megaton Hammer was, was not collected by touching it and the
            # Hammer was: a child's game loads the Boomerang's weapon first, with its copy. So the copies are
            # changed with it, in every pack that has one (seen in play: the Boomerang is collected by touch).
            for n in sorted(os.listdir(os.path.join(romfs, "Pack", "Actor"))) if pouch else []:
                if n.endswith(".pack.zs") and "Pack/Actor/" + n not in pack_files:
                    try:
                        parts = sarc_read(pack(n[:-len(".pack.zs")]))
                    except (ValueError, struct.error):
                        continue   # (not an archive of parameter files)
                    same = [name for name in pouch if name in parts and parts[name] != pouch[name]]
                    if same:
                        parts.update((name, pouch[name]) for name in same)
                        new = sarc_write(parts)
                        pack_files["Pack/Actor/" + n] = new
                        pack_sizes["Pack/Actor/" + n[:-len(".zs")]] = len(new)
        except (OSError, ValueError, struct.error) as e:
            sys.exit("an item's pack could not be made a pick-up's: %s. Nothing written." % e)
        print("%d item%s made a pick-up (what a Skulltula drops, and rando\\test_pickups.txt): %s" % (
            len(pickups), "" if len(pickups) == 1 else "s", ", ".join(pickups)))

    # ---- TEST: a character's gift made another item ----
    # ---- the gifts: each scene's flow made to give what the shuffle put there (and the tests' of test_gifts.txt) ----
    gift_files, gift_sizes = {}, {}
    swaps = collections.OrderedDict()   # a flow -> {the item it names: the item it gives now}
    for h, g in gifts.items():
        if gives[h] != g.item and g.flow and h not in lessons:   # (a shop's shelf has no scene: its actor is the sale; the songs: below)
            swaps.setdefault(g.flow, {}).update(((g.entry, old) if g.entry else old, gives[h]) for old in g.olds)
    for flow, old, new in test_gifts:
        swaps.setdefault(flow, {})[old] = new
        print("TEST: %s gives %s in place of %s (rando\\test_gifts.txt)" % (flow, new, old))
    for flow, change in swaps.items():
        twin = "%s/%s%s.bfevfl.zs" % (GIFT_FLOWS, flow, FLOW_TWIN)
        for rel in ["%s/%s.bfevfl.zs" % (GIFT_FLOWS, flow)] + ([twin] if os.path.isfile(os.path.join(romfs, *twin.split("/"))) else []):
            try:
                now, found = gift_items(unpack(open(os.path.join(romfs, *rel.split("/")), "rb").read(), zs, dicts), change)
            except (OSError, ValueError, struct.error) as e:
                sys.exit("a gift's flow, %s: %s. Nothing written." % (rel, e))
            if set(change) - found:
                sys.exit("%s gives no %s (rando\\test_gifts.txt, or the game's flow is not the one the gifts were listed from). Nothing written." % (
                    rel, ", ".join(sorted(str(k) for k in set(change) - found))))
            gift_files[rel], gift_sizes[rel[:-3]] = now, len(now)
    # ---- the songs: each lesson gives the song the shuffle put there, and who asks about a lesson asks for that song ----
    song_parts = set()
    if lessons:
        now_gives = {g.item: gives[h] for h, g in lessons.items()}
        words = song_words(now_gives)
        taught = set()
        for flow in SONG_FLOWS if words else ():
            rel = "%s/%s.bfevfl.zs" % (GIFT_FLOWS, flow)
            try:
                was = gift_files[rel] if rel in gift_files else unpack(open(os.path.join(romfs, *rel.split("/")), "rb").read(), zs, dicts)
                now, found = gift_items(was, words, kinds=(0, 1, 4))
            except (OSError, ValueError, struct.error) as e:
                sys.exit("a song's flow, %s: %s. Nothing written." % (flow, e))
            taught |= found
            if now is not None:
                gift_files[rel], gift_sizes[rel[:-3]] = now, len(now)
        missed = sorted(old for old, new in now_gives.items() if old != new and old not in taught)
        if missed:
            sys.exit("no lesson gives %s (the game's flows are not the ones the songs were listed from). Nothing written." % ", ".join(missed))
        if words:   # (the ocarina's own flow: what it adds when a lesson's notes have been played back)
            rel = "%s/%s.bfevfl.zs" % (GIFT_FLOWS, SONG_PLAY_FLOW)
            adds = {(entry, old): new for old, new in now_gives.items() if old != new for entry in SONG_PLAY_ENTRIES}
            try:
                now, found = gift_items(unpack(open(os.path.join(romfs, *rel.split("/")), "rb").read(), zs, dicts), adds, kinds=(0,))
            except (OSError, ValueError, struct.error) as e:
                sys.exit("the ocarina's flow, %s: %s. Nothing written." % (SONG_PLAY_FLOW, e))
            missed = sorted(old for old, new in now_gives.items() if old != new and not any((entry, old) in found for entry in SONG_PLAY_ENTRIES))
            if missed:
                sys.exit("the ocarina's flow adds no %s when a lesson is done (not the flow the songs were listed from). Nothing written." % ", ".join(missed))
            gift_files[rel], gift_sizes[rel[:-3]] = now, len(now)
        for rel in SONG_STONES if words else ():
            try:
                now = song_stone(open(os.path.join(romfs, *rel.split("/")), "rb").read(), now_gives)
            except (OSError, ValueError, struct.error, IndexError) as e:
                sys.exit("a royal tomb's stone, %s: %s. Nothing written." % (rel, e))
            if now is not None:
                gift_files[rel] = now
                song_parts.add(rel)
        print("Songs: %d lessons take part, %d now teach another song%s" % (
            len(lessons), sum(1 for old, new in now_gives.items() if old != new),
            "; the royal tomb's stones ask for %s" % now_gives[SUN] if song_parts else ""))
    # ---- a scrub that sells another item no longer names its own (English) ----
    lines = sorted({label for h, g in gifts.items() if g.key in SCRUB_LINES and gives[h] != g.item for label in SCRUB_LINES[g.key]})
    for lang in SCRUB_LANGS if lines else ():
        folder = os.path.join(romfs, "Mals")
        for n in sorted(n for n in (os.listdir(folder) if os.path.isdir(folder) else []) if n.startswith(lang + ".") and n.endswith(".sarc.zs")):
            try:
                was = unpack(open(os.path.join(folder, n), "rb").read(), zs, dicts)
                parts = sarc_read(was)
                text = parts[SCRUB_TEXT]
                for label in lines:
                    text = scrub_words(text, label) or text
                parts[SCRUB_TEXT] = text
                now = sarc_write(parts)
            except (OSError, KeyError, ValueError, struct.error) as e:
                sys.exit("the scrubs' words, Mals/%s: %s. Nothing written." % (n, e))
            if len(now) > len(was):   # (smaller it may be: the size table's entry is for the bigger one)
                sys.exit("the scrubs' words, Mals/%s: the archive would grow. Nothing written." % n)
            if now != was:
                gift_files["Mals/" + n] = now
    if lines:
        print("Deku Scrubs: %d sale line%s no longer name the scrub's own item (English)" % (len(lines), "" if len(lines) == 1 else "s"))


    # ---- Shops: the shelves that take part sell what the shuffle put there, once ----
    shop_files, shop_packs, shop_new, shop_sizes, shop_parts = {}, {}, set(), {}, set()
    if shelves:
        def pack(name):
            rel = "Pack/Actor/%s.pack.zs" % name
            return pack_files[rel] if rel in pack_files else unpack(open(os.path.join(romfs, *rel.split("/")), "rb").read(), zs, dicts)
        # (a test: RANDO_TEST_SHOPS="<item> <item> ..." puts those items on the shelves in their order, the Kokiri shop's
        #  four first, then the Bazaar's, the Potion Shop's, the Bombchu Shop's, the Goron shop's and the Zora shop's: to
        #  see how every item stands on a shelf and what its name and words are there. The seed's rules are not asked)
        for h, item in zip(shelves, os.environ.get("RANDO_TEST_SHOPS", "").split()):
            gives[h] = item
        try:
            # (a shelf actor for each shelf: its item, at its price)
            on_sale = collections.OrderedDict((shop_actor("%s_%d" % (shop.key, index)), (gives[h], shelf_prices[h])) for h, (shop, index, _) in shelves.items())
            base, sample, names = pack(SHOP_BASE), pack(SHOP_SAMPLE), {}
            for actor, (item, price) in on_sale.items():
                new, parts, names[actor] = shop_pack(item, unpack(open(os.path.join(romfs, "Pack", "Actor", item + ".pack.zs"), "rb").read(), zs, dicts),
                                                     base, sample, price, pouch_changed, actor)
                shop_files["Pack/Actor/%s.pack.zs" % actor] = new
                shop_packs["Pack/Actor/%s.pack" % actor] = len(new)
                shop_new.update(parts)
            folder = os.path.join(romfs, "RSDB")
            lifts, scales, turns = {}, {}, {}
            for kind in SHOP_TABLES:   # (the game's three lists of actors: a row for each shelf actor)
                n = next((n for n in sorted(os.listdir(folder)) if n.startswith(kind + ".") and ".byml" in n.lower()), None)
                if n is None:
                    raise ValueError("the game has no list %s" % kind)
                table = unpack(open(os.path.join(folder, n), "rb").read(), zs, dicts)
                if kind == "ActorInfo":   # (how high each shelf's actor stands: by its item's model)
                    fits = {actor: shelf_fit(item, model_box(table, item)) for actor, (item, _) in on_sale.items()}
                    lifts = {actor: lift for actor, (lift, _) in fits.items() if lift}
                    scales = {actor: scale for actor, (_, scale) in fits.items() if scale != 1.0}
                    turns = {actor: SHELF_TURN[item] for actor, (item, _) in on_sale.items() if item in SHELF_TURN}
                    # (a test: RANDO_TEST_LIFTS="<metres> ..." puts the shelves, in RANDO_TEST_SHOPS' order, that much
                    #  higher in place of what their items ask for; "-" leaves one as it is)
                    for (shop, index, _), turn in zip(shelves.values(), os.environ.get("RANDO_TEST_TURNS", "").split()):
                        if turn != "-":   # (a test: "<x>,<y>,<z>" in radians for each shelf, "-" for none)
                            turns[shop_actor("%s_%d" % (shop.key, index))] = tuple(float(v) for v in turn.split(","))
                    for (shop, index, _), size in zip(shelves.values(), os.environ.get("RANDO_TEST_SCALES", "").split()):
                        if size != "-":
                            scales[shop_actor("%s_%d" % (shop.key, index))] = float(size)
                    for (shop, index, _), lift in zip(shelves.values(), os.environ.get("RANDO_TEST_LIFTS", "").split()):
                        if lift != "-":
                            lifts[shop_actor("%s_%d" % (shop.key, index))] = float(lift)
                for actor, (item, price) in on_sale.items():
                    table = shop_rows(table, kind, item, price, actor)
                shop_files["RSDB/" + n] = table
                shop_sizes["RSDB/" + (n[:-3] if n.lower().endswith(".zs") else n)] = len(table)
            packs = sorted(n[:-len(".pack.zs")] for n in os.listdir(os.path.join(romfs, "Pack", "Actor")) if "Shop" in n and n.startswith("Npc_") and n.endswith(".pack.zs"))
            for shop in SHOPS:   # (the goods lists, in every pack that has a copy, and the shelves of the map files)
                sells = {index: (actor, shop_actor("%s_%d" % (shop.key, index))) for index, actor in shop_slots(shop, a.shop_shelves, shield_shelf)}
                for param in shop.params:
                    name, found = SHOP_PARAM % param, 0
                    for keeper in packs:
                        parts = sarc_read(pack(keeper))
                        if name not in parts:
                            continue
                        parts[name] = shop_goods(parts[name], sells)
                        new = sarc_write(parts)
                        pack_files["Pack/Actor/%s.pack.zs" % keeper] = new
                        pack_sizes["Pack/Actor/%s.pack" % keeper] = len(new)
                        shop_parts.add(name)
                        found += 1
                    if not found:
                        raise ValueError("no pack has the goods list %s" % param)
                on_shelf, found = {(actor, index): new for index, (actor, new) in sells.items()}, 0
                for area in shop.areas:
                    folder_map = os.path.join(romfs, "Banc", area)
                    for n in sorted(os.listdir(folder_map)) if os.path.isdir(folder_map) else ():
                        rel = "Banc/%s/%s" % (area, n)
                        if ".bcett.byml" not in n.lower():
                            continue
                        data = changed[rel] if rel in changed else unpack(open(os.path.join(folder_map, n), "rb").read(), zs, dicts)
                        if not any(actor.encode() in data for actor, _ in on_shelf):
                            continue
                        new, count = shelf_actors(data, on_shelf, lifts, scales, turns)
                        if new is not None:
                            changed[rel] = new
                            sizes[rel[:-3] if rel.lower().endswith(".zs") else rel] = len(new)
                            found += count
                if found < len(sells):
                    raise ValueError("%s: the map files have %d of its %d shelves" % (shop.name, found, len(sells)))
            folder = os.path.join(romfs, "Mals")   # (the words under an item's name, in every language)
            for n in sorted(n for n in (os.listdir(folder) if os.path.isdir(folder) else []) if n.endswith(".sarc.zs")):
                rel = "Mals/" + n
                parts = sarc_read(gift_files[rel] if rel in gift_files else unpack(open(os.path.join(folder, n), "rb").read(), zs, dicts))
                text = parts.get(SHOP_TEXT)
                if text is None:
                    continue
                was = text
                for name in sorted(set(names.values())):
                    text = shop_caption(text, name) or text
                if text != was:
                    parts[SHOP_TEXT] = text
                    gift_files[rel] = sarc_write(parts)
                    shop_sizes[rel[:-3]] = len(gift_files[rel])
        except (OSError, KeyError, ValueError, struct.error, IndexError) as e:
            sys.exit("the shops: %s. Nothing written." % e)
        print("Shops (%s): %d shelves of %d shops take part, each sold once; %d within the child's wallet, %d ask for the Adult's, %d for the Giant's" % (
            "any price" if a.shops == 2 else "most prices low", len(shelves), len(SHOPS),
            *(sum(1 for p in shelf_prices.values() if wallet_need(p) == need) for _, need in WALLETS)))

    # ---- Bombchus: a limit of their own, in every seed (the list of pouch actors, with the shops' rows when there are) ----
    try:
        folder = os.path.join(romfs, "RSDB")
        n = next((n for n in sorted(os.listdir(folder)) if n.startswith(POUCH_TABLE + ".") and ".byml" in n.lower()), None)
        if n is None:
            raise ValueError("the game has no list %s" % POUCH_TABLE)
        rel = "RSDB/" + n
        table = chu_limit(shop_files[rel] if rel in shop_files else unpack(open(os.path.join(folder, n), "rb").read(), zs, dicts))
        shop_files[rel] = table
        shop_sizes[rel[:-3] if rel.lower().endswith(".zs") else rel] = len(table)
    except (OSError, KeyError, ValueError, struct.error, IndexError) as e:
        sys.exit("the Bombchus' limit: %s. Nothing written." % e)
    print("Bombchus can be carried without a Bomb Bag: %d at most" % BOMBCHU_LIMIT)

    def shop_table(tbl):
        """the size table with the shops' files: the new packs and their own files added, the keepers' packs' goods
        lists raised, the lists of actors and the texts' archives made to fit"""
        for path, size in shop_packs.items():
            tbl = size_table_add(tbl, [path], size_entry(size, PACK_EXTRA))
        return size_table_update(size_table_raise(size_table_add(tbl, shop_new), shop_parts | song_parts), shop_sizes, SHOP_EXTRA)

    # ---- the size table ----
    folder = os.path.join(romfs, "System", "Resource")
    tables = sorted(n for n in (os.listdir(folder) if os.path.isdir(folder) else []) if "rsizetable" in n.lower())
    if not tables:
        sys.exit("no size table in %s: the grown map files would not load. Nothing written." % folder)
    new_tables = {}
    for n in tables:
        try:
            new_tables["System/Resource/" + n] = shop_table(size_table_update(size_table_add(size_table_raise(size_table_update(
                size_table_update(unpack(open(os.path.join(folder, n), "rb").read(), zs, dicts), sizes), pack_sizes, PACK_EXTRA),
                pack_parts - pack_new), pack_new), gift_sizes, FLOW_EXTRA))
        except Exception as e:
            sys.exit("the size table %s could not be updated (%s). Nothing written." % (n, e))

    spoiler = []
    if logic:
        spoiler += ["", "the gating items, in the order the rules say they can be got:"] + [
            "  %d. %s" % (k + 1, ", ".join("%s (%s)" % (i, next(spots[h][0] for h in gives if gives[h] == i) if i in gives.values() else
                                                      next(skulls[h][0] for h in skull_drops if skull_drops[h] == i) + ", a Gold Skulltula"
                                                      if i in skull_drops.values() else
                                                      next(pieces[h][0] for h in heart_drops if heart_drops[h] == i) + ", where a Piece of Heart lay"
                                                      if i in heart_drops.values() else "its own chest")
                                           for i in sphere)) for k, sphere in enumerate(spheres)]
    area_now = None
    for h in sorted(gives, key=lambda q: (spots[q][0], str(spots[q][5]), q)):
        area, old, _, _, gyaml, pos, event = spots[h]
        if area != area_now:
            spoiler.append("")
            spoiler.append(area)
            area_now = area
        spoiler.append("  %-22s %-26s %-26s -> %s%s" % (gyaml, str(pos), old, gives[h] if gives[h] != old else "(the same)",
                                                         "   [event: %s]" % event if event and event not in PLAIN_EVENTS else ""))
    if a.skulltulas:
        spoiler += ["", "Gold Skulltulas (area, position -> what it drops)"]
        for h in sorted(skulls, key=lambda q: (skulls[q][0], str(skulls[q][1]), q)):
            area, pos, can = skulls[h][:3]
            spoiler.append("  %-22s %-26s -> %s" % (area, str(pos), skull_drops.get(h) or drops.get(h, "(its token)" if can else "(its token: cannot be given a drop)")))
    if a.heart_pieces:
        spoiler += ["", "Pieces of Heart lying in the world (area, position -> what lies there)"]
        for h in sorted(pieces, key=lambda q: (pieces[q][0], str(pieces[q][1]), q)):
            spoiler.append("  %-22s %-26s -> %s" % (pieces[h][0], str(pieces[h][1]), heart_drops.get(h, "(its piece)")))
    if a.dry_run:
        print("\n".join(spoiler[:50]))
        print("(dry run: nothing written)")
        return
    removed = remove_old(mod)
    written = []
    if a.skip_intro:
        try:
            flag_files[OPENING] = opening_skip(unpack(open(os.path.join(romfs, *OPENING.split("/")), "rb").read(), zs, dicts))
        except (OSError, ValueError, struct.error) as e:
            sys.exit("%s: %s. Nothing written." % (OPENING, e))
        print("a new game starts without its two opening cutscenes")
    # (the Kokiri Sword's chest with another item in it: without the cutscene of the sword put on Link's back)
    if any(spots[h][6] == SWORD_EVENT and item != S for h, item in gives.items()):
        try:
            flag_files[SWORD_FLOW] = sword_chest_plain(unpack(open(os.path.join(romfs, *SWORD_FLOW.split("/")), "rb").read(), zs, dicts))
        except (OSError, ValueError, struct.error) as e:
            sys.exit("%s: %s. Nothing written." % (SWORD_FLOW, e))
        print("the Kokiri Sword's chest holds another item: it opens without the cutscene of the sword")
    for rel, data in (list(changed.items()) + list(new_tables.items()) + list(flag_files.items()) + list(pack_files.items()) + list(gift_files.items()) +
                      list(shop_files.items())):
        out = os.path.join(mod, "romfs", *rel.split("/"))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f:
            f.write(zs.ZstdCompressor(level=9).compress(data) if rel.lower().endswith(".zs") else data)
        written.append("romfs/" + rel)
    with open(os.path.join(mod, "spoiler.txt"), "w", encoding="utf-8") as f:
        f.write("seed %d, chests setting %d, dungeon keys setting %d\n(area: chest type, position, what it held -> what it holds now)\n" % (
            seed, which, keys_mode) + "\n".join(spoiler) + "\n")
    with open(os.path.join(mod, TRACKER), "w", encoding="utf-8", newline="\n") as f:   # (for the menu's Tracker tab)
        took = [h for h in able] if a.skulltulas else []
        f.write("\n".join(tracker_lines(collections.Counter(spots[h][0] for h in gives if h not in gifts), collections.Counter([skulls[h][0] for h in took] + [p[0] for p in pieces.values()]),
                                        collections.Counter(g.area for g in gifts.values()))) + "\n")
    with open(os.path.join(mod, CHECKS), "w", encoding="utf-8", newline="\n") as f:   # (for the Tracker tab's Go there)
        skull_need = skull_asks
        named = lambda kind, h, area, pos, item="": check_name(kind, item, about.get(h, {}), pos, exits[area], sub_areas[area])
        f.write("\n".join(check_lines([(spots[h][0], spots[h][5], check_ages(maps[h]), needs[h], named("Chest", h, spots[h][0], spots[h][5], spots[h][1]), h, gives[h],
                                        chest_front(spots[h][5], about[h]["turned"]) if len(spots[h][5]) == 3 and "turned" in about.get(h, {}) else None)
                                       for h in gives if h not in gifts],
                                      [(skulls[h][0], skulls[h][1], check_ages(maps[h]), skull_need(h), named("Gold Skulltula", h, skulls[h][0], skulls[h][1]), h, skull_drops.get(h) or drops.get(h) or TOKEN)
                                       for h in took] +
                                      [(pieces[h][0], pieces[h][1], check_ages(maps[h]), heart_asks(h), named("Piece of Heart", h, pieces[h][0], pieces[h][1]), h,
                                        heart_drops.get(h, HEART)) for h in pieces],
                                      [(g.area, GIFT_PLACES[g.key][1], GIFT_PLACES[g.key][0], needs[h], g.name, None, gives[h])
                                       for h, g in gifts.items() if h in gives and g.key in GIFT_PLACES] +
                                      [(shop.areas[0], shop.place, shop.ages, needs[h], gifts[h].name, None, gives[h])
                                       for h, (shop, _, _) in shelves.items() if h in gives])) + "\n")
    with open(os.path.join(mod, "rando_manifest.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(written)) + "\n")
    with open(stamp_path, "w", encoding="utf-8") as f:   # (last: a run that stopped half way is made again)
        f.write(stamp)
    print("wrote %s: %d map files and the size table%s" % (mod, len(changed), " (%d files of the last seed replaced)" % removed if removed else ""))
    print("where everything went: %s" % os.path.join(mod, "spoiler.txt"))


if __name__ == "__main__":
    main()
