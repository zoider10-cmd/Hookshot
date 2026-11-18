"""(hookshot) The discovery's walks in new processes where there is no fork (Windows), with the kit's result.

a64_lift.Lifter.discover walks every entry in address order (~35 s of one core for OoT on a Ryzen 5 5600, the biggest part of a
Windows lift left after #1116 and #1128), then retries the jump tables it missed, finds the PLT stubs and the setjmp owners.
Here its first loop's walks are made by processes, the entries cut into parts of consecutive addresses (at unwind-range starts),
each part walked in order by a lifter of its own; the kit's discover then runs as it is, its first loop given those bodies
(the rest, from the retry on, walks as always).

What one function's walk finds depends on the others in one way: a jump table whose address is not in the window before
its BR is looked for along the code's predecessors (a64_lift reaching_constants, preds), which include the tables found so
far in the same unwind range. So the parts agree with the kit's single walk unless two parts meet in a range where that
search ran: each part reports the ranges it found tables in and the ranges where the search ran, and when one range has
both from two parts, or the search from two, the parts are thrown away and the kit's discover walks everything, as
before. OoT has 1,475 tables, 435 found by that search, in no shared range: its parts give the kit's functions, tables,
misses and counters (tests/test_discover.py checks the merge and the fallback on a made-up image).

The workers rebuild the image from <img_dir>/image.bin (what image.write wrote) and the entries and hooks the lifter has;
they are new processes, which run nx2/lift.py's module level again (nx2/insn.py's classify, nx2/lift_fixes.py's jump tables,
nx2/walk.py): a worker whose walk is not this process's (identities) stops, and the kit's discover walks all.
HOOKSHOT_LIFT_JOBS=1, a fork (Linux, macOS: unchanged there), another image layout or a Lifter subclass: the kit's discover.
"""
import bisect
import collections
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor

import a64_lift
import nx_image

PARTS_PER_JOB = 3   # (parts are uneven: 3-9 s for a sixth of OoT; more parts than processes even them out)
MIN_ENTRIES = 4000   # (fewer: the processes' start costs more than the walks)

_view = None   # (a worker's lifter)


def identities():
    """Where the callables the walk goes through come from, as (module, qualified name): a worker compares its own with the
    lift's before it walks (as nx2/chunks.py's emit does)"""
    L = a64_lift.Lifter
    return [(f.__module__, f.__qualname__) for f in (a64_lift.classify, L.walk, L.jump_table, L.function_constant,
                                                     L.reaching_constants, L.preds, L.add_jt_edges)]


def parts_of(L, order, n):
    """order (sorted entries) cut into about n runs of consecutive entries, each cut where the unwind range changes"""
    starts = L.eh_starts

    def ext(e):
        return bisect.bisect_right(starts, e)
    cuts = [0]
    for k in range(1, n):
        i = max(cuts[-1] + 1, len(order) * k // n)
        while i < len(order) and ext(order[i]) == ext(order[i - 1]):
            i += 1
        if i >= len(order):
            break
        cuts.append(i)
    cuts.append(len(order))
    return [order[a:b] for a, b in zip(cuts, cuts[1:]) if b > a]


def _init(path, base, end, code, entries, hooks, eh_starts, theirs):
    global _view
    import image
    nx_image.MAIN_BASE = base
    img = object.__new__(image.EdenImage)
    with open(path, "rb") as f:
        img.mem = bytearray(f.read())
    if len(img.mem) != end - base:
        raise RuntimeError("%s is %d bytes, the lift's image %d" % (path, len(img.mem), end - base))
    img.end, img.code = end, code
    img.lookups()
    img.entries, img.hooks, img.names, img.eh_starts = set(entries), dict(hooks), {}, eh_starts
    if identities() != theirs:
        raise RuntimeError("this process walks with %s, the lift's with %s" % (identities(), theirs))
    _view = a64_lift.Lifter(img)


def walk_part(L, es):
    """The kit's first loop over es with L's state made fresh: (funcs, jt, jt_missing, stats, ranges with tables found,
    ranges whose predecessors were read). The predecessors (a64_lift preds, with the tables found so far in the range) are
    the only state of one walk that another walk's changes: reaching_constants reads them. (Tracked at preds, not at
    reaching_constants, which nx2/lift_fixes.py replaces on the instance for a while and then deletes)"""
    L.funcs, L.jt, L.jt_missing, L.stats = {}, {}, {}, collections.Counter()
    L.__dict__.pop("_preds", None)
    searched = set()
    base = type(L).preds

    def preds(lo, hi):
        searched.add(lo)
        return base(L, lo, hi)
    L.preds = preds
    try:
        for e in es:
            if e in L.hooks:
                continue
            L.funcs[e] = L.walk(e)
    finally:
        del L.preds
    found = {L.function_extent(pc)[0] for pc in L.jt}
    return L.funcs, L.jt, L.jt_missing, L.stats, found, searched


def _walk(es):
    return walk_part(_view, es)


def conflicts(results):
    """The unwind ranges where two parts could have seen each other's tables: a range searched by one part (reaching_constants)
    with tables found or searched by another"""
    by = collections.defaultdict(set)
    searched = set()
    for i, r in enumerate(results):
        for x in r[4] | r[5]:
            by[x].add(i)
        searched |= r[5]
    return sorted(x for x in searched if len(by[x]) > 1)


def merge(L, results):
    """The parts' walks as the kit's first loop leaves them: their bodies by entry (for discover's first loop), and L's jt,
    jt_missing and stats"""
    bodies = {}
    for funcs, jt, missing, stats, _, _ in results:
        bodies.update(funcs)
        L.jt.update(jt)
        L.jt_missing.update(missing)
        L.stats.update(stats)
    return bodies


def discover(L, img_dir, jobs, max_insns=0, run=None):
    """L.discover(max_insns), its first loop's walks made by `jobs` new processes when they can be (the module's note).
    run(fn, parts): how the parts are walked (the processes; a test's stand-in). Returns the processes used (1: none)"""
    import chunks
    import image
    img = L.img
    if run is None and (jobs <= 1 or not chunks._no_fork() or type(L) is not a64_lift.Lifter
                        or type(img) is not image.EdenImage or len(L.entries) < MIN_ENTRIES):
        L.discover(max_insns=max_insns)
        return 1
    order = sorted(L.entries)
    parts = parts_of(L, order, max(1, jobs) * PARTS_PER_JOB)
    try:
        if run is not None:
            results = run(walk_part, parts)
        else:
            path = os.path.join(img_dir, "image.bin")
            args = (path, nx_image.MAIN_BASE, img.end, img.code, L.entries - set(L.hooks), L.hooks, L.eh_starts,
                    identities())
            with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context("spawn"),
                                     initializer=_init, initargs=args) as pool:
                results = list(pool.map(_walk, parts))
    except Exception as e:   # (BrokenProcessPool, a worker that stopped or could not start, anything raised in a walk)
        print("discovery: the walks' processes stopped (%s): walked here" % e, flush=True)
        L.discover(max_insns=max_insns)
        return 1
    shared = conflicts(results)
    if shared:
        print("discovery: %d unwind ranges searched for jump tables by two parts (first at %#x): walked here, in order"
              % (len(shared), shared[0]), flush=True)
        L.discover(max_insns=max_insns)
        return 1
    bodies = merge(L, results)
    walk = L.walk

    def given(e):   # (the kit's first loop takes each body walked already; any later walk is a real one)
        b = bodies.pop(e, None)
        return b if b is not None else walk(e)
    L.walk = given
    try:
        L.discover(max_insns=max_insns)
    finally:
        del L.walk
    print("discovery: %d parts walked in %d processes" % (len(parts), jobs), flush=True)
    return jobs
