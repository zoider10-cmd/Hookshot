"""Magic and the fairies' gifts (rando_magic; tools/rando/rando_seed.py MAGIC_GIFTS, magic_free, custom_pack, custom_rows;
host/hos_main.c oot_magic_give; asked for 2026-11-19): no game data. Seen without a window 2026-11-19: a save with no
meter given the doubled magic's gift twice had the meter 0 -> 240 ("Magic Power"), then the gift; the Lens of Truth and
Din's Fire gave no meter; a chest showed "You got magic power!"; a shop's shelf with it said the gift's words, so magic
is kept off shelves.

    python -I -B tests/test_rando_magic.py
"""
import collections
import importlib.util
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rando_seed", ROOT / "tools" / "rando" / "rando_seed.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


def check(ok, why):
    if not ok:
        print("FAIL: %s" % why)
        sys.exit(1)


def row(name, **fields):
    r = collections.OrderedDict([("__RowId", ("string", name))])
    for k, v in fields.items():
        r[k] = ("string", v) if isinstance(v, str) else (0xD1, struct.pack("<i", v))
    return ("dict", r)


def main():
    S = seed
    table = S.byml_build(("array", [row("Item_GlassTruth", ExpansionAvility="MPMaxUP", MPMax=24),
                                    row("Item_FairyBless_MPDouble", ExpansionAvility="MPMaxUP", MPMax=48),
                                    row("Item_Hammer", PouchCategory="Item")]), 7)
    new, done = S.magic_free(table)
    rows = {r[1]["__RowId"][1]: r[1] for r in S.byml_parse(new)[0][1]}
    check(done == 1 and "MPMax" not in rows["Item_GlassTruth"] and "ExpansionAvility" not in rows["Item_GlassTruth"] and
          rows["Item_FairyBless_MPDouble"]["MPMax"][1] == struct.pack("<i", 48), "magic_free does not take the mark out of all but the doubled magic")
    made = S.custom_rows(table, "ActorInfo", S.MAGIC_ITEM, "Item_FairyBless_MPDouble", {"ActorName": ("string", S.MAGIC_ITEM), "MPMax": None})
    rows = {r[1]["__RowId"][1]: r[1] for r in S.byml_parse(made)[0][1]}
    check(S.MAGIC_ITEM in rows and rows[S.MAGIC_ITEM]["ActorName"][1] == S.MAGIC_ITEM and "MPMax" not in rows[S.MAGIC_ITEM] and
          rows[S.MAGIC_ITEM]["ExpansionAvility"][1] == "MPMaxUP" and list(rows) == sorted(rows),
          "custom_rows does not make the parent's row under the item's own name, sorted")
    pack = S.sarc_write(collections.OrderedDict([(S.ACTOR_FILE % "Item_FairyBless_MPDouble", S.byml_build(("dict", collections.OrderedDict()), 7))]))
    new, parts = S.custom_pack(S.MAGIC_ITEM, "Item_FairyBless_MPDouble", pack)
    actor = S.byml_parse(S.sarc_read(new)[S.ACTOR_FILE % S.MAGIC_ITEM])[0][1]
    check(parts == [S.ACTOR_FILE % S.MAGIC_ITEM] and actor["$parent"][1] == S.ACTOR_REF % "Item_FairyBless_MPDouble",
          "custom_pack does not make an actor with the parent as its $parent")
    check(S.magic_need(frozenset((S.LENS,))) == frozenset((S.LENS, S.MAGIC_DOUBLE)) and S.magic_need(frozenset((S.BOW,))) == frozenset((S.BOW,)),
          "the rules do not ask for magic where they ask for the Lens")
    check({g.key for g in S.MAGIC_GIFTS} == {"fairy_power", "fairy_wisdom", "fairy_courage"} and
          all(k in S.GIFT_PLACES and S.ZL in S.SONG_GIFTS[k] for k in ("fairy_power", "fairy_wisdom", "fairy_courage")),
          "the other three fountains are not gifts with a place and the Lullaby")
    check(S.CHECK_CODES.get(S.MAGIC_DOUBLE) == "MG", "the Tracker has no letters for magic")
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check('a.magic = ini["rando_magic"] == 1 and a.quests' in script and '(" magic 1" if a.magic else "")' in script and
          "for h in [h for h in shelves if gives.get(h) == MAGIC_DOUBLE]:" in script, "the setting is not read, stamped, or kept off shelves")
    host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    check("#define OOT_MAGIC_FIRST 240" in host and "return most < OOT_MAGIC_FIRST ? OOT_MAGIC_ITEM : NULL;" in host and
          "if (oot_magic_family(name)) return oot_magic_give(c, name);" in host, "the game's side does not give the meter first")
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
    items = (ROOT / "gpu" / "vk" / "oot_cheat_items.h").read_text(encoding="utf-8")
    check('{"MG", "magic", {"Magic Power", "Double Magic"}},' in menu and 'OOT_ITEM("Magic Power", "Item_MagicMeter", 0)' in items,
          "the Tracker cannot see magic")
    print("PASS: magic and the fairies' gifts")


if __name__ == "__main__":
    main()
