/* (OoT randomizer) The seed the game was started with: the launcher's Randomizer page keeps its settings in
   hookshot_options.ini (the Insert menu had a Randomizer tab too, until Mako 3.3's menu; it keeps the lines when it saves) (gpu/vk/oot_rando.h has the lines and the seed IDs). They are read
   once here, at the start, so a change made while playing is the next start's. HOS_RANDO_SEED_ID=<seed ID> (test
   runs) is used in place of the file's seed. The log names the seed ID, so a report's log is enough to play the same
   seed.

   Nothing here moves an item. Chests are placed outside the game: tools/rando/rando_seed.py reads the same settings
   and writes the seed as a RomFS mod (mods\rando-seed: changed map files and the size table), which mods.c loads.
   tools/rando/README.md says how that works and what it showed. hos_rando() is where the game side can ask what the
   seed shuffles, for what a mod file cannot do. Still to come:
   - the rules for which places can be reached with which items, so that every seed can be finished;
   - Gold Skulltulas, Heart Pieces, shops, songs and what characters give: none of them names its item in a map
     file. The game gives those through its event flows and the pouch (OneShotAddOrRemovePouchContent, f_828d4a70:
     host/hos_main.c oot_pouch_change calls it for the Cheats page). */
#include "hos.h"
#include "hos_paths.h"
#include "../gpu/vk/oot_rando.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>   /* (the game's folder) */

static OotRando rando;
static int rando_active;

/* The seed's settings while the randomizer is on, or NULL: the game as shipped */
const OotRando *hos_rando(void) { return rando_active ? &rando : NULL; }

/* The randomizer is on (hos_main.c hos_oot_pouch_add: the Bomb Bag the game gives with bombs is kept back) */
int hos_rando_on(void) { return rando_active; }

/* Progressive items: on with the randomizer (hos_main.c hos_oot_pouch_add) */
int hos_rando_progressive(void) { return rando_active && rando.v[OOT_RANDO_PROGRESSIVE] != 0; }
/* Skip cutscenes: on with the randomizer (hos_main.c oot_skip_cutscene) */
int hos_rando_skip_cutscenes(void) { return rando_active && rando.v[OOT_RANDO_SKIP_CUTSCENES] != 0; }

/* The seed's settings as the options file beside the game has them, HOS_RANDO_SEED_ID over them. say: what could not be
   loaded goes to the log */
static void rando_read(OotRando *r, int say) {
    memset(r, 0, sizeof *r);
    char path[MAX_PATH];
    const DWORD n = hos_game_path_a(path, MAX_PATH);
    char *slash = n ? (strrchr(path, 92) ? strrchr(path, 92) : strrchr(path, 47)) : NULL;   /* (linux: '/') */
    if (slash) {
        snprintf(slash + 1, (size_t)(path + MAX_PATH - slash - 1), "hookshot_options.ini");
        FILE *f = fopen(path, "r");
        if (f) {
            const char *bad = NULL;
            if (oot_rando_read(f, r, &bad) < 0 && say) hos_log("rando: the rando_import line was not loaded: %s", bad);
            fclose(f);
        }
    }
    const char *env = getenv("HOS_RANDO_SEED_ID");
    if (env) {
        const char *bad = oot_rando_from_id(env, r);
        if (bad && say) hos_log("rando: HOS_RANDO_SEED_ID was not loaded: %s", bad);
    }
}

/* The folder of <user> the game's saves are in: "save", or "save_rando" while the randomizer is on, so that a seed's
   saves and the game's own are apart: a save made in a seed, loaded with the randomizer off, is a game whose chests
   are not the ones it was played with. Decided once, at the first ask, and the same until the game ends: hos_main.c's
   SAVE FOLDER import asks before hos_rando_init, so this reads the options file itself */
const char *hos_save_folder(void) {
    static int on = -1;
    if (on < 0) {
        OotRando r;
        rando_read(&r, 0);
        on = r.on != 0;
    }
    /* (Mako 3.5) Master Quest keeps its saves apart too (master_quest.c: save_mq), and comes first: it is a game of its own,
       started from its own button, whatever the randomizer's switch says */
    int hos_master_quest(void);
    /* (Mako 4.0) and the launcher's Test my PC, HOS_BENCH=1: the copy it made of the saves (user\save_bench, master_quest.c
       hos_save_dir), whatever game is set: a test run never writes the player's own, the randomizer's neither */
    static int bench = -1;
    if (bench < 0) { const char *e = getenv("HOS_BENCH"); bench = e && *e && *e != '0'; }
    if (bench) return "save_bench";
    if (hos_master_quest()) return "save_mq";
    return on ? "save_rando" : "save";
}

/* hos_main.c, once at the start */
void hos_rando_init(void) {
    OotRando r;
    rando_read(&r, 1);
    if (!r.on) return;
    /* (Master Quest is a game of its own: its saves are its own, the seed is left out (mods.c), and nothing of the
       randomizer is on in it, whatever the switch says. The launcher's Master Quest leaves the switch as it was, so
       it was on there: Progressive items, Skip cutscenes, the Bomb Bag kept back and the Tracker's record) */
    /* (and in the launcher's Test my PC: it plays a copy of the saves by itself, as the game shipped) */
    if (!strcmp(hos_save_folder(), "save_bench")) {
        hos_log("rando: off in the launcher's test run (HOS_BENCH)");
        return;
    }
    int hos_master_quest(void);
    if (hos_master_quest()) {
        hos_log("rando: off in Master Quest (the randomizer's switch is on: it is for the normal game's dungeons)");
        return;
    }
    rando = r;
    rando_active = 1;
    char id[OOT_RANDO_ID_TEXT];
    oot_rando_id(&r, id);
    hos_log("rando: seed ID %s (chests are placed by the mod rando_seed.py makes at the launcher's Play, mods\\rando-seed; the other settings are not placed yet)", id);
    hos_log("rando: saves are in <user>\\%s, apart from the game's own (<user>\\save)", hos_save_folder());
    char line[256];
    size_t used = 0;
    for (int i = 0; i < OOT_RANDO_N; i++) {   /* (several short lines: the log cuts long ones) */
        const OotRandoSetting *s = &oot_rando_settings[i];
        used += (size_t)snprintf(line + used, sizeof line - used, "%s%s: %s", used ? ", " : "", s->label, s->choices[r.v[i]]);
        if (used > 150 || i + 1 == OOT_RANDO_N) hos_log("rando: %s", line), used = 0;
    }
}
