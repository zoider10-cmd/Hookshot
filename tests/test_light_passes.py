"""The light passes (nx2/build.py HOOKSHOT_LIGHT_PASSES, on by default): which sources compile at -O1 without its module passes,
and the lifter's header helpers that need no inliner to be inlined.

  1. build.py source_flags, as main() calls it for every source, on made-up lifted files in a temporary gen folder:
     - switch unset: an ordinary chunk (small functions) and one with a function split_giants cuts (300 KB: its pieces too)
       get LIGHT_FLAGS after the lifted chunks' flags; a giant (1024 KB or more), a hot piece (code_hot*) and a file outside
       gen get the flags they get with the switch off;
     - HOOKSHOT_SPLIT_GIANTS=0: the same chunks light; HOOKSHOT_LIGHT_PASSES_KB lowers the bar;
     - HOOKSHOT_LIGHT_PASSES=0: every source gets the flags it got before the switch existed (hot_fl, split_fl, fl);
     - the light flags are in the object key (object_key), so an object store never hands a light object to a full build or
       the other way round; a kept lifted file (not on disk) takes the flags its list recorded;
     - the largest function is remembered with the file's record (hash_cache.json: save_hashes, load_hashes), so a build that
       knows a file does not read it again.
  2. build.py light_flags_work: a compiler that rejects -opt-disable (LLVM 21 and older: a Linux system's clang) or does not start
     gives no light passes, and main() asks it; a real clang here takes the flags exactly when it is LLVM 22 or newer.
  3. a64_lift.fpx_header (what the lift writes to a64_fpx.h): every `static inline` helper is always_inline, the 7 a64_v_*
     helpers of the vector float code (VFPX_HEADER) by name: without the module inliner they were left as calls (bold/passes
     round 1: +4.6% game CPU).
  4. nx2/fastfp.py's FASTFP_HEADER (appended to a64_fpx.h): every static helper it defines is always_inline, apart from the
     ones marked noinline (cold), a64_ff_enabled_ by name (A64_FF_ON calls it at every fast float region).

python -I -B tests/test_light_passes.py
"""
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "third_party" / "a64-kit" / d) for d in ("lift", "tools")] + [str(ROOT / "nx2")]
import build  # noqa: E402
import a64_lift  # noqa: E402
import fastfp  # noqa: E402

PREAMBLE = '#include "a64.h"\nvoid f_90000000(Ctx *A64_NOESC);\n'
SWITCHES = ("HOOKSHOT_LIGHT_PASSES", "HOOKSHOT_LIGHT_PASSES_KB", "HOOKSHOT_SPLIT_GIANTS")
V_HELPERS = ("a64_v_ult", "a64_v_abs", "a64_v_big", "a64_v_zero", "a64_v_nonfin", "a64_v_subn", "a64_v_ovf")


def function(addr, size):
    head = "void f_%08x(Ctx *__restrict A64_NOESC c) {\n" % addr
    line = "c->x[1] = c->x[2] + 1;\n"
    return head + line * max(1, (size - len(head) - 2) // len(line)) + "}\n"


def check(ok, what):
    if not ok:
        raise SystemExit("FAIL: " + what)


def flags_of(env, srcs, gen):
    """{name: what source_flags gives it} under env, as main() works them out"""
    old = {k: os.environ.pop(k, None) for k in SWITCHES}
    os.environ.update(env)
    try:
        fl, hot_fl, deps = ["-O1", "-DLIFTED"], ["-O2", "-DHOT"], b"headers"
        split_fl = fl + build.split_giants_flags()
        bar_kb = build.light_passes_kb()
        names = {os.path.basename(s): build.source_flags(s, gen, fl, split_fl, hot_fl, deps, bar_kb) for s in srcs}
        return names, fl, split_fl, hot_fl, bar_kb
    finally:
        for k in SWITCHES:
            os.environ.pop(k, None)
            if old[k] is not None:
                os.environ[k] = old[k]


def build_checks():
    check(isinstance(getattr(build, "LIGHT_FLAGS", None), list) and hasattr(build, "source_flags"),
          "nx2/build.py has no light passes (LIGHT_FLAGS, source_flags)")
    light = build.LIGHT_FLAGS
    disabled = next((f for f in light if f.startswith("-opt-disable=")), "")[len("-opt-disable="):].split(",")
    check({"inline", "function-attrs", "ipsccp", "globalopt"} <= set(disabled), "the light flags turn off the module passes")
    check(light[-1] == "-opt-bisect-verbose=false", "the light flags keep -opt-disable quiet")

    with tempfile.TemporaryDirectory(prefix="hookshot-light-") as d:
        gen, rt = os.path.join(d, "gen"), os.path.join(d, "rt")
        os.makedirs(gen)
        os.makedirs(rt)
        files = {
            "code_000.c": "".join(function(0x80000000 + 16 * i, 4000) for i in range(100)),   # ordinary: 4 KB functions
            "code_001.c": function(0x81000000, 4000) + function(0x81000010, 300 * 1024),        # a function split_giants cuts
            "code_002.c": function(0x82000000, 1100 * 1024),                                    # a giant
            "code_hot_0.c": function(0x83000000, 4000),                                         # a hot piece
        }
        srcs = []
        for name, body in files.items():
            p = os.path.join(gen, name)
            Path(p).write_text(PREAMBLE + body, newline=chr(10))
            srcs.append(p)
        other = os.path.join(rt, "code_runtime.c")   # (a code_ name outside gen: not lifted)
        Path(other).write_text("int x;\n", newline=chr(10))
        plain = os.path.join(rt, "hos_main.c")
        Path(plain).write_text("int y;\n", newline=chr(10))
        srcs += [other, plain]

        got, fl, split_fl, hot_fl, bar = flags_of({}, srcs, gen)
        check(split_fl != fl, "the giants are split by default (HOOKSHOT_SPLIT_GIANTS unset)")
        check(bar == 1024, "switch unset: on, under 1024 KB (%r)" % bar)
        check(got["code_000.c"] == split_fl + light, "switch unset: an ordinary lifted chunk compiles light (%r)" % got["code_000.c"])
        check(got["code_001.c"] == split_fl + light, "a chunk with a function split_giants cuts compiles light, its pieces too")
        check(got["code_002.c"] == split_fl, "a giant keeps every pass")
        check(got["code_hot_0.c"] == hot_fl, "a hot piece keeps its flags")
        check(got["code_runtime.c"] == fl and got["hos_main.c"] == fl, "a file outside gen keeps its flags")

        got, fl, split_fl, hot_fl, bar = flags_of({"HOOKSHOT_SPLIT_GIANTS": "0"}, srcs, gen)
        check(split_fl == fl and bar == 1024, "HOOKSHOT_SPLIT_GIANTS=0: the bar is HOOKSHOT_LIGHT_PASSES_KB's 1024 (%r)" % bar)
        check(got["code_000.c"] == fl + light and got["code_001.c"] == fl + light,
              "giants not split: a chunk whose functions are under 1024 KB compiles light")
        check(got["code_002.c"] == fl and got["code_hot_0.c"] == hot_fl, "giants not split: the giant and the hot piece keep theirs")
        got, fl, *_ = flags_of({"HOOKSHOT_SPLIT_GIANTS": "0", "HOOKSHOT_LIGHT_PASSES_KB": "200"}, srcs, gen)
        check(got["code_000.c"] == fl + light and got["code_001.c"] == fl, "HOOKSHOT_LIGHT_PASSES_KB=200 keeps the 300 KB function's chunk full")

        for off in ("0", "off"):
            got, fl, split_fl, hot_fl, bar = flags_of({"HOOKSHOT_LIGHT_PASSES": off}, srcs, gen)
            check(bar is None, "HOOKSHOT_LIGHT_PASSES=%s: off" % off)
            check(got == {"code_000.c": split_fl, "code_001.c": split_fl, "code_002.c": split_fl, "code_hot_0.c": hot_fl,
                          "code_runtime.c": fl, "hos_main.c": fl},
                  "HOOKSHOT_LIGHT_PASSES=%s: every source gets the flags it had before the switch" % off)

        # (the object key: a light object and a full one are two objects)
        src = os.path.join(gen, "code_000.c")
        check(build.object_key(src, split_fl + light, b"h") != build.object_key(src, split_fl, b"h"),
              "the light flags are in the object key")
        check("-opt-disable=" in build.flag_text(split_fl + light), "flag_text keeps the light flags")

        # (a kept lifted file, no longer on disk: the flags its list recorded)
        gone = os.path.join(gen, "code_009.c")
        saved = dict(build.KEPT)
        try:
            build.KEPT[gone] = ("0" * 40, 1, build.kept_part(split_fl + light, b"headers"))
            check(build.lifted_flags(gone, split_fl, b"headers", 1024) == split_fl + light, "a kept light chunk stays light")
            build.KEPT[gone] = ("0" * 40, 1, build.kept_part(split_fl, b"headers"))
            check(build.lifted_flags(gone, split_fl, b"headers", 1024) == split_fl, "a kept full chunk stays full")
        finally:
            build.KEPT.clear()
            build.KEPT.update(saved)

        # (the largest function, remembered: a file the record still describes is not read again)
        build.HASHES.clear()
        n = build.lifted_largest(os.path.join(gen, "code_001.c"))
        check(300 * 1024 - 100 <= n <= 300 * 1024 + 100, "the largest function is measured (%d bytes)" % n)
        build.save_hashes(d)
        build.load_hashes(d)
        build.HASHES_AT[0] += 10 * build.RACY_NS   # (as a later build would trust the record)
        entry = build.HASHES.get(os.path.join(gen, "code_001.c"), {})
        check(entry.get("largest") == n, "the record keeps the largest function (%r)" % entry.get("largest"))
        try:
            build.open = lambda *a, **k: (_ for _ in ()).throw(AssertionError("read %r" % (a,)))
            check(build.lifted_largest(os.path.join(gen, "code_001.c")) == n, "a known file's largest function from the record")
        finally:
            del build.open
        build.HASHES.clear()


def compiler_checks():
    """light_flags_work: a compiler without -opt-disable (LLVM 21 and older, a Linux system's) builds with every pass, not at all"""
    import subprocess
    import toolchain
    real_run = build.subprocess.run
    try:
        build.subprocess.run = lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, "", "clang (LLVM option parsing): Unknown "
                                                                             "command line argument '-opt-disable=inline'.\n")
        check(build.light_flags_work("clang") is False, "a compiler that rejects -opt-disable: no light passes")
        build.subprocess.run = lambda cmd, **k: (_ for _ in ()).throw(FileNotFoundError(cmd[0]))
        check(build.light_flags_work("clang") is False, "a compiler that does not start: no light passes")
    finally:
        build.subprocess.run = real_run
    src = Path(build.__file__).read_text(encoding="utf-8")
    check("if bar_kb is not None and not light_flags_work(cc):" in src, "main() asks the compiler before choosing light flags")
    # (a real clang, when there is one: LLVM 22 or newer takes the flags, an older one does not)
    cc = toolchain.find("clang")
    try:
        version = subprocess.run([cc, "--version"], capture_output=True, text=True).stdout
    except OSError:
        print("light passes: no clang here, the compiler's own answer not checked")
        return
    m = re.search(r"clang version (\d+)", version)
    if m:
        check(build.light_flags_work(cc) == (int(m.group(1)) >= 22),
              "clang %s %s the light flags" % (m.group(1), "takes" if int(m.group(1)) >= 22 else "rejects"))


def header_checks():
    used = {("add32", "add32", 2, 2), ("sub32", "sub32", 2, 2), ("mul32", "fma32", 2, 3)}
    text = a64_lift.fpx_header(used)
    defs = {}
    for line in text.splitlines():
        m = re.match(r"static inline\b(.*?)\b(a64_\w+)\s*\(", line)
        if m and not line.rstrip().endswith(";"):
            defs[m.group(2)] = "always_inline" in m.group(1)
    for name in V_HELPERS:
        check(name in defs, "a64_fpx.h defines %s" % name)
        check(defs[name], "%s is always_inline: without the module inliner it stays a call" % name)
    loose = sorted(n for n, forced in defs.items() if not forced)
    check(not loose, "every static inline helper of a64_fpx.h is always_inline (not: %s)" % ", ".join(loose))


def fastfp_checks():
    text = fastfp.FASTFP_HEADER
    defs = {}
    for m in re.finditer(r"^static\b([^;{=\n]*?)\b(a64_\w+)\s*\([^;\n]*\{", text, re.M):
        defs[m.group(2)] = m.group(1)
    for name in ("a64_ff_enabled_", "a64_ff_begin", "a64_ff_end"):
        check(name in defs, "FASTFP_HEADER defines %s" % name)
    loose = sorted(n for n, attrs in defs.items() if "always_inline" not in attrs and "noinline" not in attrs)
    check(not loose, "every static helper of FASTFP_HEADER is always_inline, or noinline on purpose (not: %s)" % ", ".join(loose))


def main():
    build_checks()
    compiler_checks()
    header_checks()
    fastfp_checks()
    print("light passes: ok")


if __name__ == "__main__":
    main()
