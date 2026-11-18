// The output-stage CRT raster, independent of the game's render resolution and Vulkan.
#pragma once

#include <algorithm>
#include <cstdint>

namespace mkwvk::crt_policy {

constexpr bool enabled(int filter, bool native_pq) {
    return filter >= 1 && filter <= 4 && !native_pq;
}

struct Raster { uint32_t w, h; };

constexpr Raster raster(uint32_t output_w, uint32_t output_h, int choice) {
    if (!output_w || !output_h) return {};
    constexpr uint32_t lines[] = {240, 480, 720};
    // Two output pixels per virtual line at least: higher requested line counts on small outputs alias.
    const uint32_t h = std::min(lines[std::clamp(choice, 0, 2)], std::max(1u, output_h / 2));
    const uint32_t w = std::max(1u, (uint32_t)(((uint64_t)output_w * h + output_h / 2) / output_h));
    return {w, h};
}

} // namespace mkwvk::crt_policy
