// (tests/test_hold_gpu.py) gpu/vk/hold_gpu.h: what the order's watch thread does with queues stopped past hold_ms
#include "../gpu/vk/hold_gpu.h"

#include <cstdio>

using mkwvk::hold_gpu::Choice;
using mkwvk::hold_gpu::choose;

// (hold_ms 50, the bound 1000: the renderer's defaults)
constexpr double kHold = 50, kMost = 1000;

// not past hold_ms yet: nothing, whoever waits and whatever the switch
static_assert(choose(true, false, 10, 10, kHold, kMost) == Choice::Wait);
static_assert(choose(true, true, 50, 50, kHold, kMost) == Choice::Wait);
static_assert(choose(false, true, 49, 49, kHold, kMost) == Choice::Wait);
// past it with nobody waiting for the GPU: made to go, as before
static_assert(choose(true, false, 51, 51, kHold, kMost) == Choice::Force);
// a thread of the game's waits for the GPU: held on, however long since the queues stopped, up to the bound
static_assert(choose(true, true, 51, 0, kHold, kMost) == Choice::Hold);
static_assert(choose(true, true, 120, 0, kHold, kMost) == Choice::Hold);
static_assert(choose(true, true, 999, 0, kHold, kMost) == Choice::Hold);
// its wait over: hold_ms more for the signal it makes after it, then made to go
static_assert(choose(true, false, 120, 1, kHold, kMost) == Choice::Hold);
static_assert(choose(true, false, 160, 50, kHold, kMost) == Choice::Hold);
static_assert(choose(true, false, 161, 51, kHold, kMost) == Choice::Force);
// the bound: a wait that does not end cannot hold them for good
static_assert(choose(true, true, 1000, 0, kHold, kMost) == Choice::Force);
static_assert(choose(true, false, 1500, 10, kHold, kMost) == Choice::Force);
// the switch off: made to go at hold_ms whoever waits, as before
static_assert(choose(false, true, 51, 0, kHold, kMost) == Choice::Force);
static_assert(choose(false, false, 120, 1, kHold, kMost) == Choice::Force);
// a bound set at hold_ms itself (RX_VK_HOLD_GPU_MS at its least): never held
static_assert(choose(true, true, 51, 0, kHold, kHold) == Choice::Force);

int main() {
    // (a stall as it was measured: the queues stop at 0, the game waits for the GPU from 0 to 100 ms, signals 2 ms later;
    // the watch looks every millisecond. They must be held throughout, and never made to go)
    int forced = 0, held = 0;
    for (int t = 0; t <= 102; t++) {
        const bool gpu_wait = t <= 100;
        const double since = gpu_wait ? 0 : t - 100;
        const Choice c = choose(true, gpu_wait, t, since, kHold, kMost);
        forced += c == Choice::Force, held += c == Choice::Hold;
    }
    if (forced != 0 || held != 52) {
        std::fprintf(stderr, "FAIL: a 100 ms GPU wait: %d looks held, %d made to go (52 and 0 wanted)\n", held, forced);
        return 1;
    }
    // (the same with the rule off: made to go from the 51st millisecond on)
    forced = 0;
    for (int t = 0; t <= 102; t++) forced += choose(false, t <= 100, t, t <= 100 ? 0 : t - 100, kHold, kMost) == Choice::Force;
    if (forced != 52) {
        std::fprintf(stderr, "FAIL: the rule off: %d looks made to go (52 wanted)\n", forced);
        return 1;
    }
    std::puts("PASS: stopped queues are held on while a thread of the game's waits for the GPU, hold_ms after it, and to the bound");
    return 0;
}
