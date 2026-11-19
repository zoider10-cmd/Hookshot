"""The Fairy Ocarina shuffled (Songs: Anywhere, ocarina too; tools/rando/rando_seed.py ocarina_need, OCARINA_GIFT): no game data.

- a way of a rule that names a song asks for the ocarina too, and every way of a lesson's; a way without a song is as
  it was;
- the ocarina is Saria's gift on the bridge (Dm_Kokiri_0155), whose flow is changed in its pouch add and its "you got"
  call (kinds 0 and 4), kept behind the Deku Tree's story, never a Gold Skulltula's or a piece's, with the Tracker's
  letters FO (either ocarina counts);
- the setting is Songs' fourth choice, read as Anywhere with the ocarina, and on the stamp's first line.

    python -I -B tests/test_rando_ocarina.py
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
    sung = S.CHILD | {S.ZL}
    check(S.ocarina_need(sung) == sung | {S.OCARINA} and S.ocarina_need(S.CHILD) == S.CHILD,
          "a way with a song does not ask for the ocarina, or one without does")
    check(S.ocarina_need(S.CHILD, lesson=True) == S.CHILD | {S.OCARINA}, "a lesson does not ask for the ocarina")
    two = S.ocarina_need(S.either([S.CHILD, sung]))
    check(set(two) == {S.CHILD, sung | {S.OCARINA}}, "a rule of two ways is not stepped way by way")
    g = S.OCARINA_GIFT
    check(g.flow == "Dm_Kokiri_0155" and g.olds == (S.OCARINA,) and g.key in S.DEKU_STORY and g.key in S.GIFT_PLACES and
          S.OCARINA_KINDS.get(g.flow) == (0, 4), "the ocarina is not Saria's gift, changed in its pouch add and its call")
    check(S.OCARINA in S.SKULLTULA_NEVER and S.OCARINA in S.PIECE_NEVER and S.CHECK_CODES.get(S.OCARINA) == "FO",
          "the ocarina may be a Skulltula's or a piece's, or has no Tracker letters")
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check("a.ocarina = a.songs == 3 and SONGS_ANYWHERE" in script and "a.songs = 2 if a.songs == 3 else a.songs" in script and
          '" ocarina 1" if a.ocarina else ""' in script and "kinds=OCARINA_KINDS.get(flow, (4,)))" in script and
          "needs = {h: ocarina_need(n, True) if h in lessons else n for h, n in needs.items()}" in script,
          "the setting is not read, not on the stamp, or the flow and the lessons are not changed")
    header = (ROOT / "gpu" / "vk" / "oot_rando.h").read_text(encoding="utf-8")
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
    check('"Off", "Song spots", "Anywhere", "Anywhere, ocarina too")' in header and
          '{"FO", "an ocarina", {"Fairy Ocarina", "Ocarina of Time"}},' in menu, "Songs has no fourth choice, or the Tracker no ocarina")
    print("PASS: the Fairy Ocarina shuffled")


if __name__ == "__main__":
    main()
