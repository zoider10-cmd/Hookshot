"""The lifted stores mark only GPU pages, by a page bitmap (host/mark_bitmap.c, nx2/rtgen.py A64_MARK_BITMAP; Longshot
35a4a9fc): no game data.

- host/mark_bitmap.c compiled alone: a mapping sets its pages' bits and the page before's, not the page after's; a size
  of 0 sets none; HOS_MARK_BITMAP_ALL=1 sets every bit at the start;
- nx2/rtgen.py: A64_MARK tests the store's first byte's page under A64_MARK_BITMAP, and is the old one without it;
- nx2/build.py: the flag is on by default, RX_MARK_BITMAP=0 leaves it out; host/nvdrv.c map_add sets the bits of every
  mapping's guest pages before the mapping counts (the renderer reads the marks over every mapping's guest range,
  hos_gpu_guest_ranges, whatever its GPU address).

    python -I -B tests/test_mark_bitmap.py [--cc gcc]
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
#define A64_DIRTY_PAGES (1ull << 20)
@SRC@
static int bit(uint64_t page) { return (a64_gpu_pages[page >> 3] >> (page & 7)) & 1; }
int main(int argc, char **argv) {
    (void)argv;
    if (argc > 1) {   /* (HOS_MARK_BITMAP_ALL=1: every bit set at the start) */
        CHECK(bit(0) && bit(12345) && bit(A64_DIRTY_PAGES - 1));
        printf("all\n");
        return 0;
    }
    CHECK(!bit(0x100) && !bit(0x101));
    hos_gpu_pages_set(0x100000, 0x2000);   /* (pages 0x100, 0x101) */
    CHECK(bit(0xff) && bit(0x100) && bit(0x101) && !bit(0x102) && !bit(0xfe));
    hos_gpu_pages_set(0x200800, 0x10);     /* (a part of one page) */
    CHECK(bit(0x1ff) && bit(0x200) && !bit(0x201));
    hos_gpu_pages_set(0x300000, 0);
    CHECK(!bit(0x2ff) && !bit(0x300));
    printf("ok\n");
    return 0;
}
'''


def check(ok, why):
    if not ok:
        print("FAIL: %s" % why)
        sys.exit(1)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    src = (ROOT / "host" / "mark_bitmap.c").read_text(encoding="utf-8").replace('#include "hos.h"\n', "")
    check("#ifndef A64_DIRTY_PAGES" in src and "uint8_t a64_gpu_pages[A64_DIRTY_PAGES / 8];" in src, "mark_bitmap.c is not as this check knows it")
    rtgen = (ROOT / "nx2" / "rtgen.py").read_text(encoding="utf-8")
    native = rtgen[rtgen.index('MARK_NATIVE_64 = r"""'):]
    native = native[:native.index('"""', 20)]
    check("#if defined(A64_MARK_BITMAP)" in native and "#define A64_MARK(a, n) (A64_GPU_PAGE(a) ?" in native and
          native.count("#define A64_MARK(a, n)") == 2 and "#else" in native and native.rstrip().endswith("#endif"),
          "rtgen.py: A64_MARK does not test the store's page under A64_MARK_BITMAP, or has no old form without it")
    build = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
    check('else ["-DA64_MARK_BITMAP"]' in build and "RX_MARK_BITMAP" in build and "+ WRITE_TRACK + MARK_BITMAP" in build,
          "build.py: the lifted code is not built with the bitmap by default, or RX_MARK_BITMAP=0 cannot leave it out")
    nvdrv = (ROOT / "host" / "nvdrv.c").read_text(encoding="utf-8")
    add = nvdrv[nvdrv.index("static void map_add(uint64_t va, uint64_t size, uint64_t guest) {"):]
    check(add.index("hos_gpu_pages_set(guest, size);") < add.index("maps_changed = 1;") and "if (guest) hos_gpu_pages_set" in add,
          "nvdrv.c: map_add does not set the mapping's pages' bits before the mapping counts")
    with tempfile.TemporaryDirectory(prefix="mark-bitmap-") as tmp:
        c, exe = Path(tmp) / "fixture.c", Path(tmp) / "fixture"
        c.write_text(FIXTURE.replace("@SRC@", src), encoding="utf-8")
        subprocess.run([a.cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
        env = dict(os.environ, HOS_MARK_BITMAP_ALL="1")
        subprocess.run([str(exe), "all"], check=True, env=env)
    print("PASS: the lifted stores mark only GPU pages")


if __name__ == "__main__":
    main()
