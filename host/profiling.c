/* (hookshot) HOS_PROFILE=1: the profiling mode. One switch (allowed in hookshot_env.txt) that records, for the whole run,
   what it takes to find where the time goes and what each stutter was, into a folder of its own, logs/profile-<date>-<time>/:

     all.txt       every game and renderer thread's stack every 2 ms (HOS_SAMPLE_ALL, from the start; deleting all.txt.go
                   pauses it, making it again goes on), packed: each distinct stack written once ("s <id> <frames>") and a sample
                   as "<ms> <thread>|=<id>" (HOS_SAMPLE_PACKED), about a tenth of the plain format's size
     presents.csv  the game's presents (HOS_PRESENT_TRACE)
     frames.csv    the renderer's frame trace (RX_VK_FRAME_TRACE): each frame's waits, the Breakdown's parts and the main
                   thread's CPU, blocked and virtual-core time, with at_ns, the present on this clock
     cpu.csv       every second: the process's CPU time and resident memory, and the system's available memory
     events.txt    timed events the log has no time for: each wait of HOS_VCORE_LOG_MS or more for a virtual core, its cause
     process.json  the run's switches (RX_, HOS_, HOOKSHOT_), and hookshot_options.ini, the settings as the run started

   and in the log, every 5 s the busiest threads (HOS_PROFILE_EVERY=5, which also lets HOS_SAMPLE=<thread> sample one
   thread) and the threads' CPU (HOS_THREAD_TIMES=5), HOS_FPS_LOG, RX_VK_PASS_TIMING=1 (GPU time a pass: its timestamps make the GPU finish
   each pass before the next, so the GPU's numbers are its shares, not an unprofiled frame's) and RX_VK_SLOW_LOG=50. A switch
   already set keeps its value (RX_VK_PASS_TIMING=0 leaves the pass timing out). An older HOS_PROFILE=<seconds> (the
   busiest threads' log, before the mode) turns it all on too, with its seconds for the log's lines. All times are hos_now_ns's, so the samples,
   presents, frames and events line up. python -I scripts/profile_report.py <folder> reads the folder into trace.json.gz (Perfetto: each thread's
   stack over time, the frames, the waits, the counters), speedscope.json (flame graphs) and report.md: the
   frame rate and frame times over the run, what limits the frame, the hottest code on each thread, and each stutter's
   causes. It costs frame rate (the sampler suspends or signals each thread every 2 ms): a diagnostic, off by default. All
   times and names, no game data: the samples are module+offset, named from the build's symbols by the script. */
#include "hos.h"
#include "hos_paths.h"
#include "options_path.h"
#include "../gpu/vk/compat/hookshot_env.h"
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#ifdef _WIN32
#include <windows.h>
#define SEP_S "\\"
#else
#include <windows.h>   /* (host/posix's) */
#include <unistd.h>
#define SEP_S "/"
extern char **environ;
#endif

static char prof_dir[MAX_PATH + 64];   /* (the run's profile folder; "" when the mode is off) */

const char *hos_profiling_dir(void) { return prof_dir[0] ? prof_dir : NULL; }

static void set_default(const char *name, const char *value) {
    if (getenv(name)) return;   /* (the environment's or hookshot_env.txt's value goes first) */
#ifdef _WIN32
    char put[MAX_PATH + 160];
    snprintf(put, sizeof put, "%s=%s", name, value);
    _putenv(put);
#else
    setenv(name, value, 1);
#endif
}

static void in_dir(char *out, size_t cap, const char *name) { snprintf(out, cap, "%s" SEP_S "%s", prof_dir, name); }

static char game_dir[MAX_PATH];   /* (the game folder, with its separator: left out of the paths process.json names) */

static void json_string(FILE *f, const char *s) {
    fputc('"', f);
    const size_t g = strlen(game_dir);
    if (g && !strncmp(s, game_dir, g)) {   /* (the player's folders name their user: "<game folder>/logs/...") */
        fputs("<game folder>/", f);
        s += g;
    } else if (strpbrk(s, "/\\") || (s[0] && s[1] == ':')) {   /* (another path, RX_VK_DLSS_DIR's say: left out) */
        fputs("<a path>\"", f);
        return;
    }
    for (; *s; s++) {
        const unsigned char c = (unsigned char)*s;
        if (c == '"' || c == '\\') fprintf(f, "\\%c", c);
        else if (c < 0x20) fprintf(f, "\\u%04x", c);
        else fputc(c, f);
    }
    fputc('"', f);
}

/* (hos_main.c, after hookshot_env.txt and hos_game_layout: logs/ is made) the folder chosen and the switches set, before
   anything reads them */
void hos_profiling_env(void) {
    if (!env_on("HOS_PROFILE")) return;
    if (strcmp(getenv("HOS_PROFILE"), "1"))   /* (HOS_PROFILE=<seconds> was the busiest threads' log alone, before the mode) */
        fprintf(stderr, "env: HOS_PROFILE=%s turns the whole profiling mode on (the 2 ms sampler, the pass timing: not for "
                        "frame rate numbers); the busiest threads' log alone is HOS_PROFILE_EVERY=<seconds> now\n",
                getenv("HOS_PROFILE"));
    char game[MAX_PATH];
    DWORD n = hos_game_path_a(game, MAX_PATH);
    while (n && game[n - 1] != '\\' && game[n - 1] != '/') n--;
    if (!n || n >= MAX_PATH) {
        fprintf(stderr, "env: HOS_PROFILE=1: no game folder, so no profile\n");
        return;
    }
    game[n] = 0;
    snprintf(game_dir, sizeof game_dir, "%s", game);
    const time_t now = time(NULL);
    struct tm tm;
#ifdef _WIN32
    localtime_s(&tm, &now);
#else
    localtime_r(&now, &tm);
#endif
    char stamp[32];
    strftime(stamp, sizeof stamp, "%Y%m%d-%H%M%S", &tm);
    /* (a folder of this run's own: two starts in one second, the shader preparation's and the game's say, get -2, -3...) */
    int made = 0;
    for (int k = 1; k <= 50 && !made; k++) {
        if (k == 1) snprintf(prof_dir, sizeof prof_dir, "%slogs" SEP_S "profile-%s", game, stamp);
        else snprintf(prof_dir, sizeof prof_dir, "%slogs" SEP_S "profile-%s-%d", game, stamp, k);
        made = CreateDirectoryA(prof_dir, NULL) != 0;
        if (!made && GetFileAttributesA(prof_dir) == INVALID_FILE_ATTRIBUTES) break;   /* (not there and not made: no use going on) */
    }
    if (!made) {
        fprintf(stderr, "env: HOS_PROFILE=1: could not make %s, so no profile\n", prof_dir);
        prof_dir[0] = 0;
        return;
    }
    char path[MAX_PATH + 96];
#ifdef _WIN32
    snprintf(path, sizeof path, "HOS_PROFILE_DIR=%s", prof_dir);
    _putenv(path);   /* (the renderer's frames.csv: always this run's folder) */
#else
    setenv("HOS_PROFILE_DIR", prof_dir, 1);
#endif
    in_dir(path, sizeof path, "all.txt");
    set_default("HOS_SAMPLE_ALL", path);
    set_default("HOS_SAMPLE_PACKED", "1");
    if (!strcmp(getenv("HOS_SAMPLE_ALL"), path)) {   /* (sampling from the start: the sampler samples while <file>.go is there) */
        char go[MAX_PATH + 128];
        snprintf(go, sizeof go, "%s.go", path);
        FILE *g = fopen(go, "w");
        if (g) fclose(g);
    }
    in_dir(path, sizeof path, "presents.csv");
    set_default("HOS_PRESENT_TRACE", path);
    set_default("RX_VK_FRAME_TRACE", "1");
    /* (the log's lines every n seconds, the busiest threads (HOS_PROFILE_EVERY) and the threads' CPU (HOS_THREAD_TIMES): 5 s,
       or the seconds an older HOS_PROFILE=<seconds> gave, which turns the whole mode on now) */
    char every[16];
    const int secs = atoi(getenv("HOS_PROFILE"));
    snprintf(every, sizeof every, "%d", secs >= 2 ? secs : 5);
    set_default("HOS_PROFILE_EVERY", every);
    set_default("HOS_THREAD_TIMES", getenv("HOS_PROFILE_EVERY"));
    set_default("HOS_FPS_LOG", "1");
    set_default("RX_VK_PASS_TIMING", "1");
    set_default("RX_VK_SLOW_LOG", "50");
    in_dir(path, sizeof path, "process.json");
    FILE *f = fopen(path, "w");
    if (f) {
        fprintf(f, "{\"started\": \"%s\", \"os\": \"%s\", \"env\": {", stamp,
#ifdef _WIN32
                "windows"
#else
                "linux"
#endif
        );
        int first = 1;
#ifdef _WIN32
        char **env = _environ;
#else
        char **env = environ;
#endif
        for (; env && *env; env++) {
            const char *e = *env, *eq = strchr(e, '=');
            if (!eq || !(!strncmp(e, "RX_", 3) || !strncmp(e, "HOS_", 4) || !strncmp(e, "HOOKSHOT_", 9))) continue;
            char name[128];
            snprintf(name, sizeof name, "%.*s", (int)(eq - e < 127 ? eq - e : 127), e);
            fprintf(f, "%s\n  ", first ? "" : ","), first = 0;
            json_string(f, name);
            fputs(": ", f);
            json_string(f, eq + 1);
        }
        fputs("}}\n", f);
        fclose(f);
    }
    fprintf(stderr, "env: HOS_PROFILE=1: a profile of this run in %s (python -I scripts/profile_report.py <that folder>)\n",
            prof_dir);
}

/* ---- events.txt: "<ns> <text>", for what the log has no time for */
static SRWLOCK ev_lock = SRWLOCK_INIT;
static FILE *ev_file;
static int ev_n;
void hos_profiling_event(const char *fmt, ...) {
    if (!prof_dir[0]) return;
    const int64_t at = hos_now_ns();
    char text[768];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(text, sizeof text, fmt, ap);
    va_end(ap);
    for (char *q = text; *q; q++) if (*q == '\n' || *q == '\r') *q = ' ';
    AcquireSRWLockExclusive(&ev_lock);
    if (!ev_file && ev_n == 0) {
        char path[MAX_PATH + 96];
        in_dir(path, sizeof path, "events.txt");
        ev_file = fopen(path, "w");
    }
    if (ev_file && ev_n < 200000)   /* (no flush here: the caller holds the virtual cores' lock; cpu_thread flushes, every second) */
        fprintf(ev_file, "%lld %s\n", (long long)at, text);
    ev_n++;
    ReleaseSRWLockExclusive(&ev_lock);
}

/* ---- cpu.csv: the process's CPU and memory every second */
static int64_t process_cpu_ns(void) {
#ifdef _WIN32
    FILETIME c, e, k, u;
    if (!GetProcessTimes(GetCurrentProcess(), &c, &e, &k, &u)) return 0;
    const uint64_t kk = ((uint64_t)k.dwHighDateTime << 32) | k.dwLowDateTime, uu = ((uint64_t)u.dwHighDateTime << 32) | u.dwLowDateTime;
    return (int64_t)((kk + uu) * 100);
#else
    struct timespec ts;
    return clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &ts) ? 0 : (int64_t)ts.tv_sec * 1000000000LL + ts.tv_nsec;
#endif
}
static void memory_mb(double *rss, double *avail) {
    *rss = *avail = 0;
#ifdef _WIN32
    typedef struct {   /* (PROCESS_MEMORY_COUNTERS_EX, taken from kernel32 as host/mkw_glue.c does: no psapi) */
        DWORD cb, PageFaultCount;
        SIZE_T PeakWorkingSetSize, WorkingSetSize, QuotaPeakPagedPoolUsage, QuotaPagedPoolUsage,
            QuotaPeakNonPagedPoolUsage, QuotaNonPagedPoolUsage, PagefileUsage, PeakPagefileUsage, PrivateUsage;
    } Counters;
    typedef BOOL(WINAPI * Fn)(HANDLE, Counters *, DWORD);
    static Fn fn;
    if (!fn) fn = (Fn)(void *)GetProcAddress(GetModuleHandleA("kernel32.dll"), "K32GetProcessMemoryInfo");
    Counters m;
    memset(&m, 0, sizeof m);
    m.cb = sizeof m;
    if (fn && fn(GetCurrentProcess(), &m, sizeof m)) *rss = m.WorkingSetSize / 1048576.0;
    MEMORYSTATUSEX ms = {sizeof ms};
    if (GlobalMemoryStatusEx(&ms)) *avail = ms.ullAvailPhys / 1048576.0;
#else
    FILE *f = fopen("/proc/self/statm", "r");
    long size = 0, res = 0;
    if (f) {
        if (fscanf(f, "%ld %ld", &size, &res) == 2) *rss = res * (double)sysconf(_SC_PAGESIZE) / 1048576.0;
        fclose(f);
    }
    f = fopen("/proc/meminfo", "r");
    if (f) {
        char line[128];
        long kb;
        while (fgets(line, sizeof line, f))
            if (sscanf(line, "MemAvailable: %ld kB", &kb) == 1) { *avail = kb / 1024.0; break; }
        fclose(f);
    }
#endif
}
static DWORD WINAPI cpu_thread(void *p) {
    FILE *f = (FILE *)p;
    fputs("t_ns,process_cpu_ns,rss_mb,available_mb\n", f);
    for (;;) {
        double rss, avail;
        memory_mb(&rss, &avail);
        fprintf(f, "%lld,%lld,%.1f,%.1f\n", (long long)hos_now_ns(), (long long)process_cpu_ns(), rss, avail);
        fflush(f);
        AcquireSRWLockExclusive(&ev_lock);   /* (events.txt's lines of the last second) */
        if (ev_file) fflush(ev_file);
        ReleaseSRWLockExclusive(&ev_lock);
        Sleep(1000);
    }
    return 0;
}

/* (hos_prof_start, once the settings file is chosen) the settings copied and cpu.csv started */
void hos_profiling_start(void) {
    if (!prof_dir[0]) return;
    char path[MAX_PATH + 96];
    const char *ini = hos_options_file();
    if (ini && *ini) {
        FILE *from = fopen(ini, "rb");
        in_dir(path, sizeof path, "hookshot_options.ini");
        FILE *to = from ? fopen(path, "wb") : NULL;
        char buf[4096];
        size_t got;
        while (to && (got = fread(buf, 1, sizeof buf, from)) > 0) fwrite(buf, 1, got, to);
        if (to) fclose(to);
        if (from) fclose(from);
    }
    in_dir(path, sizeof path, "cpu.csv");
    FILE *f = fopen(path, "w");
    if (f) CreateThread(NULL, 0, cpu_thread, f, 0, NULL);
    hos_log("prof: profiling mode (HOS_PROFILE=1): this run's profile is in %s", prof_dir);
}

/* ---- the all-thread samplers' lines (host/posix/prof.c, host/mkw_glue.c sample_all_thread), "<ms> <thread>|<frames>":
   as they are, or with HOS_SAMPLE_PACKED each distinct stack once. Only the sampler's thread calls it. A stack is known by a
   64-bit hash of its text (a collision would give a sample another stack: about one in 10^8 runs of a million stacks) */
static uint64_t *pk_keys;   /* (hash | 1, 0 empty) */
static uint32_t *pk_ids;
static size_t pk_cap, pk_used;
static uint32_t pk_next;
static uint32_t pack_id(uint64_t h, int *fresh) {
    if (pk_used * 2 >= pk_cap) {
        const size_t cap = pk_cap ? pk_cap * 2 : 1 << 16;
        uint64_t *k = (uint64_t *)calloc(cap, sizeof *k);
        uint32_t *v = (uint32_t *)calloc(cap, sizeof *v);
        if (!k || !v) { free(k), free(v); *fresh = -1; return 0; }
        for (size_t i = 0; i < pk_cap; i++)
            if (pk_keys[i]) {
                size_t j = (size_t)(pk_keys[i] * 0x9E3779B97F4A7C15ULL >> 20) & (cap - 1);
                while (k[j]) j = (j + 1) & (cap - 1);
                k[j] = pk_keys[i], v[j] = pk_ids[i];
            }
        free(pk_keys), free(pk_ids);
        pk_keys = k, pk_ids = v, pk_cap = cap;
    }
    h |= 1;
    size_t j = (size_t)(h * 0x9E3779B97F4A7C15ULL >> 20) & (pk_cap - 1);
    while (pk_keys[j] && pk_keys[j] != h) j = (j + 1) & (pk_cap - 1);
    if (pk_keys[j]) { *fresh = 0; return pk_ids[j]; }
    pk_keys[j] = h, pk_ids[j] = ++pk_next, pk_used++;
    *fresh = 1;
    return pk_next;
}
void hos_sample_write(void *file, const char *line) {
    FILE *out = (FILE *)file;
    static int packed = -1;
    if (packed < 0) packed = env_on("HOS_SAMPLE_PACKED");
    const char *bar = packed ? strchr(line, '|') : NULL;
    if (!bar) {
        fprintf(out, "%s\n", line);
        return;
    }
    uint64_t h = 1469598103934665603ULL;   /* (FNV-1a) */
    for (const char *q = bar + 1; *q; q++) h = (h ^ (unsigned char)*q) * 1099511628211ULL;
    int fresh;
    const uint32_t id = pack_id(h, &fresh);
    if (fresh < 0) {   /* (no memory for the table: the plain line) */
        fprintf(out, "%s\n", line);
        return;
    }
    if (fresh) fprintf(out, "s %u %s\n", id, bar + 1);
    fprintf(out, "%.*s|=%u\n", (int)(bar - line), line, id);
}
