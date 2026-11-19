"""The first Deku Nut and Deku Stick bags' "You got" words (bug 48, tools/rando/rando_seed.py first_bag_words, fixes 49):
no game data.

- the first bags get a GetMessage and a GetCaption made from the bigger bag's: in English without "bigger" and "a lot
  more", with the first bag's size; in another language the bigger bag's words as they are; a line the text has is kept;
- every seed adds them (fixes 49), and the game's side no longer keeps the first bags from being shown.

    python -I -B tests/test_rando_first_bag.py
"""
import importlib.util
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


def line(data, label):
    a, b = seed.msbt_text(data, label)
    return bytes(data[a:b]).rstrip(b"\0")


def main():
    S = seed
    tag = b"\x0e\xc9\x00\x0f\x00\x00\x00"
    lines = {
        "Item_NutBag_Small_Name": b"Deku-Nut Bag",
        "Item_NutBag_Medium_GetMessage": b"You got a " + tag + b"bigger " + tag + b"Deku-nut bag!",
        "Item_NutBag_Medium_GetCaption": b"You can carry a lot more " + tag + b"Deku nuts now!\nThis bag fits up to 30 of them!",
        "Item_StickBag_Medium_GetMessage": b"You got a " + tag + b"bigger " + tag + b"Deku-stick bag!",
        "Item_StickBag_Medium_GetCaption": b"You can carry a lot more " + tag + b"Deku sticks now!\nThis bag fits up to 20 of them!",
        "Item_StickBag_Small_GetMessage": b"Kept as it is",
    }
    data, added = S.first_bag_words(msbt(lines), True)
    check(added == 3, "not the three lines missing were added (%d)" % added)
    check(line(data, "Item_NutBag_Small_GetMessage") == b"You got a " + tag + tag + b"Deku-nut bag!" and
          line(data, "Item_NutBag_Small_GetCaption") == b"You can carry " + tag + b"Deku nuts now!\nThis bag fits up to 20 of them!" and
          line(data, "Item_StickBag_Small_GetCaption") == b"You can carry " + tag + b"Deku sticks now!\nThis bag fits up to 10 of them!",
          "the English words are not the bigger bag's without 'bigger', with the first bag's size")
    check(line(data, "Item_StickBag_Small_GetMessage") == b"Kept as it is" and line(data, "Item_NutBag_Small_Name") == b"Deku-Nut Bag",
          "a line the text had was changed")
    other, added = S.first_bag_words(msbt(lines), False)
    check(added == 3 and line(other, "Item_NutBag_Small_GetMessage") == lines["Item_NutBag_Medium_GetMessage"],
          "another language's first bag does not take the bigger bag's words as they are")
    again, added = S.first_bag_words(data, True)
    check(added == 0 and again == data, "a second run added lines again")
    check(S.FIXES_VERSION >= 49, "the seeds are not written again with the words (fixes 49)")
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check("text, added = first_bag_words(parts[SHOP_TEXT], n.startswith(FIRST_BAG_ENGLISH))" in script,
          "the seed does not add the words in every archive")
    host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    no_show = host[host.index("static const char *const oot_no_show[]"):]
    no_show = no_show[:no_show.index(";")]
    check("NutBag" not in no_show and "StickBag" not in no_show, "the game's side still keeps the first bags from being shown")
    print("PASS: the first bags' \"You got\" words")


if __name__ == "__main__":
    main()
