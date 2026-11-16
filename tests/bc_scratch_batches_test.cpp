// The two production loops that fill the BC3 scratch, run with a spy in place of Vulkan (tests/test_bc_scratch_layers.py
// cuts them out of gpu/vk/vk_texture.cpp into the marks below): texture_copy_into_bc() whole, and the lines of
// upload_astc_gpu() that form a run. The scratch has bc_layers() layers: no run may be larger, each must start at the
// scratch's first layer, and a request larger than the scratch must come out whole, in order, as several runs.
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <utility>
#include <vector>

typedef void* VkCommandBuffer;
typedef void* VkImage;
enum { VK_IMAGE_ASPECT_COLOR_BIT = 1, VK_IMAGE_LAYOUT_GENERAL = 1 };
struct VkImageSubresourceLayers { uint32_t aspectMask, mipLevel, baseArrayLayer, layerCount; };
struct VkOffset3D { int32_t x, y, z; };
struct VkExtent3D { uint32_t width, height, depth; };
struct VkImageCopy {
    VkImageSubresourceLayers srcSubresource;
    VkOffset3D srcOffset;
    VkImageSubresourceLayers dstSubresource;
    VkOffset3D dstOffset;
    VkExtent3D extent;
};
struct Texture {
    bool bc = false, astc = false, bc_resized = false;
    uint32_t width = 0, height = 0, skip = 0;
    uint64_t gpu = 0;
    VkImage image = nullptr;
    struct { uint32_t width = 0, height = 0; } d;
};

constexpr uint32_t kBcDim = 2048;
static uint32_t capacity = 1;
uint32_t bc_layers() { return capacity; }
static int dummy;
static VkImage bc_scratch = &dummy;
bool bc_ready() { return true; }
bool bc_scratch_layout(VkCommandBuffer, bool) { return true; }
void full_barrier(VkCommandBuffer) {}
template <class... A> void logf(const char*, A...) {}

struct Run { uint32_t src_layer, n, dst_layer, scratch_first; bool to_scratch, resized, encoded; };
static std::vector<Run> runs;
void vkCmdCopyImage(VkCommandBuffer, VkImage, int, VkImage dst, int, uint32_t, const VkImageCopy* cp) {
    runs.push_back({cp->srcSubresource.baseArrayLayer, cp->srcSubresource.layerCount, 0, cp->dstSubresource.baseArrayLayer,
                    dst == bc_scratch && cp->dstSubresource.layerCount == cp->srcSubresource.layerCount, false, false});
}
static void encoded(uint32_t n, uint32_t layer, bool resized) {
    if (runs.empty() || runs.back().encoded || runs.back().n != n) {
        std::fprintf(stderr, "FAIL an encode of %u layers with no copy of as many before it\n", n);
        std::exit(1);
    }
    runs.back().dst_layer = layer, runs.back().resized = resized, runs.back().encoded = true;
}
void bc_encode_into(VkCommandBuffer, uint32_t, uint32_t, uint32_t n, Texture&, uint32_t, uint32_t layer, int, int) { encoded(n, layer, false); }
void bc_encode_resized(VkCommandBuffer, uint32_t, uint32_t, uint32_t, uint32_t, uint32_t n, Texture&, uint32_t, uint32_t layer) {
    encoded(n, layer, true);
}

/* COPY */

/// upload_astc_gpu()'s runs over the layers it stages (dirty ones, in order): (index of the run's first, its count)
static std::vector<std::pair<size_t, uint32_t>> upload_runs(const std::vector<uint32_t>& layers) {
    std::vector<std::pair<size_t, uint32_t>> out;
    for (size_t k0 = 0; k0 < layers.size();) {
        /* RUN */
        out.push_back({k0, n});
        k0 = k1;
    }
    return out;
}

static int failures;
static void check(bool ok, const char* what) {
    std::printf("%s  %s\n", ok ? "ok  " : "FAIL", what);
    failures += !ok;
}

/// A copy of `layers` layers from source layer 3 into destination layer 10: the runs it made, checked against the scratch
static bool copy_ok(uint32_t cap, uint32_t layers, bool resized, std::vector<uint32_t> want) {
    capacity = cap;
    runs.clear();
    Texture src, dst;
    src.astc = true, src.image = &dummy;
    dst.bc = true, dst.bc_resized = resized, dst.width = dst.d.width = 512, dst.height = dst.d.height = 256;
    if (!texture_copy_into_bc(nullptr, &src, 0, 3, 0, 0, &dst, 0, 10, 0, 0, 512, 256, layers)) return false;
    uint32_t done = 0;
    size_t i = 0;
    for (const Run& r : runs) {
        if (!r.to_scratch || !r.encoded || r.scratch_first != 0 || r.n == 0 || r.n > cap || r.resized != resized) return false;
        if (r.src_layer != 3 + done || r.dst_layer != 10 + done) return false;   // (whole and in order: no layer left out or twice)
        if (i >= want.size() || want[i++] != r.n) return false;
        done += r.n;
    }
    return done == layers && i == want.size();
}

int main() {
    check(copy_ok(1, 9, false, {1, 1, 1, 1, 1, 1, 1, 1, 1}), "a copy of 9 layers into a one-layer scratch: 9 runs of one, in order");
    check(copy_ok(4, 9, false, {4, 4, 1}), "into a 4-layer scratch: 4, 4 and a last run of 1");
    check(copy_ok(8, 9, false, {8, 1}), "into an 8-layer scratch: 8 and 1, as before the change");
    check(copy_ok(8, 8, false, {8}), "a copy the scratch holds whole is one run");
    check(copy_ok(1, 1, false, {1}), "a single layer is one run");
    check(copy_ok(1, 3, true, {1, 1, 1}) && copy_ok(4, 6, true, {4, 2}), "a resized BC3 texture: the same runs, through the second scratch");
    {
        capacity = 1;
        runs.clear();
        Texture src, dst;
        src.astc = true, dst.bc = true, dst.width = dst.d.width = 512, dst.height = dst.d.height = 256;
        const bool odd = texture_copy_into_bc(nullptr, &src, 0, 0, 0, 0, &dst, 0, 0, 2, 0, 512, 256, 4);
        const bool wide = texture_copy_into_bc(nullptr, &src, 0, 0, 0, 0, &dst, 0, 0, 0, 0, kBcDim + 4, 256, 4);
        check(!odd && !wide && runs.empty(), "a copy the scratch cannot take (off the block grid, wider than it) writes nothing into it");
    }
    using Runs = std::vector<std::pair<size_t, uint32_t>>;
    const std::vector<uint32_t> dirty{0, 1, 2, 5, 6, 9};   // (an array's dirty layers: runs end at the gaps)
    capacity = 1;
    check(upload_runs(dirty) == Runs{{0, 1}, {1, 1}, {2, 1}, {3, 1}, {4, 1}, {5, 1}}, "an upload into a one-layer scratch: one layer a run");
    capacity = 2;
    check(upload_runs(dirty) == Runs{{0, 2}, {2, 1}, {3, 2}, {5, 1}}, "into a 2-layer scratch: runs of at most 2, ended by a gap");
    capacity = 8;
    check(upload_runs(dirty) == Runs{{0, 3}, {3, 2}, {5, 1}}, "into an 8-layer scratch: the gaps alone end the runs");
    capacity = 4;
    check(upload_runs({7, 8, 9, 10, 11, 12, 13, 14, 15}) == Runs{{0, 4}, {4, 4}, {8, 1}}, "9 layers in a row into a 4-layer scratch: 4, 4 and 1");
    if (failures) return 1;
    std::printf("PASS: no run is larger than the scratch, and a larger request comes out whole\n");
    return 0;
}
