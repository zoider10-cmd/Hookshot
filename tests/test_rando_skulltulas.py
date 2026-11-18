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

    # ---- gating items to the Skulltulas, where the rules still let the game be finished ----
    P = sorted(seed.PROGRESSION)
    chests = collections.OrderedDict((k, P[k] if k < len(P) else "TBox_Rupee_Red") for k in range(40))
    needs = {k: frozenset() for k in chests}
    skulls = [2000 + k for k in range(30)]
    easy = {h: frozenset() for h in skulls}
    moved_all = 0
    for n in range(40):
        gives2, drops2, spheres, moved = seed.gate_skulltulas(random.Random("g%d" % n), chests, {2000: "Item_ScrubBusinessSeed"}, skulls, needs, easy, [])
        check(moved == sum(1 for i in gives2.values() if i == seed.TOKEN) == len(drops2) - 1, "a chest gives the token for each gating item moved")
        check(drops2[2000] == "Item_ScrubBusinessSeed" and all(i in seed.PROGRESSION for h, i in drops2.items() if h != 2000),
              "a Skulltula that drops a chest's item already was given another, or what is no gating item")
        check(collections.Counter(i for i in list(gives2.values()) + list(drops2.values()) if i != seed.TOKEN) ==
              collections.Counter(list(chests.values()) + ["Item_ScrubBusinessSeed"]), "moving a gating item lost or made an item")
        check({i for sphere in spheres for i in sphere} == seed.PROGRESSION, "the spheres after the move do not have every gating item")
        check(seed.gate_skulltulas(random.Random("g%d" % n), chests, {2000: "Item_ScrubBusinessSeed"}, skulls, needs, easy, []) ==
              (gives2, drops2, spheres, moved), "the same seed is not the same move")
        moved_all += moved
    check(40 * 13 * 0.15 < moved_all < 40 * 13 * 0.6, "about the share asked for is moved (%d of %d)" % (moved_all, 40 * 13))
    # (a Skulltula that asks for the item itself, or for what cannot be had before it: never given it)
    hard = {h: seed.PROGRESSION for h in skulls}
    for n in range(20):
        gives2, drops2, spheres, moved = seed.gate_skulltulas(random.Random("h%d" % n), chests, {}, skulls, needs, hard, [], share=1.0)
        check(moved == 0 and gives2 == dict(chests) and not drops2, "a gating item went to a Skulltula that asks for it")
    # (one that asks for the sword: everything but the sword can go there, and what the rules say is still finishable)
    sword = {h: frozenset((seed.S,)) for h in skulls}
    gives2, drops2, spheres, moved = seed.gate_skulltulas(random.Random("s"), chests, {}, skulls, needs, sword, [], share=1.0)
    check(moved == 12 and seed.S not in drops2.values() and spheres[0] == [seed.S], "with the sword asked for, the sword stays and the rest go")
    check(seed.gate_skulltulas(random.Random("s"), chests, {}, [], needs, sword, [], share=1.0)[3] == 0, "no Skulltula: nothing moves")
    # (what a Skulltula asks for: too much where it is not known better, and what is written for it where it is)
    check(seed.skulltula_rule(1, "InsideTheDekuTree") >= seed.rule("InsideTheDekuTree", "") | seed.SKULLTULA_ASKS and
          seed.skulltula_rule(1, "NoSuchArea") == seed.PROGRESSION, "a Skulltula asks for less than its area and a Skulltula's place can")
    seed.SKULLTULA_RULES[1] = frozenset((seed.BM,))
    check(seed.skulltula_rule(1, "InsideTheDekuTree") == frozenset((seed.BM,)), "a Skulltula known by its hash does not ask for what is written")
    del seed.SKULLTULA_RULES[1]

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
    placement_12()
    print("PASS: the Gold Skulltulas")


def placement_12():
    """bug 67: the Skulltulas and the pieces lying in the world take part as chests do, and the Skulltula house's rewards
    ask for their tokens, counted"""
    T, HEART = seed.TOKEN, seed.HEART
    # ---- what a Skulltula and a piece may hold ----
    gating = seed.PROGRESSION | seed.QUEST_GATES | seed.TUNICS | seed.SHOP_GATES | seed.SONG_GATES
    for item in ("TBox_Rupee_Green", "TBox_Rupee_Gold", HEART, "Item_Dungeon_SmallKey", "Item_Dungeon_Map", "Item_Melody_SunSong", seed.ZL,
                 "Item_Bottle", seed.SSC, "Item_Scale_Gold", "Item_Wallet_Medium", seed.GT, seed.ZT, "Obj_Heart_Container"):
        check(not seed.skulltula_holds(item, gating), "a Skulltula may drop %s" % item)
    for item in [T, seed.HAM, seed.BM, seed.BB, "Item_AgonyStone"] + list(seed.SKULLTULA_ITEMS):
        check(seed.skulltula_holds(item, gating), "a Skulltula may not drop %s" % item)
    check(not seed.skulltula_holds("Item_Something_Else", gating), "a Skulltula may drop what no list names")
    for item in ("Item_Dungeon_SmallKey", "Item_Dungeon_BossKey", "Item_Melody_SunSong", seed.ZL, seed.GT, "Item_Stone_Forest"):
        check(not seed.piece_holds(item), "a piece lying in the world may give %s" % item)
    for item in (T, HEART, "TBox_Rupee_Red", seed.HAM, "Item_Bottle", "Item_Wallet_Large", "Item_BombchuBundle_Small"):
        check(seed.piece_holds(item), "a piece lying in the world may not give %s" % item)

    # ---- counted tokens: collect and reach ----
    ten = [(seed.NONE, T)] * 9
    late = (frozenset({seed.tokens(10)}), seed.HAM)
    check(seed.collect(ten + [late]) == [] and seed.collect(ten + [(seed.NONE, T), late]) == [[seed.HAM]],
          "a rule that asks for 10 tokens is held with 9, or not with 10")
    check(seed.collect([(frozenset({seed.BOW}), T)] * 10 + [late, (seed.NONE, seed.BOW)]) == [[seed.BOW], [seed.HAM]],
          "the tokens behind an item are counted before it")
    check(seed.HAM not in seed.reach([], ten + [late]) and seed.HAM in seed.reach([T], ten + [late]) and
          seed.tokens(10) in seed.reach([T] * 10, []) and seed.tokens(20) not in seed.reach([T] * 10, []),
          "reach does not count the tokens held and those it gets")
    check(seed.collect([(seed.NONE, seed.HAM), (frozenset({seed.HAM}), seed.BOW)]) == [[seed.HAM], [seed.BOW]] and
          seed.reach({seed.HAM}, [(frozenset({seed.HAM}), seed.BOW)]) == {seed.HAM, seed.BOW}, "without tokens the spheres are not as before")
    either = seed.Either([{seed.tokens(10)}, {seed.BOW}])
    check(seed.collect(ten + [(seed.NONE, T), (either, seed.HAM)]) == [[seed.HAM]], "a way of a rule that asks for tokens is not held by them")
    check(seed.token_count(seed.tokens(40)) == 40 and seed.token_count(seed.HAM) is None and seed.token_codes(frozenset({seed.S, seed.tokens(30)})) == ["T30"],
          "the tokens' word is not read back, or not written for the tracker")
    line = seed.check_lines([], [], [("KakarikoVillage", (1.0, 2.0, 3.0), "CA", frozenset({seed.S, seed.SL, seed.tokens(20)}), "the Skulltula house: 20 tokens")])[1]
    check(line.split("|")[5] == "KS,SL,T20", "a house reward's rule is not written with its tokens: %r" % line)

    # ---- the house's rewards ----
    houses = {g.key: g for g in seed.GIFTS if g.key.startswith("skulltula_house_")}
    check(set(houses) == set(seed.HOUSE_TOKENS) == {"skulltula_house_%d" % n for n in (10, 20, 30, 40, 50)} and
          houses["skulltula_house_40"].olds == ("Item_BombchuBundle_Large",) and houses["skulltula_house_40"].flow == "GatheringTokenGold" and
          seed.GIFTS_FROM["skulltula_house_40"] == 12 and "skulltula_house_40" in seed.GIFT_PLACES and
          not any("100" in k for k in houses), "the house's rewards are not the five of 10 to 50 tokens, the 40's from placement 12")
    check(all(seed.house_need(k, seed.EVERYTHING, 11) == seed.EVERYTHING for k in houses) and
          all(seed.house_need(k, seed.EVERYTHING, 12) == seed.CHILD | {seed.tokens(n)} for k, n in seed.HOUSE_TOKENS.items()) and
          seed.house_need("darunia", seed.CHILD, 12) == seed.CHILD, "a house reward does not ask for its tokens from placement 12 only")

    # ---- place: the Skulltulas and the pieces as spots, what each may hold, the tokens placed by the logic ----
    P = sorted(seed.PROGRESSION)
    spots, needs, holds = collections.OrderedDict(), {}, {}
    for k in range(60):   # (chests: the gating items, rupees, supplies)
        spots[k] = ("A", P[k] if k < len(P) else "TBox_Rupee_Red" if k % 3 else "Item_ScrubBusinessSeed", False, None)
        needs[k] = seed.NONE
    skull_may = frozenset(i for i in set(s[1] for s in spots.values()) | {T, HEART} if seed.skulltula_holds(i, seed.PROGRESSION))
    for k in range(100, 140):   # (Skulltulas: their token; the last ten ask for the Megaton Hammer)
        spots[k] = ("A", T, None, None)
        needs[k] = frozenset({seed.HAM}) if k >= 130 else seed.NONE
        holds[k] = skull_may
    for k in range(200, 205):   # (pieces)
        spots[k] = ("A", HEART, None, None)
        needs[k] = seed.NONE
        holds[k] = frozenset(i for i in set(s[1] for s in spots.values()) if seed.piece_holds(i))
    for k, n in ((300, 10), (301, 30)):   # (rewards at 10 and 30 tokens)
        spots[k] = ("A", "TBox_Rupee_Red", None, None)
        needs[k] = frozenset({seed.tokens(n)})
    on_them = in_rewards = 0
    for n in range(40):
        gives, _, spheres = seed.place(random.Random("p%d" % n), spots, 3, 0, needs, holds=holds, counted=True)
        check(collections.Counter(gives.values()) == collections.Counter(s[1] for s in spots.values()), "the placement lost or made an item")
        check(all(gives[h] in holds[h] for h in holds), "a Skulltula or a piece was given what it may not hold")
        check(not any(gives[h].startswith("TBox_Rupee") or gives[h] == HEART for h in range(100, 140)), "a Skulltula drops a rupee or a piece")
        check({i for s in spheres for i in s} == seed.PROGRESSION, "a gating item cannot be got")
        on_them += sum(1 for h in list(range(100, 140)) + list(range(200, 205)) if gives[h] in seed.PROGRESSION)
        in_rewards += sum(1 for h in (300, 301) if gives[h] in seed.PROGRESSION)
        # (by this test's own count: every place is reached in the end, and a reward only with its tokens reached before it)
        places, have, done = [(needs[h], gives[h], h) for h in gives], set(), set()
        while True:
            now = [k for k, (need, _, _) in enumerate(places) if k not in done and seed.met(need, have)]
            if not now:
                break
            before = sum(1 for k in done if places[k][1] == T)
            check(all(before >= {300: 10, 301: 30}[places[k][2]] for k in now if places[k][2] in (300, 301)), "a reward reached before its tokens")
            done.update(now)
            have |= {places[k][1] for k in now} | seed.token_marks(sum(1 for k in done if places[k][1] == T))
        check(len(done) == len(places), "a place cannot be reached: %r" % [places[k] for k in range(len(places)) if k not in done][:3])
    check(on_them > 40 and in_rewards > 0, "the gating items do not go to the Skulltulas, the pieces and the house's rewards (%d, %d)" % (on_them, in_rewards))
    # (Skulltulas that keep their token, counted where they are: the setting off, or another's)
    chests_only = collections.OrderedDict((k, s) for k, s in spots.items() if k < 100 or k >= 300)
    kept = [(frozenset({seed.HAM}) if k < 25 else seed.NONE, T) for k in range(40)]
    for n in range(10):
        gives, _, spheres = seed.place(random.Random("f%d" % n), chests_only, 3, 0, {k: needs[k] for k in chests_only}, counted=True, fixed_more=kept)
        check({i for s in spheres for i in s} == seed.PROGRESSION, "with the tokens kept in place, a gating item cannot be got")
        if gives[301] in seed.PROGRESSION:   # (30 tokens: 15 free, the rest behind the Megaton Hammer)
            check([k for k, s in enumerate(spheres) if gives[301] in s][0] > [k for k, s in enumerate(spheres) if seed.HAM in s][0],
                  "the 30 tokens' reward gave its gating item before the Megaton Hammer opened the tokens behind it")
    # (a dungeon's keys go to its chests, not to its Skulltulas)
    keyed = collections.OrderedDict((k, ("Dungeon", "Item_Dungeon_SmallKey" if k < 5 else "TBox_Rupee_Red", True, None)) for k in range(20))
    keyed.update((k, ("Dungeon", T, None, None)) for k in range(100, 120))
    for n in range(10):
        gives, _, _ = seed.place(random.Random("k%d" % n), keyed, 3, 1, None, holds={k: skull_may for k in range(100, 120)})
        check(all(gives[k] != "Item_Dungeon_SmallKey" for k in range(100, 120)), "a dungeon's key went to one of its Skulltulas")
    # (no holds and no counting: as placement 11 placed)
    plain = collections.OrderedDict((k, s) for k, s in spots.items() if k < 100)
    check(seed.place(random.Random("same"), plain, 3, 0, {k: needs[k] for k in plain}) ==
          seed.place(random.Random("same"), plain, 3, 0, {k: needs[k] for k in plain}, holds=None, counted=False), "place is not the same without holds")

    # ---- the script ----
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check(seed.SHUFFLED_FROM == seed.HOUSE_FROM == 12 <= seed.PLACEMENT and "if placement >= SHUFFLED_FROM:" in script and
          "if placement < SHUFFLED_FROM:\n            gives, skull_drops = mix_skulltulas(" in script and
          "if logic and placement < SHUFFLED_FROM:" in script and "if a.heart_pieces and pieces and placement < SHUFFLED_FROM:" in script,
          "the Skulltulas and the pieces take part as chests do in a seed made before placement 12, or not from it")
    check("holds=holds or None, counted=counted, fixed_more=kept_tokens)" in script and
          "kept_tokens = [(skull_asks(h, every_skull[h][0]), TOKEN) for h in every_skull if h not in joined] if counted else []" in script and
          "gifts.update((h, g._replace(need=house_need(g.key, g.need, placement))) for h, g in list(gifts.items()) if g.key in HOUSE_TOKENS)" in script,
          "the placement is not given the Skulltulas' and the pieces' holds, the tokens kept in place, or the house's rules")
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
    check("constexpr const char* kTokenRow = \"Gold Skulltula Tokens\";" in menu and
          "if (n >= 2 && p[0] == 'T' && strspn(p + 1, \"0123456789\") >= n - 1) {" in menu and
          "item_counts[i].load(std::memory_order_relaxed) >= want" in menu and
          'OOT_ITEM("Gold Skulltula Tokens", "Item_Token_Gold", 1)' in (ROOT / "gpu" / "vk" / "oot_cheat_items.h").read_text(encoding="utf-8"),
          "the Tracker tab does not hold a rule's T<N> by the pouch's tokens")


if __name__ == "__main__":
    main()
