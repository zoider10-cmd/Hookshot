"""The randomizer's Ganon's Castle bridge setting (host/hos_main.c oot_ganon_bridge): no game data.

- the setting: its row in gpu/vk/oot_rando.h (appended: a setting's place is its place in a seed ID) with its three
  choices, the launcher's row, the seed tool's default, and the game's side reading it (the test switch
  HOS_OOT_GANON_BRIDGE);
- oot_ganon_bridge compiled alone against a fake list of flags and pouch:
  - As the game has it: the quest Step_Defeat_Ganon is never touched;
  - Open: NotReady becomes Ready (the bridge's own scene then plays at the castle's edge and moves it on);
  - Medallions: the bridge made once as many are held as the setting Bridge medallions asks (6 by default; 4 tried),
    not with one fewer;
  - a step past Ready is left alone, and if the game sets it back to Ready after the bridge's scene has played (the
    sages' scene would), the step it had is put back (or Step01 when none was seen this session);
  - the quest is looked at once a second, not every frame.

    python -I -B tests/test_rando_ganon_bridge.py [--cc gcc]
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))   # (tests/srccut.py: python -I leaves this folder off the path)
from srccut import block, between   # noqa: E402

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
typedef struct { int unused; } Ctx;
static int mode, played, held[6], sets, logs, need = 6;
static uint32_t quest;
int hos_rando_ganon_bridge(void) { return mode; }
int hos_rando_bridge_medallions(void) { return need; }
static void hos_log(const char *fmt, ...) { (void)fmt; logs++; }
static int oot_gamedata_enum(Ctx *c, uint32_t hash, uint32_t *value, int set) {
    (void)c;
    if (hash != 0x746f47c0u) return 0;
    if (set) quest = *value, sets++;
    else *value = quest;
    return 1;
}
static int oot_gamedata_bool(Ctx *c, uint32_t hash, int *value) {
    (void)c, (void)hash;
    *value = played;
    return 1;
}
static int oot_gamedata_set_bool(Ctx *c, uint32_t hash, int value) {   /* (the bridge's scene marked played) */
    (void)c, (void)hash;
    played = value;
    return 1;
}
static int oot_pouch_count(Ctx *c, const char *name) {
    (void)c;
    static const char *const names[6] = {"Item_Medal_Forest", "Item_Medal_Fire", "Item_Medal_Water",
                                         "Item_Medal_Shadow", "Item_Medal_Spirit", "Item_Medal_Light"};
    for (int i = 0; i < 6; i++)
        if (!strcmp(name, names[i])) return held[i];
    return -1;
}
@DEFINES@
@FN@
#define NOTREADY 0x57b849f0u
#define READY 0x17bfaa46u
#define STEP01 0xeb62add9u
#define STEP06 0x2d7a0bb3u   /* (any step past Ready) */
static int64_t t;
static void second(Ctx *c) { t += 1000000000LL; oot_ganon_bridge(c, t); }
int main(void) {
    Ctx c = {0};
    /* As the game has it: nothing */
    quest = NOTREADY, mode = 0;
    second(&c), second(&c);
    CHECK(quest == NOTREADY && sets == 0 && !played);
    /* Open: the bridge made at once, as its scene leaves it: the scene played, the quest at Step01 (2026-11-20: Ready
       alone never brought the scene) */
    mode = 1;
    second(&c);
    CHECK(quest == STEP01 && played && sets == 1 && logs == 2);   /* (the step read, then the bridge made) */
    /* once a second: a call in the same second does nothing, even with the quest put back */
    quest = NOTREADY, played = 0;
    oot_ganon_bridge(&c, t + 1);
    CHECK(quest == NOTREADY && sets == 1);
    /* Ready with the scene not played (a save from before): made too */
    quest = READY;
    second(&c);
    CHECK(quest == STEP01 && played && sets == 2);
    /* past it, further: left alone */
    quest = STEP06, second(&c);
    CHECK(quest == STEP06 && sets == 2);
    /* the game sets it back to Ready after the scene: the step it had is put back */
    quest = READY, played = 1;
    second(&c);
    CHECK(quest == STEP06 && sets == 3);
    /* Medallions at six: not with five, yes with six */
    mode = 2;
    quest = NOTREADY, played = 0;
    for (int i = 0; i < 5; i++) held[i] = 1;
    second(&c);
    CHECK(quest == NOTREADY && sets == 3 && !played);
    held[5] = 1;
    second(&c);
    CHECK(quest == STEP01 && played && sets == 4);
    /* (the owner's test 2026-11-19) a new game's quest holds no step yet (0): Open still makes the bridge */
    mode = 1, quest = 0, played = 0;
    second(&c);
    CHECK(quest == STEP01 && played && sets == 5);
    /* Medallions at four (Bridge medallions): not with three, yes with four */
    mode = 2, need = 4, quest = NOTREADY, played = 0;
    for (int i = 0; i < 6; i++) held[i] = i < 3;
    second(&c);
    CHECK(quest == NOTREADY && sets == 5 && !played);
    held[3] = 1;
    second(&c);
    CHECK(quest == STEP01 && played && sets == 6);
    printf("PASS: Ganon's Castle bridge\n");
    return 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    header = (ROOT / "gpu" / "vk" / "oot_rando.h").read_text(encoding="utf-8")
    rows = header[header.index("#define OOT_RANDO_SETTINGS(X)"):header.index("enum {")]
    check(rows.index("X(SKULLTULAS_DAY,") < rows.index("X(GANON_BRIDGE,") and
          '"As the game has it", "Open", "Medallions")' in rows and
          rows.index("X(CHEST_SIZE,") < rows.index("X(BRIDGE_MEDALLIONS,") and '"6", "5", "4", "3")' in rows,
          "the bridge's setting is not appended after the others, or has not its three choices")
    launcher = (ROOT / "launcher" / "Launcher.cs").read_text(encoding="utf-8")
    check('"rando_ganon_bridge", "Ganon\'s Castle bridge", new[] { "As the game has it", "Open", "Medallions" }, new[] { 0, 1, 2 }'
          in launcher and '"rando_bridge_medallions", "Bridge medallions", new[] { "6", "5", "4", "3" }, new[] { 0, 1, 2, 3 }' in launcher,
          "the launcher has no row for the bridge's settings")
    seed = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check('"rando_ganon_bridge": 0' in seed, "the seed tool does not know the setting's key")
    rando = (ROOT / "host" / "oot_rando.c").read_text(encoding="utf-8")
    check("rando.v[OOT_RANDO_GANON_BRIDGE]" in rando and 'getenv("HOS_OOT_GANON_BRIDGE")' in rando and
          "rando.v[OOT_RANDO_BRIDGE_MEDALLIONS]" in rando,
          "the game's side does not read the setting")
    host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    fn = block(host, "static void oot_ganon_bridge(Ctx *c, int64_t now) {")
    fn = fn.replace("    int hos_rando_ganon_bridge(void);   /* host/oot_rando.c */\n", "")
    fn = fn.replace("    int hos_rando_bridge_medallions(void);   /* host/oot_rando.c: 6 to 3 (the setting Bridge medallions) */\n", "")
    defines = between(host, "#define OOT_STEP_DEFEAT_GANON", "static void oot_ganon_bridge(")
    check("    oot_time_door(c, now, actor);\n    oot_ganon_bridge(c, now);\n" in host,
          "the bridge is not looked at with the Door of Time, each frame of play")
    with tempfile.TemporaryDirectory(prefix="ganon-bridge-") as tmp:
        c = Path(tmp) / "fixture.c"
        exe = Path(tmp) / "fixture"
        c.write_text(FIXTURE.replace("@DEFINES@", defines).replace("@FN@", fn), encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", str(c), "-o", str(exe)],
                       check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
