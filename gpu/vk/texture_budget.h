/* (hookshot) How much VRAM the texture cache may hold (vk_texture.cpp texture_frame), by the card: the one rule for every card,
   with no menu row and no preset over it. No Vulkan here. tests/test_texture_budget.py */
#pragma once

#include <algorithm>
#include <cstdint>

#include "mirror_budget.h"

namespace mkwvk::texture_rule {

constexpr uint64_t kMB = 1ull << 20;

/// A dedicated card's textures, by the card's own memory: 7/12 of it, or all but 5 GB where that is more, at most 11 GB, at most
/// 2.2 GB on a card of 4.5 GB or less (mirror_rule::small_card), and at most 75% of what the driver allows the game at the first
/// look. These are the sizes the Quality presets gave the cards they were for, which every card started on (Auto (this PC) at its
/// tier): Minimum's 2.2 GB on 4 GB, Low's 3.6 on 6 (3.5), Balanced's 4.8 on 8 (4.67), High's 7.5 on 12 (7), Ultra's 11 on 16; and
/// 6 GB on 10 GB, what the renderer's own rule gave those (5.8). The rest of the game's VRAM (render targets, mirrors, buffers,
/// pipelines) is about the same on every card, ~3.5-3.8 GB in Hyrule Field, so a share alone could not be every preset's: 65% of
/// the allowance was 9.75 GB on 16 GB, and 5.1 GB on an 8 GB card whose driver allows nearly all of it, where 5.1 GB had the
/// driver page VRAM out for good (an RTX 3060 Ti at 14 fps). By the card, not the allowance, the size is the same on Windows and
/// Linux. The 75% is the presets' own clamp, for a card other programs already fill. Under 12 GB of RAM, on a card past Low
/// (6GB)'s 6.75 GB, the renderer's rule from before the presets: 45% of the allowance up to 8.5 GB, else 70%, at most 6 GB
/// (auto_settings.h held such a PC at Low for the smaller budgets, and a Low preset gave its own sizes only up to 6.75 GB). The
/// cache shrinks below its size near the driver's limit whatever it is (texture_frame's 90% and 97% rules). Without the card's
/// size (no device-local heap), 4 GB
inline uint64_t dedicated_bytes(uint64_t allowed, uint64_t vram, uint64_t ram) {
    if (ram && ram < 12288 * kMB && vram > 6912 * kMB)
        return allowed ? std::min<uint64_t>(allowed / 100 * (allowed <= 8704 * kMB ? 45 : 70), 6144 * kMB) : 4096 * kMB;
    if (!vram) return 4096 * kMB;
    uint64_t b = std::max<uint64_t>(vram / 12 * 7, vram > 5120 * kMB ? vram - 5120 * kMB : 0);
    b = std::min<uint64_t>(b, 11000 * kMB);
    if (mirror_rule::small_card(vram)) b = std::min<uint64_t>(b, 2200 * kMB);
    if (allowed) b = std::min<uint64_t>(b, allowed / 4 * 3);
    return b;
}

/// An integrated GPU's share of the allowance, before texture_frame's caps by the system's RAM (2.5 GB with 16 GB, the Steam
/// Deck's): 45% of it up to 8.5 GB, else 70%, at most 6 GB, as before; and Minimum's 2.2 GB where the GPU's heap is 4.5 GB or
/// less, as the preset every integrated GPU started on gave it there. Its memory is the system's, which the game shares
/// (vk_texture.cpp)
inline uint64_t integrated_bytes(uint64_t allowed, uint64_t vram) {
    if (!allowed) return 4096 * kMB;
    uint64_t b = std::min<uint64_t>(allowed / 100 * (allowed <= 8704 * kMB ? 45 : 70), 6144 * kMB);
    if (mirror_rule::small_card(vram)) b = std::min<uint64_t>(b, 2200 * kMB);
    return b;
}

}  // namespace mkwvk::texture_rule
