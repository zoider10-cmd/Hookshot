/* The Insert menu's Shadow resolution: the sun's cascades at the game's own larger sizes. nx2/oot_shadow.py calls this
   after the game has chosen this frame's cascade size and rounded it to a multiple of 8, before it stores the size.

   The sizes are the game's: at the quality level it runs at its table holds 1600, the size it uses, and 2200, the
   largest of that level's entries; 3072 is its highest level's. Only the sun's shadow object is changed. The size is raised, never lowered, so a
   frame where the game asks for more keeps the game's. Nothing is written to the game's memory: Game's gives the
   game's size again from the next frame. */
#include "hos.h"
#include "../gpu/vk/vk_api.h"

int rx_option(int id, int otherwise);

void hos_oot_shadow(Ctx *c, uint64_t shadow) {
    const int choice = rx_option(HOS_OPT_SHADOW_RES, 0);
    if (choice < 1 || choice > 2 || !shadow) return;
    if (recomp_load64(c, shadow) != 0x84baa0a8ULL) return;   /* the sun's shadow object */
    const uint32_t size = choice == 1 ? 2200 : 3072;
    if ((uint32_t)c->x[23] < size) c->x[23] = size;   /* w23: the rounded size */
}
