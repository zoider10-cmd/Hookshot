"""HOS_VCORE_TURN_US (host/hos_thread.c, vc_turn_ns and vc_askable): a thread given a virtual core as a starved waiter
(HOS_VCORE_STARVE_US) keeps it for its turn: no waiter asks for it back before the turn ends, though a better one waits. The
actual HosThread, hos_thread_core and the whole virtual-core block (from vc_lock to hos_cv_sleep) are compiled with a
single-threaded harness (a clock the waits advance, 1 ms a look, no-op locks), as tests/test_vcore_escape.py does, and run
three ways:

- HOS_VCORE_STARVE_US=10000 HOS_VCORE_TURN_US=2000: a loading thread pinned to core 1 (priority 26) behind a frame worker
  (16) that runs on is starved after 10 ms and given the core; the worker, waiting for it again, does not ask for it before
  2 ms and has it after; a block of the starved thread in its turn gives the core up at once, as any block does; a thread
  that took a free core without being starved has no turn.
- HOS_VCORE_STARVE_US=10000 alone (the switch off, its default): the worker asks at once and has the core at the holder's
  next checkpoint, as before the switch.
- HOS_VCORE_TURN_US=1000000: the turn is held to 100 ms.

In all of them a core has one holder at a time: at every look, at most one thread holds core 1, and it is vc_owner[1].

python -I -B tests/test_vcore_turn.py [--cxx clang++]
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))   # (python -I leaves the check's own folder off the path)
from srccut import block, between  # noqa: E402

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

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
static int hos_fps_timing;
enum { HOS_CHAIN_WAIT = 1, HOS_CHAIN_WOKE, HOS_CHAIN_SIGNAL, HOS_CHAIN_SLEEP, HOS_CHAIN_AWAKE, HOS_CHAIN_PRESENT };
#define HOS_CHAIN(kind, key) ((void)(kind), (void)(key))
static int escapes_logged, turn_told;
static void hos_log(const char *fmt, ...) {
    if (strstr(fmt, "ran without a core")) escapes_logged++;
    if (strstr(fmt, "HOS_VCORE_TURN_US")) turn_told++;
}
static const char *hos_profiling_dir(void) { return 0; }
static void hos_profiling_event(const char *fmt, ...) { (void)fmt; }
static int hos_cores(void) { return 2; }
static int sleeps;
static void (*on_sleep)(void);
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
static HosThread worker, loader, other;
static int shared_core;   /* (a look found two holders of core 1, or a holder vc_owner does not name) */
static void one_holder(void) {
    HosThread *all[] = {&worker, &loader, &other};
    int n = 0;
    for (int i = 0; i < 3; i++)
        if (all[i]->vc_held == 2) {
            n++;
            if (vc_owner[1] != all[i]) shared_core = 1;
        }
    if (n > 1) shared_core = 1;
}
static void thread(HosThread *t, const char *name, int prio, uint64_t mask) {
    memset(t, 0, sizeof *t);
    snprintf(t->name, sizeof t->name, "%s", name);
    t->priority = prio, t->core_mask = mask, t->ideal_core = -2;
}
static void reset(void) {
    memset(vc_owner, 0, sizeof vc_owner), vc_nq = 0, memset(&vc_st, 0, sizeof vc_st);
    on_sleep = NULL, sleeps = 0, escapes_logged = 0, shared_core = 0;
    thread(&worker, "BaseProcExecutor1", 16, 2), thread(&loader, "PreActorModelCompose", 26, 2), thread(&other, "Other", 16, 1);
}
/* the holder of core 1 runs on and gives the core up at its next checkpoint once asked (it then blocks: it is not back) */
static int released_at;
static void answer(void) {
    one_holder();
    HosThread *h = vc_owner[1];
    if (h && h->vc_kick) {
        released_at = sleeps;
        HosThread *saved = cur;
        cur = h;
        hos_vcore_away();
        cur = saved;
    }
}
/* the loader blocks in its turn (a wait, a file read) at the first look */
static void loader_blocks(void) {
    one_holder();
    if (sleeps == 1 && loader.vc_held) {
        HosThread *saved = cur;
        cur = &loader;
        hos_vcore_away();
        cur = saved;
    }
}
/* the worker runs on core 1; the loader waits until it is starved (10 ms) and is given the core */
static void starve_loader(void) {
    reset();
    vc_take(&worker, 1);
    cur = &loader;
    on_sleep = answer;
    hos_vcore_back();
    check(loader.vc_held == 2 && !worker.vc_held && escapes_logged == 0, "the starved loader is given core 1, no escape");
    check(sleeps > 10 && sleeps < 14, "after it has waited the starved time (10 ms)");
}
static void run(const char *mode) {
    const int on = !strcmp(mode, "turn"), clamp = !strcmp(mode, "clamp");
    starve_loader();
    const int64_t turn = on ? 2000000 : clamp ? 100000000 : 0;
    check(loader.vc_turn_until == (turn ? now_ns + turn : 0), on ? "the starved loader's turn is 2 ms"
          : clamp ? "the turn is held to 100 ms" : "with the switch off a starved loader has no turn");
    check(turn_told == (turn != 0), "the log says the turn once when the switch is on, never when it is off");
    if (clamp) return;

    /* the worker waits for core 1 again while the loader runs on through its checkpoints */
    cur = &worker;
    sleeps = 0, released_at = -1;
    hos_vcore_back();
    check(worker.vc_held == 2 && !loader.vc_held, "the worker has core 1 back");
    if (on)
        check(released_at == 3 && sleeps == 3, "in its turn the loader is not asked: the worker asks at 2 ms and has it after");
    else
        check(released_at == 1 && sleeps == 1, "switch off: the worker asks at once, as before");
    check(hos_thread_core(&worker) == 1, "the worker reports core 1");

    /* a block in the turn gives the core up at once */
    starve_loader();
    cur = &worker;
    sleeps = 0;
    on_sleep = loader_blocks;
    hos_vcore_back();
    check(worker.vc_held == 2 && sleeps == 1, "a block of the loader in its turn gives the worker the core at once");

    /* a thread that took a free core without waiting gets no turn */
    reset();
    cur = &loader;
    hos_vcore_back();
    check(loader.vc_held == 2 && loader.vc_turn_until == 0, "a core taken free, without a starved wait, has no turn");
    cur = &worker;
    on_sleep = answer, released_at = -1;
    hos_vcore_back();
    check(worker.vc_held == 2 && released_at == 1 && sleeps == 1, "and its holder is asked at once by a better waiter");

    check(!shared_core, "core 1 never had two holders at once, nor a holder vc_owner did not name");
    check(escapes_logged == 0, "no thread ran without a core");
}
int main(int argc, char **argv) {
    run(argc > 1 ? argv[1] : "turn");
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
    vcores = between(src, "static SRWLOCK vc_lock = SRWLOCK_INIT;", "\n#else\nint hos_vcores_on(void) { return 0; }")
    fixture = (HARNESS.replace("@STRUCT@", block(src, "struct HosThread {") + ";\ntypedef struct HosThread HosThread;")
               .replace("@CORE@", block(src, "int hos_thread_core(HosThread *t) {"))
               .replace("@VCORES@", vcores))
    compiler = shutil.which(args.cxx)
    if not compiler:
        raise SystemExit("C++ compiler not found: " + args.cxx)
    with tempfile.TemporaryDirectory(prefix="vcore-turn-") as temporary:
        folder = Path(temporary)
        (folder / "fixture.cpp").write_text(fixture, encoding="utf-8")
        exe = folder / ("fixture.exe" if os.name == "nt" else "fixture")
        subprocess.run([compiler, "-std=c++17", "-O1", "-w", str(folder / "fixture.cpp"), "-o", str(exe)], check=True,
                       timeout=120)
        base = {k: v for k, v in os.environ.items() if not k.startswith("HOS_VCORE")}
        runs = (("turn", {"HOS_VCORE_STARVE_US": "10000", "HOS_VCORE_TURN_US": "2000"}),
                ("off", {"HOS_VCORE_STARVE_US": "10000"}),
                ("clamp", {"HOS_VCORE_STARVE_US": "10000", "HOS_VCORE_TURN_US": "1000000"}))
        failed = []
        for mode, env in runs:
            result = subprocess.run([str(exe), mode], capture_output=True, text=True, timeout=30, env={**base, **env})
            print(mode + ":", result.stdout.strip())
            if result.returncode or "ok" not in result.stdout:
                failed.append(mode)
        if failed:
            raise SystemExit("HOS_VCORE_TURN_US: a starved thread's turn is not kept, or is kept with the switch off, "
                             "or a core had two holders (%s)" % ", ".join(failed))


if __name__ == "__main__":
    main()
