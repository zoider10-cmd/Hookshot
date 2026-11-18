"""nn::fs::WriteFile and FlushFile hold no virtual core while the host writes or flushes (host/nn_fs.c), as OpenFile and
ReadFile already did.

FlushFile is an fdatasync on Linux (FlushFileBuffers on Windows): a save's flush can wait tens of ms or more for the disk,
and a write can wait for the dirty pages' writeback. With the core held, the game threads that share that core waited
behind the disk (the vcore audit of the 250-ms escapes: no escape was seen here, the scenarios save nothing). The actual
two HLEs are compiled with stand-ins that record whether the thread holds its core in the host call:

- a write and a flush by a thread with a core: neither with the core, the core back once after each;
- a thread without a core takes none.

python -I -B tests/test_vcore_fs_write.py [--cxx clang++]
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def block(source, marker):
    start = source.index(marker)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


HARNESS = r"""
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef unsigned long DWORD;
typedef int BOOL;
typedef void *HANDLE;
typedef struct { DWORD Offset, OffsetHigh; } OVERLAPPED;
typedef struct { uint64_t x[32]; } Ctx;
#define HLE(sym) static void imp_##sym(Ctx *c)
#define ARG(n) (c->x[n])
#define RET(v) (c->x[0] = (uint64_t)(v))
#define GP(a) ((void *)(uintptr_t)(a))
typedef struct { HANDLE h; } Handle;
static Handle file = {(HANDLE)1};
static Handle *get_handle(Ctx *c, uint64_t id) { (void)c, (void)id; return &file; }
/* (hookshot: the write takes guest memory only, committed first; refused is an error, not a short write) */
static int hos_guest_range(uint64_t a, uint64_t n) { (void)a, (void)n; return 1; }
static int hos_commit(uint64_t a, uint64_t n) { (void)a, (void)n; return 1; }
#define R_OUT_OF_MEMORY 0x1234
static int held, takes, writes, writes_with_core, flushes, flushes_with_core;
int hos_vcore_away(void) { if (!held) return 0; held = 0; return 1; }
void hos_vcore_back(void) { if (!held) held = 1, takes++; }
static BOOL WriteFile(HANDLE h, const void *p, DWORD n, DWORD *put, OVERLAPPED *ov) {
    (void)h, (void)p, (void)ov;
    writes++, writes_with_core += held;
    *put = n;
    return 1;
}
static BOOL FlushFileBuffers(HANDLE h) { (void)h; flushes++, flushes_with_core += held; return 1; }

@HLES@

static int bad;
static void check(int ok, const char *what) { if (!ok) { printf("FAIL: %s\n", what); bad = 1; } }
int main(void) {
    static char buf[64];
    Ctx c;
    for (int core = 1; core >= 0; core--) {
        memset(&c, 0, sizeof c);
        c.x[0] = 1, c.x[1] = 0, c.x[2] = (uint64_t)(uintptr_t)buf, c.x[3] = sizeof buf;
        held = core, takes = writes = writes_with_core = 0;
        imp__ZN2nn2fs9WriteFileENS0_10FileHandleElPKvmRKNS0_11WriteOptionE(&c);
        check(c.x[0] == 0 && writes == 1, "the write made");
        check(writes_with_core == 0, "the write without the core");
        check(takes == core && held == core, core ? "the core back once after the write" : "no core taken (none held)");
        memset(&c, 0, sizeof c);
        c.x[0] = 1;
        held = core, takes = flushes = flushes_with_core = 0;
        imp__ZN2nn2fs9FlushFileENS0_10FileHandleE(&c);
        check(c.x[0] == 0 && flushes == 1, "the flush made");
        check(flushes_with_core == 0, "the flush without the core");
        check(takes == core && held == core, core ? "the core back once after the flush" : "no core taken (none held)");
    }
    if (!bad) puts("ok");
    return bad;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    parser.add_argument("--source", type=Path, default=ROOT / "host/nn_fs.c")
    args = parser.parse_args()
    src = args.source.read_text(encoding="utf-8")
    hles = "\n\n".join((block(src, "HLE(_ZN2nn2fs9WriteFileENS0_10FileHandleElPKvmRKNS0_11WriteOptionE) {"),
                        block(src, "HLE(_ZN2nn2fs9FlushFileENS0_10FileHandleE)")))
    fixture = HARNESS.replace("@HLES@", hles)
    compiler = shutil.which(args.cxx)
    if not compiler:
        raise SystemExit("C++ compiler not found: " + args.cxx)
    with tempfile.TemporaryDirectory(prefix="vcore-fs-write-") as temporary:
        folder = Path(temporary)
        (folder / "fixture.cpp").write_text(fixture, encoding="utf-8")
        exe = folder / ("fixture.exe" if os.name == "nt" else "fixture")
        subprocess.run([compiler, "-std=c++17", "-O1", "-w", str(folder / "fixture.cpp"), "-o", str(exe)], check=True,
                       timeout=120)
        result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
        print(result.stdout, end="")
        if result.returncode or "ok" not in result.stdout:
            raise SystemExit("nn::fs WriteFile or FlushFile holds the virtual core through the host's write or flush")


if __name__ == "__main__":
    main()
