/* (hookshot) A settings file written whole or not at all: the one helper every write of a setting goes through.

   The settings (language.txt, mouse_sens.txt, saves-moved.txt) were written with fopen "w", which empties the file
   before it writes it, and a settings file was put in place by a copy made at its final name (the options' one-time copy into
   the user folder, host/options_path.c; the files the saves' move copies, host/hos_main.c): a kill, a crash or a power cut in
   the middle left an empty file or a part of one, and the next start took it for the player's settings. Now the file is written
   beside itself as "<path>.hosnew", flushed to the disk, and moved over the old one in one step: a kill leaves the old file or
   the new one, never a mixture.

     hos_atomic_write(path, data, size)  "<path>.hosnew" is written and flushed, then moved over <path> (MOVEFILE_REPLACE_EXISTING |
                                         MOVEFILE_WRITE_THROUGH on Windows; elsewhere the posix layer's MoveFileExA is a plain
                                         rename, so the folder is flushed here, as POSIX needs). 1 when <path> is the new file;
                                         0 (and <path> as it was) when anything failed.
     hos_atomic_copy_file(from, to)      the same for a file copied: from's bytes as the whole of to.
     hos_atomic_remove_stale(path)       a leftover "<path>.hosnew" from a write that was killed: removed at the next start.

   Where no stand-in can be made a setting is written in place, as it always was: a file that is a link (a file moved over it
   would replace the link, not the file it names), and a folder that takes no new file though the file itself may be written
   (hos_atomic_write only; a full disk is not that case: the file stays as it was).

   Tests: tests/test_settings_atomic.py kills a child at every HOS_AF_STEP; tests/test_options_path.py kills the options'
   one-time copy. Paths are UTF-8; / and \ are one separator. */
#pragma once
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX   /* (min and max stay the C++ library's, in the files that include this) */
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#endif
#include <errno.h>
#include <windows.h>   /* (Linux: host/posix's) */
#ifndef _WIN32
#include <fcntl.h>
#include <unistd.h>
#endif

#ifndef ERROR_SHARING_VIOLATION
#define ERROR_SHARING_VIOLATION 32L
#endif
#ifndef HOS_AF_STEP
#define HOS_AF_STEP(what) ((void)0)   /* (a test's kill point; tests/test_settings_atomic.py) */
#endif
#define HOS_AF_PATH 1024               /* (the longest path written: a longer one is not) */
#define HOS_AF_NEW ".hosnew"           /* a file being written: never whole */

static inline int hos_af_is_sep(char c) { return c == '/' || c == '\\'; }
/* the file's name: what follows the last separator */
static inline const char *hos_af_base(const char *path) {
    const char *b = path;
    for (const char *p = path; *p; p++)
        if (hos_af_is_sep(*p)) b = p + 1;
    return b;
}
static inline int hos_af_name(char *out, size_t cap, const char *path, const char *suffix) {
    return (size_t)snprintf(out, cap, "%s%s", path, suffix) < cap;
}

#ifndef _WIN32
/* A rename is on the disk once the folder it was made in is (the posix layer's MoveFileExA is a plain rename, so this does it;
   Windows is asked with MOVEFILE_WRITE_THROUGH): path's folder */
static inline void hos_af_sync_folder(const char *path) {
    char dir[HOS_AF_PATH];
    if (snprintf(dir, sizeof dir, "%s", path) >= (int)sizeof dir) return;
    for (char *p = dir; *p; p++)
        if (*p == '\\') *p = '/';
    char *slash = strrchr(dir, '/');
    if (!slash) snprintf(dir, sizeof dir, ".");
    else if (slash == dir) dir[1] = 0;
    else *slash = 0;
    const int fd = open(dir, O_RDONLY | O_CLOEXEC);
    if (fd >= 0) {
        fsync(fd);
        close(fd);
    }
}
#endif
/* from moved over to: one step. Windows asks for the move to be on the disk (MOVEFILE_WRITE_THROUGH); elsewhere the posix layer's
   MoveFileExA is a plain rename and the folders are flushed here. A file somebody holds open without FILE_SHARE_DELETE (Windows)
   refuses for a moment: tried again for a second. 1 when moved */
static inline int hos_af_move(const char *from, const char *to) {
    HOS_AF_STEP("move: before");
    for (int tries = 0;; tries++) {
        if (MoveFileExA(from, to, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) break;
        const DWORD e = GetLastError();
        if (tries >= 40 || (e != ERROR_SHARING_VIOLATION && e != ERROR_ACCESS_DENIED)) return 0;
        Sleep(25);
    }
#ifndef _WIN32
    hos_af_sync_folder(to);
    if (hos_af_base(from) - from != hos_af_base(to) - to || memcmp(from, to, (size_t)(hos_af_base(to) - to))) hos_af_sync_folder(from);
#endif
    HOS_AF_STEP("move: after");
    return 1;
}
static inline int hos_af_write_all(HANDLE h, const void *data, size_t n) {
    const char *p = (const char *)data;
    while (n) {
        const DWORD chunk = n > 0x40000000 ? 0x40000000 : (DWORD)n;
        DWORD put = 0;
        if (!WriteFile(h, p, chunk, &put, NULL) || !put) return 0;
        p += put, n -= put;
    }
    return 1;
}
/* everything from holds, at the same offsets, into to */
static inline int hos_af_copy_handle(HANDLE from, HANDLE to) {
    char *buf = (char *)malloc(1 << 16);
    if (!buf) return 0;
    int ok = 1;
    for (uint64_t at = 0; ok;) {
        OVERLAPPED in, out;
        memset(&in, 0, sizeof in), memset(&out, 0, sizeof out);
        in.Offset = out.Offset = (DWORD)at, in.OffsetHigh = out.OffsetHigh = (DWORD)(at >> 32);
        DWORD got = 0, put = 0;
        if (!ReadFile(from, buf, 1 << 16, &got, &in)) {
            ok = GetLastError() == ERROR_HANDLE_EOF;   /* (the end of the file is no error) */
            break;
        }
        if (!got) break;
        ok = WriteFile(to, buf, got, &put, &out) && put == got;
        at += got;
    }
    free(buf);
    return ok;
}
static inline HANDLE hos_af_open_new(const char *path) {
    return CreateFileA(path, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
                       CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
}
/* a link (a symbolic link, a cloud placeholder): a file moved over it would replace the link, not the file it names */
static inline int hos_af_is_link(const char *path) {
    const DWORD a = GetFileAttributesA(path);
    return a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_REPARSE_POINT) != 0;
}
/* path itself rewritten and flushed: where no stand-in can be (a link; a folder that takes no new file). Not whole if killed: the
   way a setting was always written. 1 when all of it was written */
static inline int hos_af_write_in_place(const char *path, const void *data, size_t size) {
    HANDLE h = CreateFileA(path, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, CREATE_ALWAYS,
                           FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return 0;
    int ok = hos_af_write_all(h, data, size) && FlushFileBuffers(h);
    return CloseHandle(h) && ok;
}

/* The whole file: <path>.hosnew written and flushed, then moved over <path>. 1 when <path> is the new file; 0 (and
   <path> as it was) when anything failed. A link, or a folder that takes no new file though the file itself may be written
   (not a full disk: that leaves the file as it was), has <path> itself rewritten and flushed, as a setting always was */
static inline int hos_atomic_write(const char *path, const void *data, size_t size) {
    char temp[HOS_AF_PATH];
    if (!hos_af_name(temp, sizeof temp, path, HOS_AF_NEW)) return 0;
    if (hos_af_is_link(path)) return hos_af_write_in_place(path, data, size);
    HANDLE h = CreateFileA(temp, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return GetLastError() == ERROR_ACCESS_DENIED ? hos_af_write_in_place(path, data, size) : 0;
    HOS_AF_STEP("write: temp made");
    int ok = hos_af_write_all(h, data, size);
    HOS_AF_STEP("write: temp written");
    ok = ok && FlushFileBuffers(h);
    HOS_AF_STEP("write: temp flushed");
    ok = CloseHandle(h) && ok;
    ok = ok && hos_af_move(temp, path);
    if (!ok) DeleteFileA(temp);
    return ok;
}
/* A file copied: from's bytes as the whole of to. 0 when anything failed; GetLastError is then the open's, the write's or the move's,
   not the clean-up's */
static inline int hos_atomic_copy_file(const char *from, const char *to) {
    char temp[HOS_AF_PATH];
    if (!hos_af_name(temp, sizeof temp, to, HOS_AF_NEW)) return 0;
    HANDLE in = CreateFileA(from, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, OPEN_EXISTING,
                            FILE_ATTRIBUTE_NORMAL, NULL);
    if (in == INVALID_HANDLE_VALUE) return 0;
    HANDLE out = hos_af_open_new(temp);
    int ok = out != INVALID_HANDLE_VALUE && hos_af_copy_handle(in, out);
    HOS_AF_STEP("copy: temp written");
    if (out != INVALID_HANDLE_VALUE) ok = FlushFileBuffers(out) && CloseHandle(out) && ok;
    CloseHandle(in);
    ok = ok && hos_af_move(temp, to);
    if (!ok) {
        const DWORD error = GetLastError();   /* (hos_options_carry logs it: not the clean-up's) */
        DeleteFileA(temp);
        SetLastError(error);
    }
    return ok;
}
/* a leftover <path>.hosnew from a write that was killed */
static inline void hos_atomic_remove_stale(const char *path) {
    char temp[HOS_AF_PATH];
    if (hos_af_name(temp, sizeof temp, path, HOS_AF_NEW)) DeleteFileA(temp);
}
