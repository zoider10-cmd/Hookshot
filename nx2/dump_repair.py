# (Mako) From Project ReLink (github.com/pixl27/ProjectReLink, GPL-3.0, tools/dump_repair.py, fc5eab8 issue 14); paths adapted.
"""A small mod that stands in for textures a game dump holds damaged.

Some dumps of the game carry a few texture files whose first 8 to 12 KB are zeros (the dumper's own checksum matches that
content, so nothing looks wrong: nx2/dump_check.py finds them). The game cannot decode such a texture and, when a model
needs it, loads the model again and again for ever, 12 to 22 times a second. That takes more than a processor core for good:
with adult Link, whose fairy fountain model is one of them, it costs frames per second everywhere.

This writes, for each damaged texture it knows, an intact texture of the same family with the same format, size, mip count
and resource-table size (so the memory the game sets aside fits), its name changed in place to the damaged one's. The files go
to <mod folder>/romfs/Tex/, which the game reads instead of its own (host/mods.c). Your dump is not changed, and
nothing of the game is in this script: the stand-ins are made from your own files.

    python -I nx2/dump_repair.py <game folder>/romfs <game folder>/mods/00-dump-repair

Needs the zstandard package (Mako's own Python has it: tools/python/python.exe).
Not repaired: Tex/RBake_Scene_GanonStage_G_2_1_d0_t0, a baked atlas whose size no other texture has.
"""
import os
import struct
import sys
import zlib

import zstandard

PAIRS = [   # (damaged, stand-in): same length of name, same ending
    ("CmnTex_Map_Soil_FairyFountain_Floor_D_Nrm", "CmnTex_Map_Rock_FairyFountain_Floor_C_Nrm"),
    ("Rock_WaterTemple_Gate_M_01_Nrm", "Rock_WaterTemple_Gate_P_01_Nrm"),
]


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
    """Its compressed frame does not end where the file ends (nx2/dump_check.py)"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # (python -I does not look beside the script)
    from dump_check import check
    return not check(path)[0]


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    romfs, out = sys.argv[1], sys.argv[2]
    table = size_table(romfs)
    size_of = lambda name: table[zlib.crc32(("Tex/%s.bntx" % name).encode()) & 0xffffffff]
    made = 0
    for bad, good in PAIRS:
        if not damaged(os.path.join(romfs, "Tex", bad + ".bntx.zs")):
            print("%s: intact in this dump, nothing to do" % bad)
            continue
        assert len(bad) == len(good) and bad[-4:] == good[-4:], "names must have the same length and ending"
        assert size_of(bad) == size_of(good), "resource table sizes differ: %d, %d" % (size_of(bad), size_of(good))
        with open(os.path.join(romfs, "Tex", good + ".bntx.zs"), "rb") as f:
            b = zstandard.ZstdDecompressor().decompressobj().decompress(f.read())
        assert b[:4] == b"BNTX" and b.count(good.encode()) >= 1 and bad.encode() not in b
        assert len(b) + 280 == size_of(bad), "content %d bytes against a table size of %d" % (len(b), size_of(bad))
        fixed = b.replace(good.encode(), bad.encode())
        assert len(fixed) == len(b) and fixed.count(bad.encode()) == b.count(good.encode())
        z = zstandard.ZstdCompressor(level=19, write_content_size=True, write_checksum=False).compress(fixed)
        assert zstandard.ZstdDecompressor().decompress(z) == fixed
        os.makedirs(os.path.join(out, "romfs", "Tex"), exist_ok=True)
        with open(os.path.join(out, "romfs", "Tex", bad + ".bntx.zs"), "wb") as f:
            f.write(z)
        print("%s <- %s: %d bytes of content, written %d bytes" % (bad, good, len(fixed), len(z)))
        made += 1
    if made:
        with open(os.path.join(out, "README.txt"), "w", encoding="utf-8", newline="\r\n") as f:
            f.write("Dump repair, made by nx2/dump_repair.py from this game folder's own files.\n\n"
                    "Stand-ins for textures this dump holds damaged:\n"
                    + "".join("  Tex/%s  <-  %s\n" % p for p in PAIRS) +
                    "\nThe real files only come back with a new dump of the game; this folder can then be deleted.\n")
        print("written: " + out)
    else:
        print("this dump needs no repair")


if __name__ == "__main__":
    main()
