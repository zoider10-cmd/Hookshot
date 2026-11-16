"""Where things are in the maps: actors by name, or everything near a place.

    py -I actors.py Ingo                          the map actors whose kind (Gyaml) or name has "Ingo", in every map
    py -I actors.py Skulltula_Gold --map InsideTheDekuTree --full     one map folder, each actor's whole entry
    py -I actors.py --near -82.7 150.6 228.0 --map HyruleField --radius 8     what is within 8 m of a place
    options: --modded (the seed's rewrite of a map: its drops, its moved shelves...), --max 200

Each line: the map folder and file, the kind (Gyaml), its name if it has one, its place (x y z: Go there's and the
checks' file use the same), and what decides whether it is there (Presence: a flag; IsNegation: when it is NOT set).
Maps are Banc/<folder>/*.bcett.byml.zs; a folder has the child's and the adult's files (_Child_, _Adult_). Reading only.
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # (-I leaves this folder out)
import romfs   # noqa: E402


def walk(o, out):
    if isinstance(o, dict):
        if "Gyaml" in o and "Translate" in o:
            out.append(o)
        for v in o.values():
            walk(v, out)
    elif isinstance(o, list):
        for v in o:
            walk(v, out)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("text", nargs="?")
    p.add_argument("--map")
    p.add_argument("--near", nargs=3, type=float)
    p.add_argument("--radius", type=float, default=10.0)
    p.add_argument("--full", action="store_true")
    p.add_argument("--modded", action="store_true")
    p.add_argument("--max", type=int, default=200)
    a = p.parse_args()
    if not a.text and not a.near:
        p.error("a name to find, or --near x y z")
    want = (a.text or "").lower()
    shown = 0
    for rel in romfs.files("Banc"):
        parts = rel.split("/")
        if not rel.endswith(".bcett.byml.zs") or (a.map and parts[1] != a.map):
            continue
        data = romfs.read(rel, a.modded)
        if want and want.encode() not in data.lower():
            continue
        try:
            tree = romfs.byml(data)
        except Exception:
            continue
        found = []
        walk(tree, found)
        for actor in found:
            kind, name = actor.get("Gyaml", ""), actor.get("Name", "")
            pos = [round(v, 1) for v in actor["Translate"]]
            if want and want not in kind.lower() and want not in str(name).lower():
                continue
            if a.near and math.dist(pos, a.near) > a.radius:
                continue
            presence = actor.get("Presence") or (actor.get("Dynamic") or {}).get("Presence")
            when = ""
            if isinstance(presence, dict) and presence.get("FlagName"):
                when = "when %s%s" % ("NOT " if presence.get("IsNegation") else "", presence["FlagName"])
            print("%-22s %-34s %-40s %-24s %s %s" % (parts[1], parts[-1].split(".")[0], kind, name, " ".join("%.1f" % v for v in pos), when))
            if a.full:
                print("    " + json.dumps({k: v for k, v in actor.items() if k not in ("Gyaml", "Translate")})[:1200])
            shown += 1
            if shown >= a.max:
                print("(the first %d: --max for more)" % a.max)
                return


if __name__ == "__main__":
    main()
