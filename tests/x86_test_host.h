/* The host side of tests/vbytes_test.c and tests/vfpx_elem_test.c, on Windows and on Linux: guest memory at a fixed
   place, a clock, and whether this CPU runs the instruction set the file was built for (their tests build each driver
   for -march=native, x86-64-v3, x86-64-v2 and the baseline, and a CPU without AVX2, say, cannot run the v3 one). */
#ifndef LONGSHOT_X86_TEST_HOST_H
#define LONGSHOT_X86_TEST_HOST_H
#include <stddef.h>
#include <stdint.h>
#include <cpuid.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <sys/mman.h>
#include <time.h>
#endif

/* len bytes of zeroed read-write memory exactly at p: 1, else 0 */
static inline int test_map_at(void *p, size_t len) {
#ifdef _WIN32
    return VirtualAlloc(p, len, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE) == p;
#else
    void *m = mmap(p, len, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);   /* (p a hint: checked) */
    if (m == MAP_FAILED) return 0;
    if (m != p) {
        munmap(m, len);
        return 0;
    }
    return 1;
#endif
}

/* a monotonic clock in ns, for the time modes */
static inline double test_now_ns(void) {
#ifdef _WIN32
    LARGE_INTEGER f, t;
    QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&t);
    return (double)t.QuadPart * 1e9 / (double)f.QuadPart;
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec * 1e9 + (double)ts.tv_nsec;
#endif
}

/* 1 when this CPU has every extension the compiler was allowed to use here (its -march: x86-64-v2's SSSE3, SSE4.1/4.2
   and POPCNT; v3's AVX, AVX2, FMA, BMI1/2, F16C, MOVBE and LZCNT), else 0. The drivers then exit 3 at once, before any
   such instruction runs, and their tests report that build as skipped on this CPU */
static inline int test_cpu_runs_build(void) {
    unsigned a, b, c, d;
    if (!__get_cpuid(1, &a, &b, &c, &d)) return 0;
    const unsigned need1 = 0u
#ifdef __SSE3__
        | 1u << 0
#endif
#ifdef __SSSE3__
        | 1u << 9
#endif
#ifdef __FMA__
        | 1u << 12
#endif
#ifdef __SSE4_1__
        | 1u << 19
#endif
#ifdef __SSE4_2__
        | 1u << 20
#endif
#ifdef __MOVBE__
        | 1u << 22
#endif
#ifdef __POPCNT__
        | 1u << 23
#endif
#ifdef __AVX__
        | 1u << 27 | 1u << 28   /* (OSXSAVE with it: the system saves the wide registers) */
#endif
#ifdef __F16C__
        | 1u << 29
#endif
        ;
    if ((c & need1) != need1) return 0;
    const unsigned need7 = 0u
#ifdef __BMI__
        | 1u << 3
#endif
#ifdef __AVX2__
        | 1u << 5
#endif
#ifdef __BMI2__
        | 1u << 8
#endif
        ;
    if (need7 && (!__get_cpuid_count(7, 0, &a, &b, &c, &d) || (b & need7) != need7)) return 0;
#ifdef __LZCNT__
    if (!__get_cpuid(0x80000001u, &a, &b, &c, &d) || !(c >> 5 & 1)) return 0;
#endif
    return 1;
}
#endif
