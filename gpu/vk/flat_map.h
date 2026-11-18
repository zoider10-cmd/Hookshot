// (hookshot) The replay's per-thread caches in one flat open-addressing table: texture_view_of's resolved handles (7ac89d22, after
// Project ReLink's idea), program_for's picks, graphics_pipeline's thread map and a recording's c1 uploads (after Hookshot eda64e895 /
// HeyListen 3aa51bf5). tests/test_handle_table.py, tests/test_flat_map.py
#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <type_traits>
#include <utility>
#include <vector>

/// A 64-bit key's value, searched on every draw: a node map's hash, bucket and node pointer chase cost more than the lookup's
/// work. Linear probing over a power-of-two array, kept at most half full; nothing is erased one by one (the replay clears these
/// caches whole), so no tombstones. An insert can move every entry: no pointer or reference from find or operator[] is held
/// across an insert into the same map.
template <class V>
struct FlatMap {
    struct Slot {
        uint64_t key;
        V hit;
    };
    std::vector<Slot> slots;
    std::vector<uint8_t> used;
    size_t count = 0;
    static size_t mix(uint64_t k) {   // (a key's low bits can be a slot number or an address: spread the rest in)
        k ^= k >> 29;
        k *= 0xbf58476d1ce4e5b9ull;
        k ^= k >> 32;
        return (size_t)k;
    }
    V* find(uint64_t key) {
        if (!count) return nullptr;
        const size_t m = slots.size() - 1;
        for (size_t i = mix(key) & m;; i = (i + 1) & m) {
            if (!used[i]) return nullptr;
            if (slots[i].key == key) return &slots[i].hit;
        }
    }
    V& operator[](uint64_t key) {
        if ((count + 1) * 2 > slots.size()) grow();
        const size_t m = slots.size() - 1;
        size_t i = mix(key) & m;
        for (; used[i]; i = (i + 1) & m)
            if (slots[i].key == key) return slots[i].hit;
        used[i] = 1, slots[i].key = key, slots[i].hit = V{}, count++;
        return slots[i].hit;
    }
    void grow() {
        std::vector<Slot> old = std::move(slots);
        std::vector<uint8_t> old_used = std::move(used);
        const size_t n = old.empty() ? 1024 : old.size() * 2;
        slots.assign(n, Slot{});
        used.assign(n, 0);
        count = 0;
        for (size_t j = 0; j < old.size(); j++)
            if (old_used[j]) (*this)[old[j].key] = std::move(old[j].hit);
    }
    size_t size() const { return count; }
    /// Empty, the array kept (these caches fill again to about the same size); a value that owns memory (a Pick's handles)
    /// is let go now, not when its slot is next used
    void clear() {
        if (!count) return;
        if constexpr (!std::is_trivially_destructible_v<V>) {
            for (size_t j = 0; j < slots.size(); j++)
                if (used[j]) slots[j].hit = V{};
        }
        std::fill(used.begin(), used.end(), (uint8_t)0);
        count = 0;
    }
};
