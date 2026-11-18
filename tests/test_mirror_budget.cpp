// The VRAM mirrors' budget by the card (gpu/vk/mirror_budget.h): tests/test_mirror_budget.py compiles and runs this.
#include "../gpu/vk/mirror_budget.h"

#include <cstdio>
#include <cstdlib>

#define CHECK(x) do { if (!(x)) { std::printf("FAIL line %d: %s\n", __LINE__, #x); std::exit(1); } } while (0)

int main() {
    using namespace mkwvk::mirror_rule;
    const uint64_t MB = 1ull << 20, GB = 1ull << 30;
    // a quarter, at most 2 GB under 15 GB and 3 GB from there; on a small card an eighth, at most 256 MB; 3 GB when the card is
    // not known. No preset or row over it
    CHECK(auto_bytes(2 * GB) == 256 * MB);                      // (Minimum's 256 MB, as before)
    CHECK(auto_bytes(4 * GB) == 256 * MB);                      // (a GTX 1650: the Minimum (4GB) preset's, its default before)
    CHECK(auto_bytes(4 * GB + 512 * MB) == 256 * MB);           // (the line itself)
    CHECK(auto_bytes(1 * GB) == 128 * MB);                      // (an eighth of a smaller card)
    CHECK(auto_bytes(6 * GB) == 1536 * MB);                     // (a 2060, a 3060 Laptop: Low (6GB)'s, as before)
    CHECK(auto_bytes(8 * GB) == 2048 * MB);                     // (a 3060 Ti, a 4060: not Balanced (8GB)'s 1024 that filled)
    CHECK(auto_bytes(10 * GB) == 2048 * MB && auto_bytes(12 * GB) == 2048 * MB);   // (High (12GB)'s 2 GB)
    CHECK(auto_bytes(16 * GB) == 3072 * MB && auto_bytes(24 * GB) == 3072 * MB);   // (Ultra (16GB+)'s 3 GB)
    CHECK(auto_bytes(15 * GB) == 3072 * MB && auto_bytes(15 * GB - MB) == 2048 * MB);
    CHECK(auto_bytes(0) == 3072 * MB);
    CHECK(small_card(4 * GB + 512 * MB) && !small_card(4 * GB + 513 * MB) && !small_card(0));
    std::printf("PASS: the mirrors' budget by the card\n");
    return 0;
}
