/* Linux's CreateThread when its own memory is refused (host/posix/win32_posix.c, issue 333): the out-of-memory notice is
   started on a thread after a host allocation kept failing, so the thread's calloc may be refused too. The real thread_new
   and CreateThread, cut out by tests/test_host_alloc_wait.py, with a calloc that can refuse and pthread stand-ins: NULL and
   ERROR_NOT_ENOUGH_MEMORY, not a write through NULL; and a thread started as before when memory is there. Builds on any
   host (no pthread: the stand-ins below). */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned long DWORD;
typedef size_t SIZE_T;
typedef void *HANDLE;
typedef int pid_t_fake;
typedef DWORD (*LPTHREAD_START_ROUTINE)(void *);
typedef struct { int type; } HObj;
typedef struct { int unused; } fake_pthread_t, fake_mutex_t, fake_cond_t, fake_attr_t;
#define pthread_t fake_pthread_t
#define pthread_mutex_t fake_mutex_t
#define pthread_cond_t fake_cond_t
#define pthread_attr_t fake_attr_t
#define pid_t pid_t_fake
#define H_THREAD 7
#define CREATE_SUSPENDED 4
#define ERROR_NOT_ENOUGH_MEMORY 8L
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL %s:%d: %s\n", scenario, __LINE__, #x); exit(1); } } while (0)

static const char *scenario;
static DWORD last_error;
static int refuse_calloc, creates, inits;
static void *fake_calloc(size_t n, size_t s) { return refuse_calloc ? NULL : calloc(n, s); }
static void monitor_init(fake_mutex_t *m, fake_cond_t *c) { (void)m, (void)c, inits++; }
static DWORD error_of(int e) { return (DWORD)e; }
static void *thread_entry(void *arg);
static int pthread_attr_init(fake_attr_t *a) { (void)a; return 0; }
static int pthread_attr_destroy(fake_attr_t *a) { (void)a; return 0; }
static int pthread_attr_setstacksize(fake_attr_t *a, size_t n) { (void)a, (void)n; return 0; }
static int pthread_attr_setdetachstate(fake_attr_t *a, int d) { (void)a, (void)d; return 0; }
#define PTHREAD_CREATE_DETACHED 1
static int pthread_create(fake_pthread_t *th, const fake_attr_t *a, void *(*fn)(void *), void *arg) {
    (void)th, (void)a, (void)fn, (void)arg, creates++;
    return 0;
}
static void sched_yield(void) {}
#define calloc fake_calloc
#include "posix_thread_oom.inc"
#undef calloc
static void *thread_entry(void *arg) { return arg; }
static DWORD fn(void *arg) { (void)arg; return 0; }

int main(int argc, char **argv) {
    scenario = argc > 1 ? argv[1] : "posix-thread";
    refuse_calloc = 1;
    CHECK(CreateThread(NULL, 0, fn, NULL, 0, NULL) == NULL);
    CHECK(last_error == ERROR_NOT_ENOUGH_MEMORY && creates == 0 && inits == 0);
    refuse_calloc = 0, last_error = 0;
    HThread *t = (HThread *)CreateThread(NULL, 0, fn, (void *)1, 0, NULL);
    CHECK(t && t->h.type == H_THREAD && t->fn == fn && t->arg == (void *)1 && t->refs == 2 && creates == 1 && inits == 1);
    free(t);
    printf("PASS %s\n", scenario);
    return 0;
}
