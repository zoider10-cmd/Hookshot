// The render target pool's bound by default (vk_texture.cpp pool_cap): a twelfth of what the driver allows the process, from 256 MB
// to 768 MB. OoT makes its transient targets (a 384 x 384 depth target, 1280 x 720, 640 x 360 and 2560 x 1440 ones) at shifted
// offsets of a scratch heap every frame; a dead one is reusable a frame or two after it is let go, once the GPU is done with it, so
// the pool has to hold two or three frames of them. At 256 MB it held less than that at 2560 x 1440: in Castle Town's market at
// night it destroyed ~22,000 images in 100 s for being over its bound and the replay made as many again, two a frame (vkDestroyImage
// and vmaCreateImage ~20 % of the render thread). On a small card a twelfth stays near the old 256 MB.
#pragma once

#include <algorithm>
#include <cstdint>

namespace mkwvk::target_pool {

inline constexpr uint64_t kMinMB = 256, kMaxMB = 768;

/// The default bound in MB for a driver allowance of `allowed` bytes (0: not known, the minimum)
inline uint64_t default_mb(uint64_t allowed) {
    if (!allowed) return kMinMB;
    return std::clamp<uint64_t>((allowed >> 20) / 12, kMinMB, kMaxMB);
}

}  // namespace mkwvk::target_pool
