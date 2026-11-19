"""Zelda's Letter shuffled (rando_letter, tools/rando/rando_seed.py letter_need and LETTER_GIFT; asked for 2026-11-15):
no game data.

- a child's check on Death Mountain asks for the letter, or bombs (the Lost Woods' way to Goron City), or the Bolero
  when the songs are shuffled; a way that asks for bombs already, or for the letter, is as it was; elsewhere nothing
  changes;
- the letter is a gift of Zelda's meeting (her flow's get event, as Darunia's), kept behind the Deku Tree's story,
  never a Gold Skulltula's or a piece's, with letters for the Tracker and a row of the Inventory;
- the setting is read, on the stamp's first line (a new seed), and a row of the game's table and the launcher's.

    python -I -B tests/test_rando_letter.py
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rando_seed", ROOT / "tools" / "rando" / "rando_seed.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


def check(ok, why):
    if not ok:
        print("FAIL: %s" % why)
        sys.exit(1)


def main():
    S = seed
    child = S.CHILD | {S.ZL}
    made = S.letter_need(child, "GoronCity")
    check(isinstance(made, S.Either) and set(made) == {child | {S.LETTER}, child | {S.BB}},
          "a child's check in Goron City does not ask for the letter or bombs: %r" % (made,))
    made = S.letter_need(child, "DeathMountainTrail", bolero=True)
    check(set(made) == {child | {S.LETTER}, child | {S.BB}, child | {S.LETTER_BOLERO}}, "the Bolero is not a way with the songs shuffled")
    check(S.letter_need(S.ADULT, "DeathMountainCrater") == S.ADULT and S.letter_need(S.CHILD | {S.BB}, "DodongoCavern") == S.CHILD | {S.BB},
          "a way with bombs (an adult's among them) was changed")
    check(S.letter_need(child, "KakarikoVillage") == child and S.letter_need(child, "HyruleField") == child,
          "a check below the gate asks for the letter")
    two = S.either([S.CHILD, S.ADULT])
    made = S.letter_need(two, "GoronCity")
    check(S.ADULT in made and S.CHILD | {S.LETTER} in made and S.CHILD | {S.BB} in made, "a rule of two ways is not stepped way by way")
    g = S.LETTER_GIFT
    check(g.flow == "Dm_HrlCastle_0050" and g.olds == (S.LETTER,) and g.item == S.LETTER and g.key in S.DEKU_STORY and
          g.key in S.GIFT_PLACES, "the letter is not the gift of Zelda's meeting, kept behind the Deku Tree's story, with a place")
    check(S.LETTER in S.SKULLTULA_NEVER and S.LETTER in S.PIECE_NEVER and S.CHECK_CODES.get(S.LETTER) == "LE",
          "the letter may be a Skulltula's or a piece's, or has no Tracker letters")
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check('a.letter = a.letter or ini["rando_letter"] != 0' in script and '(" letter 1" if a.letter else "")' in script and
          "PROGRESSION = PROGRESSION | {LETTER}" in script and "needs = {h: gate(n, spots[h][0]) for h, n in needs.items()}" in script and
          "lambda need, h, area: gate(need, area))" in script and "lambda need, h, area: gate(forest(need, area), area))" in script,
          "the setting is not read, not on the stamp's first line, or the rules of the chests, Skulltulas and pieces are not stepped")
    header = (ROOT / "gpu" / "vk" / "oot_rando.h").read_text(encoding="utf-8")
    launcher = (ROOT / "launcher" / "Launcher.cs").read_text(encoding="utf-8")
    items = (ROOT / "gpu" / "vk" / "oot_cheat_items.h").read_text(encoding="utf-8")
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
    check('X(LETTER, "Zelda\'s Letter", "rando_letter",' in header and 'new object[] { "rando_letter", "Zelda\'s Letter",' in launcher and
          'OOT_ITEM("Zelda\'s Letter", "Item_ZeldaLetter", 0)' in items and '{"LE", "Zelda\'s Letter", {"Zelda\'s Letter"}},' in menu,
          "the setting, the Inventory's row or the Tracker's letters are missing")
    check(items.index('OOT_ITEM("Gold Skulltula Tokens"') < items.index('OOT_ITEM("Zelda\'s Letter"'),
          "the letter's row is not the table's last (the rows before keep their numbers: the debug cheats name items by them)")
    print("PASS: Zelda's Letter shuffled")


if __name__ == "__main__":
    main()
