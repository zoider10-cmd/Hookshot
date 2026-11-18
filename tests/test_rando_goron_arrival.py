"""Bug 64: an adult's first visit to Goron City goes on to the rolling Goron's scene.

Dm_SY_BancChangeArrive's first-visit arrival (GoronCity_InitDemo_Arrive) ends after the Goron's Ruby quest's
ArriveCity step; tools/rando/rando_seed.py goron_arrival_fix sends it on to the ordinary arrival's child-or-adult
question, which plays SageOfFire_CityIn for an adult who hasn't seen it. The steps are found by what they do, and
the seed tool stops with nothing written if they are not there once each. Checked by source.

python -I -B tests/test_rando_goron_arrival.py
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "rando"))
import rando_seed as seed  # noqa: E402


def main():
    src = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    ok = (seed.ARRIVE_FLOW == "Event/EventFlow/Dm_SY_BancChangeArrive.bfevfl.zs" and seed.FIXES_VERSION >= 42 and
          's["kind"] == 0 and s.get("event") == "SageOfFire_CityIn"' in src and
          's["what"] == "EventQueryPlayerIsChild"' in src and
          's.get("entry") == "Get_StoneOfFire_ArriveCity"' in src and
          'struct.pack_into("<H", out, steps[call[0]]["next"], child[0])' in src and
          "gift_files[ARRIVE_FLOW] = goron_arrival_fix(was)" in src and
          not any("Dm_Goron_" in k or "Dm_DeathMtTrail_" in k for k in seed.AREA_INTROS))
    if not ok:
        print("FAIL: Goron City's first-visit arrival does not go on to the rolling Goron's scene, or its intro is skipped")
        sys.exit(1)
    print("PASS: an adult's first visit to Goron City reaches the rolling Goron")


if __name__ == "__main__":
    main()
