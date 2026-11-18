/* (hookshot) HOS_SLOW_FRAMES=<path>: the slow-frame recorder. The all-thread sampler (host/posix/prof.c, host/mkw_glue.c
   sample_all_thread) samples every guest thread and the renderer's every HOS_SLOW_FRAMES_EVERY_MS (4 ms) for the whole run, into
   a ring in memory (the last several seconds), and nothing is written while the frames are on time. When a present comes
   HOS_SLOW_FRAME_MS (50 ms) or more after the one before it, the samples of that frame and of the 250 ms before it are written
   to <path>-<n>.txt in HOS_SAMPLE_ALL's format ("<ms> <thread>|<frames>", after "# t0_ns"), which scripts/hotlist.py,
   scripts/crit.py and scripts/cpu_report.py read: a stutter is caught as it happens, without sampling the whole run to a file
   and finding it afterwards. At most HOS_SLOW_FRAMES_MAX (40) files a run, at least a second apart. The sampling costs frame
   rate (a signal or a suspension per thread per sweep): a diagnostic, off by default, and not with HOS_SAMPLE_ALL (one
   sampler at a time). The log says each file written, with the frame's time. */
#include "hos.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { SLOW_RING = 1 << 16, SLOW_TEXT = 232 };
typedef struct { int64_t ns; char text[SLOW_TEXT]; } SlowLine;
static SlowLine *slow_ring;   /* (written by the sampler thread alone) */
static uint64_t slow_n;       /* (lines put in so far) */
static volatile int64_t slow_present_ns, slow_frame_ns;   /* (the slow frame to write: its present and its length; 0 none) */
static int64_t slow_last_present;   /* (the presenting thread's) */

static int env_int(const char *name, int def) {
    const char *e = getenv(name);
    return e && *e ? atoi(e) : def;
}
const char *hos_slow_frames_path(void) {
    static int done;
    static const char *path;
    if (!done) {
        done = 1;
        const char *e = getenv("HOS_SLOW_FRAMES");
        path = e && *e ? e : NULL;
        if (path && getenv("HOS_SAMPLE_ALL") && *getenv("HOS_SAMPLE_ALL")) {
            hos_log("prof: HOS_SLOW_FRAMES is off: HOS_SAMPLE_ALL samples already (one sampler at a time)");
            path = NULL;
        }
        if (path) {
            slow_ring = (SlowLine *)calloc(SLOW_RING, sizeof *slow_ring);
            if (!slow_ring) path = NULL;
        }
    }
    return path;
}
int hos_slow_frames_every_ms(void) {
    const int v = env_int("HOS_SLOW_FRAMES_EVERY_MS", 4);
    return v < 1 ? 1 : v;
}

/* (rx_nvn_present, on the thread that presents) a frame that came late: noted for the sampler to write */
void hos_slow_frame_present(void) {
    if (!slow_ring) return;
    static int64_t limit = -1;
    if (limit < 0) limit = (int64_t)env_int("HOS_SLOW_FRAME_MS", 50) * 1000000;
    const int64_t now = hos_now_ns(), d = slow_last_present ? now - slow_last_present : 0;
    slow_last_present = now;
    if (limit > 0 && d >= limit && !__atomic_load_n(&slow_present_ns, __ATOMIC_ACQUIRE)) {
        __atomic_store_n(&slow_frame_ns, d, __ATOMIC_RELAXED);
        __atomic_store_n(&slow_present_ns, now, __ATOMIC_RELEASE);
    }
}

/* (the sampler) one thread's sample, "<thread>|<frames>", of the sweep that began at sweep_ns: all of a sweep's samples share its
   time, as HOS_SAMPLE_ALL's lines share their millisecond (scripts/crit.py takes a time as one instant of every thread). A sample
   too long for the ring ends at its last whole frame */
void hos_slow_sample(int64_t sweep_ns, const char *text) {
    if (!slow_ring) return;
    SlowLine *l = &slow_ring[slow_n++ & (SLOW_RING - 1)];
    l->ns = sweep_ns;
    const size_t n = strlen(text);
    if (n < sizeof l->text) {
        memcpy(l->text, text, n + 1);
        return;
    }
    size_t cut = sizeof l->text - 1;
    while (cut && text[cut] != ';') cut--;   /* (the frame cut through left out) */
    memcpy(l->text, text, cut);
    l->text[cut] = 0;
}

/* (the sampler, after each sweep) a slow frame noted: its samples and the 250 ms before it written out */
void hos_slow_sweep_done(void) {
    const int64_t at = __atomic_load_n(&slow_present_ns, __ATOMIC_ACQUIRE);
    if (!slow_ring || !at) return;
    const int64_t len = __atomic_load_n(&slow_frame_ns, __ATOMIC_RELAXED);
    static int written;
    static int64_t last_written;
    const int most = env_int("HOS_SLOW_FRAMES_MAX", 40);
    if (written < most && (!last_written || at - last_written >= 1000000000LL)) {
        const int64_t from = at - len - 250000000LL;
        char name[1024];
        snprintf(name, sizeof name, "%s-%d.txt", hos_slow_frames_path(), written + 1);
        FILE *f = fopen(name, "w");
        if (f) {
            const uint64_t n = slow_n < SLOW_RING ? slow_n : SLOW_RING;
            int lines = 0;
            fprintf(f, "# slow frame: %.1f ms, presented at %lld ns (HOS_SLOW_FRAMES)\n# t0_ns %lld\n", len / 1e6, (long long)at,
                    (long long)from);
            for (uint64_t i = slow_n - n; i < slow_n; i++) {
                const SlowLine *l = &slow_ring[i & (SLOW_RING - 1)];
                if (l->ns < from || l->ns > at) continue;
                fprintf(f, "%ld %s\n", (long)((l->ns - from) / 1000000), l->text);
                lines++;
            }
            fclose(f);
            written++, last_written = at;
            hos_log("prof: a slow frame, %.1f ms: %d samples of it and the 250 ms before it in %s", len / 1e6, lines, name);
        }
    }
    __atomic_store_n(&slow_present_ns, 0, __ATOMIC_RELEASE);
}
