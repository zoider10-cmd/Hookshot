"""A Gold Skulltula's bundle with nothing to carry it in (bug 87, host/hos_main.c hos_oot_pickup_room): no game data.

The owner's run 2026-11-19: a Skulltula's Deku Nuts, with no nut bag, could not be picked up, and the Skulltula was back
after leaving the area. The game asks the pouch for room as a pick-up is touched (f_80a94ea0 from the touch update, lr
0x82ea91dc); the host is asked first. hos_oot_pickup_room, oot_bundle_holder and oot_drop_check_near are compiled alone
against a fake pouch and a fake check list:
- nuts and sticks with no bag near their Skulltula's check: the smallest bag is given (once, not again while its add is
  counted), and the game answers (0); with any bag, or the pouch not read (-1), nothing is given;
- bombs, arrows and the scrub's seeds with no holder: taken with nothing given (1); with one, the game answers;
- a bundle that is no check's, far from it, in another map, or collected, and other items: the game answers, nothing given;
- the randomizer off: nothing;
and the patch: the hook is the function's first line, asked from the touch's call only, once, with its declaration.

    python -I -B tests/test_rando_skulltula_bagless.py [--cc gcc]
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
typedef int SRWLOCK;
static void AcquireSRWLockShared(SRWLOCK *l) { (void)l; }
static void ReleaseSRWLockShared(SRWLOCK *l) { (void)l; }
static SRWLOCK oot_checks_lock;
#define OOT_CHECK_NEAR 60.0f
static struct { char item[64], folder[40]; float place[3]; signed char done; } oot_checks[4];
static int oot_check_count;
static char oot_link_map[80];
static float oot_link_place[3];
static int oot_banc_in_folder(const char *banc, const char *folder) {
    const size_t n = strlen(folder);
    return n && !strncmp(banc, folder, n) && (!banc[n] || banc[n] == '_');
}
static int rando_on = 1;
static int hos_rando_on(void) { return rando_on; }
static unsigned char mem[256];   /* (guest memory at 0x90000000: a pointer to the name at 0, the name at 16) */
static uint64_t recomp_load64(Ctx *c, uint64_t a) { (void)c; uint64_t v; memcpy(&v, mem + (a - 0x90000000ULL), 8); return v; }
static uint8_t recomp_load8(Ctx *c, uint64_t a) { (void)c; return mem[a - 0x90000000ULL]; }
static int bags[16];   /* (each holder's count, by its name's place in this list) */
static const char *const names[] = {"Item_NutBag_Small", "Item_NutBag_Medium", "Item_NutBag_Large", "Item_StickBag_Small",
                                    "Item_StickBag_Medium", "Item_StickBag_Large", "Item_BombBag_Small", "Item_BombBag_Medium",
                                    "Item_BombBag_Large", "Item_Quiver_Small", "Item_Quiver_Medium", "Item_Quiver_Large",
                                    "Item_BulletBag_Small", "Item_BulletBag_Medium", "Item_BulletBag_Large"};
static int oot_pouch_count(Ctx *c, const char *name) {
    (void)c;
    for (int i = 0; i < 15; i++) if (!strcmp(name, names[i])) return bags[i];
    return 0;
}
static char given[64];
static int gives;
static int giving_seen;   /* (the add made while the host says it gives a holder: not a check's) */
static int oot_holder_giving;
static int oot_pouch_change(Ctx *c, const char *name, int by) {
    (void)c; (void)by;
    snprintf(given, sizeof given, "%s", name);
    gives++, giving_seen = oot_holder_giving;
    return 0;
}
static void hos_log(const char *f, ...) { (void)f; }
static int64_t clock_now = 1;
static int64_t hos_now_ns(void) { return clock_now; }
@FN@
static int touch(const char *name) {
    Ctx c;
    memset(&c, 0, sizeof c);
    const uint64_t text = 0x90000010ULL;
    memcpy(mem, &text, 8);
    snprintf((char *)mem + 16, sizeof mem - 16, "%s", name);
    c.x[1] = 0x90000000ULL;
    given[0] = 0, gives = 0;
    clock_now += 10000000000LL;   /* (each touch apart from the one before) */
    return hos_oot_pickup_room(&c);
}
static void check_at(int i, const char *item, float x) {
    snprintf(oot_checks[i].item, sizeof oot_checks[i].item, "%s", item);
    snprintf(oot_checks[i].folder, sizeof oot_checks[i].folder, "HyruleCastle");
    oot_checks[i].place[0] = x, oot_checks[i].place[1] = 0, oot_checks[i].place[2] = 0, oot_checks[i].done = 0;
}
int main(void) {
    snprintf(oot_link_map, sizeof oot_link_map, "HyruleCastle_Child");
    check_at(0, "TBox_DekuNutBundle", 3), check_at(1, "Item_BombBundle_Small", 3), check_at(2, "TBox_ArrowBundle_Medium", 3);
    check_at(3, "Item_DekuStickBundle_Small", 3);
    oot_check_count = 4;
    /* nuts with no bag: the smallest given, the game answers */
    CHECK(touch("TBox_DekuNutBundle") == 0 && gives == 1 && !strcmp(given, "Item_NutBag_Small") && giving_seen && !oot_holder_giving);
    CHECK(touch("Item_DekuStickBundle_Small") == 0 && gives == 1 && !strcmp(given, "Item_StickBag_Small"));
    /* not twice while the add is counted */
    {
        Ctx c; memset(&c, 0, sizeof c); c.x[1] = 0x90000000ULL;
        given[0] = 0, gives = 0;
        CHECK(hos_oot_pickup_room(&c) == 0 && gives == 0);
    }
    /* with any bag, or the pouch not read: nothing given */
    for (int i = 0; i < 3; i++) { bags[0] = bags[1] = bags[2] = 0, bags[i] = 1; CHECK(touch("TBox_DekuNutBundle") == 0 && gives == 0); }
    bags[0] = -1, bags[1] = bags[2] = 0;
    CHECK(touch("TBox_DekuNutBundle") == 0 && gives == 0);
    bags[0] = 0;
    /* bombs and arrows with no holder: taken, nothing given; with one, the game answers */
    CHECK(touch("Item_BombBundle_Small") == 1 && gives == 0 && touch("TBox_ArrowBundle_Medium") == 1 && gives == 0);
    bags[7] = 1;
    CHECK(touch("Item_BombBundle_Small") == 0 && gives == 0);
    bags[7] = 0;
    /* not a check's, far, another map, collected, other items: the game answers */
    CHECK(touch("Item_ScrubBusinessSeed") == 0 && touch("Item_BombchuBundle_Small") == 0 && touch("Item_Boomerang") == 0 && gives == 0);
    oot_link_place[0] = 100;
    CHECK(touch("TBox_DekuNutBundle") == 0 && gives == 0 && touch("Item_BombBundle_Small") == 0);
    oot_link_place[0] = 0;
    snprintf(oot_link_map, sizeof oot_link_map, "HyruleCastleTown");
    CHECK(touch("TBox_DekuNutBundle") == 0 && gives == 0);
    snprintf(oot_link_map, sizeof oot_link_map, "HyruleCastle_Child");
    oot_checks[0].done = 1;
    CHECK(touch("TBox_DekuNutBundle") == 0 && gives == 0);
    oot_checks[0].done = 0;
    /* the randomizer off */
    rando_on = 0;
    CHECK(touch("TBox_DekuNutBundle") == 0 && gives == 0 && touch("Item_BombBundle_Small") == 0);
    printf("PASS: a Gold Skulltula's bundle with nothing to carry it in\n");
    return 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    fn = "\n".join(block(host, marker) for marker in (
        "static int oot_bundle_holder(const char *name, const char *const **sizes) {",
        "static int oot_drop_check_near(const char *name) {")) + "\n" + block(
        host, "int hos_oot_pickup_room(Ctx *c) {")
    add = block(host, "int hos_oot_pouch_add(Ctx *c) {")
    if "if (!oot_holder_giving) oot_tracker_item(name);" not in add:
        raise SystemExit("hos_main.c: a holder given for a Skulltula's bundle would be marked as a check")
    sys.path.insert(0, str(ROOT / "nx2"))
    import oot_patches as P   # noqa: E402
    src = '#include "a64.h"\nvoid f_80a94ea0(Ctx *A64_NOESC);\n' + P.ROOM_HEAD + "    /* nop/hint */\n}\n"
    made = P.patch_pickup_room(src)
    if not (made and made.count("hos_oot_pickup_room(c)") == 1 and P.ROOM_HEAD + P.ROOM_HOOK in made and
            "c->x[30] == 0x82ea91dcULL &&" in P.ROOM_HOOK and made.count("extern int hos_oot_pickup_room(Ctx *c);") == 1):
        raise SystemExit("oot_patches.py: the hook is not the first line of f_80a94ea0, from the touch's call only, once")
    if P.patch_pickup_room(made) != made or P.patch_pickup_room(src.replace("f_80a94ea0", "f_80a94ea1")) is not None:
        raise SystemExit("oot_patches.py: the hook is made twice, or made in a file without the function")
    patches = (ROOT / "nx2" / "oot_patches.py").read_text(encoding="utf-8")
    if 'done["pickup room"] = 0' not in patches or 'counts["pickup room"] += 1' not in patches:
        raise SystemExit("oot_patches.py: the lift does not make the hook, or does not count it made")
    with tempfile.TemporaryDirectory(prefix="skulltula-bagless-") as tmp:
        c = Path(tmp) / "fixture.c"
        exe = Path(tmp) / "fixture"
        c.write_text(FIXTURE.replace("@FN@", fn), encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("PASS: a Gold Skulltula's bundle with nothing to carry it in")


if __name__ == "__main__":
    main()
