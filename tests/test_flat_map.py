"""The replay's per-draw caches (handle_hits, program_for's picks, a thread's pipelines, a recording's c1 uploads) answer as
std::unordered_map did.

FlatMap (gpu/vk/flat_map.h) is checked against std::unordered_map on random keys shaped like the replay's (hashes, slot
numbers with bits above, addresses), with the values those caches hold (a Pick with its handles, a pointer, a buffer and an
offset), through growth and the whole clears the replay does: every key found with its value, operator[] making an empty
value and returning it to be written through, a clear emptying it and letting a value's memory go. And the four caches are
the flat table in the source, program_for not writing through its pick after program_pick (an insert can move it).

From Hookshot eda64e895 / HeyListen 3aa51bf5 (tests/test_flat_map.py), adapted: our FlatMap is the handle table of 7ac89d22
made generic (find gives the value or null), and texture_view_of's own check is tests/test_handle_lookup.py.
python -I -B tests/test_flat_map.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"

DRIVER = r'''
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <unordered_map>
#include <utility>
#include <vector>
#include "flat_map.h"

struct Pick {
    const void* p = nullptr;
    std::vector<uint32_t> handles;
    bool operator==(const Pick& o) const { return p == o.p && handles == o.handles; }
};
typedef struct VkBuffer_T* VkBuffer;

template <class V>
void same(FlatMap<V>& b, std::unordered_map<uint64_t, V>& a, uint64_t k, int line) {
    V* y = b.find(k);
    auto x = a.find(k);
    if ((x == a.end()) != !y || a.size() != b.size()) {
        std::fprintf(stderr, "FAIL: maps differ at key %llx (line %d)\n", (unsigned long long)k, line);
        std::exit(1);
    }
    if (y && !(*y == x->second)) {
        std::fprintf(stderr, "FAIL: values differ at key %llx (line %d)\n", (unsigned long long)k, line);
        std::exit(1);
    }
}

template <class V, class Key, class Make>
void against_std(std::mt19937_64& r, Key key, Make make, size_t cap, int ops) {
    std::unordered_map<uint64_t, V> a;
    FlatMap<V> b;
    for (int i = 0; i < ops; i++) {
        const uint64_t k = key(r);
        switch (r() % 8) {
        case 0: case 1: case 2: same(b, a, k, __LINE__); break;
        case 3: { const V v = make(r); a[k] = v, b[k] = v; break; }   // (texture_view_of, c1: written whole)
        case 4: {   // (program_for: made empty on a miss, then written through)
            V& x = a[k];
            V& y = b[k];
            if (!(x == y)) { std::fputs("FAIL: operator[] made another value\n", stderr); std::exit(1); }
            const V v = make(r);
            x = v, y = v;
            break;
        }
        case 5: same(b, a, k ^ 0x8000000000000000ull, __LINE__); break;   // (likely never inserted)
        default:
            if (a.size() > cap) a.clear(), b.clear();   // (the replay's whole clears at its limits)
            break;
        }
    }
    for (const auto& kv : a) same(b, a, kv.first, __LINE__);
    if (b.slots.size() < 2 * b.size()) { std::fputs("FAIL: more than half full\n", stderr); std::exit(1); }
    b.clear();
    if (b.size() || b.find(key(r))) { std::fputs("FAIL: clear left something\n", stderr); std::exit(1); }
}

int main() {
    std::mt19937_64 r(2774);
    // (picks: a hash of the inputs and the program serial; values own memory)
    against_std<Pick>(r, [](std::mt19937_64& g) { return g() % 3000 * 0x9E3779B97F4A7C15ull; },
                      [](std::mt19937_64& g) {
                          Pick p;
                          p.p = (const void*)(uintptr_t)(g() % 500 * 64 + 64);
                          for (int n = (int)(g() % 5); n--;) p.handles.push_back((uint32_t)g());
                          return p;
                      }, 2000, 200000);
    // (a thread's pipelines: mixed keys, pointer values, never cleared)
    against_std<const void*>(r, [](std::mt19937_64& g) { return g() % 20000 * 0xbf58476d1ce4e5b9ull + 1; },
                             [](std::mt19937_64& g) { return (const void*)(uintptr_t)(g() % 100000 * 8 + 8); }, ~0ull >> 1, 200000);
    // (c1 uploads: a stage's address, cleared at every recording's start)
    against_std<std::pair<VkBuffer, uint64_t>>(r, [](std::mt19937_64& g) { return 0x7ff600000000ull + g() % 4096 * 0x2a8; },
                                               [](std::mt19937_64& g) { return std::make_pair((VkBuffer)(uintptr_t)(g() % 4 * 16 + 16), g() % 4096 * 256); },
                                               300, 200000);
    // (a clear lets a value's memory go: a Pick's handles are emptied at once, not when the slot is used again)
    FlatMap<Pick> m;
    for (uint64_t k = 1; k <= 100; k++) m[k].handles.assign(64, 7);
    m.clear();
    for (size_t j = 0; j < m.slots.size(); j++)
        if (m.slots[j].hit.handles.capacity()) { std::fputs("FAIL: a clear kept a pick's handles\n", stderr); return 1; }
    if (m.slots.empty()) { std::fputs("FAIL: a clear gave the array back\n", stderr); return 1; }
    std::puts("flat map ok");
    return 0;
}
'''


def block(text, marker):
    if text.count(marker) != 1:
        raise SystemExit("FAIL: marker not found once: " + marker)
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def need(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cxx", default="clang++")
    a = ap.parse_args()
    draw = (VK / "vk_draw.cpp").read_text(encoding="utf-8")
    shader = (VK / "vk_shader.cpp").read_text(encoding="utf-8")
    need("using HandleTable = FlatMap<HandleHit>;" in draw, "handle_hits is the flat table")
    need("FlatMap<std::pair<VkBuffer, uint64_t>> c1_at;" in block(draw, "struct RecordingRes {"), "a recording's c1 map is flat")
    gp = block(draw, "PipeEntry* graphics_pipeline(")
    need("static thread_local FlatMap<PipeEntry*> mine;" in gp, "graphics_pipeline's thread map is flat")
    need("mine.find(mkey)" in gp and "mine[mkey] =" in gp, "graphics_pipeline's thread map is by key and object (mkey)")
    need("thread_local FlatMap<Pick> picks;" in shader, "program_for's picks are flat")
    pf = block(shader, "const Program* program_for(const NvnState& s, ProgramKind kind, const uint8_t color_types[8]) {")
    after = pf[pf.index("program_pick(s, kind, color_types);"):]
    need("Pick& pw = picks[key];" in after and "pk." not in after,
         "program_for writes its pick through a reference held across program_pick (an insert can move it)")
    need("std::unordered_map<uint64_t, Pick>" not in shader and "unordered_map<uint64_t, PipeEntry*> mine" not in draw,
         "a node map is left in a per-draw cache")
    with tempfile.TemporaryDirectory(prefix="flat-map-") as d:
        src, exe = Path(d) / "t.cpp", Path(d) / "t.exe"
        src.write_text(DRIVER, encoding="utf-8")
        r = subprocess.run([a.cxx, "-std=c++20", "-O2", "-Wall", "-Wextra", "-I", str(VK), str(src), "-o", str(exe)],
                           capture_output=True, text=True)
        if r.returncode:
            raise SystemExit("compile failed:\n" + r.stderr[-3000:])
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=120)
        print(r.stdout.strip() + r.stderr.strip())
        if r.returncode:
            raise SystemExit(1)
    print("PASS: the replay's per-draw caches flat, answering as std::unordered_map")


if __name__ == "__main__":
    main()
