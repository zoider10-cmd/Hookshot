// gpu_clock (gpu/vk/gpu_clock.h): when the renderer holds amdgpu's stable power state. tests/test_gpu_clock.py
#include "../gpu/vk/gpu_clock.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <initializer_list>

// (the numbers vk_gpu_clock.cpp writes out, as the kernel's header has them, where the system has that header)
#if defined(__linux__) && __has_include(<drm/amdgpu_drm.h>)
#include <drm/amdgpu_drm.h>
#ifndef AMDGPU_CTX_OP_SET_STABLE_PSTATE
// (the stable power states came with Linux 5.18's amdgpu_drm.h; an older header, such as Ubuntu 22.04's linux-libc-dev 5.15,
// has the context ioctl without them. Their values as the kernel's include/uapi/drm/amdgpu_drm.h gives them; the rest of
// the ioctl is still checked against this header below)
#define AMDGPU_CTX_OP_SET_STABLE_PSTATE 6
#define AMDGPU_CTX_STABLE_PSTATE_NONE 0
#define AMDGPU_CTX_STABLE_PSTATE_STANDARD 1
#define AMDGPU_CTX_STABLE_PSTATE_PEAK 4
#define AMDGPU_HEADER_WITHOUT_PSTATE 1
#endif
static_assert(gpu_clock::NONE == AMDGPU_CTX_STABLE_PSTATE_NONE && gpu_clock::STANDARD == AMDGPU_CTX_STABLE_PSTATE_STANDARD &&
                  gpu_clock::PEAK == AMDGPU_CTX_STABLE_PSTATE_PEAK,
              "gpu_clock's states are amdgpu's");
static_assert(AMDGPU_CTX_OP_ALLOC_CTX == 1 && AMDGPU_CTX_OP_SET_STABLE_PSTATE == 6, "vk_gpu_clock.cpp's ops");
static_assert(DRM_COMMAND_BASE == 0x40 && DRM_AMDGPU_CTX == 0x02 && DRM_IOCTL_BASE == 'd', "vk_gpu_clock.cpp's ioctl number");
static_assert(sizeof(union drm_amdgpu_ctx) == 16, "vk_gpu_clock.cpp's Ctx");
#define HAVE_AMDGPU_HEADER 1
#endif

static int failures = 0;
static void expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        failures++;
    }
}

int main() {
    using namespace gpu_clock;
    expect(steam_deck("AMD Custom GPU 0405 (RADV VANGOGH)", nullptr, true), "the Deck LCD by its name");
    expect(steam_deck("AMD Custom GPU 0932 (RADV VANGOGH)", nullptr, true), "the Deck OLED by its name");
    expect(steam_deck("AMD Radeon 780M (RADV PHOENIX)", "1", true), "SteamOS's SteamDeck=1");
    expect(!steam_deck("AMD Radeon 780M (RADV PHOENIX)", "0", true) && !steam_deck("AMD Radeon 780M (RADV PHOENIX)", nullptr, true),
           "another APU is not the Deck");
    expect(!steam_deck("AMD Radeon RX 7900 XTX (RADV NAVI31)", "1", false),
           "Steam's SteamDeck=1 on a discrete card (Gaming Mode on a desktop) is not the Deck");

    expect(deck_apu("AMD Custom GPU 0932 (RADV VANGOGH)") && !deck_apu("AMD Radeon 780M (RADV PHOENIX)") && !deck_apu(nullptr),
           "the Deck's own APU by its name only");
    Facts unset;
    unset.amd = true, unset.deck = true, unset.deck_apu = true, unset.level = "auto";
    expect(choose(unset).pstate == PEAK && looked_at(unset), "unset on the Deck's APU, its level auto: the peak by default");
    unset.level = "manual";
    expect(choose(unset).pstate == NONE, "unset on the Deck with a level someone chose: left alone");
    unset.level = nullptr;
    expect(choose(unset).pstate == NONE, "unset on the Deck, its level unread: left alone");
    Facts flagged = unset;
    flagged.deck_apu = false, flagged.level = "auto";
    expect(choose(flagged).pstate == NONE && !looked_at(flagged),
           "unset on another handheld with SteamDeck=1: not by default, nothing read");
    flagged.env = "1";
    expect(choose(flagged).pstate == PEAK && looked_at(flagged), "but RX_VK_GPU_CLOCK=1 there: the Deck's rule");
    Facts desk;
    desk.amd = true, desk.level = "auto";
    expect(choose(desk).pstate == NONE && !looked_at(desk), "unset on another AMD GPU: the driver's own, nothing read");
    unset.env = "";
    unset.level = "auto";
    expect(choose(unset).pstate == NONE && !looked_at(unset), "an empty RX_VK_GPU_CLOCK: off, on the Deck too");
    expect(!asked(nullptr) && !asked("") && !asked("0") && !asked("off") && asked("1") && asked("peak"),
           "asked: only a value other than 0 or off");

    Facts deck;
    deck.amd = true, deck.deck = true, deck.deck_apu = true, deck.level = "auto", deck.env = "1";
    expect(choose(deck).pstate == PEAK, "RX_VK_GPU_CLOCK=1, the Deck, its level auto: the peak");

    Facts chosen = deck;
    for (const char* level : {"manual", "high", "low", "profile_standard", "profile_peak", "profile_min_sclk"}) {
        chosen.level = level;
        expect(choose(chosen).pstate == NONE, "the Deck with a level someone chose: left alone");
    }
    chosen.level = nullptr;
    expect(choose(chosen).pstate == NONE, "the Deck, its level unread: left alone");

    Facts apu;
    apu.amd = true, apu.level = "auto", apu.env = "1";
    expect(choose(apu).pstate == NONE, "RX_VK_GPU_CLOCK=1 on another AMD GPU: not measured, left to the driver");

    Facts off = deck;
    for (const char* e : {"0", "off"}) {
        off.env = e;
        expect(choose(off).pstate == NONE && !looked_at(off), "RX_VK_GPU_CLOCK=0 or off: the driver's own, on the Deck too");
    }

    Facts asked = apu;
    asked.env = "peak";
    expect(choose(asked).pstate == PEAK, "RX_VK_GPU_CLOCK=peak on another AMD GPU");
    asked.env = "standard";
    expect(choose(asked).pstate == STANDARD, "RX_VK_GPU_CLOCK=standard");
    asked.level = "manual", asked.env = "peak";
    expect(choose(asked).pstate == PEAK, "asked by name: whatever the level");
    asked.env = "1";
    expect(choose(asked).pstate == NONE, "RX_VK_GPU_CLOCK=1 with a level someone chose: left alone");
    asked.env = "yes";
    expect(choose(asked).pstate == NONE, "a value it does not know: the driver's own");

    Facts nvidia;
    nvidia.deck = false, nvidia.level = "auto", nvidia.env = "peak";
    expect(choose(nvidia).pstate == NONE, "not AMD: nothing, even asked");

    expect(!strcmp(name(PEAK), "peak") && !strcmp(name(STANDARD), "standard"), "the names for the log");

    if (failures) return EXIT_FAILURE;
#if defined(HAVE_AMDGPU_HEADER) && defined(AMDGPU_HEADER_WITHOUT_PSTATE)
    std::printf("gpu clock: all checks passed (the ioctl's numbers checked against <drm/amdgpu_drm.h>, which is from before "
                "Linux 5.18: the stable power states' numbers are the kernel's, written here)\n");
#elif defined(HAVE_AMDGPU_HEADER)
    std::printf("gpu clock: all checks passed (the ioctl's numbers checked against <drm/amdgpu_drm.h>)\n");
#else
    std::printf("gpu clock: all checks passed (no <drm/amdgpu_drm.h> here: the ioctl's numbers not checked)\n");
#endif
    return EXIT_SUCCESS;
}
