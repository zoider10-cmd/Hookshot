// (hookshot) The GPU's clock on the Steam Deck: whether the renderer asks amdgpu for a stable power state (vk_gpu_clock.cpp
// asks), and which. On by default on the Steam Deck (choose); RX_VK_GPU_CLOCK=0 leaves the clocks to the driver. The rules
// alone: no Vulkan, no system calls (tests/test_gpu_clock.cpp).
//
// The Deck's automatic clocks hold its GPU at about 1040 MHz of its 1600 in play, while the GPU is what the frame waits for:
// 99% busy, the APU at about 9 W of its 15 W cap (Kokiri Forest, 2026-11-14, docs/steam-deck-playbook.md). An amdgpu context may ask
// the driver for a stable power state, as profilers do (RADV's RADV_PROFILE_PSTATE): no privilege, only the render node every
// user has. On the Deck's APU the peak state holds the GPU at 1300 MHz: 13.9 fps where automatic clocks gave 11.7 (three
// interleaved runs each), the APU at about 13.4 W, still under its cap. The driver gives the level back when the context goes
// (the game's end, a crash too), and a write to the device's power_dpm_force_performance_level (the player's tools,
// SteamOS's GPU clock) goes over it.
#pragma once

#include <cstring>

namespace gpu_clock {

/// amdgpu's stable power states (include/uapi/drm/amdgpu_drm.h, AMDGPU_CTX_STABLE_PSTATE_*): NONE the driver's own clocks,
/// STANDARD a fixed middle clock (1100 MHz on the Deck), PEAK the profile's peak (1300 MHz on the Deck)
enum Pstate : unsigned { NONE = 0, STANDARD = 1, PEAK = 4 };

/// The Steam Deck's own APU by its name: LCD (Custom GPU 0405) or OLED (Custom GPU 0932)
inline bool deck_apu(const char* device_name) {
    return device_name && (strstr(device_name, "Custom GPU 0405") || strstr(device_name, "Custom GPU 0932"));
}
/// The Steam Deck's APU, or Steam's flag (SteamDeck=1) on an integrated GPU: as vk_main.cpp auto_profile's hw.handheld (Steam
/// sets the flag in Gaming Mode on desktops with a discrete card too)
inline bool steam_deck(const char* device_name, const char* steamdeck_env, bool integrated) {
    return (steamdeck_env && !strcmp(steamdeck_env, "1") && integrated) || deck_apu(device_name);
}

struct Facts {
    bool amd = false;              // (the GPU's vendor is AMD, 0x1002)
    bool deck = false;             // (steam_deck: the Deck's APU, or SteamDeck=1 on an integrated GPU)
    bool deck_apu = false;         // (deck_apu: the Deck's own APU by its name; the default holds only there, as measured)
    const char* level = nullptr;   // (the device's power_dpm_force_performance_level, its newline cut; null: not read)
    const char* env = nullptr;     // (RX_VK_GPU_CLOCK)
};
struct Choice {
    unsigned pstate = NONE;
    const char* why = "";
};

/// Whether a set RX_VK_GPU_CLOCK asks for anything: empty, 0 or off do not (the clocks stay the driver's, nothing is read).
/// Unset is the default, the Steam Deck's rule (choose)
inline bool asked(const char* env) {
    return env && *env && strcmp(env, "0") && strcmp(env, "off");
}

/// The Steam Deck's rule by default: the peak on its APU while its level is auto, so that a level someone chose (manual, a
/// profile) stays theirs. It costs about 4 W where the APU is under its 15 W limit (the same where it is at it), for +19% to
/// +46% (the OLED) and +8% to +20% (the LCD) against automatic clocks. Unset or 1: that rule; elsewhere the driver's own, where
/// it was not measured (on a discrete card the peak state may sit below the clock the driver boosts to). peak or standard:
/// that state on any AMD GPU, whatever its level (asked by name: what to measure elsewhere). Empty, 0 or off: the driver's own
inline Choice choose(const Facts& f) {
    const char* e = f.env;
    if (e && !asked(e)) return {NONE, "RX_VK_GPU_CLOCK=0"};
    if (!f.amd) return {NONE, "not an AMD GPU"};
    if (e && !strcmp(e, "peak")) return {PEAK, "RX_VK_GPU_CLOCK=peak"};
    if (e && !strcmp(e, "standard")) return {STANDARD, "RX_VK_GPU_CLOCK=standard"};
    if (e && strcmp(e, "1")) return {NONE, "RX_VK_GPU_CLOCK is not 0, 1, peak or standard"};
    if (!(e ? f.deck : f.deck_apu))   // (unset: the Deck's own APU only; another handheld with SteamDeck=1 was not measured)
        return {NONE, "measured on the Steam Deck only (RX_VK_GPU_CLOCK=1 or peak asks for it here)"};
    if (!f.level) return {NONE, "the GPU's power level could not be read"};
    if (strcmp(f.level, "auto")) return {NONE, "the GPU's power level was chosen (not auto): it stays"};
    return {PEAK, e ? "RX_VK_GPU_CLOCK=1 on the Steam Deck's APU" : "the default on the Steam Deck's APU"};
}

/// Whether anything is read or opened at all: an AMD GPU, and RX_VK_GPU_CLOCK asking for something, or unset on the Steam
/// Deck (the default). Elsewhere, unset, nothing is read and no line is logged, as before the switch
inline bool looked_at(const Facts& f) {
    return f.amd && (f.env ? asked(f.env) : f.deck_apu);
}

/// The state's name for the log
inline const char* name(unsigned pstate) {
    return pstate == PEAK ? "peak" : pstate == STANDARD ? "standard" : "none";
}

} // namespace gpu_clock
