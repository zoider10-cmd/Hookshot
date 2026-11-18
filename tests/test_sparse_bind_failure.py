"""The sparse texture binds (sparse_take/sparse_flush/sparse_queue in vk_texture.cpp) cut out and run against a
stand-in driver whose vkQueueBindSparse or vkCreateFence fails: the blocks of a failed bind are marked unbound again
(so the next write queues them anew), the retry reuses their memory instead of taking more, and no bind is ever made
with a null fence."""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ['--cxx', '{cxx}', '--headers', '{vulkan_headers}']

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r"""
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#include <algorithm>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

template <class T> T handle(uintptr_t v) { return reinterpret_cast<T>(v); }
struct { VkDevice device = handle<VkDevice>(1); VkQueue queue = handle<VkQueue>(2); std::mutex present_mu; VkPhysicalDeviceProperties props{}; } dev;
struct Texture {
    uint64_t gpu = 0x1000;
    VkImage image = handle<VkImage>(3);
    uint32_t width = 64, height = 64, levels = 1, layers = 1;
    std::vector<std::vector<uint8_t>> tiles = std::vector<std::vector<uint8_t>>(1);
    std::vector<uint8_t> tail_bound = std::vector<uint8_t>(1);
    std::vector<VkDeviceMemory> sparse_chunks;
    VkDeviceSize chunk_used = 0;
    /* SPARSE FREE */
    VkSparseImageMemoryRequirements sparse_req{};
    uint32_t sparse_type = 0;
    VkDeviceSize sparse_align = 65536;
    uint64_t bytes = 0;
};
uint64_t total_bytes = 0;
void logf(const char*, ...) {}
bool env_on(const char*) { return false; }
void queue_flush_locked() {}

static bool fail_bind, fail_fence;
static int allocations, bind_calls;
VkResult vkAllocateMemory(VkDevice, const VkMemoryAllocateInfo*, const VkAllocationCallbacks*, VkDeviceMemory* m) {
    *m = handle<VkDeviceMemory>(100 + ++allocations); return VK_SUCCESS;
}
VkResult vkCreateFence(VkDevice, const VkFenceCreateInfo*, const VkAllocationCallbacks*, VkFence* f) {
    if (fail_fence) return VK_ERROR_OUT_OF_HOST_MEMORY;
    *f = handle<VkFence>(50); return VK_SUCCESS;
}
VkResult vkQueueWaitIdle(VkQueue) { return VK_SUCCESS; }
VkResult vkQueueBindSparse(VkQueue, uint32_t, const VkBindSparseInfo*, VkFence f) {
    assert(f != VK_NULL_HANDLE);   // (a bind through a null fence is never waited for)
    bind_calls++;
    return fail_bind ? VK_ERROR_OUT_OF_DEVICE_MEMORY : VK_SUCCESS;
}
VkResult vkWaitForFences(VkDevice, uint32_t, const VkFence*, VkBool32, uint64_t) { return VK_SUCCESS; }
VkResult vkResetFences(VkDevice, uint32_t, const VkFence*) { return VK_SUCCESS; }

/* ACTUAL */

int main(int argc, char** argv) {
    const std::string test = argc > 1 ? argv[1] : "";
    Texture tex;
    tex.sparse_req.formatProperties.imageGranularity = {16, 16, 1};
    tex.sparse_req.imageMipTailFirstLod = 1;
    std::lock_guard lk(sparse_mu);
    if (test == "healthy") {
        assert(sparse_queue(&tex, 0, 0, 0, 0, 16, 16)); assert(sparse_flush(&tex));
        assert(bind_calls == 1 && tex.tiles[0][0] == 1 && allocations == 1);
    } else if (test == "bind-fail") {
        fail_bind = true;
        assert(sparse_queue(&tex, 0, 0, 0, 0, 32, 16)); assert(!sparse_flush(&tex));
        assert(tex.tiles[0][0] == 0 && tex.tiles[0][1] == 0);   // (not bound: the next write queues them again)
        const VkDeviceSize used = tex.chunk_used;
        fail_bind = false;
        assert(sparse_queue(&tex, 0, 0, 0, 0, 32, 16)); assert(sparse_flush(&tex));
        assert(tex.tiles[0][0] == 1 && tex.tiles[0][1] == 1);
        assert(tex.chunk_used == used && allocations == 1);   // (the retry reused the failed bind's memory)
    } else if (test == "fence-fail") {
        fail_fence = true;
        assert(sparse_queue(&tex, 0, 0, 0, 0, 16, 16)); assert(!sparse_flush(&tex));
        assert(bind_calls == 0 && tex.tiles[0][0] == 0);
        fail_fence = false;
        assert(sparse_queue(&tex, 0, 0, 0, 0, 16, 16)); assert(sparse_flush(&tex));
        assert(bind_calls == 1 && tex.tiles[0][0] == 1 && allocations == 1);
    } else {
        return 2;
    }
    return 0;
}
"""


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=ROOT)
    p.add_argument("--headers", type=Path, required=True)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    texture = (a.source / "gpu/vk/vk_texture.cpp").read_text(encoding="utf-8")
    header = (a.source / "gpu/vk/vk_texture.h").read_text(encoding="utf-8")
    start = texture.index("std::mutex sparse_mu;")
    end = texture.index("} // namespace", start)
    fixture = FIXTURE.replace("/* ACTUAL */", texture[start:end])
    if "sparse_free;" in header:   # (the free list's declaration, as the header has it)
        lo = header.index("struct SparseFree")
        hi = header.index("\n", header.index("sparse_free;", lo))
        fixture = fixture.replace("/* SPARSE FREE */", header[lo:hi])
    cases = ["healthy", "bind-fail", "fence-fail"]
    with tempfile.TemporaryDirectory(prefix="sparse-bind-") as temp:
        cpp, exe = Path(temp) / "fixture.cpp", Path(temp) / "fixture.exe"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-missing-field-initializers",
                        "-Wno-unused-parameter", "-Wno-unused-function", "-Wno-unused-variable",
                        "-I" + str(a.headers), str(cpp), "-o", str(exe)], check=True)
        for case in cases:
            subprocess.run([str(exe), case], check=True, timeout=20)
    print(f"{len(cases)} sparse bind failure cases passed")


if __name__ == "__main__":
    main()
