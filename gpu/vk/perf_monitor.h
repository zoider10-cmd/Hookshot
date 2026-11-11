// Built-in Mako performance monitor.
// Kept as a small module so later Mako versions only need the menu/draw, frame, and GPU-time hooks.
#pragma once

#include <cstdint>
#include "vk_paths.h"

namespace mkwvk {

// Lightweight hooks. These may stay active while the overlay is hidden.
void perf_monitor_note_frame(bool game_frame);
void perf_monitor_note_gpu_time(uint64_t ns);

// Samples process/GPU memory and rolling frame statistics. True when the displayed values changed.
bool perf_monitor_sample();

// Red left-side rectangle overlay. The caller owns the bitmap/upload path.
uint32_t perf_monitor_width(int scale);
uint32_t perf_monitor_height(int scale);
void perf_monitor_paint(HDC dc, uint32_t w, uint32_t h, int scale);

} // namespace mkwvk
