"""A submit's capture never misses a page the replay's collection is marking again (gpu/vk/vk_memory.cpp).

memory_collect_written (the render thread, at each submit's memory work) takes every page's write mark
(host->collect_written), then marks the pages in the captured ranges again, for the next capture to take as they are
then. capture_scan (the game's thread, a submit's capture) takes the marks in the captured ranges. A capture that
scanned after the collection had taken a page's mark and before it marked the page again found the page unmarked: it
was in that capture neither, and the work the capture was taken for read an older capture's copy of it (Kokiri Forest's
ground mist gone for a frame, with the render thread replaying jobs as they come: a third of the captures came in that
window).

The fixture runs the two on two threads with stand-ins for the host's marks, and lets the capture in at each end of the
collection's window: just after the collection took the marks, and as it is about to mark the captured page again. The
collection stays there until the capture has scanned or waits for it (collect_mu's stand-in notes a capture that finds
it held), so neither run depends on timing. Each time the capture must hold the captured page written before it began
and leave its mark cleared; the page outside the captured ranges is stamped by the collection and not captured.

python -I -B tests/test_vk_collect_window.py [--cxx g++]
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))   # (python -I leaves the check's own folder off the path)
from srccut import block

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <iterator>
#include <mutex>
#include <thread>
#include <utility>
#include <vector>
[[noreturn]] void fail(int line, const char* what) {   // (_Exit: the other thread may still be waiting)
    std::fprintf(stderr, "FAIL:%d %s\n", line, what);
    std::fflush(nullptr);
    std::_Exit(1);
}
#define CHECK(x) do { if (!(x)) fail(__LINE__, #x); } while (0)
constexpr uint64_t kPageShift = 12;
constexpr uint64_t kTestPages = 64;
// (stand-ins for the host: guest memory, one write mark a page, taken and set as host/rx_backend.c's collect_in and
// host/hos_mem.c's hos_mark_written do)
uint8_t guest_mem[kTestPages << kPageShift];
uint8_t marks[kTestPages];
// (where in the collection's window the capture comes: just after the marks were taken, or as the captured page is
// about to be marked again)
enum Enter { kAfterTake, kAtRemark };
Enter enter = kAfterTake;
std::mutex step_mu;
std::condition_variable step_cv;
int step = 0;                 // (1: the collection is inside its window, the capture may scan; 2: it has scanned)
bool capture_waits = false;   // (the capture found collect_mu held while the collection was inside its window)
void hold_window() {          // (the collection: let the capture in, and go on once it has scanned or waits for us)
    std::unique_lock lk(step_mu);
    step = 1;
    step_cv.notify_all();
    CHECK(step_cv.wait_for(lk, std::chrono::seconds(20), [] { return step == 2 || capture_waits; }));
}
// (vk_memory.cpp's collect_mu, with a lock() that says when it finds the mutex held inside the window)
struct ProbeMutex {
    std::mutex m;
    void lock() {
        if (m.try_lock()) return;
        {
            std::lock_guard lk(step_mu);
            if (step == 1) capture_waits = true;
        }
        step_cv.notify_all();
        m.lock();
    }
    void unlock() { m.unlock(); }
};
ProbeMutex collect_mu;
int64_t take_marks(uint64_t p0, uint64_t p1, uint32_t** pages) {
    uint32_t* out = (uint32_t*)std::malloc(kTestPages * sizeof(uint32_t));
    int64_t n = 0;
    for (uint64_t p = p0; p < p1 && p < kTestPages; p++)
        if (__atomic_exchange_n(&marks[p], 0, __ATOMIC_ACQ_REL)) out[n++] = (uint32_t)p;
    *pages = out;
    return n;
}
int64_t host_collect_written(uint32_t** pages) {
    const int64_t n = take_marks(0, kTestPages, pages);
    if (enter == kAfterTake) hold_window();   // (every mark taken, none set again yet)
    return n;
}
int64_t host_collect_written_in(const uint64_t (*ranges)[2], int n, uint32_t** pages) {
    CHECK(n == 1);
    return take_marks(ranges[0][0] >> kPageShift, (ranges[0][1] + 4095) >> kPageShift, pages);
}
uint8_t* host_gpu_ptr(uint64_t gpu, uint64_t* avail) {
    if (gpu >= sizeof guest_mem) return nullptr;
    *avail = sizeof guest_mem - gpu;
    return guest_mem + gpu;
}
void host_mark_written(const void* p, uint64_t n) {
    if (enter == kAtRemark) hold_window();    // (the captured page's mark not set again yet)
    const uint64_t a = (uint64_t)((const uint8_t*)p - guest_mem);
    for (uint64_t q = a >> kPageShift; q <= (a + n - 1) >> kPageShift && q < kTestPages; q++)
        __atomic_store_n(&marks[q], 1, __ATOMIC_RELEASE);
}
void host_free_pages(uint32_t* pages) { std::free(pages); }
struct Host {
    uint8_t* (*gpu_ptr)(uint64_t gpu, uint64_t* avail);
    int64_t (*collect_written)(uint32_t** pages);
    void (*free_pages)(uint32_t* pages);
    void (*mark_written)(const void* p, uint64_t n);
    int64_t (*collect_written_in)(const uint64_t (*ranges)[2], int n, uint32_t** pages);
};
const Host host_fns{host_gpu_ptr, host_collect_written, host_free_pages, host_mark_written, host_collect_written_in};
const Host* host = &host_fns;
// (stand-ins for the rest of vk_memory.cpp the two functions use)
uint32_t gen_now = 1;
uint64_t pages_collected = 0;
uint32_t stamped[kTestPages];
void stamp_page(uint64_t p, uint32_t g) {
    if (p < kTestPages) stamped[p] = g;
}
const std::vector<std::pair<uint64_t, uint64_t>> captured{{8 << kPageShift, 16 << kPageShift}};   // (pages 8-15)
const std::vector<std::pair<uint64_t, uint64_t>>& capture_ranges_merged() { return captured; }
void cap_view_bump() {}
void shadow_written_collected(const uint32_t*, int64_t) {}
uint32_t early_check_collect_begin() { return 0; }   // (RX_VK_LOG_EARLY_CHECK off)
void early_check_cpu_pages(const uint32_t*, int64_t, bool, uint32_t) {}
@WALK@
@COLLECT@
@SCAN@
void run(Enter e, const char* when) {
    enter = e;
    step = 0;
    capture_waits = false;
    gen_now = 1;
    std::fill(std::begin(marks), std::end(marks), 0);
    std::fill(std::begin(stamped), std::end(stamped), 0);
    marks[9] = 1;    // (the CPU wrote page 9, in the captured ranges, and page 20, outside them, before the submit)
    marks[20] = 1;
    std::vector<uint32_t> got;
    std::thread capture([&got] {   // (the game's thread: the submit's capture, while the collection is in its window)
        {
            std::unique_lock lk(step_mu);
            CHECK(step_cv.wait_for(lk, std::chrono::seconds(20), [] { return step >= 1; }));
        }
        uint32_t* pages = nullptr;
        const int64_t n = capture_scan(captured, &pages);
        if (n > 0) got.assign(pages, pages + n);
        if (pages) host_free_pages(pages);
        std::lock_guard lk(step_mu);
        step = 2;
        step_cv.notify_all();
    });
    memory_collect_written();   // (the render thread)
    {
        std::lock_guard lk(step_mu);
        CHECK(step >= 1);   // (the collection came to the point the capture is let in at)
    }
    capture.join();
    const bool has9 = std::find(got.begin(), got.end(), 9u) != got.end();
    std::printf("a capture %s %s; it took %zu pages%s, page 9's mark %s\n", when,
                capture_waits ? "waited for the collection" : "scanned at once", got.size(),
                has9 ? ", page 9 among them" : ", not page 9", marks[9] ? "set (for the next capture)" : "cleared");
    CHECK(has9);                                                  // (written before the capture began: in it)
    CHECK(!marks[9]);                                             // (taken once, by this capture)
    CHECK(std::find(got.begin(), got.end(), 20u) == got.end());   // (outside the captured ranges)
    CHECK(stamped[20] == gen_now && gen_now == 2);                // (the collection's own page, stamped)
    CHECK(!marks[20] && stamped[9] == 0);
}
int main() {
    run(kAfterTake, "just after the collection took the marks");
    run(kAtRemark, "as the collection marked the captured page again");
    std::printf("PASS: the capture holds the page the collection was marking again, at both ends of the window\n");
    return 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    source = (ROOT / "gpu" / "vk" / "vk_memory.cpp").read_text(encoding="utf-8")
    walk = block(source, "struct RangeWalk {") + ";"
    collect = block(source, "void memory_collect_written() {")
    scan = block(source, "int64_t capture_scan(")
    with tempfile.TemporaryDirectory(prefix="vk-collect-window-") as tmp:
        cpp = Path(tmp) / "fixture.cpp"
        exe = Path(tmp) / ("fixture.exe" if os.name == "nt" else "fixture")
        fixture = FIXTURE.replace("@WALK@", walk).replace("@COLLECT@", collect).replace("@SCAN@", scan)
        cpp.write_text(fixture, encoding="utf-8")
        cmd = [a.cxx, "-std=c++20", "-O2", "-pthread", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(exe)]
        subprocess.run(cmd, check=True)
        subprocess.run([str(exe)], check=True, timeout=60)


if __name__ == "__main__":
    main()
