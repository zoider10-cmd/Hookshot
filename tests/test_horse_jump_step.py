"""A horse's jump blend above 60 fps (nx2/oot_patches.py patch_horse_jump, host/oot_high_fps.h oot_horse_whole_step).

While a horse gets ready to jump an obstacle, its jump state machine (f_82c59eb0) sets each frame the blend frames into its
JumpReady animation. With a step under 1 (slow motion at 60 fps) it takes them from last frame's plus the step. Above 60 fps
every step is under 1, so the blend frames grew each frame, the blend into the jump hardly started, and Epona galloped through
the fence while her body went over it. The patch puts the host's whole-frame test before the game's "step < 1" branch: a step
that is the whole frame's (the time object's step) skips the slow-motion branch.

An authored update with the two anchor lines (the step test and its branch) and a stand-in for the slow-motion branch goes
through patch_file, is compiled with hos_oot_horse_whole_step cut from host/oot_high_fps.c (guest memory, the time object and
the switches as stand-ins) and run frame by frame, carrying the blend frames from one frame to the next as the game does:
- at 70, 120, 144 and 240 fps, with jitter between the horse's step and the frame's, the blend frames stay the game's own (they
  grew by the step each frame before the fix);
- slow motion above 60 fps (the horse's step under the frame's), slow motion at a cap of 60, a cap of 60, a frame slower than
  60 fps and a time object with no step all take the game's own test;
- the unpatched update compiled the same way fails the 120 fps check (the bug, shown without the fix);
- the patch is scoped to its function, a second run changes nothing, and a changed anchor is left alone with a warning.
No game files or lifted function body are used.

python -I -B tests/test_horse_jump_step.py [--cc gcc]
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

HEAD = "void f_82c59eb0(Ctx *__restrict A64_NOESC c) {\n"
# (the step test as the lift writes it, its flag setting cut short to the stand-in's; then its branch past the slow-motion one)
ANCHOR = ("    a64_vset64(c->vreg[9],0x3f800000ULL);\n"
          "    { if (!a64_fcmp32(c,c->vreg[10],c->vreg[9])) { c->n = 0; } }\n"
          "if (!c->n) { goto L_82c5ae48; }\n")
UPDATE = ('#include "a64.h"\n' + HEAD + "    c->slow = 0;\n" + ANCHOR
          + "    c->slow = 1;   /* (the game's branch for a step under 1: last frame's blend frames plus the step) */\n"
          + "L_82c5ae48:;\n}\n")
UNRELATED = HEAD.replace("f_82c59eb0", "f_92c59eb0") + ANCHOR + "    c->slow = 1;\nL_82c5ae48:;\n}\n"
LIFTED = UPDATE + UNRELATED

FIXTURE = r'''#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include "oot_high_fps.h"
#define A64_NOESC
typedef struct { uint64_t x[32]; uint64_t vreg[32][2]; uint8_t n; int slow; } Ctx;
static const uint64_t g_module_base = 0;
static void a64_vset64(uint64_t *v, uint64_t bits) { v[0] = bits; v[1] = 0; }
/* (1 when ordered, with n set for less than; 0 for NaN, as the lift's test then leaves n clear) */
static int a64_fcmp32(Ctx *c, const uint64_t *a, const uint64_t *b) {
    const float x = oot_bits_float((uint32_t)a[0]), y = oot_bits_float((uint32_t)b[0]);
    if (x != x || y != y) return 0;
    c->n = x < y;
    return 1;
}
/* (the host file's world: the time object's step at [[0x84c9e890]]+0x10, the cap, no log) */
static uint8_t mem[0x3000];
static uint8_t *guest(uint64_t a) {
    if (a == 0x84c9e890ULL) return mem + 0x100;
    return a < sizeof mem ? mem + a : mem;
}
#define GP(a) ((void *)guest(a))
#define G64(a) (*(uint64_t *)GP(a))
typedef long long LONG64;
#define InterlockedIncrement64(p) (++*(p))
#define InterlockedExchange64(p, v) (*(p) = (v))
static void hos_log(const char *f, ...) { (void)f; }
static int is_timed;
static int timed(void) { return is_timed; }
static int fps_log(void) { return 0; }
@HOST@
@UPDATE@
static int failures, checks;
static float blend_frames;   /* (the animation variable the state machine sets) */
/* one frame: the horse's step, the frame's (the time object's; 0: none), a cap above 60 or not. The blend frames as the game
   carries them: the slow-motion branch adds the step to last frame's (20 when there were none), the other works them out for
   the blend to end at takeoff (25 here). 1 when the slow-motion branch ran */
static int frame(float step, float frame_step, int timed_now) {
    Ctx c;
    memset(&c, 0, sizeof c);
    is_timed = timed_now;
    G64(0x84c9e890ULL) = frame_step != 0.0f ? 0x1000 : 0;
    G64(0x1000) = 0x2000;
    const uint32_t f = oot_float_bits(frame_step);
    memcpy(mem + 0x2010, &f, 4);
    c.vreg[10][0] = oot_float_bits(step);
    f_82c59eb0(&c);
    blend_frames = c.slow ? (blend_frames > 1.0f ? blend_frames : 20.0f) + step : 25.0f;
    return c.slow;
}
static void run(const char *what, float step, float frame_step, int timed_now, int frames, int slow, float expected) {
    blend_frames = 25.0f;
    int slows = 0;
    for (int i = 0; i < frames; i++) slows += frame(step, frame_step, timed_now);
    checks++;
    if (slows != (slow ? frames : 0) || fabsf(blend_frames - expected) > 1e-3f) {
        printf("FAIL: %s: the slow-motion branch ran %d of %d frames, blend frames %.3f (expected %s, %.3f)\n", what, slows,
               frames, blend_frames, slow ? "every frame" : "none", expected);
        failures++;
    }
}
int main(void) {
    /* (above 60 fps: the whole frame's step) */
    run("120 fps", 0.5f, 0.5f, 1, 40, 0, 25.0f);
    run("70 fps", 60.0f / 70.0f, 60.0f / 70.0f, 1, 40, 0, 25.0f);
    run("144 fps", 60.0f / 144.0f, 60.0f / 144.0f, 1, 40, 0, 25.0f);
    run("240 fps", 0.25f, 0.25f, 1, 40, 0, 25.0f);
    run("120 fps, the horse's step a little under the frame's", 0.5f * 0.9995f, 0.5f, 1, 40, 0, 25.0f);
    run("120 fps, the horse's step a little over the frame's", 0.5f * 1.0005f, 0.5f, 1, 40, 0, 25.0f);
    /* (the game's own test) */
    run("slow motion at 120 fps", 0.25f, 0.5f, 1, 40, 1, 25.0f + 40 * 0.25f);
    run("slow motion at a cap of 60", 0.5f, 1.0f, 0, 40, 1, 25.0f + 40 * 0.5f);
    run("a cap of 60", 1.0f, 1.0f, 0, 40, 0, 25.0f);
    run("a cap of 60, its time object at 0.5", 0.5f, 0.5f, 0, 40, 1, 25.0f + 40 * 0.5f);
    run("a frame slower than 60 fps", 1.25f, 1.25f, 1, 40, 0, 25.0f);
    run("no time object", 0.5f, 0.0f, 1, 40, 1, 25.0f + 40 * 0.5f);
    run("a NaN step", NAN, 0.5f, 1, 1, 0, 25.0f);
    if (!failures) printf("PASS: a horse's jump blend frames (%d checks)\n", checks);
    return failures != 0;
}
'''


def build_and_run(cc, update, host, directory):
    source, binary = Path(directory) / "fixture.c", Path(directory) / "fixture.exe"
    source.write_text(FIXTURE.replace("@HOST@", host).replace("@UPDATE@", update.replace('#include "a64.h"\n', "")),
                      encoding="utf-8")
    subprocess.run([cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-Wno-unused-const-variable",
                    "-I", str(ROOT / "host"),
                    str(source), "-o", str(binary), "-lm"], check=True)
    return subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    patched, counts, _ = oot_patches.patch_file(LIFTED, "code_040.c")
    hooked = "hos_oot_horse_whole_step(" in patched
    host = ""
    if hooked:   # (the host's function, as the game links it: cut from the source in the tree)
        text = (ROOT / "host" / "oot_high_fps.c").read_text(encoding="utf-8")
        host = block(text, "int hos_oot_horse_whole_step(uint32_t step_bits, uint64_t slot) {")
    with tempfile.TemporaryDirectory(prefix="horse-jump-step-") as directory:
        result = build_and_run(args.cc, patched, host, directory)
        print(result.stdout, end="")
        if result.returncode != 0:
            raise SystemExit("FAIL: a horse's jump blend frames above 60 fps (the patch %s)" % ("is in" if hooked else "is missing"))
        native = build_and_run(args.cc, LIFTED, "", directory)
        if native.returncode == 0 or "FAIL: 120 fps:" not in native.stdout:
            raise SystemExit("FAIL: the unpatched update did not fail the 120 fps check")
        print("PASS: the unpatched update compiles and fails the 120 fps check (its blend frames grow by the step)")
    assert counts["horse jump step"] == 1
    assert UNRELATED in patched
    again, repeated, _ = oot_patches.patch_file(patched, "code_040.c")
    assert again == patched and repeated["horse jump step"] == 1
    for altered in (LIFTED.replace("c->vreg[10],c->vreg[9]", "c->vreg[11],c->vreg[9]", 1),
                    LIFTED.replace("{ goto L_82c5ae48; }", "{ goto L_82c5ae50; }", 1),
                    LIFTED.replace(HEAD, HEAD + ANCHOR, 1), UNRELATED):
        output, missing, _ = oot_patches.patch_file(altered, "code_040.c")
        assert output == altered and missing["horse jump step"] == 0
        warning = io.StringIO()
        with contextlib.redirect_stdout(warning):
            oot_patches.report([Path("code_040.c")], [missing])
        assert "WARNING: the horse's jump step test was found 0 times" in warning.getvalue()
    print("PASS: scoped, idempotent, and a changed anchor is left alone with a warning")


if __name__ == "__main__":
    main()
