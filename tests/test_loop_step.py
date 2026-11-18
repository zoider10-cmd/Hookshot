"""The frozen Zoras stand still above a 60 frame-rate cap (#988).

An animation that loops over one frame or less is one pose (the Zoras under the ice in adult Zora's Domain: start 0, end 1). At 60
fps the clock's step is 1 and every update lands on the same phase. Above a 60 cap the step is the frame's own time (0.36 at 165
fps), the phase moved by it each frame and the pose twitched. The game makes the time a skeleton is drawn at in two places:
f_802cfca0 advances the clock of each animation entry (time +4, start +16, end +20, in two places that multiply the step), and
f_80944aa0 writes the time into the list the skeletons read, wrapped into the range kept beside it (+4, +8).

This compiles the production patches (nx2/oot_patches.py patch_loop_steps, patch_loop_pose) applied to authored updates cut
the way the lifted ones are, and host/loop_step.h's functions the patches call. The same checks run on the unpatched updates:
they must fail there, or the test checks nothing. No game files or lifted function body are used.

python -I -B tests/test_loop_step.py [--cc gcc]
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import oot_patches  # noqa: E402

HEADER = ROOT / "host" / "loop_step.h"

SITE_1 = ("if (((c->x[9] >> 3) & 1)) { goto L_802d077c; }\n"
          "    {uint64_t _a=0,_b=0,_z,_v;memcpy(&_a,c->vreg[8],4);memcpy(&_b,c->vreg[1],4);_z=(_a^_b)&0x80000000ULL;\n"
          "    _v=a64_fpx_mul32_fma32(c,_a,_b,_z);\n"
          "    a64_vset64(c->vreg[2],_v);}\n")
SITE_2 = ("if (((c->x[9] >> 3) & 1)) { goto L_802d07f4; }\n"
          "    {uint64_t _a=0,_b=0,_z,_v;memcpy(&_a,c->vreg[8],4);memcpy(&_b,c->vreg[0],4);_z=(_a^_b)&0x80000000ULL;\n"
          "    _v=a64_fpx_mul32_fma32(c,_a,_b,_z);\n"
          "    a64_vset64(c->vreg[2],_v);}\n")
CLOCK = ('#include "a64.h"\n'
         "void f_802cfca0(Ctx *__restrict A64_NOESC c) {\n"
         "    c->x[9]=recomp_load32(c,c->x[20] + 0);\n"
         "    if (c->x[10] == 1) { goto L_802d077c; }\n"
         + SITE_1 +
         "goto L_advance;\n"
         "L_802d077c:;\n"
         "    c->x[9] = 0;\n"
         + SITE_2 +
         "goto L_advance;\n"
         "L_802d07f4:;\n"
         "    a64_vset64(c->vreg[2],0);\n"
         "L_advance:;\n"
         "    clock_advance(c);\n"
         "}\n"
         "void f_90000000(Ctx *__restrict A64_NOESC c) {\n"
         "    c->x[9]=recomp_load32(c,c->x[20] + 0);\n"
         + SITE_1 + "L_802d077c:;\n}\n")
STORE = "    { { uint64_t _v=0; memcpy(&_v,&c->vreg[0][0],4); recomp_store32(c,(c->x[22]+0ULL),_v); } }\n"
POSE = ('#include "a64.h"\n'
        "void f_80944aa0(Ctx *__restrict A64_NOESC c) {\n" + STORE + "}\n"
        "void f_90000001(Ctx *__restrict A64_NOESC c) {\n" + STORE + "}\n")
CONTEXT = """#pragma once
#include <stdint.h>
#include <string.h>
#define A64_NOESC
typedef struct {
    uint64_t x[32], vreg[32][2];
    uint32_t fpcr, fpsr;
} Ctx;
"""
FIXTURE = r'''#define _CRT_SECURE_NO_WARNINGS
#include <math.h>
#include <stdio.h>
#include "a64.h"
@HOOKS@
static uint8_t heap[4096];
static int failures;
static const char *failed[64];
static int failed_count[64], failed_kinds;
static void fail(const char *what) {   /* (each failing check once, with how often) */
    failures++;
    for (int i = 0; i < failed_kinds; i++) if (failed[i] == what) { failed_count[i]++; return; }
    if (failed_kinds < 64) failed[failed_kinds] = what, failed_count[failed_kinds++] = 1;
}
#define CHECK(test, what) do { if (!(test)) fail(what); } while (0)
static uint32_t bits(float f) { uint32_t b; memcpy(&b, &f, 4); return b; }
static float real(uint32_t b) { float f; memcpy(&f, &b, 4); return f; }
uint64_t recomp_load32(Ctx *c, uint64_t at) { uint32_t v; (void)c; memcpy(&v, heap + at, 4); return v; }
void recomp_store32(Ctx *c, uint64_t at, uint64_t v) { uint32_t w = (uint32_t)v; (void)c; memcpy(heap + at, &w, 4); }
void a64_vset64(uint64_t *v, uint64_t value) { v[0] = value; v[1] = 0; }
uint64_t a64_fpx_mul32_fma32(Ctx *c, uint64_t a, uint64_t b, uint64_t z) {
    (void)c; (void)z;
    return bits(real((uint32_t)a) * real((uint32_t)b));
}
/* (the game's own wrap of a clock that passes its end: back into [start, end)) */
static void clock_advance(Ctx *c) {
    float time = real((uint32_t)recomp_load32(c, c->x[20] + 4)) + real((uint32_t)c->vreg[2][0]);
    const float start = real((uint32_t)recomp_load32(c, c->x[20] + 16)), end = real((uint32_t)recomp_load32(c, c->x[20] + 20));
    if (time >= end) time = start + fmodf(time - start, end - start);
    recomp_store32(c, c->x[20] + 4, bits(time));
}
@UPDATES@

enum { A = 0x100, B = 0x200, C = 0x300, STATE = 0x400 };
static void entry(uint64_t at, float time, float start, float end) {
    Ctx c = {0};
    (void)c;
    recomp_store32(&c, at + 0, 0x403);
    recomp_store32(&c, at + 4, bits(time));
    recomp_store32(&c, at + 16, bits(start));
    recomp_store32(&c, at + 20, bits(end));
}
/* (one update of the entry's clock by the frame step: the time it then holds) */
static float update(uint64_t at, float step, int mode) {
    Ctx c = {0};
    c.x[20] = at;
    c.x[10] = (uint64_t)mode;
    c.vreg[8][0] = bits(step);
    c.vreg[1][0] = c.vreg[0][0] = bits(1.0f);
    f_802cfca0(&c);
    return real((uint32_t)recomp_load32(&c, at + 4));
}
static float phase(float t) { return t - floorf(t); }
/* (the time written for the skeleton: the incoming one, the range [min, max] kept beside it) */
static float pose(float incoming, float min, float max) {
    Ctx c = {0};
    c.x[22] = STATE;
    recomp_store32(&c, STATE + 0, bits(-1.0f));
    recomp_store32(&c, STATE + 4, bits(min));
    recomp_store32(&c, STATE + 8, bits(max));
    c.vreg[0][0] = bits(incoming);
    f_80944aa0(&c);
    return real((uint32_t)recomp_load32(&c, STATE));
}

int main(void) {
    const float frame = 60.0f / 165.0f;   /* (the step at 165 fps) */
    for (int mode = 0; mode < 2; mode++) {
        /* the Zoras: a loop of one frame, a clock a different phase of it each frame at 165 fps */
        timed = 1;
        entry(A, 0.0057f, 0.0f, 1.0f);
        float lo = 2.0f, hi = -1.0f;
        for (int i = 0; i < 165; i++) {
            const float p = phase(update(A, frame, mode));
            if (p < lo) lo = p;
            if (p > hi) hi = p;
        }
        CHECK(hi - lo < 0.01f, "a loop of one frame must stay on one phase at 165 fps");
        /* two entries in turn each keep their own fractions: still one phase each */
        entry(B, 0.25f, 0.0f, 1.0f); entry(C, 0.75f, 0.0f, 1.0f);
        for (int i = 0; i < 165; i++) {
            const float pb = phase(update(B, frame, mode)), pc = phase(update(C, frame, mode));
            CHECK(fabsf(pb - 0.25f) < 0.01f && fabsf(pc - 0.75f) < 0.01f, "each loop of one frame keeps its own phase");
        }
        /* a loop of exactly one frame is a pose, a loop of a frame and a half is not */
        entry(A, 2.5f, 2.0f, 3.0f);
        update(A, frame, mode); update(A, frame, mode); update(A, frame, mode);
        CHECK(fabsf(phase(real((uint32_t)recomp_load32(&(Ctx){0}, A + 4))) - 0.5f) < 0.01f, "the loop from 2 to 3 is a pose too");
        entry(A, 0.0f, 0.0f, 1.5f);
        update(A, frame, mode);
        CHECK(fabsf(real((uint32_t)recomp_load32(&(Ctx){0}, A + 4)) - frame) < 1e-4f, "a loop longer than a frame keeps the fractional step");
        /* a long loop keeps the game's step: a second at 165 fps is 60 frames of time */
        entry(A, 0.0f, 0.0f, 1000.0f);
        float t = 0;
        for (int i = 0; i < 165; i++) t = update(A, frame, mode);
        CHECK(fabsf(t - 60.0f) < 0.05f, "a long loop must keep moving by the frames' own time");
        /* at a cap of 60 nothing changes: the step the game has */
        timed = 0;
        entry(A, 0.0057f, 0.0f, 1.0f);
        CHECK(fabsf(update(A, 0.4f, mode) - 0.4057f) < 1e-4f, "at a cap of 60 a loop of one frame moves by the game's step");
        entry(A, 0.0057f, 0.0f, 1.0f);
        CHECK(fabsf(phase(update(A, 1.0f, mode)) - 0.0057f) < 1e-4f, "at a cap of 60 the step of 1 stays on its phase");
        timed = 1;
        /* a step of 0 (paused) and one under 0 are the game's */
        entry(A, 0.3f, 0.0f, 1.0f);
        CHECK(fabsf(update(A, 0.0f, mode) - 0.3f) < 1e-6f, "a paused clock does not move");
    }
    /* the whole frames handed out add up to the frames' own time, whatever its steps */
    {
        float sum = 0;
        for (int i = 0; i < 1650; i++) sum += real(hos_loop_step(0x778, bits(frame), bits(0.0f), bits(1.0f)));
        CHECK(fabsf(sum - 600.0f) < 1.0f, "ten seconds at 165 fps are 600 whole frames");
    }
    /* the time a skeleton is drawn at */
    timed = 1;
    CHECK(pose(0.7f, 0.0f, 1.0f) == 0.0f, "a loop of one frame is drawn at its start");
    CHECK(pose(0.7f, 0.25f, 1.0f) == 0.25f, "a loop of one frame is drawn at its own start");
    CHECK(pose(0.7f, 0.0f, 100.0f) == 0.7f, "a long loop is drawn at its time");
    CHECK(pose(0.7f, 0.0f, 1.5f) == 0.7f, "a loop of a frame and a half is drawn at its time");
    CHECK(pose(0.7f, 1.0f, 0.0f) == 0.7f, "a range that is the wrong way round is left alone");
    timed = 0;
    CHECK(pose(0.7f, 0.0f, 1.0f) == 0.7f, "at a cap of 60 the time is the game's");
    for (int i = 0; i < failed_kinds; i++) printf("FAIL: %s (%d times)\n", failed[i], failed_count[i]);
    if (!failures) puts("PASS: loop of one frame");
    return failures != 0;
}
'''
WITH_HOOKS = r'''#include "loop_step.h"
static LoopStep loops;
static int timed = 1;
uint32_t hos_loop_step(uint64_t at, uint32_t step, uint32_t start, uint32_t end) { return loop_step(&loops, at, step, start, end, timed); }
uint32_t hos_loop_pose(uint32_t time, uint32_t start, uint32_t end) { return loop_pose(time, start, end, timed); }
'''
NO_HOOKS = r'''static int timed = 1;
uint32_t hos_loop_step(uint64_t at, uint32_t step, uint32_t start, uint32_t end) { (void)at; (void)start; (void)end; return step; }
uint32_t hos_loop_pose(uint32_t time, uint32_t start, uint32_t end) { (void)start; (void)end; return time; }
'''


def patched_updates():
    """(the authored updates with the production patches, the sites patched): a patch the tree does not have yet leaves its update as it is"""
    clock, loops = CLOCK, 0
    if hasattr(oot_patches, "patch_loop_steps"):
        clock, loops = oot_patches.patch_loop_steps(CLOCK)
    pose, poses = POSE, 0
    if hasattr(oot_patches, "patch_loop_pose"):
        pose, poses = oot_patches.patch_loop_pose(POSE)
    return clock, loops, pose, poses


def run(cc, directory, clock, pose):
    (directory / "a64.h").write_text(CONTEXT, encoding="utf-8")
    hooks = WITH_HOOKS if HEADER.exists() else NO_HOOKS
    source, binary = directory / "fixture.c", directory / "fixture.exe"
    # (the patched text starts with the include the fixture has already: its second copy is left out)
    updates = clock.replace('#include "a64.h"\n', "", 1) + pose.replace('#include "a64.h"\n', "", 1)
    source.write_text(FIXTURE.replace("@HOOKS@", hooks).replace("@UPDATES@", updates), encoding="utf-8")
    command = [cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-I", str(ROOT / "host"), str(source),
               "-o", str(binary), "-lm"]
    subprocess.run(command, check=True)
    return subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    clock, loops, pose, poses = patched_updates()
    with tempfile.TemporaryDirectory(prefix="loop-step-") as directory:
        directory = Path(directory)
        fixed = run(args.cc, directory, clock, pose)
        sys.stdout.write(fixed.stdout)
        if fixed.returncode != 0:
            raise SystemExit("FAIL: the patched updates do not keep a loop of one frame on one phase above a cap of 60")
        # The negative control must compile, then fail the same behavioral checks.
        native = run(args.cc, directory, CLOCK, POSE)
        if native.returncode == 0 or "must stay on one phase" not in native.stdout:
            raise SystemExit("FAIL: the unpatched updates did not fail the one-phase check")
        print("PASS: the unpatched updates are rejected by the same checks")
    assert loops == 2 and poses == 1, "the production patches must find both clocks and the pose store"
    assert clock.count("hos_loop_step(c->x[20],") == 2 and pose.count("_v=hos_loop_pose(") == 1
    assert clock.split("void f_90000000")[1] == CLOCK.split("void f_90000000")[1]  # the authored unrelated function is left alone
    assert pose.split("void f_90000001")[1] == POSE.split("void f_90000001")[1]
    assert oot_patches.patch_loop_steps(clock) == (clock, 0) and oot_patches.patch_loop_pose(pose) == (pose, 0)


if __name__ == "__main__":
    main()
