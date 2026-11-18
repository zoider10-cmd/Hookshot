"""The all-zero upload check reads only the guest memfd's pages that hold data (gpu/vk/vk_texture.cpp upload_all_zero,
gpu/vk/guest_holes.h; no game/GPU).

A hole of the guest window's memfd reads as zero, but a read of it through the window's shared mapping makes the kernel give
it a page: the 288 MB shadow map, never written, became guest memory at each Hyrule Field load. Cuts upload_all_zero out of
the source as it is, with stand-ins for the renderer around it over a real memfd window, and checks, each in a process of its
own (the function keeps its switch and the memfd in statics):
  allholes   a storage all holes: all zero, nothing read
  holes      a storage all holes but one page of zeros: all zero, and the memfd has no more pages than before
  data       a byte not zero past the holes: found, still no hole given a page
  tail       the storage's last byte not zero, in a size the check's threads don't divide evenly (each one's share a whole
             number of pages): found (the floor of the share left up to a byte a thread, at the end, unread)
  outside    the storage's pointer not in the guest window: read whole (the memfd grows)
  nofd       no guest memfd (-1): read whole
  pipe       the extent search failing (an fd lseek can't seek): read whole
  off        RX_VK_ZERO_HOLES=0: read whole, as before
Then guest_holes.h on its own (tests/test_guest_holes.cpp). The memfd parts are Linux's: skipped elsewhere.

python -I -B tests/test_guest_holes.py [--cxx g++]
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
ENV_ON_H = ROOT / "gpu" / "vk" / "compat" / "hookshot_env.h"

FIXTURE = r'''#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <thread>
#include <utility>
#include <vector>
#include <dlfcn.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>
#if __has_include("guest_holes.h")
#include "guest_holes.h"
#endif
/* (the renderer around upload_all_zero, stood in for) */
typedef uint32_t VkFlags;
enum VkImageType { VK_IMAGE_TYPE_2D = 1, VK_IMAGE_TYPE_3D = 2 };
enum VkFormat { VK_FORMAT_D16_UNORM = 124 };
enum VkImageLayout { VK_IMAGE_LAYOUT_GENERAL = 1 };
enum : VkFlags { VK_IMAGE_ASPECT_COLOR_BIT = 1, VK_IMAGE_ASPECT_DEPTH_BIT = 2, VK_IMAGE_ASPECT_STENCIL_BIT = 4 };
#define VK_REMAINING_MIP_LEVELS (~0U)
#define VK_REMAINING_ARRAY_LAYERS (~0U)
typedef struct VkImage_T* VkImage;
typedef struct VkCommandBuffer_T* VkCommandBuffer;
struct VkImageSubresourceRange { VkFlags aspectMask; uint32_t baseMipLevel, levelCount, baseArrayLayer, layerCount; };
struct VkClearDepthStencilValue { float depth; uint32_t stencil; };
union VkClearColorValue { float float32[4]; int32_t int32[4]; uint32_t uint32[4]; };
static int clears;
static void vkCmdClearDepthStencilImage(VkCommandBuffer, VkImage, VkImageLayout, const VkClearDepthStencilValue*, uint32_t,
                                        const VkImageSubresourceRange*) { clears++; }
static void vkCmdClearColorImage(VkCommandBuffer, VkImage, VkImageLayout, const VkClearColorValue*, uint32_t,
                                 const VkImageSubresourceRange*) { clears++; }
struct Texture {
    bool astc = false, bc = false, sparse = false;
    VkImage image = (VkImage)0x10;
    VkImageType type = VK_IMAGE_TYPE_2D;
    VkFormat format = VK_FORMAT_D16_UNORM;
    VkFlags aspect = VK_IMAGE_ASPECT_DEPTH_BIT;
    uint64_t gpu = 0;
    uint32_t width = 4096, height = 8192, nvn_format = 0x37;
};
using Ranges = std::vector<std::pair<uint64_t, uint64_t>>;
static bool is_bc(VkFormat) { return false; }
static bool is_astc(VkFormat) { return false; }
static bool memory_has_shadow(uint64_t, uint64_t) { return false; }
static void texture_resident_flush(Texture*) {}
static void helper_thread_start() {}   /* (a helper's start: on Linux, its thread's own nice value) */
static VkCommandBuffer upload_cmd() { return nullptr; }
static void checkpoint_mark(VkCommandBuffer, uint64_t, char) {}
static void logf(const char* fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    std::vprintf(fmt, ap);
    va_end(ap);
    std::printf("\n");
}
/* (the guest window: a memfd mapped shared, as host/hos_main.c has it; gpu addresses are offsets into it) */
static uint8_t* window;
static uint8_t* elsewhere;   /* (the same memfd mapped a second time: a pointer outside the window) */
static uint64_t window_size;
static int lookup_fd = -1;   /* (what hos_posix_guest_memfd gives) */
struct Host {
    uint8_t* (*guest_base)(void);
    uint64_t (*guest_size)(void);
    uint8_t* (*gpu_ptr)(uint64_t gpu, uint64_t* avail);
};
static uint8_t* host_base() { return window; }
static uint64_t host_size() { return window_size; }
static uint8_t* host_gpu_ptr(uint64_t gpu, uint64_t* avail) {
    *avail = window_size - gpu;
    return (elsewhere ? elsewhere : window) + gpu;
}
static Host host_v{host_base, host_size, host_gpu_ptr};
static Host* host = &host_v;
extern "C" __attribute__((visibility("default"))) int hos_posix_guest_memfd(void) { return lookup_fd; }

FUNCTION

static uint64_t backed(int fd) {
    struct stat s{};
    fstat(fd, &s);
    return (uint64_t)s.st_blocks * 512;
}
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); return 1; } } while (0)
int main(int argc, char** argv) {
    const std::string mode = argc > 1 ? argv[1] : "";
    /* (tail: 840 pages, divided by any thread count from 2 to 8, times 10, and a byte: share a whole number of pages, one over) */
    const uint64_t MB = 1ull << 20, total = mode == "tail" ? 840 * 4096 * 10 + 1 : 64 * MB, at = 128 * MB;
    window_size = 512 * MB;
    const int fd = (int)syscall(SYS_memfd_create, "upload-all-zero-test", 1u /* MFD_CLOEXEC */);
    CHECK(fd >= 0 && ftruncate(fd, (off_t)window_size) == 0);
    void* w = mmap(nullptr, window_size, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_NORESERVE, fd, 0);
    CHECK(w != MAP_FAILED);
    window = (uint8_t*)w;
    lookup_fd = fd;
    if (mode == "outside") {
        void* e = mmap(nullptr, window_size, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_NORESERVE, fd, 0);
        CHECK(e != MAP_FAILED);
        elsewhere = (uint8_t*)e;
    }
    int pipefd[2] = {-1, -1};
    if (mode == "nofd") lookup_fd = -1;
    if (mode == "pipe") {
        CHECK(pipe(pipefd) == 0);
        lookup_fd = pipefd[0];
    }
    if (mode != "allholes") std::memset(window + at + 8 * MB, 0, 4096);   /* (a page that holds data, all zero) */
    if (mode == "data") window[at + 48 * MB + 123] = 1;
    if (mode == "tail") window[at + total - 1] = 1;
    Texture tex;
    tex.gpu = at;
    const uint64_t before = backed(fd);
    const bool zero = upload_all_zero(tex, total, nullptr, false);
    const uint64_t after = backed(fd);
    std::printf("%s: %s, the memfd %llu KB backed before the check and %llu KB after\n", mode.c_str(),
                zero ? "all zero" : "not all zero", (unsigned long long)(before >> 10), (unsigned long long)(after >> 10));
    if (mode == "allholes" || mode == "holes" || mode == "data" || mode == "tail") {
        CHECK(zero == (mode != "data" && mode != "tail") && clears == (zero ? 1 : 0));
        CHECK(after == before);   /* (no hole read: the bug was every page of the storage backed here) */
    } else {
        CHECK(zero && clears == 1);
        CHECK(after >= before + total / 2);   /* (read whole: its holes given pages, as before) */
    }
    std::printf("PASS: %s\n", mode.c_str());
    return 0;
}
'''

MODES = (("allholes", {}), ("holes", {}), ("data", {}), ("tail", {}), ("outside", {}), ("nofd", {}), ("pipe", {}), ("off", {"RX_VK_ZERO_HOLES": "0"}))


def cut_upload_all_zero():
    src = (ROOT / "gpu/vk/vk_texture.cpp").read_text(encoding="utf-8")
    start = src.index("bool upload_all_zero(Texture& tex, uint64_t total, const Ranges* dirty, bool widened_format) {")
    end = src.index("\nbool upload_inner(Texture& tex, const Ranges* dirty) {", start)
    return src[start:end] + "\n"


def run_upload_all_zero(cxx, tmp):
    (tmp / "f.cpp").write_text(FIXTURE.replace("FUNCTION", cut_upload_all_zero()), encoding="utf-8")
    exe = tmp / "f"
    # (-rdynamic: the function finds hos_posix_guest_memfd with dlsym, as it finds the host's)
    subprocess.run([cxx, "-std=c++20", "-include", str(ENV_ON_H), "-I", str(ROOT / "gpu/vk"), "-Wall", "-Wextra",
                    "-Wno-unused-parameter", "-Wno-unused-function", "-Werror", "-pthread", "-rdynamic",
                    str(tmp / "f.cpp"), "-o", str(exe), "-ldl"], check=True)
    failed = []
    for mode, extra in MODES:
        env = {k: v for k, v in os.environ.items() if k not in ("RX_VK_ZERO_HOLES", "RX_VK_ZERO_UPLOAD")}
        env.update(extra)
        r = subprocess.run([str(exe), mode], env=env, capture_output=True, text=True)
        print(r.stdout.strip(), flush=True)
        if r.returncode:
            failed.append(mode)
            print(r.stderr.strip())
    if failed:
        raise SystemExit("FAIL: upload_all_zero: " + ", ".join(failed))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    cxx = shutil.which(args.cxx) or shutil.which("g++") or shutil.which("clang++")
    if not cxx:
        print("SKIP: no C++ compiler")
        return
    with tempfile.TemporaryDirectory(prefix="guest-holes-") as tmp:
        tmp = Path(tmp)
        if sys.platform.startswith("linux"):
            run_upload_all_zero(cxx, tmp)
        else:
            print("SKIP: upload_all_zero over a memfd (Linux's)")
        exe = tmp / ("guest-holes.exe" if os.name == "nt" else "guest-holes")
        subprocess.run([cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                        str(ROOT / "tests/test_guest_holes.cpp"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
