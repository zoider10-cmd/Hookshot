"""Bombs found with no Bomb Bag add nothing (bug 42, host/hos_main.c oot_bombs_bagless): no game data.

The game's own Bomb Bag with a chest's bombs is not given with the randomizer on, so the bombs that followed made the
inventory's bombs at 0/0, a slot that can't be used. oot_bombs_bagless is compiled alone against a fake pouch:
- bombs, a bomb bundle and a bomb lying in the world add nothing with no bag, and are added with any of the three;
- Bombchus, bomb flowers, other items, a count of 0 and the adds made as a save is loaded are left alone;
- a pouch that can't be read (-1) counts as a bag, so nothing is lost;
and the pouch's add asks it after the tracker's record and a piece's item named, and returns before the add.

    python -I -B tests/test_rando_bomb_bagless.py [--cc gcc]
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))   # (tests/srccut.py: python -I leaves this folder off the path)
from srccut import block   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
typedef struct { uint64_t x[32]; } Ctx;
static int bag[3];
static int oot_pouch_count(Ctx *c, const char *name) {
    (void)c;
    if (!strcmp(name, "Item_BombBag_Small")) return bag[0];
    if (!strcmp(name, "Item_BombBag_Medium")) return bag[1];
    if (!strcmp(name, "Item_BombBag_Large")) return bag[2];
    return 0;
}
@FN@
static int add(const char *name, int count, uint64_t lr) {
    Ctx c;
    memset(&c, 0, sizeof c);
    c.x[3] = (uint64_t)(int64_t)count, c.x[30] = lr;
    return oot_bombs_bagless(&c, name);
}
int main(void) {
    const uint64_t chest = 0x828d50acULL, world = 0x80c8f7e8ULL, load = 0x8112d4b8ULL;
    CHECK(add("Item_Bomb", 20, chest) && add("Item_BombBundle_Small", 5, chest) && add("Obj_Bomb", 1, world));
    CHECK(!add("Item_Bombchu", 10, chest) && !add("Obj_BombFlower_A_01", 1, world) && !add("Item_DekuNut", 5, world));
    CHECK(!add("Item_BombBag_Small", 1, chest));
    CHECK(!add("Item_Bomb", 0, chest) && !add("Item_Bomb", 20, load));
    for (int i = 0; i < 3; i++) {
        bag[0] = bag[1] = bag[2] = 0, bag[i] = 1;
        CHECK(!add("Item_Bomb", 20, chest) && !add("Obj_Bomb", 1, world));
    }
    bag[0] = -1, bag[1] = bag[2] = 0;
    CHECK(!add("Item_Bomb", 20, chest));
    printf("PASS: bombs with no Bomb Bag add nothing\n");
    return 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    fn = block(host, "static int oot_bombs_bagless(Ctx *c, const char *name) {")
    add = block(host, "int hos_oot_pouch_add(Ctx *c) {")
    at = add.index("if (oot_bombs_bagless(c, name)) {")
    if not (add.index("oot_tracker_item(name);") < at < add.index("oot_pickup_qol(c, name);")):
        raise SystemExit("hos_main.c: the bagless bombs are not asked after the tracker's record and before the add")
    if "return 1;" not in add[at:at + 200]:
        raise SystemExit("hos_main.c: bagless bombs are still added")
    with tempfile.TemporaryDirectory(prefix="bomb-bagless-") as tmp:
        c = Path(tmp) / "fixture.c"
        exe = Path(tmp) / "fixture"
        c.write_text(FIXTURE.replace("@FN@", fn), encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
