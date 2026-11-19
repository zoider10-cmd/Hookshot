"""A shelf of a family shows the tier for what Link has now, not at the map's first opening (bug 69): no game data.

The game opens a map file once a session, so the version the game's side gave then (hos_oot_shelf_map) stayed: the
Silver Scale bought in one shop, another shop's shelf still showed it. The game reads the kept map's actors again at each
entry, and two readers take an actor's name (f_805d7660, f_83b12ea0): nx2/oot_patches.py patch_shelf_actor hands the
name's place to host/hos_main.c hos_oot_shelf_actor, which answers with the shelf's actor for what Link has now.
- the patch, on copies of the two functions' text: each hooked once, after the name is read and before it is kept or
  looked at, with the right register; a second run changes nothing; a function whose text moved is left alone and counted
  so (the build warns);
- the seed writes each map's shelves' actors in shelf_tiers.txt's third field, and the game's side reads it (a seed from
  before, two fields, still reads);
- the game's side's naming, compiled alone: a shelf's own actor is its shuffled item's tier, <shelf>_<k> tier k; another
  shop's actor or a longer name is no shelf; the tier wanted follows the family's level, the shelf's own when the family
  is whole, none before the pouch is read.

    python -I -B tests/test_rando_shelf_tier_now.py [--cc gcc]
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))   # (tests/srccut.py: python -I leaves this folder off the path)
from srccut import block   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def check(ok, why):
    if not ok:
        print("FAIL: %s" % why)
        sys.exit(1)


FIXTURE = r'''#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
#define OOT_FAMILIES 2
static const char *const oot_families[OOT_FAMILIES][3][2] = {
    {{"Item_Range_Bow", "Weapon_Range_Bow"}, {"Item_Quiver_Medium", NULL}, {"Item_Quiver_Large", NULL}},
    {{"Item_Scale_Silver", NULL}, {"Item_Scale_Gold", NULL}, {NULL, NULL}},
};
static volatile int oot_family_level[OOT_FAMILIES + 1] = {-1, -1, -1};
static int oot_family_of(const char *name, int *spelling) {
    (void)spelling;
    for (int f = 0; f < OOT_FAMILIES; f++)
        for (int t = 0; t < 3; t++)
            for (int a = 0; a < 2; a++)
                if (oot_families[f][t][a] && !strcmp(oot_families[f][t][a], name)) return f;
    return -1;
}
@FNS@
int main(void) {
    oot_tier_shelf_add("Shop_Rando_zora_4", "Item_Range_Bow");        /* (own tier 0) */
    oot_tier_shelf_add("Shop_Rando_general_2", "Item_Scale_Gold");    /* (own tier 1) */
    oot_tier_shelf_add("Shop_Rando_zora_4", "Item_Range_Bow");        /* (twice: one entry) */
    oot_tier_shelf_add("Shop_Rando_general_5", "Item_Bottle");        /* (no family: none) */
    CHECK(oot_tier_shelf_count == 2);
    int tier = -1;
    CHECK(oot_tier_shelf_of("Shop_Rando_zora_4", &tier) == 0 && tier == 0);
    CHECK(oot_tier_shelf_of("Shop_Rando_zora_4_2", &tier) == 0 && tier == 2);
    CHECK(oot_tier_shelf_of("Shop_Rando_general_2", &tier) == 1 && tier == 1);
    CHECK(oot_tier_shelf_of("Shop_Rando_general_2_0", &tier) == 1 && tier == 0);
    CHECK(oot_tier_shelf_of("Shop_Rando_zora_44", &tier) < 0 && oot_tier_shelf_of("Shop_Rando_zora_4_3", &tier) < 0);
    CHECK(oot_tier_shelf_of("Shop_Rando_zora_4_1x", &tier) < 0 && oot_tier_shelf_of("Shop_Rando_zora_5", &tier) < 0);
    CHECK(oot_tier_shelf_want(0) == -1);                  /* (the pouch not read yet) */
    oot_family_level[0] = 1, oot_family_level[1] = 0;
    CHECK(oot_tier_shelf_want(0) == 1 && oot_tier_shelf_want(1) == 0);
    oot_family_level[0] = 3, oot_family_level[1] = 2;     /* (each family whole: the shelf's own item) */
    CHECK(oot_tier_shelf_want(0) == 0 && oot_tier_shelf_want(1) == 1);
    printf("PASS: a shelf's tier for what Link has now\n");
    return 0;
}
'''


def site_source(head, at):
    return '#include "a64.h"\n' + head + "    c->x[1] = 0;\n" + at + " uint64_t _r=_a-_b; }\n}\n"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    sys.path.insert(0, str(ROOT / "nx2"))
    import oot_patches as P   # noqa: E402
    check(len(P.SHELF_ACTOR_SITES) == 2, "not the two name readers")
    for head, at, reg in P.SHELF_ACTOR_SITES:
        src = site_source(head, at)
        out, hooked = P.patch_shelf_actor(src)
        hook = P.SHELF_ACTOR_HOOK % (reg, reg)
        check(hooked == 1 and out.count(hook) == 1, "%s: not hooked once" % head.strip())
        first = at.index("\n") + 1
        check(at[:first] + hook + at[first:] in out, "%s: the hook is not after the name is read and before it is used" % head.strip())
        check(("c->x[%d]" % reg) in at[:first], "%s: the hook's register is not the one the name is read into" % head.strip())
        check("extern uint64_t hos_oot_shelf_actor(Ctx *c, uint64_t name_at);\n" in out, "the host's function is not declared")
        check(P.patch_shelf_actor(out) == (out, 1), "%s: a second run changed the file" % head.strip())
        moved, n = P.patch_shelf_actor(site_source(head, at.replace("87ULL", "88ULL")))
        check(n == 0 and hook not in moved, "%s: a function whose text moved was hooked" % head.strip())
    check(P.patch_shelf_actor('#include "a64.h"\nvoid f_80000000(Ctx *__restrict A64_NOESC c) {\n}\n') is None,
          "a file with neither function was taken")
    src = (ROOT / "nx2" / "oot_patches.py").read_text(encoding="utf-8")
    check('counts["shelf actor hook"] += shelf[1]' in src and 'total["shelf actor hook"] != len(SHELF_ACTOR_SITES)' in src,
          "the hooks are not counted, or a missing one does not warn")
    seed = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check('"%s|%s|%s\\n" % (rel, ",".join(on_sale[actor][0] for actor in held), ",".join(held))' in seed,
          "the seed does not write the shelves' actors in shelf_tiers.txt")
    host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    loader = block(host, "int hos_oot_shelf_map(const char *rel, char *out, size_t cap) {")
    check("char *actors = strchr(bar + 1, '|');" in loader and "oot_tier_shelf_add(actor, maps[count].items[k]);" in loader,
          "the game's side does not read the shelves' actors")
    fns = "\n".join([
        host[host.index("static struct { char actor[48]; int family, own; } oot_tier_shelves[64];"):
             host.index("static void oot_tier_shelf_add(")],
        block(host, "static void oot_tier_shelf_add(const char *actor, const char *item) {"),
        block(host, "static int oot_tier_shelf_of(const char *name, int *tier) {"),
        block(host, "static int oot_tier_shelf_want(int i) {")])
    with tempfile.TemporaryDirectory(prefix="shelf-tier-") as tmp:
        c = Path(tmp) / "fixture.c"
        exe = Path(tmp) / "fixture"
        c.write_text(FIXTURE.replace("@FNS@", fns), encoding="utf-8")
        subprocess.run([a.cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-format-truncation", str(c), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
