"""Malon's lesson asks for everything with Songs: Anywhere from placement 15 (tools/rando/rando_seed.py MALON_HARD,
after OOTRR 856b011: the lesson is shut once the Epona quest has moved on): no game data.

    python -I -B tests/test_rando_malon_hard.py
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
    check(S.MALON_HARD == ("song_epona",) and S.MALON_HARD_FROM == 15 <= S.PLACEMENT, "Malon's lesson is not placement 15's")
    check(any(g.key == "song_epona" for g in S.SONGS), "no lesson of Malon's in the songs' table")
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check("malon_hard = a.songs == 2 and placement >= MALON_HARD_FROM" in script and
          "frozenset(PROGRESSION) if malon_hard and h in lessons and gifts[h].key in MALON_HARD else" in script,
          "Malon's lesson does not ask for everything with Songs: Anywhere from placement 15")
    print("PASS: Malon's lesson holds only what the game can be finished without")


if __name__ == "__main__":
    main()
