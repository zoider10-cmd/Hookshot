"""The write marks' collection finds the same pages 256 marks a step as 32 (host/rx_backend.c collect_in).

collect_in and its 256-mark test are cut out of the source and compiled against a small mark array. For random marks
and ranges (aligned or not, short, empty, past the guest's end, past the array's end) the pages found, their order and
the marks left must be those of a plain walk, with the wide step on and with HOS_COLLECT_WIDE=0. The fixture also
checks that the wide step is really taken (a range of 4096 clear marks is walked in 16 steps).

python -I -B tests/test_collect_wide.py [--cc gcc]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r"""
#define _POSIX_C_SOURCE 200112L
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define A64_DIRTY_PAGES (1ull << 16)
static uint8_t a64_dirty[A64_DIRTY_PAGES];
static uint64_t guest_size = A64_DIRTY_PAGES << 12;
static uint64_t hos_guest_size(void) { return guest_size; }
static int clear_calls;
#define memcpy(d, s, n) (clear_calls += (n) == 256, memcpy(d, s, n))

@MARKS_CLEAR@
@COLLECT_IN@

#undef memcpy

static uint64_t rng = 0x9E3779B97F4A7C15ull;
static uint64_t rnd(void) {
    rng ^= rng << 13, rng ^= rng >> 7, rng ^= rng << 17;
    return rng;
}

/* (the plain walk: every page of every range, in order) */
static size_t plain(const uint64_t (*ranges)[2], int n, const uint8_t *marks, uint8_t *left, uint32_t *out) {
    size_t k = 0;
    memcpy(left, marks, A64_DIRTY_PAGES);
    for (int r = 0; r < n; r++) {
        const uint64_t hi = ranges[r][1] < guest_size ? ranges[r][1] : guest_size;
        uint64_t p1 = (hi + 4095) >> 12;
        if (p1 > A64_DIRTY_PAGES) p1 = A64_DIRTY_PAGES;
        for (uint64_t p = ranges[r][0] >> 12; p < p1; p++)
            if (left[p]) left[p] = 0, out[k++] = (uint32_t)p;
    }
    return k;
}

int main(int argc, char **argv) {
    const int want_wide = argc > 1 && argv[1][0] == '1';
    static uint8_t marks[A64_DIRTY_PAGES], left[A64_DIRTY_PAGES];
    static uint32_t expect[A64_DIRTY_PAGES];
    static uint64_t ranges[64][2];
    for (int round = 0; round < 400; round++) {
        memset(marks, 0, sizeof marks);
        const int density = round % 8;   /* (0: no mark at all; then sparse to dense, some in clusters) */
        const uint64_t count = density == 0 ? 0 : (1ull << (density * 2));
        for (uint64_t i = 0; i < count; i++) {
            const uint64_t at = rnd() % A64_DIRTY_PAGES;
            marks[at] = 1;
            if (density == 5) marks[(at + 1) % A64_DIRTY_PAGES] = marks[(at + 255) % A64_DIRTY_PAGES] = 1;
        }
        if (round % 5 == 1) marks[255] = marks[256] = marks[511] = marks[A64_DIRTY_PAGES - 1] = 1;   /* (the steps' edges) */
        guest_size = round % 7 == 3 ? (rnd() % A64_DIRTY_PAGES) << 12 | (rnd() & 4095) : A64_DIRTY_PAGES << 12;
        int n = (int)(rnd() % 12);
        uint64_t at = rnd() % 4096;
        for (int r = 0; r < n; r++) {   /* (sorted, disjoint, as hos_gpu_guest_ranges gives them) */
            const uint64_t len = round % 3 == 0 ? rnd() % 300 : rnd() % 40000;
            ranges[r][0] = at << 12 | (round % 2 ? rnd() & 4095 : 0);
            ranges[r][1] = (at + len) << 12 | (round % 2 ? rnd() & 4095 : 0);
            if (ranges[r][1] < ranges[r][0]) ranges[r][1] = ranges[r][0];
            at += len + 1 + rnd() % 600;
            if (round % 11 == 7 && r == n - 1) ranges[r][1] = (A64_DIRTY_PAGES + 5000) << 12;   /* (past the array) */
        }
        const size_t k = plain(ranges, n, marks, left, expect);
        memcpy(a64_dirty, marks, sizeof marks);
        uint32_t *pages = 0;
        const int64_t got = collect_in(ranges, n, &pages);
        if ((size_t)got != k || (k && memcmp(pages, expect, k * sizeof *pages)) || memcmp(a64_dirty, left, sizeof left)) {
            printf("round %d: %lld pages found, %zu expected, or other pages, or other marks left\n", round, (long long)got, k);
            return 1;
        }
        free(pages);
    }
    /* (the wide step is taken: 4096 clear marks in 16 steps; and not with the switch off) */
    memset(a64_dirty, 0, sizeof a64_dirty);
    guest_size = A64_DIRTY_PAGES << 12;
    ranges[0][0] = 0, ranges[0][1] = 4096ull << 12;
    uint32_t *pages = 0;
    clear_calls = 0;
    if (collect_in(ranges, 1, &pages) != 0) return 1;
    free(pages);
    if (clear_calls != (want_wide ? 16 : 0)) {
        printf("4096 clear marks: %d steps of 256, %d expected\n", clear_calls, want_wide ? 16 : 0);
        return 1;
    }
    return 0;
}
"""


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    src = (ROOT / "host" / "rx_backend.c").read_text(encoding="utf-8")
    fixture = (FIXTURE.replace("@MARKS_CLEAR@", block(src, "static inline int marks_clear_256("))
               .replace("@COLLECT_IN@", block(src, "static int64_t collect_in(")))
    with tempfile.TemporaryDirectory(prefix="collect-wide-") as tmp:
        c = Path(tmp) / "fixture.c"
        exe = Path(tmp) / "fixture"
        c.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe)], check=True)
        for wide in ("1", "0"):
            env = dict(os.environ)
            env.pop("HOS_COLLECT_WIDE", None)
            if wide == "0":
                env["HOS_COLLECT_WIDE"] = "0"
            subprocess.run([str(exe), wide], check=True, env=env)
    print("ok: the same pages 256 marks a step as 32")


if __name__ == "__main__":
    main()
