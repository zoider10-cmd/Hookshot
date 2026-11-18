// The texture cache's budget by the card (gpu/vk/texture_budget.h): tests/test_texture_budget.py compiles and runs this.
#include "../gpu/vk/texture_budget.h"

#include <cstdio>
#include <cstdlib>

#define CHECK(x) do { if (!(x)) { std::printf("FAIL line %d: %s\n", __LINE__, #x); std::exit(1); } } while (0)

int main() {
    using namespace mkwvk::texture_rule;
    const uint64_t MB = 1ull << 20, GB = 1ull << 30, RAM = 32 * GB;
    // a dedicated card: the size its preset gave it, by the card (7/12, or all but 5 GB), at most 11 GB, 2.2 GB on a small card,
    // at most 75% of what the driver allows
    CHECK(dedicated_bytes(3500 * MB, 4 * GB, RAM) == 2200 * MB);    // (a 4 GB card: Minimum's 2.2 GB)
    CHECK(dedicated_bytes(2000 * MB, 4 * GB, RAM) == 1500 * MB);    // (other programs fill it: 75% of what is allowed)
    CHECK(dedicated_bytes(5500 * MB, 6 * GB, RAM) == 3584 * MB);    // (a 6 GB card: about Low's 3.6 GB)
    // (an 8 GB card: about Balanced's 4.8 GB, on Windows' allowance and on a driver that allows nearly all of it)
    CHECK(dedicated_bytes(7300 * MB, 8 * GB, RAM) > 4778 * MB && dedicated_bytes(7300 * MB, 8 * GB, RAM) < 4779 * MB);
    CHECK(dedicated_bytes(8000 * MB, 8 * GB, RAM) == dedicated_bytes(7300 * MB, 8 * GB, RAM));
    CHECK(dedicated_bytes(4000 * MB, 8 * GB, RAM) == 3000 * MB);    // (another program holds half of it)
    CHECK(dedicated_bytes(11200 * MB, 12 * GB, RAM) == 7168 * MB);  // (a 12 GB card: about High's 7.5 GB)
    CHECK(dedicated_bytes(15000 * MB, 16 * GB, RAM) == 11000 * MB); // (a 16 GB card: Ultra's 11 GB)
    CHECK(dedicated_bytes(23000 * MB, 24 * GB, RAM) == 11000 * MB); // (at most 11 GB)
    // (no budget from the driver: by the card alone)
    CHECK(dedicated_bytes(0, 8 * GB, RAM) == dedicated_bytes(7300 * MB, 8 * GB, RAM));
    CHECK(dedicated_bytes(0, 0, RAM) == 4096 * MB);
    // under 12 GB of RAM, a card past 6.75 GB: the rule from before the presets (45% up to 8.5 GB allowed); a smaller card its size
    CHECK(dedicated_bytes(7300 * MB, 8 * GB, 8 * GB) == 3285 * MB);
    CHECK(dedicated_bytes(0, 8 * GB, 8 * GB) == 4096 * MB);
    CHECK(dedicated_bytes(5500 * MB, 6 * GB, 8 * GB) == 3584 * MB);
    CHECK(dedicated_bytes(7300 * MB, 8 * GB, 0) == dedicated_bytes(7300 * MB, 8 * GB, RAM));   // (the RAM not known)
    // an integrated GPU: its share as before (45% up to 8.5 GB, else 70%, at most 6 GB), Minimum's 2.2 GB on a small heap
    CHECK(integrated_bytes(8000 * MB, 8 * GB) == 3600 * MB);
    CHECK(integrated_bytes(10000 * MB, 16 * GB) == 6144 * MB);
    CHECK(integrated_bytes(3000 * MB, 4 * GB) == 1350 * MB);
    CHECK(integrated_bytes(6000 * MB, 4 * GB) == 2200 * MB);
    CHECK(integrated_bytes(0, 8 * GB) == 4096 * MB);
    std::printf("PASS: the texture budget by the card\n");
    return 0;
}
