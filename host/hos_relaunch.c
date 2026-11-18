/* (hookshot) The Insert menu's Restart now (gpu/vk/vk_menu.cpp): it saves its options and asks the window to close for a
   restart (WM_APP + 9: host/display.c, host/posix/display_sdl.c). The window closes as when the player closes it, and at
   the very end of that, instead of only exiting, the game is started again:
     Linux: the process becomes the game again (execve) with the arguments and the environment it started with
     (/proc/self/cmdline and /proc/self/environ: hookshot_env.txt's lines are read again, not kept), so whatever waits
     for it (the launcher, a stream, a test) still has it. The game is bin/hookshot on disk, never run from inside the
     AppImage (hookshot-launch starts it with the AppImage's variables taken away), so /proc/self/exe is the game;
     argv[0] on the PATH if that is gone (the folder built again meanwhile).
     Windows: a new process of this executable (GetModuleFileNameW) with this one's command line (GetCommandLineW), in
     the same folder, with the environment this one started with (kept by hos_relaunch_keep_env before hookshot_env.txt
     was read: the file's lines are read again, and its edits since are taken, not left out as the environment's own),
     and the standard handles it was started with when it was given a stderr (a run's log.txt), inherited alone;
     then this one exits. */
#include "hos.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include "hos_relaunch.h"

static volatile LONG relaunch_asked;

void hos_relaunch_ask(void) { InterlockedExchange(&relaunch_asked, 1); }

#ifdef _WIN32
static wchar_t *start_env;   /* (the environment block at the start: hos_relaunch_keep_env) */
static HANDLE start_std[3];  /* (the standard handles the game was given, if it was given a stderr: hos_relaunch_keep_env) */

void hos_relaunch_keep_env(void) {
    /* (kept before hos_main.c opens hookshot_log.txt as stderr for a game given none, by the same test as hos_main.c's:
       only handles the game was started with are passed on to the game started again, never its own log, which the new
       run moves to .1 and opens for itself) */
    const HANDLE err = GetStdHandle(STD_ERROR_HANDLE);
    if (err && err != INVALID_HANDLE_VALUE && GetFileType(err) != FILE_TYPE_UNKNOWN) {
        start_std[0] = GetStdHandle(STD_INPUT_HANDLE);
        start_std[1] = GetStdHandle(STD_OUTPUT_HANDLE);
        start_std[2] = err;
    }
    wchar_t *b = GetEnvironmentStringsW();
    if (!b) return;
    size_t n = 0;
    while (b[n]) n += wcslen(b + n) + 1;
    start_env = (wchar_t *)malloc((n + 1) * sizeof *start_env);
    if (start_env) memcpy(start_env, b, (n + 1) * sizeof *start_env);
    FreeEnvironmentStringsW(b);
}

static void relaunch(void) {
    wchar_t exe[MAX_PATH * 4];
    const DWORD n = GetModuleFileNameW(NULL, exe, MAX_PATH * 4);
    if (!n || n >= MAX_PATH * 4) {
        hos_log("restart: this executable's path was not found: the game only exits");
        return;
    }
    const wchar_t *line = GetCommandLineW();
    const size_t len = wcslen(line);
    wchar_t *cmd = (wchar_t *)malloc((len + 1) * sizeof *cmd);   /* (CreateProcessW may write into it) */
    if (!cmd) return;
    memcpy(cmd, line, (len + 1) * sizeof *cmd);
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    memset(&si, 0, sizeof si);
    si.cb = sizeof si;
    /* (the new process waits for this one to end before it moves hookshot_log.txt to .1 and opens its own: this one still
       has it open until it exits, and a rename of an open file fails on Windows, so the new run overwrote the old run's
       log. hos_main.c reads HOS_RESTART_OF) */
    wchar_t pid[16];
    swprintf(pid, 16, L"%lu", (unsigned long)GetCurrentProcessId());
    SetEnvironmentVariableW(L"HOS_RESTART_OF", pid);
    wchar_t *env = start_env ? hos_relaunch_env_block(start_env, L"HOS_RESTART_OF", pid) : NULL;   /* (NULL: this one's) */
    /* (a game given its standard handles (a run of scripts/hookshot_ctl.py, whose log.txt is the game's stderr) passes
       them on, so the game started again logs where this one did. Only those handles are inherited
       (PROC_THREAD_ATTRIBUTE_HANDLE_LIST), never another this process holds open, and each only while it is still the
       one the game was started with. A game that opened its own hookshot_log.txt passes none, as before. Should the
       start with them fail, the game is started as before, without them) */
    HANDLE pass[3];
    DWORD npass = 0;
    STARTUPINFOEXW six;
    memset(&six, 0, sizeof six);
    six.StartupInfo.cb = sizeof six;
    six.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    HANDLE *const std_slot[3] = {&six.StartupInfo.hStdInput, &six.StartupInfo.hStdOutput, &six.StartupInfo.hStdError};
    static const DWORD std_which[3] = {STD_INPUT_HANDLE, STD_OUTPUT_HANDLE, STD_ERROR_HANDLE};
    for (int i = 0; i < 3; i++) {
        const HANDLE h = start_std[i];
        if (!h || h == INVALID_HANDLE_VALUE || GetStdHandle(std_which[i]) != h) continue;
        DWORD k = 0;
        while (k < npass && pass[k] != h) k++;   /* (stdout and stderr are often one handle: listed once) */
        if (k == npass) {
            if (!SetHandleInformation(h, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT)) continue;
            pass[npass++] = h;
        }
        *std_slot[i] = h;
    }
    SIZE_T list_size = 0;
    LPPROC_THREAD_ATTRIBUTE_LIST list = NULL;
    if (npass && six.StartupInfo.hStdError) {
        InitializeProcThreadAttributeList(NULL, 1, 0, &list_size);
        list = list_size ? (LPPROC_THREAD_ATTRIBUTE_LIST)malloc(list_size) : NULL;
        if (list && !InitializeProcThreadAttributeList(list, 1, 0, &list_size)) free(list), list = NULL;
        if (list && !UpdateProcThreadAttribute(list, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, pass, npass * sizeof *pass,
                                               NULL, NULL)) {
            DeleteProcThreadAttributeList(list);
            free(list), list = NULL;
        }
    }
    BOOL started = FALSE;
    if (list) {
        six.lpAttributeList = list;
        started = CreateProcessW(exe, cmd, NULL, NULL, TRUE,
                                 (env ? CREATE_UNICODE_ENVIRONMENT : 0) | EXTENDED_STARTUPINFO_PRESENT, env, NULL,
                                 &six.StartupInfo, &pi);
        const DWORD error = started ? 0 : GetLastError();
        DeleteProcThreadAttributeList(list);
        free(list);
        if (!started) {
            hos_log("restart: the game could not be started again with its standard handles (error %lu): trying "
                    "without them", (unsigned long)error);
            memcpy(cmd, line, (len + 1) * sizeof *cmd);   /* (as it was: CreateProcessW may have written into it) */
        }
    }
    if (started ||
        CreateProcessW(exe, cmd, NULL, NULL, FALSE, env ? CREATE_UNICODE_ENVIRONMENT : 0, env, NULL, &si, &pi)) {
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
    } else {
        hos_log("restart: the game could not be started again (error %lu): it only exits", (unsigned long)GetLastError());
        hos_log_flush();
    }
    free(cmd);
    free(env);
}
#else
#include <dirent.h>
#include <fcntl.h>
#include <unistd.h>

extern char **environ;

static void relaunch(void) {
    HosRelaunch r;
    if (!hos_relaunch_command("/proc/self/cmdline", "/proc/self/environ", &r)) {
        hos_log("restart: this process's command was not found: the game only exits");
        hos_log_flush();
        return;
    }
    /* (every file this process opened closes with it, as at an exit: the new one opens its own) */
    DIR *d = opendir("/proc/self/fd");
    if (d) {
        const int skip = dirfd(d);
        for (struct dirent *e; (e = readdir(d));) {
            const int fd = atoi(e->d_name);
            if (fd > 2 && fd != skip) fcntl(fd, F_SETFD, fcntl(fd, F_GETFD) | FD_CLOEXEC);
        }
        closedir(d);
    }
    fflush(NULL);
    execve("/proc/self/exe", r.argv, r.envp);
    environ = r.envp;   /* (execvp searches the PATH of the environment it is given: the one the game started with) */
    execvp(r.argv[0], r.argv);
    hos_log("restart: the game could not be started again: it only exits");
    hos_log_flush();
}
#endif

/* Shared tail after rx_close_asked returned. No process exit or restart here: the Windows stop worker must
   keep its watchdog alive until all explicit close work and the log flush have returned. */
void hos_close_finish(void) {
    hos_log("stop: close work done (the game's saves are not waited for)");
    hos_log_flush();
    void hos_crash_clean_end(void);
    hos_crash_clean_end();
}

/* The window was closed (host/display.c's WM_CLOSE, host/posix/display_sdl.c's quit): the game exits, and starts again
   first when the menu asked for it */
void hos_window_closed_exit(void) {
    const int again = relaunch_asked != 0;
    hos_log(again ? "display: window closed for a restart (the Insert menu's Restart now)" : "display: window closed, exiting");
    hos_close_finish();
    if (again) relaunch();
    ExitProcess(0);
}
