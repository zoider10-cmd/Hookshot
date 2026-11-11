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
    return on ? "save_rando" : "save";
}

/* hos_main.c, once at the start */
void hos_rando_init(void) {
    OotRando r;
    rando_read(&r, 1);
    if (!r.on) return;
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
