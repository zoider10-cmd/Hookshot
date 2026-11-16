"""Shared by the skill's readers: the game's files on this PC, read with tools/rando/rando_seed.py's readers.

GAME (environment) is the game folder (default F:\\Games\\OOT Remake Rando); its romfs is the game's own files, and a mod's
copy (mods/rando-seed, mods/cosmetics, mods/zz-cosmetics-models) wins when asked for (`modded=True`), as in the game.
Nothing here writes anything. What these read is the game's: it stays on this PC.
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools", "rando"))
import rando_seed as R   # noqa: E402

GAME = os.environ.get("GAME", r"F:\Games\OOT Remake Rando")
if GAME.startswith("/") and len(GAME) > 2 and GAME[2] == "/":   # (a Git Bash path, /f/...)
    GAME = GAME[1].upper() + ":" + GAME[2:].replace("/", "\\")
ROMFS = os.path.join(GAME, "romfs")
MODS = ("zz-cosmetics-models", "rando-seed", "cosmetics")   # (the later a folder sorts, the more it wins: this order)
_zs = _dicts = None


def zstd():
    global _zs, _dicts
    if _zs is None:
        import zstandard
        _zs, _dicts = zstandard, R.dictionaries(ROMFS, zstandard)
    return _zs, _dicts


def path_of(rel, modded=False):
    if modded:
        for mod in MODS:
            p = os.path.join(GAME, "mods", mod, "romfs", *rel.split("/"))
            if os.path.isfile(p):
                return p
    return os.path.join(ROMFS, *rel.split("/"))


def read(rel, modded=False):
    """a file of the game (rel to romfs), unpacked when it is .zs"""
    data = open(path_of(rel, modded), "rb").read()
    if rel.endswith(".zs"):
        zs, dicts = zstd()
        data = R.unpack(data, zs, dicts)
    return data


def files(folder):
    """the files of a romfs folder, rel paths, sorted"""
    base = os.path.join(ROMFS, *folder.split("/"))
    out = []
    for root, _, names in os.walk(base):
        for n in names:
            out.append(os.path.relpath(os.path.join(root, n), ROMFS).replace("\\", "/"))
    return sorted(out)


def plain(node):
    """a BYML tree (rando_seed.byml_parse's) as Python values"""
    kind, value = node
    if kind == "dict":
        return {k: plain(v) for k, v in value.items()}
    if kind == "array":
        return [plain(v) for v in value]
    if kind == "string":
        return value
    if kind == 0xD0:
        return bool(struct.unpack("<I", value)[0])
    if kind == 0xD1:
        return struct.unpack("<i", value)[0]
    if kind == 0xD2:
        return round(struct.unpack("<f", value)[0], 3)
    if kind == 0xD3:
        return struct.unpack("<I", value)[0]
    if kind in (0xD4, 0xD5):
        return hex(struct.unpack("<Q", value[:8])[0])
    return value.hex() if isinstance(value, (bytes, bytearray)) else value


def byml(data):
    return plain(R.byml_parse(data)[0])


def murmur3(text, seed=0):
    """the game's hash of a flag's name (its saves and HOS_OOT_SETFLAG name flags by it)"""
    data = text.encode() if isinstance(text, str) else text
    c1, c2, h, n = 0xCC9E2D51, 0x1B873593, seed, len(data) // 4
    rot = lambda x, r: ((x << r) | (x >> (32 - r))) & 0xFFFFFFFF
    for i in range(n):
        k = rot((struct.unpack_from("<I", data, i * 4)[0] * c1) & 0xFFFFFFFF, 15) * c2 & 0xFFFFFFFF
        h = (rot(h ^ k, 13) * 5 + 0xE6546B64) & 0xFFFFFFFF
    tail, k = data[n * 4:], 0
    for i in reversed(range(len(tail))):
        k = (k << 8) | tail[i]
    if tail:
        h ^= rot((k * c1) & 0xFFFFFFFF, 15) * c2 & 0xFFFFFFFF
    h ^= len(data)
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & 0xFFFFFFFF
    return h ^ (h >> 16)
