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
          'for rel in rels + ["spoiler.txt", TRACKER, CHECKS, "rando_stamp.txt", "rando_manifest.txt"]:' in script and seed.TRACKER == "tracker.txt",
          "the tracker's file is not written with the seed, or stays when the seed is taken away")
    # ---- the menu's side ----
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
    m = re.search(r"constexpr int kTrackerRows = (\d+);", menu)
    check(m and int(m.group(1)) == seed.TRACKER_ROWS, "the menu has not as many rows as the script may write")
    check(menu.count("    TRACKER_ROW(") == seed.TRACKER_ROWS and all("    TRACKER_ROW(%d)\n" % k in menu for k in range(seed.TRACKER_ROWS)),
          "the menu's table has not a row for each line")
    check(re.search(r"char tracker_name\[kTrackerRows\]\[48\];\s*char tracker_value\[kTrackerRows\]\[72\];", menu),
          "the menu's room for a name and a value is not what the script writes for (47 and 71 characters)")
    check('"mods\\\\rando-seed\\\\tracker.txt"' in menu and "TAB_TRACKER = 5," in menu and "TAB_COUNT = 6," in menu and
          '{"Graphics", "Audio", "Gameplay", "Controls", "Debug", "Tracker"}' in menu, "the menu has no Tracker tab that reads the seed's file")
    check("rows[i].tracker < tracker_count &&" in menu and "if (t == TAB_TRACKER) tracker_load();" in menu,
          "the rows past the file's lines are shown, or the file is not read for the tab")
    check("else if (press[7] && !r.value && r.tracker < 0 && can_bind()) page = 1" in menu and
          "choice_cell(c, va, vb, tracker_says(r.tracker), selected, steps, steps);" in menu and
          "if (!k) return tracker_value[row];" in menu,
          "a Tracker row opens the Controls page on confirm, or does not show the file's value")
    # ---- the checks one by one, and Go there ----
    lines = seed.check_lines([("ZoraRiver", (1.0, 2.0, 3.0), "CA"), ("KokiriForest", (-27.04, 67.6, 65.2), "C"), ("KokiriForest", (-30.0, 1.0, 2.0), "A"),
                              ("Market", (), "C"), ("Market", (1.0, 1.0, 1.0), "")],
                             [("KokiriForest", (5.0, 6.0, 7.0), "CA")])
    check(lines[0].startswith("#") and lines[1:] == [
        "Kokiri Forest|Chest|KokiriForest|A|-30.0 1.0 2.0", "Kokiri Forest|Chest|KokiriForest|C|-27.0 67.6 65.2",
        "Kokiri Forest|Gold Skulltula|KokiriForest|CA|5.0 6.0 7.0", "Zora's River|Chest|ZoraRiver|CA|1.0 2.0 3.0"],
        "the checks' lines are not the area's name, the kind, the folder, the ages and the place, by area: %r" % lines[1:])
    check(all(line.split("|")[0] in {t.split("|")[0] for t in seed.tracker_lines({"KokiriForest": 2, "ZoraRiver": 1}, {"KokiriForest": 1})}
              for line in lines[1:]), "a check's area is not the name of its tracker row")
    check(len(seed.check_lines([("Market", (float(k), 0.0, 0.0), "C") for k in range(400)], [])) == 1 + seed.CHECK_ROWS,
          "more checks are written than the menu keeps")
    check(seed.check_ages({"KokiriForest_Child_Static.bcett.byml.zs"}) == "C" and seed.check_ages({"LostWood_Adult_Dynamic.bcett.byml.zs"}) == "A" and
          seed.check_ages({"A_Child_Static", "A_Adult_Static"}) == "CA" and seed.check_ages({"FireTemple_Static.bcett.byml.zs"}) == "CA" and
          seed.check_ages(set()) == "", "the ages whose map has a check are not read from its files' names")
    check('with open(os.path.join(mod, CHECKS), "w", encoding="utf-8", newline="\\n") as f:' in script and seed.CHECKS == "checks.txt" and
          '" checks 1" +' in script, "the checks' file is not written with the seed, or a seed made before it is not made again")
    m = re.search(r"constexpr int kTrackerChecks = (\d+);", menu)
    check(m and int(m.group(1)) == seed.CHECK_ROWS, "the menu does not keep as many checks as the script may write")
    check('"%47[^|]|%23[^|]|%39[^|]|%3[^|]|%f %f %f"' in menu and '+ "checks.txt";' in menu, "the menu does not read the checks' file as it is written")
    check("if (press[3] || press[4]) tracker_pick[row] = (tracker_pick[row] + n + 1 + (press[4] ? 1 : -1)) % (n + 1), changed = true;" in menu and
          "else if (r.tracker >= 0) tracker_press(r.tracker, press, changed);" in menu,
          "Left and Right do not step through a row's checks and back to its own words")
    check("const TrackerCheck* k = press[7] && cheats_on() ? tracker_row_check(row, tracker_pick[row]) : nullptr;" in menu and
          '"rando\\\\goto_check.txt"' in menu and "cheat_action.store(kTrackerGoAction);" in menu and
          'fprintf(f, "%.2f %.2f %.2f %s %s\\n", k->pos[0], k->pos[1] + 1.0f, k->pos[2], k->folder, k->ages);' in menu,
          "confirm does not send the check shown to the game, or does so with the debug tools off")
    host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    m = re.search(r"constexpr int kTrackerGoAction = (\d+);", menu)
    check(m and "if (action == %s) {" % m.group(1) in host and '"goto_check.txt"' in host and
          'fscanf(f, "%f %f %f %39s %7s"' in host, "the game does not take the menu's action, or reads the check otherwise than it is written")
    check("else if (oot_teleport(c, actor, index)) check.waiting = 1" in host and "} else if (oot_banc_in_folder(current, check.folder)) {" in host and
          "!strchr(check.ages, child ? 'C' : 'A')" in host and
          "} else if (!oot_banc_in_folder(current, check.folder) || loading || oot_event_playing(c)) {" in host,
          "the game does not go to the check's map first, or takes the place before Link has arrived, or at an age whose map has not the check")
    check('"No seed"' in menu and "now - last < 1000" in menu, "the tab says nothing without a seed, or reads its file every frame")
    print("PASS: the randomizer's Tracker tab")


if __name__ == "__main__":
    main()
