"""(hookshot) a64_lift.Lifter.walk, the discovery's walk of one function, with the same result in less time and memory.

The kit's walk (third_party/a64-kit, at KIT_TREE below) stores each instruction of a function as body[pc] = (kind, word): for
OoT, 13.1 million entries, 12.7 million of them plain ops, of only 1.16 million distinct words. Each was a tuple and an int of
its own, about 1 GB of the lift's 4.3 GB after discovery; the lift's process holds them through the emit, and Windows starts one
emit process per 0.75 GB free (nx2/chunks.py file_jobs), so that gigabyte was one or two processes fewer on a 16 GB PC. Here
every plain op of the same word is one shared (("op",), word) tuple, and the image's lookups (nx2/image.py EdenImage's word
view and code ranges) are read inline. Kept after the fact, the duplicates' memory would stay with Python's allocator: it must
be done as the walk makes them.

Everything else is the kit's walk, line for line in its order: the same instructions visited in the same order, the same jump
tables found and the same labels (tests/test_walk.py compares the two over a made-up image, and checks that KIT_TREE is still
third_party/a64-kit's tree-sha256: an a64-kit refresh fails it until this copy is compared with the kit's walk again).
install() is run by nx2/lift.py at its module level.
"""
import a64_lift

KIT_TREE = "6164061ea8dc7896da53490df9ebc5e43b50faa50c1da61cdf9fc5e207773f7d"   # (a64-kit's tree-sha256 the kit's walk was compared at)

_installed = False


def walk(self, entry):
    """a64_lift.Lifter.walk: (body {pc: (kind, word)}, labels) of the function at entry"""
    img, entries = self.img, self.entries
    classify = a64_lift.classify   # (nx2/insn.py's, installed before any walk)
    ops = self.__dict__.setdefault("_op_entries", {})   # (word -> the shared (("op",), word) entry)
    spans = getattr(img, "_spans", None)
    words = getattr(img, "_words", None)
    if spans is not None and words is not None:
        base, size = img._base, len(img.mem)

        def in_code(a):
            if a & 3:
                return False
            for lo, hi in spans:
                if lo <= a < hi:
                    return True
            return False

        def word(a):
            off = a - base
            return words[off >> 2] if 0 <= off < size else img.word(a)
    else:
        in_code, word = img.in_code, img.word
    body, labels, todo = {}, set(), [entry]

    def visit(t):
        if t != entry and t in entries:
            return
        if in_code(t):
            labels.add(t)
            todo.append(t)

    while todo:
        pc = todo.pop()
        while pc not in body:
            if (pc != entry and pc in entries) or not in_code(pc):
                break
            w = word(pc)
            kw = ops.get(w)
            if kw is not None:   # (a word seen before as a plain op: one at every pc, nx2/insn.py classify)
                body[pc] = kw
                pc += 4
                continue
            k = classify(w, pc)
            kind = k[0]
            if kind == "op":
                kw = ops[w] = (k, w)
                body[pc] = kw
                pc += 4
                continue
            body[pc] = (k, w)
            if kind == "b":
                visit(k[1])
                break
            if kind in ("bcond", "cbz", "tbz"):
                visit(k[1])
            elif kind == "br":
                targets = self.jump_table(pc, k[1])
                if targets:
                    self.jt[pc] = targets
                    self.add_jt_edges(pc, targets)
                    for t in targets:
                        visit(t)
                break
            elif kind in ("ret", "trap"):
                break
            pc += 4
    return body, labels


def install():
    global _installed
    if _installed:
        return
    _installed = True
    a64_lift.Lifter.walk = walk
