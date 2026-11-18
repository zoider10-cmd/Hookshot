"""A timeline wait that comes back VK_ERROR_DEVICE_LOST is said as a lost device, not as a wait that timed out (gpu/vk/
vk_replay.cpp wait_rec_seq, vk_timeline_wait, wait_lost).

Run 21 (macOS, MoltenVK 1.4.2; reports/2026-11-14-device-lost-21.md in the macOS port's notes) lost the GPU device while a
capture waited for its write-back, and the log said `vk: a capture's wait for write-back 9646 timed out (done 0)`: the driver
marks the device lost, signals every timeline waited on, returns VK_ERROR_DEVICE_LOST from the wait and leaves the counter
unwritten, so completed() read 0. It runs vk_replay.cpp's own wait_rec_seq and vk_timeline_wait, cut from the source, against a
made-up driver:
- a recordings' wait (wait_rec_seq) that comes back VK_ERROR_DEVICE_LOST: `a wait for recording N came back
  VK_ERROR_DEVICE_LOST`, and no `timed out` line;
- the capture's own timeline wait that comes back VK_ERROR_DEVICE_LOST: `a capture's wait for write-back N came back
  VK_ERROR_DEVICE_LOST`;
- a wait that times out: said as before; one that is done: nothing said;
- nothing else changes: neither wait ends the process (device_lost is not called there; the next submit or the GPU hang watch
  does, as before) and every VK_ERROR_DEVICE_LOST check of vk_replay.cpp keeps test_device_lost_exit's form.
No GPU or game. python -I -B tests/test_lost_wait_said.py --headers <Vulkan-Headers/include> [--cxx clang++] [--arch x86_64]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{vulkan_headers}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def block(text, marker, start=0):
    """From marker to the end of the braces it opens"""
    at = text.index(marker, start)
    end = text.index("{", at) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[at:end]


FIXTURE = r"""
#include <vulkan/vulkan_core.h>
#include <atomic>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>
static std::vector<std::string> logs;
static void logf(const char* format, ...) {
    char line[1024];
    va_list a;
    va_start(a, format);
    std::vsnprintf(line, sizeof line, format, a);
    va_end(a);
    logs.emplace_back(line);
}
static int lost_calls = 0;
[[maybe_unused]] static void device_lost(const char* = nullptr) { lost_calls++; }
struct Dev { VkDevice device = VK_NULL_HANDLE; } dev;
static VkSemaphore timeline = (VkSemaphore)(uintptr_t)1, rec_timeline = (VkSemaphore)(uintptr_t)2;
static VkResult wait_gives = VK_TIMEOUT;
static uint64_t counter = 0;
VKAPI_ATTR VkResult VKAPI_CALL vkWaitSemaphores(VkDevice, const VkSemaphoreWaitInfo*, uint64_t) { return wait_gives; }
VKAPI_ATTR VkResult VKAPI_CALL vkGetSemaphoreCounterValue(VkDevice, VkSemaphore, uint64_t* v) {
    *v = counter;   // (a lost device: the value unwritten, 0 here, as completed() read in run 21)
    return wait_gives == VK_ERROR_DEVICE_LOST ? VK_ERROR_DEVICE_LOST : VK_SUCCESS;
}
static uint64_t completed() { uint64_t v = 0; vkGetSemaphoreCounterValue(dev.device, timeline, &v); return v; }
enum { FR_VALUE, FR_WAIT };
static void queue_flush_for(int) {}
namespace fps_stats { enum { kGpuWait }; }
static int fps_gpu_wait_kind() { return fps_stats::kGpuWait; }   // (main's #928: the kind of GPU wait, outside the game's fence wait)
struct FpsWait { explicit FpsWait(int) {} };
static bool by_recording = true;
static void wait_rec_seq(uint64_t seq, uint64_t timeout_ns, int* ok);
namespace {
/* PIECES */
bool wait_recorded(uint64_t f, uint64_t timeout_ns, int* ok) {
    if (!by_recording) return false;
    wait_rec_seq(f, timeout_ns, ok);
    return true;
}
}
/* TIMELINE_WAIT */
/* REC_SEQ */
static int fails = 0;
static bool said(const char* s) {
    for (const auto& l : logs) if (l.find(s) != std::string::npos) return true;
    return false;
}
static void show() { for (const auto& l : logs) std::printf("  %s\n", l.c_str()); }
static void run(bool recording, VkResult gives, uint64_t v) {
    logs.clear(), lost_calls = 0, by_recording = recording, wait_gives = gives, counter = 0;
    vk_timeline_wait(v);
}
int main() {
    for (bool recording : {true, false}) {
        run(recording, VK_ERROR_DEVICE_LOST, 9646);
        const char* where = recording ? "a wait for recording 9646" : "a capture's wait for write-back 9646";
        const std::string line = std::string(where) + " came back VK_ERROR_DEVICE_LOST: the GPU device is lost";
        if (!said(line.c_str())) std::printf("FAIL: %s: not said as a lost device\n", where), fails++;
        if (said("timed out")) std::printf("FAIL: %s: a lost device said as a wait that timed out (done 0)\n", where), fails++;
        if (lost_calls) std::printf("FAIL: %s: the wait ended the process (device_lost)\n", where), fails++;
        show();
        run(recording, VK_TIMEOUT, 9597);
        if (!said("vk: a capture's wait for write-back 9597 timed out (done 0)") || said("came back") || lost_calls)
            std::printf("FAIL: %s: a wait that timed out not said as before\n", recording ? "recording" : "capture"), fails++;
        show();
        run(recording, VK_SUCCESS, 9598);
        if (!logs.empty() || lost_calls) std::printf("FAIL: %s: a wait that is done says something\n", recording ? "recording" : "capture"), fails++;
    }
    // (a second loss on the same wait path: said at most 8 times in all)
    for (int i = 0; i < 12; i++) run(false, VK_ERROR_DEVICE_LOST, 9700 + i);
    if (!logs.empty()) std::printf("FAIL: the lost wait's line said more than 8 times\n"), fails++;
    std::printf(fails ? "%d failed\n" : "lost waits: every check passed\n", fails);
    return fails ? 1 : 0;
}
"""


def check_source(replay, fails):
    # (no new end of the process at a wait: the line only)
    for name, marker in (("vk_timeline_wait", "void vk_timeline_wait(uint64_t v) {"),
                         ("wait_rec_seq", "static void wait_rec_seq(uint64_t seq, uint64_t timeout_ns, int* ok) {")):
        try:
            if "device_lost(" in block(replay, marker):
                fails.append(name + " ends the process at a lost wait: this change is the line alone")
        except ValueError:
            fails.append("vk_replay.cpp has no " + marker)
    # (test_device_lost_exit reads a line with VK_ERROR_DEVICE_LOST and `if (` as a check that must end the process)
    stray = [line.strip() for line in replay.splitlines() if "VK_ERROR_DEVICE_LOST" in line and "if (" in line and
             not re.search(r"== VK_ERROR_DEVICE_LOST\) device_lost\(\);", line)]
    if stray:
        fails.append("vk_replay.cpp: a VK_ERROR_DEVICE_LOST check not in test_device_lost_exit's form: " + "; ".join(stray))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--headers", type=Path, required=True)
    p.add_argument("--cxx", default="clang++")
    p.add_argument("--arch", help="build for this architecture and run under arch(1): x86_64 runs under Rosetta")
    a = p.parse_args()
    fails = []
    replay = (VK / "vk_replay.cpp").read_text(encoding="utf-8")
    check_source(replay, fails)
    # (the lost wait's result and line, before vk_timeline_wait; a tree from before has neither, and its waits are cut as they
    # are, to show what they said)
    start = replay.find("/// (hookshot) What the calling thread's last wait on the recordings' timeline came back with")
    end = replay.find("} // namespace\nuint64_t vk_timeline_completed()")
    pieces = replay[start:end] if 0 <= start < end else ""
    try:
        src = FIXTURE.replace("/* PIECES */", pieces) \
            .replace("/* TIMELINE_WAIT */", block(replay, "void vk_timeline_wait(uint64_t v) {")) \
            .replace("/* REC_SEQ */", block(replay, "static void wait_rec_seq(uint64_t seq, uint64_t timeout_ns, int* ok) {"))
    except ValueError as e:
        fails.append("vk_replay.cpp: the waits could not be cut out (%s)" % e)
        src = None
    if src is not None:
        arch = ["-arch", a.arch] if a.arch else []
        run = ["/usr/bin/arch", "-" + a.arch] if a.arch else []
        with tempfile.TemporaryDirectory(prefix="lost-wait-") as tmp:
            tmp = Path(tmp)
            (tmp / "waits.cpp").write_text(src, encoding="utf-8")
            exe = tmp / "waits"
            # (vk_replay.cpp's own `VkSemaphoreWaitInfo wi{VK_STRUCTURE_TYPE_SEMAPHORE_WAIT_INFO};`, as the renderer builds it)
            built = subprocess.run([a.cxx, *arch, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-missing-field-initializers",
                                    "-I" + str(a.headers), str(tmp / "waits.cpp"), "-o", str(exe)], capture_output=True, text=True)
            if built.returncode:
                fails.append("the waits fixture did not build:\n" + (built.stdout + built.stderr)[-3000:])
            else:
                ran = subprocess.run([*run, str(exe)], capture_output=True, text=True, timeout=60)
                print(ran.stdout.strip())
                if ran.returncode:
                    fails.append("the waits fixture failed:\n" + (ran.stdout + ran.stderr)[-3000:])
    if fails:
        raise SystemExit("FAIL:\n" + "\n".join(fails))
    print("PASS: a timeline wait that comes back VK_ERROR_DEVICE_LOST is said as a lost device, not as a wait that timed out; "
          "timeouts said as before; no wait ends the process")


if __name__ == "__main__":
    main()
