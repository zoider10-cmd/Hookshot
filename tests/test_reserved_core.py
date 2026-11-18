"""The core hos_reserved_cpus keeps for the replay (host/hos_thread.c pick_reserved_core): the last core of the fastest kind.

On a CPU of one kind every core has the same EfficiencyClass and the last core is kept, as before; on Intel's hybrid CPUs
the efficiency cores come last and have the lower class, so the last performance core is kept instead. None is kept with
fewer than 8 logical processors, nor on a CPU of more than one kind with fewer than 4 cores of the fastest kind.

On Linux the classes come from /sys/devices/cpu_core/cpus, the performance cores' cpulist (parse_cpu_list), and
hos_reserved_cpus asks last_fastest_core there before it falls back to the last core the process may run on (its
affinity: a process kept to some processors has its replay on one of those).

The replay runs on that core on Linux too (replay_pin_mask, gpu/vk/vk_replay.cpp), and a thread made inside a pinned
replay starts with the process's affinity, not the pin (host/posix/win32_posix.c).

On Linux, with real threads over host/posix/win32_posix.c as it is (its thread records counted): inside the real ReplayPin,
guest_bytes' helper threads (gpu/vk/vk_texture.cpp) read on the process's logical processors and the replaying thread on
the pin, which is undone after; std::threads that register with the shim and end leave no thread record behind; a
CreateThread thread and a registered thread that calls ExitThread each give theirs back once.

python -I -B tests/test_reserved_core.py [--cxx clang++] [--cc clang]
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cxx", "g++", "--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cxx', default='g++')
    parser.add_argument('--cc', default='gcc')
    parser.add_argument('--source', type=Path, default=ROOT / 'host/hos_thread.c')
    args = parser.parse_args()
    helper = block(args.source.read_text(encoding='utf-8'), 'static uint64_t pick_reserved_core(')
    helper += chr(10) + block(args.source.read_text(encoding='utf-8'), 'static uint64_t pick_cache_cores(')
    helper += chr(10) + block(args.source.read_text(encoding='utf-8'), 'static uint64_t parse_cpu_list(')
    source = args.source.read_text(encoding='utf-8')
    reserved = block(source, 'uint64_t hos_reserved_cpus(void)')
    linux = block(source, 'static uint64_t last_fastest_core(int *cores) {\n    *cores = 0;')
    assert '#elif !defined(__EMSCRIPTEN__)' in reserved and reserved.index('last_fastest_core(&cores)', reserved.index('#elif')) > 0, \
        'hos_reserved_cpus no longer asks last_fastest_core on Linux'
    # (hookshot) the fallback keeps a core the process may run on: one outside its affinity is where a pinned replay would leave it
    assert 'GetProcessAffinityMask(GetCurrentProcess(), &proc, &sys)' in reserved and \
        '!((uint64_t)info[i].ProcessorMask & ~(uint64_t)proc)' in reserved, \
        "hos_reserved_cpus' fallback no longer keeps to the cores the process may run on"
    assert '/sys/devices/cpu_core/cpus' in linux and 'parse_cpu_list(' in linux and 'pick_reserved_core(' in linux, \
        "Linux's last_fastest_core no longer reads the performance cores from /sys/devices/cpu_core/cpus"
    vk_replay = (ROOT / 'gpu/vk/vk_replay.cpp').read_text(encoding='utf-8')
    pin_mask = block(vk_replay, 'uint64_t replay_pin_mask()')
    assert '_WIN32' not in pin_mask and 'host->reserved_cpus' in pin_mask, \
        'replay_pin_mask must use host->reserved_cpus on Linux as well as Windows'
    posix = (ROOT / 'host/posix/win32_posix.c').read_text(encoding='utf-8')
    assert 'apply_process_affinity(t->th)' in block(posix, 'static HThread *thread_self(void)') and \
        'apply_process_affinity(t->th)' in block(posix, 'static void *thread_entry(void *p)'), \
        'win32_posix.c must reset new threads to process_affinity so helper threads do not inherit ReplayPin on Linux'
    # (hookshot) a thread its maker pinned by its handle before it started keeps that pin: the reset and the pin under one lock
    assert 'if (!t->pinned) apply_process_affinity(t->th)' in block(posix, 'static void *thread_entry(void *p)') and \
        't->pinned = 1' in block(posix, 'DWORD_PTR SetThreadAffinityMask(HANDLE h, DWORD_PTR mask)'), \
        "thread_entry's reset must leave a thread SetThreadAffinityMask pinned already"
    fixture = r'''
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstdarg>
#define CHECK(ok) do { if (!(ok)) { std::fprintf(stderr, "failed line %d\n", __LINE__); std::exit(1); } } while (0)
// Stub for hos_log used in pick_reserved_core logging
inline void hos_log(const char* fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fprintf(stderr, "\n");
}
''' + helper + r'''
struct Core { uint64_t mask; unsigned char cls; };
uint64_t pick(const Core* cores, int n) {
    uint64_t masks[256];
    unsigned char classes[256];
    for (int i = 0; i < n; i++) { masks[i] = cores[i].mask; classes[i] = cores[i].cls; }
    return pick_reserved_core(masks, classes, n);
}
struct L3 { uint64_t mask, size; int per = 1; };   // (per: logical processors a core, 2 with SMT)
uint64_t cache(const L3* l3, int nl3) {
    uint64_t masks[64], sizes[64], cores[64];
    int ncores = 0;
    for (int i = 0; i < nl3; i++) {
        masks[i] = l3[i].mask; sizes[i] = l3[i].size;
        for (int bit = 0; bit < 64; bit += l3[i].per)
            if (l3[i].mask >> bit & 1) cores[ncores++] = ((1ull << l3[i].per) - 1) << bit;
    }
    return pick_cache_cores(masks, sizes, nl3, cores, ncores);
}
void add(Core* v, int* idx, int n, int per, int first, unsigned char cls) {
    for (int i = 0; i < n; i++) {
        v[*idx].mask = ((1ull << per) - 1) << (first + i * per);
        v[*idx].cls = cls;
        (*idx)++;
    }
}
void classify(Core* v, int n, uint64_t fast) {   // (Linux: class 1 where the core is in cpu_core's list)
    for (int i = 0; i < n; i++) v[i].cls = (v[i].mask & fast) != 0;
}
int main() {
    {   // Linux cpulists
        CHECK(parse_cpu_list("0-7\n") == 0xFF);
        CHECK(parse_cpu_list("0-11,16-19") == 0xF0FFF);
        CHECK(parse_cpu_list("3") == 0x8);
        CHECK(parse_cpu_list("0,2,4-5\n") == 0x35);
        CHECK(parse_cpu_list("60-70") == 0xF000000000000000ull);   // (past 63: left out)
        CHECK(parse_cpu_list("") == 0);
        CHECK(parse_cpu_list("x") == 0);
        CHECK(parse_cpu_list("5-2") == 0);
        CHECK(parse_cpu_list("1;2") == 0);
    }
    {   // the cores that share the largest L3, when the CPU's L3s differ
        const uint64_t MB = 1 << 20;
        L3 l3_1[2] = {{0xFF, 96 * MB, 1}, {0xFF00, 32 * MB, 1}};
        CHECK(cache(l3_1, 2) == 0xFF);                    // Ryzen 9 9950X3D, SMT off: 8 cores
        L3 l3_2[2] = {{0xFFFF, 96 * MB, 2}, {0xFFFF0000, 32 * MB, 2}};
        CHECK(cache(l3_2, 2) == 0xFFFF);                  // 9950X3D / 7950X3D with SMT: 8 cores
        L3 l3_3[2] = {{0xFFFF0000, 96 * MB, 2}, {0xFFFF, 32 * MB, 2}};
        CHECK(cache(l3_3, 2) == 0xFFFF0000);              // (the cache on the second CCD)
        L3 l3_4[2] = {{0xFFF, 96 * MB, 2}, {0xFFF000, 32 * MB, 2}};
        CHECK(cache(l3_4, 2) == 0);                       // 7900X3D with SMT: 6 cores are too few
        L3 l3_5[2] = {{0x3F, 96 * MB, 1}, {0xFC0, 32 * MB, 1}};
        CHECK(cache(l3_5, 2) == 0);                       // 7900X3D, SMT off: the same 6
        L3 l3_6[2] = {{0xFF, 16 * MB, 2}, {0xFFFF00, 8 * MB, 2}};
        CHECK(cache(l3_6, 2) == 0);                       // Ryzen AI 9 HX 370: 4 Zen 5 + 8 Zen 5c, SMT
        L3 l3_7[2] = {{0xF, 16 * MB, 1}, {0xFF0, 8 * MB, 1}};
        CHECK(cache(l3_7, 2) == 0);                       // (the same with SMT off)
        L3 l3_8[2] = {{0xFF, 16 * MB, 2}, {0xFF00, 8 * MB, 1}};
        CHECK(cache(l3_8, 2) == 0);                       // (shared by as many, but 4 cores on the largest)
        L3 l3_9[2] = {{0xFFFF, 32 * MB, 2}, {0xFFFF0000, 32 * MB, 2}};
        CHECK(cache(l3_9, 2) == 0);                       // Ryzen 9 7950X: both CCDs alike
        L3 l3_10[1] = {{0xFFFF, 96 * MB, 2}};
        CHECK(cache(l3_10, 1) == 0);                      // 9800X3D: one L3 for all
        L3 l3_11[1] = {{0xFFFFFF, 30 * MB, 1}};
        CHECK(cache(l3_11, 1) == 0);                      // Intel hybrid: one L3 for all
        CHECK(cache(nullptr, 0) == 0);
        L3 l3_12[3] = {{0xFF, 96 * MB, 1}, {0xFF00, 96 * MB, 1}, {0xFF0000, 32 * MB, 1}};
        CHECK(cache(l3_12, 3) == 0xFFFF);                 // (two of the largest: both)
        {   // (the cores could not be read: none)
            const uint64_t masks[2] = {0xFF, 0xFF00}, sizes[2] = {96 * MB, 32 * MB};
            CHECK(pick_cache_cores(masks, sizes, 2, nullptr, 0) == 0);
        }
    }
    Core v[64];
    int idx = 0;
    add(v, &idx, 12, 2, 0, 0); CHECK(pick(v, idx) == 0xC00000); idx = 0;  // Ryzen 9 3900X
    add(v, &idx, 6, 2, 0, 0); CHECK(pick(v, idx) == 0xC00); idx = 0;      // Ryzen 5 7600X
    add(v, &idx, 8, 1, 0, 0); CHECK(pick(v, idx) == 0x80); idx = 0;       // 8 cores without SMT
    add(v, &idx, 4, 2, 0, 0); CHECK(pick(v, idx) == 0xC0); idx = 0;       // 4 cores with SMT
    add(v, &idx, 6, 1, 0, 0); CHECK(pick(v, idx) == 0); idx = 0;          // 6 cores without SMT
    add(v, &idx, 8, 2, 0, 1); add(v, &idx, 4, 1, 16, 0); CHECK(pick(v, idx) == 0xC000); idx = 0;  // i7-12700K
    add(v, &idx, 8, 2, 0, 1); add(v, &idx, 16, 1, 16, 0); CHECK(pick(v, idx) == 0xC000); idx = 0;  // i9-13900K
    add(v, &idx, 4, 1, 0, 0); add(v, &idx, 4, 2, 4, 1); CHECK(pick(v, idx) == 0xC00); idx = 0;     // efficiency first
    add(v, &idx, 4, 1, 0, 1); add(v, &idx, 4, 1, 4, 0); CHECK(pick(v, idx) == 0x8); idx = 0;       // Lunar Lake
    add(v, &idx, 2, 2, 0, 1); add(v, &idx, 8, 1, 4, 0); CHECK(pick(v, idx) == 0); idx = 0;         // i5-1235U
    add(v, &idx, 2, 2, 0, 1); add(v, &idx, 4, 1, 4, 0); CHECK(pick(v, idx) == 0); idx = 0;         // i3-1215U
    add(v, &idx, 3, 2, 0, 1); add(v, &idx, 8, 1, 6, 0); CHECK(pick(v, idx) == 0); idx = 0;         // 3 fast cores
    CHECK(pick(nullptr, 0) == 0);                                       // empty
    // Linux, classes from /sys/devices/cpu_core/cpus
    add(v, &idx, 20, 1, 0, 0); classify(v, idx, parse_cpu_list("0-7\n")); CHECK(pick(v, idx) == 0x80); idx = 0;  // Core Ultra 7 265KF
    add(v, &idx, 8, 2, 0, 0); add(v, &idx, 4, 1, 16, 0); classify(v, idx, parse_cpu_list("0-15\n"));
    CHECK(pick(v, idx) == 0xC000); idx = 0;                                                                         // i7-12700K
    add(v, &idx, 2, 2, 0, 0); add(v, &idx, 8, 1, 4, 0); classify(v, idx, parse_cpu_list("0-3\n"));
    CHECK(pick(v, idx) == 0); idx = 0;                                                                              // i5-1235U
    add(v, &idx, 8, 2, 0, 0); v[idx].mask = 0; v[idx].cls = 1; idx++; CHECK(pick(v, idx) == 0xC000); // empty mask
    puts("PASS: the last core of the fastest kind with 4+ of them, the last core on CPUs of one kind, none under 8 "
          "logical processors");
}
'''
    with tempfile.TemporaryDirectory(prefix='reserved-core-') as tmp:
        cpp = Path(tmp) / 'fixture.cpp'
        exe = Path(tmp) / 'fixture.exe'
        cpp.write_text(fixture, encoding='utf-8')
        subprocess.run([args.cxx, '-std=c++20', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    if sys.platform.startswith('linux'):
        threads_check(args.cxx, args.cc)
    else:
        print('skip: the helper threads and thread records on Linux (host/posix/win32_posix.c is not built here)')


THREADS = r'''
#include <windows.h>
#include <pthread.h>
#include <sched.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <mutex>
#include <set>
#include <thread>
#include <vector>
#define CHECK(ok) do { if (!(ok)) { std::fprintf(stderr, "failed line %d\n", __LINE__); std::exit(1); } } while (0)
extern "C" long hthread_made, hthread_freed;   // (the shim's thread records: thread_new's, and thread_unref's frees)
static uint64_t mask_now() {
    cpu_set_t s;
    CPU_ZERO(&s);
    CHECK(sched_getaffinity(0, sizeof s, &s) == 0);
    uint64_t m = 0;
    for (int i = 0; i < 64; i++) if (CPU_ISSET(i, &s)) m |= 1ull << i;
    return m;
}
static uint64_t reserved;
static std::mutex seen_mu;
static std::map<long, std::set<uint64_t>> seen;   // (each reading thread's masks)
namespace mkwvk {
static void logf(const char*, ...) {}
struct Host {
    uint8_t* (*gpu_ptr)(uint64_t gpu, uint64_t* avail);
    int (*gpu_read)(uint64_t gpu, void* dst, uint64_t n);
    uint64_t (*reserved_cpus)(void);
};
static Host host_v = {
    [](uint64_t, uint64_t* avail) -> uint8_t* { *avail = 0; return nullptr; },
    [](uint64_t gpu, void* dst, uint64_t n) -> int {
        { std::lock_guard<std::mutex> l(seen_mu); seen[syscall(SYS_gettid)].insert(mask_now()); }
        for (uint64_t i = 0; i < n; i++) ((uint8_t*)dst)[i] = (uint8_t)((gpu + i) * 13);
        return 1;
    },
    [] { return reserved; },
};
static Host* host = &host_v;
static bool async_on() { return false; }
static const uint8_t* memory_as_submitted(uint64_t, const uint8_t* p, uint64_t, std::vector<uint8_t>&) { return p; }
@REPLAY@
@TEXTURE@
}
static void* registered_exit(void*) {
    GetCurrentThreadId();
    ExitThread(7);
}
static DWORD WINAPI created(void*) { return 3; }
static void wait_freed(long want) {   // (a thread gives its record back after it is marked done)
    for (int i = 0; i < 1000 && __atomic_load_n(&hthread_freed, __ATOMIC_ACQUIRE) < want; i++) usleep(1000);
    usleep(20000);
}
int main() {
    const uint64_t process = mask_now();
    if (__builtin_popcountll(process) < 2 || std::thread::hardware_concurrency() < 4) {
        std::puts("skip: fewer than 4 logical processors for the helper threads");
        return 0;
    }
    reserved = 1ull << (63 - __builtin_clzll(process));
    GetCurrentThreadId();   // (the main thread's record, kept: made before the counts are taken)
    {   // the helpers made inside the pin
        std::vector<uint8_t> scratch;
        const uint64_t gpu = 3ull << 40, n = 32ull << 20;
        const long tid = syscall(SYS_gettid);
        {
            mkwvk::ReplayPin pin;
            CHECK(mask_now() == reserved);
            const uint8_t* got = mkwvk::guest_bytes(gpu, n, scratch);
            for (uint64_t i = 0; i < n; i += 4093) CHECK(got[i] == (uint8_t)((gpu + i) * 13));
        }
        CHECK(mask_now() == process);   // (the pin undone)
        CHECK(seen.count(tid) && seen[tid] == std::set<uint64_t>{reserved});   // (the replaying thread's share on the pin)
        CHECK(seen.size() >= 2);
        for (auto& [t, masks] : seen)
            if (t != tid) {
                if (masks != std::set<uint64_t>{process})
                    std::fprintf(stderr, "helper %ld read with mask %#llx, not the process's %#llx\n", t,
                                 (unsigned long long)*masks.begin(), (unsigned long long)process);
                CHECK(masks == std::set<uint64_t>{process});
            }
    }
    {   // registered std::threads that end give their records back
        const long made = hthread_made, freed = hthread_freed;
        for (int round = 0; round < 20; round++) {
            std::vector<std::thread> pool;
            for (int i = 0; i < 10; i++) pool.emplace_back([] { GetCurrentThreadId(); });
            for (auto& t : pool) t.join();
        }
        wait_freed(freed + 200);
        if (hthread_freed - freed != 200)
            std::fprintf(stderr, "200 registered threads ended: %ld records made, %ld given back\n", hthread_made - made,
                         hthread_freed - freed);
        CHECK(hthread_made - made == 200 && hthread_freed - freed == 200);
    }
    {   // a CreateThread thread, and a registered thread that calls ExitThread: each record given back once
        long made = hthread_made, freed = hthread_freed;
        HANDLE h = CreateThread(nullptr, 0, created, nullptr, 0, nullptr);
        CHECK(h && WaitForSingleObject(h, INFINITE) == WAIT_OBJECT_0);
        DWORD code = 0;
        CHECK(GetExitCodeThread(h, &code) && code == 3);
        CloseHandle(h);
        wait_freed(freed + 1);
        CHECK(hthread_made - made == 1 && hthread_freed - freed == 1);
        made = hthread_made, freed = hthread_freed;
        pthread_t th;
        CHECK(pthread_create(&th, nullptr, registered_exit, nullptr) == 0);
        CHECK(pthread_join(th, nullptr) == 0);
        wait_freed(freed + 1);
        CHECK(hthread_made - made == 1 && hthread_freed - freed == 1);
    }
    std::puts("PASS: a pinned replay's helper threads read on the process's logical processors, its own share on the pin; "
              "200 registered threads that ended left no thread record; CreateThread's and ExitThread's given back once");
}
'''


def threads_check(cxx, cc):
    posix = (ROOT / 'host/posix/win32_posix.c').read_text(encoding='utf-8')
    new = block(posix, 'static HThread *thread_new(void) {')
    unref = block(posix, 'static void thread_unref(HThread *t) {')
    assert 'calloc(1, sizeof *t)' in new and 'free(t);' in unref, 'win32_posix.c thread_new / thread_unref changed'
    counted = posix.replace(new, new.replace('calloc(1, sizeof *t);', 'calloc(1, sizeof *t);\n    __atomic_add_fetch(&hthread_made, 1, '
                                                                          '__ATOMIC_RELEASE);'), 1)
    counted = counted.replace(unref, unref.replace('free(t);', 'free(t);\n        __atomic_add_fetch(&hthread_freed, 1, '
                                                                 '__ATOMIC_RELEASE);'), 1)
    counted = 'long hthread_made, hthread_freed;\n' + counted
    replay = (ROOT / 'gpu/vk/vk_replay.cpp').read_text(encoding='utf-8')
    pin = '\n'.join([block(replay, 'uint64_t replay_pin_mask() {'),
                     'thread_local int replay_pin_depth = 0;', 'thread_local DWORD_PTR replay_pin_prev = 0;',
                     block(replay, 'struct ReplayPin {') + ';'])
    texture = (ROOT / 'gpu/vk/vk_texture.cpp').read_text(encoding='utf-8')
    gather = block(texture, 'const uint8_t* guest_bytes(uint64_t gpu, uint64_t n, std::vector<uint8_t>& scratch) {')
    helpers = block(texture, 'void helper_thread_start() {') + '\n' if 'void helper_thread_start() {' in texture else ''
    fixture = THREADS.replace('@REPLAY@', pin).replace('@TEXTURE@', helpers + gather)
    with tempfile.TemporaryDirectory(prefix='reserved-core-threads-') as tmp:
        tmp = Path(tmp)
        (tmp / 'posix.c').write_text(counted, encoding='utf-8')
        (tmp / 'threads.cpp').write_text(fixture, encoding='utf-8')
        exe = tmp / 'threads'
        asan = subprocess.run([cxx, '-fsanitize=address', '-x', 'c++', '-', '-o', str(tmp / 'probe')], input='int main(){}',
                              capture_output=True, text=True).returncode == 0
        san = ['-fsanitize=address'] if asan else []   # (a record given back twice: a use after free)
        subprocess.run([cc, '-std=gnu11', '-D_GNU_SOURCE', '-w', '-g', *san, '-I', str(ROOT / 'host/posix'), '-c', str(tmp / 'posix.c'),
                        '-o', str(tmp / 'posix.o')], check=True)
        subprocess.run([cxx, '-std=c++20', '-D_GNU_SOURCE', '-Wall', '-Wextra', '-Wno-unused-function', '-g', *san, '-pthread',
                        '-I', str(ROOT / 'host/posix'), str(tmp / 'threads.cpp'), str(tmp / 'posix.o'), '-o', str(exe), '-ldl'],
                       check=True)
        env = {'PATH': '/usr/bin:/bin', 'ASAN_OPTIONS': 'detect_leaks=0'}
        subprocess.run([str(exe)], check=True, timeout=120, env=env)


if __name__ == '__main__':
    main()