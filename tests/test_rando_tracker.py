"""The randomizer's Tracker tab: the file the seed script writes and the menu that shows it.

tools/rando/rando_seed.py writes <game folder>/mods/rando-seed/tracker.txt with a seed: a row for each area with the
chests and Gold Skulltulas that take part. The Insert menu's Tracker tab (gpu/vk/vk_menu.cpp) shows the file's lines
as they are. Checked here: the lines for made-up counts (a line for the whole game, the areas by name, singular and
plural, nothing for an area with none, no more rows than the menu has, no name or value longer than the menu's
room for it); that the file is one of the seed's own, taken away with it; and that the menu's side reads the same
file, has as many rows as the script may write, and does nothing on a row's confirm.

    python -I -B tests/test_rando_tracker.py
"""
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rando_seed", ROOT / "tools" / "rando" / "rando_seed.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


def check(ok, what):
    if not ok:
        raise SystemExit("FAIL: " + what)


def main():
    # ---- the file's lines ----
    lines = seed.tracker_lines({"KokiriForest": 7, "ZoraRiver": 1, "Market": 0, "InsideGanonCastle": 10}, {"KokiriForest": 3, "ZoraRiver": 4, "HyruleCastle": 1})
    check(lines[0].startswith("#"), "the file does not start with a line that is no row")
    rows = [line.split("|") for line in lines[1:]]
    check(all(len(r) == 2 for r in rows), "a row is not <name>|<what>")
    check(rows[0] == ["The whole game", "18 chests, 8 Gold Skulltulas"], "the first row is not the whole game's: %r" % rows[0])
    check(rows[1:] == [["Hyrule Castle", "1 Gold Skulltula"], ["Inside Ganon's Castle", "10 chests"], ["Kokiri Forest", "7 chests, 3 Gold Skulltulas"],
                       ["Zora's River", "1 chest, 4 Gold Skulltulas"]],
          "the areas are not by their names, with what each has and none for an area with nothing: %r" % rows[1:])
    check(seed.tracker_lines({}, {})[1:] == ["The whole game|nothing"], "a seed with no check has more than the whole game's row")
    # (more areas than the menu has rows: the last row says how many more; a long name and a bar in one do not break a row)
    many = seed.tracker_lines({"Area %02d" % k: k + 1 for k in range(80)}, {})
    check(len(many) == 1 + seed.TRACKER_ROWS and many[-1].startswith("And 34 more areas|"), "more rows are written than the menu has: %d" % (len(many) - 1))
    odd = seed.tracker_lines({"A|B" + "x" * 90: 2}, {})[2]
    check(odd.count("|") == 1 and len(odd.split("|")[0]) <= 47, "a name with a bar, or too long for the menu, is written as it is")
    check(all(len(n) <= 47 and len(v) <= 71 for n, v in (line.split("|") for line in many[1:] + lines[1:])), "a name or a value is longer than the menu's room")
    check(all(name == seed.AREA_NAMES[key] and name.strip() and "|" not in name for key, name in seed.AREA_NAMES.items()) and
          set(seed.RULES) <= set(seed.AREA_NAMES), "an area the rules know has no name for the tracker")
    # ---- the seed's side: written with the seed, taken away with it ----
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check('with open(os.path.join(mod, TRACKER), "w", encoding="utf-8", newline="\\n") as f:' in script and
          'for rel in rels + ["spoiler.txt", TRACKER, "rando_stamp.txt", "rando_manifest.txt"]:' in script and seed.TRACKER == "tracker.txt",
          "the tracker's file is not written with the seed, or stays when the seed is taken away")
    # ---- the menu's side ----
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
    m = re.search(r"constexpr int kTrackerRows = (\d+);", menu)
    check(m and int(m.group(1)) == seed.TRACKER_ROWS, "the menu has not as many rows as the script may write")
    check(menu.count("    TRACKER_ROW(") == seed.TRACKER_ROWS and all("    TRACKER_ROW(%d)\n" % k in menu for k in range(seed.TRACKER_ROWS)),
          "the menu's table has not a row for each line")
    check(re.search(r"char tracker_name\[kTrackerRows\]\[48\];\s*char tracker_value\[kTrackerRows\]\[72\];", menu),
          "the menu's room for a name and a value is not what the script writes for (47 and 71 characters)")
    check('"mods\\\\rando-seed\\\\tracker.txt"' in menu and "TAB_TRACKER = 4," in menu and "TAB_COUNT = 5," in menu and
          '{"Graphics", "Gameplay", "Controls", "Debug", "Tracker"}' in menu, "the menu has no Tracker tab that reads the seed's file")
    check("rows[i].tracker < tracker_count &&" in menu and "if (t == TAB_TRACKER) tracker_load();" in menu,
          "the rows past the file's lines are shown, or the file is not read for the tab")
    check("else if (press[7] && !r.value && r.tracker < 0 && can_bind()) page = 1" in menu and
          "choice_cell(c, va, vb, tracker_value[r.tracker], selected, false, false);" in menu,
          "a Tracker row opens the Controls page on confirm, or does not show the file's value")
    check('"No seed"' in menu and "now - last < 1000" in menu, "the tab says nothing without a seed, or reads its file every frame")
    print("PASS: the randomizer's Tracker tab")


if __name__ == "__main__":
    main()
