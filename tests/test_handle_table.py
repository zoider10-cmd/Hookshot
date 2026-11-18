"""The resolved texture handles are kept in a flat open-addressing table (gpu/vk/vk_draw.cpp HandleTable, FlatMap of
gpu/vk/flat_map.h), not a node map: every texture binding of every draw looks one up. The table is compiled from the header with
the source's HandleHit, and checked against
std::unordered_map on random keys shaped like the real ones (a 20-bit slot, view type, use and format above it): every
key inserted is found with its value, a key never inserted is not, growth keeps them all, and clear() empties it.

python -I -B tests/test_handle_table.py [--cxx c++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end] + ";"


DRIVER = r"""
#include <cstdint>
#include <cstdio>
#include <random>
#include <unordered_map>
#include <vector>
#include <algorithm>
#include "flat_map.h"
typedef struct VkImageView_T* VkImageView;
struct Texture;
@HIT@
@TABLE@
int main() {
    HandleTable t;
    std::unordered_map<uint64_t, uint64_t> ref;
    std::mt19937_64 rng(1234);
    if (t.find(5) || t.size()) { std::puts("FAIL: a new table finds something"); return 1; }
    for (int round = 0; round < 3; round++) {
        for (int i = 0; i < 70000; i++) {
            const uint64_t key = (rng() & 0xFFFFF) | (uint64_t)(rng() % 4) << 20 | (uint64_t)(rng() % 3) << 28 |
                                 (uint64_t)(rng() % 8 ? 0 : rng() % 200) << 32;
            const uint64_t v = rng();
            t[key].version = (uint32_t)v, t[key].destroy_gen = v;
            ref[key] = v;
        }
        if (t.size() != ref.size()) { std::printf("FAIL: size %zu, expected %zu\n", t.size(), ref.size()); return 1; }
        for (const auto& kv : ref) {
            HandleHit* h = t.find(kv.first);
            if (!h || h->destroy_gen != kv.second || h->version != (uint32_t)kv.second) {
                std::printf("FAIL: key %llx lost\n", (unsigned long long)kv.first); return 1;
            }
        }
        for (int i = 0; i < 100000; i++) {
            const uint64_t key = rng() | 1ull << 63;   // (never inserted)
            if (t.find(key)) { std::puts("FAIL: found a key never inserted"); return 1; }
        }
        if (t.slots.size() < 2 * t.size()) { std::puts("FAIL: more than half full"); return 1; }
        t.clear(), ref.clear();
        if (t.size() || t.find(0)) { std::puts("FAIL: clear left something"); return 1; }
    }
    std::puts("handle table ok");
    return 0;
}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cxx", default="c++")
    a = ap.parse_args()
    source = (ROOT / "gpu" / "vk" / "vk_draw.cpp").read_text(encoding="utf-8")
    hit, table = block(source, "struct HandleHit {"), "using HandleTable = FlatMap<HandleHit>;"
    if "TLS_OBJECT(handle_hits, HandleTable)" not in source or table not in source:
        raise SystemExit("handle_hits is no longer the flat table")
    with tempfile.TemporaryDirectory() as d:
        src, exe = Path(d) / "t.cpp", Path(d) / "t.exe"
        src.write_text(DRIVER.replace("@HIT@", hit).replace("@TABLE@", table), encoding="utf-8")
        r = subprocess.run([a.cxx, "-std=c++17", "-O2", "-I", str(ROOT / "gpu" / "vk"), str(src), "-o", str(exe)], capture_output=True, text=True)
        if r.returncode:
            raise SystemExit("compile failed:\n" + r.stderr[-3000:])
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=120)
        print(r.stdout.strip())
        if r.returncode:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
