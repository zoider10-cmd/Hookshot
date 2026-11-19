"""Condition variable hand-offs and the timed semaphore acquires on real threads, through the HLE entries themselves.

host/nn_os_sync.c reserves a guest mutex for the waiters a Signal or a Broadcast wakes (#156: Horizon moves them onto
the mutex), and a reservation belongs to the waiters that were in when it was made. The fixture compiles the real code
cut from the source: the Obj struct, the mutex (mutex_take, mutex_take_owed, mutex_give, mutex_lock, mutex_lock_owed,
mutex_unlock, mutex_release_all), the condition variable (cv_count_in, cv_enter, cv_leave, cv_reserve, wait_until) and
the semaphore (sema_release, sema_acquire_for), and calls the HLE entries by name: LockMutex, UnlockMutex,
SignalConditionVariable, BroadcastConditionVariable, WaitConditionVariable, TimedWaitConditionVariable,
ReleaseSemaphore, TimedAcquireSemaphore, TimedAcquireLightSemaphore, TryAcquireLightSemaphore. The Win32 lock is a
pthread mutex; the Win32 condition variable is a queue of sleepers, each queued before its lock is let go (as
SleepConditionVariableSRW does), woken newest first by default: Windows does not promise an order, and the Linux layer's
futex queue need not be the order the waiters came in.

Each ordering case holds the woken waiters at the end of their sleep (the gate: they let cv->lk go and wait, as a waiter
the scheduler has not run yet), until the thread under test has either come back or is asleep on the mutex; so the
order is decided by the code, not by the scheduler:
- review 1752: A waits; B locks the mutex, Broadcasts, then waits with a zero timeout. B times out at once and must
  relock behind A (A gets the mutex first). The same with a Signal.
- sol round 3: C and D wait; B Broadcasts and waits twice with a zero timeout: both get the mutex before B's first wait
  returns.
- #156: A waits; B Signals, unlocks and locks again: A gets the mutex first.
- Eight waiters owed the mutex by a broadcast (the most there can be), held; B then waits untimed and is signalled: B
  relocks after the eight.
With HOS_NO_HANDOFF=1 there are no reservations, and B gets the mutex first in all of them (the switch works).
- The one wake of a Signal: A waits; B locks the mutex; a thread without it Signals; B comes in right after the signal
  (an untimed wait), and the wake is made once B is either the newest sleeper or blocked on cv->lk. The wake must reach
  A (the modelled condition variable says whom it woke), and A must get the mutex.
- Made again with a waiter in (a misuse; obj_lookup's own branch for it, cut from the source: the generation, counts
  and reservations cleared, the life counted), each with the old waiter in a Wait and in a TimedWait:
  - A sleeps; made again; B waits; a wake that moves no generation reaches both: A comes out, B sleeps again, and A
    counts itself out of nothing new, so a Signal still finds B;
  - A sleeps; made again; C waits; a Signal reserves for C, and its wake goes to A (oldest first here). A, from an
    earlier life, takes no hand-off and passes the wake on: C comes out and gets the mutex first, and the mutex is free
    afterwards;
  - A sleeps (on one mutex); made again; B waits on another (held); a broadcast owes B its mutex; A comes out first and
    leaves B's hand-off alone;
  - A sleeps (on one mutex); made again; C waits on another; a Signal reserves C's mutex, and its one wake goes to A.
    A takes nothing there and passes the wake on (all of them): C comes out and takes its mutex, which another thread
    can then lock, not left reserved for a sleeper. Again with D coming in after the signal (A held at the gate) and the
    host waking newest first: one passed-on wake would reach D, which sleeps again; D must sleep on (the pass-on moves
    no generation);
  - A (on one mutex) and B (on the mutex C will use) sleep; made again; C waits; S, holding the mutex, Signals: it is
    reserved for C, whose wake is held at the gate. A comes out at a wake of its own (a spurious host wake, or its
    timeout) and passes it on: B, from the earlier life too, comes out and must not take C's hand-off, so S, unlocking
    and locking again, gets the mutex after C.
- Many rounds, no gate: four waiters (untimed and 1 ms timed waits), a thread that Broadcasts or Signals each one, then
  waits with a zero timeout: no stall (a watchdog on the rounds), and at the end nothing is owed.
- Semaphore: a release made while a 60 s TimedAcquireSemaphore sleeps wakes it (not its timeout); a
  TimedAcquireLightSemaphore of 30 ms with no release times out after 30 ms; TryAcquireLightSemaphore takes a count only
  when there is one; four threads timed-acquire 2,000 counts released one at a time, all taken, none left.
- bury_locked (its own fixture, the real struct and code over a fake clock): an object dead 30 s with a condition
  variable waiter still in is not made a spare (its lock and condition variable made again under the waiter); it is
  looked at again, and made a spare once the waiter is out.
Broken variants must fail, each at its own check: reservations any waiter takes (anonymous, as before the per-waiter
rule), a Signal that moves the generation before it reserves, a Signal that wakes after letting cv->lk go, a life not
counted when the object is made again, a waiter from an earlier life counted out of the new counts, taking a hand-off
on its own mutex, not passing its wake on while a hand-off is owed, passing on only one, or moving the generation as it
does, or (Wait, TimedWait) sleeping on at a wake, a TimedWait not passing its life, a Wait passing generation 0, a
release that does not wake the timed acquire, and bury_locked without its guard.

python -I -B tests/test_cv_handoff_threads.py [--cc gcc]
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # (python -I leaves the check's own folder off the path)
from srccut import between, block  # noqa: E402

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
HLE = {"@LOCK@": "HLE(_ZN2nn2os9LockMutexEPNS0_9MutexTypeE) {",
       "@UNLOCK@": "HLE(_ZN2nn2os11UnlockMutexEPNS0_9MutexTypeE) {",
       "@SIGNAL@": "HLE(_ZN2nn2os23SignalConditionVariableEPNS0_21ConditionVariableTypeE) {",
       "@BROADCAST@": "HLE(_ZN2nn2os26BroadcastConditionVariableEPNS0_21ConditionVariableTypeE) {",
       "@WAIT@": "HLE(_ZN2nn2os21WaitConditionVariableEPNS0_21ConditionVariableTypeEPNS0_9MutexTypeE) {",
       "@TIMED@": "HLE(_ZN2nn2os26TimedWaitConditionVariableEPNS0_21ConditionVariableTypeEPNS0_9MutexTypeENS_8TimeSpanE) {",
       "@RELEASE@": "HLE(_ZN2nn2os16ReleaseSemaphoreEPNS0_13SemaphoreTypeEi) {",
       "@TACQUIRE@": "HLE(_ZN2nn2os21TimedAcquireSemaphoreEPNS0_13SemaphoreTypeENS_8TimeSpanE) {",
       "@TLACQUIRE@": "HLE(_ZN2nn2os26TimedAcquireLightSemaphoreEPNS0_18LightSemaphoreTypeENS_8TimeSpanE) {",
       "@TRYLACQUIRE@": "HLE(_ZN2nn2os24TryAcquireLightSemaphoreEPNS0_18LightSemaphoreTypeE) {"}
FUNCS = ["static int handoff_on(void) {", "static int cv_signal_always(void) {", "static void cv_count_in(Obj *cv) {",
         "static void cv_enter(Obj *cv, Obj *m) {", "static int cv_same_life(Obj *cv, unsigned life) {",
         "static int cv_leave(Obj *cv, Obj *m, uint64_t gen, unsigned life) {", "static void cv_reserve(Obj *cv) {",
         "static int wait_until(Obj *o, int64_t deadline) {",
         "static int mutex_take(Obj *m, HosThread *self) {", "static int mutex_take_owed(Obj *m, HosThread *self) {",
         "static void mutex_give(Obj *m) {", "static void mutex_lock(Obj *m, uint64_t guest, Ctx *c) {",
         "static void mutex_lock_owed(Obj *m, uint64_t guest, int owed) {", "static int mutex_unlock(Obj *m) {",
         "static int mutex_release_all(Obj *m) {", "static void sema_release(Obj *s, int n) {",
         "static int sema_acquire_for(Obj *s, int64_t ns) {"]
# (obj_lookup's branch for an address made again, run by the fixture as remake_tomb(o, kind))
TOMB = "if (!o && (o = find_dead_locked(key))) {"
LIFE = "__atomic_store_n(&o->life, o->life + 1, __ATOMIC_SEQ_CST);"


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


FIXTURE = r'''#define _POSIX_C_SOURCE 200809L
#define _CRT_SECURE_NO_WARNINGS
#include <errno.h>
#include <pthread.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "longshot_env.h"   /* (env_on: the switches' one rule) */
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
typedef unsigned DWORD;
typedef long LONG;
#define INFINITE 0xFFFFFFFFu
static void sleep_ms(int ms) { struct timespec t = {ms / 1000, (long)(ms % 1000) * 1000000}; nanosleep(&t, NULL); }
static int64_t hos_now_ns(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (int64_t)t.tv_sec * 1000000000 + t.tv_nsec;
}
/* (the Win32 lock: a pthread mutex) */
typedef pthread_mutex_t SRWLOCK;
static _Thread_local int is_late;   /* (the late waiter: it says when it blocks on a lock) */
static int late_blocked;
static void AcquireSRWLockExclusive(SRWLOCK *l) {
    if (is_late && pthread_mutex_trylock(l) == 0) return;
    if (is_late) __atomic_store_n(&late_blocked, 1, __ATOMIC_SEQ_CST);
    pthread_mutex_lock(l);
    if (is_late) __atomic_store_n(&late_blocked, 0, __ATOMIC_SEQ_CST);
}
static void ReleaseSRWLockExclusive(SRWLOCK *l) { pthread_mutex_unlock(l); }
/* (the Win32 condition variable: its sleepers queued, newest at the head; a wake takes the newest, or the oldest) */
static _Thread_local int tid;   /* (a thread's number in a case, 0 when it has none) */
typedef struct CvNode { struct CvNode *next; int woken, tid; pthread_cond_t c; } CvNode;
typedef struct { CvNode *head; int sleepers; } CONDITION_VARIABLE;
static pthread_mutex_t cvq = PTHREAD_MUTEX_INITIALIZER;   /* (every queue; never held while a lock is taken) */
static int wake_oldest;
static int sleepers(CONDITION_VARIABLE *cv) { pthread_mutex_lock(&cvq); const int n = cv->sleepers; pthread_mutex_unlock(&cvq); return n; }
static int wake_hook(CONDITION_VARIABLE *cv);
static int hooked_woke = -1;   /* (the number of the thread the hooked wake reached, 0 none) */
static int cv_wake(CONDITION_VARIABLE *cv, int n) {   /* the first woken thread's number */
    int first = 0;
    pthread_mutex_lock(&cvq);
    for (int i = 0; i < n && cv->head; i++) {
        CvNode **pp = &cv->head;
        if (wake_oldest) while ((*pp)->next) pp = &(*pp)->next;
        CvNode *w = *pp;
        *pp = w->next, w->woken = 1, cv->sleepers--;
        if (!i) first = w->tid;
        pthread_cond_signal(&w->c);
    }
    pthread_mutex_unlock(&cvq);
    return first;
}
static void WakeConditionVariable(CONDITION_VARIABLE *cv) {
    const int hooked = wake_hook(cv);
    const int woke = cv_wake(cv, 1);
    if (hooked) __atomic_store_n(&hooked_woke, woke, __ATOMIC_SEQ_CST);
}
static void WakeAllConditionVariable(CONDITION_VARIABLE *cv) { cv_wake(cv, 1 << 30); }
static int cv_sleep(CONDITION_VARIABLE *cv, SRWLOCK *lk, unsigned ms) {   /* 1 when woken, 0 at its timeout */
    CvNode me = {0};
    me.tid = tid;
    clockid_t clock = CLOCK_REALTIME;
#if defined(__linux__)
    pthread_condattr_t attr;   /* (the deadline on the monotonic clock: a wall-clock step does not stretch it) */
    pthread_condattr_init(&attr);
    if (pthread_condattr_setclock(&attr, CLOCK_MONOTONIC) == 0) clock = CLOCK_MONOTONIC;
    pthread_cond_init(&me.c, &attr);
    pthread_condattr_destroy(&attr);
#else
    pthread_cond_init(&me.c, NULL);
#endif
    struct timespec until;
    clock_gettime(clock, &until);
    until.tv_sec += ms / 1000;
    until.tv_nsec += (long)(ms % 1000) * 1000000;
    if (until.tv_nsec >= 1000000000) until.tv_sec++, until.tv_nsec -= 1000000000;
    pthread_mutex_lock(&cvq);
    me.next = cv->head, cv->head = &me, cv->sleepers++;
    pthread_mutex_unlock(lk);   /* (queued before the lock is let go) */
    while (!me.woken)
        if (ms == INFINITE) pthread_cond_wait(&me.c, &cvq);
        else if (pthread_cond_timedwait(&me.c, &cvq, &until) == ETIMEDOUT) break;
    if (!me.woken) {
        CvNode **pp = &cv->head;
        while (*pp != &me) pp = &(*pp)->next;
        *pp = me.next, cv->sleepers--;
    }
    const int woken = me.woken;
    pthread_mutex_unlock(&cvq);
    pthread_cond_destroy(&me.c);
    pthread_mutex_lock(lk);
    return woken;
}
static LONG InterlockedIncrement(volatile LONG *v) { return __atomic_add_fetch(v, 1, __ATOMIC_SEQ_CST); }
struct HosThread { int id; };
typedef struct HosThread HosThread;
static _Thread_local HosThread me;
static HosThread *hos_self(void) { return &me; }
static const char *hos_thread_name(HosThread *t) { (void)t; return "thread"; }
static void hos_log(const char *fmt, ...) { va_list a; va_start(a, fmt); vfprintf(stderr, fmt, a); va_end(a); fputc('\n', stderr); }
static int hos_chain_on;
static void hos_chain_note(int kind, uint64_t key, uint64_t lr) { (void)kind, (void)key, (void)lr; }
enum { HOS_CHAIN_WAIT = 1, HOS_CHAIN_WOKE, HOS_CHAIN_SIGNAL };
#define HOS_CHAIN(kind, key) ((void)(kind), (void)(key))   /* (HOS_CHAIN off: host/hos.h) */
typedef struct { uint64_t x[31]; } Ctx;
#define ARG(i) (c->x[i])
#define RET(v) (c->x[0] = (uint64_t)(v))
#define HLE(name) static void name(Ctx *c)
enum { K_MUTEX = 1, K_COND, K_EVENT, K_SEMA };

@STRUCT@

static Obj cvo, mo, mo2, so;
static Obj *obj(uint64_t key, int kind) {
    Obj *o = key == 0x1000 ? &cvo : key == 0x2000 ? &mo : key == 0x2100 ? &mo2 : &so;
    CHECK(o->kind == kind);
    return o;
}
static void spin_until_free(Obj *o) { (void)o; }
@TOMB@
static void poke_multiwait(Obj *o) { (void)o; }
static volatile uint64_t watch_cvs[8];
static int watched(uint64_t m) { (void)m; return 0; }
static int watched_cv(uint64_t cv) { (void)cv; return 0; }
static uint64_t watch_mutex(void) { return 0; }
static void watch_log(const char *w, uint64_t m, uint64_t cv, Ctx *c, Obj *o) { (void)w, (void)m, (void)cv, (void)c, (void)o; }

/* the gate: a gated thread's sleep on the condition variable, once over, lets cv->lk go and waits for the gate to open
   (a waiter woken and not yet run), then takes cv->lk again and returns */
static _Thread_local int gated;
static int gate_open, in_gate, sema_woken = -1;
static int hos_cv_sleep(void *cv, void *lk, unsigned ms) {
    const int r = cv_sleep((CONDITION_VARIABLE *)cv, (SRWLOCK *)lk, ms);
    if (cv == (void *)&so.cv) __atomic_store_n(&sema_woken, r, __ATOMIC_SEQ_CST);
    if (gated && cv == (void *)&cvo.cv && !__atomic_load_n(&gate_open, __ATOMIC_SEQ_CST)) {
        __atomic_add_fetch(&in_gate, 1, __ATOMIC_SEQ_CST);
        pthread_mutex_unlock((pthread_mutex_t *)lk);
        while (!__atomic_load_n(&gate_open, __ATOMIC_SEQ_CST)) sleep_ms(1);
        pthread_mutex_lock((pthread_mutex_t *)lk);
    }
    return r;
}
/* the late-waiter hook: a Signal's wake waits until the waiter that came in after the signal is either asleep (the
   newest sleeper, so the wake finds it) or blocked on a lock (a Signal that wakes under cv->lk keeps it out) */
static int late_hook, in_wake;
static int wake_hook(CONDITION_VARIABLE *cv) {   /* 1 for the hooked wake */
    if (cv != &cvo.cv || !__atomic_exchange_n(&late_hook, 0, __ATOMIC_SEQ_CST)) return 0;
    __atomic_store_n(&in_wake, 1, __ATOMIC_SEQ_CST);
    const int64_t until = hos_now_ns() + 10000000000ll;
    while (sleepers(cv) < 2 && !__atomic_load_n(&late_blocked, __ATOMIC_SEQ_CST)) {
        CHECK(hos_now_ns() < until);
        sleep_ms(1);
    }
    return 1;
}

@FUNCS@
@LOCK@
@UNLOCK@
@SIGNAL@
@BROADCAST@
@WAIT@
@TIMED@
@RELEASE@
@TACQUIRE@
@TLACQUIRE@
@TRYLACQUIRE@

static void lock_k(uint64_t m) { Ctx c = {{m}}; _ZN2nn2os9LockMutexEPNS0_9MutexTypeE(&c); }
static void unlock_k(uint64_t m) { Ctx c = {{m}}; _ZN2nn2os11UnlockMutexEPNS0_9MutexTypeE(&c); }
static void lock_m(void) { lock_k(0x2000); }
static void unlock_m(void) { unlock_k(0x2000); }
static void signal_cv(void) { Ctx c = {{0x1000}}; _ZN2nn2os23SignalConditionVariableEPNS0_21ConditionVariableTypeE(&c); }
static void broadcast_cv(void) { Ctx c = {{0x1000}}; _ZN2nn2os26BroadcastConditionVariableEPNS0_21ConditionVariableTypeE(&c); }
static void wait_k(uint64_t m) { Ctx c = {{0x1000, m}}; _ZN2nn2os21WaitConditionVariableEPNS0_21ConditionVariableTypeEPNS0_9MutexTypeE(&c); }
static void wait_cv(void) { wait_k(0x2000); }
static int timed_cv(int64_t ns) {
    Ctx c = {{0x1000, 0x2000, (uint64_t)ns}};
    _ZN2nn2os26TimedWaitConditionVariableEPNS0_21ConditionVariableTypeEPNS0_9MutexTypeENS_8TimeSpanE(&c);
    return (int)c.x[0];
}
static int owns_m(void) { return __atomic_load_n(&mo.owner, __ATOMIC_SEQ_CST) == hos_self() && mo.count == 1; }

static int inited;
static void make(Obj *o, uint64_t key, int kind) {
    if (inited) pthread_mutex_destroy(&o->lk);
    memset(o, 0, sizeof *o);
    o->key = key, o->kind = kind;
    pthread_mutex_init(&o->lk, NULL);
}
static void reset(void) {   /* (between rounds every thread is joined) */
    make(&cvo, 0x1000, K_COND), make(&mo, 0x2000, K_MUTEX), make(&mo2, 0x2100, K_MUTEX), make(&so, 0x3000, K_SEMA);
    inited = 1, wake_oldest = 0;
    __atomic_store_n(&gate_open, 0, __ATOMIC_SEQ_CST), __atomic_store_n(&in_gate, 0, __ATOMIC_SEQ_CST);
}
static int seq;
static int next_seq(void) { return __atomic_add_fetch(&seq, 1, __ATOMIC_SEQ_CST); }
static int wait_for(int *flag, int64_t ms) {   /* 1 once *flag is set, 0 after ms */
    const int64_t until = hos_now_ns() + ms * 1000000;
    while (!__atomic_load_n(flag, __ATOMIC_SEQ_CST)) {
        if (hos_now_ns() > until) return 0;
        sleep_ms(1);
    }
    return 1;
}
static int wait_sleepers(CONDITION_VARIABLE *cv, int n) {
    const int64_t until = hos_now_ns() + 5000000000ll;
    while (sleepers(cv) < n) {
        if (hos_now_ns() > until) return 0;
        sleep_ms(1);
    }
    return 1;
}

/* ---- the ordering cases ---- */
enum { LATE_ONE, LATE_SIGNAL, LATE_TWO, SIGNAL_RELOCK };
/* (timed: a 60 s TimedWait, not a Wait; m: its mutex, 0 for mo) */
typedef struct { int locked, got, done, gate, timed, tid; uint64_t m; } Waiter;
static void *waiter(void *p) {
    Waiter *w = (Waiter *)p;
    const uint64_t m = w->m ? w->m : 0x2000;
    gated = w->gate, tid = w->tid;
    lock_k(m);
    __atomic_store_n(&w->locked, 1, __ATOMIC_SEQ_CST);
    if (w->timed) {
        Ctx c = {{0x1000, m, 60000000000ull}};
        _ZN2nn2os26TimedWaitConditionVariableEPNS0_21ConditionVariableTypeEPNS0_9MutexTypeENS_8TimeSpanE(&c);
    } else {
        wait_k(m);
    }
    CHECK(m != 0x2000 || owns_m());
    __atomic_store_n(&w->got, next_seq(), __ATOMIC_SEQ_CST);
    unlock_k(m);
    __atomic_store_n(&w->done, 1, __ATOMIC_SEQ_CST);
    return NULL;
}
static int kind, b_phase, b_done, b_back[2], b_ret[2];
static void *owner(void *p) {
    (void)p;
    lock_m();   /* (the last waiter gave the mutex back in its wait: all are in) */
    if (kind == SIGNAL_RELOCK) {
        signal_cv();
        __atomic_store_n(&b_phase, 1, __ATOMIC_SEQ_CST);
        unlock_m();
        lock_m();
        b_back[0] = next_seq();
    } else {
        if (kind == LATE_SIGNAL) signal_cv();
        else broadcast_cv();
        __atomic_store_n(&b_phase, 1, __ATOMIC_SEQ_CST);
        for (int i = 0; i < (kind == LATE_TWO ? 2 : 1); i++) {
            b_ret[i] = timed_cv(0);
            CHECK(owns_m());
            __atomic_store_n(&b_back[i], next_seq(), __ATOMIC_SEQ_CST);
        }
    }
    __atomic_store_n(&b_done, 1, __ATOMIC_SEQ_CST);
    unlock_m();
    return NULL;
}
static void ordering(int k, int handoff) {
    reset();
    kind = k, seq = 0, b_phase = b_done = 0;
    memset(b_back, 0, sizeof b_back), memset(b_ret, -1, sizeof b_ret);
    const int n = k == LATE_TWO ? 2 : 1;
    Waiter w[2] = {{.gate = 1}, {.gate = 1}};
    pthread_t tw[2], tb;
    for (int i = 0; i < n; i++) {
        pthread_create(&tw[i], NULL, waiter, &w[i]);
        CHECK(wait_for(&w[i].locked, 15000));
    }
    pthread_create(&tb, NULL, owner, NULL);
    /* the gate opens once B is back, or asleep on the mutex (mwait: B is the only thread that can be) */
    CHECK(wait_for(&b_phase, 15000));
    const int64_t until = hos_now_ns() + 5000000000ll;
    while (!__atomic_load_n(&b_done, __ATOMIC_SEQ_CST) && !__atomic_load_n(&mo.mwait, __ATOMIC_SEQ_CST)) {
        CHECK(hos_now_ns() < until);
        sleep_ms(1);
    }
    __atomic_store_n(&gate_open, 1, __ATOMIC_SEQ_CST);
    for (int i = 0; i < n; i++) CHECK(wait_for(&w[i].done, 15000));   /* (a stall: the process exits with the threads) */
    CHECK(wait_for(&b_done, 15000));
    for (int i = 0; i < n; i++) pthread_join(tw[i], NULL);
    pthread_join(tb, NULL);
    if (k != SIGNAL_RELOCK) for (int i = 0; i < n; i++) CHECK(b_ret[i] == 0);   /* (timed out: nothing signalled after it came in) */
    const int b_first = b_back[0], b_last = b_back[k == LATE_TWO ? 1 : 0];
    for (int i = 0; i < n; i++) {
        if (handoff) CHECK(w[i].got < b_first);   /* (the woken waiters get the mutex before B gets it back) */
        else CHECK(b_last < w[i].got);           /* (HOS_NO_HANDOFF=1: nothing reserved, B relocks first) */
    }
    CHECK(mo.reserved == 0 && cvo.cv_owed == 0 && cvo.cv_in == 0 && cvo.cv_waiting == 0 && !mo.owner);
}

/* a late untimed waiter: eight waiters (held at the gate) are owed the mutex by a broadcast, the most there can be;
   B, holding it, then waits (untimed) and is signalled (no reservation is left to make). B must not take one of the
   eight's: it relocks after them */
static int o_phase, o_back, o_done;
static void *late_owner(void *p) {
    (void)p;
    lock_m();
    broadcast_cv();
    __atomic_store_n(&o_phase, 1, __ATOMIC_SEQ_CST);
    wait_cv();
    CHECK(owns_m());
    o_back = next_seq();
    __atomic_store_n(&o_done, 1, __ATOMIC_SEQ_CST);
    unlock_m();
    return NULL;
}
static void late_untimed(int handoff) {
    reset();
    seq = 0, o_phase = o_back = o_done = 0;
    Waiter w[8];
    pthread_t tw[8], to;
    for (int i = 0; i < 8; i++) {
        memset(&w[i], 0, sizeof w[i]), w[i].gate = 1;
        pthread_create(&tw[i], NULL, waiter, &w[i]);
        CHECK(wait_for(&w[i].locked, 15000));
    }
    pthread_create(&to, NULL, late_owner, NULL);
    CHECK(wait_for(&o_phase, 15000));
    CHECK(wait_for(&in_gate, 15000));    /* (a woken waiter held) */
    CHECK(wait_sleepers(&cvo.cv, 1));   /* (B asleep: the broadcast took every earlier sleeper off the queue) */
    CHECK(__atomic_load_n(&mo.reserved, __ATOMIC_SEQ_CST) == (handoff ? 8 : 0));
    signal_cv();
    const int64_t until = hos_now_ns() + 5000000000ll;
    while (!__atomic_load_n(&o_done, __ATOMIC_SEQ_CST) && !__atomic_load_n(&mo.mwait, __ATOMIC_SEQ_CST)) {
        CHECK(hos_now_ns() < until);
        sleep_ms(1);
    }
    __atomic_store_n(&gate_open, 1, __ATOMIC_SEQ_CST);
    for (int i = 0; i < 8; i++) CHECK(wait_for(&w[i].done, 15000));
    CHECK(wait_for(&o_done, 15000));
    for (int i = 0; i < 8; i++) pthread_join(tw[i], NULL);
    pthread_join(to, NULL);
    for (int i = 0; i < 8; i++) {
        if (handoff) CHECK(w[i].got < o_back);   /* (the eight first: B's wait came after their broadcast) */
        else CHECK(o_back < w[i].got);
    }
    CHECK(mo.reserved == 0 && cvo.cv_owed == 0 && cvo.cv_in == 0 && cvo.cv_waiting == 0 && !mo.owner);
}

/* ---- the one wake of a Signal: a waiter that came in right after it is the newest sleeper ---- */
static int late_done, late_locked;   /* (B's: late_timed is its thread, its wait untimed) */
static void *late_timed(void *p) {   /* (B: it holds the mutex before the signal, as a thread about to wait does) */
    (void)p;
    lock_m();
    __atomic_store_n(&late_locked, 1, __ATOMIC_SEQ_CST);
    CHECK(wait_for(&in_wake, 60000));   /* (the signal moved the generation and is making its wake) */
    is_late = 1, tid = 2;
    wait_cv();   /* (untimed: it never leaves the queue by itself; ended by the broadcast once A is done) */
    is_late = 0;
    CHECK(owns_m());
    unlock_m();
    __atomic_store_n(&late_done, 1, __ATOMIC_SEQ_CST);
    return NULL;
}
static void *signaller(void *p) { (void)p; signal_cv(); return NULL; }   /* (without the mutex) */
static void late_wake(void) {
    reset();
    late_done = in_wake = late_locked = late_blocked = 0, hooked_woke = -1;
    __atomic_store_n(&late_hook, 1, __ATOMIC_SEQ_CST);
    Waiter a = {.tid = 1};
    pthread_t ta, tb, ts;
    pthread_create(&ta, NULL, waiter, &a);
    CHECK(wait_for(&a.locked, 15000));
    CHECK(wait_sleepers(&cvo.cv, 1));   /* (A asleep) */
    pthread_create(&tb, NULL, late_timed, NULL);
    CHECK(wait_for(&late_locked, 15000));
    pthread_create(&ts, NULL, signaller, NULL);
    pthread_join(ts, NULL);   /* (the Signal made its one wake) */
    CHECK(__atomic_load_n(&hooked_woke, __ATOMIC_SEQ_CST) == 1);   /* (it reached A, not B) */
    CHECK(wait_for(&a.done, 60000));   /* (and A got the mutex) */
    lock_m();
    broadcast_cv();   /* (B, asleep since after the signal: it comes out, and is owed nothing) */
    unlock_m();
    CHECK(wait_for(&late_done, 15000));
    pthread_join(ta, NULL), pthread_join(tb, NULL);
    CHECK(mo.reserved == 0 && cvo.cv_owed == 0 && cvo.cv_in == 0 && cvo.cv_waiting == 0 && !mo.owner);
}

/* ---- made again with a waiter in: the waiter from before takes no hand-off, and passes its wake on ---- */
static void remake(int kind) {   /* (as obj_lookup does, under the table's lock: here cv->lk keeps the fixture's reads sane) */
    AcquireSRWLockExclusive(&cvo.lk);
    remake_tomb(&cvo, kind);
    ReleaseSRWLockExclusive(&cvo.lk);
}
static int helper_locked;
static void *lock_and_wake(void *p) {   /* (whether the mutex can be locked; then the waiters woken) */
    (void)p;
    lock_m();
    __atomic_store_n(&helper_locked, 1, __ATOMIC_SEQ_CST);
    broadcast_cv();
    unlock_m();
    return NULL;
}
static void remade(int handoff, int timed) {
    reset();
    wake_oldest = 1;
    Waiter a = {0}, a2 = {.timed = timed}, c = {0};
    pthread_t ta, tc, th;
    /* a condition variable in use: two generations in (a signal to a waiter, a broadcast to none) */
    pthread_create(&ta, NULL, waiter, &a);
    CHECK(wait_for(&a.locked, 15000));
    CHECK(wait_sleepers(&cvo.cv, 1));
    signal_cv();
    CHECK(wait_for(&a.done, 15000));
    pthread_join(ta, NULL);
    broadcast_cv();
    CHECK(cvo.gen == 2);
    pthread_create(&ta, NULL, waiter, &a2);
    CHECK(wait_for(&a2.locked, 15000));
    CHECK(wait_sleepers(&cvo.cv, 1));
    /* made again in place while A sleeps (a misuse: Horizon's waiters stay with the kernel's object) */
    remake(K_COND);
    pthread_create(&tc, NULL, waiter, &c);
    CHECK(wait_for(&c.locked, 15000));
    CHECK(wait_sleepers(&cvo.cv, 2));
    signal_cv();   /* (reserves for C, the one waiter it counts in; the wake goes to the oldest sleeper, A) */
    CHECK(__atomic_load_n(&mo.reserved, __ATOMIC_SEQ_CST) <= 1);
    CHECK(wait_for(&a2.done, 15000));   /* (A woke, came out and got the mutex) */
    helper_locked = 0;
    pthread_create(&th, NULL, lock_and_wake, NULL);
    CHECK(wait_for(&helper_locked, 15000));   /* (the mutex is not left reserved for C while C sleeps) */
    CHECK(wait_for(&c.done, 15000));
    /* (A takes no hand-off and passes its wake on: C, owed the mutex, gets it first; HOS_NO_HANDOFF=1: A first, C
       woken by the helper) */
    CHECK(handoff ? c.got < a2.got : a2.got < c.got);
    pthread_join(ta, NULL), pthread_join(tc, NULL), pthread_join(th, NULL);
    CHECK(mo.reserved == 0 && cvo.cv_owed == 0 && !mo.owner);
    CHECK(cvo.cv_in == 0 && cvo.cv_waiting == 0);   /* (the waiter from before counted itself out of nothing new) */
}
/* made again while A sleeps; B waits; a wake that moves no generation (the object's other uses wake its cv too) reaches
   both: A, from the earlier life, comes out (B goes back to sleep), and counts itself out of nothing new: a Signal still
   finds B and wakes it */
static void remade_counts(int timed) {
    reset();
    Waiter s1 = {.gate = 1, .timed = timed}, b = {0};
    pthread_t ta, tb;
    pthread_create(&ta, NULL, waiter, &s1);
    CHECK(wait_for(&s1.locked, 15000));
    CHECK(wait_sleepers(&cvo.cv, 1));
    remake(K_COND);
    pthread_create(&tb, NULL, waiter, &b);
    CHECK(wait_for(&b.locked, 15000));
    CHECK(wait_sleepers(&cvo.cv, 2));
    WakeAllConditionVariable(&cvo.cv);
    CHECK(wait_for(&in_gate, 15000));   /* (A woken, held before it looks) */
    CHECK(wait_sleepers(&cvo.cv, 1));   /* (B asleep again: nothing changed for it) */
    __atomic_store_n(&gate_open, 1, __ATOMIC_SEQ_CST);
    CHECK(wait_for(&s1.done, 15000));
    CHECK(__atomic_load_n(&cvo.cv_waiting, __ATOMIC_SEQ_CST) == 1);   /* (B's) */
    signal_cv();
    CHECK(wait_for(&b.done, 15000));
    pthread_join(ta, NULL), pthread_join(tb, NULL);
    CHECK(mo.reserved == 0 && cvo.cv_owed == 0 && cvo.cv_in == 0 && cvo.cv_waiting == 0 && !mo.owner);
}
/* made again while A sleeps (on mo); B waits on mo2 (held at the gate); a broadcast made holding mo2 owes it to B; A,
   from the earlier life, comes out first and must leave B's hand-off alone (not take it, nor give it back) */
static void remade_other_mutex(int handoff) {
    reset();
    Waiter a = {0}, b = {.gate = 1, .m = 0x2100};
    pthread_t ta, tb;
    pthread_create(&ta, NULL, waiter, &a);
    CHECK(wait_for(&a.locked, 15000));
    CHECK(wait_sleepers(&cvo.cv, 1));
    remake(K_COND);
    pthread_create(&tb, NULL, waiter, &b);
    CHECK(wait_for(&b.locked, 15000));
    CHECK(wait_sleepers(&cvo.cv, 2));
    lock_k(0x2100);
    broadcast_cv();
    unlock_k(0x2100);
    CHECK(wait_for(&a.done, 15000));
    CHECK(__atomic_load_n(&mo2.reserved, __ATOMIC_SEQ_CST) == handoff);   /* (still B's) */
    __atomic_store_n(&gate_open, 1, __ATOMIC_SEQ_CST);
    CHECK(wait_for(&b.done, 15000));
    pthread_join(ta, NULL), pthread_join(tb, NULL);
    CHECK(mo.reserved == 0 && mo2.reserved == 0 && cvo.cv_owed == 0 && cvo.cv_in == 0 && cvo.cv_waiting == 0);
}
/* made again while A sleeps (on mo); C waits on mo2; a Signal reserves mo2 for C, and its one wake reaches A (oldest
   first here). A, from the earlier life, takes nothing on mo2 and must pass the wake on: C comes out and takes mo2,
   which is not left reserved for a sleeper, refused to every other locker. late: while A is held at the gate, D comes
   in after the signal (on mo) and the host wakes newest first, so one passed-on wake would reach D, which sleeps again */
static int mo2_free, mo2_free_late;
static void *lock_mo2(void *p) {
    lock_k(0x2100);
    __atomic_store_n((int *)p, 1, __ATOMIC_SEQ_CST);
    unlock_k(0x2100);
    return NULL;
}
static void remade_signal_other(int handoff, int timed, int late) {
    reset();
    wake_oldest = 1;
    mo2_free = mo2_free_late = 0;
    Waiter a = {.gate = late, .timed = timed}, c = {.m = 0x2100}, d = {0};
    pthread_t ta, tc, td, th;
    memset(&td, 0, sizeof td);
    pthread_create(&ta, NULL, waiter, &a);
    CHECK(wait_for(&a.locked, 15000));
    CHECK(wait_sleepers(&cvo.cv, 1));
    remake(K_COND);
    pthread_create(&tc, NULL, waiter, &c);
    CHECK(wait_for(&c.locked, 15000));
    CHECK(wait_sleepers(&cvo.cv, 2));
    signal_cv();   /* (reserves mo2 for C; the wake goes to A) */
    if (late) {
        CHECK(wait_for(&in_gate, 15000));   /* (A woken, held before it looks) */
        CHECK(!__atomic_load_n(&c.done, __ATOMIC_SEQ_CST) && __atomic_load_n(&mo2.reserved, __ATOMIC_SEQ_CST) == handoff);
        pthread_create(&td, NULL, waiter, &d);
        CHECK(wait_for(&d.locked, 15000));
        CHECK(wait_sleepers(&cvo.cv, 2));   /* (C and D) */
        wake_oldest = 0;
        __atomic_store_n(&gate_open, 1, __ATOMIC_SEQ_CST);
    }
    CHECK(wait_for(&a.done, 15000));
    pthread_create(&th, NULL, lock_mo2, late ? &mo2_free_late : &mo2_free);
    if (late) CHECK(wait_for(&mo2_free_late, 15000));
    else CHECK(wait_for(&mo2_free, 15000));
    if (handoff) CHECK(wait_for(&c.done, 15000));   /* (C came out at the passed-on wake; HOS_NO_HANDOFF=1: it may sleep on) */
    if (late) CHECK(wait_sleepers(&cvo.cv, 1) && !__atomic_load_n(&d.done, __ATOMIC_SEQ_CST));   /* (D, in after the signal, sleeps on) */
    broadcast_cv();
    CHECK(wait_for(&c.done, 15000));
    if (late) CHECK(wait_for(&d.done, 15000));
    pthread_join(ta, NULL), pthread_join(tc, NULL), pthread_join(th, NULL);
    if (late) pthread_join(td, NULL);
    CHECK(mo.reserved == 0 && mo2.reserved == 0 && cvo.cv_owed == 0 && cvo.cv_in == 0 && cvo.cv_waiting == 0);
    CHECK(!mo.owner && !mo2.owner);
}

/* made again while A (on mo2) and B (on mo) sleep; C waits on mo; S, holding mo, Signals: mo is reserved for C and the
   wake reaches C (newest first), held at the gate. A then comes out at a wake of its own (a host's spurious wake; its
   timeout takes the same way out) and passes it on: B, from the earlier life too, comes out and must not take C's
   hand-off. S unlocks mo and locks it again: C, owed it, gets it before S and B */
static int st_phase, st_go, st_done, st_back;
static void *steal_owner(void *p) {
    (void)p;
    lock_m();
    signal_cv();
    __atomic_store_n(&st_phase, 1, __ATOMIC_SEQ_CST);
    CHECK(wait_for(&st_go, 60000));
    unlock_m();
    lock_m();
    __atomic_store_n(&st_back, next_seq(), __ATOMIC_SEQ_CST);
    __atomic_store_n(&st_done, 1, __ATOMIC_SEQ_CST);
    unlock_m();
    return NULL;
}
static int owed_now(void) { AcquireSRWLockExclusive(&cvo.lk); const int n = cvo.cv_owed; ReleaseSRWLockExclusive(&cvo.lk); return n; }
static void remade_steal(void) {   /* (hand-off on) */
    reset();
    seq = 0, st_phase = st_go = st_done = st_back = 0;
    Waiter a = {.m = 0x2100}, b = {0}, c = {.gate = 1};
    pthread_t ta, tb, tc, ts;
    pthread_create(&ta, NULL, waiter, &a);
    CHECK(wait_for(&a.locked, 15000));
    CHECK(wait_sleepers(&cvo.cv, 1));
    pthread_create(&tb, NULL, waiter, &b);
    CHECK(wait_for(&b.locked, 15000));
    CHECK(wait_sleepers(&cvo.cv, 2));
    remake(K_COND);
    pthread_create(&tc, NULL, waiter, &c);
    CHECK(wait_for(&c.locked, 15000));
    CHECK(wait_sleepers(&cvo.cv, 3));
    pthread_create(&ts, NULL, steal_owner, NULL);
    CHECK(wait_for(&st_phase, 15000));
    CHECK(wait_for(&in_gate, 15000));   /* (C woken, held) */
    CHECK(__atomic_load_n(&mo.reserved, __ATOMIC_SEQ_CST) == 1 && owed_now() == 1);
    wake_oldest = 1;
    WakeConditionVariable(&cvo.cv);   /* (A's own wake) */
    CHECK(wait_for(&a.done, 15000));
    const int64_t until = hos_now_ns() + 15000000000ll;
    while (__atomic_load_n(&mo.mwait, __ATOMIC_SEQ_CST) < 1) {   /* (B out, relocking mo: S holds it) */
        CHECK(hos_now_ns() < until);
        sleep_ms(1);
    }
    __atomic_store_n(&st_go, 1, __ATOMIC_SEQ_CST);
    /* the gate opens once S is back, or S and B both wait on mo while C's hand-off is still owed (only C can end that) */
    while (!__atomic_load_n(&st_done, __ATOMIC_SEQ_CST) && !(__atomic_load_n(&mo.mwait, __ATOMIC_SEQ_CST) >= 2 && owed_now() == 1)) {
        CHECK(hos_now_ns() < until);
        sleep_ms(1);
    }
    __atomic_store_n(&gate_open, 1, __ATOMIC_SEQ_CST);
    CHECK(wait_for(&c.done, 15000) && wait_for(&b.done, 15000) && wait_for(&st_done, 15000));
    pthread_join(ta, NULL), pthread_join(tb, NULL), pthread_join(tc, NULL), pthread_join(ts, NULL);
    CHECK(c.got < st_back && c.got < b.got);   /* (C, owed mo, first) */
    CHECK(mo.reserved == 0 && mo2.reserved == 0 && cvo.cv_owed == 0 && cvo.cv_in == 0 && cvo.cv_waiting == 0);
    CHECK(!mo.owner && !mo2.owner);
}

/* ---- many rounds, no gate, a watchdog on the rounds ---- */
enum { NW = 4, ROUNDS = 2000 };
static int want[NW], stop, served[NW], rounds, waiters_out;   /* (want, stop: under the guest mutex) */
static void *loop_waiter(void *p) {
    const int j = (int)(intptr_t)p;
    for (int i = 0;; i++) {
        lock_m();
        while (!want[j] && !stop) {
            if (i & 1) timed_cv(1000000);
            else wait_cv();
        }
        if (!want[j]) {
            unlock_m();
            __atomic_add_fetch(&waiters_out, 1, __ATOMIC_SEQ_CST);
            break;
        }
        want[j] = 0;
        __atomic_add_fetch(&served[j], 1, __ATOMIC_SEQ_CST);
        unlock_m();
    }
    return NULL;
}
static void *producer(void *p) {
    (void)p;
    for (int r = 0; r < ROUNDS; r++) {
        lock_m();
        for (int j = 0; j < NW; j++) want[j] = 1;
        if (r % 3) broadcast_cv();
        else for (int j = 0; j < NW; j++) signal_cv();
        (void)timed_cv(0);   /* (its own zero-timeout wait, still holding the mutex: it must not take a waiter's hand-off) */
        unlock_m();
        for (;;) {
            lock_m();
            int left = 0;
            for (int j = 0; j < NW; j++) left += want[j];
            unlock_m();
            if (!left) break;
            sleep_ms(0);
        }
        __atomic_store_n(&rounds, r + 1, __ATOMIC_SEQ_CST);
    }
    lock_m();
    stop = 1;
    broadcast_cv();
    unlock_m();
    __atomic_store_n(&rounds, ROUNDS + 1, __ATOMIC_SEQ_CST);   /* (the shutdown, watched as a round) */
    return NULL;
}
static void many_rounds(void) {
    reset();
    stop = 0, rounds = 0, waiters_out = 0;
    memset(want, 0, sizeof want), memset(served, 0, sizeof served);
    pthread_t t[NW], tp;
    for (int j = 0; j < NW; j++) pthread_create(&t[j], NULL, loop_waiter, (void *)(intptr_t)j);
    pthread_create(&tp, NULL, producer, NULL);
    int seen = 0;
    int64_t last = hos_now_ns();
    /* (the watchdog: 10 s without a round, or without the waiters out after the last, is a stall, wherever it is) */
    while (seen <= ROUNDS || __atomic_load_n(&waiters_out, __ATOMIC_SEQ_CST) < NW) {
        const int now = __atomic_load_n(&rounds, __ATOMIC_SEQ_CST);
        if (now != seen) seen = now, last = hos_now_ns();
        CHECK(hos_now_ns() - last < 10000000000ll);
        sleep_ms(1);
    }
    pthread_join(tp, NULL);
    for (int j = 0; j < NW; j++) pthread_join(t[j], NULL);
    for (int j = 0; j < NW; j++) CHECK(served[j] == ROUNDS);
    CHECK(mo.reserved == 0 && cvo.cv_owed == 0 && cvo.cv_in == 0 && cvo.cv_waiting == 0 && !mo.owner);
}

/* ---- semaphores through the timed and try entries ---- */
static void release_s(int n) { Ctx c = {{0x3000, (uint64_t)n}}; _ZN2nn2os16ReleaseSemaphoreEPNS0_13SemaphoreTypeEi(&c); }
static int tacquire(int64_t ns) {
    Ctx c = {{0x3000, (uint64_t)ns}};
    _ZN2nn2os21TimedAcquireSemaphoreEPNS0_13SemaphoreTypeENS_8TimeSpanE(&c);
    return (int)c.x[0];
}
static int tlacquire(int64_t ns) {
    Ctx c = {{0x3000, (uint64_t)ns}};
    _ZN2nn2os26TimedAcquireLightSemaphoreEPNS0_18LightSemaphoreTypeENS_8TimeSpanE(&c);
    return (int)c.x[0];
}
static int trylacquire(void) { Ctx c = {{0x3000}}; _ZN2nn2os24TryAcquireLightSemaphoreEPNS0_18LightSemaphoreTypeE(&c); return (int)c.x[0]; }
static int acq_ok, acq_done;
static void *long_acquire(void *p) {
    (void)p;
    __atomic_store_n(&acq_ok, tacquire(60000000000ll), __ATOMIC_SEQ_CST);
    __atomic_store_n(&acq_done, 1, __ATOMIC_SEQ_CST);
    return NULL;
}
static int taken[4];
static void *acquirer(void *p) {
    const int j = (int)(intptr_t)p;
    for (int i = 0; i < 500; i++) if (tacquire(10000000000ll)) __atomic_add_fetch(&taken[j], 1, __ATOMIC_SEQ_CST);
    return NULL;
}
static void semaphores(void) {
    reset();
    /* a release made while a 60 s timed acquire sleeps: it wakes the acquire, which takes it (not at its deadline) */
    pthread_t t;
    sema_woken = -1, acq_ok = acq_done = 0;
    pthread_create(&t, NULL, long_acquire, NULL);
    CHECK(wait_sleepers(&so.cv, 1));
    release_s(1);
    CHECK(wait_for(&acq_done, 15000) && sema_woken == 1);
    pthread_join(t, NULL);
    CHECK(acq_ok == 1 && so.sem == 0);
    /* no release: a 30 ms light timed acquire times out after 30 ms */
    const int64_t t0 = hos_now_ns();
    CHECK(tlacquire(30000000) == 0);
    CHECK(hos_now_ns() - t0 >= 30000000 && so.sem == 0);
    /* try: only when a count is there */
    CHECK(trylacquire() == 0);
    release_s(1);
    CHECK(trylacquire() == 1 && trylacquire() == 0 && so.sem == 0);
    /* four threads take 2,000 counts released one at a time */
    pthread_t a[4];
    memset(taken, 0, sizeof taken);
    for (int j = 0; j < 4; j++) pthread_create(&a[j], NULL, acquirer, (void *)(intptr_t)j);
    for (int i = 0; i < 2000; i++) release_s(1);
    for (int j = 0; j < 4; j++) pthread_join(a[j], NULL);
    for (int j = 0; j < 4; j++) CHECK(taken[j] == 500);
    CHECK(so.sem == 0);
}

/* the host's lazily read switches, read once before any thread races to (HOS_MUTEX_TRACE: mutex_lock's slow path) */
static int held_flag;
static void *hold_until_waited(void *p) {
    (void)p;
    lock_m();
    __atomic_store_n(&held_flag, 1, __ATOMIC_SEQ_CST);
    const int64_t until = hos_now_ns() + 60000000000ll;
    while (!__atomic_load_n(&mo.mwait, __ATOMIC_SEQ_CST)) {   /* (main is on mutex_lock's slow path) */
        CHECK(hos_now_ns() < until);
        sleep_ms(1);
    }
    unlock_m();
    return NULL;
}
static void read_switches(void) {
    (void)handoff_on(), (void)cv_signal_always();
    reset();
    pthread_t t;
    pthread_create(&t, NULL, hold_until_waited, NULL);
    CHECK(wait_for(&held_flag, 15000));
    lock_m();
    unlock_m();
    pthread_join(t, NULL);
}

int main(int argc, char **argv) {
    CHECK(argc == 2 || argc == 3);
    const int handoff = atoi(argv[1]);   /* (HOS_NO_HANDOFF set by the caller) */
    const char *only = argc == 3 ? argv[2] : NULL;   /* (one group of cases: a broken variant's) */
#define GROUP(name) (!only || !strcmp(only, name))
    read_switches();
    if (GROUP("ordering")) {
        for (int i = 0; i < 5; i++) ordering(LATE_ONE, handoff);
        for (int i = 0; i < 5; i++) ordering(LATE_SIGNAL, handoff);
        for (int i = 0; i < 5; i++) ordering(LATE_TWO, handoff);
        for (int i = 0; i < 5; i++) ordering(SIGNAL_RELOCK, handoff);
    }
    if (GROUP("late")) {
        for (int i = 0; i < 3; i++) late_untimed(handoff);
        for (int i = 0; i < 2; i++) late_wake();
    }
    if (GROUP("remade")) {
        for (int late = 0; late < 2; late++)
            for (int timed = 0; timed < 2; timed++) remade_signal_other(handoff, timed, late);
        for (int timed = 0; timed < 2; timed++) {
            for (int i = 0; i < 2; i++) remade_counts(timed);
            for (int i = 0; i < 2; i++) remade(handoff, timed);
        }
        for (int i = 0; i < 2; i++) remade_other_mutex(handoff);
    }
    if (GROUP("steal") && handoff) for (int i = 0; i < 2; i++) remade_steal();
    if (GROUP("many")) many_rounds();
    if (GROUP("sema")) semaphores();
    return 0;
}
'''


# bury_locked (an object dead 30 s becomes a spare, its lock and condition variable made again): not while a condition
# variable waiter is still in it; it is looked at again later. The real struct and globals, a fake clock
BURY_FIXTURE = r"""#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include "longshot_env.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
typedef struct { int x; } SRWLOCK;
typedef struct { int x; } CONDITION_VARIABLE;
typedef struct HosThread HosThread;
@STRUCT@
@GRAVES@
static Obj *spares;
static int64_t now_ns = 1000000000;
static int64_t hos_now_ns(void) { return now_ns; }
@BURY@
static int spare(Obj *o) { for (Obj *s = spares; s; s = s->spare) if (s == o) return 1; return 0; }
int main(void) {
    static Obj a, b, c, d;
    a.cv_waiting = 1;   /* (a waiter still in: a misuse) */
    bury_locked(&a);
    now_ns += 31000000000ll;
    bury_locked(&b);    /* (a's 30 s are over) */
    CHECK(!spare(&a));
    now_ns += 31000000000ll;
    bury_locked(&c);    /* (b's are over; a, looked at again, still has its waiter) */
    CHECK(spare(&b) && !spare(&a));
    a.cv_waiting = 0;   /* (the waiter out) */
    now_ns += 31000000000ll;
    bury_locked(&d);
    CHECK(spare(&a) && spare(&c));
    return 0;
}
"""


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()

    path = ROOT / "host" / "nn_os_sync.c"
    src = path.read_text(encoding="utf-8")
    struct = between(src, "typedef struct Obj {", "static int wake_lat_on(void);")
    funcs = "\n".join(block(src, marker) for marker in FUNCS)
    lookup = block(src, "static Obj *obj_lookup(uint64_t key, int kind) {")
    tomb = between(lookup, TOMB, "    if (!o) {")
    tomb = "static void remake_tomb(Obj *o, int kind) {\n" + tomb[tomb.index("\n") + 1:]
    check(LIFE in tomb, "obj_lookup's branch for an address made again no longer counts its life ('%s')" % LIFE)
    parts = {"@STRUCT@": struct, "@FUNCS@": funcs, "@TOMB@": tomb}
    parts.update({key: block(src, marker) for key, marker in HLE.items()})
    env = {k: v for k, v in os.environ.items() if not k.startswith("HOS_")}

    def build(tmp, name, **changed):
        text = FIXTURE
        for key, part in parts.items():
            text = text.replace(key, changed.get(key, part))
        c, exe = Path(tmp) / (name + ".c"), Path(tmp) / (name + ".exe")
        c.write_text(text, encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-Wno-unused-value",
                        "-pthread", "-I", str(ROOT / "gpu" / "vk" / "compat"), str(c), "-o", str(exe)], check=True)
        return exe

    def run(exe, no_handoff, handoff, group=None):
        e = dict(env) if no_handoff is None else dict(env, HOS_NO_HANDOFF=no_handoff)
        return subprocess.run([str(exe), str(handoff)] + ([group] if group else []), env=e, capture_output=True,
                              text=True, timeout=300)

    with tempfile.TemporaryDirectory(prefix="cv-handoff-") as tmp:
        bury = {"@STRUCT@": struct, "@GRAVES@": between(src, "static Obj **graves;", "/* Objects are not given back"),
                "@BURY@": block(src, "static void bury_locked(Obj *o) {")}
        guard = "        if (__atomic_load_n(&d->cv_waiting, __ATOMIC_SEQ_CST) > 0) {"
        check(guard in bury["@BURY@"], "bury_locked no longer leaves an object with a condition variable waiter in ('%s')" % guard.strip())
        for name, body in (("bury", bury["@BURY@"]), ("bury-no-guard", bury["@BURY@"].replace(guard, "        if (0) {"))):
            text = BURY_FIXTURE
            for key, part in dict(bury, **{"@BURY@": body}).items():
                text = text.replace(key, part)
            c, exe = Path(tmp) / (name + ".c"), Path(tmp) / (name + ".exe")
            c.write_text(text, encoding="utf-8")
            subprocess.run([a.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-I",
                            str(ROOT / "gpu" / "vk" / "compat"), str(c), "-o", str(exe)], check=True)
            r = subprocess.run([str(exe)], env=env, capture_output=True, text=True, timeout=60)
            if name == "bury":
                check(r.returncode == 0, "bury_locked: not as expected\n%s" % r.stderr)
            else:
                check(r.returncode != 0 and "!spare(&a)" in r.stderr,
                      "a bury_locked making a spare of an object with a condition variable waiter in passes\n%s" % r.stderr)

        exe = build(tmp, "fixture")
        for no_handoff, handoff in ((None, 1), ("1", 0), ("0", 1)):
            r = run(exe, no_handoff, handoff)
            check(r.returncode == 0, "HOS_NO_HANDOFF %r: not as expected\n%s" % (no_handoff, r.stderr))
            r = run(exe, no_handoff, 1 - handoff)
            check(r.returncode != 0 and "FAIL:" in r.stderr, "HOS_NO_HANDOFF %r passes both ways" % no_handoff)

        def broken(name, key, old, new, at, what, group):   # (group: the cases it runs, the ones that catch it)
            check(parts[key].count(old) == 1, "%s no longer has the line the broken variant '%s' changes" % (key, name))
            r = run(build(tmp, name, **{key: parts[key].replace(old, new)}), None, 1, group)
            check(r.returncode != 0 and any(x in r.stderr for x in at.split(" | ")),
                  "%s\n(expected a failure at '%s'; got rc %d: %s)"
                  % (what, at, r.returncode, r.stderr.strip()[-300:]))

        broken("anonymous", "@FUNCS@",
               "if (cv->cv_owed_gen[i] >= gen && (k < 0 || cv->cv_owed_gen[i] < cv->cv_owed_gen[k]))",
               "if ((void)gen, k < 0)", "w[i].got < b_first",
               "a zero-timeout waiter taking a hand-off made before it came in (anonymous reservations) passes", "ordering")
        broken("signal-gen-first", "@SIGNAL@", "    cv_reserve(cv);\n    cv->gen++;\n", "    cv->gen++;\n    cv_reserve(cv);\n",
               "w[i].got < b_first", "a Signal stamping its reservation after moving the generation passes", "ordering")
        broken("wake-after-unlock", "@SIGNAL@", "    WakeConditionVariable(&cv->cv);\n    ReleaseSRWLockExclusive(&cv->lk);\n",
               "    ReleaseSRWLockExclusive(&cv->lk);\n    WakeConditionVariable(&cv->cv);\n", "hooked_woke",
               "a Signal waking after it lets cv->lk go (its one wake taken by a later waiter) passes", "late")
        broken("no-life", "@TOMB@", LIFE, "", "s1.done | a2.done | wait_for(&c.done, 15000)",
               "a waiter from an earlier life held to its old generation (the life not counted) passes", "remade")
        broken("wait-gen-0", "@WAIT@", "cv_leave(cv, m, gen, life)", "cv_leave(cv, m, 0, life)", "w[i].got < o_back",
               "a Wait handing cv_leave generation 0 (any reservation) passes", "late")
        stale = "        if (cv->cv_owed) WakeAllConditionVariable(&cv->cv);\n        return 0;\n    }"
        take_own = ("        for (int i = 0; i < cv->cv_owed; i++)\n"
                    "            if (cv->cv_owed_mutex[i] == m) {\n"
                    "                cv->cv_owed--;\n"
                    "                cv->cv_owed_mutex[i] = cv->cv_owed_mutex[cv->cv_owed];\n"
                    "                cv->cv_owed_gen[i] = cv->cv_owed_gen[cv->cv_owed];\n"
                    "                if (cv->cv_owed) WakeAllConditionVariable(&cv->cv);\n"
                    "                return 1;\n"
                    "            }\n")
        broken("stale-takes-own", "@FUNCS@", stale, take_own + stale, "handoff ? c.got < a2.got",
               "a waiter from an earlier life taking a hand-off on its own mutex (made for a new waiter) passes", "remade")
        broken("stale-takes-own-steal", "@FUNCS@", stale, take_own + stale, "c.got < st_back",
               "a waiter from an earlier life taking a new waiter's hand-off after a wake of its own (S relocks ahead of "
               "the waiter the signal woke) passes", "steal")
        pass_on = "        if (cv->cv_owed) WakeAllConditionVariable(&cv->cv);\n"
        broken("no-pass-on", "@FUNCS@", pass_on, "", "wait_for(&mo2_free, 15000)",
               "a waiter from an earlier life that took a Signal's wake for another mutex's waiter, not passing it on "
               "(the mutex left reserved for a sleeper), passes", "remade")
        broken("pass-on-one-wake", "@FUNCS@", pass_on, pass_on.replace("WakeAllConditionVariable", "WakeConditionVariable"),
               "wait_for(&mo2_free_late, 15000)",
               "an earlier life's waiter passing on one wake (it can reach a waiter that came in after the signal) passes",
               "remade")
        broken("pass-on-moves-gen", "@FUNCS@", pass_on, pass_on.replace("WakeAll", "cv->gen++, WakeAll"),
               "!__atomic_load_n(&d.done", "an earlier life's waiter moving the generation as it passes the wake on "
               "(the waiter in after the signal comes out) passes", "remade")
        broken("stale-counted", "@FUNCS@", "    if (!cv_same_life(cv, life)) {", "    if (0 && !cv_same_life(cv, life)) {",
               "cv_waiting, __ATOMIC_SEQ_CST) == 1 | wait_for(&c.done, 15000)",
               "a waiter from an earlier life counting itself out of the new counts (and taking a hand-off) passes", "remade")
        broken("wait-ignores-life", "@WAIT@", "while (cv->gen == gen && cv_same_life(cv, life))", "while (cv->gen == gen)",
               "s1.done", "a Wait from an earlier life sleeping on at a wake that moves no generation passes", "remade")
        broken("timed-ignores-life", "@TIMED@", "while (cv->gen == gen && cv_same_life(cv, life))", "while (cv->gen == gen)",
               "s1.done", "a TimedWait from an earlier life sleeping on at a wake that moves no generation passes", "remade")
        broken("timed-wrong-life", "@TIMED@", "cv_leave(cv, m, gen, life)",
               "cv_leave(cv, m, gen, __atomic_load_n(&cv->life, __ATOMIC_RELAXED))",
               "cv_waiting, __ATOMIC_SEQ_CST) == 1 | wait_for(&c.done, 15000)",
               "a TimedWait not telling cv_leave the life it came in at passes", "remade")
        broken("release-no-wake", "@FUNCS@", "    WakeAllConditionVariable(&s->cv);\n    poke_multiwait(s);",
               "    poke_multiwait(s);", "acq_done", "a semaphore release that does not wake a timed acquire passes", "sema")


if __name__ == "__main__":
    main()
