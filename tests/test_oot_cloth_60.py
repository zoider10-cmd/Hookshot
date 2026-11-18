"""Above a 60 fps cap, Havok cloth is solved at most 60 times a second (host/oot_high_fps.h oot_cloth_gate, host/oot_high_fps.c
hos_oot_cloth_solve, nx2/oot_patches.py patch_cloth_solve), with HOS_FPS_CLOTH_60=1.

The cloth's solve runs as a job on the game's job workers (f_81b47080, under the job runner f_8016b620), once a frame for each
cloth near the camera, and each solve steps the cloth a 60th of a second whatever the frame (host/oot_high_fps.h). Above 60 fps
it is solved every frame: at 240 fps four solves where the console makes one, so the cloth runs four times too fast and costs
four times the CPU. Near King Zora in Zora's Domain that held the frame at about 55 fps under a cap of 240 (issue #1485: the
solve was 45.7 % of the job workers' game code there, about 10.5 ms of CPU a frame). With the gate, a frame whose step is under
1 (a cap above 60) solves only when the game clock (the double at hos_step_probe + 0xd58, in 60ths of a second) has crossed a
whole 60th since the frame before: about 60 solves a second, each a 60th, and every job of one frame makes the same choice. A
frame the gate holds returns from the job at once with the job's own result (0), before the job saves anything.

The job is lifted as the game has it at its head (its first line, the prologue's first store), then a stand-in for its work that
counts the solves, run through patch_file, compiled with stand-ins for guest memory, the repository's switch rule (gpu/vk/
compat/longshot_env.h) and the host's hos_oot_cloth_solve (cut from host/oot_high_fps.c, when there), and run for 240 frames of
3 jobs each at frame steps 0.25 (240 fps), 60/144 (144 fps), 0.5 (120 fps), 1 (60 fps) and 2 (30 fps), at a cap of 60 (no frame
time given), with a step of 0 and NaN, and with the clock going back (a load), for HOS_FPS_CLOTH_60 unset, 1 and 0. Checked: at
240 fps 60 frames solve, one in four; at 144 and 120, 60 give or take 1; at 60 fps and slower, at a cap of 60, for a bad step
and with the switch unset or 0, every frame; a clock that went back solves at once; the 3 jobs of a frame always agree; a held
job leaves the stack pointer as it was and returns 0. The patch hooks the job once, before its first line, declares the hook,
and leaves a file patched before, or whose code differs, as it is.

python -I -B tests/test_oot_cloth_60.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import oot_patches  # noqa: E402
sys.path.insert(0, str(ROOT / "tests"))   # (python -I leaves the check's own folder off the path)
from srccut import between, block  # noqa: E402

# (f_81b47080's head as the lift writes it, its prologue's first store, then a stand-in for the solve: it counts, and returns as
# the job does, 0 in x0 and the stack pointer given back)
LIFTED_SOLVE = """#include "a64.h"
void f_81b47080(Ctx *__restrict A64_NOESC c) {
    /* nop/hint */
    { uint64_t _b=c->x[31]; int64_t _o=-128; { uint64_t _v=0; memcpy(&_v,&c->vreg[10][0],8); recomp_store64(c,(_b+_o),_v); } c->x[31]=_b+_o; }
    cloth_solved(c);
    { uint64_t _r = ((uint64_t)0 | ((uint64_t)(uint32_t)(((uint32_t)((uint64_t)0)) << 0))); _r &= 0xFFFFFFFFULL; c->x[0] = _r; }
    { uint64_t _a=c->x[31], _b=128ULL; uint64_t _r=_a+_b; c->x[31]=_r; }
return;
}
"""

# (stand-ins for the lift's runtime and the host: guest memory a small array, the game's frame step (a float) at 0x84d61fc8,
# f_80706be0's object (hos_step_probe) at 0x100 with the game clock at +0xd58)
RUNTIME = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "../gpu/vk/compat/longshot_env.h"
#include "oot_high_fps.h"
typedef struct { uint64_t x[32]; uint64_t vreg[32][2]; uint64_t fpcr, fpsr; } Ctx;
typedef long long LONG64;
typedef struct { int unused; } SRWLOCK;
#define SRWLOCK_INIT {0}
#define A64_NOESC
static void AcquireSRWLockExclusive(SRWLOCK *l) { (void)l; }
static void ReleaseSRWLockExclusive(SRWLOCK *l) { (void)l; }
static LONG64 InterlockedIncrement64(volatile LONG64 *p) { return ++*p; }
static const uint64_t g_module_base = 0;
static uint8_t mem[0x2000];
static uint32_t game_step;
static int solves;
volatile uint32_t hos_frame_seconds_bits;
volatile uint64_t hos_step_probe;
static void *GP(uint64_t a) { return mem + (a & 0x1fff); }
static int timed(void) { return hos_frame_seconds_bits != 0; }
static int fps_log(void) { return 0; }
static void hos_log(const char *f, ...) { (void)f; }
static uint64_t recomp_load32(Ctx *c, uint64_t a) {
    (void)c;
    if (a == 0x84d61fc8ULL) return game_step;
    uint32_t v;
    memcpy(&v, GP(a), 4);
    return v;
}
static void recomp_store64(Ctx *c, uint64_t a, uint64_t v) { (void)c; memcpy(GP(a), &v, 8); }
static void cloth_solved(Ctx *c) { (void)c; solves++; }
"""

FRAMES = r"""
/* 240 frames of 3 jobs at a frame step (60ths of a second; seconds 0: a cap of 60), the clock going back at frame `back`
   (-1: never). Prints a line a frame: its index, the jobs that solved, whether every held job left x31 as it was and returned 0 */
static void run(float step, int capped, int back) {
    memset(mem, 0, sizeof mem);
    hos_step_probe = 0x100;
    hos_frame_seconds_bits = capped ? 0 : oot_float_bits(step / 60.0f);
    game_step = oot_float_bits(step);
    double clock = 1000.0;
    for (int f = 0; f < 240; f++) {
        clock = f == back ? clock - 300.0 : clock + (step == step && step > 0.0f ? step : 1.0f);
        memcpy(GP(0x100 + 0xd58), &clock, 8);
        int solved = 0, held_ok = 1;
        for (int j = 0; j < 3; j++) {
            Ctx c;
            memset(&c, 0, sizeof c);
            c.x[31] = 0x1800;
            c.x[0] = 0x55;
            const int before = solves;
            f_81b47080(&c);
            if (solves != before) solved++;
            else held_ok &= c.x[31] == 0x1800 && c.x[0] == 0;
        }
        printf("%d %d %d\n", f, solved, held_ok);
    }
}
int main(int argc, char **argv) {
    if (argc < 4) return 2;
    run((float)atof(argv[1]), atoi(argv[2]), atoi(argv[3]));
    return 0;
}
"""

SWITCH = ("unset", "1", "0")
# (name, the frame step, at a cap of 60, the frame the clock goes back at or -1)
CASES = (("240 fps", 0.25, 0, -1), ("144 fps", 60.0 / 144.0, 0, -1), ("120 fps", 0.5, 0, -1), ("60 fps", 1.0, 0, -1),
         ("30 fps", 2.0, 0, -1), ("a cap of 60", 0.25, 1, -1), ("a step of 0", 0.0, 0, -1), ("a NaN step", float("nan"), 0, -1),
         ("240 fps, a load at frame 101", 0.25, 0, 101))


def hos_solve(source):
    """host/oot_high_fps.c's hos_oot_cloth_solve and the gate's state before it, when there (the patched job calls it)"""
    if "int hos_oot_cloth_solve(" not in source:
        return ""
    return between(source, "static OotClothGate cloth_gate", "int hos_oot_cloth_solve(") + block(source, "int hos_oot_cloth_solve(") + "\n"


def compiler():
    return shutil.which("gcc") or shutil.which("clang")


class ClothSolveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="longshot-cloth60-")
        cls.binary = None
        if not compiler():
            return
        patched = oot_patches.patch_file(LIFTED_SOLVE, "code_cloth.c", False)[0]
        host = (ROOT / "host" / "oot_high_fps.c").read_text(encoding="utf-8")
        program = RUNTIME + hos_solve(host) + patched.replace('#include "a64.h"\n', "") + FRAMES
        tmp = Path(cls.tmp.name)
        (tmp / "cloth60.c").write_text(program, encoding="utf-8")
        cls.binary = tmp / "cloth60.exe"
        cls.build = subprocess.run([compiler(), "-std=gnu11", "-Wall", "-Wno-unused-function", "-O1", "-I", str(ROOT / "host"),
                                    str(tmp / "cloth60.c"), "-o", str(cls.binary), "-lm"], text=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def frames(self, switch, step, capped, back):
        """[(frame, jobs solved of 3, held jobs right)] for one case"""
        self.assertEqual(self.build.returncode, 0, self.build.stderr)
        env = dict(os.environ)
        env.pop("HOS_FPS_CLOTH_60", None)
        if switch != "unset":
            env["HOS_FPS_CLOTH_60"] = switch
        run = subprocess.run([str(self.binary), repr(step), str(capped), str(back)], text=True, capture_output=True,
                             timeout=30, env=env)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        rows = [tuple(int(v) for v in line.split()) for line in run.stdout.split("\n") if line]
        self.assertEqual(len(rows), 240, run.stdout)
        return rows

    def test_cloth_solves(self):
        if not self.binary:
            self.skipTest("no C compiler")
        wrong = []
        for switch in SWITCH:
            on = switch == "1"
            for name, step, capped, back in CASES:
                at = "%s, HOS_FPS_CLOTH_60 %s" % (name, switch)
                rows = self.frames(switch, step, capped, back)
                solved = [f for f, n, _ in rows if n]
                split = [f for f, n, _ in rows if n not in (0, 3)]
                if split:
                    wrong.append("%s: the jobs of a frame chose differently at frames %s" % (at, split[:5]))
                if not all(ok for _, _, ok in rows):
                    wrong.append("%s: a held job changed the stack pointer or did not return 0" % at)
                gated = on and not capped and 0.0 < step < 1.0
                if not gated:
                    if len(solved) != 240:
                        wrong.append("%s: the cloth solved in %d of 240 frames, not every frame" % (at, len(solved)))
                    continue
                want = 240 * step   # (a solve a 60th of game time: 60 at 240 fps over 240 frames)
                extra = 1 if back >= 0 else 0   # (the frame after a load solves at once)
                if not want - 1 <= len(solved) - extra <= want + 1:
                    wrong.append("%s: the cloth solved in %d of 240 frames, %g expected (at most 60 a second)"
                                 % (at, len(solved), want))
                steady = solved[1:]   # (the first frame the gate sees solves; then each whole 60th of the clock)
                if step == 0.25 and back < 0 and any(b - a != 4 for a, b in zip(steady, steady[1:])):
                    wrong.append("%s: the solves are not one in four frames: %s" % (at, solved[:8]))
                if back >= 0 and back not in solved:
                    wrong.append("%s: the frame the clock went back did not solve" % at)
        self.assertEqual(wrong, [], "%d cases wrong:\n%s" % (len(wrong), "\n".join(wrong)))

    def test_patch(self):
        self.assertTrue(hasattr(oot_patches, "patch_cloth_solve"), "nx2/oot_patches.py has no patch_cloth_solve")
        out, n = oot_patches.patch_cloth_solve(LIFTED_SOLVE)
        self.assertEqual(n, 1)
        self.assertEqual(out.count(oot_patches.CLOTH_SOLVE_NEW), 1)
        self.assertIn(oot_patches.CLOTH_SOLVE_DECL, out)
        self.assertLess(out.index("hos_oot_cloth_solve("), out.index("int64_t _o=-128"))   # (before the job saves anything)
        self.assertEqual(oot_patches.patch_cloth_solve(out), (out, 1))   # (patched before: as it is)
        other = LIFTED_SOLVE.replace("int64_t _o=-128", "int64_t _o=-144")   # (another game version's code)
        self.assertEqual(oot_patches.patch_cloth_solve(other), (other, 0))
        none = LIFTED_SOLVE.replace("void f_81b47080", "void f_91b47080")
        self.assertEqual(oot_patches.patch_cloth_solve(none), (none, 0))
        self.assertEqual(oot_patches.patch_file(LIFTED_SOLVE, "code_cloth.c", False)[1]["cloth solve"], 1)


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=1))
