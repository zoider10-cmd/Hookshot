# (Mako) From Project ReLink (github.com/pixl27/ProjectReLink, GPL-3.0, tools/dump_repair.py, bd01376); paths adapted.
"""A small mod that stands in for the textures a game dump holds damaged.

Some dumps of the game carry texture files whose first 8 to 12 KB are zeros (the dumper's own checksum matches that content,
so nothing looks wrong: nx2/dump_check.py finds them). Which files, and how many, differs from one dump to another. The game
cannot decode such a texture. When a model needs it, the model never finishes loading: it stays blurry or is not drawn, and
the game loads it again and again for ever, 12 to 22 times a second (more than a processor core for good). When it is a
piece of an area's baked lighting (the RBake_Scene_ files), everything that piece lights is drawn black.

This finds every damaged texture of the dump and writes, for each one that has a relative, an intact texture of the same
kind with the same format, size, mip count and resource-table size (so the memory the game sets aside fits), its name changed
in place to the damaged one's. The relative is, in this order: the pair this script knows by name (PAIRS), the same texture
of the other age (..._Child_... for ..._Adult_... and back: an area's baked lighting has both), or the texture of the same
size and kind whose name is the nearest. The files go to <mod folder>/romfs/Tex/, which the game reads instead of its own
(host/mods.c). Your dump is not changed, and nothing of the game is in this script: the stand-ins are made from
your own files. A stand-in is a relative, not the real texture: only a new dump of the game brings that back.

    python -I nx2/dump_repair.py <game folder>/romfs <game folder>/mods/00-dump-repair

Needs the zstandard package (Mako's own Python has it: tools/python/python.exe).
"""
import os
import re
import struct
import sys
import zlib

import zstandard

ZSTD = b"\x28\xb5\x2f\xfd"
PAIRS = {   # damaged -> stand-in, checked by hand: same length of name, same ending
    "CmnTex_Map_Soil_FairyFountain_Floor_D_Nrm": "CmnTex_Map_Rock_FairyFountain_Floor_C_Nrm",
    "Rock_WaterTemple_Gate_M_01_Nrm": "Rock_WaterTemple_Gate_P_01_Nrm",
}


def size_table(romfs):
    """The game's resource size table: name checksum -> bytes set aside (zstd with the dictionary of Pack/ZsDic.pack.zs)"""
    with open(os.path.join(romfs, "Pack", "ZsDic.pack.zs"), "rb") as f:
        pack = zstandard.ZstdDecompressor().decompress(f.read(), max_output_size=64 << 20)
    data_off = struct.unpack_from("<I", pack, 0x0c)[0]
    start, end = struct.unpack_from("<II", pack, 0x20 + 8)   # (the first file of the archive: zs.zsdic)
    folder = os.path.join(romfs, "System", "Resource")
    with open(os.path.join(folder, [n for n in os.listdir(folder) if "ResourceSizeTable" in n][0]), "rb") as f:
        raw = f.read()
    dictionary = zstandard.ZstdCompressionDict(pack[data_off + start:data_off + end])
    t = zstandard.ZstdDecompressor(dict_data=dictionary).decompress(raw, max_output_size=256 << 20)
    if t[:6] != b"RESTBL":
        sys.exit("the resource size table could not be read")
    n = struct.unpack_from("<I", t, 14)[0]
    return {struct.unpack_from("<I", t, 22 + 8 * i)[0]: struct.unpack_from("<I", t, 26 + 8 * i)[0] for i in range(n)}


def damaged(path):
    """The file is not one zstd frame that ends where the file ends. Only the frame's header and its block headers are read
    (3 bytes every 128 KB at most), so a whole Tex folder takes seconds. The two forms seen: the file starts with zeros (its
    first pages as the dumper read them), or it is a frame followed by bytes that are not its own (an older extraction)"""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(18)
        if len(head) < 6 or head[:4] != ZSTD:
            return True
        fhd = head[4]
        single, checksum = (fhd >> 5) & 1, (fhd >> 2) & 1
        p = 5 + (0 if single else 1) + (0, 1, 2, 4)[fhd & 3] + (1 if single else 0, 2, 4, 8)[fhd >> 6]
        while True:
            if p + 3 > size:
                return True
            f.seek(p)
            b = f.read(3)
            h = b[0] | b[1] << 8 | b[2] << 16
            last, kind, n = h & 1, (h >> 1) & 3, h >> 3
            if kind == 3:
                return True
            p += 3 + (1 if kind == 1 else n)
            if p > size:
                return True
            if last:
                break
        return p + (4 if checksum else 0) != size


def scan(tex, names, memo):
    """The damaged ones of `names`. A file found intact is remembered in `memo` with its size and time, and not read again
    while they stay the same: the first check of a dump reads every file's block headers (a minute or two on a slow disk,
    eight files at once), the later ones only ask for sizes and times"""
    from concurrent.futures import ThreadPoolExecutor
    known = {}
    try:
        with open(memo, encoding="utf-8") as f:
            for line in f:
                size, mtime, name = line.rstrip("\n").split(" ", 2)
                known[name] = (int(size), int(mtime))
    except (OSError, ValueError):
        known = {}
    stats = {}
    for n in names:
        st = os.stat(os.path.join(tex, n + ".bntx.zs"))
        stats[n] = (st.st_size, st.st_mtime_ns)
    todo = [n for n in names if known.get(n) != stats[n]]
    with ThreadPoolExecutor(8) as ex:
        results = dict(zip(todo, ex.map(lambda n: damaged(os.path.join(tex, n + ".bntx.zs")), todo)))
    bad = {n for n in todo if results[n]}
    try:
        os.makedirs(os.path.dirname(memo), exist_ok=True)
        with open(memo + ".part", "w", encoding="utf-8", newline="\n") as f:
            f.writelines("%d %d %s\n" % (stats[n][0], stats[n][1], n) for n in names if n not in bad)
        os.replace(memo + ".part", memo)
    except OSError:
        pass   # (not remembered: the next check reads them again)
    return bad


def kind_of(name):
    """What a texture is, by its name's ending: _Nrm, _Alb, ... or a baked lighting piece's _d0_t0, _d1_shgi0_uf3, ..."""
    m = re.search(r"_(d\d+_[a-z0-9]+(?:_[a-z0-9]+)?)$", name)
    return m.group(1) if m else name.rsplit("_", 1)[-1]


def common(a, b):
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return i


def other_age(name):
    if "_Child_" in name:
        return name.replace("_Child_", "_Adult_", 1)
    if "_Adult_" in name:
        return name.replace("_Adult_", "_Child_", 1)
    return None


def content(romfs, name):
    with open(os.path.join(romfs, "Tex", name + ".bntx.zs"), "rb") as f:
        return zstandard.ZstdDecompressor().decompressobj().decompress(f.read())


def stand_in(romfs, bad, good):
    """The texture `good` under the name `bad`, compressed; None (and why) when it cannot stand in"""
    try:
        b = content(romfs, good)
    except zstandard.ZstdError as e:
        return None, "%s does not decompress (%s)" % (good, e)
    if b[:4] != b"BNTX" or b.count(good.encode()) < 1 or bad.encode() in b:
        return None, "%s is not a texture file that only names itself" % good
    fixed = b.replace(good.encode(), bad.encode())
    if len(fixed) != len(b):
        return None, "names of different lengths"
    z = zstandard.ZstdCompressor(level=19, write_content_size=True, write_checksum=False).compress(fixed)
    assert zstandard.ZstdDecompressor().decompress(z) == fixed
    return z, len(fixed)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        sys.exit(__doc__)
    romfs, out = args
    # (a test's switch: the names listed in this file, one a line, are taken as damaged too)
    pretend = set()
    for a in sys.argv[1:]:
        if a.startswith("--pretend="):
            with open(a.split("=", 1)[1], encoding="utf-8") as f:
                pretend = {line.strip() for line in f if line.strip()}
    tex = os.path.join(romfs, "Tex")
    names = sorted(n[:-8] for n in os.listdir(tex) if n.endswith(".bntx.zs"))
    found = scan(tex, names, os.path.join(out, "checked.txt"))
    bad = [n for n in names if n in pretend or n in found]
    out_tex = os.path.join(out, "romfs", "Tex")
    have = sorted(n[:-8] for n in os.listdir(out_tex) if n.endswith(".bntx.zs")) if os.path.isdir(out_tex) else []
    if not bad:
        for n in have:   # (a new dump: the stand-ins of the old one go)
            os.remove(os.path.join(out_tex, n + ".bntx.zs"))
        if have and os.path.exists(os.path.join(out, "README.txt")):
            os.remove(os.path.join(out, "README.txt"))
        print("this dump needs no repair (%d texture files checked)" % len(names))
        return
    table = size_table(romfs)
    size_of = {n: table.get(zlib.crc32(("Tex/%s.bntx" % n).encode()) & 0xffffffff) for n in names}
    place = {n: i for i, n in enumerate(names)}
    sound = [n for n in names if n not in set(bad)]
    by_size = {}
    for n in sound:
        by_size.setdefault((size_of[n], kind_of(n), len(n)), []).append(n)
    made, left = [], []
    for b in bad:
        choices = []
        if b in PAIRS:
            choices.append(PAIRS[b])
        twin = other_age(b)
        if twin:
            choices.append(twin)
        if size_of[b] is not None:
            near = by_size.get((size_of[b], kind_of(b), len(b)), [])
            # (the nearest name first: the longest common beginning, then the closest in the folder's order)
            choices += sorted(near, key=lambda n: (-common(n, b), abs(place[n] - place[b])))[:6]
        z, why = None, "no intact texture of the same size and kind has a name of the same length"
        for g in dict.fromkeys(choices):
            if g not in place or g in set(bad) or len(g) != len(b) or kind_of(g) != kind_of(b):
                continue
            # (the same size in the table; the other age's texture may also be smaller: it fits in what the game sets aside)
            if size_of[g] != size_of[b] and not (g == twin and size_of[g] is not None and size_of[b] is not None and
                                                 size_of[g] < size_of[b]):
                continue
            z, why = stand_in(romfs, b, g)
            if z:
                os.makedirs(out_tex, exist_ok=True)
                with open(os.path.join(out_tex, b + ".bntx.zs"), "wb") as f:
                    f.write(z)
                made.append((b, g))
                print("%s <- %s: %d bytes of content, written %d bytes" % (b, g, why, len(z)))
                break
        if not z:
            left.append((b, why))
            print("%s: no stand-in (%s)" % (b, why))
    for n in have:   # (stand-ins of textures that are intact now, or have none any more)
        if n not in {m[0] for m in made}:
            os.remove(os.path.join(out_tex, n + ".bntx.zs"))
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "README.txt"), "w", encoding="utf-8", newline="\r\n") as f:
        f.write("Dump repair, made by nx2/dump_repair.py from this game folder's own files.\n\n"
                "This copy of the game holds %d damaged texture file(s). Stand-ins, each an intact relative under the damaged "
                "file's name:\n" % len(bad)
                + "".join("  Tex/%s  <-  %s\n" % p for p in made)
                + ("\nDamaged, with no stand-in (what uses them can look black, blurry or be missing):\n"
                   + "".join("  Tex/%s  (%s)\n" % p for p in left) if left else "")
                + "\nThe real files only come back with a new dump of the game; this folder can then be deleted.\n")
    areas = sorted({re.sub(r"^RBake_Scene_(.+?)_G\d?_.*$", r"\1", b) for b, _ in left if b.startswith("RBake_Scene_")})
    print("this dump holds %d damaged texture file(s): %d with a stand-in, %d without%s" % (
        len(bad), len(made), len(left), (" (baked lighting of: %s)" % ", ".join(areas)) if areas else ""))
    print("written: " + out)


if __name__ == "__main__":
    main()
