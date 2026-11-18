"""Game-free Shadow resolution hook: the install's checks, the sun's object only, raise-only, live changes, menu wiring.

Compile the actual host helper (host/oot_shadow.c) with the lifter's injected call against an authored shadow object.
No dump, lifted code or game assets are needed.

    python -I -B tests/test_oot_shadow.py
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import oot_shadow


class InstallTests(unittest.TestCase):
    def install(self, words=None, build_id=oot_shadow.BUILD_ID, existing=None):
        class Lifter:
            after = {} if existing is None else dict(existing)

        class Image:
            def word(self, pc):
                return (oot_shadow.WORDS if words is None else words)[(pc - oot_shadow.SITE) // 4]

        lifter = Lifter()
        result = oot_shadow.install(lifter, Image(), build_id)
        return result, lifter.after

    def test_supported_site_and_existing_hook(self):
        count, after = self.install(existing={oot_shadow.SITE: "prior();"})
        self.assertEqual(count, 1)
        self.assertEqual(after[oot_shadow.SITE], "prior();\n" + oot_shadow.HOOK)
        self.assertIn("hos_oot_shadow(c, c->x[19]);", after[oot_shadow.SITE])

    def test_rejects_wrong_build_and_each_changed_instruction(self):
        self.assertEqual(self.install(build_id="another build"), (0, {}))
        for i in range(len(oot_shadow.WORDS)):
            words = list(oot_shadow.WORDS)
            words[i] ^= 1
            self.assertEqual(self.install(words=words), (0, {}))

    def test_site_is_the_rounding_into_w23(self):
        # and w23, w8, #0xfffffff8: the rounded size the hook raises, read by every later use of it
        self.assertEqual(oot_shadow.WORDS[0], 0x121d7117)
        self.assertEqual(oot_shadow.WORDS[0] & 0x1f, 23)

    def test_lift_and_menu_wiring(self):
        lift = (ROOT / "nx2/lift.py").read_text(encoding="utf-8")
        standalone = lift[lift.index("if a.standalone:"):lift.index("discover.discover(L")]
        self.assertIn("oot_shadow.install(", standalone)
        menu = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
        api = (ROOT / "gpu/vk/vk_api.h").read_text(encoding="utf-8")
        options = (ROOT / "gpu/vk/vk_menu.h").read_text(encoding="utf-8")
        replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
        self.assertIn("HOS_OPT_SHADOW_RES = 56", api)
        self.assertIn("int shadow_res = 0;", options)
        self.assertIn('"Shadow resolution", &opts.shadow_res, 0, 3, 1, tx_shadow_res', menu)
        self.assertIn("if (id == HOS_OPT_SHADOW_RES) return menu_shadow_res();", replay)

    def test_auto_follows_the_cards_memory(self):
        # Auto, the default, is the size for the memory tier: the game's 1600 on Minimum and Low (4 and 6 GB), 2200 on
        # Balanced (8 GB), 3072 from High (12 GB) up; a chosen size is the row's less one (the host's 0 to 2); a preset
        # puts the row back on Auto
        menu = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
        start = menu.index("int menu_shadow_res() {")
        fn = menu[start:menu.index("\n}\n", start)]
        self.assertIn("if (opts.shadow_res > 0) return std::min(opts.shadow_res, 3) - 1;", fn)
        self.assertIn("const int tier = opts.budget > 0 ? opts.budget : auto_choice.tier;", fn)
        self.assertIn("return tier == 1 || tier == 2 ? 0 : tier >= 4 ? 2 : 1;", fn)
        self.assertLess(menu.index("} // namespace\n"), start, "menu_shadow_res is the header's, outside the file's own namespace")
        start = menu.index("void apply_preset(int p) {")
        preset = menu[start:menu.index("\n}\n", start)]
        self.assertIn("if (p > 0) opts.shadow_res = 0;", preset)
        self.assertNotIn("opts.shadow_res = 2;", preset)


HEAD = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
typedef struct { uint64_t x[32]; unsigned char vreg[32][16]; } Ctx;
enum { HOS_OPT_SHADOW_RES = 56 };
static unsigned char objects[0x1000];
static int menu, reads, asked;
static uint64_t recomp_load64(Ctx *c, uint64_t a) {
    uint64_t v; (void)c; reads++;
    CHECK(a >= 0x10000000ULL && a + 8 <= 0x10001000ULL);
    memcpy(&v, objects + (a - 0x10000000ULL), 8); return v;
}
int rx_option(int id, int otherwise) { CHECK(id == HOS_OPT_SHADOW_RES && otherwise == 0); asked++; return menu; }
'''

MAIN = r'''
static void site(Ctx *c) {
SITE_C
}
static const uint64_t sun = 0x10000100, other = 0x10000800;
static Ctx input(uint64_t object, uint32_t size) {
    Ctx c; memset(&c, 0xab, sizeof c);
    c.x[19] = object; c.x[23] = size;   /* and w23: the upper half zero */
    return c;
}
static uint32_t after(uint64_t object, uint32_t size) { Ctx c = input(object, size); site(&c); return (uint32_t)c.x[23]; }
static void unchanged(uint64_t object, uint32_t size) {
    Ctx c = input(object, size), before = c; site(&c); CHECK(!memcmp(&c, &before, sizeof c));
}
int main(void) {
    uint64_t vt = 0x84baa0a8ULL; memcpy(objects + 0x100, &vt, 8);
    uint64_t else_vt = 0x84baa0b0ULL; memcpy(objects + 0x800, &else_vt, 8);
    unsigned char before[sizeof objects]; memcpy(before, objects, sizeof objects);

    /* Game's and choices out of range touch no game memory and keep every register. */
    for (int i = 0; i < 4; i++) { menu = (int[]){0, -1, 3, 100}[i]; unchanged(sun, 1600); }
    CHECK(reads == 0 && asked == 4);

    /* High and Highest raise the sun's rounded size, read live each frame. */
    menu = 1; CHECK(after(sun, 1600) == 2200);
    menu = 2; CHECK(after(sun, 1600) == 3072);
    menu = 1; CHECK(after(sun, 1600) == 2200);
    menu = 0; unchanged(sun, 1600);   /* back to the game's at once: nothing cached */

    /* A frame where the game asks for more keeps the game's (raise only); the register's upper half stays zero. */
    menu = 1; CHECK(after(sun, 3072) == 3072); CHECK(after(sun, 2400) == 2400);
    { Ctx c = input(sun, 1000); menu = 2; site(&c); CHECK(c.x[23] == 3072); }

    /* Only x23 changes. */
    { menu = 2; Ctx c = input(sun, 1600), expected = c; expected.x[23] = 3072; site(&c); CHECK(!memcmp(&c, &expected, sizeof c)); }

    /* Another object, or none, keeps its size. */
    menu = 2; unchanged(other, 1600); unchanged(0, 1600);
    CHECK(!memcmp(objects, before, sizeof objects));
    puts("PASS: shadow resolution: the sun's object only, raise only, live changes, register preservation");
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(InstallTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
    host = (ROOT / "host/oot_shadow.c").read_text(encoding="utf-8")
    body = "".join(line for line in host.splitlines(keepends=True) if not line.startswith("#include"))
    with tempfile.TemporaryDirectory(prefix="oot-shadow-") as temporary:
        source = Path(temporary) / "fixture.c"
        executable = Path(temporary) / "fixture.exe"
        source.write_text(HEAD + body + MAIN.replace("SITE_C", oot_shadow.HOOK), encoding="utf-8")
        subprocess.run([args.cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(executable)], check=True)
        subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    main()
