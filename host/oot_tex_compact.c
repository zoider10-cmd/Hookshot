/* (hookshot) The texture data heap's compaction asked for once in a while: the lifted f_80797240 calls
   hos_oot_tex_compact_due where the game asks for a round (nx2/oot_patches.py patch_tex_compact); host/oot_tex_compact.h
   has why and the rule.
   HOS_TEX_COMPACT_MS=<ms>: at least that long between two rounds (1000 with no switch); 0: at every frame, as the game has
   it; off: never. From Longshot 7b229f6. */
#include "hos.h"
#include "oot_tex_compact.h"
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdlib.h>

/* (the gap with no switch. Standing in Castle Town's market, 9950X3D and RTX 4070 SUPER, two runs a setting: frames of 16.7 ms
   or more 11.0 and 9.8 % at every frame, 1.4 and 1.4 % at 1000, 1.7 and 1.3 % at 3000, 3.0 and 1.2 % never. 1000 keeps the
   heap compacted, 50 to 88 rounds in those runs, for the same frames as never) */
#define OOT_TEX_COMPACT_DEFAULT_MS 1000

static OotTexCompact compact = OOT_TEX_COMPACT_INIT;
static SRWLOCK compact_lock = SRWLOCK_INIT;   /* (the manager's step runs under its own lock; this does not rely on it) */
static int64_t compact_gap = INT64_MIN;       /* (read once, under compact_lock) */
static long long compact_calls, compact_yes;  /* (under compact_lock: the log's counts) */

int hos_oot_tex_compact_due(void) {
    const int64_t now = hos_now_ns();
    AcquireSRWLockExclusive(&compact_lock);
    if (compact_gap == INT64_MIN) {
        compact_gap = oot_tex_compact_gap_ns(getenv("HOS_TEX_COMPACT_MS"), OOT_TEX_COMPACT_DEFAULT_MS);
        if (compact_gap < 0)
            hos_log("tex: the game's texture heap is never compacted (HOS_TEX_COMPACT_MS=off; 0: at every frame, the game's own)");
        else if (compact_gap > 0)
            hos_log("tex: the game's texture heap is compacted at most every %lld ms (HOS_TEX_COMPACT_MS; 0: at every frame, "
                    "the game's own; off: never)", (long long)(compact_gap / 1000000));
    }
    const int due = oot_tex_compact_due(&compact, compact_gap, now);
    compact_calls++, compact_yes += due;
    /* (with a gap, every 3,600 asks: how many rounds the manager was let ask for) */
    if (compact_gap != 0 && compact_calls % 3600 == 0)
        hos_log("tex: the game's texture heap: %lld compaction rounds asked for in %lld frames without one running",
                compact_yes, compact_calls);
    ReleaseSRWLockExclusive(&compact_lock);
    return due;
}
