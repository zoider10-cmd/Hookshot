"""SCVTF / UCVTF (scalar, fixed-point) as nx2/insn.py translates them, against Unicorn.

The Advanced SIMD scalar form with fraction bits (`scvtf s29, s29, #1`, `scvtf s14, s14, #2`; Arm ARM, SCVTF (vector,
fixed-point), scalar) was in neither suyu's translator nor nx2/insn.py: a build names it as untranslated, and code
that ran one (a mod's code; the game's own code has none) would stop there (a trap).

For S and D, signed and unsigned, several fraction-bit counts and registers, with random register contents (and
integers chosen near the edges: 0, 1, -1, the most negative, the largest, values that round), in each of the four
FPCR rounding modes: the instruction runs in Unicorn (the "max" CPU), the C insn.emit gives runs in a small harness
with the lifter's register layout and suyu's own fixed-point helpers (cut from lift/suyu/arm64_to_c.h, as
a64_rtgen.py puts them in a64_suyu.h), and every general register, both halves of every vector register and the
FPSR's IXC bit must be the same afterwards. The half-precision immh (001x) is not taken. A broken variant (fraction
bits one off) must differ.

python -I -B tests/test_insn_fixed_convert.py [--cc gcc]
"""
import argparse
import os
import random
import re
import struct
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]
RUN_ALL_MODULES = ["unicorn"]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nx2"))
import kit  # noqa: E402,F401  (a64-kit on the path)
import insn  # noqa: E402

CODE = 0x10000
SUYU = os.path.join(ROOT, "third_party", "a64-kit", "lift", "suyu", "arm64_to_c.h")


def need(ok, what):
    if not ok:
        raise SystemExit("test_insn_fixed_convert: " + what)


def word(uns, dbl, fbits, rd, rn):
    imm = (128 if dbl else 64) - fbits   # immh:immb
    return 0x5F00E400 | (uns << 29) | (imm << 16) | (rn << 5) | rd


def cases():
    out = [("scvtf s29, s29, #1", 0x5F3FE7BD), ("scvtf s14, s14, #2", 0x5F3EE5CE)]
    for dbl, bits in ((0, (1, 2, 7, 16, 31, 32)), (1, (1, 3, 32, 52, 63, 64))):
        for uns in (0, 1):
            for k, f in enumerate(bits):
                rd, rn = ((0, 1), (5, 5), (31, 2), (17, 30), (3, 31), (9, 9))[k]
                out.append(("%s %s%d, %s%d, #%d" % ("ucvtf" if uns else "scvtf", "ds"[not dbl], rd, "ds"[not dbl], rn, f),
                            word(uns, dbl, f, rd, rn)))
    return out


def edge(rng):
    v = rng.choice([0, 1, 3, 0xFFFFFFFF, 0x80000000, 0x7FFFFFFF, 0x00FFFFFF, 0x01000001, 0x8000000000000000,
                    0x7FFFFFFFFFFFFFFF, 0xFFFFFFFFFFFFFFFF, 0x0020000000000001, rng.getrandbits(64), rng.getrandbits(64),
                    rng.getrandbits(32), rng.getrandbits(25)])
    return v & (2**64 - 1)


def unicorn_run(w, xs, vs, fpcr):
    import unicorn
    from unicorn import arm64_const as A
    uc = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
    uc.ctl_set_cpu_model(A.UC_CPU_ARM64_MAX)
    uc.mem_map(CODE, 0x1000)
    uc.mem_write(CODE, struct.pack("<I", w))
    uc.reg_write(A.UC_ARM64_REG_CPACR_EL1, 3 << 20)
    uc.reg_write(A.UC_ARM64_REG_FPCR, fpcr)
    uc.reg_write(A.UC_ARM64_REG_FPSR, 0)
    xreg = [getattr(A, "UC_ARM64_REG_X%d" % i) for i in range(29)] + [A.UC_ARM64_REG_FP, A.UC_ARM64_REG_LR]
    vreg = [getattr(A, "UC_ARM64_REG_V%d" % i) for i in range(32)]
    for r, v in zip(xreg, xs):
        uc.reg_write(r, v)
    for r, (lo, hi) in zip(vreg, vs):
        uc.reg_write(r, lo | (hi << 64))
    uc.emu_start(CODE, CODE + 4)
    got_v = [uc.reg_read(r) for r in vreg]
    return ([uc.reg_read(r) for r in xreg], [(v & (2**64 - 1), v >> 64) for v in got_v],
            uc.reg_read(A.UC_ARM64_REG_FPSR) & 16)


def helpers():
    """suyu's FP scan and fixed-point helpers (the R"FS( and R"FX( texts), as a64_suyu.h has them"""
    src = open(SUYU, encoding="utf-8").read()
    parts = [re.search(r'R"%s\((.*?)\)%s"' % (t, t), src, re.S) for t in ("FS", "FX")]
    need(all(parts), "suyu's FP helper texts not found in %s" % SUYU)
    return "\n".join(p.group(1) for p in parts)


HARNESS = r'''#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define RECOMP_INLINE inline __attribute__((always_inline))   /* (as suyu defines it for GCC / Clang) */
typedef struct { uint64_t x[32]; uint64_t vreg[32][2]; uint64_t fpcr, fpsr; } Ctx;
@HELPERS@
static const uint64_t X[][31] = {@X@};
static const uint64_t V[][64] = {@V@};
static const uint64_t F[] = {@F@};
@FUNCS@
static void (*const run[])(Ctx *) = {@NAMES@};
int main(void) {
    for (unsigned k = 0; k < sizeof run / sizeof run[0]; k++) {
        Ctx ctx = {{0}}, *c = &ctx;
        for (int i = 0; i < 31; i++) c->x[i] = X[k][i];
        for (int i = 0; i < 32; i++) c->vreg[i][0] = V[k][2 * i], c->vreg[i][1] = V[k][2 * i + 1];
        c->fpcr = F[k];
        run[k](c);
        for (int i = 0; i < 31; i++) printf("%016" PRIx64 " ", c->x[i]);
        for (int i = 0; i < 32; i++) printf("%016" PRIx64 " %016" PRIx64 " ", c->vreg[i][0], c->vreg[i][1]);
        printf("%" PRIu64 "\n", c->fpsr & 16);
    }
    return 0;
}
'''


def c_run(cc, tmp, name, texts, states):
    funcs = "\n".join("static void f%d(Ctx *c) { %s }" % (k, t) for k, t in enumerate(texts))
    src = (HARNESS.replace("@HELPERS@", helpers())
           .replace("@X@", ", ".join("{%s}" % ", ".join("0x%xULL" % v for v in xs) for xs, _, _ in states))
           .replace("@V@", ", ".join("{%s}" % ", ".join("0x%xULL, 0x%xULL" % p for p in vs) for _, vs, _ in states))
           .replace("@F@", ", ".join("0x%xULL" % f for _, _, f in states))
           .replace("@FUNCS@", funcs).replace("@NAMES@", ", ".join("f%d" % k for k in range(len(texts)))))
    c = os.path.join(tmp, name + ".c")
    exe = os.path.join(tmp, name + (".exe" if os.name == "nt" else ""))
    with open(c, "w", encoding="utf-8") as f:
        f.write(src)
    r = subprocess.run([cc, "-std=gnu11", "-O1", "-Wall", "-Werror", "-Wno-unused-variable", "-Wno-unused-function", c,
                        "-o", exe], capture_output=True, text=True)
    need(r.returncode == 0, "the emitted C does not compile (%s):\n%s" % (name, r.stderr[-3000:]))
    out = subprocess.run([exe], capture_output=True, text=True, check=True).stdout.splitlines()
    rows = []
    for line in out:
        t = line.split()
        nums = [int(v, 16) for v in t[:95]]
        rows.append((nums[:31], [(nums[31 + 2 * i], nums[32 + 2 * i]) for i in range(32)], int(t[95])))
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    rng = random.Random(0xF1BE5)
    forms = cases()
    texts, states, want, names = [], [], [], []
    for name, w in forms:
        text = insn.emit(w)
        need(text is not None, "nx2/insn.py has no C for %s (%08x)" % (name, w))
        for mode in range(4):
            for _ in range(3):
                xs = [rng.getrandbits(64) for _ in range(31)]
                vs = [(rng.getrandbits(64), rng.getrandbits(64)) for _ in range(32)]
                rn = (w >> 5) & 31
                vs[rn] = (edge(rng), vs[rn][1])
                fpcr = mode << 22
                texts.append(text)
                states.append((xs, vs, fpcr))
                names.append((name, w, mode))
                want.append(unicorn_run(w, xs, vs, fpcr))
    for name, w in (("ucvtf h0, h1, #1 (immh 001x)", 0x7F1FE420), ("scvtf v0.4s, v1.4s, #1 (vector: suyu's)", 0x4F3FE420),
                    ("fcvtzs s0, s1, #1 (not this form)", 0x5F3FFC20), ("sqshrn s0, d1, #1", 0x5F3F9420)):
        need(insn.emit(w) is None, "%s (%08x) is taken here" % (name, w))
    with tempfile.TemporaryDirectory(prefix="insn-fixed-") as tmp:
        got = c_run(a.cc, tmp, "real", texts, states)
        for (name, w, mode), g, wt in zip(names, got, want):
            need(g == wt, "%s (%08x), rounding mode %d: the C and Unicorn differ\n  C:       %r\n  Unicorn: %r" % (
                name, w, mode, [(i, v) for i, v in enumerate(g[1]) if v != wt[1][i]] + [("ixc", g[2])],
                [(i, v) for i, v in enumerate(wt[1]) if v != g[1][i]] + [("ixc", wt[2])]))
        broken = [re.sub(r", (\d+), (\d), c->fpcr", lambda m: ", %d, %s, c->fpcr" % (int(m.group(1)) + 1, m.group(2)), t)
                  for t in texts]
        bad = c_run(a.cc, tmp, "broken", broken, states)
        wrong = sum(g != wt for g, wt in zip(bad, want))
        need(wrong > len(want) // 2, "a broken variant (fraction bits one off) passes in %d of %d cases" % (len(want) - wrong, len(want)))
    print("PASS: SCVTF / UCVTF (scalar, fixed-point), S and D: nx2/insn.py's C is Unicorn's result (%d forms, 4 rounding "
          "modes, 3 states each)" % len(forms))


if __name__ == "__main__":
    main()
