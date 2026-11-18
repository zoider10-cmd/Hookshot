/* Windowless Windows stop requests. No renderer, save or log work runs on a console handler thread.
   The hidden top-level window is never shown: unlike HWND_MESSAGE, it receives enumerated/broadcast messages.
   Only OS-ending events arm a deadline. After explicit close work, this route skips DLL detach: ExitProcess
   would kill the watchdog before detach, where a driver can hang. See docs/development.md. */
#ifdef _WIN32
#include <windows.h>

void hos_log(const char *fmt, ...);
void hos_log_flush(void);
void rx_close_asked(void);
void hos_close_finish(void);

enum { STOP_WAIT_MS = 4000, STOP_TIMEOUT_EXIT = 124 };
enum { STOP_CTRL_C = 1, STOP_CTRL_BREAK, STOP_CONSOLE_CLOSE, STOP_LOGOFF, STOP_SHUTDOWN, STOP_WINDOW, STOP_SESSION };
static HANDLE stop_requested, stop_changed, stop_ready;
static volatile LONG stop_reason;
static volatile LONG64 stop_deadline;   /* 0: no OS deadline; published atomically, never extended */

static int os_ending(LONG reason) {
    return reason == STOP_CONSOLE_CLOSE || reason == STOP_LOGOFF || reason == STOP_SHUTDOWN || reason == STOP_SESSION;
}

static void request_stop(LONG reason) {
    /* An OS-ending event can follow an ordinary close already in progress. Arm its deadline without asking
       for the work twice. The separate auto-reset event wakes a monitor that was waiting without a deadline. */
    if (os_ending(reason) && InterlockedCompareExchange64(&stop_deadline,
            (LONG64)(GetTickCount64() + STOP_WAIT_MS), 0) == 0) SetEvent(stop_changed);
    if (InterlockedCompareExchange(&stop_reason, reason, 0) == 0) {
        SetEvent(stop_requested);
        SetEvent(stop_changed);
    }
}

static DWORD stop_remaining(void) {
    const ULONGLONG deadline = (ULONGLONG)InterlockedCompareExchange64(&stop_deadline, 0, 0);
    if (!deadline) return INFINITE;
    const ULONGLONG now = GetTickCount64();
    return now < deadline ? (DWORD)(deadline - now) : 0;
}

static BOOL WINAPI stop_console(DWORD event) {
    LONG reason;
    switch (event) {
    case CTRL_C_EVENT: reason = STOP_CTRL_C; break;
    case CTRL_BREAK_EVENT: reason = STOP_CTRL_BREAK; break;
    case CTRL_CLOSE_EVENT: reason = STOP_CONSOLE_CLOSE; break;
    case CTRL_LOGOFF_EVENT: reason = STOP_LOGOFF; break;
    case CTRL_SHUTDOWN_EVENT: reason = STOP_SHUTDOWN; break;
    default: return FALSE;
    }
    request_stop(reason);
    /* Returning from CLOSE/LOGOFF/SHUTDOWN ends the process even with TRUE. Leave the normal worker time to
       finish instead. Windows may impose a shorter deadline; never promise that its shutdown can be postponed. */
    if (os_ending(reason)) Sleep(stop_remaining());
    return TRUE;
}

static LRESULT CALLBACK stop_window(HWND window, UINT message, WPARAM wp, LPARAM lp) {
    switch (message) {
    case WM_CLOSE:
        request_stop(STOP_WINDOW);
        return 0;
    case WM_QUERYENDSESSION:
        return TRUE;   /* a query can be cancelled: don't quit until WM_ENDSESSION(TRUE) */
    case WM_ENDSESSION:
        if (wp) {
            request_stop(STOP_SESSION);
            /* Returning allows Windows to end the process. The worker is independent of this message pump. */
            Sleep(stop_remaining());
        }
        return 0;
    }
    return DefWindowProcW(window, message, wp, lp);
}

static DWORD WINAPI stop_worker(void *unused) {
    (void)unused;
    WaitForSingleObject(stop_requested, INFINITE);
    const LONG reason = InterlockedCompareExchange(&stop_reason, 0, 0);
    if (!reason) return 0;   /* startup failed before any handler/window was installed */
    static const char *const reasons[] = {"", "Ctrl+C", "Ctrl+Break", "console close", "console logoff",
                                         "console shutdown", "WM_CLOSE", "WM_ENDSESSION"};
    hos_log("stop: requested by %s; wait for close-work marker and process exit 0; %s", reasons[reason],
            os_ending(reason) ? "OS-ending event: at most 4000 ms" : "no forced deadline unless Windows later ends the session");
    hos_log_flush();
    rx_close_asked();
    hos_close_finish();
    /* ExitProcess ends the monitor before DLL detach. Only this explicit windowless event route bypasses
       detach, after the close hooks and log flush returned; the window/restart and control exits stay unchanged. */
    TerminateProcess(GetCurrentProcess(), 0);
    return 0;
}

static DWORD WINAPI stop_messages(void *unused) {
    (void)unused;
    WNDCLASSW wc = {0};
    wc.lpfnWndProc = stop_window;
    wc.hInstance = GetModuleHandleW(NULL);
    wc.lpszClassName = L"HookshotHeadlessStop";
    if (!RegisterClassW(&wc) || !CreateWindowExW(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, wc.lpszClassName,
            L"Hookshot windowless stop", WS_OVERLAPPED, 0, 0, 0, 0, NULL, NULL, wc.hInstance, NULL)) {
        hos_log("stop: hidden window unavailable (error %lu); use the control bridge", (unsigned long)GetLastError());
    }
    /* CREATE_NEW_PROCESS_GROUP can leave Ctrl+C ignored by inheritance. Opt this process back in. */
    if (!SetConsoleCtrlHandler(NULL, FALSE) || !SetConsoleCtrlHandler(stop_console, TRUE))
        hos_log("stop: console handler unavailable (error %lu); use the control bridge", (unsigned long)GetLastError());
    SetEvent(stop_ready);
    for (;;) {
        /* No logging here: a blocked log writer must not defeat an OS-ending event's deadline. */
        DWORD remaining = stop_remaining();
        if (!remaining) {
            TerminateProcess(GetCurrentProcess(), STOP_TIMEOUT_EXIT);
            return 0;
        }
        MsgWaitForMultipleObjects(1, &stop_changed, FALSE, remaining, QS_ALLINPUT);
        MSG msg;
        /* Bound each batch: a stream of queued messages cannot starve the deadline. */
        for (int n = 0; n < 32 && PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE); n++) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
}

static void stop_free_events(void) {
    if (stop_requested) CloseHandle(stop_requested);
    if (stop_changed) CloseHandle(stop_changed);
    if (stop_ready) CloseHandle(stop_ready);
    stop_requested = stop_changed = stop_ready = NULL;
}

int hos_windows_stop_start(void) {
    stop_requested = CreateEventW(NULL, TRUE, FALSE, NULL);
    stop_changed = CreateEventW(NULL, FALSE, FALSE, NULL);
    stop_ready = CreateEventW(NULL, TRUE, FALSE, NULL);
    if (!stop_requested || !stop_changed || !stop_ready) { stop_free_events(); return 0; }
    HANDLE worker = CreateThread(NULL, 0, stop_worker, NULL, 0, NULL);
    if (!worker) { stop_free_events(); return 0; }
    HANDLE messages = CreateThread(NULL, 0, stop_messages, NULL, 0, NULL);
    if (!messages) {
        SetEvent(stop_requested);   /* reason 0: release the idle worker without closing the game */
        DWORD ended = WaitForSingleObject(worker, STOP_WAIT_MS);
        CloseHandle(worker);
        if (ended == WAIT_OBJECT_0) stop_free_events();   /* otherwise its handles live until process exit */
        return 0;
    }
    CloseHandle(worker);
    CloseHandle(messages);
    /* A late startup can still finish. Keep its handles live, and let the caller report this timeout without
       reading an unrelated GetLastError. Failure of this best-effort route must not end an offscreen run. */
    return WaitForSingleObject(stop_ready, STOP_WAIT_MS) == WAIT_OBJECT_0;
}
#endif
