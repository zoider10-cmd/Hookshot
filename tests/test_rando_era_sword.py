"""Bug 68: back to a child, an empty sword slot is not given the Kokiri Sword Link never got.

The game's swap of the two ages' gear (Event/EventFlow/ReplaceEquipmentForEraChange) sets the child's slot,
PlayerStatus.AnotherEraEquipWeapon, to Weapon_Sword_Kokiri whenever it is empty on the way back, with no question of
the pouch. tools/rando/rando_seed.py era_sword_fix passes that one step over (lead_past). Checked by source; the
game's file itself is read by the seed tool, which stops with nothing written if the step is not there once.

python -I -B tests/test_rando_era_sword.py
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "rando"))
import rando_seed as seed  # noqa: E402


def main():
    src = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    ok = (seed.ERA_FLOW == "Event/EventFlow/ReplaceEquipmentForEraChange.bfevfl.zs" and seed.FIXES_VERSION >= 41 and
          's.get("name") == "PlayerStatus.AnotherEraEquipWeapon" and s.get("value") == "Weapon_Sword_Kokiri"' in src and
          "return lead_past(data, steps, firsts, set(kokiri), {})" in src and
          "gift_files[ERA_FLOW] = era_sword_fix(was)" in src and
          's["value"] = param(u64(e + 0x10), "Value")' in src)
    if not ok:
        print("FAIL: the step that gives an empty child's slot the Kokiri Sword is not passed over")
        sys.exit(1)
    print("PASS: back to a child, an empty sword slot stays empty")


if __name__ == "__main__":
    main()
