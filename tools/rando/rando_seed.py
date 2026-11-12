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

How a map file is changed (each step shown to work in game by rando_poc.py and rando_poc2.py):
  - a changed chest gets a parameter block of its own at the end of the file (the files store equal blocks once, so
    changing the shared one would change its twins);
  - item names the file does not have yet go into a copy of its string table at the end, after the names it has;
  - the file grows, so its entry in the game's size table (System/Resource/ResourceSizeTable...rsizetable) is raised:
    the game does not load a file larger than its entry.
Needs the zstandard package.
"""
import argparse
import collections
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
FIXES_VERSION = 3   # (1: the eye switch took the Hookshot. 2: before the Kokiri Sword's chest's own cutscene was left out)
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


def gate_skulltulas(rng, gives, drops, skulls, needs, skull_needs, fixed, share=SKULLTULA_GATING_SHARE, never=()):
    """Some of the gating items the logic put in chests (gives) moved to Gold Skulltulas that still drop their token
    (skulls: hashes, in a fixed order; drops: the ones that do not), each only if every gating item can still be
    got by the rules. The chest it leaves gives the token. needs and skull_needs: what a chest and a Skulltula ask
    for; fixed: [(what it asks for, the item)] of the gating items in chests that stay.
    never: gating items that are not tried (one not seen dropped by a Skulltula yet).
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
            gives[chest] = TOKEN
            moved += 1
        else:
            where[item] = (False, chest)
    return gives, drops, collect(placed()), moved


def mix_skulltulas(rng, gives, skulls):
    """The tokens of `skulls` (Skulltulas' hashes, in a fixed order) and the chests' items a Skulltula may be given
    (SKULLTULA_ITEMS) shuffled among those chests and those Skulltulas. Returns (what the chests give now, {a
    Skulltula's hash: the item it drops} for the ones that do not drop their token)."""
    if not skulls:
        return dict(gives), {}
    chests_in = [h for h in gives if gives[h] in SKULLTULA_ITEMS]
    items = [gives[h] for h in chests_in] + [TOKEN] * len(skulls)
    rng.shuffle(items)
    new, drops = dict(gives), {}
    for h, item in zip(chests_in + list(skulls), items):
        if h in gives:
            new[h] = item
        elif item != TOKEN:
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


def gift_items(data, swaps):
    """gift_item for several items of one flow at once: swaps is {old: new}. All are found before any is changed, so
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
        if data[e + 8] != 4:   # (4: a call of a sub-flow)
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
           "rando_start_rupees": 0, "rando_scrubs": 0}
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
# it>|<x> <y> <z>". The menu steps through an area's lines and has the game take Link to one (the debug tools: the
# teleport to the folder's map, then the place). What a check holds is not in the file. Gifts and scrubs have no place
# in a map file by their key, and are not in it. CHECK_ROWS: as many as the menu keeps (kTrackerChecks).
CHECKS = "checks.txt"
CHECK_ROWS = 320


def check_ages(names):
    """C, A or CA: the ages whose map files (names) have a check. A map without an age in its name is both's."""
    child = any("_Child" in n or "_Adult" not in n for n in names)
    adult = any("_Adult" in n or "_Child" not in n for n in names)
    return ("C" if child else "") + ("A" if adult else "")


def check_lines(chests, skulls):
    """The checks file's lines. chests and skulls: [(area (the Banc folder), position, ages)]. By the area's name, the
    chests first, then by place; no more than the menu keeps."""
    rows = [(AREA_NAMES.get(area, area).replace("|", "/")[:47], kind, area, ages, pos)
            for kind, those in (("Chest", chests), ("Gold Skulltula", skulls)) for area, pos, ages in those if len(pos) == 3 and ages]
    rows.sort(key=lambda r: (r[0].lower(), r[1], r[4]))
    return ["# The checks of this seed, one by one, for the Tracker tab's Go there: <area>|<kind>|<folder>|<ages>|<x> <y> <z>"] + [
        "%s|%s|%s|%s|%.1f %.1f %.1f" % (name, kind, area, ages, pos[0], pos[1], pos[2]) for name, kind, area, ages, pos in rows[:CHECK_ROWS]]


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


def place(rng, spots, which, keys_mode, needs=None):
    """What each chest holds. spots: {hash: (area, item, is a dungeon's chest, why it stays or None)}, in a fixed order.
    needs: {hash: what the chest asks for} for the logic, or None: no logic.
    Returns ({hash: item} for the chests that take part, how many chests stay for each reason, the spheres or None).
    With the logic, the thirteen gating items are placed so that each can be reached with the others (an assumed
    fill), counting the ones that stay in their own chests; then the rest goes where there is room."""
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
                free = [h for h in rest if h not in placed and needs[h] <= have]
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
    p.add_argument("--frogs", action="store_true", help="as rando_frogs=1: with Quest rewards, the frogs of Zora's River take part too")
    p.add_argument("--light-arrows", action="store_true", help="as rando_light_arrows=1: with Quest rewards, Zelda's Light Arrows take part too")
    p.add_argument("--scrubs", action="store_true", help="as rando_scrubs=1: the Business Scrubs' four one-time sales take part with the chests (SCRUBS)")
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
    logic_now = a.event_chests and not a.no_logic
    # (the options file's rando_open_deku and rando_open_forest too, so that the launcher's run at Play keeps them)
    a.open_deku = a.open_deku or ini["rando_open_deku"] != 0
    a.open_forest = a.open_forest or ini["rando_open_forest"] != 0
    a.skip_intro = a.skip_intro or ini["rando_skip_intro"] != 0
    a.start_rupees = a.start_rupees or ini["rando_start_rupees"] != 0
    a.scrubs = a.scrubs or ini["rando_scrubs"] != 0
    a.skulltulas = a.skulltulas if a.skulltulas is not None else ini["rando_skulltulas"]
    a.skulltulas = a.skulltulas if 0 <= a.skulltulas <= 3 else 0
    a.quests = a.quests or ini["rando_quests"] != 0
    a.frogs = a.quests and (a.frogs or ini["rando_frogs"] != 0)
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
    for name, on in (("deku", a.open_deku), ("forest", a.open_forest)):
        if on:
            flags.update(OPEN[name])
    # (the open ways are only named when one is open: the seeds made before them keep their stamp)
    rest = " seed %d chests %d keys %d major %d logic %d%s\n" % (seed, which, min(keys_mode, 1), a.event_chests, logic_now,
                                                               (" open %d%d flags" % (a.open_deku, a.open_forest) if flags else "") + (" intro skipped" if a.skip_intro else "") + (" rupees %d" % START_RUPEES if a.start_rupees else "") + ((" skulltulas %d" + " gated all" * logic_now) % a.skulltulas if a.skulltulas else "") +
                                                               (" quests 1%s%s" % (" frogs" * a.frogs, " light" * a.light_arrows) if a.quests else "") + (" scrubs 1 words 2" if a.scrubs else "") + " checks 1" +
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
    skulls = collections.OrderedDict()  # hash -> [area, position, can be given a drop (in every file it is in), a dungeon's, a child's map has it]
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
    if a.quests:
        global PROGRESSION
        PROGRESSION = PROGRESSION | QUEST_GATES
        for g in GIFTS:
            if g.when is None or g.when == "frogs" and a.frogs or g.when == "light" and a.light_arrows:
                gifts[gift_hash(g.key)] = g
                spots[gift_hash(g.key)] = [g.area, g.item, None, None, "gift", g.name, ""]
    if a.scrubs:   # (Deku Scrubs: with or without Quest rewards)
        for g in SCRUBS:
            gifts[gift_hash(g.key)] = g
            spots[gift_hash(g.key)] = [g.area, g.item, None, None, "scrub", g.name, ""]
    # (a string seed: the same on every Python 3. The seeds made before --event-chests keep their shuffle without it)
    logic = a.event_chests and not a.no_logic   # (without the event chests no gating item moves: nothing to ask)
    rng = random.Random("stage2:%d:%d:%d%s%s" % (seed, which, min(keys_mode, 1), ":events" if a.event_chests else "", ":logic" if logic else ""))
    needs = {h: rule(s[0], s[6]) for h, s in spots.items()}
    if a.quests:   # (the rules with the gifts' two gating items named; a gift asks for what its line of GIFTS says)
        needs = {h: quest_need(gifts[h].need, gifts[h].area) if h in gifts else quest_need(n, spots[h][0]) for h, n in needs.items()}
    elif gifts:    # (the scrubs alone)
        needs = {h: gifts[h].need if h in gifts else n for h, n in needs.items()}
    try:
        gives, stays, spheres = place(rng, collections.OrderedDict((h, tuple(s[:4])) for h, s in spots.items()), which, keys_mode,
                                      needs if logic else None)
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
                able, needs, {h: quest_need(skulltula_rule(h, skulls[h][0]), skulls[h][0]) if a.quests else skulltula_rule(h, skulls[h][0])
                              for h in able}, fixed, never=(SSC,) if a.quests else ())
            print("Gold Skulltulas: %d gating item%s now dropped by one" % (gated, "" if gated == 1 else "s"))
        for h, item in skull_drops.items():
            drops.setdefault(h, item)   # (a test's drop for the same Skulltula stays)
        pickups = sorted(set(pickups) | set(skull_drops.values()))
        print("Gold Skulltulas %s: %d take part (%d more cannot be given a drop: their map file is not read whole; the map files have %d), %d now drop a "
              "chest's item, %d chests hold a token" % (("", "dungeons", "overworld", "all")[a.skulltulas], len(able),
                                                        len(mine) - len(able), len(skulls), len(skull_drops),
                                          sum(1 for i in gives.values() if i == TOKEN)))

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
        mine = [h for h, g in gifts.items() if g.when != "scrubs"]
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
    if flags or a.start_rupees:
        folder = os.path.join(romfs, FLAG_LIST)
        lists = sorted(n for n in (os.listdir(folder) if os.path.isdir(folder) else []) if n.startswith("GameDataList.") and ".byml" in n.lower())
        if not lists:
            sys.exit("no list of flags in %s: the ways cannot be opened, nor the rupees given. Nothing written." % folder)
        for n in lists:
            try:
                was = unpack(open(os.path.join(folder, n), "rb").read(), zs, dicts)
                new = flag_defaults(was, flags) if flags else None
                if a.start_rupees:   # (the same file: the rupees after the flags)
                    more = flag_defaults(new if new is not None else was, {RUPEES: START_RUPEES}, kind="Int")
                    new = more if more is not None else new
            except Exception as e:
                sys.exit("%s: %s. Nothing written." % (n, e))
            if new is not None:
                flag_files[FLAG_LIST + "/" + n] = new
        if a.start_rupees:
            print("a new game starts with %d rupees" % START_RUPEES)
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
    if pickups:
        def pack(name):
            return unpack(open(os.path.join(romfs, "Pack", "Actor", name + ".pack.zs"), "rb").read(), zs, dicts)
        try:
            base = pack(PICKUP_BASE)
            base_parts = sarc_read(base)
            pouch = {}
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
        if gives[h] != g.item:
            swaps.setdefault(g.flow, {}).update(((g.entry, old) if g.entry else old, gives[h]) for old in g.olds)
    for flow, old, new in test_gifts:
        swaps.setdefault(flow, {})[old] = new
        print("TEST: %s gives %s in place of %s (rando\\test_gifts.txt)" % (flow, new, old))
    for flow, change in swaps.items():
        rel = "%s/%s.bfevfl.zs" % (GIFT_FLOWS, flow)
        try:
            now, found = gift_items(unpack(open(os.path.join(romfs, *rel.split("/")), "rb").read(), zs, dicts), change)
        except (OSError, ValueError, struct.error) as e:
            sys.exit("a gift's flow, %s: %s. Nothing written." % (flow, e))
        if set(change) - found:
            sys.exit("%s gives no %s (rando\\test_gifts.txt, or the game's flow is not the one the gifts were listed from). Nothing written." % (
                flow, ", ".join(sorted(str(k) for k in set(change) - found))))
        gift_files[rel], gift_sizes[rel[:-3]] = now, len(now)
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

    # ---- the size table ----
    folder = os.path.join(romfs, "System", "Resource")
    tables = sorted(n for n in (os.listdir(folder) if os.path.isdir(folder) else []) if "rsizetable" in n.lower())
    if not tables:
        sys.exit("no size table in %s: the grown map files would not load. Nothing written." % folder)
    new_tables = {}
    for n in tables:
        try:
            new_tables["System/Resource/" + n] = size_table_update(size_table_add(size_table_raise(size_table_update(
                size_table_update(unpack(open(os.path.join(folder, n), "rb").read(), zs, dicts), sizes), pack_sizes, PACK_EXTRA),
                pack_parts - pack_new), pack_new), gift_sizes, FLOW_EXTRA)
        except Exception as e:
            sys.exit("the size table %s could not be updated (%s). Nothing written." % (n, e))

    spoiler = []
    if logic:
        spoiler += ["", "the gating items, in the order the rules say they can be got:"] + [
            "  %d. %s" % (k + 1, ", ".join("%s (%s)" % (i, next(spots[h][0] for h in gives if gives[h] == i) if i in gives.values() else
                                                      next(skulls[h][0] for h in skull_drops if skull_drops[h] == i) + ", a Gold Skulltula"
                                                      if i in skull_drops.values() else "its own chest")
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
    for rel, data in list(changed.items()) + list(new_tables.items()) + list(flag_files.items()) + list(pack_files.items()) + list(gift_files.items()):
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
        f.write("\n".join(tracker_lines(collections.Counter(spots[h][0] for h in gives if h not in gifts), collections.Counter(skulls[h][0] for h in took),
                                        collections.Counter(g.area for g in gifts.values()))) + "\n")
    with open(os.path.join(mod, CHECKS), "w", encoding="utf-8", newline="\n") as f:   # (for the Tracker tab's Go there)
        f.write("\n".join(check_lines([(spots[h][0], spots[h][5], check_ages(maps[h])) for h in gives if h not in gifts],
                                      [(skulls[h][0], skulls[h][1], check_ages(maps[h])) for h in took])) + "\n")
    with open(os.path.join(mod, "rando_manifest.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(written)) + "\n")
    with open(stamp_path, "w", encoding="utf-8") as f:   # (last: a run that stopped half way is made again)
        f.write(stamp)
    print("wrote %s: %d map files and the size table%s" % (mod, len(changed), " (%d files of the last seed replaced)" % removed if removed else ""))
    print("where everything went: %s" % os.path.join(mod, "spoiler.txt"))


if __name__ == "__main__":
    main()
