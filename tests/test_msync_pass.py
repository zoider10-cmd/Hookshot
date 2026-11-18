"""The mirror syncs' pages from the captures by the write-back diff's pass (gpu/vk/vk_memory.cpp, RX_VK_MSYNC_PASS).

A mirror sync copied a capture buffer's pages into the pool's mirror as copy regions; with the switch on (the default) they
go as chunks of the write-back diff's pass (shaders/wb_diff.comp), whose shadow is the destination itself, so the pass is
a copy. Cuts msync_pass_add, wbd_split, WbdChunk and msync_pass_on out of the source as they are (tests/srccut.py), over
fake buffer addresses and fake memory, and checks:
- applying the chunks as the shader does (the source's words to the destination) gives the destination the copy regions
  give it, byte for byte, nothing outside them touched: page runs and partial pages, the source and the destination alike
  or not within 16 bytes, runs past 64 KB;
- every chunk is whole: at most 64 KB, its shadow is its destination, a chunk of vectors 16-byte aligned at all three
  addresses;
- a run not in whole words, a run of no size, a buffer without an address and a pass without its pipeline: nothing
  taken (false), the caller copies them as before;
- the switch: on when unset, off for 0, false, off and no (any case, spaces around), on for any other value.
  (A chunk's vecs is 0 or 1: its bit 1 would be the late pages' fix's stamps, which the pass has none of.)
Then the tables: msync_block_get and msync_pass_flush as they are, over fake blocks of host memory (guard bytes after
each) and a GPU that may read a table from its dispatch until its submission is done (a parallel replay submits a
segment before the next one is recorded), with a nonCoherentAtomSize of 64, 128 and 256 bytes (more than a chunk) and
of 1 and 32:
- a flush, as the whole atoms Vulkan flushes (vkFlushMappedMemoryRanges), never covers a byte of a table a dispatch may
  still read: an earlier submission's or one of the same submission's, tables of 1 to 9 chunks;
- nothing is written over such a table or past a block's end: the room a table asks for counts its alignment (a table
  that fits the block's rest only unaligned goes to the next block, one that fits it aligned stays);
- each table is its sync's chunks, written before its flush (the bytes flushed are the chunks) and flushed whole; the
  push constants point at it with no stamp and no observations, and the dispatch's rows cover its chunks as the shader
  numbers them; right before the dispatch, in the upload command buffer, one checkpoint of its own ('s', its chunk
  count), which vk_draw.cpp's checkpoint_kind names, so a device-lost report says the GPU stopped in the pass;
- 64 tables of a chunk share one block, not one each;
- with every block still read, a table bigger than a block (the next block free or not), or a block that can't be made
  (no memory, not mapped, no address; nothing kept of it), the sync goes as its copies; a block is taken again, from
  its start, once the submission that read it last is done (a later submission's table in it too).
Then, from the text (with comments, // and /* */, left out of mirror_sync, the presync and sparse_grow_all): every
capture buffer is made with cap_usage(), which gives them storage and an address when the pass is on (it reads them by
address); the runs the pass takes still go into the write-back shadow (shadow_sync_copy, as the copies' do: else the
diff writes a capture's older words over the CPU's newer ones), and their chunks are flushed right after mirror_sync's
loop over the capture buffers, which has no return (unless the presync holds them: it sets msync_batching right before
its loop over the pools, clears it and flushes right after, and sets it nowhere else); a sparse mirror's fill
(sparse_grow_all) ends with a full barrier when the pass is on: every vkCmdCopyBuffer (or vkCmdCopyBuffer2) it records
is in the loop over the pools and inside the if (!fill.empty()) whose first statement sets a flag declared false and
assigned nowhere else, and the barrier on that flag is the first statement after the loop, which has no return (the fill
copies into the mirror, the copies' barrier orders copies only, and a sync's dispatch after it in the same uploads reads
and writes those bytes); the pass's push constants are the write-back diff's (one shader, one layout) and the shader's
Chunk has WbdChunk's fields in its order.

python -I -B tests/test_msync_pass.py [--cxx g++] [--source path/to/vk_memory.cpp]
"""
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))   # (tests/srccut.py: python -I leaves this folder off the path)
from srccut import block, between   # noqa: E402

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
ENV_ON_H = ROOT / "gpu" / "vk" / "compat" / "hookshot_env.h"
SHADER = ROOT / "gpu" / "vk" / "shaders" / "wb_diff.comp"
DRAW = ROOT / "gpu" / "vk" / "vk_draw.cpp"
SWITCH = "RX_VK_MSYNC_PASS"


def code(text):
    """text with its comments left out (// to the end of the line, /* to */): a check reads the code, not a comment"""
    return re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)


FIXTURE = r'''
#define _CRT_SECURE_NO_WARNINGS   // (getenv, with an MSVC-target {cxx}: as the tests' own .cpp files)
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <vector>
#include "hookshot_env.h"

typedef uint64_t VkDeviceAddress;
typedef struct VkBuffer_T* VkBuffer;
typedef struct VkDevice_T* VkDevice;
typedef struct VkCommandBuffer_T* VkCommandBuffer;
typedef struct VkPipeline_T* VkPipeline;
typedef struct VkPipelineLayout_T* VkPipelineLayout;
typedef struct VmaAllocation_T* VmaAllocation;
typedef uint32_t VkBufferUsageFlags;
#define VK_NULL_HANDLE nullptr
enum { VK_STRUCTURE_TYPE_BUFFER_DEVICE_ADDRESS_INFO = 1000244001 };
enum { VK_BUFFER_USAGE_STORAGE_BUFFER_BIT = 0x20, VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT = 0x20000 };
enum { VK_PIPELINE_BIND_POINT_COMPUTE = 1, VK_SHADER_STAGE_COMPUTE_BIT = 0x20 };
struct VkBufferCopy { uint64_t srcOffset, dstOffset, size; };
struct VkBufferDeviceAddressInfo { int sType; const void* pNext; VkBuffer buffer; };

static int failures;   // (the first 24 told)
#define CHECK(ok, ...) do { if (!(ok) && failures++ < 24) { std::fprintf(stderr, "failed: %s: ", #ok); \
    std::fprintf(stderr, __VA_ARGS__); std::fprintf(stderr, "\n"); } } while (0)

namespace mkwvk {
static void logf(const char*, ...) {}
struct { VkDevice device; struct { struct { uint64_t nonCoherentAtomSize; } limits; } props; } dev{};
std::map<VkBuffer, VkDeviceAddress> addresses;   // (a buffer's device address; 0 for one without)
VkDeviceAddress vkGetBufferDeviceAddress(VkDevice, const VkBufferDeviceAddressInfo* i) {
    auto it = addresses.find(i->buffer);
    return it == addresses.end() ? 0 : it->second;
}
bool pipe_ready = true;
bool wbd_pipe_ready() { return pipe_ready; }
struct Pool { VkBuffer mirror = VK_NULL_HANDLE; };

// (the tables' fakes: a block is host memory with guard bytes after it, at a device address of its own; the commands are
// recorded, a dispatch with the push constants before it)
uint64_t mem_rec_value = 0, mem_completed = 0;
int64_t st_msync_dispatches = 0, st_msync_chunks = 0, st_msync_fallbacks = 0;
constexpr uint64_t kGuard = 4096;
struct FakeBlock {
    std::vector<uint8_t> mem;
    uint64_t size = 0;
    VkDeviceAddress address = 0;
};
std::map<VmaAllocation, FakeBlock> made;
uintptr_t made_serial = 0;
enum { MAKE_OK, MAKE_FAILS, MAKE_UNMAPPED, MAKE_NO_ADDRESS } make_next = MAKE_OK;   // (the next block made: once)
bool create_buffer(uint64_t size, VkBufferUsageFlags usage, bool host_visible, VkBuffer& buffer, VmaAllocation& allocation,
                   void** mapped, bool = false) {
    CHECK(host_visible && (usage & VK_BUFFER_USAGE_STORAGE_BUFFER_BIT) &&
          (usage & VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT),
          "a table's block made without host access, storage or an address (usage %#x)", usage);
    const auto how = make_next;
    make_next = MAKE_OK;
    if (how == MAKE_FAILS) return false;   // (as vmaCreateBuffer: nothing made, the handles left null)
    made_serial++;
    buffer = (VkBuffer)(0x100000 + made_serial);
    allocation = (VmaAllocation)(0x200000 + made_serial);
    FakeBlock& b = made[allocation];
    b.mem.assign(size + kGuard, 0xa5);
    b.size = size;
    b.address = 0x600000000000ull + (uint64_t)made_serial * (4ull << 20);
    if (how != MAKE_NO_ADDRESS) addresses[buffer] = b.address;
    *mapped = how == MAKE_UNMAPPED ? nullptr : b.mem.data();
    return true;
}
void destroy_buffer(VkBuffer buffer, VmaAllocation allocation) {
    addresses.erase(buffer);
    made.erase(allocation);
}
struct Flush {   // (the bytes as they were when flushed: what the GPU may see of a non-coherent block)
    VmaAllocation alloc;
    uint64_t offset, size;
    std::vector<uint8_t> seen;
};
std::vector<Flush> flushes;
void flush_mapped_range(VmaAllocation allocation, uint64_t offset, uint64_t size) {
    const auto it = made.find(allocation);
    std::vector<uint8_t> seen;
    if (it != made.end() && offset <= it->second.size && size <= it->second.size - offset)
        seen.assign(it->second.mem.data() + offset, it->second.mem.data() + offset + size);
    flushes.push_back({allocation, offset, size, std::move(seen)});
}
VkCommandBuffer upload_command_buffer() { return (VkCommandBuffer)(uintptr_t)0xc0; }
struct GprofSpan {
    int items = 1;
    uint64_t bytes = 0;
    GprofSpan(VkCommandBuffer, const char*) {}
};
struct { VkPipeline pipe; VkPipelineLayout layout; } wbd_pipe{(VkPipeline)(uintptr_t)0xd0,
                                                            (VkPipelineLayout)(uintptr_t)0xd1};
struct Recorded { VkDeviceAddress table; uint32_t count, x, y; };
std::vector<Recorded> dispatches;
Recorded pushed{};
struct CopyCmd { VkBuffer src, dst; std::vector<VkBufferCopy> rs; };
std::vector<CopyCmd> copy_cmds;
void vkCmdBindPipeline(VkCommandBuffer, int, VkPipeline) {}
void vkCmdPushConstants(VkCommandBuffer, VkPipelineLayout, uint32_t, uint32_t offset, uint32_t size, const void* data) {
    CHECK(offset == 0 && size == 24, "push constants of %u bytes at %u, not the write-back diff's 24 at 0", size, offset);
    std::memcpy(&pushed.table, data, 8);
    std::memcpy(&pushed.count, (const uint8_t*)data + 8, 4);
    if (size == 24) {   // (no stamp, no observations: with an address the shader writes a word a chunk there)
        const uint8_t* rest = (const uint8_t*)data + 12;
        CHECK(std::all_of(rest, rest + 12, [](uint8_t v) { return v == 0; }), "push constants with a stamp or an "
              "observations address");
    }
}
void vkCmdDispatch(VkCommandBuffer, uint32_t x, uint32_t y, uint32_t) {
    Recorded r = pushed;
    r.x = x, r.y = y;
    dispatches.push_back(r);
}
void vkCmdCopyBuffer(VkCommandBuffer, VkBuffer src, VkBuffer dst, uint32_t n, const VkBufferCopy* rs) {
    copy_cmds.push_back({src, dst, std::vector<VkBufferCopy>(rs, rs + n)});
}
struct Mark { VkCommandBuffer cmd; uint64_t key; char kind; size_t dispatches_before; };
std::vector<Mark> marks;   // (the checkpoints, each with the number of dispatches recorded before it)
void checkpoint_mark(VkCommandBuffer cmd, uint64_t key, char kind) { marks.push_back({cmd, key, kind, dispatches.size()}); }

@SWITCH_ON@
@WBD_SPLIT@
@WBD_CHUNK@;
std::vector<WbdChunk> msync_chunks;
@MSYNC_COPY@;
std::vector<MsyncCopy> msync_copies;
@PASS_ADD@
@MSYNC_BLOCKS@
@BLOCK_GET@
@PASS_FLUSH@
}  // namespace mkwvk
using namespace mkwvk;

// (the fake memory: a capture buffer and a mirror, each at a device address; a buffer's bytes by its address)
constexpr uint64_t kSrcBytes = 1u << 20, kDstBytes = 1u << 20;
static std::vector<uint8_t> src_mem(kSrcBytes), dst_mem(kDstBytes);
static VkDeviceAddress src_addr, dst_addr;

static void fill(std::vector<uint8_t>& m, uint32_t seed) {
    for (size_t i = 0; i < m.size(); i++) m[i] = (uint8_t)((i * 2654435761u + seed) >> 13);
}

/// The chunks applied as shaders/wb_diff.comp does: the source's words or vectors to the destination (where they differ,
/// which leaves it the same as writing them all), the shadow being the destination
static bool apply(const std::vector<WbdChunk>& chunks, std::vector<uint8_t>& dst, const char* what) {
    bool ok = true;
    for (const WbdChunk& c : chunks) {
        const uint64_t unit = c.vecs ? 16 : 4, bytes = (uint64_t)c.count * unit;
        CHECK(c.vecs <= 1 && c.count > 0 && bytes <= (64u << 10), "%s: a chunk of %u %s", what, c.count, c.vecs ? "vectors" : "words");
        CHECK(c.shadow == c.guest, "%s: a chunk's shadow is not its destination", what);
        if (c.vecs) CHECK(c.mirror % 16 == 0 && c.shadow % 16 == 0 && c.guest % 16 == 0, "%s: a vector chunk not 16-byte aligned", what);
        CHECK(c.mirror % 4 == 0 && c.guest % 4 == 0, "%s: a chunk not in words", what);
        const bool in_src = c.mirror >= src_addr && c.mirror + bytes <= src_addr + kSrcBytes;
        const bool in_dst = c.guest >= dst_addr && c.guest + bytes <= dst_addr + kDstBytes;
        CHECK(in_src && in_dst, "%s: a chunk outside its buffers", what);
        if (!in_src || !in_dst || bytes > (64u << 10)) { ok = false; continue; }
        std::memcpy(dst.data() + (c.guest - dst_addr), src_mem.data() + (c.mirror - src_addr), bytes);
    }
    return ok;
}

static void check_runs(const std::vector<VkBufferCopy>& rs, const char* what) {
    Pool p;
    p.mirror = (VkBuffer)(uintptr_t)0x2000;
    const VkBuffer cap = (VkBuffer)(uintptr_t)0x1000;
    msync_chunks.clear(), msync_copies.clear();
    fill(dst_mem, 7);
    std::vector<uint8_t> want = dst_mem;
    for (const VkBufferCopy& r : rs) std::memcpy(want.data() + r.dstOffset, src_mem.data() + r.srcOffset, r.size);
    const bool taken = msync_pass_add(p, cap, rs);
    CHECK(taken, "%s: not taken", what);
    if (!taken) return;
    CHECK(msync_copies.size() == 1 && msync_copies[0].src == cap && msync_copies[0].dst == p.mirror &&
          msync_copies[0].rs.size() == rs.size(), "%s: its copies not kept for a sync with no table room", what);
    std::vector<uint8_t> got = dst_mem;
    if (!apply(msync_chunks, got, what)) return;
    size_t first = got.size();
    for (size_t i = 0; i < got.size(); i++)
        if (got[i] != want[i]) { first = i; break; }
    CHECK(first == got.size(), "%s: the mirror differs from the copies' at offset %#zx", what, first);
}

static void check_refused(const std::vector<VkBufferCopy>& rs, const char* what) {
    Pool p;
    p.mirror = (VkBuffer)(uintptr_t)0x2000;
    msync_chunks.clear(), msync_copies.clear();
    msync_chunks.push_back({1, 2, 2, 1, 0});   // (an earlier sync's, still to go: left as it is)
    const bool taken = msync_pass_add(p, (VkBuffer)(uintptr_t)0x1000, rs);
    CHECK(!taken && msync_chunks.size() == 1 && msync_copies.empty(), "%s: taken (%zu chunks), not left to the copies", what,
          msync_chunks.size());
}

// ---- the tables: msync_block_get and msync_pass_flush as they are ----
struct Table {   // (a table a dispatch was recorded with: the GPU may read it until its submission is done)
    VmaAllocation alloc;
    uint64_t at, bytes, value;
    std::vector<uint8_t> want;
};
static std::vector<Table> tables;
static uint64_t chunk_serial;
static char scene[64];

static void tables_reset(uint64_t atom) {
    for (MsyncBlock& b : msync_blocks) {
        if (b.buf) destroy_buffer(b.buf, b.alloc);
        b = {};
    }
    msync_block_cur = -1;
    tables.clear(), flushes.clear(), dispatches.clear(), copy_cmds.clear(), marks.clear();
    dev.props.limits.nonCoherentAtomSize = atom;
    mem_rec_value = 1, mem_completed = 0;
}

static const FakeBlock* block_at(VkDeviceAddress a, VmaAllocation* alloc) {
    for (const auto& kv : made)
        if (a >= kv.second.address && a < kv.second.address + kv.second.size) {
            *alloc = kv.first;
            return &kv.second;
        }
    return nullptr;
}

/// A sync of n chunks (made up: a word each) through msync_pass_flush, a table taking it or (dispatch false) its copies;
/// then what it published, against every table a dispatch recorded before it may still be reading
static void publish(uint32_t n, bool dispatch, const char* what) {
    msync_chunks.clear(), msync_copies.clear();
    for (uint32_t i = 0; i < n; i++, chunk_serial++) {
        const uint64_t d = 0x10000000ull + 4 * chunk_serial;
        msync_chunks.push_back({0x7f0000000000ull + 4 * chunk_serial, d, d, 1u, 0u});
    }
    msync_copies.push_back({(VkBuffer)(uintptr_t)0x1000, (VkBuffer)(uintptr_t)0x2000, {{0, 0, 4ull * n}}});
    const std::vector<WbdChunk> chunks = msync_chunks;
    const size_t f0 = flushes.size(), d0 = dispatches.size(), c0 = copy_cmds.size(), m0 = marks.size();
    msync_pass_flush();
    CHECK(msync_chunks.empty() && msync_copies.empty(), "%s, %s: the sync's chunks or copies kept after it", scene, what);
    const uint64_t atom = std::max<uint64_t>(1, dev.props.limits.nonCoherentAtomSize), bytes = n * sizeof(WbdChunk);
    const size_t nd = dispatches.size() - d0, nf = flushes.size() - f0, nc = copy_cmds.size() - c0;
    if (!dispatch) {
        CHECK(nd == 0 && nf == 0 && nc == 1 && copy_cmds.back().rs.size() == 1 &&
              copy_cmds.back().rs[0].size == 4ull * n,
              "%s, %s: not as its copies (%zu dispatches, %zu flushes, %zu copy commands)", scene, what, nd, nf, nc);
    } else if (nd != 1 || nf != 1 || nc != 0) {
        CHECK(nd == 1 && nf == 1 && nc == 0, "%s, %s: not one dispatch with one flush (%zu dispatches, %zu flushes, %zu "
              "copy commands)", scene, what, nd, nf, nc);
    } else {
        const size_t nm = marks.size() - m0;
        CHECK(nm == 1 && marks.back().cmd == upload_command_buffer() && marks.back().kind == 's' && marks.back().key == n &&
              marks.back().dispatches_before == d0, "%s, %s: not one checkpoint of its own ('s', its %u chunks) in the "
              "upload command buffer right before its dispatch (%zu checkpoints)", scene, what, n, nm);
        const Recorded& d = dispatches.back();
        const Flush& f = flushes.back();
        VmaAllocation alloc = nullptr;
        const FakeBlock* b = block_at(d.table, &alloc);
        CHECK(b && alloc == f.alloc, "%s, %s: the table at %#llx is not in the block flushed", scene, what,
              (unsigned long long)d.table);
        const uint64_t at = b ? d.table - b->address : 0;
        if (b && alloc == f.alloc && at + bytes > b->size) {
            CHECK(at + bytes <= b->size, "%s, %s: the table [%llu, %llu) runs past its block's %llu bytes", scene, what,
                  (unsigned long long)at, (unsigned long long)(at + bytes), (unsigned long long)b->size);
        } else if (b && alloc == f.alloc) {
            CHECK(f.offset == at && f.size == bytes && d.count == n, "%s, %s: the flush [%llu, +%llu) and the count %u, not "
                  "the table's [%llu, +%llu) and its %u chunks", scene, what, (unsigned long long)f.offset,
                  (unsigned long long)f.size, d.count, (unsigned long long)at, (unsigned long long)bytes, n);
            CHECK(d.table % 8 == 0, "%s, %s: the table at %#llx, not 8-byte aligned (the shader's Table)", scene, what,
                  (unsigned long long)d.table);
            // (the shader's chunk is gl_WorkGroupID.x + gl_WorkGroupID.y * 65535: rows of 65535 but the last)
            CHECK(d.x >= 1 && d.y >= 1 && d.y <= 65535 && (d.y == 1 ? d.x >= n : d.x == 65535 && 65535ull * d.y >= n),
                  "%s, %s: a dispatch of %u x %u workgroups for %u chunks", scene, what, d.x, d.y, n);
            CHECK(!std::memcmp(b->mem.data() + at, chunks.data(), bytes), "%s, %s: the table is not the sync's chunks",
                  scene, what);
            CHECK(f.seen.size() == bytes && !std::memcmp(f.seen.data(), chunks.data(), bytes), "%s, %s: the bytes flushed "
                  "are not the sync's chunks (the table written after its flush?)", scene, what);
            // (Vulkan flushes whole atoms: the first and the last the flush touches are written whole)
            const uint64_t lo = f.offset / atom * atom;
            const uint64_t hi = std::min(b->size, (f.offset + f.size + atom - 1) / atom * atom);
            for (const Table& t : tables)
                CHECK(t.alloc != alloc || t.value <= mem_completed || t.at + t.bytes <= lo || t.at >= hi,
                      "%s, %s: its flush of bytes [%llu, %llu) is one of atoms [%llu, %llu), with bytes [%llu, %llu) of a "
                      "table submission %llu may still be reading", scene, what, (unsigned long long)f.offset,
                      (unsigned long long)(f.offset + f.size), (unsigned long long)lo, (unsigned long long)hi,
                      (unsigned long long)t.at, (unsigned long long)(t.at + t.bytes), (unsigned long long)t.value);
            tables.push_back({alloc, at, bytes, mem_rec_value, std::vector<uint8_t>(chunks.size() * sizeof(WbdChunk))});
            std::memcpy(tables.back().want.data(), chunks.data(), bytes);
        }
    }
    for (const Table& t : tables) {   // (nothing written over a table the GPU may still read, nor past a block)
        if (t.value <= mem_completed) continue;
        const auto it = made.find(t.alloc);
        CHECK(it != made.end() && !std::memcmp(it->second.mem.data() + t.at, t.want.data(), t.bytes),
              "%s, %s: a table submission %llu may still be reading, at [%llu, %llu), written over", scene, what,
              (unsigned long long)t.value, (unsigned long long)t.at, (unsigned long long)(t.at + t.bytes));
    }
    for (const auto& kv : made) {
        const uint8_t* end = kv.second.mem.data() + kv.second.size;
        CHECK(std::all_of(end, end + kGuard, [](uint8_t v) { return v == 0xa5; }), "%s, %s: written past the end of a block",
              scene, what);
    }
}

static void check_tables() {
    const uint32_t whole = (uint32_t)(kMsyncBlockBytes / sizeof(WbdChunk));
    for (uint64_t atom : {64ull, 128ull, 256ull, 1ull, 32ull}) {
        std::snprintf(scene, sizeof scene, "nonCoherentAtomSize %llu", (unsigned long long)atom);
        const uint64_t align = std::max<uint64_t>(atom, sizeof(WbdChunk));
        // (an earlier table still read: the next submission's sync, then more of that submission's)
        tables_reset(atom);
        publish(1, true, "a sync of one chunk");
        mem_rec_value = 2;
        publish(1, true, "the next submission's sync of one chunk, the first's table still read");
        for (uint32_t n : {3u, 5u, 8u, 9u, 1u, 2u}) publish(n, true, "more syncs of that submission");
        mem_completed = 1, mem_rec_value = 3;
        publish(4, true, "a sync once the first submission is done");
        // (tables of one chunk each share a block)
        tables_reset(atom);
        for (int i = 0; i < 64; i++) publish(1, true, "one of 64 syncs of a chunk");
        CHECK(made.size() == 1, "%s: 64 tables of a chunk took %zu blocks, not one", scene, made.size());
        // (the room: a table that fits the block's rest only unaligned goes to the next block; one that fits it aligned
        // stays)
        tables_reset(atom);
        publish(1, true, "a sync of one chunk");
        publish((uint32_t)((kMsyncBlockBytes - align) / sizeof(WbdChunk)), true,
                "a table that fills the block's rest, aligned");
        CHECK(made.size() == 1, "%s: a table that fits the block's rest aligned went to a block of its own", scene);
        tables_reset(atom);
        publish(1, true, "a sync of one chunk");
        publish(whole - 1, true, "a table that fits the block's rest only unaligned");
        publish(1, true, "a sync after it");
        // (the ring: every block still read, then the first one's submission done; a table bigger than a block)
        tables_reset(atom);
        for (int i = 0; i < kMsyncBlocks; i++, mem_rec_value++) publish(whole, true, "a table of a whole block");
        publish(1, false, "a sync with every block still read");
        mem_completed = 1;
        publish(1, true, "a sync once the first block's submission is done");
        CHECK(!dispatches.empty() && dispatches.back().table == msync_blocks[0].address, "%s: a block whose submission is "
              "done not taken again from its start", scene);
        publish(whole + 1, false, "a table bigger than a block");
        // (a block a later submission's table went into after an earlier one's: not taken again until the later is done)
        tables_reset(atom);
        publish(1, true, "a sync of one chunk");
        mem_rec_value = 2;
        publish(1, true, "the next submission's sync, in the same block");
        for (int i = 1; i < kMsyncBlocks; i++, mem_rec_value++) publish(whole, true, "a table of a whole block");
        mem_completed = 1;
        publish(1, false, "a sync with the first block's second submission still read");
        mem_completed = mem_rec_value - 1;
        publish(1, true, "a sync once that submission is done");
        CHECK(!dispatches.empty() && dispatches.back().table == msync_blocks[0].address, "%s: a block whose submissions are "
              "done not taken again from its start", scene);
        // (a table bigger than a block with the next block free; a block that could not be made, kept from nothing)
        tables_reset(atom);
        publish(whole + 1, false, "a table bigger than a block, the next block free");
        CHECK(made.empty(), "%s: a block made for a table bigger than a block", scene);
        for (auto how : {MAKE_FAILS, MAKE_UNMAPPED, MAKE_NO_ADDRESS}) {
            make_next = how;
            publish(1, false, "a sync whose block could not be made");
            CHECK(made.empty() && msync_block_cur == -1, "%s: a block that could not be made (%d) kept", scene, (int)how);
        }
        publish(1, true, "a sync once a block can be made");
    }
    tables_reset(64);
}

int main(int argc, char** argv) {
    if (argc > 1 && !std::strcmp(argv[1], "switch")) {
        std::printf("%d\n", msync_pass_on() ? 1 : 0);
        return 0;
    }
    if (argc > 1 && !std::strcmp(argv[1], "tables")) {
        check_tables();
        if (failures) {
            std::fprintf(stderr, "%d failed\n", failures);
            return 1;
        }
        std::puts("ok");
        return 0;
    }
    fill(src_mem, 3);
    for (uint64_t src_base : {0x7f0000000000ull, 0x7f0000000004ull, 0x7f0000000008ull, 0x7f000000000cull}) {
        src_addr = src_base, dst_addr = 0x10000000ull;   // (a mirror's address; the source's alike within 16 bytes or not)
        addresses = {{(VkBuffer)(uintptr_t)0x1000, src_addr}, {(VkBuffer)(uintptr_t)0x2000, dst_addr}};
        char what[96];
        // (a sync's runs: whole pages from capture slots, joined where contiguous, as append_capture_copy leaves them)
        std::snprintf(what, sizeof what, "pages (source at +%llu)", (unsigned long long)(src_base & 15));
        check_runs({{0, 0x3000, 0x1000}, {0x5000, 0x8000, 0x3000}, {0x2000, 0x20000, 0x1000}}, what);
        // (a pool that starts or ends inside a page: the first and last runs are part of a page)
        for (uint64_t lead : {4ull, 8ull, 12ull, 20ull, 0xffcull}) {
            std::snprintf(what, sizeof what, "partial pages (source at +%llu, %llu into the page)", (unsigned long long)(src_base & 15),
                          (unsigned long long)lead);
            check_runs({{lead, 0, 0x1000 - lead}, {0x1000, 0x1000 - lead, 0x1000}, {0x9000, 0x40000, lead}}, what);
        }
        // (long contiguous runs: past 64 KB, several of its chunks; odd words at both ends)
        std::snprintf(what, sizeof what, "long runs (source at +%llu)", (unsigned long long)(src_base & 15));
        check_runs({{4, 0x10004, (64u << 10) + 8}, {0x40000, 0x80000, 3 * (64u << 10)}, {0x90008, 0xf0000, 0x7ff8}}, what);
        for (uint64_t size = 4; size <= 80; size += 4)
            for (uint64_t at = 0; at < 32; at += 4) {
                std::snprintf(what, sizeof what, "%llu bytes at %llu (source at +%llu)", (unsigned long long)size,
                              (unsigned long long)at, (unsigned long long)(src_base & 15));
                check_runs({{0x100 + at, 0x300 + at, size}, {0x700, 0x704 + at, size}}, what);
            }
    }
    src_addr = 0x7f0000000000ull, dst_addr = 0x10000000ull;
    addresses = {{(VkBuffer)(uintptr_t)0x1000, src_addr}, {(VkBuffer)(uintptr_t)0x2000, dst_addr}};
    check_refused({{0, 0, 0x1000}, {0x1000, 0x1002, 0x100}}, "a run not at a whole word");
    check_refused({{0, 0, 0x1000}, {0x1000, 0x1000, 0x102}}, "a run of no whole words");
    check_refused({{0, 0, 0x1000}, {0x1000, 0x1000, 0}}, "a run of no size");
    check_refused({}, "no runs");
    pipe_ready = false;
    check_refused({{0, 0, 0x1000}}, "the pass's pipeline not made");
    pipe_ready = true;
    addresses.erase((VkBuffer)(uintptr_t)0x1000);
    check_refused({{0, 0, 0x1000}}, "a capture buffer without an address");
    if (failures) {
        std::fprintf(stderr, "%d failed\n", failures);
        return 1;
    }
    std::puts("ok");
    return 0;
}
'''


def text_checks(text, shader):
    errors = []
    for fn in ('void cap_spare_make(', 'bool cap_buf_get('):
        body = block(text, fn)
        calls = re.findall(r'create_buffer_cached\(\s*[^,]+,\s*([^,]+),', body)
        if not calls:
            errors.append(f"{fn.split('(')[0].split()[-1]}: no create_buffer_cached call found")
        for usage in calls:
            if usage.strip() != 'cap_usage()':
                errors.append(f"{fn.split('(')[0].split()[-1]} makes a capture buffer with {usage.strip()}, not cap_usage(): "
                              "the pass reads capture buffers by address")
    usage = block(text, 'VkBufferUsageFlags cap_usage()')
    if not re.search(r'msync_pass_on\(\)[^;]*STORAGE_BUFFER_BIT[^;]*SHADER_DEVICE_ADDRESS_BIT', usage):
        errors.append("cap_usage() does not give a capture buffer storage and an address when the pass is on (msync_pass_on())")
    every = re.findall(r'create_buffer_cached\(\s*[^,]+,\s*([^,]+),', text)
    capture_like = [u.strip() for u in every if 'TRANSFER_SRC' in u and 'STORAGE' not in u]
    if capture_like:
        errors.append(f"a buffer made with {capture_like[0]} alone: if it is a capture's, make it with cap_usage()")
    sync = code(block(text, 'void mirror_sync(Pool& p)'))
    taken = re.search(r'if \(msync_pass_on\(\) && msync_pass_add\([^)]*\)\) \{(.*?)\bcontinue;', sync, re.S)
    if not taken or 'shadow_sync_copy(' not in taken.group(1):
        errors.append("mirror_sync: the runs the pass takes are not copied into the write-back shadow (shadow_sync_copy), "
                      "as the copies' are")
    loop = 'for (const auto& [buf, rs] : cap_runs) {'   # (the runs the pass takes: their chunks flushed right after it)
    at = sync.find(loop)
    end = at + len(block(sync[at:], loop, unique=False)) if at >= 0 else -1
    if (not taken or not at < taken.start() < end or re.search(r'\breturn\b', sync[at:end])
            or not re.match(r'\s*if \(!msync_batching\)\s*msync_pass_flush\(\);', sync[end:])):
        errors.append("mirror_sync: the chunks of the runs the pass takes are not flushed right after its loop over the "
                      "capture buffers, which has no return (if (!msync_batching) msync_pass_flush();): they would not "
                      "reach the mirror")
    pre = code(block(text, 'void memory_sync_mirrors_before_segments()'))
    hold = re.search(r'[;{}]\s*msync_batching = true;\s*(for \([^;{]*\) \{)', pre)   # (the hold, then its loop at once)
    pools = block(pre[hold.start(1):], hold.group(1), unique=False) if hold else ''
    after = pre[hold.start(1) + len(pools):] if hold else ''
    if (not hold or 'mirror_sync(' not in pools or re.search(r'\breturn\b', pools)
            or not re.match(r'\s*msync_batching = false;\s*msync_pass_flush\(\);', after)
            or len(re.findall(r'\bmsync_batching\s*[&|^]?=(?!=)', pre)) != 2):
        errors.append("memory_sync_mirrors_before_segments: the presync does not hold its syncs' chunks and flush them once "
                      "after its loop (msync_batching = true; right before the loop, which has no return; "
                      "msync_batching = false; msync_pass_flush(); right after it; msync_batching set nowhere else)")
    grow = code(block(text, 'void sparse_grow_all(const std::vector<Pool*>& pools) {'))   # (a barrier in a comment records nothing)
    copies = [m.start() for m in re.finditer(r'\bvkCmdCopyBuffer(?:2(?:KHR)?)?\s*\(', grow)]   # (every copy it records)
    loop, branch = 'for (Got& g : gots) {', 'if (!fill.empty()) {'
    loops = [(m.start(), m.start() + len(block(grow[m.start():], loop, unique=False)))
             for m in re.finditer(re.escape(loop), grow)]
    around = [(a, e) for a, e in loops if copies and a < copies[0] and copies[-1] < e]
    a, e = around[0] if around else (0, 0)
    gate = re.match(r'\s*if \((\w+) && msync_pass_on\(\)\)\s*full_barrier\(up\b', grow[e:]) if around else None
    flag = gate.group(1) if gate else ''
    sets = re.search(re.escape(branch) + r'\s*' + re.escape(flag) + r' = true;', grow[a:e]) if gate else None
    b0 = a + sets.start() if sets else 0
    b1 = b0 + len(block(grow[b0:], branch, unique=False)) if sets else 0
    why = None
    if not around:
        why = f'no loop over the pools ({loop}) holds every copy'
    elif not gate:
        why = 'the first statement after that loop is not if (<flag> && msync_pass_on()) full_barrier(up, ...)'
    elif not re.search(r'\bbool ' + re.escape(flag) + r' = false;', grow[:a]):
        why = f'bool {flag} = false; is not before the loop'
    elif not sets:
        why = f'{flag} = true; is not the first statement of {branch}'
    elif not all(b0 < c < b1 for c in copies):
        why = f'a copy is outside the {branch} that sets {flag}'
    elif len(re.findall(r'\b' + re.escape(flag) + r'\s*[&|^]?=(?!=)', grow)) != 2:
        why = f'{flag} is assigned outside its declaration and that {branch}'
    elif re.search(r'\breturn\b', grow[a:e]):
        why = 'a return in the loop, before the barrier'
    if why:
        errors.append("sparse_grow_all: a sparse mirror's fill does not end with a full barrier when the pass is on: "
                      f"{why} (the fill copies into the mirror, the copies' barrier orders copies only, and a sync's "
                      "dispatch after it in the same uploads reads and writes those bytes)")
    pc = re.compile(r'const struct \{[^}]*\}\s*pc\{')
    flush = block(text, 'void msync_pass_flush() {')
    end = block(text, 'void memory_end_submission(')
    ours, theirs = pc.findall(flush), pc.findall(end)
    norm = lambda s: re.sub(r'\s+', ' ', s)
    if len(ours) != 1 or len(theirs) != 1 or norm(ours[0]) != norm(theirs[0]):
        errors.append("msync_pass_flush's push constants are not the write-back diff's (one shader, one layout): "
                      f"{ours} vs {theirs}")
    draw = DRAW.read_text(encoding='utf-8')
    if "c == 's' ? \"mirror syncs' pass" not in code(block(draw, 'const char* checkpoint_kind(char c) {')):
        errors.append("vk_draw.cpp: checkpoint_kind does not name the mirror syncs' pass ('s'): a device-lost report "
                      "would not say the GPU stopped in it")
    fields = re.findall(r'^\s*(?:uvec2|uint)\s+(\w+);', block(shader, 'struct Chunk'), re.M)
    chunk = block(text, 'struct WbdChunk')
    ours_fields = re.findall(r'\b(mirror|shadow|guest|count|vecs)\b', chunk)
    if fields != ['mirror', 'shadow', 'guest', 'count', 'vecs'] or ours_fields[:5] != fields:
        errors.append(f"the shader's Chunk fields {fields} are not WbdChunk's {ours_fields[:5]}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cxx', default='g++')
    parser.add_argument('--source', type=Path, default=ROOT / 'gpu/vk/vk_memory.cpp')
    args = parser.parse_args()
    text = args.source.read_text(encoding='utf-8')
    shader = SHADER.read_text(encoding='utf-8')
    errors = text_checks(text, shader)
    fixture = (FIXTURE.replace('@SWITCH_ON@', block(text, 'bool msync_pass_on()'))
               .replace('@WBD_SPLIT@', block(text, 'template <class F> void wbd_split('))
               .replace('@WBD_CHUNK@', block(text, 'struct WbdChunk'))
               .replace('@MSYNC_COPY@', block(text, 'struct MsyncCopy'))
               .replace('@PASS_ADD@', block(text, 'bool msync_pass_add(Pool& p, VkBuffer buf, const std::vector<VkBufferCopy>& rs) {'))
               .replace('@MSYNC_BLOCKS@', between(text, 'struct MsyncBlock {', 'MsyncBlock* msync_block_get('))
               .replace('@BLOCK_GET@', block(text, 'MsyncBlock* msync_block_get('))
               .replace('@PASS_FLUSH@', block(text, 'void msync_pass_flush() {')))
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'msync_pass.cpp'
        exe = Path(tmp) / 'msync_pass.exe'
        src.write_text(fixture, encoding='utf-8')
        # (-Wno-missing-field-initializers: the source fills Vulkan's structs by their sType alone, as Vulkan code does)
        subprocess.run([args.cxx, '-std=c++20', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-missing-field-initializers',
                        '-I', str(ENV_ON_H.parent), str(src), '-o', str(exe)], check=True)
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        if run.returncode:
            errors.append('the chunks: ' + (run.stderr.strip() or f'exit {run.returncode}'))
        run = subprocess.run([str(exe), 'tables'], capture_output=True, text=True)
        if run.returncode:
            errors.append('the tables: ' + (run.stderr.strip() or f'exit {run.returncode}'))
        for value, want in ((None, 1), ('0', 0), ('false', 0), (' OFF ', 0), ('No', 0), ('1', 1), ('yes', 1), ('2', 1)):
            env = {k: v for k, v in os.environ.items() if k != SWITCH}
            if value is not None:
                env[SWITCH] = value
            got = subprocess.run([str(exe), 'switch'], capture_output=True, text=True, env=env).stdout.strip()
            if got != str(want):
                errors.append(f"{SWITCH}={value!r}: {'on' if got == '1' else 'off'}, wanted {'on' if want else 'off'}")
    if errors:
        for e in errors:
            print('FAIL:', e)
        raise SystemExit(1)
    print('PASS: the mirror syncs\' pass takes each capture run as the copies did, whole chunks, the switch by the one rule, '
          'capture buffers made for it, its chunks flushed after each sync and after the presync\'s loop, each table on '
          'cache atoms of its own, a checkpoint of its own before each dispatch, a full barrier after a sparse mirror\'s '
          'fill')


if __name__ == '__main__':
    main()
