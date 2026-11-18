/* The storage reserved for a character's shadow map (nvn_native.c nvnTextureBuilderGetStorageSize and ...Alignment).
   tests/test_shadow_slot.py

   OoT gives each shadow-casting character near the camera a square depth map (NVN format 0x34, one level) whose side it
   computes anew every frame from the camera's distance: 384 from far, more from near, a few pixels different each frame while
   either moves (397, 439, 479 ...). It makes a frame's render targets one after another in a first-fit heap, asking the size
   and alignment of each here: a map a few pixels larger pushed every target made after it to a new address, each a new
   texture for the game (initialized, registered) and a new image for the renderer. In Castle Town's market with the camera
   turning that was 15-16 textures made a frame.

   Such a map is answered the storage size and alignment of the next multiple of a step up (HOS_SHADOW_BUCKET, 384: sides
   768, 1152, 1536, 1920), so the targets after it stay where they are until the map crosses a step. Only the bytes the game
   sets aside change, by less than one step's worth for each such map (1.8 MB at the first step; the heap is 512 MB or more,
   nn_applet.c hos_rt_pool_size): the texture keeps its own size and layout, and nothing is drawn or sampled differently. */
#ifndef HOS_SHADOW_SLOT_H
#define HOS_SHADOW_SLOT_H

#include <stdint.h>

enum { HOS_SHADOW_SLOT_STEP = 384, HOS_SHADOW_SLOT_FORMAT = 0x34, HOS_SHADOW_SLOT_MAX = 1920 };

/* The side whose storage a texture of this description reserves: the next multiple of step from its own for a square
   two-dimensional one-level depth map wider than 384 and up to 1920 (five steps of 384), never more than that; 0: its own
   (not such a map, or step 0: the switch off) */
static inline uint32_t hos_shadow_slot_side(int is_2d, int format, uint32_t levels, uint32_t depth, uint32_t width, uint32_t height,
                                            uint32_t step) {
    if (!step || !is_2d || format != HOS_SHADOW_SLOT_FORMAT || levels != 1 || depth > 1 || width != height || width <= 384 ||
        width > HOS_SHADOW_SLOT_MAX)
        return 0;
    const uint32_t side = (width + step - 1) / step * step;
    return side > HOS_SHADOW_SLOT_MAX ? HOS_SHADOW_SLOT_MAX : side;
}

#endif
