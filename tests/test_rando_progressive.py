"""The randomizer's Progressive items setting: no game data.

An upgrade found gives the next of its family that Link has not. The game's side does it where a content enters the
pouch (host/hos_main.c hos_oot_pouch_add, called at the start of the pouch manager's add by nx2/oot_patches.py); the
seed's side makes the rules ask for the ones under an upgrade too (tools/rando/rando_seed.py progressive_need).

- the rules: an upgrade asked for brings the ones under it that the seed shuffles, and no others; a rule without
  one is as it was;
- the script reads the setting, names it in the seed's stamp, and passes every rule through it;
- the patch: the hook is the first line of the pouch manager's add, once, with its declaration; made again it is
  the same; a source without the function is left;
- the game's side: the families are whole (each of the script's is one of the game's, in its order), the setting is
  read with the randomizer on, the name is given in a view of the host's own and not written over, and the settings'
  table has the row.

    python -I -B tests/test_rando_progressive.py
"""
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rando_seed", ROOT / "tools" / "rando" / "rando_seed.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)
sys.path.insert(0, str(ROOT / "nx2"))
import oot_patches   # noqa: E402


def check(ok, what):
    if not ok:
        raise SystemExit("FAIL: " + what)


def main():
    # ---- the rules ----
    BR, SG, GG, WM, WL = seed.BR, seed.SG, seed.GG, seed.WM, seed.WL
    everything = seed.PROGRESSION | seed.QUEST_GATES | seed.SHOP_GATES
    need = seed.progressive_need
    check(need({SG, seed.S}, everything) == {SG, BR, seed.S} and need({GG}, everything) == {GG, SG, BR} and need({WL}, everything) == {WL, WM},
          "an upgrade asked for does not bring the ones under it")
    check(need({GG}, seed.PROGRESSION) == {GG, SG} and need({WL}, seed.PROGRESSION) == {WL},
          "an upgrade the seed does not shuffle is asked for: the rules count on it where the game has it")
    check(need({BR, WM, seed.BB}, everything) == {BR, WM, seed.BB} and need(seed.NONE, everything) == seed.NONE and isinstance(need({SG}, everything), frozenset),
          "a rule without an upgrade over another is changed")
    check(all(len(t) >= 2 and all(i.startswith("Item_") for i in t) for t in seed.PROGRESSIVE_TIERS), "a family of the rules is not two upgrades or more")

    # ---- the script ----
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check('"rando_progressive": 0' in script and '(" progressive 1" if a.progressive else "")' in script and
          'a.progressive = a.progressive or ini["rando_progressive"] != 0' in script,
          "the script does not read the setting, or does not name it in the seed's stamp")
    check("step = (lambda need: progressive_need(need, PROGRESSION)) if a.progressive else (lambda need: need)" in script and
          "needs = {h: step(n) for h, n in needs.items()}" in script and script.count("step(quest_need(skulltula_rule(") == 2,
          "the chests', the gifts' or the Gold Skulltulas' rules are not passed through it")

    # ---- the patch ----
    head = oot_patches.POUCH_HEAD
    source = '#include "a64.h"\nvoid f_8112d570(Ctx *A64_NOESC);\n' + head + "    /* nop/hint */\n}\nvoid f_1(Ctx *__restrict A64_NOESC c) {\n}\n"
    made = oot_patches.patch_pouch_add(source)
    check(made is not None and made.count("hos_oot_pouch_add(c);") == 1 and head + oot_patches.POUCH_HOOK + "    /* nop/hint */" in made and
          made.count("extern void hos_oot_pouch_add(Ctx *c);") == 1, "the hook is not the first line of the pouch manager's add, once, with its declaration")
    check(oot_patches.patch_pouch_add(made) == made, "made again, the hook is there twice")
    check(oot_patches.patch_pouch_add(source.replace("f_8112d570", "f_8112d571")) is None, "a source without the function is changed")
    patches = (ROOT / "nx2" / "oot_patches.py").read_text(encoding="utf-8")
    check('done["progressive items"] = 0' in patches and "pouch = patch_pouch_add(out) if protect_hearts else None" in patches and
          'done["progressive items"] += 1' in patches, "the lift does not make the hook, or does not count it made")

    # ---- the game's side ----
    host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    block = host[host.index("void hos_oot_pouch_add(Ctx *c) {"):host.index("void hos_oot_lift_player(Ctx *c, uint64_t actor) {")]
    rows = re.findall(r"^        \{(\{.*\})\},$", block, re.M)
    families = [[re.findall(r'"([^"]+)"', tier) for tier in re.findall(r"\{([^{}]*)\}", row)] for row in rows]
    check(len(families) == 10 and all(2 <= len(f) <= 3 and all(1 <= len(t) <= 2 for t in f) for f in families),
          "the game's families are not ten of two or three upgrades, each in one or two spellings: %r" % families)
    flat = [name for f in families for t in f for name in t]
    check(len(flat) == len(set(flat)), "an upgrade is in two families, or twice in one")
    for tiers in seed.PROGRESSIVE_TIERS:
        mine = next((f for f in families if tiers[0] in f[0]), None)
        check(mine is not None and all(item in mine[k] for k, item in enumerate(tiers)), "a family of the rules is not one of the game's, in its order: %r" % (tiers,))
    for word in ("Item_BombBag_Small", "Item_Quiver_Large", "Item_BulletBag_Large", "Item_Longshot", "Item_Wallet_Large", "Item_StickBag_Large",
                 "Item_NutBag_Large", "Item_FairyBless_MPDouble"):
        check(word in flat, "the game's families have no %s" % word)
    check("if ((int32_t)c->x[2] <= 0 || !hos_rando_progressive()) return;" in block and "if (level >= tiers) return;" in block and
          "for (int t = tiers - 1; t >= 0 && !level; t--)" in block,
          "a content taken away, or one found with the setting off, is changed; or Link's place in a family is not the highest he carries")
    check("c->x[1] = block + 16;" in block and "memcpy(A64_PTR(block + 96), give, strlen(give) + 1);" in block and "recomp_store8(c, text" not in block,
          "the name is written over where it is, or the call is not given the host's own view of it")
    side = (ROOT / "host" / "oot_rando.c").read_text(encoding="utf-8")
    header = (ROOT / "gpu" / "vk" / "oot_rando.h").read_text(encoding="utf-8")
    check("int hos_rando_progressive(void) { return rando_active && rando.v[OOT_RANDO_PROGRESSIVE] != 0; }" in side and
          'X(PROGRESSIVE, "Progressive items", "rando_progressive", \\' in header, "the setting is not in the table, or is read with the randomizer off")
    print("PASS: Progressive items")


if __name__ == "__main__":
    main()
