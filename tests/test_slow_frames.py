"""The slow-frame recorder (host/slow_frames.c, HOS_SLOW_FRAMES), compiled with a stub host (no game, no GPU): a late present
writes the samples of its frame and the 250 ms before it, in HOS_SAMPLE_ALL's format with one time a sweep, and nothing else;
a sample too long for the ring ends at its last whole frame; an on-time frame writes nothing. Then the source checks: both
samplers feed it with the sweep's time, the present tells it, and the long virtual-core wait and the frame trace's main-thread
columns are where the time is spent.

python -I -B tests/test_slow_frames.py
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from srccut import block  # noqa: E402

STUB_HOS = r'''
#pragma once
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
extern int64_t fake_now;
static inline int64_t hos_now_ns(void) { return fake_now; }
static inline void hos_log(const char *fmt, ...) { va_list a; va_start(a, fmt); vfprintf(stderr, fmt, a); va_end(a); fputc('\n', stderr); }
const char *hos_slow_frames_path(void);
int hos_slow_frames_every_ms(void);
void hos_slow_frame_present(void);
void hos_slow_sample(int64_t sweep_ns, const char *text);
void hos_slow_sweep_done(void);
'''

DRIVER = r'''
#include "hos.h"
#include <assert.h>
#include <stdlib.h>
#ifdef _WIN32   /* (hookshot: no setenv in the Windows C library) */
static int setenv(const char *n, const char *v, int o) { (void)o; return _putenv_s(n, v); }
#endif
#include <string.h>
int64_t fake_now;
static void sweep(int64_t t, const char *a, const char *b) {
    fake_now = t;
    hos_slow_sample(t, a);
    fake_now = t + 1500000;   /* (the second thread sampled 1.5 ms into the sweep: the line keeps the sweep's time) */
    hos_slow_sample(t, b);
    hos_slow_sweep_done();
}
int main(int argc, char **argv) {
    (void)argc;
    setenv("HOS_SLOW_FRAMES", argv[1], 1);
    assert(hos_slow_frames_path() && !strcmp(hos_slow_frames_path(), argv[1]));
    char longest[800] = "Long|";   /* (hookshot: 600 held 684 bytes; Windows caught it) */
    for (int i = 0; i < 40; i++) strcat(longest, i ? ";longshot+1234567" : "longshot+1234567");
    int64_t t = 1000000000;   /* 1 s */
    for (int i = 0; i < 100; i++, t += 4000000) {   /* (400 ms of sweeps, 4 ms apart, frames on time every 16 ms) */
        sweep(t, "sead::MainThread|longshot+10;longshot+20", i == 50 ? longest : "Worker|longshot+30");
        if (i % 4 == 0) { fake_now = t; hos_slow_frame_present(); }
    }
    /* (an on-time run so far: nothing written) */
    char name[512];
    snprintf(name, sizeof name, "%s-1.txt", argv[1]);
    assert(!fopen(name, "r"));
    fake_now = t + 80000000;   /* (the next present 80 ms after the last one: a slow frame) */
    hos_slow_frame_present();
    sweep(t + 80000000, "sead::MainThread|longshot+40", "Worker|longshot+50");
    FILE *f = fopen(name, "r");
    assert(f);
    char line[1024];
    int lines = 0, header = 0, same_ms = 0, long_ok = 0;
    long last_ms = -1;
    while (fgets(line, sizeof line, f)) {
        if (line[0] == '#') { header++; continue; }
        long ms = atol(line);
        same_ms += ms == last_ms;
        last_ms = ms;
        lines++;
        if (strstr(line, " Long|")) {
            const size_t n = strlen(line);
            long_ok = n < 240 && line[n - 2] == '7' && line[n - 1] == '\n';   /* (cut at a whole frame: ends in ...+1234567) */
        }
        assert(strchr(line, '|'));
    }
    fclose(f);
    assert(header == 2);
    /* (the frame, 96 ms back to the last on-time present, and the 250 ms before it: 66 sweeps of two samples, and the slow
       present's own sweep) */
    assert(lines >= 126 && lines <= 140);
    assert(same_ms * 2 >= lines - 2);   /* (both samples of a sweep share its millisecond) */
    assert(long_ok);
    snprintf(name, sizeof name, "%s-2.txt", argv[1]);
    assert(!fopen(name, "r"));   /* (one slow frame, one file) */
    puts("slow frames: ok");
    return 0;
}
'''


def need(ok, what):
    if not ok:
        raise SystemExit("slow frames: " + what)


def sources():
    slow = (ROOT / "host/slow_frames.c").read_text(encoding="utf-8")
    for path in ("host/posix/prof.c", "host/mkw_glue.c"):
        src = (ROOT / path).read_text(encoding="utf-8")
        sampler = block(src, "static DWORD WINAPI sample_all_thread(void *p)")
        need("const int ring = path == hos_slow_frames_path();" in sampler, path + ": the sampler has no ring mode")
        need("const int64_t sweep_ns = hos_now_ns();" in sampler and "hos_slow_sample(sweep_ns," in sampler,
             path + ": the ring's samples do not share their sweep's time")
        need("if (ring) hos_slow_sweep_done();" in sampler, path + ": a sweep's end is not told to the recorder")
        need("CreateThread(NULL, 0, sample_all_thread, (void *)slow, 0, NULL);" in block(src, "void hos_prof_start(void) {"),
             path + ": HOS_SLOW_FRAMES starts no sampler")
    need("hos_slow_frame_present();" in block((ROOT / "host/rx_backend.c").read_text(encoding="utf-8"),
                                              "void rx_nvn_present(const nvn_tex *t, const int crop[4])"),
         "rx_nvn_present does not tell the recorder")
    need('getenv("HOS_SAMPLE_ALL")' in slow, "HOS_SLOW_FRAMES does not stand down for HOS_SAMPLE_ALL")
    threads = (ROOT / "host/hos_thread.c").read_text(encoding="utf-8")
    acquire = block(threads, "static void vc_acquire(HosThread *t)")
    need("if (vc_log_ns() && waited >= vc_log_ns()) vc_long_wait(t, waited, how, vc_allowed(t));" in acquire,
         "a long wait for a virtual core is not logged")
    need("if (hos_fps_timing) t->vc_wait_total += waited;" in acquire, "the virtual core's waits are not counted")
    need("vc_grant(c, t);" in block(threads, "static void vc_release(HosThread *t)"), "a grant does not know who let the core go")
    need("t->blocked_total += hos_now_ns() - t->away_at" in block(threads, "void hos_vcore_back(void)", unique=False),
         "a block's time is not counted")
    # (hookshot) the frame trace's main-thread columns (MkwVkHost main_thread_times, Longshot's API 27) are not ported: our API is Mako's 23
    main = (ROOT / "host/hos_main.c").read_text(encoding="utf-8")
    record = block(main, "static void record_stutters_env(void)")
    need('env_on("HOS_RECORD_STUTTERS")' in record and '"logs" SEP_S "slow_frame"' in record,
         "HOS_RECORD_STUTTERS does not point the recorder at logs/slow_frame")
    need('if (!getenv("HOS_SLOW_FRAMES"))' in record and 'if (!getenv("RX_VK_FRAME_TRACE"))' in record,
         "HOS_RECORD_STUTTERS replaces a switch already set")
    need(main.count("load_hookshot_env();\n    record_stutters_env();") == 2,
         "HOS_RECORD_STUTTERS is not read after hookshot_env.txt in both mains")
    need('"HOS_SLOW_FRAMES"' in block(main, "static int env_line_allowed(const char *name, const char *value)"),
         "hookshot_env.txt takes HOS_SLOW_FRAMES, a path")


def compiled():
    cc = os.environ.get("CC") or shutil.which("clang") or shutil.which("gcc") or shutil.which("cc")
    if not cc:
        print("slow frames: no C compiler, the compiled part skipped")
        return
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "hos.h").write_text(STUB_HOS, encoding="utf-8")
        (Path(d) / "driver.c").write_text(DRIVER, encoding="utf-8")
        shutil.copy(ROOT / "host/slow_frames.c", Path(d) / "slow_frames.c")
        exe = str(Path(d) / "t")
        subprocess.run([cc, "-std=c11", "-D_POSIX_C_SOURCE=200809L", "-Wall", "-I", d, str(Path(d) / "driver.c"),
                        str(Path(d) / "slow_frames.c"), "-o", exe], check=True)
        subprocess.run([exe, str(Path(d) / "f")], check=True)


if __name__ == "__main__":
    sources()
    compiled()
    print("slow frames: ok")
