"""Game-free checks of nx2/text_assets.py, on an authored archive (no game text): python -I -B tests/test_text_assets.py

An edit rewords one string in its own room: the archive keeps its size, the string keeps its tags, and nothing else changes.
A string that is not a wording the edits know is left as it is. host/mods.c asks host/texts.c only when no mod has the file."""
import importlib.util
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("text_assets", ROOT / "nx2" / "text_assets.py")
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)

TAG = b"\x0e\x01\x00\x04\x00\x02\x00\x17\x00"   # (a control tag with a NUL in it: a string does not end at the first NUL)


def msbt(strings):
    """An authored UTF-8 MSBT: strings is [(label, bytes)]"""
    labels = struct.pack("<I", 1) + struct.pack("<II", len(strings), 12)
    for i, (label, _) in enumerate(strings):
        labels += bytes([len(label)]) + label.encode() + struct.pack("<I", i)
    texts, at = b"", 4 + 4 * len(strings)
    offsets = []
    for _, text in strings:
        offsets.append(at + len(texts))
        texts += text + b"\0"
    texts = struct.pack("<I", len(strings)) + struct.pack("<%dI" % len(strings), *offsets) + texts
    body = b""
    for tag, data in ((b"LBL1", labels), (b"TXT2", texts)):
        body += tag + struct.pack("<I", len(data)) + bytes(8) + data
        body += b"\xab" * (-len(body) % 16)
    head = b"MsgStdBn\xff\xfe\0\0\0\x03" + struct.pack("<H", 2) + bytes(2) + struct.pack("<I", 0x20 + len(body))
    return head + bytes(0x20 - len(head)) + body


def sarc(files):
    """An authored SARC: files is [(name, bytes)]"""
    names, entries, data = b"", [], b""
    for name, blob in files:
        data += bytes(-len(data) % 8)
        entries.append((0, 0x01000000 | len(names) // 4, len(data), len(data) + len(blob)))
        names += name.encode() + b"\0"
        names += bytes(-len(names) % 4)
        data += blob
    table = b"SFAT" + struct.pack("<HHI", 12, len(files), 0x65) + b"".join(struct.pack("<IIII", *e) for e in entries)
    table += b"SFNT" + struct.pack("<HH", 8, 0) + names
    base = 0x14 + len(table)
    return b"SARC" + struct.pack("<H", 0x14) + b"\xff\xfe" + struct.pack("<IIHH", base + len(data), base, 0x100, 0) + table + data


HINT = b"Blow into the console's own mic to play." + TAG + b" Then stop."
FILES = [("Other/First.msbt", msbt([("A", b"first"), ("B", b"second")])),
         ("Layout/Guide.msbt", msbt([("Before", b"untouched"), ("Hint", HINT), ("After", b"also untouched")]))]
EDIT = (10, 31, "your microphone")   # ("the console's own mic")
STRINGS = [("Layout/Guide.msbt", "Hint", {T.fingerprint(HINT + b"\0"): EDIT})]


class TextAssetsTests(unittest.TestCase):
    def test_reworded_in_its_own_room(self):
        data = sarc(FILES)
        new, done, left = T.reword(data, STRINGS)
        self.assertEqual((done, left), (["Hint"], []))
        self.assertEqual(len(new), len(data))
        name, start, end = next(e for e in T.sarc_entries(new) if e[0] == "Layout/Guide.msbt")
        strings = T.msbt_strings(new[start:end])
        a, b = strings["Hint"]
        want = b"Blow into your microphone to play." + TAG + b" Then stop."
        self.assertEqual(new[start + a:start + b], want + bytes(len(HINT) + 1 - len(want)))
        changed = [i for i in range(len(data)) if data[i] != new[i]]
        self.assertTrue(changed and all(start + a <= i < start + b for i in changed))   # (nothing outside the string's room)
        self.assertEqual(new[start + strings["After"][0]:start + strings["After"][1]], b"also untouched\0")

    def test_another_wording_is_left_as_it_is(self):
        data = sarc(FILES)
        for strings in ([("Layout/Guide.msbt", "Hint", {"0" * 16: EDIT})],             # (not this text: another version's)
                        [("Layout/Guide.msbt", "No such label", {T.fingerprint(HINT + b"\0"): EDIT})],
                        [("No/Such.msbt", "Hint", {T.fingerprint(HINT + b"\0"): EDIT})]):
            new, done, left = T.reword(data, strings)
            self.assertEqual((new, done, [label for label, _ in left]), (data, [], [strings[0][1]]))
        again, done, left = T.reword(T.reword(data, STRINGS)[0], STRINGS)   # (reworded already: not twice)
        self.assertEqual((done, [label for label, _ in left]), ([], ["Hint"]))

    def test_a_replacement_that_does_not_fit_is_refused(self):
        key = T.fingerprint(HINT + b"\0")
        for edit in ((10, 13, "a much longer microphone"), (10, len(HINT) + 5, ""), (13, 10, "")):
            with self.assertRaises(ValueError):
                T.reword(sarc(FILES), [("Layout/Guide.msbt", "Hint", {key: edit})])

    def test_the_shipped_edits_fit(self):
        for msbt_name, label, edits in T.STRINGS:
            for key, (start, stop, new) in edits.items():
                self.assertRegex(key, "^[0-9a-f]{16}$")
                self.assertLessEqual(len(new.encode()), stop - start, (label, key))   # (never longer than what it replaces)

    def test_a_mod_wins(self):
        mods = (ROOT / "host" / "mods.c").read_text(encoding="utf-8")
        texts = (ROOT / "host" / "texts.c").read_text(encoding="utf-8")
        self.assertIn("hos_prompts_romfs(key, NULL, out, cap) || hos_texts_romfs(key, NULL, out, cap)", mods)
        self.assertEqual(mods.count("hos_texts_romfs(key, "), 1)   # (asked only where no mod has the file)
        self.assertIn("if (mod) return 0;", texts)


if __name__ == "__main__":
    unittest.main()
