"""The randomizer's Heart Pieces setting: no game data.

The Pieces of Heart lying in the world take part (tools/rando/rando_seed.py HEART). A piece can be a gating item: the
map is left as it is, so the piece is taken once and stays taken; its check's line says what it gives, and the game's
side puts that item in the pouch in the piece's place (host/hos_main.c oot_piece_gives). The chest the item left
gives the Piece of Heart. (The item itself lying there was there again each time its map was entered: seen in play.)

- a map file: the pieces lying in it are found, both kinds;
- the rules: a piece asks for its area's rule, the one of Lon Lon Ranch for what a child out of the forest has;
- the placing: the chest a gating item leaves for a piece gives the piece, not a token;
- the script reads the setting, names it in the seed's stamp, leaves the map files and the pick-ups alone, and
  writes the pieces with the checks;
- the game's side: a Piece of Heart entering the pouch near such a check, not from an event's action, is made the
  check's item before the tracker's record and Progressive items see it.

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
    check('"rando_heart_pieces": 0' in script and '(" hearts 2" if a.heart_pieces else "")' in script and
          'a.heart_pieces = a.heart_pieces or ini["rando_heart_pieces"] != 0' in script,
          "the script does not read the setting, or does not name it in the seed's stamp")
    check("regyaml" not in script and "pack(HEART)" not in script and "set(heart_drops.values())" not in script,
          "the item is put in the map or made a pick-up again: lying there it was there again each time its map was entered")
    check("{h: heart_asks(h) for h in pieces}, fixed, token=HEART," in script and
          "(skull_asks(h), item) for h, item in skull_drops.items() if item in PROGRESSION]" in script,
          "the pieces are not placed by the rules with the Skulltulas' gating items counted")
    check('named("Piece of Heart", h, pieces[h][0], pieces[h][1]), h,' in script and "heart_drops.get(h, HEART)) for h in pieces]," in script,
          "the pieces are not written with the checks")
    header = (ROOT / "gpu" / "vk" / "oot_rando.h").read_text(encoding="utf-8")
    check('X(HEART_PIECES, "Heart Pieces", "rando_heart_pieces", \\' in header and "With Major items: the 14 Pieces of Heart lying in the world take part. A piece can be a key item: it still looks like a Piece of Heart" in header,
          "the setting's row does not say what it does")
    host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    check('oot_checks[oot_check_count].piece = got >= 9 && !strncmp(kind, "Piece of Heart", 14) ? strtoull(hash, NULL, 16) : 0;' in host and
          'named("Piece of Heart", h,' in script, "the game's side does not know which checks are pieces lying in the world")
    block = host[host.index("int hos_oot_pouch_add(Ctx *c) {"):]
    check('(!strcmp(name, OOT_PIECE) || !strcmp(name, "Obj_GerudoValley_Heart_Piece")) && c->x[30] != 0x828d50acULL &&' in block and
          "view = oot_pouch_name(c, view, gives);" in block and 'snprintf(name, sizeof name, "%s", gives);' in block and
          block.index("view = oot_pouch_name(c, view, gives);") < block.index("oot_tracker_item(name);") < block.index("hos_rando_progressive()"),
          "a piece lying in the world does not give its check's item, a chest's piece does, or the record and Progressive items see the piece")
    check("const int other = best >= 0 && oot_checks[best].item[0] && strcmp(oot_checks[best].item, OOT_PIECE);" in host and "#define OOT_PIECE_NEAR 12.0f" in host,
          "a piece that is its own piece is made another item, or one far from Link is")
    print("PASS: Heart Pieces")


if __name__ == "__main__":
    main()
