"""Cosmetics (tools/rando/rando_cosmetics.py) on made-up ASTC blocks and a made-up game folder: no game data, no
zstandard.

A block's stored colours are read, changed and written back without touching the rest of the block: the packed
sequences read back as written for every way of storing them, a pair of colours stored is the pair read, and a block
keeps its mode, its weights and its size. A tunic's colour changes its own hues and leaves the others, and of a file of many textures only the ones named. The settings
are read from hookshot_cosmetics.ini, the launcher's Cosmetics page writes the same lines and colours and runs the
script at Play, and the build puts the script beside the game.

    python -I -B tests/test_rando_cosmetics.py
"""
import collections
import colorsys
import random
import re
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "rando"))
import rando_cosmetics as t


def check(ok, what):
    if not ok:
        raise SystemExit("FAIL: " + what)


def blocks():
    rng = random.Random(7)
    # every way a colour value is stored, and sequences of every length (a group cut short at the end too)
    seen = set()
    for top in range(5, 256):
        enc = t.encoding(top)
        if enc in seen or t.unquantized(enc) is None:
            continue
        seen.add(enc)
        kind, bits = enc
        digits = {"bits": 1, "trit": 3, "quint": 5}[kind]
        table = t.unquantized(enc)
        check(len(table) == digits << bits and min(table.values()) == 0 and max(table.values()) == 255,
              "%s: its steps run from 0 to 255" % (enc,))
        check(len(set(table.values())) == len(table), "%s: each stored form is another value" % (enc,))
        for count in range(1, 19):
            for _ in range(20):
                values = [(rng.randrange(digits), rng.randrange(1 << bits)) for _ in range(count)]
                packed = t.sequence_write(values, enc)
                check(packed < 1 << t.bit_length(enc, count), "%s x%d: fits its bits" % (enc, count))
                check(t.sequence_read(packed, enc, count) == values, "%s x%d: read back as written" % (enc, count))
    check(len(seen) >= 17, "the colour encodings were all tried (%d)" % len(seen))

    # a pair of colours stored is the pair read, in both orders, where the steps are single values
    q = t.Quantizer.of(("bits", 8))
    for _ in range(2000):
        want = tuple(tuple(rng.randrange(256) for _ in range(3)) + (255,) for _ in range(2))
        got = t.endpoints(8, [q.value[s] for s in t.store(8, want, q)])
        miss = max(abs(x - y) for a, b in zip(got, want) for x, y in zip(a, b))
        check(miss <= 1 or sum(want[1]) < sum(want[0]), "a pair with the brighter colour second is stored as it is (%r -> %r)" % (want, got))

    # a block of one part, mode 8 (two colours), 8 bits a value, a 4x4 grid of 2-bit weights: mode bits 0x042
    mode = 0x042
    info = t.block_mode(mode)
    check(info == (4, 4, False, 3), "the made-up block's mode: a 4x4 grid of weights 0..3 (%r)" % (info,))
    colours = [200, 220, 30, 40, 20, 35]   # (r0, r1, g0, g1, b0, b1): two reds
    block = mode | 0 << 11 | 8 << 13
    for i, c in enumerate(colours):
        block |= c << 17 + 8 * i
    weights = rng.getrandbits(32)
    block |= weights << 96
    counts = collections.Counter()
    same = t.turn_block(block, lambda rgb: tuple(rgb), counts)
    check(same == block, "a change that changes nothing leaves the block as it is")
    swapped = t.turn_block(block, lambda rgb: (rgb[2], rgb[1], rgb[0]), counts)   # (red and blue changed over)
    check(swapped != block and counts["turned"] == 1, "a change is written")
    check(swapped >> 96 == weights and swapped & 0x1FFFF == block & 0x1FFFF, "the weights and the mode are as they were")
    got = [swapped >> 17 + 8 * i & 255 for i in range(6)]
    check(t.endpoints(8, got) == ((20, 30, 200, 255), (35, 40, 220, 255)), "the colours are the changed ones (%r)" % (got,))
    # a void block: one colour, 16 bits a channel
    void = 0xDFC | 0xFFFFFFFFFFFFF << 12 | 0xC000 << 64 | 0x2000 << 80 | 0x1000 << 96 | 0xFFFF << 112
    turned = t.turn_block(void, lambda rgb: (rgb[2], rgb[1], rgb[0]), counts)
    check([turned >> 64 + 16 * i & 0xFFFF for i in range(4)] == [0x1000, 0x2000, 0xC000, 0xFFFF], "a one-colour block's colour is changed")
    check(t.turn_block(0, lambda rgb: (0, 0, 0), counts) == 0, "an empty block (the padding between mip levels) is left")
    bc_blocks()
    return block


def bc_blocks():
    """BC1 and BC3 colour blocks: two 5:6:5 colours, then each pixel's pick"""
    counts = collections.Counter()
    swap = lambda rgb: (rgb[2], rgb[1], rgb[0])   # (red and blue changed over)
    red, dark = t.to565((200, 40, 16)), t.to565((90, 20, 8))
    check(t.from565(t.to565((255, 255, 255))) == (255, 255, 255) and t.from565(0) == (0, 0, 0), "5:6:5 colours and back")
    picks = 0b11100100_00011011_11100100_00011011
    block = red | dark << 16 | picks << 32   # (the first colour larger: two mixes)
    check(t.turn_bc(block, lambda rgb: tuple(rgb), counts, True) == block, "a change that changes nothing leaves a BC block as it is")
    got = t.turn_bc(block, swap, counts, True)
    n0, n1 = got & 0xFFFF, got >> 16 & 0xFFFF
    check(n0 > n1, "a block of two mixes is still one (the first colour the larger)")
    # red became blue, the smaller 5:6:5 number, so the colours changed over and each pick with them
    check({t.from565(n0), t.from565(n1)} == {t.from565(t.to565(swap(t.from565(red)))), t.from565(t.to565(swap(t.from565(dark))))}, "its colours are the changed ones")
    want = 0
    for i in range(16):
        want |= (picks >> 2 * i & 3 ^ 1) << 2 * i
    turned_round = (n0, n1) != (t.to565(swap(t.from565(red))), t.to565(swap(t.from565(dark))))
    check(got >> 32 == (want if turned_round else picks), "its pixels pick the colours they picked")
    # the other kind (one mix, and pick 3 see-through): the first colour not the larger, before and after
    three = dark | red << 16 | picks << 32
    got = t.turn_bc(three, lambda rgb: (rgb[0], rgb[2], rgb[1]), counts, True)
    check((got & 0xFFFF) <= (got >> 16 & 0xFFFF), "a block with see-through pixels is still one")
    check(all((got >> 32 + 2 * i & 3 == 3) == (picks >> 2 * i & 3 == 3) for i in range(16)), "its see-through pixels are the same ones")
    # two colours that become one: kept a step apart, or the block would change kind
    grey = lambda rgb: (100, 100, 100)
    got = t.turn_bc(block, grey, counts, True)
    check((got & 0xFFFF) > (got >> 16 & 0xFFFF), "two colours made equal stay a block of two mixes")
    # BC3: no order to keep, the colours changed and the picks left
    got = t.turn_bc(block, swap, counts, False)
    check(got >> 32 == picks and got & 0xFFFF == t.to565(swap(t.from565(red))), "a BC3 block's colours are changed in place")
    check(t.block_size(0x1c06) == (16, 8) and t.block_size(0x1a06) == (8, 0) and t.block_size(0x3306) == (16, None) and t.block_size(0x0b06) is None,
          "which formats are changed, and where a block's colours are")


def bntx(textures):
    """a made-up BNTX file of (name, format, the image's bytes): only what the script reads of one"""
    out = bytearray(b"BNTX" + bytes(60))
    for name, fmt, image in textures:
        at = len(out)
        out += b"BRTI" + bytes(0x90 - 4)
        name_at = len(out)
        out += struct.pack("<H", len(name)) + name.encode() + b"\0"
        out += bytes(-len(out) % 8)
        pointers = len(out)
        out += bytes(8)
        out += bytes(-len(out) % 16)
        first = len(out)
        out += image
        struct.pack_into("<IIii", out, at + 0x1c, fmt, 0, 8, 8)
        struct.pack_into("<I", out, at + 0x50, len(image))
        struct.pack_into("<Q", out, at + 0x60, name_at)
        struct.pack_into("<Q", out, at + 0x70, pointers)
        struct.pack_into("<Q", out, pointers, first)
    return bytes(out)


def files(block):
    """a file of several textures: only the ones named are changed, and the file keeps its size"""
    red = block.to_bytes(16, "little")
    data = bntx([("Heart_00", 0x2d06, red * 4), ("Other_00", 0x2d06, red * 4), ("Shape_00", 0x1d01, bytes(range(32)))])
    names = [image[0] for image in t.images(data)]
    check(names == ["Heart_00", "Other_00", "Shape_00"], "the made-up file's textures are read (%r)" % (names,))
    swap = lambda rgb: (rgb[2], rgb[1], rgb[0])
    counts = collections.Counter()
    new = t.turn(data, swap, counts, ("Heart_00",))
    check(len(new) == len(data) and new != data, "the file is changed and keeps its size")
    was, now = t.images(data), t.images(new)
    part = lambda d, image: d[image[4]:image[4] + image[5]]
    check(part(new, now[0]) != part(data, was[0]) and part(new, now[1]) == part(data, was[1]) and part(new, now[2]) == part(data, was[2]),
          "only the texture named is changed")
    try:
        t.turn(data, swap, counts, ("Heart_00", "Gone_00"))
        check(False, "a texture the file does not have is not passed over")
    except ValueError as e:
        check("Gone_00" in str(e), "the error names the missing texture")
    try:
        t.turn(data, swap, counts)
        check(False, "a texture that is only a shape (BC4) is not changed as if it had colours")
    except ValueError:
        pass
    # the hearts and the meter are textures of one file, named with it
    for name in ("hearts", "magic"):
        row = next(r for r in t.COSMETICS if r[0] == name)
        check(len(row[5]) == 1 and row[5][0][0] == t.HUD and len(set(row[5][0][1])) == len(row[5][0][1]) > 3, "%s: pictures of the screens' file" % name)


def hue(rgb):
    return colorsys.rgb_to_hsv(*(c / 255.0 for c in rgb))[0] * 360.0


def colours(block):
    names = [c[0] for c in t.COLOURS]
    check(names[0] == "The game's" and len(set(names)) == len(names), "the first colour is the game's own, and each has its own name")
    check(t.colour_of("purple") == names.index("Purple") and t.colour_of("3") == 3 and t.colour_of("mauve") is None, "a colour by its name or number")
    by_name = {row[0]: row for row in t.COSMETICS}
    check(list(by_name) == ["kokiri", "goron", "zora", "hearts", "magic"], "the three tunics, the hearts and the magic meter")
    _, _, _, hues, centre, textures = by_name["goron"]
    purple = t.recolour(t.COLOURS[t.colour_of("purple")], hues, centre)
    red, gold, grey = (190, 30, 28), (200, 160, 40), (90, 90, 90)
    check(abs(hue(purple(red)) - 275.0) < 8.0, "the Goron Tunic's red is purple (hue %.0f)" % hue(purple(red)))
    check(max(purple(red)) == max(red), "as bright as it was")
    check(purple(gold) == gold and purple(grey) == grey, "its gold trim and grey are left")
    white = t.recolour(t.COLOURS[t.colour_of("white")], hues, centre)(red)
    black = t.recolour(t.COLOURS[t.colour_of("black")], hues, centre)(red)
    check(min(white) > 150 and max(white) - min(white) < 30, "white is light and nearly grey (%r)" % (white,))
    check(max(black) < 70, "black is dark (%r)" % (black,))
    # each tunic in its own colour is all but what it was, and in another's is that one's hue
    for name, _, _, hues, centre, _ in t.COSMETICS:
        own = colorsys.hsv_to_rgb(centre / 360.0, 0.8, 0.6)
        own = tuple(c * 255.0 for c in own)
        for i, colour in enumerate(t.COLOURS[1:], 1):
            got = t.recolour(colour, hues, centre)(own)
            if colour[1] is not None:
                away = abs((hue(got) - colour[1] + 180.0) % 360.0 - 180.0)
                check(away < 3.0, "%s in %s has its hue (%.0f, not %.0f)" % (name, colour[0], hue(got), colour[1]))
    # the made-up block (two reds) through the Goron Tunic's change: written, and blue-ish purple
    counts = collections.Counter()
    turned = t.turn_block(block, purple, counts)
    ends = t.endpoints(8, [turned >> 17 + 8 * i & 255 for i in range(6)])
    check(counts["turned"] == 1 and all(abs(hue(e[:3]) - 275.0) < 10.0 for e in ends), "a red block is a purple block (%r)" % (ends,))


def mod_and_sources():
    with tempfile.TemporaryDirectory(prefix="rando-cosmetics-") as tmp:
        game = Path(tmp)
        none = {"kokiri": 0, "goron": 0, "zora": 0, "hearts": 0, "magic": 0, "shield_deku": 0, "shield_hylian": 0, "shield_mirror": 0}
        check(t.settings(str(game)) == none, "no file: everything the game's own")
        (game / "hookshot_cosmetics.ini").write_text("cosmetic_tunic_goron=4\ncosmetic_tunic_zora=99\nother=1\ncosmetic_tunic_kokiri=x\ncosmetic_magic=5\n", encoding="utf-8")
        check(t.settings(str(game)) == dict(none, goron=4, magic=5), "the file's lines are read, a colour that is not one is the game's own")
        # (the shields' looks: places in SHIELD_MODELS, which has fewer than there are colours)
        (game / "hookshot_cosmetics.ini").write_text("cosmetic_shield_deku=3\ncosmetic_shield_hylian=5\ncosmetic_shield_mirror=4\ncosmetic_hearts=10\n", encoding="utf-8")
        check(t.settings(str(game)) == dict(none, shield_deku=3, shield_mirror=4, hearts=10), "a shield's look is read, one that is not a look is its own")
        # the files of the last colours are removed, and nothing else in the mod's folder
        mod = game / "mods" / t.MOD
        (mod / "romfs" / "Tex").mkdir(parents=True)
        (mod / "romfs" / "Tex" / "a.bntx.zs").write_bytes(b"x")
        (mod / "romfs" / "Tex" / "mine.bntx.zs").write_bytes(b"x")
        (mod / "cosmetics_manifest.txt").write_text("romfs/Tex/a.bntx.zs\n../../outside.txt\n", encoding="utf-8")
        (mod / "cosmetics_stamp.txt").write_text("cosmetics 1\n", encoding="utf-8")
        (game / "outside.txt").write_text("kept", encoding="utf-8")
        check(t.remove_old(str(mod)) == 3, "the listed texture, the stamp and the list are removed")
        check((mod / "romfs" / "Tex" / "mine.bntx.zs").is_file() and (game / "outside.txt").is_file(),
              "a file the list does not name, and one outside the mod, are left")
    # ---- the launcher's page and the build ----
    launcher = (ROOT / "launcher" / "Launcher.cs").read_text(encoding="utf-8")
    listed = re.search(r"static readonly string\[\] TunicColours = \{ ([^}]*) \};", launcher)
    check(listed and re.findall(r'"([^"]*)"', listed.group(1)) == [c[0] for c in t.COLOURS],
          "the launcher's colours are not the script's, in its order")
    values = re.search(r"static readonly int\[\] TunicValues = \{ ([^}]*) \};", launcher)
    check(values and [int(v) for v in values.group(1).split(",")] == list(range(len(t.COLOURS))), "the launcher's colour values are their places")
    rows = launcher[launcher.index("static readonly object[][] CosmeticRows = {"):]
    rows = rows[:rows.index("\n    };")]
    check(re.findall(r'new object\[\] \{ "(\w+)", "([^"]*)", TunicColours, TunicValues,', rows) == [(key, label) for _, key, label, _, _, _ in t.COSMETICS],
          "the launcher's Cosmetics page and the script's tunics differ")
    check("AddSelectors(CosmeticRows, 4, cx, colW, cosmetics);" in launcher and '"hookshot_cosmetics.ini"' in launcher and
          "void SaveCosmetics()" in launcher, "the launcher does not show or keep its Cosmetics page")
    check('Text = "Randomize all"' in launcher and "Click = OnRandomCosmetics" in launcher and "s.Set(r.Next(1, s.Items.Length), false);" in launcher,
          "the launcher's Cosmetics page has no Randomize all button, or it can pick the game's own colour")
    check("if (!RunCosmetics()) return;" in launcher and 'RunAtPlay("rando_cosmetics.py", "cosmetics", on,' in launcher and "--if-changed" in launcher,
          "the launcher does not write the colours at Play")
    check('"hookshot_cosmetics.ini"' in (ROOT / "tools" / "rando" / "rando_cosmetics.py").read_text(encoding="utf-8"), "the script reads another file")
    make = (ROOT / "nx2" / "make_game.py").read_text(encoding="utf-8")
    check('os.path.join(ROOT, "tools", "rando", "rando_cosmetics.py")' in make and 'os.path.join(out, "rando", "rando_cosmetics.py")' in make,
          "the build does not put the cosmetics script beside the game, where the launcher runs it")


def shields():
    """a shield's look: its pack names another model, nothing else of the pack changes, and the pack does not grow"""
    seed = t.seed
    info = lambda model, scale=True: seed.byml_build(("dict", collections.OrderedDict(
        ([("DebugModelScale", ("dict", collections.OrderedDict((axis, (210, struct.pack("<f", 1.0))) for axis in "XYZ")))] if scale else []) +
        [("FmdbName", ("string", model)), ("ModelProjectName", ("string", model))])), 7)

    def pack(actor):
        return seed.sarc_write({"Component/ModelInfo/%s.engine__component__ModelInfo.bgyml" % actor: info(actor),
                                "Component/ShieldParam/%s.game__component__ShieldParam.bgyml" % actor: b"guard" * 9,
                                "Actor/%s.engine__actor__ActorParam.bgyml" % actor: b"actor" * 31})

    check([m for _, m in t.SHIELD_MODELS] == [None, "Weapon_Shield_Deku", "Weapon_Shield_Hylian", "Weapon_Shield_Mirror", "Weapon_Shield_Hylian_Dark"] and
          [(key, actor) for _, key, _, actor in t.SHIELDS] == [("cosmetic_shield_deku", "Weapon_Shield_Deku"), ("cosmetic_shield_hylian", "Weapon_Shield_Hylian"),
                                                               ("cosmetic_shield_mirror", "Weapon_Shield_Mirror")],
          "the shields or their looks are not the three Link carries and the four models")
    for _, _, _, actor in t.SHIELDS:
        data = pack(actor)
        check(t.shield_pack(data, actor, actor) is None, "%s as itself is a change" % actor)
        for _, model in t.SHIELD_MODELS[1:]:
            if model == actor:
                continue
            new = t.shield_pack(data, actor, model)
            was, now = seed.sarc_read(data), seed.sarc_read(new)
            name = "Component/ModelInfo/%s.engine__component__ModelInfo.bgyml" % actor
            rows = seed.byml_parse(now[name])[0][1]
            check(sorted(was) == sorted(now) and all(now[f] == was[f] for f in was if f != name),
                  "%s as %s: a file other than the one that names the model changed" % (actor, model))
            check(rows["FmdbName"] == ("string", model) and rows["ModelProjectName"] == ("string", model), "%s as %s: the model is not named" % (actor, model))
            check(len(new) <= len(data), "%s as %s: the pack grew (%d from %d), and the mod has no size table" % (actor, model, len(new), len(data)))
            # (no model is made larger or smaller: the scale is 1 or left out, never another)
            scale = rows.get("DebugModelScale")
            check(scale is None or all(struct.unpack("<f", v[1])[0] == 1.0 for v in scale[1].values()), "%s as %s: the model is resized" % (actor, model))
    # (a pack that is not as the game's: not changed)
    for bad in (seed.sarc_write({"Actor/x.bgyml": b"x"}),
                seed.sarc_write({"Component/ModelInfo/a.bgyml": info("Weapon_Shield_Other")})):
        try:
            t.shield_pack(bad, "Weapon_Shield_Deku", "Weapon_Shield_Mirror")
            check(False, "a pack that does not name the shield's own model is changed all the same")
        except ValueError:
            pass
    check(t.shield_look_of("mirror") == 3 and t.shield_look_of("Dark Link's shield") == 4 and t.shield_look_of("0") == 0 and
          t.shield_look_of("Weapon_Shield_Hylian") == 2 and t.shield_look_of("sword") is None, "a look is not read from its name or number")
    source = (ROOT / "tools" / "rando" / "rando_cosmetics.py").read_text(encoding="utf-8")
    check('for name in [row[0] for row in COSMETICS] + [row[0] for row in SHIELDS]))' in source and t.VERSION >= 6,
          "the shields' looks are not in the mod's stamp: a changed look would not be written at Play")
    # ---- the launcher's rows: the same lines and looks, in the same order ----
    launcher = (ROOT / "launcher" / "Launcher.cs").read_text(encoding="utf-8")
    looks = re.search(r"static readonly string\[\] ShieldLooks = \{ ([^}]*) \};", launcher)
    check(looks and re.findall(r'"([^"]*)"', looks.group(1)) == [m[0] for m in t.SHIELD_MODELS] and
          "static readonly int[] ShieldValues = { 0, 1, 2, 3, 4 };" in launcher, "the launcher's looks are not the script's, in its order")
    rows = launcher[launcher.index("static readonly object[][] ShieldRows = {"):]
    rows = rows[:rows.index("\n    };")]
    check(re.findall(r'new object\[\] \{ "(\w+)", "[^"]*", ShieldLooks, ShieldValues,', rows) == [key for _, key, _, _ in t.SHIELDS],
          "the launcher's shield rows and the script's shields differ")
    check("AddSelectors(ShieldRows, 4, cx, colW, cosmetics, 70, 62, false, 5);" in launcher and
          "int place = first;" in launcher and "int col = place % 2, line = place / 2;" in launcher,
          "the launcher does not show the shields' looks on its Cosmetics page, after the colours")


def main():
    block = blocks()
    colours(block)
    files(block)
    mod_and_sources()
    shields()
    print("ok: cosmetics")


if __name__ == "__main__":
    main()
