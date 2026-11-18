/* The player's settings, hookshot_options.ini (host/options_path.c): the Insert menu's choices and the controls, in the user
   folder --user names (the launcher's, the same for every build it starts, so an update or a new build keeps them), else beside
   the game as before. Paths are UTF-8. */
#pragma once
/* Chooses the file from the game's command line and HOS_OPTIONS_FILE: at the very start of main, before anything reads it
   (the crash window's helper, the Discord status, the renderer). Nothing is moved or made; once a process */
void hos_options_choose(int argc, char **argv);
/* The file's path: "" before hos_options_choose or when none could be chosen (no file: every setting at its default) */
const char *hos_options_file(void);
/* The file's path into the log ("options: the settings file is <path>"), and the game folder's hookshot_options.ini, a build's
   from before, copied into the user folder once: when the user folder has none and it holds a setting (not only make_game.py's
   compile_shaders=). Once the log is open and the user folder made */
void hos_options_carry(void);
