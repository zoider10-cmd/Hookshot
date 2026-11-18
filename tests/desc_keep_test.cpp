// The per-binding descriptor reuse (RX_VK_DESC_KEEP; from Triforce v0.5.0 72793f2 tests/desc_keep_test.cpp): desc_keep.h's rules,
// and vk_draw.cpp's helpers that resolve through them (kept_uniform, kept_texture, buf_keep and the rest of the block before
// build_descriptors, cut into the placeholder below by tests/test_desc_keep.py) against stand-ins for what they resolve with. The
// stand-ins answer from a world whose every generation a case can move, and count their calls: a descriptor taken from what was kept
// calls nothing; one resolved calls its lookup. Each case runs in a process of its own (RX_VK_DESC_KEEP is read once).
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#include <array>
#include <atomic>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include <vector>

#include "desc_keep.h"

#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)

namespace fixture {
std::string test;
const char* getenv(const char* name) {
    if (!std::strcmp(name, "RX_VK_DESC_KEEP") && test.rfind("check", 0) == 0) return "check";
    if (!std::strcmp(name, "RX_VK_DESC_KEEP") && test == "off") return "0";
    if (!std::strcmp(name, "RX_VK_DESC_KEEP") && test != "default") return "1";   // (off by default: the cases turn it on)
    if (!std::strcmp(name, "RX_VK_DESC_REUSE") && test == "no-reuse") return "never";
    if (!std::strcmp(name, "RX_VK_SAMPLER_CACHE") && test == "sampler-cache-off") return "0";
    if (!std::strcmp(name, "RX_VK_LATE_DEFER") && test == "late-defer") return "1";
    return nullptr;
}
int logged = 0;
void logf(const char*, ...) { logged++; }
#define TLS_OBJECT(name, ...) inline __VA_ARGS__& name() { static thread_local __VA_ARGS__ v; return v; }
template <class T> T handle(uint64_t v) { return reinterpret_cast<T>((uintptr_t)v); }

constexpr int kNvnStages = 8;
struct nvn_p_bind_buf { uint64_t addr = 0, size = 0; };
struct NvnState { nvn_p_bind_buf ubo[kNvnStages][16]; };
struct Stage { int nvn_stage = 1; };
struct Program { uint64_t key = 0xabcdef; };
struct Texture { uint32_t slot; };
enum class ViewUse { Sample, Storage };

// ---- the world the lookups answer from ----
struct World {
    uint64_t stamp = 5, ub = 9, samp = 3, destroy = 11, epoch = 17;
    std::map<uint32_t, uint32_t> version;   // (a slot's)
    bool sampler_fail = false, overlay = false, old_stream = false, dummy_slot = false;
    bool move_destroy = false, move_stamp = false;   // (moved while the lookup runs: what it gives stands on the old one only)
    int views = 0, samplers = 0, uniforms = 0;
    uint64_t at = 0x100;
    uint64_t bias = 0;   // (check: what the next lookups answer otherwise with the same inputs)
} w;
Texture textures[16];
thread_local bool upload_defer_ok = false;
bool ub_snapshot_wanted() { return test == "uniform-snapshot"; }
uint32_t texture_slot_version(int slot) { return w.version[(uint32_t)slot]; }
uint64_t sampler_registrations_generation() { return w.samp; }
uint64_t texture_destroy_generation() { return w.destroy; }
uint32_t texture_epoch() { return (uint32_t)w.epoch; }
uint64_t gpu_bind_stamp() { return w.stamp; }
uint64_t ub_generation() { return w.ub; }
VkImageView texture_view_of(uint32_t h, VkImageViewType vt, ViewUse use, VkFormat f, Texture** tex) {
    CHECK(use == ViewUse::Sample && f == VK_FORMAT_UNDEFINED && upload_defer_ok == (test != "compute"));
    w.views++;
    const uint32_t slot = h & 0xFFFFF;
    const uint64_t v = (uint64_t)slot << 32 ^ (uint64_t)w.version[slot] << 20 ^ w.destroy << 8 ^ (uint64_t)vt ^ w.bias;
    if (w.move_destroy) w.destroy++;
    if (w.dummy_slot) {
        *tex = nullptr;
        return VK_NULL_HANDLE;
    }
    *tex = &textures[slot & 15];
    return handle<VkImageView>(v | 1);
}
VkSampler sampler_for(int id, bool compare) {
    w.samplers++;
    if (w.sampler_fail) return VK_NULL_HANDLE;
    return handle<VkSampler>(0x7000000ull | (uint64_t)id << 8 | (uint64_t)compare << 4 | w.samp << 32 | w.bias);
}
struct RecordingRes {
    struct Stream { VkBuffer buffer; };
    VkBuffer stream = handle<VkBuffer>(0x51);
    std::vector<Stream> streams{{handle<VkBuffer>(0x50)}, {handle<VkBuffer>(0x51)}};
} recording;
thread_local RecordingRes* cur = &recording;
VkDescriptorBufferInfo uniform_range(const NvnState& s, const Stage& st, uint32_t index) {
    w.uniforms++;
    if (w.move_stamp) w.stamp++;
    if (index == 1) return {cur->stream, 0x40, 64};
    if (index == 0 || index == 2) return {cur->stream, w.at += 0x100, 0x200};   // (a bank)
    const nvn_p_bind_buf& u = s.ubo[st.nvn_stage][index - 3];
    if (!u.addr) return {VK_NULL_HANDLE, 0, VK_WHOLE_SIZE};
    if (w.overlay) return {cur->stream, w.at += 0x100, u.size};            // (a copy with an update in)
    if (w.old_stream) return {handle<VkBuffer>(0x50), w.at += 0x100, u.size};   // (in a stream the recording grew out of)
    return {handle<VkBuffer>(0x9000 + (u.addr >> 16)), (u.addr & 0xffff) + w.bias, u.size};
}

/* KEEP */

Program prog;
Stage vs{0}, fs{1};
NvnState s{};
desc_keep::Prog* kp() { return &desc_keep::prog_of(kept_descs(), &prog, 8); }
struct Tex { VkSampler smp; VkImageView view; Texture* tex; };
Tex tex_of(uint32_t h, VkImageViewType vt = VK_IMAGE_VIEW_TYPE_2D, bool compare = false, size_t j = 4, bool keep = true) {
    Tex t{};
    t.smp = kept_texture(keep ? kp() : nullptr, j, h, vt, compare, test == "compute", &t.view, &t.tex);
    CHECK(!upload_defer_ok);
    return t;
}
bool operator==(const Tex& a, const Tex& b) { return a.smp == b.smp && a.view == b.view && a.tex == b.tex; }
bool operator==(const VkDescriptorBufferInfo& a, const VkDescriptorBufferInfo& b) {
    return a.buffer == b.buffer && a.offset == b.offset && a.range == b.range;
}
/// Resolved (the sampler and, for a handle, the view looked up) or taken (nothing looked up)
bool tex_resolved(uint32_t h, Tex* out = nullptr, VkImageViewType vt = VK_IMAGE_VIEW_TYPE_2D, bool compare = false) {
    const int v0 = w.views, s0 = w.samplers;
    const Tex t = tex_of(h, vt, compare);
    if (out) *out = t;
    CHECK((w.views - v0) == (h ? w.samplers - s0 : 0));
    return w.samplers != s0;
}
bool ubo_resolved(uint32_t index = 3, size_t j = 0, VkDescriptorBufferInfo* out = nullptr) {
    const int u0 = w.uniforms;
    const VkDescriptorBufferInfo b = kept_uniform(kp(), j, s, fs, index);
    if (out) *out = b;
    return w.uniforms != u0;
}

int header() {   // (desc_keep.h alone: every input and every stamp of each kind counts)
    using namespace desc_keep;
    Stamps st;
    st.rec = 1, st.bind = 2, st.ub = 3, st.samp = 4, st.destroy = 5, st.epoch = 7;
    const auto moved = [&](int i) { Stamps x = st; uint64_t* f[6] = {&x.rec, &x.bind, &x.ub, &x.samp, &x.destroy, &x.epoch}; (*f[i])++; return x; };
    // (what each kind stands on: 0 rec, 1 bind, 2 ub, 3 samp, 4 destroy, 5 epoch)
    const bool on[5][6] = {{}, {0, 0, 0, 1, 1, 1}, {1, 1, 1, 0, 0, 0}, {1, 0, 0, 0, 0, 0}, {1, 1, 0, 0, 0, 0}};
    for (Kind k : {kTex, kUbo, kC1, kSsbo}) {
        Elem e;
        CHECK(!take(e, k, 10, 20, 30, st));   // (nothing kept)
        keep(e, k, 10, 20, 30, st, 1, 2, 3);
        CHECK(take(e, k, 10, 20, 30, st));
        CHECK(!take(e, k, 11, 20, 30, st) && !take(e, k, 10, 21, 30, st) && !take(e, k, 10, 20, 31, st));
        for (Kind other : {kTex, kUbo, kC1, kSsbo, kNone})
            if (other != k) CHECK(!take(e, other, 10, 20, 30, st));
        for (int i = 0; i < 6; i++) CHECK(take(e, k, 10, 20, 30, moved(i)) == !on[k][i]);
        CHECK(same(e, 1, 2, 3) && !same(e, 1, 2, 4) && !same(e, 9, 2, 3));
        drop(e);
        CHECK(!take(e, k, 10, 20, 30, st));
    }
    std::array<Prog, kSlots> t;
    int a = 0, b = 0;
    const void* pa = &a;
    const void* pb = nullptr;
    for (uintptr_t i = 1; i < 4096 && !pb; i++)   // (another program in the same slot: only an address, never read)
        if (const void* q = reinterpret_cast<const void*>((uintptr_t)&b + 64 * i); slot_of(q) == slot_of(pa)) pb = q;
    CHECK(pb);
    Prog& p = prog_of(t, pa, 3);
    keep(p.e[1], kTex, 1, 0, 0, st, 1, 2, 3);
    CHECK(take(prog_of(t, pa, 3).e[1], kTex, 1, 0, 0, st));
    CHECK(prog_of(t, pa, 4).e.size() == 4 && !take(prog_of(t, pa, 4).e[1], kTex, 1, 0, 0, st));   // (another count: emptied)
    keep(prog_of(t, pa, 4).e[1], kTex, 1, 0, 0, st, 1, 2, 3);
    CHECK(prog_of(t, pb, 4).prog == pb && !take(prog_of(t, pb, 4).e[1], kTex, 1, 0, 0, st));   // (another program: emptied)
    CHECK(!take(prog_of(t, pa, 4).e[1], kTex, 1, 0, 0, st));
    return 0;
}

int run() {
    if (test == "header") return header();
    w.version[0x123] = 1, w.version[0x124] = 1;
    s.ubo[1][0] = {0x12340000, 0x100};
    s.ubo[1][1] = {0x56780000, 0x40};
    const uint32_t h = 0x123 | 7u << 20, h2 = 0x124 | 7u << 20;
    if (test == "default" || test == "off" || test == "no-reuse" || test == "sampler-cache-off" || test == "late-defer") {
        CHECK(desc_keep_mode() == 0 && logged == 1);   // (every descriptor resolved)
        return 0;
    }
    if (test == "on") {
        CHECK(desc_keep_mode() == 1);
        return 0;
    }
    if (test == "texture" || test == "compute") {
        Tex a, b;
        CHECK(tex_resolved(h, &a) && !tex_resolved(h, &b) && a == b && st_dk_taken.load() == 1 && st_dk_resolved.load() == 1);
        CHECK(a.smp && a.view && a.tex == &textures[0x123 & 15]);
        w.version[0x123]++;   // (the slot registered anew)
        CHECK(tex_resolved(h, &b) && !(a == b) && !tex_resolved(h));
        w.samp++;             // (a sampler registration's contents, a sampler retired, the LOD bias or anisotropy rows)
        CHECK(tex_resolved(h) && !tex_resolved(h));
        w.destroy++;          // (a texture destroyed or made again, issue 1126; or a frame left a texture for later)
        CHECK(tex_resolved(h) && !tex_resolved(h));
        w.epoch++;            // (the next submission: the texture touched again)
        CHECK(tex_resolved(h) && !tex_resolved(h));
        CHECK(tex_resolved(h ^ 1u << 20) && tex_resolved(h));   // (another sampler id in the handle: another input)
        CHECK(tex_resolved(h, nullptr, VK_IMAGE_VIEW_TYPE_2D_ARRAY) && tex_resolved(h));
        CHECK(tex_resolved(h, nullptr, VK_IMAGE_VIEW_TYPE_2D, true) && tex_resolved(h));
        w.stamp++, w.ub++, desc_rec++;   // (what textures do not stand on: kept)
        CHECK(!tex_resolved(h));
        CHECK(tex_resolved(0) && tex_resolved(0));   // (no handle: nothing kept, as cheap to resolve)
        for (int i = 0; i < 2; i++) {   // (no kept results: resolved each time)
            const int v0 = w.views;
            const Tex none = tex_of(h2, VK_IMAGE_VIEW_TYPE_2D, false, 4, false);
            CHECK(none.view && w.views == v0 + 1);
        }
        CHECK(!tex_resolved(h));   // (and what was kept is still there)
        return 0;
    }
    if (test == "texture-moved") {   // (a destroy while the lookup ran: what it gave is kept with the generation before it)
        w.move_destroy = true;
        CHECK(tex_resolved(h));
        w.move_destroy = false;
        CHECK(tex_resolved(h) && !tex_resolved(h));
        return 0;
    }
    if (test == "texture-dummy") {   // (a slot that resolved to the dummy: kept as the dummy until a generation moves)
        w.dummy_slot = true;
        Tex a, b;
        CHECK(tex_resolved(h, &a) && !a.view && !a.tex && !tex_resolved(h, &b) && a == b);
        w.destroy++;   // (the frame that left its texture for later ended: looked up again)
        CHECK(tex_resolved(h) && !tex_resolved(h));
        w.version[0x123]++;   // (registered anew)
        CHECK(tex_resolved(h, &a) && !a.view && !tex_resolved(h, &b) && a == b);
        w.dummy_slot = false, w.epoch++;   // (its texture there by the next submission)
        CHECK(tex_resolved(h, &a) && a.view && a.tex);
        return 0;
    }
    if (test == "texture-no-sampler") {   // (a failed sampler is not kept: the draw is left out and the next one tries again)
        w.sampler_fail = true;
        CHECK(tex_resolved(h) && tex_resolved(h));
        w.sampler_fail = false;
        CHECK(tex_resolved(h) && !tex_resolved(h));
        return 0;
    }
    if (test == "uniform") {
        VkDescriptorBufferInfo a, b;
        CHECK(ubo_resolved(3, 0, &a) && !ubo_resolved(3, 0, &b) && a == b && a.buffer);
        w.ub++;   // (an inline uniform update)
        CHECK(ubo_resolved() && !ubo_resolved());
        w.stamp++;   // (a pool moved, a mirror made, the next submission)
        CHECK(ubo_resolved() && !ubo_resolved());
        desc_rec++;   // (another recording)
        CHECK(ubo_resolved() && !ubo_resolved());
        s.ubo[1][0].addr += 0x100;
        CHECK(ubo_resolved() && !ubo_resolved());
        s.ubo[1][0].size = 0x80;
        CHECK(ubo_resolved() && !ubo_resolved());
        w.samp++, w.destroy++, w.epoch++;   // (what buffers do not stand on: kept)
        CHECK(!ubo_resolved());
        CHECK(ubo_resolved(4, 1) && !ubo_resolved(4, 1) && !ubo_resolved(3, 0));   // (each its own)
        s.ubo[1][2] = {};   // (no buffer: nothing kept)
        CHECK(ubo_resolved(5, 2) && ubo_resolved(5, 2));
        CHECK(ubo_resolved(0, 3) && ubo_resolved(0, 3) && ubo_resolved(2, 3) && ubo_resolved(2, 3));   // (the banks: their own cache)
        const int u0 = w.uniforms;
        kept_uniform(nullptr, 0, s, fs, 3), kept_uniform(nullptr, 0, s, fs, 3);   // (no kept results: resolved each time)
        CHECK(w.uniforms == u0 + 2);
        return 0;
    }
    if (test == "uniform-snapshot") {   // (the uniform snapshot, Intel's default: the user ones resolved each time; c1 kept)
        CHECK(ubo_resolved(3, 0) && ubo_resolved(3, 0) && ubo_resolved(4, 1) && ubo_resolved(4, 1));
        CHECK(ubo_resolved(1, 5) && !ubo_resolved(1, 5));
        return 0;
    }
    if (test == "uniform-stream") {   // (a copy in the recording's stream, the current or an old one: made again each time)
        w.overlay = true;
        CHECK(ubo_resolved() && ubo_resolved());
        w.overlay = false, w.old_stream = true;
        CHECK(ubo_resolved() && ubo_resolved());
        w.old_stream = false;
        CHECK(ubo_resolved() && !ubo_resolved());
        return 0;
    }
    if (test == "uniform-moved") {   // (the bind stamp moved while it resolved)
        w.move_stamp = true;
        CHECK(ubo_resolved());
        w.move_stamp = false;
        CHECK(ubo_resolved() && !ubo_resolved());
        return 0;
    }
    if (test == "c1") {   // (a stage's constants: within the recording only)
        CHECK(ubo_resolved(1, 5) && !ubo_resolved(1, 5));
        w.ub++, w.stamp++;
        CHECK(!ubo_resolved(1, 5));
        desc_rec++;
        CHECK(ubo_resolved(1, 5) && !ubo_resolved(1, 5));
        return 0;
    }
    if (test == "storage") {   // (buf_stamps and buf_keep as the storage buffer path uses them)
        using namespace desc_keep;
        Elem& e = kp()->e[6];
        const VkDescriptorBufferInfo pool{handle<VkBuffer>(0x9001), 0x40, 0x100}, stream{cur->stream, 0x40, 0x100};
        Stamps now = buf_stamps(kSsbo);
        CHECK(now.rec == desc_rec && now.bind == w.stamp && now.ub == 0 && now.samp == 0);
        CHECK(!take(e, kSsbo, 0x1000, 0x100, 0, now));
        buf_keep(*kp(), 6, e, kSsbo, 0x1000, 0x100, now, false, true, pool);
        CHECK(take(e, kSsbo, 0x1000, 0x100, 0, buf_stamps(kSsbo)));
        w.ub++;   // (not what a storage buffer stands on)
        CHECK(take(e, kSsbo, 0x1000, 0x100, 0, buf_stamps(kSsbo)));
        w.stamp++;
        CHECK(!take(e, kSsbo, 0x1000, 0x100, 0, buf_stamps(kSsbo)));
        now = buf_stamps(kSsbo);
        buf_keep(*kp(), 6, e, kSsbo, 0x1000, 0x100, now, false, true, pool);
        desc_rec++;
        CHECK(!take(e, kSsbo, 0x1000, 0x100, 0, buf_stamps(kSsbo)));
        now = buf_stamps(kSsbo);
        buf_keep(*kp(), 6, e, kSsbo, 0x1000, 0x100, now, false, false, pool);   // (not bound: the zero buffer, never kept)
        CHECK(!take(e, kSsbo, 0x1000, 0x100, 0, now));
        buf_keep(*kp(), 6, e, kSsbo, 0x1000, 0x100, now, false, true, stream);   // (a copy in the stream)
        CHECK(!take(e, kSsbo, 0x1000, 0x100, 0, now));
        return 0;
    }
    if (test == "check" || test == "check-bad") {   // (RX_VK_DESC_KEEP=check: resolved each time, compared with what was kept)
        CHECK(desc_keep_mode() == 2);
        CHECK(tex_resolved(h) && tex_resolved(h) && ubo_resolved() && ubo_resolved());
        CHECK(st_dk_checked.load() == 2 && st_dk_bad.load() == 0 && st_dk_taken.load() == 0);
        if (test == "check-bad") {   // (a lookup that answers otherwise with the same inputs: counted and logged)
            w.bias = 0x10;
            const int l0 = logged;
            CHECK(tex_resolved(h) && ubo_resolved());
            CHECK(st_dk_checked.load() == 4 && st_dk_bad.load() == 2 && logged == l0 + 2);
        }
        return 0;
    }
    std::fprintf(stderr, "no case %s\n", test.c_str());
    return 2;
}
} // namespace fixture
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    fixture::test = argv[1];
    return fixture::run();
}
