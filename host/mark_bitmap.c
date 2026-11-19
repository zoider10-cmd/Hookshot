/* (Longshot 35a4a9fc, #1617) The pages the GPU can read, a bit each, for the lifted code's page marks (build.py RX_MARK_BITMAP, nx2/rtgen.py
   A64_MARK_BITMAP): a store marks its pages only if its first byte is on one (the page before each mapping counts as one). The renderer reads the marks of GPU pages
   only, and OoT's GPU pools lie in the heap among its CPU data; a no-marks timing build ran the game's threads 2.2-2.7 ms a
   frame faster when moving (the chain run: that time is on the frame's critical path). A page's bit is set when a GPU mapping
   covering it is made (nvdrv.c map_add: here every mapping's guest pages, whatever its GPU address; Longshot
   sets them only where the two are equal), before the mapping counts, and is never cleared: a page once GPU memory is marked
   for good, the same as without the bitmap. Writes made before the mapping need no mark: the renderer imports a new pool's
   memory as it is.
   16 MB of zeroed static data for the 512 GB window, only the heap's part ever touched (~210 KB). HOS_MARK_BITMAP_ALL=1 sets
   every bit at the start: every store marks, as without the bitmap, plus the test's cost (the control of an A/B). */
#include "hos.h"
#include <stdlib.h>
#include <string.h>

#ifndef A64_DIRTY_PAGES
#define A64_DIRTY_PAGES (1ull << 27)
#endif
uint8_t a64_gpu_pages[A64_DIRTY_PAGES / 8];

__attribute__((constructor)) static void gpu_pages_all(void) {
    const char *e = getenv("HOS_MARK_BITMAP_ALL");
    if (e && atoi(e)) memset(a64_gpu_pages, 0xff, sizeof a64_gpu_pages);
}

void hos_gpu_pages_set(uint64_t guest, uint64_t size) {
    if (!size) return;
    /* (and the page before: the lifted code tests a store's first byte only, and a store from there may cross into this one) */
    uint64_t p = guest >> 12 ? (guest >> 12) - 1 : 0;
    const uint64_t end = (guest + size + 0xFFF) >> 12;
    for (; p < end; p++) {
        const uint64_t i = p & (A64_DIRTY_PAGES - 1);
        __atomic_fetch_or(&a64_gpu_pages[i >> 3], (uint8_t)(1u << (i & 7)), __ATOMIC_RELEASE);
    }
}
