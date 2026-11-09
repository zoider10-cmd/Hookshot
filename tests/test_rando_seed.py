"""The chest shuffle (tools/rando/rando_seed.py) on made-up map files: no game data, no zstandard.

A map file is built here as the game's are (BYML, equal dictionaries stored once), then checked: a changed chest gets
a block of its own and its twins keep theirs, a name new to the file is added after the names it has, nothing but the
chests asked for changes, the size table's entries are raised to fit, and the shuffle keeps every item and keeps a
dungeon's keys in their dungeon.

    python -I -B tests/test_rando_seed.py
"""
import collections
import importlib.util
import random
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rando_seed", ROOT / "tools" / "rando" / "rando_seed.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


def check(ok, what):
    if not ok:
        raise SystemExit("FAIL: " + what)


def build(root):
    """a BYML document of dictionaries, lists, strings, numbers and booleans; equal dictionaries stored once"""
    keys, strs = set(), set()

    def collect(v):
        if isinstance(v, dict):
            for k, x in v.items():
                keys.add(k)
                collect(x)
        elif isinstance(v, list):
            for x in v:
                collect(x)
        elif isinstance(v, str):
            strs.add(v)
    collect(root)
    keys, strs = sorted(keys), sorted(strs)
    blob, cache = bytearray(16), {}
    key_at = len(blob)
    blob += seed.string_table(keys)
    str_at = len(blob)
    blob += seed.string_table(strs)

    def kind(v):
        return (0xD0 if isinstance(v, bool) else 0xA0 if isinstance(v, str) else 0xD2 if isinstance(v, float) else
                (0xD5 if v > 0xffffffff else 0xD3) if isinstance(v, int) else 0xC0 if isinstance(v, list) else 0xC1)

    def value(v):
        t = kind(v)
        if t == 0xD0:
            return int(v)
        if t == 0xA0:
            return strs.index(v)
        if t == 0xD2:
            return struct.unpack("<I", struct.pack("<f", v))[0]
        if t == 0xD3:
            return v
        if t == 0xD5:
            at = len(blob)
            blob.extend(struct.pack("<Q", v))
            return at
        return node(v)

    def node(v):
        if isinstance(v, list):
            vals = [value(x) for x in v]
            at = len(blob)
            blob.extend(bytes([0xC0]) + len(v).to_bytes(3, "little") + bytes(kind(x) for x in v) + b"\0" * (-len(v) % 4))
            for x in vals:
                blob.extend(struct.pack("<I", x))
            return at
        same = repr(sorted(v.items()))
        if same in cache:
            return cache[same]
        vals = [(keys.index(k), kind(x), value(x)) for k, x in sorted(v.items())]
        at = cache[same] = len(blob)
        blob.extend(bytes([0xC1]) + len(v).to_bytes(3, "little"))
        for k, t, x in vals:
            blob.extend(k.to_bytes(3, "little") + bytes([t]) + struct.pack("<I", x))
        return at
    root_at = node(root)
    blob[0:16] = b"YB" + struct.pack("<HIII", 7, key_at, str_at, root_at)
    return bytes(blob)


def chest(ident, item, room=None, extra=None, gyaml="Obj_TBox_A_01"):
    dyn = {"Drop__DropActor": item}
    if room is not None:
        dyn["DefaultDungeonRoomIndex"] = room
    dyn.update(extra or {})
    return {"Gyaml": gyaml, "Hash": 0x1000000000000000 + ident, "Translate": [float(ident), 2.0, 3.0], "Dynamic": dyn}


def main():
    event = {"GetEventName": "KokiriForest_TreasureBox_NaviChatOff"}
    actors = [chest(1, "TBox_Rupee_Green", extra=event), chest(2, "TBox_Rupee_Blue", extra=event), chest(3, "TBox_Rupee_Blue", extra=event),
              chest(4, "TBox_Rupee_Blue", extra=event), {"Gyaml": "Obj_Pot_A_01", "Hash": 9, "Dynamic": {"Drop__DropActor": "TBox_Rupee_Blue"}},
              {"Gyaml": "Obj_Pot_A_02", "Dynamic": {"Drop__DropActor": "TBox_Rupee_Blue", "GetEventName": "KokiriForest_TreasureBox_NaviChatOff"}},
              {"Gyaml": "Obj_Tree_A_01", "Hash": 10}]
    data = build({"Actors": actors, "FilePath": "x"})
    found, keys, strings = seed.chests(data)
    check([c.item for c in found] == ["TBox_Rupee_Green"] + ["TBox_Rupee_Blue"] * 5, "the made-up map's chests were not read")
    check(found[1].dyn_at == found[2].dyn_at == found[3].dyn_at == found[5].dyn_at != found[4].dyn_at,
          "equal blocks are not stored once in the made-up map: it would not test what the game's files do")
    check(found[0].pos == (1.0, 2.0, 3.0) and found[0].event == event["GetEventName"] and found[5].hash is None, "a chest's fields")

    # ---- one of three twins, to a name the file has and to one it has not ----
    check(seed.rewrite(data, {}) is None and seed.rewrite(data, {found[1].hash: "TBox_Rupee_Blue"}) is None, "no change is not None")
    for item, grows_table in (("TBox_Rupee_Green", False), ("Obj_Heart_Piece", True)):
        new = seed.rewrite(data, {found[2].hash: item})
        again, _, names = seed.chests(new)
        check([c.item for c in again] == ["TBox_Rupee_Green", "TBox_Rupee_Blue", item] + ["TBox_Rupee_Blue"] * 3,
              "only the chest asked for changes (%s)" % item)
        differs = [i for i in range(16, len(data)) if new[i] != data[i]]
        check(new[:8] == data[:8] and differs and all(found[2].dyn_where <= i < found[2].dyn_where + 4 for i in differs),
              "the file's own bytes: only the chest's pointer to its block")
        check((names[:len(strings)] == strings) and (len(names) == len(strings) + grows_table) and (names[-1] == item or not grows_table),
              "a new name goes after the names the file has")
        check(len(new) > len(data) and len(new) % 4 == 0, "the file grows by whole words")
    # (two chests to the same new name: it is added once)
    new = seed.rewrite(data, {found[1].hash: "Item_Hammer", found[3].hash: "Item_Hammer", found[0].hash: "TBox_Rupee_Blue"})
    again, _, names = seed.chests(new)
    check([c.item for c in again] == ["TBox_Rupee_Blue", "Item_Hammer", "TBox_Rupee_Blue", "Item_Hammer", "TBox_Rupee_Blue", "TBox_Rupee_Blue"] and
          names.count("Item_Hammer") == 1, "two chests to one new name")

    # ---- which chests keep their own item ----
    def one(extra, item="TBox_Rupee_Red"):
        return seed.chests(build({"Actors": [chest(1, item, extra=extra)]}))[0][0]
    for events in (False, True):
        check(seed.stays_why(one(None), events) is None and seed.stays_why(one(event), events) is None, "a plain chest takes part")
        check(seed.stays_why(one({"GetEventName": "MiniGame_ChoiceTreasure_OpenHitTreasureBox"}), events), "a mini-game's event chest stays")
        check(seed.stays_why(one({"GetEventName": "ForestTemple_GetBow", "Drop__CheckActor": "Item_Range_Bow"}), events) and
              seed.stays_why(one({"SpawnType": 1}), events) and seed.stays_why(one(None, "Obj_MiniGame_SmallKey"), events),
              "a chest that depends on what Link has, or a mini-game's, stays")
    check(seed.stays_why(one({"GetEventName": "Get_StoneOfForest_GetSword"}), False) and
          seed.stays_why(one({"GetEventName": "Get_StoneOfForest_GetSword"}), True) is None, "an event's chest takes part only when asked")

    # ---- the size table ----
    check(seed.size_entry(510884) == 511176 and seed.size_entry(516036) == 516328 and seed.size_entry(132068) == 132360 and
          seed.size_entry(266440) == 266728, "a map file's size entry: the four the game's own table has")
    paths = ["Banc/A/A_Static.bcett.byml", "Banc/B/B_Dynamic.bcett.byml"] + ["Other/%d.bin" % i for i in range(400)]
    rows = sorted((zlib.crc32(p.encode()) & 0xffffffff, 1000 + i) for i, p in enumerate(paths))
    tbl = b"RESTBL" + struct.pack("<IIII", 1, 160, len(rows), 0) + b"".join(struct.pack("<II", c, s) for c, s in rows)
    out = seed.size_table_update(tbl, {paths[0]: 5000, paths[1]: 10})
    got = {struct.unpack_from("<I", out, 22 + i * 8)[0]: struct.unpack_from("<I", out, 26 + i * 8)[0] for i in range(len(rows))}
    want = dict(rows)
    want[zlib.crc32(paths[0].encode())] = seed.size_entry(5000)   # (raised; the other fits as it is and stays)
    check(got == want and len(out) == len(tbl) and out[:22] == tbl[:22], "only the grown file's entry is raised")
    for bad in (b"NOTBL" + tbl[5:], tbl[:40]):
        try:
            seed.size_table_update(bad, {paths[0]: 1})
            check(False, "a file that is not a size table was taken")
        except ValueError:
            pass
    try:
        seed.size_table_update(tbl, {"Banc/None.bcett.byml": 1})
        check(False, "a path the table does not have was taken")
    except ValueError:
        pass

    # ---- the shuffle ----
    spots = collections.OrderedDict()
    n = 0
    for area, dungeon, items in (("KokiriForest", False, ["TBox_Rupee_Green", "TBox_Rupee_Blue", "Obj_Heart_Piece", "TBox_Shield_Deku"] * 3),
                                 ("FireTemple", True, ["Item_Dungeon_SmallKey"] * 5 + ["Item_Dungeon_BossKey", "Item_Dungeon_Map",
                                                                                      "Item_Dungeon_Compass", "TBox_Rupee_Red", "Item_BombBundle_Small"]),
                                 ("WaterTemple", True, ["Item_Dungeon_SmallKey"] * 6 + ["Item_Dungeon_BossKey", "TBox_Rupee_Purple"])):
        for item in items:
            n += 1
            spots[n] = (area, item, dungeon, "an event's" if n % 11 == 0 else None)
    for which in (1, 2, 3):
        for keys_mode in (0, 1, 2):
            gives, stays = seed.place(random.Random("t:%d:%d" % (which, keys_mode)), spots, which, keys_mode)
            check(len(gives) + sum(stays.values()) == len(spots), "every chest takes part or stays, once")
            check(collections.Counter(gives.values()) == collections.Counter(spots[h][1] for h in gives), "the shuffle keeps every item")
            for h, item in gives.items():
                area, old, dungeon, why = spots[h]
                check(not why and (which == 3 or dungeon == (which == 2)), "a chest that stays, or not this setting's, was given an item")
                check(keys_mode or old not in seed.DUNGEON_ITEMS, "Dungeon keys off: a key's chest took part")
            for area in ("FireTemple", "WaterTemple"):   # (a dungeon's keys, map and compass are still in it)
                here = [h for h in gives if spots[h][0] == area]
                check(collections.Counter(gives[h] for h in here if gives[h] in seed.DUNGEON_ITEMS) ==
                      collections.Counter(spots[h][1] for h in here if spots[h][1] in seed.DUNGEON_ITEMS), "a dungeon's keys left it")
            check(all(item not in seed.DUNGEON_ITEMS for h, item in gives.items() if spots[h][0] == "KokiriForest"), "a key in the overworld")
    a, _ = seed.place(random.Random("same"), spots, 3, 1)
    b, _ = seed.place(random.Random("same"), spots, 3, 1)
    c, _ = seed.place(random.Random("other"), spots, 3, 1)
    check(a == b and a != c, "the same seed is the same shuffle, another seed another")
    check(sum(a[h] != spots[h][1] for h in a) > len(a) // 3, "a shuffle that moves little")
    print("PASS: the chest shuffle")


if __name__ == "__main__":
    main()
