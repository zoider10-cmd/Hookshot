"""A seed's saves are apart from the game's own: <user>/save_rando while the randomizer is on, <user>/save otherwise.

host/oot_rando.c's hos_save_folder is cut out and run against options files (off, on, a seed ID from the environment),
and the sources are checked for the rest of the path: every place the game names its save folder asks it (the three
save mounts of host/nn_fs.c, and the SAVE FOLDER import of host/hos_main.c), and the launcher's Saves button opens the
folder the next Play uses.

    python -I -B tests/test_rando_saves.py [--cc gcc]
"""
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "@HEADER@"
#define MAX_PATH 260
typedef unsigned long DWORD;
static const char *game_exe;
static DWORD hos_game_path_a(char *out, DWORD n) { snprintf(out, n, "%s", game_exe); return (DWORD)strlen(out); }
static void hos_log(const char *f, ...) { (void)f; }
/* (host/master_quest.c: the launcher's Master Quest button sets HOS_MASTER_QUEST=1) */
int hos_master_quest(void) { const char *e = getenv("HOS_MASTER_QUEST"); return e && e[0] == '1'; }
@HOST@
int main(int argc, char **argv) {
    if (argc < 2) return 2;
    game_exe = argv[1];
    const char *first = hos_save_folder();
    if (argc > 2) {   /* (the answer is the start's: a file changed while the game runs does not move the saves) */
        FILE *f = fopen(argv[2], "w");
        if (!f) return 3;
        fputs("rando_on=1\n", f);
        fclose(f);
        if (strcmp(first, hos_save_folder())) return 4;
    }
    puts(first);
    return 0;
}
'''


def check(ok, what):
    if not ok:
        raise SystemExit("FAIL: " + what)


def block(source, marker):
    """the function that starts at marker, to its closing brace in the first column"""
    start = source.index(marker)
    return source[start:source.index("\n}\n", start) + 3]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    read = lambda *parts: ROOT.joinpath(*parts).read_text(encoding="utf-8")
    side, fs, boot, launcher = read("host", "oot_rando.c"), read("host", "nn_fs.c"), read("host", "hos_main.c"), read("launcher", "Launcher.cs")

    # ---- the sources ----
    check(fs.count("hos_save_folder()") == 3 and not re.search(r'"(%s\\\\)?save\\\\%016llx', fs),
          "host/nn_fs.c: a save mount names the save folder itself: the randomizer's saves and the game's own would be one folder there")
    for name in ("IsSaveDataExisting", "13MountSaveDataEPKc", "21MountSaveDataReadOnly"):
        at = fs.index(name)
        check("hos_save_folder()" in fs[at:fs.index("\n}\n", at)], "host/nn_fs.c: %s does not ask which save folder" % name)
    imp = block(boot, "static void save_folder_import(")
    check(imp.count("hos_save_folder()") == 2 and '"%s\\\\save"' not in imp and "%s\\\\save\\\\5a3c" not in imp,
          "host/hos_main.c: the SAVE FOLDER import does not go into the saves this start plays with")
    check('string SaveFolder() { return settings.ContainsKey("rando_on") && settings["rando_on"].Value != 0 ? "save_rando" : "save"; }' in launcher and
          'OpenFolder(Path.Combine(dir, "user", SaveFolder()))' in launcher, "the launcher's Saves button does not open the folder the next Play uses")
    check('if (hos_master_quest()) return "save_mq";' in side and 'if (hos_master_quest() && !_stricmp(mods[i].name, "rando-seed")) {' in read("host", "mods.c"),
          "Master Quest does not keep its saves apart, or loads the randomizer's seed over its own dungeons")
    check('return on ? "save_rando" : "save";' in side, "host/oot_rando.c: the two folders are not save and save_rando, which the launcher opens")

    # ---- the function, run ----
    host = block(side, "static void rando_read(") + "\n" + block(side, "const char *hos_save_folder(void) {")
    fixture = FIXTURE.replace("@HEADER@", (ROOT / "gpu" / "vk" / "oot_rando.h").as_posix()).replace("@HOST@", host)
    with tempfile.TemporaryDirectory(prefix="rando-saves-") as tmp:
        c, exe = Path(tmp) / "fixture.c", Path(tmp) / ("fixture.exe" if os.name == "nt" else "fixture")
        c.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe)], check=True)

        def folder(lines, env=None, change=False):
            game = Path(tempfile.mkdtemp(dir=tmp))
            ini = game / "hookshot_options.ini"
            if lines is not None:
                ini.write_text(lines, encoding="utf-8")
            run_env = dict(os.environ)
            run_env.pop("HOS_RANDO_SEED_ID", None)
            run_env.update(env or {})
            args = [str(exe), str(game / "hookshot.exe")] + ([str(ini)] if change else [])
            out = subprocess.run(args, env=run_env, capture_output=True, text=True)
            check(out.returncode == 0, "the fixture stopped with %d" % out.returncode)
            return out.stdout.strip()

        check(folder(None) == "save", "no options file: the game's own saves")
        check(folder("rando_on=0\nrando_seed=7\nrando_chests=3\n") == "save", "the randomizer off, whatever its settings: the game's own saves")
        check(folder("fullscreen=1\nrando_on=1\nrando_seed=7\n") == "save_rando", "the randomizer on: the randomizer's saves")
        check(folder("rando_on=0\n", change=True) == "save", "the randomizer turned on while the game runs moved the saves")
        # (a seed ID from the environment, as test runs give one, turns the randomizer on: oot_rando_from_id)
        check(folder("rando_on=0\n", env={"HOS_RANDO_SEED_ID": "HVBQ4-TY300-800RD"}) == "save_rando", "a seed ID from the environment: the randomizer's saves")
        check(folder("rando_on=0\n", env={"HOS_RANDO_SEED_ID": "not an id"}) == "save", "a seed ID that is not one leaves the game's own saves")
        # (Master Quest, Mako 3.5: its own saves, whatever the randomizer's switch says, and the normal ones without it)
        check(folder("rando_on=1\nrando_seed=7\n", env={"HOS_MASTER_QUEST": "1"}) == "save_mq" and folder("rando_on=0\n", env={"HOS_MASTER_QUEST": "1"}) == "save_mq",
              "Master Quest does not keep its own saves")
        check(folder("rando_on=1\nrando_seed=7\n", env={"HOS_MASTER_QUEST": "0"}) == "save_rando", "the randomizer's saves are not its own when Master Quest is off")
    print("PASS: the randomizer's saves")


if __name__ == "__main__":
    main()
