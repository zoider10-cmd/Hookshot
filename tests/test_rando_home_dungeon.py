"""The Tracker's Return home takes Link to a dungeon's entrance when he is in one (host/hos_main.c, the action 7; asked for
2026-11-18): no game data.

- the action looks for a destination whose map is one for both ages (a dungeon's row of the Debug tab's teleport) and is
  the map Link is in, before the forest's or the Market's, and teleports there;
- the rows it can find are the dungeons' (every row with one map for both ages is a dungeon, the Hyrule Castle row's two
  maps differ), and every dungeon of the teleport has one;
- the menu's row and help say so.

    python -I -B tests/test_rando_home_dungeon.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DUNGEONS = {"InsideTheDekuTree", "DodongoCavern", "InsideJabuJabuBelly", "ForestTemple", "FireTemple", "WaterTemple",
            "ShadowTemple", "SpiritTemple", "BottomOfTheWell", "IceCavern", "GerudoTrainingGround", "InsideGanonCastle"}


def check(ok, why):
    if not ok:
        print("FAIL: %s" % why)
        sys.exit(1)


def main():
    host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    home = host[host.index("} else if (action == 7) {"):]
    home = home[:home.index("} else if (action >= 100 && action < 124) {")]
    check("if (cb && ab && !strcmp(cb, ab) && oot_banc_in_folder(oot_link_map, cb)) {" in home and
          home.index("oot_banc_in_folder(oot_link_map, cb)") < home.index("oot_teleport(c, actor, index)"),
          "Return home does not look for the dungeon Link is in before it teleports")
    table = host[host.index("oot_destinations[] = {"):]
    table = table[:table.index("};")]
    rows = re.findall(r'\{(NULL|"[^"]*"), (?:NULL|"[^"]*"), (?:NULL|"[^"]*"),\s*(NULL|"[^"]*"),', table)
    same = {c.strip('"') for c, a in rows if c != "NULL" and c == a}
    check(same == DUNGEONS, "the rows with one map for both ages are not the dungeons: %s" % sorted(same ^ DUNGEONS))
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
    check("in a dungeon, to its entrance" in menu and "\"Kokiri Forest, the Market, or the dungeon's entrance\"" in menu,
          "the menu's row or help does not say a dungeon's entrance")
    print("PASS: Return home in a dungeon goes to its entrance")


if __name__ == "__main__":
    main()
