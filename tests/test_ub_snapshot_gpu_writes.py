"""The uniform snapshot's guard (RX_VK_UB_SNAPSHOT, gpu/vk/vk_memory.cpp memory_gpu_written): a uniform range the GPU
writes earlier in the same submission, in any of its parts, or in an earlier submission the GPU has not done yet, is
bound in place, where the GPU reads it after that write, and not copied from guest memory and the captures, which do not
have the GPU's bytes yet. No game or GPU required.

The snapshot (on by default on every Intel GPU) copies a uniform buffer into the stream as the submission had it. A copy,
a fill or a storage write by the GPU earlier in the submission is not in guest memory yet, so a copy made at record time
would give the draw the bytes from before that write, where the binding in place gave it the GPU's. Nor is one of an
earlier submission still on the GPU: its bytes reach guest memory when the GPU has done it (copied back from the mirrors
at each part's end, or written there in place). The guard notes those writes (memory_stamp_gpu, memory_note_gpu_write):
split_part cuts a submission into parts and runs memory_begin_submission at each, and a part's GPU work has not
necessarily run when the next part is recorded, so a submission keeps its own for all its parts; at a submission's start
(run_submit's new recording, the present, bench_replay) the last one's take its timeline value, and a write is let go
once the GPU has done its submission (memory_recording_value, at each part's start). With the snapshot off nothing is
noted (nothing asks). A parallel replay (RX_VK_PARALLEL) records a command buffer's segments on several threads at once,
where a segment could not know the GPU writes before it: with the snapshot on, each command buffer is recorded on the
replay thread instead (par_snapshot_serial in vk_replay.cpp).

Checked here: the guard's functions, compiled alone with memory_recording_value, against a plain list (a copy then a read
in the same part, a storage write then a read after a split, ranges that meet or only touch, a parallel replay's
segments, nothing noted with the snapshot off; the last submission's writes while the GPU has not done it and once it
has, a write over one of them, a submission whose value the GPU has passed already; and submissions one after another
with the GPU some behind, where no write it has not done may be let go); and in the sources, that each GPU write is
noted, that only a submission's start begins the notes again and only it lets them go, that each recording's start gives
the guard the GPU's progress, that uniform_range binds a range the guard knows in place, and that a parallel replay
records on the replay thread with the snapshot on. Not modelled: the GPU itself, the timeline's semaphore, the
write-backs' copies (what reaching guest memory at the submission's end rests on), and a range memory_note_gpu_write
noted where the GPU writes past what is copied back, which guest memory does not get even then.

python -I -B tests/test_ub_snapshot_gpu_writes.py [--cxx g++]
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # (python -I leaves the check's own folder off the path)
from srccut import block  # noqa: E402

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def code_only(text):
    return "\n".join(line.split("//")[0] for line in text.splitlines())


def line_with(text, marker):
    for line in text.splitlines():
        if line.startswith(marker):
            return line
    raise SystemExit("FAIL: no line begins with %r" % marker)


FIXTURE = r"""
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <iterator>
#include <map>
#include <random>
#include <utility>
#include <vector>
std::atomic<bool> par_active{false};
bool uniform_snapshot_on() { return SNAPSHOT_ON; }
uint64_t mem_rec_value = 0, mem_completed = 0;
@@GUARD@@
// (the GPU's progress, and the submissions as vk_replay.cpp records them: each part's start (begin_recording) gives
// memory_recording_value the submission's timeline value and what the GPU has done; a submission's start (run_submit, the
// present, bench_replay) then begins the guard's notes)
static uint64_t gpu_done = 0, sub_value = 0;
static void part() { memory_recording_value(sub_value, gpu_done); }
static void submission(uint64_t value) { sub_value = value, part(), memory_gpu_writes_begin(); }
// (a plain list of every write noted, with its submission's value, the reference)
struct Ref { uint64_t lo, hi, value; };
static std::vector<Ref> ref;
static void note(uint64_t at, uint64_t n) {   // (what memory_stamp_gpu and memory_note_gpu_write do first)
    memory_gpu_writes_note(at, n);
    if (at && n && !par_active.load()) ref.push_back({at, at + n, sub_value});
}
static bool ref_written(uint64_t at, uint64_t n) {   // (by this submission, or by one the GPU has not done)
    if (!at || !n) return false;
    for (const Ref& r : ref)
        if (at < r.hi && r.lo < at + n && (r.value == sub_value || r.value > mem_completed)) return true;
    return false;
}
static int fails = 0;
static void expect(int got, int want, const char* what) {
    if (got != want) {
        printf("FAIL: %s: %d, wanted %d (0: not written; 1: in this submission; 2: in one the GPU has not done)\n", what,
               got, want);
        fails++;
    }
}
int main() {
    submission(1);
#if !SNAPSHOT_ON
    // (the snapshot off: nothing asks, and nothing is noted)
    memory_gpu_writes_note(0x100000, 0x400);
    expect(memory_gpu_writes_any(), 0, "the snapshot off: a copy's destination noted");
    expect(memory_gpu_written(0x100200, 0x40), 0, "the snapshot off: a uniform range inside a copy's destination");
    return fails ? 1 : 0;
#endif
    expect(memory_gpu_writes_any(), 0, "a submission's start: nothing noted");
    expect(memory_gpu_written(0x100000, 0x100), 0, "a submission's start: a uniform range");
    // (a buffer copy into a range, then a uniform binding of part of it, in the same part)
    note(0x100000, 0x400);
    expect(memory_gpu_written(0x100200, 0x40), 1, "a copy's destination, then a uniform range inside it");
    expect(memory_gpu_written(0x0ffff0, 0x20), 1, "a uniform range over the copy's start");
    expect(memory_gpu_written(0x100400, 0x40), 0, "a uniform range just past the copy");
    expect(memory_gpu_written(0x0fffc0, 0x40), 0, "a uniform range just before the copy");
    // (split_part: the next part is recorded with the notes kept, nothing begun again)
    part();
    note(0x200000, 0x1000);   // (a dispatch's storage write)
    part();
    expect(memory_gpu_written(0x200ff0, 0x10), 1, "a storage write in one part, a uniform range in the next");
    expect(memory_gpu_written(0x100000, 0x10), 1, "the first part's copy, two parts on");
    // (ranges that meet or touch are one: and the one between stays unwritten)
    note(0x300000, 0x100), note(0x300100, 0x100), note(0x300400, 0x100), note(0x3000c0, 0x400);
    expect(memory_gpu_written(0x3004f0, 0x10), 1, "ranges joined by a write over both");
    expect(memory_gpu_written(0x300500, 0x100), 0, "past ranges joined");
    // (a parallel replay's segments, were one made with the snapshot on: their writes are on their own threads, and the
    // guard is not asked while they record)
    par_active = true;
    note(0x400000, 0x100);
    par_active = false;
    expect(memory_gpu_written(0x400000, 0x100), 0, "a write while a parallel replay records (not noted)");
    // (many ranges apart in one submission, against the list: no limit that turns every range written)
    std::mt19937_64 rng(12345);
    for (int i = 0; i < 3000; i++) {
        const uint64_t at = 0x1000000 + ((rng() % 0x4000000) & ~0xfull), n = 1 + rng() % 0x3000;
        if (rng() % 3 == 0) note(at, n);
        const uint64_t q = 0x1000000 + ((rng() % 0x4000000) & ~0xfull), qn = 16 + rng() % 0x1000;
        expect(memory_gpu_written(q, qn) != 0, ref_written(q, qn), "a range against the plain list");
        if (fails > 5) return 1;
    }
    // (the next submission, the GPU not done with the last one: the last one's writes are not in guest memory yet)
    submission(2);
    expect(memory_gpu_written(0x100200, 0x40), 2, "the last submission's copy, the GPU not done with it");
    expect(memory_gpu_written(0x200ff0, 0x10), 2, "the last submission's storage write, the GPU not done with it");
    expect(memory_gpu_written(0x100400, 0x40), 0, "just past the last submission's copy");
    note(0x500000, 0x10);
    expect(memory_gpu_written(0x500008, 0x8), 1, "this submission's own write");
    note(0x1003c0, 0x100);   // (over the end of the last one's copy: one range with it, this submission's)
    expect(memory_gpu_written(0x100000, 0x10), 1, "a range the last submission wrote, written over in this one");
    // (the GPU done with the first submission when the next part starts: guest memory has its bytes, a copy has them too)
    gpu_done = 1;
    part();
    expect(memory_gpu_written(0x200ff0, 0x10), 0, "the last submission's storage write, the GPU done with it");
    expect(memory_gpu_written(0x500008, 0x8), 1, "this submission's own write, the GPU past the last one");
    // (the next submission's start lets it go; this one's are kept, the GPU not done with it)
    submission(3);
    expect(memory_gpu_written(0x200ff0, 0x10), 0, "a write of a submission the GPU has done, a submission on");
    expect(memory_gpu_written(0x500008, 0x8), 2, "the last submission's write, the GPU not done with it");
    expect(memory_gpu_written(0x100000, 0x10), 2, "a range two submissions wrote, the GPU not done with the later");
    gpu_done = 2;   // (the GPU done with the last submission, not with this one: the last one's are let go)
    part();
    expect(memory_gpu_written(0x500008, 0x8), 0, "the last submission's write, the GPU done with it");
    gpu_done = 3;
    submission(4);
    expect(memory_gpu_writes_any(), 0, "every submission done on the GPU: nothing noted");
    // (a submission whose value the GPU has passed already, as bench_replay's: its own writes kept while it is recorded,
    // let go at the next start)
    gpu_done = 4;
    submission(4);
    note(0x600000, 0x40);
    expect(memory_gpu_written(0x600010, 0x10), 1, "a write in a submission whose value the GPU has passed");
    submission(5);
    expect(memory_gpu_written(0x600010, 0x10), 0, "that write, a submission on");
    // (submissions one after another with the GPU some behind, against the list: no write the GPU has not done is let go)
    ref.clear();
    uint64_t v = 5;
    for (int s = 0; s < 60; s++) {
        for (int i = 0; i < 200; i++) {
            const uint64_t at = 0x1000000 + ((rng() % 0x400000) & ~0xfull), n = 1 + rng() % 0x3000;
            if (rng() % 4 == 0) note(at, n);
            if (rng() % 16 == 0) {   // (the next part: the GPU maybe further on)
                if (gpu_done + 1 < v && rng() % 2) gpu_done++;
                part();
            }
            const uint64_t q = 0x1000000 + ((rng() % 0x400000) & ~0xfull), qn = 16 + rng() % 0x1000;
            if (ref_written(q, qn) && !memory_gpu_written(q, qn)) {
                printf("FAIL: a range the GPU has not done writing let go (submission %llu, the GPU done up to %llu)\n",
                       (unsigned long long)v, (unsigned long long)mem_completed);
                if (++fails > 5) return 1;
            }
        }
        v++;
        if (gpu_done + 1 < v && rng() % 3 == 0) gpu_done += 1 + rng() % (v - 1 - gpu_done);
        submission(v);
    }
    return fails ? 1 : 0;
}
"""


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    args = p.parse_args()
    memory = (VK / "vk_memory.cpp").read_text(encoding="utf-8")
    replay = (VK / "vk_replay.cpp").read_text(encoding="utf-8")
    draw = (VK / "vk_draw.cpp").read_text(encoding="utf-8")
    xfer = (VK / "vk_xfer.cpp").read_text(encoding="utf-8")

    # (uniform_range, the bug: with the snapshot on, it copied every uniform range from guest memory and the captures at
    # record time, a range the GPU writes earlier in the submission too; a range the guard knows is bound in place)
    ranges = code_only(block(draw, "VkDescriptorBufferInfo uniform_range(const NvnState& s, const Stage& st, uint32_t index) {"))
    if "memory_gpu_written(" not in ranges or "const int gpu_written = snapshot" not in ranges:
        raise SystemExit("FAIL: uniform_range copies a uniform range the GPU wrote earlier in the submission (it does not ask "
                         "whether the GPU wrote it): the draw gets the bytes from before the GPU's write")
    if "snapshot && !gpu_written ? BufferRef{} : gpu_buffer_bind(" not in ranges:
        raise SystemExit("FAIL: uniform_range copies a uniform range the GPU wrote in the submission instead of binding it "
                         "in place")
    if ranges.index("const int gpu_written") > ranges.index("snapshot && !gpu_written ? BufferRef{}"):
        raise SystemExit("FAIL: uniform_range decides the binding before asking the guard")
    print("source: uniform_range binds in place a range the GPU wrote earlier in the submission or in one still on the GPU, "
          "with the snapshot on")

    # (each GPU write is noted: memory_stamp_gpu and memory_note_gpu_write note it, before anything else returns)
    stamp = code_only(block(memory, "void memory_stamp_gpu(uint64_t guest, uint64_t size) {"))
    if stamp.find("memory_gpu_writes_note(guest, size);") < 0 or \
            stamp.find("memory_gpu_writes_note(guest, size);") > stamp.find("if (!gpu_pages_on()) return;"):
        raise SystemExit("FAIL: memory_stamp_gpu does not note the GPU's write for the guard before it returns")
    note_w = code_only(block(memory, "void memory_note_gpu_write(uint64_t gpu, uint64_t size) {"))
    if "memory_gpu_writes_note(guest, size);" not in note_w:
        raise SystemExit("FAIL: memory_note_gpu_write does not note the GPU's write for the guard")
    # (the writes: a buffer copy, a fill, a draw's or a dispatch's storage write, a texture-to-buffer copy)
    copy = code_only(block(replay, "            if (src && dst) {"))
    if "vkCmdCopyBuffer(" not in copy or "memory_stamp_gpu(guest, c.size);" not in copy:
        raise SystemExit("FAIL: a buffer copy on the GPU is not stamped (memory_stamp_gpu)")
    if "if (guest && !in_stream) memory_stamp_gpu(guest, k);" not in code_only(replay):
        raise SystemExit("FAIL: a buffer fill on the GPU is not stamped (memory_stamp_gpu)")
    if "if (guest) { ParLock lk; memory_stamp_gpu(guest, n); }" not in code_only(draw):
        raise SystemExit("FAIL: a storage buffer a draw or dispatch writes is not stamped (memory_stamp_gpu)")
    if "if (b && d.is_written && (bare || wide_n)) memory_note_gpu_write(base, n);" not in code_only(draw):
        raise SystemExit("FAIL: a bare or wide storage range a program writes is not noted (memory_note_gpu_write)")
    if "if (guest) memory_stamp_gpu(guest, size);" not in code_only(xfer):
        raise SystemExit("FAIL: a texture-to-buffer copy is not stamped (memory_stamp_gpu)")
    print("source: buffer copies and fills, storage writes and texture-to-buffer copies are noted for the guard")

    # (only a submission's start begins the notes again: not split_part, which runs memory_begin_submission at each part)
    begin_call = "memory_gpu_writes_begin();"
    if begin_call in code_only(block(memory, "void memory_begin_submission() {")):
        raise SystemExit("FAIL: memory_begin_submission begins the guard's notes again: split_part runs it at every part")
    split = code_only(block(replay, "void split_part(VkCommandBuffer& cmd) {"))
    if "memory_begin_submission();" not in split:
        raise SystemExit("FAIL: split_part no longer runs memory_begin_submission: update this check")
    if begin_call in split:
        raise SystemExit("FAIL: split_part begins the guard's notes again: a part's GPU writes are forgotten at the next part")
    for f in ("bool run_submit(", "void bench_replay(", "void do_present("):
        if begin_call not in code_only(block(replay, f)):
            raise SystemExit("FAIL: %s does not begin the guard's notes at a submission's start" % f.split("(")[0])
    if code_only(replay).count(begin_call) != 3:
        raise SystemExit("FAIL: the guard's notes are begun elsewhere than the three submission starts")
    burst = code_only(block(replay, "    if (burst_open && rec_cur) {"))
    if begin_call in burst:
        raise SystemExit("FAIL: a burst's next submit (the same recording) begins the guard's notes again")
    if "gpu_writes.clear()" in code_only(memory):
        raise SystemExit("FAIL: the guard's notes are cleared all at once: an earlier submission's, which the GPU may not "
                         "have done, go with them")
    if code_only(memory).count("gpu_writes.resize(") != 1 or \
            "gpu_writes.resize(" not in code_only(block(memory, "void memory_gpu_writes_begin() {")):
        raise SystemExit("FAIL: the guard's notes are let go elsewhere than memory_gpu_writes_begin")
    # (what the GPU has done, as the guard sees it: given at each recording's start, the parts' too)
    if "memory_recording_value(value, completed());" not in code_only(block(replay, "Recording& begin_recording(uint64_t value) {")):
        raise SystemExit("FAIL: begin_recording does not give the guard the recording's timeline value and the GPU's progress "
                         "(memory_recording_value)")
    print("source: the notes are begun at run_submit's new recording, the present and bench_replay only, kept through "
          "split_part's parts and a burst, let go only there; each recording's start gives the GPU's progress")

    # (the notes only with the snapshot on: nothing else asks)
    note_f = code_only(block(memory, "void memory_gpu_writes_note(uint64_t guest, uint64_t size) {"))
    if "static const bool on = uniform_snapshot_on();" not in note_f or "if (!on ||" not in note_f:
        raise SystemExit("FAIL: memory_gpu_writes_note notes GPU writes with the uniform snapshot off")
    # (a parallel replay with the snapshot on: each command buffer on the replay thread, where the guard sees every write in
    # order; a segment is recorded at the same time as those before it)
    serial = code_only(block(replay, "static bool par_snapshot_serial(int threads) {"))
    if "if (threads < 2 || !uniform_snapshot_on()) return false;" not in serial or "return true;" not in serial:
        raise SystemExit("FAIL: par_snapshot_serial does not keep a parallel replay's segments from recording with the "
                         "uniform snapshot on")
    handle = code_only(block(replay, "const uint8_t* replay_handle(VkCommandBuffer& cmd, const uint8_t* h, bool may_stop = false) {"))
    serial_branch = handle[:handle.index("{", handle.index("if (threads < 2 ||"))]
    serial_branch = serial_branch[serial_branch.index("if (threads < 2 ||"):]
    if "par_snapshot_serial(threads)" not in serial_branch:
        raise SystemExit("FAIL: replay_handle makes a parallel replay's segments with the uniform snapshot on")
    if handle.index("if (threads < 2 ||") > handle.index("par_active = true;"):
        raise SystemExit("FAIL: replay_handle's replay-thread branch no longer comes before the segments: update this check")
    if "static const bool on = ub_snapshot_wanted();" not in code_only(block(draw, "bool uniform_snapshot_on() {")):
        raise SystemExit("FAIL: uniform_snapshot_on does not give ub_snapshot_wanted's answer")
    print("source: the notes only with the snapshot on; a parallel replay records on the replay thread with the snapshot on")

    guard = "\n".join([
        line_with(memory, "struct GpuWrite {"),
        line_with(memory, "thread_local std::vector<GpuWrite> gpu_writes;"),
        line_with(memory, "thread_local uint64_t gpu_writes_lo = UINT64_MAX, gpu_writes_hi = 0;"),
        line_with(memory, "thread_local uint64_t gpu_writes_value = 0;"),
        block(memory, "void memory_gpu_writes_begin() {"),
        block(memory, "void memory_gpu_writes_note(uint64_t guest, uint64_t size) {"),
        block(memory, "int memory_gpu_written(uint64_t guest, uint64_t size) {"),
        line_with(memory, "bool memory_gpu_writes_any() {"),
        block(memory, "void memory_recording_value(uint64_t value, uint64_t completed) {"),
    ])
    with tempfile.TemporaryDirectory(prefix="ub-guard-") as tmp:
        tmp = Path(tmp)
        for on in (1, 0):
            cpp, exe = tmp / ("t%d.cpp" % on), tmp / ("t%d.exe" % on)
            cpp.write_text(FIXTURE.replace("@@GUARD@@", guard), encoding="utf-8")
            r = subprocess.run([args.cxx, "-std=c++20", "-DSNAPSHOT_ON=%d" % on, "-include",
                                str(VK / "compat" / "hookshot_env.h"), "-Wall", "-Wextra", "-Werror", str(cpp), "-o",
                                str(exe)], capture_output=True, text=True, timeout=120)
            if r.returncode:
                print(r.stdout + r.stderr)
                raise SystemExit("FAIL: the guard's functions did not build alone")
            r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
            if r.returncode:
                print(r.stdout + r.stderr)
                raise SystemExit("FAIL: the guard answers wrongly (the snapshot %s)" % ("on" if on else "off"))
    print("guard: a copy then a uniform read in a part, a storage write then a read after a split, joined and touching "
          "ranges, a parallel replay's writes, 3000 random ranges against a plain list; the last submission's writes while "
          "the GPU has not done it and once it has, a write over one of them, a submission the GPU has passed; 60 "
          "submissions with the GPU some behind, no write it has not done let go; nothing noted with the snapshot off")
    print("PASS")


if __name__ == "__main__":
    main()
