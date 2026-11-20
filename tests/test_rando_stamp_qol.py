"""The settings that move no item on the stamp's second line (tools/rando/rando_seed.py QOL_STAMP, stamp_settings,
records_moved; asked for 2026-11-17: QoL settings changed on a save being played): no game data.

- Skip opening, Skip cutscenes, Starting rupees and Gold Skulltulas by day are taken out of the first line, and an older
  stamp's first line is compared without them, so turning one on or off keeps the seed's placement;
- the Tracker's records of the old first line are moved to the new one (their body kept), another seed's are not;
- the main writes them on the second line.

    python -I -B tests/test_rando_stamp_qol.py
"""
import importlib.util
import os
import re
import sys
import tempfile
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
    old = "placement 12 seed 5 chests 3 keys 0 major 1 logic 1 open 11 flags door 7 intro skipped talks skipped rupees 200 skulltulas 3 gated all quests 1 skulltulas by day checks 10"
    new = S.stamp_settings(old)
    check(new == "placement 12 seed 5 chests 3 keys 0 major 1 logic 1 open 11 flags door 7 skulltulas 3 gated all quests 1 checks 10",
          "the first line keeps a setting that moves no item, or lost another: %r" % new)
    check(S.stamp_settings(new) == new, "a line without them changes")
    with tempfile.TemporaryDirectory() as folder:
        for name, first in (("collected.txt", "seed " + old), ("junk.txt", "seed another seed")):
            with open(os.path.join(folder, name), "w", encoding="utf-8", newline="") as f:
                f.write(first + "\r\n3\r\n7\r\n")
        check(S.records_moved(folder, old, new) == 1, "not the one record of the seed was moved")
        with open(os.path.join(folder, "collected.txt"), encoding="utf-8", newline="") as f:
            check(f.read() == "seed " + new + "\r\n3\r\n7\r\n", "the record's first line is not the new stamp's, or its marks changed")
        with open(os.path.join(folder, "junk.txt"), encoding="utf-8", newline="") as f:
            check(f.read() == "seed another seed\r\n3\r\n7\r\n", "another seed's record was changed")
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check("rest = stamp_settings(rest)" in script and "was = stamp_settings(was_first) + \"\\n\"" in script and
          "stamp = stamp[:-1] + qol + \"\\n\"" in script and "records_moved(os.path.join(game, \"rando\"), was_first, stamp.split(\"\\n\")[0])" in script,
          "the main does not write those settings on the second line, compare without them, or move the records")
    launcher = (ROOT / "launcher" / "Launcher.cs").read_text(encoding="utf-8")
    keys = set(re.findall(r'"(rando_\w+)"', launcher[launcher.index("NoItemKeys = new HashSet<string> {"):launcher.index("static bool MovesNoItem")]))
    check({"rando_skip_intro", "rando_skip_cutscenes", "rando_start_rupees", "rando_skulltulas_day", "rando_hints", "rando_ageless"} <= keys and
          not keys & {"rando_chests", "rando_songs", "rando_letter", "rando_shops", "rando_open_door"} and
          'if ((a ?? "0") == (b ?? "0") || MovesNoItem(k + "=")) continue;' in launcher and "SeedChanges(dir, name).Count > 0" in launcher,
          "the launcher asks about another seed when only a setting that moves no item changed, or skips one that moves items")
    # (the game's side holds the stamp's whole first line: cut at 200 it never matched a record written with all of it)
    host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    size = int(re.search(r"static char oot_checks_seed\[(\d+)\];", host).group(1))
    line = int(re.search(r"    char path\[MAX_PATH \+ 48\], line\[(\d+)\];\s*static char kinds", host).group(1))
    check(size >= 1024 and line >= size + 8, "the game's side cuts a seed's stamp (%d) or its record's first line (%d) short" % (size, line))
    print("PASS: the settings that move no item are on the stamp's second line")


if __name__ == "__main__":
    main()
