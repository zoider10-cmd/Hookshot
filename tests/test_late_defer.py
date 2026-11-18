"""The late pages left to their reads (gpu/vk/vk_memory.cpp, "the late pages left to their reads", RX_VK_LATE_DEFER): where the
buffer pools have no mirror, a capture's late page outside the texture storage is not waited for at the capture's take but at
the first CPU read of it, which copies it again from guest memory after its own write-back. The section (late_defer_on,
late_defer_cpu_read, late_defer_split), the Capture struct and RangeWalk are taken from the source as they are and run with
stand-ins for the GPU's progress, guest memory and the texture ranges:

  - late_defer_on: with no mirrors, as the early reads (RX_VK_READBACK_EARLY) unless RX_VK_LATE_DEFER is given; off with mirrors
    (their syncs copy out of the captures) and with the parallel replay (RX_VK_PARALLEL above 1), whatever is given;
  - readback_early.h's rules: RX_VK_READBACK_EARLY on by default where the pools have no mirror, off where they have one,
    on with them too when asked for, off with 0, and never with the render thread or the parallel replay; RX_VK_LATE_DEFER
    following it unless given;
  - late_defer_split: no late page in the texture storage: nothing waited for, every late page left to its reads; a late page in
    the shadow's spans (whole pools) but in no texture's own storage left to its reads too; a late page in a span and in a
    texture's storage: its write-back waited for, and the other late pages that write-back covers copied again with it; a page
    whose write-back is later than that one still left to its reads;
  - late_defer_cpu_read: the read of a late copy waits for the write-back it missed only while that one is not done, copies the
    page again from guest memory into the copy's slot and flushes that slot, once; a read of the page in another capture (other
    generation or slot) copies nothing and the stale note goes.

take_capture and the replay's reads of guest memory as submitted are read as text:
  - the wait's value is c->late_value unless the split gives another one, a wait of 0 waits for nothing, and the copies again
    after it leave out the pages the split left to their reads;
  - a page left to its reads is noted only when the capture's buffer is kept and the page's entry is that capture's slot, and a
    later capture that takes the page again drops the note;
  - the texture shadow reads such a page from guest memory (as a page the GPU fixes), never from the capture's stale copy;
  - submitted_read_locked, the captures' part of a replay's read, asks late_defer_cpu_read after it has found the page's kept
    capture, before copying from it; and both reads go through it, one at a time (memory_read_as_submitted) and a draw's at
    once (memory_read_as_submitted_many).

python -I -B tests/test_late_defer.py [--cxx g++]
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


FIXTURE = r'''
#include "gpu/vk/compat/hookshot_env.h"
#include "gpu/vk/readback_early.h"
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <mutex>
#include <unordered_map>
#include <utility>
#include <vector>
#define CHECK(ok) do { if (!(ok)) { std::fprintf(stderr, "failed line %d: %s\n", __LINE__, #ok); std::exit(1); } } while (0)
constexpr uint64_t kPageShift = 12;
using VkBuffer = uintptr_t;
constexpr uintptr_t VK_NULL_HANDLE = 0;
struct VmaAllocationT {};
using VmaAllocation = VmaAllocationT*;
std::vector<int32_t> unused_stage_index;
namespace {
@RANGEWALK@
}
@CAPTURE@;
std::mutex shadow_mu;
std::vector<std::pair<uint64_t, uint64_t>> tex_merged;
void logf(const char*, ...) {}
// (the GPU's progress, its waits, guest memory and the flushes, as the fixture sets and counts them)
uint64_t completed_now = 0;
std::vector<uint64_t> waited;
uint64_t vk_timeline_completed() { return completed_now; }
void vk_timeline_wait(uint64_t v) { waited.push_back(v); if (completed_now < v) completed_now = v; }
uint8_t guest[16 * 4096];
struct Host { uint8_t* guest_base() { return guest; } } the_host;
Host* host = &the_host;
int copies = 0;
bool guarded_copy(void* dst, const void* src, size_t n) { std::memcpy(dst, src, n); copies++; return true; }
std::vector<std::pair<uint64_t, uint64_t>> flushed;   // (offset, size)
void flush_mapped_range(VmaAllocation, uint64_t offset, uint64_t size) { flushed.push_back({offset, size}); }
bool mirrors = false, early = true;
bool readback_early_on() { return early; }
std::vector<uint64_t> texture_pages;   // (pages a texture's own storage covers: vk_replay.cpp's tex_pages)
bool texture_storage_any(uint64_t gpu, uint64_t size) {
    for (uint64_t p : texture_pages)
        if (p << kPageShift < gpu + size && (p + 1) << kPageShift > gpu) return true;
    return false;
}
@SECTION@
namespace {
bool mirror_on() { return mirrors; }
}

int main() {
    // late_defer_on: no mirrors here, nothing set
    CHECK(late_defer_on());
    // late_defer_split: pages 1..6 written, 2, 4 and 5 late (4 in the texture storage) for write-backs 9, 7 and 11
    Capture c;
    c.pages = {1, 2, 3, 4, 5, 6};
    c.late = {1, 3, 4};
    c.late_pv = {9, 7, 11};
    c.late_value = 11;
    std::vector<uint32_t> out;
    std::vector<uint64_t> out_pv;
    CHECK(late_defer_split(c, out, out_pv) == 0);   // (no texture storage: none waited for)
    CHECK((out == std::vector<uint32_t>{1, 3, 4}) && (out_pv == std::vector<uint64_t>{9, 7, 11}));
    tex_merged = {{4ull << kPageShift, 5ull << kPageShift}};   // (page 4 in the shadow's spans, in no texture's storage)
    CHECK(late_defer_split(c, out, out_pv) == 0);   // (a pool shared with textures: left to its reads all the same)
    CHECK((out == std::vector<uint32_t>{1, 3, 4}) && st_ld_tex == 0);
    texture_pages = {4};   // (and in a texture's storage: it waits)
    CHECK(late_defer_split(c, out, out_pv) == 7);   // (page 4's write-back waited for: page 2's, 7 too, with it)
    CHECK((out == std::vector<uint32_t>{1, 4}) && (out_pv == std::vector<uint64_t>{9, 11}) && st_ld_tex == 1);
    tex_merged = {{2ull << kPageShift, 6ull << kPageShift}};   // (pages 2 to 5 in the spans, page 5 in a texture's storage:
    texture_pages = {5};                                       // the newest write-back waited for, none left)
    CHECK(late_defer_split(c, out, out_pv) == 11 && out.empty() && out_pv.empty() && st_ld_tex == 2);
    texture_pages = {5};
    tex_merged.clear();   // (in a texture's storage but no span: no shadow copy to make, left to its reads)
    CHECK(late_defer_split(c, out, out_pv) == 0 && out.size() == 3 && st_ld_tex == 2);
    texture_pages.clear();
    // late_defer_cpu_read: page 2's copy in capture 5's buffer, slot 1, late for write-back 9
    std::vector<uint8_t> buf(4 * 4096, 0xee);
    VmaAllocationT a;
    std::memset(guest + 2 * 4096, 0x42, 4096);
    late_defer[2] = {5, 1, 9};
    CHECK(late_defer_any());
    completed_now = 8;
    late_defer_cpu_read(2, 5, 1, &a, buf.data());
    CHECK(waited == std::vector<uint64_t>{9});   // (waited for the write-back it missed)
    CHECK(copies == 1 && buf[4096] == 0x42 && buf[2 * 4096 - 1] == 0x42 && buf[0] == 0xee && buf[2 * 4096] == 0xee);
    CHECK(flushed.size() == 1 && flushed[0].first == 4096 && flushed[0].second == 4096);
    CHECK(!late_defer_any());   // (once)
    CHECK(st_ld_reads == 1 && st_ld_read_waits == 1 && st_ld_read_wait_ms >= 0);   // (counted for the log)
    late_defer_cpu_read(2, 5, 1, &a, buf.data());
    CHECK(copies == 1 && waited.size() == 1);
    // the write-back done already: no wait, still copied again
    late_defer[3] = {5, 2, 9};
    std::memset(guest + 3 * 4096, 0x33, 4096);
    late_defer_cpu_read(3, 5, 2, &a, buf.data());
    CHECK(waited.size() == 1 && copies == 2 && buf[2 * 4096] == 0x33);
    CHECK(st_ld_reads == 2 && st_ld_read_waits == 1);
    // another capture's copy of the page (a later generation, or another slot): nothing copied, the stale note gone
    late_defer[3] = {5, 2, 12};
    late_defer_cpu_read(3, 6, 0, &a, buf.data());
    CHECK(waited.size() == 1 && copies == 2 && !late_defer_any());
    late_defer[3] = {5, 2, 12};
    late_defer_cpu_read(3, 5, 3, &a, buf.data());
    CHECK(waited.size() == 1 && copies == 2 && !late_defer_any());
    CHECK(st_ld_reads == 2 && st_ld_read_waits == 1);   // (another capture's copy: not a read of a late one)
    std::puts("PASS: late pages left to their reads: the split by texture storage and write-back, one wait and copy at the read");
    return 0;
}
'''

RULES = r'''
#include "gpu/vk/readback_early.h"
#include <cstdio>
#include <cstdlib>
#include <initializer_list>
#define CHECK(ok) do { if (!(ok)) { std::fprintf(stderr, "failed line %d: %s\n", __LINE__, #ok); std::exit(1); } } while (0)
using namespace readback_early;
static Why pick(const char* env, const char* par, bool render_thread, bool mirrors = false) {
    Facts f;
    f.env = env, f.parallel = par, f.render_thread = render_thread, f.mirrors = mirrors;
    return choose(f);
}
int main() {
    CHECK(pick(nullptr, nullptr, false) == ON_DEFAULT);              // (unset: on where the pools have no mirror, the Deck)
    CHECK(pick(nullptr, nullptr, false, true) == OFF_MIRRORS);       // (and off where they have one, discrete cards)
    CHECK(pick(nullptr, nullptr, true) == OFF_RENDER_THREAD);        // (not with the render thread)
    CHECK(pick(nullptr, "3", false) == OFF_PARALLEL);                // (nor with the parallel replay)
    CHECK(pick("1", nullptr, false, true) == ON_SWITCH);             // (asked for, with mirrors too)
    for (const char* off : {"0", "off", "false", "no", ""}) CHECK(pick(off, nullptr, false, false) == OFF_SWITCH);
    CHECK(pick("1", nullptr, false) == ON_SWITCH);                   // (asked for)
    CHECK(pick("1", nullptr, true) == OFF_RENDER_THREAD);            // (not with the render thread, even asked for)
    for (const char* off : {"0", "off", "false", "no", ""}) CHECK(pick(off, nullptr, false) == OFF_SWITCH);
    CHECK(pick("1", "3", false) == OFF_PARALLEL);                    // (never with the parallel replay)
    CHECK(pick("1", "2", true) == OFF_PARALLEL);
    CHECK(pick("1", "1", false) == ON_SWITCH);                       // (1 is not the parallel replay)
    CHECK(on(ON_SWITCH) && on(ON_DEFAULT) && !on(OFF_MIRRORS) && !on(OFF_SWITCH) && !on(OFF_PARALLEL) && !on(OFF_RENDER_THREAD));
    // RX_VK_LATE_DEFER: follows the early reads unless given; never with mirrors or the parallel replay
    CHECK(defer(nullptr, false, nullptr, true) && !defer(nullptr, false, nullptr, false));
    CHECK(defer("1", false, nullptr, false) && !defer("0", false, nullptr, true) && !defer("off", false, nullptr, true));
    CHECK(!defer(nullptr, true, nullptr, true) && !defer("1", true, nullptr, true));
    CHECK(!defer(nullptr, false, "4", true) && !defer("1", false, "2", true) && defer(nullptr, false, "1", true));
    std::puts("rules ok");
    return 0;
}
'''

CHILD = r'''
int main() {
    if (st_ld_reads || st_ld_read_waits || st_ld_read_wait_ms) return 1;   // (nothing read yet)
    std::printf("%d\n", late_defer_on() ? 1 : 0);
    return 0;
}
'''


def check_text(text):
    take = block(text, 'bool take_capture(std::unique_ptr<Capture> c, uint64_t value, uint64_t completed) {')
    late = block(take, 'if (c->late_value && c->map)')
    for needle in ('uint64_t wait = c->late_value;',
                   'if (late_defer_on() && c->late_pv.size() == c->late.size()) wait = late_defer_split(*c, deferred, deferred_pv);',
                   'if (wait) {', 'vk_timeline_wait(wait);',
                   'if (d < deferred.size() && deferred[d] == i) { d++; continue; }'):
        if needle not in late:
            raise SystemExit("take_capture: the late pages' wait no longer has: " + needle)
    if late.index('if (d < deferred.size() && deferred[d] == i) { d++; continue; }') > late.index('guarded_copy('):
        raise SystemExit("take_capture: the copies again after the wait do not leave out the pages left to their reads")
    kept = block(take, 'if (!c->copied.empty() && g && c->map) {')
    erase, entries, note = (kept.index('for (uint32_t p : c->copied) late_defer.erase(p);'),
                            kept.index('cap_entry_set(c->copied[i], CapEntry{g, c->slots[i]});'),
                            kept.index('late_defer[p] = {g, deferred[k], deferred_pv[k]}'))
    if not erase < entries < note:
        raise SystemExit("take_capture: a page left to its reads is not noted after the kept capture's entries, or a page "
                         "taken again is not let go first")
    if 'if (e.gen == g && e.slot == deferred[k])' not in kept:
        raise SystemExit("take_capture: a page left to its reads is noted without its entry being this capture's slot")
    if 'for (uint32_t i : deferred) late_index[i] = 1;' not in take or \
            'if ((fixed || !deferred.empty()) && late_index[c->slots[i]]) {' not in take:
        raise SystemExit("take_capture: the texture shadow may read a page left to its reads from the capture's stale copy")
    make = block(text, 'std::unique_ptr<Capture> capture_make() {')
    if 'c->late.push_back((uint32_t)i), c->late_pv.push_back(pv);' not in make or 'c->late_pv.clear()' not in make:
        raise SystemExit("capture_make: the late pages' write-backs (late_pv) are not kept beside them")
    read = block(text, 'int64_t submitted_read_locked(uint64_t guest, void* dst, uint64_t n) {')
    hook = read.find('if (late_defer_any()) late_defer_cpu_read((uint32_t)page, e.gen, e.slot, b->second.alloc, (uint8_t*)b->second.map);')
    if not 0 <= read.index('if (b == cap_bufs.end() || !b->second.map) continue;') < hook < read.index('std::memcpy('):
        raise SystemExit("submitted_read_locked: the late copy is not taken again before it is read")
    for head in ('bool memory_read_as_submitted(uint64_t gpu, void* dst, uint64_t n) {',
                 'void memory_read_as_submitted_many(const SubmittedRead* reads, size_t count) {'):
        if 'submitted_read_locked(' not in block(text, head):
            raise SystemExit(head.split('(')[0].split()[-1] + ": its reads of the captures skip submitted_read_locked, and the late "
                             "copies with it")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cxx', default='g++')
    parser.add_argument('--source', type=Path, default=ROOT / 'gpu/vk/vk_memory.cpp')
    args = parser.parse_args()
    text = args.source.read_text(encoding='utf-8')
    check_text(text)
    sect = between(text, '// ---- the late pages left to their reads (RX_VK_LATE_DEFER', 'bool take_capture(')
    fixture = (FIXTURE
               .replace('@RANGEWALK@', block(text, 'struct RangeWalk {') + ';')
               .replace('@CAPTURE@', block(text, 'struct Capture {'))
               .replace('@SECTION@', sect))
    child = fixture[:fixture.index('int main() {')] + CHILD
    env = {k: v for k, v in os.environ.items() if k not in ('RX_VK_LATE_DEFER', 'RX_VK_PARALLEL')}
    with tempfile.TemporaryDirectory(prefix='late-defer-') as tmp:
        for name, body in (('late_defer', fixture), ('late_defer_on', child), ('late_defer_mirrors', child.replace(
                'bool mirrors = false, early = true;', 'bool mirrors = true, early = true;')),
                           ('late_defer_no_early', child.replace('bool mirrors = false, early = true;', 'bool mirrors = false, early = false;')),
                           ('rules', RULES)):
            src, exe = Path(tmp) / (name + '.cpp'), Path(tmp) / (name + '.exe')
            src.write_text(body, encoding='utf-8')
            subprocess.run([args.cxx, '-std=c++20', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-Wno-unused-variable', '-I', str(ROOT),
                            str(src), '-o', str(exe)], check=True)
        subprocess.run([str(Path(tmp) / 'late_defer.exe')], check=True, env=env, timeout=60)
        subprocess.run([str(Path(tmp) / 'rules.exe')], check=True, env=env, timeout=60)
        on = lambda exe, **e: subprocess.run([str(Path(tmp) / exe)], check=True, env=dict(env, **e), timeout=60,
                                             capture_output=True, text=True).stdout.strip()
        for exe, e, want in (('late_defer_on.exe', {}, '1'), ('late_defer_on.exe', {'RX_VK_LATE_DEFER': '0'}, '0'),
                             ('late_defer_on.exe', {'RX_VK_LATE_DEFER': '1'}, '1'),
                             ('late_defer_on.exe', {'RX_VK_PARALLEL': '3'}, '0'), ('late_defer_on.exe', {'RX_VK_PARALLEL': '1'}, '1'),
                             ('late_defer_mirrors.exe', {}, '0'), ('late_defer_mirrors.exe', {'RX_VK_LATE_DEFER': '1'}, '0'),
                             ('late_defer_no_early.exe', {}, '0'), ('late_defer_no_early.exe', {'RX_VK_LATE_DEFER': '1'}, '1')):
            got = on(exe, **e)
            if got != want:
                raise SystemExit("late_defer_on with %s%s%s: %s, expected %s" % (
                    e or "nothing set", " and mirrors" if 'mirrors' in exe else "", " and no early reads" if 'no_early' in exe else "",
                    got, want))
    print("PASS: late_defer_on by mirrors, RX_VK_LATE_DEFER and the parallel replay; take_capture and the reads as submitted wired")


if __name__ == '__main__':
    main()
