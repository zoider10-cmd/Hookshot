# Built-in performance monitor porting notes

The monitor is intentionally self-contained in:

- `gpu/vk/perf_monitor.h`
- `gpu/vk/perf_monitor.cpp`

A later Mako build normally needs only these integration points:

1. Add a saved `resource_monitor` option and a Gameplay menu row in `vk_menu.h` / `vk_menu.cpp`.
2. Forward the existing game-frame notification to `perf_monitor_note_frame(game_frame)`.
3. Forward each completed Vulkan recording's timestamp duration to `perf_monitor_note_gpu_time(ns)`.
4. Give the monitor one keyed bitmap/upload slot, call `perf_monitor_sample()` from the menu tick, render with
   `perf_monitor_paint`, and copy the bitmap near the left edge during `menu_record`.

The module itself owns process CPU/RAM sampling, Vulkan VRAM sampling, rolling game FPS/frame time, GPU-time aggregation,
and the red rectangle UI. Keeping those details out of `vk_menu.cpp` is what makes the feature portable between Mako releases.

Current overlay order:

1. CPU Usage
2. Frame Time
3. Graphics VRAM
4. GPU Time
5. RAM
6. Framerate

Current position is 12 px from the left and 260 px from the top at 720p-scale output; Mako's existing UI scale multiplies it at
higher output sizes.
