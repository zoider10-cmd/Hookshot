"""The Great Fairies of the spells in the shuffle (tools/rando/rando_seed.py FAIRY_GIFTS, placement 14; seen without a
window 2026-11-19: Death Mountain Trail's fairy gave a seed's Hover Boots once, the tracker counted it, and the second
Lullaby healed and gave nothing): no game data.

- the three fountains are Quest rewards' gifts from placement 14 and the seeds made before keep their shuffle;
- each may hold only what a lesson asked about by name may (got nowhere else, with its own flag), as the lessons;
- the words IsGet.<item> and HavePlayedGetEvent.<item> are made to name what the fountain gives now, all at once
  (two fountains whose items changed places keep each other's straight), by the name the item's flags have;
- with the songs shuffled each fountain asks for Zelda's Lullaby.

    python -I -B tests/test_rando_fairies.py
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
    gifts = {g.key: g for g in S.GIFTS}
    check(all(k in gifts and S.GIFTS_FROM.get(k) == 14 for k in S.FAIRY_GIFTS) and S.PLACEMENT >= 14,
          "the three fountains are not gifts from placement 14")
    check({gifts[k].item for k in S.FAIRY_GIFTS} == {"Item_DinFire", "Item_FaroreWind", "Item_NayruLove"} and
          all(gifts[k].olds == (gifts[k].item,) for k in S.FAIRY_GIFTS), "the fountains are not the three spells'")
    check(all(k in S.GIFT_PLACES for k in S.FAIRY_GIFTS) and all(S.ZL in S.SONG_GIFTS.get(k, ()) for k in S.FAIRY_GIFTS),
          "a fountain has no place for the tracker, or does not ask for the Lullaby with the songs")
    check(gifts["fairy_nayru"].need >= S.DESERT and gifts["fairy_farore"].need >= S.ADULT and S.BB in gifts["fairy_din"].need,
          "a fountain asks for too little")
    words = S.fairy_words({"Item_DinFire": "Item_FaroreWind", "Item_FaroreWind": "Item_DinFire", "Item_NayruLove": "Item_HoverBoot"})
    check(words == {"IsGet.Item_DinFire": "IsGet.Item_FaroreWind", "HavePlayedGetEvent.Item_DinFire": "HavePlayedGetEvent.Item_FaroreWind",
                    "IsGet.Item_FaroreWind": "IsGet.Item_DinFire", "HavePlayedGetEvent.Item_FaroreWind": "HavePlayedGetEvent.Item_DinFire",
                    "IsGet.Item_NayruLove": "IsGet.Armor_Adult_HoverBoot", "HavePlayedGetEvent.Item_NayruLove": "HavePlayedGetEvent.Armor_Adult_HoverBoot"},
          "the fountains' words are not made to name what each gives now: %r" % words)
    check(S.fairy_words({"Item_DinFire": "Item_DinFire"}) == {}, "a fountain that keeps its spell has its words changed")
    check("TriForcePoint" in S.FAIRY_FLOWS and len([f for f in S.FAIRY_FLOWS if f.startswith("Dm_FairyFountain_")]) == 6,
          "not every fountain's flow and the mark's are made to ask for what the fountains give now")
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check("lesson_only.update((h, (lesson_safe, frozenset(SONG_ITEMS) if a.songs == 2 else frozenset())) for h in fairies)" in script and
          "if a.songs == 2 or fairies:" in script and "now, found = gift_items(was, words, kinds=(0, 1))" in script and
          'sys.exit("a Great Fairy gives what has no flag of its own' in script,
          "a fountain may hold what has no flag of its own, or its flows are not changed")
    print("PASS: the Great Fairies of the spells")


if __name__ == "__main__":
    main()
