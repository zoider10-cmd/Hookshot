#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <condition_variable>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <exception>
#include <memory>
#include <mutex>
#include <new>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace fixture {
enum Cache { None = -1, Owner, Seen, Mine, Failure, Alias, Retire };
std::atomic<int> fail_cache{None};
std::atomic<unsigned> allocation_faults{0};
template<class T, int Tag> struct FaultAllocator : std::allocator<T> {
    using value_type = T;
    FaultAllocator() = default;
    template<class U> FaultAllocator(const FaultAllocator<U, Tag>&) {}
    template<class U> struct rebind { using other = FaultAllocator<U, Tag>; };
    T* allocate(size_t n) {
        int expected = Tag;
        if (fail_cache.compare_exchange_strong(expected, None)) { allocation_faults++; throw std::bad_alloc(); }
        return std::allocator<T>{}.allocate(n);
    }
};
template<class K, class V, int Tag, class H = std::hash<K>> using FaultMap = std::unordered_map<K, V, H, std::equal_to<K>, FaultAllocator<std::pair<const K, V>, Tag>>;
template<class K, int Tag> using FaultSet = std::unordered_set<K, std::hash<K>, std::equal_to<K>, FaultAllocator<K, Tag>>;
template<class T, int Tag> using FaultVector = std::vector<T, FaultAllocator<T, Tag>>;
/* PARAMS */
/* ENUMS */
struct {
    VkDevice device{}; VkPhysicalDeviceProperties props{}; VkPhysicalDeviceFeatures features{};
    bool custom_border_color = false;
} dev;
std::mutex replay_mu;
struct ParLock { std::lock_guard<std::mutex> lock; ParLock() : lock(replay_mu) {} };
std::atomic<uint64_t> generation{1};   // (sampler_registrations_generation: a registration, the rows, or a retirement moved it)
uint64_t frame_no = 1;
unsigned creates = 0, destroyed = 0;
VkResult create_result = VK_SUCCESS;
bool garbage = false, arm_owner_commit = false, arm_failure_commit = false, cache_off = false;
bool lod_per_id = false;   // (the limit cases: each id its own sampler, by its base level)
std::string policy;
std::string descriptor_policy;
float registration_lod_max = 8;
struct Saved {
    VkSamplerCreateInfo ci{};
    bool custom = false, reduced = false;
    VkSamplerReductionMode reduction{};
    float border[4]{};
};
std::unordered_map<VkSampler, Saved> live;
uint32_t row_times = 0;   // (the Anisotropic filtering row as vk_draw.cpp anisotropy_row reads it: 0 the game's own)
uint32_t anisotropy_row() { return row_times; }
float up_bias = 0;   // (vk_draw.cpp upscale_lod_bias: DLSS or FSR drawing the 3D smaller than the game's 3/4)
float upscale_lod_bias() { return up_bias; }
uint64_t mix(uint64_t a, uint64_t b) { return (a ^ b) * 0x9e3779b97f4a7c15ull; }
uint64_t texture_frame_no() { return frame_no; }
bool sampler_cache_on() { return !cache_off; }
uint64_t sampler_registrations_generation() { return generation; }
uint32_t sampler_slot_version(int) { return (uint32_t)generation; }
bool sampler_of(int id, nvn_samp_par* p) {
    if (id < 0) return false;
    *p = {};
    p->minf = NVN_MIN_FILTER_LINEAR_MIPMAP_LINEAR; p->magf = NVN_MAG_FILTER_LINEAR;
    p->aniso = 1; p->lod_max = registration_lod_max; p->lod_bias = id * 0.25f;
    if (policy == "nearest" || policy == "force-linear" || policy.find("compare") == 0) p->minf = NVN_MIN_FILTER_NEAREST, p->magf = NVN_MAG_FILTER_NEAREST;
    if (policy == "linear" || policy == "anisotropy-no-mips") p->minf = NVN_MIN_FILTER_LINEAR;
    // (linear, mips nearest between levels: a value none of the names the code uses has, as NVN_MIN_FILTER_LINEAR_MIPMAP_NEAREST)
    if (policy == "anisotropy-nearest-mip") p->minf = 0x7E;
    if (policy == "compare-explicit") p->cmp_mode = 1, p->cmp_func = 1;
    if (policy == "custom-border" || policy == "custom-reduction") { p->border[0] = 0.25f; p->border[1] = 0.5f; p->border[2] = 0.75f; p->border[3] = 1; }
    if (policy == "standard-border") std::fill(std::begin(p->border), std::end(p->border), 1.0f);
    if (policy == "reduction" || policy == "compare-reduction" || policy == "custom-reduction") p->reduction = 1;
    if (policy == "wrap") p->ws = NVN_WRAP_MODE_REPEAT, p->wt = NVN_WRAP_MODE_MIRRORED_REPEAT, p->wr = NVN_WRAP_MODE_CLAMP_TO_BORDER;
    if (policy == "lod-clamp") p->lod_bias = 100, p->lod_min = -3, p->lod_max = -1;
    if (policy == "upscale-bias" || policy == "upscale-bias-change") p->lod_bias = -0.5f;   // (the game's upscaled materials)
    if (policy == "limit-reuse") {   // (keys apart only in what no sample reaches share a sampler; 3, 5 and 6 sample otherwise)
        p->minf = NVN_MIN_FILTER_NEAREST, p->magf = NVN_MAG_FILTER_NEAREST, p->lod_bias = 0;
        if (id == 1) p->border[0] = 0.5f, p->border[3] = 1;   // (a custom border colour no address mode clamps to)
        if (id == 2) p->aniso = 4;      // (anisotropy on a device without anisotropic filtering: Vulkan ignores it)
        if (id == 3) p->cmp_func = 3;   // (a comparison the sampler is not enabled for: kept, a driver may compare anyway)
        if (id == 4) p->lod_max = 2;    // (no mip filter: the base level only, whatever the range)
        if (id >= 5) p->ws = NVN_WRAP_MODE_CLAMP_TO_BORDER, p->border[0] = id == 5 ? 0.5f : 0.25f, p->border[3] = 1;
    }
    if (lod_per_id) p->lod_bias = 0, p->lod_min = id / 64.0f;
    return true;
}
const char* getenv(const char* name) {
    if (!std::strcmp(name, "RX_VK_DESC_DELTA") && descriptor_policy == "descriptor-no-delta") return "0";
    if (!std::strcmp(name, "RX_VK_PUSH_ALL") && descriptor_policy == "descriptor-whole") return "1";
    if (!std::strcmp(name, "RX_VK_SAMPLER_CACHE") && cache_off) return "0";
    if (!std::strcmp(name, "RX_VK_SHADOW_PCF") && policy == "compare-pcf-off") return "0";
    if (!std::strcmp(name, "RX_VK_ANISO") && policy == "anisotropy") return "16";
    if (!std::strcmp(name, "RX_VK_ANISO") && policy == "anisotropy-env-off") return "0";
    if (!std::strcmp(name, "RX_VK_FORCE_LINEAR") && policy == "force-linear") return "1";
    return nullptr;
}
bool env_on(const char* name) { const char* v = getenv(name); return v && !env_value_off(v); }   // (the switches through the stand-in)
void logf(const char*, ...) {}
// (sampler reuse) The recordings' timeline: the value the GPU reached, and the one the recording being made will signal, which
// vk_replay.cpp's vk_retirement_value gives (a signal after every recording made so far)
uint64_t gpu_done = 0, next_signal = 1;
uint64_t vk_timeline_completed() { return gpu_done; }
uint64_t vk_retirement_value() { return next_signal; }
void samplers_changed() { generation++; }   // (vk_bank.cpp: moves sampler_registrations_generation)
unsigned limit_failures = 0;   // (creations the driver refused for its maxSamplerAllocationCount, as NVIDIA's does)
std::unordered_map<VkSampler, uint64_t> last_use;   // (the recording that last took each sampler, by use() below)
VkResult vkCreateSampler(VkDevice, const VkSamplerCreateInfo* ci, const VkAllocationCallbacks*, VkSampler* out) {
    creates++;
    *out = garbage ? reinterpret_cast<VkSampler>(uintptr_t(0xdead)) : VK_NULL_HANDLE;
    const uint32_t most = dev.props.limits.maxSamplerAllocationCount;   // (0: the existing cases' device, no limit modelled)
    if (most && live.size() >= most) { limit_failures++; return VK_ERROR_OUT_OF_DEVICE_MEMORY; }
    if (create_result != VK_SUCCESS) {
        if (arm_failure_commit) { arm_failure_commit = false; fail_cache = Failure; }
        return create_result;
    }
    *out = reinterpret_cast<VkSampler>(uintptr_t(100 + creates));
    Saved saved; saved.ci = *ci; saved.ci.pNext = nullptr;
    for (auto* next = static_cast<const VkBaseInStructure*>(ci->pNext); next; next = next->pNext) {
        if (next->sType == VK_STRUCTURE_TYPE_SAMPLER_CUSTOM_BORDER_COLOR_CREATE_INFO_EXT) {
            auto* border = reinterpret_cast<const VkSamplerCustomBorderColorCreateInfoEXT*>(next);
            saved.custom = true; std::copy(std::begin(border->customBorderColor.float32), std::end(border->customBorderColor.float32), saved.border);
        }
        if (next->sType == VK_STRUCTURE_TYPE_SAMPLER_REDUCTION_MODE_CREATE_INFO) {
            saved.reduced = true; saved.reduction = reinterpret_cast<const VkSamplerReductionModeCreateInfo*>(next)->reductionMode;
        }
    }
    live.emplace(*out, saved);
    // Arm after the resource exists: target the operation, not an STL-dependent nth allocation.
    if (arm_owner_commit) { arm_owner_commit = false; fail_cache = Owner; }
    return VK_SUCCESS;
}
void vkDestroySampler(VkDevice, VkSampler sampler, const VkAllocationCallbacks*) {
    if (!sampler) return;   // (Vulkan permits null destruction; a non-null error output is still undefined)
    if (auto u = last_use.find(sampler); u != last_use.end()) {   // (destroyed only once the GPU is past every recording that took it)
        assert(u->second <= gpu_done); last_use.erase(u);
    }
    assert(live.erase(sampler) == 1); destroyed++;   // (not undefined error output or an already-owned sampler)
}
/* ACTUAL */

struct Program {
    uint64_t key = 0; bool push = true; VkPipelineLayout layout{}; VkDescriptorSetLayout set_layout{};
    std::vector<VkDescriptorType> binding_types; std::vector<uint32_t> binding_words;
};
/* WRITER */
DescWriter descriptor_writes;
DescWriter& dw() { return descriptor_writes; }
// (the template: the policies descriptor-template and descriptor-no-delta have one, the others push and update by writes)
VkDescriptorUpdateTemplate desc_template(const Program&, VkPipelineBindPoint) {
    return descriptor_policy == "descriptor-template" || descriptor_policy == "descriptor-no-delta" ||
                   descriptor_policy == "descriptor-pool-template"
               ? reinterpret_cast<VkDescriptorUpdateTemplate>(uintptr_t(30)) : VK_NULL_HANDLE;
}
const Program* tested = nullptr;   // (what a template call's data is laid out by)
struct Pushed;
std::array<Pushed, 2>& pushed();
struct Recording { VkDescriptorPool pool{}; std::vector<VkDescriptorPool> extra; } recording;
Recording* cur = &recording;
std::atomic<uint64_t> pools_extra{0};
bool g_fine = false;
enum { FC_PUSH_FULL, FC_PUSH_WRITES, FC_PUSH_DESCS, FC_PUSH_DELTA, FC_POOL_SETS, FC_POOL_DESCS, FC_PUSH_TEMPLATE, FC_PUSH_NONE };
int64_t fine_n[8]{};
#define FINE_SCOPE(x) (void)0
#define FINE_N(x, n) (void)0
unsigned descriptor_allocs = 0, descriptor_updates = 0, descriptor_binds = 0, descriptor_pushes = 0;
void check_writes(uint32_t n, const VkWriteDescriptorSet* writes) {
    for (uint32_t i = 0; i < n; i++)
        if (writes[i].descriptorType == VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER)
            for (uint32_t k = 0; k < writes[i].descriptorCount; k++)
                assert(live.count(writes[i].pImageInfo[k].sampler));
}
void vkCmdPushDescriptorSetKHR(VkCommandBuffer, VkPipelineBindPoint, VkPipelineLayout, uint32_t, uint32_t n, const VkWriteDescriptorSet* writes) {
    check_writes(n, writes); descriptor_pushes++;
}
void check_data(const void* data) {   // (a template's: every combined image sampler's sampler, by the program's bindings)
    const uint64_t* d = static_cast<const uint64_t*>(data);
    for (size_t b = 0; b < tested->binding_types.size(); b++)
        if (tested->binding_types[b] == VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER)
            for (uint32_t i = tested->binding_words[b]; i < tested->binding_words[b + 1]; i += 3)
                assert(live.count(reinterpret_cast<VkSampler>(d[i])));
}
void vkCmdPushDescriptorSetWithTemplateKHR(VkCommandBuffer, VkDescriptorUpdateTemplate, VkPipelineLayout, uint32_t, const void* data) {
    check_data(data); descriptor_pushes++;
}
void vkUpdateDescriptorSetWithTemplate(VkDevice, VkDescriptorSet, VkDescriptorUpdateTemplate, const void* data) {
    check_data(data); descriptor_updates++;
}
VkDescriptorPool make_pool() { return reinterpret_cast<VkDescriptorPool>(uintptr_t(11)); }
void vkDestroyDescriptorPool(VkDevice, VkDescriptorPool pool, const VkAllocationCallbacks*) { assert(pool); }
VkResult vkAllocateDescriptorSets(VkDevice, const VkDescriptorSetAllocateInfo*, VkDescriptorSet* out) {
    descriptor_allocs++; *out = reinterpret_cast<VkDescriptorSet>(uintptr_t(12)); return VK_SUCCESS;
}
void vkUpdateDescriptorSets(VkDevice, uint32_t n, const VkWriteDescriptorSet* writes, uint32_t, const VkCopyDescriptorSet*) {
    check_writes(n, writes); descriptor_updates++;
}
void vkCmdBindDescriptorSets(VkCommandBuffer, VkPipelineBindPoint, VkPipelineLayout, uint32_t, uint32_t, const VkDescriptorSet*, uint32_t, const uint32_t*) {
    descriptor_binds++;
}
bool ub_snapshot_wanted() { return false; }   // (no uniform snapshot: bind_descriptors pushes only the writes that changed)
int ub_snap_dedup_mode() { return 1; }
/* DESCRIPTORS */
std::array<Pushed, 2>& pushed() { static std::array<Pushed, 2> state; return state; }

std::string route;
VkSampler get(int id = 0, bool compare = false) {
    return route == "make" ? sampler_make(id, compare) : sampler_for(id, compare);
}
void valid(VkSampler sampler) { assert(sampler && live.count(sampler)); }
void retry(const std::string& test) {
    create_result = test == "host-oom" ? VK_ERROR_OUT_OF_HOST_MEMORY : test == "unknown" ? VK_ERROR_UNKNOWN : VK_ERROR_OUT_OF_DEVICE_MEMORY;
    garbage = test == "error-output";
    assert(!get()); assert(!get()); assert(creates == 1 && live.empty() && destroyed == 0);
    create_result = VK_SUCCESS;
    assert(!get()); assert(creates == 1);   // (bounded until a later present)
    frame_no++;
    if (test == "generation-retry") generation++;
    VkSampler next{};
    if (test == "thread-retry") { std::thread worker([&] { next = get(); }); worker.join(); }
    else next = get();
    valid(next); assert(creates == 2 && get() == next);
}
// (sampler reuse) A recording thread that lives through a whole case, as a parallel replay's segment workers do: its own tables
// (sampler_for's by id, sampler_make's mine) stay from one recording to the next
struct Worker {
    std::mutex m;
    std::condition_variable cv;
    std::function<void()> job;
    bool busy = false, quit = false;
    std::thread t{[this] {
        std::unique_lock l(m);
        for (;;) {
            cv.wait(l, [this] { return busy || quit; });
            if (quit) return;
            l.unlock(); job(); l.lock();
            busy = false; cv.notify_all();
        }
    }};
    void start(std::function<void()> f) { { std::lock_guard l(m); job = std::move(f); busy = true; } cv.notify_all(); }
    void join() { std::unique_lock l(m); cv.wait(l, [this] { return !busy; }); }
    ~Worker() { { std::lock_guard l(m); quit = true; } cv.notify_all(); t.join(); }
};
// A draw's sampler for id in the recording that will signal next_signal: checked under the replay's lock (the fake driver's tables
// change under it), its own key's (lod_per_id), and noted as used by that recording
VkSampler use(int id) {
    const VkSampler s = get(id);
    std::lock_guard g(replay_mu);
    valid(s); assert(live.at(s).ci.minLod == id / 64.0f);
    last_use[s] = next_signal;
    return s;
}
// The limit cases: a driver that makes at most 80 samplers, as NVIDIA's makes about 4000 (vkCreateSampler fails past it). The
// renderer's room is 60 of them (80 less a quarter for its other samplers), retiring from 45. vkDestroySampler above checks no
// sampler goes before the GPU is past the last recording that took it
bool limit_case(const std::string& test) {
    if (test == "limit") {   // (300 recordings on two threads, each drawing with 10 samplers every recording uses and 20 of a window
        // that moves 5 a recording: 1525 in all. The GPU 2 recordings behind)
        lod_per_id = true; dev.props.limits.maxSamplerAllocationCount = 80;
        Worker worker;
        for (uint64_t r = 0; r < 300; r++) {
            next_signal = r + 1, gpu_done = r ? r - 1 : 0;
            const auto draws = [r] {
                for (int id = 0; id < 10; id++) use(id);
                for (int id = 100 + 5 * (int)r; id < 120 + 5 * (int)r; id++) use(id);
            };
            worker.start(draws); draws(); worker.join();
            frame_no++;   // (a present)
        }
        // (each made once: none retired while recordings still drew with it, the 10 of every recording kept throughout)
        assert(!limit_failures && creates == 1525 && live.size() <= 60 && destroyed == creates - live.size());
        return true;
    }
    if (test == "limit-full") {   // (the GPU stopped: every sampler the room holds may still be its own)
        lod_per_id = true; dev.props.limits.maxSamplerAllocationCount = 80;
        std::vector<VkSampler> first;
        for (int id = 0; id < 60; id++) first.push_back(use(id));   // (45 made, then 15 more, each retiring the least recently used)
        assert(creates == 60 && destroyed == 0 && !limit_failures);
        assert(!get(60) && !get(60) && creates == 60 && !limit_failures);   // (none made past the room: the draw waits, as for a failure)
        gpu_done = 1, next_signal = 2; frame_no++;   // (the GPU past that recording, and a present)
        use(60);
        assert(destroyed == 15 && creates == 61 && use(59) == first[59]);   // (those retired were 0-14, the least recently used)
        assert(use(0) != first[0] && creates == 62);   // (a retired one's key made anew)
        return true;
    }
    if (test == "limit-reuse") {   // (keys apart only in what no sample reaches share one sampler; the others do not)
        policy = test; dev.features.samplerAnisotropy = VK_FALSE;
        const VkSampler s0 = get(0); valid(s0);
        assert(get(1) == s0 && get(2) == s0 && get(4) == s0 && creates == 1);
        const VkSampler s3 = get(3), s5 = get(5), s6 = get(6);
        valid(s3); valid(s5); valid(s6);
        assert(s3 != s0 && s5 != s0 && s6 != s0 && s5 != s6 && creates == 4 && live.size() == 4);
        assert(!live.at(s3).ci.compareEnable && live.at(s3).ci.compareOp == VK_COMPARE_OP_EQUAL);
        assert(live.at(s5).custom && live.at(s5).border[0] == 0.5f && live.at(s6).border[0] == 0.25f);
        return true;
    }
    if (test == "limit-alias-commit") {   // (the keys' table could not take a key: its sampler is found again by what it samples)
        fail_cache = Alias; const VkSampler s = get(); valid(s);
        assert(allocation_faults == 1 && get() == s && creates == 1 && destroyed == 0);
        return true;
    }
    if (test == "limit-retire-commit") {   // (no room to note a retirement: that sampler stays made, none lost or destroyed early)
        lod_per_id = true; dev.props.limits.maxSamplerAllocationCount = 80;
        for (int id = 0; id < 45; id++) use(id);
        fail_cache = Retire; use(45);
        assert(allocation_faults == 1 && creates == 46 && destroyed == 0 && live.size() == 46);
        use(46); assert(creates == 47 && destroyed == 0);   // (back to 45 made: 0 and 1 retired)
        gpu_done = 1, next_signal = 2; frame_no++;
        use(47); assert(destroyed == 2 && creates == 48);
        return true;
    }
    return false;
}
void run(const std::string& test) {
    cache_off = route == "cache-off";
    dev.props.limits.maxSamplerLodBias = 16; dev.props.limits.maxSamplerAnisotropy = 8;
    dev.features.samplerAnisotropy = VK_TRUE; dev.custom_border_color = true;
    if (limit_case(test)) return;
    if (test.find("descriptor-") == 0) {
        descriptor_policy = test;
        recording.pool = make_pool();   // A live recording already owns its initial pool before binding.
        Program p; p.push = test.find("descriptor-pool") != 0;
        p.layout = reinterpret_cast<VkPipelineLayout>(uintptr_t(20));
        p.binding_types = {VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER}, p.binding_words = {0, 6};
        tested = &p;
        const auto bp = test == "descriptor-compute" ? VK_PIPELINE_BIND_POINT_COMPUTE : VK_PIPELINE_BIND_POINT_GRAPHICS;
        const auto cmd = reinterpret_cast<VkCommandBuffer>(uintptr_t(21));
        auto first = get(); valid(first);
        DescWriter& d = dw();
        d.reset(); d.prog = &p;
        d.put_image(first, VK_NULL_HANDLE); d.put_image(first, VK_NULL_HANDLE);
        // (the two descriptors' samplers, words 0 and 3 of the built words)
        struct Images {
            DescWriter& d;
            struct Ref { uint64_t& w; VkSampler sampler; Ref& operator=(VkSampler s) { w = (uint64_t)s; sampler = s; return *this; } };
            Ref operator[](int i) { Ref r{d.data[3 * i], reinterpret_cast<VkSampler>(d.data[3 * i])}; return r; }
        } images{d};
        create_result = VK_ERROR_OUT_OF_DEVICE_MEMORY; images[1] = get(1);
        assert(!images[1].sampler && !bind_descriptors(cmd, bp, p));
        assert(!descriptor_allocs && !descriptor_updates && !descriptor_binds && !descriptor_pushes);
        create_result = VK_SUCCESS; frame_no++; images[1] = get(1); valid(images[1].sampler);
        assert(bind_descriptors(cmd, bp, p));
        auto before = pushed()[bp == VK_PIPELINE_BIND_POINT_COMPUTE];
        const auto allocs = descriptor_allocs, updates = descriptor_updates, binds = descriptor_binds, pushes = descriptor_pushes;
        create_result = VK_ERROR_OUT_OF_DEVICE_MEMORY;
        images[1] = get(2); assert(!images[1].sampler);
        assert(!bind_descriptors(cmd, bp, p));
        assert(descriptor_allocs == allocs && descriptor_updates == updates && descriptor_binds == binds && descriptor_pushes == pushes);
        const auto& after = pushed()[bp == VK_PIPELINE_BIND_POINT_COMPUTE];
        assert(after.cmd == before.cmd && after.layout == before.layout && after.words == before.words);
        create_result = VK_SUCCESS; frame_no++; images[1] = get(2); valid(images[1].sampler);
        assert(bind_descriptors(cmd, bp, p));
        assert(p.push ? descriptor_pushes == pushes + 1 : descriptor_updates == updates + 1 && descriptor_binds == binds + 1);
        // Storage images do not consume a sampler: their null sampler remains legal.
        p.binding_types[0] = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; images[0] = VK_NULL_HANDLE; images[1] = VK_NULL_HANDLE;
        assert(bind_descriptors(cmd, bp, p));
        // (and a build that is not this program's layout is left out, nothing pushed or bound)
        d.data.pop_back();
        const auto pushes2 = descriptor_pushes, updates2 = descriptor_updates;
        assert(!bind_descriptors(cmd, bp, p) && descriptor_pushes == pushes2 && descriptor_updates == updates2);
        return;
    }
    if (test == "host-oom" || test == "device-oom" || test == "unknown" || test == "error-output" ||
        test == "generation-retry" || test == "thread-retry") { retry(test); return; }
    if (test == "independent") {
        create_result = VK_ERROR_OUT_OF_HOST_MEMORY; assert(!get()); create_result = VK_SUCCESS;
        auto second = get(1); valid(second); assert(creates == 2 && !get() && get(1) == second); return;
    }
    if (test == "owner-commit") {
        arm_owner_commit = true; assert(!get()); assert(live.empty() && destroyed == 1 && allocation_faults == 1);
        assert(!get() && creates == 1); frame_no++; valid(get()); assert(creates == 2); return;
    }
    if (test == "concurrent") {
        std::vector<std::thread> workers;
        for (int i = 0; i < 4; i++) workers.emplace_back([] { for (int j = 0; j < 50; j++) assert(get()); });
        for (auto& worker : workers) worker.join();
        assert(creates == 1 && live.size() == 1); return;
    }
    if (test == "seen-commit") {
        auto first = get(); valid(first);
        // A distinct ID forces the parameter acceleration insertion.
        // Use sampler_make directly to test this cache even when the outer ID table is bypassed.
        if (!cache_off) {
            fail_cache = Seen; auto next = sampler_make(1, false); valid(next); assert(allocation_faults == 1);
            assert(live.at(next).ci.mipLodBias == 0.25f && live.at(next).ci.maxLod == 8);
        } else valid(get(1));
        assert(destroyed == 0); return;
    }
    if (test == "mine-commit") {
        auto first = sampler_make(0, false); valid(first);
        fail_cache = Mine; assert(sampler_make(0, false) == first);
        assert(allocation_faults == 1 && creates == 1 && destroyed == 0 && live.size() == 1); return;
    }
    if (test == "valid-after-failure" || test == "failure-commit") {
        auto first = get(); valid(first); create_result = VK_ERROR_OUT_OF_DEVICE_MEMORY;
        arm_failure_commit = test == "failure-commit"; assert(!get(1)); assert(get() == first);
        create_result = VK_SUCCESS;
        if (test == "failure-commit") { assert(allocation_faults == 1 && !get(2) && creates == 2); }
        else valid(get(2));
        assert(!get(1)); frame_no++; valid(get(1)); assert(get() == first && destroyed == 0); return;
    }
    if (test == "anisotropy-change") {   // (the row moved: samplers_changed moves the generation; the next is made anew)
        auto first = get(); valid(first); assert(!live.at(first).ci.anisotropyEnable);
        row_times = 4; generation++;
        auto second = get(); valid(second);
        assert(second != first && creates == 2 && live.at(second).ci.anisotropyEnable && live.at(second).ci.maxAnisotropy == 4);
        assert(get() == second && creates == 2);
        row_times = 0; generation++; assert(get() == first && creates == 2); return;   // (the first kept: its key again)
    }
    if (test == "upscale-bias-change") {   // (another Render resolution: samplers_changed; the biased sampler made anew)
        policy = test;
        auto first = get(); valid(first); assert(live.at(first).ci.mipLodBias == -0.5f);
        up_bias = -0.25f; generation++;
        auto second = get(); valid(second); assert(second != first && live.at(second).ci.mipLodBias == -0.75f && creates == 2);
        return;
    }
    if (test == "registration") {
        auto first = get(); valid(first); generation++; registration_lod_max = 3;
        auto second = get(); valid(second); assert(second != first && creates == 2 && live.at(second).ci.maxLod == 3); return;
    }
    if (test == "shared-thread") {
        auto first = get(); valid(first); VkSampler other{};
        std::thread worker([&] { other = get(); }); worker.join();
        assert(other == first && creates == 1); return;
    }
    policy = test;
    if (test == "upscale-bias" || test == "upscale-bias-plain") up_bias = -0.25f;
    if (test == "anisotropy-row" || test == "anisotropy-env-off" || test == "anisotropy-no-mips" || test == "anisotropy-nearest-mip") row_times = 16;
    const bool compare = test.find("compare") == 0;
    const int id = test == "unknown-id" ? -1 : 0;
    auto sampler = get(id, compare); valid(sampler);
    const auto& saved = live.at(sampler); const auto& ci = saved.ci;
    assert(get(id, compare) == sampler && creates == 1);
    if (test == "nearest") assert(ci.minFilter == VK_FILTER_NEAREST && ci.magFilter == VK_FILTER_NEAREST && ci.maxLod == 0.25f);
    if (test == "linear") assert(ci.minFilter == VK_FILTER_LINEAR && ci.maxLod == 0.25f);
    if (test == "unknown-id" || test == "force-linear") assert(ci.minFilter == VK_FILTER_LINEAR && ci.magFilter == VK_FILTER_LINEAR && ci.maxLod == 0.25f);
    if (test == "wrap") assert(ci.addressModeU == VK_SAMPLER_ADDRESS_MODE_REPEAT && ci.addressModeV == VK_SAMPLER_ADDRESS_MODE_MIRRORED_REPEAT && ci.addressModeW == VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_BORDER);
    if (test == "lod-clamp") assert(ci.mipLodBias == 16 && ci.minLod == 0 && ci.maxLod == 0);
    if (test == "upscale-bias") assert(ci.mipLodBias == -0.75f);   // (the game's -0.5 and the upscaler's)
    if (test == "upscale-bias-plain") assert(ci.mipLodBias == 0);   // (a sampler the game does not bias: as it asks)
    if (compare) {
        assert(ci.compareEnable && ci.compareOp == (test == "compare-explicit" ? VK_COMPARE_OP_NEVER : VK_COMPARE_OP_LESS_OR_EQUAL));
        assert(ci.minFilter == (test == "compare-pcf-off" ? VK_FILTER_NEAREST : VK_FILTER_LINEAR));
    }
    if (test == "custom-border" || test == "custom-reduction") assert(saved.custom && ci.borderColor == VK_BORDER_COLOR_FLOAT_CUSTOM_EXT && saved.border[0] == 0.25f && saved.border[3] == 1);
    if (test == "standard-border") assert(!saved.custom && ci.borderColor == VK_BORDER_COLOR_FLOAT_OPAQUE_WHITE);
    if (test == "reduction" || test == "custom-reduction") assert(saved.reduced && saved.reduction == VK_SAMPLER_REDUCTION_MODE_MIN);
    if (test == "compare-reduction") assert(!saved.reduced);
    if (test == "anisotropy" || test == "anisotropy-row" || test == "anisotropy-nearest-mip") assert(ci.anisotropyEnable && ci.maxAnisotropy == 8);   // (the device's limit)
    if (test == "anisotropy-game" || test == "anisotropy-env-off" || test == "anisotropy-no-mips" || test == "healthy") assert(!ci.anisotropyEnable && ci.maxAnisotropy == 1);
}
} // namespace fixture
int main(int argc, char** argv) {
    assert(argc == 3); fixture::route = argv[1]; fixture::run(argv[2]); return 0;
}
