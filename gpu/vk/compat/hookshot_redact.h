// The home folder and the user's name out of a line of the logs, one implementation for the host (C) and the renderer (C++):
// the home folder, as a whole, written ~ (%USERPROFILE% on Windows), and the user's name as a folder of any path <user>
// (/run/media/<user>, D:\Users\<user>, /var/home/<user>). The rest of the line, the rest of each path too, stays as it is.
// Used by the game's log as it writes it (host/log_redact.c), the crash window (host/hos_crash_dialog.h
// hos_crash_redact_line) and the Insert menu's Bug report (gpu/vk/vk_bug_report.cpp redact). A line redacted again comes out
// the same: ~, %USERPROFILE% and <user> are never a home folder or a name to take out.
#ifndef HOOKSHOT_REDACT_H
#define HOOKSHOT_REDACT_H

#include <stddef.h>
#include <string.h>

static inline int hookshot_redact_sep(char c) { return c == '/' || c == '\\'; }
/* (a character a file or folder name has: a name ends at any other) */
static inline int hookshot_redact_name_char(char c) {
    const unsigned char u = (unsigned char)c;
    return (u >= '0' && u <= '9') || (u >= 'a' && u <= 'z') || (u >= 'A' && u <= 'Z') || c == '.' || c == '_' || c == '-' || u >= 0x80;
}
/* (Windows: either separator for either, in any case) */
static inline int hookshot_redact_matches_at(const char *s, size_t n, size_t at, const char *what, size_t wn, int windows) {
    if (!wn || at + wn > n) return 0;
    for (size_t i = 0; i < wn; i++) {
        char a = s[at + i], b = what[i];
        if (hookshot_redact_sep(a) && hookshot_redact_sep(b)) {
            if (!windows && a != b) return 0;
            continue;
        }
        if (windows) {
            if (a >= 'A' && a <= 'Z') a = (char)(a + 32);
            if (b >= 'A' && b <= 'Z') b = (char)(b + 32);
        }
        if (a != b) return 0;
    }
    return 1;
}
/* line (n bytes) into out (cap bytes, NUL-terminated, cut to fit) with home and user taken out. The length written. home and
   user may be NULL or empty (then nothing of theirs is taken out). out needs at most n * 7 + 1 bytes: a home of 2 bytes becomes
   %USERPROFILE%'s 13, a name of 1 byte <user>'s 6 */
static inline size_t hookshot_redact_line(char *out, size_t cap, const char *line, size_t n, const char *home, const char *user,
                                          int windows) {
    size_t hn = home ? strlen(home) : 0, un = user ? strlen(user) : 0, o = 0;
    while (hn > 1 && hookshot_redact_sep(home[hn - 1])) hn--;
    const int with_home = hn > 1;
    if (!cap) return 0;
#define HOOKSHOT_REDACT_OUT(s, k) do { for (size_t j_ = 0; j_ < (k) && o + 1 < cap; j_++) out[o++] = (s)[j_]; } while (0)
    for (size_t i = 0; i < n;) {
        /* (the home folder as a whole: not inside a longer name, not the end of another path) */
        if (with_home && (i == 0 || (!hookshot_redact_name_char(line[i - 1]) && !hookshot_redact_sep(line[i - 1]))) &&
            hookshot_redact_matches_at(line, n, i, home, hn, windows) && (i + hn >= n || !hookshot_redact_name_char(line[i + hn]))) {
            const char *w = windows ? "%USERPROFILE%" : "~";
            HOOKSHOT_REDACT_OUT(w, strlen(w));
            i += hn;
            continue;
        }
        /* (the user's name as a folder of any path) */
        if (un && i > 0 && hookshot_redact_sep(line[i - 1]) && hookshot_redact_matches_at(line, n, i, user, un, windows) &&
            (i + un >= n || !hookshot_redact_name_char(line[i + un]))) {
            HOOKSHOT_REDACT_OUT("<user>", 6);
            i += un;
            continue;
        }
        HOOKSHOT_REDACT_OUT(line + i, 1);
        i++;
    }
#undef HOOKSHOT_REDACT_OUT
    out[o] = 0;
    return o;
}

#endif
