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
// How long an image waits in the pool for the next target of its shape, in presents (RX_VK_POOL_IDLE). The dead targets come
// back to the pool every present (dead_targets.h), and a shape the game makes every frame is taken again within a present or two.
// One that waits longer is a shape that is not coming back: OoT gives each character near the camera a depth map whose side it
// computes anew every frame (397, 439, 479 ...), each a pool key of its own. At 120 presents those filled the pool to its bound.
inline constexpr uint64_t kIdlePresents = 8;

/// The default bound in MB for a driver allowance of `allowed` bytes (0: not known, the minimum)
inline uint64_t default_mb(uint64_t allowed) {
    if (!allowed) return kMinMB;
    return std::clamp<uint64_t>((allowed >> 20) / 12, kMinMB, kMaxMB);
}

/// Whether an image put into the pool at present `since` has waited too long at present `now`
inline bool idle_out(uint64_t now, uint64_t since, uint64_t idle) { return now - since > idle; }

}  // namespace mkwvk::target_pool
