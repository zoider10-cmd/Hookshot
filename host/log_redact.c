/* The game's logs written without the player's user name: who to leave out, a line, and a log file once its run has ended
   (host/log_redact.h). The rule is the Bug report's and the crash window's (gpu/vk/compat/hookshot_redact.h): the home folder
   and the user's name go, the rest of each path stays. On Windows the home folder is also left out as its short name
   (C:\Users\JOHNSM~1, which TEMP often holds), and the user's name as both USERNAME and the home folder's own name, which
   can differ (an account renamed, a profile folder named john.PC). */
#if !defined(_WIN32) && !defined(_GNU_SOURCE)
#define _GNU_SOURCE   /* (pread, pwrite, O_CLOEXEC under a strict -std) */
#endif
#include "log_redact.h"
#include "../gpu/vk/compat/hookshot_redact.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <fcntl.h>
#include <pwd.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

enum { WHO_TEXT = 1024, FILE_MAX = 256 << 20, RUN_ID_HEAD = 8192 };
typedef struct Who { char home[WHO_TEXT], home_short[WHO_TEXT], user[256], user_folder[256]; int windows; } Who;
static Who who;
static int who_state;   /* 0 not yet, 1 being filled, 2 ready */

#ifdef _WIN32
static void utf8_into(char *out, size_t cap, const wchar_t *w) {
    out[0] = 0;
    if (w && WideCharToMultiByte(CP_UTF8, 0, w, -1, out, (int)cap, NULL, NULL) <= 0) out[0] = 0;
}
#endif

/* (the home folder's last name: C:\Users\john.PC's john.PC) */
static void leaf_into(char *out, size_t cap, const char *path) {
    size_t n = strlen(path);
    while (n > 1 && hookshot_redact_sep(path[n - 1])) n--;
    size_t start = n;
    while (start > 0 && !hookshot_redact_sep(path[start - 1])) start--;
    snprintf(out, cap, "%.*s", (int)(n - start), path + start);
}

static void who_fill(Who *w) {
    memset(w, 0, sizeof *w);
#ifdef _WIN32
    w->windows = 1;
    const wchar_t *h = _wgetenv(L"USERPROFILE"), *u = _wgetenv(L"USERNAME");
    utf8_into(w->home, sizeof w->home, h);
    utf8_into(w->user, sizeof w->user, u);
    if (h && *h) {
        wchar_t shortw[WHO_TEXT];
        const DWORD n = GetShortPathNameW(h, shortw, WHO_TEXT);
        if (n && n < WHO_TEXT) utf8_into(w->home_short, sizeof w->home_short, shortw);
        if (w->home_short[0] && hookshot_redact_matches_at(w->home_short, strlen(w->home_short), 0, w->home, strlen(w->home), 1) &&
            strlen(w->home_short) == strlen(w->home))
            w->home_short[0] = 0;   /* (the same: once is enough) */
    }
#else
    const struct passwd *pw = getpwuid(getuid());
    const char *h = getenv("HOME"), *u = getenv("USER");
    snprintf(w->home, sizeof w->home, "%s", h && *h ? h : pw && pw->pw_dir ? pw->pw_dir : "");
    snprintf(w->user, sizeof w->user, "%s", u && *u ? u : pw && pw->pw_name ? pw->pw_name : "");
#endif
    if (w->home[0]) leaf_into(w->user_folder, sizeof w->user_folder, w->home);
    if (!strcmp(w->user_folder, w->user) || strlen(w->user_folder) < 2) w->user_folder[0] = 0;
}

static const Who *who_here(void) {
    int state = __atomic_load_n(&who_state, __ATOMIC_ACQUIRE);
    if (state == 2) return &who;
    int expected = 0;
    if (__atomic_compare_exchange_n(&who_state, &expected, 1, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
        who_fill(&who);
        __atomic_store_n(&who_state, 2, __ATOMIC_RELEASE);
        return &who;
    }
    /* (another thread fills it: the first line is the main thread's, before any other starts, so this is a moment at most) */
    while (__atomic_load_n(&who_state, __ATOMIC_ACQUIRE) != 2) {
#ifdef _WIN32
        Sleep(0);
#else
        usleep(50);
#endif
    }
    return &who;
}

/* (the home folder, its short name, then the user's name and the home folder's own name: each pass on the last one's text) */
static size_t redact_n(const Who *w, char *out, size_t cap, const char *line, size_t n, char *scratch, size_t scratch_cap) {
    size_t len = hookshot_redact_line(out, cap, line, n, w->home, w->user, w->windows);
    if (w->home_short[0] && scratch_cap) {
        len = hookshot_redact_line(scratch, scratch_cap, out, len, w->home_short, NULL, w->windows);
        memcpy(out, scratch, (len < cap ? len : cap - 1) + 1), len = len < cap ? len : cap - 1, out[len] = 0;
    }
    if (w->user_folder[0] && scratch_cap) {
        len = hookshot_redact_line(scratch, scratch_cap, out, len, NULL, w->user_folder, w->windows);
        memcpy(out, scratch, (len < cap ? len : cap - 1) + 1), len = len < cap ? len : cap - 1, out[len] = 0;
    }
    return len;
}

size_t hos_log_redact(char *out, size_t cap, const char *line) {
    if (!cap) return 0;
    if (!line) return out[0] = 0, 0;
    char scratch[4096];
    return redact_n(who_here(), out, cap, line, strlen(line), scratch, sizeof scratch);
}

/* text (n bytes) redacted line by line into a new buffer (malloc'd; *out_n its length), NULL without memory */
static char *redact_text(const Who *w, const char *text, size_t n, size_t *out_n) {
    size_t cap = n + n / 8 + 4096, at = 0;
    char *all = (char *)malloc(cap), *line = NULL, *scratch = NULL;
    size_t line_cap = 0;
    if (!all) return NULL;
    for (size_t i = 0; i < n;) {
        const char *nl = (const char *)memchr(text + i, '\n', n - i);
        const size_t len = nl ? (size_t)(nl - (text + i)) + 1 : n - i;
        const size_t need = len * 7 + 1;
        if (need > line_cap) {
            free(line), free(scratch);
            line = (char *)malloc(need), scratch = (char *)malloc(need), line_cap = need;
            if (!line || !scratch) { free(line), free(scratch), free(all); return NULL; }
        }
        const size_t got = redact_n(w, line, line_cap, text + i, len, scratch, line_cap);
        if (at + got + 1 > cap) {
            size_t more = cap * 2 > at + got + 1 ? cap * 2 : at + got + 4096;
            char *bigger = (char *)realloc(all, more);
            if (!bigger) { free(line), free(scratch), free(all); return NULL; }
            all = bigger, cap = more;
        }
        memcpy(all + at, line, got), at += got;
        i += len;
    }
    free(line), free(scratch);
    *out_n = at;
    return all;
}

static int is_run(const char *text, size_t n, const char *run_id) {
    if (!run_id || !run_id[0]) return 1;
    char want[64];
    const int w = snprintf(want, sizeof want, "run_id: %s", run_id);
    const size_t head = n < RUN_ID_HEAD ? n : RUN_ID_HEAD;
    for (size_t i = 0; w > 0 && i + (size_t)w <= head; i++)
        if (!memcmp(text + i, want, (size_t)w)) return 1;
    return 0;
}

int hos_log_redact_file(const char *path, const char *run_id) {
    if (!path || !path[0]) return -1;
    const Who *w = who_here();
    int result = -1;
    char *text = NULL, *clean = NULL;
    size_t n = 0, clean_n = 0;
#ifdef _WIN32
    wchar_t wpath[WHO_TEXT * 2];
    if (MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, wpath, WHO_TEXT * 2) <= 0) return -1;
    /* (shared for everything, delete too: a start may rotate it while it is open here) */
    HANDLE f = CreateFileW(wpath, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
                           OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (f == INVALID_HANDLE_VALUE) return -1;
    OVERLAPPED whole;
    memset(&whole, 0, sizeof whole);
    if (!LockFileEx(f, LOCKFILE_EXCLUSIVE_LOCK, 0, MAXDWORD, MAXDWORD, &whole)) { CloseHandle(f); return -1; }
    LARGE_INTEGER size;
    if (!GetFileSizeEx(f, &size) || size.QuadPart < 0) goto done;
    if (size.QuadPart > FILE_MAX) { result = 0; goto done; }
    n = (size_t)size.QuadPart;
    text = (char *)malloc(n ? n : 1);
    if (!text) goto done;
    for (size_t got = 0; got < n;) {
        DWORD k = 0;
        if (!ReadFile(f, text + got, (DWORD)(n - got > (1u << 30) ? (1u << 30) : n - got), &k, NULL) || !k) { n = got; break; }
        got += k;
    }
#else
    int f = open(path, O_RDWR | O_CLOEXEC);
    if (f < 0) return -1;
#ifndef __EMSCRIPTEN__
    if (flock(f, LOCK_EX) != 0) { close(f); return -1; }
#endif
    struct stat st;
    if (fstat(f, &st) != 0 || st.st_size < 0) goto done;
    if (st.st_size > FILE_MAX) { result = 0; goto done; }
    n = (size_t)st.st_size;
    text = (char *)malloc(n ? n : 1);
    if (!text) goto done;
    for (size_t got = 0; got < n;) {
        const ssize_t k = pread(f, text + got, n - got, (off_t)got);
        if (k <= 0) { n = got; break; }
        got += (size_t)k;
    }
#endif
    if (!is_run(text, n, run_id)) { result = 0; goto done; }
    clean = redact_text(w, text, n, &clean_n);
    if (!clean) goto done;
    if (clean_n == n && !memcmp(clean, text, n)) { result = 0; goto done; }
#ifdef _WIN32
    {
        LARGE_INTEGER zero;
        zero.QuadPart = 0;
        int ok = SetFilePointerEx(f, zero, NULL, FILE_BEGIN) != 0;
        for (size_t put = 0; ok && put < clean_n;) {
            DWORD k = 0;
            ok = WriteFile(f, clean + put, (DWORD)(clean_n - put > (1u << 30) ? (1u << 30) : clean_n - put), &k, NULL) && k;
            put += k;
        }
        result = ok && SetEndOfFile(f) ? 1 : -1;
    }
#else
    {
        int ok = 1;
        for (size_t put = 0; ok && put < clean_n;) {
            const ssize_t k = pwrite(f, clean + put, clean_n - put, (off_t)put);
            ok = k > 0;
            if (ok) put += (size_t)k;
        }
        result = ok && ftruncate(f, (off_t)clean_n) == 0 ? 1 : -1;
    }
#endif
done:
    free(text), free(clean);
#ifdef _WIN32
    UnlockFileEx(f, 0, MAXDWORD, MAXDWORD, &whole);
    CloseHandle(f);
#else
#ifndef __EMSCRIPTEN__
    flock(f, LOCK_UN);
#endif
    close(f);
#endif
    return result;
}
