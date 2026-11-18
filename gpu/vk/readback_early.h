// Whether a read of GPU results written in place waits for its writer's part (RX_VK_READBACK_EARLY, vk_memory.cpp
// readback_early_on), and whether a capture's late pages wait for the reads that need them (RX_VK_LATE_DEFER, late_defer_on):
// the rules alone, no Vulkan (tests/test_late_defer.py).
//
// RX_VK_READBACK_EARLY: on by default where the buffer pools have no VRAM mirror (integrated GPUs: the Steam Deck, AMD APUs,
// Intel), off where they have one (discrete cards: their reads of GPU results go through the mirrors' write-back, and the
// early path had nothing to do there, 0 reads on an RTX 3090). A value other than 0, off, false, no or empty turns it on
// with mirrors too; 0 (or off, false, no, empty) turns it off. Measured: the Steam Deck OLED, Kokiri Forest at handheld
// settings 15.70 -> 20.73 fps, Hyrule Field at 1280x800 14.98 -> 18.47; an RX 580 without mirrors +10 to 24%; the byte probe
// (RX_VK_LOG_EARLY_CHECK) found no read different from main's wait. What the probe cannot see: the game, let go at its
// writer's part, writing memory a later part of the submission still reads in place (an exposure check, still to come).
// Never, asked for or not, with the parallel replay (RX_VK_PARALLEL 2 or more: its segments' parts are not on the
// recordings' timeline) or with the render thread (RX_VK_ASYNC, Threaded rendering, which records behind the game: not
// measured with it; the Deck's Auto leaves it off).
//
// RX_VK_LATE_DEFER: only where the buffer pools have no mirror and without the parallel replay; there a value given wins, and
// unset it follows RX_VK_READBACK_EARLY: with the early reads the late pages' wait was the replay's, ~19 ms a frame, and left to
// the reads it is ~1 ms; with RX_VK_READBACK_LATE=newest alone it held the game back from reads that cost more (17.6-17.9 fps
// with the wait, 15.4-16.1 without), and with neither there are almost no late pages.
#pragma once

#include "compat/hookshot_env.h"
#include <cstdlib>

namespace readback_early {

struct Facts {
    const char* env = nullptr;        // (RX_VK_READBACK_EARLY)
    const char* parallel = nullptr;   // (RX_VK_PARALLEL)
    bool render_thread = false;       // (the replay on the render thread)
    bool mirrors = false;             // (the buffer pools have a VRAM mirror: vk_memory.cpp mirror_on)
};
enum Why { OFF_MIRRORS, ON_SWITCH, OFF_SWITCH, OFF_PARALLEL, OFF_RENDER_THREAD, ON_DEFAULT };

inline bool parallel(const char* par) { return par && atoi(par) >= 2; }

inline Why choose(const Facts& f) {
    if (f.env && env_value_off(f.env)) return OFF_SWITCH;   // (an empty value is off too: env_on's reading)
    if (parallel(f.parallel)) return OFF_PARALLEL;
    if (f.render_thread) return OFF_RENDER_THREAD;
    if (f.env) return ON_SWITCH;
    return f.mirrors ? OFF_MIRRORS : ON_DEFAULT;   // (unset: on where the pools have no mirror)
}
inline bool on(Why w) { return w == ON_SWITCH || w == ON_DEFAULT; }

/// RX_VK_LATE_DEFER (env), with the pools' mirrors, the parallel replay and whether the early reads are on
inline bool defer(const char* env, bool mirrors, const char* par, bool early) {
    if (mirrors || parallel(par)) return false;
    if (env) return !env_value_off(env);
    return early;
}

} // namespace readback_early
