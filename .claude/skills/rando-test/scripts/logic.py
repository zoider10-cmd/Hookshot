"""The game's logic files (AINB: Logic/<name>.logic.module.ainb, AI/*.ainb): what makes things appear, go or open.

    py -I logic.py <name>                 its nodes (class, the links into each by input name) and the names it holds
    py -I logic.py --find <text>          the logic and AI files that name <text> (a flag, an actor, an area...)
    py -I logic.py --where <name>         the map files whose actors use that logic file (Banc, by its name)
    add --modded to read the mods' copy (the seed's rewrite, e.g. a door's rule) in place of the game's

A logic file is a small graph: nodes such as HoldGameDataGetBoolSimple (reads a flag), InvBool/OperateAND/OperateOR,
and an actor's node whose inputs are Logic_Create / Logic_Delete / EnableOpen (makes it, takes it away, opens it). The
names a file holds are listed whole: which flag a node reads is not tied to its node here; read the order and the
file's names together (or the seed's sword_prompt and bombchu_door_open, which edit them). Nodes are 0x3C bytes from
0x74 (class name at +8, hash at +12); the string pool is at the header's +0x24. Reading only.
"""
import argparse
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # (-I leaves this folder out)
import romfs   # noqa: E402

LINK_NAMES = ("BoolMulti", "Bool", "EnableOpen", "EnableDo", "Logic_Delete", "Logic_Create", "Value", "Input", "Logic_Enable")


def rel_of(name):
    if "/" in name:
        return name
    for rel in ("Logic/%s.logic.module.ainb" % name, "Logic/%s" % name):
        if os.path.isfile(romfs.path_of(rel)):
            return rel
    hits = [r for r in romfs.files("AI") if r.split("/")[-1].split(".")[0] == name]
    if hits:
        return hits[0]
    sys.exit("no logic file %s (Logic/<name>.logic.module.ainb, or a path from the romfs)" % name)


def read(rel, modded):
    return romfs.read(rel, modded) if rel.endswith(".zs") else open(romfs.path_of(rel, modded), "rb").read()


def show(rel, modded):
    d = read(rel, modded)
    u32 = lambda a: struct.unpack_from("<I", d, a)[0]
    pool = u32(0x24)
    s = lambda off: d[pool + off:].split(b"\0")[0].decode("utf-8", "replace")
    n = u32(0x10)
    print("== %s: %d nodes (%d bytes)" % (rel, n, len(d)))
    starts = [u32(0x74 + 0x3C * i + 0x14) for i in range(n)] + [u32(0x2C)]
    for i in range(n):
        a, b = starts[i], starts[i + 1]
        links = []
        for x in range(a, max(a, b - 7), 4):
            v, nm = u32(x), u32(x + 4)
            if v < n and 0 < nm < len(d) - pool and s(nm) in LINK_NAMES:
                links.append("%s<-%d" % (s(nm), v))
        print("  %2d %-44s %s" % (i, s(u32(0x74 + 0x3C * i + 8)), " ".join(links)))
    names = sorted(set(m.decode() for m in re.findall(rb"[A-Za-z][A-Za-z0-9_.]{5,95}", d[pool:])
                       if b"_" in m or b"." in m))
    print("  names:", ", ".join(names))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("name", nargs="?")
    p.add_argument("--find")
    p.add_argument("--where")
    p.add_argument("--modded", action="store_true")
    a = p.parse_args()
    if a.find:
        want = a.find.encode()
        for rel in romfs.files("Logic") + romfs.files("AI"):
            try:
                if want in read(rel, a.modded):
                    print(rel)
            except Exception:
                continue
        return
    if a.where:
        want = a.where.encode()
        for rel in romfs.files("Banc"):
            if not rel.endswith(".bcett.byml.zs"):
                continue
            data = romfs.read(rel)
            if want in data:
                print(rel)
        return
    if not a.name:
        p.error("a logic file's name, --find or --where")
    show(rel_of(a.name), a.modded)


if __name__ == "__main__":
    main()
