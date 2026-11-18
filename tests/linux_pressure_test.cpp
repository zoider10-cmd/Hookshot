// SPDX-License-Identifier: GPL-3.0-or-later
// Game-free tests for gpu/vk/linux_pressure.h and the post-precompile shader-module release / reload in
// gpu/vk/vk_progcache.cpp (compiled and run by tests/test_linux_pressure.py).
#include "../gpu/vk/linux_pressure.h"

#include <atomic>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#define CHECK(c) do { if (!(c)) { std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #c); std::exit(1); } } while (0)

#if !defined(_WIN32)
#define _fseeki64 fseeko
#define _ftelli64 ftello
#endif

// Minimal stand-ins so vk_progcache.cpp's real functions compile and run without a GPU or game.
using VkShaderStageFlagBits = uint32_t;
using VkShaderModule = uintptr_t;
using VkDescriptorSetLayout = uintptr_t;
using VkPipelineLayout = uintptr_t;
using VkDescriptorType = uint32_t;
using VkPipeline = uintptr_t;
using VkShaderStageFlags = uint32_t;
using VkPrimitiveTopology = uint32_t;

constexpr VkShaderModule VK_NULL_HANDLE = 0;
constexpr VkShaderStageFlagBits VK_SHADER_STAGE_VERTEX_BIT = 0x01;
constexpr VkShaderStageFlagBits VK_SHADER_STAGE_FRAGMENT_BIT = 0x10;
constexpr VkShaderStageFlagBits VK_SHADER_STAGE_COMPUTE_BIT = 0x20;
constexpr VkShaderStageFlagBits VK_SHADER_STAGE_TASK_BIT_EXT = 0x40;
constexpr VkShaderStageFlagBits VK_SHADER_STAGE_MESH_BIT_EXT = 0x80;
constexpr VkPrimitiveTopology VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST = 3;

namespace Shader {
namespace IR {
enum class Attribute : uint64_t { Position = 0 };
}
struct Descriptor {
    uint32_t count = 1;
};
struct Info {
    uint32_t tag = 0;
    std::vector<Descriptor> constant_buffer_descriptors;
    std::vector<Descriptor> storage_buffers_descriptors;
    std::vector<Descriptor> texture_buffer_descriptors;
    std::vector<Descriptor> image_buffer_descriptors;
    std::vector<Descriptor> texture_descriptors;
    std::vector<Descriptor> image_descriptors;
    std::map<IR::Attribute, IR::Attribute> legacy_stores_mapping;
    std::vector<std::vector<uint32_t>> handle_programs;
};
} // namespace Shader

namespace fallback_size {
inline uint32_t spirv_phis(const uint32_t* words, size_t n) { return n ? words[0] : 0; }
}

namespace mkwvk {

struct Dev {
    uintptr_t device = 1;
} dev;

struct UseCounters {
    int64_t loads = 0, load_ns = 0;
    bool background = false;
};
thread_local UseCounters use_counters;
std::atomic<bool> programs_in_play{false};
struct Census {
    std::atomic<int64_t> play_loads{0}, play_load_ns{0};
} census;

void logf(const char*, ...) {}

static size_t next_module_id = 0;
static size_t active_modules = 0;
static size_t make_module_calls = 0;
static uint64_t last_make_module_program = 0;
static bool fail_make_module = false;
static std::unordered_map<VkShaderModule, std::vector<uint32_t>> module_words;

void vkDestroyShaderModule(uintptr_t, VkShaderModule m, const void*) {
    const auto it = module_words.find(m);
    CHECK(it != module_words.end() && active_modules > 0);
    module_words.erase(it);
    --active_modules;
}

#include "cache_types.inc"

std::mutex disk_mu;
FILE* disk_in = nullptr;
std::string disk_path;
std::unordered_map<uint64_t, std::vector<DiskRecord>> disk_records;
std::unordered_map<uint64_t, std::vector<DiskRecord>> disk_taken;
FILE* disk_out = nullptr;
FILE* disk_idx = nullptr;
bool disk_listing = true;
bool disk_on = true;
bool disk_zstd = false;
std::atomic<int64_t> st_cache_hits{0};
constexpr uint32_t kCompressedKind = 16;
constexpr size_t kZstdHead = 20;
constexpr size_t kIdxEntry = 20;

std::mutex shader_mu;
std::unordered_map<uint64_t, std::vector<std::unique_ptr<Program>>> programs;

void disk_init() {}
void programs_load_wait(uint64_t) {}
void module_id_learned(uint64_t, uint64_t, VkShaderModule) {}
bool env_on(const char*) { return false; }
#define PROF_EXACT() ((void)0)

size_t ZSTD_compressBound(size_t src_size) { return src_size + 32; }
size_t ZSTD_compress(void* dst, size_t dst_cap, const void* src, size_t src_size, int) {
    if (dst_cap < src_size + 4) return ~size_t{0};
    auto* out = static_cast<uint8_t*>(dst);
    out[0] = 'Z'; out[1] = 'S'; out[2] = 'T'; out[3] = 'D';
    for (size_t i = 0; i < src_size; ++i) out[4 + i] = static_cast<const uint8_t*>(src)[i] ^ 0x5Au;
    return src_size + 4;
}
size_t ZSTD_decompress(void* dst, size_t dst_cap, const void* src, size_t src_size) {
    if (src_size < 4) return ~size_t{0};
    const auto* in = static_cast<const uint8_t*>(src);
    if (in[0] != 'Z' || in[1] != 'S' || in[2] != 'T' || in[3] != 'D' || dst_cap != src_size - 4) return ~size_t{0};
    auto* out = static_cast<uint8_t*>(dst);
    for (size_t i = 0; i < dst_cap; ++i) out[i] = in[4 + i] ^ 0x5Au;
    return dst_cap;
}
bool ZSTD_isError(size_t code) { return code == ~size_t{0}; }

VkShaderModule make_module(const std::vector<uint32_t>& spirv, uint64_t program = 0, bool* /*busy*/ = nullptr) {
    ++make_module_calls;
    last_make_module_program = program;
    if (fail_make_module || spirv.empty()) return VK_NULL_HANDLE;
    const VkShaderModule h = ++next_module_id;
    module_words[h] = spirv;
    ++active_modules;
    return h;
}

#include "cache_functions.inc"

} // namespace mkwvk

namespace {

constexpr uint64_t kMB = 1ull << 20;

void test_meminfo_and_shortfall(const std::string& dir) {
    using namespace linux_pressure;

    // 1. Default reserves and switch overrides
    CHECK(avail_reserve(nullptr) == 1536 * kMB);
    CHECK(avail_reserve("") == 1536 * kMB);
    CHECK(avail_reserve("0") == 0);
    CHECK(avail_reserve("2048") == 2048 * kMB);
    CHECK(commit_reserve(nullptr) == 2560 * kMB);
    CHECK(commit_reserve("0") == 0);
    CHECK(commit_reserve("3072") == 3072 * kMB);

    // 2. Parsing /proc/meminfo snapshots
    const char* deck_kokiri =
        "MemTotal:       15120384 kB\n"
        "MemFree:          210432 kB\n"
        "MemAvailable:     409600 kB\n"
        "Buffers:           12340 kB\n"
        "Cached:          1820416 kB\n"
        "SwapTotal:       8388604 kB\n"
        "SwapFree:        2048000 kB\n";
    uint64_t avail = 0, swap_free = 0;
    CHECK(parse_meminfo(deck_kokiri, &avail, &swap_free));
    CHECK(avail == 400 * kMB);
    CHECK(swap_free == 2000 * kMB);

    // On the Deck in Kokiri (400 MB MemAvailable, 2000 MB SwapFree):
    // - avail shortfall against 1536 MB is 1136 MB
    // - commit shortfall against 2560 MB is 2560 - 2400 = 160 MB
    // shortfall takes the larger (1136 MB), well before earlyoom's ~5% line
    CHECK(shortfall(avail, swap_free) == 1136 * kMB);

    // Swap nearly full (400 MB MemAvailable, 200 MB SwapFree -> 600 MB total free):
    // - avail shortfall is 1136 MB
    // - commit shortfall is 2560 - 600 = 1960 MB
    CHECK(shortfall(400 * kMB, 200 * kMB) == 1960 * kMB);

    // Healthy 32 GB Linux PC (18 GB MemAvailable, 8 GB SwapFree): 0 shortfall
    CHECK(shortfall(18432 * kMB, 8192 * kMB) == 0);

    // Reserves disabled via 0
    CHECK(shortfall(400 * kMB, 200 * kMB, 0, 2560 * kMB) == 1960 * kMB);
    CHECK(shortfall(400 * kMB, 200 * kMB, 1536 * kMB, 0) == 1136 * kMB);
    CHECK(shortfall(400 * kMB, 200 * kMB, 0, 0) == 0);

    // import_want subtracts dead_import_bytes already queued
    CHECK(import_want(1136 * kMB, 256 * kMB) == 880 * kMB);
    CHECK(import_want(256 * kMB, 512 * kMB) == 0);

    // episode_want: over one pressure episode, no more in all than its deepest shortfall
    CHECK(episode_want(880 * kMB, 1136 * kMB, 0) == 880 * kMB);
    CHECK(episode_want(880 * kMB, 1136 * kMB, 900 * kMB) == 236 * kMB);
    CHECK(episode_want(880 * kMB, 1136 * kMB, 1136 * kMB) == 0);
    CHECK(episode_want(880 * kMB, 1136 * kMB, 2000 * kMB) == 0);

    // Missing MemAvailable is rejected; missing SwapFree defaults to 0
    CHECK(!parse_meminfo("MemTotal: 16000000 kB\nSwapFree: 1024 kB\n", &avail, &swap_free));
    CHECK(parse_meminfo("MemAvailable: 1024000 kB\n", &avail, &swap_free));
    CHECK(avail == 1000 * kMB && swap_free == 0);

    // Swapless system (SwapTotal: 0 kB): has_swap is false, so commit_reserve (2560 MB) does not trigger at 2000 MB MemAvailable
    bool has_swap = true;
    CHECK(parse_meminfo("MemTotal: 16000000 kB\nMemAvailable: 2048000 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n",
                        &avail, &swap_free, nullptr, &has_swap));
    CHECK(!has_swap && avail == 2000 * kMB && swap_free == 0);
    CHECK(shortfall(avail, swap_free, kDefaultAvailReserve, kDefaultCommitReserve, has_swap) == 0);
    CHECK(shortfall(1000 * kMB, 0, kDefaultAvailReserve, kDefaultCommitReserve, has_swap) == 536 * kMB);

    // File read round-trip (including MemTotal)
    const std::string path = dir + "/meminfo.txt";
    FILE* f = std::fopen(path.c_str(), "wb");
    CHECK(f != nullptr);
    std::fwrite(deck_kokiri, 1, std::strlen(deck_kokiri), f);
    std::fclose(f);
    uint64_t total_ram = 0;
    CHECK(read_meminfo(&avail, &swap_free, path.c_str(), &total_ram, &has_swap));
    CHECK(has_swap && avail == 400 * kMB && swap_free == 2000 * kMB && total_ram == (15120384ull << 10));

    // 3. should_drop_modules: on by default for <= 20 GB RAM or active pressure, off on 32-64 GB desktops
    CHECK(should_drop_modules(15120 * kMB, 0, nullptr, nullptr));
    CHECK(should_drop_modules(20480 * kMB, 0, nullptr, nullptr));
    CHECK(!should_drop_modules(32768 * kMB, 0, nullptr, nullptr));
    CHECK(!should_drop_modules(65536 * kMB, 0, nullptr, nullptr));
    CHECK(should_drop_modules(32768 * kMB, 128 * kMB, nullptr, nullptr));   // active pressure at start
    CHECK(should_drop_modules(32768 * kMB, 0, nullptr, "1"));               // RX_VK_DROP_MODULES=1 forces drop
    CHECK(!should_drop_modules(15120 * kMB, 512 * kMB, "1", nullptr));      // RX_VK_KEEP_MODULES=1 keeps all
    CHECK(!should_drop_modules(15120 * kMB, 512 * kMB, nullptr, "0"));      // RX_VK_DROP_MODULES=0 keeps all

    // 4. PressureHold: hysteresis (256 MB clear margin), baseline hold (no per-frame ratchet), 512 MB floor, and stepped recovery
    PressureHold hold;
    // Healthy (1600 MB avail >= 1536 MB reserve, 4000 MB swap): inactive
    CHECK(hold.step(2600 * kMB, 1600 * kMB, 4000 * kMB) == UINT64_MAX && !hold.active);
    // Dip to 850 MB avail (686 MB short of 1536 MB): enters pressure, cuts 2600 - 686 = 1914 MB
    CHECK(hold.step(2600 * kMB, 850 * kMB, 6000 * kMB) == 1914 * kMB && hold.active);
    // Next frame: textures shrank to 2200 MB, MemAvailable is still 850 MB while VMA compaction works:
    // held budget stays at 1914 MB (does NOT ratchet down to 2200 - 686 = 1514 MB!)
    CHECK(hold.step(2200 * kMB, 850 * kMB, 6000 * kMB) == 1914 * kMB && hold.active);
    // Deeper dip to 600 MB avail (936 MB short): steps down from the entry baseline (2600 - 936 = 1664 MB)
    CHECK(hold.step(2000 * kMB, 600 * kMB, 6000 * kMB) == 1664 * kMB && hold.active);
    // Extreme shortfall (1500 MB avail short + swap empty -> 2400 MB short): clamped at the 512 MB floor
    CHECK(hold.step(2000 * kMB, 100 * kMB, 60 * kMB) == 512 * kMB && hold.active);
    // Recovery to 1600 MB avail (past 1536 MB reserve, but below 1536 + 256 = 1792 MB clear line): stays at 512 MB
    CHECK(hold.step(1800 * kMB, 1600 * kMB, 6000 * kMB) == 512 * kMB && hold.active);
    // Recovery to 1800 MB avail and 3000 MB swap (>= 1792 MB avail and >= 2816 MB commit): steps up by 256 MB per sample
    // until reaching baseline_total (2600 MB), then leaves pressure
    for (uint64_t expected = 768 * kMB; expected < 2600 * kMB; expected += 256 * kMB)
        CHECK(hold.step(1800 * kMB, 1800 * kMB, 3000 * kMB) == expected && hold.active);
    CHECK(hold.step(1800 * kMB, 1800 * kMB, 3000 * kMB) == UINT64_MAX && !hold.active);

    // Entering pressure when total_bytes < 512 MB still honors the 512 MB floor
    PressureHold low_entry;
    CHECK(low_entry.step(300 * kMB, 850 * kMB, 6000 * kMB) == 512 * kMB && low_entry.active);
}

void test_module_drop_and_reload(const std::string& dir) {
    using namespace mkwvk;
    const std::string path = dir + "/hookshot_programs.bin";
    disk_out = std::fopen(path.c_str(), "wb");
    CHECK(disk_out != nullptr);
    const uint64_t header[2] = {0x31505348u, 0x123456789abcdef0ull};
    std::fwrite(header, 8, 2, disk_out);
    std::fflush(disk_out);

    // Save 1: an ordinary graphics program (2 stages: vertex + fragment)
    Program gfx;
    gfx.key = 0x1001;
    gfx.stages.resize(2);
    gfx.stages[0].nvn_stage = 0;
    gfx.stages[0].vk_stage = VK_SHADER_STAGE_VERTEX_BIT;
    gfx.stages[1].nvn_stage = 1;
    gfx.stages[1].vk_stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    const std::vector<uint32_t> vs_spv(64, 0x11112222u), fs_spv(96, 0x33334444u);
    program_cache_save(gfx, {vs_spv, fs_spv});

    // Save 2: a mesh-fallback program (compute stage + vertex + fragment)
    Program fb;
    fb.key = 0x1002;
    fb.fallback = true;
    fb.stages.resize(3);
    fb.stages[0].nvn_stage = 0;
    fb.stages[0].vk_stage = VK_SHADER_STAGE_COMPUTE_BIT;
    fb.stages[1].nvn_stage = 0;
    fb.stages[1].vk_stage = VK_SHADER_STAGE_VERTEX_BIT;
    fb.stages[2].nvn_stage = 1;
    fb.stages[2].vk_stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    const std::vector<uint32_t> cs_spv(128, 0x55556666u);
    program_cache_save(fb, {cs_spv, vs_spv, fs_spv});

    // Save 3: a compute program
    Program comp;
    comp.key = 0x1003;
    comp.compute = true;
    comp.stages.resize(1);
    comp.stages[0].nvn_stage = 5;
    comp.stages[0].vk_stage = VK_SHADER_STAGE_COMPUTE_BIT;
    program_cache_save(comp, {cs_spv});

    std::fclose(disk_out);
    disk_out = nullptr;
    disk_path = path;
    disk_in = std::fopen(path.c_str(), "rb");
    CHECK(disk_in != nullptr);

    // Read all three into `programs`
    for (uint64_t k : {0x1001ull, 0x1002ull, 0x1003ull}) {
        program_cache_read(disk_in, &disk_mu, k, disk_records[k], programs[k]);
        CHECK(programs[k].size() == 1);
    }
    // 2 (gfx) + 3 (fb) + 1 (comp) = 6 active shader modules
    CHECK(active_modules == 6);
    CHECK(programs[0x1001][0]->stages[0].code_words == 64);
    CHECK(programs[0x1001][0]->stages[1].code_words == 96);
    CHECK(programs[0x1001][0]->stages[0].record_size != 0 &&
          programs[0x1001][0]->stages[0].record_at == programs[0x1001][0]->stages[1].record_at);
    // Nothing let go yet: no pipeline is refused, and nothing needs making again
    CHECK(!program_modules_dropped(*programs[0x1001][0]));
    CHECK(program_cache_complete_graphics(*programs[0x1001][0]));

    // With no program_cache_note_built (an un-noted variant, or when graphics pipelines are left to first draw) and before
    // compute pipelines are built: nothing is dropped (0 modules), so in-play first draws keep their modules in memory.
    CHECK(program_cache_drop_modules() == 0);
    CHECK(active_modules == 6);

    // When precompile_run builds fb's fallback compute pipeline and comp's compute pipeline, its graphics pipelines not noted:
    // only fb's compute stage (1) and comp's compute stage (1) drop (2 total), while fb's vertex + fragment modules and
    // gfx's vertex + fragment modules stay ready for their first draw in play!
    programs[0x1002][0]->compute_state.store(2, std::memory_order_release);
    programs[0x1003][0]->compute_pipeline = 0x999;
    CHECK(program_cache_drop_modules() == 2);
    CHECK(active_modules == 4);
    CHECK(programs[0x1002][0]->stages[0].module == VK_NULL_HANDLE);
    CHECK(programs[0x1002][0]->stages[1].module != VK_NULL_HANDLE);
    CHECK(programs[0x1002][0]->stages[2].module != VK_NULL_HANDLE);
    CHECK(programs[0x1003][0]->stages[0].module == VK_NULL_HANDLE);

    CHECK(!program_modules_dropped(*programs[0x1001][0]) && !program_modules_dropped(*programs[0x1002][0]));

    // When precompile_run built the noted graphics pipelines (program_cache_note_built on those variants):
    // gfx's 2 modules and fb's 2 graphics modules drop too (4 total):
    program_cache_note_built(*programs[0x1001][0]);
    program_cache_note_built(*programs[0x1002][0]);
    CHECK(program_cache_drop_modules() == 4);
    CHECK(active_modules == 0);
    CHECK(program_modules_dropped(*programs[0x1001][0]) && program_modules_dropped(*programs[0x1002][0]));

    // Another program of the same key and variant (one borrowed for the prepare) has its own modules: not dropped for it
    {
        Program copy;
        copy.key = programs[0x1001][0]->key;
        copy.variant = programs[0x1001][0]->variant;
        CHECK(!program_modules_dropped(copy));
        CHECK(program_cache_complete_graphics(copy));
        CHECK(active_modules == 0);
    }

    // When play needs to build a new graphics pipeline state for gfx or fb, program_cache_complete_graphics
    // reloads only the graphics stages (2 for gfx, 2 for fb — not fb's compute stage!):
    last_make_module_program = 0;
    CHECK(program_cache_complete_graphics(*programs[0x1001][0]));
    CHECK(last_make_module_program == 0x1001);
    CHECK(active_modules == 2);
    CHECK(module_words[programs[0x1001][0]->stages[0].module] == vs_spv);
    CHECK(module_words[programs[0x1001][0]->stages[1].module] == fs_spv);
    CHECK(!program_modules_dropped(*programs[0x1001][0]));

    last_make_module_program = 0;
    CHECK(program_cache_complete_graphics(*programs[0x1002][0]));
    CHECK(last_make_module_program == 0x1002);
    CHECK(active_modules == 4);
    CHECK(programs[0x1002][0]->stages[0].module == VK_NULL_HANDLE);
    CHECK(module_words[programs[0x1002][0]->stages[1].module] == vs_spv);
    CHECK(module_words[programs[0x1002][0]->stages[2].module] == fs_spv);

    // And dropping again releases those 4 remade modules cleanly:
    CHECK(program_cache_drop_modules() == 4);
    CHECK(active_modules == 0);
    CHECK(program_modules_dropped(*programs[0x1001][0]));
    CHECK(program_modules_dropped(*programs[0x1002][0]));

    // Failure case 1: make_module fails (e.g. out of memory). program_cache_complete_graphics returns false, marks
    // the remake failed in its own table (leaving p.failed == false so already-built pipelines keep drawing!), and a second call
    // returns false immediately without trying make_module again.
    fail_make_module = true;
    const size_t calls_before = make_module_calls;
    CHECK(!program_cache_complete_graphics(*programs[0x1001][0]));
    CHECK(program_modules_dropped(*programs[0x1001][0]) && !programs[0x1001][0]->failed);
    CHECK(make_module_calls == calls_before + 1);
    CHECK(!program_cache_complete_graphics(*programs[0x1001][0]));
    CHECK(make_module_calls == calls_before + 1);
    fail_make_module = false;

    // Failure case 2: a stale record head at record_at (its size does not match). Refused before make_module is called, and
    // marked failed to make again: a second call reads nothing
    for (Stage& st : programs[0x1002][0]->stages) st.record_size += 8;
    const size_t calls_before_stale = make_module_calls;
    CHECK(!program_cache_complete_graphics(*programs[0x1002][0]));
    CHECK(program_modules_dropped(*programs[0x1002][0]) && !programs[0x1002][0]->failed);
    CHECK(make_module_calls == calls_before_stale);
    CHECK(!program_cache_complete_graphics(*programs[0x1002][0]));
    CHECK(make_module_calls == calls_before_stale);

    std::fclose(disk_in);
    disk_in = nullptr;
    disk_path.clear();
}

} // namespace

int main(int argc, char** argv) {
    CHECK(argc == 2);
    const std::string dir = argv[1];
    test_meminfo_and_shortfall(dir);
    test_module_drop_and_reload(dir);
    std::printf("PASS: Linux memory pressure and shader module drop/reload\n");
    return 0;
}
