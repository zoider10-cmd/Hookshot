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
          "std::string words = all ? checks(told ? left : all) + (told ? \" left\" : \"\") : std::string(tracker_value[row]);" in menu,
          "a Tracker row opens the Controls page on confirm, or does not show the file's value")
    # ---- the checks one by one, and Go there ----
    lines = seed.check_lines([("ZoraRiver", (1.0, 2.0, 3.0), "CA", seed.ADULT), ("KokiriForest", (-27.04, 67.6, 65.2), "C", seed.NONE),
                              ("KokiriForest", (-30.0, 1.0, 2.0), "A", seed.quest_need(seed.ADULT | {seed.HAM}, "KokiriForest")),
                              ("Market", (), "C", seed.NONE), ("Market", (1.0, 1.0, 1.0), "", seed.NONE)],
                             [("KokiriForest", (5.0, 6.0, 7.0), "CA", frozenset((seed.S, "Item_NotOfTheRules")))])
    check(lines[0].startswith("#") and lines[1:] == [
        "Kokiri Forest|Chest|KokiriForest|A|-30.0 1.0 2.0|KS,SL,BB,BM,HM,GB,SS", "Kokiri Forest|Chest|KokiriForest|C|-27.0 67.6 65.2|-",
        "Kokiri Forest|Gold Skulltula|KokiriForest|CA|5.0 6.0 7.0|KS", "Zora's River|Chest|ZoraRiver|CA|1.0 2.0 3.0|KS,SL,BB,BM"],
        "the checks' lines are not the area's name, the kind, the folder, the ages, the place and what the rules ask for, by area: %r" % lines[1:])
    # ---- the gifts and the scrubs' sales among them ----
    check(set(seed.GIFT_PLACES) == {g.key for g in seed.GIFTS + seed.SCRUBS + seed.SONGS}, "a gift or a scrub's sale has no place for the tracker, or a place is of no gift: %r" % sorted(
        set(seed.GIFT_PLACES) ^ {g.key for g in seed.GIFTS + seed.SCRUBS}))
    check(all(ages in ("C", "A", "CA") and len(pos) == 3 and g.area in seed.AREA_NAMES and len(g.name) <= 55
              for g in seed.GIFTS + seed.SCRUBS for ages, pos in [seed.GIFT_PLACES[g.key]]), "a gift's place is not ages and three numbers, or its name is too long for a row")
    with_gifts = seed.check_lines([("KakarikoVillage", (1.0, 2.0, 3.0), "CA", seed.NONE)], [("KakarikoVillage", (4.0, 5.0, 6.0), "C", seed.CHILD)],
                                  [("KakarikoVillage", (-73.9, 99.5, 82.9), "C", seed.CHILD, "the cucco lady"), ("LostWood", (7.3, 82.9, -85.6), "CA", seed.CHILD, "a Business Scrub: the Deku Nut upgrade")])
    check(with_gifts[1:] == ["Kakariko Village|Chest|KakarikoVillage|CA|1.0 2.0 3.0|-", "Kakariko Village|Gold Skulltula|KakarikoVillage|C|4.0 5.0 6.0|KS,SL",
                             "Kakariko Village|The cucco lady|KakarikoVillage|C|-73.9 99.5 82.9|KS,SL",
                             "Lost Woods|A Business Scrub: the Deku Nut upgrade|LostWood|CA|7.3 82.9 -85.6|KS,SL"],
          "a gift's line is not its area, its name, its folder, its ages, its place and what it asks for, after the area's chests and Gold Skulltulas: %r" % with_gifts[1:])
    check("for h, g in gifts.items() if h in gives and g.key in GIFT_PLACES] +" in script and
          'if (!strcmp(k->kind, "Chest") || !strcmp(k->kind, "Gold Skulltula")) snprintf(place' in menu,
          "the gifts that take part are not written with the checks, or a gift's row is its place and not its name")
    # ---- a chest's and a Gold Skulltula's name ----
    exits = [((100.0, 0.0, 0.0), "LostWood"), ((0.0, 0.0, 30.0), "HyruleField")]
    parts = [((500.0, -50.0, 500.0), 199.0, "LakeHylia")]
    name = seed.check_name
    check(name("Chest", "TBox_Rupee_Red", {"room": 10}, (1.0, 2.0, 3.0), exits, parts) == "Chest (red rupee), room 10" and
          name("Chest", "Item_Sword_Kokiri", {"big": True}, (-300.0, 0.0, 0.0), exits, parts) == "Big chest (Kokiri Sword)" and
          name("Chest", "Item_Arrow_Fire", {}, (0.0, 0.0, 0.0), exits, parts) == "Chest (Arrow Fire), by the Hyrule Field exit" and
          name("Chest", "Obj_Heart_Piece", {}, (450.0, 130.0, 420.0), exits, parts) == "Chest (Piece of Heart), Lake Hylia" and
          name("Gold Skulltula", "", {"night": True}, (90.0, 5.0, 0.0), exits, parts) == "Gold Skulltula, night, by the Lost Woods exit" and
          name("Gold Skulltula", "", {"soil": True, "room": 0}, (), exits, parts) == "Gold Skulltula, bean soil, room 0" and
          name("Gold Skulltula", "", {}, (-300.0, 0.0, 0.0)) == "Gold Skulltula",
          "a check's name is not what it held, its kind, its room, its part of the map or the way out it is near")
    check(seed.spaced("LonLonRanch") == "Lon Lon Ranch" and seed.spaced("Item_BombBag_Small") == "Bomb Bag Small" and seed.spaced("Market") == "Market",
          "a name is not put in words")
    twins = seed.check_lines([("Market", (5.0, 0.0, 0.0), "C", seed.NONE, "Chest (red rupee)"), ("Market", (1.0, 0.0, 0.0), "C", seed.NONE, "Chest (red rupee)"),
                              ("Market", (3.0, 0.0, 0.0), "C", seed.NONE, "Chest (blue rupee)"), ("ZoraRiver", (1.0, 0.0, 0.0), "C", seed.NONE, "Chest (red rupee)")],
                             [("Market", (2.0, 0.0, 0.0), "C", seed.NONE, "x" * 120)],
                             [("Market", (0.0, 0.0, 0.0), "C", seed.NONE, "bowling"), ("Market", (0.0, 0.0, 0.0), "C", seed.NONE, "bowling")])
    kinds = [line.split("|")[1] for line in twins[1:]]
    check(kinds == ["Chest (blue rupee)", "Chest (red rupee) #1", "Chest (red rupee) #2", "X" + "x" * 78, "Bowling", "Bowling", "Chest (red rupee)"] and
          twins[2].endswith("|1.0 0.0 0.0|-"), "two checks of an area with one name are not numbered by place, or a name is longer than the menu keeps: %r" % kinds)
    # ---- collected: a line ends with its actor's hash, and the game's side reads the flag of that key ----
    keyed = seed.check_lines([("Market", (1.0, 2.0, 3.0), "C", seed.NONE, "Chest (red rupee)", 0x86f700bfe72c18fc)], [("Market", (4.0, 5.0, 6.0), "C", seed.NONE, "Gold Skulltula", 0x1f)],
                             [("Market", (7.0, 8.0, 9.0), "C", seed.NONE, "the dog lady")])
    check(keyed[1:] == ["Market|Chest (red rupee)|Market|C|1.0 2.0 3.0|-|86f700bfe72c18fc", "Market|Gold Skulltula|Market|C|4.0 5.0 6.0|-|000000000000001f",
                        "Market|The dog lady|Market|C|7.0 8.0 9.0|-"], "a line does not end with its actor's hash, or a gift's has one: %r" % keyed[1:])
    given = seed.check_lines([("Market", (1.0, 2.0, 3.0), "C", seed.NONE, "Chest (red rupee)", 0x86f700bfe72c18fc, "Item_Hammer")], [],
                             [("Market", (7.0, 8.0, 9.0), "C", seed.NONE, "the dog lady", None, "TBox_Rupee_Blue"), ("Market", (7.0, 8.0, 9.5), "C", seed.NONE, "the gallery")])
    check(given[1:] == ["Market|Chest (red rupee)|Market|C|1.0 2.0 3.0|-|86f700bfe72c18fc|Item_Hammer", "Market|The dog lady|Market|C|7.0 8.0 9.0|-|-|TBox_Rupee_Blue",
                        "Market|The gallery|Market|C|7.0 8.0 9.5|-"], "a line does not end with the item it gives, after its hash or a dash: %r" % given[1:])
    check('named("Chest", h, spots[h][0], spots[h][5], spots[h][1]), h, gives[h],' in script and
          'named("Gold Skulltula", h, skulls[h][0], skulls[h][1]), h, skull_drops.get(h) or drops.get(h) or TOKEN)' in script and
          "needs[h], g.name, None, gives[h])" in script and "needs[h], gifts[h].name, None, gives[h])" in script,
          "what the chests, the Gold Skulltulas, the gifts and the shelves give is not written with the checks")
    items = (ROOT / "gpu" / "vk" / "oot_cheat_items.h").read_text(encoding="utf-8")
    m = re.search(r"#define OOT_TRACKER_MAX (\d+)", items)
    check(m and int(m.group(1)) == seed.CHECK_ROWS and "#define OOT_TRACKER_BASE 8192" in items and
          "static_assert(kTrackerChecks == OOT_TRACKER_MAX" in menu, "the game's side does not report as many checks as the script writes and the menu keeps")
    host_text = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    check('"%47[^|]|%79[^|]|%39[^|]|%3[^|]|%f %f %f|%95[A-Z,-]|%31[0-9a-fA-F-]|%63[A-Za-z0-9_]"' in host_text and "if (got < 7) continue;" in host_text and
          "rx_option_set(OOT_TRACKER_BASE + i, oot_checks[i].done == 1);" in host_text,
          "the game's side does not take the lines the menu takes, in their order, with what each gives")
    check("if (oot_checks[i].done == 1 || strcmp(oot_checks[i].item, name)) continue;" in host_text and
          "if (best >= 0 && nearest > OOT_CHECK_NEAR) best = -1;" in host_text and "if (!oot_banc_in_folder(oot_link_map, oot_checks[i].folder)) {" in host_text and
          "c->x[30] != 0x8112d4b8ULL && c->x[30] != 0x8112f998ULL && c->x[30] != 0x8112e19cULL && (uint32_t)c->x[4] != 9)" in host_text,
          "an item given does not mark the nearest check of Link's map that gives it, or a save's load, an add inside another or the debug inventory's marks one")
    check('if (!strncmp(line, "seed ", 5) && !strcmp(line + 5, oot_checks_seed))' in host_text and 'fprintf(f, "seed %s\\n", oot_checks_seed);' in host_text and
          "if (oot_check_count < 0 || strcmp(stamp, oot_checks_seed)) oot_tracker_load(stamp);" in host_text and
          "} else if (action == 6) {" in host_text and "oot_tracker_forget();" in host_text,
          "the record is not kept with its seed's stamp, another seed's record is taken, or it cannot be forgotten")
    check("constexpr int kTrackerForgetAction = 6;" in menu and "cheat_action.store(kTrackerForgetAction);" in menu and
          "if (tracker_forget_asked && now - tracker_forget_asked < kTrackerForgetMs) {" in menu and '"Press again to forget what is collected"' in menu,
          "the first row does not forget the record at its second confirm, or forgets it at the first")
    check("TEMP-" not in host_text and "oot_flag64" not in host_text and "if (!hos_rando_on()) return;" in host_text,
          "a search for the game's flags is still in the game, or the checks are reported with the randomizer off")
    check("if (id >= OOT_TRACKER_BASE && id < OOT_TRACKER_BASE + kTrackerChecks) {" in menu and
          'collected ? ": done" : state > 0 ? ": in logic" : state == 0 ? ": not in logic" : ""' in menu and
          "if (done == 1) continue;   // (a check collected is not one to go for)" in menu and '(n == 1 ? " check" : " checks")' in menu and
          "for (auto& done : tracker_done) done.store(-1, std::memory_order_relaxed);" in menu,
          "the tab does not say a check is done, counts one collected among those in logic, or takes a check for collected before the game says so")
    # ---- where Link is put to go to a chest: before it ----
    front = seed.chest_front
    check(front((-54.2, 112.3, -40.9), (0.0, 0.83, 0.0)) == (-53.2, 112.3, -40.0) and front((-49.3, 112.3, -40.9), (0.0, -0.78, 0.0)) == (-50.2, 112.3, -40.0),
          "the two end chests of Mido's house are not gone to before them, towards the room's middle: %r %r" % (
              front((-54.2, 112.3, -40.9), (0.0, 0.83, 0.0)), front((-49.3, 112.3, -40.9), (0.0, -0.78, 0.0))))
    check(front((0.0, 5.0, 0.0), (0.0, 0.0, 0.0)) == (0.0, 5.0, 1.3) and front((0.0, 5.0, 0.0), (3.14159265, 0.0, 3.14159265)) == (0.0, 5.0, -1.3) and
          front((0.0, 5.0, 0.0), (0.0, 1.57079633, 0.0), 2.0) == (2.0, 5.0, 0.0),
          "a chest's front is not its +Z turned as the chest is")
    stood = seed.check_lines([("Market", (1.0, 2.0, 3.0), "C", seed.NONE, "Chest (red rupee)", 0x1f, "Item_Hammer", (1.0, 2.0, 4.3)),
                              ("Market", (5.0, 2.0, 3.0), "C", seed.NONE, "Chest (blue rupee)", None, "", (5.0, 2.0, 4.3))], [])
    check(stood[1:] == ["Market|Chest (blue rupee)|Market|C|5.0 2.0 3.0|-|-|-|5.0 2.0 4.3", "Market|Chest (red rupee)|Market|C|1.0 2.0 3.0|-|000000000000001f|Item_Hammer|1.0 2.0 4.3"],
          "a line does not end with where Link is put, after its hash and its item or a dash for each: %r" % stood[1:])
    check('chest_front(spots[h][5], about[h]["turned"]) if len(spots[h][5]) == 3 and "turned" in about.get(h, {}) else None)' in script and
          'was.setdefault("turned", words.get("Rotate", (0.0, 0.0, 0.0)))' in script, "a chest's front is not written with its line")
    # ---- what the tab shows: all, the ones left, the ones left and in logic ----
    check("if (tracker_done[i].load(std::memory_order_relaxed) == 1) return false;" in menu and
          "return tracker_show != kTrackerShowReachable || tracker_in_logic(tracker_checks[i]) != 0;" in menu and
          "if (tracker_show == kTrackerShowAll) return true;" in menu,
          "a check collected is shown when those are hidden, one out of logic when only the reachable are, or one is hidden when all are shown")
    check("if (!strcmp(tracker_checks[i].area, tracker_name[row]) && tracker_check_shown(i) && !--n) return &tracker_checks[i];" in menu and
          "!(rows[i].tracker > 0 && tracker_row_hidden(rows[i].tracker)) &&" in menu and
          "return row > 0 && tracker_show != kTrackerShowAll && tracker_row_checks(row, true) > 0 && !tracker_row_checks(row);" in menu,
          "a check not shown is stepped to, or an area with none to show keeps its row, or the whole game's row is hidden")
    check("tracker_show = (tracker_show + kTrackerShows + (press[4] ? 1 : -1)) % kTrackerShows;" in menu and
          "for (int r = 1; r < kTrackerRows; r++) tracker_pick[r] = 0;" in menu and 'words += std::string(". Showing: ") + kTrackerShowWords[tracker_show];' in menu and
          '{"all", "left to collect", "left and in logic"}' in menu,
          "the first row's Left and Right do not choose what the tab shows, a row stays stepped to a check that is another now, or the row does not say what is shown")
    made = [name("Chest", item, {}, ()) for item in seed.ITEM_WORDS]
    check(all(len(n) <= seed.CHECK_NAME - 40 for n in made) and set(seed.PROGRESSION) <= set(seed.ITEM_WORDS) and set(seed.DUNGEON_ITEMS) <= set(seed.ITEM_WORDS),
          "a gating item or a dungeon's item has no words for a chest's name")
    block = menu[menu.index("void tracker_load() {"):menu.index("tracker_check_count = checks;")]
    check("named = lambda kind, h, area, pos, item=\"\": check_name(kind, item, about.get(h, {}), pos, exits[area], sub_areas[area])" in script and
          "for h, gyaml, pos, scale, words in marks(data):" in script and "%79[^|]" in block,
          "the checks are not written with their names, or the menu does not read a name whole")
    check(set(seed.CHECK_CODES) == set(seed.PROGRESSION | seed.QUEST_GATES | seed.SHOP_GATES | seed.SONG_GATES) and len(set(seed.CHECK_CODES.values())) == len(seed.CHECK_CODES),
          "a gating item of the rules has no letters for the tracker, or two have the same")
    codes = re.findall(r'^    \{"([A-Z]{2})", "[^"]+", \{[^}]+\}\},$', menu, re.M)
    check(codes == list(seed.CHECK_CODES.values()), "the menu's gating items are not the script's letters: %r" % codes)
    names = set(re.findall(r'OOT_ITEM\("([^"]+)"', (ROOT / "gpu" / "vk" / "oot_cheat_items.h").read_text(encoding="utf-8")))
    block = menu[menu.index("constexpr LogicItem kLogicItems[] = {"):menu.index("int tracker_in_logic(const TrackerCheck& k, std::string* missing) {")]
    rows_named = set(re.findall(r'"([^"]+)"', "".join(re.findall(r", \{([^}]+)\}\},", block))))
    check(rows_named and rows_named <= names, "a gating item's row is not a row of the Inventory page: %r" % sorted(rows_named - names))
    check("if (k.needs[0] == '?' || item_counts[0].load(std::memory_order_relaxed) < 0) return -1;" in menu and
          'state > 0 ? ": in logic" : state == 0 ? ": not in logic" : ""' in menu and 'words += ", " + std::to_string(in) + " in logic";' in menu and
          "if (selr.tracker >= 0 && !(tracker_line = tracker_hint(selr.tracker)).empty()) hint = tracker_line.c_str();" in menu,
          "the tab does not say whether a check is in logic, or says so of a check it knows nothing of")
    check(all(line.split("|")[0] in {t.split("|")[0] for t in seed.tracker_lines({"KokiriForest": 2, "ZoraRiver": 1}, {"KokiriForest": 1})}
              for line in lines[1:]), "a check's area is not the name of its tracker row")
    check(len(seed.check_lines([("Market", (float(k), 0.0, 0.0), "C", seed.NONE) for k in range(400)], [])) == 1 + seed.CHECK_ROWS,
          "more checks are written than the menu keeps")
    check(seed.check_ages({"KokiriForest_Child_Static.bcett.byml.zs"}) == "C" and seed.check_ages({"LostWood_Adult_Dynamic.bcett.byml.zs"}) == "A" and
          seed.check_ages({"A_Child_Static", "A_Adult_Static"}) == "CA" and seed.check_ages({"FireTemple_Static.bcett.byml.zs"}) == "CA" and
          seed.check_ages(set()) == "", "the ages whose map has a check are not read from its files' names")
    check('with open(os.path.join(mod, CHECKS), "w", encoding="utf-8", newline="\\n") as f:' in script and seed.CHECKS == "checks.txt" and
          '" checks 9" +' in script, "the checks' file is not written with the seed, or a seed made before it is not made again")
    m = re.search(r"constexpr int kTrackerChecks = (\d+);", menu)
    check(m and int(m.group(1)) == seed.CHECK_ROWS, "the menu does not keep as many checks as the script may write")
    check('"%47[^|]|%79[^|]|%39[^|]|%3[^|]|%f %f %f|%95[A-Z,-]|%31[^|]|%63[^|]|%f %f %f"' in menu and "char area[48], kind[80], folder[40], ages[4];" in menu and seed.CHECK_NAME == 79 and '+ "checks.txt";' in menu, "the menu does not read the checks' file as it is written")
    check("if (press[3] || press[4]) tracker_pick[row] = (tracker_pick[row] + n + 1 + (press[4] ? 1 : -1)) % (n + 1), changed = true;" in menu and
          "else if (r.tracker >= 0) tracker_press(r.tracker, press, changed);" in menu,
          "Left and Right do not step through a row's checks and back to its own words")
    check("if (hit.side != 0) press[hit.side < 0 ? 3 : 4] = true;" in menu and "else if (tracker_pick[d.tracker]) press[7] = true;" in menu,
          "a click on a Tracker row's arrows goes to the check instead of stepping (seen in play), or its name does not go there")
    check("const TrackerCheck* k = press[7] && cheats_on() ? tracker_row_check(row, tracker_pick[row]) : nullptr;" in menu and
          '"rando\\\\goto_check.txt"' in menu and "cheat_action.store(kTrackerGoAction);" in menu and
          'fprintf(f, "%.2f %.2f %.2f %s %s\\n", k->stand[0], k->stand[1] + 1.0f, k->stand[2], k->folder, k->ages);' in menu and
          "if (got < 13) memcpy(k.stand, k.pos, sizeof k.stand);" in menu,
          "confirm does not send the check shown to the game, or does so with the debug tools off")
    host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    m = re.search(r"constexpr int kTrackerGoAction = (\d+);", menu)
    check(m and "if (action == %s && hos_rando_on()) {" % m.group(1) in host and '"goto_check.txt"' in host and
          'fscanf(f, "%f %f %f %39s %7s"' in host, "the game does not take the menu's action, or reads the check otherwise than it is written")
    check("else if (oot_teleport(c, actor, index)) check.waiting = 1" in host and "} else if (oot_banc_in_folder(current, check.folder)) {" in host and
          "!strchr(check.ages, child ? 'C' : 'A')" in host and
          "} else if (!oot_banc_in_folder(current, check.folder) || loading || oot_event_playing(c)) {" in host,
          "the game does not go to the check's map first, or takes the place before Link has arrived, or at an age whose map has not the check")
    check('"No seed"' in menu and "now - last < 1000" in menu, "the tab says nothing without a seed, or reads its file every frame")
    print("PASS: the randomizer's Tracker tab")


if __name__ == "__main__":
    main()
