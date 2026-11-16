"""What a save holds: a flag's value by its name, or what changed between two saves.

    py -I savedata.py get <save> NAME...          each name's hash, its section and value (or "not in the save")
    py -I savedata.py diff <save A> <save B>      the entries whose value differs, named where the name list knows them
    py -I savedata.py names                       (re)build the name list from the game's files (about a minute; kept)
    py -I savedata.py hash NAME...                just the hashes (as HOS_OOT_SETFLAG takes them)

<save>: a progress.sav path; or a save copy's name (under <GAME>/user/save_copies/save_rando, its newest slot); or
"live" (the newest slot of <GAME>/user/save_rando); a copy's or live's slot by "name#slot_03".

The save (progress.sav): a 32-byte header, then 8-byte entries (a name's murmur3 hash, a 32-bit value). An entry of hash
0 starts a section, its value the section's number (0 to 32); section 0 holds the true/false flags, the others other
types (counts, enums, and offsets into the data after section 32 for strings and arrays: those are shown as they are).
The name list (<WORK>/flag_names.txt, WORK as in run_headless.sh) is the strings of the game's flows, logic, maps and
packs that look like flag names, hashed: a hash it does not know is shown in hex. It stays on this PC.
"""
import argparse
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # (-I leaves this folder out)
import romfs   # noqa: E402

WORK = os.environ.get("WORK") or os.path.join(os.environ.get("TEMP", "/tmp"), "rando-test")
NAMES = os.path.join(WORK, "flag_names.txt")


def save_path(spec):
    if os.path.isfile(spec):
        return spec
    name, _, slot = spec.partition("#")
    base = os.path.join(romfs.GAME, "user", "save_rando") if name == "live" else os.path.join(romfs.GAME, "user", "save_copies", "save_rando", name)
    found = []
    for root, _, names in os.walk(base):
        if "progress.sav" in names and (not slot or os.path.basename(root) == slot):
            p = os.path.join(root, "progress.sav")
            found.append((os.path.getmtime(p), p))
    if not found:
        sys.exit("no save at %s%s" % (base, " (" + slot + ")" if slot else ""))
    return max(found)[1]


def entries(path):
    """{hash: (section, value)} of a save's sections 0 to 32"""
    d = open(path, "rb").read()
    out, section = {}, None
    for at in range(0x20, len(d) - 7, 8):
        k, v = struct.unpack_from("<II", d, at)
        if k == 0:
            if section is not None and v != section + 1:
                break   # (past the sections: the data area, where 0 keys are no markers)
            section = v
            continue
        if section is None:
            continue
        out.setdefault(k, (section, v))
        if section == 32 and at + 8 < len(d) and struct.unpack_from("<I", d, at + 8)[0] == 0:
            break
    return out


def build_names():
    names = set()
    pattern = re.compile(rb"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*")
    for folder in ("Event/EventFlow", "Logic", "AI", "Banc", "GameParameter", "Component"):
        for rel in romfs.files(folder):
            try:
                data = romfs.read(rel) if rel.endswith(".zs") else open(romfs.path_of(rel), "rb").read()
            except Exception:
                continue
            for m in pattern.findall(data):
                if 6 <= len(m) <= 96 and (b"_" in m or b"." in m):
                    names.add(m.decode())
    os.makedirs(WORK, exist_ok=True)
    with open(NAMES, "w", encoding="utf-8") as f:
        for n in sorted(names):
            f.write("%08x %s\n" % (romfs.murmur3(n), n))
    print("%s: %d names" % (NAMES, len(names)))


def known():
    if not os.path.isfile(NAMES):
        print("(building the name list once: %s)" % NAMES, file=sys.stderr)
        build_names()
    out = {}
    with open(NAMES, encoding="utf-8") as f:
        for line in f:
            h, _, n = line.rstrip("\n").partition(" ")
            out.setdefault(int(h, 16), n)
    return out


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("get"); g.add_argument("save"); g.add_argument("names", nargs="+")
    df = sub.add_parser("diff"); df.add_argument("a"); df.add_argument("b"); df.add_argument("--all-sections", action="store_true")
    sub.add_parser("names")
    hs = sub.add_parser("hash"); hs.add_argument("names", nargs="+")
    a = p.parse_args()
    if a.cmd == "names":
        build_names()
    elif a.cmd == "hash":
        for n in a.names:
            print("%08x %s" % (romfs.murmur3(n), n))
    elif a.cmd == "get":
        path = save_path(a.save)
        e = entries(path)
        print(path)
        for n in a.names:
            h = romfs.murmur3(n)
            print("%08x %-60s %s" % (h, n, "section %d: %d" % e[h] if h in e else "not in the save"))
    else:
        pa, pb = save_path(a.a), save_path(a.b)
        ea, eb = entries(pa), entries(pb)
        names = known()
        print("A %s\nB %s" % (pa, pb))
        for h in sorted(set(ea) | set(eb), key=lambda h: (ea.get(h, eb.get(h))[0], names.get(h, "~%08x" % h))):
            va, vb = ea.get(h), eb.get(h)
            if va == vb or (not a.all_sections and (va or vb)[0] >= 32):
                continue
            print("%08x %-64s %s -> %s" % (h, names.get(h, "?"), "%d:%d" % va if va else "-", "%d:%d" % vb if vb else "-"))


if __name__ == "__main__":
    main()
