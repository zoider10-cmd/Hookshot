"""AMD FSR 3.1's internal images are freed after the chain lets the engine go, without FSR 3.1 drawing again.

The chain lets an engine go when the Upscaler row leaves it (vk_temporal.cpp temporal_idle) or another engine is chosen,
and the engine's release must free what it made through temporal_later (vk_temporal.h TemporalEngine::release). FSR 3.1's
release retires its images until the GPU is past them and frees only those already complete; the rest are freed by its
next upscale or prepare. A player who tries FSR 3.1 and goes back to the game's own upscaler never runs either, so
without a later sweep the images (about 40-60 MB at the Steam Deck's 1280x800, hundreds at 4K) stay for the session.

The real Image, State, destroy_now, drop_image, free_dead, all_images and release of gpu/vk/vk_fsr3.cpp, with the
timeline and temporal_later stood in for: release while the GPU is behind, then the GPU past it and the chain's later
frees run, and every image and view is destroyed exactly once, none before the GPU was past it.
python -I -B tests/test_fsr3_release_frees.py --headers <Vulkan headers> [--cxx g++]
"""
RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{vulkan_headers}"]

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def block(source, marker):
    start = source.index(marker)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


PREFIX = r'''#include <vulkan/vulkan.h>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <map>
#include <utility>
#include <vector>
typedef struct VmaAllocation_T* VmaAllocation;
static void need(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL: %s\n", why); std::exit(1); }
}
static uint64_t gpu_done = 20, signaled = 20;
struct Bundle { uint64_t required = 0; int views = 0, images = 0; };
static std::map<uintptr_t, Bundle> bundles;   // (by image handle; a view is image * 16 + 1 + level)
struct { VkDevice device = VK_NULL_HANDLE; } dev;
VKAPI_ATTR void VKAPI_CALL vkDestroyImageView(VkDevice, VkImageView v, const VkAllocationCallbacks*) {
    Bundle& b = bundles[reinterpret_cast<uintptr_t>(v) / 16];
    need(gpu_done >= b.required, "a view destroyed while the GPU may still use it");
    need(!b.images, "a view destroyed after its image");
    b.views++;
}
namespace mkwvk {
static std::vector<std::function<void()>> laters;
void temporal_later(std::function<void()> f) { laters.push_back(std::move(f)); }
uint64_t vk_retirement_value() { return signaled + 1; }
uint64_t vk_timeline_completed() { return gpu_done; }
void destroy_image(VkImage image, VmaAllocation) {
    Bundle& b = bundles[reinterpret_cast<uintptr_t>(image)];
    need(gpu_done >= b.required, "an image destroyed while the GPU may still use it");
    need(!b.images, "an image destroyed twice");
    b.images++;
}
namespace fsr3 {
constexpr size_t kPassCount = 9;
namespace {
'''

MAIN = r'''
}   // namespace
}   // namespace fsr3
}   // namespace mkwvk

using namespace mkwvk::fsr3;
int main() {
    // (every image FSR 3.1 makes, as prepare leaves them: two views of the mipped ones' levels besides their own)
    uintptr_t next = 1, mipped = 0;
    size_t made = 0;
    for (Image* t : all_images()) {
        const uintptr_t id = next++;
        t->image = reinterpret_cast<VkImage>(id);
        t->memory = reinterpret_cast<VmaAllocation>(id);
        t->view = reinterpret_cast<VkImageView>(id * 16);
        if (t == &g.spd_mips) mipped = id, t->levels = {reinterpret_cast<VkImageView>(id * 16 + 1), reinterpret_cast<VkImageView>(id * 16 + 2)};
        bundles[id].required = signaled + 1;   // (the recording being made uses them, and its signal is not reached yet)
        made++;
    }
    need(made >= 20 && mipped, "the images all_images lists");
    // The chain lets FSR 3.1 go (the Upscaler row back to the game's own) while the GPU is behind the frame that used them
    release();
    for (const auto& [id, b] : bundles) need(!b.images && !b.views, "nothing freed before the GPU is past it");
    // Frames go on without FSR 3.1: the GPU passes the frame, and the chain runs its later frees a few frames on
    // (vk_temporal.cpp free_dead), as it does for every engine's
    for (int frame = 0; frame < 8; frame++) {
        signaled++, gpu_done = signaled;
        if (frame == 4) {
            std::vector<std::function<void()>> due;
            due.swap(mkwvk::laters);
            for (auto& f : due) f();
        }
    }
    for (const auto& [id, b] : bundles) {
        if (!b.images) std::fprintf(stderr, "image %llu not freed\n", (unsigned long long)id);
        need(b.images == 1, "every image FSR 3.1 made is freed once the chain let it go and the GPU is past it");
        need(b.views == (id == mipped ? 3 : 1), "each of its views destroyed once");
    }
    std::printf("FSR 3.1's %zu images freed after release without FSR 3.1 drawing again\n", made);
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    parser.add_argument("--headers", required=True)
    args = parser.parse_args()
    source = (ROOT / "gpu/vk/vk_fsr3.cpp").read_text(encoding="utf-8")
    parts = [
        block(source, "struct Pipeline {") + ";",
        block(source, "struct Image {") + ";",
        block(source, "struct State {") + ";",
        "State g;",
        block(source, "void destroy_now("),
        block(source, "void drop_image("),
        block(source, "void free_dead("),
        block(source, "std::vector<Image*> all_images()"),
        "}   // namespace",
        block(source, "void release() {"),
        "namespace {",
    ]
    code = PREFIX + "\n".join(parts) + MAIN
    with tempfile.TemporaryDirectory(prefix="fsr3-release-") as tmp:
        cpp = Path(tmp) / "fsr3_release.cpp"
        exe = Path(tmp) / ("fsr3_release" + (".exe" if os.name == "nt" else ".test"))
        cpp.write_text(code, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                        "-I" + args.headers, str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
