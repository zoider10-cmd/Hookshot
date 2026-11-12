"""Deku Scrubs: the Business Scrubs' one-time sales take part with the chests (tools/rando/rando_seed.py: SCRUBS,
flow_reach, gift_items with an entry point).

Checked here, without the game, on a made-up flow of two entry points:
- an entry point's events are the ones it comes to by every branch (an action's next, a switch's cases, a fork's
  branches and its join, a sub-flow call's next), and no others; a name the flow has not is an error;
- a swap of one entry point changes only that entry point's calls: two sales that name the same item (the scrubs' two
  Pieces of Heart) are told apart, each sells its own new item, and a plain swap of the same flow still works beside
  them; a key that is not found is not said to be;
- the table: four sales, each of the scrubs' flow and of an entry point, waiting for the Deku Scrubs setting and not
  for Quest rewards; no two of one entry point name the same item; the upgrades put the bigger size in the pool
  (Quest rewards' Forest Stage puts in the middle ones);
- a scrub's words (scrub_words), on a made-up text file: the words before a sale line's price are made the plain
  ones, with spaces to the same length, so the file keeps its size; the tags the line starts with, the price, its
  tags and the question are as they were, and so is every other line; done again it changes nothing; a line with no
  room, a line without a price and a label the file has not are errors;
- the script reads the setting, names it in the seed's stamp, and gives the scrubs their place among the chests with
  or without Quest rewards.

    python -I -B tests/test_rando_scrubs.py
"""
import collections
import importlib.util
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rando_seed", ROOT / "tools" / "rando" / "rando_seed.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


def check(ok, what):
    if not ok:
        raise SystemExit("FAIL: " + what)


def flow(events, entries):
    """A BFEVFL file of one flowchart. events: [(kind, next, extra, the string parameter or None)]: kind 0 an action,
    1 a switch (extra: its cases' events), 2 a fork (extra: its branches; next: its join), 3 a join, 4 a sub-flow
    call. entries: [(name, its first event)]. Returns (the bytes, {event: where its parameter's pointer is})."""
    out = bytearray(b"BFEVFL" + bytes(0x2a))
    struct.pack_into("<H", out, 0x20, 1)
    table = len(out)
    out += bytes(8)
    chart = len(out)
    struct.pack_into("<Q", out, 0x28, table)
    struct.pack_into("<Q", out, table, chart)
    out += b"EVFL" + bytes(0x44)
    struct.pack_into("<H", out, chart + 0x16, len(events))
    struct.pack_into("<H", out, chart + 0x18, len(entries))
    at_events = len(out)
    out += bytes(len(events) * 0x30)
    struct.pack_into("<Q", out, chart + 0x30, at_events)

    def string(value):
        at = len(out)
        out.extend(struct.pack("<H", len(value)) + value.encode() + b"\0")
        out.extend(bytes(-len(out) % 8))
        return at

    pointers = {}
    for i, (kind, nxt, extra, value) in enumerate(events):
        e = at_events + 0x30 * i
        out[e + 8] = kind
        if kind in (0, 3, 4):
            struct.pack_into("<H", out, e + 0x0a, nxt)
        if kind == 1:
            cases = len(out)
            for c in extra:
                out.extend(struct.pack("<IHH", 0, c, 0))
            struct.pack_into("<H", out, e + 0x0a, len(extra))
            struct.pack_into("<Q", out, e + 0x18, cases)
        if kind == 2:
            forks = len(out)
            for c in extra:
                out.extend(struct.pack("<H", c))
            out.extend(bytes(-len(out) % 8))
            struct.pack_into("<H", out, e + 0x0a, len(extra))
            struct.pack_into("<H", out, e + 0x0c, nxt)
            struct.pack_into("<Q", out, e + 0x10, forks)
        if value is not None:
            text = string(value)
            item = len(out)
            out.extend(bytes([5, 0]) + struct.pack("<H", 1) + bytes(12) + struct.pack("<Q", text))
            container = len(out)
            out.extend(bytes([1, 0]) + struct.pack("<H", 1) + bytes(12) + struct.pack("<Q", item))
            struct.pack_into("<Q", out, e + 0x10, container)
            pointers[i] = item + 0x10
    names = len(out)   # (the entry points' dictionary: a root node, then one of 16 bytes each, its name's pointer at +8)
    out.extend(bytes(8 + 16))
    for name, _ in entries:
        node = len(out)
        out.extend(bytes(16))
        struct.pack_into("<Q", out, node + 8, 0)   # (filled below: the strings come after the nodes)
    for k, (name, _) in enumerate(entries):
        struct.pack_into("<Q", out, names + 8 + 16 * (k + 1) + 8, string(name))
    table2 = len(out)
    for name, first in entries:
        out.extend(bytes(0x1c) + struct.pack("<H", first) + bytes(2))
    struct.pack_into("<Q", out, chart + 0x38, names)
    struct.pack_into("<Q", out, chart + 0x40, table2)
    struct.pack_into("<I", out, 0x1c, len(out))
    return bytes(out), pointers


def text_file(lines):
    """A text file (MSBT, UTF-8) of the lines [(label, its bytes)], each label in a group of its own."""
    lbl = struct.pack("<I", len(lines))
    at = 4 + 8 * len(lines)
    names = b""
    for i, (label, _) in enumerate(lines):
        lbl += struct.pack("<II", 1, at + len(names))
        names += bytes([len(label)]) + label.encode() + struct.pack("<I", i)
    lbl += names
    txt = struct.pack("<I", len(lines))
    at = 4 + 4 * len(lines)
    body = b""
    for _, raw in lines:
        txt += struct.pack("<I", at + len(body))
        body += raw + b"\0"
    txt += body
    out = bytearray(b"MsgStdBn" + b"\xff\xfe" + bytes(2) + bytes([0, 3]) + struct.pack("<H", 2) + bytes(0x10))
    for kind, sec in ((b"LBL1", lbl), (b"TXT2", txt)):
        out += kind + struct.pack("<I", len(sec)) + bytes(8) + sec + bytes(-len(sec) % 16)
    struct.pack_into("<I", out, 0x12, len(out))
    return bytes(out)


def given(data, pointer):
    at = struct.unpack_from("<Q", data, pointer)[0]
    return data[at + 2:at + 2 + struct.unpack_from("<H", data, at)[0]].decode()


def main():
    NONE = 0xFFFF
    events = [
        (1, 0, [1, 2], None),                  # 0: "Pouch" starts: a switch to 1 or 2
        (4, 5, None, "Obj_Heart_Piece"),       # 1: a sale of a Piece of Heart
        (4, 5, None, "Item_StickBag_Medium"),  # 2: a sale of the stick upgrade
        (2, 7, [4, 6], None),                  # 3: "Secret" starts: a fork to 4 and 6, joined at 7
        (4, NONE, None, "Obj_Heart_Piece"),    # 4: the other sale of a Piece of Heart
        (0, NONE, None, None),                 # 5: an action both of Pouch's sales go on to
        (0, NONE, None, None),                 # 6: the fork's other branch
        (3, 8, None, None),                    # 7: the join
        (4, NONE, None, "Item_Other"),         # 8: a call after the join
        (4, NONE, None, "Obj_Heart_Piece"),    # 9: a call no entry point comes to
    ]
    data, pointers = flow(events, [("Pouch", 0), ("Secret", 3)])
    check(seed.flow_reach(data, "Pouch") == {0, 1, 2, 5} and seed.flow_reach(data, "Secret") == {3, 4, 6, 7, 8},
          "an entry point's events are not the ones it comes to: %r, %r" % (seed.flow_reach(data, "Pouch"), seed.flow_reach(data, "Secret")))
    try:
        seed.flow_reach(data, "NoSuch")
        check(False, "an entry point the flow has not is taken")
    except ValueError:
        pass
    new, found = seed.gift_items(data, {("Pouch", "Obj_Heart_Piece"): "Item_Bow", ("Secret", "Obj_Heart_Piece"): "TBox_Rupee_Red",
                                        ("Pouch", "Item_StickBag_Medium"): "Obj_Heart_Piece", "Item_Other": "Item_Hammer"})
    got = {i: given(new, p) for i, p in pointers.items()}
    check(got == {1: "Item_Bow", 2: "Obj_Heart_Piece", 4: "TBox_Rupee_Red", 8: "Item_Hammer", 9: "Obj_Heart_Piece"},
          "the two sales of one item are not told apart by their entry points: %r" % got)
    check(found == {("Pouch", "Obj_Heart_Piece"), ("Secret", "Obj_Heart_Piece"), ("Pouch", "Item_StickBag_Medium"), "Item_Other"},
          "the swaps found are not the ones made: %r" % (found,))
    check(struct.unpack_from("<I", new, 0x1c)[0] == len(new) and seed.flow_reach(new, "Secret") == {3, 4, 6, 7, 8}, "the changed flow is not whole")
    _, found = seed.gift_items(data, {("Secret", "Item_StickBag_Medium"): "X"})
    check(found == set(), "a sale of another entry point is said to be this one's")
    check(seed.gift_items(data, {"Obj_Heart_Piece": "X"})[1] == {"Obj_Heart_Piece"} and
          [given(seed.gift_items(data, {"Obj_Heart_Piece": "X"})[0], pointers[i]) for i in (1, 4, 9)] == ["X", "X", "X"],
          "a plain swap is no longer every call's")

    # ---- the table ----
    check(len(seed.SCRUBS) == 4 and all(g.flow == seed.SCRUB_FLOW and g.entry and g.when == "scrubs" for g in seed.SCRUBS),
          "the scrubs' sales are not four of their flow, each of an entry point, waiting for their own setting")
    check(len({g.key for g in seed.SCRUBS} | {g.key for g in seed.GIFTS}) == len(seed.SCRUBS) + len(seed.GIFTS) and
          len({seed.gift_hash(g.key) for g in seed.SCRUBS + seed.GIFTS}) == len(seed.SCRUBS) + len(seed.GIFTS),
          "a scrub's sale has a gift's key or hash")
    per_entry = collections.Counter((g.entry, old) for g in seed.SCRUBS for old in g.olds)
    check(max(per_entry.values()) == 1, "two sales of one entry point name the same item: %r" % [k for k, n in per_entry.items() if n > 1])
    for g in seed.SCRUBS:
        check(g.item in g.olds and isinstance(g.need, frozenset) and g.need <= seed.PROGRESSION, "%s: its item or what it asks for" % g.key)
    pool = collections.Counter(g.item for g in seed.SCRUBS + seed.GIFTS)
    check(pool["Item_StickBag_Large"] == 1 and pool["Item_StickBag_Medium"] == 1 and pool["Item_NutBag_Large"] == 1 and pool["Item_NutBag_Medium"] == 1,
          "the stick and nut upgrades are not one of each size between the scrubs and the Forest Stage")
    check(all(g.when != "scrubs" for g in seed.GIFTS), "a gift of Quest rewards waits for the scrubs' setting")

    # ---- a scrub's words ----
    tag = lambda group, kind, payload=b"": b"\x0e" + struct.pack("<HHH", group, kind, len(payload)) + payload
    head = tag(3, 0, b"\x0f\0\0")
    price = b"It's " + tag(0, 3, b"\x02\0") + tag(2, 12, b"SimpleShop_Price") + b" rupees" + tag(0, 3, b"\xff\xff") + b"." + tag(5, 0) + b" Wanna buy it?"
    own = head + b"This bag will allow you to carry more " + tag(201, 15) + b"Deku sticks.\n" + price
    heart = head + b"Ohhh, a " + tag(0, 3, b"\x02\0") + b"Piece of Heart" + tag(0, 3, b"\xff\xff") + b". Shimmery glimmery! " + price
    other = head + b"Squee! Get out of here, then!"
    short = head + b"Hm.\n" + price
    lines = [("Other", other), ("Enemy_Scrub_Business_DekuStickPouch_01", own), ("Short", short), ("Enemy_Scrub_Business_Heart_01", heart)]
    data = text_file(lines)
    for label, raw in lines:
        a, b = seed.msbt_text(data, label)
        check(data[a:b].rstrip(b"\0") == raw, "the line %s is not found where it is" % label)
    new = seed.scrub_words(data, "Enemy_Scrub_Business_DekuStickPouch_01")
    a, b = seed.msbt_text(new, "Enemy_Scrub_Business_DekuStickPouch_01")
    line = new[a:b].rstrip(b"\0")
    words = seed.SCRUB_WORDS.encode()
    check(len(new) == len(data) and line.startswith(head + words) and line.endswith(b"\n" + price) and
          line[len(head) + len(words):-len(price) - 1].strip(b" ") == b"" and b"Deku sticks" not in line,
          "the sale's words are not the plain ones before its price, as long as they were: %r" % line)
    check(all(new[x:y] == data[x:y] for x, y in (seed.msbt_text(data, l) for l in ("Other", "Short", "Enemy_Scrub_Business_Heart_01"))),
          "another line was changed")
    check(seed.scrub_words(new, "Enemy_Scrub_Business_DekuStickPouch_01") is None, "done again, the line changes")
    both = seed.scrub_words(new, "Enemy_Scrub_Business_Heart_01")
    a, b = seed.msbt_text(both, "Enemy_Scrub_Business_Heart_01")
    check(len(both) == len(data) and both[a:b].startswith(head + words) and both[a:b].rstrip(b"\0").endswith(b" " + price) and b"Piece of Heart" not in both[a:b],
          "a line whose own words have tags in them is not made plain")
    for label, why in (("Short", "a line with no room for the words"), ("Other", "a line without a price"), ("NoSuch", "a label the file has not")):
        try:
            seed.scrub_words(data, label)
            check(False, "%s is taken" % why)
        except ValueError:
            pass
    check(set(seed.SCRUB_LINES) == {g.key for g in seed.SCRUBS}, "a scrub's sale has no line of text named for it")

    # ---- the script ----
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check('"rando_scrubs": 0' in script and '(" scrubs 1 words" if a.scrubs else "")' in script, "the script does not read the setting, or does not name it in the seed's stamp")
    check("if len(now) != len(was):" in script and 'gift_files["Mals/" + n] = now' in script and "if g.key in SCRUB_LINES and gives[h] != g.item" in script,
          "a changed sale's words are not written with the seed, or an archive of another size would be")
    check("if a.scrubs:   # (Deku Scrubs: with or without Quest rewards)" in script and "((g.entry, old) if g.entry else old, gives[h]) for old in g.olds" in script,
          "the scrubs wait for Quest rewards, or their sales are not swapped by their entry points")
    check("quest_need(gifts[h].need, gifts[h].area) if h in gifts" in script, "with Quest rewards a scrub does not ask for its two gating items")
    print("PASS: Deku Scrubs")


if __name__ == "__main__":
    main()
