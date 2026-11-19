"""The royal tomb's scenes with Skip cutscenes (bugs 60 and 61, tools/rando/rando_seed.py): no game data.

- bug 60: the tomb's opening after Zelda's Lullaby (Dm_Graveyard_0010) has no talk and no gift, and is taken all the
  same (SCENE_SILENT): the main loop lets it past the talk filter and quiet_scene keeps a silent scene it passed steps of;
- bug 61: the Sun's Song's lesson (Dm_MelodyGet_Sun) is no longer kept whole (SCENE_KEEP), so it is quieted as the other
  lessons (its auto-play's stray add goes with SCENE_LESSON), and the sunrise videos after it (Dm_MelodyGet_Sun_01, _04
  to _10) are left out (SCENE_VIDEOS), the step after each setting the time;
- FIXES_VERSION moved on, so a seed made before is written again.

    python -I -B tests/test_rando_royal_tomb.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(ok, why):
    if not ok:
        print("FAIL: %s" % why)
        sys.exit(1)


def main():
    sys.path.insert(0, str(ROOT / "tools" / "rando"))
    import rando_seed as R   # noqa: E402
    check("Dm_Graveyard_0010" in R.SCENE_SILENT, "the tomb's opening is not taken (SCENE_SILENT)")
    check("Dm_MelodyGet_Sun" not in R.SCENE_KEEP, "the Sun's Song's lesson is still kept whole (SCENE_KEEP)")
    sun = {"Dm_MelodyGet_Sun_%02d" % n for n in (1, 4, 5, 6, 7, 8, 9, 10)}
    check(sun <= set(R.SCENE_VIDEOS), "the tomb's sunrise videos are not all left out: %s" % sorted(sun - set(R.SCENE_VIDEOS)))
    check("Dm_MelodyGet_Sun_03" not in R.SCENE_VIDEOS, "the lesson's gift scene would be left out with the videos")
    check(R.FIXES_VERSION >= 44, "FIXES_VERSION did not move on: a seed made before keeps the tomb's scenes")
    src = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check('if "EventTalk" not in used and not any(g in used for g in SCENE_GIFTS) and stem not in SCENE_SILENT:' in src and
          "now, taken = quiet_scene(was, silent=stem in SCENE_SILENT)" in src,
          "the main loop does not let a silent scene past the talk filter, or does not say it is silent")
    body = src[src.index("def quiet_scene(data, entries=None, silent=False):"):]
    body = body[:body.index("\ndef ")]
    check(re.search(r"if not talks and not \(entries is None and passed and \(silent or ", body) is not None,
          "quiet_scene gives back nothing for a silent scene it passed steps of")
    print("PASS: the royal tomb's scenes are skipped")


if __name__ == "__main__":
    main()
