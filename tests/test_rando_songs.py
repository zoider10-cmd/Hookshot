"""The randomizer's Songs setting: no game data.

The twelve songs are shuffled among the twelve lessons (tools/rando/rando_seed.py SONGS). A lesson gives its song as a
character gives a gift, so its flow is changed as a gift's is; who asks whether a lesson is done is made to ask for
the song the lesson gives now; and the songs that gate the game are placed by the logic, in lessons only.

- the list: twelve lessons, one for each song, each with a place for the tracker; a lesson does not ask for its own
  song, and the first three ask for no song at all (the Lullaby has to start somewhere);
- the rules: an adult's check asks for the four songs an adult has, the Zoras' places for the Lullaby, the Shadow
  Temple for the Nocturne, the Spirit Temple for the Requiem; a child's check elsewhere asks for none;
- the words: a song that changed places is renamed as its name, its flag and its scene's flag, one that did not is
  left;
- the placing: with `bound`, the songs go to lessons only and a lesson holds a song only, and every gating song can
  be got (twenty seeds);
- a flow: a name is changed in an action and a question too when asked, and only in a sub-flow's call when not;
- the script reads the setting, names it in the seed's stamp and turns the logic on with it; the menu knows the
  songs' letters; a rule's letters fit the menu's and the game's lines.

    python -I -B tests/test_rando_songs.py
"""
import collections
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


def flow(steps):
    """A flow file of one flowchart whose steps are (kind, a parameter's string): enough of one for gift_items."""
    count = len(steps)
    events = 0x100
    at = events + 0x30 * count
    body = bytearray(at)
    body[:6] = b"BFEVFL"
    struct.pack_into("<H", body, 0x20, 1)
    struct.pack_into("<Q", body, 0x28, 0x40)
    struct.pack_into("<Q", body, 0x40, 0x80)
    body[0x80:0x84] = b"EVFL"
    struct.pack_into("<H", body, 0x80 + 0x16, count)
    struct.pack_into("<Q", body, 0x80 + 0x30, events)
    for i, (kind, word) in enumerate(steps):
        body += b"\0" * (-len(body) % 8)
        text = len(body)
        raw = word.encode()
        body += struct.pack("<H", len(raw)) + raw + b"\0"
        body += b"\0" * (-len(body) % 8)
        item = len(body)
        body += bytes([5, 0]) + struct.pack("<H", 1) + b"\0" * 12 + struct.pack("<Q", text)
        params = len(body)
        body += bytes([1, 0]) + struct.pack("<H", 1) + b"\0" * 12 + struct.pack("<Q", item)
        body[events + 0x30 * i + 8] = kind
        struct.pack_into("<Q", body, events + 0x30 * i + 0x10, params)
    struct.pack_into("<I", body, 0x1c, len(body))
    return bytes(body)


def names(data):
    u16 = lambda at: struct.unpack_from("<H", data, at)[0]
    u64 = lambda at: struct.unpack_from("<Q", data, at)[0]
    events, out = u64(0x80 + 0x30), []
    for i in range(u16(0x80 + 0x16)):
        item = u64(u64(events + 0x30 * i + 0x10) + 0x10)
        text = u64(item + 0x10)
        out.append(bytes(data[text + 2:text + 2 + u16(text)]).decode())
    return out


def main():
    S = seed
    # ---- the list ----
    check(len(S.SONGS) == 12 and [g.item for g in S.SONGS] == list(S.SONG_ITEMS) and all(g.olds == (g.item,) and g.when == "songs" for g in S.SONGS) and
          len({g.flow for g in S.SONGS}) == 12 and len({g.key for g in S.SONGS}) == 12, "the lessons are not twelve, one for each song, each with a flow of its own")
    check(all(g.key in S.GIFT_PLACES for g in S.SONGS), "a lesson has no place for the tracker")
    check(all(g.item not in g.need for g in S.SONGS), "a lesson asks for the song the game teaches there")
    check(all(not (g.need & set(S.SONG_ITEMS)) for g in S.SONGS[:3]), "none of the lessons can be had without a song: the Lullaby has nowhere to start")
    check(S.SONG_GATES <= set(S.SONG_ITEMS) and all(S.CHECK_CODES.get(s) for s in S.SONG_GATES) and
          len(set(S.CHECK_CODES.values())) == len(S.CHECK_CODES), "a gating song has no letters for the tracker, or two items share theirs")
    check(set(S.SONG_FLOWS) >= {g.flow for g in S.SONGS} and not any(f.startswith("Dm_SY_Ocarina") for f in S.SONG_FLOWS),
          "a lesson's flow is not gone through, or a flow that plays a song is")

    # ---- the rules ----
    grown = S.song_need(S.ADULT | {S.HAM}, "HyruleField")
    check(grown == S.ADULT | {S.HAM} | S.SONG_GROWN, "an adult's check does not ask for the four songs an adult has: %r" % sorted(grown))
    check(S.song_need(S.CHILD, "KokiriForest") == S.CHILD and S.song_need(S.NONE, "KokiriForest") == S.NONE, "a child's check asks for a song")
    check(S.ZL in S.song_need(S.CHILD, "ZoraDomain") and S.NOCTURNE in S.song_need(S.MEDALS3, "ShadowTemple") and
          S.REQUIEM in S.song_need(S.DESERT, "SpiritTemple") and S.song_need(S.PROGRESSION, "InsideGanonCastle") >= S.SONG_GATES,
          "the Zoras' places, the Shadow Temple, the Spirit Temple or Ganon's Castle do not ask for their songs")
    check(S.song_need(S.CHILD, "GoronCity", "darunia") == S.CHILD | {S.ZL, S.SARIA} and S.EPONA in S.song_need(S.ADULT, "GerudoFortress", "archery_heart"),
          "Darunia's gift or the horseback archery does not ask for its songs")

    # ---- the words ----
    words = S.song_words({S.ZL: S.SUN, S.SUN: S.ZL, S.TIME: S.TIME})
    check(words == {S.ZL: S.SUN, "IsGet." + S.ZL: "IsGet." + S.SUN, "HavePlayedGetEvent." + S.ZL: "HavePlayedGetEvent." + S.SUN,
                    S.SUN: S.ZL, "IsGet." + S.SUN: "IsGet." + S.ZL, "HavePlayedGetEvent." + S.SUN: "HavePlayedGetEvent." + S.ZL},
          "a song that changed places is not renamed as its name and its two flags, or one that did not is: %r" % words)

    # ---- the placing: songs in lessons only, and every gating song can be got ----
    was = S.PROGRESSION
    S.PROGRESSION = S.PROGRESSION | S.SONG_GATES
    try:
        spots, needs = collections.OrderedDict(), {}
        for k, item in enumerate(sorted(was) + ["TBox_Rupee_Blue"] * 30):
            spots[k] = ("HyruleField", item, False, None)
            needs[k] = S.NONE if k % 3 else S.song_need(S.ADULT, "HyruleField")
        lessons = {}
        for g in S.SONGS:
            h = S.gift_hash(g.key)
            lessons[h] = g
            spots[h] = (g.area, g.item, None, None)
            needs[h] = g.need
        for n in range(20):
            gives, _, spheres = S.place(random.Random(n), spots, 3, 0, needs, (frozenset(S.SONG_ITEMS), frozenset(lessons)))
            check(all((gives[h] in S.SONG_ITEMS) == (h in lessons) for h in gives), "seed %d: a song is in a chest, or a lesson gives something that is no song" % n)
            check(sorted(gives[h] for h in lessons) == sorted(S.SONG_ITEMS), "seed %d: the lessons do not give the twelve songs, each once" % n)
            got = {i for sphere in spheres for i in sphere}
            check(got >= S.SONG_GATES, "seed %d: a gating song cannot be got: %r" % (n, sorted(S.SONG_GATES - got)))
            check(S.TIME not in needs[next(h for h in lessons if gives[h] == S.TIME)], "seed %d: the Song of Time is taught where an adult is asked for" % n)
        same, _, _ = S.place(random.Random(5), collections.OrderedDict((k, v) for k, v in spots.items() if k not in lessons), 3, 0,
                             {k: v for k, v in needs.items() if k not in lessons})
        check(not any(i in S.SONG_ITEMS for i in same.values()), "without the lessons a song is placed")
    finally:
        S.PROGRESSION = was

    # ---- a flow: a name in an action and a question too, when asked ----
    data = flow([(4, S.ZL), (0, "IsGet." + S.ZL), (1, "IsGet." + S.ZL), (4, S.SUN), (0, "Other")])
    swaps = S.song_words({S.ZL: S.SUN, S.SUN: S.ZL})
    every, found = S.gift_items(data, swaps, kinds=(0, 1, 4))
    check(names(every) == [S.SUN, "IsGet." + S.SUN, "IsGet." + S.SUN, S.ZL, "Other"] and found == {S.ZL, "IsGet." + S.ZL, S.SUN},
          "a song's name is not changed in a call, an action and a question: %r" % names(every))
    calls, _ = S.gift_items(data, swaps)
    check(names(calls) == [S.SUN, "IsGet." + S.ZL, "IsGet." + S.ZL, S.ZL, "Other"], "a gift's change reaches past the sub-flows' calls: %r" % names(calls))

    # ---- the script, the menu and the game ----
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check('"rando_songs": 0' in script and '(" songs 2" if a.songs else "")' in script and
          "logic_now = (a.event_chests or bool(a.songs)) and not a.no_logic" in script and '":songs" if a.songs else ""' in script,
          "the script does not read the setting, does not name it in the seed's stamp, or leaves the logic off with it")
    check("(frozenset(SONG_ITEMS), frozenset(lessons)) if a.songs else None)" in script and "now, found = gift_items(was, words, kinds=(0, 1, 4))" in script and
          "now = song_stone(open(os.path.join(romfs, *rel.split(\"/\")), \"rb\").read(), now_gives)" in script and "shop_parts | song_parts" in script,
          "the songs are not bound to the lessons, their flows are not gone through, or the royal tomb's stones are left")
    check("if gives[h] != g.item and g.flow and h not in lessons:" in script and "(tuple(SONG_GATES) if a.songs else ())" in script,
          "a lesson is changed as a plain gift too, or a gating song can be a Gold Skulltula's")
    # (found in play: the ocarina's own flow added the lesson's own song as well)
    check("adds = {(entry, old): new for old, new in now_gives.items() if old != new for entry in SONG_PLAY_ENTRIES}" in script and
          "gift_items(unpack(open(os.path.join(romfs, *rel.split(\"/\")), \"rb\").read(), zs, dicts), adds, kinds=(0,))" in script and
          S.SONG_PLAY_FLOW == "Dm_SY_Ocarina" and S.SONG_PLAY_ENTRIES == ("LearningOcarinaPlayAuto", "LearningOcarinaPlayAutoForSeek") and
          S.SONG_PLAY_FLOW not in S.SONG_FLOWS,
          "the ocarina's flow still adds a lesson's own song, or is changed where a song is played")
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
    items = (ROOT / "gpu" / "vk" / "oot_cheat_items.h").read_text(encoding="utf-8")
    rows = {"ZL": "Zelda's Lullaby", "EP": "Epona's Song", "SR": "Saria's Song", "ST": "Song of Time", "SO": "Song of Storms", "RQ": "Requiem of Spirit",
            "NC": "Nocturne of Shadow"}
    check({S.CHECK_CODES[s] for s in S.SONG_GATES} == set(rows) and
          all('{"%s", "%s", {"%s"}},' % (code, name, name) in menu and 'OOT_ITEM("%s", ' % name in items for code, name in rows.items()),
          "the menu does not know a gating song's letters, or names a row the Inventory page has not")
    longest = len(",".join(S.CHECK_CODES.values()))
    host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    check(longest <= 95 and "char needs[96];" in menu and "|%95[A-Z,-]|" in menu and 'needs[96] = ""' in host and "|%95[A-Z,-]|" in host,
          "a rule that names every item (%d letters and commas) does not fit the menu's or the game's line" % longest)
    print("PASS: Songs")


if __name__ == "__main__":
    main()
