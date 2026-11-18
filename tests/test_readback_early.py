"""RX_VK_READBACK_EARLY (on by default where the pools have no mirror; =0 off): a CPU read of GPU results written in place
waits for the part its last writer was recorded in, not its whole submission, and that part ends right after the writer
(gpu/vk/vk_memory.cpp, gpu/vk/vk_replay.cpp's invalidate and replay).

With no mirror (the Steam Deck: every page) a page the GPU writes is noted with its submission only, and a read of it waited for
the whole submission: the game's job polled ~18 ms a frame for its camera block while the GPU finished a 22-26 ms submission
after the writer. Cut from the source and run:

  - with the switch on, a GPU write in place to a range whose read has waited keeps each of its pages' submission and part,
    whatever its size (note_direct_write notes only bindings up to 1 MB for the plain wait); a write elsewhere, or before
    any read waited, keeps nothing; off, nothing;
  - the part is given only when the newest write it knows is the range's newest (another, unseen, leaves the whole
    submission), and the newest of a submission's writes to its pages;
  - such a write asks for its part to end (once), not the uniform updates written at a part's end; the ranges are at most 64,
    the oldest let go with its pages;
  - invalidate's early wait: for the newest of the in-place writer's part and a mirror's part, when a page written in place is
    not done; the whole submission otherwise (writer not known, only mirrored pages pending, the part not found); none for a
    range RX_VK_READBACK_LATE reads late;
  - unset: on without mirrors and off with them; =0 off; asked for, on with mirrors too;
  - with RX_VK_PARALLEL=2 or more the switch is left off (a segment's part never reaches the recordings' timeline);
  - the wiring: note_direct_write notes every in-place write; the early wait comes before the choice of the usual wait, which
    it replaces only when it waited; the replay ends a part after an op that asked, at least RX_VK_READBACK_EARLY_GAP draws
    into it, maybe_split still ends one every RX_VK_CHUNK draws, and a draw of a program that writes storage buffers builds
    its descriptors;
  - RX_VK_LOG_EARLY_CHECK (a diagnostic): words changed after a read let go early, by whether the CPU wrote a page they are on
    (ec_compare, a word across a page's end included), the CPU's pages by interval and the second full collection begun after a
    copy closing it (early_check_cpu_pages), cut out and run; and its wiring: the sampled read's main wait is invalidate's usual
    choice;
  - RX_VK_LOG_RB_WRITERS: a recording closes its submission's span on every path that finishes it, a burst's end included
    (burst_end and the spans cut out and run).

python -I -B tests/test_readback_early.py [--cxx g++]
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))   # (tests/srccut.py: python -I leaves this folder off the path)
from srccut import block, between   # noqa: E402

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


MEMORY = r"""
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <memory>
#include <mutex>
#include <unordered_map>
#include <vector>
constexpr uint64_t kPageShift = 12, kChunkPages = 16, kPages = 1024;
#include "readback_early.h"   // (and its rule; with compat/hookshot_env.h's env_on)
static void logf(const char*, ...) {}
static struct { struct { char deviceName[256]; } props; } dev = {{""}};   // (the device's name: not asked; the pools' mirror is)
static bool replay_render_thread_on() { return false; }
namespace {
bool mirror_on() { return std::getenv("TEST_EARLY_MIRRORS") != nullptr; }   // (a discrete card's pools: the default is off)
}  // namespace
constexpr uint32_t kRbWriterUb = 0x10000, kRbWriterWb = 0x10001;
struct RbWriter {
    uint64_t value = 0, part = 0, work = 0, key = 0;
    uint32_t what = 0;
};
bool rb_writers_on();
bool readback_early_on();
static void early_check_gpu_write(uint64_t, uint64_t, uint64_t, uint64_t, int) {}   // (RX_VK_LOG_EARLY_CHECK: below)
uint64_t memory_in_place_writer_part(uint64_t guest, uint64_t size, uint64_t whole);
void memory_rb_waited(uint64_t guest, uint64_t size);
bool memory_rb_waited_range(uint64_t guest, uint64_t size);
bool memory_split_wanted();
bool memory_readback_early_active();
namespace {
/* PAGES */
std::atomic<uint64_t> mem_rec_part{0}, mem_in_place_part{0};
}  // namespace
/* WRITERS */
static int failures;
static void check(bool ok, const char* what) {
    std::printf("%s  %s\n", ok ? "ok  " : "FAIL", what);
    failures += !ok;
}
constexpr uint64_t P = 4096;
constexpr uint32_t kDispatch = 27, kCopy = 6;   // (any op but the uniform updates)
static void write(uint64_t lo, uint64_t hi, uint64_t value, uint64_t rec, uint32_t what) {   // (as note_direct_write)
    mem_rec_part = rec;
    memory_writer_note(what, 0);
    early_in_place_write(lo, hi, value);
    if (hi - lo <= (1u << 20)) wb_pages_note(lo, hi, value, 0);
}
int main(int argc, char** argv) {
    const bool on = argc > 1 && !std::strcmp(argv[1], "on");
    check(readback_early_on() == on, "the switch is read");
    write(1 * P, 1 * P + 64, 10, 5, kDispatch);
    check(!memory_readback_early_active(), "idle before a read of pages written in place waited");
    check(memory_in_place_writer_part(1 * P, 64, 10) == 0, "before any read waited: nothing kept");
    check(!memory_split_wanted(), "and no split asked for");
    memory_rb_waited(1 * P, 0x3980);   // (pages 1-4)
    check(memory_rb_waited_range(1 * P + 100, 8) == on, "a range whose read waited is known");
    check(memory_readback_early_active() == on, "and the tracking in use");
    check(!memory_rb_waited_range(9 * P, 8), "another is not");
    write(1 * P, 1 * P + 0x3980, 11, 7, kDispatch);
    check(memory_in_place_writer_part(1 * P, 0x3980, 11) == (on ? 7u : 0u), "a write in place to it keeps its part");
    check(memory_split_wanted() == on, "and asks for its part to end");
    check(!memory_split_wanted(), "once");
    check(memory_in_place_writer_part(1 * P, 0x3980, 12) == 0, "a newer write it did not see: the whole submission");
    write(2 * P, 2 * P + 64, 11, 8, kCopy);
    check(memory_in_place_writer_part(1 * P, 0x3980, 11) == (on ? 8u : 0u), "the latest part of the submission's writes to its pages");
    check(memory_split_wanted() == on, "a copy asks for its part to end too");
    write(9 * P, 10 * P, 12, 9, kDispatch);
    check(!memory_split_wanted(), "a write elsewhere asks for no split");
    check(memory_in_place_writer_part(9 * P, 64, 12) == 0, "and keeps nothing");
    write(0, 320 * P, 13, 10, kDispatch);   // (1.25 MiB: past note_direct_write's 1 MB for the plain wait, kept here whatever its size)
    check(memory_split_wanted() == on, "a write over 1 MB over it asks for its part to end");
    check(memory_in_place_writer_part(1 * P, 0x3980, 11) == 0,
          "and the read of what the plain wait knows (11) no longer finds 11's write there: the whole submission");
    write(1 * P, 1 * P + 64, 14, 11, kRbWriterUb);
    check(memory_in_place_writer_part(1 * P, 64, 14) == (on ? 11u : 0u), "the uniform updates' write keeps its part");
    check(!memory_split_wanted(), "but asks for no split: written at their part's end already");
    // (a range widened over a page that the same submission wrote before: that write was not seen)
    memory_rb_waited(20 * P, 64);
    write(20 * P, 20 * P + 64, 15, 12, kDispatch);
    write(21 * P, 21 * P + 64, 15, 13, kDispatch);   // (page 21: no range of it yet)
    (void)memory_split_wanted();
    memory_rb_waited(20 * P, 2 * P);
    check(memory_in_place_writer_part(20 * P, 2 * P, 15) == 0, "a range widened over a page its submission wrote unseen: the whole submission");
    check(memory_in_place_writer_part(20 * P, 64, 15) == (on ? 12u : 0u), "its first page alone: that page's part");
    write(21 * P, 21 * P + 64, 15, 14, kDispatch);
    check(memory_in_place_writer_part(20 * P, 2 * P, 15) == (on ? 14u : 0u), "seen once written again: the later part");
    (void)memory_split_wanted();
    // (two ranges of one page: a write of the page's other bytes in a later part is seen, for the page)
    memory_rb_waited(30 * P, 64);
    write(30 * P, 30 * P + 64, 16, 15, kDispatch);
    check(memory_split_wanted() == on, "a write of the bytes read asks for its part to end");
    write(30 * P + 128, 30 * P + 192, 16, 16, kDispatch);
    check(!memory_split_wanted(), "a write of the page's other bytes asks for no split");
    check(memory_in_place_writer_part(30 * P, 64, 16) == (on ? 16u : 0u), "but is the page's newest writer: its part");
    memory_rb_waited(30 * P + 128, 64);
    check(memory_in_place_writer_part(30 * P + 128, 64, 16) == (on ? 16u : 0u), "and for a second range of the page");
    write(31 * P, 31 * P + 64, 16, 17, kDispatch);   // (page 31: in no range)
    check(memory_in_place_writer_part(30 * P, 2 * P, 16) == 0, "a range reaching past it into a page written unseen: the whole submission");
    // (a write over 1 MiB later in the same submission: noted in early_pages but not in wb_pages, note_direct_write. zeldaootr's
    // and mooki's reviews of https://git.magicbean.dev/MagicBeanDev/Hookshot/pulls/303)
    memory_rb_waited(400 * P, 4 * P);
    write(400 * P, 400 * P + 64, 50, 20, kDispatch);
    write(401 * P, 401 * P + 300 * P, 50, 30, kDispatch);
    (void)memory_split_wanted();
    check(memory_in_place_writer_part(400 * P, 4 * P, 50) == (on ? 30u : 0u), "a later write over 1 MiB of the same submission: its part");
    memory_rb_waited(800 * P, 2 * P);
    write(801 * P, 801 * P + 64, 60, 40, kDispatch);         // (B: submission 60, a small binding)
    write(800 * P, 800 * P + 64, 61, 41, kDispatch);         // (A: submission 61, part 41)
    write(801 * P, 801 * P + 320 * P, 61, 42, kDispatch);    // (B again in 61's part 42, over 1 MiB: wb_pages still says 60)
    (void)memory_split_wanted();
    check(memory_in_place_writer_part(800 * P, 2 * P, 61) == (on ? 42u : 0u), "a small write, then a large one of the other page: the large one's part");
    for (uint64_t r = 0; r < 64; r++) memory_rb_waited((100 + 2 * r) * P, 64);   // (64 more ranges: the first is let go)
    check(!memory_rb_waited_range(1 * P + 100, 8), "the oldest range let go");
    check(memory_in_place_writer_part(1 * P, 64, 14) == 0, "with its pages");
    check(memory_rb_waited_range(226 * P, 8) == on, "the newest kept");
    return failures ? 1 : 0;
}
"""

DIAGNOSTIC = r"""
#include <algorithm>
#include <cstdint>
#include <cstdio>
struct RbDiag { bool snap = false; };
static int waits = 0;
static uint64_t waited_value = 0;
static bool succeeds = true;
static bool readback_wait_value(uint64_t value) { ++waits; waited_value = value; return succeeds; }
/* TARGET */
/* FINISH */
int main() {
    if (rb_diag_early_part(20, 30, true) != 30 || rb_diag_early_part(40, 30, true) != 40 ||
        rb_diag_early_part(0, 30, true) || rb_diag_early_part(20, 30, false)) return 1;
    RbDiag d{true};
    rb_diag_finish(d, 123);
    if (!d.snap || waits != 1 || waited_value != 123) return 2;
    succeeds = false;
    rb_diag_finish(d, 124);
    if (d.snap || waits != 2 || waited_value != 124) return 3;
    rb_diag_finish(d, 125);
    if (d.snap || waits != 2) return 4;
    std::puts("ok: diagnostic uses the early target and requires the whole submission before comparing");
}
"""

CHOICE = r"""
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
static uint64_t done_value;
static uint64_t completed() { return done_value; }
static bool early_on = true, late_rule = false;   // (late_rule: RX_VK_READBACK_LATE names the range)
static int checks_added;   // (RX_VK_LOG_EARLY_CHECK: a read let go early is checked)
static bool early_check_on() { return true; }
static void early_check_read(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, bool) { checks_added++; }
static bool readback_early_on() { return early_on; }
static uint64_t writer_part;
static int writer_asks, recorded_waits, writer_asked_after_recorded;
static bool recorded_ok = true;   // (the writer's submission recorded to its end within the wait's 250 ms)
static bool early_recorded_wait(uint64_t, double* ms) { recorded_waits++, *ms = recorded_ok ? 0 : 250; return recorded_ok; }
static uint64_t memory_in_place_writer_part(uint64_t, uint64_t, uint64_t) {
    writer_asks++, writer_asked_after_recorded += recorded_waits == writer_asks;
    return early_on ? writer_part : 0;
}
static int waited_marks;
static void memory_rb_waited(uint64_t, uint64_t) { waited_marks++; }
static uint64_t waited_part;
static bool part_known = true;
static bool wait_recorded_part(uint64_t part, uint64_t, int* ok) {
    if (!part_known) return false;
    waited_part = part, *ok = 1;
    return true;
}
struct Host { uint64_t gpu_guest(uint64_t g) const { return g; } };
static Host host_v;
static Host* host = &host_v;
static std::atomic<int64_t> st_early_waits{0}, st_early_ns{0}, st_early_whole{0};
static std::atomic<int64_t> st_early_rec{0}, st_early_rec_ns{0}, st_early_rec_late{0};
static const bool unforced = true, by_part = true;
static int failures;
static void check(bool ok, const char* what) {
    std::printf("%s  %s\n", ok ? "ok  " : "FAIL", what);
    failures += !ok;
}
/// (v: the range's newest write-back value; part: a mirror's part; whole: the newest in-place value) -> waited early, for which part
static bool choose(uint64_t v, uint64_t part, uint64_t whole) {
    const uint64_t gpu = 0x1000, size = 0x3980;
    bool w = false;
    waited_part = 0;
    const bool pending = v > completed(), late = pending && late_rule;
    /* EARLY */
    (void)w;
    return early_done;
}
int main() {
    done_value = 10;
    writer_part = 40;
    check(choose(12, 0, 12) && waited_part == 40, "a page written in place: its writer's part");
    check(choose(12, 44, 12) && waited_part == 44, "with a newer mirror part too: the newer part");
    check(choose(12, 30, 12) && waited_part == 40, "with an older mirror part: the writer's");
    check(!choose(12, 41, 9) && waited_part == 0, "only mirrored pages pending: the usual choice");
    writer_part = 0;
    check(!choose(12, 0, 12), "the writer not known: the whole submission");
    writer_part = 40;
    part_known = false;
    check(!choose(12, 0, 12), "the part not found: the whole submission");
    part_known = true;
    check(!choose(9, 0, 9), "done already: no wait");
    check(writer_asks == recorded_waits && writer_asked_after_recorded == writer_asks,
          "the writer's part is asked for only once its submission is recorded to its end");
    recorded_ok = false;
    const int asks = writer_asks;
    check(!choose(12, 0, 12) && waited_part == 0 && writer_asks == asks,
          "its submission still recorded after the wait's 250 ms: the whole submission, no writer asked for");
    check(st_early_rec == 1 && st_early_rec_ns == 250000000 && st_early_rec_late == 1,
          "the wait for the recording counted, and that it ran past its 250 ms");
    recorded_ok = true;
    late_rule = true;
    check(!choose(12, 0, 12) && waited_part == 0, "a range RX_VK_READBACK_LATE reads late: no wait, not marked");
    late_rule = false;
    early_on = false;
    check(!choose(12, 0, 12), "off: the usual choice");
    check(st_early_waits == 3 && st_early_whole == 3, "counted");
    check(checks_added == st_early_waits, "every read let go early is checked, no other");
    check(waited_marks == 6, "each read with a page written in place pending marked its pages (not one of mirrored pages only)");
    return failures ? 1 : 0;
}
"""

RECORDED = r"""
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <thread>
#include "compat/hookshot_env.h"
static void logf(const char*, ...) {}
static std::mutex rec_map_mu;
static std::condition_variable rec_map_cv;
static bool rb_writers_on() { return true; }
static bool readback_early_on() { return true; }
static uint64_t closed_value;
/* OPEN */
/* CLOSE */
void rb_release_close(uint64_t value) { closed_value = value; }
static int failures;
static void check(bool ok, const char* what) {
    std::printf("%s  %s\n", ok ? "ok  " : "FAIL", what);
    failures += !ok;
}
int main(int argc, char** argv) {
    double ms = -1;
    if (argc > 1 && !std::strcmp(argv[1], "off")) {   // (RX_VK_READBACK_EARLY_RECORDED=0)
        rec_open(5);
        check(early_recorded_wait(5, &ms) && ms == 0, "RX_VK_READBACK_EARLY_RECORDED=0: no wait for its own recording");
        return failures ? 1 : 0;
    }
    check(early_recorded_wait(7, &ms) && ms == 0, "no recording open: no wait");
    rec_open(7);
    check(early_recorded_wait(8, &ms) && ms == 0, "another submission's recording open: no wait");
    std::thread t([] { std::this_thread::sleep_for(std::chrono::milliseconds(40)); rec_close(); });
    const bool done = early_recorded_wait(7, &ms);
    t.join();
    check(done && ms >= 30 && ms < 240, "its own submission's recording open: waits until it is finished");
    check(closed_value == 7, "and the release probe is told which recording finished");
    rec_open(9);
    check(!early_recorded_wait(9, &ms) && ms >= 240, "a recording not finished within 250 ms: false (the whole submission)");
    rec_close();
    check(early_recorded_wait(9, &ms) && ms == 0, "finished since: no wait");
    return failures ? 1 : 0;
}
"""

PROBE = r"""
#include <algorithm>
#include <atomic>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
struct RbWriter { uint64_t value = 0, part = 0, work = 0, key = 0; uint32_t what = 0; };
static RbWriter newest;   // (the diagnostics' record of the range: its newest writer)
static bool memory_rb_writers(uint64_t, uint64_t, RbWriter& first, RbWriter& last, int* pages) {
    first = last = newest, *pages = 1;
    return newest.value != 0;
}
struct Host { uint64_t gpu_guest(uint64_t g) const { return g; } };
static Host host_v;
static Host* host = &host_v;
static std::atomic<uint64_t> rec_open_tag{0};
static std::string logged;
static void logf(const char* f, ...) {
    char b[1024];
    va_list ap;
    va_start(ap, f);
    std::vsnprintf(b, sizeof b, f, ap);
    va_end(ap);
    logged += b, logged += "\n";
}
/* PROBE */
static int failures;
static void check(bool ok, const char* what) {
    std::printf("%s  %s\n", ok ? "ok  " : "FAIL", what);
    failures += !ok;
}
int main() {
    const uint64_t A = 0x1000, N = 0x3980;
    rec_open_tag = 20;
    newest = {20, 5, 100};                                       // (the first writers of submission 20 recorded)
    rb_release_note(A, N, 20, true, true);                       // (this thread let go at them)
    std::thread([&] { rb_release_note(A, N, 20, true, true); }).join();   // (another thread too, never reading it again)
    newest = {20, 8, 160};                                       // (a writer of the range recorded after both)
    rb_release_note(A, N, 20, true, true);                       // (this thread reads it again: let go at that writer)
    rb_release_note(A, N, 19, true, false);                      // (a read whose record names another submission: not counted)
    rb_release_close(20);
    rec_open_tag = 0;
    rb_release_note(A, N, 20, false, false);                     // (and once more after, done: no release, a read again)
    newest = {30, 12, 300};                                      // (submission 30, its recording finished before its reads)
    for (int i = 0; i < 3; i++) rb_release_note(0x9000, 0x40, 30, true, true);
    rb_release_report();
    check(logged.empty(), "a release is reported an interval after its recording finished, not at once");
    rb_release_report();
    check(logged.find("size 0x3980: 3 let go before their writer's submission was done (3 by the early wait), 3 of them while it "
                      "was still recorded; 2 before a writer of the range recorded later in it (2 by the early wait), 1 of those the "
                      "thread's last read of the range for it") != std::string::npos, "counted");
    check(logged.find("size 0x40: 3 let go before their writer's submission was done (3 by the early wait), 0 of them while it was "
                      "still recorded; 0 before a writer") != std::string::npos,
          "a read let go once its writer's recording had finished: counted as such, at once, before no later writer");
    std::printf("%s", logged.c_str());
    logged.clear();
    rb_release_report();
    check(logged.empty(), "and let go");
    return failures ? 1 : 0;
}
"""

CHECK = r"""
#include <algorithm>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
#include <memory>
#include <mutex>
#include <vector>
static bool early_check_on() { return true; }
static int reaps;
static void ec_reap() { reaps++; }
/* COMPARE */
/* STRUCT */
static std::mutex ec_mu;
static std::deque<std::unique_ptr<EarlyCheck>> ec_pending;
/* CPU_PAGES */
static int failures;
static void check(bool ok, const char* what) {
    std::printf("%s  %s\n", ok ? "ok  " : "FAIL", what);
    failures += !ok;
}
int main() {
    const uint64_t g = 0x10000ff0;   // (a range across pages 0x10000-0x10003, as 0x3980 bytes from +0xff0)
    std::vector<uint8_t> a(0x3980, 7), b = a;
    EcDiff d = ec_compare(a.data(), b.data(), g, 0x3980, 0);
    check(!d.words_gpu && !d.words_cpu, "unchanged: nothing");
    b[0x20] = 1, b[0x21] = 2;          // (one word on the range's page 1: guest 0x10001010)
    b[0x2000] = 9;                     // (page 3)
    d = ec_compare(a.data(), b.data(), g, 0x3980, 0);
    check(d.words_gpu == 2 && d.first_gpu == 0x20 && !d.words_cpu, "changed where the CPU wrote no page: the GPU's, with the first offset");
    d = ec_compare(a.data(), b.data(), g, 0x3980, 1u << 1);
    check(d.words_gpu == 1 && d.words_cpu == 1 && d.first_gpu == 0x2000, "a word on a page the CPU wrote: the CPU's");
    std::vector<uint8_t> c(6, 0), e2 = c;
    e2[5] = 1;
    d = ec_compare(c.data(), e2.data(), 0x5000, 6, 0);
    check(d.words_gpu == 1, "a size not a multiple of 4: its last bytes compared");
    std::vector<uint8_t> u(8, 0), u2 = u;
    u2[3] = 1;   // (guest 0x1ffe + 3 = 0x2001: the word at +0 runs from page 1 into page 2)
    d = ec_compare(u.data(), u2.data(), 0x1ffe, 8, 1u << 1);
    check(d.words_cpu == 1 && !d.words_gpu, "a word across a page's end: the CPU's when it wrote either page");
    const uint32_t pages[] = {0x10003, 0x9999, 0x10000};
    check(ec_pages_hit(g, 0x3980, pages, 3) == ((1u << 0) | (1u << 3)), "the collected pages of the range, as bits");

    ec_pending.push_back(std::make_unique<EarlyCheck>());
    EarlyCheck& x = *ec_pending.back();
    x.guest = g, x.size = 0x3980;
    const uint32_t p1[] = {0x10001};
    early_check_cpu_pages(p1, 1, false, 0);
    check(x.cpu1 == 2 && !x.cpu2, "a capture's pages before sm: the first interval's");
    early_check_cpu_pages(nullptr, 0, true, 5);
    check(!x.closed1, "a full collection before sm is taken closes nothing");
    x.stage = 1, x.gen_m = 5;
    const uint32_t p2[] = {0x10002};
    early_check_cpu_pages(p2, 1, true, 5);
    check(!x.closed1 && x.cpu1 == 6 && x.cpu2 == 4, "one begun before sm was taken: both intervals', the first still open");
    early_check_cpu_pages(nullptr, 0, true, 6);
    check(!x.closed1, "the first full collection begun after sm does not close it yet (a mark published late)");
    early_check_cpu_pages(nullptr, 0, true, 7);
    check(x.closed1 && !x.closed2, "the second closes the first interval");
    const uint32_t p3[] = {0x10000};
    early_check_cpu_pages(p3, 1, false, 0);
    check(x.cpu1 == 6 && x.cpu2 == 5, "then pages count for the second only");
    x.stage = 2, x.gen_2 = 8;
    early_check_cpu_pages(nullptr, 0, true, 8);
    check(!x.closed2, "one begun before s2 does not close the second");
    early_check_cpu_pages(nullptr, 0, true, 9);
    check(!x.closed2, "nor the first begun after it");
    const int reaps_before = reaps;
    early_check_cpu_pages(nullptr, 0, true, 10);
    check(x.closed2 && reaps == reaps_before + 1, "the second does; the done ones are reaped at each report");
    return failures ? 1 : 0;
}
"""

SPAN = r"""
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <map>
#include <mutex>
static uint64_t work;   // (draws and dispatches recorded so far)
static uint64_t memory_work_count() { return work; }
static bool rb_writers_on() { return true; }
struct Recording { uint64_t value = 0, part = 0; };
static Recording rec_v;
static Recording* rec_cur = nullptr;
static std::mutex replay_mu;
static bool burst_open = false;
static uint64_t burst_value = 0, ev_looked = 0;
static bool ev_looked_any = false;
static std::atomic<uint64_t> ev_cpu_settled{0};
static int finished;
static uint64_t finished_value;
static void finish_recording(uint64_t v) { rec_cur = nullptr, finished++, finished_value = v; }
/* SPANS */
/* BURST_END */
static int failures;
static void check(bool ok, const char* what) {
    std::printf("%s  %s\n", ok ? "ok  " : "FAIL", what);
    failures += !ok;
}
int main() {
    rec_v = {20, 5}, rec_cur = &rec_v, work = 100, burst_open = true, burst_value = 20;
    rb_span_begin(20, 5);
    work = 130, rec_v.part = 6;   // (the writer)
    work = 150, rec_v.part = 7;   // (work after it, in a later part)
    burst_end();
    const SubSpan& s = rb_spans[20];
    check(finished == 1 && finished_value == 20, "the burst's recording finished at its end");
    check(s.first_part == 5 && s.last_part == 7 && s.w0 == 100 && s.w1 == 150,
          "and its span closed there: the last part and the submission's work, not the writer's");
    return failures ? 1 : 0;
}
"""


def run(cxx, src, exe, args=(), env=None):
    subprocess.run([cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-Wno-unused-variable",
                    "-pthread", "-I", str(ROOT / "gpu" / "vk"), str(src), "-o", str(exe)], check=True)
    r = subprocess.run([str(exe), *args], capture_output=True, text=True, timeout=60, env=env)
    print(r.stdout, end="")
    if r.returncode:
        raise SystemExit("FAIL: %s %s\n%s" % (exe.name, " ".join(args), r.stderr))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    memory = (ROOT / "gpu/vk/vk_memory.cpp").read_text(encoding="utf-8")
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    pages = between(memory, "std::mutex wb_pages_mu;", "} // namespace\n/// The newest write-back value")
    writers = between(memory, "namespace {\nthread_local uint32_t wr_what = 0;", "/// (RX_VK_LOG_RB_WRITERS) the writers of a range's pages")
    inv = block(replay, "void invalidate(uint64_t gpu, uint64_t size) {")
    if inv.index("rb_diag_finish(rbd, v);") > inv.index("rb_diag_done(gpu, size, rbd, d / 1e6, line);"):
        raise SystemExit("FAIL: diagnostic snapshot precedes the whole-submission wait")
    diag = block(replay, "void rb_diag_wait(")
    if "rb_diag_early_part(early, part, early_allowed)" not in diag or \
            "rb_diag_wait(gpu, size, rbd, whole, part, unforced && by_part && whole > completed())" not in inv:
        raise SystemExit("FAIL: diagnostic does not use the actual early-wait target and eligibility")
    early = between(inv, "bool early_done = false;", "if (early_done) {")
    # (the writer's part is chosen only once its submission is recorded to its end: a read let go while the rest was recorded took
    # the newest writer so far, and the culling camera block's last writer came after it in 269 of 745 reads on the Steam Deck)
    if "const bool recorded = early_recorded_wait(whole, &rec_ms);" not in early or \
            early.index("early_recorded_wait(whole, &rec_ms)") > early.index("memory_in_place_writer_part("):
        raise SystemExit("FAIL: invalidate: the early wait takes its writer's part before the writer's submission is recorded")
    if "early_recorded_wait(whole, &rec_ms)" not in diag or diag.index("early_recorded_wait") > diag.index("memory_in_place_writer_part("):
        raise SystemExit("FAIL: rb_diag_wait does not wait for the writer's recording as invalidate does: not its target")
    if "rec_open(tag);" not in block(replay, "bool run_submit(") or "rec_open(value);" not in block(replay, "void bench_replay(") or \
            "rec_close();" not in block(replay, "void finish_recording(uint64_t value) {") or \
            "rec_close();" not in block(replay, "void bench_replay("):
        raise SystemExit("FAIL: a recording opens or finishes without saying so to the early wait (rec_open, rec_close)")
    if replay.count("    rec_cur = nullptr;") != 2:   # (finish_recording's and bench_replay's: each closes its recording)
        raise SystemExit("FAIL: a recording is let go somewhere new: say so to the early wait there (rec_close)")
    if "rb_release_note(gpu, size, v, pending, early_done);" not in inv or "rb_release_report();" not in inv:
        raise SystemExit("FAIL: invalidate: the release probe (RX_VK_LOG_RB_WRITERS) is not told of the reads")
    if "if (early_done) {\n            } else if (pending && !late) {\n                int ok = 0;" not in inv:
        raise SystemExit("FAIL: invalidate: the early wait no longer replaces the usual choice only when it waited")
    if inv.index("bool early_done = false;") > inv.index("const bool in_place_after = memory_in_place_part() > part;"):
        raise SystemExit("FAIL: invalidate: the early wait comes after the usual choice")
    rep = block(replay, "void replay(VkCommandBuffer& cmd, NvnState& s, const uint8_t* p, const uint8_t* end = nullptr) {")
    if "if (split_after || memory_split_wanted()) early_split_pending = true;" not in rep or \
            "if (early_split_pending && part_work >= early_gap) early_split(cmd);\n        }\n        p += h.size;" not in rep:
        raise SystemExit("FAIL: replay: a part does not end after an op that asked for it, at least the gap into it")
    mem_note = block(memory, "void note_direct_write(")
    if "early_in_place_write(p.lo + off, p.lo + std::min(off + size, p.hi - p.lo), mem_rec_value);" not in mem_note.split("if (size <=")[0]:
        raise SystemExit("FAIL: note_direct_write does not note every write in place for the early wait, whatever its size")
    # (the writes no page record holds, a bare storage pointer's guessed range and a wide binding (vk_draw.cpp), are writers too:
    # zeldaootr's review of #303, finding 4)
    gpu_write = block(memory, "void memory_note_gpu_write(uint64_t gpu, uint64_t size) {")
    if "early_in_place_write(guest, guest + size, mem_rec_value);" not in gpu_write.split("for (auto it = imported")[0]:
        raise SystemExit("FAIL: memory_note_gpu_write does not note a bare or wide binding's write for the early wait")
    if "if (b && d.is_written && (bare || wide_n)) memory_note_gpu_write(base, n);" not in (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8"):
        raise SystemExit("FAIL: vk_draw.cpp no longer notes a bare or wide binding's writes through memory_note_gpu_write")
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    if "const bool same_desc = !no_reuse && !early_rebind && " not in draw or "if (d.is_written) return true;" not in draw or \
            "const bool early_rebind = early && memory_readback_early_active() && [&] {" not in draw:
        raise SystemExit("FAIL: vk_draw.cpp: a draw of a program that writes storage buffers may keep the set before, its write not noted")
    if "if (early && !dry && memory_rb_waited_range(host->gpu_guest(u.dst), u.size)) split_after = true;" not in rep:
        raise SystemExit("FAIL: replay: an update of uniforms a read waited for does not end its part")
    # RX_VK_LOG_EARLY_CHECK (log only): a read let go early is checked, the replay's writes and the CPU's pages reach it, and the
    # snapshots' collection generation is read after their copy
    if "if (early_check_on()) early_check_read(gpu, size, v, whole, target, unforced);" not in early:
        raise SystemExit("FAIL: invalidate: a read let go at its writer's part is not checked (RX_VK_LOG_EARLY_CHECK)")
    if "early_check_gpu_write(lo, hi, value, part," not in block(memory, "void early_in_place_write("):
        raise SystemExit("FAIL: early_in_place_write does not report the replay's writes to the early-read check")
    if "ec_kind = 2;\n    early_in_place_write(guest, guest + size, mem_rec_value);\n    ec_kind = 0;" not in gpu_write:
        raise SystemExit("FAIL: memory_note_gpu_write's bare or wide ranges are not told apart for the early-read check")
    collect = block(memory, "void memory_collect_written() {")
    if collect.index("early_check_collect_begin()") > collect.index("host->collect_written(&pages)") or \
            "if (ec_gen) early_check_cpu_pages(pages, n, true, ec_gen);" not in collect:
        raise SystemExit("FAIL: memory_collect_written's generation is not taken before it collects, or its pages not reported")
    if "if (n > 0) early_check_cpu_pages(pages, n, false, 0);" not in block(memory, "std::unique_ptr<Capture> capture_make() {"):
        raise SystemExit("FAIL: capture_make's collected pages are not reported to the early-read check")
    thread = block(replay, "void early_check_thread() {")
    if thread.index("host->gpu_read(e->gpu, snap.data(), e->size)") > thread.index("e->gen_2 = ec_full_begun.load();") or \
            "e->cpu2 |= e->cpu1;" not in thread:
        raise SystemExit("FAIL: s2's collection generation is read before its copy, or the pages collected while sm was copied are "
                         "not the second interval's too: a CPU write in between would be the GPU's")
    read = block(replay, "void early_check_read(")
    order = ["std::lock_guard lk(ec_mu);", "ok1 = host->gpu_read(gpu, x->s1.data(), size);", "ec_pending.push_back(std::move(x));",
             "if (!(unforced && wait_recorded(v, UINT64_MAX, &ok))) {", "readback_wait_value(v);",
             "const bool okm = host->gpu_read(gpu, sm.data(), size);", "e->gen_m = ec_full_begun.load();"]
    at = [read.find(s) for s in order]
    if -1 in at or at != sorted(at):
        raise SystemExit("FAIL: early_check_read: s1 under ec_mu and listed before the read goes on, then main's wait (the usual "
                         "choice: wait_recorded, else the whole submission), then sm, then its collection generation")
    usual = inv[inv.index("} else if (pending && !late) {"):]
    if "!(unforced && wait_recorded(v, UINT64_MAX, &ok))" not in usual or "readback_wait_value(v);" not in usual:
        raise SystemExit("FAIL: invalidate's usual wait changed: early_check_read's copy of it must follow")
    if "if (reads.fetch_add(1, std::memory_order_relaxed) % early_check_every()) return;" not in read or \
            "if (size > 0x10000 || v != whole) {" not in read:
        raise SystemExit("FAIL: early_check_read: one read in RX_VK_LOG_EARLY_CHECK, of 64 KiB or less, all written in place")
    for where, text in (("run_submit", block(replay, "bool run_submit(")), ("resume_queue", replay)):
        if "rb_span_close(), finish_recording(" not in text:
            raise SystemExit("FAIL: %s finishes a recording without closing its RX_VK_LOG_RB_WRITERS span" % where)
    if replay.count("finish_recording(") != replay.count("rb_span_close(), finish_recording(") + 2:   # (+ its declaration, definition)
        raise SystemExit("FAIL: a recording is finished without closing its RX_VK_LOG_RB_WRITERS span")
    if "++part_work < every" not in block(replay, "void maybe_split(VkCommandBuffer& cmd) {"):
        raise SystemExit("FAIL: maybe_split no longer ends a part by its count")
    # (the end after a writer: at once, or at the next plain draw where a part ends only there, RX_VK_SPLIT_BEFORE_DRAW;
    # tests/test_early_split_before_draw.py runs it)
    ends = block(replay, "void early_split(VkCommandBuffer& cmd) {")
    if "if (part_ends_before_draw()) {" not in ends or "part_end_wanted = true;" not in ends or "split_part(cmd);" not in ends:
        raise SystemExit("FAIL: early_split no longer ends the part at once, or at the next plain draw where parts end only there")
    split = block(replay, "void split_part(VkCommandBuffer& cmd) {")
    if "part_work = 0;" not in split:
        raise SystemExit("FAIL: split_part: a part's count of draws is no longer kept")
    if "early_split_pending = early_end_asked = false;" not in split or "(void)memory_split_wanted();" not in split or \
            "(void)memory_split_wanted(), early_split_pending = early_end_asked = false;" not in block(replay, "bool run_submit("):
        raise SystemExit("FAIL: a part ended by its count or its submission's end leaves a split asked for, and the next part ends at once")
    with tempfile.TemporaryDirectory(prefix="readback-early-") as tmp:
        tmp = Path(tmp)
        mem_src, mem_exe = tmp / "memory.cpp", tmp / ("memory.exe" if os.name == "nt" else "memory")
        mem_src.write_text(MEMORY.replace("/* PAGES */", pages).replace("/* WRITERS */", writers), encoding="utf-8")
        env_on = dict(os.environ, RX_VK_READBACK_EARLY="1")
        env_unset = {k: v for k, v in os.environ.items()
                     if k not in ("RX_VK_READBACK_EARLY", "RX_VK_LOG_RB_WRITERS", "TEST_EARLY_MIRRORS", "RX_VK_PARALLEL")}
        env_off = dict(env_unset, RX_VK_READBACK_EARLY="0")
        run(a.cxx, mem_src, mem_exe, ["on"], env_on)
        for args, env, what in ((["off"], env_off, "with the switch off (=0)"),
                                (["on"], env_unset, "unset without mirrors: on by default"),
                                (["off"], dict(env_unset, TEST_EARLY_MIRRORS="1"), "unset with mirrors: off by default"),
                                (["on"], dict(env_on, TEST_EARLY_MIRRORS="1"), "asked for with mirrors: on")):
            r = subprocess.run([str(mem_exe), *args], capture_output=True, text=True, timeout=60, env=env)
            print(r.stdout, end="")
            if r.returncode:
                raise SystemExit("FAIL: %s\n%s" % (what, r.stderr))
        env_par = dict(env_on, RX_VK_PARALLEL="3")   # (a parallel replay's segments: their parts never reach the timeline)
        r = subprocess.run([str(mem_exe), "off"], capture_output=True, text=True, timeout=60, env=env_par)
        print(r.stdout, end="")
        if r.returncode:
            raise SystemExit("FAIL: with RX_VK_PARALLEL=3 the switch is not left off\n" + r.stderr)
        choice_src, choice_exe = tmp / "choice.cpp", tmp / ("choice.exe" if os.name == "nt" else "choice")
        choice_src.write_text(CHOICE.replace("/* EARLY */", early), encoding="utf-8")
        run(a.cxx, choice_src, choice_exe)
        diag_src, diag_exe = tmp / "diag.cpp", tmp / ("diag.exe" if os.name == "nt" else "diag")
        diag_src.write_text(DIAGNOSTIC.replace("/* TARGET */", block(replay, "uint64_t rb_diag_early_part("))
                            .replace("/* FINISH */", block(replay, "void rb_diag_finish(")), encoding="utf-8")
        run(a.cxx, diag_src, diag_exe)
        rec_src, rec_exe = tmp / "recorded.cpp", tmp / ("recorded.exe" if os.name == "nt" else "recorded")
        rec_src.write_text(RECORDED.replace("/* OPEN */", between(replay, "std::atomic<uint64_t> rec_open_tag{0};", "void rec_close();"))
                           .replace("/* CLOSE */", between(replay, "void rb_release_close(uint64_t value);   // (RX_VK_LOG_RB_WRITERS",
                                                             "static void wait_rec_seq(")), encoding="utf-8")
        env_rec = {k: v for k, v in os.environ.items() if k != "RX_VK_READBACK_EARLY_RECORDED"}
        run(a.cxx, rec_src, rec_exe, env=env_rec)
        r = subprocess.run([str(rec_exe), "off"], capture_output=True, text=True, timeout=60,
                           env=dict(env_rec, RX_VK_READBACK_EARLY_RECORDED="0"))
        print(r.stdout, end="")
        if r.returncode:
            raise SystemExit("FAIL: RX_VK_READBACK_EARLY_RECORDED=0\n" + r.stderr)
        probe_src, probe_exe = tmp / "probe.cpp", tmp / ("probe.exe" if os.name == "nt" else "probe")
        probe_src.write_text(PROBE.replace("/* PROBE */", between(replay, "struct RbRelease {",
                                                                  "/// (hookshot) invalidate's wait for a write-back's value")),
                             encoding="utf-8")
        run(a.cxx, probe_src, probe_exe)
        check_src, check_exe = tmp / "check.cpp", tmp / ("check.exe" if os.name == "nt" else "check")
        cpu = block(replay, "void early_check_cpu_pages(const uint32_t* pages, int64_t n, bool full, uint32_t gen) {")
        check_src.write_text(CHECK.replace("/* COMPARE */", between(replay, "struct EcDiff {", "int early_check_every() {"))
                             .replace("/* STRUCT */", between(replay, "struct EarlyCheck {", "std::mutex ec_mu;"))
                             .replace("/* CPU_PAGES */", cpu), encoding="utf-8")
        run(a.cxx, check_src, check_exe)
        span_src, span_exe = tmp / "span.cpp", tmp / ("span.exe" if os.name == "nt" else "span")
        span_src.write_text(SPAN.replace("/* SPANS */", between(replay, "struct SubSpan {", "const char* rb_what_name("))
                            .replace("/* BURST_END */", block(replay, "void burst_end() {")), encoding="utf-8")
        run(a.cxx, span_src, span_exe)
    print("PASS: a read of pages written in place waits for its writer's part, which ends after the writer, with the switch on")


if __name__ == "__main__":
    main()
