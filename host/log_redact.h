/* The game's logs written without the player's user name (host/log_redact.c). Players pass hookshot_log.txt around, in issues
   and in chats, so what the game saves holds what a Bug report's copy holds: the home folder written ~ (%USERPROFILE% on
   Windows) and the user's name as a folder of any path <user>, the rest of each path as it was (gpu/vk/compat/hookshot_redact.h).
   - each line the game and the renderer log (hos_log, hos_log_at, the renderer's logf, hos_fatal) is redacted before it is
     written (host/hos_thread.c hos_vlog);
   - what other code writes to stderr itself (the Vulkan loader, SDL, a printf before the log started) is redacted in the file
     once its run has ended: by the crash watch (host/hos_crash_dialog.c, as soon as the game is gone) and, for a run that had
     none, by the next start, on the log it rotates to hookshot_log.1.txt (host/hos_main.c). */
#pragma once
#include <stddef.h>

/* line (NUL-terminated) into out (cap bytes, NUL-terminated, cut to fit), the home folder and the user's name out. Safe from
   any thread; no allocation, no lock after the first call. The length written */
size_t hos_log_redact(char *out, size_t cap, const char *line);

/* The log file at path redacted in place, line by line, once its run has ended (another writer would lose its place). With
   run_id, only when the file is that run's (its "run_id: <id>" line in its first 8 KB): a start since may have made a new log
   at the path. Locked while it is rewritten, so a start and a crash watch never rewrite one file at once. 1 rewritten, 0
   already clean (or not that run's, or over 256 MB), -1 not opened or not written */
int hos_log_redact_file(const char *path, const char *run_id);
