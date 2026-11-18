"""The saved steering rate in f_8263e8e0 does not decay on short steps (#312).

Apply the real patch pipeline to an authored update with the two short arithmetic
anchors, then compile and check its saved rate. Both signs, rate-limited and
target-limited turns, and the unchanged step >= 1 path are covered. No game files
or lifted function body are used. The floating-point stand-ins check ordinary
finite arithmetic and helper selection, not guest exception flags.

python -I -B tests/test_saved_turn_rate.py [--cc gcc]
"""
import argparse
import contextlib
import io
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import oot_patches  # noqa: E402

ANCHOR = """    {uint64_t _a=0,_b=0,_z,_v;memcpy(&_a,c->vreg[0],4);memcpy(&_b,c->vreg[1],4);_z=(_a^_b)&0x80000000ULL;
    _v=a64_fpx_mul32_fma32(c,_a,_b,_z);
    a64_vset64(c->vreg[1],_v);}
    {uint64_t _a=0,_b=0,_z,_v;memcpy(&_a,c->vreg[0],4);memcpy(&_b,c->vreg[8],4);_z=(_a^_b)&0x80000000ULL;
    _v=a64_fpx_mul32_fma32(c,_a,_b,_z);
    a64_vset64(c->vreg[0],_v);}
"""
HEAD = "void f_8263e8e0(Ctx *__restrict A64_NOESC c) {\n"
UPDATE = HEAD + ANCHOR + """    const float rate = as_float(c->vreg[2][0]);
    const float lower = as_float(c->vreg[1][0]);
    const float upper = as_float(c->vreg[0][0]);
    c->saved = rate < lower ? lower : (rate > upper ? upper : rate);
}
"""
UNRELATED = UPDATE.replace("f_8263e8e0", "f_90000000")
LIFTED = UPDATE + UNRELATED
FIXTURE = r'''#include <stdint.h>
#include <string.h>
#include <math.h>
#include <stdio.h>
#define A64_NOESC
typedef struct { uint64_t vreg[32][2]; float saved; int divides, multiplies; } Ctx;
static float as_float(uint64_t bits) {
    float f; uint32_t b = (uint32_t)bits; memcpy(&f, &b, 4); return f;
}
static uint64_t as_bits(float f) { uint32_t b; memcpy(&b, &f, 4); return b; }
static void a64_vset64(uint64_t *v, uint64_t bits) { v[0] = bits; v[1] = 0; }
static uint64_t a64_fpx_mul32_fma32(Ctx *c, uint64_t a, uint64_t b, uint64_t z) {
    (void)z; c->multiplies++; return as_bits(as_float(a) * as_float(b));
}
uint64_t a64_fpx_div32_div32(Ctx *c, uint64_t a, uint64_t b) {
    c->divides++; return as_bits(as_float(a) / as_float(b));
}
@UPDATE@
static int failures, checks;
static void check(float step, float rate, float applied, float expected, int corrected) {
    Ctx c = {0};
    c.vreg[0][0] = as_bits(fabsf(applied)); c.vreg[1][0] = as_bits(-step);
    c.vreg[8][0] = as_bits(step); c.vreg[2][0] = as_bits(rate);
    f_8263e8e0(&c);
    int same = fabsf(c.saved - expected) <= 1e-7f;
    if (!corrected) same = as_bits(c.saved) == as_bits(expected);
    int ok = same && c.divides == (corrected ? 2 : 0) && c.multiplies == (corrected ? 0 : 2);
    checks++;
    if (!ok) {
        printf("FAIL: saved rate step=%.9g rate=%.9g applied=%.9g saved=%.9g expected=%.9g div=%d mul=%d\n",
               step, rate, applied, c.saved, expected, c.divides, c.multiplies);
        failures++;
    }
}
static float old_saved(float step, float rate, float applied) {
    const float lower = fabsf(applied) * -step, upper = fabsf(applied) * step;
    return rate < lower ? lower : (rate > upper ? upper : rate);
}
int main(void) {
    const float steps[] = {0.25f, 0.42f, 0.5f, 0.66f, 1.0f, 2.0f};
    for (int k = 0; k < 6; k++) for (int sign = -1; sign <= 1; sign += 2) {
        const float step = steps[k], rate = sign * 0.02f;
        for (int target = 0; target < 2; target++) {
            const float applied = target ? sign * 0.002f : rate * step;
            const float expected = step < 1 ? (target ? sign * 0.002f / step : rate)
                                            : old_saved(step, rate, applied);
            check(step, rate, applied, expected, step < 1);
        }
        check(step, rate, 0.0f, step < 1 ? 0.0f : old_saved(step, rate, 0.0f), step < 1);
    }
    check(0.5f, 0.02f, -0.002f, 0.004f, 1);
    check(0.5f, -0.02f, 0.002f, -0.004f, 1);
    check(0.5f, 0.002f, 0.002f, 0.002f, 1);
    check(0.5f, -0.002f, -0.002f, -0.002f, 1);
    const uint32_t unchanged[] = {0, 0x80000000u, 0xbf000000u, 0xc0000000u,
                                 0x7f800000u, 0xff800000u, 0x7fc00000u, 0xffc00000u,
                                 0x3f800000u, 0x3f800001u, 0x40000000u};
    for (unsigned k = 0; k < sizeof unchanged / sizeof unchanged[0]; k++)
        for (int sign = -1; sign <= 1; sign += 2) {
            float step = as_float(unchanged[k]), rate = sign * 0.02f, applied = sign * 0.002f;
            check(step, rate, applied, old_saved(step, rate, applied), 0);
        }
    /* Carry each update's result into the next; the retained rate must not decay. */
    Ctx repeated = {0};
    repeated.saved = -0.02f;
    for (int k = 0; k < 100; k++) {
        repeated.vreg[0][0] = as_bits(fabsf(repeated.saved * 0.42f));
        repeated.vreg[1][0] = as_bits(-0.42f); repeated.vreg[8][0] = as_bits(0.42f);
        repeated.vreg[2][0] = as_bits(repeated.saved);
        f_8263e8e0(&repeated);
    }
    if (fabsf(repeated.saved + 0.02f) > 1e-7f) {
        puts("FAIL: saved rate decays over repeated short steps"); failures++;
    }
    Ctx other = {0};
    other.vreg[0][0] = as_bits(0.01f); other.vreg[1][0] = as_bits(-0.5f);
    other.vreg[8][0] = as_bits(0.5f); other.vreg[2][0] = as_bits(0.02f);
    f_90000000(&other);
    if (as_bits(other.saved) != as_bits(0.005f) || other.divides || other.multiplies != 2) {
        puts("FAIL: unrelated function changed"); failures++;
    }
    if (!failures) printf("PASS: saved turn rate (%d arithmetic checks and unrelated function)\n", checks);
    return failures != 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    patched, counts, _ = oot_patches.patch_file(LIFTED, "code_035.c")
    with tempfile.TemporaryDirectory(prefix="saved-turn-rate-") as directory:
        source, binary = Path(directory) / "fixture.c", Path(directory) / "fixture.exe"
        command = [args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)]
        source.write_text(FIXTURE.replace("@UPDATE@", patched), encoding="utf-8")
        subprocess.run(command, check=True)
        subprocess.run([str(binary)], check=True, timeout=30)
        source.write_text(FIXTURE.replace("@UPDATE@", LIFTED), encoding="utf-8")
        subprocess.run(command, check=True)
        native = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
        if native.returncode == 0 or "FAIL: saved rate step=0.25" not in native.stdout:
            raise SystemExit("FAIL: the original arithmetic did not fail the short-step check")
        print("PASS: original arithmetic compiles and fails the same short-step checks")
    assert counts["saved turn rate"] == 1
    assert UNRELATED in patched
    again, repeated, _ = oot_patches.patch_file(patched, "code_035.c")
    assert again == patched and repeated["saved turn rate"] == 1
    for altered in (LIFTED.replace("vreg[8],4)", "vreg[9],4)"),
                    LIFTED.replace(HEAD, HEAD + ANCHOR), UNRELATED):
        output, missing, _ = oot_patches.patch_file(altered, "code_035.c")
        assert output == altered and missing["saved turn rate"] == 0
        warning = io.StringIO()
        with contextlib.redirect_stdout(warning):
            oot_patches.report([Path("code_035.c")], [missing])
        assert "WARNING: the saved turn rate was found 0 times" in warning.getvalue()
    print("PASS: scoped, idempotent, and missing or ambiguous anchor warns without a partial fix")


if __name__ == "__main__":
    main()
