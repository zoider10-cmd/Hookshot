"""(Longshot deb08f36, #1576) Vector code the kit's translator writes slowly, rewritten on the lifted text: three passes over one
instruction's C, each with its helpers appended to a64_fpx.h. The kit's files stay as they are (third_party/ is not
edited: CONTRIBUTING.md); install(), called from nx2/lift.py beside insn's and fastfp's, wraps the kit's functions:

  - a64_lift.vectorize_fpx: vectorize_bytes before it (TBL with a one-register table, EXT), VFPX_MUL_ELEM after it
    (FMUL by element);
  - a64_lift.op_text: vectorize_moves on its result (128-bit vector loads, DUP by element);
  - a64_lift.fpx_header: VBYTE_HEADER and VMOVE_HEADER after the kit's VSET_HEADER;
  - a64_lift.VFPX_MUL_HEADER: the kit's a64_vfpx_mul32 (KIT_MUL32, its text as the kit has it) replaced by NEW_MUL32, which
    splits it into a64_vfpx_mul32_v (both operands in registers) and adds a64_vfpx_mul32_elem. install() stops the
    lift when the kit's header no longer holds KIT_MUL32 exactly once: the kit changed, and NEW_MUL32 must follow it.

Switches, read at lift time (the lift key holds them): A64_NO_VBYTES=1, A64_NO_VFPX_ELEM=1, A64_NO_VMOVES=1 keep the
kit's text for that pass. The lift's new processes (nx2/chunks.py spawn_emit) run nx2/lift.py's module level again, so
they have the wrappers too. Tests: tests/test_vbytes.py, tests/test_vfpx_elem.py."""
import os
import re

import a64_lift

# (vbytes) TBL with a one-register table and EXT, which the emitter writes as byte loops (8 or 16 single steps through
# the stack, then a 16-byte reload that cannot be forwarded): one SSSE3 instruction each on x86 (PSHUFB; PALIGNR or two
# shifts). TBL: an index of 16 or more gives 0, which PSHUFB does when the index byte's top bit is set: the index plus
# 0x70, saturated, keeps 0-15 below 0x80 with the same low nibble and lifts 16-255 to 0x80 or more. Both sources are
# read before Vd is written, so Vd may be Vn or Vm. In the market's hot game code the loops took ~6 % of game-code time
# (TBL 2,995 sites, EXT 29,451). A64_NO_VBYTES=1 keeps them as they were.
VBYTE_TBL = re.compile(
    r"\{ uint8_t _t\[16\],_x\[(8|16)\],_r\[\1\]; memcpy\(_t\+0,c->vreg\[(\d+)\],16\); memcpy\(_x,c->vreg\[(\d+)\],\1\); "
    r"for\(int _i=0;_i<\1;_i\+\+\)\{ unsigned _k=_x\[_i\]; if\(_k<16U\) _r\[_i\]=_t\[_k\]; else _r\[_i\]=0; \} "
    r"c->vreg\[(\d+)\]\[0\]=0; c->vreg\[\4\]\[1\]=0; memcpy\(c->vreg\[\4\],_r,\1\); \}")
VBYTE_EXT = re.compile(
    r"\{ uint8_t _a\[(8|16)\],_b\[\1\],_r\[\1\]; memcpy\(_a,c->vreg\[(\d+)\],\1\); memcpy\(_b,c->vreg\[(\d+)\],\1\); "
    r"for\(int _i=0;_i<\1;_i\+\+\)\{ int _k=_i\+(\d+); _r\[_i\] = \(_k<\1\) \? _a\[_k\] : _b\[_k-\1\]; \} "
    r"c->vreg\[(\d+)\]\[0\]=0; c->vreg\[\5\]\[1\]=0; memcpy\(c->vreg\[\5\],_r,\1\); \}")


def vectorize_bytes(text):
    if "uint8_t _" not in text or os.environ.get("A64_NO_VBYTES"):
        return text
    text = VBYTE_TBL.sub(lambda m: "a64_tbl1(c->vreg[%s],c->vreg[%s],c->vreg[%s],%d);"
                         % (m.group(4), m.group(2), m.group(3), m.group(1) == "16"), text)
    return VBYTE_EXT.sub(lambda m: "A64_EXT%s(c->vreg[%s],c->vreg[%s],c->vreg[%s],%s);"
                         % (m.group(1), m.group(5), m.group(2), m.group(3), m.group(4)), text)


VBYTE_HEADER = r"""
/* ---- TBL (one table register) and EXT in one SSSE3 instruction (vectorize_bytes in nx2/fastvec.py) ---- */
#if defined(__SSSE3__)
#include <tmmintrin.h>
static inline __attribute__((always_inline)) void a64_tbl1(uint64_t *d, const uint64_t *t, const uint64_t *x, int q) {
    const __m128i tv = _mm_loadu_si128((const __m128i *)t);
    const __m128i xv = q ? _mm_loadu_si128((const __m128i *)x) : _mm_loadl_epi64((const __m128i *)x);
    __m128i r = _mm_shuffle_epi8(tv, _mm_adds_epu8(xv, _mm_set1_epi8(0x70)));
    if (!q) r = _mm_move_epi64(r);
    A64_OPAQUE(r);
    _mm_storeu_si128((__m128i *)d, r);
}
/* EXT 16 bytes: Vn's bytes from imm up, then Vm's (PALIGNR takes the high source first) */
#define A64_EXT16(d, n, m, imm) do { \
    const __m128i a64_e_n_ = _mm_loadu_si128((const __m128i *)(n)), a64_e_m_ = _mm_loadu_si128((const __m128i *)(m)); \
    __m128i a64_e_r_ = _mm_alignr_epi8(a64_e_m_, a64_e_n_, imm); \
    A64_OPAQUE(a64_e_r_); \
    _mm_storeu_si128((__m128i *)(d), a64_e_r_); } while (0)
#else
static inline void a64_tbl1(uint64_t *d, const uint64_t *t, const uint64_t *x, int q) {
    uint8_t tb[16], xb[16], r[16] = {0};
    memcpy(tb, t, 16); memcpy(xb, x, 16);
    for (int i = 0; i < (q ? 16 : 8); i++) r[i] = xb[i] < 16 ? tb[xb[i]] : 0;
    memcpy(d, r, 16);
}
#define A64_EXT16(d, n, m, imm) do { uint8_t a64_e_a_[32], a64_e_r_[16]; memcpy(a64_e_a_, (n), 16); \
    memcpy(a64_e_a_ + 16, (m), 16); memcpy(a64_e_r_, a64_e_a_ + (imm), 16); memcpy((d), a64_e_r_, 16); } while (0)
#endif
/* EXT 8 bytes: the low halves, Vn's from byte imm up then Vm's; the top half zeroed */
#define A64_EXT8(d, n, m, imm) do { uint64_t a64_e_n_ = (n)[0], a64_e_m_ = (m)[0]; \
    const uint64_t a64_e_r_ = (imm) ? (a64_e_n_ >> (8 * (imm))) | (a64_e_m_ << ((64 - 8 * (imm)) & 63)) : a64_e_n_; \
    a64_vset64((d), a64_e_r_); } while (0)
"""


# (fpx-by-element) FMUL Vd.4S, Vn.4S, Vm.S[i]: each lane is Vn's times the one element, the 4-lane FMUL of Vn by that
# element in every lane, lane for lane (the same multiply, operands and rounding; FPSR's flags are or-ed whatever the
# lanes' order). So the block becomes a64_vfpx_mul32 over a broadcast of the element, which keeps a lane only where the
# scalar fast path would and otherwise runs each lane's scalar helper as before. The element is read before anything is
# written, and a64_vfpx_mul32 reads both sources before it stores, so Vd may be Vn or Vm. The market's game code has
# 56,761 of these (four helper calls each); A64_NO_VFPX_ELEM=1 keeps them as they were.
VFPX_MUL_ELEM = re.compile(
    r"\{ uint32_t _a\[4\],_r\[4\],_m; memcpy\(_a,c->vreg\[(\d+)\],16\); "
    r"memcpy\(&_m,\(const uint8_t\*\)c->vreg\[(\d+)\]\+(\d+),4\); memcpy\(_r,c->vreg\[(\d+)\],16\);"
    r"for\(int _i=0;_i<4;\+\+_i\)\{uint64_t _n=_a\[_i\],_z0=_r\[_i\];\{uint64_t _a=_n,_b=_m,_z=_z0,_v;"
    r"_z=\(_a\^_b\)&0x80000000ULL;_v=a64_fpx_mul32_fma32\(c,_a,_b,_z\);_r\[_i\]=\(uint32_t\)_v;\}\}"
    r"c->vreg\[(\d+)\]\[0\]=0; c->vreg\[\5\]\[1\]=0; memcpy\(c->vreg\[\5\],_r,16\); \}")


def vfpx_mul_elem(m):
    rn, rm, off, rd_in, rd = m.groups()
    if rd_in != rd:   # (the block's destination read and written are one register; anything else is left alone)
        return m.group(0)
    return ("{ uint32_t _m; memcpy(&_m,(const uint8_t*)c->vreg[%s]+%s,4); a64_vfpx_mul32_elem(c,c->vreg[%s],c->vreg[%s],_m); }"
            % (rm, off, rd, rn))


# (vmoves) two moves the compiler leaves slow, on the final text (after widen_vstores):
# - a 128-bit vector load (LDR Q, LDP Q, LD1 one register) as recomp_ldp64 into the register's two halves: two 8-byte
#   stores, and the next 16-byte read of the register cannot be forwarded from them (a stall of ~10 cycles). Now one
#   16-byte load and one 16-byte store (a64_vld16; guest memory is read the same way, recomp_load64 is a plain copy).
# - DUP Vd, Vn.T[i] as a loop through the stack and a 16-byte reload: one broadcast (a64_vdup). The element is read
#   before Vd is written, so Vd may be Vn. 139,843 and 26,529 sites. A64_NO_VMOVES=1 keeps them as before.
VMOVE_LDQ = re.compile(r"recomp_ldp64\(c,([^;]*?),&c->vreg\[(\d+)\]\[0\],&c->vreg\[\2\]\[1\]\);")
VMOVE_DUP = re.compile(
    r"\{ uint8_t _s\[16\]; memcpy\(_s,c->vreg\[(\d+)\],16\); uint64_t _e=0; memcpy\(&_e,_s\+(\d+),(1|2|4|8)\); "
    r"uint8_t _d\[16\]; memset\(_d,0,16\); for\(int _i=0;_i<(\d+);_i\+\+\) memcpy\(_d\+_i\*\3,&_e,\3\); "
    r"a64_vst16\(c->vreg\[(\d+)\],_d\); \}")


def vectorize_moves(text):
    if "c->vreg" not in text or os.environ.get("A64_NO_VMOVES"):
        return text
    text = VMOVE_LDQ.sub(lambda m: "a64_vld16(c->vreg[%s],%s);" % (m.group(2), m.group(1)), text)

    def dup(m):
        s, off, w, n, d = m.groups()
        if int(w) * int(n) not in (8, 16):
            return m.group(0)
        return "a64_vdup(c->vreg[%s],c->vreg[%s],%s,%s,%d);" % (d, s, off, w, int(w) * int(n) == 16)
    return VMOVE_DUP.sub(dup, text)


VMOVE_HEADER = r"""
/* ---- whole-register vector load and DUP by element (vectorize_moves in nx2/fastvec.py) ---- */
#if RECOMP_FPX_HOST == 2
static inline __attribute__((always_inline)) void a64_vld16(uint64_t *d, uint64_t a) {
    __m128i x = _mm_loadu_si128((const __m128i *)A64_PTR(a));
    A64_OPAQUE(x);
    _mm_storeu_si128((__m128i *)d, x);
}
static inline __attribute__((always_inline)) void a64_vdup(uint64_t *d, const uint64_t *s, int off, int w, int q) {
    uint64_t e = 0;
    memcpy(&e, (const uint8_t *)s + off, w);
    __m128i r = w == 1 ? _mm_set1_epi8((char)e) : w == 2 ? _mm_set1_epi16((short)e) : w == 4 ? _mm_set1_epi32((int)e)
                                                                                           : _mm_set1_epi64x((long long)e);
    if (!q) r = _mm_move_epi64(r);
    A64_OPAQUE(r);
    _mm_storeu_si128((__m128i *)d, r);
}
#else
static inline void a64_vld16(uint64_t *d, uint64_t a) { memcpy(d, A64_PTR(a), 16); }
static inline void a64_vdup(uint64_t *d, const uint64_t *s, int off, int w, int q) {
    uint8_t r[16] = {0};
    uint64_t e = 0;
    memcpy(&e, (const uint8_t *)s + off, w);
    for (int i = 0; i < (q ? 16 : 8) / w; i++) memcpy(r + i * w, &e, w);
    memcpy(d, r, 16);
}
#endif
"""


# the kit's a64_vfpx_mul32 as VFPX_MUL_HEADER has it (third_party/a64-kit/lift/a64_lift.py): what install() replaces
KIT_MUL32 = r"""static inline __attribute__((always_inline)) void a64_vfpx_mul32(Ctx *c, uint64_t *d, const uint64_t *n, const uint64_t *m, int k) {
    (void)k;
#if RECOMP_FPX_HOST == 2
    if (RECOMP_LIKELY(RECOMP_FPX_OPEN(c))) {
        const __m128i a = _mm_loadu_si128((const __m128i *)n), b = _mm_loadu_si128((const __m128i *)m);
        const __m128i t = _mm_castps_si128(_mm_mul_ps(_mm_castsi128_ps(a), _mm_castsi128_ps(b)));
        /* kept: big, or a finite product of a zero (RECOMP_FPX_KEEP32); under FZ no subnormal operand */
        const __m128i keep = _mm_or_si128(a64_v_big(t), _mm_andnot_si128(a64_v_nonfin(t), _mm_or_si128(a64_v_zero(a), a64_v_zero(b))));
        __m128i bad = _mm_andnot_si128(keep, _mm_set1_epi32(-1)), r = t;
        if (RECOMP_FPX_FZ(c)) {
            bad = _mm_or_si128(bad, _mm_or_si128(a64_v_subn(a), a64_v_subn(b)));
            if (c->fpsr & 8u) {   /* (flags raised: a tiny product is a zero of its sign; the smallest normal: exact) */
                const __m128i abs_t = a64_v_abs(t), minn = _mm_set1_epi32(0x00800000);
                const __m128i tiny = _mm_cmplt_epi32(abs_t, minn);
                const __m128i fin = _mm_andnot_si128(a64_v_nonfin(t), _mm_set1_epi32(-1));
                bad = _mm_andnot_si128(_mm_and_si128(tiny, fin), bad);   /* (still bad if a subnormal operand) */
                bad = _mm_or_si128(bad, _mm_or_si128(a64_v_subn(a), a64_v_subn(b)));
                bad = _mm_or_si128(bad, _mm_cmpeq_epi32(abs_t, minn));
                r = _mm_or_si128(_mm_andnot_si128(tiny, t), _mm_and_si128(tiny, _mm_and_si128(t, _mm_set1_epi32((int)0x80000000u))));
            }
        }
        if (RECOMP_LIKELY(!_mm_movemask_epi8(bad)) || !_mm_movemask_epi8(_mm_andnot_si128(a64_v_ovf(c, a, b, t), bad))) {
            _mm_storeu_si128((__m128i *)d, r);
            return;
        }
    }
#endif
    a64_vfpx_mul32_lanes(c, d, n, m);
}
"""

# and what it becomes: the multiply itself with both operands in registers, a64_vfpx_mul32 over it, and the by-element form
NEW_MUL32 = r"""#if RECOMP_FPX_HOST == 2
/* (fpx-by-element) the 4-lane multiply of a by b, both in registers: stored into d and 1 when every lane is kept, else 0
   (nothing stored: the caller runs the lanes' scalar helpers). a64_vfpx_mul32 below, and a64_vfpx_mul32_elem with b the
   element broadcast in a register (made from two 8-byte stores in memory and read back as one 16-byte load, the store
   could not be forwarded: ~10 cycles a guest FMUL by element, which ate the gain) */
static inline __attribute__((always_inline)) int a64_vfpx_mul32_v(Ctx *c, uint64_t *d, const __m128i a, const __m128i b) {
    if (RECOMP_LIKELY(RECOMP_FPX_OPEN(c))) {
        const __m128i t = _mm_castps_si128(_mm_mul_ps(_mm_castsi128_ps(a), _mm_castsi128_ps(b)));
        /* kept: big, or a finite product of a zero (RECOMP_FPX_KEEP32); under FZ no subnormal operand */
        const __m128i keep = _mm_or_si128(a64_v_big(t), _mm_andnot_si128(a64_v_nonfin(t), _mm_or_si128(a64_v_zero(a), a64_v_zero(b))));
        __m128i bad = _mm_andnot_si128(keep, _mm_set1_epi32(-1)), r = t;
        if (RECOMP_FPX_FZ(c)) {
            bad = _mm_or_si128(bad, _mm_or_si128(a64_v_subn(a), a64_v_subn(b)));
            if (c->fpsr & 8u) {   /* (flags raised: a tiny product is a zero of its sign; the smallest normal: exact) */
                const __m128i abs_t = a64_v_abs(t), minn = _mm_set1_epi32(0x00800000);
                const __m128i tiny = _mm_cmplt_epi32(abs_t, minn);
                const __m128i fin = _mm_andnot_si128(a64_v_nonfin(t), _mm_set1_epi32(-1));
                bad = _mm_andnot_si128(_mm_and_si128(tiny, fin), bad);   /* (still bad if a subnormal operand) */
                bad = _mm_or_si128(bad, _mm_or_si128(a64_v_subn(a), a64_v_subn(b)));
                bad = _mm_or_si128(bad, _mm_cmpeq_epi32(abs_t, minn));
                r = _mm_or_si128(_mm_andnot_si128(tiny, t), _mm_and_si128(tiny, _mm_and_si128(t, _mm_set1_epi32((int)0x80000000u))));
            }
        }
        if (RECOMP_LIKELY(!_mm_movemask_epi8(bad)) || !_mm_movemask_epi8(_mm_andnot_si128(a64_v_ovf(c, a, b, t), bad))) {
            _mm_storeu_si128((__m128i *)d, r);
            return 1;
        }
    }
    return 0;
}
#endif
static inline __attribute__((always_inline)) void a64_vfpx_mul32(Ctx *c, uint64_t *d, const uint64_t *n, const uint64_t *m, int k) {
    (void)k;
#if RECOMP_FPX_HOST == 2
    if (a64_vfpx_mul32_v(c, d, _mm_loadu_si128((const __m128i *)n), _mm_loadu_si128((const __m128i *)m))) return;
#endif
    a64_vfpx_mul32_lanes(c, d, n, m);
}
/* (fpx-by-element) FMUL Vd.4S, Vn.4S, Vm.S[i]: each lane of Vn times the element m (vectorize_fpx's VFPX_MUL_ELEM) */
static __attribute__((noinline, cold)) void a64_vfpx_mul32_elem_lanes(Ctx *c, uint64_t *d, const uint64_t *n, uint32_t m) {
    uint32_t b[4] = {m, m, m, m};
    uint64_t mb[2];
    memcpy(mb, b, 16);
    a64_vfpx_mul32_lanes(c, d, n, mb); }
static inline __attribute__((always_inline)) void a64_vfpx_mul32_elem(Ctx *c, uint64_t *d, const uint64_t *n, uint32_t m) {
#if RECOMP_FPX_HOST == 2
    if (a64_vfpx_mul32_v(c, d, _mm_loadu_si128((const __m128i *)n), _mm_set1_epi32((int)m))) return;
#endif
    a64_vfpx_mul32_elem_lanes(c, d, n, m);
}
"""


_installed = False


def install():
    """the wrappers above around the kit's vectorize_fpx, op_text and fpx_header, and its VFPX_MUL_HEADER's multiply. Once"""
    global _installed
    if _installed:
        return
    _installed = True
    if a64_lift.VFPX_MUL_HEADER.count(KIT_MUL32) != 1:
        raise SystemExit("fastvec: the kit's VFPX_MUL_HEADER no longer holds a64_vfpx_mul32 as nx2/fastvec.py's KIT_MUL32 has it: "
                         "the kit changed; bring KIT_MUL32 and NEW_MUL32 in line with it")
    a64_lift.VFPX_MUL_HEADER = a64_lift.VFPX_MUL_HEADER.replace(KIT_MUL32, NEW_MUL32)
    base_vfpx, base_op_text, base_header = a64_lift.vectorize_fpx, a64_lift.op_text, a64_lift.fpx_header

    def vectorize_fpx(text):
        text = base_vfpx(vectorize_bytes(text))
        if os.environ.get("A64_NO_VFPX") or os.environ.get("A64_NO_VFPX_ELEM"):
            return text
        return VFPX_MUL_ELEM.sub(vfpx_mul_elem, text)

    def op_text(text, fpx):
        return vectorize_moves(base_op_text(text, fpx))

    def fpx_header(used):
        text = base_header(used)
        at = a64_lift.VSET_HEADER + "\n"
        if text.count(at) != 1:
            raise SystemExit("fastvec: a64_fpx.h no longer holds the kit's VSET_HEADER once: where its helpers go")
        return text.replace(at, at + VBYTE_HEADER + "\n" + VMOVE_HEADER + "\n")

    a64_lift.vectorize_fpx, a64_lift.op_text, a64_lift.fpx_header = vectorize_fpx, op_text, fpx_header
