/* The host's allocations at the commit limit (host/mkw_glue.c, issue 333), around the real hos_out_of_memory and
   hos_alloc_failed cut out by tests/test_host_alloc_wait.py: a fake malloc that fails as Windows' does at the limit, a
   clock that Sleep moves, a notice that is counted, and a hos_fatal that returns here. No game, window or GPU.
   Built twice on any host: -DFIXTURE_LINUX=0 runs the cut code's Windows side (GlobalMemoryStatusEx, page file wording),
   -DFIXTURE_LINUX=1 its Linux side (sysinfo, swap wording), each with the stubs below. */
#include <setjmp.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#if FIXTURE_LINUX   /* (after the C library's headers: only the cut code sees the platform chosen here) */
#undef _WIN32
#elif !defined _WIN32
#define _WIN32 1
#endif
#ifdef _WIN32
#define OOM_LINE "mem: Windows is out of memory (RAM and page file)"
#define OOM_FATAL "out of memory (RAM plus the page file): "
#else
#define OOM_LINE "mem: out of memory (RAM and swap)"
#define OOM_FATAL "out of memory (RAM plus swap): "
#endif

typedef long LONG;
typedef unsigned long DWORD;
typedef void *LPVOID, *HANDLE;
typedef DWORD (*LPTHREAD_START_ROUTINE)(LPVOID);
typedef struct { DWORD dwLength; unsigned long long ullAvailPageFile; } MEMORYSTATUSEX;
#define WINAPI
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL %s:%d: %s\n", scenario, __LINE__, #x); exit(1); } } while (0)

static const char *scenario;
static unsigned long long slept_ms, left_mb = 10;
static int fails_left, fail_all, headless, boxes, box_closing, threads, deferred_thread, no_thread, fatals, sleeps_to_close = -1;
static const char *refuse_env;
static char logs[8192], fatal_text[512];
static jmp_buf fatal_jump;
static volatile LONG oom_state;

static LONG InterlockedExchange(volatile LONG *p, LONG v) { LONG o = *p; *p = v; return o; }
static LONG InterlockedIncrement(volatile LONG *p) { return ++*p; }
static LONG InterlockedCompareExchange(volatile LONG *p, LONG x, LONG c) { LONG o = *p; if (o == c) *p = x; return o; }
static void Sleep(DWORD ms) {
    slept_ms += ms;
    if (sleeps_to_close > 0 && --sleeps_to_close == 0) oom_state = 2;   /* (another thread's notice closed) */
}
static int CloseHandle(HANDLE h) { (void)h; return 1; }
static HANDLE CreateThread(void *a, size_t s, LPTHREAD_START_ROUTINE fn, LPVOID arg, DWORD f, DWORD *id) {
    (void)a, (void)s, (void)f, (void)id;
    if (no_thread) return NULL;   /* (the thread's own memory refused too: win32_posix.c's CreateThread says so with NULL) */
    threads++;
    if (!deferred_thread) fn(arg);   /* (deferred: the notice stays up on its thread) */
    return (HANDLE)1;
}
#ifdef _WIN32
static int GlobalMemoryStatusEx(MEMORYSTATUSEX *m) { m->ullAvailPageFile = left_mb << 20; return 1; }
#else
struct sysinfo { unsigned long freeram, bufferram, freeswap; unsigned mem_unit; };
static int sysinfo(struct sysinfo *si) {   /* (left_mb as free RAM, buffers and swap in 4 KB units) */
    si->mem_unit = 4096, si->freeram = (unsigned long)(left_mb << 8) - 3, si->bufferram = 1, si->freeswap = 2;
    return 0;
}
#endif
static int env_on(const char *name) { return !strcmp(name, "HOS_HEADLESS") && headless; }
static const char *test_getenv(const char *name) { return !strcmp(name, "HOS_TEST_ALLOC_REFUSE") ? refuse_env : NULL; }
static void hos_log(const char *fmt, ...) {
    char line[512];
    va_list a;
    va_start(a, fmt);
    vsnprintf(line, sizeof line, fmt, a);
    va_end(a);
    strncat(logs, line, sizeof logs - strlen(logs) - 2);
    strcat(logs, "\n");
}
static void hos_fatal(void *c, const char *fmt, ...) {
    (void)c;
    va_list a;
    va_start(a, fmt);
    vsnprintf(fatal_text, sizeof fatal_text, fmt, a);
    va_end(a);
    fatals++;
    longjmp(fatal_jump, 1);
}
DWORD WINAPI hos_out_of_memory_box(LPVOID closing) { boxes++, box_closing = closing != NULL; return 0; }
/* (Windows' malloc at the commit limit: NULL, for fails_left tries or all of them) */
static int refuse_now(void) { return fail_all || (fails_left > 0 && fails_left--); }
static void *fake_malloc(size_t n) { return refuse_now() ? NULL : malloc(n); }
static void *fake_calloc(size_t n, size_t s) { return refuse_now() ? NULL : calloc(n, s); }
static void *fake_realloc(void *p, size_t n) { return refuse_now() ? NULL : realloc(p, n); }
#define malloc fake_malloc
#define calloc fake_calloc
#define realloc fake_realloc
#define getenv test_getenv
#include "host_alloc_wait.inc"
#undef malloc
#undef calloc
#undef realloc

/* run stmt: 1 if it reached hos_fatal */
#define STOPS(stmt) (setjmp(fatal_jump) ? 1 : ((stmt), 0))

int main(int argc, char **argv) {
    scenario = argc > 1 ? argv[1] : "";
    void *volatile p = NULL;
    if (!strcmp(scenario, "recovers")) {   /* (refused 3 times: allocated on the 3rd try again, 150 ms on) */
        fails_left = 3;
        CHECK(!STOPS(p = hos_xmalloc(4096, "native NVN: recording copy")));
        CHECK(p && slept_ms == 150 && strstr(logs, "native NVN: recording copy: 4096 bytes of host memory at the commit limit allocated after 150 ms"));
        CHECK(!boxes && !fatals && !strstr(logs, "out of memory"));
        fails_left = 2;   /* realloc: the old block is kept while it waits, and comes back whole */
        memcpy(p, "kept", 5);
        CHECK(!STOPS(p = hos_xrealloc(p, 1 << 20, "native NVN: command buffer table")));
        CHECK(p && !memcmp(p, "kept", 5) && slept_ms == 250);
        CHECK(!STOPS(p = hos_xcalloc(1000, 8, "native NVN: recording handle set")));   /* (fast path: no wait) */
        CHECK(p && ((uint64_t *)p)[999] == 0 && slept_ms == 250);
    } else if (!strcmp(scenario, "limit")) {   /* (never given: 5 s, the line, the notice shown here, then the fatal) */
        fail_all = 1;
        CHECK(STOPS(hos_xcalloc(131072, 8, "native NVN: recording handle set")));
        CHECK(slept_ms == 5000 && fatals == 1);
        CHECK(strstr(logs, "native NVN: recording handle set: 1048576 bytes of host memory still refused after 5 s at the commit limit (10 MB of commit left)"));
        CHECK(strstr(logs, OOM_LINE));
        CHECK(boxes == 1 && box_closing && threads == 1);   /* (on a thread of its own: on the game's, nothing showed) */
        CHECK(!strcmp(fatal_text, OOM_FATAL "native NVN: recording handle set (1048576 bytes)"));
        CHECK(oom_state == 2);
        hos_out_of_memory(0);   /* (a guest commit refused after: said once) */
        CHECK(boxes == 1 && threads == 1);
        const char *line = strstr(logs, OOM_LINE);
        CHECK(line && !strstr(line + 1, OOM_LINE));
    } else if (!strcmp(scenario, "commit-first")) {   /* (a guest commit said it first, its notice still up: waited for) */
        deferred_thread = 1;
        hos_out_of_memory(0);
        CHECK(threads == 1 && boxes == 0 && oom_state == 1);
        fail_all = 1, sleeps_to_close = 100 + 3;   /* (the 5 s, then 3 x 100 ms until the notice is closed) */
        CHECK(STOPS(hos_xmalloc(65536, "native NVN: recording buffer")));
        CHECK(slept_ms == 5000 + 300 && boxes == 0 && threads == 1 && oom_state == 2);
        CHECK(strstr(fatal_text, OOM_FATAL "native NVN: recording buffer (65536 bytes)"));
    } else if (!strcmp(scenario, "not-limit")) {   /* (refused with 20 GB of commit left: a size gone wrong, no notice) */
        fail_all = 1, left_mb = 20000;
        CHECK(STOPS(hos_xmalloc(4096, "video: image pool")));
        CHECK(slept_ms == 5000 && boxes == 0 && !strstr(logs, "out of memory"));
        CHECK(!strcmp(fatal_text, "video: image pool: 4096 bytes of host memory refused for 5 s with 20000 MB of commit left"));
    } else if (!strcmp(scenario, "overflow")) {   /* (calloc's count x size past size_t: at once) */
        CHECK(STOPS(hos_xcalloc((size_t)-1 / 4, 8, "native NVN: texture copies table")));
        CHECK(slept_ms == 0 && boxes == 0 && strstr(fatal_text, "is past the address space"));
    } else if (!strcmp(scenario, "headless")) {   /* (no notice to wait for: the line and the fatal) */
        fail_all = 1, headless = 1;
        CHECK(STOPS(hos_xmalloc(4096, "native NVN: recording copy")));
        CHECK(boxes == 0 && threads == 0 && strstr(logs, OOM_LINE) && strstr(fatal_text, "out of memory"));
    } else if (!strcmp(scenario, "no-thread")) {   /* (the notice's thread refused too: no notice, no wait, still the fatal) */
        fail_all = 1, no_thread = 1;
        CHECK(STOPS(hos_xmalloc(4096, "native NVN: recording copy")));
        CHECK(slept_ms == 5000 && boxes == 0 && threads == 0 && oom_state == 2 && strstr(logs, OOM_LINE));
        CHECK(!strcmp(fatal_text, OOM_FATAL "native NVN: recording copy (4096 bytes)"));
    } else if (!strcmp(scenario, "test-switch")) {   /* (HOS_TEST_ALLOC_REFUSE: that label refused as at the limit, others not) */
        refuse_env = "handle set", left_mb = 20000;
        CHECK(!STOPS(p = hos_xmalloc(64, "native NVN: recording copy")));
        CHECK(p && slept_ms == 0);
        CHECK(STOPS(hos_xcalloc(65536, 8, "native NVN: recording handle set")));
        CHECK(slept_ms == 5000 && boxes == 1 && box_closing && threads == 1);
        CHECK(!strcmp(fatal_text, OOM_FATAL "native NVN: recording handle set (524288 bytes)"));
    } else if (!strcmp(scenario, "renderer")) {   /* (issue 1280: the renderer's new_handler waited its 5 s; no size known) */
        CHECK(STOPS(hos_alloc_gave_up(0, "the renderer's C++ allocations")));
        CHECK(slept_ms == 0 && fatals == 1 && boxes == 1 && box_closing && threads == 1 && oom_state == 2);
        CHECK(strstr(logs, "mem: the renderer's C++ allocations: still refused after 5 s at the commit limit (10 MB of commit left)"));
        CHECK(strstr(logs, OOM_LINE) && !strstr(logs, "bytes"));
        CHECK(!strcmp(fatal_text, OOM_FATAL "the renderer's C++ allocations"));
    } else if (!strcmp(scenario, "renderer-not-limit")) {   /* (refused with 20 GB left: a size gone wrong, no notice) */
        left_mb = 20000;
        CHECK(STOPS(hos_alloc_gave_up(0, "the renderer's C++ allocations")));
        CHECK(boxes == 0 && threads == 0 && !strstr(logs, "out of memory"));
        CHECK(!strcmp(fatal_text, "the renderer's C++ allocations: refused for 5 s with 20000 MB of commit left"));
    } else if (!strcmp(scenario, "renderer-switch")) {   /* (HOS_TEST_ALLOC_REFUSE=renderer: its 1 PB ask, as at the limit) */
        refuse_env = "renderer", left_mb = 20000;
        CHECK(STOPS(hos_alloc_gave_up(0, "the renderer's C++ allocations")));
        CHECK(boxes == 1 && box_closing && strstr(logs, OOM_LINE));
        CHECK(!strcmp(fatal_text, OOM_FATAL "the renderer's C++ allocations"));
    } else {
        fprintf(stderr, "unknown scenario %s\n", scenario);
        return 2;
    }
    printf("PASS %s\n", scenario);
    return 0;
}
