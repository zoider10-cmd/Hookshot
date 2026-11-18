"""(hookshot) nx2/fastfp.py's copy of a64-kit's Lifter.emit_function stays the kit's, apart from its fast float lines.

The fast float regions (A64_FASTFP) gather their runs inside the per-instruction loop of the kit's emit_function. The kit
stays as it was imported (CONTRIBUTING.md), so nx2/fastfp.py replaces the method with a copy that has those lines added, each
tagged "# (fastfp)". This checks, game-free and without a compiler:
  - the copy with its tagged lines taken out is the kit's method, line for line (dedented one level: a module function there),
    so a change to the kit's emit_function that the copy did not follow fails here;
  - the copy names the a64-kit tree it was taken from (KIT_TREE), and that is still the tree-sha256 in
    third_party/a64-kit/PROVENANCE.md: an a64-kit refresh fails here until the copy is compared with it again and KIT_TREE
    moved on;
  - run over a made-up function (hand-written instruction texts on a lifter with no translator), with A64_FASTFP=0 the copy
    writes exactly what the kit's method writes, with comments and without; with it on, a run of 8 vector multiplies is one
    region (its fast and exact copies, counted in the stats), a label in the middle of the run cuts it (the labelled
    instruction joins neither side), a run of 7 stays as
    the kit writes it, and an instruction with code after it (a game patch) is not joined;
  - nx2/lift.py installs it before nx2/lift_fixes.py's wrapper, so lift_fixes and poll wrap the copy, not the other way round.

It has teeth (each by hand, then restored, 2026-11-15): a line of the copy changed without the tag, the tag dropped from an
added line, KIT_TREE one digit off, and fastfp.install() moved after lift_fixes.install() each fail it.

    python -I -B tests/test_fastfp_override.py
"""
import ast
import collections
import os
import re
import sys
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = os.path.join(ROOT, "third_party", "a64-kit")
sys.path.insert(0, os.path.join(KIT, "lift"))
sys.path.insert(0, os.path.join(KIT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "nx2"))
for name in ("A64_FASTFP", "A64_FASTFP_MIN", "A64_LOCAL_REGS", "A64_KEEP_FLAGS", "A64_MARK_FRAME", "A64_HOT_FUNCS"):
    os.environ.pop(name, None)
import a64_lift  # noqa: E402
import fastfp  # noqa: E402

TAG = "# (fastfp)"
KIT_EMIT = a64_lift.Lifter.emit_function   # (the kit's: nothing installed fastfp in this process)


def fail(msg):
    raise SystemExit("fastfp override: " + msg)


def source_of(path, owner, name):
    """The source lines of function `name` (a method of class `owner`, or a module function when owner is None)"""
    text = open(path, encoding="utf-8").read()
    tree = ast.parse(text)
    nodes = tree.body
    if owner:
        nodes = next(n for n in nodes if isinstance(n, ast.ClassDef) and n.name == owner).body
    fn = next(n for n in nodes if isinstance(n, ast.FunctionDef) and n.name == name)
    lines = text.split("\n")[fn.lineno - 1:fn.end_lineno]
    return textwrap.dedent("\n".join(lines)).split("\n")


def check_text():
    kit = source_of(os.path.join(KIT, "lift", "a64_lift.py"), "Lifter", "emit_function")
    copy = source_of(os.path.join(ROOT, "nx2", "fastfp.py"), None, "emit_function")
    tagged = [l for l in copy if l.rstrip().endswith(TAG)]
    if len(tagged) < 20:
        fail("only %d lines of the copy are tagged %r: the run gathering is not where this check looks" % (len(tagged), TAG))
    plain = [l for l in copy if not l.rstrip().endswith(TAG)]
    if plain != kit:
        for n, (a, b) in enumerate(zip(plain, kit)):
            if a != b:
                fail("nx2/fastfp.py's emit_function is not a64-kit's apart from its %s lines, from line %d of the kit's:\n"
                     "  copy: %s\n  kit:  %s" % (TAG, n + 1, a, b))
        fail("nx2/fastfp.py's emit_function and a64-kit's differ in length (%d and %d lines, the tagged ones left out)"
             % (len(plain), len(kit)))
    print("ok   the copy is the kit's emit_function (%d lines) with %d tagged lines" % (len(kit), len(tagged)))


def check_tree():
    note = open(os.path.join(KIT, "PROVENANCE.md"), encoding="utf-8").read()
    tree = re.search(r"^tree-sha256: ([0-9a-f]{64})\s*$", note, re.M).group(1)
    if fastfp.KIT_TREE != tree:
        fail("a64-kit's tree is %s now, the copy was taken at %s: compare nx2/fastfp.py's emit_function with the kit's again "
             "and move KIT_TREE on" % (tree, fastfp.KIT_TREE))
    print("ok   the copy names a64-kit's tree %s..." % tree[:12])


def check_install_order():
    lift = open(os.path.join(ROOT, "nx2", "lift.py"), encoding="utf-8").read()
    if not lift.index("fastfp.install()") < lift.index("lift_fixes.install()"):
        fail("nx2/lift.py installs fastfp after lift_fixes: its emit_function would replace lift_fixes' wrapper")
    print("ok   nx2/lift.py installs fastfp before lift_fixes")


# ---- the copy run over a made-up function ----
MUL = "a64_vfpx_mul32(c,c->vreg[%d],c->vreg[1],c->vreg[2],4);"


def lifter(comments):
    L = object.__new__(a64_lift.Lifter)
    L.names, L.plt, L.no_local, L.after, L.jt, L.devirt = {}, {}, set(), {}, {}, {}
    L.entries, L.comments, L.setjmp_owner = set(), comments, {}
    L.stats, L.unhandled, L.ijump = collections.Counter(), collections.Counter(), collections.Counter()
    return L


def function(L, n_mul, label_at=None, after_at=None):
    """A function at 0x1000: n_mul vector multiplies, an integer add, a return; the instruction texts by word"""
    e = 0x1000
    body, texts, labels = {}, {}, set()
    words = [0x0e000000 + i for i in range(n_mul)] + [0x0b000000]
    for i, w in enumerate(words):
        pc = e + 4 * i
        body[pc] = (("op",), w)
        texts[(w, pc) if a64_lift.pc_relative(w) else w] = (MUL % (3 + i % 4) if i < n_mul else "c->x[5] = c->x[5] + 1;", 0)
    body[e + 4 * len(words)] = (("ret",), 0xd65f03c0)
    if label_at is not None:
        labels.add(e + 4 * label_at)
    if after_at is not None:
        L.after[e + 4 * after_at] = "/* a patch */"
    L.funcs = {e: (body, labels)}
    return e, texts


def emit(fn, comments, mode, **kw):
    os.environ["A64_FASTFP"] = mode
    L = lifter(comments)
    e, texts = function(L, **kw)
    text, _ = fn(L, e, texts)
    return text, L.stats


def check_run():
    for comments in (False, True):
        for kw in ({"n_mul": 12}, {"n_mul": 12, "label_at": 5}, {"n_mul": 3}):
            want, _ = emit(KIT_EMIT, comments, "0", **kw)
            got, stats = emit(fastfp.emit_function, comments, "0", **kw)
            if got != want:
                fail("A64_FASTFP=0, %s, comments %s: the copy wrote\n%s\nthe kit\n%s" % (kw, comments, got, want))
            if stats.get("ff_regions"):
                fail("A64_FASTFP=0 made regions")
    text, stats = emit(fastfp.emit_function, True, "1", n_mul=12)
    if stats.get("ff_regions") != 1 or stats.get("ff_ops") != 12 or text.count("A64_FF_ON(c)") != 1:
        fail("12 multiplies in a row: %s regions of %s ops, not one of 12:\n%s" % (stats.get("ff_regions"), stats.get("ff_ops"), text))
    if text.count("a64_ff_vmul32(") != 12 or text.count("a64_vfpx_mul32(") != 12 or "/* 00001004: 0e000001 */" not in text:
        fail("the region does not hold the fast and the exact copy of every multiply, with their comments:\n" + text)
    if text.index("A64_FF_ON(c)") > text.index("c->x[5] = c->x[5] + 1;"):
        fail("the integer add after the run went before the region")
    _, stats = emit(fastfp.emit_function, False, "1", n_mul=17, label_at=8)   # (the labelled one joins neither run)
    if stats.get("ff_regions") != 2 or stats.get("ff_ops") != 16:
        fail("a label on the 9th of 17 multiplies: %s regions of %s ops, not two of 8"
             % (stats.get("ff_regions"), stats.get("ff_ops")))
    want, _ = emit(KIT_EMIT, False, "1", n_mul=7)
    got, stats = emit(fastfp.emit_function, False, "1", n_mul=7)
    if got != want or stats.get("ff_regions"):
        fail("7 multiplies (below A64_FASTFP_MIN) are not written as the kit writes them")
    _, stats = emit(fastfp.emit_function, False, "1", n_mul=16, after_at=8)
    if stats.get("ff_regions") != 1 or stats.get("ff_ops") != 8:
        fail("a patch after the 9th of 16 multiplies: %s regions of %s ops, not one of 8 (the 7 after it too few)"
             % (stats.get("ff_regions"), stats.get("ff_ops")))
    os.environ.pop("A64_FASTFP", None)
    print("ok   the copy writes what the kit writes with A64_FASTFP=0; with it on, runs become regions, cut at labels and patches")


def main():
    check_text()
    check_tree()
    check_install_order()
    check_run()
    print("fastfp override: ok")


if __name__ == "__main__":
    main()
