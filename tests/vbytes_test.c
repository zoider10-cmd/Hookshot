/* tests/test_vbytes.py's driver: TBL (one table register) and EXT as a64_lift.py lifts them now (a64_tbl1, A64_EXT16,
   A64_EXT8) against the same guest words lifted as before (byte loops, A64_NO_VBYTES=1). Each case starts both from one
   random Ctx and all 32 vector registers must match after.

   vbytes_test random <n> <seed>   n random states per guest word; index bytes biased to the edges
   vbytes_test time                ns per guest instruction, now and before
   Exit 0: no mismatch. 1: a mismatch. 3: this CPU cannot run the instruction set this file was built for. */
#include "a64.h"
#include <stdio.h>
#include <stdlib.h>
#include "x86_test_host.h"   /* (guest memory, the clock, the CPU check: Windows and Linux) */
#include "vbytes_lifted.h"

static uint64_t rs;
enum { kGuestLo = 0x10000, kGuestLen = 1 << 20 };   /* (guest memory the loads read: mapped at A64_PTR, main) */
static uint64_t rnd(void) { rs ^= rs << 13; rs ^= rs >> 7; rs ^= rs << 17; return rs; }
static uint8_t edge_byte(void) {
    static const uint8_t e[] = {0, 1, 7, 8, 14, 15, 16, 17, 31, 32, 0x6f, 0x70, 0x7f, 0x80, 0x8f, 0x90, 0xf0, 0xfe, 0xff};
    switch (rnd() % 4) {
    case 0: return e[rnd() % sizeof e];
    case 1: return (uint8_t)(rnd() % 16);
    default: return (uint8_t)rnd();
    }
}
static void fill(Ctx *c) {
    memset(c, 0, sizeof *c);
    for (int r = 0; r < 32; r++) {
        uint8_t b[16];
        for (int k = 0; k < 16; k++) b[k] = (rnd() & 1) ? edge_byte() : (uint8_t)rnd();
        memcpy(c->vreg[r], b, 16);
    }
    /* (the loads: guest addresses inside the mapped window, unaligned too; memory random per state) */
    for (int r = 0; r < 31; r++) c->x[r] = kGuestLo + 0x1000 + (rnd() % (kGuestLen - 0x2000));
    for (int k = 0; k < 64; k++) ((uint64_t *)A64_PTR(kGuestLo))[rnd() % (kGuestLen / 8)] = rnd();
}
static int ncases(void) { return (int)(sizeof CASES / sizeof CASES[0]); }

int main(int argc, char **argv) {
    if (!test_cpu_runs_build()) {
        printf("skipped: this CPU lacks an extension this build may use\n");
        return 3;
    }
    if (!test_map_at(A64_PTR(kGuestLo), kGuestLen)) {
        printf("no guest memory at %p\n", (void *)A64_PTR(kGuestLo));
        return 2;
    }
    for (uint64_t k = 0; k < kGuestLen / 8; k++) ((uint64_t *)A64_PTR(kGuestLo))[k] = k * 0x9e3779b97f4a7c15ULL;
    if (argc >= 2 && !strcmp(argv[1], "random")) {
        const long n = argc > 2 ? atol(argv[2]) : 1000000;
        rs = argc > 3 ? strtoull(argv[3], 0, 10) : 1;
        if (!rs) rs = 1;
        long bad = 0, checks = 0;
        for (int k = 0; k < ncases(); k++)
            for (long i = 0; i < n; i++) {
                static Ctx a, b;
                fill(&a);
                b = a;
                CASES[k].now(&a);
                CASES[k].old(&b);
                checks++;
                if (memcmp(a.vreg, b.vreg, sizeof a.vreg) || memcmp(a.x, b.x, sizeof a.x)) {
                    if (bad++ < 5) {
                        printf("MISMATCH %s:", CASES[k].name);
                        for (int r = 0; r < 32; r++)
                            if (memcmp(a.vreg[r], b.vreg[r], 16))
                                printf(" v%d now %016llx%016llx old %016llx%016llx", r, (unsigned long long)a.vreg[r][1],
                                       (unsigned long long)a.vreg[r][0], (unsigned long long)b.vreg[r][1],
                                       (unsigned long long)b.vreg[r][0]);
                        printf("\n");
                    }
                }
            }
        printf("%d guest words, %ld checks, %ld mismatches\n", ncases(), checks, bad);
        return bad ? 1 : 0;
    }
    if (argc >= 2 && !strcmp(argv[1], "time")) {
        static Ctx c;
        rs = 7;
        fill(&c);
        uint64_t x0[32];
        memcpy(x0, c.x, sizeof x0);
        const int iters = 2000000;
        const char *kinds[] = {"TBL", "EXT v", "EXT v"};
        for (int pass = 0; pass < 2; pass++) {
            double sum_now = 0, sum_old = 0;
            int nk = 0;
            for (int k = 0; k < ncases(); k++) {
                double best[2] = {1e30, 1e30};
                for (int w = 0; w < 2; w++)
                    for (int rep = 0; rep < 3; rep++) {
                        void (*fn)(Ctx *) = w ? CASES[k].old : CASES[k].now;
                        const double t0 = test_now_ns();
                        for (int i = 0; i < iters; i += 1000) {   /* (x reset each 1000: a post-index load moves its base) */
                            memcpy(c.x, x0, sizeof x0);
                            for (int j = 0; j < 1000; j++) fn(&c);
                        }
                        const double ns = (test_now_ns() - t0) / iters;
                        if (ns < best[w]) best[w] = ns;
                    }
                if (pass) printf("  %-34s now %5.2f ns  before %5.2f ns\n", CASES[k].name, best[0], best[1]);
                sum_now += best[0], sum_old += best[1], nk++;
            }
            if (pass) printf("  mean over %d words: now %.2f ns, before %.2f ns (%.1fx)\n", nk, sum_now / nk, sum_old / nk,
                             sum_old / sum_now);
        }
        (void)kinds;
        return 0;
    }
    printf("usage: vbytes_test random <n> <seed> | time\n");
    return 2;
}
