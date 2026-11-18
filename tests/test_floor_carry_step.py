"""A moving floor's carry above 60 fps (nx2/oot_patches.py patch_floor_carry, host/oot_high_fps.h oot_floor_carry_slow).

A character standing on a moving floor (the Shadow Temple's barge, issue 439) is carried by the floor's velocity, which three
of the characters' update modules (f_80159dc0, f_8015d490, f_838baa40) add to the character's. Each first tests the physics
time object's 1/dt ([[...]]+0xc0, +0x28) against 100 and, above it (a frame under 10 ms: at 60 fps, time slowed below 0.6),
scales the floor's velocity by 0.1. Above 100 fps every frame is under 10 ms: Link and the enemies on the barge kept a tenth
of its velocity and slid to its back. The patch asks the host before the branch is taken: above a 60 fps cap, on a frame
under a 60 fps one, the test is 1/dt times the frame's step (the time object's, 0.5 at 120 fps) over 100, the game's test as
it would be at 60 fps.

An authored update for each module (the game's test and its branch, as the lift writes them, and stand-ins for the two paths)
goes through patch_file and is compiled with hos_oot_floor_carry_slow cut from host/oot_high_fps.c (guest memory, the time
objects and the switches as stand-ins):
- at 101, 120, 144, 240 and 1000 fps the floor's full velocity carries the character (a tenth before the fix);
- slowed time keeps the game's tenth wherever the game's own test at 60 fps would: at a cap of 60 (time at 0.3), and above
  60 at 0.5 and 0.3 of real time, while time at 0.7 above 60 carries in full, as at 60;
- a cap of 60, a frame slower than 60 fps, no time object and a NaN 1/dt take the game's own test;
- the unpatched updates compiled the same way fail the 120 fps check (the bug, shown without the fix);
- the patch is scoped to the three functions, a second run changes nothing, and a changed anchor is left alone with a warning.
No game files or lifted function body are used.

python -I -B tests/test_floor_carry_step.py [--cc gcc]
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
sys.path.insert(0, str(ROOT / "tests"))   # (python -I leaves the check's own folder off the path)
from srccut import block  # noqa: E402

# (the three modules: the game's test of the physics time object's 1/dt (+40) against 100, then its branch to the tenth)
MODULES = (("f_80159dc0", "L_8015a39c"), ("f_8015d490", "L_8015dad4"), ("f_838baa40", "L_838baf24"))
TEST = ("    { { uint64_t _v=recomp_load32(c,(c->x[8]+40ULL)); a64_vset64(c->vreg[0],_v); } }\n"
        "    c->x[8] = 0x42c80000ULL;\n"
        "    c->x[8] &= 0xFFFFFFFFULL;\n"
        "    { a64_vset64(c->vreg[1],0); memcpy(&c->vreg[1][0],&c->x[8],4); }\n"
        "    { if (!a64_fcmp32(c,c->vreg[0],c->vreg[1])) { c->n = 0; c->z = 0; c->c = 1; c->v = 1; } }\n")


def module(name, label):
    return ("void %s(Ctx *__restrict A64_NOESC c) {\n" % name + TEST
            + "if ((c->n == c->v) && !c->z) { goto %s; }\n" % label
            + "    c->carry = 1.0f;   /* (the game's: the floor's velocity as it is) */\n    return;\n"
            + "%s:;\n    c->carry = 0.1f;   /* (the game's: a tenth of it) */\n}\n" % label)


UPDATES = "".join(module(name, label) for name, label in MODULES)
UNRELATED = module("f_90159dc0", "L_8015a39c")
LIFTED = '#include "a64.h"\n' + UPDATES + UNRELATED

FIXTURE = r'''#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include "oot_high_fps.h"
#define A64_NOESC
typedef struct { uint64_t x[32]; uint64_t vreg[32][2]; uint8_t n, z, c, v; float carry; } Ctx;
static const uint64_t g_module_base = 0;
static void a64_vset64(uint64_t *v, uint64_t bits) { v[0] = bits; v[1] = 0; }
/* (as the lift's fcmp: n, z, c, v set; 0 for an unordered compare, whose flags the caller sets) */
static int a64_fcmp32(Ctx *c, const uint64_t *a, const uint64_t *b) {
    const float x = oot_bits_float((uint32_t)a[0]), y = oot_bits_float((uint32_t)b[0]);
    if (x != x || y != y) return 0;
    c->n = x < y, c->z = x == y, c->c = x >= y, c->v = 0;
    return 1;
}
/* (guest memory: the game's time object behind [0x84c9e890] (its step at +0x10), the physics time object at 0x3000 (1/dt
   at +40)) */
static uint8_t mem[0x4000];
static uint8_t *guest(uint64_t a) {
    if (a == 0x84c9e890ULL) return mem + 0x100;
    return a < sizeof mem ? mem + a : mem;
}
#define GP(a) ((void *)guest(a))
#define G64(a) (*(uint64_t *)GP(a))
static uint64_t recomp_load32(Ctx *c, uint64_t a) { uint32_t v; (void)c; memcpy(&v, guest(a), 4); return v; }
typedef long long LONG64;
#define InterlockedIncrement64(p) (++*(p))
static void hos_log(const char *f, ...) { (void)f; }
static int is_timed;
static int timed(void) { return is_timed; }
static int fps_log(void) { return 1; }
@HOST@
@UPDATE@
static int failures, checks;
typedef void (*Update)(Ctx *);
static const Update updates[3] = {f_80159dc0, f_8015d490, f_838baa40};
/* one frame: the frame's step (0: no time object), the physics' 1/dt, a cap above 60 or not: the carry each module chose */
static void frame(const char *what, float frame_step, float inv_dt, int timed_now, float expected) {
    is_timed = timed_now;
    G64(0x84c9e890ULL) = frame_step != 0.0f ? 0x1000 : 0;
    G64(0x1000) = 0x2000;
    const uint32_t f = oot_float_bits(frame_step), i = oot_float_bits(inv_dt);
    memcpy(mem + 0x2010, &f, 4);
    memcpy(mem + 0x3000 + 40, &i, 4);
    for (int m = 0; m < 3; m++) {
        Ctx c;
        memset(&c, 0, sizeof c);
        c.x[8] = 0x3000;
        updates[m](&c);
        checks++;
        if (fabsf(c.carry - expected) > 1e-6f) {
            printf("FAIL: %s: module %d carried %.1f of the floor's velocity (expected %.1f)\n", what, m, c.carry, expected);
            failures++;
        }
    }
}
int main(void) {
    /* (above 60: the frame's own time, 1/dt = 60 / step) */
    frame("120 fps", 0.5f, 120.0f, 1, 1.0f);
    frame("101 fps", 60.0f / 101.0f, 101.0f, 1, 1.0f);
    frame("144 fps", 60.0f / 144.0f, 144.0f, 1, 1.0f);
    frame("240 fps", 0.25f, 240.0f, 1, 1.0f);
    frame("1000 fps", 0.06f, 1000.0f, 1, 1.0f);
    frame("90 fps", 60.0f / 90.0f, 90.0f, 1, 1.0f);
    /* (slowed time: the physics' dt slowed, the frame's step not) */
    frame("120 fps, time at 0.5", 0.5f, 240.0f, 1, 0.1f);
    frame("120 fps, time at 0.3", 0.5f, 400.0f, 1, 0.1f);
    frame("120 fps, time at 0.7", 0.5f, 120.0f / 0.7f, 1, 1.0f);
    frame("240 fps, time at 0.5", 0.25f, 480.0f, 1, 0.1f);
    /* (the game's own test) */
    frame("a cap of 60", 1.0f, 60.0f, 0, 1.0f);
    frame("a cap of 60, time at 0.3", 1.0f, 200.0f, 0, 0.1f);
    frame("a cap of 60, its time object at 0.5", 0.5f, 120.0f, 0, 0.1f);
    frame("a frame slower than 60 fps, time at 0.5", 1.25f, 96.0f, 1, 1.0f);
    frame("a frame slower than 60 fps, time at 0.3", 1.25f, 160.0f, 1, 0.1f);
    frame("no time object", 0.0f, 120.0f, 1, 0.1f);
    frame("a NaN 1/dt", 0.5f, NAN, 1, 1.0f);
    if (!failures) printf("PASS: a moving floor's carry (%d checks)\n", checks);
    return failures != 0;
}
'''


def build_and_run(cc, update, host, directory):
    source, binary = Path(directory) / "fixture.c", Path(directory) / "fixture.exe"
    source.write_text(FIXTURE.replace("@HOST@", host).replace("@UPDATE@", update.replace('#include "a64.h"\n', "")),
                      encoding="utf-8")
    subprocess.run([cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-Wno-unused-const-variable",
                    "-I", str(ROOT / "host"), str(source), "-o", str(binary), "-lm"], check=True)
    return subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    patched, counts, _ = oot_patches.patch_file(LIFTED, "code_001.c")
    hooked = "hos_oot_floor_carry_slow(" in patched
    host = ""
    if hooked:   # (the host's function, as the game links it: cut from the source in the tree)
        text = (ROOT / "host" / "oot_high_fps.c").read_text(encoding="utf-8")
        host = block(text, "int hos_oot_floor_carry_slow(uint32_t inv_dt_bits, uint64_t slot) {")
    with tempfile.TemporaryDirectory(prefix="floor-carry-step-") as directory:
        result = build_and_run(args.cc, patched, host, directory)
        print(result.stdout, end="")
        if result.returncode != 0:
            raise SystemExit("FAIL: a moving floor's carry above 60 fps (the patch %s)" % ("is in" if hooked else "is missing"))
        native = build_and_run(args.cc, LIFTED, "", directory)
        if native.returncode == 0 or "FAIL: 120 fps:" not in native.stdout:
            raise SystemExit("FAIL: the unpatched updates did not fail the 120 fps check")
        print("PASS: the unpatched updates compile and fail the 120 fps check (a tenth of the floor's velocity)")
    assert counts["floor carry"] == 3
    assert UNRELATED in patched
    again, repeated, _ = oot_patches.patch_file(patched, "code_001.c")
    assert again == patched and repeated["floor carry"] == 3
    first = module(*MODULES[0])
    for altered, found in ((LIFTED.replace(first, first.replace("+40ULL", "+44ULL"), 1), 2),
                           (LIFTED.replace(first, first.replace("goto L_8015a39c", "goto L_8015a3a0"), 1), 2),
                           (LIFTED.replace(first, first.replace(TEST, TEST + TEST), 1), 2),
                           ('#include "a64.h"\n' + UNRELATED, 0)):
        output, missing, _ = oot_patches.patch_file(altered, "code_001.c")
        assert missing["floor carry"] == found, (missing["floor carry"], found)
        assert found or output == altered
        warning = io.StringIO()
        with contextlib.redirect_stdout(warning):
            oot_patches.report([Path("code_001.c")], [missing])
        assert "WARNING: a moving floor's carry was found at %d of 3 places" % found in warning.getvalue()
    print("PASS: scoped, idempotent, and a changed anchor is left alone with a warning")


if __name__ == "__main__":
    main()
