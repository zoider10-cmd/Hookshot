"""The randomizer's Heart Pieces setting: no game data.

The Pieces of Heart lying in the world take part (tools/rando/rando_seed.py HEART). A gating item can lie where a
piece lay: the map's actor is given the item's name, the item is made a pick-up from the piece itself (so one taken
stays taken: made from the token it was there again each time the map was entered, seen without a window), and the
chest the item left gives the Piece of Heart.

- a map file: the pieces lying in it are found, both kinds; an actor is given another name and reads back so, the
  others and the chests as they were; nothing to change is None;
- the rules: a piece asks for its area's rule, the one of Lon Lon Ranch for what a child out of the forest has;
- the placing: the chest a gating item leaves for a piece gives the piece, not a token;
- the script reads the setting, names it in the seed's stamp, makes what lies there from the piece and what a
  Skulltula drops from the token, and writes the pieces with the checks.

    python -I -B tests/test_rando_hearts.py
"""
import collections
import importlib.util
import random
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


def actor(h, gyaml, pos, drop=None):
    a = collections.OrderedDict()
    if drop:
        a["Dynamic"] = ("dict", collections.OrderedDict((("Drop__DropActor", ("string", drop)),)))
    a["Gyaml"] = ("string", gyaml)
    a["Hash"] = (0xD5, struct.pack("<Q", h))
    a["Translate"] = ("array", [(0xD2, struct.pack("<f", v)) for v in pos])
    return ("dict", a)


def main():
    S = seed
    data = S.byml_build(("dict", collections.OrderedDict((("Actors", ("array", [
        actor(0x11, "Obj_Heart_Piece", (1.0, 2.0, 3.0)), actor(0x12, "Obj_GerudoValley_Heart_Piece", (4.0, 5.0, 6.0)),
        actor(0x13, "Obj_TBox_A_01", (7.0, 8.0, 9.0), "TBox_Rupee_Blue"), actor(0x14, "Obj_Heart", (0.0, 0.0, 0.0))])),))), 7)
    # ---- a map file ----
    check(S.hearts(data) == [(0x11, (1.0, 2.0, 3.0)), (0x12, (4.0, 5.0, 6.0))], "the pieces lying in a map file are not found, both kinds, or a heart is taken for one: %r" % S.hearts(data))
    new = S.regyaml(data, {0x11: "Item_Hammer", 0x12: "Item_Hammer", 0x99: "Item_Longshot"})
    check(new is not None and S.hearts(new) == [], "an actor given another name is still a piece")
    names = {h: gyaml for h, gyaml, _, _, _ in S.marks(new)}
    tree = S.byml_parse(new)[0][1]["Actors"][1]
    got = [(int.from_bytes(a[1]["Hash"][1], "little"), a[1]["Gyaml"][1]) for a in tree]
    check(got == [(0x11, "Item_Hammer"), (0x12, "Item_Hammer"), (0x13, "Obj_TBox_A_01"), (0x14, "Obj_Heart")],
          "the actors do not read back with their new names, the others as they were: %r" % got)
    check([(c.hash, c.item) for c in S.chests(new)[0]] == [(0x13, "TBox_Rupee_Blue")] and names.get(0x13) == "Obj_TBox_A_01", "a chest changed with it")
    check(S.regyaml(data, {0x99: "Item_Hammer"}) is None and S.regyaml(data, {0x11: "Obj_Heart_Piece"}) is None and S.regyaml(new, {0x11: "Item_Hammer"}) is None,
          "a file with nothing to change is written")
    # ---- the rules ----
    check(S.heart_rule(0x88358af5b5300aa9, "HyruleField") == S.CHILD and S.heart_rule(0x1, "HyruleField") == S.rule("HyruleField", "") and
          S.heart_rule(0x1, "DesertColossus") >= S.DESERT and S.heart_rule(0x1, "NoSuchArea") == S.PROGRESSION,
          "a piece does not ask for its area's rule, or Lon Lon Ranch's for more than a child out of the forest has")
    # ---- the placing: the chest left gives the piece ----
    gives = {1: S.HAM, 2: "TBox_Rupee_Blue"}
    needs = {1: S.NONE, 2: S.NONE}
    out, drops, spheres, moved = S.gate_skulltulas(random.Random(1), gives, {}, [0x11], needs, {0x11: S.NONE}, [], share=1.0, token=S.HEART)
    check(moved == 1 and drops == {0x11: S.HAM} and out == {1: S.HEART, 2: "TBox_Rupee_Blue"} and [S.HAM] in spheres,
          "a gating item is not moved to a piece's place with the chest it left giving the piece: %r %r" % (out, drops))
    out, drops, _, _ = S.gate_skulltulas(random.Random(1), gives, {}, [0x11], needs, {0x11: S.NONE}, [], share=1.0)
    check(out[1] == S.TOKEN, "a Skulltula's chest no longer gives a token")
    # ---- the script ----
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check('"rando_heart_pieces": 0' in script and '(" hearts 1" if a.heart_pieces else "")' in script and
          'a.heart_pieces = a.heart_pieces or ini["rando_heart_pieces"] != 0' in script,
          "the script does not read the setting, or does not name it in the seed's stamp")
    check("new = pickup_pack(item, old, pack(HEART), base_name=HEART, effects_name=None, each_time=item not in PROGRESSION)" in script and
          "new = pickup_pack(item, old, base, each_time=item not in PROGRESSION)" in script and "lying_items = set(heart_drops.values())" in script,
          "what lies where a piece lay is not made from the piece (made from the token it is there again each time), or a Skulltula's drop is")
    check("{h: heart_asks(h) for h in pieces}, fixed, token=HEART," in script and
          "(skull_asks(h), item) for h, item in skull_drops.items() if item in PROGRESSION]" in script and
          "named_anew = regyaml(new if new is not None else data, heart_drops) if heart_drops else None" in script,
          "the pieces are not placed by the rules with the Skulltulas' gating items counted, or the map files are not changed")
    check('named("Piece of Heart", h, pieces[h][0], pieces[h][1]), h,' in script and "heart_drops.get(h, HEART)) for h in pieces]," in script,
          "the pieces are not written with the checks")
    header = (ROOT / "gpu" / "vk" / "oot_rando.h").read_text(encoding="utf-8")
    check('X(HEART_PIECES, "Heart Pieces", "rando_heart_pieces", \\' in header and "With Major items: the 14 Pieces of Heart lying in the world take part." in header,
          "the setting's row does not say what it does")
    print("PASS: Heart Pieces")


if __name__ == "__main__":
    main()
