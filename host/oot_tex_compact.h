/* (hookshot) The texture data heap's compaction, asked for once in a while and not at every frame. nx2/oot_patches.py hooks
   the place; host/oot_tex_compact.c holds the state and reads the switch.

   The game keeps its textures' storage in one heap (2,400 MB; in Castle Town's market it stays at its line of 5 % free). Its
   manager's per-frame step (f_80797240) asks the heap's Compaction thread for a round whenever none is running (the manager's
   flag bit 1, which its setup always sets), and each texture a round moved is finalized and made again at its new address
   (f_80797da0). On the console that is a copy and a new texture object. Here each texture made again is a new one to the
   renderer: its storage hashed to find the image it had, an image made and that one's copied in, and the bytes the game moved
   synced to the mirrors. Standing in the market that was a batch of about 23 textures (10 MB) every 9 frames or so, 3 to 5 ms in
   that frame, and those frames were the long ones.

   With a gap (a second, unless HOS_TEX_COMPACT_MS says otherwise), the manager asks for a round only when the last one it
   asked for is that long ago: the heap is still compacted, less often. The round itself is the game's, untouched: what it
   moves, how much, and how its textures are made again.

   gap_ns: 0, every frame no round is running, as the game has it; below 0, never; else at least that long from one round's
   start to the next. now_ns: any clock that does not go back. */
#ifndef OOT_TEX_COMPACT_H
#define OOT_TEX_COMPACT_H
#include <stdint.h>

typedef struct {
    int64_t last_ns;   /* (when the last round was asked for) */
    int asked;         /* (one was: last_ns holds a time) */
} OotTexCompact;
#define OOT_TEX_COMPACT_INIT {0, 0}

/* Whether the manager may ask for a round now; a yes is taken as asked */
static inline int oot_tex_compact_due(OotTexCompact *s, int64_t gap_ns, int64_t now_ns) {
    if (gap_ns == 0) return 1;
    if (gap_ns < 0) return 0;
    if (s->asked && now_ns - s->last_ns < gap_ns) return 0;
    s->asked = 1, s->last_ns = now_ns;
    return 1;
}

/* The switch's value as a gap: not set or empty, dflt_ms; a whole number of milliseconds (0: the game's own); "off" or
   "never" or a negative number: never; anything else: dflt_ms */
static inline int64_t oot_tex_compact_gap_ns(const char *value, int64_t dflt_ms) {
    if (value && *value) {
        if ((value[0] == 'o' && value[1] == 'f' && value[2] == 'f' && !value[3]) ||
            (value[0] == 'n' && value[1] == 'e' && value[2] == 'v' && value[3] == 'e' && value[4] == 'r' && !value[5]))
            return -1;
        int neg = 0;
        const char *p = value;
        if (*p == '-') neg = 1, p++;
        int64_t v = 0;
        int digits = 0;
        for (; *p >= '0' && *p <= '9' && v < 1000000000; p++) v = v * 10 + (*p - '0'), digits++;
        if (digits && !*p) return neg && v ? -1 : v * 1000000;
    }
    return dflt_ms < 0 ? -1 : dflt_ms * 1000000;
}
#endif
