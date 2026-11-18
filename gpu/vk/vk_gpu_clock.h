// (hookshot) The GPU's clock on the Steam Deck (vk_gpu_clock.cpp; the rules: gpu_clock.h): amdgpu's stable power state, asked
// by an amdgpu context of the renderer's own and held while the game runs.
#pragma once

namespace mkwvk {

/// Once, after the device is made: when RX_VK_GPU_CLOCK asks for it, read the device's power level and, where gpu_clock::choose
/// says so, hold amdgpu's stable power state until the game ends (Linux; elsewhere nothing). drm: the device has
/// VK_EXT_physical_device_drm, which says which render node is its own. One log line either way on an AMD GPU when asked
void gpu_clock_device_created(bool drm);

} // namespace mkwvk
