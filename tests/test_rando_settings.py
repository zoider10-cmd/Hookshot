"""The randomizer's settings (gpu/vk/oot_rando.h): the seed IDs and the options file's rando_ lines, compiled and run
(tests/test_rando_settings.cpp), the header compiled as C too (the game side is C: host/oot_rando.c), and the sources
checked for the rest of the path: the launcher's Randomizer page writes the lines with the header's choices and makes
a seed's ID as the header does, the Insert menu (which has no Randomizer tab since Mako 3.3) keeps those lines when it
saves and has the Fast forward row, and the game side reads them at its start.

    python -I -B tests/test_rando_settings.py [--cxx g++] [--cc gcc]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "g++", "--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]


def read(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def check(ok, what):
    if not ok:
        raise SystemExit("FAIL: " + what)


def table():
    """The header's settings: (NAME, label, key, help, [choices])"""
    header = read("gpu", "vk", "oot_rando.h")
    body = header[header.index("#define OOT_RANDO_SETTINGS(X)"):header.index("enum {")].replace("\\\n", " ")
    rows = []
    for name, rest in re.findall(r'X\((\w+),((?:\s*"[^"]*",?)+)\)', body):
        text = re.findall(r'"([^"]*)"', rest)
        rows.append((name, text[0], text[1], text[2], text[3:]))
    check(len(rows) >= 3 and body.count("X(") == len(rows), "the settings table was not read whole")
    return rows


def sources(rows):
    menu, menu_h, launcher = read("gpu", "vk", "vk_menu.cpp"), read("gpu", "vk", "vk_menu.h"), read("launcher", "Launcher.cs")
    main, side = read("host", "hos_main.c"), read("host", "oot_rando.c")
    api = None
    # ---- the Insert menu: no Randomizer tab since Mako 3.3 (its menu was written anew), and it keeps the lines ----
    check("TAB_RANDO" not in menu and "rando" not in menu_h, "the menu has randomizer rows again: this test and the launcher's page say it has none")
    saving = menu[menu.index("void save() {"):]
    saving = saving[:saving.index("\n}")]
    check("if (!mine) others += line" in saving and "fputs(others.c_str(), f);" in saving,
          "the menu no longer keeps the options file's lines that are not its own: the randomizer's would be dropped at its next save")
    # (the fast forward is a row of the new menu, under a number of its own: 18 is 3.3's gyro)
    api = read("gpu", "vk", "vk_api.h")
    check('{TAB_GAMEPLAY, "Fast forward", &opts.fast_forward, 0, 2, 1, tx_fast_forward,' in menu and "HOS_OPT_FAST_FORWARD = 48" in api and
          "HOS_OPT_GYRO = 18" in api, "the menu has no Fast forward row, or its option number is another's")
    check("if (id == HOS_OPT_FAST_FORWARD) return opts.fast_forward;" in read("gpu", "vk", "vk_replay.cpp") and
          "rx_option(HOS_OPT_FAST_FORWARD, 0)" in read("host", "nn_vi.c"), "the fast forward's setting does not reach the game's clock")
    # ---- the launcher: the same lines, labels and choices, in the same order ----
    block = launcher[launcher.index("static readonly object[][] RandoRows = {"):]
    block = block[:block.index("\n    };")]
    found = re.findall(r'new object\[\] \{ "(\w+)", "([^"]*)", new\[\] \{ ([^}]*) \}, new\[\] \{ ([^}]*) \},\s*"([^"]*)" \}', block)
    check(found and found[0][0] == "rando_on" and found[0][2] == '"Off", "On"', "the launcher's Randomizer page has no on / off selector")
    want = [(key, label, choices, list(range(len(choices))), help_) for _, label, key, help_, choices in rows]
    got = [(key, label, re.findall(r'"([^"]*)"', choices), [int(v) for v in values.split(",")], help_)
           for key, label, choices, values, help_ in found[1:]]
    check(got == want, "the launcher's Randomizer page and gpu/vk/oot_rando.h differ:\n  %r\n  %r" % (got, want))
    # (the settings a seed does nothing with yet cannot be picked: the page's rows, its list, a pasted ID or an older
    #  file's value, and the New seed window)
    not_yet = re.search(r"RandoNotYet = new Dictionary<string, int> \{\s*([^;]*?) \};", launcher)
    limits = dict((k, int(n)) for k, n in re.findall(r'\{ "(\w+)", (\d+) \}', not_yet.group(1))) if not_yet else {}
    rando_seed = read("tools", "rando", "rando_seed.py")
    songs_made = "\nSONGS_ANYWHERE = True\n" in rando_seed
    check(songs_made or "\nSONGS_ANYWHERE = False\n" in rando_seed, "the script no longer says whether Songs' Anywhere is offered")
    check(limits.get("rando_dungeon_rewards") in (1, 2) and limits.get("rando_keys") == 2 and
          set(limits) == {"rando_dungeon_rewards", "rando_keys"} | (set() if songs_made else {"rando_songs"}) and limits.get("rando_songs", 2) == 2,
          "the launcher's list of settings not available yet is not the ones known, or Songs' Anywhere is offered while the script holds it "
          "off (SONGS_ANYWHERE), or held off while the script makes it (%r)" % limits)
    # (the frogs are no longer a choice: the row is kept for a seed's ID and shown nowhere, and Quest rewards says so)
    check('RandoHidden = new HashSet<string> { "rando_frogs" };' in launcher and "Page = hidden ? NoPage : page" in launcher and
          "if (!hidden) place++;" in launcher and "if (LauncherForm.RandoHidden.Contains(key)) continue;" in launcher and
          "the frogs of Zora's River among them" in launcher,
          "the Frogs row is still shown on the page or in the New seed window, or Quest rewards does not name the frogs")
    check("Most of the logic (what each place asks for) is taken from the original game's" in launcher,
          "the Randomizer switch no longer says where the logic is from")
    check(all(key in {f[0] for f in found} for key in limits), "a setting listed as not available yet is not a row of the page")
    check("if (RandoNotYet.ContainsKey(s.Key)) s.Limit = RandoNotYet[s.Key];" in launcher and "i = Math.Max(0, Math.Min(Last, i));" in launcher and
          "for (int i = 0; i <= s.Last; i++) {" in launcher and "best = Math.Min(best, s.Last);" in launcher and
          "if (Last == 0) return;" in launcher and "int choices = LauncherForm.RandoChoices(key, names.Length);" in launcher and
          "if (choices <= 1) { box.Items.Add(Selector.NotYet); box.Enabled = false;" in launcher,
          "a setting not available yet can still be picked on the page, from its list, by a pasted ID or in the New seed window")
    check('2, one in any item\'s place, is not made yet: as 1' in rando_seed,
          "Dungeon rewards' Anywhere is made now: take it off the launcher's list of settings not available yet")
    check("a.songs = (a.songs if SONGS_ANYWHERE else 1) if a.songs in (1, 2) else 0" in rando_seed,
          "the script makes Songs' Anywhere though it is held off, or no longer reads the setting")
    check("AddSelectors(RandoRows, RandoPage, cx, colW, null, 47, 45, true);" in launcher and
          '"Home", "Graphics", "Game", "Randomizer", "Cosmetics", "Mods", "More"' in launcher and "int[] firstPage = { 0, 1, 2, RandoPage, CosmeticPage, 7, 3 };" in launcher and
          "public const int RandoPage = 9, CosmeticPage = 10;" in launcher and
          # (Mako 4.1's Mods tab renames every mod's folder: the seed's and the colours' are the launcher's own, and not in its list)
          'public static readonly string[] Own = { "rando-seed", "cosmetics" };' in (ROOT / "launcher" / "Mods.cs").read_text(encoding="utf-8"),
          "the launcher does not show its Randomizer page")
    # (more settings than the page has room for: the list scrolls, and a row is shown, lit and pressed only inside its view)
    check("if (PageNow == RandoPage) ScrollRando(-e.Delta * 47f / 120);" in launcher and "g.SetClip(RandoView, CombineMode.Intersect);" in launcher and
          "w.Hit(p) && InView(w, p)) return w;" in launcher and "foreach (var w in widgets) if (w.Scrolls) w.R.Y = w.HomeY - randoScroll;" in launcher,
          "the Randomizer page's list does not scroll by the wheel, is drawn over the seed's buttons, or a row scrolled out of view can be pressed")
    check('lines[i] = k + "=" + randoSeed;' in launcher and 'lines.RemoveAll(l => l.StartsWith("rando_import="))' in launcher,
          "the launcher does not keep the seed, or leaves an import that would undo its settings")
    # ---- the game side ----
    check("if (!RunRandomizer()) return;" in launcher and 'RunAtPlay("rando_seed.py", "rando-seed", on,' in launcher and 'Path.Combine(dir, "rando", name)' in launcher and "--if-changed" in launcher,
          "the launcher does not place the seed at Play")
    make = read("nx2", "make_game.py")
    check('os.path.join(ROOT, "tools", "rando", "rando_seed.py")' in make and 'os.path.join(out, "rando", "rando_seed.py")' in make,
          "the build does not put the randomizer's script beside the game, where the launcher runs it")
    script = read("tools", "rando", "rando_seed.py")
    check(all('"%s"' % key in script for key in ("rando_on", "rando_seed", "rando_chests", "rando_skulltulas", "rando_keys", "rando_major", "rando_open_deku",
                                                    "rando_open_forest", "rando_skip_intro", "rando_quests", "rando_frogs", "rando_light_arrows", "rando_start_rupees", "rando_scrubs", "rando_shops", "rando_shop_shelves", "rando_sword_shield", "rando_dungeon_rewards", "rando_progressive")),
          "rando_seed.py does not read the settings the menu keeps")
    check("hos_rando_init();" in main, "the game does not read the randomizer's settings at its start")
    # ---- Skip cutscenes: the game's own skip, asked of a cutscene's player only ----
    host = read("host", "hos_main.c")
    check("int hos_rando_skip_cutscenes(void) { return rando_active && rando.v[OOT_RANDO_SKIP_CUTSCENES] != 0; }" in side and
          '"rando_skip_cutscenes"' in launcher and 'X(SKIP_CUTSCENES, "Skip cutscenes", "rando_skip_cutscenes",' in read("gpu", "vk", "oot_rando.h"),
          "Skip cutscenes is not a setting of the menu, the launcher and the game")
    check("const int cutscene = kind == OOT_TIMELINE_PLAYER;" in host and "#define OOT_MOVIE_PLAYER 0x84c82c88ULL" in host and
          "if (env == 2 || !cutscene || oot_cutscene_kept(name)) return;" in host and "    oot_skip_cutscene(c);" in host,
          "the skip is asked of a player that is not a cutscene (a flowchart skipped ends its event before its steps have run), or is not asked at all")
    check('static const char *const kept[] = {"Dm_Title", "Dm_StaffCredit", "Dm_Kokiri_0000", "Dm_SY_"};' in host,
          "the title, the credits, the opening narration or the game's system scenes are skipped")
    # (the scenes the game plays as flowcharts, Saria's first words and the owl's: the seed takes their talks, camera moves
    #  and waits out and keeps what they do. Seen without a window: the owl's Hyrule Field scene with no talk, in under 5 s)
    check('a.skip_cutscenes = a.skip_cutscenes or ini["rando_skip_cutscenes"] != 0' in script and '(" talks skipped" if a.skip_cutscenes else "")' in script and
          "now, taken = quiet_scene(was)" in script and "if struct.unpack_from(\"<H\", was, 0x20)[0] != 1:" in script and
          '"rando_skip_cutscenes": 0' in script and "list(shop_files.items()) + list(scene_files.items())" in script,
          "Skip cutscenes does not take the talks out of the scenes the game plays as flowcharts, or a seed made with it is not told apart")
    check('    "EventTalk", "EventTalkIgnoreSameTalkAS", "EventWait",' in script and 'SCENE_NOTHING = ("EventDemoProductSupportComment", "EventDoNothing")' in script and
          '("Dm_SY_Ocarina", "LearningOcarinaFollowExample")' in script and 'SCENE_KEEP = ("Dm_MelodyGet_Sun",)' in script and
          "if stem in SCENE_KEEP or any(" in script and '"Dm_FairyFountain_"' in script and 'SCENE_CHOICE = ("EventQueryTalkChoice2", "EventQueryTalkChoice3", "EventQueryTalkChoice4")' in script and
          all('"%s"' % w not in script.split("SCENE_SHOWS = frozenset((")[1].split("))")[0] for w in (
              "EventTriggerSetGameDataBool", "EventTriggerSetGameDataInt", "EventTriggerAddOrRemovePouchContent", "EventTransition", "EventEventFadeOut",
              "EventEventFadeIn", "EventPlayerWarpToTargetPosAndRot", "EventWarpToTargetPosAndRot", "EventExecuteProgressChallengeStep", "EventTrigger_SetTime")),
          "a scene's step that changes the game is taken out with its talks, or the scenes where Link answers or plays are not kept")
    # (the videos: a player of their own that the game's skip does nothing to, seen without a window; the seed passes
    #  over the step that starts each of the story's. Seen in the owner's play: the goddesses' story played whole)
    check('SCENE_VIDEOS = ("Dm_HrlCastle_0045",' in script and "now, left_out = pass_videos(was, SCENE_VIDEOS)" in script and
          all('"%s"' % v not in script.split("SCENE_VIDEOS = (")[1].split(")")[0] for v in ("Dm_Kokiri_0000", "Dm_Title_0005", "Dm_StaffCredit_0000", "Dm_MelodyGet_Sun_01")) and
          "elif kind in (1, 5):" in script and 'struct.pack_into("<H", out, s["at"] + 0x0a, len(left))' in script and "return lead_past(data, steps, firsts, passed, answer), talks" in script,
          "the story's videos are not left out with Skip cutscenes, or the title's, the credits', the narration or the tomb's are")
    check("Saria's first words, the owl's" in launcher and "Saria's first words, the owl's" in read("gpu", "vk", "oot_rando.h"),
          "the setting's words do not say that the talk scenes lose their talk")
    check("oot_rando_read(f, r, &bad)" in side and '"hookshot_options.ini"' in side and "const OotRando *hos_rando(void)" in side,
          "host/oot_rando.c does not read the options file")
    check("rando_seed.py" in side and "not placed yet" in side, "the log no longer says what places the chests and that the other settings do nothing yet")
    check((ROOT / "tools" / "rando" / "rando_seed.py").is_file(), "tools/rando/rando_seed.py, which the log names, is gone")
    # ---- a seed's ID: made and read in the launcher as the header does (the menu's tab did it before) ----
    check("static class RandoId {" in launcher and 'Text = "Copy seed ID"' in launcher and 'Text = "Paste seed ID"' in launcher and
          'const string Alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";' in launcher and "const int Bits = 75, Check = 8, Slots = 16, FormatVersion = 1;" in launcher and
          "const int LongBits = 100, LongSlots = 28, LongVersion = 2;" in launcher and
          "for (int i = Slots; i < LongSlots; i++) longer |= Choice(choices, i) != 0;" in launcher and
          "if (n != Bits && n != LongBits) return" in launcher and "if (longer && Get(bits, ref n, 1) != 0) return" in launcher,
          "the launcher does not make, copy and paste a seed's ID as gpu/vk/oot_rando.h has it")
    header = read("gpu", "vk", "oot_rando.h")
    check('return "0123456789ABCDEFGHJKMNPQRSTVWXYZ";' in header and "OOT_RANDO_ID_VERSION = 1," in header and "OOT_RANDO_ID_SLOTS = 16," in header and
          "OOT_RANDO_ID_BITS = 75," in header and "OOT_RANDO_ID_CHECK = 8," in header and "OOT_RANDO_ID_LONG_VERSION = 2," in header and
          "OOT_RANDO_ID_LONG_SLOTS = 28," in header and "OOT_RANDO_ID_LONG_BITS = 100," in header, "the header's seed ID is no longer the one the launcher makes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    sources(table())
    with tempfile.TemporaryDirectory(prefix="rando-settings-") as tmp:
        exe = Path(tmp) / "rando-settings"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(ROOT / "tests" / "test_rando_settings.cpp"),
                        "-o", str(exe)], check=True)
        subprocess.run([str(exe), tmp], check=True)
        # (as C, as host/oot_rando.c takes it: the table, an ID and a file's lines used once each)
        (Path(tmp) / "hookshot_options.ini").write_text("rando_on=1\nrando_seed=9\n", encoding="utf-8")
        c_file = Path(tmp) / "as_c.c"
        c_file.write_text('#include "%s"\n'
                          "int main(void) {\n"
                          "    OotRando r, back;\n"
                          "    char id[OOT_RANDO_ID_TEXT];\n"
                          "    memset(&r, 0, sizeof r);\n"
                          "    r.seed = 7, r.v[OOT_RANDO_N - 1] = oot_rando_settings[OOT_RANDO_N - 1].count - 1;\n"
                          "    oot_rando_id(&r, id);\n"
                          "    if (oot_rando_from_id(id, &back) || back.seed != 7 || back.v[OOT_RANDO_N - 1] != r.v[OOT_RANDO_N - 1]) return 1;\n"
                          '    FILE *f = fopen("%s", "r");\n'
                          "    if (!f || oot_rando_read(f, &back, NULL) != 0 || !back.on || back.seed != 9) return 2;\n"
                          "    fclose(f);\n"
                          "    return 0;\n"
                          "}\n" % ((ROOT / "gpu" / "vk" / "oot_rando.h").as_posix(), (Path(tmp) / "hookshot_options.ini").as_posix()),
                          encoding="utf-8")
        c_exe = Path(tmp) / "as-c"
        subprocess.run([args.cc, "-std=c11", "-Wall", "-Werror", str(c_file), "-o", str(c_exe)], check=True)
        subprocess.run([str(c_exe)], check=True)
    print("PASS: the randomizer's settings")


if __name__ == "__main__":
    main()
