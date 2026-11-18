// astc_bc_policy::all_by_vram (gpu/vk/astc_bc_policy.h): the cards that keep every large ASTC texture as BC3.
// tests/test_astc_bc_policy.py
#include "../gpu/vk/astc_bc_policy.h"

#include <cstdio>
#include <cstdlib>

static int failures = 0;
static void expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        failures++;
    }
}

int main() {
    const uint64_t MB = 1ull << 20;
    using astc_bc_policy::all_by_vram;
    expect(!all_by_vram(0), "unknown: as before (the finer ones as RGBA8)");
    expect(all_by_vram(3379 * MB), "a 4 GB laptop card (3.3 GB allowed, issue 519)");
    expect(all_by_vram(5900 * MB), "a 6 GB card");
    expect(all_by_vram(7133 * MB), "an 8 GB RX 7700S (7.1 GB allowed)");
    expect(all_by_vram(7700 * MB), "an 8 GB card allowed more");
    expect(!all_by_vram(9400 * MB), "a 10 GB card");
    expect(!all_by_vram(11200 * MB), "a 12 GB card");
    expect(!all_by_vram(15000 * MB), "a 16 GB card");
    using astc_bc_policy::all;
    expect(all(10232 * MB, true), "an integrated GPU allowed 10 GB (a Ryzen 9 7900X's, 32 GB of RAM)");
    expect(all(0, true), "an integrated GPU whose allowance is unknown");
    expect(all(7402 * MB, true), "an integrated GPU allowed under 8.5 GB (UHD Graphics, 16 GB of RAM)");
    expect(!all(15000 * MB, false) && all(7133 * MB, false) && !all(0, false), "a card: by what it is allowed, as before");
    if (failures) return EXIT_FAILURE;
    std::printf("astc bc policy: all checks passed\n");
    return EXIT_SUCCESS;
}
