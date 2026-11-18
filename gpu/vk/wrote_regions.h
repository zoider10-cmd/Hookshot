// The 2 MB regions of GPU addresses a GPU buffer write ever reached (vk_texture.cpp, gpu_wrote). A texture whose storage
// is in none of them was not written by the GPU: gpu_wrote_into says so without its lock and its walk of the map of
// written ranges. A bit is never cleared, and addresses past 40 bits share the bits of those below: a set bit means
// "ask the map", a clear one "no".
// tests/test_wrote_regions.py
#pragma once
#include <algorithm>
#include <atomic>
#include <cstdint>

namespace wrote_regions {

constexpr unsigned kShift = 21;           // (2 MB)
constexpr uint64_t kRegions = 1ull << 19;   // (of a 40-bit address space: 64 KB of bits)
inline std::atomic<uint64_t> bits[kRegions / 64];

// A GPU write of lo..hi: its regions noted. Called before the write is in the map
inline void mark(uint64_t lo, uint64_t hi) {
    if (hi <= lo) return;
    const uint64_t a = lo >> kShift, n = std::min<uint64_t>(((hi - 1) >> kShift) - a + 1, kRegions);
    for (uint64_t i = 0; i < n; i++) {
        const uint64_t r = (a + i) % kRegions;
        bits[r >> 6].fetch_or(1ull << (r & 63), std::memory_order_relaxed);
    }
}

// Whether any region of lo..hi was ever written
inline bool any(uint64_t lo, uint64_t hi) {
    if (hi <= lo) return false;
    const uint64_t a = lo >> kShift, n = std::min<uint64_t>(((hi - 1) >> kShift) - a + 1, kRegions);
    for (uint64_t i = 0; i < n; i++) {
        const uint64_t r = (a + i) % kRegions;
        if (bits[r >> 6].load(std::memory_order_relaxed) & (1ull << (r & 63))) return true;
    }
    return false;
}

} // namespace wrote_regions
