"""The replay's own writes of guest memory reach it in command order, unaligned ones and ones across two game pools too.

gpu_write (event signals, the stream's uniform updates) and NOP_CLEAR_BUF write guest memory on the GPU timeline, in command
order with the draws around them. Where vkCmdUpdateBuffer or vkCmdFillBuffer could not take the bytes (not 4-byte aligned) or
gpu_buffer_bind found no import holding the whole range (a range across two game pools has none: pool_lookup), they were
written on the CPU at record time instead: before the GPU ran the draws recorded ahead of them, which then read the new bytes,
and under the earlier GPU writes of the same bytes, which then landed on top. Now an unaligned part is put in the recording's
stream and copied into place (a copy has no alignment rule), and a range no single import holds is written an import at a
time; only bytes outside every pool, which no import holds and so the GPU neither reads nor writes, stay on the CPU.

Checked here with gpu_write, the NOP_CLEAR_BUF case and the helpers they use (gpu_piece_bind, gpu_put, gpu_fill, and
vk_memory.cpp's gpu_pool_piece) cut from the source and run against a recorded-command stand-in: the commands are kept in
order and run at the submit, after the CPU's writes of record time, against guest memory imported in place, with two
adjacent game pools, a gap, a third pool, a pool whose import fails and a virtual pool's mapping across two of them. Each
case records a draw's read before the write, and every command is checked for Vulkan's rules (alignment, ranges) and for a
write overlapping an earlier access with no barrier between.

No GPU or game. python -I -B tests/test_replay_write_order.py --headers <Vulkan headers> [--cxx clang++] [--source <tree>]
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{vulkan_headers}"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    """From marker to the brace closing its first one (marker found once)"""
    if text.count(marker) != 1:
        raise SystemExit("FAIL: source marker not found once: " + marker)
    at = text.index(marker)
    end = text.index("{", at) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[at:end]


PREFIX = r'''
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan_core.h>
#include <algorithm>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <vector>

@@NVN@@

namespace mkwvk {
enum { NOP_CLEAR_BUF = 1 };
@@BUFFERREF@@;

// ---- guest memory, imported in place: game pools 0 and 1 adjacent, a gap, pool 2, and pool 3 whose import fails ----
constexpr uint64_t kSize = 0x50000, kVirt = 1ull << 41;
std::vector<uint8_t> guest(kSize);
struct GuestPool { uint64_t lo = 0, hi = 0; };
std::vector<GuestPool> guest_pools = {{0x10000, 0x20000}, {0x20000, 0x30000}, {0x38000, 0x40000}, {0x40000, 0x48000}};
constexpr size_t kFailing = 3;
std::mutex pools_mu;
struct ParLock { explicit ParLock(bool = true) {} };
const VkCommandBuffer kCb = (VkCommandBuffer)(uintptr_t)7;
const VkBuffer kStream = (VkBuffer)(uintptr_t)0x900;
VkBuffer pool_buffer(size_t i) { return (VkBuffer)(uintptr_t)(0x100 + i); }
int pool_of_buffer(VkBuffer b) {
    for (size_t i = 0; i < guest_pools.size(); i++) if (b == pool_buffer(i)) return (int)i;
    return -1;
}

// ---- a virtual pool from 1 TB: [kVirt, +0x1000) maps to pool 0's last page, [kVirt + 0x1000, +0x1000) to pool 2's first ----
uint64_t host_gpu_guest(uint64_t gpu) {
    if (gpu < (1ull << 40)) return gpu;
    if (gpu >= kVirt && gpu < kVirt + 0x1000) return 0x1f000 + (gpu - kVirt);
    if (gpu >= kVirt + 0x1000 && gpu < kVirt + 0x2000) return 0x38000 + (gpu - kVirt - 0x1000);
    return 0;
}
uint8_t* host_gpu_ptr(uint64_t gpu, uint64_t* avail) {
    const uint64_t g = host_gpu_guest(gpu);
    if (!g || g >= kSize) return nullptr;
    *avail = gpu < (1ull << 40) ? kSize - g : 0x1000 - ((gpu - kVirt) & 0xfff);
    return guest.data() + g;
}
struct Host { uint8_t* (*gpu_ptr)(uint64_t, uint64_t*); uint64_t (*gpu_guest)(uint64_t); };
Host the_host{host_gpu_ptr, host_gpu_guest};
Host* host = &the_host;

// ---- what the code under test did ----
struct Range { uint64_t lo, n; };
struct Cmd {
    enum Kind { Barrier, Update, Copy, Fill, Read } kind;
    uint64_t lo = 0, n = 0, src = 0;   // (guest address; for a copy, the stream offset)
    std::vector<uint8_t> bytes;
    uint32_t word = 0;
    int read = -1;
};
std::vector<Cmd> cmds;
std::vector<Range> cpu_writes, stamps;
std::vector<std::vector<uint8_t>> seen;   // (each draw's read, as it ran)
struct Access { uint64_t lo, hi; bool write; };
std::vector<Access> pending;               // (since the last barrier)
std::vector<std::string> broken;           // (Vulkan rules, hazards)
int binds = 0, logs = 0;
std::vector<uint8_t> stream_bytes(1 << 16);
uint64_t stream_used = 0;
bool stream_full = false;

void rule(bool ok, const char* what) { if (!ok) broken.push_back(what); }
void access(uint64_t lo, uint64_t n, bool write) {
    for (const Access& p : pending)
        if (lo < p.hi && p.lo < lo + n && (write || p.write)) broken.push_back("a write and an earlier access of the same bytes, no barrier between");
    pending.push_back({lo, lo + n, write});
}
uint64_t pool_guest(VkBuffer b, uint64_t offset, uint64_t n, const char* what) {
    const int i = pool_of_buffer(b);
    rule(i >= 0, what);
    if (i < 0) return 0;
    const GuestPool& p = guest_pools[(size_t)i];
    rule(n && offset <= p.hi - p.lo && n <= p.hi - p.lo - offset, what);
    return p.lo + offset;
}

void logf(const char*, ...) { logs++; }
void end_pass(VkCommandBuffer) {}
struct GprofSpan {
    GprofSpan(VkCommandBuffer, const char*) {}
    uint64_t bytes = 0;
    int items = 0;
};
void full_barrier(VkCommandBuffer cmd, const char* = nullptr) {
    rule(cmd == kCb, "a barrier in another command buffer");
    cmds.push_back({Cmd::Barrier});
    pending.clear();
}
void vkCmdUpdateBuffer(VkCommandBuffer cmd, VkBuffer b, VkDeviceSize offset, VkDeviceSize n, const void* data) {
    rule(cmd == kCb, "an update in another command buffer");
    rule(!(offset & 3) && !(n & 3) && n && n <= 65536, "vkCmdUpdateBuffer: offset and size 4-byte aligned, up to 64 KB");
    const uint64_t lo = pool_guest(b, offset, n, "vkCmdUpdateBuffer: inside an imported pool");
    access(lo, n, true);
    Cmd c{Cmd::Update};
    c.lo = lo, c.n = n, c.bytes.assign((const uint8_t*)data, (const uint8_t*)data + n);
    cmds.push_back(c);
}
void vkCmdFillBuffer(VkCommandBuffer cmd, VkBuffer b, VkDeviceSize offset, VkDeviceSize n, uint32_t word) {
    rule(cmd == kCb, "a fill in another command buffer");
    rule(!(offset & 3) && !(n & 3) && n, "vkCmdFillBuffer: offset and size 4-byte aligned");
    const uint64_t lo = pool_guest(b, offset, n, "vkCmdFillBuffer: inside an imported pool");
    access(lo, n, true);
    Cmd c{Cmd::Fill};
    c.lo = lo, c.n = n, c.word = word;
    cmds.push_back(c);
}
void vkCmdCopyBuffer(VkCommandBuffer cmd, VkBuffer src, VkBuffer dst, uint32_t count, const VkBufferCopy* r) {
    rule(cmd == kCb, "a copy in another command buffer");
    rule(src == kStream && count, "vkCmdCopyBuffer: from the recording's stream");
    std::vector<Access> regions;
    for (uint32_t i = 0; i < count; i++) {
        rule(r[i].size && r[i].srcOffset + r[i].size <= stream_used, "vkCmdCopyBuffer: from bytes put in the stream");
        const uint64_t lo = pool_guest(dst, r[i].dstOffset, r[i].size, "vkCmdCopyBuffer: inside an imported pool");
        for (const Access& o : regions) rule(!(lo < o.hi && o.lo < lo + r[i].size), "vkCmdCopyBuffer: regions overlap");
        regions.push_back({lo, lo + r[i].size, true});
    }
    for (uint32_t i = 0; i < count; i++) {
        access(regions[i].lo, r[i].size, true);
        Cmd c{Cmd::Copy};
        c.lo = regions[i].lo, c.n = r[i].size, c.src = r[i].srcOffset;
        cmds.push_back(c);
    }
}
BufferRef stream_copy(const void* src, uint64_t n) {
    const uint64_t at = (stream_used + 255) & ~255ull;
    if (stream_full || !n || at + n > stream_bytes.size()) return {};
    std::memcpy(stream_bytes.data() + at, src, n);
    stream_used = at + n;
    return {kStream, at, n, 0};
}
/// vk_memory.cpp's, as it decides: an import holds a range inside one game pool (pool_lookup), pool 3's import fails
BufferRef gpu_buffer_bind(uint64_t gpu, uint64_t n, bool written) {
    rule(written, "a write bound as a read");
    binds++;
    uint64_t g = gpu;
    if (gpu >= (1ull << 40)) {
        uint64_t avail = 0;
        if (!host_gpu_ptr(gpu, &avail) || avail < n) return {};
        g = host_gpu_guest(gpu);
    }
    for (size_t i = 0; i < guest_pools.size(); i++) {
        const GuestPool& p = guest_pools[i];
        if (g >= p.lo && g < p.hi) return i != kFailing && n && n <= p.hi - g ? BufferRef{pool_buffer(i), g - p.lo, n, 0} : BufferRef{};
    }
    return {};
}
int guest_cpu_write(uint64_t gpu, const void* src, uint64_t n) {
    cpu_writes.push_back({gpu, n});
    for (uint64_t i = 0; i < n; i++) {
        const uint64_t g = host_gpu_guest(gpu + i);
        if (!g || g >= kSize) return 0;
        guest[g] = ((const uint8_t*)src)[i];
    }
    return 1;
}
void memory_stamp_gpu(uint64_t guest_addr, uint64_t size) { stamps.push_back({guest_addr, size}); }
'''

SUFFIX = r'''
@@PAYLOAD@@
/// replay()'s NOP_CLEAR_BUF case as it is in the source, in the mode given (a parallel replay: the dry pass, then a worker)
void clear_buf(VkCommandBuffer cmd, uint64_t dst, uint64_t size, uint32_t value, bool worker = false, bool dry = false) {
    nvn_p_clear_buf p{};
    p.dst = dst, p.size = size, p.value = value;
    const uint8_t* a = (const uint8_t*)&p;
    const uint32_t avail = sizeof p;
    (void)worker, (void)dry;
    switch (NOP_CLEAR_BUF) {
    @@CLEAR@@
    }
}

// ---- the cases ----
uint8_t old_byte(uint64_t a) { return (uint8_t)(a * 131 + 7); }
void reset() {
    for (uint64_t a = 0; a < kSize; a++) guest[a] = old_byte(a);
    cmds.clear(), cpu_writes.clear(), stamps.clear(), seen.clear(), pending.clear(), broken.clear();
    binds = logs = 0, stream_used = 0, stream_full = false;
    full_barrier(kCb);   // (the work before the case)
}
/// A draw recorded here reads [gpu, gpu + n) of guest memory
void draw_reads(uint64_t gpu, uint64_t n) {
    full_barrier(kCb);
    access(gpu, n, false);
    Cmd c{Cmd::Read};
    c.lo = gpu, c.n = n, c.read = (int)seen.size();
    seen.emplace_back();
    cmds.push_back(c);
}
/// The submission: the commands in order, after every CPU write of record time
void submit() {
    for (const Cmd& c : cmds) {
        if (c.kind == Cmd::Update) std::memcpy(guest.data() + c.lo, c.bytes.data(), c.n);
        if (c.kind == Cmd::Copy) std::memcpy(guest.data() + c.lo, stream_bytes.data() + c.src, c.n);
        if (c.kind == Cmd::Fill) for (uint64_t i = 0; i < c.n; i += 4) std::memcpy(guest.data() + c.lo + i, &c.word, 4);
        if (c.kind == Cmd::Read) seen[(size_t)c.read].assign(guest.begin() + c.lo, guest.begin() + c.lo + c.n);
    }
}
int count(Cmd::Kind k) {
    int n = 0;
    for (const Cmd& c : cmds) n += c.kind == k;
    return n;
}
uint64_t total(const std::vector<Range>& v) {
    uint64_t n = 0;
    for (const Range& r : v) n += r.n;
    return n;
}
bool covers(const std::vector<Range>& v, uint64_t lo, uint64_t n) {   // (exactly [lo, lo + n), in any number of parts)
    std::vector<uint8_t> hit(n);
    for (const Range& r : v) {
        if (r.lo < lo || r.lo + r.n > lo + n) return false;
        for (uint64_t i = 0; i < r.n; i++) hit[r.lo - lo + i]++;
    }
    return std::all_of(hit.begin(), hit.end(), [](uint8_t h) { return h == 1; });
}
bool read_old(int i, uint64_t lo) {
    for (size_t k = 0; k < seen[(size_t)i].size(); k++) if (seen[(size_t)i][k] != old_byte(lo + k)) return false;
    return true;
}
bool holds(uint64_t lo, const std::vector<uint8_t>& want) {
    for (size_t k = 0; k < want.size(); k++) if (guest[lo + k] != want[k]) return false;
    return true;
}
std::vector<uint8_t> bytes(uint64_t n, uint8_t seed) {
    std::vector<uint8_t> v(n);
    for (uint64_t i = 0; i < n; i++) v[i] = (uint8_t)(seed + i * 29);
    return v;
}
std::vector<uint8_t> cleared(uint64_t n, uint32_t value) {   // (byte i of a clear: the value's byte i % 4)
    std::vector<uint8_t> v(n);
    for (uint64_t i = 0; i < n; i++) v[i] = (uint8_t)(value >> (8 * (i & 3)));
    return v;
}

int failed = 0;
void verdict(const char* name, std::string why) {
    for (const std::string& b : broken) why += (why.empty() ? "" : "; ") + b;
    if (why.empty()) std::printf("PASS: %s\n", name);
    else std::printf("FAIL: %s: %s\n", name, why.c_str()), failed++;
}
std::string need(bool ok, const char* why) { return ok ? "" : why; }
std::string all(std::initializer_list<std::string> parts) {
    std::string s;
    for (const std::string& p : parts) if (!p.empty()) s += (s.empty() ? "" : "; ") + p;
    return s;
}
const char* kAhead = "the draw recorded before it read the new bytes (written on the CPU at record time, ahead of the GPU)";

int run() {
    {   // (an event signal's or a uniform update's bytes, not 4-byte aligned, in one pool)
        reset();
        const auto v = bytes(6, 0x40);
        draw_reads(0x10101, 8);
        gpu_write(kCb, 0x10101, v.data(), v.size());
        submit();
        verdict("an unaligned write in one pool, after a draw's read", all({need(read_old(0, 0x10101), kAhead),
                need(holds(0x10101, v), "the write's bytes are not in memory after the submit"),
                need(cpu_writes.empty(), "written on the CPU")}));
    }
    {
        reset();
        const auto v = bytes(32, 0x50);
        draw_reads(0x1fff0, 32);
        gpu_write(kCb, 0x1fff0, v.data(), v.size());
        submit();
        verdict("an aligned write across two game pools, after a draw's read", all({need(read_old(0, 0x1fff0), kAhead),
                need(holds(0x1fff0, v), "the write's bytes are not in memory after the submit"),
                need(cpu_writes.empty(), "written on the CPU"), need(count(Cmd::Update) == 2, "not one update per pool")}));
    }
    {
        reset();
        const auto v = bytes(7, 0x60);
        draw_reads(0x1fffd, 7);
        gpu_write(kCb, 0x1fffd, v.data(), v.size());
        submit();
        verdict("an unaligned write across two game pools, after a draw's read", all({need(read_old(0, 0x1fffd), kAhead),
                need(holds(0x1fffd, v), "the write's bytes are not in memory after the submit"),
                need(cpu_writes.empty(), "written on the CPU")}));
    }
    {   // (from the gap into pool 2: the gap's bytes on the CPU, exact, as no import holds them; pool 2's on the GPU)
        reset();
        const auto v = bytes(16, 0x70);
        draw_reads(0x38000, 8);
        gpu_write(kCb, 0x37ff8, v.data(), v.size());
        submit();
        verdict("a write from outside every pool into one", all({need(read_old(0, 0x38000), kAhead),
                need(holds(0x37ff8, v), "the write's bytes are not in memory after the submit"),
                need(covers(cpu_writes, 0x37ff8, 8), "not exactly the bytes outside the pools on the CPU")}));
    }
    {
        reset();
        const auto v = bytes(6, 0x80);
        gpu_write(kCb, 0x30010, v.data(), v.size());
        submit();
        verdict("a write outside every pool: on the CPU", all({need(holds(0x30010, v), "the bytes are not in memory"),
                need(covers(cpu_writes, 0x30010, 6), "not on the CPU"), need(count(Cmd::Update) + count(Cmd::Copy) == 0, "a GPU command")}));
    }
    {   // (as before: the CPU, and no second import of the same range)
        reset();
        const auto v = bytes(6, 0x90);
        gpu_write(kCb, 0x40001, v.data(), v.size());
        submit();
        verdict("a write into a pool whose import fails: on the CPU", all({need(holds(0x40001, v), "the bytes are not in memory"),
                need(covers(cpu_writes, 0x40001, 6), "not on the CPU"), need(binds == 1, "its import tried again")}));
    }
    {   // (no room for the bytes in the stream: on the CPU, as before; an aligned write needs none)
        reset();
        stream_full = true;
        const auto v = bytes(6, 0xa0), w = bytes(8, 0xb0);
        gpu_write(kCb, 0x10101, v.data(), v.size());
        gpu_write(kCb, 0x10200, w.data(), w.size());
        submit();
        verdict("no room in the stream: an unaligned write on the CPU, an aligned one an update", all({
                need(holds(0x10101, v) && holds(0x10200, w), "the bytes are not in memory"),
                need(covers(cpu_writes, 0x10101, 6), "the unaligned write not on the CPU"),
                need(count(Cmd::Update) == 1 && !count(Cmd::Copy), "not one update")}));
    }
    {   // (the second write's bytes over the first's, as the stream has them)
        reset();
        const auto v = bytes(8, 0xc0), w = bytes(3, 0xd0);
        gpu_write(kCb, 0x10100, v.data(), v.size());
        gpu_write(kCb, 0x10102, w.data(), w.size());
        submit();
        auto want = v;
        std::copy(w.begin(), w.end(), want.begin() + 2);
        verdict("an unaligned write over an earlier aligned one: the later bytes stay", need(holds(0x10100, want),
                "the earlier write landed over the later one (the later on the CPU at record time)"));
    }
    {   // (a virtual pool's address: the host maps 2 bytes on into pool 0, the next 2 into pool 2)
        reset();
        const auto v = bytes(4, 0xe0);
        draw_reads(0x1fffe, 2);
        gpu_write(kCb, kVirt + 0xffe, v.data(), v.size());
        submit();
        verdict("a virtual pool's write across the end of the host's mapping", all({need(read_old(0, 0x1fffe), kAhead),
                need(holds(0x1fffe, {v[0], v[1]}) && holds(0x38000, {v[2], v[3]}), "the bytes are not where the host maps them"),
                need(cpu_writes.empty(), "written on the CPU")}));
    }
    {   // (NOP_CLEAR_BUF past the small ones, 512 bytes)
        reset();
        draw_reads(0x1ff00, 0x200);
        clear_buf(kCb, 0x1ff00, 0x200, 0xdeadbeef);
        submit();
        verdict("a clear across two game pools, after a draw's read", all({need(read_old(0, 0x1ff00), kAhead),
                need(holds(0x1ff00, cleared(0x200, 0xdeadbeef)), "not cleared after the submit"),
                need(cpu_writes.empty(), "written on the CPU"), need(covers(stamps, 0x1ff00, 0x200), "not stamped as the GPU's")}));
    }
    {
        reset();
        draw_reads(0x10202, 0x3ff);
        clear_buf(kCb, 0x10202, 0x3ff, 0x11223344);
        submit();
        verdict("an unaligned clear, after a draw's read", all({need(read_old(0, 0x10202), kAhead),
                need(holds(0x10202, cleared(0x3ff, 0x11223344)), "not cleared after the submit"),
                need(cpu_writes.empty(), "written on the CPU"), need(covers(stamps, 0x10202, 0x3ff), "not stamped as the GPU's")}));
    }
    {   // (the value's bytes go on from pool 0's last 3 into pool 1)
        reset();
        clear_buf(kCb, 0x1fffd, 0x107, 0xa1b2c3d4);
        submit();
        verdict("a clear across two game pools from an unaligned address keeps the value's byte order",
                need(holds(0x1fffd, cleared(0x107, 0xa1b2c3d4)), "the bytes after the pool's end are out of phase"));
    }
    {   // (as before: one fill)
        reset();
        clear_buf(kCb, 0x10400, 0x400, 0x5a5a0f0f);
        submit();
        const bool one = count(Cmd::Fill) == 1 && !count(Cmd::Copy) && cmds.size() == 4;   // (the reset's barrier, the clear's two, the fill)
        verdict("an aligned clear in one pool: one fill, stamped", all({need(holds(0x10400, cleared(0x400, 0x5a5a0f0f)), "not cleared"),
                need(one, "not a single fill"), need(covers(stamps, 0x10400, 0x400), "not stamped")}));
    }
    {   // (the counters' clears: on the CPU in stream order, and on the GPU too, not stamped)
        reset();
        clear_buf(kCb, 0x10400, 16, 0x01020304);
        submit();
        verdict("a small clear in one pool: on the CPU in stream order and on the GPU", all({
                need(holds(0x10400, cleared(16, 0x01020304)), "not cleared"), need(covers(cpu_writes, 0x10400, 16), "not on the CPU"),
                need(count(Cmd::Fill) == 1, "not on the GPU"), need(stamps.empty(), "stamped as the GPU's")}));
    }
    {
        reset();
        clear_buf(kCb, 0x1fff8, 16, 0x01020304);
        submit();
        verdict("a small clear across two game pools: on the CPU in stream order and on the GPU per pool", all({
                need(holds(0x1fff8, cleared(16, 0x01020304)), "not cleared"), need(covers(cpu_writes, 0x1fff8, 16), "not on the CPU"),
                need(count(Cmd::Fill) == 2, "not on the GPU, a pool at a time"), need(stamps.empty(), "stamped as the GPU's")}));
    }
    {   // (a parallel replay: its dry pass cleared it on the CPU in stream order, the worker's segment on the GPU)
        reset();
        clear_buf(kCb, 0x1fff8, 16, 0x01020304, false, true);
        clear_buf(kCb, 0x1fff8, 16, 0x01020304, true);
        submit();
        verdict("a parallel replay's small clear across two game pools: the dry pass's on the CPU, the worker's on the GPU", all({
                need(holds(0x1fff8, cleared(16, 0x01020304)), "not cleared"), need(covers(cpu_writes, 0x1fff8, 16), "not on the CPU once"),
                need(count(Cmd::Fill) == 2, "not on the GPU, a pool at a time"), need(stamps.empty(), "stamped as the GPU's")}));
    }
    {
        reset();
        clear_buf(kCb, 0x30100, 0x400, 0x77777777);
        submit();
        verdict("a clear outside every pool: on the CPU", all({need(holds(0x30100, cleared(0x400, 0x77777777)), "not cleared"),
                need(covers(cpu_writes, 0x30100, 0x400), "not on the CPU"), need(!count(Cmd::Fill) && !count(Cmd::Copy), "a GPU command"),
                need(stamps.empty(), "stamped as the GPU's")}));
    }
    {   // (its first and last bytes need the stream: the whole on the CPU, as before)
        reset();
        stream_full = true;
        clear_buf(kCb, 0x10202, 0x3ff, 0x11223344);
        submit();
        verdict("an unaligned clear with no room in the stream: on the CPU", all({
                need(holds(0x10202, cleared(0x3ff, 0x11223344)), "not cleared"), need(covers(cpu_writes, 0x10202, 0x3ff), "not on the CPU"),
                need(!count(Cmd::Fill) && !count(Cmd::Copy), "a GPU command"), need(stamps.empty(), "stamped as the GPU's")}));
    }
    if (failed) std::printf("FAIL: %d case(s): the replay's own writes do not all keep command order\n", failed);
    else std::puts("PASS: the replay's own writes keep command order, unaligned and across game pools; only bytes outside every pool go on the CPU");
    return failed ? 1 : 0;
}
} // namespace mkwvk
int main() { return mkwvk::run(); }
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="clang++")
    p.add_argument("--headers", type=Path, required=True)
    p.add_argument("--source", type=Path, default=ROOT)
    a = p.parse_args()
    vk = a.source / "gpu" / "vk"
    replay = (vk / "vk_replay.cpp").read_text(encoding="utf-8")
    memory = (vk / "vk_memory.cpp").read_text(encoding="utf-8")
    internal = (vk / "vk_internal.h").read_text(encoding="utf-8")
    nvn = (a.source / "gpu" / "render" / "rx_nvn.h").read_text(encoding="utf-8")
    clear = re.findall(r"typedef struct \{[^}]*\} nvn_p_clear_buf;", nvn)
    if len(clear) != 1:
        raise SystemExit("FAIL: rx_nvn.h: nvn_p_clear_buf not found once")
    # (the helpers the write and the clear call, where the source has them, in its order; the write and the case always)
    code = []
    if "uint64_t gpu_pool_piece(" in memory:
        code.append(block(memory, "uint64_t gpu_pool_piece("))
    for marker, always in (("BufferRef gpu_piece_bind(", False), ("bool gpu_put(", False),
                           ("void gpu_write(VkCommandBuffer", True), ("bool gpu_fill(", False)):
        if always or marker in replay:
            code.append(block(replay, marker))
    source = (PREFIX.replace("@@NVN@@", clear[0]).replace("@@BUFFERREF@@", block(internal, "struct BufferRef {")) +
              "\n".join(code) +
              SUFFIX.replace("@@PAYLOAD@@", "template <class T>\n" + block(replay, "T payload(const uint8_t* a, uint32_t bytes)"))
                    .replace("@@CLEAR@@", block(replay, "case NOP_CLEAR_BUF: {")))
    with tempfile.TemporaryDirectory(prefix="replay-write-order-") as tmp:
        cpp, exe = Path(tmp) / "t.cpp", Path(tmp) / ("t.exe" if os.name == "nt" else "t")
        cpp.write_text(source, encoding="utf-8")
        cmd = [a.cxx, "-std=c++20", "-O1", "-Wno-missing-field-initializers", "-I" + str(a.headers), str(cpp), "-o", str(exe)]
        if os.name == "nt":
            cmd.append("-static")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode:
            print(r.stdout + r.stderr)
            raise SystemExit("FAIL: the cut-out write and clear did not build against the stand-ins")
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
        print(r.stdout + r.stderr, end="")
        if r.returncode:
            sys.exit(1)


if __name__ == "__main__":
    main()
