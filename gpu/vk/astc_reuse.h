// Decoded ASTC used again (vk_texture.cpp): a texture the game made again at another address, with the same blocks as one
// it finalized, takes that one's image by a GPU copy instead of being decoded (and re-encoded as BC3) again. Issue 1069: every
// area load decoded 0.8-1.2 GB of ASTC, revisits too, the earlier copies still held (2,383 -> 10,893 textures over a tour).
// tests/test_astc_reuse.py
#pragma once
#include <cstdint>
#include <cstring>
#include <unordered_map>

namespace astc_reuse {

// XXH64 (Yann Collet's, BSD-2): the blocks' hash. Several pieces (an array's layers) go in one by one, each piece's hash
// folded into the running one with its length
constexpr uint64_t P1 = 0x9E3779B185EBCA87ull, P2 = 0xC2B2AE3D27D4EB4Full, P3 = 0x165667B19E3779F9ull,
                   P4 = 0x85EBCA77C2B2AE63ull, P5 = 0x27D4EB2F165667C5ull;
inline uint64_t rotl(uint64_t x, int r) { return (x << r) | (x >> (64 - r)); }
inline uint64_t read64(const uint8_t* p) { uint64_t v; std::memcpy(&v, p, 8); return v; }
inline uint32_t read32(const uint8_t* p) { uint32_t v; std::memcpy(&v, p, 4); return v; }
inline uint64_t xround(uint64_t acc, uint64_t in) { return rotl(acc + in * P2, 31) * P1; }
inline uint64_t merge(uint64_t acc, uint64_t v) { return (acc ^ xround(0, v)) * P1 + P4; }

inline uint64_t xxh64(const uint8_t* p, uint64_t n, uint64_t seed) {
    const uint8_t* const end = p + n;
    uint64_t h;
    if (n >= 32) {
        uint64_t v1 = seed + P1 + P2, v2 = seed + P2, v3 = seed, v4 = seed - P1;
        const uint8_t* const limit = end - 32;
        do {
            v1 = xround(v1, read64(p)), v2 = xround(v2, read64(p + 8));
            v3 = xround(v3, read64(p + 16)), v4 = xround(v4, read64(p + 24));
            p += 32;
        } while (p <= limit);
        h = rotl(v1, 1) + rotl(v2, 7) + rotl(v3, 12) + rotl(v4, 18);
        h = merge(merge(merge(merge(h, v1), v2), v3), v4);
    } else {
        h = seed + P5;
    }
    h += n;
    for (; p + 8 <= end; p += 8) h = rotl(h ^ xround(0, read64(p)), 27) * P1 + P4;
    if (p + 4 <= end) h = rotl(h ^ (uint64_t)read32(p) * P1, 23) * P2 + P3, p += 4;
    for (; p < end; p++) h = rotl(h ^ *p * P5, 11) * P1;
    h ^= h >> 33, h *= P2, h ^= h >> 29, h *= P3, h ^= h >> 32;
    return h;
}

struct Hasher {
    uint64_t h = 0, bytes = 0;
    void add(const uint8_t* p, uint64_t n) { h = xxh64(p, n, h ^ n), bytes += n; }
};

// What has to match besides the blocks for one image to stand for another: the image the decode made (its format, size,
// levels, layers, the top levels left out, BC3 or RGBA8, resized for AMD) and the storage it was decoded from (NVN format,
// the key's layout)
struct Shape {
    uint32_t format, width, height, depth, levels, layers, skip, nvn_format, layout;
    bool bc, bc_resized;
    bool operator==(const Shape& o) const {
        return format == o.format && width == o.width && height == o.height && depth == o.depth && levels == o.levels &&
               layers == o.layers && skip == o.skip && nvn_format == o.nvn_format && layout == o.layout && bc == o.bc &&
               bc_resized == o.bc_resized;
    }
};

// The textures the game finalized whose image may serve again, by their blocks' hash. T is the cache's entry; one is in the
// list at most once (listed and unlisted by its pointer)
template <class T>
class Freed {
public:
    void list(uint64_t hash, T* t) { by_hash.emplace(hash, t); }
    void unlist(uint64_t hash, T* t) {
        auto [a, b] = by_hash.equal_range(hash);
        for (auto it = a; it != b; ++it)
            if (it->second == t) {
                by_hash.erase(it);
                return;
            }
    }
    // One listed with this hash whose shape is `shape` (shape_of(T*) gives each one's), or null
    template <class ShapeOf>
    T* find(uint64_t hash, const Shape& shape, ShapeOf shape_of) const {
        auto [a, b] = by_hash.equal_range(hash);
        for (auto it = a; it != b; ++it)
            if (shape_of(it->second) == shape) return it->second;
        return nullptr;
    }
    size_t size() const { return by_hash.size(); }

private:
    std::unordered_multimap<uint64_t, T*> by_hash;
};

} // namespace astc_reuse
