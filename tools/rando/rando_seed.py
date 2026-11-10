"""Randomizer, stage 2: shuffles what the chests hold across the whole game, as a mod.

Reads the Randomizer settings the game's menu and the launcher keep in <game folder>\\hookshot_options.ini (rando_on,
rando_seed, rando_chests, rando_keys) and writes changed map files and an updated size table to
<game folder>\\mods\\rando-seed\\romfs\\..., which Mako loads in place of the game's own. The game's files are not
touched. The same seed and settings give the same shuffle.

    python -I tools/rando/rando_seed.py "F:\\Games\\OOT Remake Rando\\romfs"
    python -I tools/rando/rando_seed.py <romfs> [--game <folder>] [--seed N] [--chests 0..3] [--keys 0..2] [--event-chests] [--no-logic] [--dry-run]

Run it again after changing the seed or a setting. With the randomizer off (or Chests Off) it removes the files it
wrote before, so the game is as shipped again.

Settings:
  Chests        1 the overworld's chests take part, 2 the dungeons', 3 all. Their items are shuffled among them, across
                areas: a Kokiri Forest chest can hold what a Fire Temple chest held.
  Dungeon keys  Off: a dungeon's small keys, Boss Key, map and compass stay in their own chests. Own dungeon: they are
                shuffled among that dungeon's chests. Anywhere is treated as Own dungeon for now: the game counts a
                small key for the dungeon it is picked up in, so one from another dungeon would be miscounted.
What it leaves alone: a mini-game's chests, a chest whose item depends on what Link already has, and, unless
--event-chests is given, a chest that starts an event when opened (most of the big items: the Kokiri Sword, the Fairy
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
# (a chest with one of these parameters is left as it is: see the top of this file)
KEEP_IF = ("GetEventName", "CheckEventName", "CheckEventNameIndoor", "Drop__CheckActor", "Drop__DropActor_Substitute",
           "DropViewActor", "IsEnableRepeatOpen", "SpawnType")
# (a chest's GetEventName that is known not to care what the chest holds: Mido's house's chests, whose event only
# quiets Navi. They gave other items in the tests and played as usual)
PLAIN_EVENTS = ("KokiriForest_TreasureBox_NaviChatOff",)
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


def stays_why(c, events):
    """Why a chest keeps its own item whatever the settings, or None. events: chests that start an event take part too."""
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


def size_entry(size):
    """what the game's size table holds for a map file of `size` bytes unpacked: the size rounded up to 32, and 264
    (every map file looked at had exactly that)"""
    return (size + 31 & ~31) + 264


def size_table_update(tbl, sizes):
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
        struct.pack_into("<I", out, at + 4, max(struct.unpack_from("<I", tbl, at + 4)[0], size_entry(size)))
    return bytes(out)


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
    got = {"rando_on": 0, "rando_seed": 0, "rando_chests": 0, "rando_keys": 0}
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


def remove_old(mod):
    """the files a run before this one wrote (its list: rando_manifest.txt), and the folders they leave empty"""
    listing = os.path.join(mod, "rando_manifest.txt")
    if not os.path.isfile(listing):
        return 0
    n = 0
    with open(listing, encoding="utf-8") as f:
        rels = [line.strip() for line in f if line.strip()]
    for rel in rels + ["spoiler.txt", "rando_manifest.txt"]:
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
        if not why and (which == 1 and dungeon or which == 2 and not dungeon):
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
    print("randomizer %s, seed %d, chests %s, dungeon keys %s" % ("on" if on else "off", seed, ("off", "overworld", "dungeons", "all")[which],
                                                                   ("off", "own dungeon", "anywhere (as own dungeon for now)")[keys_mode]))
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
        if found:
            files[rel] = (data, found)

    # ---- the chests: one per hash (the same chest is in several files: child and adult, static and dynamic) ----
    spots = collections.OrderedDict()   # hash -> [area, item, dungeon, why it stays, type, position]
    for rel, (data, found) in files.items():
        parts = rel.split("/")
        area = parts[1] if len(parts) > 2 else "(Banc)"
        for c in found:
            if c.hash is None or not c.gyaml.startswith("Obj_TBox"):
                continue
            why = stays_why(c, a.event_chests)
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
    # (a string seed: the same on every Python 3. The seeds made before --event-chests keep their shuffle without it)
    logic = a.event_chests and not a.no_logic   # (without the event chests no gating item moves: nothing to ask)
    rng = random.Random("stage2:%d:%d:%d%s%s" % (seed, which, min(keys_mode, 1), ":events" if a.event_chests else "", ":logic" if logic else ""))
    needs = {h: rule(s[0], s[6]) for h, s in spots.items()}
    try:
        gives, stays, spheres = place(rng, collections.OrderedDict((h, tuple(s[:4])) for h, s in spots.items()), which, keys_mode,
                                      needs if logic else None)
    except ValueError as e:
        sys.exit("%s. Nothing written. Try Chests: All, or --no-logic." % e)
    unknown = sorted({s[0] for s in spots.values() if s[0] not in RULES})

    # (the game's own count of each item is kept: every item given was some chest's)
    before = collections.Counter(spots[h][1] for h in gives)
    if before != collections.Counter(gives.values()):
        sys.exit("the shuffle lost or made an item: nothing written")

    # ---- the map files ----
    changed, sizes = collections.OrderedDict(), {}
    for rel, (data, found) in files.items():
        try:
            new = rewrite(data, gives)
        except Exception as e:
            sys.exit("%s: %s. Nothing was written to the mod." % (rel, e))
        if new is not None:
            changed[rel] = new
            sizes[rel[:-3] if rel.lower().endswith(".zs") else rel] = len(new)
    moved = sum(1 for h, item in gives.items() if item != spots[h][1])
    print("%d chests take part, %d now hold another chest's item; %d map files change" % (len(gives), moved, len(changed)))
    for why, n in stays.most_common():
        print("  left alone: %d (%s)" % (n, why))
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

    # ---- the size table ----
    folder = os.path.join(romfs, "System", "Resource")
    tables = sorted(n for n in (os.listdir(folder) if os.path.isdir(folder) else []) if "rsizetable" in n.lower())
    if not tables:
        sys.exit("no size table in %s: the grown map files would not load. Nothing written." % folder)
    new_tables = {}
    for n in tables:
        try:
            new_tables["System/Resource/" + n] = size_table_update(unpack(open(os.path.join(folder, n), "rb").read(), zs, dicts), sizes)
        except Exception as e:
            sys.exit("the size table %s could not be updated (%s). Nothing written." % (n, e))

    spoiler = []
    if logic:
        spoiler += ["", "the gating items, in the order the rules say they can be got:"] + [
            "  %d. %s" % (k + 1, ", ".join("%s (%s)" % (i, next(spots[h][0] for h in gives if gives[h] == i) if i in gives.values() else "its own chest")
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
    if a.dry_run:
        print("\n".join(spoiler[:50]))
        print("(dry run: nothing written)")
        return
    removed = remove_old(mod)
    written = []
    for rel, data in list(changed.items()) + list(new_tables.items()):
        out = os.path.join(mod, "romfs", *rel.split("/"))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f:
            f.write(zs.ZstdCompressor(level=9).compress(data) if rel.lower().endswith(".zs") else data)
        written.append("romfs/" + rel)
    with open(os.path.join(mod, "spoiler.txt"), "w", encoding="utf-8") as f:
        f.write("seed %d, chests setting %d, dungeon keys setting %d\n(area: chest type, position, what it held -> what it holds now)\n" % (
            seed, which, keys_mode) + "\n".join(spoiler) + "\n")
    with open(os.path.join(mod, "rando_manifest.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(written)) + "\n")
    print("wrote %s: %d map files and the size table%s" % (mod, len(changed), " (%d files of the last seed replaced)" % removed if removed else ""))
    print("where everything went: %s" % os.path.join(mod, "spoiler.txt"))


if __name__ == "__main__":
    main()
