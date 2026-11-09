"""The game's item locations: every chest, Gold Skulltula, Heart Piece and item actor placed in the maps.

Reads the map placement files of an extracted game (romfs/Banc/**/*.bcett.byml.zs, BYML) on this PC and writes one
text report, rando_locations.txt: for each such actor its map, its type, its name, where it stands and its own
parameters (what a chest holds is one of them). Names and numbers only, no game files. Nothing is changed.

    python -I tools/rando/rando_locations.py "F:\\Games\\OOT Remake Rando\\romfs"
    python -I tools/rando/rando_locations.py <romfs> [--out report.txt] [--all-keys]

Needs the zstandard package.
"""
import argparse
import collections
import os
import re
import struct
import sys

ZSTD = b"\x28\xb5\x2f\xfd"
# (an actor is listed when its type, its name or one of its parameters' values says one of these)
WANT = re.compile(r"TBox|Treasure|Token|Skulltula_Gold|GoldSkull|HeartPiece|HeartContainer|^Item_|^Weapon_|^Armor_|SmallKey|BossKey|"
                  r"Rupee|Drop|Shop|Present|Reward|Pouch", re.I)
CHEST = re.compile(r"TBox|TreasureBox", re.I)


class Byml:
    """A BYML document (little-endian, "YB"), read into Python lists and dicts"""

    def __init__(self, data):
        if data[:2] != b"YB":
            raise ValueError("not a little-endian BYML (%r)" % data[:4])
        self.d = data
        self.version = struct.unpack_from("<H", data, 2)[0]
        keys, strings, root = struct.unpack_from("<III", data, 4)
        self.keys = self.table(keys) if keys else []
        self.strings = self.table(strings) if strings else []
        self.unknown = collections.Counter()
        self.root = self.node(data[root], root) if root else None

    def table(self, at):
        d = self.d
        if d[at] != 0xC2:
            raise ValueError("no string table at %#x" % at)
        n = int.from_bytes(d[at + 1:at + 4], "little")
        out = []
        for k in range(n):
            s = at + struct.unpack_from("<I", d, at + 4 + 4 * k)[0]
            out.append(d[s:d.index(b"\0", s)].decode("utf-8", "replace"))
        return out

    def value(self, kind, raw, at):
        """a value of type kind held in the 4 bytes at `at` (raw: those bytes as a number)"""
        d = self.d
        if kind == 0xA0:
            return self.strings[raw] if raw < len(self.strings) else "<string %d>" % raw
        if kind in (0xC0, 0xC1, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F):
            return self.node(d[raw], raw)
        if kind == 0xD0:
            return bool(raw)
        if kind == 0xD1:
            return struct.unpack_from("<i", d, at)[0]
        if kind == 0xD2:
            return round(struct.unpack_from("<f", d, at)[0], 4)
        if kind == 0xD3:
            return raw
        if kind == 0xD4:
            return struct.unpack_from("<q", d, raw)[0]
        if kind == 0xD5:
            return struct.unpack_from("<Q", d, raw)[0]
        if kind == 0xD6:
            return round(struct.unpack_from("<d", d, raw)[0], 6)
        if kind == 0xFF:
            return None
        if kind in (0xA1, 0xA2):
            return "<binary>"
        self.unknown[kind] += 1
        return "<type %#x>" % kind

    def node(self, kind, at):
        d = self.d
        n = int.from_bytes(d[at + 1:at + 4], "little")
        if kind == 0xC0:   # an array: the types, padded to 4 bytes, then the values
            vals = at + 4 + (n + 3 & ~3)
            return [self.value(d[at + 4 + k], struct.unpack_from("<I", d, vals + 4 * k)[0], vals + 4 * k) for k in range(n)]
        if kind == 0xC1:   # a dictionary: (key 24 bits, type 8 bits, value) each
            out = {}
            for k in range(n):
                e = at + 4 + 8 * k
                key = int.from_bytes(d[e:e + 3], "little")
                out[self.keys[key] if key < len(self.keys) else "<key %d>" % key] = self.value(
                    d[e + 3], struct.unpack_from("<I", d, e + 4)[0], e + 4)
            return out
        if 0x20 <= kind <= 0x2F:   # a map keyed by hashes: (hash, value) each, then the types
            width = 8 if kind & 1 else 4   # (0x20: 32-bit hashes, 0x21: 64-bit; the others are read as 0x20 and may be wrong)
            step = width + 4
            types = at + 4 + step * n
            out = {}
            for k in range(n):
                e = at + 4 + step * k
                h = int.from_bytes(d[e:e + width], "little")
                out["#%0*x" % (width * 2, h)] = self.value(d[types + k], struct.unpack_from("<I", d, e + width)[0], e + width)
            return out
        self.unknown[kind] += 1
        return "<node %#x>" % kind


def unpack(data, zs, dicts):
    if data[:4] != ZSTD:
        return data
    try:
        return zs.ZstdDecompressor().decompress(data, max_output_size=1 << 28)
    except Exception:
        pass
    for d in dicts:
        try:
            return zs.ZstdDecompressor(dict_data=d).decompress(data, max_output_size=1 << 28)
        except Exception:
            pass
    raise ValueError("could not be decompressed")


def dictionaries(romfs, zs):
    try:
        raw = zs.ZstdDecompressor().decompress(open(os.path.join(romfs, "Pack", "ZsDic.pack.zs"), "rb").read(), max_output_size=1 << 28)
        start = struct.unpack_from("<I", raw, 0x0c)[0]
        out = []
        for k in range(struct.unpack_from("<H", raw, 0x1a)[0]):
            _, _, st, end = struct.unpack_from("<IIII", raw, 0x20 + k * 16)
            out.append(zs.ZstdCompressionDict(raw[start + st:start + end], dict_type=zs.DICT_TYPE_FULLDICT))
        return out
    except Exception:
        return []


def short(v, limit=160):
    """a value on one line"""
    if isinstance(v, dict):
        s = "{" + ", ".join("%s: %s" % (k, short(x, 60)) for k, x in v.items()) + "}"
    elif isinstance(v, list):
        s = "[" + ", ".join(short(x, 60) for x in v) + "]"
    elif isinstance(v, int) and not isinstance(v, bool) and v > 0xFFFF:
        s = "%#x" % v
    else:
        s = str(v)
    return s if len(s) <= limit else s[:limit - 3] + "..."


def strings_of(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for k, x in v.items():
            yield k
            yield from strings_of(x)
    elif isinstance(v, list):
        for x in v:
            yield from strings_of(x)


def actor_lists(root):
    """(list name, actors) for every list of dictionaries with a Gyaml (an actor's type) under the root"""
    if isinstance(root, dict):
        for name, v in root.items():
            if isinstance(v, list) and v and isinstance(v[0], dict) and any("Gyaml" in a for a in v[:20] if isinstance(a, dict)):
                yield name, v


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("romfs")
    p.add_argument("--out", default="rando_locations.txt")
    p.add_argument("--all-keys", action="store_true", help="every parameter of each listed actor (chests always show theirs)")
    a = p.parse_args()
    romfs = os.path.abspath(a.romfs)
    banc = os.path.join(romfs, "Banc")
    if not os.path.isdir(banc):
        sys.exit("no Banc folder in %s" % romfs)
    try:
        import zstandard as zs
    except ImportError:
        sys.exit("the zstandard package is missing: python -m pip install zstandard")
    dicts = dictionaries(romfs, zs)

    out, problems = [], []
    say = out.append
    by_type = collections.Counter()          # actor type -> how many listed
    chest_keys = collections.Counter()       # a chest's parameters -> how many chests have it
    chest_values = collections.defaultdict(collections.Counter)   # a chest's parameter -> its values
    root_shapes = collections.Counter()
    listed = total = 0
    body = []
    paths = []
    for top, dirs, names in os.walk(banc):
        dirs.sort()
        paths += [os.path.join(top, n) for n in sorted(names) if ".byml" in n.lower()]
    for path in paths:
        rel = os.path.relpath(path, romfs).replace("\\", "/")
        try:
            doc = Byml(unpack(open(path, "rb").read(), zs, dicts))
        except Exception as e:
            problems.append("%s: %s: %s" % (rel, type(e).__name__, e))
            continue
        if doc.unknown:
            problems.append("%s: node types not understood: %s" % (rel, ", ".join("%#x x%d" % kv for kv in doc.unknown.items())))
        root = doc.root
        root_shapes[(type(root).__name__, tuple(sorted(root)) if isinstance(root, dict) else ())] += 1
        lines, shown = [], 0
        for list_name, actors in actor_lists(root):
            for i, actor in enumerate(actors):
                if not isinstance(actor, dict):
                    continue
                total += 1
                kind = str(actor.get("Gyaml", "?"))
                dyn = actor.get("Dynamic") if isinstance(actor.get("Dynamic"), dict) else {}
                # (the type, the name, the Dynamic block's keys and values, and the other parameters' values)
                texts = [kind, str(actor.get("Name", ""))] + list(strings_of(dyn))
                texts += [t for k, v in actor.items() if k != "Dynamic" for t in strings_of(v if not isinstance(v, dict) else list(v.values()))]
                if not any(WANT.search(t) for t in texts):
                    continue
                listed += 1
                by_type[kind] += 1
                if CHEST.search(kind):
                    for k, v in dyn.items():
                        chest_keys[k] += 1
                        chest_values[k][short(v, 60)] += 1
                    for k in actor:
                        chest_keys["(actor) " + k] += 1
                pos = actor.get("Translate")
                where = "(%s)" % ", ".join("%.1f" % c for c in pos) if isinstance(pos, list) and all(
                    isinstance(c, (int, float)) for c in pos) else ""
                ident = actor.get("Hash")
                lines.append("  %-34s %-34s %s  hash %s  %s" % (kind, actor.get("Name", ""), where,
                                                               short(ident) if ident is not None else "-", short(dyn, 400) if dyn else ""))
                shown += 1
                if a.all_keys or CHEST.search(kind):   # (a chest's other parameters always: one of them may be what it holds)
                    for k, v in actor.items():
                        if k not in ("Gyaml", "Name", "Translate", "Hash", "Dynamic"):
                            lines.append("      %s = %s" % (k, short(v, 300)))
        if lines:
            body.append("%s  (BYML version %d): %d listed" % (rel, doc.version, shown))
            body += lines
            body.append("")

    say("item locations: %d map files, %d actors, %d listed" % (len(paths), total, listed))
    say("")
    say("== 1. problems (%d) ==" % len(problems))
    out.extend("  " + x for x in problems[:60])
    say("")
    say("== 2. what a map file's top level holds ==")
    for (kind, keys), n in root_shapes.most_common(12):
        say("  x%d  %s: %s" % (n, kind, ", ".join(keys)))
    say("")
    say("== 3. listed actors by type ==")
    for kind, n in by_type.most_common(400):
        say("  %5d  %s" % (n, kind))
    say("")
    say("== 4. chests: their parameters, and each one's most common values ==")
    for k, n in chest_keys.most_common(80):
        vals = chest_values.get(k)
        say("  %5d  %s%s" % (n, k, "   e.g. " + ", ".join("%s x%d" % kv for kv in vals.most_common(25)) if vals else ""))
    say("")
    say("== 5. every listed actor, by map ==")
    out.extend(body)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("wrote %s (%d lines, %.0f KB): %d map files, %d actors, %d listed, %d problems" % (
        os.path.abspath(a.out), len(out), os.path.getsize(a.out) / 1024, len(paths), total, listed, len(problems)))


if __name__ == "__main__":
    main()
