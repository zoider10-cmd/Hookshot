"""Hints from the Gossip Stones (rando_hints, tools/rando/rando_seed.py choose_hints and hint_line; asked for 2026-11-18):
no game data.

- each hint is said by two stones, and every hint is true of the seed: an item hint names a gating item the shuffle put
  in that area, a way hint an area that holds a gating item, a foolish hint an area that holds none and no token;
- an item is named once, the Dream World never;
- a stone's line keeps its opening tags (the box, the voice, the colour) and says the hint, wrapped;
- the hints move no item: they are on the stamp's second line, the fixes', and chosen by a random of their own;
- the setting is a row of the game's table and the launcher's, and the Tracker's first row shows them.

    python -I -B tests/test_rando_hints.py
"""
import importlib.util
import random
import struct
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


def msbt(lines):
    """a little-endian UTF-8 text file (MSBT) with these {label: bytes} lines: one label group, LBL1 then TXT2"""
    labels = list(lines)
    lbl = bytearray(struct.pack("<I", 1) + struct.pack("<II", len(labels), 12))
    for k, label in enumerate(labels):
        lbl += bytes([len(label)]) + label.encode() + struct.pack("<I", k)
    txt = bytearray(struct.pack("<I", len(labels)) + bytes(4 * len(labels)))
    for k, label in enumerate(labels):
        struct.pack_into("<I", txt, 4 + 4 * k, len(txt))
        txt += lines[label] + b"\0"
    out = bytearray(b"MsgStdBn" + b"\xff\xfe" + b"\0\0" + bytes([0, 3]) + struct.pack("<H", 2) + b"\0\0" + bytes(4) + bytes(10))
    for kind, sec in ((b"LBL1", lbl), (b"TXT2", txt)):
        out += kind + struct.pack("<I", len(sec)) + bytes(8) + sec + b"\xab" * (-len(sec) % 16)
    struct.pack_into("<I", out, 0x12, len(out))
    return bytes(out)


def main():
    S = seed
    gating = frozenset(("Item_Hammer", "Item_Range_Bow", "Item_HoverBoot"))
    held = [("FireTemple", "Item_Hammer", True), ("KokiriForest", "Item_Range_Bow", True), ("KokiriForest", "Item_Rupee", True),
            ("Graveyard", "Item_Rupee", True), ("LakeHylia", S.TOKEN, True), ("DreamWorld", "Item_Rupee", True),
            ("Market", "Item_HoverBoot", False), ("ZoraRiver", "Item_Rupee", False)]
    labels = ["GOSSIP_A_%02d" % k for k in range(12)]
    hints = S.choose_hints(random.Random(1), held, gating, labels)
    said = {}
    for label, words in hints:
        said.setdefault(words, []).append(label)
    check(all(len(v) == S.HINT_STONES for v in said.values()) and len({l for l, _ in hints}) == len(hints),
          "a hint is not said by %d stones, or a stone says two" % S.HINT_STONES)
    check(len(said) <= len(labels) // S.HINT_STONES, "more hints than the stones can say")
    for words in said:
        check("Dream World" not in words, "a hint names the Dream World")
        if "can be found in" in words:
            check(any(words == "They say that %s can be found in %s." % (S.hint_item(i), S.hint_area(a)) for a, i, m in held if m and i in gating),
                  "an item hint is not of a gating item the shuffle put there: %s" % words)
        elif "on the way of the hero" in words:
            check(any(words == "They say that %s is on the way of the hero." % S.hint_area(a) for a, i, _ in held if i in gating),
                  "a way hint names an area without a gating item: %s" % words)
        else:
            check(words.startswith("They say that it is foolish to look in ") and
                  any(words.endswith(S.hint_area(a) + ".") for a in ("Graveyard", "ZoraRiver")),
                  "a foolish hint names an area with a gating item or a token: %s" % words)
    items = [w for w in said if "can be found in" in w]
    check(len(items) == len(set(items)) and not any("Hover Boots" in w for w in items),
          "an item is named twice, or an item that stays where the game has it is named")
    # (a stone's line: its opening tags kept, the words wrapped)
    tags = b"\x0e\x00\x00\x03\x00\x02\x00\x01\x00\x0e\x03\x00\x00\x00\x03\x00\x0f\x00\x00"
    data = msbt({"GOSSIP_A_00": tags + b"Old rumor.", "GOSSIP_RumorCommon_01": b"So?"})
    check(sorted(S.msbt_labels(data)) == ["GOSSIP_A_00", "GOSSIP_RumorCommon_01"], "the text file's labels are not read")
    words = "They say that the Megaton Hammer can be found in the Gerudo Training Ground."
    new = S.hint_line(data, "GOSSIP_A_00", words)
    a, b = S.msbt_text(new, "GOSSIP_A_00")
    line = new[a:b].rstrip(b"\0")
    check(line.startswith(tags) and line[len(tags):].decode().replace("\n", " ") == words and
          all(len(l) <= S.HINT_WIDTH for l in line[len(tags):].decode().split("\n")), "the stone's line lost its tags, or is not the hint wrapped")
    a, b = S.msbt_text(new, "GOSSIP_RumorCommon_01")
    check(new[a:b] == b"So?\0", "another line of the file changed")
    # (the main's wiring)
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check('stamp = stamp[:-1] + " hints %d\\n" % HINTS_VERSION' in script and "hints = choose_hints(random.Random(HINT_RANDOM % seed), held, PROGRESSION, labels)" in script and
          'a.hints = a.hints or ini["rando_hints"] != 0' in script and '"rando_hints": 0' in script,
          "the hints are not on the stamp's second line, not chosen by a random of their own, or the setting is not read")
    check(script.index('stamp = "placement %d%sfixes %d\\n"') < script.index('stamp = stamp[:-1] + " hints %d\\n"'),
          "the hints are not on the fixes' line")
    # (the stone's talk: its first question, the Mask of Truth, leads to the line whatever the answer)
    check("gift_files[HINT_FLOW] = stone_talk_open(was)" in script and 'HINT_TALK, HINT_RUMOR = "Talk", "InitTalk_GossipStone"' in script and
          "struct.pack_into(\"<H\", out, cases + 8 * c + 4, rumor[0])" in script,
          "a stone talked to without the Mask of Truth does not go to its line")
    header = (ROOT / "gpu" / "vk" / "oot_rando.h").read_text(encoding="utf-8")
    launcher = (ROOT / "launcher" / "Launcher.cs").read_text(encoding="utf-8")
    check('X(HINTS, "Gossip Stone hints", "rando_hints",' in header and 'new object[] { "rando_hints", "Gossip Stone hints",' in launcher,
          "the setting is not a row of the game's table or the launcher's")
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
    check('+ "rando_hints.txt";' in menu and "selr.tracker == 0 && !tracker_hints_help.empty() ? tracker_hints_help.c_str() : selr.help;" in menu,
          "the Tracker's first row does not show the hints")
    print("PASS: the Gossip Stones' hints")


if __name__ == "__main__":
    main()
