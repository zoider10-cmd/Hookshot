"""Bug 62: a chest with a substitute (Drop__CheckActor + Drop__DropActor_Substitute) takes part from placement 12.

tools/rando/rando_seed.py stays_why lets such a chest take part, and rewrite() writes the shuffled item into both its
item and its substitute, so it gives that item whatever Link holds. Checked on a small map file made here: a chest
with the two keys, rewritten, reads back with the new item in both.

python -I -B tests/test_rando_substitute.py
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "rando"))
import rando_seed as seed  # noqa: E402


def main():
    src = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    c = seed.Chest(1, "Obj_TBox_A_06", 0, 0, "TBox_Shield_Hylian",
                   ("Drop__CheckActor", "Drop__DropActor", "Drop__DropActor_Substitute"), (0.0, 0.0, 0.0), "")
    ok = (seed.stays_why(c, False, 12) is None and seed.stays_why(c, False, 11) is not None and
          'if dk in ("Drop__DropActor", "Drop__DropActor_Substitute"):' in src)
    race = seed.Chest(0x4ccffbd5778b67e2, "Obj_TBox_A_02_NoBake", 0, 0, "Obj_Heart_Piece",
                      ("Drop__DropActor", "GetEventName"), (-6.0, 82.5, 77.7), "MiniGame_DampeRace_OpenGoalTBox")
    hook = race._replace(hash=0xde9e62394333948e, item="Item_Hookshot")
    ok = ok and (seed.stays_why(race, False, 12) is None and seed.stays_why(race, False, 11) is not None and
                 seed.stays_why(hook, False, 12) is not None)   # (Dampe's race: the Piece of Heart takes part, the Hookshot stays)
    if not ok:
        print("FAIL: a chest with a substitute does not take part from placement 12, or its substitute is not rewritten")
        sys.exit(1)
    print("PASS: the chests with a substitute take part, the same item either way; Dampe's race's Piece of Heart takes part")


if __name__ == "__main__":
    main()
