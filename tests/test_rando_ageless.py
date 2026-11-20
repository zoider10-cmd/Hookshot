"""Either age's items (rando_ageless, tools/rando/rando_seed.py pouch_ageless; asked for 2026-11-18): no game data.

- the pouch table's entries of the actors asked for get both age marks (IsUsableAdult, IsUsableChild), others none;
- the game's bytes are kept: the file only grows by the entries written again, and nothing before them moves but the
  pointers to them (the table written anew whole made the game fall as it read it, seen 2026-11-19);
- its entry in the size table is raised (it grew, and 756 bytes more fell without), the setting is read, and it is on
  the stamp's second line (it moves no item);
- 1 is the two swords, 2 also the age-only items; the setting is a row of the game's table and the launcher's.

    python -I -B tests/test_rando_ageless.py
"""
import collections
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rando_seed", ROOT / "tools" / "rando" / "rando_seed.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)

TRUE = (208, b"\x01\x00\x00\x00")


def check(ok, why):
    if not ok:
        print("FAIL: %s" % why)
        sys.exit(1)


def entry(actor, adult, child):
    row = collections.OrderedDict([("ActorShort", ("string", actor))])
    if adult:
        row["IsUsableAdult"] = TRUE
    if child:
        row["IsUsableChild"] = TRUE
    row["PouchActorShort"] = ("string", "Pouch_" + actor)
    return ("dict", row)


def slot(*actors):
    return ("dict", collections.OrderedDict([("Actor", ("array", list(actors))), ("BtnName", ("string", "Pa_00"))]))


def main():
    S = seed
    tree = ("dict", collections.OrderedDict([
        ("EquipmentArray", ("array", [slot(entry("Weapon_Sword_Master", True, False)), slot(entry("Weapon_Sword_Kokiri", False, True)),
                                      slot(entry("Weapon_Shield_Hylian", True, True))])),
        ("ItemArray", ("array", [slot(entry("Weapon_Range_Bow", True, False), entry("Item_Arrow_Normal", True, False)),
                                 slot(entry("Item_Boomerang", False, True))])),
        ("Other", (210, b"\x00\x00\x80?")),
    ]))
    data = S.byml_build(tree, 7)
    new, count = S.pouch_ageless(data, S.AGELESS_SWORDS)
    got, _ = S.byml_parse(new)
    marks = {a[1]["ActorShort"][1]: (a[1].get("IsUsableAdult") == TRUE, a[1].get("IsUsableChild") == TRUE)
             for arr in S.AGELESS_ARRAYS for s in got[1][arr][1] for a in s[1]["Actor"][1]}
    check(count == 2 and marks["Weapon_Sword_Master"] == (True, True) and marks["Weapon_Sword_Kokiri"] == (True, True) and
          marks["Weapon_Range_Bow"] == (True, False) and marks["Item_Boomerang"] == (False, True),
          "the swords are not both ages', or another item was changed: %r" % marks)
    check(len(new) > len(data) and new[:4] == data[:4] and new[4:16] == data[4:16], "the file's header or tables moved")
    differ = [k for k in range(len(data)) if new[k] != data[k]]
    check(len(differ) <= 2 * 4, "more of the game's bytes changed than the two pointers (%d bytes)" % len(differ))
    new2, count2 = S.pouch_ageless(data, ("Weapon_Range_Bow", "Item_Arrow_Normal", "Item_Boomerang"))
    got2, _ = S.byml_parse(new2)
    marks2 = {a[1]["ActorShort"][1]: (a[1].get("IsUsableAdult") == TRUE, a[1].get("IsUsableChild") == TRUE)
              for arr in S.AGELESS_ARRAYS for s in got2[1][arr][1] for a in s[1]["Actor"][1]}
    check(count2 == 3 and marks2["Weapon_Range_Bow"] == marks2["Item_Arrow_Normal"] == marks2["Item_Boomerang"] == (True, True),
          "two entries of one slot are not both changed")
    try:
        S.pouch_ageless(data, ("Weapon_Sword_Nothing",))
        check(False, "an actor the table lacks is not refused")
    except ValueError:
        pass
    check(set(S.AGELESS_SWORDS) == {"Weapon_Sword_Master", "Weapon_Sword_Kokiri"} and set(S.AGELESS_SWORDS) < set(S.AGELESS_ITEMS) and
          {"Weapon_Range_Bow", "Item_Hookshot", "Item_Longshot", "Item_Hammer", "Item_Boomerang", "Weapon_Range_SlingShot"} <= set(S.AGELESS_ITEMS),
          "the two choices are not the swords, and the swords with the age-only items")
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check("shop_parts.add(AGELESS_TABLE)" in script and 'stamp = stamp[:-1] + " ageless %d\\n" % a.ageless' in script and
          '"rando_ageless": 0' in script and '"rando_ageless_items": 0' in script and "ageless_actors(a.ageless))" in script,
          "the table's size entry is not raised, the setting is not read, or it is not on the stamp's second line")
    header = (ROOT / "gpu" / "vk" / "oot_rando.h").read_text(encoding="utf-8")
    launcher = (ROOT / "launcher" / "Launcher.cs").read_text(encoding="utf-8")
    check('X(AGELESS, "Either age\'s swords", "rando_ageless",' in header and 'X(AGELESS_ITEMS, "Either age\'s items", "rando_ageless_items",' in header and
          'new object[] { "rando_ageless", "Either age\'s swords", new[] { "Off", "On" }' in launcher and
          'new object[] { "rando_ageless_items", "Either age\'s items", new[] { "Off", "On" }' in launcher,
          "the two settings are not rows of the game's table or the launcher's")
    # (the swords alone, the items alone, both; an older seed's 2 is both)
    check(S.ageless_actors(1) == S.AGELESS_SWORDS and not set(S.ageless_actors(2)) & set(S.AGELESS_SWORDS) and
          set(S.ageless_actors(3)) == set(S.AGELESS_ITEMS) and S.ageless_actors(0) == (),
          "the swords and the age-only items are not chosen apart")
    check('(1 if ini["rando_ageless"] in (1, 2) else 0) | (2 if ini["rando_ageless"] == 2 or ini["rando_ageless_items"] == 1 else 0)' in script,
          "an older seed's swords and items is not read as both, or the two settings are not read apart")
    print("PASS: either age's items")


if __name__ == "__main__":
    main()
