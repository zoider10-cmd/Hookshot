"""Rooms that can shut Link in: every shutter that turns saving and the warp songs off, and what is around it.

The Forest Temple's Stalfos room was found in play: its shutter is opened by an eye switch (so by the Bow, which its
chest held), and while it is shut the warp songs do not work (the shutter's IsDisableSaveAndWarp). This lists every
shutter of the game with that parameter, with the chests and the switches within --radius of it, and marks a chest
whose rule (RULES of rando_seed.py) does not ask for the item a switch beside it takes:

    eye switch: the Bow (the Slingshot in the dungeons Link is a child in)
    hammer switch: the Megaton Hammer    solar switch: the Mirror Shield

A mark is a room to look at in play, not a finding: what opens a shutter is a logic module's doing and is not in the
map files, a switch near a shutter may open something else (the Deku Tree's Slingshot room: its eye drops a ladder),
and most of these shutters open when the room's enemies are dead. Names and values only, nothing is changed.

    python -I tools/rando/rando_shutters.py "F:\\Games\\OOT Remake Rando\\romfs" [--radius 30]

Needs the zstandard package.
"""
import argparse
import collections
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rando_locations as loc   # (the BYML reader)
import rando_seed as seed       # (the rules)

# a switch's Gyaml holds one of these: the items one of which it takes
TAKES = (("EyeSwitch", (seed.BOW,)), ("HammerSwitch", (seed.HAM,)), ("SolarSwitch", (seed.MS,)))
# (where Link is a child, or can be either: an eye takes the Slingshot there. Elsewhere the Slingshot, which every
# adult's rule holds, would hide the Stalfos room itself)
CHILD_AREAS = ("InsideTheDekuTree", "DodongoCavern", "InsideJabuJabuBelly", "BottomOfTheWell")


def dynamic(actor):
    d = actor.get("Dynamic")
    return d if isinstance(d, dict) else {}


def position(actor):
    t = actor.get("Translate")
    return tuple(float(x) for x in t[:3]) if isinstance(t, list) and len(t) >= 3 and all(isinstance(x, (int, float)) for x in t[:3]) else None


def takes(gyaml, area=""):
    """the items one of which a switch of this name takes in this area, or () for a switch anything presses"""
    items = next((items for word, items in TAKES if word in gyaml), ())
    return (seed.SL,) + items if items == (seed.BOW,) and area in CHILD_AREAS else items


def report(areas, radius, fixed=()):
    """The report's lines. areas: {area: [actor]} (each actor once). fixed: the hashes the seed's mod already frees.
    Returns (lines, how many shutters, how many marked chests)."""
    out, shutters, marks = [], 0, 0
    for area, actors in areas.items():
        for a in actors:
            if not dynamic(a).get("IsDisableSaveAndWarp"):
                continue
            shutters += 1
            at = position(a)
            near = [(math.dist(at, position(b)), b) for b in actors if b is not a and at and position(b)]
            near = sorted(((d, b) for d, b in near if d <= radius), key=lambda q: q[0])
            switches = [(d, b) for d, b in near if "Switch" in str(b.get("Gyaml")) and "Shutter" not in str(b.get("Gyaml"))]
            asked = [items for _, b in switches for items in (takes(str(b.get("Gyaml")), area),) if items]
            h = a.get("Hash")
            out.append("%s  room %s  %s  %s%s" % (area, dynamic(a).get("DefaultDungeonRoomIndex"), "%#x" % h if isinstance(h, int) else h,
                                                  dynamic(a).get("ShutterEvent") or "(no ShutterEvent)",
                                                  "  [the seed's mod turns this one off]" if h in fixed else ""))
            for d, b in switches:
                out.append("    %5.1f  %s (room %s)%s" % (d, b.get("Gyaml"), dynamic(b).get("DefaultDungeonRoomIndex"),
                                                         ": takes " + " or ".join(takes(str(b.get("Gyaml")), area)) if takes(str(b.get("Gyaml")), area) else ""))
            for d, b in near:
                item = dynamic(b).get("Drop__DropActor")
                if not str(b.get("Gyaml")).startswith("Obj_TBox") or item is None:
                    continue
                event = dynamic(b).get("GetEventName") or ""
                need = seed.rule(area, event)
                lacks = [items for items in asked if not need & set(items)]
                marks += bool(lacks)
                out.append("    %5.1f  chest (room %s): %s%s%s" % (
                    d, dynamic(b).get("DefaultDungeonRoomIndex"), item, "  [event: %s]" % event if event else "",
                    "   <-- LOOK: its rule does not ask for " + ", ".join(" or ".join(i) for i in lacks) if lacks else ""))
    return out, shutters, marks


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("romfs")
    p.add_argument("--radius", type=float, default=30.0, help="how far from the shutter a chest or switch still counts (the Stalfos room's eye is 5 from its shutter, its chest 17)")
    a = p.parse_args()
    banc = os.path.join(os.path.abspath(a.romfs), "Banc")
    if not os.path.isdir(banc):
        sys.exit("no Banc folder in %s" % a.romfs)
    try:
        import zstandard as zs
    except ImportError:
        sys.exit("the zstandard package is missing: python -m pip install zstandard")
    dicts = loc.dictionaries(os.path.abspath(a.romfs), zs)
    areas, seen = collections.OrderedDict(), set()
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
            if not isinstance(root, dict):
                continue
            area = os.path.relpath(path, banc).replace("\\", "/").split("/")[0]
            for _, lst in loc.actor_lists(root):
                for actor in lst:   # (the same actor is in several files: child and adult, static and dynamic)
                    if isinstance(actor, dict) and isinstance(actor.get("Hash"), int) and actor["Hash"] not in seen:
                        seen.add(actor["Hash"])
                        areas.setdefault(area, []).append(actor)
    out, shutters, marks = report(areas, a.radius, seed.FIXES)
    print("\n".join(out))
    print("%d shutters turn saving and the warp songs off; %d chests near one are marked" % (shutters, marks))


if __name__ == "__main__":
    main()
