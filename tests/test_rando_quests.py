"""Quest rewards: what characters give takes part with the chests (tools/rando/rando_seed.py: GIFTS, gift_items,
quest_need).

Checked here, without the game:
- the table of gifts: each has a key, a hash and a name of its own; the item it puts in the pool is one its flow
  names for it; no item of a flow is two gifts' (each is told from the others by its item); the frogs and the Light
  Arrows wait for their own settings and the others do not;
- two gifts of one flow that change places (gift_items): each call gives the other's item, where changing one after
  the other would give both the same;
- the rules with the gifts' gating items (quest_need): the bracelet wherever bombs are and in Dodongo's Cavern, the
  Silver Scale wherever an adult is, nothing where neither is; a gift's own rule names them where it has to;
- a gift among the chests (place): it takes part whichever chests the Chests setting names, and the logic places the
  two new gating items so that both can be got;
- a gating item that may never go to a Gold Skulltula does not (gate_skulltulas: never), and the others' order is
  as it was without it;
- the tracker counts gifts; the script reads the three settings, names them in the seed's stamp and writes the
  changed flows with the seed.

    python -I -B tests/test_rando_quests.py
"""
import collections
import importlib.util
import random
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name, *path):
    spec = importlib.util.spec_from_file_location(name, ROOT.joinpath(*path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed = load("rando_seed", "tools", "rando", "rando_seed.py")
flows = load("test_rando_gifts", "tests", "test_rando_gifts.py")   # (its made-up flow)


def check(ok, what):
    if not ok:
        raise SystemExit("FAIL: " + what)


def given(data, pointer):
    at = struct.unpack_from("<Q", data, pointer)[0]
    return data[at + 2:at + 2 + struct.unpack_from("<H", data, at)[0]].decode()


def main():
    # ---- the table ----
    keys = [g.key for g in seed.GIFTS]
    check(len(set(keys)) == len(keys) and len({seed.gift_hash(k) for k in keys}) == len(keys) and len({g.name for g in seed.GIFTS}) == len(keys),
          "two gifts have the same key, hash or name")
    check(all(seed.gift_hash(k) >> 48 == 0xF1F7 for k in keys), "a gift's hash is not kept apart from the chests'")
    for g in seed.GIFTS:
        check(g.item in g.olds and g.olds, "%s puts %s in the pool, which its flow does not name for it" % (g.key, g.item))
        check(isinstance(g.need, frozenset) and g.need <= seed.PROGRESSION | seed.QUEST_GATES, "%s asks for something that is no gating item" % g.key)
        check(not (seed.BB in g.need and seed.BR not in g.need), "%s asks for bombs without the bracelet" % g.key)
        check(not (g.need >= seed.ADULT and seed.SSC not in g.need), "%s is an adult's and does not ask for the Silver Scale" % g.key)
    by_flow = collections.Counter((g.flow, old) for g in seed.GIFTS for old in g.olds)
    check(max(by_flow.values()) == 1, "an item of one flow is two gifts': %r" % [k for k, n in by_flow.items() if n > 1])
    check({g.key: g.when for g in seed.GIFTS if g.when} == {"frogs": "frogs", "light_arrows": "light"},
          "the frogs and the Light Arrows do not wait for their own settings, or another gift does")
    check(next(g for g in seed.GIFTS if g.key == "darunia").item == seed.BR and next(g for g in seed.GIFTS if g.key == "diving").item == seed.SSC,
          "the two gating gifts are not the bracelet and the Silver Scale")
    pool = collections.Counter(g.item for g in seed.GIFTS)
    for sizes in (("Item_BulletBag_Medium", "Item_BulletBag_Large"), ("Item_Quiver_Medium", "Item_Quiver_Large"), ("Item_BombBag_Medium", "Item_BombBag_Large")):
        check(all(pool[i] == 1 for i in sizes), "a prize of two sizes does not put one of each in the pool: %r" % (sizes,))

    # ---- two gifts of one flow that change places ----
    data, pointers = flows.flow([(4, [(5, "Item_Quiver_Medium")]), (4, [(5, "Item_Quiver_Large")]), (4, [(5, "Obj_Heart_Piece")]),
                                 (4, [(5, "Item_Other")]), (0, [(5, "Obj_Heart_Piece")])])
    new, found = seed.gift_items(data, {"Item_Quiver_Medium": "Obj_Heart_Piece", "Item_Quiver_Large": "Obj_Heart_Piece", "Obj_Heart_Piece": "Item_Quiver_Medium"})
    check(found == {"Item_Quiver_Medium", "Item_Quiver_Large", "Obj_Heart_Piece"}, "a gift's item was not found: %r" % found)
    check([given(new, pointers[(k, 0)]) for k in range(5)] == ["Obj_Heart_Piece", "Obj_Heart_Piece", "Item_Quiver_Medium", "Item_Other", "Obj_Heart_Piece"],
          "two gifts of one flow did not change places: %r" % [given(new, pointers[(k, 0)]) for k in range(5)])
    check(struct.unpack_from("<I", new, 0x1c)[0] == len(new) and len(new) % 8 == 0 and new.count(b"Item_Quiver_Medium\0") == 2,
          "the new names are not each once at the file's end, or its size is not its header's")
    check(seed.gift_items(data, {"Item_NoSuch": "Obj_Heart_Piece"}) == (None, set()), "a flow without the item was changed")
    _, found = seed.gift_items(data, {"Item_Other": "X", "Item_NoSuch": "Y"})
    check(found == {"Item_Other"}, "an item the flow has not is said to be found")
    check(seed.gift_item(data, "Item_Other", "Item_Bow") == seed.gift_items(data, {"Item_Other": "Item_Bow"})[0], "one gift changed is not the same as a set of one")

    # ---- the rules ----
    check(seed.quest_need(seed.CHILD, "KokiriForest") == seed.CHILD, "a child's chest without bombs asks for more")
    check(seed.quest_need(seed.CHILD | {seed.BB}, "ZoraRiver") == seed.CHILD | {seed.BB, seed.BR}, "bombs do not ask for the bracelet")
    check(seed.quest_need(seed.CHILD, "DodongoCavern") == seed.CHILD | {seed.BR}, "Dodongo's Cavern does not ask for the bracelet")
    check(seed.quest_need(seed.ADULT | {seed.HAM}, "GoronCity") == seed.ADULT | {seed.HAM, seed.BR, seed.SSC}, "an adult's chest does not ask for both")
    check(seed.quest_need(seed.PROGRESSION, "Nowhere") == seed.PROGRESSION | seed.QUEST_GATES, "a chest that asks for everything does not ask for the two")

    # ---- a gift among the chests ----
    old = seed.PROGRESSION
    seed.PROGRESSION = old | seed.QUEST_GATES
    try:
        spots = collections.OrderedDict()
        for k in range(12):
            spots[k] = ("KokiriForest", "TBox_Rupee_Green", False, None)
        for k in range(12, 20):
            spots[k] = ("FireTemple", "TBox_Rupee_Blue", True, None)
        spots[100], spots[101] = ("GoronCity", seed.BR, None, None), ("ZoraDomain", seed.SSC, None, None)
        needs = {k: seed.NONE for k in range(12)}
        needs.update({k: seed.quest_need(seed.ADULT, "FireTemple") for k in range(12, 20)})
        needs[100], needs[101] = seed.NONE, frozenset((seed.BR,))
        for which in (1, 2, 3):
            gives, stays, spheres = seed.place(random.Random(which), spots, which, 0, needs)
            check(100 in gives and 101 in gives, "a gift does not take part with Chests on %d" % which)
            check(collections.Counter(gives.values()) == collections.Counter(spots[h][1] for h in gives), "the shuffle lost or made an item")
            check({i for sphere in spheres for i in sphere} == set(seed.QUEST_GATES), "the two new gating items are not both got: %r" % spheres)
            where = {i: h for h, i in gives.items()}
            check(needs[where[seed.BR]] == seed.NONE, "the bracelet is behind a spot that asks for it or for the scale")
        # ---- never to a Skulltula ----
        gives = {1: seed.BR, 2: seed.SSC, 3: "TBox_Rupee_Green"}
        needs2, skull_needs = {1: seed.NONE, 2: seed.NONE, 3: seed.NONE}, {50: seed.NONE, 51: seed.NONE}
        for trial in range(20):
            g2, drops, spheres, moved = seed.gate_skulltulas(random.Random(trial), gives, {}, [50, 51], needs2, skull_needs, [], share=1.0, never=(seed.SSC,))
            check(seed.SSC not in drops.values() and g2[2] == seed.SSC and seed.BR in drops.values() and g2[1] == seed.TOKEN and moved == 1,
                  "a gating item that may never go to a Skulltula went, or the other did not: %r" % drops)
        a = seed.gate_skulltulas(random.Random(7), {1: seed.BR, 3: seed.S}, {}, [50, 51], {1: seed.NONE, 3: seed.NONE}, skull_needs, [], share=0.5)
        b = seed.gate_skulltulas(random.Random(7), {1: seed.BR, 3: seed.S}, {}, [50, 51], {1: seed.NONE, 3: seed.NONE}, skull_needs, [], share=0.5, never=())
        check(a == b, "the Skulltulas' gating items are not as they were when none is kept from them")
    finally:
        seed.PROGRESSION = old

    # ---- the tracker ----
    lines = seed.tracker_lines({"KokiriForest": 2}, {"KokiriForest": 1}, {"KokiriForest": 1, "Market": 3})
    check("The whole game|2 chests, 1 Gold Skulltula, 4 gifts" in lines and "Kokiri Forest|2 chests, 1 Gold Skulltula, 1 gift" in lines and "Market|3 gifts" in lines,
          "the tracker does not count the gifts: %r" % lines)
    check(seed.tracker_lines({"KokiriForest": 2}, {}) == seed.tracker_lines({"KokiriForest": 2}, {}, {}), "the tracker without gifts is not as it was")

    # ---- the script ----
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check(all('"%s": 0' % key in script for key in ("rando_quests", "rando_frogs", "rando_light_arrows")), "the script does not read the three settings")
    check('(" quests 1%s%s" % (" frogs" * a.frogs, " light" * a.light_arrows) if a.quests else "")' in script,
          "the seed's stamp does not name Quest rewards and its two settings (a seed made without them would not be made again)")
    check("a.frogs = a.quests and" in script and "a.light_arrows = a.quests and" in script, "the frogs or the Light Arrows take part without Quest rewards")
    check("gift_items(unpack(" in script and "gift_sizes, FLOW_EXTRA)" in script and "list(gift_files.items())" in script,
          "a changed flow is not written with the seed, or its size table entry is not raised")
    check("if set(change) - found:" in script, "a gift whose item its flow no longer names is passed over in silence")
    print("PASS: Quest rewards")


if __name__ == "__main__":
    main()
