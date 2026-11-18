"""The randomizer's Ammo pick-ups and Rupees fill the wallet settings (host/hos_main.c oot_pickup_qol): no game data.

- the settings: their rows in gpu/vk/oot_rando.h (appended: a setting's place is its place in a seed ID), the seed
  tool's defaults, and the game's side reading them (with the test switches HOS_OOT_AMMO and HOS_OOT_RUPEE_FILL);
- a pick-up from the world's pick-up path alone (0x80c8f7e8: seen without a window for Hyrule Field's Deku Nut and a
  blue rupee), not a chest's or a shop's;
- ammo: 5 each raises the add's count; Fill the bag fills it as a bag found is, without giving a bag Link has not;
  the bomb's name is the pick-up's alone (Obj_Bomb, not the bomb flowers);
- rupees: the wallet filled as a wallet found is.

    python -I -B tests/test_rando_pickup_qol.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(ok, why):
    if not ok:
        print("FAIL: %s" % why)
        sys.exit(1)


def main():
    header = (ROOT / "gpu" / "vk" / "oot_rando.h").read_text(encoding="utf-8")
    rows = header[header.index("#define OOT_RANDO_SETTINGS(X)"):header.index("enum {")]
    check(rows.index("X(OPEN_DOOR,") < rows.index("X(AMMO_PICKUPS,") < rows.index("X(RUPEE_FILL,") and
          '"As the game has it", "5 each", "Fill the bag")' in rows,
          "the two settings are not appended after the others, or Ammo pick-ups has not its three choices")
    seed = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check('"rando_ammo_pickups": 0, "rando_rupee_fill": 0}' in seed, "the seed tool does not know the two settings' keys")
    rando = (ROOT / "host" / "oot_rando.c").read_text(encoding="utf-8")
    check("rando.v[OOT_RANDO_AMMO_PICKUPS]" in rando and "rando.v[OOT_RANDO_RUPEE_FILL]" in rando and
          'getenv("HOS_OOT_AMMO")' in rando and 'getenv("HOS_OOT_RUPEE_FILL")' in rando,
          "the game's side does not read the two settings")
    host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    body = host[host.index("static void oot_pickup_qol(Ctx *c, const char *name) {"):]
    body = body[:body.index("\n}\n")]
    check("if (c->x[30] != 0x80c8f7e8ULL || (int32_t)c->x[3] <= 0) return;" in body,
          "a pick-up is not told by the world's pick-up path: a chest's or a shop's would be changed too")
    check("if (ammo == 1 && (int32_t)c->x[3] < 5) {" in body and "c->x[3] = 5;" in body and
          "oot_fill_start(oot_pickup_ammo[k][1], name);" in body,
          "5 each does not raise the count, or Fill the bag does not fill")
    check('(!strcmp(oot_pickup_ammo[k][0], "Obj_Bomb") && strcmp(name, "Obj_Bomb"))' in body,
          "a bomb flower or another Obj_Bomb... name is taken for the bomb pick-up")
    start = host[host.index("static void oot_fill_start(const char *holds, const char *why) {"):]
    check("oot_fill_bagged[k] = 1;" in start[:start.index("\n}\n")], "a pick-up's fill may give a bag Link has not")
    check('if (hos_rando_rupee_fill() && !strncmp(name, "Obj_Rupee_", 10)) oot_fill_start(OOT_FILL_RUPEES, name);' in body,
          "a rupee picked up does not fill the wallet")
    add = host[host.index("int hos_oot_pouch_add(Ctx *c) {"):]
    check(add.index("oot_tracker_item(name);") < add.index("oot_pickup_qol(c, name);") < add.index("if ((int32_t)c->x[3] <= 0) return 0;"),
          "the pick-ups' settings are not applied in the pouch's add")
    print("PASS: ammo pick-ups and rupees fill the wallet")


if __name__ == "__main__":
    main()
