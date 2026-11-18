"""A read-back whose wait timed out is still on the GPU: the next one does not reset its command buffer or fence under it,
and the eviction keeps the textures whose write-backs wait for it.

readback_submit_wait (gpu/vk/vk_texture.cpp) gives up after 5 s and returns false with rb_cmd still pending and rb_fence
still unsignaled. The eviction's write-backs go in batches of 64, one readback_begin after another in the same loop, so the
next batch reset the command pool of a command buffer the GPU was still running (VUID-vkResetCommandPool-commandPool-00040)
and, at its submit, the fence a queue operation still held (VUID-vkResetFences-pFences-01123). And every texture of those
batches was evicted with no copy of its texels: made again, it started empty.

Cut out of the source unmodified: the read-back's state, readback_begin, readback_submit_wait, struct Dead, struct Flush,
flush_textures and the end of texture_frame's eviction (from its write-backs to the textures' removal). They run against a
stub Vulkan that tracks what is pending, a stub texture and stub write-back halves; no GPU or game is involved. The cases:

  begin     a read-back after a timed-out one neither resets nor resubmits what the GPU still runs; once the GPU is past it,
            read-backs work again
  later     an eviction pass whose first batch times out: the textures of every batch that waits for that read-back stay,
            not destroyed and not counted written back; textures that need no write-back still go (the pass frees VRAM);
            the pass waits 5 s once at most, not once a batch; a later pass, the GPU past it, writes them back and evicts them
  lost      the wait fails with VK_ERROR_DEVICE_LOST: read-backs fail at once from then on (no wait), and the eviction still
            evicts everything it chose

python -I -B tests/test_readback_timeout_reuse.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r"""
#include <atomic>
#include <chrono>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
#include <map>
#include <memory>
#include <mutex>
#include <set>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "evict_reason.h"

// ---- a stub Vulkan: only what the code cut out calls ----
typedef int VkResult;
enum { VK_SUCCESS = 0, VK_TIMEOUT = 2, VK_ERROR_DEVICE_LOST = -4 };
typedef int VkStructureType;
enum { VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO = 1, VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
       VK_STRUCTURE_TYPE_FENCE_CREATE_INFO, VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, VK_STRUCTURE_TYPE_MEMORY_BARRIER_2,
       VK_STRUCTURE_TYPE_DEPENDENCY_INFO, VK_STRUCTURE_TYPE_COMMAND_BUFFER_SUBMIT_INFO, VK_STRUCTURE_TYPE_SUBMIT_INFO_2 };
enum { VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT = 2, VK_COMMAND_BUFFER_LEVEL_PRIMARY = 0,
       VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT = 1 };
enum : uint64_t { VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT = 1, VK_PIPELINE_STAGE_2_HOST_BIT = 2, VK_ACCESS_2_MEMORY_WRITE_BIT = 4,
                  VK_ACCESS_2_HOST_READ_BIT = 8 };
#define VK_TRUE 1
#define VK_NULL_HANDLE nullptr
struct Obj { int id; };
typedef Obj* VkCommandPool;
typedef Obj* VkCommandBuffer;
typedef Obj* VkFence;
typedef Obj* VkDevice;
typedef Obj* VkQueue;
typedef Obj* VkImage;
typedef Obj* VkImageView;
typedef Obj* VkDeviceMemory;
typedef Obj* VkBuffer;
typedef Obj* VmaAllocation;
struct VkCommandPoolCreateInfo { VkStructureType sType; const void* pNext; uint32_t flags; uint32_t queueFamilyIndex; };
struct VkCommandBufferAllocateInfo { VkStructureType sType; const void* pNext; VkCommandPool commandPool; int level;
                                     uint32_t commandBufferCount; };
struct VkFenceCreateInfo { VkStructureType sType; const void* pNext; uint32_t flags; };
struct VkCommandBufferBeginInfo { VkStructureType sType; const void* pNext; uint32_t flags; const void* pInheritanceInfo; };
struct VkMemoryBarrier2 { VkStructureType sType; const void* pNext; uint64_t srcStageMask, srcAccessMask, dstStageMask,
                          dstAccessMask; };
struct VkDependencyInfo { VkStructureType sType; const void* pNext; uint32_t dependencyFlags; uint32_t memoryBarrierCount;
                          const VkMemoryBarrier2* pMemoryBarriers; };
struct VkCommandBufferSubmitInfo { VkStructureType sType; const void* pNext; VkCommandBuffer commandBuffer; uint32_t deviceMask; };
struct VkSubmitInfo2 { VkStructureType sType; const void* pNext; uint32_t flags; uint32_t waitSemaphoreInfoCount;
                       const void* pWaitSemaphoreInfos; uint32_t commandBufferInfoCount;
                       const VkCommandBufferSubmitInfo* pCommandBufferInfos; };

static Obj the_pool{1}, the_cmd{2}, the_fence{3}, the_device{4}, the_queue{5}, a_buffer{6};
struct Dev { VkDevice device = &the_device; VkQueue queue = &the_queue; uint32_t queue_family = 0; std::mutex present_mu; } dev;

// (the GPU: a submission is pending until gpu_done; the fence is signaled once it is. lost: the device is lost)
static bool pending = false, fence_signaled = false, gpu_finishes = true, lost = false;
static int violations = 0, long_waits = 0, vk_calls_after_lost = 0;
static void gpu_done() { if (pending) pending = false, fence_signaled = true; }
static void violation(const char* what) { std::printf("VIOLATION: %s\n", what); violations++; }
static void call() { if (lost) vk_calls_after_lost++; }

VkResult vkCreateCommandPool(VkDevice, const VkCommandPoolCreateInfo*, const void*, VkCommandPool* p) { *p = &the_pool; return VK_SUCCESS; }
VkResult vkAllocateCommandBuffers(VkDevice, const VkCommandBufferAllocateInfo*, VkCommandBuffer* c) { *c = &the_cmd; return VK_SUCCESS; }
VkResult vkCreateFence(VkDevice, const VkFenceCreateInfo*, const void*, VkFence* f) { *f = &the_fence; return VK_SUCCESS; }
void vkDestroyCommandPool(VkDevice, VkCommandPool, const void*) {}
VkResult vkResetCommandPool(VkDevice, VkCommandPool, uint32_t) {
    call();
    if (pending && !lost) violation("vkResetCommandPool with its command buffer still pending on the GPU");
    return VK_SUCCESS;
}
VkResult vkBeginCommandBuffer(VkCommandBuffer, const VkCommandBufferBeginInfo*) { call(); return VK_SUCCESS; }
void vkCmdPipelineBarrier2(VkCommandBuffer, const VkDependencyInfo*) {}
VkResult vkEndCommandBuffer(VkCommandBuffer) { return VK_SUCCESS; }
VkResult vkResetFences(VkDevice, uint32_t, const VkFence*) {
    call();
    if (pending && !lost) violation("vkResetFences on a fence a queue submission still holds");
    fence_signaled = false;
    return VK_SUCCESS;
}
VkResult vkQueueSubmit2(VkQueue, uint32_t, const VkSubmitInfo2*, VkFence) {
    call();
    if (pending && !lost) violation("vkQueueSubmit2 of a command buffer still pending");
    pending = true;
    return VK_SUCCESS;
}
VkResult vkWaitForFences(VkDevice, uint32_t, const VkFence*, uint32_t, uint64_t timeout) {
    call();
    if (timeout) long_waits++;
    if (lost) return VK_ERROR_DEVICE_LOST;
    if (gpu_finishes) gpu_done();
    return fence_signaled ? VK_SUCCESS : VK_TIMEOUT;
}
void queue_flush_locked() {}

// ---- the rest the code cut out names ----
struct LevelGeo {};
struct Texture {
    uint64_t gpu = 0, guest_size = 4096, bytes = 1 << 20, last_frame = 0, last_value = 0;
    uint32_t id = 0, width = 64, height = 64, depth = 1, layers = 1;
    int nvn_format = 0x25;
    bool gpu_written = true, released = false, uploaded = true;
};
static uint64_t rec_value = 10, frame_no = 1000;
static void logf(const char*, ...) {}
static void full_barrier(VkCommandBuffer, const char* = nullptr) {}
static void destroy_buffer(VkBuffer, VmaAllocation) {}
static void watch_tex(const Texture*, const char*) {}
static bool remade_skip_old() { return false; }
static bool remade_log_on() { return false; }
static uint64_t evicted_key(uint64_t gpu, uint32_t, uint32_t, uint32_t) { return gpu; }
struct Evicted { uint64_t frame; bool rendered; };
static std::mutex from_memory_mu, evicted_mu;
static std::unordered_map<uint64_t, uint64_t> evicted_from_memory;
static std::unordered_map<uint64_t, Evicted> evicted_at;
static std::unordered_map<const Texture*, uint64_t> remade;
static std::set<const Texture*> destroyed, written;
static void destroy_later(Texture& t) { destroyed.insert(&t); }
static void forget_gpu(Texture*) {}
static std::map<uint64_t, std::unique_ptr<Texture>> textures;

namespace {
/* DEAD */
std::deque<Dead> dead;
/* READBACK */
/* FLUSH */
// (the write-back's halves: a copy recorded, and the texels put into memory once the copy completed)
bool flush_record(Flush& f, VkCommandBuffer = VK_NULL_HANDLE) { f.buf = &a_buffer; return f.ok = true; }
bool flush_finish(Flush& f, bool gpu_ok) {
    if (f.ok && gpu_ok) written.insert(f.t);
    f.buf = VK_NULL_HANDLE;
    return f.ok && gpu_ok;
}
/* FLUSH_TEXTURES */

static uint64_t n_dead, b_dead;
/* EVICT_STRUCT */
void evict_pass(std::vector<Texture*> flush, std::vector<Texture*> other) {
    std::vector<Evict> evict;
    for (Texture* t : flush) evict.push_back({t, true, false, false});
    for (Texture* t : other) evict.push_back({t, false, false, false});
    std::unordered_set<Texture*> gone;
/* EVICT_TAIL */
}
}

#define CHECK(c, ...) do { if (!(c)) { std::printf("FAIL: " __VA_ARGS__); std::printf("\n"); return 1; } } while (0)

static std::vector<Texture*> make(int n) {
    static uint64_t next = 0x100000;
    std::vector<Texture*> v;
    for (int i = 0; i < n; i++) {
        auto t = std::make_unique<Texture>();
        t->gpu = next, t->id = (uint32_t)(next >> 12), next += 0x10000;
        v.push_back(t.get());
        textures[t->gpu] = std::move(t);
    }
    return v;
}
static bool kept(Texture* t) { return textures.count(t->gpu) && !destroyed.count(t); }

static int case_begin() {
    CHECK(readback_begin(), "the first read-back did not begin");
    CHECK(readback_submit_wait(), "a read-back the GPU finished was not reported done");
    CHECK(!pending && violations == 0, "the ordinary read-back left something pending or broke a rule");
    CHECK(readback_begin(), "the second read-back did not begin");
    gpu_finishes = false;
    CHECK(!readback_submit_wait(), "the wait did not time out: the faulty path was not taken");
    CHECK(pending && !fence_signaled, "the stub's precondition: the timed-out submission is still pending");
    const bool began = readback_begin();
    if (began) readback_submit_wait();
    CHECK(violations == 0, "a read-back after a timed-out one reset or resubmitted what the GPU still runs (%d violation(s))",
          violations);
    CHECK(!began, "a read-back began while the one before it is still pending");
    gpu_finishes = true;
    gpu_done();
    CHECK(readback_begin(), "no read-back began after the pending one completed");
    CHECK(readback_submit_wait(), "the read-back after the pending one completed did not complete");
    CHECK(violations == 0, "rules broken after the pending one completed");
    return 0;
}

static int case_later() {
    // (70 textures to write back: two batches, 64 and 6; and 3 that need none)
    std::vector<Texture*> flush = make(70), other = make(3);
    gpu_finishes = false;   // (the first batch's read-back is still on the GPU when its 5 s are up)
    evict_pass(flush, other);
    CHECK(pending && !fence_signaled, "the stub's precondition: the first batch's read-back timed out and is still pending");
    CHECK(violations == 0, "a later batch of the pass reset or resubmitted the read-back the GPU still runs (%d violation(s))",
          violations);
    int gone_flush = 0, written_n = 0;
    for (Texture* t : flush) gone_flush += !kept(t), written_n += (int)written.count(t);
    CHECK(gone_flush == 0, "%d of the 70 textures whose write-backs wait for the pending read-back were evicted with no copy "
                           "of their texels (made again, they start empty)", gone_flush);
    CHECK(written_n == 0, "%d textures counted written back by a read-back that never completed", written_n);
    for (Texture* t : other) CHECK(!kept(t), "a texture that needs no write-back was kept: the pass freed nothing");
    CHECK(long_waits <= 1, "the pass waited %d times for the GPU (5 s each), not once at most", long_waits);
    // (a later pass, the GPU past the read-back: they are written back and go)
    gpu_finishes = true;
    gpu_done();
    evict_pass(flush, {});
    for (Texture* t : flush) {
        CHECK(written.count(t), "a texture kept for a later pass was not written back once the read-back completed");
        CHECK(!kept(t), "a texture written back on the later pass was not evicted");
    }
    CHECK(violations == 0, "rules broken on the later pass");
    return 0;
}

static int case_lost() {
    std::vector<Texture*> flush = make(70), other = make(3);
    CHECK(readback_begin(), "the first read-back did not begin");
    lost = true;
    CHECK(!readback_submit_wait(), "a wait on a lost device was reported done");
    const int waits = long_waits;
    vk_calls_after_lost = 0;
    evict_pass(flush, other);
    CHECK(vk_calls_after_lost == 0 && long_waits == waits,
          "read-backs after the device was lost still called Vulkan (%d calls, %d waits of 5 s)", vk_calls_after_lost,
          long_waits - waits);
    int left = 0;
    for (Texture* t : flush) left += kept(t);
    for (Texture* t : other) left += kept(t);
    CHECK(left == 0, "%d of 73 textures not evicted after the device was lost: the eviction stopped freeing", left);
    CHECK(!readback_begin(), "a read-back began on a lost device");
    return 0;
}

int main(int argc, char** argv) {
    const char* c = argc > 1 ? argv[1] : "";
    const int r = !strcmp(c, "begin") ? case_begin() : !strcmp(c, "later") ? case_later() : !strcmp(c, "lost") ? case_lost() : 2;
    if (!r) std::printf("read-back after a timeout, %s: ok\n", c);
    return r;
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


def between(text, first, last):
    start = text.index(first)
    return text[start:text.index(last, start)]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    source = (ROOT / "gpu/vk/vk_texture.cpp").read_text(encoding="utf-8")
    wait = block(source, "bool readback_submit_wait()")
    readback = between(source, "// (a command buffer of its own for the read-backs", wait) + wait
    frame = block(source, "void texture_frame(uint64_t completed)")
    evict_struct = frame[frame.index("    struct Evict {"):frame.index("\n", frame.index("    struct Evict {"))]
    tail = between(frame, "    evict_reason::Tally tally;", "    if (n_dead && frame_no >= dead_logged_at")
    fixture = (FIXTURE.replace("/* DEAD */", block(source, "struct Dead {") + ";")
               .replace("/* READBACK */", readback)
               .replace("/* FLUSH */", block(source, "struct Flush {") + ";")
               .replace("/* FLUSH_TEXTURES */", block(source, "void flush_textures(std::vector<Flush>& fs)"))
               .replace("/* EVICT_STRUCT */", evict_struct)
               .replace("/* EVICT_TAIL */", tail))
    with tempfile.TemporaryDirectory(prefix="hookshot-readback-timeout-") as temp:
        cpp, exe = Path(temp) / "fixture.cpp", Path(temp) / "fixture.exe"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-missing-field-initializers",
                        "-Wno-unused-function", "-Wno-unused-variable", "-Wno-unused-but-set-variable",
                        "-I" + str(ROOT / "gpu" / "vk"), str(cpp), "-o", str(exe)], check=True)
        failed = [case for case in ("begin", "later", "lost") if subprocess.run([str(exe), case], timeout=30).returncode]
        if failed:
            raise SystemExit("read-back after a timeout: failed: " + ", ".join(failed))


if __name__ == "__main__":
    main()
