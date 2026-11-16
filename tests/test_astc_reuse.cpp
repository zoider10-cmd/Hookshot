// astc_reuse (gpu/vk/astc_reuse.h): the blocks' hash, the shape that must match, and the list of finalized textures.
// tests/test_astc_reuse.py
#include "../gpu/vk/astc_reuse.h"

#include <cstdio>
#include <cstring>
#include <vector>

static int failures = 0;
static void expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        failures++;
    }
}

struct Tex {
    astc_reuse::Shape shape;
};

int main() {
    using astc_reuse::xxh64;
    // (XXH64's published values)
    expect(xxh64(nullptr, 0, 0) == 0xEF46DB3751D8E999ull, "XXH64 of nothing, seed 0");
    expect(xxh64((const uint8_t*)"a", 1, 0) == 0xD24EC4F1A98C6E5Bull, "XXH64(\"a\")");
    expect(xxh64((const uint8_t*)"abc", 3, 0) == 0x44BC2CF5AD770999ull, "XXH64(\"abc\")");
    const char* fox = "The quick brown fox jumps over the lazy dog";
    expect(xxh64((const uint8_t*)fox, std::strlen(fox), 0) == 0x0B242D361FDA71BCull, "XXH64 of the fox (over 32 bytes)");

    std::vector<uint8_t> blocks(1 << 20);
    for (size_t i = 0; i < blocks.size(); i++) blocks[i] = (uint8_t)(i * 2654435761u >> 13);
    astc_reuse::Hasher whole, parts, other;
    whole.add(blocks.data(), blocks.size());
    parts.add(blocks.data(), blocks.size());
    expect(whole.h == parts.h, "the same blocks hash the same");
    blocks[777777] ^= 1;
    other.add(blocks.data(), blocks.size());
    expect(other.h != whole.h, "one bit changed: another hash");
    blocks[777777] ^= 1;
    astc_reuse::Hasher split;
    split.add(blocks.data(), 4096), split.add(blocks.data() + 4096, blocks.size() - 4096);
    expect(split.bytes == whole.bytes, "pieces count their bytes");
    astc_reuse::Hasher moved;
    moved.add(blocks.data(), 4095), moved.add(blocks.data() + 4095, blocks.size() - 4095);
    expect(moved.h != split.h, "where the pieces are cut is part of the hash (each piece's length goes in)");

    const astc_reuse::Shape s{8, 1024, 1024, 1, 11, 1, 0, 0x8c, 0x30005, true, false};
    astc_reuse::Shape t = s;
    expect(s == t, "the same shape");
    t.levels = 10;
    expect(!(s == t), "another level count");
    t = s, t.bc = false;
    expect(!(s == t), "RGBA8 is not BC3");
    t = s, t.skip = 1;
    expect(!(s == t), "top levels left out");
    t = s, t.layout = 0x30004;
    expect(!(s == t), "another storage layout");
    t = s, t.bc_resized = true;
    expect(!(s == t), "a resized BC image (AMD)");

    astc_reuse::Freed<Tex> freed;
    Tex a{s}, b{s}, c{s};
    c.shape.width = 512;
    const auto shape_of = [](const Tex* x) { return x->shape; };
    expect(!freed.find(1, s, shape_of), "nothing listed: nothing found");
    freed.list(5, &a), freed.list(5, &c), freed.list(9, &b);
    expect(freed.find(5, s, shape_of) == &a, "the one with the hash and the shape");
    expect(freed.find(5, c.shape, shape_of) == &c, "the same hash, another shape: that one");
    expect(!freed.find(6, s, shape_of), "another hash: none");
    freed.unlist(5, &a);
    expect(!freed.find(5, s, shape_of), "unlisted: not found");
    expect(freed.size() == 2, "the others stay");
    freed.unlist(5, &a);
    expect(freed.size() == 2, "unlisting twice changes nothing");

    if (failures) return 1;
    std::printf("astc_reuse: all passed\n");
    return 0;
}
