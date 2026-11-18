/* (EvilOOT, 11-06) Stand-ins for the WebGPU renderer (gpu/render, its functions once renamed wgr_*), which is built no
   more: the Vulkan back end in hookshot_vk.dll is the only renderer (host/rx_backend.c). host/rx_backend.c and nn_hid.c
   still name these functions, and the Windows executable is linked with them, as the Linux one is with
   host/posix/linux_stubs.c. None of the wgr_* calls is made while the Vulkan back end runs; wgr_start fails, so a
   missing or unusable hookshot_vk.dll shows as "no renderer" instead of a game that runs with nothing drawn. */
#include "hos.h"
#include <stdint.h>

int wgr_start(void *hwnd) {
    (void)hwnd;
    hos_log("rx: no WebGPU renderer in this build: only the Vulkan back end (hookshot_vk.dll) draws");
    return 0;
}
void wgr_resize(int width, int height) { (void)width, (void)height; }
const char *wgr_describe(void) { return "none"; }
void wgr_stats(int64_t *draws, int64_t *skipped, int64_t *pipelines) {
    if (draws) *draws = 0;
    if (skipped) *skipped = 0;
    if (pipelines) *pipelines = 0;
}
void wgr_nvn_submit(const uint64_t *handles, int n) { (void)handles, (void)n; }
uint64_t wgr_nvn_fence(void) { return 0; }
uint64_t wgr_nvn_pushed(void) { return 0; }
uint64_t wgr_nvn_replayed(void) { return 0; }
int wgr_nvn_wait(uint64_t fence, uint64_t timeout_ns) { (void)fence, (void)timeout_ns; return 1; }
void wgr_wait_writebacks_reading(const void *p, uint64_t n) { (void)p, (void)n; }
void wgr_nvn_finish(void) {}
void wgr_nvn_present(const void *t, const int crop[4]) { (void)t, (void)crop; }
void wgr_nvn_register_texture(int id, const void *t, const void *v) { (void)id, (void)t, (void)v; }
void wgr_nvn_register_sampler(int id, const void *p) { (void)id, (void)p; }
void wgr_nvn_set_texture_pool_size(int n) { (void)n; }
void wgr_nvn_texture_released(const void *t) { (void)t; }
void wgr_nvn_program_released(const void *p) { (void)p; }
void wgr_nvn_read_texels(const void *t, unsigned level, unsigned layer0, const void *r, uint8_t *dst, uint64_t row,
                         uint64_t img) {
    (void)t, (void)level, (void)layer0, (void)r, (void)dst, (void)row, (void)img;
}
void wgr_nvn_write_texels(const void *t, unsigned level, unsigned layer0, const void *r, const uint8_t *src,
                          uint64_t row, uint64_t img) {
    (void)t, (void)level, (void)layer0, (void)r, (void)src, (void)row, (void)img;
}
void wgr_nvn_invalidate(uint64_t gpu, uint64_t size) { (void)gpu, (void)size; }
/* (gpu/render/rx_core.cpp's, for the soft write watch's other consumer: nothing tracked, as on Linux) */
uint32_t *rx_collect_written(int64_t *count) { *count = -1; return NULL; }

/* the live-input file's !commands that only the WebGPU renderer implemented (nn_hid.c) */
void rx_request_frame_dump(void) { hos_log("rx: !dump was the WebGPU renderer's: not in this build (Vulkan: RX_VK_DUMP)"); }
void rx_set_screenshot_ms(int64_t ms) { (void)ms; hos_log("rx: !shots was the WebGPU renderer's: not in this build (Vulkan: RX_VK_SHOTS)"); }
void rx_request_rdoc_capture(int frames) { (void)frames; hos_log("rx: !rdoc was the WebGPU renderer's: not in this build"); }
void rx_flash_dark_arm(void) { hos_log("rx: !flasharm was the WebGPU renderer's: not in this build (Vulkan: RX_VK_FLASH)"); }
