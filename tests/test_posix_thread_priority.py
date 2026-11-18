"""SetThreadPriority on a thread just made takes effect on Linux (host/posix/win32_posix.c).

hos_thread_start (host/hos_thread.c) calls hos_thread_pin right after CreateThread, and it lowers a thread by name:
OptimizeChangeBank to THREAD_PRIORITY_LOWEST, any thread HOS_PRIO names. The posix SetThreadPriority sets the nice value
of the thread's kernel id, which the new thread writes only once it runs: asked before that, the lowering was dropped and
the thread ran at the normal priority.

Builds win32_posix.c as it is with a fixture that makes threads and lowers each at once, before it can have run (the
process kept to one processor, so the new thread waits for this one), then reads each thread's nice value from inside it.

python -I -B tests/test_posix_thread_priority.py [--cc gcc]
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]
RUN_ALL_SKIP = {"windows": "the posix layer is Linux's"}

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''#define _GNU_SOURCE
#include <windows.h>
#include <sched.h>
#include <sys/resource.h>
#include <sys/syscall.h>
static HANDLE go;
static volatile int seen;
static DWORD lowered(void *p) {
    (void)p;
    WaitForSingleObject(go, INFINITE);
    errno = 0;
    seen = getpriority(PRIO_PROCESS, (id_t)syscall(SYS_gettid));
    return 0;
}
int main(void) {
    if (getpriority(PRIO_PROCESS, 0) >= 10) {   /* (run under nice already: nothing lower to see) */
        printf("SKIP: this process runs at nice 10 or more\n");
        return 0;
    }
    cpu_set_t one;
    CPU_ZERO(&one);
    CPU_SET(sched_getcpu(), &one);
    sched_setaffinity(0, sizeof one, &one);
    int lost = 0;
    for (int i = 0; i < 20; i++) {
        go = CreateEventA(NULL, TRUE, FALSE, NULL);
        HANDLE h = CreateThread(NULL, 0, lowered, NULL, 0, NULL);
        SetThreadPriority(h, THREAD_PRIORITY_LOWEST);
        SetEvent(go);
        WaitForSingleObject(h, INFINITE);
        CloseHandle(h);
        CloseHandle(go);
        if (seen != 10) lost++;
    }
    if (lost) {
        fprintf(stderr, "FAIL: %d of 20 threads lowered right after CreateThread kept the normal priority\n", lost);
        return 1;
    }
    printf("PASS: a thread lowered right after CreateThread runs lowered (nice 10)\n");
    return 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    if os.name == "nt" or sys.platform == "darwin":
        print("SKIP: the posix layer's checks run on Linux")
        return
    with tempfile.TemporaryDirectory(prefix="posix-prio-") as tmp:
        tmp = Path(tmp)
        src = tmp / "fixture.c"
        src.write_text(FIXTURE, encoding="utf-8")
        exe = tmp / "fixture"
        subprocess.run([a.cc, "-std=gnu11", "-O1", "-w", "-I", str(ROOT / "host/posix"), str(src),
                        str(ROOT / "host/posix/win32_posix.c"), "-o", str(exe), "-ldl", "-lpthread"], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        print(r.stdout, end="")
        if r.returncode:
            print(r.stderr, end="")
            raise SystemExit("test_posix_thread_priority: failed (exit %d)" % r.returncode)


if __name__ == "__main__":
    main()
