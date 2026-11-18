// (hookshot) The Intel shader compiles row's Auto: where Intel's Windows compiler is entered side by side without being asked.
//
// IntelDriverGate (vk_internal.h) lets one thread at a time into igvk64's compiler because it faulted with two in it on an
// Arc A750 and a UHD. On the Arc B-series (Battlemage, PCI device 0xE2xx) with driver 32.0.101.9154 that cost minutes at
// every area's first visit and its reason did not show: run on a B580 (0xE20B, a Core i5-13600K, six background workers),
// a first visit froze the picture for 248 s in Hyrule Field (398 programs) and 409 s in the Market (322) with one thread
// in the compiler; side by side, over three launches and ten other areas, 1,111 programs were first compiled with no
// frame under 5 fps, each area steady in 20 to 80 s, and no fault, device loss or exit. So Auto is side by side on that
// family from the driver that was run, and one at a time on every other Intel GPU, as before: nothing was measured there.
#pragma once

#include <cstdint>

/// Whether the row's Auto means side by side on this Intel GPU and Windows driver (deviceID, driverVersion as Vulkan
/// reports them: Intel's Windows driverVersion is major << 14 | minor, 101 << 14 | 9154 for 32.0.101.9154)
inline bool intel_side_by_side_measured(uint32_t device, uint32_t version) {
    return (device & 0xFF00u) == 0xE200u && version >= (101u << 14 | 9154u);
}

/// The row's value (0 Auto, 1 Side by side, 2 One at a time) as the choice for this GPU
inline bool intel_side_by_side_chosen(int row, uint32_t device, uint32_t version) {
    return row == 1 || (row == 0 && intel_side_by_side_measured(device, version));
}
