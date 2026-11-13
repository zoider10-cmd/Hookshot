"""Dungeon rewards (tools/rando/rando_seed.py REWARDS): the eight dungeons' Spiritual Stones and Medallions shuffled
among their eight endings.

- the table: eight endings, one for each stone and medallion but the Light Medallion, each a scene's flow that names
  its item; none is a gating item (nothing in the game asks whether Link holds one);
- the shuffle keeps them to the endings, and with the songs each group keeps to its own (place's bound groups);
- a flow's second file (<name>.110) is written with the same change;
- the setting reaches the script, the seed's stamp (named only when on) and the launcher, where Anywhere is not
  offered yet.

    python -I -B tests/test_rando_rewards.py
"""
import collections
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "rando"))
import rando_seed as seed


def check(ok, what):
    if not ok:
        print("FAIL: " + what)
        sys.exit(1)


def main():
    items = [g.item for g in seed.REWARDS]
    check(len(seed.REWARDS) == 8 and items == list(seed.REWARD_ITEMS) and len(set(items)) == 8 and
          sorted(i.split("_")[1] for i in items) == ["Medal"] * 5 + ["Stone"] * 3 and "Item_Medal_Light" not in items,
          "the rewards are not the three stones and the five medallions a dungeon ends in (the Light Medallion is Rauru's)")
    check(all(g.olds == (g.item,) and g.flow and g.when == "rewards" and g.area in seed.AREA_NAMES and g.key.startswith("reward_")
              for g in seed.REWARDS) and len({g.key for g in seed.REWARDS}) == 8 and len({g.flow for g in seed.REWARDS}) == 8,
          "an ending is not one scene's flow that names its own item, or two share a key or a flow")
    check(not set(items) & set(seed.PROGRESSION) and not set(items) & set(seed.SONG_ITEMS),
          "a stone or a medallion is a gating item: nothing in the game asks whether Link holds one")
    check({g.key for g in seed.REWARDS}.isdisjoint({g.key for g in seed.GIFTS + seed.SCRUBS + seed.SONGS}), "an ending's key is another gift's")
    by = {g.key: g for g in seed.REWARDS}
    check(by["reward_deku"].need == seed.CHILD and seed.BB in by["reward_dodongo"].need and seed.HAM in by["reward_fire"].need and
          seed.IRON in by["reward_water"].need and seed.LENS in by["reward_shadow"].need and seed.MS in by["reward_spirit"].need,
          "an ending does not ask for what its dungeon asks for")

    # ---- the shuffle: the rewards among the endings, the songs among the lessons, the rest among the rest ----
    spots = collections.OrderedDict()
    for k in range(20):
        spots[k] = ("HyruleField", "TBox_Rupee_Green" if k % 2 else "TBox_Rupee_Blue", False, None)
    lessons = {100 + k: song for k, song in enumerate(seed.SONG_ITEMS)}
    endings = {200 + k: item for k, item in enumerate(seed.REWARD_ITEMS)}
    for h, item in list(lessons.items()) + list(endings.items()):
        spots[h] = ("HyruleField", item, None, None)
    groups = [(frozenset(seed.SONG_ITEMS), frozenset(lessons)), (frozenset(seed.REWARD_ITEMS), frozenset(endings))]
    moved = 0
    for k in range(30):
        gives, _, _ = seed.place(random.Random(k), spots, 3, 0, None, groups)
        check(sorted(gives[h] for h in endings) == sorted(seed.REWARD_ITEMS) and sorted(gives[h] for h in lessons) == sorted(seed.SONG_ITEMS) and
              all(gives[h].startswith("TBox_Rupee") for h in range(20)),
              "a reward is not at an ending, a song not at a lesson, or one of them among the chests")
        moved += sum(1 for h in endings if gives[h] != endings[h])
    check(moved > 100, "the rewards are hardly shuffled (%d of 240 moved)" % moved)
    # (one group as before, a pair and not a list; and none)
    one, _, _ = seed.place(random.Random(1), spots, 3, 0, None, groups[0])
    check(sorted(one[h] for h in lessons) == sorted(seed.SONG_ITEMS), "one bound group given as a pair is not kept to its spots")
    none, _, _ = seed.place(random.Random(1), spots, 3, 0, None, None)
    check(collections.Counter(none.values()) == collections.Counter(s[1] for s in spots.values()), "without a bound group an item is lost or made")

    # ---- the script and the launcher ----
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check('"rando_dungeon_rewards": 0' in script and 'a.dungeon_rewards = 1 if a.dungeon_rewards in (1, 2) else 0' in script and
          '(" rewards 1" if a.dungeon_rewards else "")' in script,
          "the script does not read the setting, or names it in the seed's stamp when off (a seed made before it would be made again)")
    check("for g in REWARDS:" in script and '(frozenset(REWARD_ITEMS), frozenset(endings)) if a.dungeon_rewards else None' in script,
          "the endings are not spots of the shuffle, or the rewards are not bound to them")
    check('twin = "%s/%s%s.bfevfl.zs" % (GIFT_FLOWS, flow, FLOW_TWIN)' in script and seed.FLOW_TWIN == ".110" and
          "+ ([twin] if os.path.isfile(os.path.join(romfs, *twin.split(\"/\"))) else [])" in script,
          "a flow's second file (.110) is not written with the same change: the game may read that one")
    launcher = (ROOT / "launcher" / "Launcher.cs").read_text(encoding="utf-8")
    check('{ "rando_dungeon_rewards", 2 }' in launcher, "the launcher does not offer Dungeons, or offers Anywhere, which is not made")
    print("PASS: Dungeon rewards")


if __name__ == "__main__":
    main()
