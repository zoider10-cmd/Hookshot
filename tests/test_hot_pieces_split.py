"""The hot pieces' compile flags carry the giant split (nx2/build.py hot_flags, HOOKSHOT_SPLIT_GIANTS).

A build with a hot list compiles its hot functions as code_hot*.c at RX_HOT_OPT (-O2). One of them was a single lifted
function, f_81b8c000, 4.79 MB of C, and at -O2 it took 438 s of a from-scratch build's 446 s compile. The lifted chunks
compile their functions of 256 KB or more as pieces cut at their labels (HOOKSHOT_SPLIT_GIANTS, nx2/split_giants.py), but
the hot pieces' flags were built separately from the plain fl and never carried that flag, so the hot giants were compiled
whole. hot_flags() now adds it. This check is the source-level guard on those flags: the regression would be silent -- the
builds still finish, they just take minutes more.

What it checks: hot_flags() puts split_giants.FLAG on the hot pieces at RX_HOT_OPT (default O2), with
HOOKSHOT_SPLIT_GIANTS=0 turning it off and a size carrying through; main() takes its hot_fl from hot_flags(), so an edit
back to the inline list fails here; and source_flags() sends a code_hot* file to those flags.

The splitter's exactness is not this check's: tests/test_split_giants.py (unchanged) proves it, compiled, over random
lifter-shaped functions, the real emitter's output and build.compile_one's split copy.

python -I -B tests/test_hot_pieces_split.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "nx2")]
import build  # noqa: E402
import split_giants as SG  # noqa: E402

FAILS = []
SWITCHES = ("RX_HOT_OPT", "HOOKSHOT_SPLIT_GIANTS")


def check(ok, what):
    if not ok:
        FAILS.append(what)
        print("FAIL: " + what)


def flag_checks():
    fl = ["-O1", "-DLIFTED", "-mllvm", "-rotation-max-header-size=0"]
    if not hasattr(build, "hot_flags"):   # (main: the hot flags are built inline, so a giant hot function compiles whole)
        check(False, "nx2/build.py has no hot_flags(): the hot pieces' flags carry no giant split")
        check("hot_fl = hot_flags(fl)" in Path(build.__file__).read_text(encoding="utf-8"),
              "main() builds the hot flags with hot_flags(fl)")
        return
    old = {k: os.environ.get(k) for k in SWITCHES}
    try:
        for k in SWITCHES:
            os.environ.pop(k, None)
        hot = build.hot_flags(fl)
        check("-O2" in hot and "-O1" not in hot, "switch unset: the hot flags are at -O2 (%r)" % hot)
        check(all(f in hot for f in fl if f != "-O1"), "switch unset: the other flags stay (%r)" % hot)
        flags = [f for f in hot if f.startswith(SG.FLAG)]
        check(len(flags) == 1 and flags[0].startswith(SG.FLAG + "%d_" % SG.PIECE_KB),
              "switch unset: the hot flags carry the giant split at %d KB (%r)" % (SG.PIECE_KB, hot))
        check(bool(flags) and hot.index(flags[0]) == len(hot) - 1, "the split flag is the one added to fl (%r)" % hot)

        os.environ["RX_HOT_OPT"] = "O1"
        hot = build.hot_flags(fl)
        check("-O1" in hot and "-O2" not in hot, "RX_HOT_OPT=O1: the level asked for")
        check(any(f.startswith(SG.FLAG) for f in hot), "RX_HOT_OPT=O1: the split stays (it is about size, not level) (%r)" % hot)
        os.environ.pop("RX_HOT_OPT", None)

        os.environ["HOOKSHOT_SPLIT_GIANTS"] = "0"
        hot = build.hot_flags(fl)
        check(not any(f.startswith(SG.FLAG) for f in hot) and "-O2" in hot,
              "HOOKSHOT_SPLIT_GIANTS=0: no split, still -O2 (%r)" % hot)
        os.environ["HOOKSHOT_SPLIT_GIANTS"] = "16"
        hot = build.hot_flags(fl)
        check(any(f.startswith(SG.FLAG + "16_") for f in hot), "HOOKSHOT_SPLIT_GIANTS=16: the size carries through (%r)" % hot)
    finally:
        for k in SWITCHES:
            os.environ.pop(k, None)
            if old[k] is not None:
                os.environ[k] = old[k]
    # (main()'s hot pieces come from it: the regression was the inline list, which stopped at fl's level)
    src = Path(build.__file__).read_text(encoding="utf-8")
    check("hot_fl = hot_flags(fl)" in src, "main() builds the hot flags with hot_flags(fl)")
    check("hot_fl = [(" not in src, "main() does not build the hot flags inline again")
    # (source_flags sends a code_hot* file to hot_fl, so the flag reaches the compiler)
    hot = build.hot_flags(fl)
    with tempfile.TemporaryDirectory(prefix="hookshot-hot-flags-") as gen:
        Path(gen, "code_000.c").write_text('void f_00000000(Ctx *__restrict A64_NOESC c) {\n    c->x[1] = c->x[2] + 1;\n}\n',
                                           newline="\n")
        check(build.source_flags(os.path.join(gen, "code_hot_0.c"), gen, fl, fl + build.split_giants_flags(), hot, b"", 1024) == hot,
              "a code_hot* source compiles with the hot flags (and their split)")
        check(build.source_flags(os.path.join(gen, "code_000.c"), gen, fl, fl + build.split_giants_flags(), hot, b"", 1024) != hot,
              "an ordinary lifted chunk still gets the lifted chunks' flags")


def main():
    flag_checks()
    print("hot pieces split: %s" % ("FAILED (%d)" % len(FAILS) if FAILS else "OK"))
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
