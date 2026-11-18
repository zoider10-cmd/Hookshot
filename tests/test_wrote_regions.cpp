// tests/test_wrote_regions.py compiles and runs this: gpu/vk/wrote_regions.h on its own.
#include "../gpu/vk/wrote_regions.h"

#include <cstdio>

#define CHECK(c)                                                           \
    do {                                                                   \
        if (!(c)) {                                                        \
            std::fprintf(stderr, "%s:%d: not true: %s\n", __FILE__, __LINE__, #c); \
            return 1;                                                      \
        }                                                                  \
    } while (0)

int main() {
    const uint64_t MB = 1ull << 20, R = 2 * MB;
    // nothing written yet: no range is in a written region
    CHECK(!wrote_regions::any(0, 1));
    CHECK(!wrote_regions::any(5 * R, 9 * R));
    CHECK(!wrote_regions::any(0, 1ull << 39));

    // one write inside a region: that region, and only it
    wrote_regions::mark(10 * R + 4096, 10 * R + 8192);
    CHECK(wrote_regions::any(10 * R, 10 * R + 1));              // (the region's first byte)
    CHECK(wrote_regions::any(11 * R - 1, 11 * R));              // (its last byte)
    CHECK(wrote_regions::any(9 * R, 12 * R));                   // (a range over it)
    CHECK(!wrote_regions::any(9 * R, 10 * R));                  // (ends where it starts)
    CHECK(!wrote_regions::any(11 * R, 12 * R));                 // (starts where it ends)

    // a write over a boundary: both regions; one ending on a boundary: not the next
    wrote_regions::mark(20 * R + R - 16, 20 * R + R + 16);
    CHECK(wrote_regions::any(20 * R, 20 * R + 1) && wrote_regions::any(21 * R, 21 * R + 1));
    wrote_regions::mark(30 * R, 31 * R);
    CHECK(wrote_regions::any(30 * R + 5, 30 * R + 6) && !wrote_regions::any(31 * R, 32 * R) && !wrote_regions::any(29 * R, 30 * R));

    // an empty range is in none; an empty write marks none
    CHECK(!wrote_regions::any(10 * R + 4096, 10 * R + 4096));
    wrote_regions::mark(40 * R, 40 * R);
    CHECK(!wrote_regions::any(40 * R, 41 * R));

    // an address past the 40 bits the table covers shares a region's bit: never a wrong "no"
    wrote_regions::mark((1ull << 40) + 50 * R, (1ull << 40) + 50 * R + 8);
    CHECK(wrote_regions::any((1ull << 40) + 50 * R, (1ull << 40) + 50 * R + 8));
    CHECK(wrote_regions::any(50 * R, 50 * R + 8));              // (the shared bit: a "maybe", which the map then answers)

    // a range wider than the whole table: asked of every bit, and a write that wide marks every bit
    CHECK(wrote_regions::any(0, 1ull << 41));
    wrote_regions::mark(0, 1ull << 41);
    CHECK(wrote_regions::any(5 * R, 5 * R + 1) && wrote_regions::any(99999 * R, 99999 * R + 1));
    std::puts("wrote regions: ok");
    return 0;
}
