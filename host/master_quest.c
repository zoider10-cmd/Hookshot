/* (Mako) Master Quest mode: hookshot_options.ini's master_quest=1 (the launcher's Master Quest row), or HOS_MASTER_QUEST=1 / 0.
   Read once at the start, so a whole run is one mode.
   - the title logo: host/prompts.c serves the Master Quest one (prompts/mq/, made by nx2/mq_logo.py at build time);
   - the damage Link takes: master_quest_damage=2 (default) or 3, 4 times the game's (HOS_MASTER_QUEST_DAMAGE too), through
     the life write nx2/oot_patches.py patch_life hooks (hos_oot_life_damage). The hearts cheat (Debug tab) still wins. */
#include "hos.h"
#include "hos_paths.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

static volatile LONG mq_on = -1, mq_damage = 1;

static void mq_read(void) {
    int on = 0, damage = 2;
    char path[MAX_PATH], line[96];
    const DWORD len = hos_game_path_a(path, MAX_PATH);
    char *slash = len ? (strrchr(path, 92) ? strrchr(path, 92) : strrchr(path, 47)) : NULL;   /* (linux: '/') */
    FILE *f = NULL;
    if (slash) {
        snprintf(slash + 1, sizeof path - (size_t)(slash + 1 - path), "hookshot_options.ini");
        f = fopen(path, "r");
    }
    if (f) {
        while (fgets(line, sizeof line, f)) {
            if (!strncmp(line, "master_quest=", 13)) on = atoi(line + 13) != 0;
            else if (!strncmp(line, "master_quest_damage=", 20)) damage = atoi(line + 20);
        }
        fclose(f);
    }
    const char *e = getenv("HOS_MASTER_QUEST");
    if (e && *e) on = atoi(e) != 0;
    e = getenv("HOS_MASTER_QUEST_DAMAGE");
    if (e && *e) damage = atoi(e);
    if (damage < 1) damage = 1;
    if (damage > 4) damage = 4;
    InterlockedExchange(&mq_damage, on ? damage : 1);
    if (InterlockedCompareExchange(&mq_on, on, -1) == -1)
        hos_log("master quest: %s%s", on ? "on" : "off", on ? (damage == 1 ? ", normal damage" : damage == 2 ? ", double damage" :
                                                                damage == 3 ? ", triple damage" : ", 4x damage") : "");
}

int hos_master_quest(void) {
    if (mq_on < 0) mq_read();
    return (int)mq_on;
}

/* The saves' folder under user\: Master Quest has its own (save_mq), never mixed with the normal game's (save) */
const char *hos_save_dir(void) { return hos_master_quest() ? "save_mq" : "save"; }

/* nx2/oot_patches.py patch_life: Link's life going from old to new (a hit, a fall, lava...), the value to write instead: the
   hearts cheat keeps it, Master Quest multiplies the loss. Retried compare-and-swaps come back with the fresh old value, so a
   loss is multiplied once */
uint64_t hos_oot_life_damage(uint32_t old, uint32_t now) {
    int hos_oot_hearts_enabled(void);
    if (hos_oot_hearts_enabled()) return old;
    if (!hos_master_quest() || mq_damage <= 1 || now >= old) return now;
    const uint64_t loss = (uint64_t)(old - now) * (uint64_t)mq_damage;
    const uint64_t left = loss < old ? old - loss : 0;
    static volatile LONG logged;
    if (InterlockedIncrement(&logged) <= 20) hos_log("master quest: Link's life %u -> %u (x%d: %u)", old, now, (int)mq_damage, (unsigned)left);
    return left;
}
