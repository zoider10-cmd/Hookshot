/* (hookshot, 15/11) The game's name searches, natively.

   Arriving in Hyrule Castle, the game's OptimizeChangeBanc thread (it gets the next areas ready) ran in f_805aeea0 for 92 % of
   its samples in the long frames (hs2996). f_805aeea0 looks a key up in one of the game's sorted containers. Its two hot loops
   (the machine code's own sample addresses, hs3019) are binary searches over the container's elements by their name, with the
   game's strcmp inlined and unrolled eight bytes at a time:
     - at 0x805afbd4, the first element not before the name (lo w25, hi w26, mid w28; the latch at 0x805afbc0, out at 0x805afe30);
     - at 0x805b1d8c, the first element after it (lo w23, hi w3, mid w26, w21 the last step's side; out at 0x805b0200).
   Lifted, that strcmp keeps every guest register and flag in the context in memory, about fifteen host instructions a byte.
   Here an iteration runs on locals when it is the common one (an element of the expected class, a string key: w2 0, the key's
   type 8, two different strings) and the loop goes on natively until it ends; any other iteration (another class's virtual
   call, another key type, the same string object) is left to the lifted code, from that iteration's start, with every
   register as the lifted code would have it. The registers and the two stack slots the loop writes ([x29-16], [x29-8]) come
   out as the lifted loop leaves them. nx2/oot_patches.py splices the calls in at the loops' heads and exits.
   HOS_NAMES_NATIVE: 1 (default) native; 0 the lifted code; 2 each native iteration predicted, the lifted one run and the two
   compared where the loop goes next (registers, slots and flags). */
#include "hos.h"
#include <stdlib.h>
#include <string.h>

static inline uint64_t ld64(uint64_t a) { uint64_t v; memcpy(&v, GP(a), 8); return v; }
static inline uint32_t ld32(uint64_t a) { uint32_t v; memcpy(&v, GP(a), 4); return v; }
static inline uint32_t ld8(uint64_t a) { return *(const uint8_t *)GP(a); }

/* (hookshot, 15/11) The virtual cores' polls. The lifted loops poll at their backward branches (nx2/poll.py): every iteration
   on its way back to the latch, and the strcmp after each group of 8 equal bytes. A thread a better waiter asked for its
   virtual core (hos_thread.c, vc_kick) gives it up there. The native loops check c->poll at the same places: after each
   iteration done here (one done by the lifted code polls there itself) and between the strcmp's groups. The registers are
   in the loop's St meanwhile, and nothing else reads this thread's context while it waits for a core */
static inline void names_poll(Ctx *c) { A64_POLL(c); }

typedef struct {
    uint64_t x[32];
    uint32_t slot_type;   /* [x29-16] */
    uint64_t slot_key;    /* [x29-8] */
    int slots;            /* (an iteration done: the slots written) */
    int flags;            /* (n and v set by a compare of the loop's bounds) */
    int n, v;
} St;

/* The game's inlined strcmp (0x805afc64.. / 0x805b1e24..), from x8 = the element's key e and x9 = the name t: what it leaves
   in x8 (the result; the key's low word before any byte differs), x9-x14. 0: done (the latch); 1: no end in 32 MB (left to
   the lifted code) */
static int str_cmp(Ctx *c, St *s, uint64_t e, uint64_t t, uint32_t neg) {
    uint64_t x9 = t + 3, x10 = e + 3, x11 = 0x400000;
    uint32_t w8 = (uint32_t)e, w12 = 0, w13 = 0, w14 = 0;
    for (;;) {
        for (int64_t j = -3; j <= 4; j++) {
            w12 = ld8(x10 + (uint64_t)j);
            if (w12 == 0) w8 = 0;   /* (its handler: w8 = 0, then the same compare) */
            w13 = ld8(x9 + (uint64_t)j);
            w14 = w12 >= w13 ? 0u - neg : neg;
            if (w12 != w13) w8 = w14;
            if (w12 == 0 || w12 != w13) goto out;
        }
        x11 -= 8, x9 += 8, x10 += 8;
        if (x11 == 0) return 1;
        names_poll(c);   /* (the group before was 8 equal bytes: the lifted loop's back edge) */
    }
out:
    s->x[8] = w8, s->x[9] = x9, s->x[10] = x10, s->x[11] = x11, s->x[12] = w12, s->x[13] = w13, s->x[14] = w14;
    return 0;
}

static void bounds_flags(St *s, uint64_t a, uint64_t b) {   /* cmp wA, wB: n and v (signed less: n != v) */
    const uint32_t fa = (uint32_t)a, fb = (uint32_t)b, fr = fa - fb;
    s->n = (int)(fr >> 31 & 1), s->v = (int)(((fa ^ fb) & (fa ^ fr)) >> 31 & 1), s->flags = 1;
}

/* The element at mid of the container x20 and whether it is the common case: its key and the name in *key, *tgt. -1: not */
static int element(const uint64_t *x, uint64_t mid, uint64_t vt_a, uint64_t *n0, uint64_t *n1, uint64_t *n2, uint64_t *key,
                   uint64_t *tgt, uint32_t slot_type) {
    const uint64_t x20 = x[20];
    const uint64_t n9 = ld64(x20 + 8);
    *n0 = ld64(x20 + 16);
    *n2 = ld32(x20 + 24);
    uint64_t n8 = ld32(x20);
    n8 = (uint32_t)mid < (uint32_t)n8 ? mid : 0;
    *n1 = ld64(n9 + ((uint64_t)(uint32_t)n8 << 3));
    const uint64_t vt = ld64(ld64(*n0) + 120);
    if (vt != vt_a && vt != x[24]) return -1;   /* (another class: its virtual call) */
    if ((uint32_t)*n2 != 0) return -1;          /* (another key type) */
    *key = ld64(*n1);
    const uint32_t type = ld32(x[17]);
    if (slot_type != type || type != 8) return -1;
    *tgt = ld64(x[19] + 216);
    if (*key == *tgt) return -1;                /* (the same string object) */
    return 0;
}

/* One iteration of the first loop, from 0x805afbd4: -1 left to the lifted code (s unchanged), 0 back at its head, 1 out */
static int step_lower(Ctx *c, St *s) {
    uint64_t *x = s->x;
    const uint64_t mid = (uint32_t)(x[25] + x[26]) >> 1;
    uint64_t n0, n1, n2, key, tgt;
    if (element(x, mid, x[7], &n0, &n1, &n2, &key, &tgt, (uint32_t)x[22])) return -1;
    St t = *s;
    if (str_cmp(c, &t, key, tgt, (uint32_t)x[27])) return -1;
    *s = t;
    x[0] = n0, x[1] = n1, x[2] = n2, x[28] = mid;
    s->slot_type = (uint32_t)x[22], s->slot_key = key, s->slots = 1;
    const int32_t r = (int32_t)(uint32_t)x[8];   /* (0x805afbc0) */
    if (r < 0) x[25] = (uint32_t)(mid + 1);
    if (r >= 0) x[26] = (uint32_t)mid;
    bounds_flags(s, x[25], x[26]);
    return s->n == s->v ? 1 : 0;
}

/* One iteration of the second loop: from 0x805b1d8c (at_head) or from 0x805b1d98 (its first, without the bounds' check) */
static int step_upper(Ctx *c, St *s, int at_head) {
    uint64_t *x = s->x;
    if (at_head) {
        x[3] = (uint32_t)x[26];
        bounds_flags(s, x[23], x[26]);
        if (s->n == s->v) return 1;
    }
    const uint64_t mid = (uint32_t)(x[23] + x[3]) >> 1;
    uint64_t n0, n1, n2, key, tgt;
    if (element(x, mid, x[5], &n0, &n1, &n2, &key, &tgt, (uint32_t)x[7])) return -1;
    St t = *s;
    if (str_cmp(c, &t, key, tgt, (uint32_t)x[22])) return -1;
    *s = t;
    x[0] = n0, x[1] = n1, x[2] = n2, x[26] = mid;
    s->slot_type = (uint32_t)x[7], s->slot_key = key, s->slots = 1;
    const int32_t r = (int32_t)(uint32_t)x[8];   /* (0x805b1f64) */
    if (r <= 0) x[23] = (uint32_t)(mid + 1), x[21] = 1, x[26] = (uint32_t)x[3];
    else x[21] = 0;
    return 0;
}

static void load(St *s, const Ctx *c) {
    memcpy(s->x, c->x, sizeof s->x);
    s->slots = 0, s->flags = 0;
}
static void commit(Ctx *c, const St *s) {
    memcpy(c->x, s->x, sizeof s->x);
    if (s->slots) {
        memcpy(GP(s->x[29] - 16), &s->slot_type, 4);
        memcpy(GP(s->x[29] - 8), &s->slot_key, 8);
    }
    if (s->flags) c->n = s->n, c->v = s->v;
}

volatile int hos_names_checking = 0;   /* (HOS_NAMES_NATIVE=2: the exits' splices compare) */
static int names_mode(void) {
    static int m = -1;
    if (m < 0) {
        const char *e = getenv("HOS_NAMES_NATIVE");
        m = e ? atoi(e) : 1;
        hos_names_checking = m == 2;
        hos_log("names: the name searches of f_805aeea0 %s (HOS_NAMES_NATIVE=%d)",
                m == 0 ? "lifted" : m == 2 ? "lifted, each iteration checked against the native one" : "native", m);
    }
    return m;
}

static volatile long st_heads, st_steps, st_left;
static void count(long steps, int left) {
    __atomic_add_fetch(&st_steps, steps, __ATOMIC_RELAXED);
    if (left) __atomic_add_fetch(&st_left, 1, __ATOMIC_RELAXED);
    if (__atomic_add_fetch(&st_heads, 1, __ATOMIC_RELAXED) % 100000 == 0)
        hos_log("names: %ld searches entered: %ld iterations native in all, %ld left to the lifted code", (long)st_heads,
                (long)st_steps, (long)st_left);
}

/* HOS_NAMES_NATIVE=2: one prediction a loop and guest thread, checked where the lifted loop goes next */
enum { TO_HEAD = 0, TO_OUT = 1 };
typedef struct { int pending, to; St s; } Pred;
static __thread Pred pred[2];
static volatile long st_checked, st_differ;
static void check(Ctx *c, int which, int reached) {
    Pred *p = &pred[which];
    if (!p->pending) return;
    p->pending = 0;
    const St *s = &p->s;
    int bad_reg = -1;
    for (int i = 0; i < 31 && bad_reg < 0; i++)
        if (c->x[i] != s->x[i]) bad_reg = i;
    const int bad_slot = s->slots && (ld32(s->x[29] - 16) != s->slot_type || ld64(s->x[29] - 8) != s->slot_key);
    /* (the flags only out of the loop: at a head the lifted code has the last compare inside the iteration in them, read
       by nothing before the head's own compare) */
    const int bad_flags = reached == TO_OUT && s->flags && (c->n != s->n || c->v != s->v);
    const long k = __atomic_add_fetch(&st_checked, 1, __ATOMIC_RELAXED);
    if (bad_reg >= 0 || bad_slot || bad_flags || reached != p->to) {
        const long d = __atomic_add_fetch(&st_differ, 1, __ATOMIC_RELAXED);
        if (d <= 20)
            hos_log("names: loop %d, native != lifted (check %ld): went %s, predicted %s; x%d %#llx / %#llx; slots %s; flags %s",
                    which, k, reached ? "out" : "on", p->to ? "out" : "on", bad_reg,
                    (unsigned long long)(bad_reg >= 0 ? c->x[bad_reg] : 0), (unsigned long long)(bad_reg >= 0 ? s->x[bad_reg] : 0),
                    bad_slot ? "differ" : "same", bad_flags ? "differ" : "same");
    }
    if (k % 20000 == 0) hos_log("names: %ld iterations checked, %ld different", k, (long)st_differ);
}
static void predict(Ctx *c, int which, int at_head) {
    Pred *p = &pred[which];
    load(&p->s, c);
    const int r = which ? step_upper(c, &p->s, at_head) : step_lower(c, &p->s);
    p->pending = r >= 0, p->to = r == 1 ? TO_OUT : TO_HEAD;
}

/* (the first loop's head, 0x805afbd4) 1: the loop ended natively, out at 0x805afe30 */
int hos_names_lower(Ctx *c) {
    const int m = names_mode();
    if (m == 0) return 0;
    if (m == 2) {
        check(c, 0, TO_HEAD);
        predict(c, 0, 1);
        return 0;
    }
    St s;
    load(&s, c);
    long steps = 0;
    int r;
    while ((r = step_lower(c, &s)) >= 0) {
        names_poll(c);   /* (the iteration's way back to the latch, 0x805afbc0) */
        if (r) break;
        steps++;
    }
    if (r == 1) steps++;
    commit(c, &s);
    count(steps, r < 0);
    return r == 1;
}

/* (the second loop: at_head 1 at 0x805b1d8c, 0 at 0x805b1d98) 1: ended natively, out at 0x805b0200 */
int hos_names_upper(Ctx *c, int at_head) {
    const int m = names_mode();
    if (m == 0) return 0;
    if (m == 2) {
        if (at_head) check(c, 1, TO_HEAD);
        predict(c, 1, at_head);
        return 0;
    }
    St s;
    load(&s, c);
    long steps = 0;
    int r = step_upper(c, &s, at_head);
    for (;;) {
        if (r >= 0) names_poll(c);   /* (back to the latch, 0x805b1d80, or out from the head: both backward branches) */
        if (r != 0) break;
        steps++, r = step_upper(c, &s, 1);
    }
    commit(c, &s);
    count(steps, r < 0);
    return r == 1;
}

/* (the loops' exits, 0x805afe30 and 0x805b0200, HOS_NAMES_NATIVE=2) */
void hos_names_exit(Ctx *c, int which) {
    check(c, which, TO_OUT);
}
