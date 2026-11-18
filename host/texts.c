/* (hookshot) The game's texts with the console's wording made the PC's. One text names the console (the hint for playing the
   ocarina by microphone says to use its built-in one); nx2/text_assets.py rewords it in the player's own text archives at
   build time, into the game folder's texts/, and this serves those in place of the game's romfs/Mals/<language>.Product.<n>.sarc.zs.
   A language the build made no file for keeps the game's own, and so does a mod's file for the same path (as for the button
   prompts, host/prompts.c). HOS_TEXTS=0: the game's own texts. */
#include "hos.h"
#include "hos_paths.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

/* mods.c: the file for a RomFS path the texts replace (key: lower case, '/'), 1 with one. mod: a mod's file for it, or NULL:
   the mod's own wins */
int hos_texts_romfs(const char *key, const char *mod, char *out, size_t cap) {
    static volatile LONG off = -1, logged;
    if (strncmp(key, "mals/", 5) || !key[5] || strchr(key + 5, '/')) return 0;
    if (mod) return 0;
    if (off < 0) {
        const char *const e = getenv("HOS_TEXTS");
        if (InterlockedExchange(&off, e && !atoi(e)) < 0 && e && !atoi(e)) hos_log("texts: HOS_TEXTS=0, the game's own texts");
    }
    if (off) return 0;
    char path[MAX_PATH];
    const DWORD len = hos_game_path_a(path, MAX_PATH);
    char *const slash = len ? (strrchr(path, 92) ? strrchr(path, 92) : strrchr(path, 47)) : NULL;   /* (linux: '/') */
    if (!slash) return 0;
    slash[1] = 0;
    snprintf(out, cap, "%stexts/%s", path, key + 5);   /* (nx2/text_assets.py names its files in lower case, as the key) */
    if (GetFileAttributesA(out) == INVALID_FILE_ATTRIBUTES) return 0;
    if (InterlockedIncrement(&logged) <= 4) hos_log("texts: %s <- %s (the console's wording made the PC's)", key, out);
    return 1;
}
