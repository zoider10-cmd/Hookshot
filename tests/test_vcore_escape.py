"""A guest thread that escaped a long wait for a virtual core (host/hos_thread.c vc_acquire: it runs without one) takes a
core again after its next block, like every other thread (issue 1929). The actual HosThread, hos_thread_core and the whole
virtual-core block (from vc_lock to hos_cv_sleep) are compiled with a single-threaded harness: a clock the waits advance,
no-op locks, a log that counts escapes. Before, hos_vcore_away answered 0 for the escaped thread (it held no core to give
up), so its `if (away) hos_vcore_back();` never ran and the thread kept running with no core, and with the core number of
a core another thread held, for the rest of its life. A hos_vcore_back without its away (a thread's start) ends an escape
too: a flag left up while the thread holds a core would make an inner block's away answer 1 and take a core in the
middle of the outer block.

A waiter that only waits because better threads keep the core it is pinned to (they take it in turns at every block, or
one runs on and never blocks) is starved, not deadlocked, and must not escape (issue 262): after HOS_VCORE_STARVE_US (1 s)
it goes before every other waiter at the next release of its core and asks the holder to give the core up, whatever the
holder's priority, so its wait ends in a grant. The same fixture with HOS_VCORE_STARVE_US=0 (the old rule) escapes after
2 s in both cases. Before the starved time nothing changes: the better waiter still gets the core first.

python -I -B tests/test_vcore_escape.py [--cxx clang++]
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def block(source, marker):
    start = source.index(marker)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end] + (";" if source[end:end + 1] == ";" else "")


HARNESS = r"""
#define _CRT_SECURE_NO_WARNINGS   /* (the vcore block reads its switches with getenv: the MSVC CRT warns of it) */
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef void *HANDLE;
typedef int BOOL;
typedef unsigned long DWORD;
typedef struct { void *p; } SRWLOCK, *PSRWLOCK;
typedef struct { void *p; } CONDITION_VARIABLE, *PCONDITION_VARIABLE;
#define SRWLOCK_INIT {0}
#define HOS_TLS_SLOTS 64
typedef struct { uint64_t x[32]; volatile int poll; } Ctx;
static int64_t now_ns = 1000000000;
static int64_t hos_now_ns(void) { return now_ns; }
static int hos_fps_timing;   /* (hookshot: the slow-frame port's counters read it, host/hos_main.c) */
enum { HOS_CHAIN_WAIT = 1, HOS_CHAIN_WOKE, HOS_CHAIN_SIGNAL, HOS_CHAIN_SLEEP, HOS_CHAIN_AWAKE, HOS_CHAIN_PRESENT };
#define HOS_CHAIN(kind, key) ((void)(kind), (void)(key))   /* (HOS_CHAIN off: host/hos.h) */
static int escapes_logged;
static void hos_log(const char *fmt, ...) { if (strstr(fmt, "ran without a core")) escapes_logged++; }
static int hos_cores(void) { return 2; }
static int sleeps;
static void (*on_sleep)(void);   /* (what the other threads do during one look: only the test sets it) */
/* (no other thread runs here, except what on_sleep does: a wait for a core lets the clock go on, 1 ms a look, as the real one
   times out) */
static BOOL SleepConditionVariableSRW(PCONDITION_VARIABLE cv, PSRWLOCK lk, DWORD ms, unsigned long f) {
    (void)cv, (void)lk, (void)f;
    now_ns += (int64_t)(ms ? ms : 1) * 1000000;
    sleeps++;
    if (on_sleep) on_sleep();
    return 1;
}
static void WakeConditionVariable(PCONDITION_VARIABLE cv) { (void)cv; }
static void AcquireSRWLockExclusive(PSRWLOCK l) { (void)l; }
static void ReleaseSRWLockExclusive(PSRWLOCK l) { (void)l; }
@STRUCT@
static HosThread *cur;
@CORE@
@VCORES@
static int bad;
static void check(int ok, const char *what) { if (!ok) { printf("FAIL: %s\n", what); bad = 1; } }
static void thread(HosThread *t, const char *name, int prio, uint64_t mask) {
    memset(t, 0, sizeof *t);
    snprintf(t->name, sizeof t->name, "%s", name);
    t->priority = prio, t->core_mask = mask, t->ideal_core = -2;
}
/* the holders of both cores never give them up while t waits: t escapes; then one holder blocks */
static void escape(HosThread *t, HosThread *h0, HosThread *h1) {
    cur = h0; hos_vcore_back();
    cur = h1; hos_vcore_back();
    check(h0->vc_held && h1->vc_held, "the two holders hold the two cores");
    const int before = escapes_logged;
    cur = t; hos_vcore_back();
    check(escapes_logged == before + 1 && !t->vc_held, "the waiter escaped (ran without a core)");
    cur = h1; check(hos_vcore_away() == 1, "a holder gives its core up for a block");
    cur = t;
}
/* issue 262: a thread pinned to core 1 waits behind better ones. sa (16) and sb (17) are better than sw (28). */
static HosThread sa, sb, sw;
static int replaced, picked_better;
static void enqueue(HosThread *t) { t->vc_since = now_ns; t->vc_queued = 1; vc_queue[vc_nq++] = t; }
static void reset(uint64_t sa_mask) {
    memset(vc_owner, 0, sizeof vc_owner), vc_nq = 0, memset(&vc_st, 0, sizeof vc_st);
    on_sleep = NULL, sleeps = replaced = picked_better = 0, escapes_logged = 0;
    thread(&sa, "better0", 16, sa_mask), thread(&sb, "better1", 17, 2), thread(&sw, "starved", 28, 2);
    cur = &sw;
}
/* the holder of core 1 blocks and is back at once: a release, then a new wait behind the others */
static void take_turns(void) {
    HosThread *old = vc_owner[1];
    vc_release(old);
    if (vc_owner[1] != &sw) enqueue(old), replaced++;
}
/* the holder runs on, and gives the core up when asked, at its next checkpoint (hos_vcore_checkpoint) */
static void checkpoint(void) {
    HosThread *saved = cur;
    cur = vc_owner[1];
    hos_vcore_checkpoint();
    cur = saved;
}
/* before the starved time the better waiter still gets the core: one release at look 300, one at 301 */
static void order(void) {
    if (sleeps == 300) vc_release(vc_owner[1]), picked_better = vc_owner[1] == &sb;
    else if (sleeps == 301 && vc_owner[1] == &sb) vc_release(&sb);
}
static void starvation(int off) {
    reset(2);   /* better threads take the core in turns */
    vc_take(&sa, 1), enqueue(&sb);
    on_sleep = take_turns;
    hos_vcore_back();
    check(replaced > 100, "the better threads took the core in turns while sw waited");
    if (off) {
        check(escapes_logged == 1 && !sw.vc_held && sleeps > 2000, "turn taking: without the boost sw escapes after 2 s");
    } else {
        check(escapes_logged == 0 && sw.vc_held == 2, "turn taking: the starved thread gets the core, no escape");
        check(sleeps > 1000 && sleeps < 1100, "and not before it has waited 1 s");
    }

    reset(3);   /* a better thread runs on, and answers a request at its checkpoints */
    vc_take(&sa, 1);
    on_sleep = checkpoint;
    hos_vcore_back();
    if (off) {
        check(escapes_logged == 1 && !sw.vc_held && sa.vc_held == 2, "holder runs on: without the boost sw escapes");
    } else {
        check(escapes_logged == 0 && sw.vc_held == 2, "a holder that runs on gives the core to the starved thread");
        check(sa.vc_held == 1 && sleeps > 1000 && sleeps < 1100, "and takes the other core after it, not before 1 s");
    }

    reset(2);   /* before the starved time nothing changes: the better waiter first */
    vc_take(&sa, 1), enqueue(&sb);
    on_sleep = order;
    hos_vcore_back();
    check(picked_better && escapes_logged == 0 && sw.vc_held == 2,
          "before the starved time the better waiter gets the core first and the waiter after it");
    on_sleep = NULL;
}
int main(int argc, char **argv) {
    if (argc > 1) {   /* the old rule: HOS_VCORE_STARVE_US=0 */
        starvation(1);
        if (!bad) puts("ok");
        return bad;
    }
    HosThread h0, h1, t, u;
    thread(&h0, "holder0", 16, 1), thread(&h1, "holder1", 16, 2), thread(&t, "waiter", 16, 3);

    escape(&t, &h0, &h1);   /* a block of the escaped thread (hos_sleep_ns, hos_thread_wait, the NVN waits, ...) */
    const int away = hos_vcore_away();
    check(away == 1, "hos_vcore_away tells an escaped thread to take a core after its block");
    if (away) hos_vcore_back();
    check(t.vc_held == 2, "after its block the escaped thread holds the free core");
    check(hos_thread_core(&t) == 1 && hos_thread_core(&t) != hos_thread_core(&h0),
          "and reports that core's number, not the one the other holder runs on");
    check(hos_vcore_away() == 1 && !t.vc_held, "and gives it up at its next block as every holder does");

    thread(&t, "waiter", 16, 3), thread(&h0, "holder0", 16, 1), thread(&h1, "holder1", 16, 2);
    memset(vc_owner, 0, sizeof vc_owner);
    escape(&t, &h0, &h1);   /* the same through hos_cv_sleep (the nn::os waits) */
    SRWLOCK lk = SRWLOCK_INIT;
    CONDITION_VARIABLE cv = {0};
    hos_cv_sleep(&cv, &lk, 1);
    check(t.vc_held == 2, "after a hos_cv_sleep the escaped thread holds the free core");

    thread(&t, "waiter", 16, 3), thread(&h0, "holder0", 16, 1), thread(&h1, "holder1", 16, 2);
    memset(vc_owner, 0, sizeof vc_owner);
    escape(&t, &h0, &h1);   /* a block inside a block: only the outer one takes the core again */
    const int outer = hos_vcore_away();
    const int inner = hos_vcore_away();
    check(outer == 1 && inner == 0, "only the outermost block of an escaped thread takes a core after it");
    if (inner) hos_vcore_back();
    check(!t.vc_held, "no core is taken inside the outer block");
    if (outer) hos_vcore_back();
    check(t.vc_held == 2, "the core is taken after the outer block");

    thread(&t, "waiter", 16, 3), thread(&h0, "holder0", 16, 1), thread(&h1, "holder1", 16, 2);
    memset(vc_owner, 0, sizeof vc_owner);
    escape(&t, &h0, &h1);   /* a back without its away (as at a thread's start) takes the core: the escape is over */
    hos_vcore_back();
    check(t.vc_held == 2, "a back without an away gives the escaped thread the free core");
    const int outer2 = hos_vcore_away();
    const int inner2 = hos_vcore_away();
    check(outer2 == 1 && inner2 == 0, "after a back without an away, a block inside a block takes no core after it");
    if (inner2) hos_vcore_back();
    check(!t.vc_held, "no core is taken inside the outer block after a back without an away");
    if (outer2) hos_vcore_back();
    check(t.vc_held == 2, "the core is taken after the outer block");

    thread(&t, "waiter", 16, 3), thread(&h0, "holder0", 16, 1), thread(&h1, "holder1", 16, 2);
    memset(vc_owner, 0, sizeof vc_owner);
    escape(&t, &h0, &h1);   /* a back without its away that escapes again: that escape ends at the next block */
    cur = &h1; hos_vcore_back();
    cur = &t;
    const int before = escapes_logged;
    hos_vcore_back();
    check(escapes_logged == before + 1 && !t.vc_held, "a back without an away escapes again while both cores are held");
    check(hos_vcore_away() == 1, "and the thread still takes a core after its next block");

    thread(&u, "never-held", 16, 3);   /* a thread that holds no core and never escaped: nothing to take after a block */
    cur = &u;
    check(hos_vcore_away() == 0, "a thread that never escaped and holds no core takes none after a block");
    starvation(0);
    if (!bad) puts("ok");
    return bad;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    parser.add_argument("--source", type=Path, default=ROOT / "host/hos_thread.c")
    args = parser.parse_args()
    src = args.source.read_text(encoding="utf-8")
    start = src.index("static SRWLOCK vc_lock = SRWLOCK_INIT;")
    end = src.index("\n#else", src.index("int hos_cv_sleep(void *cv, void *lk, unsigned ms) {", start))
    fixture = (HARNESS.replace("@STRUCT@", block(src, "struct HosThread {") + "\ntypedef struct HosThread HosThread;")
               .replace("@CORE@", block(src, "int hos_thread_core(HosThread *t) {"))
               .replace("@VCORES@", src[start:end]))
    compiler = shutil.which(args.cxx)
    if not compiler:
        raise SystemExit("C++ compiler not found: " + args.cxx)
    with tempfile.TemporaryDirectory(prefix="vcore-escape-") as temporary:
        folder = Path(temporary)
        (folder / "fixture.cpp").write_text(fixture, encoding="utf-8")
        exe = folder / ("fixture.exe" if os.name == "nt" else "fixture")
        subprocess.run([compiler, "-std=c++17", "-O1", "-w", str(folder / "fixture.cpp"), "-o", str(exe)], check=True,
                       timeout=120)
        result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
        print(result.stdout, end="")
        old = subprocess.run([str(exe), "old"], capture_output=True, text=True, timeout=30,
                             env={**os.environ, "HOS_VCORE_STARVE_US": "0"})
        print(old.stdout, end="")
        if result.returncode or "ok" not in result.stdout:
            raise SystemExit("a starved thread escapes, or an escaped thread does not take a core again (issues 262, 1929)")
        if old.returncode or "ok" not in old.stdout:
            raise SystemExit("with HOS_VCORE_STARVE_US=0 the fixture no longer shows the old escape (issue 262)")


if __name__ == "__main__":
    main()
