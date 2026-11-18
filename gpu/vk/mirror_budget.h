/* (hookshot) How much VRAM the game's memory pools may be mirrored in (vk_memory.cpp mirror_budget), by the card. No Vulkan here.
   tests/test_mirror_budget.py */
#pragma once

#include <algorithm>
#include <cstdint>

namespace mkwvk::mirror_rule {

/// What a card counts as small: 4.5 GB or less, where the mirrors get at most 256 MB and the textures at most 2.2 GB
/// (texture_budget.h)
inline bool small_card(uint64_t vram) { return vram && vram <= (4ull << 30) + (512ull << 20); }

/// The mirrors: a quarter of the card, at most 2 GB under 15 GB and 3 GB from there, and on a card of 4.5 GB or less an eighth, at
/// most 256 MB (the Minimum (4GB) preset's). The one rule
/// for every card: no menu row or Quality preset sets them. A pool left out is read by the GPU over PCIe: on 8 GB cards, a 3070 or
/// a 4060, that left the GPU at a few percent and the frame stuttering, and on a 6 GB RTX 3060 Laptop at an eighth (768 MB) or the
/// Low preset's 512 MB, 30-32 GB of bound ranges went over PCIe every 600 submits in Hyrule Field, the GPU's frame 27 ms against
/// 19 at a quarter. The Balanced (8GB) preset's 1024 MB, what every 8 GB card started on, filled within minutes on an RTX 3060 Ti
/// and new pools went over PCIe; at a quarter (2048) none did, 37.1 -> 45.3 fps, 1% lows 16.4 -> 20.7 (Kokiri Forest, Hyrule
/// Field and the Market, 1080p, three interleaved runs each: #724). 6 GB cards had an eighth because, with a quarter, the mirrors
/// and the textures went past what the card has; the image blocks made at the start were then 896 MB of it held empty, and now
/// they are made in the textures' pool, where the textures take them (vram_compact.h blocks_at_start). The mirrors are not
/// squeezed when VRAM runs short (RX_VK_MIRROR_TIGHT is opt-in): the texture cache is. On that laptop the process then used 95%
/// of what the driver allows (82% at 512 MB, 89% at 1024), the textures it holds about the same (1.56 GB against 1.62), 39 fps
/// against 18. 2 GB is enough under 15 GB of VRAM: at 2048 no pool went over PCIe on the 3060 Ti, and High (12GB)'s 2 GB was what
/// 12 GB cards started on (a quarter, 3 GB, beside High's 7.5 GB of textures left 10 and 11 GB cards too little: auto_settings.h);
/// 10 GB cards had 2.5 GB, the renderer's own quarter. Ultra (16GB+)'s 3 GB stays from 15 GB. A small card keeps Minimum's 256 MB
/// (an eighth of a smaller one), what every such card started on (Auto (this PC) at Minimum)
inline uint64_t auto_bytes(uint64_t vram) {
    if (!vram) return 3072ull << 20;
    if (small_card(vram)) return std::min<uint64_t>(vram / 8, 256ull << 20);
    return std::min<uint64_t>(vram / 4, vram < (15ull << 30) ? 2048ull << 20 : 3072ull << 20);
}

}  // namespace mkwvk::mirror_rule
