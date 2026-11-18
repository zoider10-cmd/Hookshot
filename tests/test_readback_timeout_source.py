"""The image a timed-out read-back copies from is not freed or pooled before the GPU is past that copy.

A batch of write-backs (flush_textures, gpu/vk/vk_texture.cpp) records vkCmdCopyImageToBuffer from each texture's image and
waits 5 s for it. When the wait times out, the staging buffers the copies write are kept until a submission after it is
done (dead, rec_value + 1), but the textures they read were not: the eviction then destroys each one with its own
last_value, already completed, and the next texture_frame destroyed its image (or put it in the render targets' pool, for
a new texture to clear and draw into) while the copy could still run on the GPU: a read from a freed image.

Cut out of the source unmodified: the read-back's state and functions, struct Dead, struct Flush, flush_textures,
destroy_later and texture_frame's loop over the dead list. They run against stub Vulkan, VMA and pool calls; no GPU or
game is involved. Each case: a write-back whose wait times out, the texture evicted, and the next present's dead list
handled with the GPU not yet past the copy's recording; the image must still be there, then go once the GPU is past it.

python -I -B tests/test_readback_timeout_source.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r"""
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
#include <mutex>
#include <set>
#include <unordered_map>
#include <vector>

typedef int VkResult;
enum { VK_SUCCESS = 0, VK_TIMEOUT = 2 };
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

static Obj the_pool{1}, the_cmd{2}, the_fence{3}, the_device{4}, the_queue{5}, a_buffer{6}, the_image{7}, the_alloc{8};
struct Dev { VkDevice device = &the_device; VkQueue queue = &the_queue; uint32_t queue_family = 0; std::mutex present_mu; } dev;

VkResult vkCreateCommandPool(VkDevice, const VkCommandPoolCreateInfo*, const void*, VkCommandPool* p) { *p = &the_pool; return VK_SUCCESS; }
VkResult vkAllocateCommandBuffers(VkDevice, const VkCommandBufferAllocateInfo*, VkCommandBuffer* c) { *c = &the_cmd; return VK_SUCCESS; }
VkResult vkCreateFence(VkDevice, const VkFenceCreateInfo*, const void*, VkFence* f) { *f = &the_fence; return VK_SUCCESS; }
VkResult vkResetCommandPool(VkDevice, VkCommandPool, uint32_t) { return VK_SUCCESS; }
VkResult vkBeginCommandBuffer(VkCommandBuffer, const VkCommandBufferBeginInfo*) { return VK_SUCCESS; }
void vkCmdPipelineBarrier2(VkCommandBuffer, const VkDependencyInfo*) {}
VkResult vkEndCommandBuffer(VkCommandBuffer) { return VK_SUCCESS; }
VkResult vkResetFences(VkDevice, uint32_t, const VkFence*) { return VK_SUCCESS; }
VkResult vkQueueSubmit2(VkQueue, uint32_t, const VkSubmitInfo2*, VkFence) { return VK_SUCCESS; }
VkResult vkWaitForFences(VkDevice, uint32_t, const VkFence*, uint32_t, uint64_t) { return VK_TIMEOUT; }   // (the GPU behind)
void vkDestroyImageView(VkDevice, VkImageView, const void*) {}
void vkFreeMemory(VkDevice, VkDeviceMemory, const void*) {}
void queue_flush_locked() {}

struct LevelGeo {};
struct Texture {
    VkImage image = &the_image;
    VmaAllocation allocation = &the_alloc;
    uint64_t gpu = 0x100000, guest_size = 4096, bytes = 1 << 20, pad = 0, last_value = 0, pool_key = 0;
    std::vector<VkDeviceMemory> sparse_chunks;
    std::unordered_map<uint64_t, VkImageView> views;
    struct BlockAttachment { VkImage image; VmaAllocation allocation; int format; uint32_t level; };
    std::vector<BlockAttachment> block_attachments;
};
static uint64_t rec_value = 0, destroy_gen = 1, total_bytes = 1 << 20;
static void logf(const char*, ...) {}
static void full_barrier(VkCommandBuffer, const char* = nullptr) {}
static void destroy_buffer(VkBuffer, VmaAllocation) {}
static uint64_t pool_cap() { return 256ull << 20; }
static std::set<VkImage> freed, pooled;
static void destroy_image(VkImage i, VmaAllocation) { if (i) freed.insert(i); }
struct { bool in_pass = false; } compact;

namespace {
/* DEAD */
std::deque<Dead> dead;
void pool_put(Dead& d) { pooled.insert(d.image); }
/* READBACK */
/* FLUSH */
bool flush_record(Flush& f, VkCommandBuffer = VK_NULL_HANDLE) { f.buf = &a_buffer; return f.ok = true; }
bool flush_finish(Flush& f, bool gpu_ok) { f.buf = VK_NULL_HANDLE; return f.ok && gpu_ok; }
/* FLUSH_TEXTURES */
/* DESTROY_LATER */
void dead_list(uint64_t completed) {
/* DEAD_LOOP */
}
}

int main(int argc, char** argv) {
    const bool target = argc > 1 && !strcmp(argv[1], "target");   // (a render target's image: to the pool, not destroyed)
    Texture t;
    if (target) t.pool_key = 0x1235;
    // (its last use completed long ago: the eviction may take it)
    t.last_value = 5;
    uint64_t completed = 9;
    rec_value = 10;   // (the present's recording)
    std::vector<Flush> batch;
    batch.push_back(Flush{&t, t.gpu, t.gpu + t.guest_size});
    flush_textures(batch);
    if (batch[0].ok) { std::printf("FAIL: the stub's precondition: the write-back's wait did not time out\n"); return 1; }
    const uint64_t gen = destroy_gen;
    destroy_later(t);   // (the eviction, as texture_frame does after the write-backs)
    if (destroy_gen == gen || dead.empty()) {
        std::printf("FAIL: the stub's precondition: destroy_later did not retire the texture (no new destroy generation)\n");
        return 1;
    }
    // (the next present: the GPU has finished the recording before it, not the read-back's (submitted after rec_value's work
    // began) nor anything after it)
    completed = 10;
    rec_value = 11;
    dead_list(completed);
    if (freed.count(&the_image) || pooled.count(&the_image)) {
        std::printf("FAIL: the image a timed-out read-back copies from was %s at completed %llu, before the GPU is past the "
                    "copy (its staging buffer waits for %llu)\n", freed.count(&the_image) ? "destroyed" : "put in the target pool",
                    (unsigned long long)completed, 11ull);
        return 1;
    }
    dead_list(11);   // (the GPU past a submission after the read-back: now it goes)
    if (!freed.count(&the_image) && !pooled.count(&the_image)) {
        std::printf("FAIL: the image never went once the GPU was past the read-back\n");
        return 1;
    }
    std::printf("timed-out read-back's source image (%s): ok\n", target ? "render target" : "texture");
    return 0;
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
    frame = block(source, "void texture_frame(uint64_t completed)")
    fixture = (FIXTURE.replace("/* DEAD */", block(source, "struct Dead {") + ";")
               .replace("/* READBACK */", between(source, "// (a command buffer of its own for the read-backs", wait) + wait)
               .replace("/* FLUSH */", block(source, "struct Flush {") + ";")
               .replace("/* FLUSH_TEXTURES */", block(source, "void flush_textures(std::vector<Flush>& fs)"))
               .replace("/* DESTROY_LATER */", block(source, "void destroy_later(Texture& tex)"))
               .replace("/* DEAD_LOOP */", block(frame, "    for (auto it = dead.begin(); it != dead.end();)")))
    with tempfile.TemporaryDirectory(prefix="hookshot-readback-source-") as temp:
        cpp, exe = Path(temp) / "fixture.cpp", Path(temp) / "fixture.exe"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-missing-field-initializers",
                        "-Wno-unused-function", "-Wno-unused-variable", str(cpp), "-o", str(exe)], check=True)
        failed = [case for case in ("texture", "target") if subprocess.run([str(exe), case], timeout=30).returncode]
        if failed:
            raise SystemExit("timed-out read-back's source image: failed: " + ", ".join(failed))


if __name__ == "__main__":
    main()
