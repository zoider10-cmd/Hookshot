"""How a room is wired: every actor around one chest, in full, with the links between them.

Finds the chest with the given event (or hash) in the map files on this PC and writes to one report, rando_room.txt:
every actor of the same room (DefaultDungeonRoomIndex) or within --radius of the chest, with all its parameters; the
links that start or end at one of them, and the actors at their other ends; and the groups of the file that name
them. For finding what holds a room's doors shut (the Forest Temple's Stalfos room and its Bow). Names and values
only, no game files. Nothing is changed.

    python -I tools/rando/rando_room.py "F:\\Games\\OOT Remake Rando\\romfs"
    python -I tools/rando/rando_room.py <romfs> [--event ForestTemple_GetBow | --hash 0x...] [--radius 60] [--out report.txt]

Needs the zstandard package.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rando_locations as loc   # (the BYML reader)
import rando_actors as act      # (a value as indented text)


def hash_of(actor):
    h = actor.get("Hash")
    return h if isinstance(h, int) else None


def position(actor):
    t = actor.get("Translate")
    return tuple(float(x) for x in t[:3]) if isinstance(t, list) and len(t) >= 3 and all(isinstance(x, (int, float)) for x in t[:3]) else None


def link_ends(link):
    """the hashes a link names (Src, Dst, or whatever integer fields it has that look like one)"""
    return [v for k, v in link.items() if isinstance(v, int) and v > 0xffffffff] if isinstance(link, dict) else []


def mentions(v, hashes):
    """does a group (any nesting) name one of the hashes"""
    if isinstance(v, dict):
        return any(mentions(x, hashes) for x in v.values())
    if isinstance(v, list):
        return any(mentions(x, hashes) for x in v)
    return isinstance(v, int) and v in hashes


def room_report(root, chest, radius):
    """the report's lines for one map file's root and the chest found in it"""
    actors = [a for _, lst in loc.actor_lists(root) for a in lst if isinstance(a, dict)]
    by_hash = {hash_of(a): a for a in actors if hash_of(a) is not None}
    dyn = chest.get("Dynamic") if isinstance(chest.get("Dynamic"), dict) else {}
    room, at = dyn.get("DefaultDungeonRoomIndex"), position(chest)

    def inside(a):
        d = a.get("Dynamic") if isinstance(a.get("Dynamic"), dict) else {}
        if room is not None and d.get("DefaultDungeonRoomIndex") == room:
            return True
        p = position(a)
        return at is not None and p is not None and sum((x - y) ** 2 for x, y in zip(p, at)) <= radius * radius

    here = [a for a in actors if inside(a)]
    mine = {hash_of(a) for a in here} - {None}
    # the actors at the other end of a link that starts or ends in the room (a link is kept by one of its two actors)
    others = []
    for a in actors:
        for link in a.get("Links") or []:
            ends = set(link_ends(link)) | {hash_of(a)}
            if ends & mine:
                for h in ends - mine - {None}:
                    if h in by_hash and by_hash[h] not in others:
                        others.append(by_hash[h])
    out = ["room %s, chest at %s: %d actors in the room, %d linked from outside it" % (room, at, len(here), len(others)), ""]
    for title, group in (("== in the room ==", here), ("== linked to the room, outside it ==", others)):
        out.append(title)
        for a in sorted(group, key=lambda a: str(a.get("Gyaml"))):
            out.append("%s  hash %s  at %s" % (a.get("Gyaml", "?"), "%#x" % hash_of(a) if hash_of(a) is not None else "?", position(a)))
            act.lines({k: v for k, v in a.items() if k not in ("Gyaml", "Hash", "Translate")}, 2, out)
            out.append("")
    wide = mine | {hash_of(a) for a in others}
    out.append("== the file's groups that name them ==")
    for name, v in root.items():
        if isinstance(v, list) and not (v and isinstance(v[0], dict) and "Gyaml" in v[0]):
            for i, g in enumerate(v):
                if mentions(g, wide):
                    out.append("%s[%d]:" % (name, i))
                    act.lines(g, 2, out)
    return out


def find(root, event, want_hash):
    for _, lst in loc.actor_lists(root):
        for a in lst:
            if not isinstance(a, dict):
                continue
            d = a.get("Dynamic") if isinstance(a.get("Dynamic"), dict) else {}
            if want_hash is not None and hash_of(a) == want_hash or want_hash is None and d.get("GetEventName") == event:
                return a
    return None


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("romfs")
    p.add_argument("--event", default="ForestTemple_GetBow", help="the chest's GetEventName")
    p.add_argument("--hash", help="the chest's hash, in place of its event")
    p.add_argument("--radius", type=float, default=60.0, help="how far from the chest an actor of another room still counts")
    p.add_argument("--out", default="rando_room.txt")
    a = p.parse_args()
    romfs = os.path.abspath(a.romfs)
    banc = os.path.join(romfs, "Banc")
    if not os.path.isdir(banc):
        sys.exit("no Banc folder in %s" % romfs)
    try:
        import zstandard as zs
    except ImportError:
        sys.exit("the zstandard package is missing: python -m pip install zstandard")
    dicts = loc.dictionaries(romfs, zs)
    want = int(a.hash, 16) if a.hash else None
    out, found = [], 0
    for top, dirs, names in os.walk(banc):
        dirs.sort()
        for n in sorted(names):
            if ".byml" not in n.lower():
                continue
            path = os.path.join(top, n)
            try:
                root = loc.Byml(loc.unpack(open(path, "rb").read(), zs, dicts)).root
            except Exception:
                continue
            chest = find(root, a.event, want) if isinstance(root, dict) else None
            if chest is None:
                continue
            found += 1
            out.append("#### %s" % os.path.relpath(path, romfs).replace("\\", "/"))
            out += room_report(root, chest, a.radius)
            out.append("")
    if not found:
        sys.exit("no chest with %s was found" % ("hash " + a.hash if a.hash else "the event " + a.event))
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("%s: %d map file%s, %d lines" % (a.out, found, "" if found == 1 else "s", len(out)))
    print("Send that file back: it holds actor names and values only, no game files.")


if __name__ == "__main__":
    main()
