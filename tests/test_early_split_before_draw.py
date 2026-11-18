"""RX_VK_READBACK_EARLY's end after a writer keeps RX_VK_SPLIT_BEFORE_DRAW's rule (no game/GPU required): where a part ends
only right before a plain draw (part_ends_before_draw: Intel by default), the part a readback's writer was recorded in ends
at the next plain draw, never right after the writer, so no part begins with a mesh draw or a dispatch; elsewhere it ends
right after the writer, as on the Steam Deck where the early reads were measured. The writer's part ends no earlier than
the writer either way, so a read that waits for that part still waits for its writer.

The replay loop's steps (the end maybe_split asked for, before the op; the op; maybe_split's count; the early end, after
the op) run on streams of draws, mesh draws and dispatches, with part_ends_before_draw, maybe_split, split_part and
early_split cut from gpu/vk/vk_replay.cpp and compiled with stubs.

python -I -B tests/test_early_split_before_draw.py [--cxx g++]
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))   # (tests/srccut.py: python -I leaves this folder off the path)
from srccut import block, between   # noqa: E402

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


FIXTURE = r"""
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
typedef int VkCommandBuffer;   // (the part's index)
enum : uint32_t { NOP_DRAW = 1, NOP_DRAW_IDX, NOP_DRAW_INDIRECT, NOP_DRAW_MESH, NOP_DISPATCH, NOP_DISPATCH_INDIRECT };
static bool env_value_off(const char* e) {
    return !*e || !strcmp(e, "0") || !strcmp(e, "off") || !strcmp(e, "false") || !strcmp(e, "no");
}
static bool env_on(const char* n) { const char* e = getenv(n); return e && !env_value_off(e); }
static int64_t env_int(const char* n, int64_t d) { const char* e = getenv(n); return e ? atoll(e) : d; }
static struct { struct { uint32_t vendorID; } props; } dev = {{(uint32_t)strtoul(getenv("VENDOR") ? getenv("VENDOR") : "0", nullptr, 0)}};
static bool pools_mirrored() { return false; }
static bool dump_on() { return false; }
struct Recording { VkCommandBuffer cmd = 0; uint64_t part = 0; };
static std::vector<std::vector<uint32_t>> parts;   // (the ops each part recorded)
static Recording recs[64];
static Recording& begin_recording(uint64_t) {
    const int i = (int)parts.size();
    parts.emplace_back();
    recs[i].cmd = i, recs[i].part = (uint64_t)i + 1;
    return recs[i];
}
static void end_pass(VkCommandBuffer&) {}
static void flush_ub_updates(VkCommandBuffer&) {}
static void memory_end_submission(VkCommandBuffer&, uint64_t) {}
static void memory_begin_submission() {}
static void full_barrier(VkCommandBuffer&, const char*) {}
static void occ_copy_part(VkCommandBuffer&) {}
static void submit_recording(Recording&, bool) {}
size_t ub_first_of_recording = 0;   // (not static: written only, as split_part does)
static std::vector<int> ub_updates;
static bool early_on = true;
static bool readback_early_on() { return early_on; }
static bool split_asked = false;   // (vk_memory.cpp: a write of a waited-for range asks for its part to end)
static bool memory_split_wanted() { const bool w = split_asked; split_asked = false; return w; }

Recording* rec_cur = nullptr;
uint64_t rec_cur_value = 0;
int rec_parts = 0;
int64_t part_work = 0;
constexpr int kMaxParts = 32;
thread_local bool split_off = false;
bool part_end_wanted = false;
bool early_split_pending = false;
void split_part(VkCommandBuffer& cmd);
void early_split(VkCommandBuffer& cmd);
/* COUNTERS */
/* BEFORE_DRAW */
/* MAYBE_SPLIT */
/* SPLIT_PART */
/* EARLY_SPLIT */

static const char* name(uint32_t op) {
    return op == NOP_DRAW ? "draw" : op == NOP_DRAW_MESH ? "mesh" : op == NOP_DISPATCH ? "dispatch" : "?";
}
// (a stream: 'd' a plain draw, 'm' a mesh draw, 'c' a dispatch, 'W' a dispatch writing a range a read has waited for).
// Returns the part the writer was recorded in
static int replay_stream(const std::string& stream) {
    parts.clear(), part_work = 0, rec_parts = 0, part_end_wanted = false, early_split_pending = false, split_asked = false;
    st_early_splits = 0, early_end_asked = false;
    Recording& first = begin_recording(1);
    rec_cur = &first, rec_cur_value = 1;
    VkCommandBuffer cmd = first.cmd;
    int writer_part = -1;
    struct { bool render_enabled = true, raster_discard = false; } s;
    const bool dry = false, worker = false, early = early_on;
    for (char c : stream) {
        struct { uint32_t op; } h = {c == 'd' ? (uint32_t)NOP_DRAW : c == 'm' ? (uint32_t)NOP_DRAW_MESH : (uint32_t)NOP_DISPATCH};
        bool split_after = false;
        /* REPLAY_BEFORE */
        parts[cmd].push_back(h.op);   // (the op, recorded in the part being recorded)
        if (c == 'W') writer_part = cmd, split_asked = true;
        maybe_split(cmd);   // (replay(): after every draw or dispatch)
        /* REPLAY_AFTER */
        (void)split_after;
    }
    return writer_part;
}
static int fails = 0;
static void check(bool ok, const std::string& what) {
    printf("%s  %s\n", ok ? "ok  " : "FAIL", what.c_str());
    fails += !ok;
}
static bool begins_plain(size_t i) { return parts[i].empty() || parts[i][0] == NOP_DRAW; }
int main(int argc, char** argv) {
    const std::string mode = argc > 1 ? argv[1] : "";
    const std::string gap(20, 'd');   // (past RX_VK_READBACK_EARLY_GAP's 16 draws)
    if (mode == "before-draw") {   // (Intel, or RX_VK_SPLIT_BEFORE_DRAW=1)
        int w = replay_stream(gap + "W" + "ccmmd" + "ddd");
        check(parts.size() == 2, "the writer's part ended once");
        check(w == 0 && parts[0].size() == 25, "it ran on over the dispatches and mesh draws after the writer, to the plain draw");
        check(parts.size() == 2 && begins_plain(1), "and the next part begins with that plain draw, not a mesh draw or a dispatch");
        check(st_early_splits == 1, "counted once, as a part ended after a readback's writer");
        replay_stream(gap + "W" + "cccmm");
        check(parts.size() == 1, "no plain draw after the writer: no part ends, the submission's end comes first");
        check(st_early_splits == 0, "and nothing is counted");
        replay_stream(std::string(130, 'd') + "mmccd");
        check(parts.size() == 2 && parts[0].size() == 120, "maybe_split's end by its count, before a plain draw, is as before");
        check(st_early_splits == 0, "and is not counted as an early end");
        replay_stream(std::string(118, 'd') + "W" + "mmmmmd" + "dd");   // (the count's end and the writer's at one draw)
        check(parts.size() == 2 && parts[0].size() == 124, "the count's end and the writer's are one end, at the plain draw");
        for (size_t i = 0; i < parts.size(); i++) check(begins_plain(i), "part " + std::to_string(i) + " begins with a plain draw");
    } else if (mode == "at-once") {   // (elsewhere: right after the writer, as measured on the Steam Deck)
        int w = replay_stream(gap + "W" + "ccmmd" + "ddd");
        check(parts.size() == 2 && w == 0 && parts[0].size() == 21, "the writer's part ends right after the writer");
        check(parts.size() == 2 && parts[1][0] == NOP_DISPATCH, "the next part begins with the op after it, whatever it is");
        check(st_early_splits == 1, "counted once");
        replay_stream("dddd" + std::string("W") + gap);
        check(parts.size() == 2 && parts[0].size() == 16, "a writer before the gap's 16 draws ends its part at the 16th");
    } else if (mode == "off") {   // (RX_VK_READBACK_EARLY off: the parts maybe_split makes, nothing else)
        early_on = false;
        replay_stream(gap + "W" + "ccmmd" + "ddd");
        check(parts.size() == 1 && st_early_splits == 0, "no part ends after the writer");
        replay_stream(std::string(250, 'd'));
        check(parts.size() == 3 && parts[0].size() == 120 && parts[1].size() == 120, "maybe_split's ends, every 120 draws");
    } else {
        check(false, "a mode: before-draw, at-once or off");
    }
    for (size_t i = 0; i < parts.size() && fails; i++) {
        printf("  part %zu:", i);
        for (uint32_t op : parts[i]) printf(" %s", name(op));
        printf("\n");
    }
    return fails ? 1 : 0;
}
"""


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    loop = block(replay, "void replay(VkCommandBuffer& cmd, NvnState& s, const uint8_t* p, const uint8_t* end")
    before = between(loop, "// (the part's end maybe_split asked for", "switch (h.op) {")
    after = block(loop, "if (early && !dry && !worker) {")
    if "early_split(cmd);" not in after:
        raise SystemExit("FAIL: replay() no longer ends a writer's part through early_split")
    src = (FIXTURE.replace("/* COUNTERS */", between(replay, "std::atomic<int64_t> st_early_splits{0};", "/// The recording's part ends here"))
           .replace("/* BEFORE_DRAW */", block(replay, "bool part_ends_before_draw() {"))
           .replace("/* MAYBE_SPLIT */", block(replay, "void maybe_split(VkCommandBuffer& cmd) {"))
           .replace("/* SPLIT_PART */", block(replay, "void split_part(VkCommandBuffer& cmd) {"))
           .replace("/* EARLY_SPLIT */", block(replay, "void early_split(VkCommandBuffer& cmd) {"))
           .replace("/* REPLAY_BEFORE */", before).replace("/* REPLAY_AFTER */", after))
    base = {k: v for k, v in os.environ.items() if not k.startswith("RX_VK_")}
    runs = (("before-draw", dict(base, VENDOR="0x8086")),                               # (Intel: the rule by default)
            ("before-draw", dict(base, VENDOR="0x1002", RX_VK_SPLIT_BEFORE_DRAW="1")),   # (asked for elsewhere)
            ("at-once", dict(base, VENDOR="0x1002")),                                    # (the Steam Deck's AMD APU)
            ("at-once", dict(base, VENDOR="0x8086", RX_VK_SPLIT_BEFORE_DRAW="0")),       # (Intel with the rule off)
            ("off", dict(base, VENDOR="0x8086")), ("off", dict(base, VENDOR="0x1002")))
    with tempfile.TemporaryDirectory(prefix="early-split-") as tmp:
        tmp = Path(tmp)
        c, exe = tmp / "split.cpp", tmp / ("split.exe" if os.name == "nt" else "split")
        c.write_text(src, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-Wno-unused-variable",
                        "-Wno-unused-parameter", str(c), "-o", str(exe)], check=True)
        for mode, env in runs:
            print("--", mode, "vendor", env["VENDOR"], " ".join("%s=%s" % (k, v) for k, v in env.items() if k.startswith("RX_VK_")))
            r = subprocess.run([str(exe), mode], capture_output=True, text=True, timeout=60, env=env)
            print(r.stdout, end="")
            if r.returncode:
                raise SystemExit("FAIL: %s, vendor %s\n%s" % (mode, env["VENDOR"], r.stderr))
    print("PASS: a writer's part ends at the next plain draw where parts end only there (RX_VK_SPLIT_BEFORE_DRAW), at once elsewhere")


if __name__ == "__main__":
    main()
