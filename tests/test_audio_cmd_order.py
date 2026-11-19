"""The audio renderer's queued changes keep their order when the store cannot grow.

The game's changes to a voice wait in a store until its update applies them in order (host/nn_audio.c submit, commit).
A store that was full and could not grow applied the new change at once, ahead of the older ones still waiting: a
queued Stop then came after the next sound's buffers and cut them (Reborn's audio, read 2026-11-1x, a candidate for
stuck music). Now the waiting ones are applied first, then the new one.

python -I -B tests/test_audio_cmd_order.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))   # (tests/srccut.py: python -I leaves this folder off the path)
from srccut import block   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]   # (tests/run_all.py: the compiler it finds here)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    source = (ROOT / "host" / "nn_audio.c").read_text(encoding="utf-8")
    submit = block(source, "static void submit(const Cmd *k)")
    fixture = r'''#include <cstdio>
#include <cstdlib>
#include <cstring>
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
typedef struct { int op; } Cmd;
static Cmd *cmds;
static int ncmds, cmds_cap;
static int order[64], norder;
static int grow_fails;
static void apply(const Cmd *k) { order[norder++] = k->op; }
static int env_on(const char *) { return 0; }
static void *grow(void *p, size_t n) { return grow_fails ? nullptr : std::realloc(p, n); }
#define realloc grow
''' + submit + r'''
#undef realloc
int main() {
    /* a full store that cannot grow: three changes waiting, then a fourth */
    cmds = (Cmd *)std::malloc(3 * sizeof *cmds);
    cmds_cap = 3;
    for (int op = 1; op <= 3; op++) { Cmd k = {op}; submit(&k); }
    CHECK(ncmds == 3 && norder == 0);
    grow_fails = 1;
    Cmd k = {4};
    submit(&k);
    CHECK(norder == 3);   /* the waiting ones applied, in order */
    for (int i = 0; i < 3; i++) CHECK(order[i] == i + 1);
    CHECK(ncmds == 1 && cmds[0].op == 4);   /* the new one waits for the update, after them */
    /* a store that can grow keeps waiting */
    grow_fails = 0;
    Cmd m = {5};
    submit(&m);
    CHECK(ncmds == 2 && norder == 3);
    std::printf("PASS: the audio changes keep their order when the store is full\n");
}
'''
    with tempfile.TemporaryDirectory(prefix="audio-cmd-order-") as tmp:
        cpp = Path(tmp) / "fixture.cpp"
        exe = Path(tmp) / "fixture"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
