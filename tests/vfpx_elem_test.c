/* tests/test_vfpx_elem.py's driver: FMUL Vd.4S, Vn.4S, Vm.S[i] as a64_lift.py lifts it now (a64_vfpx_mul32 over a
   broadcast of the element, vectorize_fpx's VFPX_MUL_ELEM) against the same guest word lifted as before (four scalar
   a64_fpx_mul32_fma32 calls, A64_NO_VFPX_ELEM=1). Built against the real a64.h and the generated a64_fpx.h, at the
   lifted code's FP flags. Each case starts both from one random Ctx (all 32 vector registers, FPCR and FPSR) and the
   whole Ctx must match after: the result lanes, every other register, and FPSR's cumulative flags.

   vfpx_elem_test random <n> <seed>   n random states per guest word (operand classes and states as fpx_sticky_test.c's)
   vfpx_elem_test sweep               every pair of a set of special values as a lane and as the element, under FZ on and
                                      off, flags all set / IXC only / none / UFC alone, the other lanes random
   Exit 0: no mismatch, and both the fast path and the per-lane fallback were taken (counted by the case's result).
   1: a mismatch. 3: this CPU cannot run the instruction set this file was built for. */
#include "a64.h"
#include <stdio.h>
#include <stdlib.h>
#include "x86_test_host.h"   /* (the time mode's clock, the CPU check: Windows and Linux) */
#include "vfpx_elem_lifted.h"

static uint64_t rs;
static uint64_t rnd(void) { rs ^= rs << 13; rs ^= rs >> 7; rs ^= rs << 17; return rs; }
static uint32_t r32(void) { return (uint32_t)(rnd() >> 16); }
static uint32_t rbelow(uint32_t n) { return (uint32_t)(((rnd() >> 32) * n) >> 32); }
static uint32_t mkf(uint32_t sign, int e, uint32_t frac) { return (sign << 31) | ((uint32_t)e << 23) | (frac & 0x7fffff); }

/* ---- operand classes and states: tests/fpx_sticky_test.c's, unchanged ---- */
static uint32_t sparse_frac(void) {
    switch (rbelow(4)) {
    case 0: return 0;
    case 1: return (uint32_t)1 << rbelow(23);
    case 2: return r32() & 0x7ff000;
    default: return r32() & 0x7fffff;
    }
}
static uint32_t any_operand(void) {
    const uint32_t s = r32() & 1;
    switch (rbelow(16)) {
    case 0: return s << 31;
    case 1: return mkf(s, 0, r32() | 1);
    case 2: return mkf(s, 0, rbelow(8) + 1);
    case 3: return mkf(s, 0, 0x7fffff - rbelow(8));
    case 4: return mkf(s, 1 + rbelow(3), sparse_frac());
    case 5: return mkf(s, 254 - rbelow(3), sparse_frac());
    case 6: return mkf(s, 255, 0);
    case 7: return mkf(s, 255, (r32() | 1) & 0x7fffff);
    case 8: return mkf(s, 255, 0x400000 | (r32() & 0x3fffff));
    case 9: case 10: return mkf(s, 120 + rbelow(15), sparse_frac());
    default: return mkf(s, 1 + rbelow(254), r32());
    }
}
static void tiny_pair(uint32_t *a, uint32_t *b) {   /* a product near the bottom of the normal range, or the overflow edge */
    const int target = (rbelow(8) == 0) ? 255 - (int)rbelow(3) : (int)rbelow(60) - 30;
    int ea = 1 + (int)rbelow(253);
    int eb = target - ea + 127;
    if (eb < 1 || eb > 254) { eb = 1 + (int)rbelow(254); ea = target - eb + 127; }
    if (ea < 1) ea = rbelow(4) ? 1 : 0;
    if (ea > 254) ea = 254;
    *a = mkf(r32() & 1, ea, rbelow(2) ? sparse_frac() : r32());
    *b = mkf(r32() & 1, eb, rbelow(2) ? sparse_frac() : r32());
}
static void gen_state(uint64_t *fpcr, uint64_t *fpsr) {
    uint64_t cr = 0, sr = 0;
    if (rbelow(2)) cr |= 1u << 24;
    if (rbelow(10) == 0) cr |= 1u << 25;
    if (rbelow(10) == 0) cr |= (uint64_t)rbelow(4) << 22;
    if (rbelow(40) == 0) cr |= r32() & 0x07ff9f07u;
    if (rbelow(16) == 0) cr |= 1u << rbelow(3);
    if (rbelow(200) == 0) cr |= RECOMP_FPX_INHIBIT;
    static const uint32_t bits[6] = {1, 2, 4, 8, 16, 128};
    for (int k = 0; k < 6; k++)
        if (k == 4 ? rbelow(10) != 0 : rbelow(3) != 0) sr |= bits[k];
    if (rbelow(8) == 0) sr |= 1u << 27;
    *fpcr = cr;
    *fpsr = sr;
}

/* ---- one check ---- */
static uint64_t checks, mismatches, flags_changed, flags_unchanged;
static void set_lane(Ctx *c, int reg, int lane, uint32_t v) { memcpy((uint8_t *)c->vreg[reg] + 4 * lane, &v, 4); }
static uint32_t get_lane(const Ctx *c, int reg, int lane) { uint32_t v; memcpy(&v, (const uint8_t *)c->vreg[reg] + 4 * lane, 4); return v; }

static void check(int k, const Ctx *start) {
    static Ctx a, b;   /* (static: a Ctx is large) */
    memcpy(&a, start, sizeof a);
    memcpy(&b, start, sizeof b);
    CASES[k].old(&a);
    CASES[k].now(&b);
    checks++;
    if (a.fpsr != start->fpsr) flags_changed++;
    else flags_unchanged++;
    if (memcmp(&a, &b, sizeof a) != 0) {
        if (mismatches++ < 12) {
            printf("MISMATCH %s: fpcr %#llx fpsr %#llx -> before %#llx, now %#llx\n", CASES[k].name,
                   (unsigned long long)start->fpcr, (unsigned long long)start->fpsr, (unsigned long long)a.fpsr,
                   (unsigned long long)b.fpsr);
            for (int l = 0; l < 4; l++)
                printf("  lane %d: n %08x m %08x -> before %08x now %08x\n", l, get_lane(start, CASES[k].rn, l),
                       get_lane(start, CASES[k].rm, CASES[k].index), get_lane(&a, CASES[k].rd, l), get_lane(&b, CASES[k].rd, l));
        }
    }
}

static void random_start(Ctx *c, int k) {
    for (int r = 0; r < 32; r++)
        for (int l = 0; l < 4; l++) set_lane(c, r, l, any_operand());
    /* the operands: often a product at the edges, the element shared by every lane */
    uint32_t m = any_operand();
    for (int l = 0; l < 4; l++) {
        uint32_t x, y;
        if (rbelow(3) == 0) { tiny_pair(&x, &y); if (l == 0) m = y; }
        else x = any_operand();
        set_lane(c, CASES[k].rn, l, x);
    }
    set_lane(c, CASES[k].rm, CASES[k].index, m);
    gen_state(&c->fpcr, &c->fpsr);
}

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    if (!test_cpu_runs_build()) {
        printf("skipped: this CPU lacks an extension this build may use\n");
        return 3;
    }
    static Ctx start;
    const int ncases = (int)(sizeof CASES / sizeof CASES[0]);
    if (!strcmp(argv[1], "random")) {
        const uint64_t n = argc > 2 ? strtoull(argv[2], 0, 10) : 1000000;
        rs = argc > 3 ? strtoull(argv[3], 0, 10) : 1;
        for (int k = 0; k < ncases; k++)
            for (uint64_t i = 0; i < n; i++) { memset(&start, 0, sizeof start); random_start(&start, k); check(k, &start); }
    } else if (!strcmp(argv[1], "sweep")) {
        rs = 7;
        static uint32_t special[64];
        int ns = 0;
        const uint32_t base[] = {0, 0x80000000u, 0x00000001u, 0x007fffffu, 0x00800000u, 0x00800001u, 0x3f800000u,
                                 0xbf800000u, 0x3f7fffffu, 0x40000000u, 0x7f7fffffu, 0xff7fffffu, 0x7f800000u, 0xff800000u,
                                 0x7fc00000u, 0xffc00001u, 0x7f800001u, 0x7fbfffffu, 0x1f800000u, 0x20000000u, 0x1fffffffu,
                                 0x5f800000u, 0x5f7fffffu, 0x60000000u, 0x0c000000u, 0x33800000u, 0x34000000u};
        for (unsigned i = 0; i < sizeof base / sizeof base[0]; i++) special[ns++] = base[i], special[ns++] = base[i] ^ 0x80000000u;
        const uint64_t srs[4] = {0x9f, 0x10, 0, 0x08};   /* every flag, IXC only, none, UFC alone */
        for (int k = 0; k < ncases; k++)
            for (int i = 0; i < ns; i++)
                for (int j = 0; j < ns; j++)
                    for (int fz = 0; fz < 2; fz++)
                        for (int s = 0; s < 4; s++) {
                            memset(&start, 0, sizeof start);
                            for (int r = 0; r < 32; r++)
                                for (int l = 0; l < 4; l++) set_lane(&start, r, l, any_operand());
                            for (int l = 0; l < 4; l++) set_lane(&start, CASES[k].rn, l, l == (i & 3) ? special[i] : any_operand());
                            set_lane(&start, CASES[k].rm, CASES[k].index, special[j]);
                            start.fpcr = fz ? (1u << 24) : 0;
                            start.fpsr = srs[s];
                            check(k, &start);
                        }
    } else if (!strcmp(argv[1], "time")) {
        /* ns a guest FMUL by element, as before and now, on typical play operands: normal numbers near 1 (the fast
           path's case), FZ set, IXC raised as the game's threads have it. Over 8 register states (a Ctx is large: 256
           of them missed the caches, both versions then took ~7 ns waiting for memory), copied fresh before each
           round. Only the shapes whose destination is neither source: one where Vd is Vn multiplies its own result
           again on every pass, which drifts out of the normal range into the exact body. Best of 5 rounds */
        const int reps = argc > 2 ? atoi(argv[2]) : 4000000;
        enum { NSTATE = 8 };
        rs = 3;
        static Ctx pristine[NSTATE], st[NSTATE];
        for (int s = 0; s < NSTATE; s++) {
            memset(&pristine[s], 0, sizeof pristine[s]);
            for (int r = 0; r < 32; r++)
                for (int l = 0; l < 4; l++) set_lane(&pristine[s], r, l, mkf(r32() & 1, 120 + rbelow(15), r32()));
            pristine[s].fpcr = argc > 3 ? strtoull(argv[3], 0, 16) : 1u << 24;   /* (FZ unless given) */
            pristine[s].fpsr = argc > 4 ? strtoull(argv[4], 0, 16) : 0x10;      /* (IXC unless given) */
        }
        printf("(a Ctx is %u bytes)\n", (unsigned)sizeof(Ctx));
        for (int k = 0; k < ncases; k++) {
            if (CASES[k].rd == CASES[k].rn || CASES[k].rd == CASES[k].rm) continue;
            double best[2] = {1e30, 1e30};
            for (int round = 0; round < 5; round++)
                for (int which = 0; which < 2; which++) {
                    memcpy(st, pristine, sizeof st);
                    const double t0 = test_now_ns();
                    for (int i = 0; i < reps; i++) (which ? CASES[k].now : CASES[k].old)(&st[i & (NSTATE - 1)]);
                    const double ns = (test_now_ns() - t0) / reps;
                    if (ns < best[which]) best[which] = ns;
                }
            printf("%-28s before %6.2f ns, now %6.2f ns (%.1fx)\n", CASES[k].name, best[0], best[1], best[0] / best[1]);
        }
        return 0;
    } else {
        return 2;
    }
    printf("vfpx elem %s: %llu checks over %d guest words, %llu mismatches; FPSR changed in %llu, unchanged in %llu\n",
           argv[1], (unsigned long long)checks, ncases, (unsigned long long)mismatches, (unsigned long long)flags_changed,
           (unsigned long long)flags_unchanged);
    if (mismatches) return 1;
    if (!flags_changed || !flags_unchanged) { printf("the cases never took one of the two routes\n"); return 4; }
    return 0;
}
