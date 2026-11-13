"""Cosmetics: the colours of Link's three tunics, the hearts and the magic meter, and the look of his shields, as a mod.

Reads the launcher's Cosmetics page (<game folder>\\hookshot_cosmetics.ini: cosmetic_tunic_kokiri, cosmetic_tunic_goron,
cosmetic_tunic_zora, cosmetic_hearts, cosmetic_magic, each a colour of COLOURS below, 0 the game's own) and writes
their colour textures, changed, to <game folder>\\mods\\cosmetics\\romfs, which Mako loads in place of the game's own.
The game's files are not touched. With every one on the game's own colour the mod is removed.

The hearts and the magic meter are pictures of the file that holds every picture of the game's screens
(UI/Layout2Archive/Common...bntx.zs, a quarter of a gigabyte unpacked): the mod carries that file whole, with those
pictures changed.

    python -I tools/rando/rando_cosmetics.py "F:\\Games\\OOT Remake Rando\\romfs"
    python -I tools/rando/rando_cosmetics.py <romfs> [--game <folder>] [--kokiri purple] [--goron blue] [--zora 0] [--hearts blue] [--magic pink] [--if-changed] [--dry-run]
    python -I tools/rando/rando_cosmetics.py <romfs> --stats Mt_Vest_Armor_Adult_Goron_Alb    what colours a texture holds

The launcher runs it at Play (the copy the build puts in <game folder>\\rando, with --if-changed).

How a texture is changed: the tunics' colour textures (Tex/*_Alb.bntx.zs) are ASTC, but for the Kokiri Tunic's cloth,
which is BC3 (a block there: two colours and each pixel's pick between them, changed the same way). Nothing here
decodes or compresses one. An ASTC block stores two colours for each of its parts and, for every pixel, how far it lies between
them: the stored colours are changed and the rest of the block is left as it is. So the picture keeps its detail, the
file keeps its size (no size table entry to raise), and every mip level is done by the same pass (a block is 16 bytes
wherever it lies in the file, so the console's block layout does not matter). Shown to work in game with the Goron
Tunic's vest and inner shirt turned purple.

What is changed: on each texture of a tunic, the hearts or the meter (COSMETICS below), only the colours whose hue is the tunic's own (the Goron
Tunic's reds, not its gold trim or its leather). What is not: the tunic's icon in the equipment menu, which is a
picture of its own. The Kokiri Tunic's cloth is a picture young Link's tunic, Mido's clothes and a few Kokiri things
share, so they take its colour too: young Link's vest, hat and stitching are changed with it, so his tunic is whole;
Mido keeps his own green vest over the changed cloth. The Goron and Zora Tunics' pictures are their own.

What a block can hold limits it: the two colours of a part are stored with few steps (as few as 6 a channel), so a
changed colour lands on the nearest step, as the game's own did.

The shields (cosmetic_shield_deku, cosmetic_shield_hylian, cosmetic_shield_mirror: 0 its own look, else a place in
SHIELD_MODELS): a shield Link carries is an actor (Pack/Actor/Weapon_Shield_Deku, _Hylian, _Mirror) whose pack names
its model in one small file, Component/ModelInfo. The game's own Dark Link carries a Hylian Shield whose pack differs
in that name alone (Weapon_Shield_DarkLinkShield: the model Weapon_Shield_Hylian_Dark). So a shield is given another's
look by that name, and nothing else of it: it is still the shield it was, with its own guard, weight, burning and
mirror, held as Link's age and that shield are held (young Link holds a Deku Shield up, and crouches under a Hylian
one). No model is made larger or smaller: the Mirror Shield's is its full size on young Link, the Deku Shield's its
small one on adult Link. Shown to work in game with the Deku Shield as the Mirror Shield, on young Link's back and held up.

Needs the zstandard package. The ASTC layout is as gpu/third_party/suyu/video_core/textures/astc.cpp reads it.
"""
import argparse
import collections
import colorsys
import functools
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rando_seed as seed   # (the game's zstd dictionaries)

MOD = "cosmetics"
VERSION = 6   # (raised when the same settings would write other textures: the launcher's run at Play then writes them again.
# 2: the Kokiri Tunic's cloth, and a pinker Pink; 3: its stitching and fringe; 4: the hearts and the magic meter; 5: young Link's vest and stitching; 6: the shields' looks)
TRIT_AT, TRIT_N = (0, 2, 4, 5, 7), (2, 2, 1, 2, 1)   # (where a trit block's T bits lie between its values' bits)
QUINT_AT, QUINT_N = (0, 3, 5), (3, 2, 2)


# ---- bounded integer sequences (the spec's C.2.12): values of 3 * 2^n or 5 * 2^n steps, packed 5 or 3 together ----
def encoding(max_value):
    """how values of 0..max_value are stored: ("bits" | "trit" | "quint", bits each)"""
    while max_value > 0:
        check = max_value + 1
        if not check & (check - 1):
            return "bits", bin(max_value).count("1")
        if check % 3 == 0 and not (check // 3) & (check // 3 - 1):
            return "trit", bin(check // 3 - 1).count("1")
        if check % 5 == 0 and not (check // 5) & (check // 5 - 1):
            return "quint", bin(check // 5 - 1).count("1")
        max_value -= 1
    return "bits", 0


def bit_length(enc, count):
    kind, bits = enc
    return bits * count + ((count * 8 + 4) // 5 if kind == "trit" else (count * 7 + 2) // 3 if kind == "quint" else 0)


def trits_of(T):
    b = lambda v, lo, hi: v >> lo & (1 << hi - lo + 1) - 1
    t = [0] * 5
    if b(T, 2, 4) == 7:
        C = b(T, 5, 7) << 2 | b(T, 0, 1)
        t[4] = t[3] = 2
    else:
        C = b(T, 0, 4)
        if b(T, 5, 6) == 3:
            t[4], t[3] = 2, b(T, 7, 7)
        else:
            t[4], t[3] = b(T, 7, 7), b(T, 5, 6)
    if b(C, 0, 1) == 3:
        t[2], t[1], t[0] = 2, b(C, 4, 4), b(C, 3, 3) << 1 | b(C, 2, 2) & ~b(C, 3, 3) & 1
    elif b(C, 2, 3) == 3:
        t[2], t[1], t[0] = 2, 2, b(C, 0, 1)
    else:
        t[2], t[1], t[0] = b(C, 4, 4), b(C, 2, 3), b(C, 1, 1) << 1 | b(C, 0, 0) & ~b(C, 1, 1) & 1
    return tuple(t)


def quints_of(Q):
    b = lambda v, lo, hi: v >> lo & (1 << hi - lo + 1) - 1
    q = [0] * 3
    if b(Q, 1, 2) == 3 and b(Q, 5, 6) == 0:
        q[0] = q[1] = 4
        q[2] = b(Q, 0, 0) << 2 | (b(Q, 4, 4) & ~b(Q, 0, 0) & 1) << 1 | b(Q, 3, 3) & ~b(Q, 0, 0) & 1
    else:
        if b(Q, 1, 2) == 3:
            q[2] = 4
            C = b(Q, 3, 4) << 3 | (~b(Q, 5, 6) & 3) << 1 | b(Q, 0, 0)
        else:
            q[2] = b(Q, 5, 6)
            C = b(Q, 0, 4)
        if b(C, 0, 2) == 5:
            q[1], q[0] = 4, b(C, 3, 4)
        else:
            q[1], q[0] = b(C, 3, 4), b(C, 0, 2)
    return tuple(q)


def packings(unpack_one, group, at, n, total):
    """{how many of a group's values are there: {those values: the packed bits}}: a group cut short by the end of the
    sequence only has the low bits of its packing, the rest read as 0"""
    out = {}
    for k in range(1, group + 1):
        have = at[k - 1] + n[k - 1]   # (the packed bits a group of k values has)
        table = {}
        for packed in range(1 << have):
            table.setdefault(unpack_one(packed)[:k], packed)
        out[k] = table
    return out


TRIT_PACK = packings(trits_of, 5, TRIT_AT, TRIT_N, 8)
QUINT_PACK = packings(quints_of, 3, QUINT_AT, QUINT_N, 7)


def sequence_read(data, enc, count):
    """count values of a sequence that starts at bit 0 of data (an int; the bits past the sequence 0): [(digit, bits)],
    digit the trit or quint (0 for plain bits)"""
    kind, bits = enc
    out, pos = [], 0
    take = lambda n: (data >> pos & (1 << n) - 1)
    if kind == "bits":
        for _ in range(count):
            out.append((0, take(bits)))
            pos += bits
        return out
    group, at, n, one = (5, TRIT_AT, TRIT_N, trits_of) if kind == "trit" else (3, QUINT_AT, QUINT_N, quints_of)
    while len(out) < count:
        m, packed = [], 0
        for i in range(group):
            m.append(take(bits))
            pos += bits
            packed |= take(n[i]) << at[i]
            pos += n[i]
        out += list(zip(one(packed), m))
    return out[:count]


def sequence_write(values, enc):
    """the bits of a sequence of (digit, bits) values, as an int from bit 0"""
    kind, bits = enc
    data, pos = 0, 0
    if kind == "bits":
        for _, m in values:
            data |= m << pos
            pos += bits
        return data
    group, at, n, pack = (5, TRIT_AT, TRIT_N, TRIT_PACK) if kind == "trit" else (3, QUINT_AT, QUINT_N, QUINT_PACK)
    for start in range(0, len(values), group):
        part = values[start:start + group]
        packed = pack[len(part)][tuple(d for d, _ in part)]
        for i, (_, m) in enumerate(part):
            data |= m << pos
            pos += bits
            data |= (packed >> at[i] & (1 << n[i]) - 1) << pos
            pos += n[i]
    return data & (1 << bit_length(enc, len(values))) - 1


@functools.lru_cache(maxsize=None)
def unquantized(enc):
    """{(digit, bits): the 0..255 value it stands for} for a colour value stored this way (C.2.13), or None"""
    kind, bits = enc
    if kind == "bits":
        if bits < 1:
            return None
        table = {}
        for m in range(1 << bits):
            v, have = 0, 0
            while have < 8:   # (the bits repeated down to fill 8)
                v = v << bits | m
                have += bits
            table[(0, m)] = v >> have - 8
        return table
    if not 1 <= bits <= (6 if kind == "trit" else 5):
        return None
    table = {}
    for d in range(3 if kind == "trit" else 5):
        for m in range(1 << bits):
            A = 0x1FF if m & 1 else 0
            x = m >> 1
            if kind == "trit":
                C = (204, 93, 44, 22, 11, 5)[bits - 1]
                B = (0, x << 8 | x << 4 | x << 2 | x << 1, x << 7 | x << 2 | x, x << 6 | x, x << 5 | x >> 2, x << 4 | x >> 4)[bits - 1]
            else:
                C = (113, 54, 26, 13, 6)[bits - 1]
                B = (0, x << 8 | x << 3 | x << 2, x << 7 | x << 1 | x >> 1, x << 6 | x >> 1, x << 5 | x >> 3)[bits - 1]
            T = (d * C + B) ^ A
            table[(d, m)] = A & 0x80 | T >> 2
    return table


# ---- a block ----
def block_mode(mode):
    """a block's 11 mode bits: (weight grid width, height, two planes, the largest weight), "void" (one colour for the
    whole block), or None (reserved, or a void block of HDR colour)"""
    if mode & 0x1FF == 0x1FC:
        return None if mode & 0x200 else "void"
    if mode & 0xF == 0 or mode & 3 == 0 and mode & 0x1C0 == 0x1C0:
        return None
    A, B = mode >> 5 & 3, mode >> 7 & 3
    if mode & 3:
        R = (mode >> 4 & 1) | (mode & 3) << 1
        if not mode & 8:
            w, h = (B + 8, A + 2) if mode & 4 else (B + 4, A + 2)
        elif not mode & 4:
            w, h = A + 2, B + 8
        elif mode & 0x100:
            w, h = (B & 1) + 2, A + 2
        else:
            w, h = A + 2, (B & 1) + 6
        nine = False
    else:
        R = (mode >> 4 & 1) | (mode & 0xC) >> 1
        nine = False
        if mode & 0x100:
            if mode & 0x80:
                w, h = (10, 6) if mode & 0x20 else (6, 10)
            else:
                w, h, nine = A + 6, (mode >> 9 & 3) + 6, True
        else:
            w, h = (A + 2, 12) if mode & 0x80 else (12, A + 2)
    if not 2 <= R <= 7:
        return None
    dual, high = not nine and bool(mode & 0x400), not nine and bool(mode & 0x200)
    return w, h, dual, ((9, 11, 15, 19, 23, 31) if high else (1, 2, 3, 4, 5, 7))[R - 2]


def clamp(v):
    return 0 if v < 0 else 255 if v > 255 else int(v)


def transfer(a, b):
    """the spec's bit_transfer_signed"""
    b = b >> 1 | a & 0x80
    a = a >> 1 & 0x3F
    return (a - 0x40 if a & 0x20 else a), b


def endpoints(cem, v):
    """the two colours a part's values stand for: ((r, g, b, a), (r, g, b, a)), for the colour modes turned here"""
    if cem in (6, 10):
        a0, a1 = (v[4], v[5]) if cem == 10 else (255, 255)
        return (v[0] * v[3] >> 8, v[1] * v[3] >> 8, v[2] * v[3] >> 8, a0), (v[0], v[1], v[2], a1)
    v = list(v)
    if cem in (9, 13):
        for i in range(0, len(v), 2):
            v[i + 1], v[i] = transfer(v[i + 1], v[i])
    a0, a1 = (v[6], v[7]) if cem >= 12 else (255, 255)
    if cem in (9, 13):
        direct = v[1] + v[3] + v[5] >= 0
        first, second = (v[0], v[2], v[4]), (v[0] + v[1], v[2] + v[3], v[4] + v[5])
        if cem == 13:
            a1 = a0 + a1
    else:
        direct = v[1] + v[3] + v[5] >= v[0] + v[2] + v[4]
        first, second = (v[0], v[2], v[4]), (v[1], v[3], v[5])
    if not direct:   # (the other order, with blue in red and green: the spec's blue contraction)
        first, second, a0, a1 = second, first, a1, a0
        first = (first[0] + first[2] >> 1, first[1] + first[2] >> 1, first[2])
        second = (second[0] + second[2] >> 1, second[1] + second[2] >> 1, second[2])
    return tuple(map(clamp, first + (a0,))), tuple(map(clamp, second + (a1,)))


class Quantizer:
    """a block's colour values are stored in steps: the stored form nearest a value, and back"""
    cache = {}

    def __init__(self, enc):
        self.value = unquantized(enc)
        steps = sorted((v, k) for k, v in self.value.items())
        self.nearest = [min(steps, key=lambda s: abs(s[0] - x))[1] for x in range(256)]

    @classmethod
    def of(cls, enc):
        if enc not in cls.cache:
            cls.cache[enc] = cls(enc)
        return cls.cache[enc]


def store(cem, want, q):
    """The stored values (as (digit, bits)) of mode 8 or 12 (two colours as they are) whose colours come nearest to
    want, ((r, g, b, a), (r, g, b, a)). Two ways to store a pair: as it is, when the second is at least as bright as
    the first, or the other way round with blue taken out of red and green; whichever reads back closer."""
    (r0, g0, b0, a0), (r1, g1, b1, a1) = want
    best = None
    plain = [r0, r1, g0, g1, b0, b1] + ([a0, a1] if cem == 12 else [])
    other = [2 * r1 - b1, 2 * r0 - b0, 2 * g1 - b1, 2 * g0 - b0, b1, b0] + ([a1, a0] if cem == 12 else [])
    for values in (plain, other):
        stored = [q.nearest[clamp(x)] for x in values]
        if values is other:   # (red and green are read back as (stored + blue) / 2, rounded down: the step that reads back nearest)
            for i, target in ((0, r1), (1, r0), (2, g1), (3, g0)):
                blue = q.value[stored[4 + i % 2]]
                stored[i] = min((q.nearest[clamp(values[i] + d)] for d in (0, 1, -1, 2, -2)),
                                key=lambda s: abs((q.value[s] + blue >> 1) - target))
        for _ in range(8):   # (the steps can turn the order round: nudged back, a step at a time)
            got = [q.value[s] for s in stored]
            is_plain = got[1] + got[3] + got[5] >= got[0] + got[2] + got[4]
            if is_plain == (values is plain):
                break
            raise_these = (1, 3, 5) if values is plain else (0, 2, 4)
            moved = False
            for i in sorted(raise_these, key=lambda i: got[i]):
                up = q.nearest[min(255, got[i] + 1)]
                x = got[i] + 1
                while up == stored[i] and x < 255:
                    x += 1
                    up = q.nearest[x]
                if up != stored[i]:
                    stored[i], moved = up, True
                    break
            if not moved:
                break
        back = endpoints(cem, [q.value[s] for s in stored])
        miss = sum((x - y) ** 2 for a, b in zip(back, want) for x, y in zip(a, b))
        if best is None or miss < best[0]:
            best = (miss, stored)
    return best[1]


def turn_block(block, change, counts):
    """a 16-byte block (as an int) with its colours changed by change((r, g, b)) -> (r, g, b), or the same block"""
    info = block_mode(block & 0x7FF)
    if info is None:
        counts["left: reserved or HDR"] += 1
        return block
    if info == "void":
        rgb = [(block >> 64 + 16 * i & 0xFFFF) for i in range(3)]
        new = change(tuple(c / 257.0 for c in rgb))
        if all(abs(x - c / 257.0) < 0.5 for x, c in zip(new, rgb)):
            return block
        counts["one colour"] += 1
        for i in range(3):
            block = block & ~(0xFFFF << 64 + 16 * i) | min(65535, max(0, int(round(new[i] * 257)))) << 64 + 16 * i
        return block
    w, h, dual, max_weight = info
    weight_bits = bit_length(encoding(max_weight), w * h * (2 if dual else 1))
    parts = (block >> 11 & 3) + 1
    if parts == 4 and dual or w * h * (2 if dual else 1) > 64 or not 24 <= weight_bits <= 96:
        counts["left: not a block the format allows"] += 1
        return block
    # the colour modes: one for all the parts, or a class for each and two bits more each, some below the weights
    low_bit = []   # (where the lowest bit of each part's mode is: cleared to store a mode 9 or 13 part as 8 or 12)
    if parts == 1:
        cems, start, extra = [block >> 13 & 15], 17, 0
        low_bit = [13]
    else:
        base, start = block >> 23 & 63, 29
        if base & 3:
            extra = (2, 5, 8)[parts - 2]
            at = 128 - weight_bits - extra
            field = ((block >> at & (1 << extra) - 1) << 6 | base) >> 2
            where = lambda k: 25 + k if k < 4 else at + k - 4
            cems = [((base & 3) - (0 if field >> i & 1 else 1)) << 2 | field >> parts + 2 * i & 3 for i in range(parts)]
            low_bit = [where(parts + 2 * i) for i in range(parts)]
        else:
            extra, cems, low_bit = 0, [base >> 2] * parts, [25] * parts
    colour_bits = 128 - weight_bits - start - extra - (2 if dual else 0)
    counts_of = [((c >> 2) + 1) * 2 for c in cems]
    total = sum(counts_of)
    enc = next((encoding(r) for r in range(255, 0, -1) if bit_length(encoding(r), total) <= colour_bits), None)
    if enc is None or unquantized(enc) is None or colour_bits <= 0:
        counts["left: not a block the format allows"] += 1
        return block
    q = Quantizer.of(enc)
    used = bit_length(enc, total)
    stored = sequence_read(block >> start & (1 << colour_bits) - 1, enc, total)
    changed, at, new_block = False, 0, block
    same_mode = parts > 1 and len(set(low_bit)) == 1   # (one mode field for all the parts)
    plan = []
    for i, cem in enumerate(cems):
        mine = stored[at:at + counts_of[i]]
        at += counts_of[i]
        if cem not in (6, 8, 9, 10, 12, 13):
            plan.append(None)   # (grey, or HDR: as it is)
            continue
        ends = endpoints(cem, [q.value[s] for s in mine])
        want = tuple(tuple(clamp(round(x)) for x in change(e[:3])) + (e[3],) for e in ends)
        plan.append((cem, mine, ends, want))
    if all(p is None or p[2] == p[3] for p in plan):
        counts["left: grey or unchanged" if any(p is not None for p in plan) else "left: grey or HDR"] += 1
        return block
    if same_mode and any(p is None for p in plan):
        return block
    out, at = list(stored), 0
    for i, p in enumerate(plan):
        n = counts_of[i]
        if p is not None and (p[2] != p[3] or same_mode and p[0] in (9, 13)):
            cem, mine, ends, want = p
            if cem in (6, 10):   # (a colour and how dark its other end is: the colour turned, the darkening kept)
                new = [q.nearest[c] for c in want[1][:3]] + list(mine[3:])
            else:
                new = store(12 if cem >= 12 else 8, want, q)
                if cem in (9, 13):
                    new_block &= ~(1 << low_bit[i])
            out[at:at + n] = new
            changed = True
        at += n
    if not changed:
        return block
    counts["turned"] += 1
    mask = (1 << used) - 1
    return new_block & ~(mask << start) | sequence_write(out, enc) << start


# ---- the colours ----
# (name, hue in degrees or None for no hue of its own, saturation times this, how far towards white, brightness times
# this). The first is the game's own: nothing written for that tunic. A setting's value is its place here: append only.
# The launcher's Cosmetics page lists the same names in the same order (tests/test_rando_cosmetics.py).
COLOURS = (
    ("The game's", None, 1.0, 0.0, 1.0),
    ("Green", 105.0, 1.0, 0.0, 1.0),
    ("Red", 358.0, 1.0, 0.0, 1.0),
    ("Blue", 222.0, 1.0, 0.0, 1.0),
    ("Purple", 275.0, 1.0, 0.0, 1.0),
    ("Pink", 335.0, 0.75, 0.3, 1.0),
    ("Orange", 26.0, 1.0, 0.12, 1.0),
    ("Yellow", 50.0, 1.0, 0.25, 1.0),
    ("Teal", 172.0, 1.0, 0.0, 1.0),
    ("White", None, 0.1, 0.6, 1.0),
    ("Black", None, 0.35, 0.0, 0.3),
)
# What can be coloured: its name here, its line in hookshot_cosmetics.ini, its label, the hues that are its own colour
# (from, to, in degrees), the hue its colour is taken to be, and its colour textures. A texture is a name in Tex
# (without .bntx.zs); or (that name, hues, a hue) for one whose colour is another than the rest's; or (a file of many
# textures, the names of the ones in it). The tunics' were found in their models (Model/Armor_Adult_Goron and _Zora;
# the Kokiri Tunic is on Link's own, Model/Player_Adult) and by --stats.
HUD = "UI/Layout2Archive/Common.Product.100.Nin_Ounce_NVN2.bntx.zs"   # (every picture of the game's screens but the title's)
COSMETICS = (
    # (the Kokiri Tunic's cloth, Angin_Tile_A_Alb, is not Link's alone: young Link's tunic, Mido's clothes, a Kokiri bed
    # and the Fairy Ocarina's strap are the same picture, and change with it. Young Link's other pictures are changed
    # too, below; Mido's vest is his own and stays green over the changed cloth)
    ("kokiri", "cosmetic_tunic_kokiri", "Kokiri Tunic", (70.0, 165.0), 100.0,
     ("Mt_Vest_Player_Adult_Alb", "Angin_Tile_A_Alb",
      # (its stitching and fringe are an olive of their own: taken as that texture's colour, so they come out the
      # tunic's colour and not one a third of the way round from it)
      ("Mt_Angin_Acs_Player_Adult_Alb", (50.0, 165.0), 75.0),
      # (young Link's: his cloth is the shared picture above, so his vest and hat, and the stitching and fringe of his
      # cloth and shorts, go with it. Seen in play before they did: white cloth under a green vest)
      "Mt_Vest_Player_Child_Alb",
      ("Mt_Cloth_Parts_Player_Child_Alb", (50.0, 165.0), 90.0),
      ("Mt_PantsParts_Player_Child_Alb", (50.0, 165.0), 80.0))),
    ("goron", "cosmetic_tunic_goron", "Goron Tunic", (320.0, 15.0), 358.0,
     ("Mt_Vest_Armor_Adult_Goron_Alb", "Mt_Inner_Armor_Adult_Goron_Alb", "Mt_Angin_Armor_Adult_Goron_Alb")),
    ("zora", "cosmetic_tunic_zora", "Zora Tunic", (190.0, 262.0), 222.0,
     ("Mt_Vest_Armor_Adult_Zora_Alb", "Mt_Angin_Armor_Adult_Zora_Alb", "Mt_Angin_Acs_Armor_Adult_Zora_Alb", "Mt_Parts_Armor_Adult_Zora_Alb")),
    # (the hearts of the screen's corner run from red to orange: both are their colour. Their gold frame, HeartFrame_00,
    # is left; the pictures that are only a shape, BC4, have no colour to change)
    ("hearts", "cosmetic_hearts", "Hearts", (335.0, 50.0), 10.0,
     ((HUD, ("HeartW_00_ASTC4x4", "HeartFrameGlow_00", "HeartGlowBase_00", "HeartGlowBase_01", "HeartGlowBase_02", "HeartGlowBase_03",
             "HeartGlowW_00", "HeartGlowW_01", "HeartGlowW_02", "HeartGlowW_03", "HeartGlowW_04",
             "HeartKiraKira_00", "HeartKiraKira_01", "HeartKiraKira_02", "HeartKiraKira_03", "HeartKiraKira_04", "HeartKiraKira_05")),)),
    ("magic", "cosmetic_magic", "Magic meter", (55.0, 175.0), 140.0,
     ((HUD, ("MpGaugeCenter_00", "MpGaugeFlash_00", "MpGaugeFlash_01", "MpGaugeGlow_00", "MpGaugeGlow_01",
             "MpKiraKira_00", "MpKiraKira_01", "MpKiraKira_02")),)),
)
# The shields Link carries: its name here, its line in hookshot_cosmetics.ini, its label, its actor (whose pack is
# changed). And the looks one can be given: a label and the model's name (its project and its model are named alike:
# Model/<name>.<name>.bfres.zs); the first, 0, is the shield's own. The launcher's list is in the same order.
SHIELDS = (
    ("shield_deku", "cosmetic_shield_deku", "Deku Shield", "Weapon_Shield_Deku"),
    ("shield_hylian", "cosmetic_shield_hylian", "Hylian Shield", "Weapon_Shield_Hylian"),
    ("shield_mirror", "cosmetic_shield_mirror", "Mirror Shield", "Weapon_Shield_Mirror"),
)
SHIELD_MODELS = (
    ("Its own", None),
    ("Deku Shield", "Weapon_Shield_Deku"),
    ("Hylian Shield", "Weapon_Shield_Hylian"),
    ("Mirror Shield", "Weapon_Shield_Mirror"),
    ("Dark Link's shield", "Weapon_Shield_Hylian_Dark"),
)
SHIELD_MODEL_FILE = "Component/ModelInfo/"   # (the one file of a shield's pack that names its model)


def shield_look_of(text):
    """a look's place in SHIELD_MODELS, from its number, its label or its model's name; None when it is none of them"""
    text = str(text).strip().lower()
    for i, (label, model) in enumerate(SHIELD_MODELS):
        if text in (str(i), label.lower(), (model or "own").lower(), label.lower().split()[0]):
            return i
    return None


def shield_pack(data, actor, model):
    """A shield actor's pack (a SARC archive) with `model` named as its model: the new bytes, or None when the pack
    names that model already. The pack must not grow: the game's size table holds each pack's size, and this mod
    carries no table (the randomizer's seed has its own). A longer name can add a few bytes to the file; then the
    file's DebugModelScale, 1.0 in every shield and not needed for it, is left out, which gives more back."""
    files = seed.sarc_read(data)
    names = [name for name in files if name.startswith(SHIELD_MODEL_FILE)]
    if len(names) != 1:
        raise ValueError("%s's pack has %d files that name a model, not one" % (actor, len(names)))
    tree, version = seed.byml_parse(files[names[0]])
    kind, rows = tree
    if kind != "dict" or rows.get("FmdbName") != ("string", actor) or rows.get("ModelProjectName") != ("string", actor):
        raise ValueError("%s's pack does not name its own model as this was written for" % actor)
    if model == actor:
        return None
    rows["FmdbName"] = rows["ModelProjectName"] = ("string", model)
    files[names[0]] = seed.byml_build(tree, version)
    new = seed.sarc_write(files)
    if len(new) > len(data):
        scale = rows.get("DebugModelScale")
        one = ("dict", {axis: (210, struct.pack("<f", 1.0)) for axis in "XYZ"})
        if scale is None or scale[0] != "dict" or dict(scale[1]) != one[1]:
            raise ValueError("%s's pack would grow, and its model's scale is not 1" % actor)
        del rows["DebugModelScale"]
        files[names[0]] = seed.byml_build(tree, version)
        new = seed.sarc_write(files)
    if len(new) > len(data):
        raise ValueError("%s's pack would grow (%d bytes, from %d)" % (actor, len(new), len(data)))
    return new


SOFT = 12.0   # (degrees past a tunic's hues over which the change fades out)


def recolour(colour, hues, centre, soft=SOFT):
    """(r, g, b) of 0..255 -> the same in the colour (a row of COLOURS), for the colours whose hue is within hues
    (from, to); a hue keeps its distance from centre, so the cloth's lighter and darker shades stay apart"""
    _, hue, sat, lift, dim = colour
    lo, hi = hues

    def change(rgb):
        h, s, v = colorsys.rgb_to_hsv(*(min(255.0, max(0.0, c)) / 255.0 for c in rgb))
        if s == 0.0:
            return tuple(rgb)
        deg = h * 360.0
        amount = 1.0
        if (deg - lo) % 360.0 > (hi - lo) % 360.0:
            away = min((lo - deg) % 360.0, (deg - hi) % 360.0)
            amount = max(0.0, 1.0 - away / soft) if soft > 0 else 0.0
        if amount <= 0.0:
            return tuple(rgb)
        offset = (deg - centre + 180.0) % 360.0 - 180.0
        new_h = ((hue + offset) % 360.0) / 360.0 if hue is not None else h
        new = colorsys.hsv_to_rgb(new_h, min(1.0, s * sat), min(1.0, (v + (1.0 - v) * lift) * dim))
        return tuple(c + (n * 255.0 - c) * amount for c, n in zip(rgb, new))
    return change


def colour_of(text):
    """a colour's place in COLOURS, from its number or its name; None when it is neither"""
    text = str(text).strip().lower()
    for i, row in enumerate(COLOURS):
        if text == str(i) or text == row[0].lower():
            return i
    return None


# ---- a texture file ----
def images(data):
    """(name, format, width, height, where the image data starts, its size) of each texture of a BNTX file"""
    if data[:4] != b"BNTX":
        raise ValueError("not a BNTX file")
    out, at = [], data.find(b"BRTI")
    while at >= 0:
        fmt, _, w, h = struct.unpack_from("<IIii", data, at + 0x1c)
        size = struct.unpack_from("<I", data, at + 0x50)[0]
        name_at = struct.unpack_from("<Q", data, at + 0x60)[0]
        first = struct.unpack_from("<Q", data, struct.unpack_from("<Q", data, at + 0x70)[0])[0]
        name = data[name_at + 2:name_at + 2 + struct.unpack_from("<H", data, name_at)[0]].decode("utf-8", "replace")
        out.append((name, fmt, w, h, first, size))
        at = data.find(b"BRTI", at + 4)
    return out


def is_astc(fmt):
    return 0x2d <= fmt >> 8 <= 0x3a


def block_size(fmt):
    """(bytes a block, where its two 5:6:5 colours are in it) of a BC1, BC2 or BC3 texture; (16, None) of an ASTC one;
    None of a format not changed here"""
    kind = fmt >> 8
    return (16, None) if is_astc(fmt) else (8, 0) if kind == 0x1a else (16, 8) if kind in (0x1b, 0x1c) else None


def from565(c):
    r, g, b = c >> 11 & 31, c >> 5 & 63, c & 31
    return r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2


def to565(rgb):
    r, g, b = (min(255.0, max(0.0, c)) for c in rgb)
    return int(r * 31.0 / 255.0 + 0.5) << 11 | int(g * 63.0 / 255.0 + 0.5) << 5 | int(b * 31.0 / 255.0 + 0.5)


def turn_bc(colour, change, counts, bc1):
    """A BC colour block (8 bytes as an int: two 5:6:5 colours, then 2 bits a pixel that pick one of them or a mix)
    with its two colours changed. bc1: the order of the two colours means something (the first larger: two mixes;
    else one mix and a see-through pixel), so it is kept, the colours changed over and the pixels' picks with them
    when the change turns it round."""
    c0, c1, picks = colour & 0xFFFF, colour >> 16 & 0xFFFF, colour >> 32
    was = from565(c0), from565(c1)
    now = tuple(change(c) for c in was)
    if all(abs(x - y) < 0.5 for a, b in zip(now, was) for x, y in zip(a, b)):
        counts["left: grey or unchanged"] += 1
        return colour
    n0, n1 = to565(now[0]), to565(now[1])
    if bc1:
        four = c0 > c1
        if four and n0 == n1:   # (equal would make it the other kind: a step apart)
            if n0 & 31 < 31:
                n0 += 1
            else:
                n1 -= 1
        if (n0 > n1) != four and n0 != n1:
            n0, n1 = n1, n0
            # (pick 0 is the first colour, 1 the second; with two mixes 2 and 3 change over too)
            swapped = 0
            for i in range(16):
                pick = picks >> 2 * i & 3
                pick = pick ^ 1 if four or pick < 2 else pick
                swapped |= pick << 2 * i
            picks = swapped
    counts["turned"] += 1
    return n0 | n1 << 16 | picks << 32


def turn(data, change, counts, only=None):
    """a BNTX file's bytes with every block's stored colours changed (ASTC, or BC1 to BC3). only: the names of the
    textures of the file to change (all of them must be there), or None for every one"""
    out = bytearray(data)
    todo = images(data)
    if only is not None:
        missing = sorted(set(only) - {name for name, _, _, _, _, _ in todo})
        if missing:
            raise ValueError("it has no texture named " + ", ".join(missing))
        todo = [image for image in todo if image[0] in only]
    for name, fmt, w, h, first, size in todo:
        kind = block_size(fmt)
        if kind is None:
            raise ValueError("%s is neither ASTC nor BC1 to BC3 (format %#x): not a texture changed here" % (name, fmt))
        if first + size > len(data):
            raise ValueError("%s: its image data runs past the file" % name)
        step, colour_at = kind
        memo = {}
        for at in range(first, first + size - step + 1, step):
            raw = bytes(data[at:at + step])
            new = memo.get(raw)
            if new is None:
                block = int.from_bytes(raw, "little")
                if colour_at is None:
                    block = turn_block(block, change, counts)
                else:
                    shift = 8 * colour_at
                    block = block & (1 << shift) - 1 | turn_bc(block >> shift, change, counts, fmt >> 8 == 0x1a) << shift
                new = memo[raw] = block.to_bytes(step, "little")
            out[at:at + step] = new
    return bytes(out)


def stats(data):
    """what colours a texture's blocks store: a count of stored colours by hue, and of blocks by what was done"""
    hues, counts = collections.Counter(), collections.Counter()

    def note(rgb):
        h, s, v = colorsys.rgb_to_hsv(*(min(255.0, max(0.0, c)) / 255.0 for c in rgb))
        hues["grey or dark" if s < 0.15 or v < 0.08 else "%3d" % (int(h * 360.0 / 30.0 + 0.5) % 12 * 30)] += 1
        return rgb
    turn(data, note, counts)
    return hues, counts


# ---- the mod ----
def settings(game):
    """the tunics' lines of hookshot_cosmetics.ini: {a tunic's name: its colour's place in COLOURS} (0 where it does not say)"""
    got = {name: 0 for name, _, _, _, _, _ in COSMETICS}
    keys = {key: name for name, key, _, _, _, _ in COSMETICS}
    got.update({name: 0 for name, _, _, _ in SHIELDS})   # (the shields' looks: places in SHIELD_MODELS)
    keys.update({key: name for name, key, _, _ in SHIELDS})
    most = dict({name: len(COLOURS) for name in got}, **{name: len(SHIELD_MODELS) for name, _, _, _ in SHIELDS})
    try:
        with open(os.path.join(game, "hookshot_cosmetics.ini"), encoding="utf-8", errors="replace") as f:
            for line in f:
                key, eq, value = line.partition("=")
                if eq and key.strip() in keys:
                    try:
                        v = int(value.strip())
                    except ValueError:
                        continue
                    got[keys[key.strip()]] = v if 0 <= v < most[keys[key.strip()]] else 0
    except OSError:
        pass
    return got


def remove_old(mod):
    """the files a run before this one wrote (its list: cosmetics_manifest.txt), and the folders they leave empty"""
    listing = os.path.join(mod, "cosmetics_manifest.txt")
    if not os.path.isfile(listing):
        return 0
    n = 0
    with open(listing, encoding="utf-8") as f:
        rels = [line.strip() for line in f if line.strip()]
    for rel in rels + ["cosmetics_stamp.txt", "cosmetics_manifest.txt"]:
        path = os.path.normpath(os.path.join(mod, rel))
        if not path.startswith(os.path.normpath(mod) + os.sep) or not os.path.isfile(path):   # (only inside the mod's folder)
            continue
        os.remove(path)
        n += 1
        folder = os.path.dirname(path)
        while folder != os.path.normpath(mod) and not os.listdir(folder):
            os.rmdir(folder)
            folder = os.path.dirname(folder)
    if os.path.isdir(mod) and not os.listdir(mod):
        os.rmdir(mod)
    return n


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("romfs")
    p.add_argument("--game", help="the game folder (default: the folder the romfs is in)")
    for name, _, label, _, _, _ in COSMETICS:
        p.add_argument("--" + name, help="in place of the %s's line: a colour's name or number (%s)" % (label, ", ".join(c[0] for c in COLOURS)))
    for name, _, label, _ in SHIELDS:
        p.add_argument("--" + name.replace("_", "-"), help="in place of the %s's line: a look's name or number (%s)" % (label, ", ".join(m[0] for m in SHIELD_MODELS)))
    p.add_argument("--if-changed", action="store_true", help="do nothing when the mod is already these colours' (the launcher, at Play)")
    p.add_argument("--dry-run", action="store_true", help="say what would change, write nothing")
    p.add_argument("--stats", nargs="+", metavar="TEXTURE", help="say what colours these textures hold (names in Tex, without .bntx.zs), write nothing")
    a = p.parse_args()
    romfs = os.path.abspath(a.romfs)
    game = os.path.abspath(a.game) if a.game else os.path.dirname(romfs)
    mod = os.path.join(game, "mods", MOD)
    chosen = settings(game)
    for name, _, label, _, _, _ in COSMETICS:
        given = getattr(a, name)
        if given is not None:
            if colour_of(given) is None:
                sys.exit("--%s %s: not a colour (%s)" % (name, given, ", ".join(c[0] for c in COLOURS)))
            chosen[name] = colour_of(given)
    for name, _, label, actor in SHIELDS:
        given = getattr(a, name)
        if given is not None:
            if shield_look_of(given) is None:
                sys.exit("--%s %s: not a look (%s)" % (name.replace("_", "-"), given, ", ".join(m[0] for m in SHIELD_MODELS)))
            chosen[name] = shield_look_of(given)
        if SHIELD_MODELS[chosen[name]][1] == actor:   # (its own look, chosen by name: nothing to change)
            chosen[name] = 0
    stamp = "cosmetics %d %s\n" % (VERSION, " ".join("%s=%d" % (name, chosen[name]) for name in [row[0] for row in COSMETICS] + [row[0] for row in SHIELDS]))
    stamp_path = os.path.join(mod, "cosmetics_stamp.txt")
    if not a.stats:
        print("cosmetics: " + ", ".join(["%s %s" % (label, COLOURS[chosen[name]][0]) for name, _, label, _, _, _ in COSMETICS] +
                                        ["%s as %s" % (label, SHIELD_MODELS[chosen[name]][0].lower()) for name, _, label, _ in SHIELDS]))
        if not any(chosen.values()):
            n = 0 if a.dry_run else remove_old(mod)
            print("everything has the game's own colour: nothing to write%s" % (": %d files of the last colours removed" % n if n else ""))
            return
        if a.if_changed:
            try:
                if open(stamp_path, encoding="utf-8").read() == stamp:
                    print("the mod is already these colours': nothing to do")
                    return
            except OSError:
                pass
    try:
        import zstandard as zs
    except ImportError:
        sys.exit("the zstandard package is missing: python -m pip install zstandard")
    dicts = seed.dictionaries(romfs, zs)

    def load(name):
        rel = name if "/" in name else "Tex/%s.bntx.zs" % name
        try:
            return rel, seed.unpack(open(os.path.join(romfs, *rel.split("/")), "rb").read(), zs, dicts)
        except (OSError, ValueError) as e:
            sys.exit("%s: %s. Nothing written." % (rel, e))
    if a.stats:
        for name in a.stats:
            _, data = load(name)
            try:
                hues, kinds = stats(data)
            except ValueError as e:
                print("%s: %s" % (name, e))
                continue
            print("%s: %s" % (name, ", ".join("%dx%d format %#x" % (w, h, f) for _, f, w, h, _, _ in images(data))))
            print("  blocks, each kind once: " + ", ".join("%s %d" % kv for kv in kinds.most_common()))
            print("  colours stored, by hue (degrees): " + ", ".join("%s: %d" % kv for kv in sorted(hues.items())))
        return
    made = collections.OrderedDict()   # rel -> bytes
    for name, _, label, hues, centre, textures in COSMETICS:
        if not chosen[name]:
            continue
        for texture in textures:
            only, its_hues, its_centre = None, hues, centre
            if not isinstance(texture, str) and len(texture) == 2:
                texture, only = texture
            elif not isinstance(texture, str):
                texture, its_hues, its_centre = texture
            change = recolour(COLOURS[chosen[name]], its_hues, its_centre)
            rel = texture if "/" in texture else "Tex/%s.bntx.zs" % texture
            if rel in made:   # (a file two settings change: the hearts and the magic meter)
                data = made[rel]
            else:
                rel, data = load(texture)
            counts = collections.Counter()
            try:
                new = turn(data, change, counts, only)
            except ValueError as e:
                sys.exit("%s: %s. Nothing written." % (rel, e))
            if len(new) != len(data):
                sys.exit("%s changed size: nothing written" % rel)
            made[rel] = new
            print("  %s, %s: %d blocks changed of %d" % (label, "%d pictures of %s" % (len(only), rel.split("/")[-1]) if only else texture,
                                                         counts["turned"] + counts["one colour"], sum(counts.values())))
    for name, _, label, actor in SHIELDS:
        if not chosen[name]:
            continue
        look, model = SHIELD_MODELS[chosen[name]]
        rel, data = load("Pack/Actor/%s.pack.zs" % actor)
        if not os.path.isfile(os.path.join(romfs, "Model", "%s.%s.bfres.zs" % (model, model))):
            sys.exit("Model/%s.%s.bfres.zs is not among the game's files. Nothing written." % (model, model))
        try:
            new = shield_pack(data, actor, model)
        except (ValueError, KeyError, IndexError, struct.error) as e:
            sys.exit("%s: %s. Nothing written." % (rel, e))
        if new is not None:
            made[rel] = new
            print("  %s: the look of %s (%s)" % (label, look, model))
    if a.dry_run:
        print("(dry run: nothing written)")
        return
    removed = remove_old(mod)
    written = []
    for rel, data in made.items():
        out = os.path.join(mod, "romfs", *rel.split("/"))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f:
            # (the screens' file is a quarter of a gigabyte: packed fast)
            f.write(zs.ZstdCompressor(level=9 if len(data) < 32 << 20 else 3, threads=-1).compress(data))
        written.append("romfs/" + rel)
    with open(os.path.join(mod, "cosmetics_manifest.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(written)) + "\n")
    with open(stamp_path, "w", encoding="utf-8") as f:   # (last: a run that stopped half way is made again)
        f.write(stamp)
    print("wrote %s: %d files%s" % (mod, len(made), " (%d files of the last colours replaced)" % removed if removed else ""))


if __name__ == "__main__":
    main()
