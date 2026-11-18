"""The game's texture heap compaction asked for once in a while (host/oot_tex_compact.h, nx2/oot_patches.py patch_tex_compact).

The texture data manager's per-frame step (f_80797240) asks its Compaction thread for a round at every frame none runs, and
every texture a round moved is made again; here that is a batch of new textures to the renderer every few frames (the long frames
standing in Castle Town's market). The manager now asks only when its last round is a second ago (HOS_TEX_COMPACT_MS=<ms> for another gap, 0 for the game's own).

The rule (the header, compiled alone): a gap of 0 says yes at every ask, as the game has it; a negative gap never; a gap says
yes at the first ask and then only once the gap has passed since the last yes. The switch's value: not set or empty is the
default, a whole number its milliseconds, "off" or "never" or a negative number never, anything else the default.

The patch: the request's second test also asks the host, once, in the manager's step only; a file patched before, or whose code
differs (another game version), is left as it is; the host's function is declared.

python -I -B tests/test_tex_compact.py
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import oot_patches  # noqa: E402

FIXTURE = r"""
#include "oot_tex_compact.h"
#include <stdio.h>
static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)
#define MS 1000000LL
int main(void) {
    {   /* (the game's own: every ask) */
        OotTexCompact s = OOT_TEX_COMPACT_INIT;
        for (int i = 0; i < 100; i++) CHECK(oot_tex_compact_due(&s, 0, i * 16 * MS) == 1);
    }
    {   /* (never) */
        OotTexCompact s = OOT_TEX_COMPACT_INIT;
        for (int i = 0; i < 100; i++) CHECK(oot_tex_compact_due(&s, -1, i * 16 * MS) == 0);
    }
    {   /* (a gap of 1 s, asked every 16 ms for 10 s from a clock that starts anywhere: the first ask, then one a second) */
        OotTexCompact s = OOT_TEX_COMPACT_INIT;
        const long long t0 = 123456789012LL;
        int yes = 0;
        long long last = -1;
        for (long long t = 0; t < 10000 * MS; t += 16 * MS) {
            const int due = oot_tex_compact_due(&s, 1000 * MS, t0 + t);
            if (due) {
                CHECK(last < 0 || t - last >= 1000 * MS);
                CHECK(last < 0 || t - last < 1016 * MS);   /* (at the first ask past the gap) */
                last = t, yes++;
            }
        }
        CHECK(yes == 10);
        CHECK(oot_tex_compact_due(&s, 1000 * MS, t0) == 0);   /* (a clock that stood still or went back: not yet) */
    }
    {   /* (the first ask is a yes even at time 0, and at a negative time) */
        OotTexCompact a = OOT_TEX_COMPACT_INIT, b = OOT_TEX_COMPACT_INIT;
        CHECK(oot_tex_compact_due(&a, 5000 * MS, 0) == 1);
        CHECK(oot_tex_compact_due(&a, 5000 * MS, 4999 * MS) == 0);
        CHECK(oot_tex_compact_due(&a, 5000 * MS, 5000 * MS) == 1);
        CHECK(oot_tex_compact_due(&b, 5000 * MS, -7 * MS) == 1);
    }
    /* (the switch's value) */
    CHECK(oot_tex_compact_gap_ns(0, 0) == 0);
    CHECK(oot_tex_compact_gap_ns("", 2000) == 2000 * MS);
    CHECK(oot_tex_compact_gap_ns(0, -1) == -1);
    CHECK(oot_tex_compact_gap_ns("0", 2000) == 0);
    CHECK(oot_tex_compact_gap_ns("1500", 0) == 1500 * MS);
    CHECK(oot_tex_compact_gap_ns("off", 2000) == -1);
    CHECK(oot_tex_compact_gap_ns("never", 2000) == -1);
    CHECK(oot_tex_compact_gap_ns("-1", 2000) == -1);
    CHECK(oot_tex_compact_gap_ns("-0", 2000) == 0);
    CHECK(oot_tex_compact_gap_ns("offf", 2000) == 2000 * MS);
    CHECK(oot_tex_compact_gap_ns("12x", 2000) == 2000 * MS);
    CHECK(oot_tex_compact_gap_ns("x", 0) == 0);
    printf(fails ? "tex_compact: %d FAILED\n" : "tex_compact: all passed\n", fails);
    return fails != 0;
}
"""

# (the manager's step as the lift has it around the request, and the next function, which has the same two lines)
LIFTED = '''#include "a64.h"
void f_80797240(Ctx *__restrict A64_NOESC c) {
    c->x[8]=recomp_load8(c,c->x[0] + 960);
if (!((c->x[8] >> 0) & 1)) { goto L_80797334; }
    c->x[8]=recomp_load32(c,c->x[19] + 776);
if ((uint32_t)c->x[8] != 0) { goto L_80797288; }
    c->x[8]=recomp_load8(c,c->x[19] + 960);
if (!((c->x[8] >> 1) & 1)) { goto L_80797288; }
    c->x[9] = 0x1ULL;
L_80797288:;
    c->x[8]=recomp_load32(c,c->x[19] + 776);
L_80797334:;
}

void f_807974f0(Ctx *__restrict A64_NOESC c) {
    c->x[8]=recomp_load8(c,c->x[19] + 960);
if (!((c->x[8] >> 1) & 1)) { goto L_80797288; }
L_80797288:;
}
'''


class TexCompactTests(unittest.TestCase):
    def test_rule(self):
        compiler = shutil.which("gcc") or shutil.which("clang")
        if not compiler:
            self.skipTest("no C compiler")
        with tempfile.TemporaryDirectory(prefix="hookshot-tex-compact-") as tmp:
            tmp = Path(tmp)
            (tmp / "rule.c").write_text(FIXTURE, encoding="utf-8")
            binary = tmp / "rule.exe"
            build = subprocess.run([compiler, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-O1", "-I", str(ROOT / "host"),
                                    str(tmp / "rule.c"), "-o", str(binary)], text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("all passed", run.stdout)

    def test_patch(self):
        out, n = oot_patches.patch_tex_compact(LIFTED)
        self.assertEqual(n, 1)
        self.assertEqual(out.count("hos_oot_tex_compact_due()"), 1)   # (the one call; the declaration is checked below)
        self.assertEqual(out.count(oot_patches.TEXC_NEW), 1)
        self.assertEqual(out.count(oot_patches.TEXC_OLD), 1)   # (the next function's own two lines, as they were)
        step = out[out.index(oot_patches.TEXC_HEAD):out.index("void f_807974f0")]
        self.assertIn(oot_patches.TEXC_NEW, step)
        self.assertNotIn(oot_patches.TEXC_OLD, step)
        self.assertIn('#include "a64.h"\n' + oot_patches.TEXC_DECL, out)
        self.assertEqual(oot_patches.patch_tex_compact(out), (out, 1))   # (patched before: as it is)
        other = LIFTED.replace("c->x[19] + 960);\nif (!((c->x[8] >> 1) & 1)) { goto L_80797288; }\n    c->x[9]",
                               "c->x[19] + 964);\nif (!((c->x[8] >> 1) & 1)) { goto L_80797288; }\n    c->x[9]")
        self.assertNotEqual(other, LIFTED)
        self.assertEqual(oot_patches.patch_tex_compact(other), (other, 0))   # (another game version's code)
        none = LIFTED.replace("void f_80797240", "void f_90797240")
        self.assertEqual(oot_patches.patch_tex_compact(none), (none, 0))

    def test_patch_file_counts_it(self):
        out, counts, lines = oot_patches.patch_file(LIFTED, "code_004.c", False)
        self.assertEqual(counts["texture compaction"], 1)
        self.assertIn(oot_patches.TEXC_NEW, out)
        self.assertTrue(any("texture heap's compaction" in line for line in lines), lines)
        again, counts, lines = oot_patches.patch_file(out, "code_004.c", False)
        self.assertEqual(again, out)
        self.assertEqual(counts["texture compaction"], 1)

    def test_host_calls_the_rule(self):
        host = (ROOT / "host" / "oot_tex_compact.c").read_text(encoding="utf-8")
        for needle in ('getenv("HOS_TEX_COMPACT_MS")', "oot_tex_compact_due(&compact, compact_gap, now)",
                       "int hos_oot_tex_compact_due(void) {", "#define OOT_TEX_COMPACT_DEFAULT_MS 1000\n",
                       "oot_tex_compact_gap_ns(getenv(\"HOS_TEX_COMPACT_MS\"), OOT_TEX_COMPACT_DEFAULT_MS)"):
            self.assertIn(needle, host)


if __name__ == "__main__":
    unittest.main()
