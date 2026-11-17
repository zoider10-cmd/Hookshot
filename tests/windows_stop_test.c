/* Win32 API stand-ins only: no real window, console, process exit or game. */
#define _CRT_SECURE_NO_WARNINGS
#include <assert.h>
#include <setjmp.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>

typedef int BOOL;
typedef int32_t LONG;
typedef int64_t LONG64;
typedef uint32_t DWORD, UINT;
typedef uint64_t ULONGLONG;
typedef uintptr_t WPARAM;
typedef intptr_t LPARAM, LRESULT;
typedef void *HANDLE, *HWND, *HINSTANCE;
typedef struct { LRESULT (*lpfnWndProc)(HWND, UINT, WPARAM, LPARAM); HINSTANCE hInstance; const wchar_t *lpszClassName; } WNDCLASSW;
typedef struct { UINT message; } MSG;
#define WINAPI
#define CALLBACK
#define TRUE 1
#define FALSE 0
#define INFINITE UINT32_MAX
#define WAIT_OBJECT_0 0
#define WAIT_TIMEOUT 258
#define CTRL_C_EVENT 0
#define CTRL_BREAK_EVENT 1
#define CTRL_CLOSE_EVENT 2
#define CTRL_LOGOFF_EVENT 5
#define CTRL_SHUTDOWN_EVENT 6
#define WM_CLOSE 16
#define WM_QUERYENDSESSION 17
#define WM_ENDSESSION 22
#define WS_EX_TOOLWINDOW 0x80
#define WS_EX_NOACTIVATE 0x08000000
#define WS_OVERLAPPED 0
#define QS_ALLINPUT 0x4ff
#define PM_REMOVE 1

static ULONGLONG now, rx_delay;
static int requested, signals, changed, wakes, sleeps, work, flushes, closes, default_calls, windows, registrations;
static int event_calls, thread_calls, closed_events, aborted_worker, ready_timeout, join_timeout;
static int fail_event, fail_thread, force_code, in_handler, flood, messages_seen;
static int watchdog_alive, exit_process_calls, detach_blocked, scenario, promoted;
static LONG inject_reason;
static DWORD last_sleep;
static jmp_buf escaped;
static DWORD (*threads[2])(void *);
static char logs[2048];
static void request_stop(LONG reason);
static LONG InterlockedCompareExchange(volatile LONG *value, LONG set, LONG expected) {
    LONG old = *value;
    if (old == expected) *value = set;
    return old;
}
static LONG64 InterlockedCompareExchange64(volatile LONG64 *value, LONG64 set, LONG64 expected) {
    LONG64 old = *value;
    if (old == expected) *value = set;
    return old;
}
static ULONGLONG GetTickCount64(void) { return now; }
static BOOL SetEvent(HANDLE event) {
    if (event == (HANDLE)(uintptr_t)1) { requested = 1; signals++; }
    if (event == (HANDLE)(uintptr_t)2) { changed = 1; wakes++; }
    return TRUE;
}
static DWORD WaitForSingleObject(HANDLE event, DWORD ms) {
    (void)ms;
    if (event == (HANDLE)(uintptr_t)1) return requested ? WAIT_OBJECT_0 : WAIT_TIMEOUT;
    if (event == (HANDLE)(uintptr_t)3) return ready_timeout ? WAIT_TIMEOUT : WAIT_OBJECT_0;
    assert(event == (HANDLE)(uintptr_t)11 && requested && thread_calls == 2);
    if (join_timeout) return WAIT_TIMEOUT;
    assert(threads[0](NULL) == 0);   /* startup abort must not perform close work */
    aborted_worker++;
    return WAIT_OBJECT_0;
}
static void Sleep(DWORD ms) { assert(ms != INFINITE); last_sleep = ms; sleeps++; now += ms; }
static LRESULT DefWindowProcW(HWND w, UINT message, WPARAM wp, LPARAM lp) {
    (void)w; (void)message; (void)wp; (void)lp; default_calls++; return 99;
}
void hos_log(const char *format, ...) {
    assert(!in_handler);
    va_list ap;
    va_start(ap, format);
    size_t n = strlen(logs);
    vsnprintf(logs + n, sizeof logs - n, format, ap);
    va_end(ap);
}
void hos_log_flush(void) { assert(!in_handler); flushes++; }
void rx_close_asked(void) { assert(!in_handler); work++; now += rx_delay; }
void hos_close_finish(void) {
    assert(!in_handler && work == 1);
    closes++;
    hos_log("stop: close work done (a file the game was writing waited for, at most 3 s)");
    hos_log_flush();
}
/* ExitProcess kills the watchdog BEFORE entering a potentially stuck DLL detach. The old fixture just
   longjmp'ed from the close wrapper, which could not distinguish this lifetime from a safe termination. */
void ExitProcess(UINT code) {
    assert(code == 0);
    exit_process_calls++;
    watchdog_alive = 0;
    detach_blocked = 1;
    longjmp(escaped, 3);   /* simulated process still stuck, with no watchdog left to run */
}
void hos_window_closed_exit(void) { hos_close_finish(); ExitProcess(0); }   /* the former worker route */
static HINSTANCE GetModuleHandleW(const wchar_t *name) { assert(!name); return (HINSTANCE)(uintptr_t)3; }
static int RegisterClassW(const WNDCLASSW *wc) { assert(wc->lpfnWndProc); return 1; }
static HWND CreateWindowExW(DWORD ex, const wchar_t *cls, const wchar_t *title, DWORD style,
                            int x, int y, int w, int h, HWND parent, HANDLE menu, HINSTANCE instance, void *arg) {
    (void)cls; (void)title; (void)x; (void)y; (void)w; (void)h; (void)menu; (void)instance; (void)arg;
    assert(ex == (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE));
    assert(style == WS_OVERLAPPED && parent == NULL);
    windows++;
    return (HWND)(uintptr_t)4;
}
static DWORD GetLastError(void) { return 8; }
static BOOL SetConsoleCtrlHandler(BOOL (*fn)(DWORD), BOOL add) {
    if (!fn) { assert(!add); return TRUE; }
    assert(add); registrations++; return TRUE;
}
static HANDLE GetCurrentProcess(void) { return (HANDLE)(uintptr_t)5; }
static BOOL TerminateProcess(HANDLE process, UINT code) {
    assert(!in_handler && process == GetCurrentProcess());
    assert(watchdog_alive);   /* a dead monitor cannot rescue ExitProcess's DLL detach */
    if (!code) assert(work == 1 && closes == 1 && flushes == 2);
    force_code = (int)code;
    longjmp(escaped, 2);
}
static DWORD MsgWaitForMultipleObjects(DWORD n, const HANDLE *events, BOOL all, DWORD ms, DWORD mask) {
    assert(n == 1 && *events == (HANDLE)(uintptr_t)2 && !all && mask == QS_ALLINPUT);
    if (inject_reason) { LONG reason = inject_reason; inject_reason = 0; request_stop(reason); return 0; }
    if (changed) { changed = 0; return 0; }
    if (scenario == 1) {
        assert(ms == INFINITE); now += 12000; longjmp(escaped, 4);   /* still waiting, not force-killed */
    }
    if (scenario == 2 && !promoted) {
        assert(ms == INFINITE); now += 12000; promoted = 1; request_stop(3); return 0; /* console close */
    }
    assert(ms != INFINITE && ms <= 4000);
    now += flood && ms > 250 ? 250 : ms;
    return 0;
}
static BOOL PeekMessageW(MSG *msg, HWND window, UINT low, UINT high, UINT mode) {
    (void)window; (void)low; (void)high; assert(mode == PM_REMOVE);
    msg->message = 0;
    if (flood) { messages_seen++; return TRUE; }
    return FALSE;
}
static BOOL TranslateMessage(const MSG *msg) { (void)msg; return TRUE; }
static LRESULT DispatchMessageW(const MSG *msg) { (void)msg; return 0; }
static HANDLE CreateEventW(void *security, BOOL manual, BOOL initial, const wchar_t *name) {
    assert(!security && !initial && !name);
    event_calls++;
    assert(manual == (event_calls != 2));
    return event_calls == fail_event ? NULL : (HANDLE)(uintptr_t)event_calls;
}
static HANDLE CreateThread(void *security, size_t stack, DWORD (*fn)(void *), void *arg, DWORD flags, DWORD *id) {
    assert(!security && !stack && !arg && !flags && !id);
    assert(thread_calls < 2);
    threads[thread_calls++] = fn;
    return thread_calls == fail_thread ? NULL : (HANDLE)(uintptr_t)(10 + thread_calls);
}
static BOOL CloseHandle(HANDLE handle) { assert(handle); if ((uintptr_t)handle <= 3) closed_events++; return TRUE; }

/* ACTUAL_WINDOWS_STOP */

static void reset(void) {
    now = 100; rx_delay = 0;
    stop_requested = (HANDLE)(uintptr_t)1;
    stop_changed = (HANDLE)(uintptr_t)2;
    stop_ready = (HANDLE)(uintptr_t)3;
    stop_reason = 0; stop_deadline = 0;
    requested = signals = changed = wakes = sleeps = work = flushes = closes = default_calls = windows = registrations = 0;
    event_calls = thread_calls = closed_events = aborted_worker = ready_timeout = join_timeout = 0;
    fail_event = fail_thread = in_handler = flood = messages_seen = exit_process_calls = detach_blocked = scenario = promoted = 0;
    watchdog_alive = 1; force_code = -1; inject_reason = 0;
    last_sleep = 0; logs[0] = 0;
}

int main(void) {
    const DWORD events[] = {CTRL_C_EVENT, CTRL_BREAK_EVENT, CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT};
    for (size_t i = 0; i < sizeof events / sizeof events[0]; i++) {
        reset(); in_handler = 1;
        assert(!stop_console(99) && !requested);
        assert(stop_console(events[i]));
        assert(signals == 1 && stop_reason == (LONG)i + 1);
        assert(stop_deadline == (i < 2 ? 0 : 4100));
        assert(work == 0 && closes == 0 && flushes == 0 && logs[0] == 0);
        assert(sleeps == (i >= 2) && (i < 2 || last_sleep == STOP_WAIT_MS));
        assert(stop_console(CTRL_BREAK_EVENT) && signals == 1);
        assert(stop_reason == (LONG)i + 1 && stop_deadline == (i < 2 ? 0 : 4100));
        in_handler = 0;
    }
    reset(); request_stop(STOP_CONSOLE_CLOSE); now += 1500; in_handler = 1;
    assert(stop_console(CTRL_LOGOFF_EVENT) && last_sleep == 2500 && now == 4100);
    assert(signals == 1 && stop_deadline == 4100); in_handler = 0;
    puts("PASS: console handlers only request; OS-ending events share the remaining deadline, ordinary events have none");

    reset();
    assert(stop_window(NULL, WM_QUERYENDSESSION, 0, 0) == TRUE);
    assert(stop_window(NULL, WM_ENDSESSION, 0, 0) == 0 && signals == 0 && !stop_deadline);
    assert(stop_window(NULL, 99, 0, 0) == 99 && default_calls == 1);
    in_handler = 1;
    assert(stop_window(NULL, WM_CLOSE, 0, 0) == 0 && signals == 1 && work == 0 && !stop_deadline);
    assert(stop_window(NULL, WM_CLOSE, 0, 0) == 0 && signals == 1);
    now += 1500;
    assert(stop_window(NULL, WM_ENDSESSION, 1, 0) == 0 && last_sleep == 4000 && stop_deadline == 5600);
    assert(signals == 1 && stop_reason == STOP_WINDOW && stop_remaining() == 0); in_handler = 0;
    reset(); assert(stop_window(NULL, WM_ENDSESSION, 1, 0) == 0);
    assert(stop_reason == STOP_SESSION && signals == 1 && last_sleep == STOP_WAIT_MS);
    puts("PASS: WM_CLOSE has no forced deadline; only confirmed end-session arms it, without repeating close work");

    const LONG ordinary[] = {STOP_CTRL_C, STOP_CTRL_BREAK, STOP_WINDOW};
    for (size_t i = 0; i < sizeof ordinary / sizeof ordinary[0]; i++) {
        reset(); request_stop(ordinary[i]); scenario = 1;
        if (!setjmp(escaped)) stop_messages(NULL);
        assert(now == 12100 && force_code == -1 && !stop_deadline && signals == 1);
        reset(); request_stop(ordinary[i]); rx_delay = 12000;
        if (!setjmp(escaped)) stop_worker(NULL);
        assert(force_code == 0 && !exit_process_calls && !detach_blocked && watchdog_alive);
        assert(now == 12100 && work == 1 && closes == 1 && flushes == 2);
        assert(strstr(logs, "no forced deadline") && strstr(logs, "a file the game was writing waited for, at most 3 s"));
    }
    reset(); request_stop(STOP_SESSION);
    if (!setjmp(escaped)) stop_worker(NULL);
    assert(force_code == 0 && !exit_process_calls && !detach_blocked && watchdog_alive && flushes == 2);
    puts("PASS: slow ordinary closes finish; completed event close terminates after flush, never entering DLL detach");

    for (int mode = 0; mode < 2; mode++) {
        reset(); inject_reason = STOP_SESSION; flood = mode;
        if (!setjmp(escaped)) stop_messages(NULL);
        assert(force_code == STOP_TIMEOUT_EXIT && now == 4100);
        assert(windows == 1 && registrations == 1 && signals == 1 && work == 0 && logs[0] == 0);
        assert(!mode || messages_seen > 32);
    }
    reset(); request_stop(STOP_CTRL_C); scenario = 2;
    if (!setjmp(escaped)) stop_messages(NULL);
    assert(force_code == STOP_TIMEOUT_EXIT && now == 16100 && promoted && signals == 1);
    assert(stop_reason == STOP_CTRL_C && stop_deadline == 16100 && wakes == 2);
    puts("PASS: OS deadline bounds a stuck worker and queued-message flood; later OS event wakes an unbounded close");

    reset(); assert(hos_windows_stop_start() && event_calls == 3 && thread_calls == 2);
    assert(threads[0] == stop_worker && threads[1] == stop_messages);
    for (int i = 1; i <= 3; i++) {
        reset(); fail_event = i;
        assert(!hos_windows_stop_start() && thread_calls == 0 && closed_events == 2);
        assert(!stop_requested && !stop_changed && !stop_ready);
    }
    reset(); fail_thread = 1;
    assert(!hos_windows_stop_start() && closed_events == 3 && work == 0);
    reset(); fail_thread = 2;
    assert(!hos_windows_stop_start() && aborted_worker == 1 && closed_events == 3 && work == 0);
    reset(); fail_thread = 2; join_timeout = 1;
    assert(!hos_windows_stop_start() && closed_events == 0 && stop_requested && work == 0);
    reset(); ready_timeout = 1;
    assert(!hos_windows_stop_start() && closed_events == 0 && stop_requested && work == 0);
    puts("PASS: setup failures release idle resources safely or retain live handles, without closing the game");
    return 0;
}
