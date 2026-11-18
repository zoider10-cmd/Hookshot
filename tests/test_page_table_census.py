"""The guest pools the page table cannot reach are logged: one line for each pool that comes outside its windows (the first 30),
and at close how many came, their bytes outside and where they lie.

Guest memory's page table, for the pointers shaders follow, covers two windows of the guest's 512 GB: 8 GB from 64 GB and 4 GB
from 508 GB (vk_memory.cpp guest_pages_set, read by spirv_emit_context.cpp). A pointer into a pool outside them that no bound
buffer holds reads 0, and whether the game has such pools was never counted. Checked here:
- gpu/vk/page_table_census.h's windows are the shaders' own (kGuestPagesBase, kGuestPagesBytes, kGuestPagesBase2,
  kGuestPagesBytes2), and guest_pages_set and memory_guest_pages take theirs from it: the census counts what the table leaves out;
- its census, run against pool tables like memory_sync's: pools at 128 GB and 504 GB and two across a window's end are named
  (the two by their bytes outside), the ones inside are not; a table refreshed with the same pools names nothing again; past 30
  the pools are counted and not named; one that leaves and comes back counts again; the summary line gives what came, the most at
  once, what is outside now and where they lie; with none outside it says so, with the pools in the table;
- memory_sync refreshes the census with the pool table it is about to take, and mkwvk_close_asked logs the summary.

No Vulkan, GPU or game. python -I -B tests/test_page_table_census.py [--cxx clang++] [--source <tree>]
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    at = text.index(marker)
    end = text.index("{", at) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[at:end]


FIXTURE = r"""
#include "page_table_census.h"
#include <cstdio>
#include <cstdlib>
#include <vector>
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
using namespace mkwvk;
struct GuestPool { uint64_t lo, hi; };   // (vk_memory.cpp's: aligned outwards, by lo)
constexpr uint64_t KB = 1ull << 10, MB = 1ull << 20, GB = 1ull << 30;
void out(const std::vector<std::string>& lines) {
    for (const std::string& line : lines) std::printf("LOG %s\n", line.c_str());
}
int main() {
    for (const PageWindow& w : kPageWindows)
        std::printf("WINDOW %llu %llu %llu\n", (unsigned long long)w.base, (unsigned long long)w.bytes, (unsigned long long)w.first);
    std::printf("ENTRIES %llu\n", (unsigned long long)kPageTableEntries);
    // (the bytes outside)
    CHECK(page_table_outside(0x1000000000ull, 0x1004000000ull) == 0);
    CHECK(page_table_outside(0x2000000000ull, 0x2004000000ull) == 64 * MB);
    CHECK(page_table_outside(0x11ffff0000ull, 0x1200010000ull) == 64 * KB);
    CHECK(page_table_outside(0x0fffff0000ull, 0x1000010000ull) == 64 * KB);
    CHECK(page_table_outside(0x7fffff0000ull, 0x8000010000ull) == 64 * KB);
    CHECK(page_table_outside(0, 512 * GB) == 500 * GB);
    CHECK(page_table_outside(0x2000000000ull, 0x2000000000ull) == 0 && page_table_outside(5, 4) == 0);
    const GuestPool in_a{0x1000000000ull, 0x1004000000ull}, across_a{0x11ffff0000ull, 0x1200010000ull},
                    at_128{0x2000000000ull, 0x2004000000ull}, at_504{0x7e00000000ull, 0x7e00100000ull},
                    in_b{0x7f00000000ull, 0x7f40000000ull}, across_b{0x7fffff0000ull, 0x8000010000ull};
    {
        PageTableCensus none;
        const std::vector<GuestPool> inside{in_a, in_b};
        CHECK(none.refresh(inside).empty());
        std::printf("SUMMARY %s\n", none.summary("close").c_str());
    }
    PageTableCensus c;
    std::vector<GuestPool> first{in_a, across_a, at_128, at_504, in_b, across_b};
    std::printf("REFRESH 1\n");
    out(c.refresh(first));
    std::printf("REFRESH 2\n");
    out(c.refresh(first));   // (the same pools: nothing new)
    CHECK(c.came == 4 && c.came_bytes == 64 * MB + 1 * MB + 128 * KB);
    std::vector<GuestPool> second{in_a, across_a, at_504, in_b, across_b};
    for (uint64_t i = 0; i < 40; i++) second.push_back({0x3000000000ull + i * MB, 0x3000000000ull + (i + 1) * MB});
    std::printf("REFRESH 3\n");
    out(c.refresh(second));   // (128 GB's pool gone, 40 new ones: 26 named, the 30 reached)
    CHECK(c.came == 44 && c.named == 30 && c.outside.size() == 43);
    std::vector<GuestPool> third = second;
    third.push_back(at_128);   // (back: it counts again, and is not named again past the 30)
    std::printf("REFRESH 4\n");
    out(c.refresh(third));
    CHECK(c.came == 45 && c.outside.size() == 44 && c.most == 44 && c.pools == 46);
    std::printf("SUMMARY %s\n", c.summary("close").c_str());
    return 0;
}
"""

WANT_FIRST = [
    "vk: page table: pool 0x11ffff0000..0x1200010000 (128 KB) is partly outside its windows (64 KB of it): a pointer into those "
    "bytes that no bound buffer holds reads 0",
    "vk: page table: pool 0x2000000000..0x2004000000 (64.0 MB) is outside its windows: a pointer into it that no bound buffer "
    "holds reads 0",
    "vk: page table: pool 0x7e00000000..0x7e00100000 (1.0 MB) is outside its windows: a pointer into it that no bound buffer "
    "holds reads 0",
    "vk: page table: pool 0x7fffff0000..0x8000010000 (128 KB) is partly outside its windows (64 KB of it): a pointer into those "
    "bytes that no bound buffer holds reads 0",
]
WANT_THIRD = ["vk: page table: pool %#x..%#x (1.0 MB) is outside its windows: a pointer into it that no bound buffer holds reads 0"
              % (0x3000000000 + i * 2**20, 0x3000000000 + (i + 1) * 2**20) for i in range(26)]
WANT_NONE = "vk: page table census (close): no pool outside its windows, 64-72 GB and 508-512 GB (2 pools in the table now)"
WANT_SUMMARY = ("vk: page table census (close): 45 pools outside its windows, 64-72 GB and 508-512 GB, came into the pool table "
                "(the first 30 named above), 169.1 MB of them outside; at most 44 at once (105.1 MB), 44 now of 46 pools; between "
                "0x11ffff0000 and 0x8000010000")


def number(text):
    """0x1000000000ull, 8ull << 30"""
    m = re.fullmatch(r"\s*(0x[0-9a-fA-F]+|\d+)ull(?:\s*<<\s*(\d+))?\s*", text)
    if not m:
        raise ValueError(text)
    return int(m.group(1), 0) << int(m.group(2) or 0)


def source_checks(vk, fails):
    emit = (vk / "eden/shader_recompiler/backend/spirv/spirv_emit_context.cpp").read_text(encoding="utf-8")
    shaders = {}
    for name in ("kGuestPagesBase", "kGuestPagesBytes", "kGuestPagesBase2", "kGuestPagesBytes2"):
        m = re.search(r"constexpr unsigned long long %s = ([^;]+);" % name, emit)
        if not m:
            fails.append("spirv_emit_context.cpp: no %s" % name)
            return None
        shaders[name] = number(m.group(1))
    memory = (vk / "vk_memory.cpp").read_text(encoding="utf-8")
    setter = block(memory, "void guest_pages_set(")
    if "for (const PageWindow& w : kPageWindows)" not in setter or re.search(r"0x[0-9a-fA-F]{6,}", setter):
        fails.append("vk_memory.cpp guest_pages_set: its windows are not page_table_census.h's kPageWindows")
    if "const uint64_t bytes = kPageTableEntries * 8;" not in block(memory, "uint64_t memory_guest_pages("):
        fails.append("vk_memory.cpp memory_guest_pages: the table is not sized by page_table_census.h's kPageTableEntries")
    sync = block(memory, "void memory_sync(")
    refresh, swap = sync.find("page_census.refresh(next)"), sync.find("guest_pools.swap(next);")
    if refresh < 0 or swap < 0 or refresh > swap or "page_census_mu" not in sync:
        fails.append("vk_memory.cpp memory_sync: the census is not refreshed (under its lock) with the pool table before it is taken")
    log = block(memory, "void page_table_census_log(const char* when)")
    if "page_census_mu" not in log or "page_census.summary(when)" not in log:
        fails.append("vk_memory.cpp page_table_census_log: not the census's summary, under its lock")
    close = block((vk / "vk_main.cpp").read_text(encoding="utf-8"), "void mkwvk_close_asked(void)")
    if 'page_table_census_log("close");' not in close:
        fails.append("vk_main.cpp mkwvk_close_asked: the census's summary is not logged at close")
    return shaders


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cxx", default="clang++")
    ap.add_argument("--source", type=Path, default=ROOT, help="the tree to check (default: this one)")
    a = ap.parse_args()
    vk = a.source / "gpu" / "vk"
    fails = []
    if not (vk / "page_table_census.h").is_file():
        fails.append("gpu/vk/page_table_census.h: no census of the guest pools outside the page table's windows")
    else:
        shaders = source_checks(vk, fails)
        with tempfile.TemporaryDirectory(prefix="page-table-census-") as tmp:
            src, exe = Path(tmp) / "fixture.cpp", Path(tmp) / ("fixture" + (".exe" if os.name == "nt" else ""))
            src.write_text(FIXTURE, encoding="utf-8")
            r = subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(vk), str(src), "-o", str(exe)],
                               capture_output=True, text=True, timeout=180)
            if r.returncode:
                print(r.stdout + r.stderr)
                fails.append("the fixture did not compile")
            else:
                got = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
                if got.returncode:
                    fails.append("the fixture failed: " + got.stderr.strip())
                else:
                    out = got.stdout.splitlines()
                    windows = [tuple(int(x) for x in line.split()[1:]) for line in out if line.startswith("WINDOW ")]
                    if shaders and windows != [(shaders["kGuestPagesBase"], shaders["kGuestPagesBytes"], 0),
                                               (shaders["kGuestPagesBase2"], shaders["kGuestPagesBytes2"], shaders["kGuestPagesBytes"] >> 12)]:
                        fails.append("page_table_census.h's windows %r are not the shaders' %r" % (windows, shaders))
                    if shaders and out.count("ENTRIES %d" % ((shaders["kGuestPagesBytes"] + shaders["kGuestPagesBytes2"]) >> 12)) != 1:
                        fails.append("kPageTableEntries is not the two windows' 4 KB pages")
                    parts, at = {}, None
                    for line in out:
                        if line.startswith("REFRESH "):
                            at = int(line.split()[1])
                            parts[at] = []
                        elif line.startswith("LOG "):
                            parts.setdefault(at, []).append(line[4:])
                    summaries = [line[8:] for line in out if line.startswith("SUMMARY ")]
                    for k, want in ((1, WANT_FIRST), (2, []), (3, WANT_THIRD), (4, [])):
                        if parts.get(k) != want:
                            fails.append("refresh %d named:\n  got  %s\n  want %s" % (k, "\n       ".join(parts.get(k) or ["(none)"]),
                                                                                    "\n       ".join(want or ["(none)"])))
                    if summaries != [WANT_NONE, WANT_SUMMARY]:
                        fails.append("the summaries:\n  got  %s\n  want %s" % ("\n       ".join(summaries),
                                                                              "\n       ".join([WANT_NONE, WANT_SUMMARY])))
    for f in fails:
        print("FAIL: " + f)
    if fails:
        return 1
    print("PASS: each guest pool outside the page table's windows is named as it comes (the first 30), and the close's line counts "
          "them all, their bytes outside and where they lie")
    return 0


if __name__ == "__main__":
    sys.exit(main())
