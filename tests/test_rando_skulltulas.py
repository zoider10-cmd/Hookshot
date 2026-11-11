"""The Gold Skulltulas setting (tools/rando/rando_seed.py) on made-up map files: no game data.

A map file is built as tests/test_rando_seed.py builds one, then checked: the Gold Skulltulas are found, a dungeon's
told from the overworld's and one that can be given a drop in place from one that cannot; a drop is written in place
where that can be done and the whole file anew where not, with every other actor as it was; the tokens and the
chests' rupees and supplies change places without one lost or made, the same for the same seed, and nothing else in
a chest moves; an item made from another item is made a pick-up at the right actor.

    python -I -B tests/test_rando_skulltulas.py
"""
import collections
import importlib.util
import random
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name, *parts):
    spec = importlib.util.spec_from_file_location(name, ROOT.joinpath(*parts))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed = load("rando_seed", "tools", "rando", "rando_seed.py")
maps = load("test_rando_seed", "tests", "test_rando_seed.py")      # (its build() and chest())
packs = load("test_rando_pickups", "tests", "test_rando_pickups.py")   # (its byml() and read())


def check(ok, what):
    if not ok:
        raise SystemExit("FAIL: " + what)


def skull(ident, dynamic=None, gyaml=seed.SKULLTULA):
    actor = {"Gyaml": gyaml, "Hash": 0x2000000000000000 + ident, "Translate": [float(ident), 5.0, 6.0]}
    if dynamic is not None:
        actor["Dynamic"] = dynamic
    return actor


def main():
    H = 0x2000000000000000
    actors = [maps.chest(1, "TBox_Rupee_Red"), maps.chest(2, "Item_Hammer"),
              skull(1, {"DefaultDungeonRoomIndex": 3}), skull(2, {"Enemy_Skulltula_Gold_Nocturnal": True}), skull(3),
              skull(4, {"DefaultDungeonRoomIndex": 3}, gyaml="Enemy_Skulltula_Gold_Dictionary"), {"Gyaml": "Obj_Tree_A_01", "Hash": 10}]
    data = maps.build({"Actors": actors, "FilePath": "x"})

    # ---- the Skulltulas of a file ----
    found = seed.skulltulas(data)
    check(found == [(H + 1, (1.0, 5.0, 6.0), True, True), (H + 2, (2.0, 5.0, 6.0), True, False), (H + 3, (3.0, 5.0, 6.0), False, False)],
          "a file's Gold Skulltulas: which they are, a dungeon's, one without a Dynamic block")
    bare = maps.build({"Actors": [skull(1, {"DefaultDungeonRoomIndex": 3}), {"Gyaml": "Obj_Tree_A_01", "Hash": 10}]})
    check(seed.skulltulas(bare) == [(H + 1, (1.0, 5.0, 6.0), False, True)], "a file without the drop's key: its Skulltula is not in place")

    # ---- a drop, in place and with the file written anew ----
    before = {c.hash: c.item for c in seed.chests(data)[0]}
    check(seed.add_drop(data, {}) is None and seed.add_drop(data, {0x77: "TBox_Rupee_Red"}) is None, "no drop for this file is not None")
    for drops, in_place in (({H + 1: "TBox_Rupee_Blue"}, True), ({H + 2: "TBox_DekuNutBundle", H + 1: "TBox_Rupee_Red"}, True),
                            ({H + 3: "TBox_Rupee_Blue"}, False), ({H + 3: "Item_ScrubBusinessSeed", H + 1: "TBox_Rupee_Gold"}, False)):
        if in_place:
            check(seed.add_drop_in_place(data, drops) == seed.add_drop(data, drops), "a drop that can be written in place was not")
        else:
            try:
                seed.add_drop_in_place(data, drops)
                check(False, "a Skulltula without a Dynamic block was written in place")
            except seed.NotInPlace:
                pass
        for anew in (False, True):
            new = seed.add_drop(data, drops, anew=anew)
            now = {c.hash: c.item for c in seed.chests(new)[0]}
            check(now == {**before, **drops}, "a drop: the Skulltula's, and every chest as it was (%r, anew %s)" % (drops, anew))
            check([(h, pos, dungeon) for h, pos, _, dungeon in seed.skulltulas(new)] == [(h, pos, dungeon) for h, pos, _, dungeon in found],
                  "a drop lost or moved a Skulltula")
            tree = packs.plain(seed.byml_parse(new)[0])
            check(len(tree["Actors"]) == len(actors) and tree["FilePath"] == "x" and tree["Actors"][-1] == {"Gyaml": "Obj_Tree_A_01", "Hash": 10},
                  "a drop changed what is not an actor's drop")
            kept = [a for a in tree["Actors"] if a.get("Gyaml") == seed.SKULLTULA and a["Hash"] == H + 2][0]["Dynamic"]
            check(kept.get("Enemy_Skulltula_Gold_Nocturnal") is True, "a Skulltula's own settings were lost")
    new = seed.add_drop(bare, {H + 1: "TBox_Rupee_Blue"})
    check({c.hash: c.item for c in seed.chests(new)[0]} == {H + 1: "TBox_Rupee_Blue"} and
          packs.plain(seed.byml_parse(new)[0])["Actors"][0]["Dynamic"] == {"DefaultDungeonRoomIndex": 3, "Drop__DropActor": "TBox_Rupee_Blue"},
          "a file without the drop's key: written anew with it")

    # ---- the tokens and the chests' rupees and supplies change places ----
    gives = collections.OrderedDict()
    kinds = list(seed.SKULLTULA_ITEMS) * 2 + list(seed.SKULLTULA_ITEMS_NOT_YET) + ["Item_Hammer", "Item_Dungeon_SmallKey", "Obj_Heart_Piece", "TBox_Shield_Deku", "Item_Hookshot"]
    for k in range(120):
        gives[k] = kinds[k % len(kinds)]
    skulls = [1000 + k for k in range(100)]
    tokens_in_chests = 0
    for n in range(30):
        new, drops = seed.mix_skulltulas(random.Random("t%d" % n), gives, skulls)
        check(list(new) == list(gives) and set(drops) <= set(skulls), "the chests and the Skulltulas are the ones given")
        check(all(new[h] == gives[h] for h in gives if gives[h] not in seed.SKULLTULA_ITEMS), "an item no Skulltula may have left its chest")
        check(all(i in seed.SKULLTULA_ITEMS for i in drops.values()), "a Skulltula was given what it may not have")
        tokens = sum(1 for i in new.values() if i == seed.TOKEN)
        check(tokens == len(drops), "as many chests hold a token as Skulltulas drop a chest's item")
        check(collections.Counter(i for i in list(new.values()) + list(drops.values()) if i != seed.TOKEN) == collections.Counter(gives.values()),
              "the mix lost or made an item")
        tokens_in_chests += tokens
        again = seed.mix_skulltulas(random.Random("t%d" % n), gives, skulls)
        check(again == (new, drops), "the same seed is not the same mix")
    check(tokens_in_chests > 30 * 10, "the mix moves few tokens into chests")
    check(seed.mix_skulltulas(random.Random("x"), gives, []) == (dict(gives), {}), "no Skulltula: nothing changes")
    check(not set(seed.SKULLTULA_ITEMS) & (set(seed.PROGRESSION) | set(seed.DUNGEON_ITEMS) | {"Obj_Heart_Piece"}),
          "a gating item, a dungeon's key or a Heart Piece may be given to a Skulltula")

    # ---- an item made from another item: the pick-up's parent goes to the one made from the chest's base ----
    actor, table_, pouch = packs.ACTOR, packs.TABLE, packs.POUCH
    chest_base = "Work/" + (actor % seed.CHEST_BASE).replace(".bgyml", ".gyml")
    item = collections.OrderedDict()
    item[actor % "TBox_Red"] = packs.byml({"$parent": "Work/" + (actor % "TBox_Green").replace(".bgyml", ".gyml"),
                                          "Components": {"PouchContentRef": "?" + pouch % "Red"}})
    item[actor % "TBox_Green"] = packs.byml({"$parent": chest_base, "Components": {"PouchContentRef": "?" + pouch % "Default"}})
    item[actor % seed.CHEST_BASE] = packs.byml({"Components": {"PouchContentRef": "?" + pouch % "None"}})
    item[pouch % "Red"] = packs.byml({"$parent": "Work/" + (pouch % "Default").replace(".bgyml", ".gyml"), "EnableStock": False})
    item[pouch % "Default"] = packs.byml({"DefaultAutoGet": True})
    _, base = packs.packs()
    check(seed.pickup_family("TBox_Red", seed.sarc_write(item)) == ["TBox_Red", "TBox_Green"], "the items an item is made from")
    new = seed.sarc_read(seed.pickup_pack("TBox_Red", seed.sarc_write(item), seed.sarc_write(base)))
    check(new[actor % "TBox_Red"] == item[actor % "TBox_Red"], "an item made from another: its own actor changed")
    check(packs.read(new[actor % "TBox_Green"])["$parent"] == "Work/" + (actor % seed.PICKUP_BASE).replace(".bgyml", ".gyml"),
          "an item made from another: the one made from the chest's base does not take the pick-up's")
    check(new[pouch % "Red"] == item[pouch % "Red"] and new[pouch % "Default"] == item[pouch % "Default"],
          "what is got by touching it already, by its parent, was changed")
    item[pouch % "Default"] = packs.byml({"DefaultAutoGet": False})
    new = seed.sarc_read(seed.pickup_pack("TBox_Red", seed.sarc_write(item), seed.sarc_write(base)))
    check(packs.read(new[pouch % "Red"]).get("DefaultAutoGet") is True and new[pouch % "Default"] == item[pouch % "Default"],
          "what is not got by touching it: the item's own file says so now, not its parent's")
    check(not set(seed.SKULLTULA_ITEMS) & set(seed.SKULLTULA_ITEMS_NOT_YET), "an item kept from the Skulltulas is given to them")
    stray = collections.OrderedDict([(actor % "Obj_Thing", packs.byml({"$parent": "Work/Actor/Other.engine__actor__ActorParam.gyml"}))])
    try:
        seed.pickup_pack("Obj_Thing", seed.sarc_write(stray), seed.sarc_write(base))
        check(False, "an actor that is no chest's item was made a pick-up")
    except ValueError:
        pass
    print("PASS: the Gold Skulltulas")


if __name__ == "__main__":
    main()
