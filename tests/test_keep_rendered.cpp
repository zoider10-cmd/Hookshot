// keep_rendered::presents (gpu/vk/keep_rendered.h): how long an unused texture the GPU drew is kept. tests/test_keep_rendered.py
#include "../gpu/vk/keep_rendered.h"

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
    const uint64_t allowed = 7244 * MB;   // (an 8 GB RX 7700S)
    using keep_rendered::presents;
    expect(presents(false, 0, 0, false) == 3600, "unknown use: a minute");
    expect(presents(true, 3000 * MB, allowed, false) == 3600, "far from the limit: a minute");
    expect(presents(true, allowed / 100 * 96, allowed, false) == 3600, "under 97%: a minute");
    expect(presents(true, allowed / 100 * 97, allowed, false) == 600, "at 97%: 600");
    expect(presents(true, allowed, allowed, false) == 600, "AMD's report clamped at what it allows: 600");
    expect(presents(true, allowed + 600 * MB, allowed, false) == 600, "past it: 600");
    // (the old rule, RX_VK_KEEP_RENDERED_OVER=1: only past it, so never on AMD)
    expect(presents(true, allowed, allowed, true) == 3600, "old rule at the clamp: a minute");
    expect(presents(true, allowed + MB, allowed, true) == 600, "old rule past it: 600");
    // (under 60 fps: the same seconds, 120 presents at least; at 60 fps or more, or no rate known, as counted)
    using keep_rendered::at_rate;
    expect(at_rate(3600, 60.0) == 3600 && at_rate(3600, 144.0) == 3600 && at_rate(600, 0.0) == 600, "60 fps or more: as counted");
    expect(at_rate(3600, 30.0) == 1800 && at_rate(600, 30.0) == 300, "30 fps: the same seconds");
    expect(at_rate(3600, 3.5) == 210, "a minute at 3.5 fps: 210 presents, not 3600 (17 minutes)");
    expect(at_rate(600, 3.5) == 120, "ten seconds at 3.5 fps: the 120-present floor, not 35");
    expect(at_rate(3600, 0.5) == 120, "a load's stall counts as 2 fps");
    expect(at_rate(60, 3.5) == 60, "the floor is never more than the wait itself");
    if (failures) return EXIT_FAILURE;
    std::printf("keep rendered: all checks passed\n");
    return EXIT_SUCCESS;
}
