"""The randomizer's settings (gpu/vk/oot_rando.h): the seed IDs and the options file's rando_ lines, compiled and run
(tests/test_rando_settings.cpp), the header compiled as C too (the game side is C: host/oot_rando.c), and the sources
checked for the rest of the path: the Insert menu has a Randomizer tab with a row for each setting and keeps them in
the options file, the launcher's Randomizer page writes the same lines with the same choices, and the game side reads
them at its start.

    python -I -B tests/test_rando_settings.py [--cxx g++] [--cc gcc]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

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
    # ---- the Insert menu ----
    check("TAB_RANDO = 3" in menu and "TAB_COUNT = 4" in menu and '"CONTROLS", "RANDOMIZER"}' in menu, "the menu has no Randomizer tab")
    check("int rando[OOT_RANDO_N] = {};" in menu_h and "int rando_on = 0;" in menu_h and "int rando_seed = 0;" in menu_h,
          "the menu's options have no randomizer settings")
    check("OOT_RANDO_SETTINGS(OOT_RANDO_MENU_ROW)" in menu and '{TAB_RANDO, "Randomizer", &opts.rando_on, 0, 1, 1,' in menu and
          '{TAB_RANDO, "Seed", &opts.rando_seed, 0, OOT_RANDO_SEED_MAX, 1,' in menu, "the Randomizer tab lacks its rows")
    key = menu[menu.index("const char* ini_key(const Row& r) {"):]
    key = key[:key.index("\n}")]
    check('return "rando_on";' in key and 'return "rando_seed";' in key and "return oot_rando_settings[i].key;" in key,
          "the menu does not keep the randomizer's rows under the lines oot_rando.h reads")
    init = menu[menu.index("void menu_init() {"):]
    init = init[:init.index("\n}")]
    check("oot_rando_read(f, &r, nullptr)" in init and "if (imported) save();" in init, "the menu does not take a rando_import line")
    setter = menu[menu.index("void set_row(Row& r"):]
    setter = setter[:setter.index("\n}")]
    check(setter.index("r.tab == TAB_RANDO") < setter.index("opts.preset = 0;"), "a randomizer row changes the quality preset to Custom")
    # (the menu is as tall as its longest tab, and one taller than the window is not shown: one row more than Graphics
    # at most, which at the options page's width is as tall as the menu was before this tab)
    rows_text = menu[menu.index("Row rows[] = {"):menu.index("constexpr int kCheatsRow")]
    graphics = rows_text.count("{TAB_GRAPHICS,")
    rando = rows_text.count("{TAB_RANDO,") - 1 + len(rows)   # (the macro's row is one for each setting)
    check(rando <= graphics + 1, "the Randomizer tab has %d rows, the Graphics tab %d: the menu would be taller than it was" % (rando, graphics))
    check("menu_hit::tab_slot_w(s, (int)w, TAB_COUNT)" in menu and
          "menu_hit::options(mx, my, scale, mw, mh, TAB_COUNT," in menu, "the tab strip is not drawn and hit-tested for every tab")
    check("hover_tab == 3" not in menu and "kTabPrev ? 3" not in menu, "the previous-tab arrow's hover is a tab's number")
    # ---- the launcher: the same lines, labels and choices, in the same order ----
    block = launcher[launcher.index("static readonly object[][] RandoRows = {"):]
    block = block[:block.index("\n    };")]
    found = re.findall(r'new object\[\] \{ "(\w+)", "([^"]*)", new\[\] \{ ([^}]*) \}, new\[\] \{ ([^}]*) \},\s*"([^"]*)" \}', block)
    check(found and found[0][0] == "rando_on" and found[0][2] == '"Off", "On"', "the launcher's Randomizer page has no on / off selector")
    want = [(key, label, choices, list(range(len(choices))), help_) for _, label, key, help_, choices in rows]
    got = [(key, label, re.findall(r'"([^"]*)"', choices), [int(v) for v in values.split(",")], help_)
           for key, label, choices, values, help_ in found[1:]]
    check(got == want, "the launcher's Randomizer page and gpu/vk/oot_rando.h differ:\n  %r\n  %r" % (got, want))
    check("AddSelectors(RandoRows, 2, cx, colW);" in launcher and '"Game", "Randomizer", "Cosmetics", "AMD fixes", "About"' in launcher,
          "the launcher does not show its Randomizer page")
    check('lines[i] = k + "=" + randoSeed;' in launcher and 'lines.RemoveAll(l => l.StartsWith("rando_import="))' in launcher,
          "the launcher does not keep the seed, or leaves an import that would undo its settings")
    # ---- the game side ----
    check("if (!RunRandomizer()) return;" in launcher and 'RunAtPlay("rando_seed.py", "rando-seed", on,' in launcher and 'Path.Combine(dir, "rando", name)' in launcher and "--if-changed" in launcher,
          "the launcher does not place the seed at Play")
    make = read("nx2", "make_game.py")
    check('os.path.join(ROOT, "tools", "rando", "rando_seed.py")' in make and 'os.path.join(out, "rando", "rando_seed.py")' in make,
          "the build does not put the randomizer's script beside the game, where the launcher runs it")
    script = read("tools", "rando", "rando_seed.py")
    check(all('"%s"' % key in script for key in ("rando_on", "rando_seed", "rando_chests", "rando_keys", "rando_major")),
          "rando_seed.py does not read the settings the menu keeps")
    check("hos_rando_init();" in main, "the game does not read the randomizer's settings at its start")
    check("oot_rando_read(f, &r, &bad)" in side and '"hookshot_options.ini"' in side and "const OotRando *hos_rando(void)" in side,
          "host/oot_rando.c does not read the options file")
    check("rando_seed.py" in side and "rando_seed.py" in menu and "not placed yet" in side and "not placed yet" in menu,
          "the log and the menu no longer say what places the chests and that the other settings do nothing yet")
    check((ROOT / "tools" / "rando" / "rando_seed.py").is_file(), "tools/rando/rando_seed.py, which the menu names, is gone")


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
