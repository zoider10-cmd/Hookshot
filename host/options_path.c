/* The player's settings, hookshot_options.ini (options_path.h): in the user folder the game is given, the saves' (host/hos_main.c),
   not beside the game. The launcher starts every build with the same one (--user: %APPDATA%\Hookshot on Windows, a portable
   launcher's own folder), so an update, a new build or another channel keeps the Insert menu's choices and the controls; a
   build in its own folder kept its own before, and an update into a new folder started from the defaults. Where it is:
   - HOS_OPTIONS_FILE=<path>: that file (a scripted or test run brings its own and leaves the player's as it is, as HOS_ENV_FILE
     does for hookshot_env.txt);
   - --user <folder>: in that folder. A relative folder is made whole against the folder the game will run in (the game folder
     when it is started with nothing: hos_main.c goes there), so the crash window's helper, started before that, reads the same
     file;
   - else beside the game, as before: a game started by itself (RecompLauncher, which sets its rows in that file and updates in
     place, a shortcut, the tools) keeps its folder's.
   Chosen with no side effect, before anything reads it. The build's own choice stays in the game folder's file: compile_shaders=,
   which make_game.py writes there (gpu/vk/vk_draw.cpp compile_all). A game folder's file from before is copied once into the
   user folder when that has none (hos_options_carry), whole or not at all (host/hos_atomic_file.h): a kill in the copy leaves no
   file there, and the next start copies again. */
#include "hos_paths.h"   /* (first: windows.h, host/posix's on Linux) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "options_path.h"
#include "hos_atomic_file.h"

#ifdef _WIN32
#define SEP '\\'
#define SEP_S "\\"
#else
#define SEP '/'
#define SEP_S "/"
#endif

void hos_log(const char *fmt, ...);   /* (hos.h; declared here so a test builds this file alone) */

static const char options_name[] = "hookshot_options.ini";
static char file[MAX_PATH];
static int chosen;

static int is_sep(char c) { return c == '/' || c == '\\'; }
static int absolute(const char *p) {
#ifdef _WIN32
    return is_sep(p[0]) || (p[0] && p[1] == ':');
#else
    return p[0] == '/';
#endif
}
/* the game folder, with its separator: 0 when not known */
static size_t game_folder(char *out, size_t cap) {
    DWORD n = hos_game_path_a(out, (DWORD)cap);
    if (!n || n >= cap) return 0;
    while (n && !is_sep(out[n - 1])) n--;
    out[n] = 0;
    return n;
}
/* folder/name (name NULL: folder itself) into file, made whole against base (with its separator; "" the working folder); file
   "" when too long */
static void put(const char *base, const char *folder, const char *name) {
    char whole[MAX_PATH];
    file[0] = 0;
    if (!absolute(folder)) {
        char cwd[MAX_PATH];
        if (!base[0]) {
            const DWORD n = GetCurrentDirectoryA(MAX_PATH, cwd);
            if (!n || n >= MAX_PATH - 1) return;
            if (!is_sep(cwd[n - 1])) cwd[n] = SEP, cwd[n + 1] = 0;
            base = cwd;
        }
        if (snprintf(whole, sizeof whole, "%s%s", base, folder) >= (int)sizeof whole) return;
        folder = whole;
    }
    const size_t n = strlen(folder);
    if (snprintf(file, sizeof file, "%s%s%s", folder, !name || (n && is_sep(folder[n - 1])) ? "" : SEP_S, name ? name : "") >=
        (int)sizeof file)
        file[0] = 0;
}

void hos_options_choose(int argc, char **argv) {
    if (chosen) return;
    chosen = 1;
    file[0] = 0;
    const char *own = getenv("HOS_OPTIONS_FILE");
    if (own && own[0]) {
        put("", own, NULL);
        return;
    }
    /* (the game's command line as hos_main.c reads it: --romfs and --compile-shaders take a value; the first other word is
       the image) */
    const char *user = NULL, *image = NULL;
    for (int i = 1; i < argc; i++) {
        if ((!strcmp(argv[i], "--romfs") || !strcmp(argv[i], "--compile-shaders")) && i + 1 < argc) i++;
        else if (!strcmp(argv[i], "--user") && i + 1 < argc) user = argv[++i];
        else if (!strcmp(argv[i], "--trace") || !strcmp(argv[i], "--prepare-shaders")) continue;
        else if (!image) image = argv[i];
    }
    char game[MAX_PATH], probe[MAX_PATH];
    const size_t g = game_folder(game, sizeof game);
    if (!user) {
        if (g) put(game, options_name, NULL);   /* (beside the game, as before) */
        return;
    }
    /* (started with nothing and image.bin beside: hos_main.c goes into the game folder, where a relative --user is) */
    const int beside = !image && g && snprintf(probe, sizeof probe, "%simage.bin", game) < (int)sizeof probe &&
                       GetFileAttributesA(probe) != INVALID_FILE_ATTRIBUTES;
    put(beside ? game : "", user, options_name);
}

const char *hos_options_file(void) { return file; }

/* Whether the file at path has a setting of the player's: a key=value line other than compile_shaders= (make_game.py writes
   that one into a new folder before the game has started) */
static int has_settings(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    char line[256];
    int found = 0;
    while (!found && fgets(line, sizeof line, f)) {
        const char *eq = strchr(line, '=');
        found = eq && eq != line && strncmp(line, "compile_shaders=", 16);
    }
    fclose(f);
    return found;
}

void hos_options_carry(void) {
    static int done;
    if (done) return;
    done = 1;
    const char *own = getenv("HOS_OPTIONS_FILE");
    /* (where it is, for a report: nx2/pipeline_share.py reads it from this line) */
    hos_log("options: the settings file is %s", file[0] ? file : "none (every setting at its default, nothing saved)");
    if ((own && own[0]) || !file[0] || GetFileAttributesA(file) != INVALID_FILE_ATTRIBUTES) return;
    char from[MAX_PATH];
    const size_t g = game_folder(from, sizeof from);
    if (!g || snprintf(from + g, sizeof from - g, "%s", options_name) >= (int)(sizeof from - g)) return;
#ifdef _WIN32
    if (!_stricmp(from, file)) return;   /* (beside the game: the file is already where it is read) */
#else
    if (!strcmp(from, file)) return;
#endif
    if (!has_settings(from)) return;
    char folder[MAX_PATH];
    snprintf(folder, sizeof folder, "%s", file);
    char *slash = folder + strlen(folder);
    while (slash > folder && !is_sep(slash[-1])) slash--;
    if (slash > folder) slash[-1] = 0, CreateDirectoryA(folder, NULL);   /* (hos_main.c made the user folder: in case) */
    if (hos_atomic_copy_file(from, file)) {
        hos_log("options: the settings in %s were copied to %s, where every build the launcher starts reads them now (the game "
                "folder's copy is no longer read, but for compile_shaders=)", from, file);
        return;
    }
    /* (a user folder that cannot be written: this run reads and saves the game folder's, as before, and the next one tries again) */
    hos_log("options: %s could not be copied to %s (error %lu): this run keeps the game folder's", from, file,
            (unsigned long)GetLastError());
    snprintf(file, sizeof file, "%s", from);
}
