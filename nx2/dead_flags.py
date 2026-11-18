"""(hookshot) a64_lift.Lifter.dead_flags, answered at once for a function none of whose instructions writes a flag.

dead_flags (the kit's) works out, per function, which flags each instruction stores that nothing reads, so emit_function
can drop those stores: one pass over the function's instructions to gather what each reads and writes, then a liveness
fixpoint. Only an instruction that writes a flag (a translated op whose text stores c->n, z, c or v) can have a dead store,
so a function without one has none, and the kit's answer is {} after all that work. dead_flags ran on every one of OoT's
285,000 functions and was a fifth of the emit's time; here a function is first looked over for a flag write (flag_masks, kept
by the text), and only one that has one goes through the kit's method. The answers are the kit's
(tests/test_dead_flags.py).

install() is run by nx2/lift.py at its module level, so the emit's new processes (nx2/chunks.py spawn_emit) have it too.
"""
import a64_lift
import a64emit

_installed = False


def writes_flags(body, texts):
    """an instruction of body is a translated op whose text stores a flag (the only kind dead_flags can find dead)"""
    for pc, (k, w) in body.items():
        if k[0] == "op":
            text, fl = texts[(w, pc) if a64_lift.pc_relative(w) else w]
            if not fl & a64emit.UNHANDLED and a64_lift.flag_masks(text)[1]:
                return True
    return False


def install():
    global _installed
    if _installed:
        return
    _installed = True
    base = a64_lift.Lifter.dead_flags

    def dead_flags(self, body, pcs, texts):
        if not writes_flags(body, texts):
            return {}
        return base(self, body, pcs, texts)

    a64_lift.Lifter.dead_flags = dead_flags
