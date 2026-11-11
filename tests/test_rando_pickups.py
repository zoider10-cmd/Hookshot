"""An item's pack made a pick-up's (tools/rando/rando_seed.py: pickup_pack) on made-up packs: no game data.

A pack is built here as the game's are (a SARC archive of BYML parameter files), then checked: the archive and a
parameter file come back as they were written, the item's actor takes the base's as its parent, its table of game
parameters names the base's, what it is in the pouch is got by touching it, the pack gets the base's files and keeps
its own over them, the base's effects name another's, and the size table's entries of changed files are raised.

    python -I -B tests/test_rando_pickups.py
"""
import collections
import importlib.util
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


def tree(value):
    """a Python value as a tree of byml_parse"""
    if isinstance(value, dict):
        return ("dict", collections.OrderedDict((k, tree(v)) for k, v in value.items()))
    if isinstance(value, list):
        return ("array", [tree(v) for v in value])
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, bool):
        return (0xD0, struct.pack("<I", int(value)))
    if isinstance(value, float):
        return (0xD2, struct.pack("<f", value))
    return (0xD1, struct.pack("<i", value))


def byml(value):
    return seed.byml_build(tree(value), 7)


def plain(node):
    """a tree of byml_parse as a Python value again"""
    if node[0] == "dict":
        return {k: plain(v) for k, v in node[1].items()}
    if node[0] == "array":
        return [plain(v) for v in node[1]]
    if node[0] == "string":
        return node[1]
    if node[0] == 0xD0:
        return bool(struct.unpack("<I", node[1])[0])
    if node[0] == 0xD2:
        return struct.unpack("<f", node[1])[0]
    return int.from_bytes(node[1], "little", signed=node[0] in (0xD1, 0xD4))   # (4 bytes, or the 8 of a 64-bit value)


def read(data):
    return plain(seed.byml_parse(data)[0])


ACTOR = "Actor/%s.engine__actor__ActorParam.bgyml"
TABLE = "GameParameter/GameParameterTable/%s.engine__actor__GameParameterTable.bgyml"
POUCH = "Component/PouchContentParam/%s.game__component__PouchContentParam.bgyml"
LINK = "Component/%s/%s.engine__component__%sParam.bgyml"
BASE = seed.PICKUP_BASE


def packs():
    item = collections.OrderedDict()
    item[ACTOR % "Item_Thing"] = byml({"$parent": "Work/Actor/Item_EventObject_Base.engine__actor__ActorParam.gyml",
                                       "Components": {"GameParameterTableRef": "?" + TABLE % "Item_Thing",
                                                      "ModelInfoRef": "?Component/ModelInfo/Item_Thing.bgyml",
                                                      "PouchContentRef": "?" + POUCH % "Thing"}})
    item[TABLE % "Item_Thing"] = byml({"Category": "GameParameterTableDefault", "Components": {"Own": "?Own.bgyml"}})
    item[POUCH % "Thing"] = byml({"GetDemoOffsetPos": {"X": 0.0, "Y": 0.25, "Z": 0.0}, "IsOpenActionGuide": True})
    item["Component/ModelInfo/Item_Thing.bgyml"] = byml({"FmdbName": "Item_Thing"})
    item["Shared.bgyml"] = byml({"Whose": "the item's"})
    base = collections.OrderedDict()
    base[ACTOR % BASE] = byml({"$parent": "Work/Actor/Obj_Item_Base.engine__actor__ActorParam.gyml",
                               "Components": {"ELinkRef": "?" + LINK % ("ELink", BASE, "ELink")}})
    base[TABLE % BASE] = byml({"Components": {"DropBoundParam": "?Drop.bgyml"}})
    base[LINK % ("ELink", BASE, "ELink")] = byml({"UserName": BASE})
    base[LINK % ("SLink", BASE, "SLink")] = byml({"UserName": BASE})
    base["Shared.bgyml"] = byml({"Whose": "the base's"})
    return item, base


def main():
    item, base = packs()

    # ---- the archive and a parameter file come back as written ----
    packed = seed.sarc_write(item)
    check(dict(seed.sarc_read(packed)) == dict(item), "a SARC archive read again is not what was written")
    check(seed.sarc_write(seed.sarc_read(packed)) == packed, "a SARC archive written twice differs")
    value = {"A": [1, 2, {"B": "text", "C": True}], "D": 0.5, "E": {"F": "text", "G": -3}, "$parent": "p"}
    check(read(byml(value)) == value, "a parameter file read again is not what was written")
    check(seed.byml_build(*seed.byml_parse(byml(value))) == byml(value), "a parameter file written twice differs")
    try:
        seed.sarc_read(b"SARCnot one")
        check(False, "bytes that are no archive were taken")
    except (ValueError, struct.error):
        pass

    # ---- the item made a pick-up ----
    new = seed.sarc_read(seed.pickup_pack("Item_Thing", packed, seed.sarc_write(base)))
    actor = read(new[ACTOR % "Item_Thing"])
    check(actor["$parent"] == "Work/" + (ACTOR % BASE).replace(".bgyml", ".gyml"), "the item's actor does not take the base's as its parent")
    check(actor["Components"] == read(item[ACTOR % "Item_Thing"])["Components"], "the item's own parts changed")
    table = read(new[TABLE % "Item_Thing"])
    check(table["$parent"] == "Work/" + (TABLE % BASE).replace(".bgyml", ".gyml") and table["Components"] == {"Own": "?Own.bgyml"},
          "the item's table of game parameters does not name the base's, or lost its own")
    pouch = read(new[POUCH % "Thing"])
    check(pouch["DefaultAutoGet"] is True and pouch["IsOpenActionGuide"] is True and abs(pouch["GetDemoOffsetPos"]["Y"] - 0.25) < 1e-6,
          "what the item is in the pouch is not got by touching it, or lost what it had")
    check(set(new) == set(item) | set(base), "the pack does not have the item's files and the base's")
    check(new["Shared.bgyml"] == item["Shared.bgyml"], "the base's file took the place of the item's own")
    check(new[ACTOR % BASE] == base[ACTOR % BASE] and new[TABLE % BASE] == base[TABLE % BASE], "the base's actor or table changed")
    for kind in ("ELink", "SLink"):
        check(read(new[LINK % (kind, BASE, kind)]) == {"UserName": seed.PICKUP_EFFECTS}, "the base's %s still names the base" % kind)
    check(new["Component/ModelInfo/Item_Thing.bgyml"] == item["Component/ModelInfo/Item_Thing.bgyml"], "the item's model changed")

    # (got each time, for what a Skulltula drops: the get event each time, and how it is got where the file does not say)
    check("PlayGetEventManyTimes" not in pouch and "GetType" not in pouch, "an item not asked to be got each time was made so")
    each = seed.sarc_read(seed.pickup_pack("Item_Thing", packed, seed.sarc_write(base), each_time=True))
    pouch = read(each[POUCH % "Thing"])
    check(pouch["PlayGetEventManyTimes"] is True and pouch["GetType"] == seed.GET_LARGE and pouch["DefaultAutoGet"] is True,
          "an item got each time: its get event each time, and got as the game's own such items are")
    said = collections.OrderedDict(item)
    said[POUCH % "Thing"] = byml({"GetType": 7, "IsOpenActionGuide": True})
    pouch = read(seed.sarc_read(seed.pickup_pack("Item_Thing", seed.sarc_write(said), seed.sarc_write(base), each_time=True))[POUCH % "Thing"])
    check(pouch["PlayGetEventManyTimes"] is True and pouch["GetType"] == 7, "how an item is got was changed where its file says it")

    # (a small item is made larger, by its model's own setting; the others' models are left as they are)
    seed.PICKUP_SCALES["Item_Thing"] = 1.5
    try:
        big = read(seed.sarc_read(seed.pickup_pack("Item_Thing", packed, seed.sarc_write(base)))["Component/ModelInfo/Item_Thing.bgyml"])
    finally:
        del seed.PICKUP_SCALES["Item_Thing"]
    check(big["FmdbName"] == "Item_Thing" and all(abs(big["DebugModelScale"][axis] - 1.5) < 1e-6 for axis in "XYZ"),
          "a small item's model is not made larger, or lost what it had")
    check(all(1.0 < k <= 2.0 for k in seed.PICKUP_SCALES.values()), "an item is made smaller, or so large that it hangs far from where it is taken")

    # (a pouch file of its own, for an item whose pouch file is another thing's too: a copy under a new name, the
    # item's actor naming it, the item's own file as it was; and the size table given an entry for the new file)
    mine = seed.sarc_read(seed.pickup_pack("Item_Thing", packed, seed.sarc_write(base), each_time=True, own_pouch=frozenset(("Item_Thing",))))
    new_name = seed.OWN_POUCH % "Item_Thing"
    check(mine[POUCH % "Thing"] == item[POUCH % "Thing"], "the item's pouch file, another thing's too, was changed")
    own = read(mine[new_name])
    check(own["DefaultAutoGet"] is True and own["PlayGetEventManyTimes"] is True and own["GetType"] == seed.GET_LARGE and
          own["IsOpenActionGuide"] is True and abs(own["GetDemoOffsetPos"]["Y"] - 0.25) < 1e-6, "the pouch file of its own is not the item's with the pick-up's changes")
    check(read(mine[ACTOR % "Item_Thing"])["Components"]["PouchContentRef"] == "?" + new_name, "the item's actor does not name the pouch file of its own")
    check(set(mine) == set(item) | set(base) | {new_name}, "more than one file was added for it")
    check(new_name not in new, "an item not asked to have a pouch file of its own was given one")
    check(all(i not in seed.PROGRESSION for i in seed.PICKUP_OWN_POUCH), "a gating item is given a pouch file of its own")

    # (a table that has a parent keeps it; a pack without the actor is not taken)
    kept = collections.OrderedDict(item)
    kept[TABLE % "Item_Thing"] = byml({"$parent": "Work/Other.gyml"})
    again = seed.sarc_read(seed.pickup_pack("Item_Thing", seed.sarc_write(kept), seed.sarc_write(base)))
    check(read(again[TABLE % "Item_Thing"]) == {"$parent": "Work/Other.gyml"}, "a table's own parent was changed")
    try:
        seed.pickup_pack("Item_Other", packed, seed.sarc_write(base))
        check(False, "a pack without the item's actor was taken")
    except ValueError:
        pass

    # ---- the size table: an actor's pack, and the files changed inside one ----
    paths = ["Pack/Actor/Item_Thing.pack", POUCH % "Thing", TABLE % "Item_Thing", "Untouched.bgyml"]
    rows = sorted((zlib.crc32(p.encode()) & 0xffffffff, 1000 + 8 * k) for k, p in enumerate(paths))
    tbl = b"RESTBL" + bytes(8) + struct.pack("<II", len(rows), 0) + b"".join(struct.pack("<II", *r) for r in rows)

    def entry(t, path):
        crc = zlib.crc32(path.encode()) & 0xffffffff
        return next(struct.unpack_from("<I", t, 26 + 8 * k)[0] for k in range(len(rows))
                    if struct.unpack_from("<I", t, 22 + 8 * k)[0] == crc)

    check(seed.size_entry(5000, seed.PACK_EXTRA) == 5024 + 312, "an actor pack's entry is its size rounded up to 32, and 312")
    grown = seed.size_table_update(tbl, {paths[0]: 5000}, seed.PACK_EXTRA)
    check(entry(grown, paths[0]) == 5336 and entry(grown, paths[3]) == entry(tbl, paths[3]), "the pack's entry was not raised to fit")
    raised = seed.size_table_raise(grown, [paths[1], paths[2], paths[1], "NotInTheTable.bgyml"])
    check(len(raised) == len(tbl), "the size table changed its size")
    for p in paths[1:3]:
        check(entry(raised, p) == entry(tbl, p) + seed.PART_GROWTH, "a changed file's entry was not raised once by PART_GROWTH")
    check(entry(raised, paths[3]) == entry(tbl, paths[3]) and entry(raised, paths[0]) == 5336, "an entry not asked for changed")
    # (an entry for a file the table does not have: in its place among the sorted CRC32s, the count raised, the rest as it was)
    tail = b"the names' table, after the entries"
    added = seed.size_table_add(tbl + tail, ["A/New/File.bgyml", paths[1], "A/New/File.bgyml", "Another.bgyml"])
    n = struct.unpack_from("<I", added, 14)[0]
    crcs = [struct.unpack_from("<I", added, 22 + 8 * k)[0] for k in range(n)]
    check(n == len(rows) + 2 and crcs == sorted(crcs) and len(set(crcs)) == n, "the new entries are not in their places, once each")
    check(added[:14] == tbl[:14] and added[18:22] == tbl[18:22] and added.endswith(tail) and len(added) == len(tbl) + len(tail) + 16,
          "adding an entry changed the header, or what follows the entries")
    for path in ("A/New/File.bgyml", "Another.bgyml"):
        k = crcs.index(zlib.crc32(path.encode()) & 0xffffffff)
        check(struct.unpack_from("<I", added, 26 + 8 * k)[0] == seed.PART_NEW, "a new entry does not have the size given")
    for path in paths:
        k = crcs.index(zlib.crc32(path.encode()) & 0xffffffff)
        check(struct.unpack_from("<I", added, 26 + 8 * k)[0] == entry(tbl, path), "an entry the table had was changed by adding another")
    check(seed.size_table_add(tbl, [paths[0]]) == tbl, "a path the table has was added again")
    print("PASS: an item made a pick-up")


if __name__ == "__main__":
    main()
