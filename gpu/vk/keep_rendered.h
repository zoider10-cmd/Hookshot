// How long a texture the GPU drew, unused, stays before the eviction pass lets it go (vk_texture.cpp).
// tests/test_keep_rendered.py
#pragma once
#include <algorithm>
#include <cstdint>

namespace keep_rendered {

// Presents unused: 3600 (a minute; a course left behind goes, the game draws it again when it comes back), 600 near what
// the driver allows the process. "Near" is the budget's own line, 97% of it: AMD's driver reports the process's use of the
// device heap at most at what it allows (7244 of 7244 MB while VMA held 7861 MB of blocks), so "past what it allows" never
// held on AMD and the rendered textures stayed 3600 presents with the VRAM full and the driver paging. over_only: as before
inline uint64_t presents(bool known, uint64_t used, uint64_t allowed, bool over_only) {
    if (!known) return 3600;
    const bool near_limit = over_only ? used > allowed : used >= allowed / 100 * 97;
    return near_limit ? 600 : 3600;
}

// The same wait under 60 fps (fps: the presents a second lately; 0: not known): as many presents as it is seconds at 60 fps,
// never fewer than kFloor. Counted as presents a minute was 17 at 3.5 fps (a UHD Graphics laptop, whose 1,776 MB of textures
// were 1,011 MB rendered, 47 MB of it used in the last 8 presents). kFloor: the game samples some textures the GPU drew every
// so many of its own frames (a 260 x 260 terrain normal map every 40), and one let go between two samples came back empty
inline constexpr uint64_t kFloor = 120;
inline uint64_t at_rate(uint64_t keep, double fps) {
    if (!(fps > 0) || fps >= 60) return keep;
    return std::max<uint64_t>((uint64_t)((double)keep * std::max(fps, 2.0) / 60.0), std::min(keep, kFloor));
}

} // namespace keep_rendered
