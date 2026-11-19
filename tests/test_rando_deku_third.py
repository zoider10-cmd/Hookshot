"""The Deku Tree's third floor asks for the Slingshot from placement 15 (tools/rando/rando_seed.py DEKU_THIRD_FLOOR,
after the other randomizer's remake logic, OOTRR adf81ae): no game data.

    python -I -B tests/test_rando_deku_third.py
"""
import importlib.util
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


def main():
    S = seed
    check(S.PLACEMENT >= S.DEKU_THIRD_FROM == 15 and len(S.DEKU_THIRD_FLOOR) == 2, "the third floor's rule is not placement 15's")
    check(S.SL in S.CHILD and S.skulltula_rule(0xbce05898ce61f1c0, "InsideTheDekuTree") == frozenset((S.S,)),
          "the Skulltula's own line changed (seeds before 15 must keep their rules)")
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check("slingshot_room |= {h for h in DEKU_THIRD_FLOOR if h in needs} if placement >= DEKU_THIRD_FROM else set()" in script and
          "(CHILD if placement >= DEKU_THIRD_FROM and h in DEKU_THIRD_FLOOR else NONE)" in script,
          "the chest's or the Skulltula's rule does not follow the placement")
    print("PASS: the Deku Tree's third floor asks for the Slingshot")


if __name__ == "__main__":
    main()
