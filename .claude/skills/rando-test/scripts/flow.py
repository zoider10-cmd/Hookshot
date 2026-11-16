"""A character's or a scene's event flow (Event/EventFlow/<name>.bfevfl.zs): its steps, branches, marks and texts.

    py -I flow.py <flow>                        every step, numbered, with where it goes and its parameters
    py -I flow.py <flow> --entry <entry>        only the steps an entry point reaches, in order
    py -I flow.py <flow> --entries              the entry points and where they start
    py -I flow.py --find <text> [--in Npc_]     the flows whose steps name <text> (a flag, an item, a message label...)
    add --modded to read the mods' copy (the seed's rewrite) in place of the game's

A step: "action" (an actor does something), "switch" (a question; its cases (value, step): in these dumps the case 0 of
a true/false question is the TRUE answer), "fork"/"join" (steps at once), "subflow" (another flow's entry). "-> end"
ends the branch. Talk steps name their message (EventFlowMsg/<file>:<label>): text.py finds its words.
Reading only; tools/rando/rando_seed.py scene_steps() is what the seed edits flows with.
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # (-I leaves this folder out)
import romfs   # noqa: E402

FOLDER = "Event/EventFlow"


class Flow:
    def __init__(s, data):
        s.d = data
        c = s.u64(s.u64(0x28))
        s.nact, s.nevt, s.nent = s.u16(c + 0x10), s.u16(c + 0x16), s.u16(c + 0x18)
        s.actors, s.events, s.names, s.entries = s.u64(c + 0x28), s.u64(c + 0x30), s.u64(c + 0x38), s.u64(c + 0x40)

    def u16(s, a): return struct.unpack_from("<H", s.d, a)[0]
    def u64(s, a): return struct.unpack_from("<Q", s.d, a)[0]
    def text(s, p): return bytes(s.d[p + 2:p + 2 + s.u16(p)]).decode("utf-8", "replace") if 0 < p < len(s.d) - 2 else ""
    def actor(s, i): return s.text(s.u64(s.actors + 0x38 * i))
    def action(s, i, k): return s.text(s.u64(s.u64(s.actors + 0x38 * i + 0x18) + 8 * k))
    def query(s, i, k): return s.text(s.u64(s.u64(s.actors + 0x38 * i + 0x20) + 8 * k))

    def params(s, at):
        out = {}
        if not at:
            return out
        dic = s.u64(at + 8)
        for k in range(s.u16(at + 2)):
            key = s.text(s.u64(dic + 8 + 16 * (k + 1) + 8)) if dic else str(k)
            item = s.u64(at + 0x10 + 8 * k)
            t = s.d[item]
            if t in (0, 5) and s.u16(item + 2) == 1:
                out[key] = s.text(s.u64(item + 0x10))
            elif t == 2:
                out[key] = struct.unpack_from("<i", s.d, item + 0x10)[0]
            elif t == 3:   # (a true/false: 0x80000001 true, 0 false)
                out[key] = bool(struct.unpack_from("<I", s.d, item + 0x10)[0] & 1)
            elif t == 4:
                out[key] = round(struct.unpack_from("<f", s.d, item + 0x10)[0], 3)
            else:
                out[key] = "<type %d>" % t
        return out

    def entry_points(s):
        return [(s.text(s.u64(s.names + 8 + 16 * (k + 1) + 8)), s.u16(s.entries + 0x20 * k + 0x1C)) for k in range(s.nent)]

    def step(s, i):
        e = s.events + 0x30 * i
        kind = s.d[e + 8]
        if kind == 0:
            a = s.u16(e + 0x0C)
            return dict(kind="action", next=s.u16(e + 0x0A), what="%s.%s" % (s.actor(a), s.action(a, s.u16(e + 0x0E))), p=s.params(s.u64(e + 0x10)))
        if kind in (1, 5):
            a, cases = s.u16(e + 0x0C), s.u64(e + 0x18)
            return dict(kind="switch", what="%s.%s" % (s.actor(a), s.query(a, s.u16(e + 0x0E))), p=s.params(s.u64(e + 0x10)),
                        cases=[(struct.unpack_from("<I", s.d, cases + 8 * c)[0], s.u16(cases + 8 * c + 4)) for c in range(s.u16(e + 0x0A))])
        if kind == 2:
            forks = s.u64(e + 0x10)
            return dict(kind="fork", forks=[s.u16(forks + 2 * c) for c in range(s.u16(e + 0x0A))], join=s.u16(e + 0x0C))
        if kind == 3:
            return dict(kind="join", next=s.u16(e + 0x0A))
        if kind == 4:
            return dict(kind="subflow", next=s.u16(e + 0x0A), what="%s:%s" % (s.text(s.u64(e + 0x18)), s.text(s.u64(e + 0x20))),
                        p=s.params(s.u64(e + 0x10)))
        return dict(kind="?%d" % kind)

    def reach(s, start):
        seen, stack = [], [start]
        while stack:
            i = stack.pop()
            if i == 0xFFFF or i >= s.nevt or i in seen:
                continue
            seen.append(i)
            st = s.step(i)
            stack += [st["next"]] if "next" in st else []
            stack += [c[1] for c in st.get("cases", [])] + st.get("forks", []) + ([st["join"]] if "join" in st else [])
        return sorted(seen)


def line(i, st, short=False):
    nx = st.get("next")
    nx = "" if nx is None else ("-> end" if nx == 0xFFFF else "-> %d" % nx)
    extra = "cases %s" % st["cases"] if st.get("cases") else ("forks %s join %d" % (st["forks"], st["join"]) if st["kind"] == "fork" else "")
    p = {k: v for k, v in st.get("p", {}).items() if v not in ("", None)}
    if short:
        keep = ("GameDataName", "Value", "ChoiceNumber", "MessageID", "MessageId", "ActorName", "EventName", "FirstGreeting_MesageId", "Title")
        p = {k: v for k, v in p.items() if k in keep}
    return "%3d %-8s %-56s %-7s %s %s" % (i, st["kind"], st.get("what", ""), nx, extra, p if p else "")


def load(name, modded):
    return Flow(romfs.read("%s/%s.bfevfl.zs" % (FOLDER, name), modded))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("flow", nargs="?")
    p.add_argument("--entry")
    p.add_argument("--entries", action="store_true")
    p.add_argument("--find")
    p.add_argument("--in", dest="within", default="", help="with --find: only flows whose name has this")
    p.add_argument("--modded", action="store_true")
    p.add_argument("--short", action="store_true", help="only the parameters that matter most")
    a = p.parse_args()
    if a.find:
        want = a.find.encode()
        for rel in romfs.files(FOLDER):
            name = rel.split("/")[-1].split(".")[0]
            if a.within not in name or not rel.endswith(".bfevfl.zs"):
                continue
            data = romfs.read(rel)
            if want not in data:
                continue
            try:
                f = Flow(data)
                hits = [i for i in range(f.nevt) if a.find in repr(f.step(i))]
            except Exception:
                hits = []
            print("%-56s steps %s" % (name, hits[:12] if hits else "(in its names, not a step's)"))
        return
    if not a.flow:
        p.error("a flow's name, or --find")
    f = load(a.flow, a.modded)
    if a.entries:
        for name, start in f.entry_points():
            print("%-60s -> %d" % (name, start))
        return
    if a.entry:
        starts = dict(f.entry_points())
        if a.entry not in starts:
            sys.exit("no entry %s: %s" % (a.entry, ", ".join(starts)))
        print("== %s : %s starts at %d" % (a.flow, a.entry, starts[a.entry]))
        for i in f.reach(starts[a.entry]):
            print(line(i, f.step(i), True))
        return
    print("== %s: %d actors, %d steps; entries %s" % (a.flow, f.nact, f.nevt, f.entry_points()))
    for i in range(f.nevt):
        print(line(i, f.step(i), a.short))


if __name__ == "__main__":
    main()
