"""BroadcastConditionVariable and the timed/try semaphore acquires run on the HLE's objects, not the guest SDK's words.

host/nn_os_sync.c replaces the nn::os condition variable and semaphore functions with host objects. Siblings left to the
lifted SDK act on guest words the HLE never writes, and signal kernel keys no HLE waiter sleeps on:
- BroadcastConditionVariable woke nobody (the movie framework and NVIDIA's OS layer call it);
- TimedAcquireSemaphore (the C library's timed semaphore wait, NVIDIA's OS layer) never saw an HLE release.

The fixture runs the real code cut from the source (handoff_on, cv_enter, cv_leave, cv_reserve, the Broadcast HLE,
sema_acquire_for) over stubs: counted lock pairs and wake calls, and a fake clock whose wait can release the semaphore.
- Broadcast: it moves the generation and wakes all, and every waiter not yet owed the mutex is owed it, up to
  cv_reserve's 8; none with mixed mutexes or HOS_NO_HANDOFF=1.
- Whose hand-off it is (cv_leave): a reservation goes only to a waiter that was in when it was made. A thread that
  holds the mutex, broadcasts, then waits with a zero timeout (it times out and leaves first) is owed nothing, and the
  waiters the broadcast woke keep theirs; twice in a row too, and after a Signal. Each waiter takes the oldest it may,
  so one that came in between two signals still finds the newer one. A condition variable made again (obj_lookup's
  clear) hands off as before, and a waiter still in from before it (an earlier life) takes no hand-off, passes its wake
  on (a wake-all) while one is owed, and is not counted out of the new counts (tests/test_cv_handoff_threads.py runs
  that through the waits).
- Semaphore: a count is taken at once, a zero timeout never waits, a release inside the timeout is taken, and the
  deadline ends the wait.
- wait_until (cut on its own, over a fake clock): a finite wait sleeps in whole ms rounded up, in steps below INFINITE
  (0xFFFFFFFF ms is INFINITE on Windows), also for 2^32 ms and a saturated deadline.
Broken variants must fail: one wake instead of all, no generation move, one reservation, anonymous reservations (any
waiter takes any, as before), the newest one taken first, an earlier life's waiter taking a hand-off on its mutex or
not passing its wake on, a reservation not stamped with its generation, a single
wait, a count of 0 taken, no decrement, a long finite wait passed as a bare DWORD, its ms rounded in int64_t (a
saturated deadline wraps). tests/test_cv_handoff_threads.py runs the same hand-offs on real threads.

python -I -B tests/test_os_lifted_siblings.py [--cc gcc]
"""
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
PARTS = {"@HANDOFF@": "static int handoff_on(void) {", "@COUNTIN@": "static void cv_count_in(Obj *cv) {",
         "@ENTER@": "static void cv_enter(Obj *cv, Obj *m) {",
         "@SAME@": "static int cv_same_life(Obj *cv, unsigned life) {", "@LEAVE@": "static int cv_leave(Obj *cv, Obj *m, uint64_t gen, unsigned life) {", "@RESERVE@": "static void cv_reserve(Obj *cv) {",
         "@BROADCAST@": "HLE(_ZN2nn2os26BroadcastConditionVariableEPNS0_21ConditionVariableTypeE) {",
         "@SEMA@": "static int sema_acquire_for(Obj *s, int64_t ns) {"}
# (each acquire the guest SDK would otherwise run, as one line calling sema_acquire_for)
SEMA_HLE = {"_ZN2nn2os21TimedAcquireSemaphoreEPNS0_13SemaphoreTypeENS_8TimeSpanE": "(int64_t)ARG(1)",
            "_ZN2nn2os26TimedAcquireLightSemaphoreEPNS0_18LightSemaphoreTypeENS_8TimeSpanE": "(int64_t)ARG(1)",
            "_ZN2nn2os24TryAcquireLightSemaphoreEPNS0_18LightSemaphoreTypeE": "0"}


def block(source, marker):
    if marker not in source:
        raise SystemExit("FAIL: host/nn_os_sync.c has no '%s'" % marker.strip())
    start = source.index(marker)
    line = source[start:source.index("\n", start)]
    if line.rstrip().endswith("}"):   # (a function on one line)
        return line
    return source[start:start + re.search(r"^}", source[start:], re.M).end()]


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


FIXTURE = r'''#define _CRT_SECURE_NO_WARNINGS
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "longshot_env.h"   /* (env_on: the switches' one rule) */
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
typedef struct { int held; } SRWLOCK;
typedef struct { int x; } CONDITION_VARIABLE;
static int wakes, wakealls;
static void AcquireSRWLockExclusive(SRWLOCK *l) { CHECK(!l->held); l->held = 1; }
static void ReleaseSRWLockExclusive(SRWLOCK *l) { CHECK(l->held); l->held = 0; }
static void WakeConditionVariable(CONDITION_VARIABLE *cv) { (void)cv; wakes++; }
static void WakeAllConditionVariable(CONDITION_VARIABLE *cv) { (void)cv; wakealls++; }
typedef struct Obj {
    uint64_t key;
    SRWLOCK lk;
    CONDITION_VARIABLE cv;
    unsigned life;
    uint64_t gen;   /* (from here on: what obj_lookup clears, remake) */
    int cv_waiting, cv_in, cv_owed, cv_mixed;
    struct Obj *cv_mutex, *cv_owed_mutex[8];
    uint64_t cv_owed_gen[8];
    int sem;
    int reserved;
} Obj;
static Obj cvo, so, mo, mo2;
enum { K_COND = 2, K_SEMA = 4 };
static Obj *obj(uint64_t key, int kind) { Obj *o = kind == K_COND ? &cvo : &so; o->key = key; return o; }
static int watched_cv(uint64_t cv) { (void)cv; return 0; }
static uint64_t watch_mutex(void) { return 0; }
typedef struct { uint64_t x[8]; } Ctx;
static void watch_log(const char *w, uint64_t m, uint64_t cv, Ctx *c, Obj *o) { (void)w, (void)m, (void)cv, (void)c, (void)o; }
enum { HOS_CHAIN_WAIT = 1, HOS_CHAIN_WOKE, HOS_CHAIN_SIGNAL };
#define HOS_CHAIN(kind, key) ((void)(kind), (void)(key))   /* (HOS_CHAIN off: host/hos.h) */
static int hos_chain_on, chain_notes;
static void hos_chain_note(int kind, uint64_t key, uint64_t lr) { (void)kind, (void)key, (void)lr; chain_notes++; }
#define ARG(i) (c->x[i])
#define HLE(name) static void name(Ctx *c)
/* a fake clock: each wait sleeps 1 ms (or less, to its deadline); a release can be due at a time */
static int64_t now_ns = 1000000000, release_at;
static int waits;
static int64_t hos_now_ns(void) { return now_ns; }
static int wait_until(Obj *o, int64_t deadline) {   /* (host/nn_os_sync.c's: 0 on timeout) */
    CHECK(o->lk.held && deadline);
    CHECK(++waits < 100000);
    const int64_t left = deadline - now_ns;
    if (left <= 0) return 0;
    now_ns += left < 1000000 ? left : 1000000;
    if (release_at && now_ns >= release_at) { o->sem++; release_at = 0; }
    return 1;
}

@HANDOFF@
@COUNTIN@
@ENTER@
@SAME@
@LEAVE@
@RESERVE@
@BROADCAST@
@SEMA@

static void broadcast(void) {
    const int a = wakealls, w = wakes;
    const uint64_t g = cvo.gen;
    Ctx c = {{0x1000}};
    _ZN2nn2os26BroadcastConditionVariableEPNS0_21ConditionVariableTypeE(&c);
    CHECK(cvo.gen == g + 1 && wakealls == a + 1 && wakes == w && !cvo.lk.held);
}
/* a waiter in, as WaitConditionVariable does: counted in before cv->lk, then in under it; its ticket is the generation
   it read there (what it hands cv_leave) */
static uint64_t enter(Obj *m) {
    cv_count_in(&cvo);
    const uint64_t g = cvo.gen;
    cv_enter(&cvo, m);
    return g;
}
/* one waiter out: whether it was owed its mutex (an owed one takes it, as mutex_take_owed does) */
static int leave(Obj *m, uint64_t g) {
    const int owed = cv_leave(&cvo, m, g, cvo.life);
    if (owed) m->reserved--;
    return owed;
}
/* n waiters in on m, their tickets in g */
static void enter_n(Obj *m, uint64_t *g, int n) { for (int i = 0; i < n; i++) g[i] = enter(m); }
/* all out, in order: how many were owed their mutex; nothing is left owed */
static int leave_all(Obj *m, const uint64_t *g, int n) {
    int owed = 0;
    for (int i = 0; i < n; i++) owed += leave(m, g[i]);
    CHECK(cvo.cv_waiting == 0 && cvo.cv_in == 0);
    CHECK(cvo.cv_owed == 0 && m->reserved == 0);
    return owed;
}
/* made again in place, as obj_lookup does: the condition variable's fields cleared, its life counted */
static void remake(void) { memset(&cvo.gen, 0, sizeof cvo - offsetof(Obj, gen)); cvo.life++; }
/* the thread that holds the mutex waits with a zero timeout after its signal: in, and at once out (TimedWait's timeout) */
static int late_timeout(Obj *m) { return leave(m, enter(m)); }
static int acquire(int sem, int64_t ns, int64_t release_after) {
    so.sem = sem;
    waits = 0;
    release_at = release_after ? now_ns + release_after : 0;
    const int ok = sema_acquire_for(&so, ns);
    CHECK(!so.lk.held);
    return ok;
}

int main(int argc, char **argv) {
    CHECK(argc == 2);
    const int handoff = atoi(argv[1]);   /* (HOS_NO_HANDOFF set by the caller) */
    uint64_t g[10];
    /* Broadcast with nobody waiting: the generation moves, nothing is owed */
    broadcast();
    CHECK(mo.reserved == 0);
    /* whose hand-off (review 1752): A waits; B, holding the mutex, broadcasts, then waits with a zero timeout. B times
       out and leaves first, before A runs: B is owed nothing (it relocks behind A), A keeps its hand-off */
    g[0] = enter(&mo);
    broadcast();
    CHECK(late_timeout(&mo) == 0);
    CHECK(mo.reserved == (handoff ? 1 : 0) && cvo.cv_owed == (handoff ? 1 : 0));
    CHECK(leave(&mo, g[0]) == handoff);
    CHECK(cvo.cv_owed == 0 && mo.reserved == 0 && cvo.cv_in == 0 && cvo.cv_waiting == 0);
    /* twice (sol, round 3): C and D wait; B broadcasts and times out twice: neither is B's, C and D each keep one */
    enter_n(&mo, g, 2);
    broadcast();
    CHECK(late_timeout(&mo) == 0 && late_timeout(&mo) == 0);
    CHECK(mo.reserved == (handoff ? 2 : 0));
    CHECK(leave_all(&mo, g, 2) == (handoff ? 2 : 0));
    /* a Signal's the same (#156: one waiter; the signaller's own zero-timeout wait does not take it) */
    g[0] = enter(&mo);
    cv_reserve(&cvo);
    cvo.gen++;   /* (Signal: reserve, then move the generation, under cv->lk) */
    CHECK(late_timeout(&mo) == 0);
    CHECK(leave_all(&mo, g, 1) == (handoff ? 1 : 0));
    /* three waiters on one mutex: all wake and all are owed it */
    enter_n(&mo, g, 3);
    broadcast();
    CHECK(mo.reserved == (handoff ? 3 : 0));
    CHECK(leave_all(&mo, g, 3) == (handoff ? 3 : 0));
    /* one owed by an earlier signal, two more in: the broadcast owes only the two */
    g[0] = enter(&mo);
    if (handoff) cv_reserve(&cvo);
    enter_n(&mo, g + 1, 2);
    broadcast();
    CHECK(mo.reserved == (handoff ? 3 : 0));
    CHECK(leave_all(&mo, g, 3) == (handoff ? 3 : 0));
    /* ten waiters: at most 8 owed (cv_reserve's limit), the others lock as anyone does */
    enter_n(&mo, g, 10);
    broadcast();
    CHECK(mo.reserved == (handoff ? 8 : 0));
    CHECK(leave_all(&mo, g, 10) == (handoff ? 8 : 0));
    /* waiters with different mutexes: no hand-off */
    g[0] = enter(&mo);
    g[1] = enter(&mo2);
    broadcast();
    CHECK(mo.reserved == 0 && mo2.reserved == 0);
    CHECK(leave(&mo, g[0]) == 0 && leave(&mo2, g[1]) == 0);
    CHECK(cvo.cv_waiting == 0 && cvo.cv_owed == 0);
    /* a waiter that came in between two broadcasts: A in, a broadcast (A's), E in, a broadcast (one more: E's). The late
       zero-timeout waiter takes neither; A leaves and takes the older, E still finds the newer */
    g[0] = enter(&mo);
    broadcast();
    g[1] = enter(&mo);
    broadcast();
    CHECK(mo.reserved == (handoff ? 2 : 0));
    CHECK(late_timeout(&mo) == 0);
    CHECK(leave(&mo, g[0]) == handoff);
    CHECK(leave(&mo, g[1]) == handoff);
    CHECK(cvo.cv_owed == 0 && mo.reserved == 0 && cvo.cv_in == 0);
    /* the other order: E leaves first and takes the newer (the older is not its), then A the older */
    g[0] = enter(&mo);
    broadcast();
    g[1] = enter(&mo);
    broadcast();
    CHECK(leave(&mo, g[1]) == handoff && leave(&mo, g[0]) == handoff);
    CHECK(cvo.cv_owed == 0 && mo.reserved == 0);
    /* one waiter in and one only counted in (between cv_count_in and cv_enter, #156): only the one in is owed, and the
       other, in after the broadcast, does not take it even when it leaves first */
    g[0] = enter(&mo);
    cv_count_in(&cvo);
    broadcast();
    CHECK(mo.reserved == (handoff ? 1 : 0) && cvo.cv_owed == (handoff ? 1 : 0));
    g[1] = cvo.gen;
    cv_enter(&cvo, &mo);
    CHECK(leave(&mo, g[1]) == 0);
    CHECK(leave_all(&mo, g, 1) == (handoff ? 1 : 0));

    /* made again with nothing in: a new waiter and a new broadcast hand off as before, and a zero-timeout waiter after
       it takes nothing */
    g[0] = enter(&mo);
    broadcast();
    CHECK(leave_all(&mo, g, 1) == (handoff ? 1 : 0));
    CHECK(cvo.gen > 0);
    remake();
    g[0] = enter(&mo);
    CHECK(g[0] == 0);
    broadcast();
    CHECK(late_timeout(&mo) == 0);
    CHECK(leave_all(&mo, g, 1) == (handoff ? 1 : 0));
    /* made again with a waiter still in (a misuse): the one from before (its life an earlier one) takes no hand-off
       made for the waiter that came after, wakes all (the wake it came out at may have been that waiter's), and is not
       counted out of the new counts */
    g[0] = enter(&mo);
    CHECK(g[0] > 0);   /* (held to it, it could take no reservation of the new life: gen starts at 0 again) */
    const unsigned old_life = cvo.life;
    remake();
    g[1] = enter(&mo);
    broadcast();
    CHECK(mo.reserved == (handoff ? 1 : 0));
    const int a0 = wakealls;
    const int stale_owed = cv_leave(&cvo, &mo, g[0], old_life);
    CHECK(stale_owed == 0 && cvo.cv_in == 1 && cvo.cv_waiting == 1 && cvo.cv_owed == handoff);
    CHECK(wakealls == a0 + handoff);
    CHECK(leave_all(&mo, g + 1, 1) == handoff);
    /* two reservations on its mutex: the old-life waiter takes neither; the waiter that came in between the two
       broadcasts takes the newer (the only one it may), the other the older */
    g[0] = enter(&mo);
    const unsigned older_life = cvo.life;
    remake();
    g[1] = enter(&mo);
    broadcast();
    g[2] = enter(&mo);
    broadcast();
    CHECK(mo.reserved == (handoff ? 2 : 0));
    const int a1 = wakealls;
    CHECK(cv_leave(&cvo, &mo, g[0], older_life) == 0 && wakealls == a1 + handoff);
    CHECK(leave(&mo, g[2]) == handoff);
    CHECK(leave(&mo, g[1]) == handoff && mo.reserved == 0 && cvo.cv_owed == 0 && cvo.cv_in == 0);

    /* semaphore: a count there is taken at once */
    CHECK(acquire(2, 0, 0) == 1 && so.sem == 1 && waits == 0);
    CHECK(acquire(1, 5000000, 0) == 1 && so.sem == 0 && waits == 0);
    /* none there, zero or negative timeout: fails without waiting */
    CHECK(acquire(0, 0, 0) == 0 && so.sem == 0 && waits <= 1);
    CHECK(acquire(0, -5, 0) == 0 && so.sem == 0 && waits <= 1);
    /* a release 3 ms into a 10 ms wait: taken, before the deadline */
    int64_t t0 = now_ns;
    CHECK(acquire(0, 10000000, 3000000) == 1 && so.sem == 0 && now_ns - t0 < 10000000);
    /* no release: the deadline ends it */
    t0 = now_ns;
    CHECK(acquire(0, 10000000, 0) == 0 && so.sem == 0 && now_ns - t0 >= 10000000);
    /* a release after the deadline is not taken */
    CHECK(acquire(0, 2000000, 5000000) == 0 && so.sem == 0);
    /* a huge timeout (the deadline must not wrap): a release 3 ms in is taken */
    CHECK(acquire(0, INT64_MAX, 3000000) == 1 && so.sem == 0);
    /* HOS_CHAIN on: a wait is noted (in and out), an acquire that does not wait is not */
    hos_chain_on = 1;
    CHECK(acquire(1, 5000000, 0) == 1 && chain_notes == 0);
    CHECK(acquire(0, 5000000, 1000000) == 1 && chain_notes == 2);
    hos_chain_on = 0;
    return 0;
}
'''

# wait_until itself (the fixture above stubs it): the real one over a fake clock and a hos_cv_sleep that notes its ms
WAIT_FIXTURE = r'''#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
typedef uint32_t DWORD;
#define INFINITE 0xFFFFFFFFu
typedef struct { int held; } SRWLOCK;
typedef struct { int x; } CONDITION_VARIABLE;
typedef struct Obj { SRWLOCK lk; CONDITION_VARIABLE cv; } Obj;
static int64_t now_ns = 1000000000;
static int64_t hos_now_ns(void) { return now_ns; }
static int sleeps;
static unsigned slept_ms;
static int hos_cv_sleep(void *cv, void *lk, unsigned ms) { (void)cv, (void)lk; sleeps++; slept_ms = ms; return 1; }

@UNTIL@

/* a finite wait of left ns: one sleep, of whole ms rounded up, never INFINITE */
static unsigned finite(int64_t deadline) {
    sleeps = 0;
    CHECK(wait_until(&(Obj){{0}, {0}}, deadline) == 1 && sleeps == 1);
    CHECK(slept_ms != INFINITE);
    return slept_ms;
}
/* the longest step: below INFINITE (0x7FFFFFFF or INFINITE - 1 ms), not a wrapped or truncated count */
static int longest(unsigned ms) { return ms == 0x7FFFFFFF || ms == INFINITE - 1; }
int main(void) {
    Obj o = {{0}, {0}};
    /* 0: forever */
    CHECK(wait_until(&o, 0) == 1 && sleeps == 1 && slept_ms == INFINITE);
    /* a deadline now or past: a timeout, no sleep */
    sleeps = 0;
    CHECK(wait_until(&o, now_ns) == 0 && wait_until(&o, now_ns - 5) == 0 && sleeps == 0);
    /* short waits round up to whole ms (never 0: a 0 ms sleep would spin) */
    CHECK(finite(now_ns + 1) == 1 && finite(now_ns + 1000000) == 1 && finite(now_ns + 1000001) == 2);
    CHECK(finite(now_ns + (int64_t)0x7FFFFFFE * 1000000) == 0x7FFFFFFE);
    /* 0xFFFFFFFE ms, 0xFFFFFFFF ms (INFINITE as a DWORD), 2^32 ms (0 as a DWORD), 2^32 + 5 ms, a saturated deadline
       (INT64_MAX, as sema_acquire_for and event_wait make for a huge TimeSpan): one long step (~24 days or more), and the
       caller waits again */
    CHECK(finite(now_ns + (int64_t)0xFFFFFFFEu * 1000000) >= 0x7FFFFFFF);
    CHECK(longest(finite(now_ns + (int64_t)0xFFFFFFFFu * 1000000)));
    CHECK(longest(finite(now_ns + ((int64_t)1 << 32) * 1000000)));
    CHECK(longest(finite(now_ns + (((int64_t)1 << 32) + 5) * 1000000)));
    CHECK(longest(finite(INT64_MAX)));
    /* a clock near 0 with a saturated deadline: left + 999999 ns does not fit an int64_t (rounding must not wrap) */
    now_ns = 1;
    CHECK(longest(finite(INT64_MAX)));
    return 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()

    src = (ROOT / "host" / "nn_os_sync.c").read_text(encoding="utf-8")
    parts = {key: block(src, marker) for key, marker in PARTS.items()}
    for name, arg in SEMA_HLE.items():
        check(re.search(r"^HLE\(%s\) \{ RET\(sema_acquire_for\(obj\(ARG\(0\), K_SEMA\), %s\)\); \}$" % (name, re.escape(arg)), src, re.M),
              "%s is not the HLE's sema_acquire_for (left to the guest SDK, it never sees an HLE release)" % name)
    wait = block(src, "static int wait_until(Obj *o, int64_t deadline) {")
    env = {k: v for k, v in os.environ.items() if not k.startswith("HOS_")}

    def build(tmp, name, fixture=FIXTURE, **changed):
        text = fixture
        for key, part in dict(parts, **{"@UNTIL@": wait}).items():
            text = text.replace(key, changed.get(key, part))
        c, exe = Path(tmp) / (name + ".c"), Path(tmp) / (name + ".exe")
        c.write_text(text, encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-I",
                        str(ROOT / "gpu" / "vk" / "compat"), str(c), "-o", str(exe)], check=True)
        return exe

    def run(exe, no_handoff, handoff):
        e = dict(env) if no_handoff is None else dict(env, HOS_NO_HANDOFF=no_handoff)
        return subprocess.run([str(exe), str(handoff)], env=e, capture_output=True, text=True)

    with tempfile.TemporaryDirectory(prefix="os-siblings-") as tmp:
        exe = build(tmp, "fixture")
        for no_handoff, handoff in ((None, 1), ("1", 0), ("0", 1)):
            r = run(exe, no_handoff, handoff)
            check(r.returncode == 0, "HOS_NO_HANDOFF %r: not as expected\n%s" % (no_handoff, r.stderr))
            r = run(exe, no_handoff, 1 - handoff)
            check(r.returncode != 0 and "FAIL:" in r.stderr, "HOS_NO_HANDOFF %r passes both ways" % no_handoff)

        def broken(name, part, old, new, what):
            check(old in parts[part], "%s no longer has the line the broken variant '%s' changes" % (part, name))
            r = run(build(tmp, name, **{part: parts[part].replace(old, new)}), None, 1)
            check(r.returncode != 0 and "FAIL:" in r.stderr, what)

        broken("wake-one", "@BROADCAST@", "WakeAllConditionVariable(&cv->cv);", "WakeConditionVariable(&cv->cv);",
               "a broadcast waking one waiter passes")
        broken("no-gen", "@BROADCAST@", "cv->gen++;", "", "a broadcast not moving the generation passes")
        broken("owe-one", "@BROADCAST@", "for (int n = cv->cv_in - cv->cv_owed; n > 0; n--) cv_reserve(cv);",
               "cv_reserve(cv);", "a broadcast owing the mutex to one waiter passes")
        eligible = "if (cv->cv_owed_gen[i] >= gen && (k < 0 || cv->cv_owed_gen[i] < cv->cv_owed_gen[k]))"
        broken("anonymous", "@LEAVE@", eligible, "if ((void)gen, k < 0)",
               "a waiter that came in after the broadcast taking its hand-off (anonymous reservations) passes")
        broken("newest-first", "@LEAVE@", eligible,
               "if (cv->cv_owed_gen[i] >= gen && (k < 0 || cv->cv_owed_gen[i] > cv->cv_owed_gen[k]))",
               "a waiter taking the newest reservation it may (an older one is left to nobody) passes")
        stale = "        if (cv->cv_owed) WakeAllConditionVariable(&cv->cv);\n        return 0;\n    }"
        broken("stale-takes-own", "@LEAVE@", stale,
               "        if (cv->cv_owed && cv->cv_owed_mutex[0] == m) return cv->cv_owed--, 1;\n" + stale,
               "an old-life waiter taking a hand-off on its mutex (a later waiter's) passes")
        broken("stale-no-pass-on", "@LEAVE@", stale, stale.replace("if (cv->cv_owed) WakeAllConditionVariable(&cv->cv);", ""),
               "an old-life waiter not passing its wake on while a hand-off is owed passes")
        broken("unstamped", "@RESERVE@", "cv->cv_owed_gen[cv->cv_owed] = cv->gen;", "cv->cv_owed_gen[cv->cv_owed] = 0;",
               "a reservation not stamped with its generation passes")
        broken("wait-once", "@SEMA@", "while (s->sem <= 0 && wait_until(s, deadline) && hos_now_ns() < deadline) {}",
               "if (s->sem <= 0) wait_until(s, deadline);", "a timed acquire that waits once passes")
        broken("take-zero", "@SEMA@", "const int ok = s->sem > 0;", "const int ok = s->sem >= 0;",
               "a timed acquire taking a count of 0 passes")
        broken("no-take", "@SEMA@", "if (ok) __atomic_store_n(&s->sem, s->sem - 1, __ATOMIC_RELEASE);", "",
               "a timed acquire not taking the count passes")

        # wait_until: a finite wait sleeps in steps below INFINITE (0xFFFFFFFF ms is INFINITE on Windows)
        r = subprocess.run([str(build(tmp, "wait", WAIT_FIXTURE))], capture_output=True, text=True)
        check(r.returncode == 0, "wait_until: not as expected\n%s" % r.stderr)
        clamp = "ms >= INFINITE ? INFINITE - 1 : (DWORD)ms"
        check(clamp in wait, "wait_until no longer has the line the broken variant 'no-clamp' changes")
        r = subprocess.run([str(build(tmp, "wait-no-clamp", WAIT_FIXTURE, **{"@UNTIL@": wait.replace(clamp, "(DWORD)ms")}))],
                           capture_output=True, text=True)
        check(r.returncode != 0 and "FAIL:" in r.stderr,
              "a wait_until passing a long finite wait to the sleep as a bare DWORD (INFINITE, or truncated) passes")
        rounding = "const uint64_t ms = ((uint64_t)left + 999999) / 1000000;"
        check(rounding in wait, "wait_until no longer has the line the broken variant 'signed-rounding' changes")
        r = subprocess.run([str(build(tmp, "wait-signed", WAIT_FIXTURE, **{"@UNTIL@": wait.replace(
            rounding, "const int64_t ms = (left + 999999) / 1000000;")}))], capture_output=True, text=True)
        check(r.returncode != 0 and "FAIL:" in r.stderr,
              "a wait_until rounding a saturated deadline's ms in int64_t (it wraps) passes")


if __name__ == "__main__":
    main()
