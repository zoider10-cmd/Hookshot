"""scripts/coverage/cover.py run marks exactly the lifted functions a game runs, with the real DLL, on Windows.

Builds a stand-in game (bin/hookshot.exe with four f_<address> functions, two of them called, one of those a thousand
times) with the given clang, then runs it under `cover.py run` (the real cover_dll.c, loaded before the entry point) and
checks the run folder: four functions found in the exe's symbol table, the two called ones and only those in covered.txt,
in the order they first ran, and the program ending normally (exit code 0) after the breakpoints.

python -I -B tests/test_coverage_run.py --cc clang       (llvm-mingw's: llvm-nm is taken from beside it)
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "clang"]
RUN_ALL_SKIP = {"linux": "cover.py run hooks the Windows game (report and compare are checked by test_coverage_report.py)"}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COVER = os.path.join(ROOT, "scripts", "coverage", "cover.py")

GAME = r"""
#include <stdio.h>
#define F(name) __attribute__((noinline, used)) int name(int x)
F(f_80000000) { return x + 1; }
F(f_80000100) { return x * 3; }   /* never called */
F(f_80000200) { return x - 7; }
F(f_80000300) { return x ^ 5; }   /* never called */
int main(int argc, char **argv) {
    (void)argv;
    volatile int k = argc;
    int r = f_80000000(k);
    for (int i = 0; i < 1000; i++) r = f_80000200(r);
    if (k > 100) r += f_80000100(r) + f_80000300(r);
    printf("result %d\n", r);
    return 0;
}
"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cc", default="clang")
    a = p.parse_args()
    cc = shutil.which(a.cc) or a.cc
    nm = os.path.join(os.path.dirname(cc), "llvm-nm.exe")
    if not os.path.exists(nm):
        sys.exit("test_coverage_run: no llvm-nm beside %s (llvm-mingw has one)" % cc)
    with tempfile.TemporaryDirectory() as tmp:
        game = os.path.join(tmp, "game")
        os.makedirs(os.path.join(game, "bin"))
        src = os.path.join(tmp, "game.c")
        with open(src, "w") as f:
            f.write(GAME)
        exe = os.path.join(game, "bin", "hookshot.exe")
        subprocess.run([cc, "-O1", "-o", exe, src], check=True)
        want = subprocess.run([exe], capture_output=True, text=True, check=True).stdout
        assert want.strip() == "result -6998", want

        out = os.path.join(tmp, "run")
        r = subprocess.run([sys.executable, "-I", "-B", COVER, "run", game, "--out", out, "--seconds", "60", "--force",
                            "--cc", cc, "--nm", nm], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
        if r.returncode:
            raise AssertionError("cover.py run failed:\n%s%s" % (r.stdout, r.stderr))
        if "the game ended (exit code 0x0)" not in r.stdout:
            raise AssertionError("expected the stand-in game to end normally:\n" + r.stdout)
        if "cover: 4 lifted functions (4 names)" not in r.stdout:
            raise AssertionError("expected the 4 functions in the exe's symbol table:\n" + r.stdout)
        if "Functions that ran: 2 of 4" not in r.stdout:
            raise AssertionError("expected 2 of 4 functions to have run:\n%s\n%s" % (r.stdout, open(out + "/cover.bin.log").read()))
        with open(os.path.join(out, "covered.txt"), encoding="ascii") as f:
            got = [line.split()[0] for line in f]
        assert got == ["f_80000000", "f_80000200"], got
        with open(os.path.join(out, "cover.bin.log"), encoding="ascii") as f:
            log = f.read()
        assert "4 functions marked" in log and "exit, 2 functions ran" in log, log
    print("test_coverage_run: OK")


if __name__ == "__main__":
    main()
