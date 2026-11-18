"""A crash or kill while a setting is written never leaves a torn file (host/hos_atomic_file.h and the writers of the settings).

The settings were written with fopen "w", which empties the file before it writes it, and a settings file was put in place by a
copy made at its final name (the options' one-time copy into the user folder, the saves' move to another drive): a kill, a crash
or a power cut in the middle left an empty file or a part of one, and the next start took it for the player's settings.
tests/settings_atomic_test.c repeats those writes over the helper with a kill point at every step the helper takes; this test
runs it once to count the steps, then once per step with the process killing itself there (SIGKILL; TerminateProcess on
Windows), and looks at the folder:

- write: hos_atomic_write over a settings file (language.txt, mouse_sens.txt, saves-moved.txt are written so): after
  each kill the file is the old one or the new one, whole (every word one generation, the size of that generation), and after the
  next start's clean-up (hos_atomic_remove_stale) no ".hosnew" is left; the next write after the kill, with the stand-in still
  there, gives the new file. A first write (no file yet, language.txt's template): absent or whole.
- copy: hos_atomic_copy_file over a settings file, and to a name that is not there (the options' one-time copy into the user
  folder, each file the saves' move copies): the old file or the copy, whole; absent or whole.
- random kills: writes without end, killed at 60 random moments: every file whole.
- in place: a settings file that is a link, or sits in a folder nobody can make a file in (the file itself still writable), is
  written where it is, as before: the link stays a link, the setting is saved.
- control: the old ways (fopen "w", a copy made at the final name) torn at some kill steps, so the checks can see a tear.
- the sources: the writers of language.txt, mouse_sens.txt and saves-moved.txt, the options' one-time copy and the
  saves' move go through the helper and not through fopen "w" or CopyFileA, and the start removes the stand-ins
  (tests/test_options_path.py kills the options' copy at each of its steps and runs the start's clean-up).

    python -I -B tests/test_settings_atomic.py [--cc gcc]
"""
import argparse
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from array import array
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = os.name == "nt"
KILLED = (137,) if WINDOWS else (-signal.SIGKILL,)
SETTINGS = "settings.ini"
SIZES = (8000, 8004)   # (generation 1, later ones)
COPY_SIZE = 40000      # (source.ini, generation 1)


def build(cc, tmp):
    exe = tmp / ("settings_atomic_test" + (".exe" if WINDOWS else ""))
    flags = ["-std=gnu11", "-O1", "-Wall", "-Wextra", "-Werror"]   # (the helper and the fixture: no warning)
    if WINDOWS:
        subprocess.run([cc] + flags + ["-D_CRT_SECURE_NO_WARNINGS", str(ROOT / "tests/settings_atomic_test.c"), "-o", str(exe)], check=True)
    else:
        shim = tmp / "win32_posix.o"   # (the posix layer, as the game's Linux build has it: its own warnings are not this test's)
        subprocess.run([cc, "-std=gnu11", "-O1", "-w", "-I", str(ROOT / "host/posix"), "-c", str(ROOT / "host/posix/win32_posix.c"),
                        "-o", str(shim)], check=True)
        subprocess.run([cc] + flags + ["-I", str(ROOT / "host/posix"), str(ROOT / "tests/settings_atomic_test.c"), str(shim),
                                       "-lpthread", "-ldl", "-o", str(exe)], check=True)
    # the helper as the renderer's C++ files include it
    cpp = tmp / "header.cpp"
    cpp.write_text('#include <windows.h>\n#include "hos_atomic_file.h"\nint main() { return hos_atomic_write("x", "y", 1) ? 0 : 1; }\n')
    if WINDOWS:
        subprocess.run([cc, "-x", "c++", "-std=c++17", "-fsyntax-only", "-Wall", "-Wextra", "-Werror", "-D_CRT_SECURE_NO_WARNINGS",
                        "-I", str(ROOT / "host"), str(cpp)], check=True)
    else:
        subprocess.run(["g++", "-std=c++17", "-fsyntax-only", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "host/posix"),
                        "-I", str(ROOT / "host"), str(cpp)], check=True)
    return exe


class Run:
    def __init__(self, exe, work):
        self.exe, self.work, self.n = exe, work, 0

    def folder(self):
        self.n += 1
        return self.work / ("f%05d" % self.n)

    def run(self, mode, step, folder, timeout=60):
        r = subprocess.run([str(self.exe), mode, str(step), str(folder)], capture_output=True, text=True, timeout=timeout)
        killed = r.returncode in KILLED
        steps = int(m.group(1)) if (m := re.search(r"steps (\d+)", r.stdout)) else None
        assert killed or r.returncode in (0, 1), "%s %s: exit %s %s" % (mode, step, r.returncode, r.stderr)
        return killed, steps, r.returncode


def kind(data):
    """1 or a later generation (whole), "copy" (source.ini's bytes, whole), or "torn" (empty, short or a mixture)"""
    if not data or len(data) % 4:
        return "torn"
    words = array("I")
    words.frombytes(data)
    gens = set(words)
    if len(gens) != 1:
        return "torn"
    gen = gens.pop()
    if gen == 1 and len(data) == COPY_SIZE:
        return "copy"
    return gen if len(data) == SIZES[gen > 1] else "torn"


def state(folder):
    """(what settings.ini is: None when absent, else kind()), the stand-ins left beside it"""
    p = folder / SETTINGS
    what = kind(p.read_bytes()) if p.exists() else None
    left = [str(q.relative_to(folder)) for q in sorted(folder.rglob("*")) if q.name.endswith(".hosnew")] if folder.exists() else []
    return what, left


def sweep(r, report, mode, start, old, new, label):
    """kill `mode` at each of its steps; the file is whole after each, the start's clean-up leaves no stand-in, and the next write works"""
    want = {old, new}
    probe = r.folder()
    r.run(start, 0, probe)
    _, n, _ = r.run(mode, 0, probe)
    assert n and n >= 3, "%s took %s steps" % (label, n)
    seen = set()
    for k in range(1, n + 1):
        d = r.folder()
        r.run(start, 0, d)
        killed, _, _ = r.run(mode, k, d)
        assert killed, "%s: step %d of %d did not kill" % (label, k, n)
        what, _ = state(d)
        assert what in want, "%s kill %d: settings.ini is %s, expected one of %s" % (label, k, what, sorted(map(str, want)))
        seen.add(what)
        d2 = r.folder()   # (the next write finds the stand-in the kill left, if any, and goes over it)
        shutil.copytree(d, d2)
        assert r.run(mode, 0, d2)[2] == 0, "%s kill %d: the next write failed" % (label, k)
        after, left = state(d2)
        assert after == new, "%s kill %d: the next write left %s, not the new file" % (label, k, after)
        assert not left, "%s kill %d: the next write left %s" % (label, k, left)
        r.run("remove_stale", 0, d)   # (the start's clean-up)
        what2, left = state(d)
        assert what2 == what and not left, "%s kill %d: after the start %s, left %s" % (label, k, what2, left)
    report.append("%s: %d kill steps, each left the old file or the new one, whole (seen: %s), no stand-in after the start"
                  % (label, n, ", ".join(sorted(map(str, seen)))))
    assert len(seen) == 2, "%s: the kills saw only %s" % (label, sorted(map(str, seen)))


def stale_cleanup(r, report):
    d = r.folder()
    r.run("setup", 0, d)
    before = (d / SETTINGS).read_bytes()
    assert r.run("stale", 0, d)[2] == 0
    assert not (d / (SETTINGS + ".hosnew")).exists(), "the leftover stand-in was not removed"
    assert (d / SETTINGS).read_bytes() == before, "settings.ini changed"
    report.append("stale: a leftover settings.ini.hosnew is removed at the start (hos_atomic_remove_stale), the setting is left as it is")


def random_kills(r, report, count=60):
    seen = {}
    rng = random.Random(7)
    for i in range(count):
        d = r.folder()
        r.run("setup", 0, d)
        proc = subprocess.Popen([str(r.exe), "loop", "0", str(d)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(rng.uniform(0.02, 0.35))
        proc.kill()
        proc.wait()
        what, _ = state(d)
        assert what != "torn" and what is not None, "random kill %d: settings.ini is %s" % (i, what)
        r.run("remove_stale", 0, d)
        assert not state(d)[1], "random kill %d: a stand-in is left after the start" % i
        seen[what] = seen.get(what, 0) + 1
    report.append("loop: %d kills at random moments of repeated writes: every file whole, no stand-in after the start "
                  "(generations seen: %d different)" % (count, len(seen)))


def in_place(r, report):
    """A settings file that is a link, or whose folder refuses a new file though the file itself is writable, is written where it is,
    as fopen "w" did: a file moved over a link replaces the link (its target goes stale), and a folder that refuses the stand-in must
    not lose the setting. A full disk is not this case (no fallback: the file stays as it was)."""
    if WINDOWS:   # (a link needs a privilege there; the folder's access rights are another matter)
        return
    d = r.folder()
    r.run("setup", 0, d)
    target = d.parent / (d.name + "-elsewhere.ini")
    shutil.copyfile(d / SETTINGS, target)
    (d / SETTINGS).unlink()
    (d / SETTINGS).symlink_to(target)
    assert r.run("write", 0, d)[2] == 0, "write over a link failed"
    assert (d / SETTINGS).is_symlink(), "write replaced the link with a file"
    assert kind(target.read_bytes()) == 2, "the file the link names was not written"
    assert not state(d)[1], "stand-ins left"
    lines = ["through a link"]
    if os.geteuid() != 0:   # (root makes files in any folder)
        d = r.folder()
        r.run("setup", 0, d)
        d.chmod(0o555)
        try:
            assert r.run("write", 0, d)[2] == 0, "write in a folder that takes no new file failed: the setting is lost"
            assert kind((d / SETTINGS).read_bytes()) == 2, "settings.ini is not the new one"
        finally:
            d.chmod(0o755)
        assert not state(d)[1], "stand-ins left"
        lines.append("in a folder that takes no new file")
    report.append("in place: " + ", ".join(lines) + ": written where the file is, the link kept")


def control(r, report):
    torn = {}
    for mode in ("plain_write", "plain_copy"):
        d = r.folder()
        r.run("setup", 0, d)
        _, n, _ = r.run(mode, 0, d)
        bad = 0
        for k in range(1, n + 1):
            d = r.folder()
            r.run("setup", 0, d)
            killed, _, _ = r.run(mode, k, d)
            assert killed
            bad += state(d)[0] == "torn"
        torn[mode] = (bad, n)
    report.append("control (the old ways): %d of %d kill steps of fopen \"w\" and %d of %d of a copy at the final name left an empty or "
                  "part file" % (torn["plain_write"] + torn["plain_copy"]))
    assert all(bad for bad, _ in torn.values()), "the old ways tore nothing: the checks see no tear"


def sources():
    """every write of a setting goes through the helper: the problems found"""
    bad = []

    def text(rel):
        p = ROOT / rel
        return p.read_text(encoding="utf-8") if p.exists() else ""   # (a tree from before the change has no helper)

    def body(src, marker, end="\n}\n"):
        start = src.find(marker)
        return src[start:src.index(end, start) + len(end)] if start >= 0 else ""

    def need(ok, what):
        if not ok:
            bad.append(what)

    header = text("host/hos_atomic_file.h")
    need("MOVEFILE_WRITE_THROUGH" in header and "fsync(fd)" in header, "the helper moves with MOVEFILE_WRITE_THROUGH and flushes the folder on POSIX")
    sites = {
        "host/nn_hid.c": ("static void mouse_sens_save(void) {", "hos_atomic_write("),
        "host/nn_applet.c": ("static const char *desired_language(void) {", "hos_atomic_write("),
        "host/hos_main.c": ("static int copy_tree(const char *from, const char *to) {", "hos_atomic_copy_file("),
        "gpu/vk/vk_menu_i18n.cpp": ("bool set_game_language(int index) {", "hos_atomic_write("),
    }
    for rel, (marker, call) in sites.items():
        src = text(rel)
        need("hos_atomic_file.h" in src, rel + " includes the helper")
        fn = body(src, marker)
        need(call in fn, "%s: %s writes through %s" % (rel, marker, call))
        need(not re.search(r'fopen\([^;]*"w[b+]?"\)', fn), "%s: %s still writes in place with fopen" % (rel, marker))
    main = text("host/hos_main.c")
    moved = body(main, "static const char *saves_dir(const char *beside) {")
    need("hos_atomic_write(" in moved and not re.search(r'fopen\([^;]*"w[b+]?"\)', moved), "hos_main.c: saves-moved.txt through the helper")
    recover = body(main, "static void recover_writes(void) {")
    need(recover and "hos_atomic_remove_stale(" in recover, "hos_main.c has recover_writes, which removes the stand-ins of the settings")
    need("hos_atomic_remove_stale(hos_options_file())" in recover, "recover_writes removes the stand-in of the settings file wherever it is (the user folder's, HOS_OPTIONS_FILE's)")
    call = main.find("\n    recover_writes();")
    need(call >= 0 and main.rfind('if (!hos_user_dir) hos_user_dir = "user";', 0, call) >= 0 and call < main.find("hos_options_carry();", call),
         "the start calls recover_writes() after the user folder is chosen and before the options' one-time copy")
    carry = body(text("host/options_path.c"), "void hos_options_carry(void) {")
    need("hos_atomic_file.h" in text("host/options_path.c") and "hos_atomic_copy_file(" in carry and "CopyFileA(" not in carry,
         "options_path.c: the one-time copy of the settings into the user folder goes through hos_atomic_copy_file, not CopyFileA")
    return bad


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    problems = sources()
    for line in problems:
        print("FAIL (source): " + line)
    if not (ROOT / "host/hos_atomic_file.h").exists():
        raise SystemExit("test_settings_atomic: host/hos_atomic_file.h is not there (%d source checks failed)" % len(problems))
    with tempfile.TemporaryDirectory(prefix="settings-atomic-") as t:
        tmp = Path(t)
        exe = build(args.cc, tmp)
        work = tmp / "work"
        work.mkdir()
        r = Run(exe, work)
        report, failed = [], list(problems)
        steps = (
            lambda r, rep: sweep(r, rep, "write", "setup", 1, 2, "write over a file"),
            lambda r, rep: sweep(r, rep, "write", "setup_new", None, 2, "first write"),
            lambda r, rep: sweep(r, rep, "copy", "setup", 1, "copy", "copy over a file"),
            lambda r, rep: sweep(r, rep, "copy", "setup_new", None, "copy", "copy to a new name"),
            stale_cleanup, random_kills, in_place, control,
        )
        for step in steps:
            try:
                step(r, report)
            except AssertionError as e:
                failed.append("%s: %s" % (getattr(step, "__name__", "sweep"), e))
    for line in report:
        print(line)
    for line in failed:
        print("FAIL: " + line)
    if failed:
        raise SystemExit("test_settings_atomic: %d checks failed" % len(failed))
    print("PASS: every kill leaves the old settings file or the new one, whole")


if __name__ == "__main__":
    main()
