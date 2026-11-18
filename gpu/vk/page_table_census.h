// (hookshot) Guest memory's page table, for the pointers shaders follow (vk_memory.cpp guest_pages_set), covers two windows of
// the guest's 512 GB, as the shaders read it (spirv_emit_context.cpp kGuestPagesBase, kGuestPagesBase2): 8 GB from 64 GB, where
// the heap is, and 4 GB from 508 GB, where the game's GPU allocator put its storage buffers. A load through a pointer into a pool
// outside them that no bound buffer holds reads 0. Whether the game has such pools was never counted: the census logs each one
// as it comes into the pool table (the first 30), and at close how many came, their bytes outside and where they lie, before
// the table is made to reach the whole window.
// Rules only, no Vulkan: vk_memory.cpp keeps the census (memory_sync, page_table_census_log). tests/test_page_table_census.py
// runs them.
#pragma once
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <string>
#include <utility>
#include <vector>

namespace mkwvk {

struct PageWindow {
    uint64_t base, bytes, first;   // (first: the window's first entry in the table, after the windows before it)
};
inline constexpr PageWindow kPageWindows[] = {{0x1000000000ull, 8ull << 30, 0}, {0x7f00000000ull, 4ull << 30, (8ull << 30) >> 12}};
inline constexpr uint64_t kPageTableEntries = ((8ull << 30) + (4ull << 30)) >> 12;   // (4 KB pages: a device address each)

/// The bytes of [lo, hi) that no window covers
inline uint64_t page_table_outside(uint64_t lo, uint64_t hi) {
    if (hi <= lo) return 0;
    uint64_t in = 0;
    for (const PageWindow& w : kPageWindows) {
        const uint64_t a = std::max(lo, w.base), b = std::min(hi, w.base + w.bytes);
        if (a < b) in += b - a;
    }
    return hi - lo - in;
}

/// "16 KB", "64.0 MB", "1.25 GB"
inline std::string page_census_size(uint64_t bytes) {
    char b[32];
    if (bytes < (1ull << 20)) std::snprintf(b, sizeof b, "%llu KB", (unsigned long long)(bytes >> 10));
    else if (bytes < (1ull << 30)) std::snprintf(b, sizeof b, "%.1f MB", bytes / 1048576.0);
    else std::snprintf(b, sizeof b, "%.2f GB", bytes / 1073741824.0);
    return b;
}

/// "64-72 GB and 508-512 GB"
inline std::string page_census_windows() {
    std::string s;
    for (const PageWindow& w : kPageWindows) {
        char b[48];
        std::snprintf(b, sizeof b, "%s%llu-%llu GB", s.empty() ? "" : " and ", (unsigned long long)(w.base >> 30),
                      (unsigned long long)((w.base + w.bytes) >> 30));
        s += b;
    }
    return s;
}

struct PageTableCensus {
    static constexpr int kNamed = 30;   // (pools named one by one; the rest are counted)
    std::vector<std::pair<uint64_t, uint64_t>> outside;   // (lo, hi) of the pools outside now, sorted
    uint64_t pools = 0;                    // (in the table now, all of them)
    uint64_t came = 0, came_bytes = 0;     // (pools that came into the table with bytes outside, and those bytes; again if one leaves and comes back)
    uint64_t most = 0, most_bytes = 0;     // (the most outside at once, and their bytes outside then)
    uint64_t lowest = UINT64_MAX, highest = 0;   // (the lowest start and the highest end of those pools)
    int named = 0;

    /// The pool table refreshed (its pools, each with lo and hi): the lines naming the pools that came outside the windows, the
    /// first kNamed of all that came
    template <class Pools>
    std::vector<std::string> refresh(const Pools& table) {
        std::vector<std::string> lines;
        std::vector<std::pair<uint64_t, uint64_t>> now;
        uint64_t now_bytes = 0;
        pools = 0;
        for (const auto& p : table) {
            pools++;
            const uint64_t out = page_table_outside(p.lo, p.hi);
            if (!out) continue;
            const std::pair<uint64_t, uint64_t> r{p.lo, p.hi};
            now.push_back(r);
            now_bytes += out;
            if (std::binary_search(outside.begin(), outside.end(), r)) continue;
            came++, came_bytes += out;
            lowest = std::min(lowest, p.lo), highest = std::max(highest, p.hi);
            if (named >= kNamed) continue;
            named++;
            const bool partly = out < p.hi - p.lo;
            char b[288];
            std::snprintf(b, sizeof b, "vk: page table: pool %#llx..%#llx (%s) is %soutside its windows%s%s%s: a pointer into %s that no "
                          "bound buffer holds reads 0", (unsigned long long)p.lo, (unsigned long long)p.hi,
                          page_census_size(p.hi - p.lo).c_str(), partly ? "partly " : "", partly ? " (" : "",
                          partly ? page_census_size(out).c_str() : "", partly ? " of it)" : "", partly ? "those bytes" : "it");
            lines.push_back(b);
        }
        std::sort(now.begin(), now.end());
        if (now.size() > most || (now.size() == most && now_bytes > most_bytes)) most = now.size(), most_bytes = now_bytes;
        outside.swap(now);
        return lines;
    }

    /// The census in a line (when: "close")
    std::string summary(const char* when) const {
        char b[512];
        if (!came) {
            std::snprintf(b, sizeof b, "vk: page table census (%s): no pool outside its windows, %s (%llu pools in the table now)", when,
                          page_census_windows().c_str(), (unsigned long long)pools);
            return b;
        }
        char named_text[48];
        if (came > (uint64_t)named) std::snprintf(named_text, sizeof named_text, "the first %d named above", named);
        else std::snprintf(named_text, sizeof named_text, "named above");
        std::snprintf(b, sizeof b, "vk: page table census (%s): %llu pool%s outside its windows, %s, came into the pool table (%s), %s "
                      "of %s outside; at most %llu at once (%s), %zu now of %llu pools; between %#llx and %#llx", when,
                      (unsigned long long)came, came == 1 ? "" : "s", page_census_windows().c_str(), named_text,
                      page_census_size(came_bytes).c_str(), came == 1 ? "it" : "them", (unsigned long long)most,
                      page_census_size(most_bytes).c_str(), outside.size(), (unsigned long long)pools, (unsigned long long)lowest,
                      (unsigned long long)highest);
        return b;
    }
};

} // namespace mkwvk
