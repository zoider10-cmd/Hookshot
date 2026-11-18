/* (hookshot, 15/11) The game's zstd sequence loop, natively.

   Arriving in Hyrule Castle, the frames of 50 to 400 ms are the game's loading: its ParallelDecompThread spent 89 % of its
   samples in those frames in f_801102e0 (hs2996, all-thread samples), and ARes_Loading most of its own. f_801102e0 is the
   main module's zstd 1.4 sequence loop (ZSTD_decompressSequences_body, its decoding and its execution of each sequence),
   built with its state handed in and out:
       size_t f(ZSTD_DCtx *dctx, seqState_t *s, U32 *nbSeq, const BYTE **litPtr, BYTE *op, BYTE *oend)
   It decodes and executes sequences until nbSeq is 0, the bit stream overflows, or a sequence ends too close to oend, which
   it hands to ZSTD_execSequenceEnd (f_834ab4a0, lifted, called from here); then it writes the stream, the three FSE states
   and the repeat offsets back into *s, nbSeq and litPtr, and returns what it wrote (op - op at entry) or an error code.
   The dctx fields it reads: +0x7050 prefixStart, +0x7058 virtualStart, +0x7060 dictEnd, +0x7138 the literals' size.

   Lifted, each guest instruction is a step on the context in memory and each store marks its page; here the same steps run
   on locals and the pages written are marked once at the end. This is a transcription of its 352 instructions, not zstd's
   source: every load, store and branch is the game's, in its order (the copies with an offset under 8 read what they just
   wrote), and the label names are their guest addresses, so that guest memory and the state come out byte for byte as the
   lifted function leaves them. nx2/oot_patches.py puts the call at the head of the lifted f_801102e0.
   HOS_ZSTD_NATIVE: 1 (default) native; 0 the lifted code; 2 both, compared on every call (the lifted run's result kept, a
   difference logged): see zstd_compare. */
#include "hos.h"
#include <stdlib.h>
#include <string.h>

void f_834ab4a0(Ctx *A64_NOESC c);   /* (lifted) ZSTD_execSequenceEnd(op, oend, &seq, &litPtr, litLimit, prefixStart, virtualStart, dictEnd) */

static inline uint64_t ld64(uint64_t a) { uint64_t v; memcpy(&v, GP(a), 8); return v; }
static inline uint32_t ld32(uint64_t a) { uint32_t v; memcpy(&v, GP(a), 4); return v; }
static inline uint8_t ld8(uint64_t a) { return *(const uint8_t *)GP(a); }
/* (the output's stores: their highest end is kept, its pages marked once at the end) */
#define ST64(a, v) do { const uint64_t _a = (a), _v = (v); memcpy(GP(_a), &_v, 8); if (_a + 8 > whi) whi = _a + 8; } while (0)
#define ST32(a, v) do { const uint64_t _a = (a); const uint32_t _v = (uint32_t)(v); memcpy(GP(_a), &_v, 4); if (_a + 4 > whi) whi = _a + 4; } while (0)
#define ST8(a, v) do { const uint64_t _a = (a); *(uint8_t *)GP(_a) = (uint8_t)(v); if (_a + 1 > whi) whi = _a + 1; } while (0)

static void put64(uint64_t a, uint64_t v) { memcpy(GP(a), &v, 8); HOS_WRITTEN(GP(a), 8); }
static void put32(uint64_t a, uint32_t v) { memcpy(GP(a), &v, 4); HOS_WRITTEN(GP(a), 4); }
static inline uint64_t ror64(uint64_t v, unsigned n) { n &= 63; return n ? (v >> n) | (v << (64 - n)) : v; }

/* (hookshot, 15/11) The virtual cores' polls. The lifted f_801102e0 polls at every backward branch (nx2/poll.py): a thread
   that a better waiter asked for its virtual core (hos_thread.c, vc_kick) gives it up there. This loop is one block's
   sequences (110 KB written a call on average, ~155 us natively: hs3004), and without the polls a waiter asked for the core
   waited for the whole call. BACK(cond) is one of those branches here: when it is taken, the lifted code's check of c->poll;
   POLL() alone, a backward branch always taken (each copy loop's way back to its head among them). Before the core is given
   up, the output written so far is marked: the lifted code marks each store as it goes, this loop at its end otherwise, and
   the thread may now wait for a core in between */
static __attribute__((noinline, cold)) void give_core(Ctx *c, uint64_t op0, uint64_t whi) {
    if (whi > op0) HOS_WRITTEN(GP(op0), (size_t)(whi - op0));
#if defined(A64_POLL_CTX)
    a64_poll(c);
#else
    __atomic_store_n(&c->poll, 0, __ATOMIC_RELAXED);
    a64_poll_cur();
#endif
}
#if defined(A64_POLLING)
#define POLL() ((void)(__builtin_expect(__atomic_load_n(&c->poll, __ATOMIC_RELAXED) != 0, 0) ? (give_core(c, op0, whi), 0) : 0))
#else
#define POLL() ((void)0)
#endif
#define BACK(cond) ((cond) && (POLL(), 1))

/* ZSTD_execSequenceEnd, the lifted function, as the loop calls it (0x80110730): its seq_t on the guest stack */
static uint64_t sequence_end(Ctx *c, uint64_t op, uint64_t oend, uint64_t ll, uint64_t ml, uint64_t off, uint64_t pLit,
                             uint64_t litEnd, uint64_t prefixStart, uint64_t virtualStart, uint64_t dictEnd) {
    /* (x29 and x30 as the guest function leaves them: its own epilogue restores them; the callee keeps x19-x28 itself) */
    const uint64_t sp = c->x[31], frame = (sp - 0x180) & ~15ull, fp = c->x[29], lr = c->x[30];
    const uint64_t seq = frame + 0x18;
    put64(seq, ll), put64(seq + 8, ml), put64(seq + 16, off), put64(seq + 24, 0);
    c->x[31] = frame;
    c->x[0] = op, c->x[1] = oend, c->x[2] = seq, c->x[3] = pLit, c->x[4] = litEnd;
    c->x[5] = prefixStart, c->x[6] = virtualStart, c->x[7] = dictEnd;
    c->x[30] = 0x80110784ULL;
    f_834ab4a0(c);
    c->x[31] = sp, c->x[29] = fp, c->x[30] = lr;
    return c->x[0];
}

/* f_801102e0, natively: its result (x0); the context's x[0..30] are left as they were but for what the end call clobbers */
static uint64_t seq_native(Ctx *c) {
    const uint64_t dctx = c->x[0], S = c->x[1], pNb = c->x[2], pLit = c->x[3];
    uint64_t x4 = c->x[4];
    const uint64_t x5 = c->x[5], op0 = x4;
    uint64_t whi = op0;
    const uint64_t prefixStart = ld64(dctx + 0x7050), virtualStart = ld64(dctx + 0x7058), dictEnd = ld64(dctx + 0x7060);
    uint64_t x2 = ld32(pNb);
    uint64_t x3 = ld64(pLit);
    const uint64_t litEnd = x3 + ld64(dctx + 0x7138);
    uint64_t x10 = ld64(S + 0x18);
    uint64_t x11 = ld64(S + 0x10) - x10;
    uint64_t x9 = ld32(S + 8);
    uint64_t x8 = ld64(S) << (x9 & 63);
    const uint64_t LLt = ld64(S + 0x30);
    uint64_t x12 = ld64(S + 0x28);
    uint64_t x13 = ld64(S + 0x48);
    const uint64_t x15 = ld64(S + 0x50);
    uint64_t x14 = ld64(S + 0x38);
    const uint64_t x16 = ld64(S + 0x40);
    uint64_t x25 = ld64(S + 0x68), x23 = ld64(S + 0x58), x24 = ld64(S + 0x60);
    const uint64_t x30 = x5 - 13;
    uint64_t x0 = 0, x6 = 0, x7 = 0, x17 = 0, x18 = 0, x19 = 0, x20 = 0, x21 = 0, x22 = 0, x26 = 0, x27 = 0, x28 = 0, v = 0;
    uint64_t oMatchEnd = 0, ret = 0;
    int back = 0;   /* (0x80110614's copy returns to 0x801105a0 (0) or 0x8011069c (1): its x7) */
    int cflag;

L80110370:
    cflag = x9 >= 65;
    x26 = x9 - 65;
    x27 = x9 >> 3;
    x17 = ld64(LLt + (x12 << 3));
    cflag = !cflag ? (x11 >= 8) : 0;
    x18 = ld64(x15 + (x13 << 3));
    if (!cflag) goto L80110418;
    x11 -= x27;
    x9 &= 7;
L80110394:
    x8 = ld64(x10 + x11) << (x9 & 63);
L8011039c:
    x6 = ld64(x16 + (x14 << 3));
    if ((uint32_t)x2 == 0) goto L801107dc;
    x0 = (x17 >> 16) & 0xff;
    x7 = (x18 >> 16) & 0xff;
    x19 = (x6 >> 16) & 0xff;
    x26 = (uint32_t)(x0 + x7);
    x2 = (uint32_t)(x2 - 1);
    x26 = (uint32_t)(x26 + x19);
    x22 = 0 - x19;
    x20 = x17 >> 32;
    if (x19 == 0) goto L801103e4;
    {
        const int hi = x19 > 1;
        x27 = x6 >> 32;
        x9 += x19;
        x28 = x8 >> (x22 & 63);
        x8 <<= (x19 & 63);
        x22 = x27 + x28;
        if (hi) goto L80110450;
    }
L801103e4:
    if (x20 == 0) x22 += 1;
    if (x22 == 0) goto L80110410;
    {
        const int z = x22 == 2, hs = x22 >= 2;
        x27 = x23 - 1;
        x27 = z ? x25 : x27;
        x25 = hs ? x24 : x25;
        x27 = !hs ? x24 : x27;
        x24 = x23;
        x23 = x27 == 0 ? x27 + 1 : x27;
    }
L80110410:
    x22 = x23;
    goto L8011045c;
L80110418:
    if (!((x26 >> 63) & 1)) goto L801107dc;
    if (BACK(x11 == 0)) goto L8011039c;
    if (x27 > x11) x27 = x11;
    x11 -= x27;
    x9 -= x27 << 3;
    POLL();
    goto L80110394;
L80110434:
    if (!((x26 >> 63) & 1)) goto L801104a0;
    if (x11 == 0) goto L801104a0;
    if (x27 > x11) x27 = x11;
    x11 -= x27;
    x9 -= x27 << 3;
    goto L80110498;
L80110450:
    x25 = x24;
    x24 = x23;
    x23 = x22;
L8011045c:
    x21 = x18 >> 32;
    if (x7 != 0) {
        x27 = 0 - x7;
        x9 += x7;
        x27 = x8 >> (x27 & 63);
        x8 <<= (x7 & 63);
        x21 += x27;
    }
    if ((uint32_t)x26 < 31u) goto L801104a0;
    cflag = x9 >= 65;
    x26 = x9 - 65;
    x27 = x9 >> 3;
    cflag = !cflag ? (x11 >= 8) : 0;
    if (BACK(!cflag)) goto L80110434;
    x11 -= x27;
    x9 &= 7;
L80110498:
    x8 = ld64(x10 + x11) << (x9 & 63);
L801104a0:
    if (x0 != 0) {
        x27 = 0 - x0;
        x9 += x0;
        x27 = x8 >> (x27 & 63);
        x8 <<= (x0 & 63);
        x20 += x27;
    }
    x26 = (x17 >> 24) & 0xff;
    x12 = x17 & 0xffff;
    if (x26 != 0) {
        x27 = 0 - x26;
        x9 += x26;
        x27 = x8 >> (x27 & 63);
        x8 <<= (x26 & 63);
        x12 += x27;
    }
    x26 = (x18 >> 24) & 0xff;
    x13 = x18 & 0xffff;
    if (x26 != 0) {
        x27 = 0 - x26;
        x9 += x26;
        x27 = x8 >> (x27 & 63);
        x8 <<= (x26 & 63);
        x13 += x27;
    }
    x26 = (x6 >> 24) & 0xff;
    x14 = x6 & 0xffff;
    if (x26 != 0) {
        x27 = 0 - x26;
        x9 += x26;
        x27 = x8 >> (x27 & 63);
        x8 <<= (x26 & 63);
        x14 += x27;
    }
    /* 0x80110518: the sequence's execution */
    x26 = litEnd;
    x6 = x20 + x21;
    x18 = x5 - 8;
    x6 = x4 + x6;
    x27 = x3 + x20;
    x17 = x4 + x20;
    x0 = prefixStart;
    x7 = virtualStart;
    oMatchEnd = x6;
    if (x6 > x5 || x27 > x26 || x17 > x18) goto L80110720;
    for (;;) {   /* 0x80110548: the literals, 8 bytes at a time (8 at least) */
        const uint64_t old = x20;
        v = ld64(x3);
        x3 += 8;
        x20 -= 8;
        ST64(x4, v);
        x4 += 8;
        if (!(old > 8)) break;
        POLL();
    }
    x4 = x17 - x22;
    x3 = x27;
    x26 = x4 - x0;
    if (x4 < x0) goto L801105e8;
L80110568:
    if (x22 < 8) goto L801106cc;
    {
        v = ld64(x4);
        x4 += 8;
        const int hi = x6 > x30;
        ST64(x17, v);
        x17 += 8;
        if (hi) goto L801105a8;
    }
L80110580:
    {
        v = ld64(x4);
        x4 += 8;
        const uint64_t old = x21;
        x21 -= 16;
        if (old <= 16) goto L8011059c;
    }
    for (;;) {   /* 0x8011058c */
        ST64(x17, v);
        x17 += 8;
        v = ld64(x4);
        x4 += 8;
        const uint64_t old = x21;
        x21 -= 8;
        if (!(old > 8)) break;
        POLL();
    }
L8011059c:
    ST64(x17, v);
L801105a0:   /* (the lifted code polls on the branch to 0x80110370 and on the backward ones to here: this one poll stands for both) */
    x4 = oMatchEnd;
    POLL();
    goto L80110370;
L801105a8:
    if (x18 <= x17) goto L801105cc;
    x26 = x18 - x17;
    x27 = x4;
    x4 += x26;
    for (;;) {
        const uint64_t old = x26;
        x28 = ld64(x27);
        x27 += 8;
        x26 -= 8;
        ST64(x17, x28);
        x17 += 8;
        if (!(old > 8)) break;
        POLL();
    }
    x17 = x18;
L801105cc:
    if (x6 <= x17) goto L801105a0;
    x26 = x6 - x17;
    do {
        x27 = ld8(x4);
        x4 += 1;
        x26 -= 1;
        ST8(x17, x27);
        x17 += 1;
    } while (BACK(x26 != 0));
    goto L801105a0;
L801105e8:   /* the match starts in the dictionary (before prefixStart) */
    x19 = dictEnd;
    x27 = x17 - x7;
    x4 = x19 + x26;
    if (x22 > x27) { ret = (uint64_t)-0x14; goto L801107e4; }
    x26 = x4 + x21;
    if (x26 > x19) goto L8011068c;
    x28 = x21;
    back = 0;
    if (x21 == 0) goto L801105a0;
L80110614:   /* memmove(x17, x4, x28), then on at `back` */
    if (x17 >= x4) goto L80110674;
    x27 = x17;
    if (x28 >= 8) goto L8011063c;
    do {
        x26 = ld8(x4);
        x4 += 1;
        x28 -= 1;
        ST8(x27, x26);
        x27 += 1;
    } while (BACK(x28 != 0));
    goto back_to;
L8011063c:
    x20 = x28 & 7;
    if (x20 == 0) goto L80110660;
    x26 = ld64(x4);
    x28 &= ~7ull;
    x4 += x20;
    do {
        x20 -= 1;
        ST8(x27, x26);
        x27 += 1;
        x26 >>= 8;
    } while (BACK(x20 != 0));
L80110660:
    do {
        x26 = ld64(x4);
        x4 += 8;
        x28 -= 8;
        ST64(x27, x26);
        x27 += 8;
    } while (BACK(x28 != 0));
    goto back_to;
L80110674:
    x4 += x28;
    do {
        x4 -= 1;
        x26 = ld8(x4);
        x28 -= 1;
        ST8(x17 + x28, x26);
    } while (BACK(x28 != 0));
back_to:
    if (back == 0) goto L801105a0;
    goto L8011069c;
L8011068c:   /* the match runs from the dictionary into the prefix */
    x28 = x19 - x4;
    x19 = x19 - x4;
    back = 1;
    if (BACK(x28 != 0)) goto L80110614;
L8011069c:
    x17 += x19;
    x21 -= x19;
    {
        const int hs = x18 >= x17;
        x4 = x0;
        if (BACK(hs && x21 >= 3)) goto L80110568;
    }
    if (x21 == 0) goto L801105a0;
    do {
        x26 = ld8(x4);
        x4 += 1;
        x21 -= 1;
        ST8(x17, x26);
        x17 += 1;
    } while (BACK(x21 != 0));
    goto L801105a0;
L801106cc:   /* an offset under 8: the match overlaps what it writes */
    {
        const int ls = x6 <= x30;
        x26 = ld8(x4);
        x27 = 0x0414243441222110ULL;
        ST8(x17, x26);
        x17 += 8;
        x26 = ld8(x4 + 1);
        x28 = x22 << 3;
        ST8(x17 - 7, x26);
        x26 = ld8(x4 + 2);
        x27 = ror64(x27, (unsigned)(x28 & 63));
        ST8(x17 - 6, x26);
        x26 = ld8(x4 + 3);
        x28 = x27 & 0xf;
        ST8(x17 - 5, x26);
        x28 = ld32(x4 + x28);
        x4 = x4 + (x27 >> 60);
        ST32(x17 - 4, x28);
        if (BACK(ls)) goto L80110580;
        POLL();
        goto L801105a8;
    }
L80110720:   /* near oend, or past what the literals hold: ZSTD_execSequenceEnd */
    if (x6 > x5) { ret = (uint64_t)-0x46; goto L801107e4; }
    if (x27 > x26) { ret = (uint64_t)-0x14; goto L801107e4; }
    put64(pLit, x3);
    if (whi > op0) HOS_WRITTEN(GP(op0), (size_t)(whi - op0));   /* (what this loop wrote, before the lifted code goes on) */
    ret = sequence_end(c, x4, x5, x20, x21, x22, pLit, litEnd, prefixStart, virtualStart, dictEnd);
    x3 = ld64(pLit);
    if (ret <= (uint64_t)-0x78) goto L801105a0;
    goto L801107e4;
L801107dc:
    ret = x4 - op0;
L801107e4:
    if (whi > op0) HOS_WRITTEN(GP(op0), (size_t)(whi - op0));
    put32(S + 8, (uint32_t)x9);
    x8 = x9 >= 64 ? 0 : x8 >> (x9 & 63);
    put32(pNb, (uint32_t)x2);
    put64(pLit, x3);
    put64(S + 0x10, x10 + x11);
    put64(S, x8);
    put64(S + 0x28, x12);
    put64(S + 0x48, x13);
    put64(S + 0x38, x14);
    put64(S + 0x68, x25);
    put64(S + 0x58, x23);
    put64(S + 0x60, x24);
    return ret;
}

static int zstd_mode(void) {
    static int m = -1;
    if (m < 0) {
        const char *e = getenv("HOS_ZSTD_NATIVE");
        m = e ? atoi(e) : 1;
        hos_log("zstd: the sequence loop (f_801102e0) %s (HOS_ZSTD_NATIVE=%d)",
                m == 0 ? "lifted" : m == 2 ? "native and lifted, compared on every call" : "native", m);
    }
    return m;
}

static __thread int zstd_bypass;   /* (zstd_compare's own call of the lifted function) */

/* HOS_ZSTD_NATIVE=2: the native run on the state and output as they are, then all of it put back and the lifted function run;
   the two compared (result, *s, nbSeq, litPtr, the output from op to oend). The lifted run's result stays */
static void zstd_compare(Ctx *c, void (*self)(Ctx *)) {
    static volatile long calls, differ;
    const uint64_t S = c->x[1], pNb = c->x[2], pLit = c->x[3], op = c->x[4], oend = c->x[5];
    const size_t n = oend > op ? (size_t)(oend - op) : 0;
    uint64_t regs[32];
    memcpy(regs, c->x, sizeof regs);
    if (n > (16u << 20)) {   /* (an output that large is not a block: as lifted, uncompared) */
        zstd_bypass = 1, self(c), zstd_bypass = 0;
        return;
    }
    uint8_t s0[0x70], s1[0x70], *o0 = malloc(n ? n : 1), *o1 = malloc(n ? n : 1);
    uint32_t nb0, nb1;
    uint64_t lit0, lit1;
    memcpy(s0, GP(S), 0x70), nb0 = ld32(pNb), lit0 = ld64(pLit), memcpy(o0, GP(op), n);
    const uint64_t rn = seq_native(c);
    memcpy(s1, GP(S), 0x70), nb1 = ld32(pNb), lit1 = ld64(pLit), memcpy(o1, GP(op), n);
    memcpy(GP(S), s0, 0x70), put32(pNb, nb0), put64(pLit, lit0), memcpy(GP(op), o0, n);
    memcpy(c->x, regs, sizeof regs);
    zstd_bypass = 1, self(c), zstd_bypass = 0;
    const uint64_t rl = c->x[0];
    const int bad_s = memcmp(s1, GP(S), 0x70) != 0, bad_o = memcmp(o1, GP(op), n) != 0;
    const int bad = rn != rl || bad_s || nb1 != ld32(pNb) || lit1 != ld64(pLit) || bad_o;
    const long k = __atomic_add_fetch(&calls, 1, __ATOMIC_RELAXED);
    if (bad) {
        const long d = __atomic_add_fetch(&differ, 1, __ATOMIC_RELAXED);
        if (d <= 20) {
            size_t at = 0;
            if (bad_o)
                while (at < n && o1[at] == ((const uint8_t *)GP(op))[at]) at++;
            int sat = 0;
            if (bad_s)
                while (sat < 0x70 && s1[sat] == ((const uint8_t *)GP(S))[sat]) sat++;
            hos_log("zstd: native != lifted (call %ld): result %#llx / %#llx, nbSeq %u / %u, litPtr %+lld, state %s (byte %#x), "
                    "output %s (first at +%#zx of %#zx)", k, (unsigned long long)rn, (unsigned long long)rl, nb1, ld32(pNb),
                    (long long)(lit1 - ld64(pLit)), bad_s ? "differs" : "same", sat, bad_o ? "differs" : "same", at, n);
        }
    }
    if (k % 20000 == 0)
        hos_log("zstd: %ld sequence loops compared, %ld different", k, (long)differ);
    free(o0), free(o1);
}

/* HOS_ZSTD_TIME=1 (measuring): each call timed, natively or lifted, and every 20000 calls the time, the bytes written and their
   rate logged, for the two to be compared on the same loads */
static void zstd_timed(Ctx *c, void (*self)(Ctx *), int native) {
    static volatile long long ns_sum, bytes_sum, n;
    const uint64_t op = c->x[4];
    const int64_t t0 = hos_now_ns();
    if (native) {
        c->x[0] = seq_native(c);
    } else {
        zstd_bypass = 1, self(c), zstd_bypass = 0;
    }
    const int64_t dt = hos_now_ns() - t0;
    const uint64_t r = c->x[0];
    __atomic_add_fetch(&ns_sum, dt, __ATOMIC_RELAXED);
    if (r <= (uint64_t)-0x78) __atomic_add_fetch(&bytes_sum, (long long)r, __ATOMIC_RELAXED);
    (void)op;
    if (__atomic_add_fetch(&n, 1, __ATOMIC_RELAXED) % 20000 == 0) {
        const double ms = ns_sum / 1e6, mb = bytes_sum / 1048576.0;
        hos_log("zstd: %s sequence loops: %lld calls, %.1f ms, %.1f MB written, %.0f MB/s", native ? "native" : "lifted", n, ms, mb,
                ms > 0 ? mb / (ms / 1000.0) : 0.0);
    }
}

/* (the head of the lifted f_801102e0: nx2/oot_patches.py) 1 when the call was handled here */
int hos_zstd_seq(Ctx *c, void (*self)(Ctx *)) {
    if (zstd_bypass) return 0;
    static int timed = -1;
    if (timed < 0) timed = getenv("HOS_ZSTD_TIME") && atoi(getenv("HOS_ZSTD_TIME")) != 0;
    const int mode = zstd_mode();
    if (timed && mode != 2) {
        zstd_timed(c, self, mode != 0);
        return 1;
    }
    switch (mode) {
    case 0:
        return 0;
    case 2:
        zstd_compare(c, self);
        return 1;
    default:
        c->x[0] = seq_native(c);
        return 1;
    }
}
